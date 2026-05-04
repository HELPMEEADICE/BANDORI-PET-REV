import ctypes
import ctypes.wintypes
import os
import random
import re

from PySide6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QIcon, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QApplication, QSystemTrayIcon, QMenu,
    QGraphicsOpacityEffect,
)

from qfluentwidgets import (
    setTheme, Theme, FluentIcon,
)
from qfluentwidgets.components.widgets.menu import DWMMenu

from live2d_widget import Live2DWidget
from model_manager import ModelManager
from settings_window import SettingsWindow
from radial_menu import RadialMenu


WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
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
else:
    _get_window_long = None
    _set_window_long = None
    _set_window_pos = None


class PetWindow(QWidget):
    def __init__(self, live2d_module, model_manager=None,
                 character="", costume="", fps=120, opacity=1.0,
                 config_manager=None):
        super().__init__()
        self._live2d = live2d_module
        self._model_manager = model_manager or ModelManager()
        self._current_char = character
        self._current_costume = costume
        self._fps = fps
        self._opacity = opacity
        self._tray_icon = None
        self._settings_window = None
        self._cfg = config_manager
        self._radial_menu = None
        self._chat_window = None
        self._show_pos_set = False
        self._motion_guard_token = 0
        self._mouse_passthrough = False
        self._passthrough_timer = QTimer(self)
        self._passthrough_timer.setInterval(35)
        self._passthrough_timer.timeout.connect(self._update_mouse_passthrough)

        self._init_ui()
        self._init_tray()
        self._load_initial_model()
        self._passthrough_timer.start()

        self.setWindowOpacity(self._opacity)

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop, True)
        self.setAutoFillBackground(False)

        self.resize(400, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._live2d_widget = Live2DWidget(self)
        self._live2d_widget.set_live2d_module(self._live2d)
        self._live2d_widget.set_window_drag_callback(self._on_drag)
        self._live2d_widget.set_click_callback(self._on_click)
        self._live2d_widget.set_right_click_callback(self._on_right_click)
        self._live2d_widget.set_fps(self._fps)
        layout.addWidget(self._live2d_widget)

    def nativeEvent(self, event_type, message):
        if os.name == "nt":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCHITTEST:
                    lparam = int(msg.lParam)
                    x = ctypes.c_short(lparam & 0xFFFF).value
                    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
                    if not self._live2d_widget.is_model_hit_at_global(QPoint(x, y)):
                        return True, HTTRANSPARENT
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _set_mouse_passthrough(self, enabled: bool):
        if os.name != "nt" or enabled == self._mouse_passthrough:
            return
        self._apply_passthrough_to_hwnd(int(self.winId()), enabled)
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

    def _update_mouse_passthrough(self):
        if os.name != "nt" or not self.isVisible():
            return
        global_pos = QCursor.pos()
        if not self.geometry().contains(global_pos):
            self._set_mouse_passthrough(False)
            return
        self._set_mouse_passthrough(not self._live2d_widget.is_model_hit_at_global(global_pos))

    def set_fps(self, fps: int):
        self._fps = fps
        self._live2d_widget.set_fps(fps)

    def _init_tray(self):
        self._tray_icon = QSystemTrayIcon(self)
        icon_path = os.path.join(
            os.path.dirname(__file__),
            "third_party", "PyQt-Fluent-Widgets", "qfluentwidgets",
            "_rc", "images", "logo.png"
        )
        if os.path.exists(icon_path):
            self._tray_icon.setIcon(QIcon(icon_path))
        else:
            self._tray_icon.setIcon(QIcon())

        self._tray_icon.setToolTip("Bandori Desktop Pet")

        menu = QMenu()

        show_action = menu.addAction(self.tr("Show/Hide"))
        show_action.triggered.connect(self._toggle_visible)

        chat_action = menu.addAction(self.tr("Chat..."))
        chat_action.triggered.connect(self._open_chat)

        settings_action = menu.addAction(self.tr("Settings..."))
        settings_action.triggered.connect(self._open_settings)

        menu.addSeparator()

        opacity_menu = menu.addMenu(self.tr("Opacity"))
        for pct in [100, 80, 60, 40, 20]:
            act = opacity_menu.addAction(f"{pct}%")
            act.triggered.connect(lambda checked, v=pct: self.set_opacity(v / 100.0))

        menu.addSeparator()

        exit_action = menu.addAction(self.tr("Exit"))
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
            self._update_tooltip()

    def _switch_model(self, character: str, costume: str):
        path = self._model_manager.get_model_json_path(character, costume)
        if not path:
            return
        self._current_char = character
        self._current_costume = costume
        self._live2d_widget.set_model_path(path)
        self._update_tooltip()
        self._save_config()

    def _apply_settings(self, data: dict):
        if "fps" in data:
            self.set_fps(data["fps"])
        if "opacity" in data:
            self.set_opacity(data["opacity"])
        if "dark_theme" in data:
            setTheme(Theme.DARK if data["dark_theme"] else Theme.LIGHT)
        self._save_config()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_settings()

    def _update_tooltip(self):
        display = self._model_manager.get_display_name(self._current_char)
        costume_name = self._model_manager.get_costume_display_name(
            self._current_char, self._current_costume
        )
        self._tray_icon.setToolTip(
            f"Bandori Desktop Pet - {display} ({costume_name})"
        )

    def _on_drag(self, dx: int, dy: int):
        self.move(self.x() + dx, self.y() + dy)

    def _on_click(self):
        if self._radial_menu and self._radial_menu.isVisible():
            self._radial_menu.dismiss()

    def _on_right_click(self, gx: int, gy: int):
        if self._radial_menu is not None and self._radial_menu.isVisible():
            self._radial_menu.dismiss()
            return

        self._radial_menu = RadialMenu()
        self._radial_menu.set_animation_fps(self._fps)
        self._radial_menu.set_locked(self._live2d_widget._drag_locked)
        self._radial_menu.lock_toggled.connect(self._on_lock_toggled)
        self._radial_menu.closed.connect(lambda: setattr(self, '_radial_menu', None))

        self._radial_menu.add_item(
            "", "Chat", QColor(138, 43, 226),
            glyph="\U0001F4AC",
            on_click=self._on_radial_chat,
        )
        self._radial_menu.add_item(
            "", "Costume", QColor(220, 50, 120),
            glyph="\U0001F457",
            on_click=self._on_radial_costume,
        )
        self._radial_menu.add_item(
            "", "Motion", QColor(30, 144, 255),
            glyph="\U0001F3AC",
            on_click=self._on_radial_motion,
        )
        self._radial_menu.add_item(
            "", "Pixel", QColor(34, 180, 140),
            glyph="\U0001F47E",
            on_click=self._on_radial_pixel,
        )

        self._radial_menu.show_at(QPoint(gx, gy))

    def _on_radial_chat(self):
        self._open_chat()

    def _open_chat(self):
        from chat_window import ChatWindow

        if self._chat_window is not None and self._chat_window.isVisible():
            self._chat_window.raise_()
            self._chat_window.activateWindow()
            return

        self._chat_window = ChatWindow(
            self._current_char,
            self._model_manager,
            self._live2d,
            self._cfg,
            parent_pet=self,
        )
        self._chat_window.action_triggered.connect(self._on_chat_action)
        self._chat_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._chat_window.destroyed.connect(lambda: setattr(self, '_chat_window', None))
        self._chat_window.show()
        self._chat_window.position_next_to_pet(self)

    def _on_chat_action(self, action_name: str):
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
            prefix = f"{char_lower}_{tag_low}"
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
            base = normalized.rsplit(".", 1)[0]
            exp = _find_expression(base)
            if exp:
                try:
                    model.SetExpression(exp)
                except Exception:
                    pass
            return

        mapped = tag_map.get(normalized, normalized)

        motion = _find_motion(mapped)
        if motion:
            try:
                self._motion_guard_token += 1
                token = self._motion_guard_token
                model.StartMotion(
                    motion,
                    0,
                    self._live2d.MotionPriority.FORCE,
                    onFinishMotionHandler=self._on_motion_finished,
                )
                QTimer.singleShot(8000, lambda t=token: self._clear_motion_if_current(t))
            except Exception:
                try:
                    self._motion_guard_token += 1
                    token = self._motion_guard_token
                    model.StartRandomMotion(
                        priority=self._live2d.MotionPriority.FORCE,
                        onFinishMotionHandler=self._on_motion_finished,
                    )
                    QTimer.singleShot(8000, lambda t=token: self._clear_motion_if_current(t))
                except Exception:
                    pass

        exp = _find_expression(mapped)
        if exp:
            try:
                model.SetExpression(exp)
            except Exception:
                pass

    def _on_radial_costume(self):
        self._open_settings(start_on_costumes=True)

    def _on_radial_motion(self):
        model = self._live2d_widget.model
        if model is None:
            return
        try:
            self._motion_guard_token += 1
            token = self._motion_guard_token
            model.StartRandomMotion(
                priority=self._live2d.MotionPriority.FORCE,
                onFinishMotionHandler=self._on_motion_finished,
            )
            QTimer.singleShot(8000, lambda t=token: self._clear_motion_if_current(t))
        except Exception:
            pass

    def _on_motion_finished(self):
        self._motion_guard_token += 1
        model = self._live2d_widget.model
        if model is not None:
            model.ClearMotions()

    def _clear_motion_if_current(self, token: int):
        if token != self._motion_guard_token:
            return
        model = self._live2d_widget.model
        if model is not None:
            model.ClearMotions()
        self._motion_guard_token += 1

    def _on_lock_toggled(self, locked: bool):
        self._live2d_widget.set_drag_locked(locked)

    def _on_radial_pixel(self):
        pass

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def _open_settings(self, start_on_costumes=False):
        if self._settings_window is not None and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return

        self._settings_window = SettingsWindow(
            self._model_manager,
            current_char=self._current_char,
            current_costume=self._current_costume,
            current_fps=self._fps,
            current_opacity=self._opacity,
            show_launch=False,
            start_on_costumes=start_on_costumes,
            config_manager=self._cfg,
        )
        self._settings_window.model_selected.connect(self._switch_model)
        self._settings_window.settings_changed.connect(self._apply_settings)
        self._settings_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._settings_window.destroyed.connect(lambda: setattr(self, '_settings_window', None))
        self._settings_window.show()

    def set_opacity(self, value: float):
        self._opacity = value
        self.setWindowOpacity(value)

    def _save_config(self):
        if self._cfg:
            from qfluentwidgets import isDarkTheme
            self._cfg.set("character", self._current_char)
            self._cfg.set("costume", self._current_costume)
            self._cfg.set("fps", self._fps)
            self._cfg.set("opacity", self._opacity)
            self._cfg.set("dark_theme", isDarkTheme())
            self._cfg.set("drag_locked", self._live2d_widget._drag_locked)
            self._cfg.set("window_x", self.x())
            self._cfg.set("window_y", self.y())
            self._cfg.set("window_width", self.width())
            self._cfg.set("window_height", self.height())
            self._cfg.save()

    def _quit(self):
        self._tray_icon.hide()
        QApplication.quit()

    def contextMenuEvent(self, event):
        menu = DWMMenu(self)

        menu.addAction(
            FluentIcon.SETTING,
            self.tr("Settings..."),
            triggered=self._open_settings,
        )
        menu.addAction(
            FluentIcon.CHAT,
            self.tr("Chat..."),
            triggered=self._open_chat,
        )
        menu.addSeparator()

        opacity_menu = DWMMenu(self.tr("Opacity"), menu)
        for pct in [100, 80, 60, 40, 20]:
            opacity_menu.addAction(
                f"{pct}%",
                triggered=lambda checked, v=pct: self.set_opacity(v / 100.0),
            )
        menu.addMenu(opacity_menu)

        menu.addSeparator()

        theme_text = self.tr("Light Theme") if isDarkTheme() else self.tr("Dark Theme")
        menu.addAction(
            FluentIcon.CONTRAST,
            theme_text,
            triggered=self._toggle_theme,
        )
        menu.addSeparator()

        menu.addAction(
            FluentIcon.HIDE,
            self.tr("Hide"),
            triggered=self.hide,
        )
        menu.addAction(
            FluentIcon.CLOSE,
            self.tr("Exit"),
            triggered=self._quit,
        )

        menu.exec(event.globalPos())

    @staticmethod
    def _toggle_theme():
        setTheme(Theme.LIGHT if isDarkTheme() else Theme.DARK)

    def showEvent(self, event):
        super().showEvent(event)
        if self._show_pos_set:
            return
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.width() - 20, geo.bottom() - self.height() - 40)
        self._show_pos_set = True
        self._play_entrance()

    def _play_entrance(self):
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(400)
        anim.setStartValue(0.0)
        anim.setEndValue(float(self._opacity))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()


def isDarkTheme():
    from qfluentwidgets import isDarkTheme as _is_dark
    return _is_dark()
