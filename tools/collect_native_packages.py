#!/usr/bin/env python3
"""Collect CPack outputs and write deterministic SHA-256 checksums."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil


PACKAGE_SUFFIXES = (".zip", ".exe", ".dmg", ".tar.gz", ".deb")


def is_package(path: Path) -> bool:
    return (
        path.is_file()
        and path.name.startswith("BandoriPet-")
        and any(path.name.endswith(suffix) for suffix in PACKAGE_SUFFIXES)
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("build_root", type=Path)
    parser.add_argument("output_root", type=Path)
    arguments = parser.parse_args()

    build_root = arguments.build_root.resolve()
    output_root = arguments.output_root.resolve()
    packages = sorted(path for path in build_root.iterdir() if is_package(path))
    if not packages:
        raise SystemExit(f"no BandoriPet CPack outputs found under {build_root}")

    output_root.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for package in packages:
        destination = output_root / package.name
        shutil.copy2(package, destination)
        copied.append(destination)

    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in copied)
    (output_root / "SHA256SUMS").write_text(checksums, encoding="utf-8", newline="\n")
    print(f"collected {len(copied)} native packages in {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
