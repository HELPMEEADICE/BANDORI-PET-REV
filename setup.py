import importlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import bandori_ui.fluent_bootstrap as fluent_bootstrap
from setuptools import Command

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

from cx_Freeze import Executable, setup
from cx_Freeze.command.bdist_mac import bdist_mac
from cx_Freeze.command.bdist_msi import bdist_msi
from cx_Freeze.command.build_exe import build_exe



BASE_DIR = Path(__file__).resolve().parent
# Windows Installer database strings are not reliably installable when authored
# as UTF-8 (65001). The bundled resources contain Chinese filenames, so use the
# Simplified Chinese ANSI code page by default and allow CI to override it.
DEFAULT_WINDOWS_INSTALLER_CODEPAGE = 936
WINDOWS_INSTALLER_CODEPAGE_ENV = "BANDORIPET_MSI_CODEPAGE"
INNO_RESOURCE_DIRS = (
    "audio_reference",
    "characters",
    "events",
    "pixels",
    "lang",
    "band_logo",
)
USER_DATA_FILENAMES = (
    "config.json",
    "data.db",
    "data.db-shm",
    "data.db-wal",
)
MANAGED_FILES_MANIFEST = ".bandoripet-managed-files"
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

from bandori_core.app_info import APP_NAME, APP_REPO_URL, APP_VERSION  # noqa: E402


class BuildExeWithEmptyModels(build_exe):
    def run(self):
        # Incremental builds must not retain the retired renderer's resources.
        output = Path(self.build_exe).resolve()
        for relative in ("third_party/Live2D-v2-Lua", "custom_hit_area_state.ljbc", "live2d_platform_manager_override.ljbc"):
            obsolete = (output / relative).resolve()
            if not obsolete.is_relative_to(output):
                raise RuntimeError("Retired renderer cleanup escaped the build directory")
            if obsolete.is_dir():
                shutil.rmtree(obsolete)
            elif obsolete.exists():
                obsolete.unlink()
        manifest = BASE_DIR / "native" / "pet_backend" / "Cargo.toml"
        rust_args = ["cargo", "build", "--release", "--locked", "--manifest-path", str(manifest), "-p", "bandori-pet-native", "-p", "pet-assets"]
        native_output = manifest.parent / "target"
        if sys.platform == "darwin":
            rust_arch = "aarch64" if release_arch_name() == "ARM64" else "x86_64"
            rust_target = rust_arch + "-apple-darwin"
            if shutil.which("rustup"):
                subprocess.run(["rustup", "target", "add", rust_target], check=True)
            rust_args.extend(["--target", rust_target])
            native_output /= rust_target
        subprocess.run(rust_args, check=True)
        super().run()
        build_dir = Path(self.build_exe)
        native_name = "bandori-pet-native" + (".exe" if sys.platform == "win32" else "")
        native_binary = native_output / "release" / native_name
        shutil.copy2(native_binary, build_dir / native_name)
        assets_name = "pet_assets.dll" if sys.platform == "win32" else "libpet_assets.dylib" if sys.platform == "darwin" else "libpet_assets.so"
        shutil.copy2(native_output / "release" / assets_name, build_dir / assets_name)
        native_licenses = build_dir / "licenses" / "neocari"
        native_licenses.mkdir(parents=True, exist_ok=True)
        upstream = manifest.parent / "vendor" / "neocari"
        shutil.copy2(upstream / "LICENSE", native_licenses / "LICENSE")
        shutil.copytree(upstream / "LICENSES", native_licenses / "LICENSES", dirs_exist_ok=True)
        shutil.copy2(manifest.parent / "NOTICE.md", native_licenses / "NOTICE.md")
        pyside_source = Path(importlib.import_module("PySide6").__file__).resolve().parent
        pyside_icu_names = {
            path.name.casefold()
            for path in pyside_source.rglob("icu*.dll")
        }
        bundled_pyside_dir = build_dir / "lib" / "PySide6"
        if bundled_pyside_dir.is_dir():
            for path in bundled_pyside_dir.glob("icu*.dll"):
                if path.name.casefold() not in pyside_icu_names:
                    # cx_Freeze can resolve ICU from unrelated packages on PATH
                    # (such as Poppler), which is incompatible with Qt6Core.
                    path.unlink()
        for filename in USER_DATA_FILENAMES:
            path = build_dir / filename
            if path.exists():
                path.unlink()
        models_dir = Path(self.build_exe) / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        managed_names = sorted(
            entry.name
            for entry in build_dir.iterdir()
            if entry.name not in USER_DATA_FILENAMES
            and entry.name not in {"models", "chat_attachments", MANAGED_FILES_MANIFEST}
        )
        managed_names.append(MANAGED_FILES_MANIFEST)
        (build_dir / MANAGED_FILES_MANIFEST).write_text(
            "\n".join(managed_names) + "\n",
            encoding="utf-8",
        )


def _force_msi_database_codepage(db, installer_name: str, codepage: int) -> None:
    import ctypes
    import tempfile
    from ctypes import wintypes

    # Python 3.13+ uses python-msilib, including native Windows ARM64 builds.
    _msi = _windows_msi_module()

    if codepage <= 0:
        raise ValueError(f"MSI codepage must be a positive integer: {codepage}")
    if not ctypes.windll.kernel32.IsValidCodePage(codepage):
        raise ValueError(f"Windows does not recognize MSI codepage: {codepage}")

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


def _windows_installer_codepage() -> int:
    raw_codepage = os.environ.get(WINDOWS_INSTALLER_CODEPAGE_ENV)
    if not raw_codepage:
        return DEFAULT_WINDOWS_INSTALLER_CODEPAGE
    try:
        return int(raw_codepage)
    except ValueError as exc:
        raise ValueError(
            f"{WINDOWS_INSTALLER_CODEPAGE_ENV} must be an integer codepage, "
            f"got {raw_codepage!r}"
        ) from exc


def _windows_msi_module():
    if sys.version_info >= (3, 13):
        return importlib.import_module("msilib._msi")
    return importlib.import_module("_msi")


def _init_msi_database_with_codepage(original_init_database):
    def init_database_with_codepage(installer_name, *args, **kwargs):
        db = original_init_database(installer_name, *args, **kwargs)
        codepage = _windows_installer_codepage()
        _force_msi_database_codepage(
            db,
            installer_name,
            codepage,
        )

        _msi = _windows_msi_module()

        db = _msi.OpenDatabase(installer_name, _msi.MSIDBOPEN_TRANSACT)
        summary_info = db.GetSummaryInformation(20)
        summary_info.SetProperty(
            _msi.PID_CODEPAGE,
            codepage,
        )
        summary_info.Persist()
        summary_info = None
        db.Commit()
        return db

    return init_database_with_codepage


class BuildMsiAlias(bdist_msi):
    """Expose cx_Freeze's MSI builder as `python setup.py build_msi`."""

    def run(self):
        if sys.platform != "win32":
            super().run()
            return

        bdist_msi_module = importlib.import_module("cx_Freeze.command.bdist_msi")
        original_init_database = bdist_msi_module.init_database
        bdist_msi_module.init_database = _init_msi_database_with_codepage(
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
        native_source = Path(self.resources_dir) / "bandori-pet-native"
        if native_source.is_file():
            self.execute(shutil.move, (str(native_source), str(Path(self.bin_dir) / "bandori-pet-native")), msg="placing Neocari in Contents/MacOS")
        assets_source = Path(self.resources_dir) / "libpet_assets.dylib"
        if assets_source.is_file():
            self.execute(shutil.move, (str(assets_source), str(Path(self.bin_dir) / "libpet_assets.dylib")), msg="placing pet-assets in Contents/MacOS")
        self._link_root_resource_files()
        if self.codesign_identity:
            self._codesign(self.bundle_dir)
        else:
            # cx_Freeze 在加入资源符号链接之前就给 bundle 签了名，导致封印
            # 与磁盘内容不一致（codesign --verify 报 "code has no resources
            # but signature indicates they must be present"）。本机直接双击能开
            # （无 quarantine，Gatekeeper 不介入），但经 dmg 分发后即便清掉
            # quarantine，arm64 也会因签名损坏而静默秒杀（双击/右键无反应、无弹窗）。
            # 没有 Developer ID 时，在所有文件就位后补一次 ad-hoc 重签，重建一致封印。
            self._adhoc_resign()

    def _adhoc_resign(self):
        bundle = str(self.bundle_dir)
        self.execute(
            lambda: subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", bundle],
                check=True,
            ),
            (),
            msg=f"ad-hoc re-signing {bundle}",
        )

    def _link_root_resource_files(self):
        for filename in (
            "logo.ico",
            "band.json",
            "outfit.json",
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
            "{INSTALL_ARCH}": "arm64" if release_arch_name() == "ARM64" else "x64compatible",
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
        if not installer_path.is_file() or installer_path.stat().st_size <= 0:
            raise RuntimeError(
                f"Inno Setup completed without creating a valid installer: {installer_path}"
            )
        print(f"Inno Setup installer created: {installer_path}")


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


include_files = [
    include_if_exists("logo.ico"),
    include_if_exists("band.json"),
    include_if_exists("outfit.json"),
    *(include_if_exists(dirname) for dirname in INNO_RESOURCE_DIRS),
    include_package_subdir("_sounddevice_data", "portaudio-binaries"),
    include_package_dir("_soundfile_data"),
]

include_files = [item for item in include_files if item is not None]

build_exe_options = {
    "build_exe": str(BASE_DIR / "BUILD" / f"BANDORI-PET-REV-RELEASE-{release_platform_name()}-{release_arch_name()}"),
    "include_files": include_files,
    "includes": ["bandori_audio.tts_manager", "lupa.luajit21"],
    "packages": [
        "OpenGL",
        "PIL",
        "aiohttp",
        "lupa",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtWidgets",
        "certifi",
        "cryptography",
        "darkdetect",
        "numpy",
        "packaging",
        "platformdirs",
        "py7zr",
        "plugin_system",
        "psutil",
        "qrcode",
        "qfluentwidgets",
        "requests",
        "sounddevice",
        "soundfile",
        "sqlite3",
        "zstandard",
        "zeroconf",
    ],
    "excludes": [
        "PyQt5",
        "PyQt6",
        "PySide2",
        "tkinter",
        "lupa.lua51",
        "lupa.lua52",
        "lupa.lua53",
        "lupa.lua54",
        "lupa.lua55",
    ],
    "include_msvcr": sys.platform == "win32",
    
    "zip_include_packages": ["*"], 
    "zip_exclude_packages": ["_sounddevice_data", "_soundfile_data", "qfluentwidgets", "PIL", "lupa"],
}

base = "gui" if sys.platform == "win32" else None
icon = str(BASE_DIR / "logo.ico") if (BASE_DIR / "logo.ico").exists() else None

build_msi_options = {
    "dist_dir": str(BASE_DIR / "BUILD"),
    "product_name": APP_NAME,
    "product_version": APP_VERSION,
    "upgrade_code": "{A8D4D0D2-3D5F-4F1E-9B26-1BDCBFC6D4A1}",
    "install_icon": icon,
    "initial_target_dir": r"[ProgramFiles64Folder]\BandoriPet",
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
    Executable("pet_process.py", base=base, target_name=f"pet_process{_exec_suffix}", icon=icon),
    Executable("radial_menu_process.py", base=base, target_name=f"radial_menu_process{_exec_suffix}"),
    Executable("settings_process.py", base=base, target_name=f"settings_process{_exec_suffix}"),
    Executable("chat_process.py", base=base, target_name=f"chat_process{_exec_suffix}"),
    Executable("plugin_worker.py", base=None, target_name=f"plugin_worker{_exec_suffix}"),
    Executable("bandori_ai_event.py", base=None, target_name=f"bandori-ai-event{_exec_suffix}"),
    Executable("bandori_codex_runner.py", base=None, target_name=f"bandori-codex-runner{_exec_suffix}"),
]

setup(
    name=APP_NAME,
    version=APP_VERSION,
    description="Bandori desktop pet",
    options={
        "build": {"build_base": str(BASE_DIR / "BUILD")},
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
