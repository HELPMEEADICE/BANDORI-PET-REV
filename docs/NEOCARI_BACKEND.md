# Neocari 宠物后端

主程序直接启动 `bandori-pet-native`，每个角色一个 Rust 进程。该进程使用 Neocari 加载 `.moc` / `.moc3`，通过 wgpu 和 winit 绘制透明窗口；像素角色也使用同一套原生 GPU 渲染与透明度命中检测。宠物进程不加载 Python、Qt、OpenGL Widgets、LuaJIT 或 Cubism Core。设置预览由 Neocari 离屏生成 PNG，Qt 仅显示图像。

## 构建和运行

安装 Rust stable、对应平台的 C/C++ 构建工具，以及原有 Python 界面依赖：

```sh
git submodule update --init --recursive
cargo build --release --manifest-path native/pet_backend/Cargo.toml --locked
python main.py
```

源码运行自动查找 `native/pet_backend/target/release/`、`target/debug/`；发行包从主程序目录查找 `bandori-pet-native[.exe]`。`BANDORI_PET_NATIVE` 可以指定可执行文件。找不到后端时会提示构建命令，不会退回 Qt 宠物窗口。`pet_process.py` 是兼容命令行入口，实际启动的仍是 Rust 后端。

Windows 使用 Vulkan / DirectX 12，macOS 使用 Metal。Linux 宠物窗口使用 X11，在 Wayland 会话中需要 XWayland；原来的 Qt layer-shell 宠物窗口不参与渲染。原生 Wayland 窗口定位与层级协议尚未接入 Rust 后端。此处与原来的 [Qt Wayland 指南](WAYLAND_NATIVE.md) 不同，应以本文为准。

`setup.py build` 会先构建 release 后端并将其和许可文件复制到发行目录。安装包校验包含该可执行文件；macOS / Linux / Windows 构建工作流会拉取固定的 Neocari 子模块。

## 进程边界

- Rust：模型及纹理、动作/表情/物理/眨眼/呼吸、TTS 口型、头部追踪与角色对视、区域点击、拖动、联动拖动、DPI/缩放/裁腿、音乐形变、透明区域穿透、置顶和 OBS 窗口样式。
- Python 主进程：托盘、设置、聊天、径向菜单、紧凑对话框、插件服务、输出音量采样、服装识别任务及配置持久化。这些界面不会进入宠物进程。
- 设置进程：异步调用 Neocari 离屏预览命令，由 Qt 显示 PNG；不加载旧渲染运行时。

Rust 只读启动配置，并接收 `SETTINGS` 增量更新；位置变化回报主程序，由主程序加载最新配置并只修改对应角色的几何字段。避免多个语言的进程同时覆写 `config.json`。保留已有模型路径、服装动作方案以及 `.zst::member` 路径，归档按服装解压到 `.cache/neocari/`。


## 共享内存协议

所有进程继续使用 `SharedMemoryLineQueue` 和原有 `BDIPC01!` 二进制布局、UTF-8 行与 JSON envelope：

| 数据 | 小端布局 |
| --- | --- |
| 28 字节队列头 | `8s magic, u32 version, u32 slots, u32 slot_size, u64 next_seq` |
| 每个槽 | `u64 seq, u32 length, payload[slot_size]` |

底层由 Qt `QSharedMemory` 改为操作系统文件内存映射。映射位于当前用户的私有临时目录，名称来自现有队列 key 的 SHA-256。Windows 使用兼容的字节范围锁，Unix 使用 `flock`，Rust 侧对应 `fs2`。独立 owner 锁避免重置存活队列，进程异常退出后可重新创建。正常分离时尝试删除映射，锁文件保留以避免并发创建时分裂锁。

保留四个通道：`main-in`、`main-reliable-in`、`main-out`、`main-control`。位置/拖动更新使用有界通道；设置、生命周期、聊天事件、原生控制事件使用独立控制通道。消费者保留独立游标，溢出跳过旧的完整消息。升级后应一起重启所有进程，旧 Qt 共享内存进程不能与新版本混用。

新增 `NATIVE_EVENT\t<json>` 用于就绪、位置保存、菜单、点击及帧捕获回报；`NATIVE_CONTROL\t<json>` 用于主程序到原生角色的控制。现有 `ACTION`、`LIP`、`EMOTION`、`PREVIEW_MOTION`、`PEER_*`、`SETTINGS`、`SHUTDOWN` 继续使用。

## 验证

```sh
cargo fmt --manifest-path native/pet_backend/Cargo.toml --all -- --check
cargo clippy --manifest-path native/pet_backend/Cargo.toml --workspace --all-targets --locked -- -D warnings
cargo test --manifest-path native/pet_backend/Cargo.toml --workspace --all-targets --locked
python -m pytest tests -q
python tools/smoke_native_backend.py --character kasumi --model models/kasumi.zst::live_default/model.json
```

`test_native_backend.py` 启动真实 Rust 进程，检查双向共享内存、控制通道、Unicode、设置兼容、口型命令、关闭及配置只读约束；无需模型。Linux 使用 `xvfb-run` 提供测试显示服务。GPU 冒烟工具需要本地模型和图形桌面，会输出启动帧及运行中的 GPU 帧，并在安装了 psutil 时确认原生进程没有加载 Qt/Python/LuaJIT。

## 渲染性能基准

动画顶点按连续变化的网格合并上传，未变化的网格仍跳过；遮罩计划在边界变化时复用分组，只在显隐或拓扑变化时重建。`.moc` 的口型覆盖在物理和姿态之后、网格求值之前应用，避免同一帧重复求值。

使用已解压的模型运行基准，输出 JSON 中的动画求值和网格上传准备耗时（微秒）：

```sh
cargo run --release --manifest-path native/pet_backend/Cargo.toml --example render_benchmark --locked -- path/to/model.json 600
cargo run --release --manifest-path native/pet_backend/Cargo.toml --example render_benchmark --locked -- path/to/model.model3.json 600 .runtime/render-benchmark
```

基准预热 120 帧，再采样指定帧数，包含默认动作、追踪、物理及周期口型，关闭随机眨眼。GPU 提交和等待、几何校验、可选截图均不计时。指定截图目录后，在第 120、300、600 帧比较持续更新的 GPU 缓冲区与全新上传的 RGBA 像素，必须逐字节一致。该指标衡量 CPU 帧准备开销，不代表最终呈现 FPS。

2026-10-29 在 NVIDIA GeForce RTX 5080 Laptop GPU 上，将同一基准分别编译到原始代码（主仓库 `2ecef8c`、Neocari `bae7610`）和优化代码，交替运行三轮，每轮采样 600 帧。以下是三轮中位耗时的中位数：

| 模型 | 网格 / 顶点 | 动画求值：优化前 → 后 | 上传准备：优化前 → 后 | 上传准备降幅 |
| --- | --- | --- | --- | --- |
| Kasumi `live_default`（moc） | 124 / 5,085 | 260.6 → 159.8 µs | 179.6 → 63.2 µs | 64.8% |
| Anon `casual_spring_01`（moc3） | 352 / 9,190 | 1,418.7 → 1,438.1 µs | 669.1 → 345.6 µs | 48.3% |

两种模型的全程几何校验值及三个抽样帧的 RGBA 像素在优化前后均一致。moc3 动画求值路径没有改动，表中的小幅波动保留原始测量结果；实际收益随模型、驱动及硬件而变化。

## 来源与许可

原生组件参考 [BANDORI-PET-LITE](https://github.com/HELPMEEADICE/BANDORI-PET-LITE) 的 `b102c3123f1e74262b4155237d2b2ad31d5c7c6a`：模型适配、渲染、窗口、输入、行为和配置公共类型在此基础上调整，采用 GPL-3.0-only。Neocari 使用子模块固定在 `f4eee3e95ec27530a1ebfdb60aa6bd478b4cabbc`，参见其 `LICENSE` 和 `LICENSES/`。发布包携带这些许可；本项目不在安装包中附带角色模型。

Lua 插件仍使用 `lupa.luajit21`；安装包保留该插件运行时。旧 Live2D Lua 适配器、命中区域脚本、字节码编译和渲染源码打包已移除。
