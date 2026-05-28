import fluent_bootstrap

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

from PySide6.QtCore import Qt, QObject, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QRect, QRectF, QSize, QVariantAnimation, QParallelAnimationGroup
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap, QImage, QRegion
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QScrollArea, QSizePolicy, QToolButton, QMenu,
    QApplication, QGraphicsOpacityEffect, QWidgetAction,
    QGraphicsColorizeEffect, QFrame, QFileDialog, QMessageBox,
    QSplitter, QSplitterHandle, QCheckBox,
)

from i18n_manager import tr as _tr
from qfluentwidgets import Action, BodyLabel, StrongBodyLabel, FluentIcon, RoundMenu, LineEdit, MessageBoxBase, TransparentToolButton, isDarkTheme
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
from ui_helpers import AVATAR_EXTENSIONS, FluentContextTextEdit, INTERRUPT_COMMANDS, circular_pixmap
from win32_dwm import apply_windows_11_border_fix

import base64
import math
import mimetypes
import os
import shutil
import sys
import uuid
import urllib.error
from datetime import datetime
import json
import re
from pathlib import Path

if sys.platform == "darwin":
    import macos_patch
else:
    macos_patch = None

from llm_manager import (
    build_system_prompt, LLMStreamWorker, ResponsesStreamWorker, NonStreamWorker,
    parse_action_tags, strip_action_tags, extract_inline_search_sources,
)
from llm_api_compat import chat_completions_api_url
from llm_error_hints import format_llm_error_message
from vision_fallback import analyze_images_with_aux_model
from chat_config_snapshots import (
    memory_extraction_api_config,
    tool_config_snapshot,
    tts_config_snapshot,
)
from local_tools import reminder_tools_enabled
try:
    from tts_manager import TTSPlayer, TTSRequestWorker, TTSTranslationWorker, flush_tts_sentence, strip_tts_action_tags
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
    TTSTranslationWorker = None

    def flush_tts_sentence(buffer: str) -> str:
        return buffer.strip()

    def strip_tts_action_tags(text: str) -> str:
        import re as _re
        return _re.sub(r"\[(?:DONE|[A-Za-z0-9_.\-]+)\]", "", text).strip()
from relationship_memory import (
    analyze_interaction,
    build_memory_extraction_messages,
    build_relationship_context,
    format_character_status,
    parse_memory_extraction_response,
    parse_relationship_analysis_response,
    user_key_from_config,
)
from action_bus import publish_action, publish_lip_sync


class AuxVisionFallbackWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, config: dict, text: str, image_data_urls: list[str], parent=None):
        super().__init__(parent)
        self._config = dict(config or {})
        self._text = text
        self._image_data_urls = list(image_data_urls or [])

    def run(self):
        try:
            aux_api_url = str(self._config.get("llm_aux_api_url", "") or "").strip() or str(self._config.get("llm_api_url", "") or "")
            aux_api_key = str(self._config.get("llm_aux_api_key", "") or "").strip() or str(self._config.get("llm_api_key", "") or "")
            summary = analyze_images_with_aux_model(
                aux_api_url,
                aux_api_key,
                str(self._config.get("llm_aux_model_id", "") or "").strip()
                or str(self._config.get("llm_model_id", "") or "").strip(),
                self._image_data_urls,
                self._text,
                self._config.get("llm_aux_enable_thinking", None),
            )
            if not self.isInterruptionRequested():
                self.finished.emit(summary)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")
                data = json.loads(body)
                message = data.get("error", {}).get("message", body[:300])
            except Exception:
                message = str(exc)
            if not self.isInterruptionRequested():
                self.error.emit(f"HTTP {exc.code}: {message}")
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.error.emit(str(exc))


_BG_LIGHT = "#f5f7fb"
_BG_DARK = "#0f1117"

_USER_BUBBLE_LIGHT = BANDORI_PRIMARY_SOFT
_USER_BUBBLE_DARK = BANDORI_PRIMARY_SOFT_DARK
_ASSIST_BUBBLE_LIGHT = "#ffffff"
_ASSIST_BUBBLE_DARK = "#1b1f29"
_TEAMS_ACCENT = "#6264a7"
_TELEGRAM_ACCENT = BANDORI_PRIMARY
_AVATAR_EXTENSIONS = AVATAR_EXTENSIONS
_CHAT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_AVATAR_PIXMAP_CACHE = {}
_AVATAR_PIXMAP_CACHE_LIMIT = 96
_HISTORY_ROW_WIDTH = 368
_HISTORY_ROW_HEIGHT = 48
_HISTORY_SCROLL_WIDTH = _HISTORY_ROW_WIDTH + 24
_GROUP_SIDEBAR_DEFAULT_RATIO = 0.28
_GROUP_SIDEBAR_MIN_RATIO = 0.18
_GROUP_SIDEBAR_MAX_RATIO = 0.46
_INTERRUPT_COMMANDS = INTERRUPT_COMMANDS


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
    rounded = circular_pixmap(crop, size)
    _AVATAR_PIXMAP_CACHE[cache_key] = QPixmap(rounded)
    if len(_AVATAR_PIXMAP_CACHE) > _AVATAR_PIXMAP_CACHE_LIMIT:
        _AVATAR_PIXMAP_CACHE.pop(next(iter(_AVATAR_PIXMAP_CACHE)))
    return rounded


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
    def __init__(self, current_name: str, parent=None, title: str = "", label: str = ""):
        super().__init__(parent)
        self.title_label = StrongBodyLabel(title or _tr("ChatWindow.rename_group_title"), self.widget)
        self.desc_label = BodyLabel(label or _tr("ChatWindow.rename_group_label"), self.widget)
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
        self._wave_glow = False
        self._wave_phase = 0.0

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

    def set_wave_glow(self, enabled: bool, phase: float = 0.0):
        self._wave_glow = enabled
        self._wave_phase = phase
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = self._border_width / 2
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        path = _rounded_path(rect, self._radii)
        painter.fillPath(path, self._bg)
        if self._wave_glow:
            for index, base_alpha in enumerate((150, 90, 45)):
                wave = (math.sin(self._wave_phase + index * 0.85) + 1.0) / 2.0
                color = QColor(255, 105, 180, int(base_alpha * (0.45 + wave * 0.55)))
                pen = QPen(color, 2.0 + index * 1.35 + wave * 1.2)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawPath(path)
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


class ChatSendButton(IconButton):
    def __init__(self, parent=None):
        super().__init__(FluentIcon.SEND, parent, primary=True)
        self._busy = False
        self._hovered = False
        self._spin_angle = 0
        self._normal_icon = FluentIcon.SEND.icon()
        self._spin_timer = QTimer(self)
        self._spin_timer.setInterval(34)
        self._spin_timer.timeout.connect(self._tick_spinner)

    def set_busy(self, busy: bool):
        busy = bool(busy)
        if self._busy == busy:
            return
        self._busy = busy
        if hasattr(self, "_hover_anim"):
            self._hover_anim.stop()
        self.setGraphicsEffect(None)
        self.setIcon(QIcon() if busy else self._normal_icon)
        self.setToolTip(
            _tr("ChatWindow.stop_tooltip", default="停止生成")
            if busy
            else _tr("ChatWindow.send_tooltip")
        )
        if busy:
            self._spin_timer.start()
        else:
            self._spin_timer.stop()
            self._spin_angle = 0
        self.apply_theme()
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        if self._busy:
            self.update()
        else:
            super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if self._busy:
            self.update()
        else:
            super().leaveEvent(event)

    def apply_theme(self):
        if not self._busy:
            super().apply_theme()
            return
        self.setStyleSheet("""
            QToolButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.update()

    def _tick_spinner(self):
        if not self._busy or self._hovered:
            return
        self._spin_angle = (self._spin_angle + 18) % 360
        self.update()

    def paintEvent(self, event):
        if not self._busy:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        base = QColor(accent_color(dark))
        hover = QColor(BANDORI_PRIMARY_DARK_HOVER if dark else BANDORI_PRIMARY_HOVER)
        pressed = QColor(BANDORI_PRIMARY_DARK_PRESSED if dark else BANDORI_PRIMARY_PRESSED)
        bg = pressed if self.isDown() else hover if self._hovered else base

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        if self._hovered:
            painter.drawEllipse(rect)
            painter.setBrush(QColor("#ffffff"))
            center = rect.center()
            icon_w = rect.width() * 0.38
            icon_h = rect.height() * 0.34
            icon_rect = QRectF(
                center.x() - icon_w / 2,
                center.y() - icon_h / 2,
                icon_w,
                icon_h,
            )
            painter.drawRoundedRect(
                icon_rect,
                min(icon_rect.width(), icon_rect.height()) * 0.22,
                min(icon_rect.width(), icon_rect.height()) * 0.22,
            )
            return

        painter.drawEllipse(rect)
        spinner_rect = rect.adjusted(12, 12, -12, -12)
        track = QColor("#ffffff")
        track.setAlpha(74)
        painter.setPen(QPen(track, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(spinner_rect)
        painter.setPen(QPen(QColor("#ffffff"), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(spinner_rect, int(-self._spin_angle * 16), int(-235 * 16))


class FluentSplitterHandle(QSplitterHandle):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._hovered = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        if self._pressed:
            color = QColor(accent_color(dark))
            width = 4
            alpha = 190
        elif self._hovered:
            color = QColor("#8f98ad" if dark else "#9aa8c2")
            width = 3
            alpha = 150
        else:
            color = QColor("#3d4658" if dark else "#d6deec")
            width = 2
            alpha = 120
        color.setAlpha(alpha)
        x = (self.width() - width) / 2
        y = 18
        height = max(28, self.height() - 36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(x, y, width, height), width / 2, width / 2)


class FluentSplitter(QSplitter):
    def createHandle(self):
        return FluentSplitterHandle(self.orientation(), self)


class ChatResizeGrip(QWidget):
    def __init__(self, target: QWidget, parent=None):
        super().__init__(parent)
        self._target = target
        self._hovered = False
        self._pressed = False
        self._start_pos = None
        self._start_size = None
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip(_tr("ChatWindow.resize_tooltip"))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._start_pos = event.globalPosition().toPoint()
            self._start_size = self._target.size()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed and self._start_pos is not None and self._start_size is not None:
            delta = event.globalPosition().toPoint() - self._start_pos
            minimum = self._target.minimumSize()
            self._target.resize(
                max(minimum.width(), self._start_size.width() + delta.x()),
                max(minimum.height(), self._start_size.height() + delta.y()),
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed:
            self._pressed = False
            self._start_pos = None
            self._start_size = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        color = QColor(accent_color(dark) if self._pressed else ("#aab4c5" if dark else "#98a5ba"))
        color.setAlpha(220 if (self._hovered or self._pressed) else 150)
        pen = QPen(color, 1.45)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        w = self.width()
        h = self.height()
        for offset in (6, 10, 14):
            painter.drawLine(w - offset, h - 4, w - 4, h - offset)
        super().paintEvent(event)


class ConversationHistoryRow(QWidget):
    selected = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, conv_id, title: str, current: bool, parent=None):
        super().__init__(parent)
        self._conv_id = conv_id
        self._current = current
        self._hovered = False
        self._pressed = False
        self._bg_color = QColor("transparent")
        self._indicator_color = QColor("transparent")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(_HISTORY_ROW_WIDTH, _HISTORY_ROW_HEIGHT)
        self.setFixedHeight(_HISTORY_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 2, 6)
        layout.setSpacing(10)

        leading_icon = QToolButton(self)
        leading_icon.setObjectName("HistoryLeadingIcon")
        leading_icon.setIcon((FluentIcon.ACCEPT_MEDIUM if current else FluentIcon.HISTORY).icon())
        leading_icon.setIconSize(QSize(15, 15))
        leading_icon.setFixedSize(26, 26)
        leading_icon.setAutoRaise(True)
        leading_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        leading_icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(leading_icon)

        label = QLabel(title, self)
        label.setObjectName("HistoryTitle")
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label, 1)

        delete_btn = QToolButton(self)
        delete_btn.setObjectName("HistoryDeleteButton")
        delete_btn.setIcon(FluentIcon.DELETE.icon())
        delete_btn.setIconSize(QSize(15, 15))
        delete_btn.setFixedSize(28, 28)
        delete_btn.setAutoRaise(True)
        delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        delete_btn.setToolTip(_tr("ChatWindow.delete_conv"))
        delete_btn.clicked.connect(self._emit_delete)
        layout.addWidget(delete_btn)

        self._leading_icon = leading_icon
        self._label = label
        self._delete_btn = delete_btn
        self.apply_theme()

    def set_row_width(self, width: int):
        self.setMinimumWidth(max(_HISTORY_ROW_WIDTH, int(width)))

    def apply_theme(self):
        dark = isDarkTheme()
        if dark:
            normal_bg = "transparent"
            hover_bg = "#202634"
            pressed_bg = "#171d29"
            selected_bg = "#1f2940"
            selected_hover_bg = "#26324c"
            selected_pressed_bg = "#1a2438"
            icon_bg = "#252c3b"
            icon_fg = "#dbe5ff"
        else:
            normal_bg = "transparent"
            hover_bg = "#f4f7fc"
            pressed_bg = "#e8edf6"
            selected_bg = "#edf4ff"
            selected_hover_bg = "#e4eefc"
            selected_pressed_bg = "#dbe7f7"
            icon_bg = "#eef3fb"
            icon_fg = "#4b5874"

        if self._current:
            bg = selected_pressed_bg if self._pressed else selected_hover_bg if self._hovered else selected_bg
        else:
            bg = pressed_bg if self._pressed else hover_bg if self._hovered else normal_bg

        text = "#f7f7fb" if dark else "#1f2328"
        icon_bg = accent_color(dark) if self._current else icon_bg
        icon_fg = "#ffffff" if self._current else icon_fg
        danger = "#ff6b6b" if dark else "#c42b1c"
        danger_hover = "#3a2630" if dark else "#fde7e9"
        danger_pressed = "#4a202d" if dark else "#f7d4d8"
        self._bg_color = QColor(bg)
        self._indicator_color = QColor(accent_color(dark) if self._current else "transparent")
        self.setStyleSheet(f"""
            ConversationHistoryRow {{
                background: transparent;
            }}
            QLabel#HistoryTitle {{
                color: {text};
                background: transparent;
                font-size: 13px;
            }}
            QToolButton#HistoryLeadingIcon {{
                background: {icon_bg};
                color: {icon_fg};
                border: none;
                border-radius: 13px;
                padding: 0px;
            }}
            QToolButton#HistoryDeleteButton {{
                background: transparent;
                color: {danger};
                border: none;
                border-radius: 14px;
                padding: 0px;
            }}
            QToolButton#HistoryDeleteButton:hover {{
                background: {danger_hover};
            }}
            QToolButton#HistoryDeleteButton:pressed {{
                background: {danger_pressed};
            }}
        """)

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
        if event.button() == Qt.MouseButton.LeftButton and not self._delete_btn.geometry().contains(event.position().toPoint()):
            self._pressed = True
            self.apply_theme()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.apply_theme()
        if event.button() == Qt.MouseButton.LeftButton and not self._delete_btn.geometry().contains(event.position().toPoint()):
            self.selected.emit(self._conv_id)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 2, self.width() - 2, self.height() - 4)
        if self._bg_color.alpha() > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bg_color)
            painter.drawRoundedRect(rect, 8, 8)
        if self._current:
            indicator = QRectF(1, 12, 3, self.height() - 24)
            painter.setBrush(self._indicator_color)
            painter.drawRoundedRect(indicator, 1.5, 1.5)
        super().paintEvent(event)

    def _emit_delete(self):
        self.delete_requested.emit(self._conv_id)


class GroupChatListRow(QWidget):
    selected = Signal(object)
    context_menu_requested = Signal(object, object)

    def __init__(
        self,
        characters: list[str],
        title: str,
        preview: str,
        current: bool,
        parent=None,
        avatar_pixmap: QPixmap | None = None,
        kind_text: str = "",
        pinned: bool = False,
    ):
        super().__init__(parent)
        self._characters = list(characters)
        self._title_text = title
        self._preview_text = preview
        self._kind_text = kind_text
        self._pinned = bool(pinned)
        self._current = current
        self._hovered = False
        self._pressed = False
        self._avatar_has_pixmap = avatar_pixmap is not None and not avatar_pixmap.isNull()
        self._bg_color = QColor("transparent")
        self._indicator_color = QColor("transparent")
        self._border_color = QColor("transparent")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(9)

        avatar = QLabel(title[:1].upper(), self)
        avatar.setObjectName("GroupListAvatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        if self._avatar_has_pixmap:
            avatar.setText("")
            avatar.setPixmap(avatar_pixmap)
        layout.addWidget(avatar)

        text_stack = QVBoxLayout()
        text_stack.setContentsMargins(0, 0, 0, 0)
        text_stack.setSpacing(2)
        title_label = QLabel(title, self)
        title_label.setObjectName("GroupListTitle")
        title_label.setMinimumWidth(0)
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_label.setToolTip(title)
        preview_label = QLabel(preview, self)
        preview_label.setObjectName("GroupListPreview")
        preview_label.setMinimumWidth(0)
        preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview_label.setTextFormat(Qt.TextFormat.PlainText)
        preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        preview_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        preview_label.setToolTip(preview)
        text_stack.addWidget(title_label)
        text_stack.addWidget(preview_label)
        layout.addLayout(text_stack, 1)

        meta_stack = QVBoxLayout()
        meta_stack.setContentsMargins(0, 0, 0, 0)
        meta_stack.setSpacing(2)
        pin_label = QLabel("★" if self._pinned else "", self)
        pin_label.setObjectName("GroupListPin")
        pin_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pin_label.setFixedHeight(16)
        pin_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        pin_label.setVisible(self._pinned)
        badge_label = QLabel(kind_text, self)
        badge_label.setObjectName("GroupListBadge")
        badge_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        badge_label.setFixedHeight(18)
        badge_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge_label.setVisible(bool(kind_text))
        meta_stack.addWidget(pin_label)
        meta_stack.addWidget(badge_label)
        layout.addLayout(meta_stack)

        self._avatar = avatar
        self._title_label = title_label
        self._preview_label = preview_label
        self._pin_label = pin_label
        self._badge_label = badge_label
        self.apply_theme()
        self._update_elided_texts()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_texts()

    def _update_elided_texts(self):
        for label, text in (
            (self._title_label, self._title_text),
            (self._preview_label, self._preview_text),
        ):
            width = max(24, label.width() - 2)
            label.setText(label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width))

    def apply_theme(self):
        dark = isDarkTheme()
        if dark:
            normal_bg = "transparent"
            hover_bg = "#202636"
            pressed_bg = "#1b2130"
            selected_bg = "#252c3d"
            selected_hover_bg = "#2a3244"
            selected_pressed_bg = "#202838"
            selected_border = "#343d52"
        else:
            normal_bg = "transparent"
            hover_bg = "#f3f6fb"
            pressed_bg = "#e9eef7"
            selected_bg = "#ffffff"
            selected_hover_bg = "#f8fbff"
            selected_pressed_bg = "#edf3fb"
            selected_border = "#d9e3f3"

        if self._current:
            bg = selected_pressed_bg if self._pressed else selected_hover_bg if self._hovered else selected_bg
        else:
            bg = pressed_bg if self._pressed else hover_bg if self._hovered else normal_bg

        title = "#f8f8fb" if dark else "#1f2328"
        preview = "#a9b0c3" if dark else "#657089"
        badge_bg = "#303849" if dark else "#eaf0fb"
        badge_fg = "#cfd8ec" if dark else "#5c6a84"
        pin_fg = "#f6c344" if dark else "#a15c00"
        avatar_bg = accent_color(dark) if self._current else ("#2d3444" if dark else "#edf2f9")
        avatar_fg = "#ffffff" if self._current else ("#dce4f7" if dark else "#4f5d74")
        self._bg_color = QColor(bg)
        self._indicator_color = QColor(accent_color(dark) if self._current else "transparent")
        self._border_color = QColor(selected_border if self._current else "transparent")
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
            QLabel#GroupListPin {{
                color: {pin_fg};
                background: transparent;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#GroupListBadge {{
                color: {badge_fg};
                background: {badge_bg};
                border-radius: 8px;
                padding: 1px 6px;
                font-size: 10px;
            }}
        """)
        self._update_elided_texts()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)
        if self._bg_color.alpha() > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._bg_color)
            painter.drawRoundedRect(rect, 8, 8)
        if self._border_color.alpha() > 0:
            painter.setPen(QPen(self._border_color, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        if self._current:
            indicator = QRectF(1, 14, 3, self.height() - 28)
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


class ChatCharacterPickerPanel(QWidget):
    open_requested = Signal(object)

    def __init__(self, characters: list[str], display_name_for, selected=None, parent=None):
        super().__init__(parent)
        self._characters = list(characters)
        self._display_name_for = display_name_for
        self._checks: dict[str, QCheckBox] = {}
        selected_set = set(selected or [])
        self.setObjectName("ChatCharacterPickerPanel")
        self.setMinimumWidth(260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        title = StrongBodyLabel(_tr("ChatWindow.new_chat_picker_title", default="选择角色"), self)
        title.setObjectName("ChatPickerTitle")
        layout.addWidget(title)

        scroll = QScrollArea(self)
        scroll.setObjectName("ChatPickerScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMaximumHeight(320)

        list_widget = QWidget(scroll)
        list_widget.setObjectName("ChatPickerList")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(2)
        for character in self._characters:
            check = QCheckBox(self._display_name_for(character), list_widget)
            check.setObjectName("ChatPickerCheck")
            check.setChecked(character in selected_set)
            check.stateChanged.connect(self._sync_action_button)
            self._checks[character] = check
            list_layout.addWidget(check)
        list_layout.addStretch()
        scroll.setWidget(list_widget)
        layout.addWidget(scroll)

        self._open_btn = QToolButton(self)
        self._open_btn.setObjectName("ChatPickerOpenButton")
        self._open_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._open_btn.setIcon(FluentIcon.ADD.icon())
        self._open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_btn.clicked.connect(self._emit_open_requested)
        layout.addWidget(self._open_btn)

        self.apply_theme()
        self._sync_action_button()

    def _selected_characters(self) -> list[str]:
        return [
            character
            for character in self._characters
            if self._checks.get(character) is not None and self._checks[character].isChecked()
        ]

    def _sync_action_button(self):
        count = len(self._selected_characters())
        self._open_btn.setEnabled(count > 0)
        if count <= 1:
            self._open_btn.setText(_tr("ChatWindow.open_private_chat", default="打开私聊"))
        else:
            self._open_btn.setText(_tr("ChatWindow.open_group_chat", default="打开群聊"))

    def _emit_open_requested(self):
        characters = self._selected_characters()
        if characters:
            self.open_requested.emit(characters)

    def apply_theme(self):
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#a9b0c3" if dark else "#657089"
        hover = "#252c3a" if dark else "#f3f7ff"
        button_bg = accent_color(dark)
        button_hover = BANDORI_PRIMARY_DARK_HOVER if dark else BANDORI_PRIMARY_HOVER
        button_pressed = BANDORI_PRIMARY_DARK_PRESSED if dark else BANDORI_PRIMARY_PRESSED
        handle = "#4c5569" if dark else "#c7d0e3"
        self.setStyleSheet(f"""
            QWidget#ChatCharacterPickerPanel {{
                background: {bg};
            }}
            QLabel#ChatPickerTitle {{
                color: {text};
                background: transparent;
                font-size: 13px;
                font-weight: 700;
            }}
            QScrollArea#ChatPickerScroll {{
                background: {bg};
                border: none;
            }}
            QWidget#ChatPickerList {{
                background: {bg};
            }}
            QCheckBox#ChatPickerCheck {{
                color: {text};
                background: transparent;
                border-radius: 7px;
                padding: 7px 8px;
                font-size: 13px;
            }}
            QCheckBox#ChatPickerCheck:hover {{
                background: {hover};
            }}
            QCheckBox#ChatPickerCheck::indicator {{
                width: 16px;
                height: 16px;
            }}
            QToolButton#ChatPickerOpenButton {{
                background: {button_bg};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 700;
            }}
            QToolButton#ChatPickerOpenButton:hover {{
                background: {button_hover};
            }}
            QToolButton#ChatPickerOpenButton:pressed {{
                background: {button_pressed};
            }}
            QToolButton#ChatPickerOpenButton:disabled {{
                background: {'#2a2f3b' if dark else '#e6ebf3'};
                color: {muted};
            }}
            QScrollBar:vertical {{
                background: {bg};
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)


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


class SearchSourcePopup(QFrame):
    def __init__(self, title: str, url: str, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip)
        self.setObjectName("SearchSourcePopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(3)

        title_label = QLabel(title or url, self)
        title_label.setWordWrap(True)
        title_label.setMaximumWidth(300)
        title_font = QFont()
        title_font.setPointSize(9)
        title_font.setBold(True)
        title_label.setFont(title_font)

        url_label = QLabel(url, self)
        url_label.setObjectName("SearchSourceUrl")
        url_label.setWordWrap(True)
        url_label.setMaximumWidth(300)
        url_font = QFont()
        url_font.setPointSize(8)
        url_label.setFont(url_font)

        layout.addWidget(title_label)
        layout.addWidget(url_label)

        dark = isDarkTheme()
        bg = "#242a38" if dark else "#ffffff"
        border = "#3b4356" if dark else "#dce2ee"
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#b8c0d4" if dark else "#657089"
        self.setStyleSheet(f"""
            QFrame#SearchSourcePopup {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QFrame#SearchSourcePopup QLabel {{ color: {text}; background: transparent; }}
            QFrame#SearchSourcePopup QLabel#SearchSourceUrl {{ color: {muted}; }}
        """)


def _enable_translucent_menu(menu: QMenu):
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    menu.setAutoFillBackground(False)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)


def _apply_rounded_menu_mask(menu: QMenu, radius: float):
    width = menu.width()
    height = menu.height()
    if width <= 0 or height <= 0:
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    menu.setMask(QRegion(path.toFillPolygon().toPolygon()))


def _prepare_rounded_menu(menu: QMenu, radius: float = 12):
    _enable_translucent_menu(menu)
    menu.setProperty("rounded_menu_radius", float(radius))
    if menu.property("rounded_menu_prepared"):
        return
    menu.setProperty("rounded_menu_prepared", True)

    def _refresh_mask():
        _apply_rounded_menu_mask(menu, float(menu.property("rounded_menu_radius") or radius))

    menu.aboutToShow.connect(lambda: QTimer.singleShot(0, _refresh_mask))


class SearchSourceBadge(QLabel):
    _CIRCLED_NUMBERS = "123456789"

    def __init__(self, index: int, source: dict, parent=None):
        label = self._CIRCLED_NUMBERS[index - 1] if 1 <= index <= len(self._CIRCLED_NUMBERS) else str(index)
        super().__init__(label, parent)
        self._source = source
        self._popup = None
        self.setFixedSize(20, 20)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        self.setFont(font)

    def enterEvent(self, event):
        title = str(self._source.get("title", "") or "").strip()
        url = str(self._source.get("url", "") or "").strip()
        if url:
            self._popup = SearchSourcePopup(title, url, self)
            pos = self.mapToGlobal(self.rect().bottomLeft())
            self._popup.move(pos.x(), pos.y() + 6)
            self._popup.show()
        return super().enterEvent(event)

    def leaveEvent(self, event):
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None
        return super().leaveEvent(event)

    def apply_theme(self):
        dark = isDarkTheme()
        bg = "rgba(255, 105, 165, 0.14)" if dark else "rgba(255, 105, 165, 0.10)"
        border = "rgba(255, 135, 185, 0.48)" if dark else "rgba(220, 78, 140, 0.36)"
        text = "#ff8fbd" if dark else "#bf3f79"
        hover_bg = "rgba(255, 105, 165, 0.28)" if dark else "rgba(255, 105, 165, 0.20)"
        hover_border = "#ff8fbd" if dark else "#d94e8b"
        self.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 10px;
                padding-bottom: 1px;
            }}
            QLabel:hover {{
                background: {hover_bg};
                border-color: {hover_border};
            }}
        """)


class ChatImagePreview(QWidget):
    _MAX_HEIGHT = 190
    _DEFAULT_WIDTH = 260

    def __init__(self, attachment: dict, parent=None):
        super().__init__(parent)
        self._attachment = dict(attachment or {})
        self._path = str(self._attachment.get("path", "") or "")
        self._name = self._attachment.get("name") or Path(self._path).name or "image"
        self._pixmap = QPixmap(self._path) if self._path else QPixmap()
        self._bg = QColor("transparent")
        self._border = QColor("transparent")
        self._empty_text = QColor("#657089")
        self.setToolTip(self._name)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_preview_width(self._DEFAULT_WIDTH)

    def preferred_width(self) -> int:
        if self._pixmap.isNull():
            return 180
        return self._scaled_outer_size(self._DEFAULT_WIDTH).width()

    def _scaled_outer_size(self, max_width: int) -> QSize:
        max_width = max(96, int(max_width))
        if self._pixmap.isNull():
            return QSize(min(max_width, 220), 52)

        source_w = max(1, self._pixmap.width())
        source_h = max(1, self._pixmap.height())
        scale = min(max_width / source_w, self._MAX_HEIGHT / source_h)
        if max(source_w, source_h) < 96:
            scale = min(
                max(96 / source_w, 96 / source_h),
                max_width / source_w,
                self._MAX_HEIGHT / source_h,
            )
        scale = min(scale, 1.35)
        display_w = max(1, int(round(source_w * scale)))
        display_h = max(1, int(round(source_h * scale)))
        outer_w = max(96, min(max_width, display_w))
        return QSize(outer_w, display_h)

    def set_preview_width(self, max_width: int):
        self.setFixedSize(self._scaled_outer_size(max_width))
        self.update()

    def apply_theme(self):
        dark = isDarkTheme()
        self._bg = QColor("#202634" if dark else "#ffffff")
        self._border = QColor("#39415a" if dark else "#dde4f0")
        self._empty_text = QColor("#a9b0c3" if dark else "#657089")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, self._bg)

        if self._pixmap.isNull():
            painter.setPen(self._empty_text)
            text = self.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight, max(24, self.width() - 18))
            painter.drawText(rect.adjusted(9, 0, -9, 0), Qt.AlignmentFlag.AlignCenter, text)
        else:
            clipped = QPainterPath()
            clipped.addRoundedRect(rect.adjusted(1, 1, -1, -1), 9, 9)
            painter.setClipPath(clipped)
            scaled = self._pixmap.scaled(
                max(1, int(rect.width())),
                max(1, int(rect.height())),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = int(rect.left() + (rect.width() - scaled.width()) / 2)
            y = int(rect.top() + (rect.height() - scaled.height()) / 2)
            painter.drawPixmap(x, y, scaled)
            painter.setClipping(False)

        painter.setPen(QPen(self._border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        super().paintEvent(event)


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
        self._reasoning_title = QLabel(_tr("ChatWindow.reasoning_title"), self._reasoning_panel)
        title_font = QFont()
        title_font.setPointSize(8)
        title_font.setBold(True)
        self._reasoning_title.setFont(title_font)
        self._reasoning_label = FluentContextLabel(self._reasoning, self._reasoning_panel)
        self._reasoning_label.setWordWrap(True)
        self._reasoning_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._reasoning_label.setTextFormat(Qt.TextFormat.PlainText)
        self._reasoning_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        reasoning_font = QFont()
        reasoning_font.setPointSize(9)
        self._reasoning_label.setFont(reasoning_font)
        reasoning_stack.addWidget(self._reasoning_title)
        reasoning_stack.addWidget(self._reasoning_label)
        reasoning_layout.addLayout(reasoning_stack, 1)

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
            reasoning_width = max(
                self._widest_plain_line(self._reasoning_title),
                self._widest_plain_line(self._reasoning_label),
            )
            content_width = max(content_width, reasoning_width + 28)
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
        self._reasoning_label.setFixedHeight(
            self._plain_text_height(self._reasoning_label, reasoning_text_width, True)
        )

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
        self._modern_chat_ui_enabled = bool(
            self._cfg.get("fluent_chat_window_enabled", False)
        ) if self._cfg else False
        display_names = self._cfg.get("chat_display_names", {}) if self._cfg else {}
        self._chat_display_names = display_names if isinstance(display_names, dict) else {}
        pinned_chat_keys = self._cfg.get("pinned_chat_keys", []) if self._cfg else []
        self._pinned_chat_keys = [
            str(key)
            for key in pinned_chat_keys
            if str(key or "").strip()
        ] if isinstance(pinned_chat_keys, list) else []
        self._parent_pet = parent_pet
        self._conv_id: int | None = None
        self._group_conv_id = ""
        self._worker = None
        self._cancelled_workers = []
        self._current_bubble: MessageBubble | None = None
        self._pending_actions: list[str] = []
        self._pending_action_character = character
        self._seen_actions: set[str] = set()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._stream_search_sources: list[dict] = []
        self._pending_source_json = ""
        self._tts_text_buffer = ""
        self._tts_tag_buffer = ""
        self._tts_queue: list[tuple[int, str, str]] = []
        self._tts_active_workers: dict[int, TTSRequestWorker] = {}
        self._tts_translation_workers: dict[int, TTSTranslationWorker] = {}
        self._tts_audio_buffers: dict[int, list[tuple[bytes, str]]] = {}
        self._tts_bubbles: dict[int, MessageBubble] = {}
        self._tts_characters: dict[int, str] = {}
        self._tts_completed_sequences: set[int] = set()
        self._tts_generation = 0
        self._tts_next_sequence = 0
        self._tts_next_play_sequence = 0
        self._tts_playing_sequence: int | None = None
        self._tts_max_parallel = 1
        self._tts_player = TTSPlayer(self)
        self._tts_player.mouth_pose_changed.connect(self._on_tts_mouth_pose_changed)
        self._tts_player.playback_finished.connect(self._on_tts_playback_finished)
        self._pending_actions.clear()
        self._seen_actions.clear()
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setInterval(28)
        self._stream_flush_timer.timeout.connect(self._flush_stream_text)
        self._composer_colors = {}
        self._group_queue: list[str] = []
        self._group_spoken: list[str] = []
        self._group_plan_worker = None
        self._vision_fallback_worker = None
        self._memory_workers: list[NonStreamWorker] = []
        self._pending_vision_send: tuple[str, list[dict]] | None = None
        self._plan_divider = None
        self._active_response_character = character
        self._last_user_text = ""
        self._last_user_message_id: int | None = None
        self._last_group_user_message_id: int | None = None
        self._closing = False
        self._close_animating = False
        self._window_anim = None
        self._pending_history_menu_action = None
        self._pending_attachments: list[dict] = []
        self._composer_drag_active = False
        self._group_splitter = None
        self._group_toggle_btn = None
        self._group_sidebar_toggle_btn = None
        self._group_splitter_adjusting = False
        self._collapsed_chat_size: QSize | None = None
        self._group_sidebar_ratio = self._normalized_group_sidebar_ratio(
            self._cfg.get("group_chat_sidebar_ratio", _GROUP_SIDEBAR_DEFAULT_RATIO)
        ) if self._cfg else _GROUP_SIDEBAR_DEFAULT_RATIO
        self._group_sidebar_collapsed = bool(
            self._cfg.get("group_chat_sidebar_collapsed", False)
        ) if (self._modern_chat_ui_enabled or self._is_group_chat) and self._cfg else False
        self._group_sidebar_save_timer = QTimer(self)
        self._group_sidebar_save_timer.setSingleShot(True)
        self._group_sidebar_save_timer.timeout.connect(self._save_group_sidebar_settings)
        self._group_sidebar_ratio_timer = QTimer(self)
        self._group_sidebar_ratio_timer.setSingleShot(True)
        self._group_sidebar_ratio_timer.timeout.connect(self._apply_group_sidebar_ratio_to_splitter)
        self._group_relayout_timer = QTimer(self)
        self._group_relayout_timer.setSingleShot(True)
        self._group_relayout_timer.setInterval(45)
        self._group_relayout_timer.timeout.connect(self._relayout_message_bubbles)

        self._user_name = self._cfg.get("user_name", "").strip() if self._cfg else ""
        self._user_avatar_color = self._cfg.get("user_avatar_color", _TELEGRAM_ACCENT) if self._cfg else _TELEGRAM_ACCENT
        self._user_avatar_path = str(self._cfg.get("user_avatar_path", "") or "").strip() if self._cfg else ""
        self._chat_user_key = self._user_memory_key()
        avatar_paths = self._cfg.get("chat_avatar_paths", {}) if self._cfg else {}
        self._chat_avatar_paths = avatar_paths if isinstance(avatar_paths, dict) else {}
        self._show_reasoning = bool(self._cfg.get("llm_show_reasoning", True)) if self._cfg else True

        from database_manager import DatabaseManager
        self._db = DatabaseManager()
        self._assign_legacy_chat_history()
        if not self._is_group_chat:
            self._db.delete_empty_conversations(self._conversation_key, self._chat_user_key)
        self._display_name = self._chat_display_name()

        icon_path = os.path.join(app_base_dir(), "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        self._apply_chat_window_minimum_size()
        if self._chat_sidebar_enabled() and not self._group_sidebar_collapsed:
            self.resize(880, 680)
        else:
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

    def _assign_legacy_chat_history(self):
        if not self._cfg or not hasattr(self._cfg, "legacy_chat_user_key"):
            return
        try:
            self._db.assign_legacy_chat_history_user(self._cfg.legacy_chat_user_key())
        except Exception:
            pass

    def _normalized_group_sidebar_ratio(self, value) -> float:
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            ratio = _GROUP_SIDEBAR_DEFAULT_RATIO
        return max(_GROUP_SIDEBAR_MIN_RATIO, min(_GROUP_SIDEBAR_MAX_RATIO, ratio))

    def _chat_sidebar_enabled(self) -> bool:
        return bool(self._modern_chat_ui_enabled or self._is_group_chat)

    def _chat_minimum_size_for(self, sidebar_collapsed: bool | None = None) -> tuple[int, int]:
        if sidebar_collapsed is None:
            sidebar_collapsed = self._group_sidebar_collapsed
        if self._chat_sidebar_enabled() and not sidebar_collapsed:
            return 720, 600
        return 360, 520

    def _chat_minimum_size(self) -> tuple[int, int]:
        return self._chat_minimum_size_for()

    def _apply_chat_window_minimum_size(self, ensure_visible_size: bool = False):
        min_width, min_height = self._chat_minimum_size()
        self.setMinimumSize(min_width, min_height)
        if ensure_visible_size and (self.width() < min_width or self.height() < min_height):
            self.resize(max(self.width(), min_width), max(self.height(), min_height))

    def _valid_collapsed_chat_size(self, size: QSize | None) -> QSize | None:
        if size is None or not size.isValid() or size.isEmpty():
            return None
        min_width, min_height = self._chat_minimum_size_for(sidebar_collapsed=True)
        return QSize(max(min_width, size.width()), max(min_height, size.height()))

    def _fallback_collapsed_chat_size(self) -> QSize:
        content_width = 0
        if self._group_splitter is not None:
            sizes = self._group_splitter.sizes()
            if len(sizes) > 1:
                content_width = sizes[1]
        if content_width <= 0:
            sidebar_width = self._group_sidebar.width() if self._group_sidebar is not None else 0
            handle_width = self._group_splitter.handleWidth() if self._group_splitter is not None else 0
            content_width = self.width() - sidebar_width - handle_width
        min_width, min_height = self._chat_minimum_size_for(sidebar_collapsed=True)
        return QSize(max(min_width, content_width), max(min_height, self.height()))

    def _restore_collapsed_chat_size(self, size: QSize):
        size = self._valid_collapsed_chat_size(size) or self._fallback_collapsed_chat_size()
        if self.size() == size:
            return
        self.resize(size)

    def _normalize_group_characters(self, characters: list[str]) -> list[str]:
        result = []
        seen = set()
        for character in characters:
            if not character or character in seen:
                continue
            result.append(character)
            seen.add(character)
        return result

    def _private_display_name(self, character: str) -> str:
        custom_name = str(self._chat_display_names.get(character, "") or "").strip()
        return custom_name or self._model_manager.get_display_name(character)

    def _save_chat_display_names(self):
        if not self._cfg:
            return
        self._cfg.set("chat_display_names", dict(self._chat_display_names))
        try:
            self._cfg.save()
        except Exception:
            pass

    def _is_chat_pinned(self, chat_key: str) -> bool:
        return chat_key in set(self._pinned_chat_keys)

    def _set_chat_pinned(self, chat_key: str, pinned: bool):
        chat_key = str(chat_key or "").strip()
        if not chat_key:
            return
        pinned_keys = [key for key in self._pinned_chat_keys if key != chat_key]
        if pinned:
            pinned_keys.insert(0, chat_key)
        self._pinned_chat_keys = pinned_keys
        if self._cfg:
            self._cfg.set("pinned_chat_keys", list(self._pinned_chat_keys))
            try:
                self._cfg.save()
            except Exception:
                pass
        self._refresh_group_list()

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

    def _set_available_group_characters(self, characters: list[str]):
        merged = list(self._available_group_characters)
        seen = set(merged)
        for character in characters:
            if character and character not in seen:
                merged.append(character)
                seen.add(character)
        self._available_group_characters = self._normalize_group_characters(merged)

    def _group_display_name(self, characters: list[str]) -> str:
        group_key = self._conversation_key_for(characters)
        if group_key.startswith("__group__:"):
            custom_name = self._db.get_group_display_name(group_key).strip()
            if custom_name:
                return custom_name
        return self._group_default_display_name(characters)

    def _group_default_display_name(self, characters: list[str]) -> str:
        names = [self._model_manager.get_display_name(character) for character in characters]
        members = "、".join(names)
        return _tr(
            "ChatWindow.group_default_name",
            default="{members}：{name}",
            members=members,
            name=self._auto_group_name(characters),
        )

    def _auto_group_name(self, characters: list[str]) -> str:
        normalized = self._normalize_group_characters(characters)
        bands = {
            self._model_manager.get_character_band(character)
            for character in normalized
            if self._model_manager.get_character_band(character)
        }
        if len(bands) == 1:
            band_id = next(iter(bands))
            if band_id and band_id != "others":
                return _tr(
                    "ChatWindow.group_auto_band_room",
                    default="{band}练习室",
                    band=self._model_manager.get_band_display_name(band_id),
                )
        count = len(normalized)
        if count <= 2:
            return _tr("ChatWindow.group_auto_duo", default="双人练习室")
        if count == 3:
            return _tr("ChatWindow.group_auto_trio", default="三人聊天室")
        if count == 4:
            return _tr("ChatWindow.group_auto_quartet", default="四人排练室")
        return _tr("ChatWindow.group_auto_band", default="联合乐队群")

    def _chat_display_name(self) -> str:
        if self._is_group_chat:
            members = self._group_display_name(self._group_characters)
            return _tr("ChatWindow.group_chat_named", members=members)
        return self._private_display_name(self._character)

    def _group_chats(self) -> list[dict]:
        result = []
        seen = set()
        for chat in self._db.get_group_chats(self._chat_user_key):
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
        current_characters = self._normalize_group_characters(self._group_characters)
        current_key = self._conversation_key_for(current_characters)
        if len(current_characters) > 1 and current_key not in seen:
            result.insert(0, {
                "group_key": current_key,
                "conversation_id": "",
                "content": "",
                "created_at": "",
                "characters": current_characters,
            })
            seen.add(current_key)
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
            QTimer.singleShot(0, lambda: macos_patch.apply_floating_tool_window_polish(self))
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(0, self._play_entrance)

    def _apply_windows_11_border_fix(self):
        hwnd = int(self.winId())
        apply_windows_11_border_fix(hwnd)

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

        if self._chat_sidebar_enabled():
            shell_layout = QHBoxLayout(self._shell)
            shell_layout.setContentsMargins(0, 0, 0, 0)
            shell_layout.setSpacing(0)
            self._group_splitter = FluentSplitter(Qt.Orientation.Horizontal, self._shell)
            self._group_splitter.setObjectName("GroupChatSplitter")
            self._group_splitter.setChildrenCollapsible(False)
            self._group_splitter.setHandleWidth(10)
            self._group_splitter.setOpaqueResize(True)
            self._group_splitter.splitterMoved.connect(self._on_group_splitter_moved)
            shell_layout.addWidget(self._group_splitter)

            self._group_sidebar = self._build_group_sidebar()
            self._group_splitter.addWidget(self._group_sidebar)

            content = QWidget(self._shell)
            content.setObjectName("ChatContent")
            content.setMinimumWidth(360)
            content_layout = QVBoxLayout(content)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            self._group_splitter.addWidget(content)
            self._group_splitter.setStretchFactor(0, 0)
            self._group_splitter.setStretchFactor(1, 1)
            if self._group_sidebar_collapsed:
                self._group_sidebar.setVisible(False)
            QTimer.singleShot(0, self._restore_group_splitter_sizes)
        else:
            self._group_sidebar = None
            self._group_splitter = None
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

        self._resize_grip = ChatResizeGrip(self, self._shell)
        self._resize_grip.setObjectName("ChatResizeGrip")
        self._resize_grip.raise_()
        self._position_resize_grip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._chat_sidebar_enabled() and not self._group_sidebar_collapsed:
            self._schedule_group_sidebar_ratio_apply()
        self._position_resize_grip()
        self._relayout_message_bubbles()

    def _position_resize_grip(self):
        if not self._resize_grip:
            return
        inset = 5
        self._resize_grip.move(
            max(0, self._shell.width() - self._resize_grip.width() - inset),
            max(0, self._shell.height() - self._resize_grip.height() - inset),
        )

    def _restore_group_splitter_sizes(self):
        if not self._group_splitter:
            return
        if self._group_sidebar_collapsed:
            self._set_group_sidebar_collapsed(True, persist=False)
            return
        self._apply_group_sidebar_ratio_to_splitter()

    def _schedule_group_sidebar_ratio_apply(self):
        if self._group_sidebar_ratio_timer.isActive():
            self._group_sidebar_ratio_timer.stop()
        self._group_sidebar_ratio_timer.start(0)

    def _schedule_group_relayout(self):
        if self._group_relayout_timer.isActive():
            return
        self._group_relayout_timer.start()

    def _apply_group_sidebar_ratio_to_splitter(self):
        if (
            not self._group_splitter
            or not self._group_sidebar
            or self._group_sidebar_collapsed
            or self._group_splitter_adjusting
        ):
            return
        total = max(1, self._group_splitter.width())
        min_width = self._group_sidebar.minimumWidth()
        max_width = max(min_width, int(total * _GROUP_SIDEBAR_MAX_RATIO))
        sidebar_width = int(total * self._group_sidebar_ratio)
        sidebar_width = max(min_width, min(max_width, sidebar_width))
        content_width = max(1, total - sidebar_width)
        self._group_splitter_adjusting = True
        self._group_splitter.setSizes([sidebar_width, content_width])
        self._group_splitter_adjusting = False

    def _on_group_splitter_moved(self, pos: int, index: int):
        if self._group_splitter_adjusting or not self._group_splitter or self._group_sidebar_collapsed:
            return
        sizes = self._group_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        ratio = self._normalized_group_sidebar_ratio(sizes[0] / total)
        if abs(ratio - (sizes[0] / total)) > 0.001:
            self._group_sidebar_ratio = ratio
            self._apply_group_sidebar_ratio_to_splitter()
        else:
            self._group_sidebar_ratio = ratio
        self._schedule_group_sidebar_settings_save()
        self._schedule_group_relayout()

    def _set_group_sidebar_collapsed(self, collapsed: bool, persist: bool = True):
        if not self._chat_sidebar_enabled() or not self._group_splitter or not self._group_sidebar:
            return
        was_collapsed = self._group_sidebar_collapsed
        collapsed = bool(collapsed)
        collapsed_size = None
        if was_collapsed and not collapsed:
            self._collapsed_chat_size = self.size()
        elif not was_collapsed and collapsed:
            collapsed_size = self._valid_collapsed_chat_size(self._collapsed_chat_size)
            if collapsed_size is None:
                collapsed_size = self._fallback_collapsed_chat_size()
        self._group_sidebar_collapsed = bool(collapsed)
        self._apply_chat_window_minimum_size(ensure_visible_size=not self._group_sidebar_collapsed)
        self._group_sidebar.setVisible(not self._group_sidebar_collapsed)
        if self._group_sidebar_collapsed:
            self._group_splitter.setSizes([0, max(1, self._group_splitter.width())])
            if collapsed_size is not None:
                self._restore_collapsed_chat_size(collapsed_size)
        else:
            self._schedule_group_sidebar_ratio_apply()
        self._sync_group_sidebar_toggle_buttons()
        self._apply_theme()
        self._schedule_group_relayout()
        if persist:
            self._schedule_group_sidebar_settings_save()

    def _toggle_group_sidebar(self):
        self._set_group_sidebar_collapsed(not self._group_sidebar_collapsed)

    def _sync_group_sidebar_toggle_buttons(self):
        collapse_text = _tr(
            "ChatWindow.chat_list_collapse",
            default="收起聊天列表",
        ) if self._modern_chat_ui_enabled else _tr("ChatWindow.group_list_collapse")
        expand_text = _tr(
            "ChatWindow.chat_list_expand",
            default="展开聊天列表",
        ) if self._modern_chat_ui_enabled else _tr("ChatWindow.group_list_expand")
        if self._group_toggle_btn is not None:
            icon = FluentIcon.MENU if self._group_sidebar_collapsed else FluentIcon.CARE_LEFT_SOLID
            self._group_toggle_btn.setIcon(icon.icon())
            self._group_toggle_btn.setToolTip(expand_text if self._group_sidebar_collapsed else collapse_text)
        if self._group_sidebar_toggle_btn is not None:
            self._group_sidebar_toggle_btn.setIcon(FluentIcon.CARE_LEFT_SOLID.icon())
            self._group_sidebar_toggle_btn.setToolTip(collapse_text)

    def _schedule_group_sidebar_settings_save(self):
        if self._cfg:
            self._group_sidebar_save_timer.start(250)

    def _save_group_sidebar_settings(self):
        if not self._cfg:
            return
        self._cfg.set("group_chat_sidebar_ratio", self._group_sidebar_ratio)
        self._cfg.set("group_chat_sidebar_collapsed", self._group_sidebar_collapsed)
        try:
            self._cfg.save()
        except Exception:
            pass

    def _build_group_sidebar(self):
        sidebar = RoundedPanel(self._shell)
        sidebar.setObjectName("GroupSidebar")
        sidebar.setMinimumWidth(164)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 10, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = StrongBodyLabel(
            _tr("ChatWindow.chat_list", default="聊天列表")
            if self._modern_chat_ui_enabled
            else _tr("ChatWindow.group_list"),
            sidebar,
        )
        title.setObjectName("GroupSidebarTitle")
        title.setMinimumWidth(0)
        header.addWidget(title, 1)
        collapse_btn = TransparentToolButton(FluentIcon.CARE_LEFT_SOLID, sidebar)
        collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse_btn.setFixedSize(28, 28)
        collapse_btn.clicked.connect(lambda: self._set_group_sidebar_collapsed(True))
        header.addWidget(collapse_btn)
        subtitle = BodyLabel(
            _tr(
                "ChatWindow.chat_list_hint",
                default="快速切换私聊和群聊；右键可管理名称、头像和置顶。",
            )
            if self._modern_chat_ui_enabled
            else _tr("ChatWindow.group_list_hint"),
            sidebar,
        )
        subtitle.setObjectName("GroupSidebarSubtitle")
        subtitle.setWordWrap(True)
        layout.addLayout(header)
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
        list_layout.setContentsMargins(0, 2, 2, 2)
        list_layout.setSpacing(4)
        scroll.setWidget(list_widget)
        layout.addWidget(scroll, 1)

        if self._modern_chat_ui_enabled:
            new_chat_btn = QToolButton(sidebar)
            new_chat_btn.setObjectName("NewChatPickerButton")
            new_chat_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            new_chat_btn.setIcon(FluentIcon.ADD.icon())
            new_chat_btn.setText(_tr("ChatWindow.new_chat_picker", default="新建聊天"))
            new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            new_chat_btn.clicked.connect(self._show_new_chat_picker)
            layout.addWidget(new_chat_btn)
            self._new_chat_picker_btn = new_chat_btn
        else:
            self._new_chat_picker_btn = None

        self._group_sidebar_title = title
        self._group_sidebar_subtitle = subtitle
        self._group_sidebar_toggle_btn = collapse_btn
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

    def _chat_avatar_pixmap_for_characters(self, characters: list[str], size: int = 34) -> QPixmap:
        for character in self._normalize_group_characters(characters):
            path, data, focus = self._avatar_info_for_character(character)
            pixmap = _rounded_avatar_pixmap(path, data, size, focus)
            if not pixmap.isNull():
                return pixmap
        return QPixmap()

    def _chat_picker_characters(self) -> list[str]:
        result = []
        seen = set()

        def add(character: str):
            character = str(character or "").strip()
            if character and character in self._model_manager.characters and character not in seen:
                result.append(character)
                seen.add(character)

        add(self._character)
        for character in self._available_group_characters:
            add(character)
        models = self._cfg.get("models", []) if self._cfg else []
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict):
                    add(item.get("character", ""))
        for conv in self._db.get_conversations(user_key=self._chat_user_key):
            add(conv.get("character", ""))
        for character in self._model_manager.characters:
            add(character)
        return result

    def _private_chat_characters_with_history(self) -> list[str]:
        result = []
        seen = set()
        for conv in self._db.get_conversations(user_key=self._chat_user_key):
            character = str(conv.get("character", "") or "").strip()
            if character and character in self._model_manager.characters and character not in seen:
                result.append(character)
                seen.add(character)
        return result

    def _private_chat_preview(self, character: str) -> tuple[str, str]:
        conversations = self._db.get_conversations(character, self._chat_user_key)
        if not conversations:
            return _tr("ChatWindow.private_empty_preview", default="开始私聊"), ""
        conv = conversations[0]
        return self._conversation_title(conv), str(conv.get("last_message_at") or conv.get("created_at") or "")

    def _private_chat_entries(self) -> list[dict]:
        entries = []
        for index, character in enumerate(self._private_chat_characters_with_history()):
            preview, last_at = self._private_chat_preview(character)
            chat_key = self._conversation_key_for([character])
            entries.append({
                "characters": [character],
                "chat_key": chat_key,
                "title": self._private_display_name(character),
                "preview": preview,
                "last_at": last_at,
                "order": index,
                "pinned": self._is_chat_pinned(chat_key),
            })
        entries.sort(key=lambda item: (0 if item["pinned"] else 1, item["order"]))
        return entries

    def _group_chat_entries(self) -> list[dict]:
        entries = []
        for index, chat in enumerate(self._group_chats()):
            characters = chat["characters"]
            chat_key = self._conversation_key_for(characters)
            entries.append({
                "characters": characters,
                "chat_key": chat_key,
                "title": self._group_display_name(characters),
                "preview": self._group_preview(chat),
                "last_at": str(chat.get("created_at", "")),
                "order": index,
                "pinned": self._is_chat_pinned(chat_key),
            })
        entries.sort(key=lambda item: (0 if item["pinned"] else 1, item["order"]))
        return entries

    def _add_chat_sidebar_section(self, text: str):
        label = BodyLabel(text, self._group_list_widget)
        label.setObjectName("GroupListSection")
        self._group_list_layout.addWidget(label)

    def _refresh_modern_chat_list(self):
        current_key = self._conversation_key
        private_entries = self._private_chat_entries()
        group_entries = self._group_chat_entries()

        self._add_chat_sidebar_section(_tr("ChatWindow.private_chats", default="私聊"))
        if not private_entries:
            empty = BodyLabel(_tr("ChatWindow.no_private_chats", default="暂无私聊记录"), self._group_list_widget)
            empty.setObjectName("GroupListEmpty")
            empty.setWordWrap(True)
            self._group_list_layout.addWidget(empty)
        for entry in private_entries:
            row = GroupChatListRow(
                entry["characters"],
                entry["title"],
                entry["preview"],
                entry["chat_key"] == current_key and not self._is_group_chat,
                self._group_list_widget,
                avatar_pixmap=self._chat_avatar_pixmap_for_characters(entry["characters"]),
                kind_text=_tr("ChatWindow.private_chat_short", default="私聊"),
                pinned=entry["pinned"],
            )
            row.selected.connect(self._switch_group_chat)
            row.context_menu_requested.connect(self._show_group_chat_context_menu)
            self._group_list_layout.addWidget(row)

        self._add_chat_sidebar_section(_tr("ChatWindow.group_chats", default="群聊"))
        if not group_entries:
            empty = BodyLabel(_tr("ChatWindow.no_group_chats", default="暂无群聊"), self._group_list_widget)
            empty.setObjectName("GroupListEmpty")
            empty.setWordWrap(True)
            self._group_list_layout.addWidget(empty)
        for entry in group_entries:
            row = GroupChatListRow(
                entry["characters"],
                entry["title"],
                entry["preview"],
                entry["chat_key"] == current_key and self._is_group_chat,
                self._group_list_widget,
                avatar_pixmap=self._chat_avatar_pixmap_for_characters(entry["characters"]),
                kind_text=_tr("ChatWindow.group_chat_short", default="群聊"),
                pinned=entry["pinned"],
            )
            row.selected.connect(self._switch_group_chat)
            row.context_menu_requested.connect(self._show_group_chat_context_menu)
            self._group_list_layout.addWidget(row)
        self._group_list_layout.addStretch()

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

        if self._modern_chat_ui_enabled:
            self._refresh_modern_chat_list()
            return

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
        self._group_list_layout.addStretch()

    def _show_new_chat_picker(self):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        characters = self._chat_picker_characters()
        if not characters:
            return
        menu = QMenu(self)
        _prepare_rounded_menu(menu, 10)
        menu.setObjectName("NewChatPickerMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        border = "#303849" if dark else "#d8deea"
        menu.setStyleSheet(f"""
            QMenu#NewChatPickerMenu {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 0px;
            }}
        """)
        current_selection = self._group_characters if self._is_group_chat else [self._character]
        panel = ChatCharacterPickerPanel(
            characters,
            lambda character: self._model_manager.get_display_name(character),
            selected=current_selection,
            parent=menu,
        )
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)

        def open_chat(selected_characters):
            menu.close()
            self._switch_group_chat(list(selected_characters))

        panel.open_requested.connect(open_chat)
        button = getattr(self, "_new_chat_picker_btn", None)
        if button is not None:
            pos = button.mapToGlobal(button.rect().topLeft())
            menu.exec(pos)
        else:
            menu.exec(self.mapToGlobal(self.rect().center()))

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

        if self._chat_sidebar_enabled():
            group_toggle_btn = IconButton(FluentIcon.CARE_LEFT_SOLID, bar)
            group_toggle_btn.setFixedSize(32, 32)
            group_toggle_btn.clicked.connect(self._toggle_group_sidebar)
            layout.addWidget(group_toggle_btn)
            self._group_toggle_btn = group_toggle_btn

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
        self._sync_group_sidebar_toggle_buttons()

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
        if self._is_group_chat:
            return self._group_characters[0] if self._group_characters else ""
        return self._character

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
        self._refresh_group_list()
        if self._is_group_chat or self._conv_id is not None:
            self._clear_message_widgets()
            self._load_messages()

    def _build_input_area(self):
        area = RoundedPanel()
        area.setObjectName("InputArea")
        area.setFixedHeight(110)
        outer = QVBoxLayout(area)
        outer.setContentsMargins(20, 8, 20, 14)
        outer.setSpacing(8)

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
        self._composer.setFixedHeight(66)
        self._composer.setAcceptDrops(True)
        self._composer.installEventFilter(self)
        layout = QHBoxLayout(self._composer)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)
        self._composer_layout = layout

        self._attach_btn = IconButton(FluentIcon.PHOTO, self._composer)
        self._attach_btn.setFixedSize(46, 46)
        self._attach_btn.setIconSize(QSize(22, 22))
        self._attach_btn.setToolTip(_tr("ChatWindow.attach_image_tooltip", default="添加图片"))
        self._attach_btn.clicked.connect(self._choose_chat_images)
        self._attach_btn.setAcceptDrops(True)
        self._attach_btn.installEventFilter(self)
        layout.addWidget(self._attach_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._input = FluentContextTextEdit()
        self._input.setPlaceholderText(_tr("ChatWindow.input_placeholder"))
        self._input.setAcceptRichText(False)
        self._input.setFixedHeight(46)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font = QFont()
        font.setPointSize(10)
        self._input.setFont(font)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setAcceptDrops(True)
        self._input.installEventFilter(self)
        self._input.viewport().setAcceptDrops(True)
        self._input.viewport().installEventFilter(self)
        self._input.textChanged.connect(self._sync_input_height)
        layout.addWidget(self._input)

        self._send_btn = ChatSendButton(self._composer)
        self._send_btn.setFixedSize(46, 46)
        self._send_btn.setIconSize(QSize(22, 22))
        self._send_btn.setToolTip(_tr("ChatWindow.send_tooltip"))
        self._send_btn.clicked.connect(self._on_send_button_clicked)
        self._send_btn.setAcceptDrops(True)
        self._send_btn.installEventFilter(self)
        layout.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        outer.addWidget(self._composer)

        self._input_area = area
        self._input_area.setAcceptDrops(True)
        self._input_area.installEventFilter(self)
        return area

    def eventFilter(self, obj, event):
        input_widget = getattr(self, "_input", None)
        input_viewport = input_widget.viewport() if input_widget is not None else None
        drag_targets = {
            widget
            for widget in (
                input_widget,
                input_viewport,
                getattr(self, "_composer", None),
                getattr(self, "_input_area", None),
                getattr(self, "_attach_btn", None),
                getattr(self, "_send_btn", None),
            )
            if widget is not None
        }
        if obj in drag_targets:
            if event.type() in (
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
                QEvent.Type.DragLeave,
                QEvent.Type.Drop,
            ):
                return self._handle_composer_drag_event(event)
        if input_widget is not None and obj == input_widget and event.type() == QKeyEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._send_message()
                return True
            if event.key() == Qt.Key.Key_Return and not event.modifiers():
                self._send_message()
                return True
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                return False
        if input_widget is not None and obj == input_widget and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
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
        group_sidebar_visible = (
            self._chat_sidebar_enabled()
            and self._group_sidebar is not None
            and not self._group_sidebar_collapsed
        )
        title_radius = (0, 14, 0, 0) if group_sidebar_visible else (14, 14, 0, 0)
        input_radius = (0, 0, 14, 0) if group_sidebar_visible else (0, 0, 14, 14)
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

        if self._group_splitter is not None:
            self._group_splitter.setStyleSheet(f"""
                QSplitter#GroupChatSplitter {{
                    background: transparent;
                    border: none;
                }}
            """)

        if self._group_sidebar is not None:
            sidebar_bg = "#151923" if dark else "#f8fafd"
            sidebar_border = "#242a37" if dark else "#e6ebf3"
            self._group_sidebar.set_panel_style(sidebar_bg, "transparent", (14, 0, 0, 14), 0)
            self._group_sidebar.setStyleSheet(f"""
                QLabel#GroupSidebarTitle {{
                    color: {text_color};
                    background: transparent;
                    font-size: 14px;
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
                QLabel#GroupListSection {{
                    color: {muted};
                    background: transparent;
                    font-size: 11px;
                    font-weight: 700;
                    padding: 8px 8px 3px 8px;
                }}
                QToolButton#NewChatPickerButton {{
                    background: {'#252c3a' if dark else '#ffffff'};
                    color: {text_color};
                    border: 1px solid {sidebar_border};
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-weight: 700;
                    text-align: left;
                }}
                QToolButton#NewChatPickerButton:hover {{
                    background: {'#2a3244' if dark else '#f3f7ff'};
                }}
                QToolButton#NewChatPickerButton:pressed {{
                    background: {'#202838' if dark else '#e7eefb'};
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
                padding: 9px 4px 5px 4px;
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
        if self._group_toggle_btn is not None:
            self._group_toggle_btn.apply_theme()
        if self._group_sidebar_toggle_btn is not None:
            if hasattr(self._group_sidebar_toggle_btn, "apply_theme"):
                self._group_sidebar_toggle_btn.apply_theme()
        self._sync_group_sidebar_toggle_buttons()
        self._send_btn.apply_theme()
        self._attach_btn.apply_theme()
        if self._resize_grip:
            self._resize_grip.update()
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

    def _history_scroll_style(self, bg: str, dark: bool) -> str:
        handle = "#566074" if dark else "#c4cfe3"
        handle_hover = "#69758d" if dark else "#aebbd4"
        return f"""
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
                background: {handle};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::add-line:vertical,
            QScrollArea#ConversationHistoryScroll QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::add-page:vertical,
            QScrollArea#ConversationHistoryScroll QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """

    def _fit_history_menu_widgets(self, menu: QMenu, rows: list[ConversationHistoryRow], scrolls: list[QScrollArea]):
        if not rows and not scrolls:
            return
        menu.adjustSize()
        content_width = max(_HISTORY_ROW_WIDTH, menu.sizeHint().width() - 40)
        for row in rows:
            row.set_row_width(content_width)
        for scroll in scrolls:
            scroll.setFixedWidth(content_width + 20)
        menu.adjustSize()

    def _conversation_title(self, conv: dict) -> str:
        preview = self._db.get_first_user_message_content(conv["id"]).replace("\n", " ")
        if not preview:
            preview = conv.get("title") or _tr("ChatWindow.empty_conv")
        if len(preview) > 28:
            preview = preview[:28] + "..."
        created_at = conv.get("last_message_at") or conv.get("created_at", "")
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
        _prepare_rounded_menu(menu)
        menu.setObjectName("ConversationHistoryMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT
        border = "#303849" if dark else "#d8deea"
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#9aa5bd" if dark else "#657089"
        menu_style = f"""
            QMenu#ConversationHistoryMenu {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 8px;
                font-size: 13px;
            }}
            QMenu#ConversationHistoryMenu::item {{
                padding: 9px 12px 9px 12px;
                border-radius: 8px;
                min-width: {_HISTORY_ROW_WIDTH}px;
            }}
            QMenu#ConversationHistoryMenu::item:selected {{
                background: {hover};
            }}
            QMenu#ConversationHistoryMenu::separator {{
                height: 1px;
                background: {border};
                margin: 8px 4px;
            }}
            QMenu#ConversationHistoryMenu::item:disabled {{
                color: {muted};
            }}
        """
        menu.setStyleSheet(menu_style)
        history_rows: list[ConversationHistoryRow] = []
        history_scrolls: list[QScrollArea] = []

        if self._is_group_chat:
            conversations = self._db.get_group_conversations(self._conversation_key, self._chat_user_key)
            title = Action(FluentIcon.HISTORY, _tr("ChatWindow.history_title"), menu)
            menu.addAction(title)
            title.setEnabled(False)
            if conversations:
                history_parent = menu
                history_layout = None
                if len(conversations) > 8:
                    history_parent = QWidget(menu)
                    history_parent.setObjectName("ConversationHistoryList")
                    history_layout = QVBoxLayout(history_parent)
                    history_layout.setContentsMargins(4, 4, 8, 4)
                    history_layout.setSpacing(4)
                for conv in conversations:
                    row = ConversationHistoryRow(
                        conv["conversation_id"],
                        self._group_preview(conv),
                        conv["conversation_id"] == self._group_conv_id,
                        history_parent,
                    )
                    row.selected.connect(lambda conv_id: self._select_group_history_row(menu, conv_id))
                    row.delete_requested.connect(lambda conv_id: self._delete_group_history_row(menu, conv_id))
                    history_rows.append(row)
                    if history_layout is not None:
                        history_layout.addWidget(row)
                    else:
                        action = QWidgetAction(menu)
                        action.setDefaultWidget(row)
                        menu.addAction(action)
                if history_layout is not None:
                    scroll = QScrollArea(menu)
                    scroll.setObjectName("ConversationHistoryScroll")
                    scroll.setWidgetResizable(True)
                    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
                    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    scroll.setFixedSize(_HISTORY_SCROLL_WIDTH, 8 * (_HISTORY_ROW_HEIGHT + 4) + 8)
                    scroll.setWidget(history_parent)
                    scroll.viewport().setAutoFillBackground(False)
                    scroll.setStyleSheet(self._history_scroll_style(bg, dark))
                    history_scrolls.append(scroll)
                    scroll_action = QWidgetAction(menu)
                    scroll_action.setDefaultWidget(scroll)
                    menu.addAction(scroll_action)
            else:
                empty = menu.addAction(_tr("ChatWindow.no_convs"))
                empty.setEnabled(False)
            menu.addSeparator()

            change_menu = QMenu(_tr("ChatWindow.avatar_change_menu"), menu)
            _prepare_rounded_menu(change_menu)
            change_menu.setObjectName("ConversationHistoryMenu")
            change_menu.setIcon(FluentIcon.PHOTO.icon())
            change_menu.setStyleSheet(menu_style)
            menu.addMenu(change_menu)
            reset_menu = QMenu(_tr("ChatWindow.avatar_reset_menu"), menu)
            _prepare_rounded_menu(reset_menu)
            reset_menu.setObjectName("ConversationHistoryMenu")
            reset_menu.setIcon(FluentIcon.RETURN.icon())
            reset_menu.setStyleSheet(menu_style)
            menu.addMenu(reset_menu)
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                change_action = change_menu.addAction(display)
                change_action.triggered.connect(lambda _checked=False, c=character: self._set_character_avatar(c))
                reset_action = reset_menu.addAction(display)
                reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
                reset_action.triggered.connect(lambda _checked=False, c=character: self._reset_character_avatar(c))
            pos = self._title_avatar.mapToGlobal(self._title_avatar.rect().bottomLeft())
            self._pending_history_menu_action = None
            self._fit_history_menu_widgets(menu, history_rows, history_scrolls)
            menu.exec(pos)
            self._run_pending_history_menu_action()
            return
        else:
            change_action = Action(FluentIcon.PHOTO, _tr("ChatWindow.avatar_change"), menu)
            menu.addAction(change_action)
            change_action.triggered.connect(lambda: self._set_character_avatar(self._character))
            reset_action = Action(FluentIcon.RETURN, _tr("ChatWindow.avatar_reset"), menu)
            menu.addAction(reset_action)
            reset_action.setEnabled(bool(self._chat_avatar_paths.get(self._character)))
            reset_action.triggered.connect(lambda: self._reset_character_avatar(self._character))
        menu.addSeparator()

        title = Action(FluentIcon.HISTORY, _tr("ChatWindow.history_title"), menu)
        menu.addAction(title)
        title.setEnabled(False)
        menu.addSeparator()

        conversations = self._db.get_conversations(self._conversation_key, self._chat_user_key)
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
                history_rows.append(row)
                layout.addWidget(row)

            scroll = QScrollArea(menu)
            scroll.setObjectName("ConversationHistoryScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFixedSize(_HISTORY_SCROLL_WIDTH, 8 * (_HISTORY_ROW_HEIGHT + 4) + 8)
            scroll.setWidget(container)
            scroll.viewport().setAutoFillBackground(False)
            scroll.setStyleSheet(self._history_scroll_style(bg, dark))
            history_scrolls.append(scroll)
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
                history_rows.append(row)
                action = QWidgetAction(menu)
                action.setDefaultWidget(row)
                menu.addAction(action)

        menu.addSeparator()
        new_action = Action(FluentIcon.ADD, _tr("ChatWindow.new_conversation"), menu)
        menu.addAction(new_action)
        new_action.triggered.connect(self._new_conversation)

        pos = self._title_avatar.mapToGlobal(self._title_avatar.rect().bottomLeft())
        self._pending_history_menu_action = None
        self._fit_history_menu_widgets(menu, history_rows, history_scrolls)
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
        if not normalized:
            return
        self._switch_chat_members(normalized)

    def _reset_chat_switch_state(self):
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._last_user_message_id = None
        self._last_group_user_message_id = None

    def _sync_chat_mode_chrome(self):
        self._apply_chat_window_minimum_size(ensure_visible_size=True)
        if self._group_toggle_btn is not None:
            self._group_toggle_btn.setVisible(self._chat_sidebar_enabled())
        if self._group_sidebar is not None:
            self._group_sidebar.setVisible(self._chat_sidebar_enabled() and not self._group_sidebar_collapsed)
        if self._group_splitter is not None:
            if self._chat_sidebar_enabled():
                self._schedule_group_sidebar_ratio_apply()
            else:
                self._group_splitter.setSizes([0, max(1, self._group_splitter.width())])
        self._sync_group_sidebar_toggle_buttons()
        self._apply_theme()

    def _switch_chat_members(self, characters: list[str]):
        normalized = self._normalize_group_characters(characters)
        if not normalized:
            return
        next_is_group = len(normalized) > 1
        next_key = self._conversation_key_for(normalized)
        if next_key == self._conversation_key and next_is_group == self._is_group_chat:
            return

        self._reset_chat_switch_state()
        self._set_available_group_characters(normalized)
        self._is_group_chat = next_is_group
        if next_is_group:
            self._group_characters = normalized
            if self._character not in normalized:
                self._character = normalized[0]
        else:
            self._character = normalized[0]
            self._group_characters = []
        self._active_response_character = self._character
        self._pending_action_character = self._character
        self._conversation_key = next_key
        self._display_name = self._chat_display_name()
        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        self._title_label.setText(self._display_name)
        self._update_title_avatar()
        self._sync_chat_mode_chrome()
        self._clear_message_widgets()
        self._conv_id = None
        self._group_conv_id = ""
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
        characters = self._normalize_group_characters(characters)
        if not characters:
            return
        group_key = self._conversation_key_for(characters)
        menu = QMenu(self)
        _prepare_rounded_menu(menu, 8)
        menu.setObjectName("GroupChatContextMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT
        border = "#303849" if dark else "#d8deea"
        text = "#f7f7fb" if dark else "#1f2328"
        menu.setStyleSheet(f"""
            QMenu#GroupChatContextMenu {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu#GroupChatContextMenu::item {{
                padding: 9px 28px 9px 12px;
                border-radius: 6px;
                min-width: 168px;
            }}
            QMenu#GroupChatContextMenu::item:selected {{
                background: {hover};
            }}
        """)
        if len(characters) == 1:
            character = characters[0]
            rename_action = Action(
                FluentIcon.EDIT,
                _tr("ChatWindow.rename_private", default="修改聊天名称"),
                menu,
            )
            rename_action.triggered.connect(lambda: self._rename_private_chat(character))
            menu.addAction(rename_action)

            change_action = Action(FluentIcon.PHOTO, _tr("ChatWindow.avatar_change"), menu)
            change_action.triggered.connect(lambda: self._set_character_avatar(character))
            menu.addAction(change_action)

            reset_action = Action(FluentIcon.RETURN, _tr("ChatWindow.avatar_reset"), menu)
            reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
            reset_action.triggered.connect(lambda: self._reset_character_avatar(character))
            menu.addAction(reset_action)
        else:
            rename_action = Action(FluentIcon.EDIT, _tr("ChatWindow.rename_group"), menu)
            rename_action.triggered.connect(lambda: self._rename_group_chat(characters))
            menu.addAction(rename_action)

            change_menu = QMenu(_tr("ChatWindow.avatar_change_menu"), menu)
            change_menu.setIcon(FluentIcon.PHOTO.icon())
            reset_menu = QMenu(_tr("ChatWindow.avatar_reset_menu"), menu)
            reset_menu.setIcon(FluentIcon.RETURN.icon())
            for character in characters:
                display = self._model_manager.get_display_name(character)
                change_action = change_menu.addAction(display)
                change_action.triggered.connect(lambda checked=False, c=character: self._set_character_avatar(c))
                reset_action = reset_menu.addAction(display)
                reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
                reset_action.triggered.connect(lambda checked=False, c=character: self._reset_character_avatar(c))
            menu.addMenu(change_menu)
            menu.addMenu(reset_menu)

        pinned = self._is_chat_pinned(group_key)
        pin_action = menu.addAction(
            _tr("ChatWindow.unpin_chat", default="取消置顶")
            if pinned
            else _tr("ChatWindow.pin_chat", default="置顶聊天")
        )
        pin_action.triggered.connect(lambda: self._set_chat_pinned(group_key, not pinned))
        delete_action = Action(FluentIcon.DELETE, _tr("ChatWindow.delete_chat", default="删除聊天"), menu)
        delete_action.triggered.connect(lambda: self._delete_chat_entry(characters))
        menu.addSeparator()
        menu.addAction(delete_action)
        menu.exec(global_pos)

    def _rename_private_chat(self, character: str):
        default_name = self._model_manager.get_display_name(character)
        current_name = str(self._chat_display_names.get(character, "") or "").strip() or default_name
        dialog = GroupRenameDialog(
            current_name,
            self,
            title=_tr("ChatWindow.rename_private_title", default="修改聊天名称"),
            label=_tr("ChatWindow.rename_private_label", default="输入新的聊天显示名称，留空恢复角色默认名称："),
        )
        if not dialog.exec():
            return
        new_name = dialog.group_name()
        if new_name and new_name != default_name:
            self._chat_display_names[character] = new_name
        else:
            self._chat_display_names.pop(character, None)
        self._save_chat_display_names()
        if not self._is_group_chat and character == self._character:
            self._display_name = self._chat_display_name()
            self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
            self._title_label.setText(self._display_name)
            self._update_title_avatar()
        self._refresh_group_list()

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
            self._title_label.setText(self._display_name)
            self._update_title_avatar()
        self._refresh_group_list()

    def _delete_chat_entry(self, characters: list[str]):
        characters = self._normalize_group_characters(characters)
        if not characters:
            return
        chat_key = self._conversation_key_for(characters)
        if len(characters) <= 1:
            character = characters[0]
            was_current = not self._is_group_chat and character == self._character
            for conv in self._db.get_conversations(character, self._chat_user_key):
                self._db.delete_conversation(conv["id"])
            self._chat_display_names.pop(character, None)
            self._save_chat_display_names()
            if was_current:
                self._stream_flush_timer.stop()
                self._stream_buffer = ""
                self._visible_stream_text = ""
                self._reasoning_stream_text = ""
                self._current_bubble = None
                self._clear_message_widgets()
                self._conv_id = None
                self._display_name = self._chat_display_name()
                self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
                self._title_label.setText(self._display_name)
        else:
            was_current = self._is_group_chat and chat_key == self._conversation_key
            for conv in self._db.get_group_conversations(chat_key, self._chat_user_key):
                self._db.delete_group_conversation(chat_key, conv["conversation_id"], self._chat_user_key)
            self._db.set_group_display_name(chat_key, "")
            if was_current:
                self._stream_flush_timer.stop()
                self._stream_buffer = ""
                self._visible_stream_text = ""
                self._reasoning_stream_text = ""
                self._current_bubble = None
                self._group_queue = []
                self._group_spoken = []
                self._clear_message_widgets()
                self._group_conv_id = ""

        self._set_chat_pinned(chat_key, False)
        self._refresh_avatar_views()
        self._input.setFocus()

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

        conversations = self._db.get_conversations(self._conversation_key, self._chat_user_key)
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
        self._db.delete_group_conversation(self._conversation_key, conversation_id, self._chat_user_key)
        self._refresh_group_list()

        if not was_current:
            return

        conversations = self._db.get_group_conversations(self._conversation_key, self._chat_user_key)
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
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        if hasattr(self._send_btn, "set_busy"):
            self._send_btn.set_busy(busy)
        self._new_btn.setEnabled(not busy)
        if planning:
            status = _tr("ChatWindow.planning_group_response")
        elif busy:
            status = _tr("ChatWindow.streaming_response_with_stop", default="正在回复，输入 @stop 或 @停止 可中断")
        else:
            status = self._idle_status_text()
        self._composer_hint.setText(status)
        dot = _TEAMS_ACCENT if busy else _TELEGRAM_ACCENT
        self._status_dot.setStyleSheet(f"background: {dot}; border-radius: 3px;")

    def _update_composer_focus_style(self):
        if not self._composer_colors:
            return
        focused = self._input.hasFocus()
        dragging = self._composer_drag_active
        active = focused or dragging
        border = self._composer_colors["focus_border"] if active else self._composer_colors["border"]
        target_width = 3.0 if dragging else 2.0 if focused else 1.0
        current_width = getattr(self, '_composer_border_width', 1.0)
        if abs(current_width - target_width) < 0.01:
            self._composer_border_width = target_width
            self._composer.set_panel_style(self._composer_colors["bg"], border, 22, int(target_width))
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
            self._composer_colors["focus_border"] if active else self._composer_colors["border"],
            22,
            int(round(v))
        ))
        self._composer_focus_anim = anim
        anim.start()

    def _sync_input_height(self):
        doc_height = int(self._input.document().size().height()) + 10
        input_height = max(42, min(86, doc_height))
        composer_height = max(66, input_height + 20)
        area_height = composer_height + 44
        self._input.setFixedHeight(input_height)
        self._composer.setFixedHeight(composer_height)
        self._input_area.setFixedHeight(area_height)
        scrollbar_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if doc_height > 86 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._input.setVerticalScrollBarPolicy(scrollbar_policy)

    def _load_or_create_conversation(self):
        if self._is_group_chat:
            conversations = self._db.get_group_conversations(self._conversation_key, self._chat_user_key)
            self._group_conv_id = conversations[0]["conversation_id"] if conversations else ""
            self._load_messages()
            return
        last = self._db.get_last_conversation(self._conversation_key, self._chat_user_key)
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
            messages = self._db.get_group_messages(self._conversation_key, self._group_conv_id, user_key=self._chat_user_key)
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
            if m["role"] == "user":
                avatar_path = self._user_avatar_path
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
                search_sources=self._message_search_sources(m.get("tool_trace_json")),
                attachments=self._normalize_attachments(m.get("attachments_json")) if m["role"] == "user" else None,
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
            character = self._message_character(content, role)
            lines = content.splitlines()
            first_line = lines[0].strip() if lines else ""
            if first_line.startswith("【") and "】" in first_line:
                return self._sanitize_group_assistant_reply(character, "\n".join(lines[1:]).lstrip())
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                prefix = f"【{display}】"
                if content.startswith(prefix):
                    return self._sanitize_group_assistant_reply(character, content[len(prefix):].lstrip())
        return content

    def _sanitize_group_assistant_reply(self, character: str, text: str) -> str:
        if not self._is_group_chat or not text:
            return text
        names = {
            self._model_manager.get_display_name(item): item
            for item in self._group_characters
        }
        if not names:
            return text.strip()
        name_pattern = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        label_re = re.compile(
            rf"(?m)^[ \t]*(?:【(?P<fw>{name_pattern})】|\[(?P<sq>{name_pattern})\]|(?P<plain>{name_pattern})\s*[：:])\s*"
        )
        matches = list(label_re.finditer(text))
        if not matches:
            return text.strip()

        active_name = self._model_manager.get_display_name(character)
        active_segments = []
        for index, match in enumerate(matches):
            speaker = match.group("fw") or match.group("sq") or match.group("plain") or ""
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segment = text[start:end].strip()
            if speaker == active_name and segment:
                active_segments.append(segment)
        if active_segments:
            return "\n\n".join(active_segments).strip()

        # If the model ignored the requested speaker entirely, at least remove
        # transcript labels so the UI does not display a false nested speaker.
        return label_re.sub("", text).strip()

    def _assistant_content(self, character: str, text: str) -> str:
        if not self._is_group_chat:
            return text
        text = self._sanitize_group_assistant_reply(character, text)
        return f"【{self._model_manager.get_display_name(character)}】\n{text}"

    def _user_memory_key(self) -> str:
        return user_key_from_config(self._cfg)

    def _memory_target_characters(self) -> list[str]:
        return list(self._group_characters) if self._is_group_chat else [self._character]

    def _show_local_assistant_message(self, text: str):
        avatar_character = self._character
        avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(avatar_character)
        bubble = MessageBubble(
            text,
            "assistant",
            self._display_name,
            avatar_path=avatar_path,
            avatar_data=avatar_data,
            avatar_focus=avatar_focus,
            show_reasoning=self._show_reasoning,
        )
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom()

    @staticmethod
    def _is_interrupt_command(text: str) -> bool:
        return text.strip().lower() in _INTERRUPT_COMMANDS

    def _generation_busy(self) -> bool:
        return bool(
            (self._worker is not None and self._worker.isRunning())
            or (self._group_plan_worker is not None and self._group_plan_worker.isRunning())
            or (self._vision_fallback_worker is not None and self._vision_fallback_worker.isRunning())
            or self._group_queue
        )

    def _interrupt_generation(self, clear_input: bool = True):
        interrupted = False
        worker = self._worker
        if worker is not None:
            try:
                worker.cancel()
            except Exception:
                worker.requestInterruption()
            self._park_cancelled_worker(worker)
            interrupted = True
        self._worker = None

        planner = self._group_plan_worker
        if planner is not None:
            planner.requestInterruption()
            planner.quit()
            self._park_cancelled_worker(planner)
            interrupted = True
        self._group_plan_worker = None
        self._group_queue = []

        vision_worker = self._vision_fallback_worker
        if vision_worker is not None:
            vision_worker.requestInterruption()
            vision_worker.quit()
            self._park_cancelled_worker(vision_worker)
            interrupted = True
        self._vision_fallback_worker = None
        self._pending_vision_send = None
        self._hide_plan_divider()

        self._stream_flush_timer.stop()
        current_text = (self._visible_stream_text + self._stream_buffer).strip()
        self._stream_buffer = ""
        self._visible_stream_text = current_text
        if self._current_bubble:
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(current_text or _tr("ChatWindow.response_interrupted", default="已中断当前回复。"))
        elif interrupted:
            self._composer_hint.setText(_tr("ChatWindow.response_interrupted", default="已中断当前回复。"))
        self._current_bubble = None
        self._reset_tts_stream()
        self._set_busy(False)
        if clear_input:
            self._input.clear()
        self._input.setFocus()

    def _park_cancelled_worker(self, worker):
        if worker is None:
            return
        self._cancelled_workers.append(worker)
        QTimer.singleShot(1000, self._prune_cancelled_workers)

    def _prune_cancelled_workers(self):
        self._cancelled_workers = [worker for worker in self._cancelled_workers if worker is not None and worker.isRunning()]

    def _relationship_status_text(self) -> str:
        user_key = self._user_memory_key()
        parts = []
        for character in self._memory_target_characters():
            parts.append(format_character_status(
                self._db,
                character,
                user_key,
                self._model_manager.get_display_name(character),
            ))
        return "\n\n".join(parts)

    def _remember_manual_text(self, text: str):
        content = text.strip()
        if not content:
            self._show_local_assistant_message(_tr("ChatWindow.memory_remember_hint", "要记住什么？可以输入 @记住 你的内容。"))
            return
        user_key = self._user_memory_key()
        for character in self._memory_target_characters():
            self._db.add_character_memory(
                character,
                user_key,
                "manual",
                "用户希望我记住：" + content,
                95,
            )
            self._db.apply_relationship_delta(
                character,
                user_key,
                trust_delta=1,
                familiarity_delta=1,
                mood="soft",
                mood_intensity=42,
                event_type="manual_memory",
                reason="用户手动添加长期记忆",
            )
        self._show_local_assistant_message(_tr("ChatWindow.memory_remembered", "已记住：{content}", content=content))

    def _forget_memory_text(self, text: str):
        query = text.strip()
        if not query:
            self._show_local_assistant_message(_tr("ChatWindow.memory_forget_hint", "要忘记哪条记忆？可以输入 @忘记 关键词。"))
            return
        user_key = self._user_memory_key()
        total = 0
        for character in self._memory_target_characters():
            total += self._db.delete_character_memories_like(character, user_key, query)
        self._show_local_assistant_message(_tr("ChatWindow.memory_forget_result", "已删除 {count} 条包含\u201c{query}\u201d的长期记忆。", count=total, query=query))

    def _set_relationship_value_text(self, field: str, text: str):
        text = text.strip()
        if not text:
            self._show_local_assistant_message(_tr("ChatWindow.set_value_hint", "请输入数值。例如：@好感度 80"))
            return
        user_key = self._user_memory_key()
        if field == "mood":
            try:
                value = int(text)
            except ValueError:
                self._show_local_assistant_message(_tr("ChatWindow.set_mood_hint", "请输入 0-100 的心情数值。例如：@当前心情 75（数值越高心情越好）"))
                return
            value = max(0, min(100, value))
            from relationship_memory import mood_from_intensity, MOOD_LABELS
            mood_key = mood_from_intensity(value)
            label = MOOD_LABELS[mood_key]
            for character in self._memory_target_characters():
                self._db.upsert_relationship_state(character, user_key, mood=mood_key, mood_intensity=value)
            self._show_local_assistant_message(
                _tr("ChatWindow.mood_set", "已设置当前心情为：{mood}（{label}，数值 {value}/100）",
                    mood=mood_key, label=label, value=value))
            return
        try:
            value = int(text)
        except ValueError:
            self._show_local_assistant_message(_tr("ChatWindow.set_value_not_number", "请输入 0-100 的数字。"))
            return
        value = max(0, min(100, value))
        field_cn = {"affection": "好感度", "trust": "信任", "familiarity": "熟悉度"}[field]
        for character in self._memory_target_characters():
            self._db.upsert_relationship_state(character, user_key, **{field: value})
        self._show_local_assistant_message(
            _tr("ChatWindow.relationship_set", "{field} 已设置为：{value}/100", field=field_cn, value=value))

    def _current_chat_members(self) -> list[str]:
        return list(self._group_characters) if self._is_group_chat else [self._character]

    def _handle_local_memory_command(self, text: str) -> bool:
        stripped = text.strip()
        lowered = stripped.lower()
        if lowered in {"@memory", "/memory", "@status", "/status", "@mood", "/mood", "@记忆", "/记忆", "@状态", "/状态", "@心情", "/心情"}:
            self._input.clear()
            self._show_local_assistant_message(self._relationship_status_text())
            return True
        for prefix in ("@remember ", "/remember ", "@记住 ", "/记住 "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._remember_manual_text(stripped[len(prefix):])
                return True
        for prefix in ("@forget ", "/forget ", "@忘记 ", "/忘记 "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._forget_memory_text(stripped[len(prefix):])
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

    def _apply_relationship_update(self, character: str, user_text: str, assistant_text: str, actions: list[str]):
        if not user_text.strip() or not character:
            return
        user_key = self._user_memory_key()
        fallback_analysis = analyze_interaction(user_text, assistant_text, actions)
        if self._start_memory_extraction(
            character,
            user_key,
            user_text,
            assistant_text,
            self._last_user_message_id,
            self._last_group_user_message_id,
            fallback_analysis,
        ):
            return
        self._apply_relationship_analysis(character, user_key, fallback_analysis, "chat")

    def _apply_relationship_analysis(self, character: str, user_key: str, analysis: dict, event_type: str):
        self._db.apply_relationship_delta(
            character,
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
        character: str,
        user_key: str,
        user_text: str,
        assistant_text: str,
        source_message_id: int | None,
        source_group_message_id: int | None,
        fallback_analysis: dict,
    ) -> bool:
        api_url, api_key, model_id = memory_extraction_api_config(
            self._cfg,
            self._use_responses_api,
            self._chat_completions_api_url,
        )
        if not api_url or not api_key or not model_id:
            return False
        existing = self._db.get_character_memories(character, user_key, limit=12)
        messages = build_memory_extraction_messages(user_text, assistant_text, existing)
        worker = NonStreamWorker(api_url, api_key, model_id, messages, None)
        self._memory_workers.append(worker)
        worker.finished.connect(
            lambda content, _reasoning, _actions, worker=worker, character=character, user_key=user_key,
            source_message_id=source_message_id, source_group_message_id=source_group_message_id,
            fallback_analysis=fallback_analysis:
                self._on_memory_extraction_finished(
                    worker,
                    character,
                    user_key,
                    content,
                    source_message_id,
                    source_group_message_id,
                    fallback_analysis,
                )
        )
        worker.error.connect(
            lambda _error, worker=worker, character=character, user_key=user_key, fallback_analysis=fallback_analysis:
                self._on_memory_extraction_error(worker, character, user_key, fallback_analysis)
        )
        worker.start()
        return True

    def _on_memory_extraction_finished(
        self,
        worker: NonStreamWorker,
        character: str,
        user_key: str,
        content: str,
        source_message_id: int | None,
        source_group_message_id: int | None,
        fallback_analysis: dict,
    ):
        self._forget_memory_worker(worker)
        relationship_analysis = parse_relationship_analysis_response(content) or fallback_analysis
        self._apply_relationship_analysis(
            character,
            user_key,
            relationship_analysis,
            "chat_model",
        )
        for memory in parse_memory_extraction_response(content):
            self._db.add_character_memory(
                character,
                user_key,
                memory["kind"],
                memory["content"],
                memory["importance"],
                source_message_id=source_message_id,
                source_group_message_id=source_group_message_id,
            )

    def _forget_memory_worker(self, worker: NonStreamWorker):
        self._memory_workers = [item for item in self._memory_workers if item is not worker]

    def _on_memory_extraction_error(
        self,
        worker: NonStreamWorker,
        character: str,
        user_key: str,
        fallback_analysis: dict,
    ):
        self._forget_memory_worker(worker)
        self._apply_relationship_analysis(character, user_key, fallback_analysis, "chat")

    def _group_system_prompt(self, character: str, spoken_names: list[str]) -> str:
        prompt = build_system_prompt(character, self._cfg)
        names = [self._model_manager.get_display_name(c) for c in self._group_characters]
        prompt += "\n\n【群聊规则】\n这是一个多人群聊。当前群聊成员：" + "、".join(names) + "。"
        prompt += (
            "\n你只扮演自己，不要代替其他角色说话。"
            "\n本轮只有你一个角色发言；其他角色如果需要回应，程序会在后续轮次单独生成。"
            "\n你的输出必须是一条仅属于你自己的单人回复，不要写成多人连续对话、对手戏脚本或旁白串场。"
            "\n严禁输出其他角色的直接台词，严禁替其他角色回答，严禁在同一条回复里模拟别人接话。"
            "\n如果需要提到其他成员的反应，只能用你自己的视角转述，不能写出对方的原话。"
            "\n回复时不要添加任何角色名前缀或剧本标签，例如【角色名】、[角色名]、角色名：，程序会自动添加。"
        )
        return prompt

    def _chat_attachment_dir(self) -> Path:
        path = app_base_dir() / "chat_attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _choose_chat_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            _tr("ChatWindow.attach_image_title", default="选择图片"),
            "",
            _tr("ChatWindow.attach_image_filter", default="Images (*.png *.jpg *.jpeg *.webp *.gif)"),
        )
        if not paths:
            return
        self._add_chat_images(paths)

    def _chat_image_paths_from_mime(self, mime_data) -> list[str]:
        if not mime_data or not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            path = url.toLocalFile() if url.isLocalFile() else ""
            if not path:
                continue
            source = Path(path)
            if source.suffix.lower() in _CHAT_IMAGE_EXTENSIONS and source.exists():
                paths.append(path)
        return paths

    def _mime_has_chat_images(self, mime_data) -> bool:
        return bool(self._chat_image_paths_from_mime(mime_data))

    def _set_composer_drag_active(self, active: bool):
        if self._composer_drag_active == active:
            return
        self._composer_drag_active = active
        self._update_composer_focus_style()

    def _handle_composer_drag_event(self, event) -> bool:
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._mime_has_chat_images(event.mimeData()):
                self._set_composer_drag_active(True)
                event.acceptProposedAction()
                return True
            self._set_composer_drag_active(False)
            event.ignore()
            return True
        if event_type == QEvent.Type.DragLeave:
            self._set_composer_drag_active(False)
            event.accept()
            return True
        if event_type == QEvent.Type.Drop:
            paths = self._chat_image_paths_from_mime(event.mimeData())
            self._set_composer_drag_active(False)
            if paths:
                self._add_chat_images(paths, dropped=True)
                event.acceptProposedAction()
            else:
                event.ignore()
            return True
        return False

    def _add_chat_images(self, paths: list[str], dropped: bool = False) -> int:
        added = 0
        target_dir = self._chat_attachment_dir()
        for path in paths:
            source = Path(path)
            suffix = source.suffix.lower()
            if suffix not in _CHAT_IMAGE_EXTENSIONS or not source.exists() or not source.is_file():
                continue
            target = target_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}{suffix}"
            try:
                shutil.copy2(source, target)
            except OSError as exc:
                QMessageBox.warning(
                    self,
                    _tr("ChatWindow.attach_failed_title", default="图片添加失败"),
                    _tr("ChatWindow.attach_failed_content", default="无法添加图片：{error}", error=str(exc)),
                )
                continue
            mime = mimetypes.guess_type(str(target))[0] or "image/png"
            self._pending_attachments.append({
                "type": "image",
                "path": str(target),
                "name": source.name,
                "mime": mime,
            })
            added += 1
        if added:
            self._update_attachment_hint()
            self._input.setFocus()
        elif dropped:
            self._composer_hint.setText(_tr("ChatWindow.attach_drop_unsupported", default="目前只能拖入 png、jpg、jpeg、webp 或 gif 图片。"))
        return added

    def _update_attachment_hint(self):
        if self._pending_attachments:
            count = len(self._pending_attachments)
            self._composer_hint.setText(_tr("ChatWindow.attach_pending", default="已添加 {count} 张图片，发送时会一起交给模型。", count=count))
        else:
            self._composer_hint.setText(self._idle_status_text())

    def _message_search_sources(self, tool_trace) -> list[dict]:
        if not tool_trace:
            return []
        if isinstance(tool_trace, str):
            try:
                tool_trace = json.loads(tool_trace)
            except (TypeError, ValueError):
                return []
        if not isinstance(tool_trace, dict):
            return []
        sources = tool_trace.get("web_search_sources", [])
        return MessageBubble._normalize_search_sources(sources)

    def _merge_search_sources(self, sources: list[dict]):
        current = list(self._stream_search_sources)
        for source in MessageBubble._normalize_search_sources(sources):
            if all(item["url"] != source["url"] for item in current):
                current.append(source)
        self._stream_search_sources = current[:9]
        if self._current_bubble:
            self._current_bubble.set_search_sources(self._stream_search_sources)

    def _extract_stream_search_sources(self, text: str) -> str:
        source = self._pending_source_json + text
        self._pending_source_json = ""
        cleaned, sources = extract_inline_search_sources(source)
        if sources:
            self._merge_search_sources(sources)
            return cleaned

        markers = (
            '{"web_search_sources"', '{"search_sources"', '{"sources"',
            '{ "web_search_sources"', '{ "search_sources"', '{ "sources"',
        )
        positions = [source.find(marker) for marker in markers if source.find(marker) >= 0]
        if positions:
            start = min(positions)
            self._pending_source_json = source[start:]
            return source[:start]
        return source

    def _normalize_attachments(self, attachments) -> list[dict]:
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
        safe_root = self._chat_attachment_dir().resolve()
        for item in attachments:
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            path = str(item.get("path", ""))
            if not path:
                continue
            try:
                resolved = Path(path).resolve()
                resolved.relative_to(safe_root)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved.suffix.lower() not in _CHAT_IMAGE_EXTENSIONS or not resolved.exists():
                continue
            result.append(dict(item, path=str(resolved)))
        return result

    def _image_data_url(self, attachment: dict) -> str:
        path = str(attachment.get("path", ""))
        if not path or not os.path.exists(path):
            return ""
        mime = attachment.get("mime") or mimetypes.guess_type(path)[0] or "image/png"
        try:
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return ""
        return f"data:{mime};base64,{encoded}"

    def _chat_message_content(self, text: str, attachments=None):
        items = self._normalize_attachments(attachments)
        if not items:
            return text
        text = text or ""
        vision_notes = []
        for item in items:
            summary = str(item.get("vision_summary", "") or "").strip()
            if summary:
                name = item.get("name") or Path(item.get("path", "")).name or "image"
                vision_notes.append(f"{name}：{summary}")
            else:
                error_note = str(item.get("vision_error", "") or "").strip()
                if error_note:
                    name = item.get("name") or Path(item.get("path", "")).name or "image"
                    vision_notes.append(f"{name}：{error_note}")
        if vision_notes:
            text += "\n\n【快速视觉模型观察】\n" + "\n".join(vision_notes)
        parts = [{"type": "text", "text": text}]
        for item in items:
            if str(item.get("vision_summary", "") or "").strip() or str(item.get("vision_error", "") or "").strip():
                continue
            data_url = self._image_data_url(item)
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
        return parts if len(parts) > 1 else text

    def _aux_vision_fallback_enabled(self) -> bool:
        if not self._cfg or not bool(self._cfg.get("llm_aux_vision_fallback_enabled", False)):
            return False
        aux_model_id = str(self._cfg.get("llm_aux_model_id", "") or "").strip()
        return bool(aux_model_id)

    def _attachments_need_aux_vision(self, attachments) -> bool:
        if not self._aux_vision_fallback_enabled():
            return False
        items = self._normalize_attachments(attachments)
        return any(not str(item.get("vision_summary", "") or "").strip() for item in items)

    def _supports_openai_responses_api(self, api_url: str) -> bool:
        url = (api_url or "").lower()
        return "api.openai.com" in url

    def _use_responses_api(self, api_url: str = "") -> bool:
        if not self._cfg or self._cfg.get("llm_api_mode", "chat_completions") != "responses":
            return False
        return self._supports_openai_responses_api(api_url or self._cfg.get("llm_api_url", ""))

    def _chat_completions_api_url(self, api_url: str) -> str:
        return chat_completions_api_url(api_url)

    def _reload_runtime_config(self):
        if self._cfg and hasattr(self._cfg, "load"):
            previous_user_key = getattr(self, "_chat_user_key", "")
            try:
                self._cfg.load()
            except Exception:
                pass
            self._user_name = self._cfg.get("user_name", "").strip()
            self._user_avatar_color = self._cfg.get("user_avatar_color", _TELEGRAM_ACCENT)
            self._user_avatar_path = str(self._cfg.get("user_avatar_path", "") or "").strip()
            self._show_reasoning = bool(self._cfg.get("llm_show_reasoning", True))
            next_user_key = self._user_memory_key()
            if next_user_key != previous_user_key:
                self._chat_user_key = next_user_key
                self._conv_id = None
                self._group_conv_id = ""
                self._group_queue = []
                self._group_spoken = []
                self._current_bubble = None
                self._clear_message_widgets()
                self._load_or_create_conversation()
                self._refresh_group_list()

    def _history_user_label(self) -> str:
        return self._user_name or _tr("ChatWindow.you")

    @staticmethod
    def _compact_history_text(content: str, attachments=None) -> str:
        text = str(content or "").strip()
        if isinstance(attachments, str) and attachments:
            try:
                attachments = json.loads(attachments)
            except (TypeError, ValueError):
                attachments = []
        if isinstance(attachments, list) and attachments:
            count = sum(1 for item in attachments if isinstance(item, dict) and item.get("type") == "image")
            if count:
                text = (text + "\n" if text else "") + f"[图片 {count} 张]"
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 420:
            text = text[:420].rstrip() + "..."
        return text

    def _split_group_history_message(self, content: str) -> tuple[str, str]:
        text = str(content or "").strip()
        first_line = text.splitlines()[0].strip() if text else ""
        if first_line.startswith("【") and "】" in first_line:
            speaker = first_line[1:first_line.index("】")].strip()
            body = "\n".join(text.splitlines()[1:]).strip()
            return speaker or _tr("ChatWindow.ai", default="AI"), body
        for character in self._model_manager.characters:
            display = self._model_manager.get_display_name(character)
            for prefix in (f"【{display}】", f"{display}：", f"{display}:"):
                if text.startswith(prefix):
                    return display, text[len(prefix):].strip()
        return _tr("ChatWindow.ai", default="AI"), text

    def _append_unified_history_item(self, items: list[dict], seen: set[tuple[str, int]], source: str, message: dict, label: str, content: str):
        msg_id = message.get("id")
        if msg_id is None:
            return
        key = (source, int(msg_id))
        if key in seen:
            return
        text = self._compact_history_text(content, message.get("attachments_json"))
        if not text:
            return
        seen.add(key)
        items.append({
            "created_at": message.get("created_at", ""),
            "id": int(msg_id),
            "label": label,
            "content": text,
        })

    def _unified_history_context(self, character: str, limit: int = 18) -> str:
        related = self._current_chat_members() if self._is_group_chat else [character]
        related = self._normalize_group_characters(related)
        if character and character not in related:
            related.append(character)

        items: list[dict] = []
        seen: set[tuple[str, int]] = set()
        user_label = self._history_user_label()

        for member in related:
            display = self._model_manager.get_display_name(member)
            for conv in self._db.get_conversations(member, self._chat_user_key)[:3]:
                for message in self._db.get_messages(conv["id"], limit=6):
                    if message["role"] == "assistant":
                        label = f"{display}/私聊"
                    elif message["role"] == "user":
                        label = f"{user_label}/{display}"
                    else:
                        continue
                    self._append_unified_history_item(items, seen, "private", message, label, message["content"])

        related_set = set(related)
        for chat in self._db.get_group_chats(self._chat_user_key)[:24]:
            group_key = chat.get("group_key", "")
            group_members = self._characters_for_group_key(group_key)
            if not group_members or not (related_set & set(group_members)):
                continue
            conversation_id = chat.get("conversation_id", "")
            for message in self._db.get_group_messages(group_key, conversation_id, limit=8, user_key=self._chat_user_key):
                if message["role"] == "assistant":
                    speaker, body = self._split_group_history_message(message["content"])
                    label = f"{speaker}/群聊"
                    content = body
                elif message["role"] == "user":
                    label = f"{user_label}/群聊"
                    content = message["content"]
                else:
                    continue
                self._append_unified_history_item(items, seen, "group", message, label, content)

        items.sort(key=lambda item: (item["created_at"], item["id"]))
        recent = items[-limit:]
        if not recent:
            return ""
        return "\n".join(f"{item['label']}：{item['content']}" for item in recent)

    def _build_messages_for_character(self, character: str, spoken_names: list[str]) -> list[dict]:
        system_prompt = self._group_system_prompt(character, spoken_names) if self._is_group_chat else build_system_prompt(character, self._cfg)
        dynamic_context = build_relationship_context(
            self._db,
            character,
            self._user_memory_key(),
            self._user_name or _tr("ChatWindow.you"),
        )
        unified_history = self._unified_history_context(character)
        if unified_history:
            dynamic_context += "\n\n【跨聊天记录】\n" + unified_history
        if self._is_group_chat and spoken_names:
            dynamic_context += "\n\n【群聊发言顺序】\n你是在" + "、".join(spoken_names) + "之后发言，请自然承接前面角色的内容。"
        if self._cfg and self._cfg.get("chat_integration_enabled", False) and self._cfg.get("chat_integration_include_context", True):
            external_context = self._db.external_chat_context_text()
            if external_context:
                dynamic_context += "\n\n" + external_context
        messages = [{"role": "system", "content": system_prompt}]
        if self._is_group_chat:
            max_history = 20
            history = self._db.get_group_messages(
                self._conversation_key,
                self._group_conv_id,
                limit=max_history * 2,
                user_key=self._chat_user_key,
            ) if self._group_conv_id else []
            for m in history:
                messages.append({
                    "role": m["role"],
                    "content": self._chat_message_content(m["content"], m.get("attachments_json")),
                })
        elif self._conv_id:
            max_history = 20
            history = self._db.get_messages(self._conv_id, limit=max_history * 2)
            for m in history:
                messages.append({
                    "role": m["role"],
                    "content": self._chat_message_content(m["content"], m.get("attachments_json")),
                })
        now = datetime.now()
        time_str = now.strftime("%Y-%m-%d %I:%M %p")
        dynamic_context += f"\n\n【后置提示词】\n当前时间：{time_str}"
        self._append_dynamic_context_to_last_user(messages, dynamic_context)
        return messages

    @staticmethod
    def _append_dynamic_context_to_last_user(messages: list[dict], context: str):
        context = str(context or "").strip()
        if not context:
            return
        suffix = "\n\n【动态上下文】\n" + context
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                content = messages[i]["content"]
                if isinstance(content, list) and content:
                    content.append({"type": "text", "text": suffix})
                else:
                    messages[i]["content"] = str(content) + suffix
                break


    def _send_message(self):
        text = self._input.toPlainText().strip()
        attachments = list(self._pending_attachments)
        if not text and attachments:
            text = _tr("ChatWindow.image_only_prompt", default="请看这张图片。")
        if not text:
            return

        if self._is_interrupt_command(text):
            self._interrupt_generation()
            return

        if self._generation_busy():
            self._composer_hint.setText(_tr("ChatWindow.busy_interrupt_hint", default="当前回复还在进行中；输入 @stop 或 @停止 可以中断。"))
            return

        self._reload_runtime_config()

        if not attachments and self._handle_local_memory_command(text):
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
        self._pending_attachments = []
        self._update_attachment_hint()
        self._set_busy(True, planning=self._is_group_chat)
        self._reset_tts_stream()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""

        user_bubble = MessageBubble(
            text,
            "user",
            self._user_name or _tr("ChatWindow.you"),
            avatar_color=self._user_avatar_color,
            avatar_path=self._user_avatar_path,
            show_reasoning=self._show_reasoning,
            attachments=self._normalize_attachments(attachments),
        )
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, user_bubble)
        self._relayout_message_bubbles()

        if self._attachments_need_aux_vision(attachments):
            self._start_aux_vision_fallback(text, attachments)
            return

        self._commit_user_message(text, attachments)

    def _on_send_button_clicked(self):
        if self._generation_busy():
            self._interrupt_generation(clear_input=False)
            return
        self._send_message()

    def _start_aux_vision_fallback(self, text: str, attachments: list[dict]):
        data_urls = []
        normalized = self._normalize_attachments(attachments)
        for item in normalized:
            if str(item.get("vision_summary", "") or "").strip():
                continue
            data_url = self._image_data_url(item)
            if data_url:
                data_urls.append(data_url)
        if not data_urls:
            self._commit_user_message(text, attachments)
            return
        self._show_aux_vision_divider()
        self._pending_vision_send = (text, [dict(item) for item in attachments])
        self._vision_fallback_worker = AuxVisionFallbackWorker(
            {
                "llm_api_url": self._cfg.get("llm_api_url", ""),
                "llm_api_key": self._cfg.get("llm_api_key", ""),
                "llm_model_id": self._cfg.get("llm_model_id", ""),
                "llm_aux_api_url": self._cfg.get("llm_aux_api_url", ""),
                "llm_aux_api_key": self._cfg.get("llm_aux_api_key", ""),
                "llm_aux_model_id": self._cfg.get("llm_aux_model_id", ""),
                "llm_aux_enable_thinking": self._cfg.get("llm_aux_enable_thinking", None),
            },
            text,
            data_urls,
            self,
        )
        self._vision_fallback_worker.finished.connect(self._on_aux_vision_finished)
        self._vision_fallback_worker.error.connect(self._on_aux_vision_error)
        self._vision_fallback_worker.start()

    def _show_aux_vision_divider(self):
        self._hide_plan_divider()
        divider = PlanDivider(_tr("ChatWindow.ai_viewing_image", default="AI 正在看图"), self._msg_area)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, divider)
        self._plan_divider = divider
        self._scroll_to_bottom()

    def _on_aux_vision_finished(self, summary: str):
        if self.sender() is not self._vision_fallback_worker:
            return
        self._vision_fallback_worker = None
        self._hide_plan_divider()
        pending = self._pending_vision_send
        self._pending_vision_send = None
        if not pending:
            self._set_busy(False)
            return
        text, attachments = pending
        summary = str(summary or "").strip()
        if summary:
            attachments = [
                dict(item, vision_summary=summary)
                if isinstance(item, dict) and item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
                else item
                for item in attachments
            ]
        else:
            empty_note = _tr("ChatWindow.vision_fallback_empty", default="快速视觉模型没有返回图片观察结果。")
            attachments = [
                dict(item, vision_error=empty_note)
                if isinstance(item, dict) and item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
                else item
                for item in attachments
            ]
            self._composer_hint.setText(empty_note)
            self._commit_user_message(text, attachments, start_response=False)
            self._set_busy(False)
            self._input.setFocus()
            return
        self._commit_user_message(text, attachments)

    def _on_aux_vision_error(self, error_msg: str):
        if self.sender() is not self._vision_fallback_worker:
            return
        self._vision_fallback_worker = None
        self._hide_plan_divider()
        pending = self._pending_vision_send
        self._pending_vision_send = None
        if not pending:
            self._set_busy(False)
            return
        text, attachments = pending
        error_note = _tr("ChatWindow.vision_fallback_failed", default="快速视觉模型看图失败：{error}", error=error_msg)
        attachments = [
            dict(item, vision_error=error_note)
            if isinstance(item, dict) and item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
            else item
            for item in attachments
        ]
        self._composer_hint.setText(error_note)
        self._commit_user_message(text, attachments, start_response=False)
        self._set_busy(False)
        self._input.setFocus()

    def _commit_user_message(self, text: str, attachments: list[dict], start_response: bool = True):
        if self._is_group_chat:
            self._last_group_user_message_id = self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "user", text, attachments=attachments, user_key=self._chat_user_key)
            self._last_user_message_id = None
        else:
            if self._conv_id is None:
                self._conv_id = self._db.create_conversation(self._conversation_key, user_key=self._chat_user_key)
            self._last_user_message_id = self._db.add_message(self._conv_id, "user", text, attachments=attachments)
            self._last_group_user_message_id = None
        self._last_user_text = text
        self._refresh_group_list()
        if not start_response:
            return
        if self._is_group_chat:
            self._group_spoken = []
            self._start_group_plan(text)
        else:
            self._start_response_for_character(self._character, [])

    def _start_group_plan(self, user_text: str):
        self._show_plan_divider()
        api_url = str(self._cfg.get("llm_aux_api_url", "") or "").strip() or self._cfg.get("llm_api_url", "")
        api_key = str(self._cfg.get("llm_aux_api_key", "") or "").strip() or self._cfg.get("llm_api_key", "")
        aux_model_id = self._cfg.get("llm_aux_model_id", "").strip() or self._cfg.get("llm_model_id", "")
        if self._use_responses_api(api_url):
            api_url = self._chat_completions_api_url(api_url)
        if not aux_model_id:
            self._hide_plan_divider()
            self._use_fallback_group_plan()
            return
        members = [
            {"key": character, "name": self._model_manager.get_display_name(character)}
            for character in self._group_characters
        ]
        recent = []
        history = self._db.get_group_messages(
            self._conversation_key,
            self._group_conv_id,
            limit=12,
            user_key=self._chat_user_key,
        ) if self._group_conv_id else []
        for m in history:
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
        self._group_plan_worker = NonStreamWorker(api_url, api_key, aux_model_id, messages, self._cfg.get("llm_aux_enable_thinking", None))
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
        if self.sender() is not self._group_plan_worker:
            return
        del reasoning_text, actions
        self._group_plan_worker = None
        self._hide_plan_divider()
        self._group_queue = self._parse_group_plan(full_text)
        if not self._group_queue:
            self._use_fallback_group_plan()
            return
        self._start_next_group_response()

    def _on_group_plan_error(self, error_msg: str):
        if self.sender() is not self._group_plan_worker:
            return
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
        self._stream_search_sources = []
        self._pending_source_json = ""
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
        tool_config = tool_config_snapshot(
            self._cfg,
            include_chat_keys=True,
            latest_user_text=self._last_user_text,
        )
        web_search = bool(self._cfg.get("llm_web_search_enabled", False))
        show_search_sources = bool(self._cfg.get("llm_web_search_show_sources", True))
        use_reminder_tools = reminder_tools_enabled(tool_config)
        if self._use_responses_api(api_url) and not web_search and not use_reminder_tools:
            self._worker = ResponsesStreamWorker(
                api_url,
                api_key,
                model_id,
                messages,
                enable_thinking,
                False,
                show_search_sources=show_search_sources,
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
                web_search=web_search,
                show_search_sources=show_search_sources,
                tool_config=tool_config,
            )
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
        if self.sender() is not self._worker:
            return
        if reasoning:
            self._reasoning_stream_text += reasoning
            if self._current_bubble:
                self._current_bubble.set_reasoning(self._reasoning_stream_text)
                self._current_bubble.set_streaming(True)
                self._scroll_to_bottom()

        text = self._extract_stream_search_sources(text)
        tts_clean = self._clean_tts_stream_text(text)
        if tts_clean:
            self._enqueue_tts_text(tts_clean, self._active_response_character)

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
        if self.sender() is not self._worker:
            return
        self._merge_search_sources(actions)
        acts = parse_action_tags(full_text)
        self._pending_action_character = self._active_response_character
        self._pending_actions.extend(acts)
        self._flush_actions()

        clean, inline_sources = extract_inline_search_sources(full_text)
        self._merge_search_sources(inline_sources)
        clean = strip_action_tags(clean)
        clean = self._sanitize_group_assistant_reply(self._active_response_character, clean)
        reasoning_clean = strip_action_tags(reasoning_text)
        self._flush_tts_text(self._active_response_character)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._reasoning_stream_text = reasoning_clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_reasoning(reasoning_clean)
            self._current_bubble.set_search_sources(self._stream_search_sources)
            self._current_bubble.set_text(clean)

        stored = self._assistant_content(self._active_response_character, clean)
        tool_trace = {"web_search_sources": self._stream_search_sources} if self._stream_search_sources else None
        if self._is_group_chat:
            self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "assistant", stored, reasoning_clean, tool_trace=tool_trace, user_key=self._chat_user_key)
            self._refresh_group_list()
        elif self._conv_id:
            self._db.add_message(self._conv_id, "assistant", stored, reasoning_clean, tool_trace=tool_trace)
            self._refresh_group_list()
        self._apply_relationship_update(self._active_response_character, self._last_user_text, clean, acts)

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
        if self.sender() is not self._worker:
            return
        self._merge_search_sources(actions)
        acts = parse_action_tags(full_text)
        self._pending_action_character = self._active_response_character
        self._pending_actions.extend(acts)
        self._flush_actions()

        clean, inline_sources = extract_inline_search_sources(full_text)
        self._merge_search_sources(inline_sources)
        clean = strip_action_tags(clean)
        clean = self._sanitize_group_assistant_reply(self._active_response_character, clean)
        reasoning_clean = strip_action_tags(reasoning_text)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._reasoning_stream_text = reasoning_clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_reasoning(reasoning_clean)
            self._current_bubble.set_search_sources(self._stream_search_sources)
            self._current_bubble.set_text(clean)

        stored = self._assistant_content(self._active_response_character, clean)
        tool_trace = {"web_search_sources": self._stream_search_sources} if self._stream_search_sources else None
        if self._is_group_chat:
            self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "assistant", stored, reasoning_clean, tool_trace=tool_trace, user_key=self._chat_user_key)
            self._refresh_group_list()
        elif self._conv_id:
            self._db.add_message(self._conv_id, "assistant", stored, reasoning_clean, tool_trace=tool_trace)
            self._refresh_group_list()
        self._apply_relationship_update(self._active_response_character, self._last_user_text, clean, acts)

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
        if self.sender() is not self._worker:
            return
        if self._current_bubble:
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(format_llm_error_message(error_msg))
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._reset_tts_stream(stop_player=False)
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

    def _tts_enabled(self) -> bool:
        return bool(_TTS_AVAILABLE and self._cfg and self._cfg.get("tts_enabled", False))

    def _reset_tts_stream(self, stop_player: bool = True):
        self._tts_text_buffer = ""
        self._tts_tag_buffer = ""
        self._tts_queue.clear()
        self._clear_tts_bubble_highlights()
        for worker in list(self._tts_active_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
        for worker in list(self._tts_translation_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
        self._tts_active_workers.clear()
        self._tts_translation_workers.clear()
        self._tts_audio_buffers.clear()
        self._tts_bubbles.clear()
        self._tts_characters.clear()
        self._tts_completed_sequences.clear()
        self._tts_generation += 1
        self._tts_next_sequence = 0
        self._tts_next_play_sequence = 0
        self._tts_playing_sequence = None
        if stop_player:
            self._tts_player.stop()

    def _enqueue_tts_text(self, text: str, character: str):
        if not self._tts_enabled():
            return
        text = self._clean_tts_payload(text)
        if not text:
            return
        self._tts_text_buffer += text

    def _flush_tts_text(self, character: str):
        if not self._tts_enabled():
            return
        self._tts_tag_buffer = ""
        text = self._clean_tts_payload(flush_tts_sentence(self._tts_text_buffer))
        self._tts_text_buffer = ""
        if text:
            sequence = self._tts_next_sequence
            self._tts_next_sequence += 1
            if self._current_bubble:
                self._tts_bubbles[sequence] = self._current_bubble
            self._tts_characters[sequence] = character
            self._queue_tts_request(sequence, text, character)
        self._start_next_tts_request()

    def _clear_tts_bubble_highlights(self):
        for bubble in self._tts_bubbles.values():
            bubble.set_tts_playing(False)

    def _set_tts_bubble_playing(self, sequence: int | None):
        for seq, bubble in list(self._tts_bubbles.items()):
            bubble.set_tts_playing(sequence is not None and seq == sequence)

    def _queue_tts_request(self, sequence: int, text: str, character: str):
        text = self._clean_tts_payload(text)
        if not text:
            return
        if self._tts_should_translate():
            worker = TTSTranslationWorker(sequence, self._tts_generation, text, character, tts_config_snapshot(self._cfg), self)
            self._tts_translation_workers[sequence] = worker
            worker.translated.connect(self._on_tts_translation_ready)
            worker.error.connect(self._on_tts_error)
            worker.finished.connect(self._on_tts_translation_finished)
            worker.start()
            return
        self._tts_queue.append((sequence, text, character))

    def _clean_tts_payload(self, text: str) -> str:
        text, _ = extract_inline_search_sources(text)
        text = re.sub(r"\{\s*\"(?:web_search_sources|search_sources|sources)\"\s*:\s*\[.*", "", text, flags=re.S)
        return strip_tts_action_tags(text).strip()

    def _tts_should_translate(self) -> bool:
        if not self._cfg or not self._cfg.get("tts_translate_to_selected_language", True):
            return False
        language = self._cfg.get("tts_language", "Chinese") or "Chinese"
        return language not in {"Chinese", "zh", "中文"}

    def _clean_tts_stream_text(self, text: str) -> str:
        source = self._tts_tag_buffer + text
        self._tts_tag_buffer = ""
        output = []
        i = 0
        while i < len(source):
            if source[i] != "[":
                output.append(source[i])
                i += 1
                continue

            end = source.find("]", i + 1)
            if end < 0:
                fragment = source[i:]
                if re.fullmatch(r"\[[A-Za-z0-9_.\-]*", fragment):
                    self._tts_tag_buffer = fragment
                else:
                    output.append(source[i])
                    output.append(fragment[1:])
                break

            tag = source[i + 1:end]
            if tag == "DONE" or re.fullmatch(r"[A-Za-z0-9_.\-]+", tag):
                i = end + 1
                continue
            output.append(source[i:end + 1])
            i = end + 1
        return "".join(output)

    def _start_next_tts_request(self):
        if self._tts_active_workers or self._tts_playing_sequence is not None or not self._tts_player.is_idle():
            return
        next_index = next((i for i, item in enumerate(self._tts_queue) if item[0] == self._tts_next_play_sequence), None)
        if next_index is None:
            return
        sequence, text, character = self._tts_queue.pop(next_index)
        config = tts_config_snapshot(self._cfg)
        config["tts_translate_to_selected_language"] = False
        worker = TTSRequestWorker(sequence, self._tts_generation, text, character, config, self)
        self._tts_active_workers[sequence] = worker
        worker.audio_ready.connect(self._on_tts_audio_ready)
        worker.error.connect(self._on_tts_error)
        worker.finished.connect(self._on_tts_worker_finished)
        worker.start()

    def _on_tts_translation_ready(self, sequence: int, generation: int, text: str, character: str):
        if generation != self._tts_generation or sequence not in self._tts_translation_workers:
            return
        self._tts_queue.append((sequence, text, character))
        self._start_next_tts_request()

    def _on_tts_translation_finished(self):
        worker = self.sender()
        sequence = getattr(worker, "sequence", None)
        if sequence is None or self._tts_translation_workers.get(sequence) is not worker:
            return
        self._tts_translation_workers.pop(sequence, None)

    def _on_tts_audio_ready(self, sequence: int, generation: int, audio: bytes, media_type: str):
        if generation != self._tts_generation or sequence not in self._tts_active_workers:
            return
        worker = self._tts_active_workers.get(sequence)
        if worker is not None:
            self._tts_player.prepare_lip_sync_text(
                getattr(worker, "prepared_text", ""),
                getattr(worker, "prepared_language", ""),
            )
        if sequence < self._tts_next_play_sequence:
            return
        if sequence == self._tts_next_play_sequence:
            if self._tts_playing_sequence is None:
                self._tts_playing_sequence = sequence
                self._set_tts_bubble_playing(sequence)
            if self._tts_playing_sequence == sequence:
                self._tts_player.enqueue(audio, media_type)
                return
        self._tts_audio_buffers.setdefault(sequence, []).append((audio, media_type))

    def _on_tts_error(self, error_msg: str):
        del error_msg

    def _on_tts_mouth_pose_changed(self, level: float, form: float):
        character = self._tts_characters.get(self._tts_playing_sequence)
        if character:
            publish_lip_sync(character, level, form)

    def _on_tts_playback_finished(self):
        self._release_tts_audio_in_order()
        self._start_next_tts_request()

    def _on_tts_worker_finished(self):
        worker = self.sender()
        sequence = getattr(worker, "sequence", None)
        generation = getattr(worker, "generation", None)
        if generation != self._tts_generation or sequence is None or self._tts_active_workers.get(sequence) is not worker:
            return
        self._tts_active_workers.pop(sequence, None)
        self._tts_completed_sequences.add(sequence)
        self._release_tts_audio_in_order()
        self._start_next_tts_request()

    def _release_tts_audio_in_order(self):
        if self._tts_playing_sequence is not None:
            if self._tts_playing_sequence not in self._tts_completed_sequences or not self._tts_player.is_idle():
                return
            sequence = self._tts_playing_sequence
            for audio, media_type in self._tts_audio_buffers.pop(sequence, []):
                self._tts_player.enqueue(audio, media_type)
            if not self._tts_player.is_idle():
                return
            self._tts_completed_sequences.remove(sequence)
            self._tts_next_play_sequence = sequence + 1
            self._tts_playing_sequence = None
            self._set_tts_bubble_playing(None)
            self._tts_bubbles.pop(sequence, None)
            self._tts_characters.pop(sequence, None)

        while self._tts_next_play_sequence in self._tts_completed_sequences and not self._tts_audio_buffers.get(self._tts_next_play_sequence):
            self._tts_bubbles.pop(self._tts_next_play_sequence, None)
            self._tts_characters.pop(self._tts_next_play_sequence, None)
            self._tts_completed_sequences.remove(self._tts_next_play_sequence)
            self._tts_next_play_sequence += 1

        buffers = self._tts_audio_buffers.pop(self._tts_next_play_sequence, [])
        if not buffers:
            return
        self._tts_playing_sequence = self._tts_next_play_sequence
        self._set_tts_bubble_playing(self._tts_playing_sequence)
        for audio, media_type in buffers:
            self._tts_player.enqueue(audio, media_type)

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
        if self._vision_fallback_worker and self._vision_fallback_worker.isRunning():
            self._vision_fallback_worker.requestInterruption()
            self._vision_fallback_worker.quit()
            self._vision_fallback_worker.wait(2000)
        for worker in list(self._cancelled_workers):
            if worker is not None and worker.isRunning():
                worker.wait(1000)
        self._cancelled_workers.clear()
        for worker in list(self._tts_active_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
        for worker in list(self._tts_translation_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
                worker.wait(1000)
        self._stream_flush_timer.stop()
        self._tts_player.stop()
        self._db.close()
        self.closed.emit()
        super().closeEvent(event)
