import ctypes
import ctypes.wintypes
import os
from datetime import datetime

from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer, Signal, QRect
from PySide6.QtGui import QColor, QKeyEvent
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
    build_system_prompt,
    parse_action_tags,
    strip_action_tags,
)

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE

if os.name == "nt":
    _dwmapi = ctypes.windll.dwmapi
    _dwm_set_window_attribute = _dwmapi.DwmSetWindowAttribute
    _dwm_set_window_attribute.argtypes = [
        ctypes.wintypes.HWND,
        ctypes.wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
    ]
    _dwm_set_window_attribute.restype = ctypes.c_long
else:
    _dwm_set_window_attribute = None


def _color_from_config(value: str, alpha: int) -> QColor:
    color = QColor(value or "#e4004f")
    if not color.isValid():
        color = QColor("#e4004f")
    color.setAlpha(alpha)
    return color


def _rgba(color: QColor) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"


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


class CompactAIWindow(QWidget):
    action_triggered = Signal(str)

    def __init__(self, character: str, model_manager, config_manager, parent=None):
        super().__init__(parent)
        self._character = character
        self._model_manager = model_manager
        self._cfg = config_manager
        self._worker = None
        self._history = []
        self._stream_text = ""
        self._thinking_text = ""
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

        self._init_ui()
        self.refresh_theme()
        self._update_output_height(animated=False)

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
        self.setMinimumSize(240, 82)
        self.resize(300, 88)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._output = QTextEdit(self)
        self._output.setObjectName("compactOutput")
        self._output.setReadOnly(True)
        self._output.setAcceptRichText(False)
        self._output.setFrameShape(QFrame.Shape.NoFrame)
        self._output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._output.viewport().installEventFilter(self)
        layout.addWidget(self._output, 1)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        layout.addLayout(row)

        self._input = CompactPromptEdit(self)
        self._input.setObjectName("compactInput")
        self._input.setAcceptRichText(False)
        self._input.setFrameShape(QFrame.Shape.NoFrame)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setPlaceholderText("输入消息")
        self._input.send_requested.connect(self.send_message)
        self._input.textChanged.connect(self._sync_scrollbar_policies)
        row.addWidget(self._input, 1)

        self._send_button = QPushButton("\u2191", self)
        self._send_button.setObjectName("compactSendButton")
        self._send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_button.clicked.connect(self.send_message)
        row.addWidget(self._send_button)
        self._sync_scaled_controls()

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
        pressed = QColor(accent)
        pressed.setAlpha(min(255, accent.alpha() + 73))
        if not QColor(text_color).isValid():
            text_color = "#24242a"
        radius = self._control_radius()
        button_radius = self._send_button.width() // 2 if hasattr(self, "_send_button") else 18

        self.setStyleSheet(f"""
            CompactAIWindow {{
                background: transparent;
                border: none;
            }}
            QTextEdit#compactOutput,
            QTextEdit#compactInput {{
                background: {_rgba(accent)};
                border: 1px solid {_rgba(border)};
                border-radius: {radius}px;
                color: {text_color};
                padding: 7px 9px;
                font-size: {self._font_size()}px;
                selection-background-color: rgba(255, 255, 255, 96);
            }}
            QTextEdit#compactOutput:focus,
            QTextEdit#compactInput:focus {{
                border: 1px solid {_rgba(border)};
            }}
            QPushButton#compactSendButton {{
                background: {_rgba(accent)};
                border: 1px solid {_rgba(border)};
                border-radius: {button_radius}px;
                color: {text_color};
                font-size: {max(18, self._font_size() + 8)}px;
                font-weight: 600;
            }}
            QPushButton#compactSendButton:hover {{
                background: {_rgba(hover)};
            }}
            QPushButton#compactSendButton:pressed {{
                background: {_rgba(pressed)};
            }}
            QPushButton#compactSendButton:disabled {{
                background: {_rgba(hover)};
                color: rgba(36, 36, 42, 120);
            }}
        """)
        if hasattr(self, "_input"):
            self._sync_scaled_controls()

    def _font_size(self) -> int:
        if self._cfg:
            return _font_size_from_config(self._cfg.get("compact_ai_window_font_size", 12))
        return 12

    def _control_radius(self) -> int:
        return max(9, min(14, self.width() // 25))

    def _sync_scaled_controls(self):
        row_h = max(self._font_size() + 22, min(48, round(self.width() * 0.12)))
        self._input.setFixedHeight(row_h)
        self._send_button.setFixedSize(row_h, row_h)
        self._update_output_height(animated=False)

    def fit_to_width(self, target_width: int):
        width = max(240, min(430, int(round(target_width))))
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
        return self._input.height() if self._input.height() > 0 else max(34, self._font_size() + 22)

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
        return self._target_output_height() + self._input.height() + 8

    def _set_output_text(self, text: str, animated: bool = True):
        self._output.setPlainText(text)
        self._update_output_height(animated=animated)

    def _update_output_height(self, animated: bool = True):
        if not hasattr(self, "_output") or not hasattr(self, "_input"):
            return
        output_height = self._target_output_height()
        self._output.setFixedHeight(output_height)
        self._sync_scrollbar_policies()
        target_height = self._target_window_height()
        if self.height() == target_height:
            return
        old_geo = self.geometry()
        bottom = old_geo.bottom()
        target_geo = QRect(old_geo.x(), bottom - target_height + 1, old_geo.width(), target_height)
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
        if not hasattr(self, "_output") or not hasattr(self, "_input"):
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

    def eventFilter(self, obj, event):
        if obj is self._output.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._dragging = True
                self._drag_start = event.globalPosition().toPoint()
                self._drag_window_start = self.pos()
                return True
            if event.type() == QEvent.Type.MouseMove and self._dragging:
                delta = event.globalPosition().toPoint() - self._drag_start
                self.move(self._drag_window_start + delta)
                if not self._pet_geo.isNull():
                    self._manual_offset = self.pos() - self._pet_geo.topLeft()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._dragging:
                self._dragging = False
                if not self._pet_geo.isNull():
                    self._manual_offset = self.pos() - self._pet_geo.topLeft()
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_frameless_fix()

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
        if os.name != "nt" or _dwm_set_window_attribute is None:
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
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
        border_color = ctypes.c_int(DWMWA_COLOR_NONE)
        try:
            _dwm_set_window_attribute(
                hwnd,
                DWMWA_BORDER_COLOR,
                ctypes.byref(border_color),
                ctypes.sizeof(border_color),
            )
        except Exception:
            pass

    def set_character(self, character: str):
        if character == self._character:
            return
        self._character = character
        self._history.clear()
        self._external_stream_text = ""
        self._set_output_text("", animated=False)

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

        line = self._format_ai_event_text(state, title, text, source, event.get("progress"))
        if mode == "append":
            if line:
                self._external_stream_text = (self._external_stream_text + line)[-4000:]
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
            "thinking": "正在思考...",
            "tool": "正在执行...",
            "stream": "正在输出...",
            "error": "出错了",
            "done": "完成",
        }
        return labels.get(state, state or "...")

    def send_message(self):
        text = self._input.toPlainText().strip()
        if not text or self._worker is not None:
            return

        api_url = self._cfg.get("llm_api_url", "") if self._cfg else ""
        api_key = self._cfg.get("llm_api_key", "") if self._cfg else ""
        model_id = self._cfg.get("llm_model_id", "") if self._cfg else ""
        if not api_url or not api_key or not model_id:
            self._set_output_text("LLM API 尚未配置。")
            return

        self._input.clear()
        self._history.append({"role": "user", "content": text})
        self._history = self._history[-12:]
        self._stream_text = ""
        self._thinking_text = ""
        self._set_output_text("...")
        self._set_busy(True)

        messages = self._build_messages()
        enable_thinking = self._cfg.get("llm_enable_thinking", None) if self._cfg else None
        self._worker = LLMStreamWorker(api_url, api_key, model_id, messages, enable_thinking, self)
        self._worker.chunk_received.connect(self._on_chunk_received)
        self._worker.finished.connect(self._on_response_finished)
        self._worker.error.connect(self._on_response_error)
        self._worker.start()

    def _build_messages(self) -> list[dict]:
        messages = [{"role": "system", "content": build_system_prompt(self._character, self._cfg)}]
        history = [dict(item) for item in self._history[-12:]]
        now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "user":
                history[i]["content"] = history[i].get("content", "") + f"\n\n【后置提示词】\n当前时间：{now}"
                break
        messages.extend(history)
        return messages

    def _on_chunk_received(self, text: str, reasoning: str):
        if reasoning:
            self._thinking_text += reasoning
        clean = strip_action_tags(text)
        if not clean:
            return
        self._stream_text += clean
        self._set_output_text(self._stream_text)
        self._scroll_output_to_bottom()

    def _on_response_finished(self, full_text: str, reasoning_text: str, actions: list):
        del reasoning_text, actions
        clean = strip_action_tags(full_text)
        if clean:
            self._stream_text = clean
            self._set_output_text(clean)
            self._history.append({"role": "assistant", "content": clean})
            self._history = self._history[-12:]
        for action in parse_action_tags(full_text):
            self.action_triggered.emit(action)
        self._worker = None
        self._set_busy(False)
        self._input.setFocus()

    def _on_response_error(self, error_msg: str):
        self._set_output_text(f"Error: {error_msg}")
        self._worker = None
        self._set_busy(False)
        self._input.setFocus()

    def _set_busy(self, busy: bool):
        self._send_button.setEnabled(not busy)
        self._input.setEnabled(not busy)

    def _scroll_output_to_bottom(self):
        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event):
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        super().closeEvent(event)
