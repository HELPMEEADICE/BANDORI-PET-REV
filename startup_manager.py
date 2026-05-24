import os
import subprocess
import sys

from process_utils import app_base_dir, frozen_executable_name


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_VALUE = "BandoriPet"


def is_supported() -> bool:
    return sys.platform == "win32"


def _packaged_main_executable(base_dir: str) -> str:
    preferred = os.path.join(base_dir, "BandoriPet.exe")
    if os.path.exists(preferred):
        return preferred
    return os.path.join(base_dir, frozen_executable_name("main.py"))


def startup_command() -> str:
    base_dir = str(app_base_dir())
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([_packaged_main_executable(base_dir)])
    interpreter = sys.executable
    if sys.platform == "win32" and os.path.basename(interpreter).lower() == "python.exe":
        pythonw = os.path.join(os.path.dirname(interpreter), "pythonw.exe")
        if os.path.exists(pythonw):
            interpreter = pythonw
    return subprocess.list2cmdline([interpreter, os.path.join(base_dir, "main.py")])


def _open_run_key(access):
    winreg = _winreg()
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def _winreg():
    import winreg

    return winreg


def current_startup_command() -> str:
    if not is_supported():
        return ""
    try:
        winreg = _winreg()
        with _open_run_key(winreg.KEY_READ) as key:
            value, _value_type = winreg.QueryValueEx(key, APP_RUN_VALUE)
            return str(value or "").strip()
    except OSError:
        return ""


def is_startup_enabled() -> bool:
    return bool(current_startup_command())


def set_startup_enabled(enabled: bool) -> None:
    if not is_supported():
        raise RuntimeError("Auto start is only supported on Windows.")
    winreg = _winreg()

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, APP_RUN_VALUE, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_RUN_VALUE)
            except FileNotFoundError:
                pass
