import os
import sys
import hashlib
import subprocess
from pathlib import Path


def ensure_xwayland():
    if sys.platform not in ("linux", "linux2"):
        return
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def frozen_executable_name(script_name: str) -> str:
    base, _ext = os.path.splitext(script_name)
    return base + (".exe" if sys.platform == "win32" else "")


def process_program_and_args(base_dir: str, script_name: str, args: list[str]) -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return os.path.join(base_dir, frozen_executable_name(script_name)), args
    return sys.executable, [os.path.join(base_dir, script_name), *args]


def set_windows_app_user_model_id(app_id: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def ensure_windows_app_user_model_shortcut(
    app_id: str,
    name: str = "BandoriPet",
    icon_path: str = "",
    target_path: str = "",
    arguments: str = "",
    working_dir: str = "",
) -> bool:
    if sys.platform != "win32" or not app_id:
        return False
    try:
        import pythoncom
        from win32com.propsys import propsys, pscon
        from win32com.shell import shell

        base_dir = app_base_dir()
        if not target_path:
            target_path = sys.executable
        if not working_dir:
            working_dir = str(base_dir)
        if not icon_path:
            candidate = base_dir / "logo.ico"
            icon_path = str(candidate) if candidate.exists() else target_path
        if not arguments and not getattr(sys, "frozen", False):
            main_py = base_dir / "main.py"
            if main_py.exists():
                arguments = f'"{main_py}"'

        programs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        programs.mkdir(parents=True, exist_ok=True)
        shortcut_path = programs / f"{_safe_shortcut_name(name)}.lnk"

        pythoncom.CoInitialize()
        try:
            link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.CLSCTX_INPROC_SERVER,
                shell.IID_IShellLink,
            )
            link.SetPath(str(target_path))
            link.SetArguments(str(arguments or ""))
            link.SetWorkingDirectory(str(working_dir or ""))
            if icon_path:
                link.SetIconLocation(str(icon_path), 0)

            store = link.QueryInterface(propsys.IID_IPropertyStore)
            store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(str(app_id)))
            store.Commit()

            persist = link.QueryInterface(pythoncom.IID_IPersistFile)
            persist.Save(str(shortcut_path), 0)
        finally:
            pythoncom.CoUninitialize()
        return True
    except Exception:
        return False


def _safe_shortcut_name(name: str) -> str:
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in str(name or "BandoriPet"))
    cleaned = cleaned.strip().strip(".")
    return cleaned or "BandoriPet"


def ipc_server_name() -> str:
    override = os.environ.get("BANDORI_PET_IPC_SERVER_NAME", "").strip()
    if override:
        return override
    digest = hashlib.sha1(str(app_base_dir()).encode("utf-8")).hexdigest()[:12]
    return f"BandoriPet-{digest}"


def clamp_int(value: object, minimum: int, maximum: int, default: int | None = None) -> int:
    if default is None:
        default = minimum
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def clamp_float(value: object, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def hidden_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }
