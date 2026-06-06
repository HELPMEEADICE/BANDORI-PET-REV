# macOS DMG 打包指南（开发者）

本指南说明如何构建 BandoriPet 的 macOS `.dmg`，**并把首次打开辅助文件一起打进去**，
让没有 Apple 公证的应用也能让普通用户顺利打开。

> 背景：本应用未做 Apple 付费公证（Developer ID + notarization，$99/年），
> 出包走的是 ad-hoc 临时签名。这种包在别人机器上会被 Gatekeeper 拦截，
> 报「已损坏」或「无法验证开发者」。解决办法是随包附带一个清除 quarantine
> 隔离标记的辅助脚本 —— 即本目录下的两个文件。

---

## 需要一起打包的文件

位于 [`installer/macos/`](.)：

| 文件 | 作用 |
|---|---|
| `首次打开修复.command` | 用户双击 → 自动定位 `BandoriPet.app` 并清除 quarantine 标记 |
| `首次运行必读.txt` | 三种解除方法的图文说明（脚本 / 右键打开 / 命令行） |

**这两个文件必须放进 dmg，跟 `.app` 平级。** 不要只发 `.app`。

---

## 架构（Intel / Apple Silicon）

cx_Freeze 只会把**构建机当前架构**的原生 `.so` 打进包里。所以在 Apple Silicon
（arm64）上直接打的包，到 Intel Mac（x86_64）上会报：

```
ImportError: ... (mach-o file, but is an incompatible architecture
              (have 'arm64', need 'x86_64h' or 'x86_64'))
```

cx_Freeze 没有 universal2 模式，因此 **arm64 和 x86_64 要分别出两个 dmg**。
x86_64 包必须用一个能以 x86_64 运行的 Python（通过 Rosetta 的 `arch -x86_64`）来构建。

一次性安装一个 x86_64 的 Python 3.12（任选其一）：

- python.org 的 **universal2** 安装包 → `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`
  （universal2 二进制可经 `arch -x86_64` 跑成 Intel 模式，最省事）
- 或 Intel 工具链下的 pyenv：`arch -x86_64 /bin/bash -c 'pyenv install 3.12.7'`

---

## 完整打包步骤（推荐用脚本，一条命令到底）

[`build_dmg.sh`](build_dmg.sh) 把"建独立 venv → 装依赖（含从源码编译的 lupa）→
`bdist_mac` → 架构自检 → 组 dmg"全包了，并按架构命名产物：

```bash
# Apple Silicon 包（本机即 arm64 时无需额外 Python）
installer/macos/build_dmg.sh arm64

# Intel 包（脚本会自动探测 universal2 / x86_64 的 Python；也可手动指定）
BANDORIPET_PYTHON=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  installer/macos/build_dmg.sh x86_64
```

产物：`BUILD/BandoriPet-<版本>-macos-arm64.dmg` 和 `…-macos-x86_64.dmg`。
脚本内置架构校验：包内任一 `.so/.dylib` 缺目标架构就直接报错停手，
杜绝再发出 issue 里那种"装上打不开"的包。

发布时两个 dmg 都传，发布说明里写明 Intel 用户下 `x86_64`、Apple 芯片下 `arm64`
（`x86_64` 包在 Apple 芯片上也能经 Rosetta 跑，可作通用兜底）。

---

## 手动打包步骤（脚本不可用时的等价流程）

### 1. 构建 .app

```bash
# 在项目根目录、已激活对应架构的 Python 环境的前提下
python setup.py bdist_mac          # arm64
arch -x86_64 python setup.py bdist_mac   # x86_64（须用 x86_64/universal2 的 Python）
```

产物在 `BUILD/` 下，形如 `BUILD/BandoriPet.app`。

### 2. 自查 LuaJIT 是否打进去了（重要）

应用依赖 `lupa.luajit21`（LuaJIT 引擎），漏掉会导致 Live2D 启动崩溃：

```bash
find BUILD/*.app -ipath '*luajit21*'   # 必须有输出
find BUILD/*.app -ipath '*lua5*so'     # 应为空（已在 setup.py 排除多余引擎）
```

第一条没输出就别往下走，检查 `setup.py` 里 `packages` 是否含 `"lupa"`。

接着验证**代码签名是否完整**（关键，否则经 dmg 分发后双击会静默无反应）：

```bash
codesign --verify --deep --strict --verbose=2 BUILD/dist/BandoriPet.app
# 必须看到 "valid on disk" 且 "satisfies its Designated Requirement"
```

> 背景：cx_Freeze 会在加资源符号链接**之前**就签名，破坏封印。`setup.py` 的
> `BuildMacWithResourceLinks._adhoc_resign()` 已在所有文件就位后补一次 ad-hoc
> 重签来修复。若这条验证报 "code has no resources but signature indicates they
> must be present"，说明重签没生效，别出包 —— 手动补一刀：
> `codesign --force --deep --sign - BUILD/dist/BandoriPet.app`

### 3. 组装并生成 dmg（含辅助文件）

```bash
APP=BUILD/BandoriPet.app                 # ← 改成实际产物路径
DMG=BUILD/BandoriPet-3.1.0-macos-arm64.dmg   # ← 输出 dmg 路径（带架构后缀）

STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/BandoriPet.app"
cp installer/macos/首次打开修复.command "$STAGE/"
cp installer/macos/首次运行必读.txt     "$STAGE/"
chmod +x "$STAGE/首次打开修复.command"   # 确保可执行位保留
ln -s /Applications "$STAGE/Applications"   # 拖拽安装快捷方式

hdiutil create -volname "BandoriPet" \
  -srcfolder "$STAGE" -ov -format UDZO "$DMG"

rm -rf "$STAGE"
echo "✓ 已生成 $DMG"
```

用户打开 dmg 后会看到四样东西：
**BandoriPet.app · Applications 快捷方式 · 首次打开修复.command · 首次运行必读.txt**

### 4. 发布前自查 dmg 内容

```bash
hdiutil attach "$DMG" -nobrowse -mountpoint /tmp/bp_dmg
ls -la /tmp/bp_dmg                      # 四个条目都应在
hdiutil detach /tmp/bp_dmg
```

---

## 给用户的使用流程（写进发布说明）

1. 打开 dmg，把 **BandoriPet** 拖到 **Applications**。
2. 双击 dmg 里的 **首次打开修复.command**，首次会提示是否打开脚本 → 点「打开」。
3. 之后正常双击 BandoriPet 启动。

> 脚本自身被下载后也带 quarantine，所以第 2 步那次「是否打开」提示绕不掉，
> 这是 macOS 的安全设计，属正常现象。`首次运行必读.txt` 已对用户说明。

---

## 注意事项

- **`.command` 的可执行位**：`cp` 一般会保留，但 `chmod +x` 那行是保险，别删。
- **文件名用中文**：dmg / HFS+ 对中文文件名兼容良好，无需改英文。
- **改了 app 名/版本号**：记得同步修改上面脚本里的 `APP` / `DMG` 变量，
  以及 `首次打开修复.command` 顶部的 `APP_NAME`（若改了 .app 的名字）。
- **真要做到双击即开**：唯一正途是花 $99 买 Apple Developer Program，
  签 Developer ID 并 notarize。在那之前，本辅助文件方案是免费且可行的替代。
