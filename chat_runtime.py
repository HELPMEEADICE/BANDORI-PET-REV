from pathlib import Path

from app_info import APP_NAME
from process_utils import app_runtime_dir, ipc_server_name


def chat_lock_path() -> Path:
    runtime_dir = app_runtime_dir()
    server_name = ipc_server_name() or APP_NAME
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in server_name)
    return runtime_dir / f"{safe_name}-chat.lock"


def chat_window_is_active() -> bool:
    try:
        from PySide6.QtCore import QLockFile
    except Exception:
        return chat_lock_path().exists()

    lock = QLockFile(str(chat_lock_path()))
    if lock.tryLock(0):
        lock.unlock()
        return False
    lock.removeStaleLockFile()
    if lock.tryLock(0):
        lock.unlock()
        return False
    return True
