import base64
import ctypes
import io
import json
import os
import time

from PIL import ImageGrab

from vision_fallback import analyze_images_with_aux_model


_TOOL_PREFIX = "computer_"
_LAST_SCREENSHOT_METRICS: dict[str, int] = {}


def computer_tools(config: dict) -> list[dict]:
    if not bool(config.get("computer_use_enabled", False)):
        return []
    tools = []
    if bool(config.get("computer_use_allow_screenshot", True)):
        tools.append(_tool(
            "computer_screenshot",
            "Capture the current desktop screen. Use this before deciding where to click, move, type, or inspect the UI.",
            {},
        ))
    if bool(config.get("computer_use_allow_mouse", False)):
        tools.extend([
            _tool(
                "computer_move",
                "Move the mouse pointer. Use coordinates from the latest screenshot image; the app maps them to real desktop coordinates.",
                {
                    "x": {"type": "integer", "description": "X coordinate in pixels on the latest screenshot image."},
                    "y": {"type": "integer", "description": "Y coordinate in pixels on the latest screenshot image."},
                },
                ["x", "y"],
            ),
            _tool(
                "computer_click",
                "Click at a point from the latest screenshot image. Use this when the user asks to press, tap, choose, open, close, or interact with something on screen.",
                {
                    "x": {"type": "integer", "description": "X coordinate in pixels on the latest screenshot image."},
                    "y": {"type": "integer", "description": "Y coordinate in pixels on the latest screenshot image."},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button."},
                },
                ["x", "y"],
            ),
            _tool(
                "computer_double_click",
                "Double-click at a point from the latest screenshot image.",
                {
                    "x": {"type": "integer", "description": "X coordinate in pixels on the latest screenshot image."},
                    "y": {"type": "integer", "description": "Y coordinate in pixels on the latest screenshot image."},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button."},
                },
                ["x", "y"],
            ),
            _tool(
                "computer_scroll",
                "Scroll at a point from the latest screenshot image.",
                {
                    "x": {"type": "integer", "description": "X coordinate in pixels on the latest screenshot image."},
                    "y": {"type": "integer", "description": "Y coordinate in pixels on the latest screenshot image."},
                    "delta": {"type": "integer", "description": "Positive scrolls up, negative scrolls down."},
                },
                ["x", "y", "delta"],
            ),
        ])
    if bool(config.get("computer_use_allow_keyboard", False)):
        tools.extend([
            _tool(
                "computer_type",
                "Type text into the active focused UI element.",
                {"text": {"type": "string", "description": "Text to type."}},
                ["text"],
            ),
            _tool(
                "computer_key",
                "Press a key or shortcut. Examples: enter, esc, ctrl+l, ctrl+shift+s.",
                {"keys": {"type": "string", "description": "Key name or shortcut."}},
                ["keys"],
            ),
        ])
    if bool(config.get("computer_use_allow_clipboard", False)):
        tools.append(_tool(
            "computer_set_clipboard",
            "Set the system clipboard text. This does not paste automatically.",
            {"text": {"type": "string", "description": "Text to place on the clipboard."}},
            ["text"],
        ))
    if bool(config.get("computer_use_allow_wait", True)):
        tools.append(_tool(
            "computer_wait",
            "Wait for the UI to settle.",
            {"seconds": {"type": "number", "description": "Seconds to wait, from 0.1 to 10."}},
        ))
    return tools


def is_computer_tool_name(name: str) -> bool:
    return str(name or "").startswith(_TOOL_PREFIX)


def run_computer_tool(name: str, arguments, config: dict) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    if not bool(config.get("computer_use_enabled", False)):
        return _result("Computer Use is disabled in settings.")

    try:
        if name == "computer_screenshot":
            return _screenshot_result(config, "Screenshot captured.")
        if name == "computer_move":
            _require(config, "computer_use_allow_mouse", "mouse control")
            sx, sy = _int(arguments.get("x")), _int(arguments.get("y"))
            x, y = _map_point(sx, sy)
            _mouse_move(x, y)
            return _after_action(config, _mapped_action_text("Mouse moved", sx, sy, x, y))
        if name == "computer_click":
            _require(config, "computer_use_allow_mouse", "mouse control")
            sx, sy = _int(arguments.get("x")), _int(arguments.get("y"))
            x, y = _map_point(sx, sy)
            _click(x, y, str(arguments.get("button", "left") or "left"), clicks=1)
            return _after_action(config, _mapped_action_text("Clicked", sx, sy, x, y))
        if name == "computer_double_click":
            _require(config, "computer_use_allow_mouse", "mouse control")
            sx, sy = _int(arguments.get("x")), _int(arguments.get("y"))
            x, y = _map_point(sx, sy)
            _click(x, y, str(arguments.get("button", "left") or "left"), clicks=2)
            return _after_action(config, _mapped_action_text("Double-clicked", sx, sy, x, y))
        if name == "computer_scroll":
            _require(config, "computer_use_allow_mouse", "mouse control")
            sx, sy, delta = _int(arguments.get("x")), _int(arguments.get("y")), _int(arguments.get("delta"))
            x, y = _map_point(sx, sy)
            _scroll(x, y, delta)
            return _after_action(config, f"{_mapped_action_text('Scrolled', sx, sy, x, y)} Delta: {delta}.")
        if name == "computer_type":
            _require(config, "computer_use_allow_keyboard", "keyboard input")
            text = str(arguments.get("text", "") or "")
            _type_text(text)
            return _after_action(config, f"Typed {len(text)} characters.")
        if name == "computer_key":
            _require(config, "computer_use_allow_keyboard", "keyboard input")
            keys = str(arguments.get("keys", "") or "").strip()
            _press_keys(keys)
            return _after_action(config, f"Pressed key: {keys}.")
        if name == "computer_set_clipboard":
            _require(config, "computer_use_allow_clipboard", "clipboard write")
            text = str(arguments.get("text", "") or "")
            _set_clipboard(text)
            return _result(f"Clipboard updated with {len(text)} characters.")
        if name == "computer_wait":
            _require(config, "computer_use_allow_wait", "wait")
            seconds = max(0.1, min(10.0, float(arguments.get("seconds", 2) or 2)))
            time.sleep(seconds)
            return _after_action(config, f"Waited {seconds:.1f} seconds.")
        return _result(f"Unsupported computer tool: {name}")
    except Exception as exc:
        return _result(f"Computer tool failed: {exc}")


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    schema = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def _result(content: str, extra_messages: list[dict] | None = None) -> dict:
    return {"content": content, "extra_messages": extra_messages or []}


def _after_action(config: dict, content: str) -> dict:
    if bool(config.get("computer_use_send_screenshots", True)) and bool(config.get("computer_use_allow_screenshot", True)):
        return _screenshot_result(config, content)
    return _result(content)


def _screenshot_result(config: dict, content: str) -> dict:
    if not bool(config.get("computer_use_allow_screenshot", True)):
        return _result(content + " Screenshot capture is disabled.")
    data_url, width, height, desktop_width, desktop_height = _capture_screenshot_data_url(config)
    coord_hint = (
        f"Latest screenshot image is {width}x{height}; real desktop coordinate space is "
        f"{desktop_width}x{desktop_height}. When calling mouse tools, use the screenshot image coordinates; "
        "the app maps them to the real desktop."
    )
    if bool(config.get("llm_aux_vision_fallback_enabled", False)) and str(config.get("llm_aux_model_id", "") or "").strip():
        try:
            aux_api_url = str(config.get("llm_aux_api_url", "") or "").strip() or str(config.get("llm_api_url", "") or "")
            aux_api_key = str(config.get("llm_aux_api_key", "") or "").strip() or str(config.get("llm_api_key", "") or "")
            summary = analyze_images_with_aux_model(
                aux_api_url,
                aux_api_key,
                str(config.get("llm_aux_model_id", "") or "").strip()
                or str(config.get("llm_model_id", "") or "").strip(),
                [data_url],
                "请观察这张桌面截图，提取下一步操作所需的信息。",
                config.get("llm_aux_enable_thinking", None),
            )
            if summary:
                return _result(f"{content} {coord_hint}\n\nFast vision observation:\n{summary}")
        except Exception as exc:
            return _result(f"{content} {coord_hint}\n\nFast vision fallback failed: {exc}")
    message = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": (
                    "Computer Use screenshot after the last action. "
                    f"{coord_hint} "
                    "Use the image to decide the next UI step. Do not mention tool internals unless the user asked."
                ),
            },
            {"type": "image_url", "image_url": {"url": data_url}},
        ],
    }
    return _result(f"{content} {coord_hint}", [message])


def _capture_screenshot_data_url(config: dict) -> tuple[str, int, int, int, int]:
    global _LAST_SCREENSHOT_METRICS
    image = ImageGrab.grab(all_screens=True)
    max_width = max(640, min(1920, _int(config.get("computer_use_max_screenshot_width", 1280))))
    original_width, original_height = image.size
    desktop_left, desktop_top, desktop_width, desktop_height = _desktop_bounds(original_width, original_height)
    width, height = original_width, original_height
    longest = max(original_width, original_height)
    if longest > max_width:
        scale = max_width / float(longest)
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        width, height = image.size
    _LAST_SCREENSHOT_METRICS = {
        "image_width": width,
        "image_height": height,
        "desktop_left": desktop_left,
        "desktop_top": desktop_top,
        "desktop_width": desktop_width,
        "desktop_height": desktop_height,
    }
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", width, height, desktop_width, desktop_height


def _require(config: dict, key: str, label: str):
    if not bool(config.get(key, False)):
        raise PermissionError(f"{label} is disabled in Computer Use settings")


def _int(value) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _desktop_bounds(fallback_width: int, fallback_height: int) -> tuple[int, int, int, int]:
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


def _map_point(x: int, y: int) -> tuple[int, int]:
    metrics = _LAST_SCREENSHOT_METRICS
    if not metrics:
        return x, y
    image_width = max(1, int(metrics.get("image_width", 1)))
    image_height = max(1, int(metrics.get("image_height", 1)))
    left = int(metrics.get("desktop_left", 0))
    top = int(metrics.get("desktop_top", 0))
    desktop_width = max(1, int(metrics.get("desktop_width", image_width)))
    desktop_height = max(1, int(metrics.get("desktop_height", image_height)))

    within_image = -1 <= x <= image_width + 1 and -1 <= y <= image_height + 1
    if within_image and (image_width != desktop_width or image_height != desktop_height):
        mapped_x = _scale_axis(x, image_width, desktop_width, left)
        mapped_y = _scale_axis(y, image_height, desktop_height, top)
        return mapped_x, mapped_y

    return (
        max(left, min(left + desktop_width - 1, x)),
        max(top, min(top + desktop_height - 1, y)),
    )


def _scale_axis(value: int, image_size: int, desktop_size: int, origin: int) -> int:
    if image_size <= 1 or desktop_size <= 1:
        return origin
    clipped = max(0, min(image_size - 1, int(value)))
    mapped = round(clipped * (desktop_size - 1) / float(image_size - 1))
    return origin + int(mapped)


def _mapped_action_text(action: str, screenshot_x: int, screenshot_y: int, desktop_x: int, desktop_y: int) -> str:
    if (screenshot_x, screenshot_y) == (desktop_x, desktop_y):
        return f"{action} at ({desktop_x}, {desktop_y})."
    return (
        f"{action} at screenshot ({screenshot_x}, {screenshot_y}), "
        f"mapped to desktop ({desktop_x}, {desktop_y})."
    )


def _pyautogui():
    try:
        import pyautogui
    except Exception as exc:
        raise RuntimeError(
            "pyautogui is required for keyboard actions. Run: pip install -r requirements.txt"
        ) from exc
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = True
    return pyautogui


def _mouse_move(x: int, y: int):
    try:
        _pyautogui().moveTo(x, y)
    except RuntimeError:
        if not _win32_mouse_move(x, y):
            raise


def _click(x: int, y: int, button: str, clicks: int = 1):
    button = button if button in {"left", "right", "middle"} else "left"
    try:
        _pyautogui().click(x=x, y=y, clicks=max(1, clicks), button=button)
    except RuntimeError:
        if not _win32_click(x, y, button, clicks=max(1, clicks)):
            raise


def _scroll(x: int, y: int, delta: int):
    try:
        pg = _pyautogui()
        pg.moveTo(x, y)
        pg.scroll(delta)
    except RuntimeError:
        if not _win32_scroll(x, y, delta):
            raise


def _type_text(text: str):
    _pyautogui().write(text, interval=0.01)


def _press_keys(keys: str):
    pg = _pyautogui()
    parts = [part.strip().lower() for part in re_split_keys(keys) if part.strip()]
    if not parts:
        return
    if len(parts) == 1:
        pg.press(parts[0])
    else:
        pg.hotkey(*parts)


def re_split_keys(keys: str) -> list[str]:
    return str(keys or "").replace("+", " ").split()


def _set_clipboard(text: str):
    try:
        import pyperclip
    except Exception as exc:
        raise RuntimeError("pyperclip is required for clipboard access") from exc
    # Avoid accidentally leaking huge data through the system clipboard.
    pyperclip.copy(text[:100_000])


def _win32_mouse_move(x: int, y: int) -> bool:
    if os.name != "nt":
        return False
    return bool(ctypes.windll.user32.SetCursorPos(int(x), int(y)))


def _win32_click(x: int, y: int, button: str, clicks: int = 1) -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    down, up = {
        "left": (0x0002, 0x0004),
        "right": (0x0008, 0x0010),
        "middle": (0x0020, 0x0040),
    }.get(button, (0x0002, 0x0004))
    for _ in range(max(1, int(clicks))):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
    return True


def _win32_scroll(x: int, y: int, delta: int) -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    user32.mouse_event(0x0800, 0, 0, int(delta) * 120, 0)
    return True
