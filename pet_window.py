import ctypes
import ctypes.util
import json
import os
import random
import re
import sys
import time

if os.name == "nt":
    import ctypes.wintypes

from PySide6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEasingCurve, QProcess, QEvent
from PySide6.QtGui import QColor, QIcon, QCursor, QGuiApplication, QMoveEvent, QResizeEvent
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QApplication, QSystemTrayIcon, QMenu, QStackedLayout,
)

from app_theme import apply_app_theme
from compact_ai_window import CompactAIWindow
from i18n_manager import tr as _tr, set_language
from live2d_click_actions import (
    CLICK_MOTION_NONE,
    CLICK_MOTION_RANDOM,
    click_motion_auto_buckets,
    click_motion_region_for_point,
    normalize_click_motion_actions,
)
from live2d_widget import Live2DWidget, normalize_live2d_quality
from model_manager import ModelManager
from pixel_pet_widget import PixelPetWidget, load_pixel_frames, pixel_path_for_character
from process_utils import app_base_dir, ipc_server_name, process_program_and_args
from radial_menu import RadialMenu

if sys.platform == "darwin":
    import macos_patch
else:
    macos_patch = None


WM_NCHITTEST = 0x0084
WM_NCCALCSIZE = 0x0083
HTTRANSPARENT = -1
HTCLIENT = 1
GWL_EXSTYLE = -20
HWND_TOPMOST = -1
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DONOTROUND = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

if os.name == "nt":
    _user32 = ctypes.windll.user32
    _get_window_long = _user32.GetWindowLongPtrW
    _set_window_long = _user32.SetWindowLongPtrW
    _set_window_pos = _user32.SetWindowPos
    _dwmapi = ctypes.windll.dwmapi
    _rtl_get_version = ctypes.windll.ntdll.RtlGetVersion
    _get_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    _get_window_long.restype = ctypes.c_ssize_t
    _set_window_long.argtypes = [ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _set_window_long.restype = ctypes.c_ssize_t
    _set_window_pos.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    _set_window_pos.restype = ctypes.wintypes.BOOL

    class _OSVERSIONINFOEXW(ctypes.Structure):
        _fields_ = [
            ("dwOSVersionInfoSize", ctypes.wintypes.DWORD),
            ("dwMajorVersion", ctypes.wintypes.DWORD),
            ("dwMinorVersion", ctypes.wintypes.DWORD),
            ("dwBuildNumber", ctypes.wintypes.DWORD),
            ("dwPlatformId", ctypes.wintypes.DWORD),
            ("szCSDVersion", ctypes.wintypes.WCHAR * 128),
            ("wServicePackMajor", ctypes.wintypes.WORD),
            ("wServicePackMinor", ctypes.wintypes.WORD),
            ("wSuiteMask", ctypes.wintypes.WORD),
            ("wProductType", ctypes.wintypes.BYTE),
            ("wReserved", ctypes.wintypes.BYTE),
        ]

    _rtl_get_version.argtypes = [ctypes.POINTER(_OSVERSIONINFOEXW)]
    _rtl_get_version.restype = ctypes.wintypes.LONG
    _dwm_set_window_attribute = _dwmapi.DwmSetWindowAttribute
    _dwm_set_window_attribute.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    ]
    _dwm_set_window_attribute.restype = ctypes.c_long
else:
    _get_window_long = None
    _set_window_long = None
    _set_window_pos = None
    _dwm_set_window_attribute = None

_x11 = None
_xext = None
_SHAPE_SET = 0
_SHAPE_INPUT = 2


class _XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


if sys.platform.startswith("linux"):
    try:
        _x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
        _x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        _x11.XOpenDisplay.restype = ctypes.c_void_p
        _x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        _x11.XCloseDisplay.restype = ctypes.c_int
        _x11.XFlush.argtypes = [ctypes.c_void_p]
        _x11.XFlush.restype = ctypes.c_int
        _x11.XMoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int]
        _x11.XMoveWindow.restype = ctypes.c_int
    except Exception:
        _x11 = None
    try:
        _xext = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xext") or "libXext.so.6")
        _xext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_XRectangle),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        _xext.XShapeCombineRectangles.restype = None
        _xext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_int,
        ]
        _xext.XShapeCombineMask.restype = None
    except Exception:
        _xext = None


def _is_windows_11_or_later() -> bool:
    if os.name != "nt":
        return False
    version = _OSVERSIONINFOEXW()
    version.dwOSVersionInfoSize = ctypes.sizeof(version)
    if _rtl_get_version(ctypes.byref(version)) != 0:
        return False
    return version.dwMajorVersion >= 10 and version.dwBuildNumber >= 22000


LIVE2D_BASE_WIDTH = 400
LIVE2D_BASE_HEIGHT = 500
LIVE2D_SCALE_MIN = 25
LIVE2D_SCALE_MAX = 500
LIVE2D_CONTEXT_IDLE_INTERVAL_MS = 5000
LIVE2D_DAZE_AFTER_SECONDS = 7 * 60
LIVE2D_SLEEP_AFTER_SECONDS = 18 * 60
LIVE2D_AMBIENT_COOLDOWN_SECONDS = 180
LIVE2D_MOUSE_APPROACH_COOLDOWN_SECONDS = 150
LIVE2D_MOUSE_APPROACH_MIN_IDLE_SECONDS = 12
LIVE2D_MOUSE_APPROACH_DWELL_SECONDS = 4.0
LIVE2D_MOUSE_APPROACH_RADIUS = 180
LIVE2D_MOUSE_APPROACH_EXIT_RADIUS = 270
TOPMOST_INTERACTION_REFRESH_SECONDS = 0.25


def _clamp_live2d_scale(value) -> int:
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        pct = 100
    return max(LIVE2D_SCALE_MIN, min(LIVE2D_SCALE_MAX, pct))


class PetWindow(QWidget):
    def __init__(self, live2d_module, model_manager=None,
                 character="", costume="", fps=120, opacity=1.0,
                 config_manager=None, enable_tray=True):
        super().__init__()
        icon_path = os.path.join(app_base_dir(), "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self._live2d = live2d_module
        self._model_manager = model_manager or ModelManager()
        self._current_char = character
        self._current_costume = costume
        self._fps = fps
        self._opacity = opacity
        self._vsync = True
        self._game_topmost = bool(config_manager.get("game_topmost", False)) if config_manager else False
        self._hide_live2d_model = bool(config_manager.get("hide_live2d_model", False)) if config_manager else False
        self._live2d_idle_actions_enabled = (
            bool(config_manager.get("live2d_idle_actions_enabled", True)) if config_manager else True
        )
        self._live2d_quality = "balanced"
        self._live2d_scale = 100
        self._tray_icon = None
        self._enable_tray = enable_tray
        self._cfg = config_manager
        if self._cfg:
            self._live2d_quality = normalize_live2d_quality(
                self._cfg.get("live2d_quality", "balanced")
            )
            self._live2d_scale = _clamp_live2d_scale(self._cfg.get("live2d_scale", 100) or 100)
        self._radial_menu = None
        self._compact_ai_window = None
        self._compact_ai_bounds_cache = None
        self._compact_ai_drag_bounds = None
        self._suppress_compact_ai_sync = False
        self._compact_ai_window_enabled = bool(self._cfg.get("compact_ai_window_enabled", False)) if self._cfg else False
        self._ai_event_overlay_enabled = bool(self._cfg.get("ai_event_overlay_enabled", False)) if self._cfg else False
        self._chat_integration_overlay_enabled = bool(self._cfg.get("chat_integration_overlay_enabled", True)) if self._cfg else True
        self._chat_process = None
        self._settings_process = None
        self._entrance_anim = None
        self._pixel_mode = self._configured_pet_mode() == "pixel"
        self._pixel_frames = load_pixel_frames() if self._pixel_mode else None
        self._pixel_ready = False
        self._show_pos_set = False
        self._radial_menu_prewarmed = False
        self._motion_guard_token = 0
        self._expression_guard_token = 0
        self._click_expression_hold_until = 0.0
        now = time.monotonic()
        self._last_user_interaction_at = now
        self._last_context_idle_action_at = 0.0
        self._last_mouse_approach_action_at = 0.0
        self._last_topmost_interaction_refresh_at = 0.0
        self._cursor_was_near_live2d = False
        self._cursor_near_live2d_since = 0.0
        self._cursor_near_live2d_reacted = False
        self._daily_context_idle_seen = set()
        self._mouse_passthrough = False
        # QOpenGLWidget alpha reads are not reliable during WM_NCHITTEST on
        # Windows 11; keep hit sampling on the Qt timer path.
        self._use_native_hit_test_passthrough = False
        self._passthrough_timer = QTimer(self)
        self._passthrough_timer.setInterval(50)
        self._passthrough_timer.timeout.connect(self._update_mouse_passthrough)
        self._context_idle_timer = QTimer(self)
        self._context_idle_timer.setInterval(LIVE2D_CONTEXT_IDLE_INTERVAL_MS)
        self._context_idle_timer.timeout.connect(self._tick_context_idle_behavior)
        self._ipc_socket = QLocalSocket(self)
        self._ipc_buffer = ""
        self._ipc_reconnect_timer = QTimer(self)
        self._ipc_reconnect_timer.setInterval(1000)
        self._ipc_reconnect_timer.timeout.connect(self._connect_ipc_socket)
        self._ipc_socket.connected.connect(self._on_ipc_connected)
        self._ipc_socket.readyRead.connect(self._read_ipc_messages)
        self._ipc_socket.disconnected.connect(self._schedule_ipc_reconnect)
        self._ipc_socket.errorOccurred.connect(lambda _error: self._schedule_ipc_reconnect())
        self._position_save_timer = QTimer(self)
        self._position_save_timer.setSingleShot(True)
        self._position_save_timer.setInterval(250)
        self._position_save_timer.timeout.connect(self._save_config)

        self._init_ui()
        if self._enable_tray:
            self._init_tray()
        self._load_initial_model()
        self._passthrough_timer.start()
        self._context_idle_timer.start()
        self._apply_game_topmost_state()
        self._connect_ipc_socket()
        QApplication.instance().installEventFilter(self)

        self.setWindowOpacity(self._opacity)

    def _init_ui(self):
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if self._should_bypass_x11_window_manager():
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setAutoFillBackground(False)

        self.resize(*self._live2d_size())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._stack)

        self._live2d_widget = Live2DWidget(self)
        self._live2d_widget.set_live2d_module(self._live2d)
        self._live2d_widget.set_window_drag_callback(self._on_drag)
        self._live2d_widget.set_click_callback(self._on_click)
        self._live2d_widget.set_right_click_callback(self._on_right_click)
        self._live2d_widget.set_fps(self._fps)
        self._live2d_widget.set_render_quality(self._live2d_quality)
        self._live2d_widget.model_loaded.connect(self._on_live2d_model_loaded)
        self._stack.addWidget(self._live2d_widget)

        self._pixel_widget = PixelPetWidget(self)
        self._pixel_widget.set_window_drag_callback(self._on_drag)
        self._pixel_widget.set_click_callback(self._on_click)
        self._pixel_widget.set_right_click_callback(self._on_right_click)
        self._stack.addWidget(self._pixel_widget)

    @staticmethod
    def _should_bypass_x11_window_manager() -> bool:
        if not sys.platform.startswith("linux"):
            return False
        try:
            return "xcb" in QGuiApplication.platformName().lower()
        except Exception:
            return False

    def nativeEvent(self, event_type, message):
        if os.name == "nt":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCCALCSIZE:
                    return True, 0
                if msg.message == WM_NCHITTEST and self._use_native_hit_test_passthrough:
                    lparam = int(msg.lParam)
                    x = ctypes.c_short(lparam & 0xFFFF).value
                    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    point = QPoint(x, y)
                    hit = self._is_interaction_hit(point)
                    if not hit:
                        return True, HTTRANSPARENT
                    return True, HTCLIENT
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _apply_windows_frameless_fix(self):
        if os.name != "nt":
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        if _is_windows_11_or_later() and _dwm_set_window_attribute is not None:
            preference = ctypes.c_int(DWMWCP_DONOTROUND)
            try:
                _dwm_set_window_attribute(
                    hwnd,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(preference),
                    ctypes.sizeof(preference),
                )
            except Exception:
                pass
        _set_window_pos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        self._apply_no_activate_to_hwnd(hwnd)
        self._enforce_game_topmost()

    def _apply_no_activate_to_hwnd(self, hwnd: int):
        if os.name != "nt" or not hwnd:
            return
        style = _get_window_long(hwnd, GWL_EXSTYLE)
        if style & WS_EX_NOACTIVATE:
            return
        _set_window_long(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        _set_window_pos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def _apply_game_topmost_state(self):
        if os.name == "nt":
            # Re-applying HWND_TOPMOST periodically pushes the pet to the front
            # of the topmost z-order, covering menus and system overlays. Apply
            # it only when the window appears or the setting changes.
            self._enforce_game_topmost()
        elif sys.platform == "darwin" and macos_patch is not None and self.isVisible():
            # macOS: bump to pop-up-menu level (above almost everything) when
            # game_topmost is on; otherwise sit at status-bar level so the
            # window can still be dragged past the menu bar.
            if self._game_topmost:
                macos_patch.set_window_level_above_menu_bar(self)
            else:
                macos_patch.set_window_level_status_bar(self)

    def _enforce_game_topmost(self):
        if os.name != "nt" or not self.isVisible():
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        _set_window_pos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def _refresh_topmost_for_interaction(self, *, force: bool = False):
        if os.name != "nt" or not self.isVisible():
            return
        now = time.monotonic()
        if (
            not force
            and now - self._last_topmost_interaction_refresh_at < TOPMOST_INTERACTION_REFRESH_SECONDS
        ):
            return
        self._last_topmost_interaction_refresh_at = now
        self._enforce_game_topmost()

    def _apply_macos_window_polish(self):
        if sys.platform != "darwin" or macos_patch is None:
            return
        macos_patch.set_window_no_shadow(self)
        # Status-bar level (25) bypasses macOS's auto-constrain so the user can
        # drag the pet anywhere on screen — the Live2D widget has transparent
        # padding around the visible character that would otherwise hit the
        # menu bar before the character does.
        if self._game_topmost:
            macos_patch.set_window_level_above_menu_bar(self)
        else:
            macos_patch.set_window_level_status_bar(self)
        # Qt.Tool windows are NSPanels, which AppKit hides whenever the app
        # deactivates — clicking any other window would otherwise make the pet
        # vanish. Force the panel to stay visible across app focus changes and
        # across all Spaces.
        macos_patch.set_hides_on_deactivate(self, False)
        macos_patch.set_collection_behavior(self, macos_patch.PET_COLLECTION_BEHAVIOR)

    def eventFilter(self, obj, event):
        if self._radial_menu is not None and self._radial_menu.isVisible():
            event_type = event.type()
            if event_type == QEvent.Type.ApplicationDeactivate:
                self._radial_menu.dismiss()
            elif obj is self and event_type == QEvent.Type.WindowDeactivate:
                self._radial_menu.dismiss()
        return super().eventFilter(obj, event)

    def _set_mouse_passthrough(self, enabled: bool):
        if self._use_native_hit_test_passthrough or enabled == self._mouse_passthrough:
            return
        if os.name == "nt":
            self._apply_passthrough_to_hwnd(int(self.winId()), enabled)
        elif sys.platform == "darwin" and macos_patch is not None:
            macos_patch.set_ignores_mouse_events(self, enabled)
        elif sys.platform.startswith("linux"):
            if not self._apply_passthrough_to_x11_window(int(self.winId()), enabled):
                return
        else:
            return
        self._mouse_passthrough = enabled

    def _apply_passthrough_to_hwnd(self, hwnd: int, enabled: bool):
        if not hwnd:
            return
        style = _get_window_long(hwnd, GWL_EXSTYLE)
        if enabled:
            style |= WS_EX_TRANSPARENT
        else:
            style &= ~WS_EX_TRANSPARENT
        _set_window_long(hwnd, GWL_EXSTYLE, style)
        _set_window_pos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def _apply_passthrough_to_x11_window(self, window: int, enabled: bool) -> bool:
        if not self._should_bypass_x11_window_manager() or _x11 is None or _xext is None or not window:
            return False
        display = _x11.XOpenDisplay(None)
        if not display:
            return False
        try:
            if enabled:
                _xext.XShapeCombineRectangles(
                    display,
                    ctypes.c_ulong(window),
                    _SHAPE_INPUT,
                    0,
                    0,
                    None,
                    0,
                    _SHAPE_SET,
                    0,
                )
            else:
                _xext.XShapeCombineMask(
                    display,
                    ctypes.c_ulong(window),
                    _SHAPE_INPUT,
                    0,
                    0,
                    0,
                    _SHAPE_SET,
                )
            _x11.XFlush(display)
            return True
        finally:
            _x11.XCloseDisplay(display)

    def _is_interaction_hit(self, global_pos: QPoint) -> bool:
        if self._pixel_mode:
            return self._pixel_widget.is_sprite_hit_at_global(global_pos)
        return self._live2d_widget.is_model_hit_at_global(global_pos)

    def _update_mouse_passthrough(self):
        if self._use_native_hit_test_passthrough or not self.isVisible():
            return
        if os.name != "nt" and sys.platform != "darwin" and not sys.platform.startswith("linux"):
            return
        if self._live2d_widget._dragging or self._pixel_widget._dragging:
            return
        global_pos = QCursor.pos()
        if not self.geometry().contains(global_pos):
            self._set_mouse_passthrough(False)
            return
        hit = self._is_interaction_hit(global_pos)
        self._set_mouse_passthrough(not hit)

    def set_fps(self, fps: int):
        self._fps = fps
        self._live2d_widget.set_fps(fps)

    def set_vsync(self, enabled: bool):
        self._vsync = enabled
        self._live2d_widget.set_vsync(enabled)

    def set_game_topmost(self, enabled: bool):
        self._game_topmost = bool(enabled)
        self._apply_game_topmost_state()

    def set_hide_live2d_model(self, enabled: bool):
        self._hide_live2d_model = bool(enabled)
        if self._hide_live2d_model:
            if self.isVisible():
                self.hide()
        elif not self.isVisible():
            self.show()

    def set_live2d_idle_actions_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if self._live2d_idle_actions_enabled == enabled:
            return
        self._live2d_idle_actions_enabled = enabled
        self._motion_guard_token += 1
        self._last_context_idle_action_at = time.monotonic()
        self._cursor_was_near_live2d = False
        self._cursor_near_live2d_since = 0.0
        self._cursor_near_live2d_reacted = False
        if not enabled:
            model = self._live2d_widget.model
            if model is not None:
                try:
                    model.ClearMotions()
                except Exception:
                    pass
        else:
            QTimer.singleShot(
                50,
                lambda t=self._motion_guard_token: self._restore_default_motion(t, force_clear=False),
            )

    def moveEvent(self, event: QMoveEvent):
        super().moveEvent(event)
        if not self._suppress_compact_ai_sync and not self._is_pet_dragging():
            self._sync_compact_ai_window()
        self._schedule_position_save()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self._sync_compact_ai_window()
        self._schedule_position_save()

    def hideEvent(self, event):
        if self._compact_ai_window is not None:
            self._compact_ai_window.hide()
        super().hideEvent(event)

    def closeEvent(self, event):
        self._close_chat_process()
        self._close_compact_ai_window()
        self._close_settings_process()
        self._save_config()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def _schedule_position_save(self):
        if not self._cfg or not getattr(self, "_show_pos_set", False):
            return
        self._position_save_timer.start()

    def _init_tray(self):
        self._tray_icon = QSystemTrayIcon(self)
        icon_path = os.path.join(app_base_dir(), "logo.ico")
        if os.path.exists(icon_path):
            self._tray_icon.setIcon(QIcon(icon_path))
        else:
            self._tray_icon.setIcon(QIcon())

        self._tray_icon.setToolTip(_tr("PetWindow.tray_tooltip"))

        menu = QMenu()

        show_action = menu.addAction(_tr("PetWindow.tray_show_hide"))
        show_action.triggered.connect(self._toggle_visible)

        chat_action = menu.addAction(_tr("PetWindow.tray_chat"))
        chat_action.triggered.connect(self._open_chat)

        settings_action = menu.addAction(_tr("PetWindow.tray_settings"))
        settings_action.triggered.connect(self._open_settings)

        menu.addSeparator()

        opacity_menu = menu.addMenu(_tr("PetWindow.tray_opacity"))
        for pct in [100, 80, 60, 40, 20]:
            act = opacity_menu.addAction(_tr("PetWindow.opacity_pct", pct=pct))
            act.triggered.connect(lambda checked, v=pct: self.set_opacity(v / 100.0))

        menu.addSeparator()

        exit_action = menu.addAction(_tr("PetWindow.tray_exit"))
        exit_action.triggered.connect(self._quit)

        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _load_initial_model(self):
        if not self._current_char or not self._current_costume:
            chars = self._model_manager.characters
            if not chars:
                return
            self._current_char = chars[0]
            self._current_costume = self._model_manager.get_default_costume(self._current_char)

        path = self._model_manager.get_model_json_path(
            self._current_char, self._current_costume
        )
        if path:
            self._live2d_widget.set_model_path(path)
            if self._pixel_mode and not self._enable_pixel_mode(save=False):
                self._enable_live2d_mode(save=False)
            self._update_tooltip()

    def _current_model_entry(self) -> dict:
        if not self._cfg:
            return {}
        models = self._cfg.get("models", [])
        fallback = None
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict) or item.get("character") != self._current_char:
                    continue
                if item.get("costume") == self._current_costume:
                    return self._with_saved_action_profile(item)
                if fallback is None:
                    fallback = item
        return self._with_saved_action_profile(fallback or {})

    def _with_saved_action_profile(self, entry: dict) -> dict:
        if not self._cfg or not hasattr(self._cfg, "get_model_action_profile"):
            return entry
        profile = self._cfg.get_model_action_profile(self._current_char, self._current_costume)
        if not profile:
            return entry
        merged = dict(entry)
        for key in ("default_motion", "default_expression", "click_motion_actions"):
            if not merged.get(key) and profile.get(key):
                merged[key] = profile[key]
        return merged

    def _configured_pet_mode(self) -> str:
        if not self._cfg:
            return "live2d"
        entry = self._current_model_entry()
        mode = entry.get("pet_mode") if entry else None
        if mode in {"live2d", "pixel"}:
            return mode
        models = self._cfg.get("models", [])
        if isinstance(models, list) and len(models) > 1:
            return "live2d"
        mode = self._cfg.get("pet_mode", "live2d")
        return mode if mode in {"live2d", "pixel"} else "live2d"

    def _switch_model(self, character: str, costume: str):
        path = self._model_manager.get_model_json_path(character, costume)
        if not path:
            return
        self._note_user_interaction()
        self._close_chat_process()
        self._current_char = character
        self._current_costume = costume
        self._live2d_widget.set_model_path(path)
        self._sync_current_model_entry(path)
        if self._pixel_mode and not self._load_pixel_for_current_character():
            self._enable_live2d_mode(save=False)
        self._update_tooltip()
        self._sync_compact_ai_window(allow_create=True)
        self._save_config()

    def _on_live2d_model_loaded(self):
        self._motion_guard_token += 1
        self._last_context_idle_action_at = 0.0
        self._cursor_was_near_live2d = False
        self._cursor_near_live2d_since = 0.0
        self._cursor_near_live2d_reacted = False
        QTimer.singleShot(120, lambda t=self._motion_guard_token: self._restore_default_motion(t, force_clear=False))
        QTimer.singleShot(0, lambda: self._sync_compact_ai_window(allow_create=True))

    def _note_user_interaction(self):
        self._last_user_interaction_at = time.monotonic()
        self._last_context_idle_action_at = self._last_user_interaction_at

    def _tick_context_idle_behavior(self):
        if not self._live2d_idle_actions_enabled or self._pixel_mode or not self.isVisible():
            return
        model = self._live2d_widget.model
        if model is None or self._is_pet_dragging():
            return
        self._maybe_trigger_mouse_approach_behavior()
        if self._radial_menu is not None and self._radial_menu.isVisible():
            return
        now = time.monotonic()
        if now - self._last_context_idle_action_at < LIVE2D_AMBIENT_COOLDOWN_SECONDS:
            return
        idle_seconds = now - self._last_user_interaction_at
        action_kind = self._context_idle_kind(idle_seconds)
        if not action_kind:
            return
        if self._start_context_idle_behavior(action_kind):
            self._last_context_idle_action_at = now
            if action_kind == "morning":
                self._daily_context_idle_seen.add(f"{time.strftime('%Y-%m-%d')}:morning")

    def _context_idle_kind(self, idle_seconds: float) -> str:
        hour = time.localtime().tm_hour
        today = time.strftime("%Y-%m-%d")
        if 5 <= hour < 10 and f"{today}:morning" not in self._daily_context_idle_seen:
            return "morning"
        if idle_seconds >= LIVE2D_SLEEP_AFTER_SECONDS:
            return "sleep"
        if (hour >= 23 or hour < 5) and idle_seconds >= 90:
            return "late_night"
        if idle_seconds >= LIVE2D_DAZE_AFTER_SECONDS:
            return "daze"
        return ""

    def _maybe_trigger_mouse_approach_behavior(self):
        if not self._live2d_idle_actions_enabled:
            return
        if self._radial_menu is not None and self._radial_menu.isVisible():
            return
        cursor = QCursor.pos()
        approach_radius = max(
            LIVE2D_MOUSE_APPROACH_RADIUS,
            min(360, int(max(self.width(), self.height()) * 0.42)),
        )
        exit_radius = max(LIVE2D_MOUSE_APPROACH_EXIT_RADIUS, approach_radius + 80)
        if not self.geometry().adjusted(
            -exit_radius,
            -exit_radius,
            exit_radius,
            exit_radius,
        ).contains(cursor):
            self._cursor_was_near_live2d = False
            self._cursor_near_live2d_since = 0.0
            self._cursor_near_live2d_reacted = False
            return
        center = self.geometry().center()
        dx = cursor.x() - center.x()
        dy = cursor.y() - center.y()
        dist_sq = dx * dx + dy * dy
        if dist_sq > exit_radius * exit_radius:
            self._cursor_was_near_live2d = False
            self._cursor_near_live2d_since = 0.0
            self._cursor_near_live2d_reacted = False
            return
        near = dist_sq <= approach_radius * approach_radius
        if not near:
            self._cursor_near_live2d_since = 0.0
            return
        now = time.monotonic()
        if not self._cursor_was_near_live2d:
            self._cursor_was_near_live2d = True
            self._cursor_near_live2d_since = now
            self._cursor_near_live2d_reacted = False
            return
        if self._cursor_near_live2d_reacted:
            return
        if not self._cursor_near_live2d_since:
            self._cursor_near_live2d_since = now
            return
        if now - self._cursor_near_live2d_since < LIVE2D_MOUSE_APPROACH_DWELL_SECONDS:
            return
        self._cursor_near_live2d_reacted = True
        if now - self._last_user_interaction_at < LIVE2D_MOUSE_APPROACH_MIN_IDLE_SECONDS:
            return
        if now - self._last_mouse_approach_action_at < LIVE2D_MOUSE_APPROACH_COOLDOWN_SECONDS:
            return
        if self._start_context_idle_behavior("approach"):
            self._last_mouse_approach_action_at = now

    def _start_context_idle_behavior(self, kind: str) -> bool:
        if not self._live2d_idle_actions_enabled:
            return False
        model = self._live2d_widget.model
        if model is None:
            return False
        try:
            if not model.IsMotionFinished():
                return False
        except Exception:
            pass

        motion_names = self._current_motion_names()
        motion = self._choose_context_idle_motion(kind, motion_names)
        expression = self._choose_context_idle_expression(kind)
        if not motion and not expression:
            return False

        started = False
        if motion:
            self._motion_guard_token += 1
            token = self._motion_guard_token
            try:
                model.StartRandomMotion(
                    motion,
                    priority=self._live2d.MotionPriority.FORCE,
                    onFinishMotionHandler=self._on_motion_finished,
                )
                started = True
            except Exception:
                try:
                    model.StartMotion(
                        motion,
                        0,
                        self._live2d.MotionPriority.FORCE,
                        onFinishMotionHandler=self._on_motion_finished,
                    )
                    started = True
                except Exception:
                    started = False
            if started:
                QTimer.singleShot(9000, lambda t=token: self._clear_motion_if_current(t))
                QTimer.singleShot(1800, lambda t=token: self._restore_default_if_finished(t))

        expression_applied = False
        if expression:
            self._expression_guard_token += 1
            token = self._expression_guard_token
            try:
                model.SetExpression(expression)
                expression_applied = True
                QTimer.singleShot(6000, lambda t=token: self._restore_default_expression_if_current(t))
            except Exception:
                pass
        return started or expression_applied

    def _current_motion_names(self) -> list[str]:
        model = self._live2d_widget.model
        if model is None:
            return []
        try:
            return list(model.modelSetting.getMotionNames())
        except Exception:
            return []

    def _choose_context_idle_motion(self, kind: str, motion_names: list[str]) -> str:
        if not motion_names:
            return ""
        if kind == "approach":
            weighted_tags = (
                ("smile", 3),
                ("nf", 3),
                ("idle02", 2),
                ("surprised", 1),
            )
            choices = []
            for tag, weight in weighted_tags:
                motion = self._resolve_motion_tag(tag, motion_names)
                if motion:
                    choices.extend([motion] * weight)
            return random.choice(choices) if choices else ""
        tags_by_kind = {
            "morning": ("stretch", "akubi", "sigh", "smile", "kime", "idle02"),
            "late_night": ("sleep", "akubi", "sigh", "sad", "idle02"),
            "sleep": ("sleep", "akubi", "sigh", "sad", "idle02"),
            "daze": ("stare", "mitore", "thinking", "eeto", "odoodo", "nf", "idle02"),
            "approach": ("surprised", "smile", "nf", "idle02"),
        }
        for tag in tags_by_kind.get(kind, ()):
            motion = self._resolve_motion_tag(tag, motion_names)
            if motion:
                return motion
        if kind in {"sleep", "late_night"}:
            idle_names = [name for name in motion_names if str(name).lower().startswith("idle")]
            return random.choice(idle_names) if idle_names else ""
        return ""

    def _choose_context_idle_expression(self, kind: str) -> str:
        if kind == "approach":
            weighted_tags = (
                ("smile", 4),
                ("default", 3),
                ("idle", 2),
                ("surprised", 1),
            )
            choices = []
            for tag, weight in weighted_tags:
                expression = self._find_expression_tag(tag)
                if expression:
                    choices.extend([expression] * weight)
            return random.choice(choices) if choices else ""
        tags_by_kind = {
            "morning": ("smile", "default", "idle"),
            "late_night": ("sad", "sleep", "idle", "default"),
            "sleep": ("sad", "sleep", "idle", "default"),
            "daze": ("idle", "default", "sad"),
            "approach": ("surprised", "smile", "default"),
        }
        for tag in tags_by_kind.get(kind, ()):
            expression = self._find_expression_tag(tag)
            if expression:
                return expression
        return ""

    def _find_expression_tag(self, tag: str) -> str:
        tag = str(tag or "").strip().lower()
        if not tag:
            return ""
        model = self._live2d_widget.model
        if model is None or not hasattr(model, "expressions"):
            return ""
        try:
            names = list(model.expressions.keys())
        except Exception:
            return ""
        char_prefix = (self._current_char or "").lower()
        for name in names:
            name_low = str(name).lower()
            name_base = os.path.splitext(name_low)[0]
            if name_low == tag or name_base == tag:
                return name
            if char_prefix and name_base == f"{char_prefix}_{tag}":
                return name
        for name in names:
            name_base = os.path.splitext(str(name).lower())[0]
            if name_base.endswith(f"_{tag}") or name_base.startswith(f"{tag}"):
                return name
        return ""

    def _apply_settings(self, data: dict):
        if data.get("language"):
            set_language(str(data["language"]))
        compact_keys = {
            "compact_ai_window_enabled",
            "compact_ai_window_opacity",
            "compact_ai_window_font_size",
            "compact_ai_window_background_color",
            "compact_ai_window_text_color",
            "ai_event_overlay_enabled",
            "chat_integration_enabled",
            "chat_integration_overlay_enabled",
            "chat_integration_include_context",
            "chat_integration_port",
            "chat_integration_token",
            "user_avatar_color",
            "user_avatar_path",
            "language",
            "hide_live2d_model",
            "live2d_idle_actions_enabled",
        }
        if self._cfg and any(key in data for key in compact_keys):
            self._cfg.load()
            if "compact_ai_window_enabled" in data:
                self._cfg.set("compact_ai_window_enabled", bool(data["compact_ai_window_enabled"]))
            if "compact_ai_window_opacity" in data:
                self._cfg.set("compact_ai_window_opacity", data["compact_ai_window_opacity"])
            if "compact_ai_window_font_size" in data:
                self._cfg.set("compact_ai_window_font_size", data["compact_ai_window_font_size"])
            if "compact_ai_window_background_color" in data:
                self._cfg.set("compact_ai_window_background_color", data["compact_ai_window_background_color"])
            if "compact_ai_window_text_color" in data:
                self._cfg.set("compact_ai_window_text_color", data["compact_ai_window_text_color"])
            if "ai_event_overlay_enabled" in data:
                self._cfg.set("ai_event_overlay_enabled", bool(data["ai_event_overlay_enabled"]))
            if "chat_integration_overlay_enabled" in data:
                self._cfg.set("chat_integration_overlay_enabled", bool(data["chat_integration_overlay_enabled"]))
            if "chat_integration_enabled" in data:
                self._cfg.set("chat_integration_enabled", bool(data["chat_integration_enabled"]))
            if "chat_integration_include_context" in data:
                self._cfg.set("chat_integration_include_context", bool(data["chat_integration_include_context"]))
            if "chat_integration_port" in data:
                self._cfg.set("chat_integration_port", data["chat_integration_port"])
            if "chat_integration_token" in data:
                self._cfg.set("chat_integration_token", data["chat_integration_token"])
            if "hide_live2d_model" in data:
                self._cfg.set("hide_live2d_model", bool(data["hide_live2d_model"]))
            if "live2d_idle_actions_enabled" in data:
                self._cfg.set("live2d_idle_actions_enabled", bool(data["live2d_idle_actions_enabled"]))
            if "user_avatar_color" in data:
                self._cfg.set("user_avatar_color", data["user_avatar_color"])
            if "user_avatar_path" in data:
                self._cfg.set("user_avatar_path", data["user_avatar_path"])
            if data.get("language"):
                self._cfg.set("language", str(data["language"]))
            self._cfg.save()
        if "compact_ai_window_enabled" in data:
            self._compact_ai_window_enabled = bool(data["compact_ai_window_enabled"])
        if "ai_event_overlay_enabled" in data:
            self._ai_event_overlay_enabled = bool(data["ai_event_overlay_enabled"])
        if "chat_integration_overlay_enabled" in data:
            self._chat_integration_overlay_enabled = bool(data["chat_integration_overlay_enabled"])
        if data.get("compact_ai_window_reset_position") and self._compact_ai_window is not None:
            self._compact_ai_window.reset_position_offset()
        if "fps" in data:
            self.set_fps(data["fps"])
        if "opacity" in data:
            self.set_opacity(data["opacity"])
        if "dark_theme" in data:
            apply_app_theme(data["dark_theme"])
        if "vsync" in data:
            self._vsync = data["vsync"]
            self._live2d_widget.set_vsync(data["vsync"])
        if "game_topmost" in data:
            self.set_game_topmost(data["game_topmost"])
        if "hide_live2d_model" in data:
            self.set_hide_live2d_model(data["hide_live2d_model"])
        if "live2d_idle_actions_enabled" in data:
            self.set_live2d_idle_actions_enabled(data["live2d_idle_actions_enabled"])
        if "live2d_quality" in data:
            self._live2d_quality = normalize_live2d_quality(data["live2d_quality"])
            self._live2d_widget.set_render_quality(self._live2d_quality)
        if "live2d_scale" in data:
            self.set_live2d_scale(data["live2d_scale"])
        self._sync_compact_ai_window(allow_create=True)
        if self._cfg and ("models" in data or "model_action_settings" in data):
            self._cfg.load()
        if "model_action_settings" in data and self._cfg:
            self._cfg.set("model_action_settings", data["model_action_settings"])
        if "models" in data and self._cfg:
            self._cfg.set("models", data["models"])
            self._cfg.save()
        self._save_config()

    def _live2d_size(self):
        scale = self._live2d_scale / 100.0
        return int(round(LIVE2D_BASE_WIDTH * scale)), int(round(LIVE2D_BASE_HEIGHT * scale))

    def set_live2d_scale(self, value):
        self._live2d_scale = _clamp_live2d_scale(value)
        if not self._pixel_mode:
            self.resize(*self._live2d_size())
        self._sync_compact_ai_window()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_settings()

    def _update_tooltip(self):
        display = self._model_manager.get_display_name(self._current_char)
        costume_name = self._model_manager.get_costume_display_name(
            self._current_char, self._current_costume
        )
        if self._tray_icon is None:
            return
        self._tray_icon.setToolTip(
            _tr("PetWindow.tray_tooltip_with_model", display=display, costume=costume_name)
        )

    def _on_drag(self, dx: int, dy: int):
        self._note_user_interaction()
        self._refresh_topmost_for_interaction()
        self._set_mouse_passthrough(False)
        self._suppress_compact_ai_sync = True
        try:
            self._move_unconstrained(self.x() + dx, self.y() + dy)
        finally:
            self._suppress_compact_ai_sync = False
        self._move_compact_ai_with_pet(dx, dy)

    def _move_unconstrained(self, x: int, y: int):
        if not self._should_bypass_x11_window_manager() or _x11 is None:
            self.move(x, y)
            return
        display = _x11.XOpenDisplay(None)
        if not display:
            self.move(x, y)
            return
        try:
            _x11.XMoveWindow(display, ctypes.c_ulong(int(self.winId())), int(x), int(y))
            _x11.XFlush(display)
        finally:
            _x11.XCloseDisplay(display)

    def _is_pet_dragging(self) -> bool:
        return bool(
            getattr(self._live2d_widget, "_dragging", False)
            or getattr(self._pixel_widget, "_dragging", False)
        )

    def _on_click(self, x: float | None = None, y: float | None = None, area_name: str = ""):
        self._note_user_interaction()
        self._refresh_topmost_for_interaction(force=True)
        if self._radial_menu and self._radial_menu.isVisible():
            self._radial_menu.dismiss()
            return
        if self._pixel_mode or x is None or y is None:
            return
        self._trigger_click_motion(float(x), float(y), area_name)

    def _trigger_click_motion(self, x: float, y: float, area_name: str = ""):
        model = self._live2d_widget.model
        if model is None:
            return
        area_bounds = self._click_motion_area_bounds(area_name)
        region = click_motion_region_for_point(
            x,
            y,
            self._live2d_widget.width(),
            self._live2d_widget.height(),
            area_name,
            area_bounds,
        )
        feedback = self._configured_click_motion_feedback(region)
        configured_motion = feedback.get("motion", "")
        configured_expression = feedback.get("expression", "")
        if configured_motion == CLICK_MOTION_NONE:
            return
        if configured_motion == CLICK_MOTION_RANDOM:
            self._start_click_motion("", configured_expression)
            return
        if configured_motion:
            self._start_click_motion(configured_motion, configured_expression)
            return

        motion = self._choose_click_action_motion(region)
        if motion:
            self._start_click_motion(motion, configured_expression)
        else:
            self._start_click_motion("", configured_expression)

    def _click_motion_area_bounds(self, area_name: str):
        area_name = str(area_name or "").strip().lower()
        visible_bounds = self._live2d_widget.visible_model_bounds()
        if area_name in {"head", "face"}:
            return visible_bounds or self._live2d_widget.hit_area_bounds(area_name)
        if area_name in {"body", "hit", ""}:
            return (
                visible_bounds
                or self._live2d_widget.hit_area_bounds("body")
                or self._live2d_widget.hit_area_union_bounds()
            )
        return visible_bounds or self._live2d_widget.hit_area_bounds(area_name)

    def _configured_click_motion_feedback(self, region: str) -> dict[str, str]:
        try:
            motion_names = list(self._live2d_widget.model.modelSetting.getMotionNames())
        except Exception:
            motion_names = []
        expression_names = self._current_expression_names()
        actions = normalize_click_motion_actions(
            self._current_model_entry().get("click_motion_actions", {}),
            motion_names,
            expression_names,
        )
        return actions.get(region, {})

    def _current_expression_names(self) -> list[str]:
        model = self._live2d_widget.model
        if model is None or not hasattr(model, "expressions"):
            return []
        try:
            return list(model.expressions.keys())
        except Exception:
            return []

    def _start_click_motion(self, motion_name: str = "", expression: str = ""):
        model = self._live2d_widget.model
        if model is None:
            return
        if expression:
            self._apply_click_expression(expression)
        try:
            self._motion_guard_token += 1
            token = self._motion_guard_token
            if motion_name:
                try:
                    model.StartRandomMotion(
                        motion_name,
                        priority=self._live2d.MotionPriority.FORCE,
                    )
                except Exception:
                    model.StartMotion(
                        motion_name,
                        0,
                        self._live2d.MotionPriority.FORCE,
                    )
            else:
                model.StartRandomMotion(priority=self._live2d.MotionPriority.FORCE)
            if expression:
                QTimer.singleShot(80, lambda t=self._expression_guard_token, e=expression: self._set_click_expression_if_current(t, e))
            QTimer.singleShot(9000, lambda t=token: self._clear_motion_if_current(t))
            QTimer.singleShot(3200, lambda t=token: self._restore_default_if_finished(t))
        except Exception:
            if expression:
                QTimer.singleShot(5000, lambda t=self._expression_guard_token: self._restore_default_expression_if_current(t))

    def _apply_click_expression(self, expression: str):
        expression = str(expression or "").strip()
        if not expression:
            return
        model = self._live2d_widget.model
        if model is None:
            return
        self._expression_guard_token += 1
        token = self._expression_guard_token
        self._click_expression_hold_until = max(
            self._click_expression_hold_until,
            time.monotonic() + 5.0,
        )
        self._set_click_expression_if_current(token, expression)
        QTimer.singleShot(5000, lambda t=token: self._restore_default_expression_if_current(t))

    def _set_click_expression_if_current(self, token: int, expression: str):
        if token != self._expression_guard_token:
            return
        model = self._live2d_widget.model
        if model is None:
            return
        try:
            if hasattr(model, "expressions") and expression not in model.expressions:
                return
            model.SetExpression(expression)
        except Exception:
            return

    def _choose_click_action_motion(self, region: str) -> str:
        try:
            motion_names = list(self._live2d_widget.model.modelSetting.getMotionNames())
        except Exception:
            motion_names = []
        if not motion_names:
            return ""

        for bucket in click_motion_auto_buckets(region):
            available = [
                motion for tag in bucket
                if (motion := self._resolve_motion_tag(tag, motion_names))
            ]
            if available:
                return random.choice(available)

        non_idle = [
            name for name in motion_names
            if not str(name).lower().startswith(("idle", "sys-"))
        ]
        return random.choice(non_idle) if non_idle else ""

    def _resolve_motion_tag(self, tag: str, motion_names: list[str]) -> str:
        tag_low = tag.lower()
        char_lower = (self._current_char or "").lower()
        candidates = [tag_low]
        if tag_low == "thinking":
            candidates.extend(["nf", "nnf", "eeto", "odoodo"])

        matches = []
        for candidate in candidates:
            candidate_prefix = f"{char_lower}_{candidate}" if char_lower else candidate
            for motion_name in motion_names:
                motion_low = str(motion_name).lower()
                if motion_low == candidate or motion_low.startswith(candidate):
                    matches.append(str(motion_name))
                elif motion_low == candidate_prefix or motion_low.startswith(candidate_prefix):
                    matches.append(str(motion_name))
                elif re.search(rf"(^|[_\-]){re.escape(candidate)}($|[_\-]?\d)", motion_low):
                    matches.append(str(motion_name))
        return random.choice(matches) if matches else ""

    def _on_right_click(self, gx: int, gy: int):
        self._note_user_interaction()
        self._refresh_topmost_for_interaction(force=True)
        self._set_mouse_passthrough(False)
        radial_menu = self._ensure_radial_menu()
        if radial_menu.isVisible():
            radial_menu.dismiss()
            return
        self._refresh_radial_menu()
        radial_menu.show_at(QPoint(gx, gy))

    def _ensure_radial_menu(self) -> RadialMenu:
        if self._radial_menu is not None:
            return self._radial_menu

        radial_menu = RadialMenu()
        radial_menu.lock_toggled.connect(self._on_lock_toggled)
        radial_menu.add_item(
            "", _tr("PetWindow.radial_chat"), QColor(138, 43, 226),
            glyph="\U0001F4AC",
            on_click=self._on_radial_chat,
        )
        radial_menu.add_item(
            "", _tr("PetWindow.radial_costume"), QColor(220, 50, 120),
            glyph="\U0001F457",
            on_click=self._on_radial_costume,
        )
        radial_menu.add_item(
            "", _tr("PetWindow.radial_motion"), QColor(30, 144, 255),
            glyph="\U0001F3AC",
            on_click=self._on_radial_motion,
        )
        radial_menu.add_item(
            "", _tr("PetWindow.radial_pixel"), QColor(34, 180, 140),
            glyph="\U0001F47E",
            on_click=self._on_radial_pixel,
            enabled=False,
        )
        self._radial_menu = radial_menu
        return radial_menu

    def _refresh_radial_menu(self):
        if self._radial_menu is None:
            return
        self._radial_menu.set_animation_fps(self._fps)
        self._radial_menu.set_locked(self._live2d_widget._drag_locked)
        pixel_label = _tr("PetWindow.radial_live2d") if self._pixel_mode else _tr("PetWindow.radial_pixel")
        pixel_glyph = "L2D" if self._pixel_mode else "\U0001F47E"
        pixel_enabled = True if self._pixel_mode else bool(pixel_path_for_character(self._current_char))
        self._radial_menu.update_item(
            3,
            label=pixel_label,
            glyph=pixel_glyph,
            enabled=pixel_enabled,
        )

    def _prewarm_radial_menu(self):
        if self._radial_menu_prewarmed or not self.isVisible():
            return
        radial_menu = self._ensure_radial_menu()
        self._refresh_radial_menu()
        radial_menu.prepare_for_show()
        self._radial_menu_prewarmed = True

    def _on_radial_chat(self):
        self._note_user_interaction()
        self._open_chat()

    def _open_chat(self):
        if self._chat_process is not None and self._chat_process.state() != QProcess.ProcessState.NotRunning:
            return

        base_dir = str(app_base_dir())
        process = QProcess(self)
        program, arguments = process_program_and_args(base_dir, "chat_process.py", [
            "--character", self._current_char,
            "--pet-x", str(self.x()),
            "--pet-y", str(self.y()),
            "--pet-w", str(self.width()),
            "--pet-h", str(self.height()),
        ])
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(lambda p=process: self._read_chat_process_error(p))
        process.finished.connect(lambda *args, p=process: self._on_chat_process_finished(p))
        process.errorOccurred.connect(lambda _error, p=process: self._on_chat_process_finished(p))
        self._chat_process = process
        process.start()

    def _read_chat_process_output(self, process: QProcess):
        data = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            if line.startswith("ACTION\t"):
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    if parts[1] == self._current_char:
                        self._on_chat_action(parts[2])
                elif len(parts) == 2:
                    self._on_chat_action(parts[1])

    def _connect_ipc_socket(self):
        if self._ipc_socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            return
        self._ipc_socket.connectToServer(ipc_server_name())

    def _schedule_ipc_reconnect(self):
        if not self._ipc_reconnect_timer.isActive():
            self._ipc_reconnect_timer.start()

    def _on_ipc_connected(self):
        self._ipc_reconnect_timer.stop()
        self._ipc_socket.write(f"REGISTER\tPET\t{self._current_char}\n".encode("utf-8"))
        self._ipc_socket.flush()

    def _read_ipc_messages(self):
        data = bytes(self._ipc_socket.readAll()).decode("utf-8", errors="replace")
        buffer = self._ipc_buffer + data
        lines = buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            self._ipc_buffer = lines.pop()
        else:
            self._ipc_buffer = ""
        for raw_line in lines:
            self._handle_ipc_line(raw_line.rstrip("\r\n"))

    def _handle_ipc_line(self, line: str):
        if line.startswith("ACTION\t"):
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[1] == self._current_char:
                self._on_chat_action(parts[2])
            elif len(parts) == 2:
                self._on_chat_action(parts[1])
        elif line.startswith("LIP\t"):
            parts = line.split("\t", 2)
            if len(parts) == 3 and parts[1] == self._current_char:
                try:
                    self._live2d_widget.set_lip_sync_level(float(parts[2]))
                except ValueError:
                    pass
        elif line.startswith("SETTINGS\t"):
            try:
                if self._cfg:
                    self._cfg.load()
                self._apply_settings(json.loads(line.split("\t", 1)[1]))
            except json.JSONDecodeError:
                pass
        elif line.startswith("AI_EVENT\t"):
            try:
                self._handle_ai_event(json.loads(line.split("\t", 1)[1]))
            except json.JSONDecodeError:
                pass
        elif line.startswith("CHAT_EVENT\t"):
            try:
                self._handle_chat_event(json.loads(line.split("\t", 1)[1]))
            except json.JSONDecodeError:
                pass
        elif line == "SHUTDOWN":
            self._quit()

    def _handle_ai_event(self, event: dict):
        if not isinstance(event, dict):
            return
        if not self._ai_event_overlay_enabled:
            return
        target = str(
            event.get("character")
            or event.get("target_character")
            or ""
        ).strip()
        if target and target != self._current_char:
            return

        action = str(event.get("action", "") or "").strip()
        state = str(event.get("state", "") or "").strip().lower()
        if not action and state in {"thinking", "tool"}:
            action = "thinking"
        elif not action and state == "error":
            action = "surprised"
        elif not action and state == "done":
            action = "smile"
        if action:
            self._on_chat_action(action)

        if not self._compact_ai_window_enabled:
            return
        if not self.isVisible():
            return
        should_position = (
            self._compact_ai_window is None
            or not self._compact_ai_window.isVisible()
            or bool(event.get("anchor_to_pet"))
        )
        self._sync_compact_ai_window(
            allow_create=True,
            force_visible=True,
            reposition=should_position,
        )
        if self._compact_ai_window is None:
            return
        self._compact_ai_window.apply_ai_event(event)

    def _handle_chat_event(self, event: dict):
        if not isinstance(event, dict):
            return
        if not self._chat_integration_overlay_enabled:
            return
        target = str(
            event.get("character")
            or event.get("target_character")
            or ""
        ).strip()
        if target and target != self._current_char:
            return

        action = str(event.get("action", "") or "").strip()
        if action:
            self._on_chat_action(action)

        if not self.isVisible():
            return
        should_position = (
            self._compact_ai_window is None
            or not self._compact_ai_window.isVisible()
            or bool(event.get("anchor_to_pet"))
        )
        self._sync_compact_ai_window(
            allow_create=True,
            force_visible=True,
            reposition=should_position,
        )
        if self._compact_ai_window is None:
            return
        self._compact_ai_window.apply_ai_event(event)

    def _read_chat_process_error(self, process: QProcess):
        data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            print(data)

    def _on_chat_process_finished(self, process: QProcess):
        if self._chat_process is process:
            self._chat_process = None
        process.deleteLater()

    def _close_chat_process(self):
        if self._chat_process is None:
            return
        if self._chat_process.state() != QProcess.ProcessState.NotRunning:
            self._chat_process.terminate()
            if not self._chat_process.waitForFinished(1000):
                self._chat_process.kill()
        self._chat_process = None

    def _close_compact_ai_window(self):
        if self._compact_ai_window is None:
            return
        self._compact_ai_window.close()
        self._compact_ai_window.deleteLater()
        self._compact_ai_window = None

    def _close_settings_process(self):
        process = self._settings_process
        if process is None:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
        self._settings_process = None
        process.deleteLater()

    def _ensure_compact_ai_window(self):
        if self._compact_ai_window is None:
            self._compact_ai_window = CompactAIWindow(
                self._current_char,
                self._model_manager,
                self._cfg,
            )
            self._compact_ai_window.action_triggered.connect(self._on_chat_action)
        self._compact_ai_window.set_character(self._current_char)
        self._compact_ai_window.refresh_theme()
        return self._compact_ai_window

    def _compact_window_target(self):
        bounds = None
        if not self._pixel_mode:
            dragging = bool(getattr(self._live2d_widget, "_dragging", False))
            if dragging:
                if self._compact_ai_drag_bounds is None:
                    self._compact_ai_drag_bounds = (
                        self._compact_ai_bounds_cache
                        or self._live2d_widget.visible_model_bounds()
                    )
                bounds = self._compact_ai_drag_bounds
            else:
                bounds = self._live2d_widget.visible_model_bounds()
                if bounds:
                    self._compact_ai_bounds_cache = bounds
                self._compact_ai_drag_bounds = None
            if bounds:
                left, right, _top, _bottom = bounds
                width = max(1, int(round(right - left)))
                return width, bounds
            return max(240, int(round(self.width() * 0.72))), None
        self._compact_ai_bounds_cache = None
        self._compact_ai_drag_bounds = None
        return max(240, int(round(self.width() * 0.9))), None

    def _sync_compact_ai_window(
        self,
        allow_create: bool = False,
        force_visible: bool = False,
        reposition: bool = True,
    ):
        if not (self._compact_ai_window_enabled or force_visible) or not self.isVisible():
            if self._compact_ai_window is not None:
                self._compact_ai_window.hide()
            return
        if self._compact_ai_window is None:
            if not allow_create:
                return
            self._ensure_compact_ai_window()
        if reposition:
            target_width, bounds = self._compact_window_target()
            self._compact_ai_window.position_near_pet(self.geometry(), target_width, bounds)
        self._compact_ai_window.show()
        self._compact_ai_window.raise_()

    def _move_compact_ai_with_pet(self, dx: int, dy: int):
        if (
            self._compact_ai_window is None
            or not self._compact_ai_window.isVisible()
            or not (self._compact_ai_window_enabled or self._ai_event_overlay_enabled)
        ):
            return
        self._compact_ai_window.follow_pet_delta(dx, dy, self.geometry())

    def _on_chat_action(self, action_name: str):
        self._note_user_interaction()
        model = self._live2d_widget.model
        if model is None:
            return

        char_prefix = self._current_char if self._current_char else "anon"
        normalized = action_name.strip().lower()
        normalized = normalized.strip("[] \t\r\n")
        normalized = normalized.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

        exp_names = list(model.expressions.keys()) if hasattr(model, 'expressions') else []
        exp_map = {}
        for ename in exp_names:
            l = ename.lower()
            exp_map[l] = ename
            exp_map[os.path.splitext(l)[0]] = ename

        def _find_expression(tag: str) -> str | None:
            tag_low = tag.lower()
            tag_base = os.path.splitext(tag_low)[0]
            if tag_low in exp_map:
                return exp_map[tag_low]
            if tag_base in exp_map:
                return exp_map[tag_base]
            prefix = f"{char_prefix}_{tag_base}"
            for ename in exp_names:
                ename_low = ename.lower()
                ename_base = os.path.splitext(ename_low)[0]
                if ename_base.startswith(prefix):
                    return ename
                if ename_base.startswith(tag_base):
                    return ename
            return None

        try:
            motion_names = list(model.modelSetting.getMotionNames())
        except Exception:
            motion_names = []

        char_lower = char_prefix.lower()

        def _find_motion(tag: str) -> str | None:
            tag_low = tag.lower()
            candidates = []
            if tag_low == "thinking":
                candidates.extend(["thinking", "nf", "nnf", "eeto", "odoodo"])
            else:
                candidates.append(tag_low)

            matches = []
            for candidate in candidates:
                candidate_prefix = f"{char_lower}_{candidate}"
                for mname in motion_names:
                    mlow = mname.lower()
                    if mlow == candidate or mlow.startswith(candidate):
                        matches.append(mname)
                    elif mlow == candidate_prefix or mlow.startswith(candidate_prefix):
                        matches.append(mname)
                    elif re.search(rf"(^|[_\-]){re.escape(candidate)}($|[_\-]?\d)", mlow):
                        matches.append(mname)
            if matches:
                return random.choice(matches)
            try:
                if hasattr(model.modelSetting, "resolveMotion") and model.modelSetting.resolveMotion(tag, 0):
                    return tag
            except Exception:
                pass
            return None

        tag_map = {
            "angry": "angry",
            "cry": "cry",
            "bye": "bye",
            "kandou": "kandou",
            "smile": "smile",
            "sad": "sad",
            "surprised": "surprised",
            "thinking": "thinking",
            "shame": "shame",
            "serious": "serious",
            "wink": "wink",
            "kime": "kime",
            "nf": "nf",
            "nnf": "nnf",
            "scared": "scared",
            "sleep": "sleep",
            "sneeze": "sneeze",
            "sing": "sing",
            "sigh": "sigh",
            "odoodo": "odoodo",
            "eeto": "eeto",
            "gattsu": "gattsu",
            "jaan": "jaan",
            "nekodere": "nekodere",
            "pui": "pui",
            "niya": "niya",
            "ando": "ando",
            "mitore": "mitore",
            "nod": "nod",
            "f": "f",
        }

        if "." in normalized:
            base, ext = normalized.rsplit(".", 1)
            exp = _find_expression(base)
            if exp:
                try:
                    model.SetExpression(exp)
                    self._schedule_default_expression_restore()
                except Exception:
                    pass
                return
            if ext.lower() in {"mtn", "motion"}:
                normalized = base
            else:
                return

        mapped = tag_map.get(normalized, normalized)

        motion = _find_motion(mapped)
        motion_started = False
        if motion:
            self._expression_guard_token += 1
            try:
                self._motion_guard_token += 1
                token = self._motion_guard_token
                model.StartMotion(
                    motion,
                    0,
                    self._live2d.MotionPriority.FORCE,
                    onFinishMotionHandler=self._on_motion_finished,
                )
                motion_started = True
                QTimer.singleShot(8000, lambda t=token: self._clear_motion_if_current(t))
                QTimer.singleShot(1800, lambda t=token: self._restore_default_if_finished(t))
            except Exception:
                try:
                    self._motion_guard_token += 1
                    token = self._motion_guard_token
                    model.StartRandomMotion(
                        priority=self._live2d.MotionPriority.FORCE,
                        onFinishMotionHandler=self._on_motion_finished,
                    )
                    motion_started = True
                    QTimer.singleShot(8000, lambda t=token: self._clear_motion_if_current(t))
                    QTimer.singleShot(1800, lambda t=token: self._restore_default_if_finished(t))
                except Exception:
                    pass

        exp = _find_expression(mapped)
        if exp:
            try:
                model.SetExpression(exp)
                if not motion_started:
                    self._schedule_default_expression_restore()
            except Exception:
                pass

    def _on_radial_costume(self):
        self._note_user_interaction()
        self._open_settings(start_on_costumes=True)

    def _on_radial_motion(self):
        self._note_user_interaction()
        model = self._live2d_widget.model
        if model is None:
            return
        try:
            self._expression_guard_token += 1
            self._motion_guard_token += 1
            token = self._motion_guard_token
            model.StartRandomMotion(
                priority=self._live2d.MotionPriority.FORCE,
                onFinishMotionHandler=self._on_motion_finished,
            )
            QTimer.singleShot(8000, lambda t=token: self._clear_motion_if_current(t))
            QTimer.singleShot(1800, lambda t=token: self._restore_default_if_finished(t))
        except Exception:
            pass

    def _on_motion_finished(self, *_args):
        self._motion_guard_token += 1
        QTimer.singleShot(0, lambda t=self._motion_guard_token: self._restore_default_motion(t, force_clear=False))

    def _clear_motion_if_current(self, token: int):
        if token != self._motion_guard_token:
            return
        self._motion_guard_token += 1
        QTimer.singleShot(0, lambda t=self._motion_guard_token: self._restore_default_motion(t, force_clear=True))

    def _restore_default_motion(self, token: int, force_clear: bool = False):
        if token != self._motion_guard_token:
            return
        model = self._live2d_widget.model
        if model is None:
            return
        if not self._live2d_idle_actions_enabled:
            if force_clear:
                try:
                    model.ClearMotions()
                except Exception:
                    pass
            return
        if force_clear:
            try:
                model.ClearMotions()
            except Exception:
                pass
            QTimer.singleShot(50, lambda t=token: self._start_idle_motion_if_current(t, smooth=False))
        else:
            self._start_idle_motion_if_current(token, smooth=True)

    def _start_idle_motion_if_current(self, token: int, smooth: bool):
        if token != self._motion_guard_token:
            return
        if not self._live2d_idle_actions_enabled:
            return
        self._start_idle_motion(smooth=smooth)

    def _restore_default_if_finished(self, token: int):
        if token != self._motion_guard_token:
            return
        if not self._live2d_idle_actions_enabled:
            return
        model = self._live2d_widget.model
        if model is None:
            return
        try:
            if not model.IsMotionFinished():
                QTimer.singleShot(500, lambda t=token: self._restore_default_if_finished(t))
                return
        except Exception:
            pass
        self._motion_guard_token += 1
        self._restore_default_motion(self._motion_guard_token, force_clear=False)

    def _start_idle_motion(self, smooth: bool):
        if not self._live2d_idle_actions_enabled:
            return
        model = self._live2d_widget.model
        if model is None:
            return
        try:
            motion_names = list(model.modelSetting.getMotionNames())
        except Exception:
            motion_names = []
        configured_motion = str(self._current_model_entry().get("default_motion", ""))
        if configured_motion in motion_names:
            try:
                priority = self._live2d.MotionPriority.NORMAL if smooth else self._live2d.MotionPriority.FORCE
                model.StartRandomMotion(configured_motion, priority=priority)
                self._apply_default_expression(model)
                return
            except Exception:
                try:
                    model.StartMotion(configured_motion, 0, self._live2d.MotionPriority.FORCE)
                    self._apply_default_expression(model)
                    return
                except Exception:
                    pass
        idle_names = [name for name in motion_names if str(name).lower().startswith("idle")]
        if idle_names:
            idle_name = random.choice(idle_names)
            priority = self._live2d.MotionPriority.NORMAL if smooth else self._live2d.MotionPriority.FORCE
            try:
                model.StartRandomMotion(
                    idle_name,
                    priority=priority,
                )
            except Exception:
                try:
                    model.StartMotion(
                        idle_name,
                        0,
                        self._live2d.MotionPriority.FORCE,
                    )
                except Exception:
                    pass
        else:
            try:
                model.ClearMotions()
            except Exception:
                pass
        self._apply_default_expression(model)

    def _schedule_default_expression_restore(self, delay_ms: int = 3000):
        self._expression_guard_token += 1
        token = self._expression_guard_token
        QTimer.singleShot(delay_ms, lambda t=token: self._restore_default_expression_if_current(t))

    def _restore_default_expression_if_current(self, token: int):
        if token != self._expression_guard_token:
            return
        remaining_ms = int((self._click_expression_hold_until - time.monotonic()) * 1000)
        if remaining_ms > 0:
            QTimer.singleShot(min(remaining_ms, 1000), lambda t=token: self._restore_default_expression_if_current(t))
            return
        model = self._live2d_widget.model
        if model is None:
            return
        self._apply_default_expression(model)

    def _apply_default_expression(self, model):
        if time.monotonic() < self._click_expression_hold_until:
            return
        try:
            if hasattr(model, "ResetExpression"):
                model.ResetExpression()
        except Exception:
            pass
        try:
            default_exp = self._find_default_expression(model)
            if default_exp:
                model.SetExpression(default_exp)
        except Exception:
            pass

    def _find_default_expression(self, model):
        if not hasattr(model, 'expressions') or not model.expressions:
            return None
        configured_expression = str(self._current_model_entry().get("default_expression", ""))
        if configured_expression in model.expressions:
            return configured_expression
        for name in model.expressions:
            if name.lower().endswith('_default') or name.lower() == 'default':
                return name
        return None

    def _on_lock_toggled(self, locked: bool):
        self._live2d_widget.set_drag_locked(locked)
        self._pixel_widget.set_drag_locked(locked)
        if self._cfg:
            self._cfg.load()
            self._cfg.set("drag_locked", bool(locked))
            self._cfg.save()

    def _on_radial_pixel(self):
        self._note_user_interaction()
        if self._pixel_mode:
            self._enable_live2d_mode()
        else:
            self._enable_pixel_mode()

    def _load_pixel_for_current_character(self) -> bool:
        path = pixel_path_for_character(self._current_char)
        if not path:
            self._pixel_ready = False
            return False
        if self._pixel_frames is None:
            self._pixel_frames = load_pixel_frames()
        self._pixel_ready = self._pixel_widget.load_sprite(path, self._pixel_frames)
        return self._pixel_ready

    def _remember_current_position(self):
        if not self._cfg:
            return
        path = self._model_manager.get_model_json_path(self._current_char, self._current_costume)
        if self._pixel_mode:
            self._cfg.set("pixel_window_x", self.x())
            self._cfg.set("pixel_window_y", self.y())
        else:
            self._cfg.set("window_x", self.x())
            self._cfg.set("window_y", self.y())
            self._cfg.set("window_width", self.width())
            self._cfg.set("window_height", self.height())
        self._sync_current_model_entry(path, save=False)

    def _restore_live2d_position(self):
        if not self._cfg:
            self.resize(*self._live2d_size())
            return
        entry = self._current_model_entry()
        w, h = self._live2d_size()
        x = entry.get("window_x", self._cfg.get("window_x", -1))
        y = entry.get("window_y", self._cfg.get("window_y", -1))
        self.resize(w, h)
        if x >= 0 and y >= 0:
            self.move(x, y)

    def _restore_pixel_position(self):
        if not self._cfg:
            return
        entry = self._current_model_entry()
        x = entry.get("pixel_window_x", self._cfg.get("pixel_window_x", -1))
        y = entry.get("pixel_window_y", self._cfg.get("pixel_window_y", -1))
        if x >= 0 and y >= 0:
            self.move(x, y)

    def _enable_pixel_mode(self, save: bool = True) -> bool:
        if not self._load_pixel_for_current_character():
            return False
        self._remember_current_position()
        self._pixel_mode = True
        self._stack.setCurrentWidget(self._pixel_widget)
        self.resize(self._pixel_widget.size())
        self._restore_pixel_position()
        self._pixel_widget.set_drag_locked(self._live2d_widget._drag_locked)
        self._motion_guard_token += 1
        if save:
            self._save_config()
        return True

    def _enable_live2d_mode(self, save: bool = True):
        self._remember_current_position()
        self._pixel_mode = False
        self._stack.setCurrentWidget(self._live2d_widget)
        self._restore_live2d_position()
        if save:
            self._save_config()

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self._hide_live2d_model = False
            if self._cfg:
                self._cfg.load()
                self._cfg.set("hide_live2d_model", False)
                self._cfg.save()
            self.show()

    def _open_settings(self, start_on_costumes=False):
        if self._settings_process is not None and self._settings_process.state() != QProcess.ProcessState.NotRunning:
            return

        base_dir = str(app_base_dir())
        process = QProcess(self)
        program, arguments = process_program_and_args(base_dir, "settings_process.py", [
            "--character", self._current_char,
            "--costume", self._current_costume,
            "--fps", str(self._fps),
            "--opacity", str(self._opacity),
            "--vsync", "1" if self._vsync else "0",
            "--show-launch", "0",
            "--start-on-costumes", "1" if start_on_costumes else "0",
        ])
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(lambda p=process: self._read_settings_process_error(p))
        process.finished.connect(lambda *args, p=process: self._on_settings_process_finished(p))
        self._settings_process = process
        process.start()

    def _read_settings_process_error(self, process: QProcess):
        data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            print(data)

    def _on_settings_process_finished(self, process: QProcess):
        if self._settings_process is process:
            self._settings_process = None
        process.deleteLater()

    def set_opacity(self, value: float):
        self._opacity = value
        self.setWindowOpacity(value)

    def _save_config(self):
        if self._cfg:
            from i18n_manager import current_language
            from qfluentwidgets import isDarkTheme
            self._cfg.load()
            models = self._cfg.get("models", [])
            model_exists = (
                not isinstance(models, list)
                or not models
                or any(
                    isinstance(item, dict) and item.get("character") == self._current_char
                    for item in models
                )
            )
            self._cfg.set("language", current_language())
            path = self._model_manager.get_model_json_path(self._current_char, self._current_costume)
            if model_exists:
                self._cfg.set("character", self._current_char)
                self._cfg.set("costume", self._current_costume)
                self._sync_current_model_entry(path, save=False)
            self._cfg.set("fps", self._fps)
            self._cfg.set("opacity", self._opacity)
            self._cfg.set("dark_theme", isDarkTheme())
            self._cfg.set("vsync", self._vsync)
            self._cfg.set("game_topmost", self._game_topmost)
            self._cfg.set("hide_live2d_model", self._hide_live2d_model)
            self._cfg.set("live2d_idle_actions_enabled", self._live2d_idle_actions_enabled)
            self._cfg.set("live2d_quality", self._live2d_quality)
            self._cfg.set("live2d_scale", self._live2d_scale)
            self._cfg.set("drag_locked", self._live2d_widget._drag_locked)
            if model_exists:
                self._cfg.set("pet_mode", "pixel" if self._pixel_mode else "live2d")
                if self._pixel_mode:
                    self._cfg.set("pixel_window_x", self.x())
                    self._cfg.set("pixel_window_y", self.y())
                else:
                    self._cfg.set("window_x", self.x())
                    self._cfg.set("window_y", self.y())
                    self._cfg.set("window_width", self.width())
                    self._cfg.set("window_height", self.height())
            self._cfg.save()

    def _sync_current_model_entry(self, path: str, save: bool = True):
        if not self._cfg or not path:
            return
        if save:
            self._cfg.load()
        models = self._cfg.get("models", [])
        if not isinstance(models, list):
            models = []
        entry = {"character": self._current_char, "costume": self._current_costume, "path": path}
        default_motion = self._current_model_entry().get("default_motion", "")
        if default_motion:
            entry["default_motion"] = default_motion
        default_expression = self._current_model_entry().get("default_expression", "")
        if default_expression:
            entry["default_expression"] = default_expression
        click_motion_actions = self._current_model_entry().get("click_motion_actions", {})
        if click_motion_actions:
            entry["click_motion_actions"] = click_motion_actions
        if hasattr(self._cfg, "set_model_action_profile"):
            self._cfg.set_model_action_profile(self._current_char, self._current_costume, entry)
        entry["pet_mode"] = "pixel" if self._pixel_mode else "live2d"
        if self._pixel_mode:
            entry.update({
                "pixel_window_x": self.x(),
                "pixel_window_y": self.y(),
            })
        else:
            entry.update({
                "window_x": self.x(),
                "window_y": self.y(),
                "window_width": self.width(),
                "window_height": self.height(),
            })
        updated = False
        for idx, item in enumerate(models):
            if (
                isinstance(item, dict)
                and item.get("character") == self._current_char
                and item.get("costume") == self._current_costume
            ):
                preserved = dict(item)
                preserved.update(entry)
                entry = preserved
                models[idx] = entry
                updated = True
                break
        if not updated:
            for idx, item in enumerate(models):
                if isinstance(item, dict) and item.get("character") == self._current_char:
                    preserved = dict(item)
                    preserved.update(entry)
                    entry = preserved
                    models[idx] = entry
                    updated = True
                    break
        if not updated:
            models.append(entry)
        self._cfg.set("models", models)
        if save:
            self._cfg.save()

    def _quit(self):
        QApplication.instance().removeEventFilter(self)
        self._close_chat_process()
        self._close_compact_ai_window()
        self._close_settings_process()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        QApplication.quit()

    def contextMenuEvent(self, event):
        event.accept()

    @staticmethod
    def _toggle_theme():
        apply_app_theme(not isDarkTheme())

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_frameless_fix()
        if sys.platform == "darwin" and macos_patch is not None:
            QTimer.singleShot(0, self._apply_macos_window_polish)
        # _apply_game_topmost_state reads isVisible(), so call it after show
        # — and on macOS it depends on the NSWindow already existing, so defer
        # to the next event loop tick alongside the polish call above.
        QTimer.singleShot(0, self._apply_game_topmost_state)
        QTimer.singleShot(0, self._prewarm_radial_menu)
        if self._show_pos_set and self._is_position_on_screen():
            self._sync_compact_ai_window(allow_create=True)
            return
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.left() + (geo.width() - self.width()) // 2,
                geo.top() + (geo.height() - self.height()) // 2,
            )
        self._show_pos_set = True
        self._play_entrance()
        self._sync_compact_ai_window(allow_create=True)

    def _is_position_on_screen(self) -> bool:
        screen = QApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.availableGeometry()
        return (self.x() + self.width() > geo.left() and
                self.x() < geo.right() and
                self.y() + self.height() > geo.top() and
                self.y() < geo.bottom())

    def _play_entrance(self):
        self.setWindowOpacity(0.0)
        self._entrance_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._entrance_anim.setDuration(400)
        self._entrance_anim.setStartValue(0.0)
        self._entrance_anim.setEndValue(float(self._opacity))
        self._entrance_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrance_anim.start()


def isDarkTheme():
    from qfluentwidgets import isDarkTheme as _is_dark
    return _is_dark()
