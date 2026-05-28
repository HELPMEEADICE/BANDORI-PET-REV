import importlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import fluent_bootstrap
from setuptools import Command

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

from cx_Freeze import Executable, setup
from cx_Freeze.command.bdist_mac import bdist_mac
from cx_Freeze.command.bdist_msi import bdist_msi
from cx_Freeze.command.build_exe import build_exe


BASE_DIR = Path(__file__).resolve().parent
BYTECODE_BUILD_DIR = BASE_DIR / "BUILD" / ".luajit-bytecode"
WINDOWS_INSTALLER_UTF8_CODEPAGE = 65001
INNO_RESOURCE_DIRS = (
    "audio_reference",
    "characters",
    "pixels",
    "lang",
    "band_logo",
)
PYOPENGL_PLATFORM_MODULES = (
    "OpenGL.platform.win32",
    "OpenGL.platform.baseplatform",
    "OpenGL.platform.ctypesloader",
)

for module_name in (
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtWidgets",
):
    importlib.import_module(module_name)

from app_info import APP_NAME, APP_REPO_URL, APP_VERSION  # noqa: E402


class BuildExeWithEmptyModels(build_exe):
    def run(self):
        super().run()
        if BYTECODE_BUILD_DIR.exists():
            shutil.rmtree(BYTECODE_BUILD_DIR)
        models_dir = Path(self.build_exe) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)


def _force_msi_database_codepage(db, installer_name: str, codepage: int) -> None:
    import ctypes
    import tempfile
    import _msi
    from ctypes import wintypes

    db.Commit()
    db.Close()

    msi = ctypes.WinDLL("msi")
    msi_handle = wintypes.UINT
    msi.MsiOpenDatabaseW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(msi_handle),
    ]
    msi.MsiOpenDatabaseW.restype = wintypes.UINT
    msi.MsiDatabaseImportW.argtypes = [
        msi_handle,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
    ]
    msi.MsiDatabaseImportW.restype = wintypes.UINT
    msi.MsiDatabaseCommit.argtypes = [msi_handle]
    msi.MsiDatabaseCommit.restype = wintypes.UINT
    msi.MsiCloseHandle.argtypes = [msi_handle]
    msi.MsiCloseHandle.restype = wintypes.UINT

    with tempfile.TemporaryDirectory() as temp_dir:
        force_codepage = Path(temp_dir) / "_ForceCodepage.idt"
        force_codepage.write_text(
            f"\r\n\r\n{codepage}\t_ForceCodepage\r\n",
            encoding="ascii",
        )

        handle = msi_handle(0)
        result = msi.MsiOpenDatabaseW(
            installer_name,
            ctypes.c_wchar_p(_msi.MSIDBOPEN_TRANSACT),
            ctypes.byref(handle),
        )
        if result != 0:
            raise RuntimeError(
                f"Failed to open MSI database for codepage update: {result}"
            )
        try:
            result = msi.MsiDatabaseImportW(
                handle.value,
                temp_dir,
                force_codepage.name,
            )
            if result != 0:
                raise RuntimeError(
                    f"Failed to import MSI codepage table: {result}"
                )
            result = msi.MsiDatabaseCommit(handle.value)
            if result != 0:
                raise RuntimeError(
                    f"Failed to commit MSI codepage update: {result}"
                )
        finally:
            msi.MsiCloseHandle(handle.value)


def _init_utf8_msi_database(original_init_database):
    def init_database_utf8(installer_name, *args, **kwargs):
        db = original_init_database(installer_name, *args, **kwargs)
        _force_msi_database_codepage(
            db,
            installer_name,
            WINDOWS_INSTALLER_UTF8_CODEPAGE,
        )

        import _msi

        db = _msi.OpenDatabase(installer_name, _msi.MSIDBOPEN_TRANSACT)
        summary_info = db.GetSummaryInformation(20)
        summary_info.SetProperty(
            _msi.PID_CODEPAGE,
            WINDOWS_INSTALLER_UTF8_CODEPAGE,
        )
        summary_info.Persist()
        summary_info = None
        db.Commit()
        return db

    return init_database_utf8


class BuildMsiAlias(bdist_msi):
    """Expose cx_Freeze's MSI builder as `python setup.py build_msi`."""

    def run(self):
        if sys.platform != "win32":
            super().run()
            return

        bdist_msi_module = importlib.import_module("cx_Freeze.command.bdist_msi")
        original_init_database = bdist_msi_module.init_database
        bdist_msi_module.init_database = _init_utf8_msi_database(
            original_init_database
        )
        try:
            super().run()
        finally:
            bdist_msi_module.init_database = original_init_database


class BuildMacWithResourceLinks(bdist_mac):
    """Keep cx_Freeze's macOS app layout compatible with app_base_dir()."""

    def run(self):
        super().run()
        self._link_root_resource_files()
        if self.codesign_identity:
            self._codesign(self.bundle_dir)

    def _link_root_resource_files(self):
        for filename in (
            "logo.ico",
            "band.json",
            "outfit.json",
            "custom_hit_area_state.ljbc",
            "live2d_platform_manager_override.ljbc",
        ):
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


def _find_iscc() -> str:
    """Locate Inno Setup Compiler (ISCC.exe)."""
    candidates = [
        os.environ.get("ISCC_PATH", ""),
        r"C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
        r"C:\Program Files\Inno Setup 7\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    if iscc:
        return iscc
    raise RuntimeError(
        "Inno Setup Compiler (ISCC.exe) not found. "
        "Install Inno Setup 6+ or set ISCC_PATH environment variable."
    )


def _inno_language_entries(iscc: str) -> str:
    entries = ['Name: "english"; MessagesFile: "compiler:Default.isl"']
    chinese_simplified = Path(iscc).resolve().parent / "Languages" / "ChineseSimplified.isl"
    if chinese_simplified.exists():
        entries.append(
            'Name: "chinesesimplified"; MessagesFile: "compiler:Languages\\ChineseSimplified.isl"'
        )
    return "\n".join(entries)


class BuildInnoAlias(Command):
    """Build Inno Setup installer via `python setup.py build_inno`."""

    description = "build Inno Setup installer"
    user_options = [
        ("iss-template=", None, "Path to .iss template file"),
    ]

    def initialize_options(self):
        self.iss_template = None

    def finalize_options(self):
        if self.iss_template is None:
            self.iss_template = str(BASE_DIR / "installer" / "bandoripet.iss.tpl")

    def run(self):
        self.run_command("build")

        template_path = Path(self.iss_template)
        if not template_path.exists():
            raise FileNotFoundError(f"IS template not found: {template_path}")

        template = template_path.read_text(encoding="utf-8")

        iscc = _find_iscc()
        app_guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "bandoripet.rev")).upper()
        build_exe_cmd = self.get_finalized_command("build_exe")
        build_dir = Path(build_exe_cmd.build_exe).resolve()
        output_dir = BASE_DIR / "BUILD"
        output_dir.mkdir(parents=True, exist_ok=True)

        output_filename = f"BandoriPet-{APP_VERSION}-{release_platform_name().lower()}{release_arch_name().lower()}-setup"

        license_file = BASE_DIR / "LICENSE"
        icon_file = BASE_DIR / "logo.ico"

        replacements = {
            "{APP_NAME}": APP_NAME,
            "{APP_VERSION}": APP_VERSION,
            "{APP_REPO_URL}": APP_REPO_URL,
            "{APP_ID}": f"{{{{{app_guid}}}",
            "{BUILD_DIR}": str(build_dir),
            "{OUTPUT_DIR}": str(output_dir),
            "{OUTPUT_FILENAME}": output_filename,
            "{LICENSE_FILE}": str(license_file) if license_file.exists() else "",
            "{ICON_FILE}": str(icon_file) if icon_file.exists() else "",
            "{LANGUAGE_ENTRIES}": _inno_language_entries(iscc),
        }

        iss_content = template
        for placeholder, value in replacements.items():
            iss_content = iss_content.replace(placeholder, value)

        iss_path = output_dir / "BandoriPet.iss"
        iss_path.write_text(iss_content, encoding="utf-8")
        print(f"Generated Inno Setup script: {iss_path}")

        print(f"Compiling with: {iscc}")
        subprocess.run([iscc, "/Q", str(iss_path)], check=True)

        installer_path = output_dir / f"{output_filename}.exe"
        if installer_path.exists():
            print(f"Inno Setup installer created: {installer_path}")
        else:
            print(f"Warning: Expected installer not found at {installer_path}")


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
    name = "lupa.luajit21"
    spec = importlib.util.find_spec(name)
    if spec is None:
        raise RuntimeError("lupa.luajit21 is required but is not installed.")
    try:
        module = __import__(name, fromlist=["LuaRuntime"])
        lua = module.LuaRuntime()
        lua.execute('assert(require("ffi"))')
    except Exception as exc:
        raise RuntimeError(
            "lupa.luajit21 must be available and built with LuaJIT FFI. "
            "On macOS, reinstall it with: "
            "LUPA_NO_BUNDLE=true pip install --no-binary lupa --force-reinstall lupa. "
            f"Error: {exc}"
        ) from exc
    return name


include_files = [
    include_if_exists("logo.ico"),
    include_if_exists("band.json"),
    include_if_exists("outfit.json"),
    _compiled_lua_include("custom_hit_area_state.lua"),
    _compiled_lua_include("live2d_platform_manager_override.lua"),
    *(include_if_exists(dirname) for dirname in INNO_RESOURCE_DIRS),
    include_package_subdir("_sounddevice_data", "portaudio-binaries"),
    include_package_dir("_soundfile_data"),
]

include_files.extend(_live2d_lua_include_files())
include_files = [item for item in include_files if item is not None]
lupa_runtime = lupa_luajit_runtime_module()

build_exe_options = {
    "build_exe": str(BASE_DIR / "BUILD" / f"BANDORI-PET-REV-RELEASE-{release_platform_name()}-{release_arch_name()}"),
    "include_files": include_files,
    "includes": ["tts_manager", lupa_runtime, *PYOPENGL_PLATFORM_MODULES],
    "packages": [
        "OpenGL",
        "PIL",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtWidgets",
        "darkdetect",
        "numpy",
        "qfluentwidgets",
        "requests",
        "sounddevice",
        "soundfile",
        "sqlite3",
        "zstandard",
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
        "build_inno": BuildInnoAlias,
        "bdist_mac": BuildMacWithResourceLinks,
    },
)
