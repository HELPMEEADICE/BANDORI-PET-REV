# Rust IPC 迁移、审计与验证

本次迁移以 `10a804c` 为基线。Python 和原生桌宠的队列读写现在都由
`native/pet_backend/crates/pet-ipc` 实现。`pet-ipc-python` 只负责 PyO3 适配，
`native/pet_backend/src/ipc.rs` 只负责四通道路由和 Envelope 过滤。
没有改变 UI、Neocari 渲染器、角色行为、消息分类或配置格式。

## 审计范围与调用链

| 入口／模块 | 队列和职责 | 迁移后的处理 |
| --- | --- | --- |
| `main.py` | 创建四条主通道，定时批量读取入站消息，广播位置／控制命令，退出时关闭 | 调用原 `SharedMemoryLineQueue` 接口 |
| `bandori_core/ipc_bus.py` | key、可靠消息分类、一次性发送锁、连接缓存、Qt 自适应定时器 | 分类、锁顺序、返回值和计时器保持原样 |
| `chat_process.py` | 四通道附加；注册、聊天、动作等发送；广播／控制读取 | 自动使用 Rust 队列 |
| `settings_process.py` | 四通道附加；可靠消息暂存与重试；已有 stdout 启动后备路径 | 保留既有队列及失败处理 |
| `pet_process.py` | 原生进程兼容启动入口 | 经 `native_pet.py` 传递相同映射路径 |
| `native/pet_backend/src/ipc.rs` | 四通道附加，JSON Envelope，发送／读取路由 | 直接依赖 `pet-ipc::Queue` |
| `bandori_ui/native_pet_services.py` | 每个径向菜单的命令／事件队列；READY 后发送待处理命令 | 相同 8×8192／8×4096 队列参数 |
| `radial_menu_process.py` | 附加菜单通道、批量读命令、发事件、退出关闭 | 自动使用 Rust 队列；原 stdio 模式保持 |
| `bandori_core/native_pet.py`、原生测试与 smoke 工具 | 将 `queue_file_path(key)` 传入原生程序 | 路径哈希算法保持 |
| `shared_memory_ipc.py` | Envelope、key、位置合并和 Python 队列接口 | 纯 Python 业务辅助函数保留；所有队列存储访问转发 PyO3 |
| `mapped_memory.py` | 旧 lock/data/unlock 存储接口与文件名算法 | Rust 存储事务适配；应用队列直接使用 NativeQueue |

搜索了仓库内全部 `SharedMemoryLineQueue`、`MappedMemory`、`queue_file_path`、
游标、槽参数、丢包和发布错误的调用，以及单元测试、GitHub Actions、
`setup.py`、Windows MSI／Inno、Linux portable／AppImage／DEB／RPM 和 macOS DMG 流程。
除原实现内部外，没有生产调用方依赖 `_memory`、`_cursor` 或直接构造队列对象。
保留 `key`、`slot_count`、`slot_size`、可读写的 `dropped_messages`、
`last_publish_error`，新增 `last_read_error` 诊断。

## 二进制协议保持不变

| 队列头偏移 | 类型 | 内容 |
| --- | --- | --- |
| 0 | 8 bytes | `BDIPC01!` |
| 8 | u32 LE | 版本 `1` |
| 12 | u32 LE | 槽数 |
| 16 | u32 LE | 每槽最大 payload 字节数 |
| 20 | u64 LE | 下一条序列号 |

队列大小严格等于 `28 + count * (12 + size)`。序列 `s` 的槽起点为
`28 + (s % count) * (12 + size)`，其头部依次为 u64 LE 序列号和 u32 LE
消息字节长度；后面是 UTF-8 payload。首条序列号为 0，末尾 CR/LF 移除，
空 payload／超过槽大小的发布失败。无效 UTF-8 与旧 Python 一样以替代字符解码。
不会将字节数组强转为未对齐的 Rust 结构体。

JSON Envelope 字段仍是 `sender`、`exclude`、`line`、`message_id`、`reliable`。
Python 的编码／宽容解码规则保持；Rust 的 Envelope 使用 serde。未改变
`ACTION`、`LIP`、`EMOTION`、`SETTINGS`、`SHUTDOWN`、`NATIVE_EVENT`、
`NATIVE_CONTROL` 和菜单消息内容。

| 主通道 | 默认参数 | 用途 |
| --- | --- | --- |
| `main-in` | 8 × 65536 | 位置、拖动等可覆盖入站消息 |
| `main-reliable-in` | 32 × 65536，回退 16／8 | 按现有分类发送的入站控制／用户事件 |
| `main-out` | 8 × 65536 | 可覆盖广播 |
| `main-control` | 8 × 65536，回退 4／2 | 控制广播 |

每个消费者的 cursor 仍在本地；tail 附加从 next 开始，非 tail 从最早保留条目开始。
覆盖规则未变。批量读取限制按返回的有效消息数计数，损坏槽位会跳过并计入丢包。
发布成功表示已提交给映射环形队列，并不表示消费者已处理。

## 发现与修复的问题

* 旧 Python 创建映射后才另行初始化队列头，附加者可能看到中间状态。
  Rust 在独占生命周期锁与数据锁下完成 extent、清零和头部初始化后才开放附加。
* 旧创建者退出后，Unix 上可能 unlink 仍被映射的文件；新创建者可能重建另一 inode，
  或截断残存消费者的映射。现在所有新参与者持有 `.lease` 共享锁，重建必须取得独占锁。
  创建者崩溃而旧消费者还活着时，重建明确失败；旧消费者仍可通信和重新附加。
* 旧 Python 对发布／读取时被损坏的 count、size、extent 检查不完整，可能除零、越界或抛异常；
  原生实现还使用外部字节转换的 `unwrap()`，序列递增可能溢出。
  现在每次事务校验 magic、version、extent 和固定布局，所有大小计算受 checked arithmetic
  与 256 MiB 上限约束；u64 序列耗尽时返回错误而不回绕。
* 发布先将槽长度置零，再写 payload／序列／有效长度，最后提交 next；写入阶段间有 release fence。
  被杀死的写入者不能让旧序列引用部分替换的有效 payload；无效槽会明确计入丢包。
  这不是磁盘持久化日志，不承诺断电后的事务持久性。
* 新 PyO3 对象使用 `frozen` 类和每对象 Mutex；先释放 GIL，再取 Mutex／OS 锁，
  不在持锁时调用 Python。避免并发 `&mut pyclass` 的 already-borrowed 错误及 GIL 互锁。
* 读取一次返回整个批次、丢包计数和错误；没有每条消息的 FFI、后台工作线程、忙等待，
  也没有新增轮询或修改 Qt／winit 的现有调度。
* 所有路径都由 RAII 持有文件／mmap；显式 close 先 unmap 再关闭文件句柄。
  存储失败返回结构化错误，Python 可恢复发布／读取仍返回 False／[]。

### 锁顺序和文件生命周期

创建／回收使用 `.owner` 独占锁 → `.lease` 独占锁 → `.shm` 数据锁。
附加者持 `.lease` 共享锁直到解除映射；数据读写只取 `.shm` 锁。
关闭不在持有数据锁时等待 owner，且清理锁都使用 try-lock；最后一个参与者在
owner 已退出后删除 `.shm`。活跃队列的重复 create 不会清空数据。

`.owner` 与 `.lease` 是稳定锁名，故意保留空文件，不在运行中删除以避免 Unix
锁命名空间分裂。每个进程的映射和句柄均会释放，正常最后关闭删除数据文件。
全部进程被强制终止时，操作系统释放锁；下一次 create 可回收遗留数据文件。

锁由 fs2 提供：Windows 使用 LockFileEx，Unix 使用 flock。数据锁仍锁定原
`.shm` 文件，能与旧 Python 的 Windows 首字节锁／Unix flock 冲突并正确串行化。
旧实现不认识新 lease，故新旧版本只承诺数据格式／读写互通；滚动升级时必须先退出
旧进程再重建队列，不能让旧创建者继续执行其不安全的截断／unlink 生命周期操作。

### 可靠通道的协议边界

v1 没有共享消费者确认或持久重放。可靠通道仍是有限覆盖环：不能将 publish=True
解释成端到端送达，也不能保证暂停的消费者在无限积压后收到所有命令。
迁移保留单独通道、既有分类、设置进程重试／stdout 后备、注册时重发设置和
False／异常的既有调用处理。`NATIVE_CONTROL/music_scale` 仍走可覆盖通道。

兼容修复增加了可观测性：覆盖／损坏计数与读取错误在 Python 记录为 error，
原生端报告广播／CONTROL 丢失、可靠发布失败和损坏 Envelope，避免静默吞掉控制消息。
没有假装在未改变协议的情况下实现 ACK／重放／exactly-once；需要这种保证的后续工作
必须单独设计并对旧参与者提供兼容方案。

## Python／构建接口

`SharedMemoryLineQueue.create/attach/publish/read_available/close/is_attached`
保持调用方式、默认值、较小槽数回退和正常返回语义。关闭后的读取为空；非空且合法长度
的发布失败并给出 `queue is detached`，空／超长 payload 的错误优先级也保持。

`MappedMemory` 保留 create/attach/detach/lock/unlock/data/isAttached/error/errorString。
它仅供旧低层调用兼容：data 返回受事务保护的 bytearray 快照，lock 刷新、unlock 提交。
不再向 Python 暴露可能在 close 后悬空的 mmap 指针。它不是 mmap 类型替代品；
外部调用方必须遵守原有 lock/data/unlock 契约，不能在解锁后保留 buffer 并期待跨进程实时更新。
应用队列没有使用此拷贝路径。

源码开发（使用运行应用的同一个 CPython 3.10+，普通 GIL 构建）：

```sh
python -m pip install -r requirements.txt -r requirements-dev.txt
python tools/build_ipc.py
cargo build --manifest-path native/pet_backend/Cargo.toml -p pet-ipc --example ipc_peer --locked
python -m pytest tests/test_rust_ipc.py tests/test_shared_memory_ipc.py -q
```

PyO3 使用 abi3-py310；普通 CPython 3.10+ 同架构可加载，操作系统和 CPU 架构必须匹配。
free-threaded CPython 不在本次发行目标中，构建脚本会明确拒绝。
构建脚本读取 Cargo JSON 产物，支持 CARGO_TARGET_DIR；macOS 显式选择当前 Python
的 arm64／x86_64 目标，包含 Rosetta 下的 x86_64。无导入时编译、自动下载或运行时后备。

`setup.py build/build_exe/bdist_mac/build_msi/build_inno` 先构建扩展并验证导入，再交给
cx_Freeze 显式包含 `bandori_core._pet_ipc`。冻结后的扩展数量、非空内容和 PE／ELF／
薄 Mach-O 架构均校验，缺少或错架构就失败。`smoke_frozen_ipc.py` 用独立 session
检查真实冻结 helper 的 Unicode 消息发布；不启动 UI 或写用户配置。
Windows、Linux、macOS 发行路径共用此步骤，Linux portable 也通过 setup.py 进入。

CI 的 Python 回归先构建扩展及独立 Rust peer；native CI 覆盖三平台的 x86_64／aarch64
runner，执行相同的协议、并发、崩溃测试。发行矩阵保留六种原生架构构建。

## 可复现基准

旧实现原样隔离在 `tools/benchmarks/legacy_ipc.py`，只被测试和基准导入；它不在
应用运行路径，也不是缺少扩展时的后备。原始测量见
[Windows x86_64 JSON](benchmarks/ipc-windows-x86_64.json)。

```sh
python tools/build_ipc.py
cargo build --manifest-path native/pet_backend/Cargo.toml -p pet-ipc --example ipc_peer --release --locked
python tools/benchmarks/ipc_benchmark.py --count 400000 --size 256 --slots 256 --batch 64 --repeats 3 --output docs/benchmarks/ipc-windows-x86_64.json
```

同一台 Windows 10 x86_64，CPython 3.14.6、GNU Rust 1.99.1 release。每组 40 万条，
每条恰好 256 字节，256 槽；旧／新交替执行顺序，下面为三轮各指标的中位数。
单进程延迟是 publish + read 的一次往返；跨进程延迟是发布前时间戳至消费者批量读取，
含批内等待和 OS Event 唤醒。跨进程按 64 条握手，避免覆盖，也不通过自旋等待。

| 场景 | 消息/秒 | 平均 µs | P95 µs | P99 µs | CPU 秒/40 万条 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 旧 Python，单进程 | 125533 | 7.882 | 8.5 | 10.5 | 3.188 |
| Rust，Python 兼容接口，单进程 | 338393 | 2.859 | 3.1 | 3.6 | 1.188 |
| Rust，直接 PyO3 接口，单进程 | 369519 | 2.621 | 2.9 | 3.1 | 1.078 |
| Rust 原生循环，单进程 | 501692 | 1.915 | 2.0 | 2.3 | 0.797 |
| 旧 Python，跨进程批量 | 172150 | 199.457 | 332.6 | 503.7 | 2.188 |
| Rust，Python 兼容接口，跨进程批量 | 359302 | 93.037 | 184.3 | 332.3 | 1.016 |

本机的兼容接口单进程吞吐约 2.69 倍、跨进程约 2.09 倍。CPU 百分比也在 JSON 中：
这些是持续饱和负载，单进程都接近一核，不能据此声称空闲 CPU 降低。
Python CPU 使用 process_time，跨进程为双方 CPU 总和；Rust 原生循环用 psutil 读取
子进程 CPU 差值，包含少量请求解析／统计／结果编码。Windows CPU 时间有计时粒度误差。
FFI 与原生循环的差值含 Python 循环、返回值转换与断言，并非纯粹的 ABI 调用成本。
主机没有隔离 CPU 或关闭其他应用，结果不能外推到其他机器／平台。

## 本机验证记录

本次实际验证环境为 Windows x86_64，CPython 3.14.6、Rust 1.99.1 GNU。
系统最初混用了 MSYS2 Cargo 与 rustup 默认 MSVC Clippy，缺少 link.exe；本次验证
通过进程环境选择同一个 GNU 工具链，安装其 Clippy／rustfmt 后重跑成功，没有修改仓库默认目标。

| 实际执行 | 结果 |
| --- | --- |
| `cargo fmt --manifest-path native/pet_backend/Cargo.toml --all -- --check` | 通过 |
| `cargo clippy --manifest-path native/pet_backend/Cargo.toml --workspace --all-targets --locked -- -D warnings` | 通过 |
| `cargo test --manifest-path native/pet_backend/Cargo.toml --workspace --all-targets --locked` | 469 passed，5 ignored |
| `python -m pytest tests -q -rs` | 802 passed，2 skipped，190 subtests passed |
| `python -m pytest tests/test_rust_ipc.py tests/test_shared_memory_ipc.py -q` | 52 passed，确认 Rust 扩展类型与双向跨语言通信 |
| `python -m ruff check .`、`git diff --check` | 通过 |
| actionlint 校验三份修改后的 GitHub Actions 工作流 | 通过 |
| 重建后的原生后端 `tests/test_native_backend.py` | 5 passed |
| Windows DirectComposition 生命周期测试，显式 `--ignored` | 1 passed（在默认忽略项之外单独执行） |
| 实际 GPU／窗口／IPC smoke，arisa 像素模型及 anon Live2D MOC3 | 均通过；生成截图于 `.runtime/ipc-*-smoke*.png` |
| cx_Freeze `setup.py build_exe --build-exe .runtime/ipc-freeze-smoke` | 通过；自动检查冻结 helper 的 Unicode 发布 |
| 临时移走冻结目录内扩展后执行 helper，再恢复 | 明确失败并提示必须安装 Rust 扩展；无 Python 后备 |
| 冻结目录扫描 | 没有 `legacy_ipc` 模块 |

Python 两个跳过项为当前测试解释器缺少 py7zr 的升级包测试，以及 Windows 无 Unix resource 模块。
全套 Python 测试输出还包含原有 LuaJIT 错误跨 RPC 测试的 Windows 本机异常诊断，
pytest 最终退出码为 0；没有将这些输出隐藏或计作 Rust IPC 测试失败。
默认 Rust 忽略项需要真实模型／GPU／Windows 桌面条件，其中 Windows 合成生命周期测试另行运行通过。
本机冻结使用既有 `.venv-build` 的 cx_Freeze 8.7.3，并通过 site.addsitedir 提供已安装的系统依赖；
首次缺少 PySide6／pywintypes 的构建失败后补齐搜索路径，再执行真实构建和冻结通信测试。
未在本机生成或安装 MSI／Inno／Linux／macOS 安装器。

本机不能证明 Linux／macOS 的 flock／mmap 行为、aarch64 二进制加载或六平台发行包完成。
CI 已接入这些目标，但未把尚未在远端运行的 workflow 报告为通过。

## Git 交付

分支为 `codex/unify-rust-ipc`，保留开始时的两个未跟踪项
`examples/plugins/hello_managed/` 和 `tools/plugin_dev_check.py`，未把它们混入提交。
实现与验证按阶段提交，最终文档／测量数据另作一笔提交：

| 提交 | 内容 |
| --- | --- |
| `71ee060fd9cefb0d44913212dd8cdbf8286309d0` | Rust 核心、PyO3 crate、原生后端路由整合 |
| `bad374d87c79136e813263f5e3eba990fa733b01` | Python 兼容队列／存储接口接入 PyO3 |
| `a1ff530e7e3da4649d7fd2513adb641a0f31b8a5` | 冻结／发行构建、架构校验与 CI |
| `5d2df933b455b7b1582cbec4bb0d37cc0ae49bba` | 单次 FFI 返回批量消息与诊断 |
| `f2ba36e9544add561a15e4a2ac0ed3469fe50f90` | 并发、崩溃、互通、冻结包测试与基准工具 |
| `751a57ee2f8b6604ec02459331cb162032f3953d` | Python 超大批量参数兼容修复；最终基准对应版本 |
| `c9e2f557ff0da8b7b0afd7201f5b9e0f49b0f927` | 六平台 CI 明确选择对应 CPU 架构的 Python |

参考：[fs2 锁接口](https://docs.rs/fs2/0.4.3/fs2/trait.FileExt.html)、
[PyO3 线程安全](https://pyo3.rs/v0.29.0/class/thread-safety.html)、
[PyO3 构建与分发](https://pyo3.rs/v0.29.0/building-and-distribution.html)。
