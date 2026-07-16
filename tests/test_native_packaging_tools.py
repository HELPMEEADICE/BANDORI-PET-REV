from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def touch(path: Path, content: bytes = b"native") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def create_install_tree(root: Path, platform: str) -> None:
    if platform == "windows":
        resources = root
        files = [
            root / "BandoriPet.exe",
            root / "bandori-pet-renderer-rust.exe",
            root / "Qt6Core.dll",
            root / "platforms" / "qwindows.dll",
        ]
    elif platform == "macos":
        contents = root / "BandoriPet.app" / "Contents"
        resources = contents / "Resources"
        files = [
            contents / "MacOS" / "BandoriPet",
            contents / "MacOS" / "bandori-pet-renderer-rust",
            contents / "PlugIns" / "platforms" / "libqcocoa.dylib",
        ]
        (contents / "Frameworks" / "QtCore.framework").mkdir(parents=True)
    else:
        resources = root / "share" / "bandoripet"
        files = [
            root / "bin" / "BandoriPet",
            root / "bin" / "bandori-pet-renderer-rust",
            root / "share" / "applications" / "bandoripet.desktop",
        ]
    for path in files:
        touch(path)
    for path in [
        resources / ".bandoripet-native-package",
        resources / "band.json",
        resources / "outfit.json",
        resources
        / "third_party"
        / "Live2D-v2-Lua"
        / "live2d_moc3_pet_embed.lua",
        resources / "licenses" / "Qt-Fluent-Widgets" / "LICENSE",
    ]:
        touch(path)


@pytest.mark.parametrize("platform", ["windows", "macos", "linux"])
def test_validate_native_install_accepts_each_platform_layout(tmp_path: Path, platform: str):
    create_install_tree(tmp_path, platform)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_native_install.py"),
            str(tmp_path),
            "--platform",
            platform,
            "--skip-smoke",
        ],
        check=True,
    )


def test_validate_native_install_rejects_python_payload(tmp_path: Path):
    create_install_tree(tmp_path, "linux")
    touch(tmp_path / "share" / "bandoripet" / "legacy.py")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_native_install.py"),
            str(tmp_path),
            "--platform",
            "linux",
            "--skip-smoke",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "Python runtime payloads" in completed.stderr


def test_collect_native_packages_filters_and_hashes_cpack_outputs(tmp_path: Path):
    build_root = tmp_path / "build"
    output_root = tmp_path / "output"
    build_root.mkdir()
    packages = {
        "BandoriPet-3.1.4-Linux-x86_64.tar.gz": b"tar",
        "BandoriPet-3.1.4-Linux-x86_64.deb": b"deb",
    }
    for name, content in packages.items():
        touch(build_root / name, content)
    touch(build_root / "BandoriPet", b"executable")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "collect_native_packages.py"),
            str(build_root),
            str(output_root),
        ],
        check=True,
    )

    assert {path.name for path in output_root.iterdir()} == {*packages, "SHA256SUMS"}
    checksum_lines = (output_root / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert checksum_lines == [
        f"{hashlib.sha256(content).hexdigest()}  {name}"
        for name, content in sorted(packages.items())
    ]
