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
