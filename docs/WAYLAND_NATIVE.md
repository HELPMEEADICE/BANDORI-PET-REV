# BandoriPet 原生 Wayland 运行指南

BandoriPet 在 Wayland 会话中只使用 Qt Wayland，不再自动设置
`QT_QPA_PLATFORM=xcb`。如果用户显式设置了 `xcb`，应用会拒绝启动并给出错误，
以免用户误以为正在使用原生 Wayland。

## 能力矩阵

| 合成器 | 透明区域穿透 | 绝对定位/恢复 | 全局鼠标注视 | 全屏游戏置顶 |
|---|---:|---:|---:|---:|
| Plasma 6 | 是 | LayerShellQt | KWin 脚本 | overlay layer |
| Hyprland | 是 | LayerShellQt | `cursorpos` 权限 | overlay layer |
| GNOME 46+ | 是 | GNOME Shell 扩展 | GNOME Shell 扩展 | Shell top window group |
| 其他 Wayland | 是 | 仅系统拖动 | 仅窗口内 | 尽力而为 |

锁屏、认证对话框及其他安全界面始终由合成器置于桌宠之上。GNOME 扩展检测到
锁屏时会主动撤销游戏 overlay。

## 1. 使用系统 Qt/PySide6

LayerShellQt 使用 QtWayland 私有 ABI。Plasma/Hyprland 源码运行环境必须安装
同一发行版、同一 Qt minor 的以下组件：

- Python 3 与系统 PySide6；
- Qt 6 Base 开发包；
- Qt 6 Wayland 运行时与开发包；
- LayerShellQt 运行时与开发包；
- Shiboken6 开发文件、CMake 和 C++17 编译器。

不要在该环境中安装 PyPI 的 `PySide6` wheel。推荐让虚拟环境读取发行版的
PySide6：

```bash
python3 -m venv --system-site-packages venv-wayland
source venv-wayland/bin/activate
python -m pip install -r requirements-linux-wayland.txt
```

安装完成后先确认 Qt 确实来自系统环境：

```bash
python -c 'from PySide6.QtCore import qVersion; import PySide6; print(qVersion(), PySide6.__file__)'
```

GNOME 不需要 LayerShellQt 原生桥，但仍需要 Qt 6 Wayland。

## 2. 构建 LayerShellQt 桥

Plasma 6 与 Hyprland 执行：

```bash
BANDORIPET_PYTHON=venv-wayland/bin/python \
  bash installer/linux/wayland/build_native_bridge.sh
```

脚本会：

1. 从当前 PySide6 读取 Qt 版本；
2. 用 `find_package(Qt6 <版本> EXACT)` 查找系统开发文件；
3. 链接 `LayerShellQt::Interface`、PySide6 和 Shiboken6；
4. 将扩展复制到 `wayland/_native/`；
5. 在当前 Python 中验证编译期与运行期 Qt minor 一致。

版本不匹配时桥接会失败关闭，应用仍可原生 Wayland 启动，但只提供通用降级能力，
绝不会切回 XWayland。

## 3. 安装合成器伴侣

也可以在“设置 → 角色行为 → Wayland 原生集成”中安装、刷新或移除。设置页执行
任何修改前都会显示确认框。

命令行状态：

```bash
python installer/linux/wayland/manage_companion.py --status
```

安装当前合成器的伴侣：

```bash
python installer/linux/wayland/manage_companion.py --install
```

移除：

```bash
python installer/linux/wayland/manage_companion.py --remove
```

### Plasma 6

安装器使用 `kpackagetool6` 安装并启用 `bandoripet-wayland` KWin 脚本。脚本只
识别带有本次进程随机标记、PID 和 BandoriPet 应用 ID 的窗口，并将
`workspace.cursorPos` 推送到对应进程。窗口定位与置顶仍完全由 layer-shell
处理。

### GNOME 46+

安装器复制并启用 `bandoripet-wayland@bandoripet`。部分发行版或 Wayland
会话需要注销并重新登录后扩展才会加载。扩展只管理 PID、随机会话标记和
surface ID 同时匹配的 BandoriPet 窗口；禁用扩展会恢复 actor 父级、
`make_above` 和工作区常驻状态。

### Hyprland

不安装合成器插件。桌宠可见且“头部跟随鼠标”开启时，应用最多以 60 Hz 直接
访问 Hyprland command socket 的 `cursorpos`。应用首次访问前会先显示明确授权
对话框，也可在 Wayland 状态卡撤销或重新授权；拒绝后桌宠只保留窗口内跟踪并
平滑回正。若 Hyprland 本身拒绝 command socket，状态卡会保留降级状态。

## 4. 启动和验证

```bash
unset QT_QPA_PLATFORM
python main.py
```

验证 Qt 平台：

```bash
QT_LOGGING_RULES='qt.qpa.*=true' python main.py
```

调试协议提交：

```bash
WAYLAND_DEBUG=client python main.py 2>wayland.log
```

验收时应满足：

- 设置卡显示 Qt 平台为 `wayland`；
- 应用进程未加载 `libqxcb.so`；
- `xlsclients` 中没有 BandoriPet 窗口；
- 日志中能看到 `wl_surface.set_input_region`；
- 透明像素的点击到达下层窗口，模型像素仍可拖动和交互；
- `game_topmost` 在全屏应用上方，而锁屏仍覆盖桌宠。

## 已知降级

- Generic Wayland 没有跨应用的被动全局鼠标协议，因此只在鼠标进入桌宠表面后
  跟踪，并在 250 ms 无样本后用 300 ms 平滑回正。
- Generic xdg-shell 不允许客户端恢复任意全局位置，拖动使用
  `QWindow.startSystemMove()`，重启后不承诺恢复位置。
- 首版只支持源码运行；Linux cx_Freeze/便携包不包含原生桥或桌面伴侣。
