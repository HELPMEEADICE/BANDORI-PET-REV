from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QRect, QRectF, QVariantAnimation
from PySide6.QtGui import QFont, QColor, QPalette, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QScrollArea, QSizePolicy, QToolButton, QMenu,
    QApplication, QGraphicsOpacityEffect, QWidgetAction,
    QGraphicsColorizeEffect,
)

from i18n_manager import tr as _tr
from qfluentwidgets import BodyLabel, StrongBodyLabel, FluentIcon, isDarkTheme
from qfluentwidgets.common.config import qconfig

from datetime import datetime

from llm_manager import (
    build_system_prompt, LLMStreamWorker, NonStreamWorker,
    parse_action_tags, strip_action_tags,
)


_BG_LIGHT = "#f5f7fb"
_BG_DARK = "#0f1117"

_USER_BUBBLE_LIGHT = "#e6f0ff"
_USER_BUBBLE_DARK = "#1f355c"
_ASSIST_BUBBLE_LIGHT = "#ffffff"
_ASSIST_BUBBLE_DARK = "#1b1f29"
_TEAMS_ACCENT = "#6264a7"
_TELEGRAM_ACCENT = "#2aabee"


def _rounded_path(rect: QRectF, radii: tuple[float, float, float, float]) -> QPainterPath:
    tl, tr, br, bl = radii
    path = QPainterPath()
    path.moveTo(rect.left() + tl, rect.top())
    path.lineTo(rect.right() - tr, rect.top())
    if tr:
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + tr)
    path.lineTo(rect.right(), rect.bottom() - br)
    if br:
        path.quadTo(rect.right(), rect.bottom(), rect.right() - br, rect.bottom())
    path.lineTo(rect.left() + bl, rect.bottom())
    if bl:
        path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - bl)
    path.lineTo(rect.left(), rect.top() + tl)
    if tl:
        path.quadTo(rect.left(), rect.top(), rect.left() + tl, rect.top())
    path.closeSubpath()
    return path


class RoundedPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg = QColor("transparent")
        self._border = QColor("transparent")
        self._border_width = 0
        self._radii = (0.0, 0.0, 0.0, 0.0)

    def set_panel_style(self, bg: str, border: str = "transparent", radius=0, border_width: int = 0):
        self._bg = QColor(bg)
        self._border = QColor(border)
        self._border_width = border_width
        if isinstance(radius, tuple):
            self._radii = tuple(float(r) for r in radius)
        else:
            r = float(radius)
            self._radii = (r, r, r, r)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self._border_width / 2
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path = _rounded_path(rect, self._radii)
        painter.fillPath(path, self._bg)
        if self._border_width > 0 and self._border.alpha() > 0:
            pen = QPen(self._border, self._border_width)
            painter.setPen(pen)
            painter.drawPath(path)
        super().paintEvent(event)


class IconButton(QToolButton):
    def __init__(self, icon, parent=None, primary: bool = False):
        super().__init__(parent)
        self._primary = primary
        self.setIcon(icon.icon() if hasattr(icon, "icon") else icon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setAutoRaise(True)

    def enterEvent(self, event):
        self._hover_glow(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_glow(False)
        super().leaveEvent(event)

    def _hover_glow(self, entering: bool):
        if hasattr(self, '_hover_anim'):
            self._hover_anim.stop()
        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsColorizeEffect):
            eff = QGraphicsColorizeEffect(self)
            eff.setColor(QColor(255, 255, 255))
            eff.setStrength(0.0)
            self.setGraphicsEffect(eff)
        self._hover_anim = QPropertyAnimation(eff, b"strength")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.setStartValue(eff.strength())
        self._hover_anim.setEndValue(0.3 if entering else 0.0)
        if not entering:
            self._hover_anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._hover_anim.start()

    def apply_theme(self):
        dark = isDarkTheme()
        if self._primary:
            bg = _TELEGRAM_ACCENT
            hover = "#45bdf2"
            pressed = "#168fca"
            fg = "#ffffff"
        else:
            bg = "#2a2f3b" if dark else "#edf2fb"
            hover = "#343b4d" if dark else "#e1e8f6"
            pressed = "#222835" if dark else "#d6deef"
            fg = "#eef2ff" if dark else "#34405a"
        self.setStyleSheet(f"""
            QToolButton {{
                background: {bg};
                color: {fg};
                border: none;
                border-radius: {self.width() // 2}px;
                padding: 0px;
            }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: {pressed}; }}
            QToolButton:disabled {{ background: {'#252932' if dark else '#e6ebf3'}; color: {'#6b7280' if dark else '#a0a8b8'}; }}
        """)


class ConversationHistoryRow(QWidget):
    selected = Signal(int)
    delete_requested = Signal(int)

    def __init__(self, conv_id: int, title: str, current: bool, parent=None):
        super().__init__(parent)
        self._conv_id = conv_id
        self._current = current
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(288, 36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 6, 4)
        layout.setSpacing(8)

        marker = QLabel("✓" if current else "", self)
        marker.setFixedWidth(14)
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(marker)

        label = QLabel(title, self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(label, 1)

        delete_btn = QToolButton(self)
        delete_btn.setText("×")
        delete_btn.setFixedSize(24, 24)
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setToolTip(_tr("ChatWindow.delete_conv"))
        delete_btn.clicked.connect(self._emit_delete)
        layout.addWidget(delete_btn)

        self._marker = marker
        self._label = label
        self._delete_btn = delete_btn
        self.apply_theme()

    def apply_theme(self):
        dark = isDarkTheme()
        bg = "#263044" if self._current and dark else "#eef4ff" if self._current else "transparent"
        text = "#f7f7fb" if dark else "#1f2328"
        marker = _TELEGRAM_ACCENT if self._current else "transparent"
        danger = "#ff6b6b" if dark else "#c42b1c"
        hover = "#3a2630" if dark else "#fde7e9"
        self._hover_bg = hover
        self._normal_bg = bg
        self.setStyleSheet(f"""
            ConversationHistoryRow {{
                background: {bg};
                border-radius: 6px;
            }}
            QLabel {{
                color: {text};
                background: transparent;
            }}
            QToolButton {{
                background: transparent;
                color: {danger};
                border: none;
                border-radius: 12px;
                font-size: 18px;
                font-weight: 700;
                padding-bottom: 2px;
            }}
            QToolButton:hover {{
                background: {hover};
            }}
        """)
        self._marker.setStyleSheet(f"color: {marker}; background: transparent; font-weight: 700;")

    def enterEvent(self, event):
        self._hover_glow(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_glow(False)
        super().leaveEvent(event)

    def _hover_glow(self, entering: bool):
        if hasattr(self, '_hover_anim'):
            self._hover_anim.stop()
        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsColorizeEffect):
            eff = QGraphicsColorizeEffect(self)
            eff.setColor(QColor(96, 205, 255))
            eff.setStrength(0.0)
            self.setGraphicsEffect(eff)
        self._hover_anim = QPropertyAnimation(eff, b"strength")
        self._hover_anim.setDuration(160)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.setStartValue(eff.strength())
        self._hover_anim.setEndValue(0.25 if entering else 0.0)
        if not entering:
            self._hover_anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._hover_anim.start()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._delete_btn.geometry().contains(event.position().toPoint()):
            self.selected.emit(self._conv_id)
        super().mouseReleaseEvent(event)

    def _emit_delete(self):
        self.delete_requested.emit(self._conv_id)


class MessageBubble(QWidget):
    def __init__(self, text: str, role: str, author: str = "", created_at: str = "", parent=None, avatar_color: str = ""):
        super().__init__(parent)
        self._text = text
        self._role = role
        self._author = author or (_tr("ChatWindow.you") if role == "user" else _tr("ChatWindow.you"))
        self._created_at = created_at
        self._avatar_color = avatar_color
        self._streaming = False
        self._dot_step = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(420)
        self._typing_timer.timeout.connect(self._tick_typing)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._init_ui()
        self.apply_theme()
        QTimer.singleShot(0, self._animate_in)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(0)

        self._avatar = QLabel(self._initials(), self)
        self._avatar.setFixedSize(28, 28)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._meta = QLabel(self._meta_text(), self)
        self._meta.setFixedHeight(18)
        meta_font = QFont()
        meta_font.setPointSize(8)
        self._meta.setFont(meta_font)

        self._label = QLabel(self._text, self)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = QFont()
        font.setPointSize(10)
        self._label.setFont(font)

        self._stream_label = QLabel("", self)
        stream_font = QFont()
        stream_font.setPointSize(8)
        self._stream_label.setFont(stream_font)
        self._stream_label.hide()

        self._container = self._make_container(user=self._role == "user")
        bubble_layout = QVBoxLayout(self._container)
        bubble_layout.setContentsMargins(12, 9, 12, 9)
        bubble_layout.setSpacing(4)
        bubble_layout.addWidget(self._label)
        bubble_layout.addWidget(self._stream_label)

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(2)
        stack.addWidget(self._meta)
        stack.addWidget(self._container)

        inner = QHBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)

        if self._role == "user":
            inner.addStretch()
            inner.addLayout(stack, 4)
            inner.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
            inner.setContentsMargins(48, 0, 0, 0)
        else:
            inner.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignTop)
            inner.addLayout(stack, 4)
            inner.addStretch()
            inner.setContentsMargins(0, 0, 48, 0)

        layout.addLayout(inner)

    def _make_container(self, user: bool) -> QWidget:
        w = RoundedPanel()
        w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return w

    def _initials(self) -> str:
        text = self._author.strip()
        return text[:1].upper() if text else ("U" if self._role == "user" else "A")

    def _meta_text(self) -> str:
        if not self._created_at:
            return self._author
        return f"{self._author} - {self._created_at[11:16]}"

    def _animate_in(self):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._fade_anim = anim
        anim.start()

    def _tick_typing(self):
        self._dot_step = (self._dot_step + 1) % 4
        self._stream_label.setText(_tr("ChatWindow.streaming") + "." * self._dot_step)

    def apply_theme(self):
        dark = isDarkTheme()
        user = self._role == "user"
        bubble_bg = _USER_BUBBLE_DARK if user and dark else _USER_BUBBLE_LIGHT if user else _ASSIST_BUBBLE_DARK if dark else _ASSIST_BUBBLE_LIGHT
        border = "#39415a" if dark else "#e4e7ef"
        text = "#f7f7fb" if dark else "#1f2328"
        meta = "#a9b0c3" if dark else "#657089"
        stream = "#82cfff" if dark else "#5470c6"
        avatar_bg = self._avatar_color if user and self._avatar_color else _TELEGRAM_ACCENT if user else _TEAMS_ACCENT
        avatar_text = "#ffffff"
        self._label.setStyleSheet(f"color: {text}; background: transparent;")
        self._meta.setAlignment(Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft)
        self._meta.setStyleSheet(f"color: {meta}; background: transparent; padding: 0 2px;")
        self._stream_label.setStyleSheet(f"color: {stream}; background: transparent;")
        self._avatar.setStyleSheet(f"""
            QLabel {{
                background: {avatar_bg};
                color: {avatar_text};
                border-radius: 14px;
                font-weight: 700;
            }}
        """)
        radii = (18, 6, 18, 18) if user else (6, 18, 18, 18)
        self._container.set_panel_style(bubble_bg, border, radii, 1)

    def set_text(self, text: str):
        self._label.setText(text)

    def set_streaming(self, streaming: bool):
        self._streaming = streaming
        if streaming:
            self._stream_label.show()
            self._tick_typing()
            self._typing_timer.start()
        else:
            self._typing_timer.stop()
            self._stream_label.hide()


class ChatWindow(QWidget):
    action_triggered = Signal(str)
    closed = Signal()

    def __init__(self, character: str, model_manager, live2d_module,
                 config_manager, parent_pet=None):
        super().__init__()
        self._character = character
        self._model_manager = model_manager
        self._live2d = live2d_module
        self._cfg = config_manager
        self._parent_pet = parent_pet
        self._conv_id: int | None = None
        self._worker = None
        self._current_bubble: MessageBubble | None = None
        self._pending_actions: list[str] = []
        self._seen_actions: set[str] = set()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._pending_actions.clear()
        self._seen_actions.clear()
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setInterval(28)
        self._stream_flush_timer.timeout.connect(self._flush_stream_text)
        self._composer_colors = {}

        self._display_name = model_manager.get_display_name(character)
        self._user_name = self._cfg.get("user_name", "").strip() if self._cfg else ""
        self._user_avatar_color = self._cfg.get("user_avatar_color", _TELEGRAM_ACCENT) if self._cfg else _TELEGRAM_ACCENT

        from database_manager import DatabaseManager
        self._db = DatabaseManager()

        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        self.setMinimumSize(360, 520)
        self.resize(420, 620)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._init_ui()
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

        self._load_or_create_conversation()

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(30, self._play_entrance)

    def _play_entrance(self):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._shell = RoundedPanel(self)
        self._shell.setObjectName("ChatShell")
        shell_layout = QVBoxLayout(self._shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        main_layout.addWidget(self._shell)

        self._titlebar = self._build_titlebar()
        shell_layout.addWidget(self._titlebar)

        self._msg_area = QWidget()
        self._msg_area.setObjectName("MessageArea")
        self._msg_layout = QVBoxLayout(self._msg_area)
        self._msg_layout.setContentsMargins(0, 14, 0, 14)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._msg_area)
        shell_layout.addWidget(self._scroll, 1)

        shell_layout.addWidget(self._build_input_area())

    def _build_titlebar(self):
        bar = RoundedPanel()
        bar.setObjectName("Titlebar")
        bar.setFixedHeight(58)
        bar.setCursor(Qt.CursorShape.ArrowCursor)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(10)

        avatar = QLabel(self._display_name[:1].upper(), bar)
        avatar.setObjectName("TitleAvatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setCursor(Qt.CursorShape.PointingHandCursor)
        avatar.setToolTip(_tr("ChatWindow.history_tooltip"))
        avatar.mousePressEvent = self._on_title_avatar_pressed
        layout.addWidget(avatar)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(0)
        title = StrongBodyLabel(self._display_name, bar)
        title.setObjectName("ChatTitle")
        subtitle = BodyLabel(_tr("ChatWindow.subtitle"), bar)
        subtitle.setObjectName("ChatSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        layout.addLayout(title_stack)
        layout.addStretch()

        new_btn = IconButton(FluentIcon.ADD, bar)
        new_btn.setFixedSize(32, 32)
        new_btn.setToolTip(_tr("ChatWindow.new_chat"))
        new_btn.clicked.connect(self._new_conversation)
        layout.addWidget(new_btn)

        close_btn = IconButton(FluentIcon.CLOSE, bar)
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)

        self._new_btn = new_btn
        self._close_btn = close_btn
        self._title_avatar = avatar

        self._drag_start = None

        def mouse_press(event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_start = event.globalPosition().toPoint()

        def mouse_move(event):
            if self._drag_start is not None:
                delta = event.globalPosition().toPoint() - self._drag_start
                self.move(self.x() + delta.x(), self.y() + delta.y())
                self._drag_start = event.globalPosition().toPoint()

        def mouse_release(event):
            self._drag_start = None

        bar.mousePressEvent = mouse_press
        bar.mouseMoveEvent = mouse_move
        bar.mouseReleaseEvent = mouse_release

        return bar

    def _build_input_area(self):
        area = RoundedPanel()
        area.setObjectName("InputArea")
        area.setFixedHeight(108)
        outer = QVBoxLayout(area)
        outer.setContentsMargins(12, 8, 12, 12)
        outer.setSpacing(6)

        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(6, 0, 6, 0)
        hint_row.setSpacing(6)
        self._status_dot = QLabel("", area)
        self._status_dot.setFixedSize(7, 7)
        self._composer_hint = QLabel(_tr("ChatWindow.ready"), area)
        hint_font = QFont()
        hint_font.setPointSize(8)
        self._composer_hint.setFont(hint_font)
        hint_row.addWidget(self._status_dot)
        hint_row.addWidget(self._composer_hint)
        hint_row.addStretch()
        outer.addLayout(hint_row)

        self._composer = RoundedPanel(area)
        self._composer.setObjectName("Composer")
        layout = QHBoxLayout(self._composer)
        layout.setContentsMargins(12, 8, 8, 8)
        layout.setSpacing(8)

        self._input = QTextEdit()
        self._input.setPlaceholderText(_tr("ChatWindow.input_placeholder"))
        self._input.setAcceptRichText(False)
        self._input.setFixedHeight(58)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font = QFont()
        font.setPointSize(10)
        self._input.setFont(font)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.installEventFilter(self)
        self._input.textChanged.connect(self._sync_input_height)
        layout.addWidget(self._input)

        self._send_btn = IconButton(FluentIcon.SEND, self._composer, primary=True)
        self._send_btn.setFixedSize(42, 42)
        self._send_btn.setToolTip(_tr("ChatWindow.send_tooltip"))
        self._send_btn.clicked.connect(self._send_message)
        layout.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)

        outer.addWidget(self._composer)

        self._input_area = area
        return area

    def eventFilter(self, obj, event):
        if obj == self._input and event.type() == QKeyEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._send_message()
                return True
            if event.key() == Qt.Key.Key_Return and not event.modifiers():
                self._send_message()
                return True
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                return False
        if obj == self._input and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self._update_composer_focus_style)
        return super().eventFilter(obj, event)

    def _apply_theme(self):
        dark = isDarkTheme()
        bg = _BG_DARK if dark else _BG_LIGHT
        border = "#242a37" if dark else "#d8deea"
        input_bg = "#181c25" if dark else "#ffffff"
        input_border = "#303849" if dark else "#cfd8ec"
        text_color = "#f8f8fb" if dark else "#1f2328"
        muted = "#a9b0c3" if dark else "#657089"
        title_bg = "#151923" if dark else "#ffffff"
        title_border = "#242a37" if dark else "#e0e6f2"
        composer_bg = "#131720" if dark else "#eef3fb"
        scroll_bg = "#0f1117" if dark else "#f5f7fb"
        self._composer_colors = {
            "bg": input_bg,
            "border": input_border,
            "focus_border": _TELEGRAM_ACCENT if not dark else "#7dd7ff",
        }

        self.setStyleSheet(f"""
            ChatWindow {{
                background: transparent;
            }}
        """)

        self._shell.set_panel_style(bg, border, 14, 1)
        self._titlebar.set_panel_style(title_bg, title_border, (14, 14, 0, 0), 0)
        self._titlebar.setStyleSheet(f"""
            QLabel#TitleAvatar {{
                background: {_TEAMS_ACCENT};
                color: #ffffff;
                border-radius: 17px;
                font-weight: 700;
            }}
            QLabel#ChatSubtitle {{
                color: {muted};
                font-size: 11px;
            }}
        """)

        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {text_color};
                border: none;
                padding: 4px 2px;
                font-size: 13px;
                selection-background-color: {_TEAMS_ACCENT};
            }}
            QTextEdit:disabled {{
                color: {muted};
            }}
        """)

        self._input_area.set_panel_style(composer_bg, title_border, (0, 0, 14, 14), 0)
        self._update_composer_focus_style()

        self._composer_hint.setStyleSheet(f"color: {muted}; background: transparent;")
        self._status_dot.setStyleSheet(f"background: {_TELEGRAM_ACCENT}; border-radius: 3px;")
        self._new_btn.apply_theme()
        self._close_btn.apply_theme()
        self._send_btn.apply_theme()

        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {scroll_bg};
                border: none;
            }}
            QWidget#MessageArea {{
                background: {scroll_bg};
            }}
            QScrollBar:vertical {{
                background: {scroll_bg};
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {'#4c5569' if dark else '#c7d0e3'};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self._scroll.viewport().setStyleSheet(f"background: {scroll_bg};")

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        self.setPalette(pal)

        for bubble in self._message_bubbles():
            bubble.apply_theme()

    def _message_bubbles(self):
        bubbles = []
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, MessageBubble):
                bubbles.append(widget)
        return bubbles

    def _clear_message_widgets(self):
        if self._msg_layout.count() > 0:
            item = self._msg_layout.takeAt(self._msg_layout.count() - 1)
            if item:
                del item
        for i in range(self._msg_layout.count() - 1, -1, -1):
            item = self._msg_layout.takeAt(i)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
            if item:
                del item
        self._msg_layout.addStretch()

    def _conversation_title(self, conv: dict) -> str:
        messages = self._db.get_messages(conv["id"])
        preview = ""
        for msg in messages:
            if msg["role"] == "user" and msg["content"].strip():
                preview = msg["content"].strip().replace("\n", " ")
                break
        if not preview:
            preview = conv.get("title") or _tr("ChatWindow.empty_conv")
        if len(preview) > 28:
            preview = preview[:28] + "..."
        created_at = conv.get("created_at", "")
        time_text = created_at[5:16] if len(created_at) >= 16 else created_at
        return f"{time_text}  {preview}".strip()

    def _on_title_avatar_pressed(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._show_conversation_history()

    def _show_conversation_history(self):
        if self._worker and self._worker.isRunning():
            return
        menu = QMenu(self)
        menu.setObjectName("ConversationHistoryMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        hover = "#263044" if dark else "#eef4ff"
        border = "#303849" if dark else "#d8deea"
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#9aa5bd" if dark else "#657089"
        menu.setStyleSheet(f"""
            QMenu#ConversationHistoryMenu {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 6px;
            }}
            QMenu#ConversationHistoryMenu::item {{
                padding: 8px 28px 8px 10px;
                border-radius: 6px;
                min-width: 288px;
            }}
            QMenu#ConversationHistoryMenu::item:selected {{
                background: {hover};
            }}
            QMenu#ConversationHistoryMenu::separator {{
                height: 1px;
                background: {border};
                margin: 6px 4px;
            }}
            QMenu#ConversationHistoryMenu::item:disabled {{
                color: {muted};
            }}
        """)

        title = menu.addAction(_tr("ChatWindow.history_title"))
        title.setEnabled(False)
        menu.addSeparator()

        conversations = self._db.get_conversations(self._character)
        if not conversations:
            empty = menu.addAction(_tr("ChatWindow.no_convs"))
            empty.setEnabled(False)
        else:
            for conv in conversations:
                row = ConversationHistoryRow(
                    conv["id"],
                    self._conversation_title(conv),
                    conv["id"] == self._conv_id,
                    menu,
                )
                row.selected.connect(lambda conv_id: self._select_history_row(menu, conv_id))
                row.delete_requested.connect(lambda conv_id: self._delete_history_row(menu, conv_id))
                action = QWidgetAction(menu)
                action.setDefaultWidget(row)
                menu.addAction(action)

        menu.addSeparator()
        new_action = menu.addAction(_tr("ChatWindow.new_conversation"))
        new_action.triggered.connect(self._new_conversation)

        pos = self._title_avatar.mapToGlobal(self._title_avatar.rect().bottomLeft())
        menu.exec(pos)

    def _select_history_row(self, menu: QMenu, conv_id: int):
        menu.close()
        self._switch_conversation(conv_id)

    def _delete_history_row(self, menu: QMenu, conv_id: int):
        menu.close()
        self._delete_conversation(conv_id)

    def _switch_conversation(self, conv_id: int):
        if conv_id == self._conv_id:
            return
        if self._worker and self._worker.isRunning():
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._current_bubble = None
        self._conv_id = conv_id
        self._clear_message_widgets()
        self._load_messages()
        self._input.setFocus()

    def _delete_conversation(self, conv_id: int):
        if self._worker and self._worker.isRunning():
            return
        was_current = conv_id == self._conv_id
        self._db.delete_conversation(conv_id)

        if not was_current:
            return

        conversations = self._db.get_conversations(self._character)
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._current_bubble = None
        self._clear_message_widgets()
        if conversations:
            self._conv_id = conversations[0]["id"]
            self._load_messages()
        else:
            self._conv_id = self._db.create_conversation(self._character)
        self._input.setFocus()

    def _set_busy(self, busy: bool):
        self._input.setEnabled(not busy)
        self._send_btn.setEnabled(not busy)
        self._new_btn.setEnabled(not busy)
        self._composer_hint.setText(_tr("ChatWindow.streaming_response") if busy else _tr("ChatWindow.ready"))
        dot = _TEAMS_ACCENT if busy else _TELEGRAM_ACCENT
        self._status_dot.setStyleSheet(f"background: {dot}; border-radius: 3px;")

    def _update_composer_focus_style(self):
        if not self._composer_colors:
            return
        focused = self._input.hasFocus()
        border = self._composer_colors["focus_border"] if focused else self._composer_colors["border"]
        target_width = 2.0 if focused else 1.0
        current_width = getattr(self, '_composer_border_width', 1.0)
        if abs(current_width - target_width) < 0.01:
            self._composer_border_width = target_width
            self._composer.set_panel_style(self._composer_colors["bg"], border, 18, int(target_width))
            return
        self._composer_border_width = target_width
        if hasattr(self, '_composer_focus_anim'):
            self._composer_focus_anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(float(current_width))
        anim.setEndValue(float(target_width))
        anim.valueChanged.connect(lambda v: self._composer.set_panel_style(
            self._composer_colors["bg"],
            self._composer_colors["focus_border"] if focused else self._composer_colors["border"],
            18,
            int(round(v))
        ))
        self._composer_focus_anim = anim
        anim.start()

    def _sync_input_height(self):
        doc_height = int(self._input.document().size().height()) + 10
        input_height = max(42, min(92, doc_height))
        area_height = input_height + 50
        self._input.setFixedHeight(input_height)
        self._input_area.setFixedHeight(area_height)
        scrollbar_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if doc_height > 92 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._input.setVerticalScrollBarPolicy(scrollbar_policy)

    def _load_or_create_conversation(self):
        last = self._db.get_last_conversation(self._character)
        if last:
            self._conv_id = last["id"]
        else:
            self._conv_id = self._db.create_conversation(self._character)
        self._load_messages()

    def _new_conversation(self):
        self._clear_message_widgets()
        self._conv_id = self._db.create_conversation(self._character)

    def _load_messages(self):
        if self._conv_id is None:
            return
        messages = self._db.get_messages(self._conv_id)
        stretch = self._msg_layout.takeAt(self._msg_layout.count() - 1)
        if stretch:
            del stretch
        for m in messages:
            author = self._user_name if m["role"] == "user" and self._user_name else _tr("ChatWindow.you") if m["role"] == "user" else self._display_name
            avatar = self._user_avatar_color if m["role"] == "user" else ""
            bubble = MessageBubble(m["content"], m["role"], author, m.get("created_at", ""), avatar_color=avatar)
            self._msg_layout.addWidget(bubble)
        self._msg_layout.addStretch()
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _send_message(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        model_id = self._cfg.get("llm_model_id", "")

        if not api_url or not api_key or not model_id:
            bubble = MessageBubble(
                _tr("ChatWindow.no_llm_config"),
                "assistant",
                self._display_name,
            )
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
            self._scroll_to_bottom()
            return

        self._input.clear()
        self._set_busy(True)
        self._stream_buffer = ""
        self._visible_stream_text = ""

        user_bubble = MessageBubble(text, "user", self._user_name or _tr("ChatWindow.you"), avatar_color=self._user_avatar_color)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, user_bubble)

        assist_bubble = MessageBubble("", "assistant", self._display_name)
        assist_bubble.set_streaming(True)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, assist_bubble)
        self._current_bubble = assist_bubble
        self._scroll_to_bottom()

        if self._conv_id:
            self._db.add_message(self._conv_id, "user", text)

        system_prompt = build_system_prompt(self._character)
        messages = [{"role": "system", "content": system_prompt}]

        if self._conv_id:
            history = self._db.get_messages(self._conv_id)
            max_history = 20
            for m in history[-(max_history * 2):]:
                messages.append({"role": m["role"], "content": m["content"]})

        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %I:%M %p")
        time_suffix = f"\n\n【后置提示词】\n当前时间：{time_str}"
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                messages[i]["content"] += time_suffix
                break

        use_stream = True
        enable_thinking = self._cfg.get("llm_enable_thinking", None)
        if use_stream:
            self._worker = LLMStreamWorker(api_url, api_key, model_id, messages, enable_thinking)
            self._worker.chunk_received.connect(self._on_chunk_received)
            self._worker.finished.connect(self._on_response_finished)
            self._worker.error.connect(self._on_response_error)
        else:
            self._worker = NonStreamWorker(api_url, api_key, model_id, messages, enable_thinking)
            self._worker.finished.connect(self._on_response_finished_nonstream)
            self._worker.error.connect(self._on_response_error)

        self._worker.start()

    def _on_chunk_received(self, text: str):
        clean = strip_action_tags(text)
        if clean:
            self._stream_buffer += clean
            if self._current_bubble:
                self._current_bubble.set_streaming(True)
            if not self._stream_flush_timer.isActive():
                self._stream_flush_timer.start()

    def _flush_stream_text(self):
        if not self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            return
        if not self._stream_buffer:
            self._stream_flush_timer.stop()
            return

        take = max(1, min(4, len(self._stream_buffer)))
        self._visible_stream_text += self._stream_buffer[:take]
        self._stream_buffer = self._stream_buffer[take:]
        self._current_bubble.set_text(self._visible_stream_text)
        self._scroll_to_bottom()

    def _on_response_finished(self, full_text: str, actions: list):
        self._pending_actions.extend(parse_action_tags(full_text))
        self._flush_actions()

        clean = strip_action_tags(full_text)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(clean)

        if self._conv_id:
            self._db.add_message(self._conv_id, "assistant", clean)

        self._set_busy(False)
        self._input.setFocus()
        self._sync_input_height()
        self._worker = None
        self._current_bubble = None
        self._scroll_to_bottom()

    def _on_response_finished_nonstream(self, full_text: str, actions: list):
        acts = parse_action_tags(full_text)
        self._pending_actions.extend(acts)
        self._flush_actions()

        clean = strip_action_tags(full_text)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(clean)

        if self._conv_id:
            self._db.add_message(self._conv_id, "assistant", clean)

        self._set_busy(False)
        self._input.setFocus()
        self._sync_input_height()
        self._worker = None
        self._current_bubble = None
        self._scroll_to_bottom()

    def _on_response_error(self, error_msg: str):
        if self._current_bubble:
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(f"Error: {error_msg}")
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._set_busy(False)
        self._input.setFocus()
        self._sync_input_height()
        self._worker = None
        self._current_bubble = None

    def _flush_actions(self):
        if not self._pending_actions:
            return
        for action in self._pending_actions:
            key = action.strip().lower()
            if key in self._seen_actions:
                continue
            self._seen_actions.add(key)
            self.action_triggered.emit(action)
        self._pending_actions.clear()

    def emit_action_for_ipc(self, action: str):
        print(f"ACTION\t{action}", flush=True)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def position_next_to_pet(self, pet_window: QWidget):
        pet_geo = pet_window if isinstance(pet_window, QRect) else pet_window.geometry()
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
        else:
            screen_geo = pet_geo

        chat_w = self.width()
        left_space = pet_geo.left() - screen_geo.left()
        right_space = screen_geo.right() - pet_geo.right()

        if left_space >= chat_w + 20:
            x = pet_geo.left() - chat_w - 16
        elif right_space >= chat_w + 20:
            x = pet_geo.right() + 16
        else:
            x = max(screen_geo.left(), pet_geo.left() - chat_w - 16)

        y = pet_geo.top() + (pet_geo.height() - self.height()) // 2
        y = max(screen_geo.top(), min(y, screen_geo.bottom() - self.height()))
        self.move(x, y)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        self._stream_flush_timer.stop()
        self._db.close()
        self.closed.emit()
        super().closeEvent(event)
