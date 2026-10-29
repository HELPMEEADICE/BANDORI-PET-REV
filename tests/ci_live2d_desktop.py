"""CI smoke test of the real desktop process with the checked-in Hiyori model."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bandori_core.mapped_memory import queue_file_path
from bandori_core.native_pet import native_executable, native_program_and_args
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, decode_ipc_envelope


def capture_screen(path):
    """Capture the complete runner desktop, including decorations and background."""
    try:
        screen = ImageGrab.grab(all_screens=True) if sys.platform == "win32" else ImageGrab.grab()
        screen.save(path)
        print(f"Full desktop screenshot: {path.name} {screen.size}", flush=True)
        return True
    except Exception as error:
        print(f"Full desktop screenshot failed: {error}", flush=True)
        return False


def window_present(pid):
    if sys.platform == "win32":
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        found = []
        @callback
        def collect(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if owner.value == pid and user32.IsWindowVisible(hwnd) and title.value == "CI-Hiyori":
                found.append(hwnd)
            return True
        user32.EnumWindows(collect, 0)
        for hwnd in found:
            outer, client = wintypes.RECT(), wintypes.RECT()
            origin = wintypes.POINT()
            assert user32.GetWindowRect(hwnd, ctypes.byref(outer))
            assert user32.GetClientRect(hwnd, ctypes.byref(client))
            assert user32.ClientToScreen(hwnd, ctypes.byref(origin))
            assert (outer.left, outer.top, outer.right, outer.bottom) == (
                origin.x, origin.y, origin.x + client.right, origin.y + client.bottom
            ), f"window has a non-client frame: outer={(outer.left, outer.top, outer.right, outer.bottom)}, client={(origin.x, origin.y, origin.x + client.right, origin.y + client.bottom)}"
        return bool(found)
    import Quartz
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    return any(w.get("kCGWindowOwnerPID") == pid and w.get("kCGWindowName") == "CI-Hiyori" for w in windows or [])


def main():
    import tempfile
    if sys.platform == "win32":
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    model = ROOT / "native/pet_backend/vendor/neocari/assets/models/Hiyori/Hiyori.model3.json"
    snapshot = ROOT / "live2d-ci-snapshot.png"
    queues = [SharedMemoryLineQueue.create("ci-live2d-" + uuid.uuid4().hex, slot_count=32) for _ in range(4)]
    process = None
    stderr_file = tempfile.TemporaryFile()
    screen_dir = ROOT / "live2d-ci-screens"
    screen_dir.mkdir(exist_ok=True)
    stop_capture = threading.Event()
    capture_thread = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.json"
            config.write_text(json.dumps({"fps": 30, "models": [{"character": "CI", "costume": "Hiyori", "path": str(model)}]}), encoding="utf-8")
            binary = native_executable(ROOT)
            _, args = native_program_and_args(ROOT, "CI", "Hiyori", str(model), config_path=config, data_dir=Path(tmp))
            for flag, queue in zip(["--inbound", "--reliable-inbound", "--broadcast", "--control"], queues):
                args[args.index(flag) + 1] = str(queue_file_path(queue.key))
            args.extend(["--exit-after", "90"])
            env = os.environ.copy()
            env["BANDORI_PET_SNAPSHOT"] = str(snapshot)
            env["RUST_LOG"] = "info"
            process = subprocess.Popen([str(binary), *args], stdout=subprocess.DEVNULL, stderr=stderr_file, env=env)
            def capture_during_startup():
                index = 0
                while not stop_capture.is_set():
                    capture_screen(screen_dir / f"startup-{index % 4}.png")
                    index += 1
                    stop_capture.wait(0.5)
            capture_thread = threading.Thread(target=capture_during_startup, daemon=True)
            capture_thread.start()
            ready = False
            deadline = time.monotonic() + 70
            while time.monotonic() < deadline:
                for queue in queues[:2]:
                    for line in queue.read_available():
                        decoded = decode_ipc_envelope(line).line
                        if decoded.startswith("NATIVE_EVENT\t"):
                            event = json.loads(decoded.split("\t", 1)[1])
                            if event["event"] == "error":
                                raise AssertionError(f"backend error: {event}")
                            ready |= event["event"] == "ready"
                if process.poll() is not None:
                    raise AssertionError(f"backend exited: {process.returncode}")
                if ready and snapshot.exists() and window_present(process.pid):
                    break
                time.sleep(0.2)
            else:
                raise AssertionError(f"timed out: ready={ready}, snapshot={snapshot.exists()}")
            image = Image.open(snapshot).convert("RGBA")
            alpha = image.getchannel("A")
            assert alpha.getextrema()[0] == 0 and alpha.getextrema()[1] > 0, "snapshot must contain transparent and visible pixels"
            assert sum(alpha.histogram()[1:]) > 1000, "model has too few visible pixels"
            time.sleep(0.5)  # Allow the desktop compositor to display the presented frame.
            assert capture_screen(screen_dir / "visible-window.png"), "full desktop screenshot failed"
            print(f"Real Live2D model rendered: {image.size}; process window visible after first frame")
            if sys.platform == "win32":
                print("Windows client area covers its window; DWM border pixels require visual verification")
            else:
                print("macOS window is visible; visual absence of borders is not verified by this test")
    finally:
        stop_capture.set()
        if capture_thread is not None:
            capture_thread.join(timeout=10)
        capture_screen(screen_dir / "test-end.png")
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            stderr_file.seek(0)
            print(stderr_file.read().decode(errors="replace"))
        stderr_file.close()
        for queue in queues:
            queue.close()


if __name__ == "__main__":
    main()
