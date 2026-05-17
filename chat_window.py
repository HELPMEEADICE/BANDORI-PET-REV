import fluent_bootstrap  # noqa: F401
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QRect, QRectF, QVariantAnimation, QParallelAnimationGroup
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap, QImage
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QScrollArea, QSizePolicy, QToolButton, QMenu,
    QApplication, QGraphicsOpacityEffect, QWidgetAction,
    QGraphicsColorizeEffect, QFrame, QFileDialog, QMessageBox, QSizeGrip,
)

from i18n_manager import tr as _tr
from qfluentwidgets import Action, BodyLabel, StrongBodyLabel, FluentIcon, RoundMenu, LineEdit, MessageBoxBase, isDarkTheme
from qfluentwidgets.components.widgets.menu import TextEditMenu
from qfluentwidgets.common.config import qconfig
from process_utils import app_base_dir
from app_theme import (
    BANDORI_PRIMARY,
    BANDORI_PRIMARY_HOVER,
    BANDORI_PRIMARY_PRESSED,
    BANDORI_PRIMARY_DARK,
    BANDORI_PRIMARY_DARK_HOVER,
    BANDORI_PRIMARY_DARK_PRESSED,
    BANDORI_PRIMARY_SOFT,
    BANDORI_PRIMARY_SOFT_DARK,
    BANDORI_PRIMARY_SOFT_DARK_HOVER,
    accent_color,
)

import ctypes
import os
import shutil
import sys
from datetime import datetime
import json
import re
from pathlib import Path

if os.name == "nt":
    import ctypes.wintypes

if sys.platform == "darwin":
    import macos_patch
else:
    macos_patch = None

from llm_manager import (
    build_system_prompt, LLMStreamWorker, NonStreamWorker,
    parse_action_tags, strip_action_tags,
)
from action_bus import publish_action


_BG_LIGHT = "#f5f7fb"
_BG_DARK = "#0f1117"

_USER_BUBBLE_LIGHT = BANDORI_PRIMARY_SOFT
_USER_BUBBLE_DARK = BANDORI_PRIMARY_SOFT_DARK
_ASSIST_BUBBLE_LIGHT = "#ffffff"
_ASSIST_BUBBLE_DARK = "#1b1f29"
_TEAMS_ACCENT = "#6264a7"
_TELEGRAM_ACCENT = BANDORI_PRIMARY
_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_AVATAR_PIXMAP_CACHE = {}
_AVATAR_PIXMAP_CACHE_LIMIT = 96

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


def _avatar_cache_key(path: str, data: bytes, size: int, focus: str):
    if path and os.path.exists(path):
        try:
            stat = os.stat(path)
            return "path", path, stat.st_mtime_ns, stat.st_size, size, focus
        except OSError:
            return "path", path, size, focus
    if data:
        sample = data[:2048] + data[-2048:]
        return "data", len(data), hash(sample), size, focus
    return "empty", size, focus


def _opaque_bounds(source: QPixmap) -> tuple[int, int, int, int]:
    image = source.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    width = image.width()
    height = image.height()
    step = max(1, min(width, height) // 180)
    left = width
    right = -1
    top = height
    bottom = -1

    for y in range(0, height, step):
        for x in range(0, width, step):
            if image.pixelColor(x, y).alpha() <= 12:
                continue
            left = min(left, x)
            right = max(right, x)
            top = min(top, y)
            bottom = max(bottom, y)

    if right < left or bottom < top:
        return 0, 0, width, height
    return (
        max(0, left - step),
        max(0, top - step),
        min(width, right + step + 1),
        min(height, bottom + step + 1),
    )


def _avatar_crop(source: QPixmap, focus: str) -> QPixmap:
    width = source.width()
    height = source.height()
    if width <= 0 or height <= 0:
        return source

    if focus != "head":
        side = min(width, height)
        return source.copy((width - side) // 2, (height - side) // 2, side, side)

    left, top, right, bottom = _opaque_bounds(source)
    content_w = max(1, right - left)
    content_h = max(1, bottom - top)
    upper_bottom = top + int(content_h * 0.42)
    image = source.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    step = max(1, min(width, height) // 180)
    x_sum = 0
    count = 0

    for y in range(top, min(bottom, upper_bottom), step):
        for x in range(left, right, step):
            if image.pixelColor(x, y).alpha() > 12:
                x_sum += x
                count += 1

    center_x = (x_sum / count) if count else left + content_w * 0.5
    center_y = top + content_h * 0.23
    side = max(content_h * 0.30, min(content_w, content_h) * 0.45)
    side = min(side, content_h * 0.38, width, height)
    side = max(1, int(side))

    x = int(round(center_x - side / 2))
    y = int(round(center_y - side / 2))
    x = max(0, min(width - side, x))
    y = max(0, min(height - side, y))
    return source.copy(x, y, side, side)


def _rounded_avatar_pixmap(path: str = "", data: bytes = b"", size: int = 28, focus: str = "center") -> QPixmap:
    cache_key = _avatar_cache_key(path, data, size, focus)
    cached = _AVATAR_PIXMAP_CACHE.get(cache_key)
    if cached is not None:
        return QPixmap(cached)

    source = QPixmap()
    if data:
        source.loadFromData(data)
    elif path and os.path.exists(path):
        source.load(path)
    if source.isNull():
        return QPixmap()

    crop = _avatar_crop(source, focus)
    scaled = crop.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    rounded = QPixmap(size, size)
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path_shape = QPainterPath()
    path_shape.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(path_shape)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    _AVATAR_PIXMAP_CACHE[cache_key] = QPixmap(rounded)
    if len(_AVATAR_PIXMAP_CACHE) > _AVATAR_PIXMAP_CACHE_LIMIT:
        _AVATAR_PIXMAP_CACHE.pop(next(iter(_AVATAR_PIXMAP_CACHE)))
    return rounded


class FluentContextTextEdit(QTextEdit):
    def contextMenuEvent(self, event):
        menu = TextEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


class FluentContextLabel(QLabel):
    def contextMenuEvent(self, event):
        if not self.text():
            return

        menu = RoundMenu(parent=self)
        selected_text = self.selectedText()
        copy_text = selected_text or self.text()

        copy_action = Action(FluentIcon.COPY, _tr("Common.copy"), self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(copy_text))
        menu.addAction(copy_action)

        copy_all_action = Action(FluentIcon.SAVE_COPY, _tr("Common.copy_all"), self)
        copy_all_action.triggered.connect(lambda: QApplication.clipboard().setText(self.text()))
        copy_all_action.setEnabled(copy_text != self.text())
        menu.addAction(copy_all_action)

        menu.exec(event.globalPos(), ani=True)


class GroupRenameDialog(MessageBoxBase):
    def __init__(self, current_name: str, parent=None):
        super().__init__(parent)
        self.title_label = StrongBodyLabel(_tr("ChatWindow.rename_group_title"), self.widget)
        self.desc_label = BodyLabel(_tr("ChatWindow.rename_group_label"), self.widget)
        self.desc_label.setWordWrap(True)
        self.name_edit = LineEdit(self.widget)
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setText(current_name)
        self.name_edit.selectAll()
        self.name_edit.returnPressed.connect(self.yesButton.click)

        self.yesButton.setText(_tr("ChatWindow.rename_group_save"))
        self.cancelButton.setText(_tr("ChatWindow.rename_group_cancel"))
        self.widget.setFixedWidth(380)
        self.viewLayout.addWidget(self.title_label)
        self.viewLayout.addWidget(self.desc_label)
        self.viewLayout.addWidget(self.name_edit)
        QTimer.singleShot(0, self.name_edit.setFocus)

    def group_name(self) -> str:
        return self.name_edit.text().strip()


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
            bg = accent_color(dark)
            hover = BANDORI_PRIMARY_DARK_HOVER if dark else BANDORI_PRIMARY_HOVER
            pressed = BANDORI_PRIMARY_DARK_PRESSED if dark else BANDORI_PRIMARY_PRESSED
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
    selected = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, conv_id, title: str, current: bool, parent=None):
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
        bg = BANDORI_PRIMARY_SOFT_DARK if self._current and dark else BANDORI_PRIMARY_SOFT if self._current else "transparent"
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
            eff.setColor(QColor(BANDORI_PRIMARY_DARK))
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


class GroupChatListRow(QWidget):
    selected = Signal(object)
    context_menu_requested = Signal(object, object)

    def __init__(self, characters: list[str], title: str, preview: str, current: bool, parent=None):
        super().__init__(parent)
        self._characters = list(characters)
        self._current = current
        self._hovered = False
        self._pressed = False
        self._bg_color = QColor("transparent")
        self._indicator_color = QColor("transparent")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        avatar = QLabel(title[:1].upper(), self)
        avatar.setObjectName("GroupListAvatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(avatar)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(2)
        title_label = QLabel(title, self)
        title_label.setObjectName("GroupListTitle")
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        preview_label = QLabel(preview, self)
        preview_label.setObjectName("GroupListPreview")
        preview_label.setTextFormat(Qt.TextFormat.PlainText)
        preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_stack.addWidget(title_label)
        text_stack.addWidget(preview_label)
        layout.addLayout(text_stack, 1)

        self._avatar = avatar
        self._title_label = title_label
        self._preview_label = preview_label
        self.apply_theme()

    def apply_theme(self):
        dark = isDarkTheme()
        if dark:
            normal_bg = "transparent"
            hover_bg = "#161c29"
            pressed_bg = "#111724"
            selected_bg = "#12192a"
            selected_hover_bg = "#101626"
            selected_pressed_bg = "#0c1220"
        else:
            normal_bg = "transparent"
            hover_bg = "#f1f4fa"
            pressed_bg = "#e7ecf5"
            selected_bg = "#eaf0fb"
            selected_hover_bg = "#e1e8f5"
            selected_pressed_bg = "#d7e0ef"

        if self._current:
            bg = selected_pressed_bg if self._pressed else selected_hover_bg if self._hovered else selected_bg
        else:
            bg = pressed_bg if self._pressed else hover_bg if self._hovered else normal_bg

        title = "#f8f8fb" if dark else "#1f2328"
        preview = "#a9b0c3" if dark else "#657089"
        avatar_bg = _TEAMS_ACCENT if self._current else ("#2a2f3b" if dark else "#e4eaf6")
        avatar_fg = "#ffffff" if self._current else ("#dce4f7" if dark else "#44506a")
        self._bg_color = QColor(bg)
        self._indicator_color = QColor(accent_color(dark) if self._current else "transparent")
        self.setStyleSheet(f"""
            GroupChatListRow {{
                background: transparent;
            }}
            QLabel#GroupListAvatar {{
                background: {avatar_bg};
                color: {avatar_fg};
                border-radius: 17px;
                font-weight: 700;
            }}
            QLabel#GroupListTitle {{
                color: {title};
                background: transparent;
                font-weight: 600;
            }}
            QLabel#GroupListPreview {{
                color: {preview};
                background: transparent;
                font-size: 11px;
            }}
        """)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self._bg_color.alpha() > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bg_color)
            painter.drawRoundedRect(rect, 8, 8)
        if self._current:
            indicator = QRectF(1, 10, 3, self.height() - 20)
            painter.setBrush(self._indicator_color)
            painter.drawRoundedRect(indicator, 1.5, 1.5)
        super().paintEvent(event)

    def enterEvent(self, event):
        self._hovered = True
        self.apply_theme()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.apply_theme()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.apply_theme()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.apply_theme()
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(list(self._characters))
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.context_menu_requested.emit(list(self._characters), event.globalPos())
        event.accept()


class PlanDivider(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_theme()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        line_color = QColor("#505060" if dark else "#c8cdd4")
        text_color = QColor("#9098a8" if dark else "#8890a0")

        fm = painter.fontMetrics()
        text_width = fm.horizontalAdvance(self._text) + 24
        mid_y = self.height() // 2

        painter.setPen(QPen(line_color, 1))
        gap = 16
        left_end = (self.width() - text_width) // 2 - gap
        right_start = (self.width() + text_width) // 2 + gap
        if left_end > 8:
            painter.drawLine(8, mid_y, int(left_end), mid_y)
        if right_start < self.width() - 8:
            painter.drawLine(int(right_start), mid_y, self.width() - 8, mid_y)

        painter.setPen(text_color)
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        rect = QRectF(0, 0, self.width(), self.height())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)

    def _apply_theme(self):
        self.update()


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
    ):
        super().__init__(parent)
        self._text = text
        self._role = role
        self._reasoning = reasoning
        self._show_reasoning = show_reasoning
        self._author = author or (_tr("ChatWindow.you") if role == "user" else _tr("ChatWindow.you"))
        self._created_at = created_at
        self._avatar_color = avatar_color
        self._avatar_path = avatar_path
        self._avatar_data = avatar_data
        self._avatar_focus = avatar_focus
        self._streaming = False
        self._dot_step = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(420)
        self._typing_timer.timeout.connect(self._tick_typing)
        self._text_opacity_effect = None
        self._text_fade_anim = None
        self._height_anim = None
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
        self._reasoning_title = QLabel(_tr("ChatWindow.reasoning_title"), self._reasoning_panel)
        title_font = QFont()
        title_font.setPointSize(8)
        title_font.setBold(True)
        self._reasoning_title.setFont(title_font)
        self._reasoning_label = FluentContextLabel(self._reasoning, self._reasoning_panel)
        self._reasoning_label.setWordWrap(True)
        self._reasoning_label.setTextFormat(Qt.TextFormat.PlainText)
        self._reasoning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        reasoning_font = QFont()
        reasoning_font.setPointSize(9)
        self._reasoning_label.setFont(reasoning_font)
        reasoning_stack.addWidget(self._reasoning_title)
        reasoning_stack.addWidget(self._reasoning_label)
        reasoning_layout.addLayout(reasoning_stack, 1)

        self._stream_label = QLabel("", self)
        stream_font = QFont()
        stream_font.setPointSize(8)
        self._stream_label.setFont(stream_font)
        self._stream_label.hide()

        self._container = self._make_container(user=self._role == "user")
        bubble_layout = QVBoxLayout(self._container)
        bubble_layout.setContentsMargins(12, 9, 12, 9)
        bubble_layout.setSpacing(4)
        bubble_layout.addWidget(self._reasoning_panel)
        bubble_layout.addWidget(self._label)
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
        if self._stream_label.isVisible() and self._stream_label.text():
            content_width = max(content_width, self._widest_plain_line(self._stream_label))
        if self._reasoning_panel.isVisible():
            reasoning_width = max(
                self._widest_plain_line(self._reasoning_title),
                self._widest_plain_line(self._reasoning_label),
            )
            content_width = max(content_width, reasoning_width + 28)
        return max(36, content_width + 24)

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
        reasoning_text_width = max(1, target_width - 52)
        self._reasoning_title.setFixedWidth(reasoning_text_width)
        self._reasoning_label.setFixedWidth(reasoning_text_width)
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
        self._meta.setAlignment(Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft)
        self._meta.setStyleSheet(f"color: {meta}; background: transparent; padding: 0 2px;")
        self._stream_label.setStyleSheet(f"color: {stream}; background: transparent;")
        self._reasoning_title.setStyleSheet(f"color: {reasoning_title}; background: transparent;")
        self._reasoning_label.setStyleSheet(f"color: {reasoning_text}; background: transparent;")
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


class ChatWindow(QWidget):
    action_triggered = Signal(str, str)
    closed = Signal()

    def __init__(self, character: str, model_manager, live2d_module,
                 config_manager, parent_pet=None, group_characters=None):
        super().__init__()
        self._character = character
        self._available_group_characters = self._normalize_group_characters(group_characters or [])
        self._group_characters = list(self._available_group_characters)
        self._is_group_chat = len(self._group_characters) > 1
        self._conversation_key = self._conversation_key_for(self._group_characters if self._is_group_chat else [character])
        self._model_manager = model_manager
        self._live2d = live2d_module
        self._cfg = config_manager
        self._parent_pet = parent_pet
        self._conv_id: int | None = None
        self._group_conv_id = ""
        self._worker = None
        self._current_bubble: MessageBubble | None = None
        self._pending_actions: list[str] = []
        self._pending_action_character = character
        self._seen_actions: set[str] = set()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._pending_actions.clear()
        self._seen_actions.clear()
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setInterval(28)
        self._stream_flush_timer.timeout.connect(self._flush_stream_text)
        self._composer_colors = {}
        self._group_queue: list[str] = []
        self._group_spoken: list[str] = []
        self._group_plan_worker = None
        self._plan_divider = None
        self._active_response_character = character
        self._closing = False
        self._close_animating = False
        self._window_anim = None
        self._pending_history_menu_action = None

        self._user_name = self._cfg.get("user_name", "").strip() if self._cfg else ""
        self._user_avatar_color = self._cfg.get("user_avatar_color", _TELEGRAM_ACCENT) if self._cfg else _TELEGRAM_ACCENT
        avatar_paths = self._cfg.get("chat_avatar_paths", {}) if self._cfg else {}
        self._chat_avatar_paths = avatar_paths if isinstance(avatar_paths, dict) else {}
        self._show_reasoning = bool(self._cfg.get("llm_show_reasoning", True)) if self._cfg else True

        from database_manager import DatabaseManager
        self._db = DatabaseManager()
        if not self._is_group_chat:
            self._db.delete_empty_conversations(self._conversation_key)
        self._display_name = self._chat_display_name()

        icon_path = os.path.join(app_base_dir(), "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        if self._is_group_chat:
            self.setMinimumSize(720, 600)
            self.resize(880, 680)
        else:
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

    def _normalize_group_characters(self, characters: list[str]) -> list[str]:
        result = []
        seen = set()
        for character in characters:
            if not character or character in seen:
                continue
            result.append(character)
            seen.add(character)
        return result

    def _conversation_key_for(self, characters: list[str]) -> str:
        normalized = self._normalize_group_characters(characters)
        if len(normalized) <= 1:
            return normalized[0] if normalized else self._character
        return "__group__:" + "|".join(sorted(normalized, key=str.casefold))

    def _characters_for_group_key(self, group_key: str) -> list[str]:
        if not group_key.startswith("__group__:"):
            return []
        allowed = set(self._model_manager.characters)
        return [character for character in group_key[len("__group__:"):].split("|") if character in allowed]

    def _group_display_name(self, characters: list[str]) -> str:
        group_key = self._conversation_key_for(characters)
        if hasattr(self, "_db") and group_key.startswith("__group__:"):
            custom_name = self._db.get_group_display_name(group_key).strip()
            if custom_name:
                return custom_name
        return self._group_default_display_name(characters)

    def _group_default_display_name(self, characters: list[str]) -> str:
        names = [self._model_manager.get_display_name(character) for character in characters]
        return "、".join(names)

    def _chat_display_name(self) -> str:
        if self._is_group_chat:
            members = self._group_display_name(self._group_characters)
            return _tr("ChatWindow.group_chat_named", members=members)
        return self._model_manager.get_display_name(self._character)

    def _group_chats(self) -> list[dict]:
        result = []
        seen = set()
        for chat in self._db.get_group_chats():
            characters = self._characters_for_group_key(chat.get("group_key", ""))
            if len(characters) <= 1:
                continue
            group_key = self._conversation_key_for(characters)
            if group_key in seen:
                continue
            seen.add(group_key)
            entry = dict(chat)
            entry["characters"] = characters
            entry["group_key"] = group_key
            result.append(entry)
        live2d_characters = self._normalize_group_characters(self._available_group_characters)
        live2d_key = self._conversation_key_for(live2d_characters)
        if len(live2d_characters) > 1 and live2d_key not in seen:
            result.insert(0, {
                "group_key": live2d_key,
                "conversation_id": "",
                "content": "",
                "created_at": "",
                "characters": live2d_characters,
            })
        return result

    def _new_group_conversation_id(self) -> str:
        return "group-" + datetime.now().strftime("%Y%m%d%H%M%S%f")

    def _ensure_group_conversation_id(self) -> str:
        if not self._group_conv_id:
            self._group_conv_id = self._new_group_conversation_id()
        return self._group_conv_id

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_11_border_fix()
        if macos_patch is not None:
            QTimer.singleShot(0, self._apply_macos_window_polish)
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(0, self._play_entrance)

    def _apply_macos_window_polish(self):
        if macos_patch is None:
            return
        macos_patch.set_window_no_shadow(self)
        macos_patch.set_window_level_floating(self)
        # Tool window = NSPanel; default hidesOnDeactivate makes it disappear
        # whenever the user clicks another app. Pin the chat visible.
        macos_patch.set_hides_on_deactivate(self, False)

    def _apply_windows_11_border_fix(self):
        if os.name != "nt" or _dwm_set_window_attribute is None:
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        for attr, value in (
            (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND),
            (DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE),
        ):
            value_ref = ctypes.c_int(value)
            try:
                _dwm_set_window_attribute(
                    hwnd,
                    attr,
                    ctypes.byref(value_ref),
                    ctypes.sizeof(value_ref),
                )
            except Exception:
                pass

    def _play_entrance(self):
        target = self.geometry()
        start = self._scaled_geometry(target, 0.94)
        self.setWindowOpacity(0.0)
        self.setGeometry(start)

        group = QParallelAnimationGroup(self)
        opacity = QPropertyAnimation(self, b"windowOpacity")
        opacity.setDuration(180)
        opacity.setStartValue(0.0)
        opacity.setEndValue(1.0)
        opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(opacity)

        geometry = QPropertyAnimation(self, b"geometry")
        geometry.setDuration(220)
        geometry.setStartValue(start)
        geometry.setEndValue(target)
        geometry.setEasingCurve(QEasingCurve.Type.OutCubic)
        group.addAnimation(geometry)

        self._window_anim = group
        group.start()

    def _play_close_animation(self):
        if self._close_animating:
            return
        self._close_animating = True
        start = self.geometry()
        end = self._scaled_geometry(start, 0.96)

        group = QParallelAnimationGroup(self)
        opacity = QPropertyAnimation(self, b"windowOpacity")
        opacity.setDuration(140)
        opacity.setStartValue(self.windowOpacity())
        opacity.setEndValue(0.0)
        opacity.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(opacity)

        geometry = QPropertyAnimation(self, b"geometry")
        geometry.setDuration(160)
        geometry.setStartValue(start)
        geometry.setEndValue(end)
        geometry.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(geometry)

        group.finished.connect(self._finish_animated_close)
        self._window_anim = group
        group.start()

    @staticmethod
    def _scaled_geometry(rect: QRect, scale: float) -> QRect:
        width = max(1, int(rect.width() * scale))
        height = max(1, int(rect.height() * scale))
        return QRect(
            rect.center().x() - width // 2,
            rect.center().y() - height // 2,
            width,
            height,
        )

    def _finish_animated_close(self):
        self._closing = True
        self._close_animating = False
        self.close()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._shell = RoundedPanel(self)
        self._shell.setObjectName("ChatShell")
        main_layout.addWidget(self._shell)
        self._resize_grip = None

        if self._is_group_chat:
            shell_layout = QHBoxLayout(self._shell)
            shell_layout.setContentsMargins(0, 0, 0, 0)
            shell_layout.setSpacing(0)
            self._group_sidebar = self._build_group_sidebar()
            shell_layout.addWidget(self._group_sidebar, 1)

            content = QWidget(self._shell)
            content.setObjectName("ChatContent")
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            shell_layout.addWidget(content, 3)
        else:
            self._group_sidebar = None
            shell_layout = QVBoxLayout(self._shell)
            shell_layout.setContentsMargins(0, 0, 0, 0)
            shell_layout.setSpacing(0)
            content_layout = shell_layout

        self._titlebar = self._build_titlebar()
        content_layout.addWidget(self._titlebar)

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
        content_layout.addWidget(self._scroll, 1)

        content_layout.addWidget(self._build_input_area())

        if self._is_group_chat:
            self._resize_grip = QSizeGrip(self._shell)
            self._resize_grip.setObjectName("GroupChatResizeGrip")
            self._resize_grip.setFixedSize(18, 18)
            self._resize_grip.raise_()
            self._position_resize_grip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_resize_grip()
        self._relayout_message_bubbles()

    def _position_resize_grip(self):
        if not getattr(self, "_resize_grip", None):
            return
        margin = 6
        self._resize_grip.move(
            max(0, self._shell.width() - self._resize_grip.width() - margin),
            max(0, self._shell.height() - self._resize_grip.height() - margin),
        )

    def _build_group_sidebar(self):
        sidebar = RoundedPanel(self._shell)
        sidebar.setObjectName("GroupSidebar")
        sidebar.setFixedWidth(220)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 10, 12)
        layout.setSpacing(10)

        title = StrongBodyLabel(_tr("ChatWindow.group_list"), sidebar)
        title.setObjectName("GroupSidebarTitle")
        subtitle = BodyLabel(_tr("ChatWindow.group_list_hint"), sidebar)
        subtitle.setObjectName("GroupSidebarSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        scroll = QScrollArea(sidebar)
        scroll.setObjectName("GroupListScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        list_widget = QWidget(scroll)
        list_widget.setObjectName("GroupList")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 2, 4, 2)
        list_layout.setSpacing(6)
        scroll.setWidget(list_widget)
        layout.addWidget(scroll, 1)

        self._group_sidebar_title = title
        self._group_sidebar_subtitle = subtitle
        self._group_list_scroll = scroll
        self._group_list_widget = list_widget
        self._group_list_layout = list_layout
        self._refresh_group_list()
        return sidebar

    def _group_preview(self, chat: dict) -> str:
        preview = str(chat.get("content", "")).strip().replace("\n", " ")
        if preview.startswith("【") and "】" in preview:
            preview = preview[preview.index("】") + 1:].strip()
        if not preview:
            preview = _tr("ChatWindow.empty_conv")
        if len(preview) > 28:
            preview = preview[:28] + "..."
        created_at = str(chat.get("created_at", ""))
        time_text = created_at[5:16] if len(created_at) >= 16 else created_at
        return f"{time_text}  {preview}".strip()

    def _refresh_group_list(self):
        if not hasattr(self, "_group_list_layout"):
            return
        while self._group_list_layout.count():
            item = self._group_list_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
            if item:
                del item

        current_key = self._conversation_key_for(self._group_characters)
        chats = self._group_chats()
        if not chats:
            empty = BodyLabel(_tr("ChatWindow.no_convs"), self._group_list_widget)
            empty.setObjectName("GroupListEmpty")
            empty.setWordWrap(True)
            self._group_list_layout.addWidget(empty)
            self._group_list_layout.addStretch()
            return

        for idx, chat in enumerate(chats):
            combo = chat["characters"]
            row = GroupChatListRow(
                combo,
                self._group_display_name(combo),
                self._group_preview(chat),
                self._conversation_key_for(combo) == current_key,
                self._group_list_widget,
            )
            row.selected.connect(self._switch_group_chat)
            row.context_menu_requested.connect(self._show_group_chat_context_menu)
            self._group_list_layout.addWidget(row)
            if idx < len(chats) - 1:
                separator = QFrame(self._group_list_widget)
                separator.setObjectName("GroupListSeparator")
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFixedHeight(1)
                self._group_list_layout.addWidget(separator)
        self._group_list_layout.addStretch()

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
        avatar.setToolTip(_tr("ChatWindow.avatar_tooltip"))
        avatar.mouseReleaseEvent = self._on_title_avatar_released
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
        self._title_label = title
        self._update_title_avatar()

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

    def _title_avatar_character(self) -> str:
        return "" if self._is_group_chat else self._character

    def _avatar_info_for_character(self, character: str) -> tuple[str, bytes, str]:
        if not character:
            return "", b"", "center"
        custom_path = str(self._chat_avatar_paths.get(character, "")).strip()
        if custom_path and os.path.exists(custom_path):
            return custom_path, b"", "center"
        path = self._model_manager.get_character_image_path(character)
        if path:
            return path, b"", "head"
        data = self._model_manager.get_character_image_data(character)
        return "", data, "head" if data else "center"

    def _update_title_avatar(self):
        if not hasattr(self, "_title_avatar"):
            return
        character = self._title_avatar_character()
        path, data, focus = self._avatar_info_for_character(character)
        pixmap = _rounded_avatar_pixmap(path, data, 34, focus)
        if pixmap.isNull():
            self._title_avatar.setPixmap(QPixmap())
            self._title_avatar.setText(self._display_name[:1].upper())
        else:
            self._title_avatar.setText("")
            self._title_avatar.setPixmap(pixmap)

    def _message_character(self, content: str, role: str) -> str:
        if role != "assistant":
            return ""
        if not self._is_group_chat:
            return self._character
        first_line = content.splitlines()[0].strip() if content else ""
        if first_line.startswith("【") and "】" in first_line:
            name = first_line[1:first_line.index("】")]
            for character in self._group_characters:
                if name == self._model_manager.get_display_name(character):
                    return character
        for character in self._group_characters:
            display = self._model_manager.get_display_name(character)
            if content.startswith(f"【{display}】"):
                return character
        return ""

    def _avatar_storage_dir(self) -> Path:
        return Path(app_base_dir()) / ".runtime" / "chat_avatars"

    def _safe_avatar_name(self, character: str, ext: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", character).strip("._")
        return f"{safe or 'avatar'}{ext}"

    def _set_character_avatar(self, character: str):
        if not character:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _tr("ChatWindow.avatar_choose_title"),
            "",
            _tr("ChatWindow.avatar_image_filter"),
        )
        if not file_path:
            return
        source = Path(file_path)
        ext = source.suffix.lower()
        if ext not in _AVATAR_EXTENSIONS:
            ext = ".png"
        try:
            target_dir = self._avatar_storage_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / self._safe_avatar_name(character, ext)
            shutil.copyfile(source, target)
            self._chat_avatar_paths[character] = str(target)
            if self._cfg:
                self._cfg.set("chat_avatar_paths", dict(self._chat_avatar_paths))
                self._cfg.save()
            self._refresh_avatar_views()
        except Exception as exc:
            QMessageBox.warning(
                self,
                _tr("ChatWindow.avatar_save_failed_title"),
                _tr("ChatWindow.avatar_save_failed_content", error=str(exc)),
            )

    def _reset_character_avatar(self, character: str):
        if not character:
            return
        if character in self._chat_avatar_paths:
            self._chat_avatar_paths.pop(character, None)
            if self._cfg:
                self._cfg.set("chat_avatar_paths", dict(self._chat_avatar_paths))
                self._cfg.save()
            self._refresh_avatar_views()

    def _refresh_avatar_views(self):
        self._update_title_avatar()
        if self._is_group_chat or self._conv_id is not None:
            self._clear_message_widgets()
            self._load_messages()

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
        self._composer_hint = QLabel(self._idle_status_text(), area)
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

        self._input = FluentContextTextEdit()
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
            "focus_border": accent_color(dark),
        }

        self.setStyleSheet("""
            ChatWindow {
                background: transparent;
            }
        """)

        self._shell.set_panel_style(bg, border, 14, 1)
        title_radius = (0, 14, 0, 0) if self._is_group_chat else (14, 14, 0, 0)
        input_radius = (0, 0, 14, 0) if self._is_group_chat else (0, 0, 14, 14)
        self._titlebar.set_panel_style(title_bg, title_border, title_radius, 0)
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

        if self._group_sidebar is not None:
            sidebar_bg = "#151923" if dark else "#ffffff"
            sidebar_border = "#242a37" if dark else "#e0e6f2"
            self._group_sidebar.set_panel_style(sidebar_bg, sidebar_border, (14, 0, 0, 14), 0)
            self._group_sidebar.setStyleSheet(f"""
                QLabel#GroupSidebarTitle {{
                    color: {text_color};
                    background: transparent;
                    font-size: 15px;
                    font-weight: 700;
                }}
                QLabel#GroupSidebarSubtitle {{
                    color: {muted};
                    background: transparent;
                    font-size: 11px;
                }}
                QLabel#GroupListEmpty {{
                    color: {muted};
                    background: transparent;
                    padding: 10px;
                }}
                QFrame#GroupListSeparator {{
                    background: {sidebar_border};
                    border: none;
                    margin-left: 46px;
                    margin-right: 8px;
                }}
            """)
            self._group_list_scroll.setStyleSheet(f"""
                QScrollArea#GroupListScroll {{
                    background: {sidebar_bg};
                    border: none;
                }}
                QWidget#GroupList {{
                    background: {sidebar_bg};
                }}
                QScrollBar:vertical {{
                    background: {sidebar_bg};
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
            for i in range(self._group_list_layout.count()):
                item = self._group_list_layout.itemAt(i)
                widget = item.widget() if item else None
                if isinstance(widget, GroupChatListRow):
                    widget.apply_theme()

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

        self._input_area.set_panel_style(composer_bg, title_border, input_radius, 0)
        self._update_composer_focus_style()

        self._composer_hint.setStyleSheet(f"color: {muted}; background: transparent;")
        self._status_dot.setStyleSheet(f"background: {_TELEGRAM_ACCENT}; border-radius: 3px;")
        self._new_btn.apply_theme()
        self._close_btn.apply_theme()
        self._send_btn.apply_theme()
        self._update_title_avatar()

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

    def _relayout_message_bubbles(self):
        if not hasattr(self, "_scroll"):
            return
        viewport_width = self._scroll.viewport().width()
        for bubble in self._message_bubbles():
            bubble.update_bubble_width(viewport_width)

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

    def _on_title_avatar_released(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        event.accept()
        self._show_conversation_history()

    def _show_conversation_history(self):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        menu = QMenu(self)
        menu.setObjectName("ConversationHistoryMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT
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

        if self._is_group_chat:
            conversations = self._db.get_group_conversations(self._conversation_key)
            title = menu.addAction(_tr("ChatWindow.history_title"))
            title.setEnabled(False)
            if conversations:
                for conv in conversations:
                    row = ConversationHistoryRow(
                        conv["conversation_id"],
                        self._group_preview(conv),
                        conv["conversation_id"] == self._group_conv_id,
                        menu,
                    )
                    row.selected.connect(lambda conv_id: self._select_group_history_row(menu, conv_id))
                    row.delete_requested.connect(lambda conv_id: self._delete_group_history_row(menu, conv_id))
                    action = QWidgetAction(menu)
                    action.setDefaultWidget(row)
                    menu.addAction(action)
            else:
                empty = menu.addAction(_tr("ChatWindow.no_convs"))
                empty.setEnabled(False)
            menu.addSeparator()

            change_menu = menu.addMenu(_tr("ChatWindow.avatar_change_menu"))
            reset_menu = menu.addMenu(_tr("ChatWindow.avatar_reset_menu"))
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                change_action = change_menu.addAction(display)
                change_action.triggered.connect(lambda _checked=False, c=character: self._set_character_avatar(c))
                reset_action = reset_menu.addAction(display)
                reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
                reset_action.triggered.connect(lambda _checked=False, c=character: self._reset_character_avatar(c))
            pos = self._title_avatar.mapToGlobal(self._title_avatar.rect().bottomLeft())
            self._pending_history_menu_action = None
            menu.exec(pos)
            self._run_pending_history_menu_action()
            return
        else:
            change_action = menu.addAction(_tr("ChatWindow.avatar_change"))
            change_action.triggered.connect(lambda: self._set_character_avatar(self._character))
            reset_action = menu.addAction(_tr("ChatWindow.avatar_reset"))
            reset_action.setEnabled(bool(self._chat_avatar_paths.get(self._character)))
            reset_action.triggered.connect(lambda: self._reset_character_avatar(self._character))
        menu.addSeparator()

        title = menu.addAction(_tr("ChatWindow.history_title"))
        title.setEnabled(False)
        menu.addSeparator()

        conversations = self._db.get_conversations(self._conversation_key)
        if not conversations:
            empty = menu.addAction(_tr("ChatWindow.no_convs"))
            empty.setEnabled(False)
        elif len(conversations) > 10:
            container = QWidget(menu)
            container.setObjectName("ConversationHistoryList")
            layout = QVBoxLayout(container)
            layout.setContentsMargins(4, 4, 8, 4)
            layout.setSpacing(4)
            for conv in conversations:
                row = ConversationHistoryRow(
                    conv["id"],
                    self._conversation_title(conv),
                    conv["id"] == self._conv_id,
                    container,
                )
                row.selected.connect(lambda conv_id: self._select_history_row(menu, conv_id))
                row.delete_requested.connect(lambda conv_id: self._delete_history_row(menu, conv_id))
                layout.addWidget(row)

            scroll = QScrollArea(menu)
            scroll.setObjectName("ConversationHistoryScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFixedSize(312, 10 * 40 + 8)
            scroll.setWidget(container)
            scroll.viewport().setAutoFillBackground(False)
            scroll.setStyleSheet(f"""
                QScrollArea#ConversationHistoryScroll {{
                    background: {bg};
                    border: none;
                }}
                QScrollArea#ConversationHistoryScroll > QWidget > QWidget {{
                    background: {bg};
                }}
                QWidget#ConversationHistoryList {{
                    background: {bg};
                }}
                QScrollArea#ConversationHistoryScroll QScrollBar:vertical {{
                    background: {bg};
                    width: 8px;
                    margin: 4px 0px 4px 0px;
                }}
                QScrollArea#ConversationHistoryScroll QScrollBar::handle:vertical {{
                    background: {'#566074' if dark else '#c4cfe3'};
                    border-radius: 4px;
                    min-height: 30px;
                }}
                QScrollArea#ConversationHistoryScroll QScrollBar::handle:vertical:hover {{
                    background: {'#69758d' if dark else '#aebbd4'};
                }}
                QScrollArea#ConversationHistoryScroll QScrollBar::add-line:vertical,
                QScrollArea#ConversationHistoryScroll QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
                QScrollArea#ConversationHistoryScroll QScrollBar::add-page:vertical,
                QScrollArea#ConversationHistoryScroll QScrollBar::sub-page:vertical {{
                    background: transparent;
                }}
            """)
            scroll_action = QWidgetAction(menu)
            scroll_action.setDefaultWidget(scroll)
            menu.addAction(scroll_action)
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
        self._pending_history_menu_action = None
        menu.exec(pos)
        self._run_pending_history_menu_action()

    def _select_history_row(self, menu: QMenu, conv_id: int):
        self._pending_history_menu_action = ("switch", conv_id)
        QTimer.singleShot(0, menu.close)

    def _select_group_history_row(self, menu: QMenu, conversation_id: str):
        self._pending_history_menu_action = ("switch_group", conversation_id)
        QTimer.singleShot(0, menu.close)

    def _delete_group_history_row(self, menu: QMenu, conversation_id: str):
        self._pending_history_menu_action = ("delete_group", conversation_id)
        QTimer.singleShot(0, menu.close)

    def _delete_history_row(self, menu: QMenu, conv_id: int):
        self._pending_history_menu_action = ("delete", conv_id)
        QTimer.singleShot(0, menu.close)

    def _run_pending_history_menu_action(self):
        action = self._pending_history_menu_action
        self._pending_history_menu_action = None
        if not action:
            return
        name, value = action
        if name == "switch":
            QTimer.singleShot(0, lambda value=value: self._switch_conversation(value))
        elif name == "delete":
            QTimer.singleShot(0, lambda value=value: self._delete_conversation(value))
        elif name == "switch_group":
            QTimer.singleShot(0, lambda value=value: self._switch_group_conversation(value))
        elif name == "delete_group":
            QTimer.singleShot(0, lambda value=value: self._delete_group_conversation(value))

    def _switch_group_chat(self, characters: list[str]):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        normalized = self._normalize_group_characters(characters)
        if len(normalized) <= 1:
            return
        next_key = self._conversation_key_for(normalized)
        if next_key == self._conversation_key:
            return

        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._group_characters = normalized
        self._is_group_chat = True
        self._conversation_key = next_key
        self._display_name = self._chat_display_name()
        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        if hasattr(self, "_title_label"):
            self._title_label.setText(self._display_name)
        self._update_title_avatar()
        self._clear_message_widgets()
        self._conv_id = None
        self._load_or_create_conversation()
        self._refresh_group_list()
        self._input.setFocus()

    def _switch_group_conversation(self, conversation_id: str):
        if conversation_id == self._group_conv_id:
            return
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._group_conv_id = conversation_id
        self._clear_message_widgets()
        self._load_messages()
        self._input.setFocus()

    def _show_group_chat_context_menu(self, characters: list[str], global_pos):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        group_key = self._conversation_key_for(characters)
        if not group_key.startswith("__group__:"):
            return
        menu = RoundMenu(parent=self)
        rename_action = Action(FluentIcon.EDIT, _tr("ChatWindow.rename_group"), self)
        rename_action.triggered.connect(lambda: self._rename_group_chat(characters))
        menu.addAction(rename_action)
        menu.exec(global_pos, ani=True)

    def _rename_group_chat(self, characters: list[str]):
        group_key = self._conversation_key_for(characters)
        default_name = self._group_default_display_name(characters)
        current_name = self._db.get_group_display_name(group_key).strip() or default_name
        dialog = GroupRenameDialog(current_name, self)
        if not dialog.exec():
            return
        new_name = dialog.group_name()
        self._db.set_group_display_name(group_key, new_name if new_name != default_name else "")
        if group_key == self._conversation_key:
            self._display_name = self._chat_display_name()
            self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
            if hasattr(self, "_title_label"):
                self._title_label.setText(self._display_name)
            self._update_title_avatar()
        self._refresh_group_list()

    def _switch_conversation(self, conv_id: int):
        if conv_id == self._conv_id:
            return
        if self._worker and self._worker.isRunning():
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
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
        self._refresh_group_list()

        if not was_current:
            return

        conversations = self._db.get_conversations(self._conversation_key)
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._clear_message_widgets()
        if conversations:
            self._conv_id = conversations[0]["id"]
            self._load_messages()
        else:
            self._conv_id = None
        self._input.setFocus()

    def _delete_group_conversation(self, conversation_id: str):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        was_current = conversation_id == self._group_conv_id
        self._db.delete_group_conversation(self._conversation_key, conversation_id)
        self._refresh_group_list()

        if not was_current:
            return

        conversations = self._db.get_group_conversations(self._conversation_key)
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._clear_message_widgets()
        self._group_conv_id = conversations[0]["conversation_id"] if conversations else ""
        if self._group_conv_id:
            self._load_messages()
        self._input.setFocus()

    def _has_llm_config(self) -> bool:
        return bool(
            self._cfg
            and self._cfg.get("llm_api_url", "").strip()
            and self._cfg.get("llm_api_key", "").strip()
            and self._cfg.get("llm_model_id", "").strip()
        )

    def _idle_status_text(self) -> str:
        return _tr("ChatWindow.ready") if self._has_llm_config() else _tr("ChatWindow.not_configured")

    def _set_busy(self, busy: bool, planning: bool = False):
        self._input.setEnabled(not busy)
        self._send_btn.setEnabled(not busy)
        self._new_btn.setEnabled(not busy)
        if planning:
            status = _tr("ChatWindow.planning_group_response")
        elif busy:
            status = _tr("ChatWindow.streaming_response")
        else:
            status = self._idle_status_text()
        self._composer_hint.setText(status)
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
        if self._is_group_chat:
            conversations = self._db.get_group_conversations(self._conversation_key)
            self._group_conv_id = conversations[0]["conversation_id"] if conversations else ""
            self._load_messages()
            return
        last = self._db.get_last_conversation(self._conversation_key)
        if last:
            self._conv_id = last["id"]
        self._load_messages()

    def _new_conversation(self):
        if self._worker and self._worker.isRunning():
            return
        if self._is_group_chat:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = ""
            self._reasoning_stream_text = ""
            self._current_bubble = None
            self._clear_message_widgets()
            self._group_conv_id = self._new_group_conversation_id()
            self._refresh_group_list()
            self._input.setFocus()
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._clear_message_widgets()
        self._conv_id = None

    def _load_messages(self):
        if self._is_group_chat:
            if not self._group_conv_id:
                return
            messages = self._db.get_group_messages(self._conversation_key, self._group_conv_id)
        elif self._conv_id is None:
            return
        else:
            messages = self._db.get_messages(self._conv_id)
        stretch = self._msg_layout.takeAt(self._msg_layout.count() - 1)
        if stretch:
            del stretch
        for m in messages:
            author = self._user_name if m["role"] == "user" and self._user_name else _tr("ChatWindow.you") if m["role"] == "user" else self._message_author(m["content"])
            avatar = self._user_avatar_color if m["role"] == "user" else ""
            avatar_path = ""
            avatar_data = b""
            avatar_focus = "center"
            if m["role"] == "assistant":
                avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(
                    self._message_character(m["content"], m["role"])
                )
            bubble = MessageBubble(
                self._message_content(m["content"], m["role"]),
                m["role"],
                author,
                m.get("created_at", ""),
                avatar_color=avatar,
                avatar_path=avatar_path,
                avatar_data=avatar_data,
                avatar_focus=avatar_focus,
                reasoning=m.get("reasoning_content", ""),
                show_reasoning=self._show_reasoning,
            )
            self._msg_layout.addWidget(bubble)
        self._msg_layout.addStretch()
        self._relayout_message_bubbles()
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _message_author(self, content: str) -> str:
        if self._is_group_chat:
            first_line = content.splitlines()[0].strip() if content else ""
            if first_line.startswith("【") and "】" in first_line:
                return first_line[1:first_line.index("】")]
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                if content.startswith(f"【{display}】"):
                    return display
        return self._display_name

    def _message_content(self, content: str, role: str) -> str:
        if role == "assistant" and self._is_group_chat:
            lines = content.splitlines()
            first_line = lines[0].strip() if lines else ""
            if first_line.startswith("【") and "】" in first_line:
                return "\n".join(lines[1:]).lstrip()
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                prefix = f"【{display}】"
                if content.startswith(prefix):
                    return content[len(prefix):].lstrip()
        return content

    def _assistant_content(self, character: str, text: str) -> str:
        if not self._is_group_chat:
            return text
        return f"【{self._model_manager.get_display_name(character)}】\n{text}"

    def _group_system_prompt(self, character: str, spoken_names: list[str]) -> str:
        prompt = build_system_prompt(character, self._cfg)
        names = [self._model_manager.get_display_name(c) for c in self._group_characters]
        prompt += "\n\n【群聊规则】\n这是一个多人群聊。当前群聊成员：" + "、".join(names) + "。"
        prompt += "\n你只扮演自己，不要代替其他角色说话。回复时不要添加角色名前缀，程序会自动添加。"
        if spoken_names:
            prompt += "\n你是在" + "、".join(spoken_names) + "之后发言，请自然承接前面角色的内容。"
        return prompt

    def _build_messages_for_character(self, character: str, spoken_names: list[str]) -> list[dict]:
        system_prompt = self._group_system_prompt(character, spoken_names) if self._is_group_chat else build_system_prompt(character, self._cfg)
        messages = [{"role": "system", "content": system_prompt}]
        if self._is_group_chat:
            history = self._db.get_group_messages(self._conversation_key, self._group_conv_id) if self._group_conv_id else []
            max_history = 20
            for m in history[-(max_history * 2):]:
                messages.append({"role": m["role"], "content": m["content"]})
        elif self._conv_id:
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
        return messages

    def _send_message(self):
        text = self._input.toPlainText().strip()
        if not text:
            return

        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        model_id = self._cfg.get("llm_model_id", "")

        if not api_url or not api_key or not model_id:
            self._composer_hint.setText(_tr("ChatWindow.not_configured"))
            avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(self._character)
            bubble = MessageBubble(
                _tr("ChatWindow.no_llm_config"),
                "assistant",
                self._display_name,
                avatar_path=avatar_path,
                avatar_data=avatar_data,
                avatar_focus=avatar_focus,
            )
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
            self._relayout_message_bubbles()
            self._scroll_to_bottom()
            return

        self._input.clear()
        self._set_busy(True, planning=self._is_group_chat)
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""

        user_bubble = MessageBubble(
            text,
            "user",
            self._user_name or _tr("ChatWindow.you"),
            avatar_color=self._user_avatar_color,
            show_reasoning=self._show_reasoning,
        )
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, user_bubble)
        self._relayout_message_bubbles()

        if self._is_group_chat:
            self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "user", text)
        else:
            if self._conv_id is None:
                self._conv_id = self._db.create_conversation(self._conversation_key)
            self._db.add_message(self._conv_id, "user", text)
        self._refresh_group_list()
        if self._is_group_chat:
            self._group_spoken = []
            self._start_group_plan(text)
        else:
            self._start_response_for_character(self._character, [])

    def _start_group_plan(self, user_text: str):
        self._show_plan_divider()
        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        aux_model_id = self._cfg.get("llm_aux_model_id", "").strip() or self._cfg.get("llm_model_id", "")
        if not aux_model_id:
            self._hide_plan_divider()
            self._use_fallback_group_plan()
            return
        members = [
            {"key": character, "name": self._model_manager.get_display_name(character)}
            for character in self._group_characters
        ]
        recent = []
        history = self._db.get_group_messages(self._conversation_key, self._group_conv_id) if self._group_conv_id else []
        for m in history[-12:]:
            recent.append({"role": m["role"], "content": m["content"]})
        planner_prompt = (
            "你是群聊发言调度器。根据用户最新发言、成员关系和最近上下文，决定接下来哪些角色发言以及发言条数。"
            "输出必须是严格 JSON，格式：{\"speakers\":[\"角色key\",...]}。"
            "speakers 长度 1 到 6。可以让同一角色连续或多次出现。"
            "只允许使用给定成员 key，不要输出解释、Markdown 或多余文字。"
        )
        content = json.dumps({
            "members": members,
            "latest_user_message": user_text,
            "recent_history": recent,
        }, ensure_ascii=False)
        messages = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": content},
        ]
        self._group_plan_worker = NonStreamWorker(api_url, api_key, aux_model_id, messages, self._cfg.get("llm_enable_thinking", None))
        self._group_plan_worker.finished.connect(self._on_group_plan_finished)
        self._group_plan_worker.error.connect(self._on_group_plan_error)
        self._group_plan_worker.start()

    def _show_plan_divider(self):
        self._hide_plan_divider()
        divider = PlanDivider(_tr("ChatWindow.ai_scheduling"), self._msg_area)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, divider)
        self._plan_divider = divider
        self._scroll_to_bottom()

    def _hide_plan_divider(self):
        if self._plan_divider is not None:
            self._plan_divider.deleteLater()
            self._plan_divider = None

    def _on_group_plan_finished(self, full_text: str, reasoning_text: str, actions: list):
        del reasoning_text, actions
        self._group_plan_worker = None
        self._hide_plan_divider()
        self._group_queue = self._parse_group_plan(full_text)
        if not self._group_queue:
            self._use_fallback_group_plan()
            return
        self._start_next_group_response()

    def _on_group_plan_error(self, error_msg: str):
        del error_msg
        self._group_plan_worker = None
        self._hide_plan_divider()
        self._use_fallback_group_plan()

    def _parse_group_plan(self, text: str) -> list[str]:
        allowed = set(self._group_characters)
        try:
            match = re.search(r"\{.*\}", text, re.S)
            data = json.loads(match.group(0) if match else text)
            speakers = data.get("speakers", [])
        except Exception:
            speakers = []
        result = []
        for speaker in speakers:
            if speaker in allowed:
                result.append(speaker)
            elif isinstance(speaker, str):
                for character in self._group_characters:
                    if speaker == self._model_manager.get_display_name(character):
                        result.append(character)
                        break
            if len(result) >= 6:
                break
        return result

    def _use_fallback_group_plan(self):
        self._group_queue = list(self._group_characters[:3])
        self._start_next_group_response()

    def _start_response_for_character(self, character: str, spoken_names: list[str]):
        self._set_busy(True, planning=False)
        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        model_id = self._cfg.get("llm_model_id", "")
        self._active_response_character = character
        self._pending_action_character = character
        avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(character)
        self._current_bubble = MessageBubble(
            "",
            "assistant",
            self._message_author(self._assistant_content(character, "")),
            avatar_path=avatar_path,
            avatar_data=avatar_data,
            avatar_focus=avatar_focus,
            show_reasoning=self._show_reasoning,
        )
        self._current_bubble.set_streaming(True)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, self._current_bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom()

        messages = self._build_messages_for_character(character, spoken_names)
        enable_thinking = self._cfg.get("llm_enable_thinking", None)
        self._worker = LLMStreamWorker(api_url, api_key, model_id, messages, enable_thinking)
        self._worker.chunk_received.connect(self._on_chunk_received)
        self._worker.finished.connect(self._on_response_finished)
        self._worker.error.connect(self._on_response_error)
        self._worker.start()

    def _start_next_group_response(self):
        if not self._group_queue:
            self._set_busy(False)
            self._input.setFocus()
            self._sync_input_height()
            self._worker = None
            self._current_bubble = None
            self._scroll_to_bottom()
            return
        character = self._group_queue.pop(0)
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._start_response_for_character(character, list(self._group_spoken))

    def _on_chunk_received(self, text: str, reasoning: str):
        if reasoning:
            self._reasoning_stream_text += reasoning
            if self._current_bubble:
                self._current_bubble.set_reasoning(self._reasoning_stream_text)
                self._current_bubble.set_streaming(True)
                self._scroll_to_bottom()

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

    def _on_response_finished(self, full_text: str, reasoning_text: str, actions: list):
        self._pending_action_character = self._active_response_character
        self._pending_actions.extend(parse_action_tags(full_text))
        self._flush_actions()

        clean = strip_action_tags(full_text)
        reasoning_clean = strip_action_tags(reasoning_text)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._reasoning_stream_text = reasoning_clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_reasoning(reasoning_clean)
            self._current_bubble.set_text(clean)

        stored = self._assistant_content(self._active_response_character, clean)
        if self._is_group_chat:
            self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "assistant", stored, reasoning_clean)
            self._refresh_group_list()
        elif self._conv_id:
            self._db.add_message(self._conv_id, "assistant", stored, reasoning_clean)
            self._refresh_group_list()

        if self._is_group_chat:
            self._group_spoken.append(self._model_manager.get_display_name(self._active_response_character))
            self._worker = None
            self._current_bubble = None
            self._start_next_group_response()
        else:
            self._set_busy(False)
            self._input.setFocus()
            self._sync_input_height()
            self._worker = None
            self._current_bubble = None
            self._scroll_to_bottom()

    def _on_response_finished_nonstream(self, full_text: str, reasoning_text: str, actions: list):
        acts = parse_action_tags(full_text)
        self._pending_action_character = self._active_response_character
        self._pending_actions.extend(acts)
        self._flush_actions()

        clean = strip_action_tags(full_text)
        reasoning_clean = strip_action_tags(reasoning_text)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._reasoning_stream_text = reasoning_clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_reasoning(reasoning_clean)
            self._current_bubble.set_text(clean)

        stored = self._assistant_content(self._active_response_character, clean)
        if self._is_group_chat:
            self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "assistant", stored, reasoning_clean)
            self._refresh_group_list()
        elif self._conv_id:
            self._db.add_message(self._conv_id, "assistant", stored, reasoning_clean)
            self._refresh_group_list()

        if self._is_group_chat:
            self._group_spoken.append(self._model_manager.get_display_name(self._active_response_character))
            self._worker = None
            self._current_bubble = None
            self._start_next_group_response()
        else:
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
            self.action_triggered.emit(self._pending_action_character, action)
        self._pending_actions.clear()

    def emit_action_for_ipc(self, character: str, action: str):
        publish_action(character, action)

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
        if not self._closing:
            event.ignore()
            self._play_close_animation()
            return
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(2000)
        if self._group_plan_worker and self._group_plan_worker.isRunning():
            self._group_plan_worker.quit()
            self._group_plan_worker.wait(2000)
        self._stream_flush_timer.stop()
        self._db.close()
        self.closed.emit()
        super().closeEvent(event)
