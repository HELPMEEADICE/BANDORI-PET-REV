import base64
import ctypes
import io
import os
import threading

from PIL import ImageGrab


_SCREENSHOT_LOCK = threading.Lock()


def capture_screenshot_data_url(max_width: int = 1280) -> tuple[str, int, int, int, int]:
    try:
        with _SCREENSHOT_LOCK:
            image = ImageGrab.grab(all_screens=True)
    except Exception:
        raise RuntimeError("Failed to capture screenshot. This may happen when no display is available or a security restriction prevents screen capture.")
    max_width = max(640, min(1920, _int(max_width, 1280)))
    original_width, original_height = image.size
    _desktop_left, _desktop_top, desktop_width, desktop_height = desktop_bounds(original_width, original_height)
    width, height = original_width, original_height
    longest = max(original_width, original_height)
    if longest > max_width:
        scale = max_width / float(longest)
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        width, height = image.size
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", width, height, desktop_width, desktop_height


def desktop_bounds(fallback_width: int, fallback_height: int) -> tuple[int, int, int, int]:
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            left = int(user32.GetSystemMetrics(76))
            top = int(user32.GetSystemMetrics(77))
            width = int(user32.GetSystemMetrics(78))
            height = int(user32.GetSystemMetrics(79))
            if width > 0 and height > 0:
                return left, top, width, height
        except Exception:
            pass
    return 0, 0, max(1, fallback_width), max(1, fallback_height)


def _int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default
