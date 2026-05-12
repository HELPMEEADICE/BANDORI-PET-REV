import platform
import shutil
import subprocess
import sys
from pathlib import Path

from cx_Freeze import Executable, setup
from cx_Freeze.command.build_exe import build_exe


BASE_DIR = Path(__file__).resolve().parent
BYTECODE_BUILD_DIR = BASE_DIR / "BUILD" / ".luajit-bytecode"

import PySide6.QtCore  # noqa: E402,F401
import PySide6.QtGui  # noqa: E402,F401
import PySide6.QtOpenGLWidgets  # noqa: E402,F401
import PySide6.QtWidgets  # noqa: E402,F401


class BuildExeWithEmptyModels(build_exe):
    def run(self):
        super().run()
        models_dir = Path(self.build_exe) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)


def include_if_exists(path: str) -> tuple[str, str] | None:
    src = BASE_DIR / path
    if not src.exists():
        return None
    return str(src), path


def _luajit_executable() -> str:
    luajit = shutil.which("luajit")
    if luajit:
        return luajit
    raise RuntimeError("luajit executable was not found in PATH")


def _compiled_lua_include(path: str, dest_path: str | None = None) -> tuple[str, str] | None:
    src = BASE_DIR / path
    if not src.exists():
        return None

    relative = Path(dest_path or path)
    compiled_dest = relative.with_suffix(".ljbc")
    compiled_src = BYTECODE_BUILD_DIR / compiled_dest
    compiled_src.parent.mkdir(parents=True, exist_ok=True)

    if not compiled_src.exists() or src.stat().st_mtime_ns > compiled_src.stat().st_mtime_ns:
        subprocess.run(
            [_luajit_executable(), "-b", str(src), str(compiled_src)],
            check=True,
            cwd=BASE_DIR,
        )

    return str(compiled_src), compiled_dest.as_posix()


def _live2d_lua_include_files() -> list[tuple[str, str]]:
    root = BASE_DIR / "third_party" / "Live2D-v2-Lua"
    if not root.is_dir():
        return []
    exclude_dirs = {".git", "examples", "resources", "test-data"}
    exclude_files = {
        "render_frames.lua",
        "simple.lua",
        "main.lua",
    }
    result = []
    for entry in sorted(root.rglob("*")):
        if any(p.name in exclude_dirs for p in entry.parents):
            continue
        if not entry.is_file():
            continue
        rel = entry.relative_to(root)
        if rel.name in exclude_files and rel.parent == Path("."):
            continue
        dest = "third_party/Live2D-v2-Lua/" + rel.as_posix()
        if entry.suffix == ".lua":
            compiled = _compiled_lua_include(str(entry.relative_to(BASE_DIR)), dest)
            if compiled is not None:
                result.append(compiled)
            continue
        result.append((str(entry), dest))
    return result


def release_platform_name() -> str:
    if sys.platform == "win32":
        return "WIN"
    if sys.platform == "darwin":
        return "MACOS"
    if sys.platform.startswith("linux"):
        return "LINUX"
    return sys.platform.upper().replace("-", "_")


def release_arch_name() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "AMD64"
    if machine in {"arm64", "aarch64"}:
        return "ARM64"
    if machine in {"x86", "i386", "i686"}:
        return "X86"
    return machine.upper().replace("-", "_")


include_files = [
    include_if_exists("logo.ico"),
    include_if_exists("band.json"),
    include_if_exists("outfit.json"),
    _compiled_lua_include("custom_hit_area_state.lua"),
    include_if_exists("lang"),
    include_if_exists("band_logo"),
    include_if_exists("characters"),
    include_if_exists("pixels"),
]

include_files.extend(_live2d_lua_include_files())
include_files = [item for item in include_files if item is not None]

build_exe_options = {
    "build_exe": str(BASE_DIR / "BUILD" / f"BANDORI-PET-REV-RELEASE-{release_platform_name()}-{release_arch_name()}"),
    "include_files": include_files,
    "packages": [
        "OpenGL",
        "PIL",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtWidgets",
        "darkdetect",
        "lupa.luajit21",
        "qfluentwidgets",
        "sqlite3",
    ],
    "excludes": ["PyQt5", "PyQt6", "PySide2", "tkinter"],
    "include_msvcr": True,
    
    "zip_include_packages": ["*"], 
    "zip_exclude_packages": [],
}

base = "Win32GUI" if sys.platform == "win32" else None
icon = str(BASE_DIR / "logo.ico") if (BASE_DIR / "logo.ico").exists() else None

executables = [
    Executable("main.py", base=base, target_name="BandoriPet.exe", icon=icon),
    Executable("pet_process.py", base=base, target_name="pet_process.exe"),
    Executable("settings_process.py", base=base, target_name="settings_process.exe"),
    Executable("chat_process.py", base=base, target_name="chat_process.exe"),
]

setup(
    name="BandoriPet",
    version="1.0.0",
    description="Bandori desktop pet",
    options={"build_exe": build_exe_options},
    executables=executables,
    cmdclass={"build_exe": BuildExeWithEmptyModels},
)
