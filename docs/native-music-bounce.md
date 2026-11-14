# Native Music Bounce

## Audit and migration design

Baseline: `main` before `refactor/rust-native-music-bounce`. The production
`NativePetServices._poll` runs every 30 ms, starts one Python Core Audio worker
(60 Hz), maintains one Python spring per role and broadcasts one JSON
`music_scale` per role per poll. Each role is a separate native process.
`MusicBounceController` has no production callers; its 16 ms timer and per-window
monitor are legacy test-only interfaces. Configuration defaults to false on all
platforms; only Windows supports output metering.

The native executable gains a non-graphical `--music-service PATH` mode, managed
by Python through QProcess. One service serves all roles belonging to that main
application session. Its stdin pipe is the lifetime lease (EOF ends sampling).
No Python interpreter, GUI, GPU or audio stream capture is initialized in this mode.
Reusing the packaged executable covers source, frozen Windows, Linux and macOS
layouts without a second payload. Non-Windows output metering remains unsupported.

`pet-ipc` supplies a fixed latest-value mapping using its existing owner/lease
locks and last-participant cleanup. Python announces only source changes over
the existing reliable control lane; peaks never travel through Python. A new
random path per service generation prevents reconnecting to stale mappings.
Each role advances its independent f64 MusicSpring in the existing frame loop,
then uses the existing matrix setter for drawing and inverse hit testing.
All constants, time-step cap, substeps and scale limits retain the Python baseline.
The Python oracle is frozen under tests/baselines, never imported by production.

## 生产数据流和生命周期

旧路径：Core Audio → Python worker（请求 60 Hz）→ Qt 30 ms 轮询 →
每角色 Python MusicSpring → JSON / 主程序广播队列 → 每角色 Rust 矩阵。

新路径：Core Audio → 单个 Rust 服务（请求 60 Hz）→ `BDLEVEL!` 映射 →
各角色已有帧循环 / 独立 MusicSpring → 原有 GPU 和命中检测共用矩阵。
Python 仅发送 `NATIVE_MUSIC_SOURCE` 源变化通知和原有 `SETTINGS` 配置。
稳态没有音乐电平或缩放 JSON 消息，也没有音乐 Qt 定时回调。

- 同一主程序的多个角色共用一个 QProcess 服务；不同主程序实例独立管理。
  `set_running(True)` 幂等，不会因新增角色再启动一个采样器。
- 管理器只在有可活动角色、已启用且未全局隐藏时启动服务。
  Rust 的 `music_active` 仅在状态变化时报告。最后一个角色离线、隐藏、
  拖动暂停或执行窗口位移动画时停止服务，重新活动时恢复。
- 停止先撤销源通知，再异步关闭 stdin；服务的阻塞管道读取线程收到 EOF 后
  唤醒采样线程。异常退出后以 1 秒单次定时器重试，每次使用新的 UUID 路径。
  主程序崩溃也会由 OS 关闭管道。应用退出最多等待 1.5 秒，超时强制终止服务。
- COM apartment、枚举器和 meter 都在服务采样线程创建、调用和释放。
  `PhantomData<Rc<()>>` 禁止把 apartment 移至其他线程；字段顺序保证先释放
  COM 接口再 `CoUninitialize`。创建失败同样通过 RAII 清理。
- 使用 `GetDefaultAudioEndpoint(eRender, eMultimedia)` 和
  `IAudioMeterInformation::GetPeakValue`，不打开录音流或麦克风。
  沿用原实现的 2 秒默认设备重绑定和失败后 1 秒重试策略。
  参见微软 [默认端点接口](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nf-mmdeviceapi-immdeviceenumerator-getdefaultaudioendpoint)
  和 [峰值接口](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudiometerinformation)。
- 物理 dt 使用实际帧间隔的 f64，不经 f32 中转；弹簧仍将 dt 限制到 0.1 秒，
  按 `ceil(dt*240)` 子步积分。采样使用绝对期限等待，跳过错过的期限，避免
  Windows 等待时间舍入逐次累积，也不执行追赶式忙采样。
- 禁用、隐藏、拖动和窗口位移动画立即清空弹簧与包络并恢复比例 1。
  没有声音源时以零电平自然回弹。缩放只更新矩阵，不修改窗口位置或尺寸。
  MOC、MOC3、VRM 和像素模型继续经过同一个既有矩阵入口。

旧 Python `MusicSpring`、`OutputLevelMonitor`、`MusicBounceController` 已从生产模块
删除：代码搜索未找到任何非测试调用方。没有保留会重新启动旧采样器的兼容层。
迁移后测试对原行为的验证转为 Rust 单元测试、冻结 Python oracle 的数值对照以及
原生服务和 GPU 集成测试。原 `music_scale` 的 IPC 分类仍保留，旧消息不会挤占
可靠通道，但原生角色已不接受该控制命令，避免形成第二条缩放驱动路径。

## 共享数据契约

版本 1，固定 40 字节，全部小端编码，不依赖 Rust 原生结构体布局：

| 偏移 | 长度 | 内容 |
|---|---|---|
| 0 | 8 | `BDLEVEL!` |
| 8 | 4 | version = 1 |
| 12 | 4 | committed，0 表示无效 / 写入未完成 |
| 16 | 8 | 单调递增的 sequence，0 表示没有样本 |
| 24 | 8 | Unix 毫秒采样时间戳 |
| 32 | 4 | 有限且限制在 0..1 的 f32 peak |
| 36 | 4 | 保留，0 |

生产者使用非阻塞 OS 排他数据锁，读者使用非阻塞 OS 共享数据锁，允许并发读。
Acquire/Release fence 配合锁保证内存可见性。写入先使 committed 无效，最后提交；
锁竞争允许丢弃样本，读竞争、坏版本、未提交、NaN、未来时间或超过 250 ms 的
样本均视为静音。读者还按 sequence 使用本地单调时钟超时，防止系统时间回调
重新激活已经冻结的数据。每帧读取不创建 Vec、不解析 JSON、不复制整个映射。

复用 `pet-ipc::Storage` 的 `.owner`、`.lease` 协议：活 owner 不允许第二个
生产者；存在任何读者时不允许截断或复用文件；最后一个参与者释放后删除映射。
管理器还通过轻量 Rust FFI 清理“生产者在第一个消费者连接前被杀死”的映射。
正常主程序崩溃由 stdin EOF 触发服务正常释放。所有路径都由已有用户临时目录
生成器和随机 UUID 创建，不写配置，不要求用户设置环境变量；Unix 沿用目录
0700、文件 0600，Windows 沿用用户临时目录的 ACL。独立用户及主程序会话不会
共用一个固定全局名字。

与现有 IPC 一样，锁 sidecar 必须保留，不能 unlink 后产生两个锁命名空间。
同时强杀全部参与者或系统掉电仍可能留下临时文件；新一代不会读取或复用它，
它不含音频数据，仅有峰值和时间戳。这些残留不参与下一次运行。
现有有限可靠控制环仍没有 ACK，未改变其已有协议保证。

## 修改文件和模块职责

| 文件 | 职责 |
|---|---|
| `native/pet_backend/Cargo.toml` | 为现有 windows 依赖启用 Core Audio、COM、Variant 所需 features；没有新增依赖或 workspace 成员 |
| `crates/pet-behavior/src/music.rs`、`src/lib.rs` | 独立 f64 弹簧、包络、重拍、复位、安全缩放及单元测试 |
| `crates/pet-behavior/examples/music_trace.rs` | stdin/stdout 确定性轨迹对照工具 |
| `crates/pet-ipc/src/level.rs`、`src/lib.rs`、`src/storage.rs` | 版本化最新电平、非阻塞锁、所有权和回收 |
| `crates/pet-ipc/tests/level.rs`、`examples/level_peer.rs` | 并发、过期、半写入、异常退出、多进程验证 |
| `crates/pet-ipc-python/src/lib.rs` | 只暴露映射回收，不向 Python 暴露音频采样或物理 |
| `crates/pet-config/src/config.rs` | 明确 `music_bounce_enabled: false` 数据契约，保留未知配置 |
| `native/pet_backend/src/music_service.rs` | 非图形服务入口、COM RAII、设备恢复、管道生命周期、可选性能计数 |
| `native/pet_backend/src/music_source.rs` | 角色的共享源连接、重连、禁用释放和最新电平读取 |
| `native/pet_backend/src/main.rs`、`src/role.rs` | 每帧独立弹簧、状态变化事件、立即复位、共用矩阵和诊断状态 |
| `native/pet_backend/examples/music_benchmark.rs` | 纯物理和无 GPU 多角色资源测量 |
| `bandori_audio/music_bounce.py` | 配置支持判断、幂等服务管理、异常恢复和退出 |
| `bandori_ui/native_pet_services.py` | 按配置与角色活动管理服务；无菜单时停止 30 ms 轮询 |
| `bandori_core/ipc_bus.py` | 共享源通知进入原有可靠控制通道 |
| `tests/baselines/music_spring.py` | 冻结原 Python 算法，仅用于测试 |
| `tests/test_music_bounce.py`、`tests/test_native_pet_services.py` | 数值对照、生命周期、无高频 Python 工作、多角色服务控制 |
| `tools/benchmarks/music_bounce_benchmark.py` | 可复跑旧 / 新实际计时与 IPC / RSS 测量 |
| `tools/smoke_music_bounce.py` | 确定性测试电平驱动的真实窗口 / GPU / 几何 / 禁用冒烟 |
| `.github/workflows/native-backend.yml`、`ci.yml` | 在现有平台矩阵构建对照工具并执行音乐回归 |
| `setup.py` | 说明共用原生可执行文件的打包要求 |
| `docs/native-music-bounce.md`、`rust-ipc.md`、`benchmarks/native-music-windows-debug.json` | 数据契约、限制、验证和原始测量 |

表中 `crates/` 路径相对于 `native/pet_backend/`。

## 构建与验证

沿用 `native_executable()` 的源码 / 冻结包发现逻辑，无需手设环境变量。
`setup.py` 已经构建并复制 `bandori-pet-native`；Windows MSI / Inno、Linux
portable / AppImage / DEB / RPM、macOS DMG 均已有该可执行文件的验证、复制和
签名路径。因此服务作为同一可执行文件的模式随包交付，没有第二个服务文件遗漏
的风险。`Cargo.lock`、workspace 成员和 GPL-3.0-only 许可均无需改变。

本机 Windows x86_64 GNU、Rust 1.98.1、CPython 3.14.6：

- `cargo fmt --manifest-path native/pet_backend/Cargo.toml --all -- --check`：通过。
- `cargo clippy ... --workspace --all-targets --locked -- -D warnings`：通过。
  本机 `cargo clippy` 的自动插件发现曾选中另一套缺少 link.exe 的 MSVC 工具链；
  最终直接调用 `C:/msys64/ucrt64/bin/cargo-clippy.exe clippy` 完成同等严格检查。
- `cargo test ... --workspace --all-targets --locked`：481 passed，5 ignored。
- `python -m pytest tests -q`：840 passed，3 skipped，200 subtests passed。
  全仓库运行仍打印既有插件 Lua 用例的 Windows 原生异常诊断，pytest 退出码为 0；
  本次未修改该插件路径或屏蔽诊断。
- 对照音频：30/60/144 FPS，各 20 秒的重拍、音量突变、弱音乐和静音，加极端 dt、
  NaN/Inf 和 reset，Rust 与冻结 Python 逐点误差满足绝对 / 相对 `1e-11`。
- 四个独立消费者进程并发读取；生产者退出码 13、服务 kill/restart、新 generation、
  数据过期、父 Python `os._exit`、禁用释放、半写入无效槽和锁竞争均有测试。
- 真实 GPU 音乐冒烟：MOC (`kasumi/2018_dog`)、MOC3 (`Wanko`)、最小 VRM1
  和像素 `arisa.webp` 均通过。观察到 scale 约 0.778..1.102，所有采集到的窗口
  坐标和尺寸不变，禁用 / 隐藏复位为 1，GPU 截图成功，最后参与者删除共享映射。

复跑：先构建 debug 原生后端、`pet-ipc --example level_peer`、
`pet-behavior --example music_trace` 及 `python tools/build_ipc.py --debug`。
随后运行测试或：

```text
python tools/smoke_music_bounce.py --model native/pet_backend/vendor/neocari/assets/models/Wanko/Wanko.model3.json
python tools/smoke_music_bounce.py --model pixels/arisa.webp --pixel
python tools/smoke_music_bounce.py --model native/pet_backend/crates/pet-vrm/tests/fixtures/minimal-vrm1.vrm
cargo build --manifest-path native/pet_backend/Cargo.toml --example music_benchmark --locked
python tools/benchmarks/music_bounce_benchmark.py --seconds 5 --roles 1 8 --output docs/benchmarks/native-music-windows-debug.json
```

Linux/macOS 的音乐采样支持仍为 false；条件编译保留可启动的安全零电平服务桩，
不宣称支持其他平台的系统输出采样。现有六项 OS/架构 CI 矩阵已增加 parity / 服务
生命周期验证，本机没有执行远端 CI、Linux/macOS/ARM64 构建、发行包安装或 DMG
签名验证。真实设备拔插与默认输出切换、独占音频模式、人工拖动观感亦未实测；
设备失败恢复和拖动 / 位移动画暂停的状态逻辑分别由测试和代码路径覆盖。

## 实测性能（2026-11-14）

原始数据：`docs/benchmarks/native-music-windows-debug.json`。Windows 10 x86_64，
debug profile（本项目 dev opt-level=1），每组稳态计时 5 秒，测量前预热，编译和
测试不与最终测量并行。旧模块从审计基线 Git commit 加载；新版运行实际
`NativePetServices` / `NativeMusicService`，两者向隔离的真实映射队列发布消息。
新版另启动 N 个独立原生无 GPU 帧循环探针，模拟现有角色里的读取和物理工作。

| 场景 | 旧音乐缩放 IPC/s | 新音乐缩放 IPC/s | 旧 Python 百万 CPU 周期/s | 新 Python 百万 CPU 周期/s |
|---|---:|---:|---:|---:|
| 启用，1 角色 | 31.74 | 0 | 23.89 | 0.176 |
| 启用，8 角色 | 246.76 | 0 | 30.12 | 0.220 |
| 关闭，1 角色 | 0 | 0 | 8.15 | 0.258 |
| 关闭，8 角色 | 0 | 0 | 8.52 | 0.255 |

此表 CPU 周期来自实际 `QueryProcessCycleTime`，包括旧 Python 音频线程。
没有用假定 CPU 主频把周期换算成秒或利用率。最终这轮 Windows 进程 CPU 秒计时
在所有组都舍入为 0，因此**不能定量声称整机 CPU 百分比下降多少**。周期和消息
计数能够反映该隔离路径中主 Python 工作量的减少；不同硬件、负载、编译 profile
或 CPU 频率下不应直接复用这些数字。新版稳态源变化通知实测也为 0。

- 同一 100 万步热循环：Python 平均 1.035 µs/步，Rust 0.0229 µs/步。
  这是热循环微基准，不能当作端到端帧耗时；实际有等待间隔的探针物理更新平均
  为 1.25–1.96 µs/帧，映射读取平均 15.36–20.57 µs/帧。
- 真实默认输出端点可用：服务分别成功读取 365/365、366/366 次，平均采样 API
  路径 136.7/141.2 µs（包含初始化 / 周期重绑定），发布 9.34/9.26 µs。
  实际服务采样率约 60 Hz，与探针的 60 FPS 独立。
- 1/8 角色均只有一个服务，工作集约 9.9 MiB；各独立无 GPU 探针工作集约
  6.4 MiB。原始 JSON 同时记录主 Python 工作集、每个探针和服务的 CPU 秒、
  CPU 周期、工作集及逐进程计时。主 Python 工作集包含已加载 Qt、预热和先前组
  的分配，不能把其小幅变化归因为本次迁移的净内存变化。
- 关闭后服务数量为 0，无音乐后台线程、重试定时器或映射读取。没有菜单时
  Python 原先一直运行的 30 ms 服务轮询也停止。无 GPU 探针仍有自身 60 FPS
  等待循环，代表已有角色循环，不代表关闭功能后新增了后台进程。
- 独立服务相对旧 Python 线程增加约 10 MiB 的服务进程工作集，这是本方案的
  实测资源代价。**本次没有测量完整应用在多宠 GPU 渲染下的总 CPU / 总内存净变化**，
  不将探针结果冒充整机或完整应用性能。

## 分阶段提交

- `0f687c3`：审计设计与冻结 Python 基线。
- `aac0243`：原生弹簧和确定性轨迹工具。
- `6e34094`：跨进程最新电平映射。
- `6530637`：Windows 原生采样服务。
- `c09da4c`：角色渲染循环集成。
- `7734521`：Python 生产路径清理及服务生命周期。
- `303aee3`：回归、故障恢复、GPU 冒烟、基准和构建检查。
- 最后一个文档提交记录本报告与原始实测数据，具体 hash 见 `git log -8`。
