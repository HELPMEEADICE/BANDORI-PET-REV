#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PYTHON="${BANDORIPET_PYTHON:-python3}"
BUILD_DIR="${BANDORIPET_WAYLAND_BUILD_DIR:-$ROOT/.build/wayland-layer-shell}"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This bridge can only be built on Linux." >&2
    exit 1
fi

QT_VERSION="$("$PYTHON" -c 'from PySide6.QtCore import qVersion; print(qVersion())')"
PYSIDE_CMAKE="$("$PYTHON" -c 'import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).resolve().parent / "lib" / "cmake")')"
SHIBOKEN_CMAKE="$("$PYTHON" -c 'import pathlib, shiboken6; print(pathlib.Path(shiboken6.__file__).resolve().parent / "lib" / "cmake")')"

cmake \
    -S "$ROOT/native/wayland_layer_shell" \
    -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBANDORIPET_QT_VERSION="$QT_VERSION" \
    -DPython3_EXECUTABLE="$("$PYTHON" -c 'import sys; print(sys.executable)')" \
    -DCMAKE_PREFIX_PATH="$PYSIDE_CMAKE;$SHIBOKEN_CMAKE;${CMAKE_PREFIX_PATH:-}"
cmake --build "$BUILD_DIR" --config Release --parallel

mkdir -p "$ROOT/wayland/_native"
find "$BUILD_DIR/python" -maxdepth 1 -type f -name '_layer_shell*.so' -exec cp -f {} "$ROOT/wayland/_native/" \;

if ! find "$ROOT/wayland/_native" -maxdepth 1 -type f -name '_layer_shell*.so' -print -quit | grep -q .; then
    echo "The _layer_shell extension was not produced." >&2
    exit 1
fi

"$PYTHON" -c 'from wayland.native_bridge import LayerShellBridge; s=LayerShellBridge().status; print(s); raise SystemExit(0 if s.available else 1)'
