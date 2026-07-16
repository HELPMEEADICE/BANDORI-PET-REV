"""Small source-tree launcher for the native BandoriPet application.

The installed application starts ``BandoriPet`` directly.  This module keeps
``python main.py`` useful for source checkouts without importing PySide unless
the user explicitly requests the compatibility runtime.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Mapping, MutableSequence, Sequence


PYTHON_FALLBACK_FLAG = "--python-legacy"
PYTHON_FALLBACK_ENV = "BANDORI_PET_PYTHON_FALLBACK"
NATIVE_APP_ENV = "BANDORI_PET_NATIVE_APP_PATH"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def python_fallback_requested(
    argv: Sequence[str],
    environ: Mapping[str, str] | None = None,
) -> bool:
    environment = os.environ if environ is None else environ
    return (
        PYTHON_FALLBACK_FLAG in argv[1:]
        or environment.get(PYTHON_FALLBACK_ENV, "").strip().lower() in _TRUE_VALUES
    )


def prepare_python_fallback(argv: MutableSequence[str]) -> None:
    """Remove launcher-only flags before the legacy Qt application sees them."""
    while PYTHON_FALLBACK_FLAG in argv[1:]:
        argv.remove(PYTHON_FALLBACK_FLAG)


def native_application_candidates(project_root: Path) -> tuple[Path, ...]:
    root = project_root.resolve()
    if sys.platform == "win32":
        names = (Path("BandoriPet.exe"),)
    elif sys.platform == "darwin":
        names = (
            Path("BandoriPet.app/Contents/MacOS/BandoriPet"),
            Path("BandoriPet"),
        )
    else:
        names = (Path("BandoriPet"),)

    build_roots = (
        root,
        root / "build-rust",
        root / "build-rust" / "native" / "qt",
        root / "build-rust" / "native" / "qt" / "Release",
        root / "build-rust" / "native" / "qt" / "RelWithDebInfo",
        root / "build-rust" / "native" / "qt" / "Debug",
        root / "build-rust" / "Release",
        root / "build-rust" / "RelWithDebInfo",
        root / "build-rust" / "Debug",
    )
    return tuple(directory / name for directory in build_roots for name in names)


def _is_launchable(path: Path) -> bool:
    if not path.is_file():
        return False
    return os.name == "nt" or os.access(path, os.X_OK)


def find_native_application(
    project_root: Path,
    environ: Mapping[str, str] | None = None,
) -> tuple[Path | None, str]:
    environment = os.environ if environ is None else environ
    explicit = environment.get(NATIVE_APP_ENV, "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if _is_launchable(path):
            return path, ""
        return None, f"{NATIVE_APP_ENV} does not point to a launchable file: {path}"

    current_executable = Path(sys.executable).resolve()
    for candidate in native_application_candidates(project_root):
        resolved = candidate.resolve()
        if resolved == current_executable:
            continue
        if _is_launchable(resolved):
            return resolved, ""
    return None, (
        "Native BandoriPet executable was not found. Build it with "
        "`cmake -S . -B build-rust` and "
        "`cmake --build build-rust --config Release`, or set "
        f"{NATIVE_APP_ENV}. To run the temporary Python compatibility runtime, "
        f"pass {PYTHON_FALLBACK_FLAG}."
    )


def launch_native_application(
    argv: Sequence[str],
    project_root: Path,
    environ: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    executable, error = find_native_application(project_root, environ)
    if executable is None:
        print(error, file=sys.stderr)
        return 2
    try:
        completed = runner(
            [str(executable), *argv[1:]],
            cwd=str(project_root.resolve()),
            check=False,
        )
    except OSError as exc:
        print(f"Could not start native BandoriPet: {exc}", file=sys.stderr)
        return 126
    return int(completed.returncode)


def dispatch_source_entrypoint(
    argv: MutableSequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> int | None:
    """Return a native exit code, or ``None`` for explicit Python fallback."""
    arguments = sys.argv if argv is None else argv
    if python_fallback_requested(arguments, environ):
        prepare_python_fallback(arguments)
        return None
    root = Path(__file__).resolve().parent if project_root is None else project_root
    return launch_native_application(arguments, root, environ)
