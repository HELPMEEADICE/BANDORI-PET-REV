import ctypes
import ctypes.wintypes
import os
import re
import sys
from datetime import datetime

from PySide6.QtCore import QEvent, QEasingCurve, QObject, QPoint, QPropertyAnimation, Qt, QTimer, Signal, QRect, QRectF
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QFrame,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from llm_manager import (
    LLMStreamWorker,
    NonStreamWorker,
    ResponsesStreamWorker,
    build_system_prompt,
    parse_action_tags,
    strip_action_tags,
)
from llm_api_compat import chat_completions_api_url
from llm_error_hints import format_llm_error_message
from chat_config_snapshots import (
    memory_extraction_api_config,
    tool_config_snapshot,
    tts_config_snapshot,
)
try:
    from tts_manager import TTSPlayer, TTSRequestWorker, strip_tts_action_tags
    _TTS_AVAILABLE = True
except (ImportError, OSError):
    _TTS_AVAILABLE = False

    class TTSPlayer(QObject):
        error = Signal(str)
        level_changed = Signal(float)
        mouth_pose_changed = Signal(float, float)
        playback_finished = Signal()
        def prepare_lip_sync_text(self, text, language=""): pass
        def enqueue(self, audio, media_type): pass
        def stop(self): pass
        def is_idle(self): return True
    TTSRequestWorker = None

    def strip_tts_action_tags(text: str) -> str:
        return re.sub(r"\[(?:DONE|[A-Za-z0-9_.\-]+)\]", "", text).strip()
from database_manager import DatabaseManager
from i18n_manager import tr as _tr
from relationship_memory import (
    analyze_interaction,
    build_memory_extraction_messages,
    build_relationship_context,
    format_character_status,
    parse_memory_extraction_response,
    parse_relationship_analysis_response,
    user_key_from_config,
)
from action_bus import publish_lip_sync
from ui_helpers import INTERRUPT_COMMANDS
from win32_dwm import apply_windows_11_border_fix

_INTERRUPT_COMMANDS = INTERRUPT_COMMANDS

if sys.platform == "darwin":
    import macos_patch
else:
    macos_patch = None


def _color_from_config(value: str, alpha: int) -> QColor:
    color = QColor(value or "#e4004f")
    if not color.isValid():
        color = QColor("#e4004f")
    color.setAlpha(alpha)
    return color


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


def _contrast_text(color: QColor) -> str:
    luminance = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
    return "#24121a" if luminance > 170 else "#ffffff"


def _opacity_alpha(value) -> int:
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        pct = 44
    return max(15, min(100, pct)) * 255 // 100


def _font_size_from_config(value) -> int:
    try:
        size = int(round(float(value)))
    except (TypeError, ValueError):
        size = 12
    return max(9, min(22, size))


class CompactPromptEdit(QTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
            return
        super().keyPressEvent(event)


class CompactSendButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = QColor("#e4004f")
        self._hover_bg = QColor("#f02466")
        self._pressed_bg = QColor("#b8003f")
        self._fg = QColor("#ffffff")

    def set_colors(self, bg: QColor, hover_bg: QColor, pressed_bg: QColor, fg: QColor):
        self._bg = QColor(bg)
        self._hover_bg = QColor(hover_bg)
        self._pressed_bg = QColor(pressed_bg)
        self._fg = QColor(fg)
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        bg = self._pressed_bg if self.isDown() else self._hover_bg if self.underMouse() else self._bg
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bg))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        center = rect.center()
        size = max(8.0, min(rect.width(), rect.height()) * 0.32)
        pen = QPen(self._fg, max(2, int(round(size * 0.22))))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(
            int(round(center.x())),
            int(round(center.y() + size * 0.65)),
            int(round(center.x())),
            int(round(center.y() - size * 0.65)),
        )
        painter.drawLine(
            int(round(center.x())),
            int(round(center.y() - size * 0.65)),
            int(round(center.x() - size * 0.48)),
            int(round(center.y() - size * 0.12)),
        )
        painter.drawLine(
            int(round(center.x())),
            int(round(center.y() - size * 0.65)),
            int(round(center.x() + size * 0.48)),
            int(round(center.y() - size * 0.12)),
        )


class CompactAIWindow(QWidget):
    action_triggered = Signal(str)

    def __init__(self, character: str, model_manager, config_manager, parent=None):
        super().__init__(parent)
        self._character = character
        self._model_manager = model_manager
        self._cfg = config_manager
        self._db = DatabaseManager()
        self._assign_legacy_chat_history()
        self._worker = None
        self._cancelled_workers = []
        self._memory_workers: list[NonStreamWorker] = []
        self._conv_id: int | None = None
        self._chat_user_key = user_key_from_config(self._cfg)
        self._history = []
        self._last_user_text = ""
        self._last_user_message_id: int | None = None
        self._stream_text = ""
        self._thinking_text = ""
        self._tts_worker = None
        self._tts_generation = 0
        self._tts_playing_character = ""
        self._tts_player = TTSPlayer(self)
        self._tts_player.mouth_pose_changed.connect(self._on_tts_mouth_pose_changed)
        self._tts_player.playback_finished.connect(self._on_tts_playback_finished)
        self._external_stream_text = ""
        self._clear_timer = QTimer(self)
        self._clear_timer.setSingleShot(True)
        self._clear_timer.timeout.connect(self._clear_external_output)
        self._pet_geo = QRect()
        self._manual_offset = None
        self._dragging = False
        self._drag_start = QPoint()
        self._drag_window_start = QPoint()
        self._geometry_anim = None
        self._output_scroll_needed = False
        self._panel_color = QColor(255, 255, 255, 210)
        self._panel_border_color = QColor(255, 255, 255, 160)
        self._shadow_color = QColor(0, 0, 0, 42)
        self._output = None
        self._input_shell = None
        self._input = None
        self._send_button = None

        self._init_ui()
        self.refresh_theme()
        self._load_last_conversation()
        self._update_output_height(animated=False)

    def _assign_legacy_chat_history(self):
        if not self._cfg or not hasattr(self._cfg, "legacy_chat_user_key"):
            return
        try:
            self._db.assign_legacy_chat_history_user(self._cfg.legacy_chat_user_key())
        except Exception:
            pass

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMinimumSize(260, 96)
        self.resize(320, 108)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(7)

        self._output = QTextEdit(self)
        self._output.setObjectName("compactOutput")
        self._output.setReadOnly(True)
        self._output.setAcceptRichText(False)
        self._output.setFrameShape(QFrame.Shape.NoFrame)
        self._output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._output.viewport().installEventFilter(self)
        layout.addWidget(self._output, 1)

        self._input_shell = QFrame(self)
        self._input_shell.setObjectName("compactComposer")
        self._input_shell.installEventFilter(self)
        row = QHBoxLayout(self._input_shell)
        row.setContentsMargins(9, 4, 4, 4)
        row.setSpacing(6)
        layout.addWidget(self._input_shell)

        self._input = CompactPromptEdit(self)
        self._input.setObjectName("compactInput")
        self._input.setAcceptRichText(False)
        self._input.setFrameShape(QFrame.Shape.NoFrame)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setPlaceholderText(_tr("CompactAIWindow.input_placeholder"))
        self._input.send_requested.connect(self.send_message)
        self._input.textChanged.connect(self._sync_scrollbar_policies)
        row.addWidget(self._input, 1, Qt.AlignmentFlag.AlignVCenter)

        self._send_button = CompactSendButton(self)
        self._send_button.setObjectName("compactSendButton")
        self._send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_button.clicked.connect(self.send_message)
        row.addWidget(self._send_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._sync_scaled_controls()
        self.installEventFilter(self)

    def refresh_theme(self):
        background_color = ""
        text_color = "#24242a"
        opacity = 44
        if self._cfg:
            background_color = self._cfg.get("compact_ai_window_background_color", "")
            text_color = self._cfg.get("compact_ai_window_text_color", "#24242a")
            opacity = self._cfg.get("compact_ai_window_opacity", 44)
        if not background_color:
            background_color = self._cfg.get("user_avatar_color", "#e4004f") if self._cfg else "#e4004f"
        accent = _color_from_config(
            background_color,
            _opacity_alpha(opacity),
        )
        border = _color_from_config(
            background_color,
            min(230, accent.alpha() + 78),
        )
        hover = QColor(accent)
        hover.setAlpha(min(240, accent.alpha() + 38))
        if not QColor(text_color).isValid():
            text_color = "#24242a"
        radius = self._control_radius()
        button_radius = self._send_button.width() // 2 if self._send_button is not None else 18
        solid_accent = QColor(background_color)
        if not solid_accent.isValid():
            solid_accent = QColor("#e4004f")
        panel = QColor(solid_accent)
        panel.setAlpha(max(92, min(226, accent.alpha() + 56)))
        self._panel_color = panel
        self._panel_border_color = QColor(solid_accent)
        self._panel_border_color.setAlpha(max(86, min(218, accent.alpha() + 72)))
        self._shadow_color = QColor(0, 0, 0, 55 if panel.alpha() > 170 else 38)
        output_bg = QColor(255, 255, 255, 42) if _contrast_text(solid_accent) == "#24121a" else QColor(0, 0, 0, 34)
        input_bg = QColor(255, 255, 255, 56) if _contrast_text(solid_accent) == "#24121a" else QColor(0, 0, 0, 42)
        subtle_border = QColor(255, 255, 255, 86) if _contrast_text(solid_accent) == "#24121a" else QColor(255, 255, 255, 44)
        send_bg = QColor(solid_accent)
        send_bg.setAlpha(236)
        send_hover = QColor(solid_accent)
        send_hover.setAlpha(255)
        send_pressed = QColor(solid_accent.darker(116))
        send_pressed.setAlpha(255)
        send_text = _contrast_text(solid_accent)
        if self._send_button is not None:
            self._send_button.set_colors(send_bg, send_hover, send_pressed, QColor(send_text))

        self.setStyleSheet(f"""
            CompactAIWindow {{
                background: transparent;
                border: none;
            }}
            QTextEdit#compactOutput {{
                background: {_rgba(output_bg)};
                border: 1px solid {_rgba(subtle_border)};
                border-radius: {radius}px;
                color: {text_color};
                padding: 8px 10px;
                font-size: {self._font_size()}px;
                selection-background-color: rgba(255, 255, 255, 96);
            }}
            QFrame#compactComposer {{
                background: {_rgba(input_bg)};
                border: 1px solid {_rgba(subtle_border)};
                border-radius: {radius}px;
            }}
            QTextEdit#compactInput {{
                background: transparent;
                border: none;
                border-radius: 0px;
                color: {text_color};
                padding: 4px 2px;
                font-size: {self._font_size()}px;
                selection-background-color: rgba(255, 255, 255, 96);
            }}
            QTextEdit#compactOutput:focus {{
                border: 1px solid {_rgba(border)};
            }}
            QTextEdit#compactInput:focus {{
                border: none;
            }}
            QPushButton#compactSendButton {{
                background: transparent;
                border: none;
                border-radius: {button_radius}px;
                color: {send_text};
            }}
            QPushButton#compactSendButton:hover {{
                background: transparent;
            }}
            QPushButton#compactSendButton:pressed {{
                background: transparent;
            }}
            QPushButton#compactSendButton:disabled {{
                background: {_rgba(hover)};
                color: rgba(255, 255, 255, 120);
            }}
            QScrollBar:vertical {{
                width: 4px;
                margin: 4px 1px 4px 0;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255, 255, 255, 96);
                border-radius: 2px;
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        if self._input is not None:
            self._sync_scaled_controls()
        self.update()

    def _font_size(self) -> int:
        if self._cfg:
            return _font_size_from_config(self._cfg.get("compact_ai_window_font_size", 12))
        return 12

    def _control_radius(self) -> int:
        return max(10, min(13, self.width() // 28))

    def _sync_scaled_controls(self):
        row_h = max(self._font_size() + 24, min(48, round(self.width() * 0.12)))
        button_size = max(28, row_h - 8)
        self._input_shell.setFixedHeight(row_h)
        self._input.setFixedHeight(max(26, row_h - 8))
        self._send_button.setFixedSize(button_size, button_size)
        self._update_output_height(animated=False)

    def fit_to_width(self, target_width: int):
        width = max(260, min(440, int(round(target_width))))
        if self.width() != width:
            self.resize(width, self.height())
            self._sync_scaled_controls()
            self.refresh_theme()
        target_height = self._target_window_height()
        if self.height() != target_height:
            self.resize(width, target_height)
            self._update_output_height(animated=False)

    def position_near_pet(self, pet_geo: QRect, target_width: int | None = None, bounds=None):
        self._pet_geo = QRect(pet_geo)
        if self._geometry_anim is not None:
            self._geometry_anim.stop()
            self._geometry_anim = None
        if target_width:
            self.fit_to_width(target_width)
        screen = QApplication.screenAt(pet_geo.center()) or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen else pet_geo
        margin = 8
        if self._manual_offset is not None:
            x = pet_geo.left() + self._manual_offset.x()
            y = pet_geo.top() + self._manual_offset.y()
            x, y = self._clamp_to_screen(x, y, screen_geo, margin)
            self.move(x, y)
            return
        if bounds:
            left, right, top, _bottom = bounds
            center_x = pet_geo.left() + int(round((left + right) * 0.5))
            gap = max(6, min(14, self.width() // 30))
            y = pet_geo.top() + int(round(top)) - self.height() - gap
        else:
            center_x = pet_geo.center().x()
            y = pet_geo.top() + max(10, min(24, self.height() // 5))
        x = center_x - self.width() // 2
        x, y = self._clamp_to_screen(x, y, screen_geo, margin)
        self.move(x, y)

    def follow_pet_delta(self, dx: int, dy: int, pet_geo: QRect):
        self._pet_geo = QRect(pet_geo)
        if self._geometry_anim is not None:
            self._geometry_anim.stop()
            self._geometry_anim = None
        self.move(self.x() + int(dx), self.y() + int(dy))

    def reset_position_offset(self):
        self._manual_offset = None

    def _base_output_height(self) -> int:
        return self._input_shell.height() if self._input_shell.height() > 0 else max(36, self._font_size() + 24)

    def _max_output_height(self) -> int:
        return max(self._base_output_height(), min(240, int(round(self.width() * 0.78))))

    def _target_output_height(self) -> int:
        text = self._output.toPlainText().strip()
        if not text:
            self._output_scroll_needed = False
            return self._base_output_height()
        doc = self._output.document()
        doc.setTextWidth(max(1, self._output.viewport().width()))
        content_height = int(round(doc.size().height())) + 18
        max_height = self._max_output_height()
        self._output_scroll_needed = content_height > max_height
        return max(self._base_output_height(), min(max_height, content_height))

    def _target_window_height(self) -> int:
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()
        return self._target_output_height() + self._input_shell.height() + spacing + margins.top() + margins.bottom()

    def _set_output_text(self, text: str, animated: bool = True):
        self._output.setPlainText(text)
        self._update_output_height(animated=animated)

    def _update_output_height(self, animated: bool = True):
        if self._output is None or self._input is None:
            return
        output_height = self._target_output_height()
        self._output.setFixedHeight(output_height)
        self._sync_scrollbar_policies()
        target_height = self._target_window_height()
        if self.height() == target_height:
            return
        old_geo = self.geometry()
        target_geo = QRect(old_geo.x(), old_geo.y(), old_geo.width(), target_height)
        if self._manual_offset is not None and not self._pet_geo.isNull():
            self._manual_offset = target_geo.topLeft() - self._pet_geo.topLeft()
        if not animated or not self.isVisible():
            self.setGeometry(target_geo)
            return
        if self._geometry_anim is not None:
            self._geometry_anim.stop()
        self._geometry_anim = QPropertyAnimation(self, b"geometry", self)
        self._geometry_anim.setDuration(150)
        self._geometry_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._geometry_anim.setStartValue(old_geo)
        self._geometry_anim.setEndValue(target_geo)
        self._geometry_anim.start()

    def _sync_scrollbar_policies(self):
        if self._output is None or self._input is None:
            return
        self._set_vertical_scrollbar_policy(
            self._output,
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self._output_scroll_needed else Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self._set_vertical_scrollbar_policy(
            self._input,
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if self._text_edit_needs_vertical_scrollbar(self._input)
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )

    def _set_vertical_scrollbar_policy(self, edit: QTextEdit, policy: Qt.ScrollBarPolicy):
        if edit.verticalScrollBarPolicy() != policy:
            edit.setVerticalScrollBarPolicy(policy)

    def _text_edit_needs_vertical_scrollbar(self, edit: QTextEdit) -> bool:
        if not edit.toPlainText():
            return False
        doc = edit.document()
        doc.setTextWidth(max(1, edit.viewport().width()))
        return doc.size().height() > edit.viewport().height() + 8

    def _clamp_to_screen(self, x: int, y: int, screen_geo: QRect, margin: int) -> tuple[int, int]:
        x = max(screen_geo.left() + margin, min(x, screen_geo.right() - self.width() - margin))
        y = max(screen_geo.top() + margin, min(y, screen_geo.bottom() - self.height() - margin))
        return x, y

    def _drag_targets(self) -> tuple[QObject, ...]:
        targets = [self]
        if self._output is not None:
            targets.append(self._output.viewport())
        if self._input_shell is not None:
            targets.append(self._input_shell)
        return tuple(targets)

    def _begin_drag(self, global_pos: QPoint):
        if self._geometry_anim is not None:
            self._geometry_anim.stop()
            self._geometry_anim = None
        self._dragging = True
        self._drag_start = global_pos
        self._drag_window_start = self.pos()

    def _update_drag(self, global_pos: QPoint):
        delta = global_pos - self._drag_start
        self.move(self._drag_window_start + delta)
        if not self._pet_geo.isNull():
            self._manual_offset = self.pos() - self._pet_geo.topLeft()

    def _end_drag(self):
        self._dragging = False
        if not self._pet_geo.isNull():
            self._manual_offset = self.pos() - self._pet_geo.topLeft()

    def eventFilter(self, obj, event):
        if obj in self._drag_targets():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._begin_drag(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseMove and self._dragging:
                self._update_drag(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._dragging:
                self._end_drag()
                return True
        return super().eventFilter(obj, event)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)

        shadow = QPainterPath(path)
        shadow.translate(0, 3)
        painter.fillPath(shadow, QBrush(self._shadow_color))
        painter.fillPath(path, QBrush(self._panel_color))
        painter.setPen(QPen(self._panel_border_color, 1))
        painter.drawPath(path)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_frameless_fix()
        if macos_patch is not None:
            QTimer.singleShot(0, lambda: macos_patch.apply_floating_tool_window_polish(self, join_all_spaces=True))

    def nativeEvent(self, event_type, message):
        if os.name == "nt":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == 0x0083:
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _apply_windows_frameless_fix(self):
        hwnd = int(self.winId())
        apply_windows_11_border_fix(hwnd)

    def set_character(self, character: str):
        if character == self._character:
            return
        self._reset_tts()
        self._character = character
        self._conv_id = None
        self._last_user_message_id = None
        self._history.clear()
        self._external_stream_text = ""
        self._set_output_text("", animated=False)
        self._load_last_conversation()

    def _load_last_conversation(self):
        self._history = []
        self._conv_id = None
        last = self._db.get_last_conversation(self._character, self._chat_user_key)
        if not last:
            return
        self._conv_id = last["id"]
        for message in self._db.get_messages(self._conv_id, limit=12):
            role = message.get("role", "")
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "") or "").strip()
            if content:
                self._history.append({"role": role, "content": content})

    def _ensure_conversation(self) -> int:
        if self._conv_id is None:
            self._conv_id = self._db.create_conversation(
                self._character,
                _tr("CompactAIWindow.history_title", default="悬浮窗聊天"),
                self._chat_user_key,
            )
        return self._conv_id

    def apply_ai_event(self, event: dict):
        if not isinstance(event, dict):
            return
        self._clear_timer.stop()
        state = str(event.get("state", "stream") or "stream").strip().lower()
        if state in {"idle", "clear"}:
            self._external_stream_text = ""
            self._set_output_text("")
            return

        text = str(event.get("text", "") or "")
        title = str(event.get("title", "") or "")
        source = str(event.get("source", "") or "")
        mode = str(event.get("mode", "") or "").strip().lower()
        if not mode:
            mode = "append" if state == "stream" else "replace"

        raw_text_mode = mode.endswith("_raw")
        normalized_mode = mode.removesuffix("_raw")

        line = (
            text
            if raw_text_mode
            else self._format_ai_event_text(state, title, text, source, event.get("progress"))
        )
        if normalized_mode == "append":
            if line:
                chunk = text if self._external_stream_text and not raw_text_mode else line
                self._external_stream_text = (self._external_stream_text + chunk)[-4000:]
            output = self._external_stream_text
        else:
            self._external_stream_text = line
            output = line

        self._set_output_text(output or self._state_label(state))
        self._scroll_output_to_bottom()

        ttl_ms = event.get("ttl_ms")
        if ttl_ms is None and state == "done":
            ttl_ms = 4500
        try:
            ttl_ms = int(ttl_ms)
        except (TypeError, ValueError):
            ttl_ms = 0
        if ttl_ms > 0:
            self._clear_timer.start(ttl_ms)

    def _clear_external_output(self):
        self._external_stream_text = ""
        self._set_output_text("")

    def _format_ai_event_text(self, state: str, title: str, text: str, source: str, progress) -> str:
        prefix = title or self._state_label(state)
        if source:
            prefix = f"{source}: {prefix}" if prefix else source
        progress_text = self._format_progress(progress)
        if progress_text:
            prefix = f"{prefix} {progress_text}" if prefix else progress_text
        if text and prefix:
            return f"{prefix}\n{text}"
        return text or prefix

    def _format_progress(self, progress) -> str:
        try:
            value = float(progress)
        except (TypeError, ValueError):
            return ""
        if value <= 1:
            value *= 100
        value = max(0, min(100, int(round(value))))
        return f"{value}%"

    def _state_label(self, state: str) -> str:
        labels = {
            "thinking": _tr("CompactAIWindow.state_thinking"),
            "tool": _tr("CompactAIWindow.state_tool"),
            "stream": _tr("CompactAIWindow.state_stream"),
            "error": _tr("CompactAIWindow.state_error"),
            "done": _tr("CompactAIWindow.state_done"),
        }
        return labels.get(state, state or "...")

    def send_message(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        if self._is_interrupt_command(text):
            self._interrupt_generation()
            return
        if text.lower() == "@clear":
            self._input.clear()
            self._clear_timer.stop()
            self._external_stream_text = ""
            self._stream_text = ""
            self._thinking_text = ""
            self._set_output_text("")
            return
        if self._worker is not None:
            self._input.setPlaceholderText(_tr("CompactAIWindow.input_busy_stop", default="正在回复，输入 @stop 或 @停止 中断"))
            return

        if self._cfg:
            self._cfg.load()
            next_user_key = user_key_from_config(self._cfg)
            if next_user_key != self._chat_user_key:
                self._chat_user_key = next_user_key
                self._load_last_conversation()
        if self._handle_local_memory_command(text):
            return
        api_url = self._cfg.get("llm_api_url", "") if self._cfg else ""
        api_key = self._cfg.get("llm_api_key", "") if self._cfg else ""
        model_id = self._cfg.get("llm_model_id", "") if self._cfg else ""
        if not api_url or not api_key or not model_id:
            self._set_output_text(_tr("CompactAIWindow.llm_not_configured"))
            return

        self._input.clear()
        self._reset_tts()
        conv_id = self._ensure_conversation()
        self._last_user_message_id = self._db.add_message(conv_id, "user", text)
        self._history.append({"role": "user", "content": text})
        self._history = self._history[-12:]
        self._last_user_text = text
        self._stream_text = ""
        self._thinking_text = ""
        self._set_output_text("...")
        self._set_busy(True)

        messages = self._build_messages()
        enable_thinking = self._cfg.get("llm_enable_thinking", None) if self._cfg else None
        tool_config = tool_config_snapshot(self._cfg)
        web_search = bool(self._cfg.get("llm_web_search_enabled", False)) if self._cfg else False
        show_sources = bool(self._cfg.get("llm_web_search_show_sources", True)) if self._cfg else True
        if self._use_responses_api(api_url) and not web_search:
            self._worker = ResponsesStreamWorker(
                api_url,
                api_key,
                model_id,
                messages,
                enable_thinking,
                False,
                self,
                show_search_sources=show_sources,
                tool_config=tool_config,
            )
        else:
            if self._use_responses_api(api_url):
                api_url = self._chat_completions_api_url(api_url)
            self._worker = LLMStreamWorker(
                api_url,
                api_key,
                model_id,
                messages,
                enable_thinking,
                self,
                web_search=web_search,
                show_search_sources=show_sources,
                tool_config=tool_config,
            )
        self._worker.chunk_received.connect(self._on_chunk_received)
        self._worker.finished.connect(self._on_response_finished)
        self._worker.error.connect(self._on_response_error)
        self._worker.start()

    def _build_messages(self) -> list[dict]:
        system_prompt = build_system_prompt(self._character, self._cfg)
        dynamic_context = build_relationship_context(
            self._db,
            self._character,
            self._user_memory_key(),
            self._display_user_name(),
        )
        if self._cfg and self._cfg.get("chat_integration_enabled", False) and self._cfg.get("chat_integration_include_context", True):
            external_context = self._db.external_chat_context_text()
            if external_context:
                dynamic_context += "\n\n" + external_context
        messages = [{"role": "system", "content": system_prompt}]
        history = [dict(item) for item in self._history[-12:]]
        now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        messages.extend(history)
        dynamic_context += f"\n\n【后置提示词】\n当前时间：{now}"
        self._append_dynamic_context_to_last_user(messages, dynamic_context)
        return messages

    @staticmethod
    def _append_dynamic_context_to_last_user(messages: list[dict], context: str):
        context = str(context or "").strip()
        if not context:
            return
        suffix = "\n\n【动态上下文】\n" + context
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                messages[i]["content"] = str(messages[i].get("content", "")) + suffix
                break

    def _supports_openai_responses_api(self, api_url: str) -> bool:
        return "api.openai.com" in (api_url or "").lower()

    def _use_responses_api(self, api_url: str = "") -> bool:
        if not self._cfg or self._cfg.get("llm_api_mode", "chat_completions") != "responses":
            return False
        return self._supports_openai_responses_api(api_url or self._cfg.get("llm_api_url", ""))

    def _chat_completions_api_url(self, api_url: str) -> str:
        return chat_completions_api_url(api_url)

    def _on_chunk_received(self, text: str, reasoning: str):
        if self.sender() is not self._worker:
            return
        if reasoning:
            self._thinking_text += reasoning
        clean = strip_action_tags(text)
        if not clean:
            return
        self._stream_text += clean
        self._set_output_text(self._stream_text)
        self._scroll_output_to_bottom()

    def _on_response_finished(self, full_text: str, reasoning_text: str, actions: list):
        if self.sender() is not self._worker:
            return
        del actions
        acts = parse_action_tags(full_text)
        clean = strip_action_tags(full_text)
        reasoning_clean = strip_action_tags(reasoning_text or self._thinking_text)
        if clean:
            self._stream_text = clean
            self._set_output_text(clean)
            self._history.append({"role": "assistant", "content": clean})
            self._history = self._history[-12:]
            self._db.add_message(self._ensure_conversation(), "assistant", clean, reasoning_clean)
            self._speak_tts_text(clean, self._character)
        self._apply_relationship_update(clean, acts)
        for action in acts:
            self.action_triggered.emit(action)
        self._worker = None
        self._set_busy(False)
        self._input.setFocus()

    def _user_memory_key(self) -> str:
        return user_key_from_config(self._cfg)

    def _display_user_name(self) -> str:
        return str(self._cfg.get("user_name", "") or "").strip() if self._cfg else ""

    def _set_relationship_value_text(self, field: str, text: str):
        text = text.strip()
        if not text:
            self._set_output_text(_tr("ChatWindow.set_value_hint", "请输入数值。例如：@好感度 80"))
            return
        user_key = self._user_memory_key()
        if field == "mood":
            try:
                value = int(text)
            except ValueError:
                self._set_output_text(_tr("ChatWindow.set_mood_hint", "请输入 0-100 的心情数值。例如：@当前心情 75（数值越高心情越好）"))
                return
            value = max(0, min(100, value))
            from relationship_memory import mood_from_intensity, MOOD_LABELS
            mood_key = mood_from_intensity(value)
            label = MOOD_LABELS[mood_key]
            self._db.upsert_relationship_state(self._character, user_key, mood=mood_key, mood_intensity=value)
            self._set_output_text(
                _tr("ChatWindow.mood_set", "已设置当前心情为：{mood}（{label}，数值 {value}/100）",
                    mood=mood_key, label=label, value=value))
            return
        try:
            value = int(text)
        except ValueError:
            self._set_output_text(_tr("ChatWindow.set_value_not_number", "请输入 0-100 的数字。"))
            return
        value = max(0, min(100, value))
        field_cn = {"affection": "好感度", "trust": "信任", "familiarity": "熟悉度"}[field]
        self._db.upsert_relationship_state(self._character, user_key, **{field: value})
        self._set_output_text(
            _tr("ChatWindow.relationship_set", "{field} 已设置为：{value}/100", field=field_cn, value=value))

    def _handle_local_memory_command(self, text: str) -> bool:
        stripped = text.strip()
        lowered = stripped.lower()
        if lowered in {"@memory", "/memory", "@status", "/status", "@mood", "/mood", "@记忆", "/记忆", "@状态", "/状态", "@心情", "/心情"}:
            self._input.clear()
            self._set_output_text(format_character_status(
                self._db,
                self._character,
                self._user_memory_key(),
                self._model_manager.get_display_name(self._character),
            ))
            return True
        for prefix in ("@remember ", "/remember ", "@记住 ", "/记住 "):
            if stripped.startswith(prefix):
                self._input.clear()
                content = stripped[len(prefix):].strip()
                if not content:
                    self._set_output_text(_tr("ChatWindow.memory_remember_hint", "要记住什么？可以输入 @记住 你的内容。"))
                    return True
                self._db.add_character_memory(
                    self._character,
                    self._user_memory_key(),
                    "manual",
                    "用户希望我记住：" + content,
                    95,
                )
                self._db.apply_relationship_delta(
                    self._character,
                    self._user_memory_key(),
                    trust_delta=1,
                    familiarity_delta=1,
                    mood="soft",
                    mood_intensity=42,
                    event_type="manual_memory",
                    reason="用户手动添加长期记忆",
                )
                self._set_output_text(_tr("ChatWindow.memory_remembered", "已记住：{content}", content=content))
                return True
        for prefix in ("@forget ", "/forget ", "@忘记 ", "/忘记 "):
            if stripped.startswith(prefix):
                self._input.clear()
                query = stripped[len(prefix):].strip()
                if not query:
                    self._set_output_text(_tr("ChatWindow.memory_forget_hint", "要忘记哪条记忆？可以输入 @忘记 关键词。"))
                    return True
                count = self._db.delete_character_memories_like(
                    self._character,
                    self._user_memory_key(),
                    query,
                )
                self._set_output_text(_tr("ChatWindow.memory_forget_result", "已删除 {count} 条包含\u201c{query}\u201d的长期记忆。", count=count, query=query))
                return True
        for prefix in ("@好感度 ", "/好感度 ", "@affection ", "/affection "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("affection", stripped[len(prefix):])
                return True
        for prefix in ("@信任 ", "/信任 ", "@trust ", "/trust "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("trust", stripped[len(prefix):])
                return True
        for prefix in ("@熟悉度 ", "/熟悉度 ", "@familiarity ", "/familiarity "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("familiarity", stripped[len(prefix):])
                return True
        for prefix in ("@当前心情 ", "/当前心情 ", "@setmood ", "/setmood "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("mood", stripped[len(prefix):])
                return True
        return False

    def _apply_relationship_update(self, assistant_text: str, actions: list[str]):
        if not self._last_user_text.strip():
            return
        user_key = self._user_memory_key()
        fallback_analysis = analyze_interaction(self._last_user_text, assistant_text, actions)
        if self._start_memory_extraction(user_key, self._last_user_text, assistant_text, self._last_user_message_id, fallback_analysis):
            return
        self._apply_relationship_analysis(user_key, fallback_analysis, "compact_chat")

    def _apply_relationship_analysis(self, user_key: str, analysis: dict, event_type: str):
        self._db.apply_relationship_delta(
            self._character,
            user_key,
            affection_delta=analysis["affection_delta"],
            trust_delta=analysis["trust_delta"],
            familiarity_delta=analysis["familiarity_delta"],
            mood=analysis["mood"],
            mood_intensity=analysis["mood_intensity"],
            event_type=event_type,
            reason=analysis["reason"],
        )

    def _start_memory_extraction(
        self,
        user_key: str,
        user_text: str,
        assistant_text: str,
        source_message_id: int | None,
        fallback_analysis: dict,
    ) -> bool:
        api_url, api_key, model_id = memory_extraction_api_config(
            self._cfg,
            self._use_responses_api,
            self._chat_completions_api_url,
        )
        if not api_url or not api_key or not model_id:
            return False
        existing = self._db.get_character_memories(self._character, user_key, limit=12)
        messages = build_memory_extraction_messages(user_text, assistant_text, existing)
        worker = NonStreamWorker(api_url, api_key, model_id, messages, None)
        self._memory_workers.append(worker)
        worker.finished.connect(
            lambda content, _reasoning, _actions, worker=worker, user_key=user_key,
            source_message_id=source_message_id, fallback_analysis=fallback_analysis:
                self._on_memory_extraction_finished(worker, user_key, content, source_message_id, fallback_analysis)
        )
        worker.error.connect(
            lambda _error, worker=worker, user_key=user_key, fallback_analysis=fallback_analysis:
                self._on_memory_extraction_error(worker, user_key, fallback_analysis)
        )
        worker.start()
        return True

    def _on_memory_extraction_finished(
        self,
        worker: NonStreamWorker,
        user_key: str,
        content: str,
        source_message_id: int | None,
        fallback_analysis: dict,
    ):
        self._forget_memory_worker(worker)
        relationship_analysis = parse_relationship_analysis_response(content) or fallback_analysis
        self._apply_relationship_analysis(
            user_key,
            relationship_analysis,
            "compact_chat_model",
        )
        for memory in parse_memory_extraction_response(content):
            self._db.add_character_memory(
                self._character,
                user_key,
                memory["kind"],
                memory["content"],
                memory["importance"],
                source_message_id=source_message_id,
            )

    def _forget_memory_worker(self, worker: NonStreamWorker):
        self._memory_workers = [item for item in self._memory_workers if item is not worker]

    def _on_memory_extraction_error(
        self,
        worker: NonStreamWorker,
        user_key: str,
        fallback_analysis: dict,
    ):
        self._forget_memory_worker(worker)
        self._apply_relationship_analysis(user_key, fallback_analysis, "compact_chat")

    def _tts_enabled(self) -> bool:
        return bool(_TTS_AVAILABLE and self._cfg and self._cfg.get("tts_enabled", False))

    def _clean_tts_payload(self, text: str) -> str:
        text = re.sub(r"\{\s*\"(?:web_search_sources|search_sources|sources)\"\s*:\s*\[.*", "", text, flags=re.S)
        return strip_tts_action_tags(text).strip()

    def _reset_tts(self, stop_player: bool = True):
        self._tts_generation += 1
        worker = self._tts_worker
        self._tts_worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            self._park_cancelled_worker(worker)
        if stop_player:
            self._tts_player.stop()
            if self._tts_playing_character:
                publish_lip_sync(self._tts_playing_character, 0.0)
        self._tts_playing_character = ""

    def _speak_tts_text(self, text: str, character: str):
        if not self._tts_enabled():
            return
        payload = self._clean_tts_payload(text)
        if not payload:
            return
        self._reset_tts(stop_player=True)
        generation = self._tts_generation
        self._tts_playing_character = character
        config = tts_config_snapshot(self._cfg)
        worker = TTSRequestWorker(0, generation, payload, character, config, self)
        self._tts_worker = worker
        worker.audio_ready.connect(self._on_tts_audio_ready)
        worker.error.connect(self._on_tts_error)
        worker.finished.connect(self._on_tts_worker_finished)
        worker.start()

    def _on_tts_audio_ready(self, sequence: int, generation: int, audio: bytes, media_type: str):
        del sequence
        if generation != self._tts_generation or self.sender() is not self._tts_worker:
            return
        if self._tts_worker is not None:
            self._tts_player.prepare_lip_sync_text(
                getattr(self._tts_worker, "prepared_text", ""),
                getattr(self._tts_worker, "prepared_language", ""),
            )
        self._tts_player.enqueue(audio, media_type)

    def _on_tts_error(self, error_msg: str):
        del error_msg

    def _on_tts_worker_finished(self):
        if self.sender() is self._tts_worker:
            self._tts_worker = None

    def _on_tts_mouth_pose_changed(self, level: float, form: float):
        if self._tts_playing_character:
            publish_lip_sync(self._tts_playing_character, level, form)

    def _on_tts_playback_finished(self):
        if self._tts_playing_character:
            publish_lip_sync(self._tts_playing_character, 0.0)
        self._tts_playing_character = ""

    def _on_response_error(self, error_msg: str):
        if self.sender() is not self._worker:
            return
        self._set_output_text(format_llm_error_message(error_msg))
        self._reset_tts(stop_player=False)
        self._worker = None
        self._set_busy(False)
        self._input.setFocus()

    def _set_busy(self, busy: bool):
        self._send_button.setEnabled(True)
        self._input.setEnabled(True)
        self._input.setPlaceholderText(
            _tr("CompactAIWindow.input_busy_stop", default="正在回复，输入 @stop 或 @停止 中断")
            if busy else _tr("CompactAIWindow.input_placeholder")
        )

    @staticmethod
    def _is_interrupt_command(text: str) -> bool:
        return text.strip().lower() in _INTERRUPT_COMMANDS

    def _interrupt_generation(self):
        worker = self._worker
        if worker is not None:
            worker.cancel()
            self._park_cancelled_worker(worker)
        self._worker = None
        self._thinking_text = ""
        self._reset_tts()
        if not self._stream_text.strip():
            self._set_output_text(_tr("CompactAIWindow.response_interrupted", default="已中断当前回复。"))
        self._set_busy(False)
        self._input.clear()
        self._input.setFocus()

    def _park_cancelled_worker(self, worker):
        if worker is None:
            return
        self._cancelled_workers.append(worker)
        QTimer.singleShot(1000, self._prune_cancelled_workers)

    def _prune_cancelled_workers(self):
        self._cancelled_workers = [worker for worker in self._cancelled_workers if worker is not None and worker.isRunning()]

    def _scroll_output_to_bottom(self):
        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
            self._park_cancelled_worker(self._worker)
            self._worker = None
        self._reset_tts()
        for worker in list(self._cancelled_workers):
            if worker is not None and worker.isRunning():
                worker.wait(1000)
        self._cancelled_workers.clear()
        self._db.close()
        super().closeEvent(event)
