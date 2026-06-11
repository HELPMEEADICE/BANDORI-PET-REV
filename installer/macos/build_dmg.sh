#!/usr/bin/env bash
# 构建 BandoriPet 的 macOS .app 并打包成 .dmg（按架构区分）。
#
# 用法:
#   installer/macos/build_dmg.sh [arm64|x86_64]
#
# 不带参数时按当前机器架构构建。x86_64（Intel）包必须在能以 x86_64 运行的
# Python 上构建 —— cx_Freeze 只会打包"构建机当前架构"的原生 .so，所以在
# Apple Silicon 上直接打出来的包在 Intel Mac 上会报
#   "incompatible architecture (have 'arm64', need 'x86_64')"。
#
# 跨架构构建（在 arm64 上打 x86_64）需要一个 universal2 / x86_64 的 Python，
# 通过 `arch -x86_64` 运行。脚本会自动探测常见位置，也可用环境变量指定:
#   BANDORIPET_PYTHON=/path/to/python  installer/macos/build_dmg.sh x86_64
#
# 推荐安装一个 x86_64 Python 3.12 的两种方式:
#   1) python.org 的 universal2 安装包 →
#        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3
#   2) pyenv（Intel 工具链）:
#        arch -x86_64 /bin/bash -c 'pyenv install 3.12.7'   # 需 x86_64 homebrew 依赖
set -euo pipefail

ARCH="${1:-$(uname -m)}"
case "$ARCH" in
  arm64|x86_64) ;;
  intel|amd64) ARCH=x86_64 ;;
  *) echo "不支持的架构: $ARCH（用 arm64 或 x86_64）" >&2; exit 1 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

ARCHRUN=(arch "-$ARCH")

# ---------------------------------------------------------------------------
# 1. 选定能以目标架构运行的解释器
# ---------------------------------------------------------------------------
runs_as_target() {
  # $1 = python 可执行文件；要求能在 arch -$ARCH 下跑且自报 machine == $ARCH
  local py="$1" got
  [ -x "$py" ] || command -v "$py" >/dev/null 2>&1 || return 1
  got="$("${ARCHRUN[@]}" "$py" -c 'import platform;print(platform.machine())' 2>/dev/null)" || return 1
  [ "$got" = "$ARCH" ]
}

PYTHON="${BANDORIPET_PYTHON:-}"
if [ -n "$PYTHON" ]; then
  runs_as_target "$PYTHON" || {
    echo "BANDORIPET_PYTHON=$PYTHON 无法以 $ARCH 运行" >&2; exit 1; }
else
  candidates=()
  if [ "$ARCH" = "$(uname -m)" ]; then
    candidates+=("$(command -v python3 || true)")
  fi
  # python.org framework（universal2），版本号倒序优先取高版本
  while IFS= read -r p; do candidates+=("$p"); done < <(
    ls -d /Library/Frameworks/Python.framework/Versions/3.*/bin/python3 2>/dev/null | sort -rV)
  candidates+=(/usr/local/bin/python3)   # Intel homebrew
  candidates+=(/usr/bin/python3)         # 系统自带 universal2（较旧）
  for p in "${candidates[@]}"; do
    [ -n "$p" ] || continue
    if runs_as_target "$p"; then PYTHON="$p"; break; fi
  done
  [ -n "$PYTHON" ] || {
    echo "找不到能以 $ARCH 运行的 Python。" >&2
    echo "请装一个 x86_64/universal2 的 Python 3.12 并用 BANDORIPET_PYTHON 指定，详见脚本顶部说明。" >&2
    exit 1; }
fi

VERSION="$("${ARCHRUN[@]}" "$PYTHON" -c 'import sys;sys.path.insert(0,".");import app_info;print(app_info.APP_VERSION)')"
PYVER="$("${ARCHRUN[@]}" "$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
echo "▶ 架构=$ARCH  Python=$PYTHON (3.x=$PYVER)  版本=$VERSION"

# ---------------------------------------------------------------------------
# 2. 为该架构建独立 venv，安装依赖（含从源码编译、带 LuaJIT FFI 的 lupa）
# ---------------------------------------------------------------------------
VENV="$ROOT/BUILD/venv-$ARCH"
echo "▶ 重建虚拟环境 $VENV"
rm -rf "$VENV"
"${ARCHRUN[@]}" "$PYTHON" -m venv "$VENV"
VPY="$VENV/bin/python"

"${ARCHRUN[@]}" "$VPY" -m pip install --upgrade pip wheel setuptools Cython >/dev/null
echo "▶ 安装依赖（requirements.txt + cx_Freeze）"
"${ARCHRUN[@]}" "$VPY" -m pip install -r requirements.txt cx_Freeze

# lupa：本项目需要 `lupa.luajit21`（LuaJIT 引擎，带 FFI），但：
#   - PyPI 的预编 wheel 只含 lua5.1~5.5，没有 luajit21；
#   - lupa 源码在 macOS 上**硬编码跳过**内置 LuaJIT
#     （setup.py 里 `platform == 'darwin' and 'luajit' in ...`），
#     所以 `--no-binary lupa` 直接装也得不到 luajit21。
# 因此这里下 lupa 源码、去掉那一行 darwin 跳过，再从源码编译，
# 让它把内置的 LuaJIT 2.1 一起按 $ARCH 编进来（自带 FFI、静态自包含、无外部 lua 依赖）。
echo "▶ 从源码编译 lupa（打补丁启用内置 LuaJIT 2.1，按 $ARCH 编译）"
LUPA_SRC="$ROOT/BUILD/lupa-src-$ARCH"
rm -rf "$LUPA_SRC"; mkdir -p "$LUPA_SRC"
"${ARCHRUN[@]}" "$VPY" -m pip download lupa --no-binary lupa --no-deps -d "$LUPA_SRC" >/dev/null
LUPA_TGZ="$(ls "$LUPA_SRC"/lupa-*.tar.gz | head -1)"
tar xzf "$LUPA_TGZ" -C "$LUPA_SRC"
LUPA_DIR="$(ls -d "$LUPA_SRC"/lupa-*/ | head -1)"
"${ARCHRUN[@]}" "$VPY" - "$LUPA_DIR/setup.py" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
needle = "or (platform == 'darwin' and 'luajit' in os.path.basename(lua_bundle_path.rstrip(os.sep)))"
if needle not in s:
    sys.exit("lupa setup.py 的 darwin-luajit 跳过行未找到，lupa 版本可能已变，请检查补丁。")
open(p, "w").write(s.replace(needle, "or False  # patched by build_dmg.sh: allow bundled LuaJIT on macOS"))
print("  已为 lupa 去掉 macOS 跳过内置 LuaJIT 的逻辑")
PY
MACOSX_DEPLOYMENT_TARGET=10.13 "${ARCHRUN[@]}" "$VPY" -m pip install \
  --force-reinstall --no-build-isolation "$LUPA_DIR"

echo "▶ 复核 lupa.luajit21 可用"
"${ARCHRUN[@]}" "$VPY" -c "import lupa.luajit21 as lj; print('  luajit21 OK:', lj.LuaRuntime().eval('jit.version'))"

# ---------------------------------------------------------------------------
# 3. 构建 .app
# ---------------------------------------------------------------------------
echo "▶ 清理旧产物并构建 .app"
rm -rf "$ROOT/BUILD/BandoriPet.app" "$ROOT/BUILD/dist"
MACOSX_DEPLOYMENT_TARGET=10.13 "${ARCHRUN[@]}" "$VPY" setup.py bdist_mac

APP="$ROOT/BUILD/BandoriPet.app"
[ -d "$APP" ] || APP="$ROOT/BUILD/dist/BandoriPet.app"
[ -d "$APP" ] || { echo "构建失败：找不到 BandoriPet.app" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 4. 架构自检（守住 issue 里那个 bug，绝不静默出错包）
# ---------------------------------------------------------------------------
echo "▶ 校验包内原生二进制都含 $ARCH"
bad=0
while IFS= read -r f; do
  if ! lipo -archs "$f" 2>/dev/null | tr ' ' '\n' | grep -qx "$ARCH"; then
    echo "  ✗ 缺 $ARCH: ${f#$APP/}"; bad=$((bad+1))
  fi
done < <(find "$APP" \( -name '*.so' -o -name '*.dylib' \))
if [ "$bad" -ne 0 ]; then
  echo "有 $bad 个二进制缺 $ARCH 架构，停止打包。" >&2
  exit 1
fi
# LuaJIT 自查（漏了会导致 Live2D 启动崩溃）
find "$APP" -ipath '*luajit21*' | grep -q . || {
  echo "包内找不到 lupa.luajit21，停止打包。" >&2; exit 1; }
codesign --verify --deep --strict "$APP" 2>/dev/null \
  || echo "  ⚠ codesign 校验未通过，发布前请手动 ad-hoc 重签（见打包指南）"

# ---------------------------------------------------------------------------
# 5. 组装 dmg（含首次打开辅助文件 + Applications 快捷方式）
# ---------------------------------------------------------------------------
DMG="$ROOT/BUILD/BandoriPet-${VERSION}-macos-${ARCH}.dmg"
echo "▶ 组装 $DMG"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/BandoriPet.app"
cp "$ROOT/installer/macos/首次打开修复.command" "$STAGE/"
cp "$ROOT/installer/macos/首次运行必读.txt" "$STAGE/"
chmod +x "$STAGE/首次打开修复.command"
ln -s /Applications "$STAGE/Applications"

rm -f "$DMG"
hdiutil create -volname "BandoriPet" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
echo "✓ 完成: $DMG"
