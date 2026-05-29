import argparse
import ctypes
import ctypes.wintypes
import json
import os
import random
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import glfw
import OpenGL.GL as gl

from process_utils import app_base_dir, configure_debug_logging, process_program_and_args, set_windows_app_user_model_id
from shared_event_ipc import SharedEventReader

configure_debug_logging()

BASE_DIR = Path(app_base_dir())
CONFIG_PATH = BASE_DIR / "config.json"
PIXELS_DIR = BASE_DIR / "pixels"
PIXEL_FRAMES_PATH = PIXELS_DIR / "frames.json"
LIVE2D_BASE_WIDTH = 400
LIVE2D_BASE_HEIGHT = 500
DEFAULT_HIT_ALPHA_THRESHOLD = 8
DEFAULT_LIP_SYNC_MAX_OPEN = 0.55

GWL_EXSTYLE = -20
GWLP_WNDPROC = -4
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

if os.name == "nt":
    _user32 = ctypes.windll.user32
    _get_window_long = _user32.GetWindowLongPtrW
    _set_window_long = _user32.SetWindowLongPtrW
    _set_window_pos = _user32.SetWindowPos
    _set_layered_window_attributes = _user32.SetLayeredWindowAttributes
    _call_window_proc = _user32.CallWindowProcW
    _def_window_proc = _user32.DefWindowProcW
    _get_cursor_pos = _user32.GetCursorPos
    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.wintypes.HWND,
        ctypes.c_uint,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    )
    _get_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    _get_window_long.restype = ctypes.c_ssize_t
    _set_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _set_window_long.restype = ctypes.c_ssize_t
    _call_window_proc.argtypes = [
        ctypes.c_ssize_t,
        ctypes.wintypes.HWND,
        ctypes.c_uint,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    ]
    _call_window_proc.restype = ctypes.c_ssize_t
    _def_window_proc.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.c_uint,
        ctypes.wintypes.WPARAM,
        ctypes.wintypes.LPARAM,
    ]
    _def_window_proc.restype = ctypes.c_ssize_t
else:
    _user32 = None
    _get_window_long = None
    _set_window_long = None
    _set_window_pos = None
    _set_layered_window_attributes = None
    _call_window_proc = None
    _def_window_proc = None
    _get_cursor_pos = None
    _WNDPROC = None


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one isolated lightweight Live2D pet process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--costume", required=True)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--group-characters", default="")
    return parser.parse_args()


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    return data if isinstance(data, dict) else {}


def _save_config(data: dict):
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def _cfg_get(config: dict, key: str, default=None):
    return config.get(key, default)


def _clamp_float(value, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _model_entry(config: dict, character: str, costume: str) -> dict:
    models = config.get("models", [])
    if isinstance(models, list):
        fallback = {}
        for item in models:
            if not isinstance(item, dict) or item.get("character") != character:
                continue
            if item.get("costume") == costume:
                return item
            if not fallback:
                fallback = item
        return fallback
    return {}


def _parse_group_characters(value: str, character: str) -> list[str]:
    try:
        parsed = json.loads(value) if value else []
    except json.JSONDecodeError:
        parsed = []
    result = []
    seen = set()
    for item in parsed if isinstance(parsed, list) else []:
        name = str(item or "").strip()
        if name and name not in seen:
            result.append(name)
            seen.add(name)
    if character and character not in seen:
        result.insert(0, character)
    return result


def _pixel_path_for_character(character: str) -> str:
    if not character:
        return ""
    path = PIXELS_DIR / f"{character}.webp"
    if path.exists() and PIXEL_FRAMES_PATH.exists():
        return str(path.resolve())
    return ""


class Live2DGlRenderer:
    def __init__(self, width: int, height: int, fps: int, quality: str, hit_threshold: int, lip_max_open: float):
        from live2d_lua_adapter import live2d
        from live2d_quality import LIVE2D_QUALITY_PROFILES, normalize_live2d_quality
        from platform_patch import set_live2d_texture_quality

        self.live2d = live2d
        self.quality = normalize_live2d_quality(quality)
        self.disable_precision = LIVE2D_QUALITY_PROFILES[self.quality]["disable_precision"]
        set_live2d_texture_quality(self.quality)
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        self.fps = max(10, min(int(fps), 240))
        self.hit_threshold = max(0, min(int(hit_threshold), 255))
        self.lip_max_open = max(0.0, min(float(lip_max_open), 1.0))
        self.model = None
        self.model_path = ""
        self.lip_level = 0.0
        self.lip_target = 0.0
        self.lip_form = 0.0
        self.lip_form_target = 0.0
        self.lip_last_at = -1000.0

    def init_gl(self):
        self.live2d.glInit()
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_DITHER)
        gl.glViewport(0, 0, self.width, self.height)

    def load_model(self, model_json_path: str):
        from zst_model_archive import clear_virtual_byte_cache, is_virtual_path, prefetch_virtual_model_resources

        if not model_json_path:
            return
        try:
            if is_virtual_path(model_json_path):
                clear_virtual_byte_cache()
                prefetch_virtual_model_resources(model_json_path)
            self.model = self.live2d.LAppModel()
            self.model.Resize(self.width, self.height)
            self.model.LoadModelJson(model_json_path, disable_precision=self.disable_precision)
            self.model_path = model_json_path
        finally:
            if is_virtual_path(model_json_path):
                clear_virtual_byte_cache()

    def resize(self, width: int, height: int):
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        gl.glViewport(0, 0, self.width, self.height)
        if self.model is not None:
            self.model.Resize(self.width, self.height)

    def draw(self):
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendEquationSeparate(gl.GL_FUNC_ADD, gl.GL_FUNC_ADD)
        gl.glBlendFuncSeparate(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA, gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        if self.model is None:
            return
        self._apply_lip_sync()
        self.model.Draw()

    def set_lip_sync_pose(self, level: float, form: float = 0.0):
        self.lip_target = max(0.0, min(float(level), self.lip_max_open))
        self.lip_form_target = max(-1.0, min(float(form), 1.0))
        self.lip_last_at = time.monotonic()

    def _apply_lip_sync(self):
        target = self.lip_target if time.monotonic() - self.lip_last_at <= 0.18 else 0.0
        form_target = self.lip_form_target if time.monotonic() - self.lip_last_at <= 0.18 else 0.0
        self.lip_level += (target - self.lip_level) * 0.55
        self.lip_form += (form_target - self.lip_form) * 0.45
        if self.lip_level < 0.01:
            self.lip_level = 0.0
        if abs(self.lip_form) < 0.01:
            self.lip_form = 0.0
        self.model.SetParameterValue("PARAM_MOUTH_OPEN_Y", self.lip_level, 1.0)
        self.model.SetParameterValue("PARAM_MOUTH_FORM", self.lip_form, 1.0)

    def drag(self, x: float, y: float):
        if self.model is not None:
            self.model.Drag(x, y)

    def hit_at(self, x: float, y: float) -> bool:
        if self.model is None or not (0 <= x < self.width and 0 <= y < self.height):
            return False
        pixel = (ctypes.c_ubyte * 4)()
        gl.glReadPixels(int(x), int(self.height - 1 - y), 1, 1, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, pixel)
        return int(pixel[3]) > self.hit_threshold

    def hit_area_name_at(self, x: float, y: float) -> str:
        if self.model is None:
            return ""
        try:
            return (self.model.HitTest("", x, y) or "").strip().lower()
        except Exception:
            return ""

    def start_random_motion(self):
        if self.model is None:
            return
        try:
            self.model.StartRandomMotion(priority=self.live2d.MotionPriority.FORCE)
        except Exception:
            pass

    def start_motion(self, motion_name: str, expression: str = ""):
        if self.model is None:
            return
        if expression:
            self.set_expression(expression)
        motion_name = str(motion_name or "").strip()
        if not motion_name:
            self.start_random_motion()
            return
        try:
            self.model.StartMotion(motion_name, priority=self.live2d.MotionPriority.FORCE)
        except Exception:
            self.start_random_motion()

    def set_expression(self, expression: str):
        if self.model is None:
            return
        expression = str(expression or "").strip()
        if not expression:
            return
        names = list(getattr(self.model, "expressions", {}).keys())
        exp_map = {}
        for name in names:
            low = str(name).lower()
            exp_map[low] = name
            exp_map[os.path.splitext(low)[0]] = name
        match = exp_map.get(expression.lower()) or exp_map.get(os.path.splitext(expression.lower())[0])
        if not match:
            return
        try:
            self.model.SetExpression(match)
        except Exception:
            pass

    def start_action(self, action_name: str, character: str = ""):
        if self.model is None:
            return
        normalized = str(action_name or "").strip().lower().strip("[] \t\r\n")
        normalized = normalized.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if not normalized:
            return
        if "." in normalized:
            base, ext = normalized.rsplit(".", 1)
            if ext in {"exp", "json"}:
                self.set_expression(base)
                return
            if ext in {"mtn", "motion"}:
                normalized = base
            else:
                return
        tag_map = {
            "angry": "angry", "cry": "cry", "bye": "bye", "kandou": "kandou",
            "smile": "smile", "sad": "sad", "surprised": "surprised",
            "thinking": "thinking", "shame": "shame", "serious": "serious",
            "wink": "wink", "kime": "kime", "nf": "nf", "nnf": "nnf",
            "scared": "scared", "sleep": "sleep", "sneeze": "sneeze",
            "sing": "sing", "sigh": "sigh", "odoodo": "odoodo", "eeto": "eeto",
            "gattsu": "gattsu", "jaan": "jaan", "nekodere": "nekodere",
            "pui": "pui", "niya": "niya", "ando": "ando", "mitore": "mitore",
            "nod": "nod", "f": "f",
        }
        tag = tag_map.get(normalized, normalized)
        motion = self._find_motion(tag, character)
        if motion:
            self.start_motion(motion)
        self.set_expression(tag)

    def _find_motion(self, tag: str, character: str = "") -> str:
        if self.model is None or self.model.modelSetting is None:
            return ""
        tag_low = str(tag or "").lower()
        candidates = [tag_low]
        if tag_low == "thinking":
            candidates = ["thinking", "nf", "nnf", "eeto", "odoodo"]
        char_lower = str(character or "").lower()
        matches = []
        for candidate in candidates:
            candidate_prefix = f"{char_lower}_{candidate}" if char_lower else candidate
            for motion_name in self.model.modelSetting.getMotionNames():
                motion_low = str(motion_name).lower()
                if motion_low == candidate or motion_low.startswith(candidate):
                    matches.append(str(motion_name))
                elif char_lower and (motion_low == candidate_prefix or motion_low.startswith(candidate_prefix)):
                    matches.append(str(motion_name))
                elif re.search(rf"(^|[_\-]){re.escape(candidate)}($|[_\-]?\d)", motion_low):
                    matches.append(str(motion_name))
        if matches:
            return random.choice(matches)
        try:
            return tag if self.model.modelSetting.resolveMotion(tag, 0) else ""
        except Exception:
            return ""

    def dispose(self):
        self.live2d.dispose()


class RadialMenuClient:
    def __init__(self, on_action, on_lock):
        self.on_action = on_action
        self.on_lock = on_lock
        self.process = None
        self.sock = None
        self.visible = False
        self._reader = None

    def ensure_started(self):
        if self.process is not None and self.process.poll() is None and self.sock is not None:
            return True
        self.close(force=True)
        program, arguments = process_program_and_args(str(BASE_DIR), "radial_menu_process.py", ["--tcp-port", "0"])
        self.process = subprocess.Popen(
            [program, *arguments],
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        port = None
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and self.process.poll() is None:
            line = self.process.stdout.readline() if self.process.stdout is not None else ""
            if not line:
                continue
            line = line.rstrip("\r\n")
            if line.startswith("READY"):
                parts = line.split("\t")
                port = int(parts[1]) if len(parts) > 1 else None
                break
        if not port:
            self.close(force=True)
            return False
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
        self.sock.settimeout(None)
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        return True

    def _read_stdout(self):
        stream = self.process.stdout if self.process is not None else None
        if stream is None:
            return
        for raw in stream:
            self._handle_line(raw.rstrip("\r\n"))

    def _handle_line(self, line: str):
        if line == "STATE\tOPEN":
            self.visible = True
        elif line == "STATE\tCLOSED":
            self.visible = False
        elif line.startswith("ACT\t"):
            self.on_action(line.split("\t", 1)[1].strip())
        elif line.startswith("LOCK\t"):
            self.on_lock(line.split("\t", 1)[1].strip() == "1")

    def send(self, line: str):
        if not self.ensure_started() or self.sock is None:
            return
        self.sock.sendall((line + "\n").encode("utf-8"))

    def close(self, force: bool = False):
        try:
            if self.sock is not None:
                self.sock.sendall(b"EXIT\n")
                self.sock.close()
        except OSError:
            pass
        self.sock = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(0.3 if force else 1.0)
            except subprocess.TimeoutExpired:
                if force:
                    self.process.kill()
        self.process = None
        self.visible = False


class LightweightPet:
    def __init__(self, args):
        self.args = args
        self.config = _load_config()
        from i18n_manager import detect_system_language, set_language

        set_language(str(self.config.get("language", "") or detect_system_language()))
        self.character = args.character
        self.costume = args.costume
        self.group_characters = _parse_group_characters(args.group_characters, self.character)
        self.entry = _model_entry(self.config, self.character, self.costume)
        self.model_path = args.model_path or self.entry.get("path", "")
        self.fps = _clamp_int(_cfg_get(self.config, "fps", 120), 10, 240, 120)
        self.opacity = _clamp_float(_cfg_get(self.config, "opacity", 1.0), 0.05, 1.0, 1.0)
        self.vsync = bool(_cfg_get(self.config, "vsync", True))
        self.drag_locked = bool(_cfg_get(self.config, "drag_locked", False))
        self.hide = bool(_cfg_get(self.config, "hide_live2d_model", False))
        self.head_tracking = bool(_cfg_get(self.config, "live2d_head_tracking_enabled", True))
        self.quality = str(_cfg_get(self.config, "live2d_quality", "balanced"))
        scale = _clamp_int(_cfg_get(self.config, "live2d_scale", 100), 25, 500, 100)
        self.width = int(round(LIVE2D_BASE_WIDTH * scale / 100.0))
        self.height = int(round(LIVE2D_BASE_HEIGHT * scale / 100.0))
        self.x = int(self.entry.get("window_x", _cfg_get(self.config, "window_x", -1)))
        self.y = int(self.entry.get("window_y", _cfg_get(self.config, "window_y", -1)))
        if self.x < 0 or self.y < 0:
            self.x, self.y = 100 + args.index * 36, 100
        self.window = None
        self.hwnd = 0
        self.mouse_passthrough = False
        self.native_hit_test = False
        self._original_wndproc = 0
        self._wndproc = None
        self.dragging = False
        self.drag_moved = False
        self.pressed_on_model = False
        self.drag_start = (0.0, 0.0)
        self.drag_origin = (0.0, 0.0)
        self.last_head_track = 0.0
        self.last_save = 0.0
        self.renderer = Live2DGlRenderer(
            self.width,
            self.height,
            self.fps,
            self.quality,
            _clamp_int(_cfg_get(self.config, "live2d_hit_alpha_threshold", DEFAULT_HIT_ALPHA_THRESHOLD), 0, 255, DEFAULT_HIT_ALPHA_THRESHOLD),
            _clamp_float(_cfg_get(self.config, "live2d_lip_sync_max_open", DEFAULT_LIP_SYNC_MAX_OPEN), 0.0, 1.0, DEFAULT_LIP_SYNC_MAX_OPEN),
        )
        self.radial = RadialMenuClient(self._on_radial_action, self._on_lock_toggled)
        self.shared_events = SharedEventReader()

    def run(self) -> int:
        if not self.model_path:
            print("No Live2D model path configured", file=sys.stderr)
            return 2
        if not glfw.init():
            print("Failed to initialize GLFW", file=sys.stderr)
            return 3
        try:
            self._create_window()
            glfw.make_context_current(self.window)
            glfw.swap_interval(1 if self.vsync else 0)
            self.renderer.init_gl()
            self.renderer.load_model(self.model_path)
            if not self.hide:
                glfw.show_window(self.window)
            frame_interval = 1.0 / self.fps
            next_frame = time.monotonic()
            while not glfw.window_should_close(self.window):
                glfw.poll_events()
                self._poll_shared_events()
                self._poll_head_tracking()
                self._update_mouse_passthrough()
                now = time.monotonic()
                if now >= next_frame:
                    self.renderer.draw()
                    glfw.swap_buffers(self.window)
                    next_frame = now + frame_interval
                else:
                    time.sleep(min(0.004, next_frame - now))
        finally:
            self._save_position()
            self.shared_events.close()
            self.radial.close(force=True)
            self._restore_windows_hit_test_hook()
            self.renderer.dispose()
            if self.window is not None:
                glfw.destroy_window(self.window)
            glfw.terminate()
        return 0

    def _poll_shared_events(self):
        for line in self.shared_events.poll_lines():
            self._handle_shared_event_line(line)

    def _handle_shared_event_line(self, line: str):
        if line.startswith("ACTION\t"):
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[1] == self.character:
                self.renderer.start_action(parts[2], self.character)
            elif len(parts) == 2:
                self.renderer.start_action(parts[1], self.character)
        elif line.startswith("LIP\t"):
            parts = line.split("\t")
            if len(parts) >= 3 and parts[1] == self.character:
                try:
                    level = float(parts[2])
                    form = float(parts[3]) if len(parts) >= 4 else 0.0
                    self.renderer.set_lip_sync_pose(level, form)
                except ValueError:
                    pass
        elif line.startswith("AI_EVENT\t"):
            self._handle_ai_event_payload(line.split("\t", 1)[1])
        elif line.startswith("CHAT_EVENT\t") or line.startswith("REMINDER_EVENT\t"):
            self._handle_action_event_payload(line.split("\t", 1)[1])
        elif line.startswith("PREVIEW_MOTION\t"):
            parts = line.split("\t", 4)
            if len(parts) >= 4 and parts[1] == self.character:
                self.renderer.start_motion(parts[2], parts[3])
        elif line.startswith("OPEN_CHAT"):
            parts = line.split("\t", 1)
            if len(parts) == 1 or not parts[1] or parts[1] == self.character:
                self._open_chat()
        elif line == "SHUTDOWN":
            if self.window is not None:
                glfw.set_window_should_close(self.window, True)

    def _handle_ai_event_payload(self, payload: str):
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict) or not self._event_targets_this_pet(event):
            return
        action = str(event.get("action") or "").strip()
        state = str(event.get("state") or "").strip().lower()
        if not action and state in {"thinking", "tool"}:
            action = "thinking"
        elif not action and state == "error":
            action = "surprised"
        elif not action and state == "done":
            action = "smile"
        if action:
            self.renderer.start_action(action, self.character)

    def _handle_action_event_payload(self, payload: str):
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict) or not self._event_targets_this_pet(event):
            return
        action = str(event.get("action") or "").strip()
        if action:
            self.renderer.start_action(action, self.character)

    def _event_targets_this_pet(self, event: dict) -> bool:
        target = str(event.get("character") or event.get("target_character") or "").strip()
        return not target or target == self.character

    def _create_window(self):
        glfw.window_hint(glfw.CLIENT_API, glfw.OPENGL_API)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 2)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
        glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.FOCUS_ON_SHOW, glfw.FALSE)
        self.window = glfw.create_window(self.width, self.height, f"BandoriPet-{self.character}", None, None)
        if self.window is None:
            raise RuntimeError("Failed to create GLFW window")
        glfw.set_window_pos(self.window, self.x, self.y)
        glfw.set_mouse_button_callback(self.window, self._mouse_button_callback)
        glfw.set_cursor_pos_callback(self.window, self._cursor_pos_callback)
        if os.name == "nt":
            set_windows_app_user_model_id("BandoriPet.PetRenderer")
            self.hwnd = int(glfw.get_win32_window(self.window))
            self._apply_windows_window_style()

    def _apply_windows_window_style(self):
        if not self.hwnd:
            return
        style = _get_window_long(self.hwnd, GWL_EXSTYLE)
        style |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        if self.opacity < 1.0:
            style |= WS_EX_LAYERED
        style &= ~WS_EX_APPWINDOW
        _set_window_long(self.hwnd, GWL_EXSTYLE, style)
        if self.opacity < 1.0:
            _set_layered_window_attributes(self.hwnd, 0, int(round(self.opacity * 255)), LWA_ALPHA)
        self._install_windows_hit_test_hook()
        _set_window_pos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)

    def _install_windows_hit_test_hook(self):
        if os.name != "nt" or not self.hwnd or _WNDPROC is None or self._original_wndproc:
            return
        try:
            self._wndproc = _WNDPROC(self._native_wndproc)
            proc_ptr = ctypes.cast(self._wndproc, ctypes.c_void_p).value
            previous = _set_window_long(self.hwnd, GWLP_WNDPROC, int(proc_ptr))
            if previous:
                self._original_wndproc = int(previous)
                self.native_hit_test = True
            else:
                self._wndproc = None
        except Exception:
            self.native_hit_test = False
            self._original_wndproc = 0
            self._wndproc = None

    def _restore_windows_hit_test_hook(self):
        if os.name != "nt" or not self.hwnd or not self._original_wndproc:
            return
        try:
            _set_window_long(self.hwnd, GWLP_WNDPROC, self._original_wndproc)
        except Exception:
            pass
        self.native_hit_test = False
        self._original_wndproc = 0
        self._wndproc = None

    def _call_original_wndproc(self, hwnd, msg, wparam, lparam):
        if self._original_wndproc and _call_window_proc is not None:
            return _call_window_proc(self._original_wndproc, hwnd, msg, wparam, lparam)
        if _def_window_proc is not None:
            return _def_window_proc(hwnd, msg, wparam, lparam)
        return 0

    @staticmethod
    def _signed_word(value: int) -> int:
        value &= 0xffff
        return value - 0x10000 if value & 0x8000 else value

    def _native_wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_NCHITTEST and self.window is not None and not self.dragging:
                raw = int(lparam) & 0xffffffff
                gx = self._signed_word(raw)
                gy = self._signed_word(raw >> 16)
                wx, wy = glfw.get_window_pos(self.window)
                if wx <= gx < wx + self.width and wy <= gy < wy + self.height:
                    if not self.renderer.hit_at(gx - wx, gy - wy):
                        return HTTRANSPARENT
        except Exception:
            pass
        return self._call_original_wndproc(hwnd, msg, wparam, lparam)

    def _set_mouse_passthrough(self, enabled: bool):
        if self.native_hit_test:
            return
        if os.name != "nt" or not self.hwnd or enabled == self.mouse_passthrough:
            return
        style = _get_window_long(self.hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        _set_window_long(self.hwnd, GWL_EXSTYLE, style)
        _set_window_pos(
            self.hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        self.mouse_passthrough = enabled

    def _global_cursor_pos(self) -> tuple[int, int]:
        if os.name == "nt":
            point = ctypes.wintypes.POINT()
            _get_cursor_pos(ctypes.byref(point))
            return int(point.x), int(point.y)
        x, y = glfw.get_cursor_pos(self.window)
        wx, wy = glfw.get_window_pos(self.window)
        return int(wx + x), int(wy + y)

    def _mouse_button_callback(self, _window, button, action, _mods):
        x, y = glfw.get_cursor_pos(self.window)
        gx, gy = self._global_cursor_pos()
        if button == glfw.MOUSE_BUTTON_RIGHT and action == glfw.PRESS:
            if self.renderer.hit_at(x, y):
                self._show_radial_menu(gx, gy)
            return
        if button != glfw.MOUSE_BUTTON_LEFT:
            return
        if action == glfw.PRESS:
            self.pressed_on_model = self.renderer.hit_at(x, y)
            if self.pressed_on_model and not self.drag_locked:
                self.dragging = True
                self.drag_moved = False
                self.drag_start = (gx, gy)
                self.drag_origin = (gx, gy)
                self._set_mouse_passthrough(False)
        elif action == glfw.RELEASE:
            should_click = self.pressed_on_model and not self.drag_moved and self.renderer.hit_at(x, y)
            self.dragging = False
            self.pressed_on_model = False
            if should_click:
                self._on_click(x, y)

    def _cursor_pos_callback(self, _window, _x, _y):
        if not self.dragging or self.drag_locked:
            return
        gx, gy = self._global_cursor_pos()
        if not self.drag_moved:
            dx0 = gx - self.drag_origin[0]
            dy0 = gy - self.drag_origin[1]
            if dx0 * dx0 + dy0 * dy0 < 16:
                return
            self.drag_moved = True
        dx = int(gx - self.drag_start[0])
        dy = int(gy - self.drag_start[1])
        if dx or dy:
            wx, wy = glfw.get_window_pos(self.window)
            glfw.set_window_pos(self.window, wx + dx, wy + dy)
            self.drag_start = (gx, gy)
            self.last_save = time.monotonic()

    def _poll_head_tracking(self):
        if not self.head_tracking or self.dragging or self.renderer.model is None:
            return
        now = time.monotonic()
        if now - self.last_head_track < 1.0 / 30.0:
            return
        self.last_head_track = now
        gx, gy = self._global_cursor_pos()
        wx, wy = glfw.get_window_pos(self.window)
        cx = wx + self.width * 0.5
        cy = wy + self.height * 0.5
        dx, dy = gx - cx, gy - cy
        dist_sq = dx * dx + dy * dy
        if dist_sq <= 0:
            return
        max_dist = 600.0
        if dist_sq <= max_dist * max_dist:
            local_x, local_y = gx - wx, gy - wy
        else:
            factor = max_dist / (dist_sq ** 0.5)
            local_x = self.width * 0.5 + dx * factor
            local_y = self.height * 0.5 + dy * factor
        self.renderer.drag(local_x, local_y)

    def _update_mouse_passthrough(self):
        if self.dragging:
            return
        gx, gy = self._global_cursor_pos()
        wx, wy = glfw.get_window_pos(self.window)
        inside = wx <= gx < wx + self.width and wy <= gy < wy + self.height
        if not inside:
            self._set_mouse_passthrough(False)
            return
        lx, ly = gx - wx, gy - wy
        self._set_mouse_passthrough(not self.renderer.hit_at(lx, ly))

    def _on_click(self, x: float, y: float):
        if self.radial.visible:
            self.radial.send("CLOSE")
            return
        self.renderer.start_random_motion()

    def _show_radial_menu(self, gx: int, gy: int):
        self._set_mouse_passthrough(False)
        self.radial.send(f"SHOW\t{json.dumps(self._radial_payload(gx, gy), ensure_ascii=False)}")

    def _radial_payload(self, gx: int, gy: int) -> dict:
        from i18n_manager import tr as _tr

        pixel_enabled = bool(_pixel_path_for_character(self.character))
        return {
            "x": int(gx),
            "y": int(gy),
            "fps": int(self.fps),
            "locked": bool(self.drag_locked),
            "items": [
                {
                    "action": "chat",
                    "label": _tr("PetWindow.radial_chat"),
                    "glyph": "💬",
                    "color": [138, 43, 226],
                    "enabled": True,
                },
                {
                    "action": "costume",
                    "label": _tr("PetWindow.radial_costume"),
                    "glyph": "👗",
                    "color": [220, 50, 120],
                    "enabled": True,
                },
                {
                    "action": "motion",
                    "label": _tr("PetWindow.radial_motion"),
                    "glyph": "🎬",
                    "color": [30, 144, 255],
                    "enabled": True,
                },
                {
                    "action": "pixel",
                    "label": _tr("PetWindow.radial_pixel"),
                    "glyph": "👾",
                    "color": [124, 92, 210],
                    "enabled": pixel_enabled,
                },
            ],
        }

    def _on_radial_action(self, action: str):
        if action == "chat":
            self._open_chat()
        elif action == "costume":
            self._open_settings()
        elif action == "motion":
            self.renderer.start_random_motion()
        elif action == "pixel":
            self._enable_pixel_mode_next_launch()

    def _on_lock_toggled(self, locked: bool):
        self.drag_locked = bool(locked)
        self.config = _load_config()
        self.config["drag_locked"] = self.drag_locked
        _save_config(self.config)

    def _open_chat(self):
        wx, wy = glfw.get_window_pos(self.window)
        program, arguments = process_program_and_args(str(BASE_DIR), "chat_process.py", [
            "--character", self.character,
            "--pet-x", str(wx),
            "--pet-y", str(wy),
            "--pet-w", str(self.width),
            "--pet-h", str(self.height),
            "--group-characters", json.dumps(self.group_characters, ensure_ascii=False),
        ])
        subprocess.Popen([program, *arguments], cwd=str(BASE_DIR))

    def _open_settings(self):
        program, arguments = process_program_and_args(str(BASE_DIR), "settings_process.py", [
            "--character", self.character,
            "--costume", self.costume,
            "--fps", str(self.fps),
            "--opacity", str(self.opacity),
            "--vsync", "1" if self.vsync else "0",
            "--show-launch", "0",
            "--start-on-costumes", "1",
            "--first-run-wizard", "0",
        ])
        subprocess.Popen([program, *arguments], cwd=str(BASE_DIR))

    def _enable_pixel_mode_next_launch(self):
        if not _pixel_path_for_character(self.character):
            return
        self.config = _load_config()
        self.config["pet_mode"] = "pixel"
        models = self.config.get("models", [])
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("character") == self.character and item.get("costume") == self.costume:
                    item["pet_mode"] = "pixel"
                    break
        _save_config(self.config)

    def _save_position(self):
        if self.window is None:
            return
        wx, wy = glfw.get_window_pos(self.window)
        self.config = _load_config()
        self.config["character"] = self.character
        self.config["costume"] = self.costume
        self.config["fps"] = self.fps
        self.config["opacity"] = self.opacity
        self.config["vsync"] = self.vsync
        self.config["drag_locked"] = self.drag_locked
        self.config["window_x"] = int(wx)
        self.config["window_y"] = int(wy)
        self.config["window_width"] = self.width
        self.config["window_height"] = self.height
        models = self.config.get("models", [])
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("character") == self.character and item.get("costume") == self.costume:
                    item.update({"window_x": int(wx), "window_y": int(wy), "window_width": self.width, "window_height": self.height})
                    break
        _save_config(self.config)


def main():
    os.chdir(BASE_DIR)
    args = _parse_args()
    try:
        return LightweightPet(args).run()
    except Exception as exc:
        print(f"Lightweight pet renderer failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
