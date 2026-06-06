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

## 完整打包步骤

### 1. 构建 .app

```bash
# 在项目根目录、已激活 Python 环境的前提下
python setup.py bdist_mac
```

产物在 `BUILD/` 下，形如 `BUILD/bandoripet-<版本>.app`。

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
APP=BUILD/bandoripet-3.0.6.app          # ← 改成实际产物路径
DMG=BUILD/bandoripet-3.0.6.dmg          # ← 输出 dmg 路径

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
