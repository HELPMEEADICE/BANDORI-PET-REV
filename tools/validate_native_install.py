#!/usr/bin/env python3
"""Validate an installed native BandoriPet tree and run its help smoke test."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def platform_layout(root: Path, platform: str) -> tuple[Path, Path, Path, list[Path]]:
    if platform == "windows":
        executable = root / "BandoriPet.exe"
        renderer = root / "bandori-pet-renderer-rust.exe"
        resources = root
        platform_files = [
            root / "Qt6Core.dll",
            root / "Qt6OpenGL.dll",
            root / "Qt6OpenGLWidgets.dll",
            root / "plugins" / "platforms" / "qwindows.dll",
        ]
    elif platform == "macos":
        bundle = root / "BandoriPet.app" / "Contents"
        executable = bundle / "MacOS" / "BandoriPet"
        renderer = bundle / "MacOS" / "bandori-pet-renderer-rust"
        resources = bundle / "Resources"
        platform_files = [
            bundle / "Frameworks" / "QtCore.framework",
            bundle / "PlugIns" / "platforms" / "libqcocoa.dylib",
        ]
    else:
        executable = root / "bin" / "BandoriPet"
        renderer = root / "bin" / "bandori-pet-renderer-rust"
        resources = root / "share" / "bandoripet"
        platform_files = [root / "share" / "applications" / "bandoripet.desktop"]
    return executable, renderer, resources, platform_files


def validate_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise SystemExit(f"required installed file is missing or empty: {path}")


def validate_tree(root: Path, platform: str) -> tuple[Path, Path]:
    executable, renderer, resources, platform_files = platform_layout(root, platform)
    validate_file(executable)
    validate_file(renderer)
    for path in platform_files:
        if path.suffix == ".framework":
            if not path.is_dir():
                raise SystemExit(f"required installed framework is missing: {path}")
        else:
            validate_file(path)

    required_resources = [
        resources / ".bandoripet-native-package",
        resources / "band.json",
        resources / "outfit.json",
        resources
        / "third_party"
        / "Live2D-v2-Lua"
        / "live2d_moc3_pet_embed.lua",
        resources / "licenses" / "Qt-Fluent-Widgets" / "LICENSE",
    ]
    for path in required_resources:
        validate_file(path)

    python_payloads = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.suffix.casefold() in {".py", ".pyc"}
            or path.name.casefold().startswith("python3")
        )
    ]
    if python_payloads:
        joined = "\n".join(str(path) for path in python_payloads[:20])
        raise SystemExit(f"native install unexpectedly contains Python runtime payloads:\n{joined}")
    return executable, renderer


def smoke(executable: Path, platform: str, expected_output: str) -> None:
    environment = os.environ.copy()
    if platform == "linux":
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    else:
        environment.pop("QT_QPA_PLATFORM", None)
    completed = subprocess.run(
        [str(executable), "--help"],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"native --help smoke test failed with {completed.returncode}:\n{completed.stdout}"
        )
    if expected_output not in completed.stdout:
        raise SystemExit(f"native --help output is incomplete:\n{completed.stdout}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--platform",
        choices=("windows", "macos", "linux"),
        default=(
            "windows"
            if sys.platform == "win32"
            else "macos"
            if sys.platform == "darwin"
            else "linux"
        ),
    )
    parser.add_argument("--skip-smoke", action="store_true")
    arguments = parser.parse_args()

    root = arguments.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"native install root does not exist: {root}")
    executable, renderer = validate_tree(root, arguments.platform)
    if not arguments.skip_smoke:
        smoke(
            executable,
            arguments.platform,
            "BandoriPet Rust + Qt migration shell",
        )
        smoke(
            renderer,
            arguments.platform,
            "Isolated Rust + LuaJIT + Qt pet renderer",
        )
    print(f"validated native {arguments.platform} install: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
