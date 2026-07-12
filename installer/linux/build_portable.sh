#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This script must be run on Linux." >&2
    exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON="${BANDORIPET_PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python was not found: $PYTHON" >&2
    exit 1
fi

normalize_arch() {
    case "${1,,}" in
        amd64|x86_64|x64) printf '%s' "AMD64" ;;
        arm64|aarch64) printf '%s' "ARM64" ;;
        x86|i386|i686) printf '%s' "X86" ;;
        *) return 1 ;;
    esac
}

HOST_ARCH="$(normalize_arch "$(uname -m)")" || {
    echo "Unsupported Linux architecture: $(uname -m)" >&2
    exit 1
}
REQUESTED_ARCH="$(normalize_arch "${1:-$HOST_ARCH}")" || {
    echo "Unsupported requested architecture: ${1:-}" >&2
    exit 1
}
if [[ "$REQUESTED_ARCH" != "$HOST_ARCH" ]]; then
    echo "Cross-architecture packaging is not supported: host=$HOST_ARCH requested=$REQUESTED_ARCH" >&2
    exit 1
fi

VERSION="$("$PYTHON" -c 'import app_info; print(app_info.APP_VERSION)')"
BUILD_ROOT="$ROOT/BUILD"
BUILD_DIR="$BUILD_ROOT/BANDORI-PET-REV-RELEASE-LINUX-$REQUESTED_ARCH"
PACKAGE_NAME="BandoriPet-$VERSION-LINUX-$REQUESTED_ARCH"
ZIP_PATH="$BUILD_ROOT/$PACKAGE_NAME.zip"
CHECKSUM_PATH="$ZIP_PATH.sha256"

mkdir -p "$BUILD_ROOT"
rm -rf -- "$BUILD_DIR"
rm -f -- "$ZIP_PATH" "$CHECKSUM_PATH"

echo "Building BandoriPet $VERSION for Linux $REQUESTED_ARCH"
"$PYTHON" setup.py build

[[ -d "$BUILD_DIR" ]] || {
    echo "Build directory was not created: $BUILD_DIR" >&2
    exit 1
}

required_executables=(
    BandoriPet
    pet_process
    radial_menu_process
    settings_process
    chat_process
    bandori-ai-event
    bandori-codex-runner
)
for name in "${required_executables[@]}"; do
    [[ -f "$BUILD_DIR/$name" && -x "$BUILD_DIR/$name" ]] || {
        echo "Required executable is missing or not executable: $name" >&2
        exit 1
    }
done

required_resources=(
    .bandoripet-managed-files
    audio_reference
    band.json
    band_logo
    characters
    events
    lang
    outfit.json
    pixels
)
for name in "${required_resources[@]}"; do
    [[ -e "$BUILD_DIR/$name" ]] || {
        echo "Required packaged resource is missing: $name" >&2
        exit 1
    }
done

protected_entries=(config.json data.db data.db-shm data.db-wal chat_attachments)
for name in "${protected_entries[@]}"; do
    [[ ! -e "$BUILD_DIR/$name" ]] || {
        echo "User data must not be included in a release package: $name" >&2
        exit 1
    }
done

[[ -d "$BUILD_DIR/models" ]] || {
    echo "The empty models directory is missing from the build." >&2
    exit 1
}
if find "$BUILD_DIR/models" -mindepth 1 -print -quit | grep -q .; then
    echo "The release models directory must be empty." >&2
    exit 1
fi

"$PYTHON" - "$BUILD_DIR" "$ZIP_PATH" "$PACKAGE_NAME" <<'PY'
import hashlib
import os
import sys
import zipfile
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])
wrapper = sys.argv[3]

with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for current, directories, files in os.walk(source):
        directories.sort()
        files.sort()
        current_path = Path(current)
        relative_dir = current_path.relative_to(source)
        archive_dir = Path(wrapper, relative_dir).as_posix().rstrip("/") + "/"
        info = zipfile.ZipInfo(archive_dir)
        info.external_attr = (0o40755 << 16) | 0x10
        archive.writestr(info, b"")
        for filename in files:
            path = current_path / filename
            archive.write(path, Path(wrapper, path.relative_to(source)).as_posix())

digest = hashlib.sha256(output.read_bytes()).hexdigest()
checksum = output.with_name(output.name + ".sha256")
checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
print(f"Created: {output}")
print(f"SHA-256: {digest}")
print(f"Checksum: {checksum}")
PY

[[ -s "$ZIP_PATH" && -s "$CHECKSUM_PATH" ]] || {
    echo "Portable package or checksum was not created." >&2
    exit 1
}
