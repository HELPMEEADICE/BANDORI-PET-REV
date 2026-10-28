"""Validate frozen builds and collect the exact installer set for a release."""

import argparse
import hashlib
import os
import platform
import re
import shutil
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bandori_core.app_info import APP_VERSION  # noqa: E402

TARGETS = ("windows", "linux", "macos")
ARCHES = ("x86_64", "aarch64")
EXECUTABLES = (
    "BandoriPet", "pet_process", "radial_menu_process", "settings_process",
    "chat_process", "plugin_worker", "bandori-ai-event", "bandori-codex-runner",
)
RESOURCES = (
    ".bandoripet-managed-files", "audio_reference", "band.json", "band_logo",
    "characters", "events", "lang", "outfit.json", "pixels",
)
USER_DATA = ("config.json", "data.db", "data.db-shm", "data.db-wal", "chat_attachments")


def validate_version(version=APP_VERSION, tag=None):
    # MSI accepts three numeric components; all outputs share this version.
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"APP_VERSION must be major.minor.patch: {version!r}")
    major, minor, patch = map(int, version.split("."))
    if major > 255 or minor > 255 or patch > 65535:
        raise ValueError(f"APP_VERSION exceeds Windows Installer limits: {version}")
    if tag is not None and tag not in (version, f"v{version}"):
        raise ValueError(f"Release tag {tag!r} does not match APP_VERSION={version}")
    return version


def installer_names(target, arch, version=APP_VERSION):
    prefix = f"BandoriPet-{version}-"
    if target == "windows":
        suffix = "win-x86_64" if arch == "x86_64" else "win-arm64"
        return [prefix + suffix + ext for ext in (".zip", ".msi", "-setup.exe")]
    if target == "linux":
        return [prefix + f"linux-{arch}" + ext for ext in (".AppImage", ".deb", ".rpm", ".tar.gz")]
    mac_arch = "x86_64" if arch == "x86_64" else "arm64"
    return [prefix + f"macos-{mac_arch}" + ext for ext in (".dmg", ".zip")]


def validate_build(directory, target, arch):
    for name in (*RESOURCES, "models"):
        if not (directory / name).exists():
            raise ValueError(f"Missing frozen resource: {directory / name}")
    for name in USER_DATA:
        if (directory / name).exists():
            raise ValueError(f"User data must not be packaged: {name}")
    if any((directory / "models").iterdir()):
        raise ValueError("The packaged models directory must be empty")
    for name in EXECUTABLES:
        path = directory / (name + (".exe" if target == "windows" else ""))
        with path.open("rb") as binary:
            header = binary.read(64)
            if target == "windows":
                if header[:2] != b"MZ":
                    raise ValueError(f"Invalid Windows executable: {path}")
                binary.seek(struct.unpack_from("<I", header, 60)[0])
                signature, machine = struct.unpack("<4sH", binary.read(6))
                expected = 0x8664 if arch == "x86_64" else 0xAA64
                if signature != b"PE\0\0" or machine != expected:
                    raise ValueError(f"Wrong executable architecture: {path}")
            elif target == "linux":
                expected = 62 if arch == "x86_64" else 183
                if header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != expected:
                    raise ValueError(f"Wrong ELF architecture: {path}")
                if not os.access(path, os.X_OK):
                    raise ValueError(f"Missing executable permission: {path}")
    # The standalone LuaJIT compiler and lupa must agree on the bytecode format.
    bytecode_files = list(directory.rglob("*.ljbc"))
    if bytecode_files:
        from lupa.luajit21 import LuaRuntime

        lua = LuaRuntime(encoding=None)
        check = lua.eval(b"function(s) local f,e = loadstring(s); assert(f,e) end")
        for path in bytecode_files:
            check(path.read_bytes())


def write_checksums(directory, names, filename):
    lines = []
    for name in sorted(names):
        path = directory / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty installer: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        lines.append(f"{digest.hexdigest()}  {name}\n")
    (directory / filename).write_text("".join(lines), encoding="ascii")


def package_windows(arch, output):
    machine = platform.machine().lower()
    if machine not in ({"amd64", "x86_64"} if arch == "x86_64" else {"arm64", "aarch64"}):
        raise ValueError(f"Native build required: {machine} != {arch}")
    build = ROOT / "BUILD" / f"BANDORI-PET-REV-RELEASE-WIN-{'AMD64' if arch == 'x86_64' else 'ARM64'}"
    validate_build(build, "windows", arch)
    names = installer_names("windows", arch)
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output / names[0], "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(build.rglob("*")):
            archive.write(path, path.relative_to(build).as_posix())
    # Build tools produce their own filenames; publish a consistent architecture suffix.
    msi_arch = "win64" if arch == "x86_64" else "win-arm64"
    inno_arch = "amd64" if arch == "x86_64" else "arm64"
    shutil.copy2(ROOT / "BUILD" / f"BandoriPet-{APP_VERSION}-{msi_arch}.msi", output / names[1])
    shutil.copy2(ROOT / "BUILD" / f"BandoriPet-{APP_VERSION}-win{inno_arch}-setup.exe", output / names[2])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "validate-build", "windows", "checksums", "collect"))
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--arch", choices=ARCHES)
    parser.add_argument("--directory", type=Path, default=ROOT / "BUILD" / "release")
    args = parser.parse_args()
    validate_version(tag=os.environ.get("RELEASE_TAG") or None)
    if args.command == "version":
        print(APP_VERSION)
        return
    if args.command == "collect":
        names = [name for target in TARGETS for arch in ARCHES for name in installer_names(target, arch)]
        write_checksums(args.directory, names, "SHA256SUMS.txt")
        print(f"Verified {len(names)} installers for {APP_VERSION}")
        return
    if args.target is None or args.arch is None:
        parser.error("--target and --arch are required for this command")
    if args.command == "validate-build":
        validate_build(args.directory, args.target, args.arch)
        return
    if args.command == "windows":
        if args.target != "windows":
            parser.error("windows requires --target windows")
        package_windows(args.arch, args.directory)
    write_checksums(
        args.directory, installer_names(args.target, args.arch),
        f"SHA256SUMS-{args.target}-{args.arch}.txt",
    )


if __name__ == "__main__":
    main()
