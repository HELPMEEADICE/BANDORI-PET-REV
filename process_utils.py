import atexit
import hmac
import json
import os
import sys
import hashlib
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from app_info import APP_NAME


DEBUG_LOG_ENV = "BANDORI_PET_DEBUG_LOG"
INTERACTION_TRACE_ENV = "BANDORI_PET_INTERACTION_TRACE"
_DEBUG_LOG_LOCK = threading.RLock()
_DEBUG_LOG_FILE = None
_DEBUG_LOG_CONFIGURED = False


def _close_debug_log():
    global _DEBUG_LOG_FILE
    with _DEBUG_LOG_LOCK:
        if _DEBUG_LOG_FILE is not None:
            try:
                _DEBUG_LOG_FILE.close()
            except Exception:
                pass
            _DEBUG_LOG_FILE = None


class _BinaryTee:
    def __init__(self, original, log_file):
        self._original = original
        self._log_file = log_file

    def write(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        with _DEBUG_LOG_LOCK:
            if self._original is not None:
                try:
                    self._original.write(data)
                except Exception:
                    pass
            self._log_file.write(data)
        return len(data)

    def flush(self):
        with _DEBUG_LOG_LOCK:
            if self._original is not None:
                try:
                    self._original.flush()
                except Exception:
                    pass
            self._log_file.flush()

    def isatty(self):
        try:
            return bool(self._original is not None and self._original.isatty())
        except Exception:
            return False

    def fileno(self):
        if self._original is None:
            raise OSError("no original stream")
        return self._original.fileno()


class _TextTee:
    encoding = "utf-8"
    errors = "replace"

    def __init__(self, original, log_file):
        self._original = original
        self.buffer = _BinaryTee(getattr(original, "buffer", None), log_file)

    def write(self, text):
        if not isinstance(text, str):
            text = str(text)
        data = text.encode("utf-8", errors="replace")
        with _DEBUG_LOG_LOCK:
            if self._original is not None:
                try:
                    self._original.write(text)
                except Exception:
                    pass
            self.buffer._log_file.write(data)
        return len(text)

    def flush(self):
        with _DEBUG_LOG_LOCK:
            if self._original is not None:
                try:
                    self._original.flush()
                except Exception:
                    pass
            self.buffer._log_file.flush()

    def isatty(self):
        try:
            return bool(self._original is not None and self._original.isatty())
        except Exception:
            return False

    def fileno(self):
        if self._original is None:
            raise OSError("no original stream")
        return self._original.fileno()


def _remove_debug_flag(argv: list[str]) -> bool:
    found = False
    index = 1
    while index < len(argv):
        if argv[index] == "--debug":
            del argv[index]
            found = True
        else:
            index += 1
    return found


def _new_debug_log_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = Path.cwd() / f"{timestamp}.log"
    if not path.exists():
        return path
    return Path.cwd() / f"{timestamp}-{os.getpid()}.log"


def configure_debug_logging(argv: list[str] | None = None) -> Path | None:
    """Enable --debug logging and propagate it to child processes via env."""
    global _DEBUG_LOG_CONFIGURED, _DEBUG_LOG_FILE
    if argv is None:
        argv = sys.argv
    debug_requested = _remove_debug_flag(argv)
    log_path = os.environ.get(DEBUG_LOG_ENV, "").strip()
    if debug_requested and not log_path:
        log_path = str(_new_debug_log_path())
        os.environ[DEBUG_LOG_ENV] = log_path
    if not log_path:
        return None
    if _DEBUG_LOG_CONFIGURED:
        return Path(log_path)

    path = Path(log_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _DEBUG_LOG_FILE = open(path, "ab", buffering=0)
    except OSError:
        return None

    sys.stdout = _TextTee(sys.stdout, _DEBUG_LOG_FILE)
    sys.stderr = _TextTee(sys.stderr, _DEBUG_LOG_FILE)
    _DEBUG_LOG_CONFIGURED = True
    atexit.register(_close_debug_log)
    print(f"[debug] logging to {path}", file=sys.stderr)
    return path


def interaction_trace(component: str, event: str, **fields) -> None:
    if os.environ.get(INTERACTION_TRACE_ENV, "").strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return
    payload = {
        "t": round(time.monotonic(), 6),
        "pid": os.getpid(),
        "component": str(component),
        "event": str(event),
        **fields,
    }
    print(
        "[interaction] " + json.dumps(payload, ensure_ascii=False, default=str),
        file=sys.stderr,
        flush=True,
    )


def debug_logging_enabled() -> bool:
    return _DEBUG_LOG_CONFIGURED or bool(os.environ.get(DEBUG_LOG_ENV, "").strip())


def log_swallowed(context: str, exc: BaseException | None = None) -> None:
    """Record an intentionally swallowed exception so it can be diagnosed.

    Stays silent unless --debug logging is active (BANDORI_PET_DEBUG_LOG set),
    so normal runs behave exactly as a bare ``except ...: pass`` while a debug
    session surfaces the hidden traceback. Never raises.
    """
    if not debug_logging_enabled():
        return
    try:
        import traceback

        if exc is None:
            exc = sys.exc_info()[1]
        if exc is not None:
            detail = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ).rstrip()
        else:
            detail = "(no active exception)"
        print(f"[swallowed] {context}: {detail}", file=sys.stderr, flush=True)
    except Exception:
        pass


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


def app_data_dir() -> Path:
    if not getattr(sys, "frozen", False) or sys.platform != "darwin":
        return app_base_dir()

    override = os.environ.get("BANDORI_PET_DATA_DIR", "").strip()
    if override:
        path = Path(override).expanduser()
    else:
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


_FROZEN_RUNTIME_PATHS_CONFIGURED = False
_FROZEN_DLL_DIRECTORY_HANDLES = []


def configure_frozen_runtime_paths() -> None:
    if not getattr(sys, "frozen", False):
        return
    global _FROZEN_RUNTIME_PATHS_CONFIGURED
    if _FROZEN_RUNTIME_PATHS_CONFIGURED:
        return
    _FROZEN_RUNTIME_PATHS_CONFIGURED = True

    base_dir = app_base_dir()
    lib_dir = base_dir / "lib"
    pyside_dir = lib_dir / "PySide6"
    shiboken_dir = lib_dir / "shiboken6"
    candidate_dirs = [base_dir, lib_dir, pyside_dir, shiboken_dir]
    existing_dirs = [str(path) for path in candidate_dirs if path.is_dir()]

    if existing_dirs:
        current_path = os.environ.get("PATH", "")
        path_parts = [part for part in current_path.split(os.pathsep) if part]
        known = {part.lower() for part in path_parts}
        prepend = [part for part in existing_dirs if part.lower() not in known]
        if prepend:
            os.environ["PATH"] = (
                os.pathsep.join([*prepend, current_path])
                if current_path
                else os.pathsep.join(prepend)
            )

    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        for directory in existing_dirs:
            try:
                _FROZEN_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(directory))
            except OSError:
                pass

    qt_plugins = pyside_dir / "plugins"
    if qt_plugins.is_dir():
        os.environ.setdefault("QT_PLUGIN_PATH", str(qt_plugins))


def app_runtime_dir(base_dir: Path | str | None = None, *, create: bool = True) -> Path:
    if base_dir is not None and (not getattr(sys, "frozen", False) or sys.platform != "darwin"):
        root = Path(base_dir)
    else:
        root = app_data_dir()
    path = root / ".runtime"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


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
    name: str = APP_NAME,
    icon_path: str = "",
    target_path: str = "",
    arguments: str = "",
    working_dir: str = "",
) -> bool:
    if sys.platform != "win32" or not app_id:
        return False
    programs = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    shortcut_path = programs / f"{_safe_shortcut_name(name)}.lnk"
    try:
        if shortcut_path.is_file() and shortcut_path.stat().st_size > 0:
            return True
    except OSError:
        pass
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

        programs.mkdir(parents=True, exist_ok=True)

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
    cleaned = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in str(name or APP_NAME))
    cleaned = cleaned.strip().strip(".")
    return cleaned or APP_NAME


def ipc_server_name() -> str:
    override = os.environ.get("BANDORI_PET_IPC_SERVER_NAME", "").strip()
    if override:
        return override
    digest = hashlib.sha1(str(app_base_dir()).encode("utf-8")).hexdigest()[:12]
    return f"BandoriPet-{digest}"


RUNTIME_LOCK_MIN_AGE_SECONDS = 60


def cleanup_stale_runtime_locks(
    base_dir: Path | None = None,
    min_age_seconds: int = RUNTIME_LOCK_MIN_AGE_SECONDS,
) -> int:
    """Remove leftover ``.runtime/*-chat.lock`` files from dead sessions.

    Each app session creates a uniquely named chat lock (the IPC server name
    embeds the parent PID + a uuid), so old files pile up after crashes or hard
    kills. ``QLockFile`` knows whether the owning process is still alive, so we
    only delete locks that are free or stale and never touch one held by a live
    instance. A short minimum age avoids racing a concurrently launching peer.
    """
    runtime_dir = app_runtime_dir(base_dir, create=False)
    if not runtime_dir.is_dir():
        return 0
    try:
        from PySide6.QtCore import QLockFile
    except Exception:
        QLockFile = None
    cutoff = time.time() - max(0, int(min_age_seconds))
    removed = 0
    try:
        candidates = list(runtime_dir.glob("*-chat.lock"))
    except OSError:
        return 0
    for lock_path in candidates:
        try:
            if not lock_path.is_file():
                continue
            if lock_path.stat().st_mtime > cutoff:
                continue
            if QLockFile is not None:
                lock = QLockFile(str(lock_path))
                # tryLock(0) succeeds when the lock is free or stale (owner
                # dead); QLockFile then reclaims it and unlock() deletes the
                # file. A live owner makes tryLock fail, so we leave it alone.
                if lock.tryLock(0):
                    lock.unlock()
                    if lock_path.exists():
                        try:
                            lock_path.unlink()
                        except OSError:
                            continue
                    removed += 1
                else:
                    lock.removeStaleLockFile()
            else:
                lock_path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def clamp_int(value: object, minimum: int, maximum: int, default: int | None = None) -> int:
    if default is None:
        default = minimum
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        number = default
    return max(minimum, min(maximum, number))


def clamp_float(value: object, minimum: float, maximum: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def token_matches(expected: str, candidate: str) -> bool:
    """Constant-time token comparison to avoid leaking the token via timing."""
    return hmac.compare_digest(str(expected or ""), str(candidate or ""))


def install_parent_death_watch(app, interval_ms: int = 2000, on_parent_death=None):
    # When the parent process dies (SIGKILL, terminal closed, etc.) Unix-like
    # systems reparent this process to init/launchd, so getppid() changes.
    # Windows keeps orphaned child processes alive; waiting on a handle to the
    # original parent detects that case reliably across sleep/resume.
    from PySide6.QtCore import QMetaObject, Qt, QTimer

    def _request_quit():
        try:
            QMetaObject.invokeMethod(app, "quit", Qt.ConnectionType.QueuedConnection)
        except Exception:
            app.quit()

    initial_ppid = os.getppid()
    if os.name == "nt":
        _install_windows_parent_handle_watch(app, initial_ppid, on_parent_death, _request_quit)

    def _check():
        if os.getppid() != initial_ppid:
            if callable(on_parent_death):
                on_parent_death()
            _request_quit()

    timer = QTimer(app)
    timer.setInterval(int(interval_ms))
    timer.timeout.connect(_check)
    timer.start()
    return timer


def _install_windows_parent_handle_watch(
    app,
    parent_pid: int,
    on_parent_death=None,
    request_quit=None,
) -> bool:
    if os.name != "nt" or parent_pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    infinite = 0xFFFFFFFF

    handle = kernel32.OpenProcess(synchronize, False, int(parent_pid))
    if not handle:
        return False

    def _watch_parent_handle():
        try:
            result = kernel32.WaitForSingleObject(handle, infinite)
            if result == wait_object_0:
                if callable(on_parent_death):
                    on_parent_death()
                if callable(request_quit):
                    request_quit()
                else:
                    app.quit()
        finally:
            kernel32.CloseHandle(handle)

    threading.Thread(
        target=_watch_parent_handle,
        name="BandoriPetParentDeathWatch",
        daemon=True,
    ).start()
    return True


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


def run_off_gui_thread(fn):
    try:
        from PySide6.QtCore import QThread
        from PySide6.QtWidgets import QApplication
    except Exception:
        return fn()
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        return fn()

    done = threading.Event()
    result = {}

    def worker():
        try:
            result["value"] = fn()
        except Exception as exc:
            result["error"] = exc
        finally:
            done.set()

    threading.Thread(target=worker, daemon=True).start()
    done.wait()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def bootstrap_app() -> tuple[str, object]:
    """Common startup preamble: debug logging, base dir, GPU config."""
    configure_debug_logging()
    configure_frozen_runtime_paths()
    base_dir = str(app_base_dir())
    from config_manager import ConfigManager
    from gpu_acceleration import configure_qt_opengl_environment, is_gpu_acceleration_enabled

    startup_config = ConfigManager()
    configure_qt_opengl_environment(is_gpu_acceleration_enabled(startup_config))
    return base_dir, startup_config


def app_icon_path(base_dir: str | None = None) -> str:
    if base_dir is None:
        base_dir = str(app_base_dir())
    for name in ("icon.ico", "logo.ico"):
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            return path
    return ""


def ensure_taskbar_icon_identity(app_id: str, display_name: str, base_dir: str | None = None) -> bool:
    if sys.platform != "win32":
        return True
    if base_dir is None:
        base_dir = str(app_base_dir())
    icon_path = app_icon_path(base_dir)
    target_path = sys.executable
    arguments = ""
    if getattr(sys, "frozen", False):
        candidate = os.path.join(base_dir, "BandoriPet.exe")
        if os.path.exists(candidate):
            target_path = candidate
    else:
        arguments = f'"{os.path.join(base_dir, "main.py")}"'
    return ensure_windows_app_user_model_shortcut(
        app_id,
        display_name,
        icon_path,
        target_path=target_path,
        arguments=arguments,
        working_dir=base_dir,
    )
