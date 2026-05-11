import sys
import platform
from pathlib import Path

from cx_Freeze import Executable, setup
from cx_Freeze.command.build_exe import build_exe


BASE_DIR = Path(__file__).resolve().parent
LIVE2D_PACKAGE = BASE_DIR / "third_party" / "live2d-py" / "package"

if LIVE2D_PACKAGE.exists():
    sys.path.insert(0, str(LIVE2D_PACKAGE))

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
    include_if_exists("lang"),
    include_if_exists("band_logo"),
    include_if_exists("characters"),
    include_if_exists("pixels"),
    include_if_exists("third_party/live2d-py/package"),
]
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
        "live2d.v2",
        "numpy",
        "qfluentwidgets",
        "sqlite3",
    ],
    "excludes": ["PyQt5", "PyQt6", "PySide2", "tkinter"],
    "include_msvcr": True,
}

base = "Win32GUI" if sys.platform == "win32" else None
icon = str(BASE_DIR / "logo.ico") if (BASE_DIR / "logo.ico").exists() else None

executables = [
    Executable("main.py", base=base, target_name="BandoriPet.exe", icon=icon),
    Executable("pet_process.py", base=base, target_name="pet_process.exe", icon=icon),
    Executable("settings_process.py", base=base, target_name="settings_process.exe", icon=icon),
    Executable("chat_process.py", base=base, target_name="chat_process.exe", icon=icon),
]

setup(
    name="BandoriPet",
    version="1.0.0",
    description="Bandori desktop pet",
    options={"build_exe": build_exe_options},
    executables=executables,
    cmdclass={"build_exe": BuildExeWithEmptyModels},
)
