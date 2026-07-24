#!/usr/bin/env bash
# Install BandoriPet's source-runtime dependencies into the active macOS venv.
#
# Usage:
#   source venv/bin/activate
#   bash installer/macos/install_source_dependencies.sh
#
# BANDORIPET_PYTHON may be set to an explicit virtual-environment interpreter.
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This installer is only for macOS." >&2
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  echo "Do not run this installer with sudo; activate a user-owned venv first." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [ -n "${BANDORIPET_PYTHON:-}" ]; then
  PYTHON="$BANDORIPET_PYTHON"
elif [ -n "${VIRTUAL_ENV:-}" ]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
else
  echo "No active Python virtual environment was found." >&2
  echo "Run: python3 -m venv venv && source venv/bin/activate" >&2
  exit 1
fi

[ -x "$PYTHON" ] || {
  echo "Python interpreter is not executable: $PYTHON" >&2
  exit 1
}

"$PYTHON" - <<'PY'
import platform
import sys

if sys.prefix == sys.base_prefix:
    raise SystemExit("The selected Python is not inside a virtual environment.")
if sys.version_info < (3, 10):
    raise SystemExit("BandoriPet requires Python 3.10 or newer.")
if platform.system() != "Darwin":
    raise SystemExit("The selected Python is not running on macOS.")
print(f"▶ Python={sys.executable}")
print(f"▶ Version={platform.python_version()}  Architecture={platform.machine()}")
PY

ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
case "$ARCH" in
  arm64|x86_64) ;;
  *) echo "Unsupported Python architecture: $ARCH" >&2; exit 1 ;;
esac

if ! xcrun --find clang >/dev/null 2>&1; then
  echo "Apple Command Line Tools are required." >&2
  echo "Install them with: xcode-select --install" >&2
  exit 1
fi

echo "▶ Installing Python dependencies into the active venv"
"$PYTHON" -m pip install --upgrade pip wheel setuptools Cython
"$PYTHON" -m pip install -r requirements.txt

# PyPI macOS wheels do not provide the lupa.luajit21 module required by the
# Live2D runtime. Build lupa again from source after enabling bundled LuaJIT
# 2.1 and excluding LuaJIT 2.0 on Apple Silicon.
WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bandoripet-lupa.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "▶ Downloading lupa source"
"$PYTHON" -m pip download lupa --no-binary lupa --no-deps -d "$WORK_DIR"
shopt -s nullglob
LUPA_ARCHIVES=("$WORK_DIR"/lupa-*.tar.gz)
shopt -u nullglob
[ "${#LUPA_ARCHIVES[@]}" -eq 1 ] || {
  echo "Unable to find the downloaded lupa source archive." >&2
  exit 1
}
LUPA_TGZ="${LUPA_ARCHIVES[0]}"

tar xzf "$LUPA_TGZ" -C "$WORK_DIR"
shopt -s nullglob
LUPA_DIRS=("$WORK_DIR"/lupa-*/)
shopt -u nullglob
[ "${#LUPA_DIRS[@]}" -eq 1 ] || {
  echo "Unable to find the extracted lupa source directory." >&2
  exit 1
}
LUPA_DIR="${LUPA_DIRS[0]%/}"

echo "▶ Enabling bundled LuaJIT 2.1 for macOS"
"$PYTHON" - "$LUPA_DIR/setup.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
replacements = [
    (
        "or (platform == 'darwin' and 'luajit' in os.path.basename(lua_bundle_path.rstrip(os.sep)))",
        "or False  # patched by BandoriPet: allow bundled LuaJIT on macOS",
        "macOS LuaJIT exclusion",
    ),
    (
        "or (get_machine().lower() in (\"aarch64\", \"arm64\") and 'luajit20' in os.path.basename(lua_bundle_path.rstrip(os.sep)))",
        "or ('luajit20' in os.path.basename(lua_bundle_path.rstrip(os.sep)))  # patched by BandoriPet: require LuaJIT 2.1",
        "Apple Silicon LuaJIT 2.0 selection",
    ),
]
for needle, replacement, description in replacements:
    if needle not in source:
        raise SystemExit(
            f"Could not patch lupa's {description}; its build layout may have changed."
        )
    source = source.replace(needle, replacement)
path.write_text(source, encoding="utf-8")
PY

echo "▶ Building and installing lupa.luajit21 for $ARCH"
MACOSX_DEPLOYMENT_TARGET=10.13 \
ARCHFLAGS="-arch $ARCH" \
CFLAGS="-arch $ARCH ${CFLAGS:-}" \
LDFLAGS="-arch $ARCH ${LDFLAGS:-}" \
"$PYTHON" -m pip install \
  --force-reinstall --no-build-isolation "$LUPA_DIR"

echo "▶ Verifying LuaJIT 2.1 and FFI"
"$PYTHON" - <<'PY'
from lupa.luajit21 import LuaRuntime

lua = LuaRuntime()
lua.execute('assert(require("ffi"))')
print("  OK:", lua.eval("jit.version"))
PY

echo
echo "Source dependencies are ready. Start BandoriPet with:"
echo "  $PYTHON main.py"
