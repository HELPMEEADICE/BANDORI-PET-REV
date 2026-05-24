import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import fluent_bootstrap

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

from cx_Freeze import Executable, setup
from cx_Freeze.command.bdist_mac import bdist_mac
from cx_Freeze.command.bdist_msi import bdist_msi
from cx_Freeze.command.build_exe import build_exe


BASE_DIR = Path(__file__).resolve().parent
BYTECODE_BUILD_DIR = BASE_DIR / "BUILD" / ".luajit-bytecode"

for module_name in (
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtWidgets",
):
    importlib.import_module(module_name)

from app_info import APP_NAME, APP_VERSION  # noqa: E402


class BuildExeWithEmptyModels(build_exe):
    def run(self):
        super().run()
        if BYTECODE_BUILD_DIR.exists():
            shutil.rmtree(BYTECODE_BUILD_DIR)
        models_dir = Path(self.build_exe) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)


class BuildMsiAlias(bdist_msi):
    """Expose cx_Freeze's MSI builder as `python setup.py build_msi`."""


class BuildMacWithResourceLinks(bdist_mac):
    """Keep cx_Freeze's macOS app layout compatible with app_base_dir()."""

    def run(self):
        super().run()
        self._link_root_resource_files()
        if self.codesign_identity:
            self._codesign(self.bundle_dir)

    def _link_root_resource_files(self):
        for filename in ("logo.ico", "band.json", "outfit.json", "custom_hit_area_state.ljbc"):
            source = Path(self.resources_dir) / filename
            origin = Path(self.bin_dir) / filename
            if not source.exists() or origin.exists():
                continue
            relative_reference = os.path.relpath(source, self.bin_dir)
            self.execute(
                os.symlink,
                (relative_reference, origin, True),
                msg=f"linking {origin} -> {relative_reference}",
            )


def include_if_exists(path: str) -> tuple[str, str] | None:
    src = BASE_DIR / path
    if not src.exists():
        return None
    return str(src), path


def include_package_subdir(package_name: str, subdir: str, dest_path: str | None = None) -> tuple[str, str] | None:
    spec = importlib.util.find_spec(package_name)
    if spec is None or spec.origin is None:
        return None
    package_subdir = Path(spec.origin).resolve().parent / subdir
    if not package_subdir.exists():
        return None
    return str(package_subdir), dest_path or f"lib/{package_name}/{subdir}"


def include_package_dir(package_name: str, dest_path: str | None = None) -> tuple[str, str] | None:
    spec = importlib.util.find_spec(package_name)
    if spec is None or spec.origin is None:
        return None
    package_dir = Path(spec.origin).resolve().parent
    if not package_dir.exists():
        return None
    return str(package_dir), dest_path or f"lib/{package_name}"


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


def _mac_iconfile() -> str | None:
    if sys.platform != "darwin":
        return None
    source = BASE_DIR / "logo.ico"
    if not source.exists():
        return None

    try:
        from PIL import Image
    except ImportError:
        return None

    iconfile = BASE_DIR / "BUILD" / "BandoriPet.icns"
    if iconfile.exists() and iconfile.stat().st_mtime_ns >= source.stat().st_mtime_ns:
        return str(iconfile)

    iconfile.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.convert("RGBA").save(
            iconfile,
            format="ICNS",
            sizes=[(16, 16), (32, 32), (128, 128), (256, 256), (512, 512), (1024, 1024)],
        )
    return str(iconfile) if iconfile.exists() else None


def lupa_luajit_runtime_module() -> str:
    candidates = ("lupa.luajit21", "lupa.lua")
    errors: list[str] = []

    for name in candidates:
        spec = importlib.util.find_spec(name)
        if spec is None:
            errors.append(f"{name}: not installed")
            continue
        try:
            module = __import__(name, fromlist=["LuaRuntime"])
            lua = module.LuaRuntime()
            lua.execute('assert(require("ffi"))')
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        return name

    details = "; ".join(errors)
    raise RuntimeError(
        "A Lupa runtime built with LuaJIT FFI is required. "
        "On macOS, reinstall it with: "
        "LUPA_NO_BUNDLE=true pip install --no-binary lupa --force-reinstall lupa. "
        f"Checked runtimes: {details}"
    )


include_files = [
    include_if_exists("logo.ico"),
    include_if_exists("band.json"),
    include_if_exists("outfit.json"),
    _compiled_lua_include("custom_hit_area_state.lua"),
    include_if_exists("lang"),
    include_if_exists("band_logo"),
    include_if_exists("characters"),
    include_if_exists("pixels"),
    include_if_exists("audio_reference"),
    include_package_subdir("_sounddevice_data", "portaudio-binaries"),
    include_package_dir("_soundfile_data"),
]

include_files.extend(_live2d_lua_include_files())
include_files = [item for item in include_files if item is not None]
lupa_runtime = lupa_luajit_runtime_module()

build_exe_options = {
    "build_exe": str(BASE_DIR / "BUILD" / f"BANDORI-PET-REV-RELEASE-{release_platform_name()}-{release_arch_name()}"),
    "include_files": include_files,
    "includes": ["tts_manager", lupa_runtime],
    "packages": [
        "OpenGL",
        "PIL",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtWidgets",
        "darkdetect",
        "numpy",
        "qfluentwidgets",
        "requests",
        "sounddevice",
        "soundfile",
        "sqlite3",
    ],
    "excludes": ["PyQt5", "PyQt6", "PySide2", "tkinter"],
    "include_msvcr": sys.platform == "win32",
    
    "zip_include_packages": ["*"], 
    "zip_exclude_packages": ["_sounddevice_data", "_soundfile_data"],
}

base = "Win32GUI" if sys.platform == "win32" else None
icon = str(BASE_DIR / "logo.ico") if (BASE_DIR / "logo.ico").exists() else None

build_msi_options = {
    "dist_dir": str(BASE_DIR / "BUILD"),
    "product_name": APP_NAME,
    "product_version": APP_VERSION,
    "upgrade_code": "{A8D4D0D2-3D5F-4F1E-9B26-1BDCBFC6D4A1}",
    "install_icon": icon,
    "initial_target_dir": r"[ProgramFilesFolder]\BandoriPet",
    "summary_data": {
        "author": "BandoriPet",
        "comments": "Bandori desktop pet",
        "keywords": "BandoriPet,Live2D,Desktop Pet",
    }
} if sys.platform == "win32" else {}

build_mac_options = {
    "bundle_name": APP_NAME,
    "iconfile": _mac_iconfile(),
    "plist_items": [
        ("CFBundleDisplayName", APP_NAME),
        ("CFBundleName", APP_NAME),
        ("CFBundleIdentifier", "com.bandori.pet.rev"),
        ("CFBundleShortVersionString", APP_VERSION),
        ("CFBundleVersion", APP_VERSION),
        ("LSUIElement", True),
    ],
} if sys.platform == "darwin" else {}

_exec_suffix = ".exe" if sys.platform == "win32" else ""

executables = [
    Executable("main.py", base=base, target_name=f"BandoriPet{_exec_suffix}", icon=icon),
    Executable("pet_process.py", base=base, target_name=f"pet_process{_exec_suffix}"),
    Executable("radial_menu_process.py", base=base, target_name=f"radial_menu_process{_exec_suffix}"),
    Executable("settings_process.py", base=base, target_name=f"settings_process{_exec_suffix}"),
    Executable("chat_process.py", base=base, target_name=f"chat_process{_exec_suffix}"),
    Executable("bandori_ai_event.py", base=None, target_name=f"bandori-ai-event{_exec_suffix}"),
    Executable("bandori_codex_runner.py", base=None, target_name=f"bandori-codex-runner{_exec_suffix}"),
]

setup(
    name=APP_NAME,
    version=APP_VERSION,
    description="Bandori desktop pet",
    options={
        "build_exe": build_exe_options,
        "build_msi": build_msi_options,
        "bdist_msi": build_msi_options,
        "bdist_mac": build_mac_options,
    },
    executables=executables,
    cmdclass={
        "build_exe": BuildExeWithEmptyModels,
        "build_msi": BuildMsiAlias,
        "bdist_mac": BuildMacWithResourceLinks,
    },
)
