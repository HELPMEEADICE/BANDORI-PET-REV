import json
import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QRectF, QSize
from PySide6.QtGui import QFont, QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QGraphicsOpacityEffect, QFrame, QToolButton,
)

from i18n_manager import tr as _tr
from qfluentwidgets import isDarkTheme

from app_theme import (
    BANDORI_PRIMARY,
    BANDORI_PRIMARY_DARK,
    accent_color,
)

from .constants import (
    _USER_BUBBLE_LIGHT, _USER_BUBBLE_DARK,
    _ASSIST_BUBBLE_LIGHT, _ASSIST_BUBBLE_DARK,
    _TEAMS_ACCENT, _TELEGRAM_ACCENT,
    _CHAT_IMAGE_EXTENSIONS,
)
from .avatar_utils import _rounded_avatar_pixmap
from .widgets import FluentContextLabel, RoundedPanel, SearchSourceBadge, ChatImagePreview


class ReasoningHeader(QWidget):
    def __init__(self, on_toggle, parent=None):
        super().__init__(parent)
        self._on_toggle = on_toggle
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_toggle()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MessageBubble(QWidget):
    def __init__(
        self,
        text: str,
        role: str,
        author: str = "",
        created_at: str = "",
        parent=None,
        avatar_color: str = "",
        avatar_path: str = "",
        avatar_data: bytes = b"",
        avatar_focus: str = "center",
        reasoning: str = "",
        show_reasoning: bool = True,
        search_sources: list[dict] | None = None,
        attachments: list[dict] | str | None = None,
    ):
        super().__init__(parent)
        self._text = text
        self._role = role
        self._reasoning = reasoning
        self._show_reasoning = show_reasoning
        self._reasoning_collapsed = True
        self._search_sources = self._normalize_search_sources(search_sources)
        self._attachments = self._normalize_display_attachments(attachments)
        self._author = author or (_tr("ChatWindow.you") if role == "user" else _tr("ChatWindow.you"))
        self._created_at = created_at
        self._avatar_color = avatar_color
        self._avatar_path = avatar_path
        self._avatar_data = avatar_data
        self._avatar_focus = avatar_focus
        self._streaming = False
        self._tts_playing = False
        self._tts_wave_phase = 0.0
        self._dot_step = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(420)
        self._typing_timer.timeout.connect(self._tick_typing)
        self._tts_wave_timer = QTimer(self)
        self._tts_wave_timer.setInterval(55)
        self._tts_wave_timer.timeout.connect(self._tick_tts_wave)
        self._text_opacity_effect = None
        self._text_fade_anim = None
        self._height_anim = None
        self._attachment_previews: list[ChatImagePreview] = []
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

        self._label = FluentContextLabel(self._text, self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        font = QFont()
        font.setPointSize(10)
        self._label.setFont(font)

        self._reasoning_panel = RoundedPanel(self)
        self._reasoning_panel.setVisible(self._should_show_reasoning())
        reasoning_layout = QHBoxLayout(self._reasoning_panel)
        reasoning_layout.setContentsMargins(8, 7, 9, 7)
        reasoning_layout.setSpacing(8)

        self._reasoning_bar = QFrame(self._reasoning_panel)
        self._reasoning_bar.setFixedWidth(3)
        reasoning_layout.addWidget(self._reasoning_bar)

        reasoning_stack = QVBoxLayout()
        reasoning_stack.setContentsMargins(0, 0, 0, 0)
        reasoning_stack.setSpacing(3)
        self._reasoning_header = ReasoningHeader(self._toggle_reasoning_collapsed, self._reasoning_panel)
        reasoning_header_layout = QHBoxLayout(self._reasoning_header)
        reasoning_header_layout.setContentsMargins(0, 0, 0, 0)
        reasoning_header_layout.setSpacing(4)

        self._reasoning_toggle = QToolButton(self._reasoning_header)
        self._reasoning_toggle.setFixedSize(18, 18)
        self._reasoning_toggle.setAutoRaise(True)
        self._reasoning_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reasoning_toggle.clicked.connect(self._toggle_reasoning_collapsed)

        self._reasoning_title = QLabel(_tr("ChatWindow.reasoning_title"), self._reasoning_header)
        self._reasoning_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_font = QFont()
        title_font.setPointSize(8)
        title_font.setBold(True)
        self._reasoning_title.setFont(title_font)
        reasoning_header_layout.addWidget(self._reasoning_toggle)
        reasoning_header_layout.addWidget(self._reasoning_title, 1)
        self._reasoning_label = FluentContextLabel(self._reasoning, self._reasoning_panel)
        self._reasoning_label.setWordWrap(True)
        self._reasoning_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._reasoning_label.setTextFormat(Qt.TextFormat.PlainText)
        self._reasoning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        reasoning_font = QFont()
        reasoning_font.setPointSize(9)
        self._reasoning_label.setFont(reasoning_font)
        reasoning_stack.addWidget(self._reasoning_header)
        reasoning_stack.addWidget(self._reasoning_label)
        reasoning_layout.addLayout(reasoning_stack, 1)
        self._sync_reasoning_collapsed()

        self._stream_label = QLabel("", self)
        self._stream_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        stream_font = QFont()
        stream_font.setPointSize(8)
        self._stream_label.setFont(stream_font)
        self._stream_label.hide()

        self._sources_row = QWidget(self)
        self._sources_row.setStyleSheet("background: transparent;")
        self._sources_layout = QHBoxLayout(self._sources_row)
        self._sources_layout.setContentsMargins(0, 4, 0, 0)
        self._sources_layout.setSpacing(4)
        self._sources_layout.addStretch()
        self._rebuild_source_badges()

        self._attachments_panel = QWidget(self)
        self._attachments_panel.setStyleSheet("background: transparent;")
        attachments_layout = QVBoxLayout(self._attachments_panel)
        attachments_layout.setContentsMargins(0, 3, 0, 0)
        attachments_layout.setSpacing(6)
        for item in self._attachments:
            preview = ChatImagePreview(item, self._attachments_panel)
            self._attachment_previews.append(preview)
            attachments_layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignLeft)
        self._attachments_panel.setVisible(bool(self._attachment_previews))

        self._container = self._make_container(user=self._role == "user")
        bubble_layout = QVBoxLayout(self._container)
        bubble_layout.setContentsMargins(12, 9, 12, 9)
        bubble_layout.setSpacing(4)
        bubble_layout.addWidget(self._reasoning_panel)
        bubble_layout.addWidget(self._label)
        bubble_layout.addWidget(self._attachments_panel)
        bubble_layout.addWidget(self._sources_row)
        bubble_layout.addWidget(self._stream_label)

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(2)
        align = Qt.AlignmentFlag.AlignRight if self._role == "user" else Qt.AlignmentFlag.AlignLeft
        stack.addWidget(self._meta)
        stack.addWidget(self._container, 0, align)

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
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        return w

    def _available_bubble_width(self, viewport_width: int = 0) -> int:
        width = viewport_width or self.width()
        if width <= 0 and self.parentWidget():
            width = self.parentWidget().width()
        if width <= 0:
            width = 320
        return max(80, width - 108)

    @staticmethod
    def _widest_plain_line(label: QLabel) -> int:
        text = label.text().replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n") if text else [""]
        fm = label.fontMetrics()
        return max(fm.horizontalAdvance(line) for line in lines)

    @staticmethod
    def _has_plain_newline(label: QLabel) -> bool:
        return "\n" in label.text().replace("\r\n", "\n").replace("\r", "\n")

    def _natural_bubble_width(self) -> int:
        content_width = self._widest_plain_line(self._label)
        for preview in self._attachment_previews:
            content_width = max(content_width, preview.preferred_width())
        if self._stream_label.isVisible() and self._stream_label.text():
            content_width = max(content_width, self._widest_plain_line(self._stream_label))
        if self._reasoning_panel.isVisible():
            reasoning_width = self._widest_plain_line(self._reasoning_title)
            if not self._reasoning_collapsed:
                reasoning_width = max(reasoning_width, self._widest_plain_line(self._reasoning_label))
            content_width = max(content_width, reasoning_width + 50)
        if self._sources_row.isVisible():
            content_width = max(content_width, len(self._search_sources) * 24)
        return max(36, content_width + 24)

    @staticmethod
    def _plain_text_height(label: QLabel, width: int, wrap: bool = True) -> int:
        text = label.text() or " "
        flags = int(Qt.TextFlag.TextExpandTabs)
        if wrap:
            flags |= int(Qt.TextFlag.TextWordWrap)
        rect = label.fontMetrics().boundingRect(
            QRect(0, 0, max(1, width), 16777215),
            flags,
            text,
        )
        return max(label.fontMetrics().lineSpacing(), rect.height()) + 2

    def _sync_text_label_heights(self, text_width: int, reasoning_text_width: int, wrap_main: bool):
        self._label.setFixedHeight(self._plain_text_height(self._label, text_width, wrap_main))
        if self._stream_label.isVisible():
            self._stream_label.setFixedHeight(
                self._plain_text_height(self._stream_label, text_width, False)
            )
        else:
            self._stream_label.setFixedHeight(0)
        if self._reasoning_label.isVisible():
            self._reasoning_label.setFixedHeight(
                self._plain_text_height(self._reasoning_label, reasoning_text_width, True)
            )
        else:
            self._reasoning_label.setFixedHeight(0)

    def update_bubble_width(self, viewport_width: int = 0):
        available_width = self._available_bubble_width(viewport_width)
        natural_width = self._natural_bubble_width()
        target_width = min(natural_width, available_width)
        should_wrap = natural_width > available_width or self._has_plain_newline(self._label)
        self._label.setWordWrap(should_wrap)
        self._reasoning_label.setWordWrap(True)
        self._container.setFixedWidth(target_width)

        text_width = max(1, target_width - 24)
        self._label.setFixedWidth(text_width)
        self._stream_label.setFixedWidth(text_width)
        for preview in self._attachment_previews:
            preview.set_preview_width(text_width)
        reasoning_text_width = max(1, target_width - 52)
        self._reasoning_title.setFixedWidth(reasoning_text_width)
        self._reasoning_label.setFixedWidth(reasoning_text_width)
        self._sync_text_label_heights(text_width, reasoning_text_width, should_wrap)
        if self.layout():
            self.layout().invalidate()
        if self._container.layout():
            self._container.layout().invalidate()
        self._container.updateGeometry()
        self.updateGeometry()

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
        self.update_bubble_width()

    def _tick_tts_wave(self):
        self._tts_wave_phase = (self._tts_wave_phase + 0.34) % (math.pi * 2.0)
        self._container.set_wave_glow(True, self._tts_wave_phase)

    def apply_theme(self):
        dark = isDarkTheme()
        user = self._role == "user"
        bubble_bg = _USER_BUBBLE_DARK if user and dark else _USER_BUBBLE_LIGHT if user else _ASSIST_BUBBLE_DARK if dark else _ASSIST_BUBBLE_LIGHT
        border = "#39415a" if dark else "#e4e7ef"
        text = "#f7f7fb" if dark else "#1f2328"
        meta = "#a9b0c3" if dark else "#657089"
        stream = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        reasoning_bg = "#22283a" if dark else "#f1f5ff"
        reasoning_border = "#31394e" if dark else "#d9e3f6"
        reasoning_text = "#cbd3e8" if dark else "#4e5b75"
        reasoning_title = "#aeb8d7" if dark else "#5667a7"
        avatar_bg = self._avatar_color if user and self._avatar_color else _TELEGRAM_ACCENT if user else _TEAMS_ACCENT
        avatar_text = "#ffffff"
        avatar_pixmap = _rounded_avatar_pixmap(
            self._avatar_path,
            self._avatar_data,
            28,
            self._avatar_focus,
        )
        if avatar_pixmap.isNull():
            self._avatar.setPixmap(QPixmap())
            self._avatar.setText(self._initials())
        else:
            self._avatar.setText("")
            self._avatar.setPixmap(avatar_pixmap)
        self._label.setStyleSheet(f"color: {text}; background: transparent;")
        for preview in self._attachment_previews:
            preview.apply_theme()
        self._meta.setAlignment(Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft)
        self._meta.setStyleSheet(f"color: {meta}; background: transparent; padding: 0 2px;")
        self._stream_label.setStyleSheet(f"color: {stream}; background: transparent;")
        for index in range(self._sources_layout.count()):
            item = self._sources_layout.itemAt(index)
            widget = item.widget() if item else None
            if isinstance(widget, SearchSourceBadge):
                widget.apply_theme()
        self._reasoning_title.setStyleSheet(f"color: {reasoning_title}; background: transparent;")
        self._reasoning_label.setStyleSheet(f"color: {reasoning_text}; background: transparent;")
        self._reasoning_toggle.setStyleSheet(f"""
            QToolButton {{
                color: {reasoning_title};
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QToolButton:hover {{
                background: {'#30374b' if dark else '#e3ebfb'};
                border-radius: 9px;
            }}
            QToolButton:pressed {{
                background: {'#272e40' if dark else '#d7e1f5'};
                border-radius: 9px;
            }}
        """)
        self._reasoning_bar.setStyleSheet(f"background: {_TEAMS_ACCENT}; border-radius: 1px;")
        self._reasoning_panel.set_panel_style(reasoning_bg, reasoning_border, 9, 1)
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

    @staticmethod
    def _normalize_search_sources(sources) -> list[dict]:
        result = []
        if not isinstance(sources, list):
            return result
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url", "") or "").strip()
            if not url or any(item["url"] == url for item in result):
                continue
            title = str(source.get("title", "") or "").strip() or url
            result.append({"title": title, "url": url})
            if len(result) >= 9:
                break
        return result

    @staticmethod
    def _normalize_display_attachments(attachments) -> list[dict]:
        if not attachments:
            return []
        if isinstance(attachments, str):
            try:
                attachments = json.loads(attachments)
            except (TypeError, ValueError):
                return []
        if not isinstance(attachments, list):
            return []
        result = []
        for item in attachments:
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            path = str(item.get("path", "") or "")
            if not path:
                continue
            try:
                resolved = Path(path)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved.suffix.lower() not in _CHAT_IMAGE_EXTENSIONS or not resolved.exists():
                continue
            result.append(dict(item, path=str(resolved)))
        return result

    def _rebuild_source_badges(self):
        while self._sources_layout.count() > 1:
            item = self._sources_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._sources_row.setVisible(bool(self._search_sources) and self._role != "user")
        for index, source in enumerate(self._search_sources, 1):
            badge = SearchSourceBadge(index, source, self._sources_row)
            badge.apply_theme()
            self._sources_layout.insertWidget(index - 1, badge)

    def set_search_sources(self, sources: list[dict]):
        normalized = self._normalize_search_sources(sources)
        if normalized == self._search_sources:
            return
        self._search_sources = normalized
        self._rebuild_source_badges()
        self.update_bubble_width()

    def set_text(self, text: str):
        if text == self._label.text():
            return
        old_height = self.height()
        if self._streaming and old_height > 0:
            self.setMaximumHeight(old_height)
        self._label.setText(text)
        self.update_bubble_width()
        if self._streaming:
            self._animate_stream_text()
            QTimer.singleShot(0, lambda h=old_height: self._animate_stream_height(h))

    def set_reasoning(self, reasoning: str):
        was_visible = self._reasoning_panel.isVisible()
        old_height = self.height()
        self._reasoning = reasoning.strip()
        if self._streaming and old_height > 0:
            self.setMaximumHeight(old_height)
        self._reasoning_label.setText(self._reasoning)
        self._reasoning_panel.setVisible(self._should_show_reasoning())
        self._sync_reasoning_collapsed()
        self.update_bubble_width()
        if self._streaming:
            if self._reasoning_panel.isVisible() and not was_visible:
                self._animate_stream_text()
            QTimer.singleShot(0, lambda h=old_height: self._animate_stream_height(h))

    def _animate_stream_text(self):
        if self._text_opacity_effect is None:
            self._text_opacity_effect = QGraphicsOpacityEffect(self._label)
            self._label.setGraphicsEffect(self._text_opacity_effect)
        if self._text_fade_anim:
            self._text_fade_anim.stop()
        self._text_opacity_effect.setOpacity(0.55)
        anim = QPropertyAnimation(self._text_opacity_effect, b"opacity", self)
        anim.setDuration(140)
        anim.setStartValue(0.55)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._text_fade_anim = anim
        anim.start()

    def _animate_stream_height(self, old_height: int):
        if not self._streaming or old_height <= 0:
            self.setMaximumHeight(16777215)
            return
        self.layout().activate()
        target_height = max(old_height, self.sizeHint().height())
        if target_height <= old_height:
            self.setMaximumHeight(16777215)
            return
        if self._height_anim:
            self._height_anim.stop()
        anim = QPropertyAnimation(self, b"maximumHeight", self)
        anim.setDuration(170)
        anim.setStartValue(old_height)
        anim.setEndValue(target_height)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setMaximumHeight(16777215))
        self._height_anim = anim
        anim.start()

    def _should_show_reasoning(self) -> bool:
        return self._show_reasoning and bool(self._reasoning) and self._role != "user"

    def _sync_reasoning_collapsed(self):
        collapsed = self._reasoning_collapsed
        self._reasoning_label.setVisible(not collapsed)
        self._reasoning_toggle.setArrowType(
            Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow
        )
        tooltip_key = (
            "ChatWindow.reasoning_expand_tooltip"
            if collapsed
            else "ChatWindow.reasoning_collapse_tooltip"
        )
        self._reasoning_toggle.setToolTip(_tr(tooltip_key))
        self._reasoning_header.setToolTip(_tr(tooltip_key))

    def _toggle_reasoning_collapsed(self):
        self._reasoning_collapsed = not self._reasoning_collapsed
        self._sync_reasoning_collapsed()
        self.update_bubble_width()

    def set_streaming(self, streaming: bool):
        self._streaming = streaming
        if streaming:
            self._stream_label.show()
            self._tick_typing()
            self._typing_timer.start()
        else:
            self._typing_timer.stop()
            self._stream_label.hide()
            self.setMaximumHeight(16777215)
            self.update_bubble_width()

    def set_tts_playing(self, playing: bool):
        if self._tts_playing == playing:
            return
        self._tts_playing = playing
        if playing:
            self._tts_wave_phase = 0.0
            self._container.set_wave_glow(True, self._tts_wave_phase)
            self._tts_wave_timer.start()
        else:
            self._tts_wave_timer.stop()
            self._container.set_wave_glow(False)
