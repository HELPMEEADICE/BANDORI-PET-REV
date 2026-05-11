import os
import sys
import hashlib
from pathlib import Path


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
    digest = hashlib.sha1(str(app_base_dir()).encode("utf-8")).hexdigest()[:12]
    return f"BandoriPet-{digest}"
