# Neocari 宠物后端

主程序直接启动 `bandori-pet-native`，每个角色一个 Rust 进程。该进程使用 Neocari 加载 `.moc` / `.moc3`，通过 wgpu 和 winit 绘制透明窗口；像素角色也使用同一套原生 GPU 渲染与透明度命中检测。宠物进程不加载 Python、Qt、OpenGL Widgets、LuaJIT 或 Cubism Core。设置页的 Live2D 预览仍使用现有 Qt 实现。

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
- 设置进程：继续持有 Qt 模型预览。

Rust 只读启动配置，并接收 `SETTINGS` 增量更新；位置变化回报主程序，由主程序加载最新配置并只修改对应角色的几何字段。避免多个语言的进程同时覆写 `config.json`。保留已有模型路径、服装动作方案以及 `.zst::member` 路径，归档按服装解压到 `.cache/neocari/`。

`bandori_ui/pet_window.py` 保留用于旧实现的行为回归测试与迁移参考；主程序和兼容启动器均不再导入它，也没有 Qt 宠物回退路径。

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

## 来源与许可

原生组件参考 [BANDORI-PET-LITE](https://github.com/HELPMEEADICE/BANDORI-PET-LITE) 的 `b102c3123f1e74262b4155237d2b2ad31d5c7c6a`：模型适配、渲染、窗口、输入、行为和配置公共类型在此基础上调整，采用 GPL-3.0-only。Neocari 使用子模块固定在 `bae7610a67d846ae7d2b8286fd6062e6a64e451d`，参见其 `LICENSE` 和 `LICENSES/`。发布包携带这些许可；本项目不在安装包中附带角色模型。
