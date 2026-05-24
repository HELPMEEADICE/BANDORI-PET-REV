import os
import secrets
import shutil
import urllib.error
import urllib.request
import ssl
from datetime import datetime

import fluent_bootstrap

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation, QPoint, QEvent, QUrl, QRectF, QRect, QSize
from PySide6.QtGui import QColor, QPalette, QPixmap, QIcon, QCursor, QPainter, QPainterPath, QPen, QBrush, QIntValidator, QDoubleValidator, QDesktopServices, QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QSizePolicy, QScrollArea,
    QLineEdit, QGraphicsOpacityEffect, QGraphicsColorizeEffect, QApplication,
    QTextEdit, QPlainTextEdit, QToolButton, QFileDialog, QMessageBox,
)

from qfluentwidgets import (
    CardWidget, PushButton, PrimaryPushButton, TransparentPushButton,
    BodyLabel, StrongBodyLabel, TitleLabel, SubtitleLabel,
    FluentIcon, Slider, SwitchButton, ScrollArea, ComboBox, LineEdit,
    isDarkTheme, InfoBar, InfoBarPosition,
)
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from qfluentwidgets.components.widgets.menu import (
    LineEditMenu,
    MenuAnimationManager,
    MenuAnimationType,
    TextEditMenu,
)
from qfluentwidgets.common.config import qconfig

from i18n_manager import tr as _tr, set_language, available_languages, current_language
from llm_api_compat import (
    chat_completions_api_url,
    is_google_generative_language_url,
    models_api_url,
    responses_api_url,
    sanitize_chat_body_for_url,
)
from process_utils import app_base_dir
from app_info import APP_LICENSE_URL, APP_QQ_GROUP_URL, APP_REPO_URL, APP_VERSION
from app_update import detect_update_channel
from app_theme import (
    BANDORI_PRIMARY,
    BANDORI_PRIMARY_HOVER,
    BANDORI_PRIMARY_PRESSED,
    BANDORI_PRIMARY_DARK,
    BANDORI_PRIMARY_DARK_HOVER,
    BANDORI_PRIMARY_DARK_PRESSED,
    BANDORI_PRIMARY_SOFT,
    BANDORI_PRIMARY_SOFT_HOVER,
    BANDORI_PRIMARY_SOFT_DARK,
    BANDORI_PRIMARY_SOFT_DARK_HOVER,
    accent_color,
    apply_app_theme,
)
from database_manager import DatabaseManager
from relationship_memory import (
    MEMORY_KIND_LABELS,
    affection_label,
    display_user_name,
    mood_label,
    role_character_from_user_key,
    user_key_from_config,
)
TTSPlayer = None
TTSRequestWorker = None
_SETTINGS_TTS_AVAILABLE = True
_SETTINGS_TTS_CHECKED = False


def _ensure_settings_tts_available() -> bool:
    global TTSPlayer, TTSRequestWorker, _SETTINGS_TTS_AVAILABLE, _SETTINGS_TTS_CHECKED
    if _SETTINGS_TTS_CHECKED:
        return _SETTINGS_TTS_AVAILABLE
    _SETTINGS_TTS_CHECKED = True
    try:
        from tts_manager import TTSPlayer as player_class, TTSRequestWorker as worker_class
    except (ImportError, OSError):
        _SETTINGS_TTS_AVAILABLE = False
        return False
    TTSPlayer = player_class
    TTSRequestWorker = worker_class
    _SETTINGS_TTS_AVAILABLE = True
    return True

import json

from startup_manager import (
    is_startup_enabled,
    is_supported as is_startup_supported,
    set_startup_enabled,
)
from live2d_click_actions import (
    CLICK_MOTION_NONE,
    CLICK_MOTION_RANDOM,
    CLICK_MOTION_REGIONS,
    normalize_click_motion_actions,
)
from live2d_quality import LIVE2D_SCALE_MAX, LIVE2D_SCALE_MIN, clamp_live2d_scale, normalize_live2d_quality
from ui_helpers import rounded_avatar_pixmap

_BG_LIGHT = "#ffffff"
_BG_DARK = "#1e1e1e"
_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

_ROLEPLAY_STATUS_COLORS = {
    "green": "#2ecc71",
    "yellow": "#f1c40f",
    "red": "#e74c3c",
}

_ROLEPLAY_STATUS_TIPS = {
    "green": "SettingsWindow.roleplay_status_green",
    "yellow": "SettingsWindow.roleplay_status_yellow",
    "red": "SettingsWindow.roleplay_status_red",
}

PROJECT_REPO_URL = APP_REPO_URL
PROJECT_LICENSE_URL = APP_LICENSE_URL
PROJECT_QQ_GROUP_URL = APP_QQ_GROUP_URL
CLICK_MOTION_CONFIG_FORMAT = "bandori-click-motion-actions"
CLICK_MOTION_CONFIG_VERSION = 1
CLICK_MOTION_SCOPE_ALL = "all_models"
CLICK_MOTION_SCOPE_CHARACTER = "current_character"
CLICK_MOTION_SCOPE_COSTUME = "current_costume"
CLICK_MOTION_SCOPES = {
    CLICK_MOTION_SCOPE_ALL,
    CLICK_MOTION_SCOPE_CHARACTER,
    CLICK_MOTION_SCOPE_COSTUME,
}
MEMORY_KIND_ORDER = ("profile", "preference", "relationship", "manual", "note")


def _app_icon_path() -> str:
    base = app_base_dir()
    for name in ("icon.ico", "logo.ico"):
        path = os.path.join(base, name)
        if os.path.exists(path):
            return path
    return ""


def _rounded_avatar_pixmap(path: str, size: int) -> QPixmap:
    return rounded_avatar_pixmap(path, size)


class FluentContextLineEdit(QLineEdit):
    def contextMenuEvent(self, event):
        menu = LineEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


class FluentContextTextEdit(QTextEdit):
    def contextMenuEvent(self, event):
        menu = TextEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


class FluentPlainTextEdit(QPlainTextEdit):
    def insertFromMimeData(self, source):
        self.insertPlainText(source.text())


class CodeLineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)


class JsonCodeEdit(FluentPlainTextEdit):
    INDENT = "  "

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("JsonCodeEdit")
        self._line_number_area = CodeLineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._update_editor_caret)
        self.update_line_number_area_width(0)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(10)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * len(self.INDENT))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setAcceptDrops(True)

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_editor_caret(self):
        self.viewport().update()
        self._line_number_area.update()

    def update_line_number_area_width(self, _block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)
        dark = isDarkTheme()
        painter.fillRect(event.rect(), QColor("#252525" if dark else "#f4f4f4"))
        painter.setPen(QColor("#8f8f8f" if dark else "#737373"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()
        width = self._line_number_area.width() - 5

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if block_number == current_block:
                    painter.setPen(QColor(BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY))
                else:
                    painter.setPen(QColor("#8f8f8f" if dark else "#737373"))
                painter.drawText(0, top, width, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            if block.isValid():
                bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Tab and not (
            modifiers
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.ShiftModifier
            )
        ):
            self._indent_selection()
            return
        if key == Qt.Key.Key_Backtab or (
            key == Qt.Key.Key_Tab and modifiers & Qt.KeyboardModifier.ShiftModifier
        ):
            self._unindent_selection()
            return
        super().keyPressEvent(event)

    def _selected_blocks(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if end > start:
            end -= 1
        block = self.document().findBlock(start)
        last = self.document().findBlock(end)
        blocks = []
        while block.isValid():
            blocks.append(block)
            if block == last:
                break
            block = block.next()
        return blocks

    def _indent_selection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.insertText(self.INDENT)
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        blocks = self._selected_blocks()
        cursor.beginEditBlock()
        for block in blocks:
            line_cursor = QTextCursor(block)
            line_cursor.insertText(self.INDENT)
        cursor.endEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end + len(self.INDENT) * len(blocks), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _unindent_selection(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        blocks = self._selected_blocks()
        removed_before_start = 0
        removed_total = 0
        cursor.beginEditBlock()
        for block in blocks:
            text = block.text()
            count = 0
            if text.startswith("\t"):
                count = 1
            else:
                count = min(len(text) - len(text.lstrip(" ")), len(self.INDENT))
            if count <= 0:
                continue
            if block.position() < start:
                removed_before_start += count
            removed_total += count
            line_cursor = QTextCursor(block)
            line_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, count)
            line_cursor.removeSelectedText()
        cursor.endEditBlock()
        if cursor.hasSelection():
            new_start = max(0, start - removed_before_start)
            new_end = max(new_start, end - removed_total)
            cursor.setPosition(new_start)
            cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)


class OpaqueDropDownComboBox(ComboBox):
    def _createComboMenu(self):
        return OpaqueDropDownComboBoxMenu(self)


class OpaqueDropDownComboBoxMenu(ComboBoxMenu):
    def __init__(self, parent=None):
        super().__init__(parent)
        dark = isDarkTheme()
        bg = "#2b2b2b" if dark else "#ffffff"
        border = "#4a4a4a" if dark else "#d8d8d8"
        # Keep the popup window transparent so the rounded list widget defines
        # the visible shape instead of exposing an opaque rectangular backdrop.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.setPalette(palette)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.view.setGraphicsEffect(None)
        self.view.setStyleSheet(
            self.view.styleSheet()
            + f"""
            QListWidget#comboListWidget {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            """
        )

    def exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        self.view.adjustSize(pos, aniType)
        self.adjustSize()
        if not ani:
            aniType = MenuAnimationType.NONE
        self.aniManager = MenuAnimationManager.make(self, aniType)
        self.aniManager.exec(pos)
        self.show()
        if getattr(self, "isSubMenu", False) and getattr(self, "menuItem", None):
            self.menuItem.setSelected(True)


def _clamp_live2d_scale(value: object) -> int:
    return clamp_live2d_scale(value, use_device_pixel_ratio_default=True)


class ModelListItem(QWidget):
    selected = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, character: str, title: str, subtitle: str, current: bool, parent=None):
        super().__init__(parent)
        self._character = character
        self._current = current
        self._selection_anim = None
        self._animated_bg = None
        self.setObjectName("ModelListItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 6, 6)
        layout.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._title = BodyLabel(title, self)
        self._subtitle = QLabel(subtitle, self)
        for label in (self._title, self._subtitle):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setToolTip(label.text())
        text_col.addWidget(self._title)
        text_col.addWidget(self._subtitle)
        layout.addLayout(text_col, 1)

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("x")
        self._remove_btn.setFixedSize(22, 22)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.clicked.connect(lambda: self.remove_requested.emit(self._character))
        layout.addWidget(self._remove_btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedHeight(50)
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)
        if self._current:
            QTimer.singleShot(0, self._play_selected_animation)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._character)
        super().mousePressEvent(event)

    def _apply_theme(self):
        dark = isDarkTheme()
        selected_bg = QColor(BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT)
        bg = self._qss_color(self._animated_bg) if self._animated_bg else self._qss_color(selected_bg) if self._current else "transparent"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#9aa5bd" if dark else "#657089"
        danger = "#ff6b6b" if dark else "#c42b1c"
        self.setStyleSheet(f"""
            #ModelListItem {{
                background: {bg};
                border-radius: 8px;
            }}
            #ModelListItem:hover {{ background: {hover}; }}
            QLabel {{ color: {muted}; font-size: 11px; }}
            BodyLabel {{ color: {text}; font-size: 13px; }}
            QToolButton {{
                color: {danger};
                background: transparent;
                border: none;
                border-radius: 11px;
                font-weight: 700;
            }}
            QToolButton:hover {{ background: {'#4a2730' if dark else '#fde7e9'}; }}
        """)

    @staticmethod
    def _qss_color(color: QColor) -> str:
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

    def _play_selected_animation(self):
        dark = isDarkTheme()
        start = QColor(BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT)
        start.setAlpha(0)
        end = QColor(BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT)

        anim = QVariantAnimation(self)
        anim.setDuration(220)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_selected_anim_value)
        anim.finished.connect(self._on_selected_anim_finished)
        self._selection_anim = anim
        anim.start()

    def _on_selected_anim_value(self, value):
        self._animated_bg = value
        self._apply_theme()

    def _on_selected_anim_finished(self):
        self._animated_bg = None
        self._apply_theme()


class AddModelListItem(QPushButton):
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(_tr("SettingsWindow.model_list_add"), parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.clicked.connect(self.add_requested.emit)
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def _apply_theme(self):
        dark = isDarkTheme()
        border = accent_color(dark)
        bg = "#242226" if dark else BANDORI_PRIMARY_SOFT
        hover = "#30262b" if dark else BANDORI_PRIMARY_SOFT_HOVER
        text = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        self.setStyleSheet(f"""
            QPushButton {{
                color: {text};
                background: {bg};
                border: 1px dashed {border};
                border-radius: 10px;
                font-weight: 600;
                text-align: center;
            }}
            QPushButton:hover {{ background: {hover}; }}
        """)


class RoleplayStatusDot(QWidget):
    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self._status = status if status in _ROLEPLAY_STATUS_COLORS else "red"
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip(_tr(_ROLEPLAY_STATUS_TIPS.get(self._status, "")))

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 210), 2))
        painter.setBrush(QBrush(QColor(_ROLEPLAY_STATUS_COLORS[self._status])))
        painter.drawEllipse(1, 1, self.width() - 2, self.height() - 2)


def _theme_color(key: str) -> QColor:
    colors = {
        "bg": QColor(_BG_DARK if isDarkTheme() else _BG_LIGHT),
        "text": QColor("#ffffff" if isDarkTheme() else "#000000"),
        "dim": QColor("#999999" if isDarkTheme() else "#888888"),
    }
    return colors.get(key, QColor(_BG_LIGHT))


def _wrap_label(label: QLabel):
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return label


class CharacterCard(CardWidget):
    char_selected = Signal(str)

    def __init__(self, char_key: str, display_name: str, costume_count: int,
                 image_path: str = "", roleplay_status: str = "red", parent=None,
                 image_data: bytes = b""):
        super().__init__(parent)
        self._char_key = char_key
        self._disabled_for_existing = False
        self.setFixedSize(220, 360)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._status_dot = RoleplayStatusDot(roleplay_status, self)
        self._position_status_dot()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        image = QPixmap(image_path) if image_path else QPixmap()
        if image.isNull() and image_data:
            image.loadFromData(image_data)
        if not image.isNull():
            image_label = QLabel(self)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setPixmap(
                image.scaled(
                    188, 260,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(image_label, 1)

        name_label = StrongBodyLabel(display_name, self)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        self._count_label = BodyLabel(_tr("costume_count", count=costume_count), self)
        self._count_label.setStyleSheet(self._count_label_style())
        layout.addWidget(self._count_label)

        layout.addStretch()
        self.clicked.connect(self._on_card_clicked)
        qconfig.themeChanged.connect(self._update_count_label_style)

    def animate_in(self, delay_ms: int = 0):
        if self._disabled_for_existing:
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, anim.start)
        else:
            anim.start()

    @staticmethod
    def _count_label_style():
        return f"color: {'#999999' if isDarkTheme() else '#888888'};"

    def _update_count_label_style(self):
        self._count_label.setStyleSheet(self._count_label_style())

    def _on_card_clicked(self):
        if self._disabled_for_existing:
            return
        self.char_selected.emit(self._char_key)

    def set_disabled_for_existing(self, disabled: bool):
        self._disabled_for_existing = disabled
        self.setEnabled(not disabled)
        self.setCursor(Qt.CursorShape.ForbiddenCursor if disabled else Qt.CursorShape.PointingHandCursor)
        self.setGraphicsEffect(None)
        if disabled:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.38)
            self.setGraphicsEffect(effect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_status_dot()

    def _position_status_dot(self):
        self._status_dot.move(self.width() - self._status_dot.width() - 12, 12)


class BandCard(CardWidget):
    band_selected = Signal(str)

    def __init__(self, band_id: str, display_name: str, character_count: int,
                 logo_path: str = "", roleplay_status: str = "red", parent=None):
        super().__init__(parent)
        self._band_id = band_id
        self.setFixedSize(180, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._status_dot = RoleplayStatusDot(roleplay_status, self)
        self._position_status_dot()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        name_label = StrongBodyLabel(display_name, self)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        self._count_label = BodyLabel(_tr("character_count", count=character_count), self)
        self._count_label.setStyleSheet(self._count_label_style())
        layout.addWidget(self._count_label)

        logo = QPixmap(logo_path) if logo_path else QPixmap()
        if not logo.isNull():
            logo_label = QLabel(self)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setPixmap(
                logo.scaled(
                    142, 36,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(logo_label)

        layout.addStretch()
        self.clicked.connect(self._on_card_clicked)
        qconfig.themeChanged.connect(self._update_count_label_style)

    def animate_in(self, delay_ms: int = 0):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, anim.start)
        else:
            anim.start()

    @staticmethod
    def _count_label_style():
        return f"color: {'#999999' if isDarkTheme() else '#888888'};"

    def _update_count_label_style(self):
        self._count_label.setStyleSheet(self._count_label_style())

    def _on_card_clicked(self):
        self.band_selected.emit(self._band_id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_status_dot()

    def _position_status_dot(self):
        self._status_dot.move(self.width() - self._status_dot.width() - 12, 12)


class CostumeItem(QPushButton):
    preview_requested = Signal(object, str)
    preview_cancelled = Signal()

    def __init__(self, costume_id: str, display_name: str, parent=None):
        super().__init__(parent)
        self._costume_id = costume_id
        self.setText(display_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setCheckable(True)
        self._update_stylesheet()
        qconfig.themeChanged.connect(self._update_stylesheet)

    def animate_in(self, delay_ms: int = 0):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, anim.start)
        else:
            anim.start()

    def _update_stylesheet(self):
        dark = isDarkTheme()
        bg = "#2d2d2d" if dark else "#fafafa"
        border = "#555555" if dark else "#e0e0e0"
        hover_bg = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER
        hover_border = accent_color(dark)
        checked_bg = accent_color(dark)
        checked_fg = "#1a1a1a" if dark else "white"
        text_color = "#e0e0e0" if dark else "#333333"
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 8px 16px;
                border: 1px solid {border};
                border-radius: 6px;
                background: {bg};
                font-size: 14px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border-color: {hover_border};
            }}
            QPushButton:checked {{
                background: {checked_bg};
                color: {checked_fg};
                border-color: {hover_border};
            }}
        """)

    @property
    def costume_id(self):
        return self._costume_id

    def enterEvent(self, event):
        self._maybe_request_preview()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.preview_cancelled.emit()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        self._maybe_request_preview()
        super().keyPressEvent(event)

    def _maybe_request_preview(self):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.preview_requested.emit(self, self._costume_id)


class Live2DPreviewBubble(QWidget):
    def __init__(self, live2d_module, quality_profile="balanced", parent=None):
        super().__init__(None)
        from live2d_widget import Live2DWidget

        self._current_model_path = ""
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.resize(300, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 10, 10, 10)
        self._live2d_widget = Live2DWidget(self)
        self._live2d_widget.set_live2d_module(live2d_module)
        self._live2d_widget.set_render_quality(quality_profile)
        self._live2d_widget.set_static_render(True)
        self._apply_live2d_background()
        layout.addWidget(self._live2d_widget)
        qconfig.themeChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self):
        self._apply_live2d_background()
        self.update()

    def _apply_live2d_background(self):
        if isDarkTheme():
            self._live2d_widget.set_clear_color(32 / 255, 32 / 255, 32 / 255, 1.0)
        else:
            self._live2d_widget.set_clear_color(1.0, 1.0, 1.0, 1.0)

    def set_render_quality(self, profile: str):
        self._live2d_widget.set_render_quality(profile)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dark = isDarkTheme()
        bg = QColor(32, 32, 32, 255) if dark else QColor(255, 255, 255, 255)
        border = QColor(BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY)
        border.setAlpha(190 if dark else 165)
        shadow = QColor(0, 0, 0, 65) if dark else QColor(0, 0, 0, 38)

        rect = self.rect().adjusted(18, 2, -2, -2)
        tail_y = max(70, min(self.height() - 70, 150))

        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        tail = QPainterPath()
        tail.moveTo(19, tail_y - 18)
        tail.lineTo(2, tail_y)
        tail.lineTo(19, tail_y + 18)
        tail.closeSubpath()
        path = path.united(tail)

        shadow_path = QPainterPath(path)
        shadow_path.translate(0, 3)
        painter.fillPath(shadow_path, QBrush(shadow))
        painter.fillPath(path, QBrush(bg))
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)

    def show_preview(self, model_path: str, anchor: QWidget):
        if not model_path:
            self.hide()
            return
        if model_path != self._current_model_path:
            self._current_model_path = model_path
            self._live2d_widget.set_model_path(model_path)

        top_right = anchor.mapToGlobal(anchor.rect().topRight())
        pos = top_right + QPoint(14, -120)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = min(max(pos.x(), geo.left()), geo.right() - self.width())
            y = min(max(pos.y(), geo.top()), geo.bottom() - self.height())
            pos = QPoint(x, y)
        self.move(pos)
        if not self.isVisible():
            self.show()
        self.raise_()


class NavButton(QPushButton):
    nav_activated = Signal(str)

    def __init__(self, nav_key: str, icon, text: str, parent=None, accent: str = BANDORI_PRIMARY):
        super().__init__(parent)
        self._nav_key = nav_key
        self._custom_icon = icon if isinstance(icon, str) else ""
        self._fluent_icon = icon if hasattr(icon, "icon") else None
        self._fallback_icon = icon if isinstance(icon, QIcon) else QIcon()
        self._accent = QColor(accent if QColor(accent).isValid() else BANDORI_PRIMARY)
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self.setText(text)
        self.setCheckable(True)
        self.setIconSize(QSize(18, 18))
        self._update_stylesheet()
        qconfig.themeChanged.connect(self._update_stylesheet)
        self.clicked.connect(lambda: self.nav_activated.emit(self._nav_key))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def _update_stylesheet(self):
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dark = isDarkTheme()
        checked = self.isChecked()
        accent = QColor(self._accent)
        if dark:
            accent = accent.lighter(118)

        bg = QColor("#2a272b" if dark else "#ffffff")
        hover_bg = QColor("#332b31" if dark else "#fff6f9")
        checked_bg = QColor(accent)
        checked_bg.setAlpha(48 if dark else 28)
        border = QColor("#40373f" if dark else "#ece5ea")
        checked_border = QColor(accent)
        checked_border.setAlpha(170)
        text = QColor("#ece7ee" if dark else "#242832")
        checked_text = QColor(accent)
        muted_text = QColor("#cfc6d0" if dark else "#4f5968")

        rect = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        painter.setPen(QPen(checked_border if checked else border, 1))
        painter.setBrush(QBrush(checked_bg if checked else hover_bg if self._hovered else bg))
        painter.drawRoundedRect(rect, 9, 9)

        plate_rect = QRectF(12, (self.height() - 28) / 2, 28, 28)
        plate = QColor(accent)
        plate.setAlpha(236 if checked else 38 if not dark else 52)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(plate))
        painter.drawRoundedRect(plate_rect, 8, 8)

        icon_color = QColor("#ffffff") if checked else QColor(accent)
        icon_rect = QRect(
            int(plate_rect.x() + 5),
            int(plate_rect.y() + 5),
            18,
            18,
        )
        if self._custom_icon == "avatar":
            self._paint_avatar_icon(painter, QRectF(icon_rect), icon_color)
        elif self._fluent_icon is not None:
            self._fluent_icon.icon(color=icon_color).paint(painter, icon_rect)
        else:
            self._fallback_icon.paint(painter, icon_rect)

        font = QFont(self.font())
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(checked_text if checked else muted_text if self._hovered else text)
        text_rect = QRect(50, 0, max(1, self.width() - 58), self.height())
        label = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

    @staticmethod
    def _paint_avatar_icon(painter: QPainter, rect: QRectF, color: QColor):
        painter.save()
        pen = QPen(color, max(2, int(round(rect.width() * 0.12))))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        head_size = rect.width() * 0.38
        head = QRectF(
            rect.center().x() - head_size / 2,
            rect.top() + rect.height() * 0.13,
            head_size,
            head_size,
        )
        painter.drawEllipse(head)

        shoulders = QPainterPath()
        shoulders.moveTo(rect.left() + rect.width() * 0.18, rect.bottom() - rect.height() * 0.12)
        shoulders.cubicTo(
            rect.left() + rect.width() * 0.26,
            rect.top() + rect.height() * 0.62,
            rect.left() + rect.width() * 0.38,
            rect.top() + rect.height() * 0.57,
            rect.center().x(),
            rect.top() + rect.height() * 0.57,
        )
        shoulders.cubicTo(
            rect.left() + rect.width() * 0.62,
            rect.top() + rect.height() * 0.57,
            rect.left() + rect.width() * 0.74,
            rect.top() + rect.height() * 0.62,
            rect.right() - rect.width() * 0.18,
            rect.bottom() - rect.height() * 0.12,
        )
        painter.drawPath(shoulders)
        painter.restore()


class SettingsWindow(QWidget):
    model_selected = Signal(str, str)
    settings_changed = Signal(dict)
    launch_requested = Signal()

    def __init__(self, model_manager, current_char="", current_costume="",
                 current_fps=120, current_opacity=1.0, show_launch=True,
                 start_on_costumes=False, config_manager=None, vsync=True,
                 live2d_module=None):
        super().__init__()
        self._model_manager = model_manager
        self._live2d = live2d_module
        characters = model_manager.characters
        self._current_char = current_char or (characters[0] if start_on_costumes and characters else "")
        self._current_costume = current_costume
        self._fps = current_fps
        self._opacity = current_opacity
        self._cfg = config_manager
        self._costume_buttons: list[CostumeItem] = []
        self._selection_cards: list[CardWidget] = []
        self._selected_costume = ""
        self._configured_models = self._load_configured_models()
        self._selected_list_character = ""
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = False
        if self._current_char:
            self._selected_list_character = self._current_char
        elif self._configured_models:
            self._selected_list_character = self._configured_models[0]["character"]
            self._current_char = self._selected_list_character
            self._current_costume = self._configured_models[0]["costume"]
        self._selected_band = model_manager.get_character_band(self._current_char)
        self._preview_bubble = None
        self._owns_live2d = False
        self._live2d_error_shown = False
        self._show_launch = show_launch
        self._start_on_costumes = start_on_costumes
        self._theme_widgets: list[QWidget] = []
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, NavButton] = {}
        self._char_page = None
        self._costume_page = None
        self._llm_page = None
        self._tts_page = None
        self._pov_page = None
        self._memory_page = None
        self._relationship_guide_page = None
        self._memory_db = None
        self._memory_items: list[dict] = []
        self._selected_memory_id = 0
        self._compact_window_page = None
        self._chat_integration_page = None
        self._mcp_computer_page = None
        self._quality_page = None
        self._about_page = None
        self._current_page = "characters"
        self._selecting_model = False
        self._vsync = vsync
        self._game_topmost = bool(self._cfg.get("game_topmost", False)) if self._cfg else False
        self._hide_live2d_model = (
            bool(self._cfg.get("hide_live2d_model", False)) if self._cfg else False
        )
        self._live2d_idle_actions_enabled = (
            bool(self._cfg.get("live2d_idle_actions_enabled", True)) if self._cfg else True
        )
        self._auto_start_supported = is_startup_supported()
        self._auto_start_enabled = False
        if self._auto_start_supported:
            self._auto_start_enabled = is_startup_enabled()
        self._live2d_quality = normalize_live2d_quality(
            self._cfg.get("live2d_quality", "balanced") if self._cfg else "balanced"
        )
        self._live2d_scale = _clamp_live2d_scale(
            self._cfg.get("live2d_scale", 0) if self._cfg else 0
        )
        self._saved_user_name = ""
        self._user_avatar_path_pending = ""
        self._loading_llm_profile = False
        self._compact_window_reset_position_pending = False

        icon_path = _app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(_tr("SettingsWindow.title"))
        self.setMinimumSize(1180, 680)
        self.resize(1180, 680)

        self._launched = False
        self._init_ui()
        QApplication.instance().installEventFilter(self)

        if self._current_costume:
            self._selected_costume = self._current_costume
        else:
            self._selected_costume = self._model_manager.get_default_costume(
                self._current_char
            )

        self._nav_buttons["characters"].setChecked(True)

        if self._start_on_costumes:
            self._selecting_model = True
            self._populate_costumes(self._current_char)
            display = self._model_manager.get_display_name(self._current_char)
            self._costume_title.setText(_tr("SettingsWindow.costumes_title", display=display))
            self._costume_subtitle.setText(_tr("SettingsWindow.costume_subtitle", display=display))
            self._char_page.hide()
            self._costume_page.show()
        else:
            if self._selected_list_character:
                self._show_model_detail()
            else:
                self._enter_model_selection()
        self._refresh_model_list()

    def _load_configured_models(self) -> list[dict]:
        models = self._cfg.get("models", []) if self._cfg else []
        result = []
        seen = set()
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                character = item.get("character", "")
                costume = item.get("costume", "")
                if character in seen or character not in self._model_manager.characters:
                    continue
                if not costume:
                    costume = self._model_manager.get_default_costume(character)
                path = self._model_manager.get_model_json_path(character, costume)
                if not path:
                    continue
                entry = dict(item)
                entry.update({"character": character, "costume": costume, "path": path})
                self._restore_model_action_profile(entry, prefer_existing=True)
                entry["click_motion_actions"] = normalize_click_motion_actions(
                    entry.get("click_motion_actions", {})
                )
                if entry.get("pet_mode") not in {"live2d", "pixel"}:
                    entry["pet_mode"] = "live2d"
                result.append(entry)
                seen.add(character)
        if self._current_char and self._current_char not in seen:
            costume = self._current_costume or self._model_manager.get_default_costume(self._current_char)
            path = self._model_manager.get_model_json_path(self._current_char, costume)
            if path:
                pet_mode = self._cfg.get("pet_mode", "live2d") if self._cfg else "live2d"
                if pet_mode not in {"live2d", "pixel"}:
                    pet_mode = "live2d"
                result.insert(0, {
                    "character": self._current_char,
                    "costume": costume,
                    "path": path,
                    "window_x": self._cfg.get("window_x", -1) if self._cfg else -1,
                    "window_y": self._cfg.get("window_y", -1) if self._cfg else -1,
                    "window_width": self._cfg.get("window_width", 400) if self._cfg else 400,
                    "window_height": self._cfg.get("window_height", 500) if self._cfg else 500,
                    "pixel_window_x": self._cfg.get("pixel_window_x", -1) if self._cfg else -1,
                    "pixel_window_y": self._cfg.get("pixel_window_y", -1) if self._cfg else -1,
                    "pet_mode": pet_mode,
                    "click_motion_actions": {},
                })
        return result

    def _restore_model_action_profile(self, entry: dict, prefer_existing: bool = False):
        if not self._cfg or not hasattr(self._cfg, "get_model_action_profile"):
            return
        profile = self._cfg.get_model_action_profile(
            entry.get("character", ""),
            entry.get("costume", ""),
        )
        if not profile:
            return
        for key in ("default_motion", "default_expression", "click_motion_actions"):
            if prefer_existing and entry.get(key):
                continue
            if profile.get(key):
                entry[key] = profile[key]

    def _archive_model_action_profile(self, entry: dict):
        if not self._cfg or not hasattr(self._cfg, "set_model_action_profile"):
            return
        self._cfg.set_model_action_profile(
            entry.get("character", ""),
            entry.get("costume", ""),
            entry,
        )

    def _on_language_changed(self, index: int):
        lang = self._lang_combo.itemData(index)
        if lang and lang != current_language():
            set_language(lang)
            if self._cfg:
                self._cfg.set("language", lang)
                self._cfg.save()

    def closeEvent(self, event):
        self._dispose_live2d_preview()
        self._cleanup_workers()
        if self._memory_db is not None:
            try:
                self._memory_db.close()
            except Exception:
                pass
            self._memory_db = None
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def _ensure_live2d_preview_module(self):
        if self._live2d:
            return self._live2d
        try:
            from live2d_lua_adapter import live2d

            self._live2d = live2d
            self._owns_live2d = True
            return self._live2d
        except Exception as exc:
            if not self._live2d_error_shown:
                self._live2d_error_shown = True
                InfoBar.error(
                    _tr("SettingsWindow.preview_failed_title"),
                    _tr("SettingsWindow.preview_failed_content", error=str(exc)),
                    duration=4000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            return None

    def _dispose_live2d_preview(self):
        self._hide_costume_preview()
        if self._preview_bubble is not None:
            self._preview_bubble.close()
            self._preview_bubble.deleteLater()
            self._preview_bubble = None
        if self._owns_live2d and self._live2d is not None:
            try:
                self._live2d.dispose()
            except Exception:
                pass
            self._live2d = None
            self._owns_live2d = False

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Shift:
            self._hide_costume_preview()
        elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Shift:
            widget = QApplication.widgetAt(QCursor.pos())
            while widget is not None:
                if isinstance(widget, CostumeItem):
                    self._show_costume_preview(widget, widget.costume_id)
                    break
                widget = widget.parentWidget()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(80, self._play_entrance)
            QTimer.singleShot(120, lambda: self._animate_indicator(self._current_page))

    def _play_entrance(self):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start()

    @staticmethod
    def _animate_button_in(btn):
        effect = QGraphicsOpacityEffect(btn)
        effect.setOpacity(0.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", btn)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: btn.setGraphicsEffect(None))
        anim.start()

    def _cleanup_workers(self):
        for attr in ('_test_worker', '_fetch_worker', '_mcp_test_worker', '_update_check_worker', '_update_apply_worker', '_tts_test_worker'):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(2000)
        player = getattr(self, '_tts_test_player', None)
        if player is not None:
            player.stop()

    def _make_theme_widget(self, w: QWidget) -> QWidget:
        w.setAutoFillBackground(True)
        self._theme_widgets.append(w)
        self._apply_theme_bg(w)
        return w

    def _apply_theme_bg(self, w: QWidget):
        bg = _BG_DARK if isDarkTheme() else _BG_LIGHT
        pal = w.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        w.setPalette(pal)
        w.update()

    def _update_all_theme_bgs(self):
        for w in self._theme_widgets:
            self._apply_theme_bg(w)

    @staticmethod
    def _refresh_theme_widget_styles(widget: QWidget | None):
        if widget is None:
            return
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def _refresh_json_code_edit_theme(self, edit: JsonCodeEdit | None):
        if edit is None:
            return
        self._refresh_theme_widget_styles(edit)
        self._refresh_theme_widget_styles(edit.viewport())
        self._refresh_theme_widget_styles(edit._line_number_area)

    def _init_ui(self):
        self._make_theme_widget(self)
        qconfig.themeChanged.connect(self._update_all_theme_bgs)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        main_layout.addWidget(sidebar, 0)

        right_area = QWidget()
        right_layout = QHBoxLayout(right_area)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(16)

        self._page_stack = self._make_theme_widget(QWidget())
        self._page_stack_layout = QVBoxLayout(self._page_stack)
        self._page_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._page_stack_layout.setSpacing(0)

        self._char_page = self._build_char_page()
        self._costume_page = self._build_costume_page()
        self._costume_page.hide()

        self._page_stack_layout.addWidget(self._char_page)
        self._page_stack_layout.addWidget(self._costume_page)

        self._pages["characters"] = self._char_page
        self._pages["costumes"] = self._costume_page

        page_scroll = ScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setWidget(self._page_stack)
        page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        side_panel = self._build_side_panel()

        right_layout.addWidget(page_scroll, 1)
        right_layout.addWidget(side_panel, 0)

        main_layout.addWidget(right_area, 1)

    def _add_lazy_page(self, key: str, page: QWidget):
        page.hide()
        self._page_stack_layout.addWidget(page)
        self._pages[key] = page
        return page

    def _ensure_page(self, key: str) -> QWidget | None:
        if key in self._pages:
            return self._pages[key]
        if key in {"llm", "pov"}:
            self._ensure_llm_and_pov_pages()
            return self._pages.get(key)
        if key == "tts":
            self._tts_page = self._add_lazy_page("tts", self._build_tts_page())
            return self._tts_page
        if key == "memory":
            self._memory_page = self._add_lazy_page("memory", self._build_memory_page())
            return self._memory_page
        if key == "relationship_guide":
            self._relationship_guide_page = self._add_lazy_page(
                "relationship_guide",
                self._build_relationship_guide_page(),
            )
            return self._relationship_guide_page
        if key == "compact_window":
            self._compact_window_page = self._add_lazy_page("compact_window", self._build_compact_window_page())
            return self._compact_window_page
        if key == "chat_integration":
            self._chat_integration_page = self._add_lazy_page("chat_integration", self._build_chat_integration_page())
            return self._chat_integration_page
        if key == "mcp_computer":
            self._mcp_computer_page = self._add_lazy_page("mcp_computer", self._build_mcp_computer_page())
            return self._mcp_computer_page
        if key == "quality":
            self._quality_page = self._add_lazy_page("quality", self._build_quality_page())
            return self._quality_page
        if key == "about":
            self._about_page = self._add_lazy_page("about", self._build_about_page())
            return self._about_page
        return None

    def _ensure_llm_and_pov_pages(self):
        if self._pov_page is None:
            self._pov_page = self._add_lazy_page("pov", self._build_pov_page())
        if self._llm_page is None:
            self._llm_page = self._add_lazy_page("llm", self._build_llm_page())

    def _update_sidebar_style(self):
        dark = isDarkTheme()
        self._sidebar.setStyleSheet(f"""
            #sidebar {{
                background: {'#181818' if dark else '#f5f6f8'};
                border-right: 1px solid {'#404040' if dark else '#d5d5d5'};
            }}
        """)

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(210)
        sidebar.setObjectName("sidebar")
        self._sidebar = sidebar

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(10, 4, 4, 10)
        brand_row.setSpacing(8)
        icon_path = _app_icon_path()
        if icon_path:
            icon_label = QLabel(sidebar)
            icon_label.setFixedSize(24, 24)
            icon_label.setPixmap(QIcon(icon_path).pixmap(24, 24))
            brand_row.addWidget(icon_label)
        title = StrongBodyLabel(_tr("SettingsWindow.nav_title"), sidebar)
        title.setMinimumWidth(0)
        brand_row.addWidget(title, 1)
        layout.addLayout(brand_row)

        btn_chars = NavButton("characters", FluentIcon.PEOPLE, _tr("SettingsWindow.nav_chars"), sidebar, "#e4004f")
        btn_chars.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["characters"] = btn_chars
        layout.addWidget(btn_chars)

        btn_llm = NavButton("llm", FluentIcon.ROBOT, _tr("SettingsWindow.nav_llm"), sidebar, "#8b5cf6")
        btn_llm.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["llm"] = btn_llm
        layout.addWidget(btn_llm)

        btn_tts = NavButton("tts", FluentIcon.MICROPHONE, _tr("SettingsWindow.nav_tts", "TTS 配置"), sidebar, "#f59e0b")
        btn_tts.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["tts"] = btn_tts
        layout.addWidget(btn_tts)

        btn_pov = NavButton("pov", "avatar", _tr("SettingsWindow.nav_pov"), sidebar, "#ec4899")
        btn_pov.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["pov"] = btn_pov
        layout.addWidget(btn_pov)

        btn_memory = NavButton("memory", FluentIcon.LIBRARY, _tr("SettingsWindow.nav_memory"), sidebar, "#10b981")
        btn_memory.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["memory"] = btn_memory
        layout.addWidget(btn_memory)

        btn_relationship_guide = NavButton(
            "relationship_guide",
            FluentIcon.QUICK_NOTE,
            _tr("SettingsWindow.nav_relationship_guide"),
            sidebar,
            "#06b6d4",
        )
        btn_relationship_guide.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["relationship_guide"] = btn_relationship_guide
        layout.addWidget(btn_relationship_guide)

        btn_compact = NavButton("compact_window", FluentIcon.CHAT, _tr("SettingsWindow.nav_compact_window"), sidebar, "#3b82f6")
        btn_compact.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["compact_window"] = btn_compact
        layout.addWidget(btn_compact)

        btn_chat_integration = NavButton(
            "chat_integration",
            FluentIcon.MESSAGE,
            _tr("SettingsWindow.nav_chat_integration", default="聊天接入"),
            sidebar,
            "#14b8a6",
        )
        btn_chat_integration.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["chat_integration"] = btn_chat_integration
        layout.addWidget(btn_chat_integration)

        btn_mcp_computer = NavButton(
            "mcp_computer",
            FluentIcon.DEVELOPER_TOOLS,
            _tr("SettingsWindow.nav_mcp_computer", default="工具与电脑控制"),
            sidebar,
            "#64748b",
        )
        btn_mcp_computer.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["mcp_computer"] = btn_mcp_computer
        layout.addWidget(btn_mcp_computer)

        btn_quality = NavButton("quality", FluentIcon.PALETTE, _tr("SettingsWindow.nav_quality"), sidebar, "#22c55e")
        btn_quality.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["quality"] = btn_quality
        layout.addWidget(btn_quality)

        layout.addStretch()

        btn_about = NavButton("about", FluentIcon.INFO, _tr("SettingsWindow.nav_about"), sidebar, "#94a3b8")
        btn_about.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["about"] = btn_about
        layout.addWidget(btn_about)

        self._update_sidebar_style()
        self._theme_widgets.append(sidebar)
        qconfig.themeChanged.connect(self._update_sidebar_style)

        self._nav_indicator = QWidget(sidebar)
        self._nav_indicator.setFixedSize(4, 28)
        self._nav_indicator.setStyleSheet(f"""
            background: {BANDORI_PRIMARY};
            border-radius: 2px;
        """)
        self._nav_indicator.hide()

        return sidebar

    def _on_nav_selected(self, nav_key: str):
        page = self._ensure_page(nav_key)
        if page is None:
            return

        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == nav_key)
        for stacked_page in self._pages.values():
            stacked_page.hide()

        if nav_key == "characters":
            self._selecting_model = False
            self._char_page.show()
            self._costume_page.hide()
            if self._selected_list_character:
                self._show_model_detail()
            else:
                self._enter_model_selection()
        else:
            self._costume_page.hide()
            page.show()
            if nav_key == "memory":
                self._refresh_memory_page()
        self._current_page = nav_key
        self._animate_indicator(nav_key)

    def _activate_char_page_for_model_list(self):
        page = self._ensure_page("characters")
        if page is None:
            return
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        for stacked_page in self._pages.values():
            stacked_page.hide()
        self._costume_page.hide()
        self._char_page.show()
        self._current_page = "characters"
        self._animate_indicator("characters")

    def _animate_indicator(self, nav_key: str):
        btn = self._nav_buttons.get(nav_key)
        if btn is None:
            return
        target_y = btn.mapTo(btn.parent(), btn.rect().topLeft()).y()
        target_y += (btn.height() - self._nav_indicator.height()) // 2
        target_x = 6
        target = self._nav_indicator.geometry()
        target.setRect(target_x, target_y, 4, 28)

        if not self._nav_indicator.isVisible():
            self._nav_indicator.move(target_x, target_y)
            self._nav_indicator.show()
            effect = QGraphicsOpacityEffect(self._nav_indicator)
            effect.setOpacity(0.0)
            self._nav_indicator.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self._nav_indicator)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self._nav_indicator.setGraphicsEffect(None))
            anim.start()
            return

        if hasattr(self, '_indicator_anim') and self._indicator_anim:
            self._indicator_anim.stop()
        self._indicator_anim = QPropertyAnimation(self._nav_indicator, b"geometry")
        self._indicator_anim.setDuration(300)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._indicator_anim.setStartValue(self._nav_indicator.geometry())
        self._indicator_anim.setEndValue(target)
        self._indicator_anim.start()

    def _build_char_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        self._selection_back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.band_back"), page)
        self._selection_back_btn.clicked.connect(self._go_back_to_bands)
        top_row.addWidget(self._selection_back_btn)
        top_row.addStretch()
        self._selection_title = TitleLabel(_tr("SettingsWindow.band_title"), page)
        self._selection_title.setMinimumWidth(0)
        top_row.addWidget(self._selection_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._selection_subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.band_subtitle"), page))
        self._selection_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._selection_subtitle)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        grid_widget = self._make_theme_widget(QWidget())
        self._char_grid = QGridLayout(grid_widget)
        self._char_grid.setSpacing(12)
        self._char_grid.setContentsMargins(0, 8, 0, 0)
        cols_per_row = 3
        for c in range(cols_per_row):
            self._char_grid.setColumnStretch(c, 0)
        self._selection_grid_widget = grid_widget
        self._selection_back_btn.hide()

        scroll.setWidget(grid_widget)
        self._selection_scroll = scroll
        layout.addWidget(scroll, 1)

        self._model_detail_widget = self._make_theme_widget(QWidget(page))
        detail_shell = QVBoxLayout(self._model_detail_widget)
        detail_shell.setContentsMargins(0, 0, 0, 0)
        detail_shell.setSpacing(0)

        detail_center = QHBoxLayout()
        detail_center.setContentsMargins(0, 0, 0, 0)
        detail_center.setSpacing(12)
        detail_center.addStretch(1)

        self._detail_card = CardWidget(self._model_detail_widget)
        self._detail_card.setFixedSize(280, 420)
        card_layout = QVBoxLayout(self._detail_card)
        card_h_margin = 26
        card_layout.setContentsMargins(card_h_margin, 22, card_h_margin, 22)
        card_layout.setSpacing(12)

        self._detail_image = QLabel(self._detail_card)
        self._detail_image.setFixedSize(self._detail_card.width() - card_h_margin * 2, 260)
        self._detail_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._detail_image, 0, Qt.AlignmentFlag.AlignHCenter)

        self._detail_name = TitleLabel("", self._detail_card)
        self._detail_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_costume = SubtitleLabel("", self._detail_card)
        self._detail_costume.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_band = BodyLabel("", self._detail_card)
        self._detail_band.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._detail_name)
        card_layout.addWidget(self._detail_costume)
        card_layout.addWidget(self._detail_band)

        action_scroll = ScrollArea(self._model_detail_widget)
        action_scroll.setWidgetResizable(True)
        action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        action_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        action_scroll.setFixedWidth(320)
        action_scroll.setFixedHeight(self._detail_card.height())
        action_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        action_container = self._make_theme_widget(QWidget(action_scroll))
        action_container.setFixedWidth(292)
        action_col = QVBoxLayout(action_container)
        action_col.setContentsMargins(0, 0, 0, 0)
        action_col.setSpacing(10)
        self._switch_model_btn = QPushButton(_tr("SettingsWindow.model_switch"), action_container)
        self._switch_model_btn.setFixedSize(132, 132)
        self._switch_model_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._switch_model_btn.clicked.connect(self._edit_selected_model)
        action_col.addWidget(self._switch_model_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = _wrap_label(BodyLabel(_tr("SettingsWindow.model_detail_hint"), action_container))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(hint)

        idle_row = QHBoxLayout()
        idle_row.setSpacing(8)
        idle_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.live2d_idle_actions"), action_container))
        self._live2d_idle_actions_switch = SwitchButton(action_container)
        self._live2d_idle_actions_switch.setChecked(self._live2d_idle_actions_enabled)
        self._live2d_idle_actions_switch.checkedChanged.connect(self._on_live2d_idle_actions_changed)
        idle_row.addWidget(idle_label, 1)
        idle_row.addWidget(self._live2d_idle_actions_switch, 0, Qt.AlignmentFlag.AlignRight)
        action_col.addLayout(idle_row)
        idle_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.live2d_idle_actions_hint"), action_container))
        idle_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(idle_hint)

        motion_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.default_motion"), action_container))
        motion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(motion_label)
        motion_row = QHBoxLayout()
        motion_row.setSpacing(8)
        self._default_motion_combo = OpaqueDropDownComboBox(action_container)
        self._default_motion_combo.setMinimumWidth(190)
        self._default_motion_combo.currentIndexChanged.connect(self._on_default_motion_changed)
        motion_row.addWidget(self._default_motion_combo, 1)
        self._default_motion_btn = PushButton(_tr("SettingsWindow.model_default"), action_container)
        self._default_motion_btn.clicked.connect(self._reset_default_motion)
        motion_row.addWidget(self._default_motion_btn)
        action_col.addLayout(motion_row)

        expression_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.default_expression"), action_container))
        expression_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(expression_label)
        expression_row = QHBoxLayout()
        expression_row.setSpacing(8)
        self._default_expression_combo = OpaqueDropDownComboBox(action_container)
        self._default_expression_combo.setMinimumWidth(190)
        self._default_expression_combo.currentIndexChanged.connect(self._on_default_expression_changed)
        expression_row.addWidget(self._default_expression_combo, 1)
        self._default_expression_btn = PushButton(_tr("SettingsWindow.model_default"), action_container)
        self._default_expression_btn.clicked.connect(self._reset_default_expression)
        expression_row.addWidget(self._default_expression_btn)
        action_col.addLayout(expression_row)

        click_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.click_motion_title"), action_container))
        click_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(click_label)
        click_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.click_motion_hint"), action_container))
        click_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(click_hint)

        click_grid_widget = QWidget(action_container)
        click_grid = QGridLayout(click_grid_widget)
        click_grid.setContentsMargins(0, 0, 0, 0)
        click_grid.setHorizontalSpacing(8)
        click_grid.setVerticalSpacing(6)
        self._click_motion_combos = {}
        self._click_expression_combos = {}
        click_grid.addWidget(BodyLabel(_tr("SettingsWindow.click_motion_column_motion"), click_grid_widget), 0, 0)
        click_grid.addWidget(BodyLabel(_tr("SettingsWindow.click_motion_column_expression"), click_grid_widget), 0, 1)
        for index, region in enumerate(CLICK_MOTION_REGIONS):
            row = index * 2 + 1
            label = BodyLabel(_tr(f"SettingsWindow.click_motion_region_{region}"), click_grid_widget)
            label.setWordWrap(True)
            combo = OpaqueDropDownComboBox(click_grid_widget)
            combo.setMinimumWidth(135)
            combo.setMaximumWidth(140)
            combo.currentIndexChanged.connect(
                lambda index, r=region: self._on_click_motion_changed(r, index)
            )
            expression_combo = OpaqueDropDownComboBox(click_grid_widget)
            expression_combo.setMinimumWidth(135)
            expression_combo.setMaximumWidth(140)
            expression_combo.currentIndexChanged.connect(
                lambda index, r=region: self._on_click_expression_changed(r, index)
            )
            self._click_motion_combos[region] = combo
            self._click_expression_combos[region] = expression_combo
            click_grid.addWidget(label, row, 0, 1, 2)
            click_grid.addWidget(combo, row + 1, 0)
            click_grid.addWidget(expression_combo, row + 1, 1)
        click_grid.setColumnStretch(0, 1)
        click_grid.setColumnStretch(1, 1)
        action_col.addWidget(click_grid_widget)

        self._click_motion_reset_btn = PushButton(_tr("SettingsWindow.click_motion_reset"), action_container)
        self._click_motion_reset_btn.clicked.connect(self._reset_click_motions)
        action_col.addWidget(self._click_motion_reset_btn, 0, Qt.AlignmentFlag.AlignRight)

        click_scope_label = _wrap_label(BodyLabel(_tr("SettingsWindow.click_motion_scope_label"), action_container))
        click_scope_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(click_scope_label)
        self._click_motion_scope_combo = OpaqueDropDownComboBox(action_container)
        self._click_motion_scope_combo.setMinimumWidth(260)
        self._click_motion_scope_combo.addItem(
            _tr("SettingsWindow.click_motion_scope_all"),
            userData=CLICK_MOTION_SCOPE_ALL,
        )
        self._click_motion_scope_combo.addItem(
            _tr("SettingsWindow.click_motion_scope_character"),
            userData=CLICK_MOTION_SCOPE_CHARACTER,
        )
        self._click_motion_scope_combo.addItem(
            _tr("SettingsWindow.click_motion_scope_costume"),
            userData=CLICK_MOTION_SCOPE_COSTUME,
        )
        self._click_motion_scope_combo.setCurrentIndex(2)
        action_col.addWidget(self._click_motion_scope_combo, 0, Qt.AlignmentFlag.AlignHCenter)

        click_import_export_row = QHBoxLayout()
        click_import_export_row.setSpacing(8)
        self._click_motion_import_btn = PushButton(
            FluentIcon.SYNC,
            _tr("SettingsWindow.click_motion_import"),
            action_container,
        )
        self._click_motion_import_btn.clicked.connect(self._import_click_motion_config)
        self._click_motion_export_btn = PushButton(
            FluentIcon.SAVE,
            _tr("SettingsWindow.click_motion_export"),
            action_container,
        )
        self._click_motion_export_btn.clicked.connect(self._export_click_motion_config)
        click_import_export_row.addWidget(self._click_motion_import_btn)
        click_import_export_row.addWidget(self._click_motion_export_btn)
        action_col.addLayout(click_import_export_row)
        action_scroll.setWidget(action_container)

        detail_center.addWidget(self._detail_card, 0, Qt.AlignmentFlag.AlignTop)
        detail_center.addWidget(action_scroll, 0, Qt.AlignmentFlag.AlignTop)
        detail_center.addStretch(1)
        detail_shell.addLayout(detail_center, 1)

        self._detail_action_hint = hint
        self._detail_idle_label = idle_label
        self._detail_idle_hint = idle_hint
        self._detail_motion_label = motion_label
        self._detail_expression_label = expression_label
        self._detail_click_motion_label = click_label
        self._detail_click_motion_hint = click_hint
        self._detail_click_motion_scope_label = click_scope_label
        self._detail_action_scroll = action_scroll
        self._update_switch_button_style()
        qconfig.themeChanged.connect(self._update_switch_button_style)

        layout.addWidget(self._model_detail_widget, 1)
        self._model_detail_widget.hide()
        return page

    def _update_switch_button_style(self):
        dark = isDarkTheme()
        card_bg = "#252525" if dark else "#ffffff"
        card_border = "#3a3a3a" if dark else "#e5e7eb"
        hint_color = "#a7b0bf" if dark else "#687385"
        self._detail_card.setStyleSheet(f"""
            CardWidget {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 18px;
            }}
        """)
        self._detail_action_hint.setStyleSheet(f"color: {hint_color};")
        self._detail_idle_label.setStyleSheet(f"color: {hint_color};")
        self._detail_idle_hint.setStyleSheet(f"color: {hint_color};")
        self._detail_motion_label.setStyleSheet(f"color: {hint_color};")
        self._detail_expression_label.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_label.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_hint.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_scope_label.setStyleSheet(f"color: {hint_color};")
        self._switch_model_btn.setStyleSheet(f"""
            QPushButton {{
                color: #ffffff;
                background: {BANDORI_PRIMARY if not dark else BANDORI_PRIMARY_DARK};
                border: 1px solid {accent_color(dark)};
                border-radius: 66px;
                font-size: 18px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: {BANDORI_PRIMARY_HOVER if not dark else BANDORI_PRIMARY_DARK_HOVER}; }}
            QPushButton:pressed {{ background: {BANDORI_PRIMARY_PRESSED if not dark else BANDORI_PRIMARY_DARK_PRESSED}; }}
        """)

    def _show_model_detail(self):
        item = self._selected_model_item()
        if not item:
            self._enter_model_selection()
            return
        self._selecting_model = False
        self._clear_selection_cards()
        self._selection_scroll.hide()
        self._selection_grid_widget.hide()
        self._selection_back_btn.hide()
        self._selection_title.setText(_tr("SettingsWindow.model_detail_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.model_detail_subtitle"))
        self._model_detail_widget.show()

        character = item["character"]
        costume = item["costume"]
        self._current_char = character
        self._current_costume = costume
        self._selected_costume = costume
        self._selected_band = self._model_manager.get_character_band(character)

        display = self._model_manager.get_display_name(character)
        costume_name = self._model_manager.get_costume_display_name(character, costume)
        band_name = self._model_manager.get_band_display_name(self._selected_band) if self._selected_band else ""
        self._detail_name.setText(display)
        self._detail_costume.setText(_tr("SettingsWindow.detail_costume", costume=costume_name))
        self._detail_band.setText(_tr("SettingsWindow.detail_band", band=band_name) if band_name else "")
        self._populate_default_motion_combo(item)
        self._populate_default_expression_combo(item)
        self._populate_click_motion_combos(item)

        pixmap = QPixmap(self._model_manager.get_character_image_path(character))
        image_data = self._model_manager.get_character_image_data(character)
        if pixmap.isNull() and image_data:
            pixmap.loadFromData(image_data)
        if not pixmap.isNull():
            self._detail_image.setPixmap(pixmap.scaled(
                self._detail_image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._detail_image.setText(display)

    def _selected_model_item(self):
        for item in self._configured_models:
            if item["character"] == self._selected_list_character:
                return item
        return None

    def _on_live2d_idle_actions_changed(self, checked: bool):
        self._live2d_idle_actions_enabled = bool(checked)
        if self._cfg:
            self._cfg.set("live2d_idle_actions_enabled", self._live2d_idle_actions_enabled)
            self._cfg.save()

    def _populate_default_motion_combo(self, item: dict):
        combo = self._default_motion_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_tr("SettingsWindow.follow_model_default"), userData="")
        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        for motion in motions:
            combo.addItem(motion, userData=motion)
        current = item.get("default_motion", "")
        if current not in motions:
            current = ""
            item["default_motion"] = ""
        for idx in range(combo.count()):
            if combo.itemData(idx) == current:
                combo.setCurrentIndex(idx)
                break
        combo.blockSignals(False)

    def _on_default_motion_changed(self, index: int):
        item = self._selected_model_item()
        if not item:
            return
        motion = self._default_motion_combo.itemData(index) or ""
        item["default_motion"] = motion
        self._save_configured_models()

    def _reset_default_motion(self):
        item = self._selected_model_item()
        if not item:
            return
        item["default_motion"] = ""
        self._populate_default_motion_combo(item)
        self._save_configured_models()

    def _populate_default_expression_combo(self, item: dict):
        combo = self._default_expression_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_tr("SettingsWindow.follow_model_default"), userData="")
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])
        for expression in expressions:
            combo.addItem(expression, userData=expression)
        current = item.get("default_expression", "")
        if current not in expressions:
            current = ""
            item["default_expression"] = ""
        for idx in range(combo.count()):
            if combo.itemData(idx) == current:
                combo.setCurrentIndex(idx)
                break
        combo.blockSignals(False)

    def _on_default_expression_changed(self, index: int):
        item = self._selected_model_item()
        if not item:
            return
        expression = self._default_expression_combo.itemData(index) or ""
        item["default_expression"] = expression
        self._save_configured_models()

    def _reset_default_expression(self):
        item = self._selected_model_item()
        if not item:
            return
        item["default_expression"] = ""
        self._populate_default_expression_combo(item)
        self._save_configured_models()

    def _populate_click_motion_combos(self, item: dict):
        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])
        actions = normalize_click_motion_actions(
            item.get("click_motion_actions", {}),
            motions,
            expressions,
        )
        item["click_motion_actions"] = actions
        for region, combo in self._click_motion_combos.items():
            expression_combo = self._click_expression_combos[region]
            current = actions.get(region, {})
            current_motion = current.get("motion", "")
            current_expression = current.get("expression", "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_tr("SettingsWindow.click_motion_auto"), userData="")
            combo.addItem(_tr("SettingsWindow.click_motion_random"), userData=CLICK_MOTION_RANDOM)
            combo.addItem(_tr("SettingsWindow.click_motion_none"), userData=CLICK_MOTION_NONE)
            for motion in motions:
                combo.addItem(motion, userData=motion)
            for idx in range(combo.count()):
                if combo.itemData(idx) == current_motion:
                    combo.setCurrentIndex(idx)
                    break
            combo.blockSignals(False)

            expression_combo.blockSignals(True)
            expression_combo.clear()
            expression_combo.addItem(_tr("SettingsWindow.click_expression_default"), userData="")
            for expression in expressions:
                expression_combo.addItem(expression, userData=expression)
            for idx in range(expression_combo.count()):
                if expression_combo.itemData(idx) == current_expression:
                    expression_combo.setCurrentIndex(idx)
                    break
            expression_combo.blockSignals(False)

    def _on_click_motion_changed(self, region: str, index: int):
        item = self._selected_model_item()
        if not item:
            return
        combo = self._click_motion_combos.get(region)
        if combo is None:
            return
        actions = normalize_click_motion_actions(item.get("click_motion_actions", {}))
        value = combo.itemData(index) or ""
        current = dict(actions.get(region, {}))
        if value:
            current["motion"] = value
            if value == CLICK_MOTION_NONE:
                current["expression"] = ""
                expression_combo = self._click_expression_combos.get(region)
                if expression_combo is not None:
                    expression_combo.blockSignals(True)
                    expression_combo.setCurrentIndex(0)
                    expression_combo.blockSignals(False)
            actions[region] = current
        else:
            current["motion"] = ""
            if current.get("expression"):
                actions[region] = current
            else:
                actions.pop(region, None)
        item["click_motion_actions"] = actions
        self._save_configured_models()

    def _on_click_expression_changed(self, region: str, index: int):
        item = self._selected_model_item()
        if not item:
            return
        combo = self._click_expression_combos.get(region)
        if combo is None:
            return
        actions = normalize_click_motion_actions(item.get("click_motion_actions", {}))
        value = combo.itemData(index) or ""
        current = dict(actions.get(region, {}))
        if value:
            current["expression"] = value
            actions[region] = current
        else:
            current["expression"] = ""
            if current.get("motion"):
                actions[region] = current
            else:
                actions.pop(region, None)
        item["click_motion_actions"] = actions
        self._save_configured_models()

    def _reset_click_motions(self):
        item = self._selected_model_item()
        if not item:
            return
        item["click_motion_actions"] = {}
        self._populate_click_motion_combos(item)
        self._save_configured_models()

    def _current_click_motion_scope(self) -> str:
        if not hasattr(self, "_click_motion_scope_combo"):
            return CLICK_MOTION_SCOPE_COSTUME
        scope = self._click_motion_scope_combo.itemData(
            self._click_motion_scope_combo.currentIndex()
        )
        return scope if scope in CLICK_MOTION_SCOPES else CLICK_MOTION_SCOPE_COSTUME

    @staticmethod
    def _click_motion_profile_key(character: str, costume: str) -> str:
        return f"{character}\t{costume}"

    @staticmethod
    def _split_click_motion_profile_key(key: str) -> tuple[str, str]:
        parts = str(key or "").split("\t", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", ""

    @staticmethod
    def _looks_like_click_motion_actions(value) -> bool:
        return isinstance(value, dict) and any(
            str(region) in CLICK_MOTION_REGIONS for region in value
        )

    def _selected_click_motion_pair(self) -> tuple[str, str]:
        item = self._selected_model_item()
        if not item:
            return "", ""
        return item.get("character", ""), item.get("costume", "")

    def _click_motion_scope_display(self, scope: str) -> str:
        key = {
            CLICK_MOTION_SCOPE_ALL: "SettingsWindow.click_motion_scope_all",
            CLICK_MOTION_SCOPE_CHARACTER: "SettingsWindow.click_motion_scope_character",
            CLICK_MOTION_SCOPE_COSTUME: "SettingsWindow.click_motion_scope_costume",
        }.get(scope, "SettingsWindow.click_motion_scope_costume")
        return _tr(key)

    def _default_click_motion_config_path(self) -> str:
        name = "bandori-click-actions-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
        return str(app_base_dir() / name)

    def _known_click_motion_model(self, character: str, costume: str) -> bool:
        return bool(
            character
            and costume
            and self._model_manager.get_model_json_path(character, costume)
        )

    def _normalize_click_actions_for_model(self, character: str, costume: str, actions) -> dict:
        motions = self._model_manager.get_motion_names(character, costume)
        expressions = self._model_manager.get_expression_names(character, costume)
        return normalize_click_motion_actions(actions, motions, expressions)

    def _click_motion_profile_from_item(self, item: dict) -> dict | None:
        character = item.get("character", "")
        costume = item.get("costume", "")
        if not self._known_click_motion_model(character, costume):
            return None
        return {
            "character": character,
            "costume": costume,
            "click_motion_actions": self._normalize_click_actions_for_model(
                character,
                costume,
                item.get("click_motion_actions", {}),
            ),
        }

    def _stored_click_motion_profiles(self) -> dict[str, dict]:
        profiles: dict[str, dict] = {}
        raw_profiles = self._cfg.get("model_action_settings", {}) if self._cfg else {}
        if isinstance(raw_profiles, dict):
            for key, profile in raw_profiles.items():
                if not isinstance(profile, dict) or "click_motion_actions" not in profile:
                    continue
                character, costume = self._split_click_motion_profile_key(key)
                if not self._known_click_motion_model(character, costume):
                    continue
                actions = self._normalize_click_actions_for_model(
                    character,
                    costume,
                    profile.get("click_motion_actions", {}),
                )
                if actions:
                    profiles[self._click_motion_profile_key(character, costume)] = {
                        "character": character,
                        "costume": costume,
                        "click_motion_actions": actions,
                    }

        for item in self._configured_models:
            profile = self._click_motion_profile_from_item(item)
            if profile and profile["click_motion_actions"]:
                profiles[
                    self._click_motion_profile_key(profile["character"], profile["costume"])
                ] = profile
        return profiles

    def _collect_click_motion_profiles(self, scope: str) -> dict[str, dict]:
        profiles = self._stored_click_motion_profiles()
        character, costume = self._selected_click_motion_pair()
        current = self._click_motion_profile_from_item(self._selected_model_item() or {})
        current_key = self._click_motion_profile_key(character, costume) if current else ""

        if scope == CLICK_MOTION_SCOPE_COSTUME:
            return {current_key: current} if current else {}

        if scope == CLICK_MOTION_SCOPE_CHARACTER:
            filtered = {
                key: profile
                for key, profile in profiles.items()
                if profile.get("character") == character
            }
            if current:
                filtered[current_key] = current
            return filtered

        if current:
            profiles[current_key] = current
        return profiles

    def _export_click_motion_config(self):
        scope = self._current_click_motion_scope()
        if self._cfg:
            self._save_configured_models()
        profiles = self._collect_click_motion_profiles(scope)
        if not profiles:
            InfoBar.warning(
                _tr("SettingsWindow.click_motion_export_empty_title"),
                _tr("SettingsWindow.click_motion_export_empty_content"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _tr("SettingsWindow.click_motion_export_dialog"),
            self._default_click_motion_config_path(),
            _tr("SettingsWindow.click_motion_config_filter"),
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".json"

        current_character, current_costume = self._selected_click_motion_pair()
        payload = {
            "format": CLICK_MOTION_CONFIG_FORMAT,
            "version": CLICK_MOTION_CONFIG_VERSION,
            "scope": scope,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "source": {
                "character": current_character,
                "costume": current_costume,
            },
            "profiles": [
                profiles[key]
                for key in sorted(
                    profiles,
                    key=lambda value: (
                        profiles[value].get("character", ""),
                        profiles[value].get("costume", ""),
                    ),
                )
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self._show_click_motion_config_error(exc)
            return

        InfoBar.success(
            _tr("SettingsWindow.click_motion_export_success_title"),
            _tr(
                "SettingsWindow.click_motion_export_success_content",
                count=len(profiles),
            ),
            duration=2500,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _import_click_motion_config(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.click_motion_import_dialog"),
            str(app_base_dir()),
            _tr("SettingsWindow.click_motion_config_filter"),
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            imported = self._extract_click_motion_profiles(payload)
        except Exception as exc:
            self._show_click_motion_config_error(exc)
            return

        if not imported:
            InfoBar.warning(
                _tr("SettingsWindow.click_motion_import_empty_title"),
                _tr("SettingsWindow.click_motion_import_empty_content"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        scope = self._current_click_motion_scope()
        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.click_motion_import_confirm_title"),
            _tr(
                "SettingsWindow.click_motion_import_confirm_content",
                scope=self._click_motion_scope_display(scope),
                count=len(imported),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        applied = self._apply_imported_click_motion_profiles(imported, scope)
        if not applied:
            InfoBar.warning(
                _tr("SettingsWindow.click_motion_import_no_match_title"),
                _tr("SettingsWindow.click_motion_import_no_match_content"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        self._save_configured_models()
        item = self._selected_model_item()
        if item:
            self._populate_click_motion_combos(item)
        InfoBar.success(
            _tr("SettingsWindow.click_motion_import_success_title"),
            _tr(
                "SettingsWindow.click_motion_import_success_content",
                count=applied,
            ),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _extract_click_motion_profiles(self, payload) -> list[dict]:
        if not isinstance(payload, dict):
            return []

        extracted: dict[tuple[str, str], dict] = {}
        current_character, current_costume = self._selected_click_motion_pair()
        source = payload.get("source", {})
        if not isinstance(source, dict):
            source = {}
        default_character = str(
            payload.get("character") or source.get("character") or current_character or ""
        )
        default_costume = str(
            payload.get("costume") or source.get("costume") or current_costume or ""
        )

        def add_profile(character, costume, actions, allow_empty: bool = False):
            character = str(character or "").strip()
            costume = str(costume or "").strip()
            if not character or not costume:
                return
            normalized = normalize_click_motion_actions(actions)
            if not normalized and not allow_empty:
                return
            extracted[(character, costume)] = {
                "character": character,
                "costume": costume,
                "click_motion_actions": normalized,
            }

        raw_profiles = payload.get("profiles")
        if isinstance(raw_profiles, list):
            for profile in raw_profiles:
                if not isinstance(profile, dict):
                    continue
                actions = profile.get("click_motion_actions")
                if actions is None:
                    actions = profile.get("actions")
                if actions is None and self._looks_like_click_motion_actions(profile):
                    actions = profile
                if actions is None:
                    continue
                add_profile(
                    profile.get("character") or default_character,
                    profile.get("costume") or default_costume,
                    actions,
                    allow_empty=True,
                )
        elif isinstance(raw_profiles, dict):
            for key, profile in raw_profiles.items():
                key_character, key_costume = self._split_click_motion_profile_key(key)
                if not isinstance(profile, dict):
                    continue
                actions = profile.get("click_motion_actions")
                if actions is None:
                    actions = profile.get("actions")
                if actions is None and self._looks_like_click_motion_actions(profile):
                    actions = profile
                if actions is None:
                    continue
                add_profile(
                    profile.get("character") or key_character or default_character,
                    profile.get("costume") or key_costume or default_costume,
                    actions,
                    allow_empty=True,
                )

        raw_models = payload.get("models")
        if isinstance(raw_models, list):
            for item in raw_models:
                if not isinstance(item, dict) or "click_motion_actions" not in item:
                    continue
                add_profile(
                    item.get("character"),
                    item.get("costume"),
                    item.get("click_motion_actions"),
                )

        raw_action_settings = payload.get("model_action_settings")
        if isinstance(raw_action_settings, dict):
            for key, profile in raw_action_settings.items():
                if not isinstance(profile, dict) or "click_motion_actions" not in profile:
                    continue
                character, costume = self._split_click_motion_profile_key(key)
                add_profile(character, costume, profile.get("click_motion_actions"))

        root_actions = payload.get("click_motion_actions")
        if root_actions is None:
            root_actions = payload.get("actions")
        if root_actions is not None:
            add_profile(default_character, default_costume, root_actions, allow_empty=True)

        return list(extracted.values())

    def _apply_imported_click_motion_profiles(self, imported: list[dict], scope: str) -> int:
        if not self._cfg:
            return 0
        updates: dict[tuple[str, str], dict] = {}
        current_character, current_costume = self._selected_click_motion_pair()

        if scope == CLICK_MOTION_SCOPE_COSTUME:
            profile = self._select_click_motion_import_for_current_costume(
                imported,
                current_character,
                current_costume,
            )
            if profile:
                updates[(current_character, current_costume)] = profile["click_motion_actions"]
        elif scope == CLICK_MOTION_SCOPE_CHARACTER:
            for profile in imported:
                character = profile.get("character", "")
                costume = profile.get("costume", "")
                if character != current_character:
                    continue
                if self._known_click_motion_model(character, costume):
                    updates[(character, costume)] = profile["click_motion_actions"]
        else:
            for profile in imported:
                character = profile.get("character", "")
                costume = profile.get("costume", "")
                if self._known_click_motion_model(character, costume):
                    updates[(character, costume)] = profile["click_motion_actions"]

        applied = 0
        for (character, costume), actions in updates.items():
            if self._apply_click_motion_actions_to_model(character, costume, actions):
                applied += 1
        return applied

    def _select_click_motion_import_for_current_costume(
        self,
        imported: list[dict],
        current_character: str,
        current_costume: str,
    ) -> dict | None:
        if not current_character or not current_costume:
            return None
        exact = [
            profile for profile in imported
            if profile.get("character") == current_character
            and profile.get("costume") == current_costume
        ]
        if exact:
            return exact[0]
        if len(imported) == 1:
            return imported[0]
        return None

    def _apply_click_motion_actions_to_model(self, character: str, costume: str, actions) -> bool:
        if not self._known_click_motion_model(character, costume):
            return False
        normalized = self._normalize_click_actions_for_model(character, costume, actions)
        profile = self._cfg.get_model_action_profile(character, costume)
        if normalized:
            profile["click_motion_actions"] = normalized
        else:
            profile.pop("click_motion_actions", None)
        self._cfg.set_model_action_profile(character, costume, profile)
        for item in self._configured_models:
            if item.get("character") == character and item.get("costume") == costume:
                item["click_motion_actions"] = normalized
        return True

    def _show_click_motion_config_error(self, exc: Exception):
        InfoBar.error(
            _tr("SettingsWindow.click_motion_config_failed_title"),
            str(exc),
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _enter_model_selection(self):
        self._selecting_model = True
        self._model_detail_widget.hide()
        self._selection_scroll.show()
        self._selection_grid_widget.show()
        self._populate_bands()
        self._char_page.show()
        self._costume_page.hide()
        self._current_page = "characters"
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        self._animate_indicator("characters")

    def _edit_selected_model(self):
        self._editing_list_character = self._selected_list_character
        self._editing_model_index = next(
            (
                idx for idx, item in enumerate(self._configured_models)
                if item["character"] == self._selected_list_character
            ),
            None,
        )
        self._adding_model = False
        self._enter_model_selection()

    def _clear_selection_cards(self):
        for card in self._selection_cards:
            self._char_grid.removeWidget(card)
            card.deleteLater()
        self._selection_cards.clear()

    def _populate_bands(self):
        self._clear_selection_cards()
        self._model_detail_widget.hide()
        self._selection_grid_widget.show()
        self._selection_scroll.show()
        self._selected_band = ""
        self._selection_back_btn.hide()
        self._selection_title.setText(_tr("SettingsWindow.band_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.band_subtitle"))

        col = 0
        row = 0
        cols_per_row = 3
        card_idx = 0
        for band in self._model_manager.bands:
            characters = band.get("characters", [])
            if not characters:
                continue
            card = BandCard(
                band.get("id", ""), band.get("display", ""),
                len(characters), band.get("logo", ""),
                self._model_manager.get_band_advanced_roleplay_status(band.get("id", "")),
                self._selection_grid_widget
            )
            card.band_selected.connect(self._on_band_selected)
            card.animate_in(delay_ms=card_idx * 80)
            self._char_grid.addWidget(card, row, col)
            self._selection_cards.append(card)
            col += 1
            card_idx += 1
            if col >= cols_per_row:
                col = 0
                row += 1

    def _populate_characters(self, band_id: str):
        self._clear_selection_cards()
        self._selected_band = band_id
        self._selection_back_btn.show()
        band_display = self._model_manager.get_band_display_name(band_id)
        self._selection_title.setText(_tr("SettingsWindow.char_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.char_subtitle_with_band", band=band_display))
        configured_characters = {
            item["character"] for item in self._configured_models
            if item.get("character") != self._selected_list_character
        }

        col = 0
        row = 0
        card_idx = 0
        for char_key in self._model_manager.get_band_characters(band_id):
            costumes = self._model_manager.get_costumes(char_key)
            if not costumes:
                continue
            display = self._model_manager.get_display_name(char_key)
            image_path = self._model_manager.get_character_image_path(char_key)
            image_data = self._model_manager.get_character_image_data(char_key)
            card = CharacterCard(
                char_key, display, len(costumes), image_path,
                "green" if self._model_manager.has_advanced_roleplay(char_key) else "red",
                self._selection_grid_widget,
                image_data=image_data,
            )
            card.set_disabled_for_existing(char_key in configured_characters)
            card.char_selected.connect(self._on_char_selected)
            card.animate_in(delay_ms=card_idx * 80)
            self._char_grid.addWidget(card, row, col)
            self._selection_cards.append(card)
            col += 1
            card_idx += 1

    def _build_costume_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.costume_back"), page)
        back_btn.clicked.connect(self._go_back_to_chars)
        top_row.addWidget(back_btn)
        top_row.addStretch()

        self._costume_title = TitleLabel(_tr("SettingsWindow.costume_title"), page)
        top_row.addWidget(self._costume_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._costume_subtitle = SubtitleLabel("", page)
        layout.addWidget(self._costume_subtitle)
        self._costume_preview_hint = BodyLabel(_tr("SettingsWindow.costume_preview_hint"), page)
        self._costume_preview_hint.setWordWrap(True)
        layout.addWidget(self._costume_preview_hint)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._costume_list_widget = self._make_theme_widget(QWidget())
        self._costume_list = QVBoxLayout(self._costume_list_widget)
        self._costume_list.setSpacing(6)
        self._costume_list.setContentsMargins(0, 4, 0, 0)
        self._costume_list.addStretch()

        scroll.setWidget(self._costume_list_widget)
        layout.addWidget(scroll, 1)
        return page

    def _build_llm_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.llm_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.llm_subtitle"), page))
        layout.addWidget(subtitle)
        capability_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_capability_hint",
            default="提示：图片理解、联网搜索、MCP 和 Computer Use 等能力，只有在当前模型支持多模态输入或工具调用时才会实际生效。",
        ), page))
        layout.addWidget(capability_hint)

        profile_header = QHBoxLayout()
        profile_header.setContentsMargins(0, 0, 0, 0)
        profile_header.setSpacing(8)
        profile_label = BodyLabel(_tr("SettingsWindow.llm_api_profile", default="API 配置档案"), page)
        profile_header.addWidget(profile_label)
        self._llm_active_api_profile_label = BodyLabel("", page)
        self._llm_active_api_profile_label.setWordWrap(False)
        profile_header.addWidget(self._llm_active_api_profile_label)
        profile_header.addStretch()
        layout.addLayout(profile_header)
        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        self._llm_api_profile_combo = OpaqueDropDownComboBox(page)
        self._llm_api_profile_combo.setFixedHeight(36)
        self._llm_api_profile_combo.currentIndexChanged.connect(self._on_llm_api_profile_selected)
        profile_row.addWidget(self._llm_api_profile_combo, 1)

        self._llm_api_profile_name = FluentContextLineEdit(page)
        self._llm_api_profile_name.setPlaceholderText(_tr("SettingsWindow.llm_api_profile_name_placeholder", default="配置名称"))
        self._llm_api_profile_name.setFixedHeight(36)
        profile_row.addWidget(self._llm_api_profile_name, 1)

        save_profile_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_api_profile_save", default="保存配置"), page)
        save_profile_btn.setFixedHeight(36)
        save_profile_btn.clicked.connect(self._save_llm_api_profile)
        profile_row.addWidget(save_profile_btn)

        delete_profile_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.llm_api_profile_delete", default="删除"), page)
        delete_profile_btn.setFixedHeight(36)
        delete_profile_btn.clicked.connect(self._delete_llm_api_profile)
        profile_row.addWidget(delete_profile_btn)
        layout.addLayout(profile_row)

        api_url_label = BodyLabel(_tr("SettingsWindow.llm_api_url"), page)
        layout.addWidget(api_url_label)
        self._llm_api_url = FluentContextLineEdit(page)
        self._llm_api_url.setPlaceholderText(_tr("SettingsWindow.llm_api_url_placeholder"))
        self._llm_api_url.setFixedHeight(36)
        self._llm_api_url.textChanged.connect(lambda: self._on_llm_api_mode_changed(self._llm_api_mode.currentIndex()) if hasattr(self, "_llm_api_mode") else None)
        api_url_input_col = QVBoxLayout()
        api_url_input_col.setContentsMargins(0, 0, 0, 0)
        api_url_input_col.setSpacing(4)
        api_url_input_col.addWidget(self._llm_api_url)
        self._llm_api_url_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.llm_api_url_hint"), page))
        api_url_input_col.addWidget(self._llm_api_url_hint)
        layout.addLayout(api_url_input_col)

        api_key_label = BodyLabel(_tr("SettingsWindow.llm_api_key"), page)
        layout.addWidget(api_key_label)
        self._llm_api_key = FluentContextLineEdit(page)
        self._llm_api_key.setPlaceholderText(_tr("SettingsWindow.llm_api_key_placeholder"))
        self._llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key.setFixedHeight(36)
        layout.addWidget(self._llm_api_key)

        model_label = BodyLabel(_tr("SettingsWindow.llm_primary_model_id"), page)
        layout.addWidget(model_label)

        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self._llm_model_id = FluentContextLineEdit(page)
        self._llm_model_id.setPlaceholderText(_tr("SettingsWindow.llm_model_id_placeholder"))
        self._llm_model_id.setFixedHeight(36)
        model_row.addWidget(self._llm_model_id, 1)

        fetch_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.llm_fetch"), page)
        fetch_btn.setFixedHeight(36)
        fetch_btn.clicked.connect(lambda: self._fetch_models(self._llm_model_id))
        model_row.addWidget(fetch_btn)
        layout.addLayout(model_row)

        thinking_label = BodyLabel(_tr("SettingsWindow.llm_enable_thinking"), page)
        layout.addWidget(thinking_label)
        self._llm_enable_thinking = OpaqueDropDownComboBox(page)
        self._llm_enable_thinking.addItems([
            _tr("SettingsWindow.llm_enable_thinking_default"),
            _tr("SettingsWindow.llm_enable_thinking_on"),
            _tr("SettingsWindow.llm_enable_thinking_off"),
        ])
        self._llm_enable_thinking.setFixedHeight(36)
        self._llm_enable_thinking.setCurrentIndex(0)
        layout.addWidget(self._llm_enable_thinking)

        show_reasoning_row = QHBoxLayout()
        show_reasoning_row.setContentsMargins(0, 0, 0, 0)
        show_reasoning_label = BodyLabel(_tr("SettingsWindow.llm_show_reasoning"), page)
        self._llm_show_reasoning = SwitchButton(page)
        self._llm_show_reasoning.setChecked(True)
        show_reasoning_row.addWidget(show_reasoning_label)
        show_reasoning_row.addStretch()
        show_reasoning_row.addWidget(self._llm_show_reasoning)
        layout.addLayout(show_reasoning_row)

        (
            self._llm_primary_model_combo_label,
            self._llm_primary_model_scroll,
            self._llm_primary_model_list,
            self._llm_primary_model_list_layout,
        ) = self._create_llm_model_picker(page)
        layout.addWidget(self._llm_primary_model_combo_label)
        layout.addWidget(self._llm_primary_model_scroll)

        aux_api_url_label = BodyLabel(_tr("SettingsWindow.llm_aux_api_url", default="辅助模型 API 地址"), page)
        layout.addWidget(aux_api_url_label)
        self._llm_aux_api_url = FluentContextLineEdit(page)
        self._llm_aux_api_url.setPlaceholderText(_tr(
            "SettingsWindow.llm_aux_api_url_placeholder",
            default="留空则复用主模型 API 地址",
        ))
        self._llm_aux_api_url.setFixedHeight(36)
        layout.addWidget(self._llm_aux_api_url)

        aux_api_key_label = BodyLabel(_tr("SettingsWindow.llm_aux_api_key", default="辅助模型 API 密钥"), page)
        layout.addWidget(aux_api_key_label)
        self._llm_aux_api_key = FluentContextLineEdit(page)
        self._llm_aux_api_key.setPlaceholderText(_tr(
            "SettingsWindow.llm_aux_api_key_placeholder",
            default="留空则复用主模型 API 密钥",
        ))
        self._llm_aux_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_aux_api_key.setFixedHeight(36)
        layout.addWidget(self._llm_aux_api_key)

        aux_model_label = BodyLabel(_tr("SettingsWindow.llm_aux_model_id"), page)
        layout.addWidget(aux_model_label)
        self._llm_aux_model_id = FluentContextLineEdit(page)
        self._llm_aux_model_id.setPlaceholderText(_tr("SettingsWindow.llm_aux_model_id_placeholder"))
        self._llm_aux_model_id.setFixedHeight(36)
        aux_model_row = QHBoxLayout()
        aux_model_row.setSpacing(8)
        aux_model_row.addWidget(self._llm_aux_model_id, 1)
        aux_fetch_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.llm_fetch"), page)
        aux_fetch_btn.setFixedHeight(36)
        aux_fetch_btn.clicked.connect(lambda: self._fetch_models(self._llm_aux_model_id))
        aux_model_row.addWidget(aux_fetch_btn)
        layout.addLayout(aux_model_row)
        (
            self._llm_aux_model_combo_label,
            self._llm_aux_model_scroll,
            self._llm_aux_model_list,
            self._llm_aux_model_list_layout,
        ) = self._create_llm_model_picker(page)
        layout.addWidget(self._llm_aux_model_combo_label)
        layout.addWidget(self._llm_aux_model_scroll)

        aux_thinking_label = BodyLabel(_tr("SettingsWindow.llm_aux_enable_thinking"), page)
        layout.addWidget(aux_thinking_label)
        self._llm_aux_enable_thinking = OpaqueDropDownComboBox(page)
        self._llm_aux_enable_thinking.addItems([
            _tr("SettingsWindow.llm_enable_thinking_default"),
            _tr("SettingsWindow.llm_enable_thinking_on"),
            _tr("SettingsWindow.llm_enable_thinking_off"),
        ])
        self._llm_aux_enable_thinking.setFixedHeight(36)
        self._llm_aux_enable_thinking.setCurrentIndex(0)
        layout.addWidget(self._llm_aux_enable_thinking)

        aux_vision_row = QHBoxLayout()
        aux_vision_row.setContentsMargins(0, 0, 0, 0)
        aux_vision_label = BodyLabel(_tr("SettingsWindow.llm_aux_vision_fallback_enabled", default="辅助模型视觉解析"), page)
        self._llm_aux_vision_fallback_enabled = SwitchButton(page)
        aux_vision_row.addWidget(aux_vision_label)
        aux_vision_row.addStretch()
        aux_vision_row.addWidget(self._llm_aux_vision_fallback_enabled)
        layout.addLayout(aux_vision_row)

        api_mode_label = BodyLabel(_tr("SettingsWindow.llm_api_mode", default="API 模式"), page)
        layout.addWidget(api_mode_label)
        self._llm_api_mode = OpaqueDropDownComboBox(page)
        self._llm_api_mode.addItem(_tr("SettingsWindow.llm_api_mode_chat", default="兼容 Chat Completions"), userData="chat_completions")
        self._llm_api_mode.addItem(_tr("SettingsWindow.llm_api_mode_responses", default="OpenAI Responses"), userData="responses")
        self._llm_api_mode.setFixedHeight(36)
        self._llm_api_mode.currentIndexChanged.connect(self._on_llm_api_mode_changed)
        layout.addWidget(self._llm_api_mode)

        web_search_row = QHBoxLayout()
        web_search_row.setContentsMargins(0, 0, 0, 0)
        web_search_label = BodyLabel(_tr("SettingsWindow.llm_web_search_enabled", default="联网搜索"), page)
        self._llm_web_search_enabled = SwitchButton(page)
        self._llm_web_search_enabled.checkedChanged.connect(self._on_llm_web_search_enabled_changed)
        web_search_row.addWidget(web_search_label)
        web_search_row.addStretch()
        web_search_row.addWidget(self._llm_web_search_enabled)
        layout.addLayout(web_search_row)

        web_search_engine_label = BodyLabel(_tr("SettingsWindow.llm_web_search_engine", default="搜索引擎"), page)
        layout.addWidget(web_search_engine_label)
        self._llm_web_search_engine = OpaqueDropDownComboBox(page)
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_bing", default="Bing"), userData="bing")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_bing_cn", default="Bing CN"), userData="bing_cn")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_google", default="Google"), userData="google")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_duckduckgo", default="DuckDuckGo"), userData="duckduckgo")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_baidu", default="Baidu"), userData="baidu")
        self._llm_web_search_engine.setFixedHeight(36)
        layout.addWidget(self._llm_web_search_engine)

        web_search_sources_row = QHBoxLayout()
        web_search_sources_row.setContentsMargins(0, 0, 0, 0)
        sources_label = BodyLabel(_tr("SettingsWindow.llm_web_search_show_sources", default="显示联网来源"), page)
        self._llm_web_search_show_sources = SwitchButton(page)
        web_search_sources_row.addSpacing(16)
        web_search_sources_row.addWidget(sources_label)
        web_search_sources_row.addStretch()
        web_search_sources_row.addWidget(self._llm_web_search_show_sources)
        layout.addLayout(web_search_sources_row)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.llm_chat_commands_title", default="LLM 对话命令"), page))
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_chat_commands_hint",
            default="@stop / @停止 / @中断：强制中断当前模型输出。好感度、记忆和关系数值命令在“好感度 / 记忆”页说明。",
        ), page)))

        custom_system_label = BodyLabel(_tr(
            "SettingsWindow.llm_custom_system_prompt",
            default="最高优先级系统提示词",
        ), page)
        layout.addWidget(custom_system_label)
        self._llm_custom_system_prompt = FluentContextTextEdit(page)
        self._llm_custom_system_prompt.setPlaceholderText(_tr(
            "SettingsWindow.llm_custom_system_prompt_placeholder",
            default="留空则不启用。这里的内容会在每次聊天请求中置于角色设定之前。",
        ))
        self._llm_custom_system_prompt.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._llm_custom_system_prompt.setMinimumHeight(72)
        self._llm_custom_system_prompt.setMaximumHeight(120)
        layout.addWidget(self._llm_custom_system_prompt)
        custom_system_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_custom_system_prompt_hint",
            default="这段指令优先级高于角色档案、长期记忆和会话历史；建议只写全局行为约束，避免与角色身份或动作标签规则冲突。",
        ), page))
        layout.addWidget(custom_system_hint)

        data_title = SubtitleLabel(_tr("SettingsWindow.chat_data_title"), page)
        layout.addWidget(data_title)

        data_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.chat_data_hint"), page))
        layout.addWidget(data_hint)

        data_btn_row = QHBoxLayout()
        data_btn_row.setSpacing(8)

        export_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.chat_data_export"), page)
        export_btn.setFixedHeight(36)
        export_btn.clicked.connect(self._export_chat_database)
        data_btn_row.addWidget(export_btn)

        import_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.chat_data_import"), page)
        import_btn.setFixedHeight(36)
        import_btn.clicked.connect(self._import_chat_database)
        data_btn_row.addWidget(import_btn)

        data_btn_row.addStretch()
        layout.addLayout(data_btn_row)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        test_btn = PushButton(FluentIcon.WIFI, _tr("SettingsWindow.llm_test"), page)
        test_btn.setFixedHeight(36)
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)

        save_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.llm_apply_current", default="应用当前配置"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_llm_config)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_llm_config()
        self._style_llm_inputs()
        qconfig.themeChanged.connect(self._style_llm_inputs)

        return page

    def _create_llm_model_picker(self, parent: QWidget):
        label = BodyLabel(_tr("SettingsWindow.llm_available_models"), parent)
        label.hide()

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(80)
        scroll.setMaximumHeight(220)
        scroll.hide()

        list_widget = QWidget(parent)
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 4, 0, 4)
        list_layout.setSpacing(2)
        scroll.setWidget(list_widget)
        return label, scroll, list_widget, list_layout

    def _build_tts_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.tts_title", "聊天 TTS"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.tts_subtitle",
            "配置聊天回复的语音合成、参考音频和非中文 TTS 翻译。",
        ), page))
        layout.addWidget(subtitle)

        tts_enable_row = QHBoxLayout()
        tts_enable_row.setContentsMargins(0, 0, 0, 0)
        tts_enable_label = BodyLabel(_tr("SettingsWindow.tts_enabled", "启用聊天语音合成"), page)
        self._tts_enabled = SwitchButton(page)
        tts_enable_row.addWidget(tts_enable_label)
        tts_enable_row.addStretch()
        tts_enable_row.addWidget(self._tts_enabled)
        layout.addLayout(tts_enable_row)

        tts_api_label = BodyLabel(_tr("SettingsWindow.tts_api_url", "TTS API 地址"), page)
        layout.addWidget(tts_api_label)
        self._tts_api_url = FluentContextLineEdit(page)
        self._tts_api_url.setPlaceholderText("http://127.0.0.1:9880/")
        self._tts_api_url.setFixedHeight(36)
        layout.addWidget(self._tts_api_url)

        tts_lang_label = BodyLabel(_tr("SettingsWindow.tts_language", "TTS 文本语言"), page)
        layout.addWidget(tts_lang_label)
        self._tts_language = OpaqueDropDownComboBox(page)
        self._tts_language.addItem(_tr("SettingsWindow.tts_language_chinese", "中文"), userData="Chinese")
        self._tts_language.addItem(_tr("SettingsWindow.tts_language_japanese", "日语"), userData="Japanese")
        self._tts_language.addItem(_tr("SettingsWindow.tts_language_english", "英语"), userData="English")
        self._tts_language.setFixedHeight(36)
        layout.addWidget(self._tts_language)

        tts_ref_label = BodyLabel(_tr("SettingsWindow.tts_reference", "参考音频角色"), page)
        layout.addWidget(tts_ref_label)
        self._tts_reference_character = OpaqueDropDownComboBox(page)
        self._tts_reference_character.addItem(_tr("SettingsWindow.tts_reference_auto", "跟随聊天角色"), userData="")
        ref_dir = app_base_dir() / "audio_reference"
        ref_paths = []
        if ref_dir.exists():
            for suffix in ("*.mp3", "*.wav", "*.flac", "*.ogg", "*.m4a"):
                ref_paths.extend(ref_dir.glob(suffix))
        seen_refs = set()
        for audio_path in sorted(ref_paths, key=lambda path: path.stem):
            key = audio_path.stem
            if key in seen_refs:
                continue
            seen_refs.add(key)
            display = self._model_manager.get_display_name(key) if key in self._model_manager.characters else key
            self._tts_reference_character.addItem(display, userData=key)
        self._tts_reference_character.setFixedHeight(36)
        layout.addWidget(self._tts_reference_character)

        tts_temperature_label = BodyLabel(_tr("SettingsWindow.tts_temperature", "TTS 温度参数"), page)
        layout.addWidget(tts_temperature_label)
        self._tts_temperature = FluentContextLineEdit(page)
        self._tts_temperature.setPlaceholderText("0.9")
        self._tts_temperature.setFixedHeight(36)
        temp_validator = QDoubleValidator(0.01, 2.0, 2, self._tts_temperature)
        temp_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self._tts_temperature.setValidator(temp_validator)
        layout.addWidget(self._tts_temperature)

        tts_stream_row = QHBoxLayout()
        tts_stream_row.setContentsMargins(0, 0, 0, 0)
        tts_stream_label = BodyLabel(_tr("SettingsWindow.tts_streaming", "启用 TTS 流式请求"), page)
        self._tts_streaming = SwitchButton(page)
        self._tts_streaming.setChecked(True)
        tts_stream_row.addWidget(tts_stream_label)
        tts_stream_row.addStretch()
        tts_stream_row.addWidget(self._tts_streaming)
        layout.addLayout(tts_stream_row)

        tts_translate_row = QHBoxLayout()
        tts_translate_row.setContentsMargins(0, 0, 0, 0)
        tts_translate_label = BodyLabel(_tr("SettingsWindow.tts_translate_to_selected_language", "非中文 TTS 时用快速模型逐段翻译到所选语言"), page)
        self._tts_translate_to_selected_language = SwitchButton(page)
        self._tts_translate_to_selected_language.setChecked(True)
        tts_translate_row.addWidget(tts_translate_label)
        tts_translate_row.addStretch()
        tts_translate_row.addWidget(self._tts_translate_to_selected_language)
        layout.addLayout(tts_translate_row)

        tts_test_label = BodyLabel(_tr("SettingsWindow.tts_test_text", default="测试文本"), page)
        layout.addWidget(tts_test_label)
        self._tts_test_text = FluentContextTextEdit(page)
        self._tts_test_text.setPlaceholderText(_tr(
            "SettingsWindow.tts_test_text_placeholder",
            default="留空则使用默认测试文案。",
        ))
        self._tts_test_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._tts_test_text.setFixedHeight(92)
        layout.addWidget(self._tts_test_text)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._tts_test_button = PushButton(FluentIcon.PLAY, _tr("SettingsWindow.tts_test_button", default="测试播放"), page)
        self._tts_test_button.setFixedHeight(36)
        self._tts_test_button.setEnabled(_SETTINGS_TTS_AVAILABLE)
        self._tts_test_button.clicked.connect(self._test_tts)
        btn_row.addWidget(self._tts_test_button)
        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_tts_config)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_tts_config()
        self._style_tts_inputs()
        qconfig.themeChanged.connect(self._style_tts_inputs)

        return page

    def _build_pov_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("povPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = TitleLabel(_tr("SettingsWindow.pov_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.pov_subtitle"), page))
        layout.addWidget(subtitle)

        profile_title = SubtitleLabel(_tr("SettingsWindow.llm_profile"), page)
        layout.addWidget(profile_title)

        name_label = BodyLabel(_tr("SettingsWindow.llm_display_name"), page)
        layout.addWidget(name_label)
        self._user_name = FluentContextLineEdit(page)
        self._user_name.setPlaceholderText(_tr("SettingsWindow.llm_display_name_placeholder"))
        self._user_name.setFixedHeight(36)
        self._user_name.textChanged.connect(lambda _text: self._update_user_avatar_preview())
        layout.addWidget(self._user_name)

        image_label = BodyLabel(_tr("SettingsWindow.llm_avatar_image"), page)
        layout.addWidget(image_label)
        avatar_row = QHBoxLayout()
        avatar_row.setSpacing(10)
        self._user_avatar_preview = QLabel(page)
        self._user_avatar_preview.setFixedSize(44, 44)
        self._user_avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_row.addWidget(self._user_avatar_preview)
        choose_avatar_btn = PushButton(FluentIcon.PHOTO, _tr("SettingsWindow.llm_avatar_choose"), page)
        choose_avatar_btn.setFixedHeight(36)
        choose_avatar_btn.clicked.connect(self._choose_user_avatar)
        avatar_row.addWidget(choose_avatar_btn)
        self._user_avatar_reset_btn = PushButton(FluentIcon.RETURN, _tr("SettingsWindow.llm_avatar_reset"), page)
        self._user_avatar_reset_btn.setFixedHeight(36)
        self._user_avatar_reset_btn.clicked.connect(self._reset_user_avatar)
        avatar_row.addWidget(self._user_avatar_reset_btn)
        avatar_row.addStretch()
        layout.addLayout(avatar_row)

        avatar_label = BodyLabel(_tr("SettingsWindow.llm_avatar_color"), page)
        layout.addWidget(avatar_label)
        self._avatar_colors = [
            (BANDORI_PRIMARY, "Bandori"),
            ("#e91e63", _tr("color.pink")),
            ("#9c27b0", _tr("color.purple")),
            ("#4caf50", _tr("color.green")),
            ("#ff9800", _tr("color.orange")),
            ("#f44336", _tr("color.red")),
            ("#00bcd4", _tr("color.cyan")),
            ("#607d8b", _tr("color.grey")),
        ]
        colors_row = QHBoxLayout()
        colors_row.setSpacing(6)
        self._avatar_color_btns: list[QPushButton] = []
        for color_hex, color_name in self._avatar_colors:
            btn = QPushButton("", page)
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color_name)
            btn.setProperty("avatar_color", color_hex)
            btn.clicked.connect(lambda checked, b=btn: self._on_avatar_color_clicked(b))
            self._avatar_color_btns.append(btn)
            colors_row.addWidget(btn)
        colors_row.addStretch()
        layout.addLayout(colors_row)

        mode_label = BodyLabel(_tr("SettingsWindow.pov_mode"), page)
        layout.addWidget(mode_label)
        self._pov_mode = OpaqueDropDownComboBox(page)
        self._pov_mode.addItem(_tr("SettingsWindow.pov_mode_off"), userData="off")
        self._pov_mode.addItem(_tr("SettingsWindow.pov_mode_custom"), userData="custom")
        self._pov_mode.addItem(_tr("SettingsWindow.pov_mode_role"), userData="role")
        self._pov_mode.setFixedHeight(36)
        self._pov_mode.currentIndexChanged.connect(self._on_pov_mode_changed)
        layout.addWidget(self._pov_mode)

        prompt_label = BodyLabel(_tr("SettingsWindow.pov_custom_prompt"), page)
        layout.addWidget(prompt_label)
        self._pov_custom_prompt = FluentContextTextEdit(page)
        self._pov_custom_prompt.setPlaceholderText(_tr("SettingsWindow.pov_custom_prompt_placeholder"))
        self._pov_custom_prompt.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._pov_custom_prompt.setMinimumHeight(64)
        self._pov_custom_prompt.setMaximumHeight(96)
        layout.addWidget(self._pov_custom_prompt)

        persona_label = BodyLabel(_tr("SettingsWindow.pov_saved_personas"), page)
        layout.addWidget(persona_label)
        persona_row = QHBoxLayout()
        persona_row.setSpacing(8)
        self._pov_persona_combo = OpaqueDropDownComboBox(page)
        self._pov_persona_combo.setFixedHeight(36)
        self._pov_persona_combo.currentIndexChanged.connect(self._on_pov_persona_selected)
        persona_row.addWidget(self._pov_persona_combo, 1)
        save_persona_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.pov_save_persona"), page)
        save_persona_btn.setFixedHeight(36)
        save_persona_btn.clicked.connect(self._save_current_pov_persona)
        persona_row.addWidget(save_persona_btn)
        delete_persona_btn = PushButton(FluentIcon.CLOSE, _tr("SettingsWindow.pov_delete_persona"), page)
        delete_persona_btn.setFixedHeight(36)
        delete_persona_btn.clicked.connect(self._delete_current_pov_persona)
        persona_row.addWidget(delete_persona_btn)
        layout.addLayout(persona_row)

        role_label = BodyLabel(_tr("SettingsWindow.pov_role_character"), page)
        layout.addWidget(role_label)
        self._pov_role_character = OpaqueDropDownComboBox(page)
        self._pov_role_character.setFixedHeight(36)
        for char_key in self._model_manager.characters:
            self._pov_role_character.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
        self._pov_role_character.currentIndexChanged.connect(self._sync_role_display_name)
        layout.addWidget(self._pov_role_character)

        pov_hint_panel = QWidget(page)
        pov_hint_panel.setObjectName("povHintPanel")
        pov_hint_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pov_hint_layout = QVBoxLayout(pov_hint_panel)
        pov_hint_layout.setContentsMargins(14, 12, 14, 12)
        pov_hint_layout.setSpacing(0)
        pov_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.pov_hint"), pov_hint_panel))
        pov_hint.setObjectName("povHintText")
        pov_hint.setMinimumHeight(52)
        pov_hint_layout.addWidget(pov_hint)
        layout.addWidget(pov_hint_panel)

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(lambda: self._save_llm_config("pov"))
        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self._style_pov_page(page)
        qconfig.themeChanged.connect(lambda: self._style_pov_page(page))

        return page

    def _style_pov_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        text = "#d5dae5" if dark else "#4b5565"
        page.setStyleSheet(f"""
            QWidget#povPage {{
                background: {page_bg};
            }}
            QWidget#povHintPanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 8px;
            }}
            BodyLabel#povHintText {{
                color: {text};
                font-size: 13px;
                line-height: 1.35em;
            }}
        """)

    def _build_relationship_guide_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("relationshipGuidePage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = TitleLabel(_tr("SettingsWindow.relationship_guide_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.relationship_guide_subtitle"), page))
        layout.addWidget(subtitle)

        for title_key, body_key in (
            ("SettingsWindow.relationship_guide_affection_title", "SettingsWindow.relationship_guide_affection_body"),
            ("SettingsWindow.relationship_guide_trust_title", "SettingsWindow.relationship_guide_trust_body"),
            ("SettingsWindow.relationship_guide_familiarity_title", "SettingsWindow.relationship_guide_familiarity_body"),
            ("SettingsWindow.relationship_guide_mood_title", "SettingsWindow.relationship_guide_mood_body"),
            ("SettingsWindow.relationship_guide_memory_title", "SettingsWindow.relationship_guide_memory_body"),
            ("SettingsWindow.relationship_guide_pov_title", "SettingsWindow.relationship_guide_pov_body"),
            ("SettingsWindow.relationship_guide_commands_title", "SettingsWindow.relationship_guide_commands_body"),
        ):
            panel = QWidget(page)
            panel.setObjectName("relationshipGuidePanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(16, 14, 16, 14)
            panel_layout.setSpacing(6)
            section_title = StrongBodyLabel(_tr(title_key), panel)
            section_body = BodyLabel(_tr(body_key), panel)
            section_body.setWordWrap(True)
            section_body.setObjectName("relationshipGuideText")
            panel_layout.addWidget(section_title)
            panel_layout.addWidget(section_body)
            layout.addWidget(panel)

        layout.addStretch()
        self._style_relationship_guide_page(page)
        qconfig.themeChanged.connect(lambda: self._style_relationship_guide_page(page))
        return page

    def _style_relationship_guide_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f3f3f6" if dark else "#202126"
        page.setStyleSheet(f"""
            QWidget#relationshipGuidePage {{
                background: {page_bg};
            }}
            QWidget#relationshipGuidePanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 10px;
            }}
            BodyLabel#relationshipGuideText {{
                color: {text};
                font-size: 13px;
                line-height: 1.35em;
            }}
            SubtitleLabel {{
                color: {muted};
            }}
        """)

    def _build_memory_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("memoryPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = TitleLabel(_tr("SettingsWindow.memory_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.memory_subtitle"), page))
        layout.addWidget(subtitle)

        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(10)
        selector_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_character"), page))
        self._memory_character_combo = OpaqueDropDownComboBox(page)
        self._memory_character_combo.setFixedHeight(36)
        selected_character = self._current_char or self._selected_list_character
        selected_index = 0
        for index, char_key in enumerate(self._model_manager.characters):
            self._memory_character_combo.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
            if char_key == selected_character:
                selected_index = index
        self._memory_character_combo.setCurrentIndex(selected_index)
        self._memory_character_combo.currentIndexChanged.connect(lambda _i: self._refresh_memory_page())
        selector_row.addWidget(self._memory_character_combo, 1)
        self._memory_user_label = BodyLabel("", page)
        self._memory_user_label.setMinimumWidth(0)
        selector_row.addWidget(self._memory_user_label, 1)
        layout.addLayout(selector_row)

        status_panel = QWidget(page)
        status_panel.setObjectName("memoryStatusPanel")
        status_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(8)
        self._memory_affection_value = StrongBodyLabel("", status_panel)
        self._memory_trust_value = StrongBodyLabel("", status_panel)
        self._memory_familiarity_value = StrongBodyLabel("", status_panel)
        self._memory_mood_value = StrongBodyLabel("", status_panel)
        self._memory_updated_value = BodyLabel("", status_panel)
        for column, (label_key, value_label) in enumerate((
            ("SettingsWindow.memory_affection", self._memory_affection_value),
            ("SettingsWindow.memory_trust", self._memory_trust_value),
            ("SettingsWindow.memory_familiarity", self._memory_familiarity_value),
            ("SettingsWindow.memory_mood", self._memory_mood_value),
        )):
            caption = BodyLabel(_tr(label_key), status_panel)
            caption.setObjectName("memoryStatCaption")
            status_layout.addWidget(caption, 0, column)
            status_layout.addWidget(value_label, 1, column)
        self._memory_updated_value.setObjectName("memoryUpdated")
        status_layout.addWidget(self._memory_updated_value, 2, 0, 1, 4)
        layout.addWidget(status_panel)

        memory_title = SubtitleLabel(_tr("SettingsWindow.memory_editor_title"), page)
        layout.addWidget(memory_title)
        memory_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.memory_editor_hint"), page))
        memory_hint.setObjectName("memoryHint")
        layout.addWidget(memory_hint)

        self._memory_item_combo = OpaqueDropDownComboBox(page)
        self._memory_item_combo.setFixedHeight(36)
        self._memory_item_combo.currentIndexChanged.connect(self._on_memory_item_selected)
        layout.addWidget(self._memory_item_combo)

        edit_row = QHBoxLayout()
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.setSpacing(10)
        edit_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_kind"), page))
        self._memory_kind_combo = OpaqueDropDownComboBox(page)
        self._memory_kind_combo.setFixedHeight(36)
        for kind in MEMORY_KIND_ORDER:
            self._memory_kind_combo.addItem(self._memory_kind_label(kind), userData=kind)
        edit_row.addWidget(self._memory_kind_combo, 1)
        edit_row.addSpacing(8)
        edit_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_importance"), page))
        self._memory_importance_slider = Slider(Qt.Orientation.Horizontal, page)
        self._memory_importance_slider.setRange(1, 100)
        self._memory_importance_slider.setSingleStep(1)
        self._memory_importance_slider.setValue(70)
        self._memory_importance_value = BodyLabel("70", page)
        self._memory_importance_slider.valueChanged.connect(
            lambda v: self._memory_importance_value.setText(str(v))
        )
        edit_row.addWidget(self._memory_importance_slider, 1)
        edit_row.addWidget(self._memory_importance_value)
        layout.addLayout(edit_row)

        self._memory_content = FluentContextTextEdit(page)
        self._memory_content.setPlaceholderText(_tr("SettingsWindow.memory_content_placeholder"))
        self._memory_content.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._memory_content.setMinimumHeight(96)
        self._memory_content.setMaximumHeight(150)
        layout.addWidget(self._memory_content)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        new_btn = PushButton(FluentIcon.ADD, _tr("SettingsWindow.memory_new"), page)
        new_btn.setFixedHeight(36)
        new_btn.clicked.connect(self._start_new_memory)
        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.memory_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_memory_item)
        self._memory_delete_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.memory_delete"), page)
        self._memory_delete_btn.setFixedHeight(36)
        self._memory_delete_btn.clicked.connect(self._delete_memory_item)
        refresh_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.memory_refresh"), page)
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(lambda: self._refresh_memory_page())
        btn_row.addWidget(new_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(self._memory_delete_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        command_panel = QWidget(page)
        command_panel.setObjectName("memoryCommandPanel")
        command_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        command_layout = QVBoxLayout(command_panel)
        command_layout.setContentsMargins(16, 14, 16, 14)
        command_layout.setSpacing(8)
        command_layout.addWidget(SubtitleLabel(_tr("SettingsWindow.memory_commands_title"), command_panel))
        for key in (
            "SettingsWindow.memory_command_status",
            "SettingsWindow.memory_command_remember",
            "SettingsWindow.memory_command_forget",
            "SettingsWindow.memory_command_affection",
            "SettingsWindow.memory_command_trust",
            "SettingsWindow.memory_command_familiarity",
            "SettingsWindow.memory_command_mood",
        ):
            line = BodyLabel(_tr(key), command_panel)
            line.setWordWrap(True)
            line.setObjectName("memoryCommandLine")
            command_layout.addWidget(line)
        layout.addWidget(command_panel)

        layout.addStretch()
        self._style_memory_page(page)
        qconfig.themeChanged.connect(lambda: self._style_memory_page(page))
        self._refresh_memory_page()
        return page

    def _memory_database(self) -> DatabaseManager:
        if self._memory_db is None:
            self._memory_db = DatabaseManager()
        return self._memory_db

    @staticmethod
    def _memory_kind_label(kind: str) -> str:
        return _tr(
            f"SettingsWindow.memory_kind_{kind}",
            default=MEMORY_KIND_LABELS.get(kind, kind or "note"),
        )

    def _selected_memory_character(self) -> str:
        if not hasattr(self, "_memory_character_combo"):
            return self._current_char or (self._model_manager.characters[0] if self._model_manager.characters else "")
        character = self._memory_character_combo.itemData(self._memory_character_combo.currentIndex())
        return character or self._current_char or (self._model_manager.characters[0] if self._model_manager.characters else "")

    def _memory_page_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_memory_character_combo",
                "_memory_user_label",
                "_memory_affection_value",
                "_memory_trust_value",
                "_memory_familiarity_value",
                "_memory_mood_value",
                "_memory_updated_value",
                "_memory_item_combo",
                "_memory_kind_combo",
                "_memory_importance_slider",
                "_memory_content",
                "_memory_delete_btn",
            )
        )

    def _memory_item_title(self, memory: dict) -> str:
        kind = self._memory_kind_label(memory.get("kind", "note"))
        content = str(memory.get("content", "") or "").replace("\n", " ").strip()
        if len(content) > 56:
            content = content[:56].rstrip() + "..."
        return f"{kind} - {content or _tr('SettingsWindow.memory_empty_content')}"

    def _memory_user_display(self, user_key: str) -> str:
        role_character = role_character_from_user_key(user_key)
        if role_character:
            role_name = self._model_manager.get_display_name(role_character)
            return _tr("Relationship.role_user_display", role=role_name)
        return display_user_name(user_key)

    def _set_memory_kind(self, kind: str):
        for index in range(self._memory_kind_combo.count()):
            if self._memory_kind_combo.itemData(index) == kind:
                self._memory_kind_combo.setCurrentIndex(index)
                return
        self._memory_kind_combo.setCurrentIndex(0)

    def _refresh_memory_page(self, prefer_memory_id: int | None = None):
        if not self._memory_page_ready():
            return
        character = self._selected_memory_character()
        if not character:
            return
        db = self._memory_database()
        user_key = user_key_from_config(self._cfg)
        user_display = self._memory_user_display(user_key) or _tr("SettingsWindow.memory_default_user")
        self._memory_user_label.setText(_tr("SettingsWindow.memory_current_user", display=user_display))

        state = db.get_relationship_state(character, user_key)
        self._memory_affection_value.setText(
            _tr(
                "SettingsWindow.memory_affection_value",
                value=state["affection"],
                label=affection_label(state["affection"]),
            )
        )
        self._memory_trust_value.setText(_tr("SettingsWindow.memory_score_value", value=state["trust"]))
        self._memory_familiarity_value.setText(_tr("SettingsWindow.memory_score_value", value=state["familiarity"]))
        self._memory_mood_value.setText(
            _tr(
                "SettingsWindow.memory_mood_value",
                mood=mood_label(state["mood"]),
                value=state["mood_intensity"],
            )
        )
        updated_at = state.get("updated_at") or _tr("SettingsWindow.memory_never_updated")
        self._memory_updated_value.setText(_tr("SettingsWindow.memory_updated_at", time=updated_at))

        self._memory_items = db.get_character_memories(character, user_key, limit=100)
        target_id = self._selected_memory_id if prefer_memory_id is None else int(prefer_memory_id or 0)
        selected_index = 0
        self._memory_item_combo.blockSignals(True)
        self._memory_item_combo.clear()
        self._memory_item_combo.addItem(_tr("SettingsWindow.memory_new_item"), userData=0)
        for memory in self._memory_items:
            self._memory_item_combo.addItem(self._memory_item_title(memory), userData=memory["id"])
            if memory["id"] == target_id:
                selected_index = self._memory_item_combo.count() - 1
        self._memory_item_combo.setCurrentIndex(selected_index)
        self._memory_item_combo.blockSignals(False)
        self._on_memory_item_selected(selected_index)

    def _on_memory_item_selected(self, index: int):
        if not self._memory_page_ready():
            return
        memory_id = int(self._memory_item_combo.itemData(index) or 0)
        self._selected_memory_id = memory_id
        memory = next((item for item in self._memory_items if item.get("id") == memory_id), None)
        if memory:
            self._set_memory_kind(memory.get("kind", "note"))
            self._memory_importance_slider.setValue(max(1, min(100, int(memory.get("importance") or 50))))
            self._memory_content.setPlainText(memory.get("content", "") or "")
            self._memory_delete_btn.setEnabled(True)
            return
        self._set_memory_kind("profile")
        self._memory_importance_slider.setValue(70)
        self._memory_content.clear()
        self._memory_delete_btn.setEnabled(False)

    def _start_new_memory(self):
        if not self._memory_page_ready():
            return
        self._memory_item_combo.setCurrentIndex(0)
        self._memory_content.setFocus()

    def _save_memory_item(self):
        if not self._memory_page_ready():
            return
        content = self._memory_content.toPlainText().strip()
        if not content:
            InfoBar.warning(
                _tr("SettingsWindow.memory_empty_title"),
                _tr("SettingsWindow.memory_empty_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        character = self._selected_memory_character()
        user_key = user_key_from_config(self._cfg)
        kind = self._memory_kind_combo.itemData(self._memory_kind_combo.currentIndex()) or "note"
        importance = self._memory_importance_slider.value()
        try:
            if self._selected_memory_id:
                saved = self._memory_database().update_character_memory(
                    self._selected_memory_id,
                    character,
                    user_key,
                    kind,
                    content,
                    importance,
                )
                memory_id = self._selected_memory_id if saved else 0
            else:
                memory_id = 0
            if not memory_id:
                memory_id = self._memory_database().add_character_memory(
                    character,
                    user_key,
                    kind,
                    content,
                    importance,
                )
            self._refresh_memory_page(memory_id)
            InfoBar.success(
                _tr("SettingsWindow.memory_saved_title"),
                _tr("SettingsWindow.memory_saved_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.memory_failed_title"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _delete_memory_item(self):
        if not self._memory_page_ready() or not self._selected_memory_id:
            return
        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.memory_delete_confirm_title"),
            _tr("SettingsWindow.memory_delete_confirm_content"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        character = self._selected_memory_character()
        user_key = user_key_from_config(self._cfg)
        try:
            self._memory_database().delete_character_memory(self._selected_memory_id, character, user_key)
            self._selected_memory_id = 0
            self._refresh_memory_page(0)
            InfoBar.success(
                _tr("SettingsWindow.memory_deleted_title"),
                _tr("SettingsWindow.memory_deleted_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.memory_failed_title"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _style_memory_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f3f3f6" if dark else "#202126"
        input_bg = "#282828" if dark else "#ffffff"
        input_border = "#505050" if dark else "#d0d0d0"
        page.setStyleSheet(f"""
            QWidget#memoryPage {{
                background: {page_bg};
            }}
            QWidget#memoryStatusPanel,
            QWidget#memoryCommandPanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 12px;
            }}
            BodyLabel#memoryStatCaption,
            BodyLabel#memoryUpdated,
            BodyLabel#memoryHint {{
                color: {muted};
                font-size: 13px;
            }}
            BodyLabel#memoryCommandLine {{
                color: {text};
                font-size: 13px;
            }}
            QTextEdit {{
                background: {input_bg};
                color: {text};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
        """)

    def _build_compact_window_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.compact_window_title"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr("SettingsWindow.compact_window_subtitle"), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        enabled_row = QHBoxLayout()
        enabled_row.setContentsMargins(0, 0, 0, 0)
        enabled_label = BodyLabel(_tr("SettingsWindow.compact_ai_window"), page)
        self._compact_ai_window_enabled = SwitchButton(page)
        enabled_row.addWidget(enabled_label)
        enabled_row.addStretch()
        enabled_row.addWidget(self._compact_ai_window_enabled)
        layout.addLayout(enabled_row)

        ai_event_row = QHBoxLayout()
        ai_event_row.setContentsMargins(0, 0, 0, 0)
        ai_event_label = BodyLabel(_tr("SettingsWindow.ai_event_overlay"), page)
        self._ai_event_overlay_enabled = SwitchButton(page)
        ai_event_row.addWidget(ai_event_label)
        ai_event_row.addStretch()
        ai_event_row.addWidget(self._ai_event_overlay_enabled)
        layout.addLayout(ai_event_row)

        self._compact_hint_labels = []

        ai_event_hint = BodyLabel(_tr("SettingsWindow.ai_event_overlay_hint"), page)
        ai_event_hint.setWordWrap(True)
        self._compact_hint_labels.append(ai_event_hint)
        layout.addWidget(ai_event_hint)

        port_row = QHBoxLayout()
        port_row.setContentsMargins(0, 0, 0, 0)
        self._ai_status_port_enabled = SwitchButton(page)
        port_label = BodyLabel(_tr("SettingsWindow.ai_status_port"), page)
        port_row.addWidget(port_label)
        port_row.addStretch()
        port_row.addWidget(self._ai_status_port_enabled)
        layout.addLayout(port_row)

        port_input_row = QHBoxLayout()
        port_input_row.setContentsMargins(0, 0, 0, 0)
        port_input_row.setSpacing(8)
        self._ai_status_port_input = LineEdit(page)
        self._ai_status_port_input.setFixedWidth(120)
        self._ai_status_port_input.setFixedHeight(36)
        self._ai_status_port_input.setValidator(QIntValidator(1024, 65535, self))
        self._ai_status_port_input.setPlaceholderText("38472")
        token_label = BodyLabel(_tr("SettingsWindow.ai_status_token"), page)
        self._ai_status_token_input = LineEdit(page)
        self._ai_status_token_input.setFixedHeight(36)
        self._ai_status_token_input.setPlaceholderText(_tr("SettingsWindow.ai_status_token_placeholder"))
        port_input_row.addWidget(BodyLabel(_tr("SettingsWindow.ai_status_port_number"), page))
        port_input_row.addWidget(self._ai_status_port_input)
        port_input_row.addSpacing(12)
        port_input_row.addWidget(token_label)
        port_input_row.addWidget(self._ai_status_token_input, 1)
        layout.addLayout(port_input_row)

        port_hint = BodyLabel(_tr("SettingsWindow.ai_status_port_hint"), page)
        port_hint.setWordWrap(True)
        self._compact_hint_labels.append(port_hint)
        layout.addWidget(port_hint)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.compact_commands_title", default="悬浮窗 @ 命令"), page))
        compact_commands = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.compact_commands_hint",
            default="@clear：清空悬浮窗输出；@stop / @停止 / @中断：中断当前悬浮窗回复。",
        ), page))
        self._compact_hint_labels.append(compact_commands)
        layout.addWidget(compact_commands)

        opacity_label = BodyLabel(_tr("SettingsWindow.compact_window_opacity"), page)
        layout.addWidget(opacity_label)
        self._compact_window_opacity_slider = Slider(Qt.Orientation.Horizontal, page)
        self._compact_window_opacity_slider.setRange(15, 100)
        self._compact_window_opacity_slider.setSingleStep(5)
        self._compact_window_opacity_value = BodyLabel("", page)
        self._compact_window_opacity_slider.valueChanged.connect(
            lambda v: self._compact_window_opacity_value.setText(_tr("SettingsWindow.opacity_value", v=v))
        )
        layout.addWidget(self._compact_window_opacity_slider)
        layout.addWidget(self._compact_window_opacity_value)

        font_label = BodyLabel(_tr("SettingsWindow.compact_window_font_size"), page)
        layout.addWidget(font_label)
        self._compact_window_font_size_slider = Slider(Qt.Orientation.Horizontal, page)
        self._compact_window_font_size_slider.setRange(9, 22)
        self._compact_window_font_size_slider.setSingleStep(1)
        self._compact_window_font_size_value = BodyLabel("", page)
        self._compact_window_font_size_slider.valueChanged.connect(
            lambda v: self._compact_window_font_size_value.setText(f"{v}px")
        )
        font_hint = BodyLabel(_tr("SettingsWindow.compact_window_font_hint"), page)
        font_hint.setWordWrap(True)
        self._compact_hint_labels.append(font_hint)
        layout.addWidget(self._compact_window_font_size_slider)
        layout.addWidget(self._compact_window_font_size_value)
        layout.addWidget(font_hint)

        bg_label = BodyLabel(_tr("SettingsWindow.compact_window_bg_color"), page)
        layout.addWidget(bg_label)
        self._compact_bg_color_btns = self._build_compact_color_row(
            page,
            [
                (BANDORI_PRIMARY, "Bandori"),
                ("#e91e63", _tr("color.pink")),
                ("#9c27b0", _tr("color.purple")),
                ("#4caf50", _tr("color.green")),
                ("#ff9800", _tr("color.orange")),
                ("#f44336", _tr("color.red")),
                ("#00bcd4", _tr("color.cyan")),
                ("#607d8b", _tr("color.grey")),
                ("#ffffff", "White"),
            ],
            "compact_color",
        )
        layout.addLayout(self._compact_bg_color_row)

        text_label = BodyLabel(_tr("SettingsWindow.compact_window_text_color"), page)
        layout.addWidget(text_label)
        self._compact_text_color_btns = self._build_compact_color_row(
            page,
            [
                ("#24242a", "Ink"),
                ("#ffffff", "White"),
                ("#000000", "Black"),
                ("#5b3150", "Berry"),
                ("#254a6a", "Blue"),
                ("#315c3b", "Green"),
                ("#704b12", "Gold"),
            ],
            "compact_color",
        )
        layout.addLayout(self._compact_text_color_row)

        layout.addStretch()

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_compact_window_config)
        reset_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.compact_window_reset"), page)
        reset_btn.setFixedHeight(36)
        reset_btn.clicked.connect(self._reset_compact_window_config)
        hint = BodyLabel(_tr("SettingsWindow.compact_window_apply_hint"), page)
        hint.setWordWrap(True)
        self._compact_hint_labels.append(hint)
        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addWidget(hint, 1)
        layout.addLayout(btn_row)

        self._load_compact_window_config()
        self._style_compact_controls()
        qconfig.themeChanged.connect(self._style_compact_controls)
        return page

    def _build_compact_color_row(self, page: QWidget, colors: list[tuple[str, str]], prop_name: str) -> list[QPushButton]:
        row = QHBoxLayout()
        row.setSpacing(6)
        btns: list[QPushButton] = []
        for color_hex, color_name in colors:
            btn = PushButton("", page)
            btn.setFixedSize(32, 32)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color_name)
            btn.setProperty(prop_name, color_hex)
            btn.clicked.connect(lambda checked, buttons=btns, b=btn: self._on_compact_color_clicked(buttons, b))
            btns.append(btn)
            row.addWidget(btn)
        row.addStretch()
        if not hasattr(self, "_compact_bg_color_row"):
            self._compact_bg_color_row = row
        else:
            self._compact_text_color_row = row
        return btns

    def _on_compact_color_clicked(self, buttons: list[QPushButton], btn: QPushButton):
        for b in buttons:
            b.setChecked(False)
        btn.setChecked(True)
        self._style_compact_color_buttons(buttons)
        self._pulse_button(btn)

    def _style_compact_color_buttons(self, buttons: list[QPushButton]):
        dark = isDarkTheme()
        checked_border = accent_color(dark)
        idle_border = "#4a4a4a" if dark else "#d7d7d7"
        hover_border = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        for btn in buttons:
            color = btn.property("compact_color")
            checked = btn.isChecked()
            btn.setText("\u2713" if checked else "")
            btn.setFixedSize(32, 32)
            border = f"2px solid {checked_border}" if checked else f"1px solid {idle_border}"
            text_color = "#111111" if QColor(color).lightness() > 170 else "#ffffff"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: {border};
                    border-radius: 6px;
                    color: {text_color};
                    font-weight: 900;
                    font-size: 14px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    border: 2px solid {hover_border};
                }}
            """)

    def _style_compact_controls(self):
        if not self._compact_config_widgets_ready():
            return
        muted = "#a0a7b7" if isDarkTheme() else "#6b7280"
        for label in getattr(self, "_compact_hint_labels", []):
            label.setStyleSheet(f"color: {muted}; font-size: 13px;")
        self._style_compact_color_buttons(self._compact_bg_color_btns)
        self._style_compact_color_buttons(self._compact_text_color_btns)

    def _compact_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_compact_ai_window_enabled",
                "_ai_event_overlay_enabled",
                "_ai_status_port_enabled",
                "_ai_status_port_input",
                "_ai_status_token_input",
                "_compact_window_opacity_slider",
                "_compact_window_opacity_value",
                "_compact_window_font_size_slider",
                "_compact_window_font_size_value",
                "_compact_bg_color_btns",
                "_compact_text_color_btns",
            )
        )

    @staticmethod
    def _selected_compact_color(buttons: list[QPushButton], fallback: str) -> str:
        for btn in buttons:
            if btn.isChecked():
                return btn.property("compact_color")
        return fallback

    @staticmethod
    def _set_compact_color_selection(buttons: list[QPushButton], color: str):
        normalized = QColor(color).name().lower() if QColor(color).isValid() else ""
        selected = False
        for btn in buttons:
            btn_color = QColor(btn.property("compact_color")).name().lower()
            checked = bool(normalized and btn_color == normalized)
            btn.setChecked(checked)
            selected = selected or checked
        if not selected and buttons:
            buttons[0].setChecked(True)

    def _load_compact_window_config(self):
        if not self._cfg or not self._compact_config_widgets_ready():
            return
        self._compact_ai_window_enabled.setChecked(bool(self._cfg.get("compact_ai_window_enabled", False)))
        self._ai_event_overlay_enabled.setChecked(bool(self._cfg.get("ai_event_overlay_enabled", False)))
        self._ai_status_port_enabled.setChecked(bool(self._cfg.get("ai_status_port_enabled", False)))
        self._ai_status_port_input.setText(str(self._clamp_ai_status_port(self._cfg.get("ai_status_port", 38472))))
        self._ai_status_token_input.setText(str(self._cfg.get("ai_status_token", "") or ""))
        opacity = self._cfg.get("compact_ai_window_opacity", 44)
        try:
            opacity = int(opacity)
        except (TypeError, ValueError):
            opacity = 44
        opacity = max(15, min(100, opacity))
        self._compact_window_opacity_slider.setValue(opacity)
        self._compact_window_opacity_value.setText(_tr("SettingsWindow.opacity_value", v=opacity))
        font_size = self._cfg.get("compact_ai_window_font_size", 12)
        try:
            font_size = int(font_size)
        except (TypeError, ValueError):
            font_size = 12
        font_size = max(9, min(22, font_size))
        self._compact_window_font_size_slider.setValue(font_size)
        self._compact_window_font_size_value.setText(f"{font_size}px")
        bg_color = self._cfg.get("compact_ai_window_background_color", "") or self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
        text_color = self._cfg.get("compact_ai_window_text_color", "#24242a")
        self._set_compact_color_selection(self._compact_bg_color_btns, bg_color)
        self._set_compact_color_selection(self._compact_text_color_btns, text_color)
        self._style_compact_color_buttons(self._compact_bg_color_btns)
        self._style_compact_color_buttons(self._compact_text_color_btns)

    def _compact_window_settings_data(self) -> dict:
        if not self._cfg:
            return {}
        data = {
            "compact_ai_window_enabled": self._cfg.get("compact_ai_window_enabled", False),
            "compact_ai_window_opacity": self._cfg.get("compact_ai_window_opacity", 44),
            "compact_ai_window_font_size": self._cfg.get("compact_ai_window_font_size", 12),
            "compact_ai_window_background_color": self._cfg.get("compact_ai_window_background_color", ""),
            "compact_ai_window_text_color": self._cfg.get("compact_ai_window_text_color", "#24242a"),
            "ai_event_overlay_enabled": self._cfg.get("ai_event_overlay_enabled", False),
            "ai_status_port_enabled": self._cfg.get("ai_status_port_enabled", False),
            "ai_status_port": self._clamp_ai_status_port(self._cfg.get("ai_status_port", 38472)),
            "ai_status_token": self._cfg.get("ai_status_token", ""),
        }
        if self._compact_window_reset_position_pending:
            data["compact_ai_window_reset_position"] = True
        return data

    def _save_compact_window_config(self, show_info: bool = True, emit_update: bool = False):
        if not self._cfg or not self._compact_config_widgets_ready():
            return
        self._cfg.set("compact_ai_window_enabled", self._compact_ai_window_enabled.isChecked())
        self._cfg.set("compact_ai_window_opacity", self._compact_window_opacity_slider.value())
        self._cfg.set("compact_ai_window_font_size", self._compact_window_font_size_slider.value())
        self._cfg.set("compact_ai_window_background_color", self._selected_compact_color(self._compact_bg_color_btns, BANDORI_PRIMARY))
        self._cfg.set("compact_ai_window_text_color", self._selected_compact_color(self._compact_text_color_btns, "#24242a"))
        self._cfg.set("ai_event_overlay_enabled", self._ai_event_overlay_enabled.isChecked())
        self._cfg.set("ai_status_port_enabled", self._ai_status_port_enabled.isChecked())
        self._cfg.set("ai_status_port", self._clamp_ai_status_port(self._ai_status_port_input.text()))
        self._cfg.set("ai_status_token", self._ai_status_token_input.text().strip())
        try:
            self._cfg.save()
            if emit_update:
                self.settings_changed.emit(self._compact_window_settings_data())
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.compact_window_saved_title"),
                    _tr("SettingsWindow.compact_window_saved_content"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
        except Exception:
            pass

    def _reset_compact_window_config(self):
        if not self._cfg or not self._compact_config_widgets_ready():
            return
        avatar_color = self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
        self._compact_window_opacity_slider.setValue(44)
        self._compact_window_opacity_value.setText(_tr("SettingsWindow.opacity_value", v=44))
        self._set_compact_color_selection(self._compact_bg_color_btns, avatar_color)
        self._set_compact_color_selection(self._compact_text_color_btns, "#24242a")
        self._style_compact_color_buttons(self._compact_bg_color_btns)
        self._style_compact_color_buttons(self._compact_text_color_btns)
        self._compact_window_reset_position_pending = True

    def _build_chat_integration_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("chatIntegrationPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.chat_integration_title", default="聊天接入"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr(
            "SettingsWindow.chat_integration_subtitle",
            default="接收外部聊天软件或脚本推送的消息，写入本地上下文，并在桌宠悬浮窗显示未读摘要。",
        ), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self._chat_integration_enabled = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.chat_integration_enabled", default="启用本地聊天接入端口"),
            self._chat_integration_enabled,
        )

        self._chat_integration_overlay_enabled = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.chat_integration_overlay_enabled", default="收到消息时显示悬浮窗摘要"),
            self._chat_integration_overlay_enabled,
        )

        self._chat_integration_include_context = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.chat_integration_include_context", default="允许模型读取最近外部聊天上下文"),
            self._chat_integration_include_context,
        )

        layout.addWidget(SubtitleLabel(_tr(
            "SettingsWindow.chat_integration_quick_setup",
            default="快速配置",
        ), page))

        endpoint_row = QHBoxLayout()
        endpoint_row.setContentsMargins(0, 0, 0, 0)
        endpoint_row.setSpacing(8)
        self._chat_integration_endpoint_input = FluentContextLineEdit(page)
        self._chat_integration_endpoint_input.setReadOnly(True)
        self._chat_integration_endpoint_input.setFixedHeight(36)
        copy_endpoint_btn = PushButton(FluentIcon.COPY, _tr(
            "SettingsWindow.chat_integration_copy_endpoint",
            default="复制地址",
        ), page)
        copy_endpoint_btn.clicked.connect(self._copy_chat_integration_endpoint)
        endpoint_row.addWidget(BodyLabel(_tr(
            "SettingsWindow.chat_integration_endpoint",
            default="接收地址",
        ), page))
        endpoint_row.addWidget(self._chat_integration_endpoint_input, 1)
        endpoint_row.addWidget(copy_endpoint_btn)
        layout.addLayout(endpoint_row)

        config_row = QHBoxLayout()
        config_row.setContentsMargins(0, 0, 0, 0)
        config_row.setSpacing(8)
        self._chat_integration_port_input = LineEdit(page)
        self._chat_integration_port_input.setFixedWidth(120)
        self._chat_integration_port_input.setFixedHeight(36)
        self._chat_integration_port_input.setValidator(QIntValidator(1024, 65535, self))
        self._chat_integration_port_input.setPlaceholderText("38473")
        token_label = BodyLabel(_tr("SettingsWindow.chat_integration_token", default="Token"), page)
        self._chat_integration_token_input = LineEdit(page)
        self._chat_integration_token_input.setFixedHeight(36)
        self._chat_integration_token_input.setPlaceholderText(_tr(
            "SettingsWindow.chat_integration_token_placeholder",
            default="可留空；给第三方脚本使用时建议填写",
        ))
        generate_token_btn = PushButton(FluentIcon.SYNC, _tr(
            "SettingsWindow.chat_integration_generate_token",
            default="生成 Token",
        ), page)
        generate_token_btn.clicked.connect(self._generate_chat_integration_token)
        copy_token_btn = PushButton(FluentIcon.COPY, _tr(
            "SettingsWindow.chat_integration_copy_token",
            default="复制 Token",
        ), page)
        copy_token_btn.clicked.connect(self._copy_chat_integration_token)
        config_row.addWidget(BodyLabel(_tr("SettingsWindow.chat_integration_port_number", default="端口"), page))
        config_row.addWidget(self._chat_integration_port_input)
        config_row.addSpacing(12)
        config_row.addWidget(token_label)
        config_row.addWidget(self._chat_integration_token_input, 1)
        config_row.addWidget(generate_token_btn)
        config_row.addWidget(copy_token_btn)
        layout.addLayout(config_row)

        hint = BodyLabel(_tr(
            "SettingsWindow.chat_integration_hint",
            default="开启后监听 127.0.0.1，可接收 JSON、表单、纯文本或 URL 参数。外部消息会进入本地数据库；开启上下文后，下一次角色聊天会看到最近消息。",
        ), page)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._chat_integration_preview = JsonCodeEdit(page)
        self._chat_integration_preview.setReadOnly(True)
        self._chat_integration_preview.setFixedHeight(170)
        layout.addWidget(self._chat_integration_preview)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        save_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.chat_integration_save", default="保存聊天接入配置"), page)
        save_btn.clicked.connect(lambda: self._save_chat_integration_config(show_info=True, emit_update=True))
        copy_setup_btn = PushButton(FluentIcon.COPY, _tr(
            "SettingsWindow.chat_integration_copy_setup",
            default="复制接入信息",
        ), page)
        copy_setup_btn.clicked.connect(self._copy_chat_integration_setup)
        test_btn = PushButton(FluentIcon.WIFI, _tr(
            "SettingsWindow.chat_integration_test",
            default="发送测试消息",
        ), page)
        test_btn.clicked.connect(self._test_chat_integration)
        guide_btn = PushButton(FluentIcon.INFO, _tr(
            "SettingsWindow.chat_integration_open_guide",
            default="打开教程",
        ), page)
        guide_btn.clicked.connect(self._open_chat_integration_guide)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(copy_setup_btn)
        btn_row.addWidget(test_btn)
        btn_row.addWidget(guide_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        apply_hint = BodyLabel(_tr(
            "SettingsWindow.chat_integration_apply_hint",
            default="保存后会立即通知正在运行的桌宠刷新端口；如果没有启动桌宠，请启动后再测试。",
        ), page)
        apply_hint.setWordWrap(True)
        layout.addWidget(apply_hint)
        layout.addStretch()

        self._chat_integration_port_input.textChanged.connect(self._update_chat_integration_quick_setup)
        self._chat_integration_token_input.textChanged.connect(self._update_chat_integration_quick_setup)
        self._load_chat_integration_config()
        self._style_chat_integration_page(page)
        qconfig.themeChanged.connect(lambda: self._style_chat_integration_page(page))
        return page

    def _chat_integration_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_chat_integration_enabled",
                "_chat_integration_overlay_enabled",
                "_chat_integration_include_context",
                "_chat_integration_endpoint_input",
                "_chat_integration_port_input",
                "_chat_integration_token_input",
                "_chat_integration_preview",
            )
        )

    def _style_chat_integration_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        text_border = "#4a4a4a" if dark else "#d8d8d8"
        input_bg = "#2b2b2b" if dark else "#ffffff"
        text = "#f7f7fb" if dark else "#1f2328"
        readonly_bg = "#242424" if dark else "#f8f8f8"
        page.setStyleSheet(f"""
            QWidget#chatIntegrationPage {{
                background: {page_bg};
            }}
            QLineEdit {{
                color: {text};
                background: {input_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                padding: 6px;
            }}
            QLineEdit[readOnly="true"] {{
                background: {readonly_bg};
            }}
            QPlainTextEdit#JsonCodeEdit {{
                color: {text};
                background: {readonly_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                padding-left: 0px;
                selection-background-color: {BANDORI_PRIMARY};
            }}
        """)
        self._refresh_theme_widget_styles(page)
        self._refresh_json_code_edit_theme(getattr(self, "_chat_integration_preview", None))

    def _chat_integration_endpoint_url(self) -> str:
        if self._chat_integration_widgets_ready():
            port = self._clamp_chat_integration_port(self._chat_integration_port_input.text())
        elif self._cfg:
            port = self._clamp_chat_integration_port(self._cfg.get("chat_integration_port", 38473))
        else:
            port = 38473
        return f"http://127.0.0.1:{port}/chat-events"

    def _chat_integration_sample_event(self) -> dict:
        return {
            "platform": "qq",
            "thread_id": "default",
            "thread_name": "接入测试",
            "sender_name": "测试用户",
            "text": "这是一条从聊天软件推送到 BandoriPet 的测试消息。",
        }

    def _chat_integration_setup_text(self) -> str:
        endpoint = self._chat_integration_endpoint_url()
        token = self._chat_integration_token_input.text().strip() if self._chat_integration_widgets_ready() else ""
        headers = "Content-Type: application/json"
        if token:
            headers += f"\nAuthorization: Bearer {token}"
        sample = json.dumps(self._chat_integration_sample_event(), ensure_ascii=False, indent=2)
        url_sample = (
            f"{endpoint}?platform=qq&thread_id=default&thread_name=接入测试"
            f"&sender_name=发送人&text=消息内容"
        )
        if token:
            url_sample += f"&token={token}"
        return "\n".join([
            "BandoriPet 聊天接入信息",
            f"接收地址: {endpoint}",
            "请求方式: POST（推荐）或 GET URL 参数；支持 JSON、表单和纯文本正文",
            headers,
            "",
            "最小 JSON:",
            sample,
            "",
            "URL 参数模式:",
            url_sample,
            "",
            "字段对应：text=消息内容，sender_name=发送人，thread_name=群聊/私聊名称。",
        ])

    def _update_chat_integration_quick_setup(self, *_args):
        if not self._chat_integration_widgets_ready():
            return
        self._chat_integration_endpoint_input.setText(self._chat_integration_endpoint_url())
        self._chat_integration_preview.setPlainText(self._chat_integration_setup_text())

    def _copy_chat_integration_endpoint(self):
        if not self._chat_integration_widgets_ready():
            return
        QApplication.clipboard().setText(self._chat_integration_endpoint_url())
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_endpoint_copied_title", default="已复制"),
            _tr("SettingsWindow.chat_integration_endpoint_copied_content", default="聊天接入地址已复制。"),
            duration=1600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _generate_chat_integration_token(self):
        if not self._chat_integration_widgets_ready():
            return
        self._chat_integration_token_input.setText(secrets.token_urlsafe(18))
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_token_generated_title", default="已生成 Token"),
            _tr("SettingsWindow.chat_integration_token_generated_content", default="请保存配置后，把 Token 一起填到聊天软件或转发插件里。"),
            duration=2200,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _copy_chat_integration_token(self):
        if not self._chat_integration_widgets_ready():
            return
        token = self._chat_integration_token_input.text().strip()
        if not token:
            InfoBar.warning(
                _tr("SettingsWindow.chat_integration_token_empty_title", default="没有 Token"),
                _tr("SettingsWindow.chat_integration_token_empty_content", default="当前 Token 为空，可以先点击“生成 Token”。"),
                duration=2200,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        QApplication.clipboard().setText(token)
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_token_copied_title", default="已复制"),
            _tr("SettingsWindow.chat_integration_token_copied_content", default="Token 已复制。"),
            duration=1600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _copy_chat_integration_setup(self):
        if not self._chat_integration_widgets_ready():
            return
        QApplication.clipboard().setText(self._chat_integration_setup_text())
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_setup_copied_title", default="已复制"),
            _tr("SettingsWindow.chat_integration_setup_copied_content", default="接入信息已复制，可直接粘贴到聊天软件的 Webhook/HTTP 配置里。"),
            duration=2200,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _open_chat_integration_guide(self):
        path = os.path.join(app_base_dir(), "CHAT_INTEGRATION_GUIDE.md")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _test_chat_integration(self):
        if not self._chat_integration_widgets_ready():
            return
        if not self._chat_integration_enabled.isChecked():
            self._chat_integration_enabled.setChecked(True)
        self._save_chat_integration_config(show_info=False, emit_update=True)
        QTimer.singleShot(350, self._send_chat_integration_test_request)

    def _send_chat_integration_test_request(self):
        endpoint = self._chat_integration_endpoint_url()
        token = self._chat_integration_token_input.text().strip() if self._chat_integration_widgets_ready() else ""
        data = json.dumps(self._chat_integration_sample_event(), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict) and payload.get("ok"):
                InfoBar.success(
                    _tr("SettingsWindow.chat_integration_test_success_title", default="测试成功"),
                    _tr("SettingsWindow.chat_integration_test_success_content", default="BandoriPet 已收到测试消息，悬浮摘要和上下文接入可用。"),
                    duration=2600,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            raise RuntimeError(body or "empty response")
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            detail = body or str(exc)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
            detail = str(exc)
        InfoBar.error(
            _tr("SettingsWindow.chat_integration_test_failed_title", default="测试失败"),
            _tr(
                "SettingsWindow.chat_integration_test_failed_content",
                default="没有连上本地接入口。请确认桌宠正在运行，并已保存/应用聊天接入配置。错误：{error}",
                error=detail,
            ),
            duration=4500,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _load_chat_integration_config(self):
        if not self._cfg or not self._chat_integration_widgets_ready():
            return
        self._chat_integration_enabled.setChecked(bool(self._cfg.get("chat_integration_enabled", False)))
        self._chat_integration_overlay_enabled.setChecked(bool(self._cfg.get("chat_integration_overlay_enabled", True)))
        self._chat_integration_include_context.setChecked(bool(self._cfg.get("chat_integration_include_context", True)))
        self._chat_integration_port_input.setText(str(self._clamp_chat_integration_port(self._cfg.get("chat_integration_port", 38473))))
        self._chat_integration_token_input.setText(str(self._cfg.get("chat_integration_token", "") or ""))
        self._update_chat_integration_quick_setup()

    def _chat_integration_settings_data(self) -> dict:
        if not self._cfg:
            return {}
        return {
            "chat_integration_enabled": self._cfg.get("chat_integration_enabled", False),
            "chat_integration_overlay_enabled": self._cfg.get("chat_integration_overlay_enabled", True),
            "chat_integration_include_context": self._cfg.get("chat_integration_include_context", True),
            "chat_integration_port": self._clamp_chat_integration_port(self._cfg.get("chat_integration_port", 38473)),
            "chat_integration_token": self._cfg.get("chat_integration_token", ""),
        }

    def _save_chat_integration_config(self, show_info: bool = True, emit_update: bool = False):
        if not self._cfg or not self._chat_integration_widgets_ready():
            return
        self._cfg.set("chat_integration_enabled", self._chat_integration_enabled.isChecked())
        self._cfg.set("chat_integration_overlay_enabled", self._chat_integration_overlay_enabled.isChecked())
        self._cfg.set("chat_integration_include_context", self._chat_integration_include_context.isChecked())
        self._cfg.set("chat_integration_port", self._clamp_chat_integration_port(self._chat_integration_port_input.text()))
        self._cfg.set("chat_integration_token", self._chat_integration_token_input.text().strip())
        try:
            self._cfg.save()
            if emit_update:
                self.settings_changed.emit(self._chat_integration_settings_data())
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.chat_integration_saved_title", default="已保存"),
                    _tr("SettingsWindow.chat_integration_saved_content", default="聊天接入配置已保存。"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.chat_integration_failed_title", default="保存失败"),
                str(exc),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    @staticmethod
    def _clamp_ai_status_port(value) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = 38472
        return max(1024, min(65535, port))

    @staticmethod
    def _clamp_chat_integration_port(value) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = 38473
        return max(1024, min(65535, port))

    def _build_mcp_computer_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("mcpComputerPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.mcp_computer_title", default="智能工具与电脑控制"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.mcp_computer_subtitle",
            default="支持服务商原生 MCP，也支持 Chat Completions 的 tool_calls/function calling，把 MCP 和 Computer Use 转成兼容工具。",
        ), page))
        layout.addWidget(subtitle)
        capability_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.mcp_capability_hint",
            default="提示：启用 MCP 或 Computer Use 只是把工具提供给模型；必须使用支持 tool_calls/function calling 的模型才会调用工具，截图理解还需要模型支持多模态输入。",
        ), page))
        layout.addWidget(capability_hint)

        risk_panel = QWidget(page)
        risk_panel.setObjectName("mcpRiskPanel")
        risk_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        risk_layout = QVBoxLayout(risk_panel)
        risk_layout.setContentsMargins(12, 10, 12, 10)
        risk_layout.setSpacing(4)
        risk_layout.addWidget(StrongBodyLabel(_tr("SettingsWindow.computer_use_risk_title", default="风险提示"), risk_panel))
        risk_layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.computer_use_risk_text",
            default=(
                "Computer Use 会把屏幕截图发送给模型，并可按你的授权移动鼠标、点击、输入文本或按快捷键。"
                "只在可信任务中开启；不要让模型接触密码、支付、删除、购买、发帖等不可逆操作。"
            ),
        ), risk_panel)))
        layout.addWidget(risk_panel)

        self._llm_hide_tool_call_details = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.llm_hide_tool_call_details", default="沉浸模式隐藏工具细节"),
            self._llm_hide_tool_call_details,
        )
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_hide_tool_call_details_hint",
            default="开启后会提示模型不要在角色回复里说出 MCP、工具调用、function calling、Computer Use 等实现细节。",
        ), page)))

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.mcp_title", default="MCP 接口"), page))
        self._llm_mcp_enabled = SwitchButton(page)
        self._llm_mcp_use_native = SwitchButton(page)
        self._add_switch_row(layout, page, _tr("SettingsWindow.llm_mcp_enabled", default="启用 MCP 工具"), self._llm_mcp_enabled)
        self._add_switch_row(layout, page, _tr("SettingsWindow.llm_mcp_use_native", default="OpenAI Responses 优先使用原生 MCP"), self._llm_mcp_use_native)
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_mcp_use_native_hint",
            default="原生 MCP 只对支持该工具的服务商生效；DeepSeek、OpenRouter 等兼容接口会走本地 MCP 代理工具。",
        ), page)))

        layout.addWidget(BodyLabel(_tr("SettingsWindow.llm_mcp_servers", default="MCP 服务器 JSON（纯文本）"), page))
        self._llm_mcp_servers_text = JsonCodeEdit(page)
        self._llm_mcp_servers_text.setPlaceholderText(self._default_mcp_servers_json())
        self._llm_mcp_servers_text.setFixedHeight(260)
        layout.addWidget(self._llm_mcp_servers_text)
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_mcp_servers_hint",
            default="这里是纯文本 JSON，只读取字符内容；支持 stdio、本地/远程 HTTP 代理，以及 OpenAI Responses 原生 native/server_url 配置。",
        ), page)))

        mcp_btn_row = QHBoxLayout()
        guide_btn = PushButton(FluentIcon.INFO, _tr("SettingsWindow.mcp_open_guide", default="打开教程"), page)
        guide_btn.clicked.connect(self._open_mcp_guide)
        format_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.mcp_format_json", default="格式化 JSON"), page)
        format_btn.clicked.connect(self._format_mcp_servers_json)
        copy_btn = PushButton(FluentIcon.COPY, _tr("SettingsWindow.mcp_copy_json", default="复制 JSON"), page)
        copy_btn.clicked.connect(self._copy_mcp_servers_json)
        test_mcp_btn = PushButton(FluentIcon.WIFI, _tr("SettingsWindow.mcp_test_connection", default="测试 MCP 连接"), page)
        test_mcp_btn.clicked.connect(self._test_mcp_connection)
        mcp_btn_row.addWidget(guide_btn)
        mcp_btn_row.addWidget(format_btn)
        mcp_btn_row.addWidget(copy_btn)
        mcp_btn_row.addWidget(test_mcp_btn)
        mcp_btn_row.addStretch()
        layout.addLayout(mcp_btn_row)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.computer_use_title", default="Computer Use 权限"), page))
        self._computer_use_enabled = SwitchButton(page)
        self._computer_use_auto_detect = SwitchButton(page)
        self._computer_use_send_screenshots = SwitchButton(page)
        self._computer_use_allow_screenshot = SwitchButton(page)
        self._computer_use_allow_mouse = SwitchButton(page)
        self._computer_use_allow_keyboard = SwitchButton(page)
        self._computer_use_allow_clipboard = SwitchButton(page)
        self._computer_use_allow_wait = SwitchButton(page)
        for label, widget in (
            (_tr("SettingsWindow.computer_use_enabled", default="启用 Computer Use"), self._computer_use_enabled),
            (_tr("SettingsWindow.computer_use_auto_detect", default="让模型按自然语义自行判断是否使用"), self._computer_use_auto_detect),
            (_tr("SettingsWindow.computer_use_send_screenshots", default="向模型发送操作后的截图"), self._computer_use_send_screenshots),
            (_tr("SettingsWindow.computer_use_allow_screenshot", default="允许截屏"), self._computer_use_allow_screenshot),
            (_tr("SettingsWindow.computer_use_allow_mouse", default="允许鼠标移动、点击、滚动"), self._computer_use_allow_mouse),
            (_tr("SettingsWindow.computer_use_allow_keyboard", default="允许键盘输入和快捷键"), self._computer_use_allow_keyboard),
            (_tr("SettingsWindow.computer_use_allow_clipboard", default="允许剪贴板写入"), self._computer_use_allow_clipboard),
            (_tr("SettingsWindow.computer_use_allow_wait", default="允许等待/暂停"), self._computer_use_allow_wait),
        ):
            self._add_switch_row(layout, page, label, widget)

        screenshot_row = QHBoxLayout()
        screenshot_row.setSpacing(8)
        screenshot_row.addWidget(BodyLabel(_tr("SettingsWindow.computer_use_max_screenshot_width", default="截图最长边像素"), page))
        self._computer_use_max_screenshot_width = FluentContextLineEdit(page)
        self._computer_use_max_screenshot_width.setValidator(QIntValidator(640, 1920, self._computer_use_max_screenshot_width))
        self._computer_use_max_screenshot_width.setFixedHeight(34)
        self._computer_use_max_screenshot_width.setMaximumWidth(120)
        screenshot_row.addWidget(self._computer_use_max_screenshot_width)
        screenshot_row.addStretch()
        layout.addLayout(screenshot_row)
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.computer_use_hint",
            default="DeepSeek/OpenRouter 等兼容接口会通过 tool_calls/function calling 使用这些能力。模型需要支持图片输入，才能稳定理解屏幕截图；鼠标工具会把截图坐标映射到真实桌面坐标。",
        ), page)))

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.clicked.connect(self._save_mcp_computer_config)
        layout.addWidget(save_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch()

        self._load_mcp_computer_config()
        self._style_mcp_computer_page(page)
        qconfig.themeChanged.connect(lambda: self._style_mcp_computer_page(page))
        return page

    def _add_switch_row(self, layout: QVBoxLayout, page: QWidget, label: str, switch: SwitchButton):
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label, page))
        row.addStretch()
        row.addWidget(switch)
        layout.addLayout(row)

    def _style_mcp_computer_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        risk_bg = "#2a2022" if dark else "#fff4e5"
        risk_border = "#8a5b20" if dark else "#ffd599"
        text_border = "#4a4a4a" if dark else "#d8d8d8"
        input_bg = "#2b2b2b" if dark else "#ffffff"
        text = "#f7f7fb" if dark else "#1f2328"
        page.setStyleSheet(f"""
            QWidget#mcpComputerPage {{
                background: {page_bg};
            }}
            #mcpRiskPanel {{
                background: {risk_bg};
                border: 1px solid {risk_border};
                border-radius: 8px;
            }}
            #mcpRiskPanel QLabel {{
                background: transparent;
            }}
            QTextEdit, QPlainTextEdit, QLineEdit {{
                color: {text};
                background: {input_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                padding: 6px;
            }}
            QPlainTextEdit#JsonCodeEdit {{
                padding-left: 0px;
                selection-background-color: {BANDORI_PRIMARY};
            }}
        """)
        self._refresh_theme_widget_styles(page)
        self._refresh_json_code_edit_theme(getattr(self, "_llm_mcp_servers_text", None))

    def _mcp_computer_widgets_ready(self) -> bool:
        return all(
            hasattr(self, name)
            for name in (
                "_llm_hide_tool_call_details",
                "_llm_mcp_enabled",
                "_llm_mcp_use_native",
                "_llm_mcp_servers_text",
                "_computer_use_enabled",
                "_computer_use_auto_detect",
                "_computer_use_send_screenshots",
                "_computer_use_allow_screenshot",
                "_computer_use_allow_mouse",
                "_computer_use_allow_keyboard",
                "_computer_use_allow_clipboard",
                "_computer_use_allow_wait",
                "_computer_use_max_screenshot_width",
            )
        )

    def _default_mcp_servers_json(self) -> str:
        project_dir = str(app_base_dir()).replace("\\", "/")
        sample = [
            {
                "enabled": True,
                "label": "filesystem",
                "transport": "stdio",
                "command": "python",
                "args": ["filesystem_mcp_server.py", "~/Documents"],
                "cwd": project_dir,
                "allowed_tools": [],
                "require_approval": "always",
            },
            {
                "enabled": True,
                "label": "remote_docs",
                "transport": "native",
                "url": "https://example.com/mcp",
                "allowed_tools": [],
                "require_approval": "never",
            },
        ]
        return json.dumps(sample, ensure_ascii=False, indent=2)

    def _load_mcp_computer_config(self):
        if not self._cfg or not self._mcp_computer_widgets_ready():
            return
        self._llm_hide_tool_call_details.setChecked(bool(self._cfg.get("llm_hide_tool_call_details", True)))
        self._llm_mcp_enabled.setChecked(bool(self._cfg.get("llm_mcp_enabled", False)))
        self._llm_mcp_use_native.setChecked(bool(self._cfg.get("llm_mcp_use_native", True)))
        servers = self._cfg.get("llm_mcp_servers", [])
        self._llm_mcp_servers_text.setPlainText(json.dumps(servers if isinstance(servers, list) else [], ensure_ascii=False, indent=2))
        self._computer_use_enabled.setChecked(bool(self._cfg.get("computer_use_enabled", False)))
        self._computer_use_auto_detect.setChecked(bool(self._cfg.get("computer_use_auto_detect", True)))
        self._computer_use_send_screenshots.setChecked(bool(self._cfg.get("computer_use_send_screenshots", True)))
        self._computer_use_allow_screenshot.setChecked(bool(self._cfg.get("computer_use_allow_screenshot", True)))
        self._computer_use_allow_mouse.setChecked(bool(self._cfg.get("computer_use_allow_mouse", False)))
        self._computer_use_allow_keyboard.setChecked(bool(self._cfg.get("computer_use_allow_keyboard", False)))
        self._computer_use_allow_clipboard.setChecked(bool(self._cfg.get("computer_use_allow_clipboard", False)))
        self._computer_use_allow_wait.setChecked(bool(self._cfg.get("computer_use_allow_wait", True)))
        self._computer_use_max_screenshot_width.setText(str(self._cfg.get("computer_use_max_screenshot_width", 1280)))

    def _parse_mcp_servers_text(self) -> list[dict] | None:
        text = self._llm_mcp_servers_text.toPlainText().strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            InfoBar.error(
                _tr("SettingsWindow.mcp_json_invalid_title", default="MCP JSON 有误"),
                _tr("SettingsWindow.mcp_json_invalid_content", default="请检查 JSON 格式：{error}", error=str(exc)),
                duration=3500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        if not isinstance(data, list):
            InfoBar.error(
                _tr("SettingsWindow.mcp_json_invalid_title", default="MCP JSON 有误"),
                _tr("SettingsWindow.mcp_json_must_be_list", default="MCP 服务器配置必须是数组。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        return data

    def _format_mcp_servers_json(self):
        if not self._mcp_computer_widgets_ready():
            return
        data = self._parse_mcp_servers_text()
        if data is None:
            return
        self._llm_mcp_servers_text.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))

    def _copy_mcp_servers_json(self):
        if not self._mcp_computer_widgets_ready():
            return
        QApplication.clipboard().setText(self._llm_mcp_servers_text.toPlainText())
        InfoBar.success(
            _tr("SettingsWindow.mcp_json_copied_title", default="已复制"),
            _tr("SettingsWindow.mcp_json_copied_content", default="MCP JSON 已复制为纯文本。"),
            duration=1600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _test_mcp_connection(self):
        if not self._mcp_computer_widgets_ready():
            return
        servers = self._parse_mcp_servers_text()
        if servers is None:
            return
        if not self._llm_mcp_enabled.isChecked():
            InfoBar.warning(
                _tr("SettingsWindow.mcp_test_disabled_title", default="MCP 未启用"),
                _tr("SettingsWindow.mcp_test_disabled_content", default="请先打开“启用 MCP 工具”，再测试连接。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not any(isinstance(server, dict) and server.get("enabled", True) for server in servers):
            InfoBar.warning(
                _tr("SettingsWindow.mcp_test_empty_title", default="没有可测试的 MCP"),
                _tr("SettingsWindow.mcp_test_empty_content", default="MCP 服务器 JSON 里没有启用的服务器。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if hasattr(self, "_mcp_test_worker") and self._mcp_test_worker is not None and self._mcp_test_worker.isRunning():
            self._mcp_test_worker.quit()
            self._mcp_test_worker.wait(2000)
        config = {
            "llm_mcp_enabled": True,
            "llm_mcp_use_native": self._llm_mcp_use_native.isChecked(),
            "llm_mcp_servers": servers,
        }
        self._mcp_test_worker = McpConnectionTestWorker(config, parent=self)
        self._mcp_test_worker.finished.connect(self._on_mcp_test_finished)
        self._mcp_test_worker.error.connect(self._on_mcp_test_error)
        self._mcp_test_worker.start()

    def _on_mcp_test_finished(self, details: str):
        InfoBar.success(
            _tr("SettingsWindow.mcp_test_success_title", default="MCP 连接成功"),
            details,
            duration=6000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_mcp_test_error(self, details: str):
        InfoBar.error(
            _tr("SettingsWindow.mcp_test_failed_title", default="MCP 连接失败"),
            details,
            duration=8000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _open_mcp_guide(self):
        path = os.path.join(app_base_dir(), "MCP_COMPUTER_USE_GUIDE.md")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _save_mcp_computer_config(self, show_info: bool = True):
        if not self._cfg or not self._mcp_computer_widgets_ready():
            return
        servers = self._parse_mcp_servers_text()
        if servers is None:
            return
        try:
            max_width = int(self._computer_use_max_screenshot_width.text().strip() or "1280")
        except ValueError:
            max_width = 1280
        max_width = max(640, min(1920, max_width))
        self._cfg.set("llm_hide_tool_call_details", self._llm_hide_tool_call_details.isChecked())
        self._cfg.set("llm_mcp_enabled", self._llm_mcp_enabled.isChecked())
        self._cfg.set("llm_mcp_use_native", self._llm_mcp_use_native.isChecked())
        self._cfg.set("llm_mcp_servers", servers)
        self._cfg.set("computer_use_enabled", self._computer_use_enabled.isChecked())
        self._cfg.set("computer_use_auto_detect", self._computer_use_auto_detect.isChecked())
        self._cfg.set("computer_use_send_screenshots", self._computer_use_send_screenshots.isChecked())
        self._cfg.set("computer_use_max_screenshot_width", max_width)
        self._cfg.set("computer_use_allow_screenshot", self._computer_use_allow_screenshot.isChecked())
        self._cfg.set("computer_use_allow_mouse", self._computer_use_allow_mouse.isChecked())
        self._cfg.set("computer_use_allow_keyboard", self._computer_use_allow_keyboard.isChecked())
        self._cfg.set("computer_use_allow_clipboard", self._computer_use_allow_clipboard.isChecked())
        self._cfg.set("computer_use_allow_wait", self._computer_use_allow_wait.isChecked())
        self._cfg.save()
        if show_info:
            InfoBar.success(
                _tr("SettingsWindow.mcp_saved_title", default="智能工具与电脑控制已保存"),
                _tr("SettingsWindow.mcp_saved_content", default="新的工具配置会在下一次聊天请求时生效。"),
                duration=2200,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _quality_options(self) -> list[tuple[str, str]]:
        return [
            ("performance", _tr("SettingsWindow.quality_performance")),
            ("balanced", _tr("SettingsWindow.quality_balanced")),
        ]

    def _quality_detail_text(self, profile: str) -> str:
        return _tr(f"SettingsWindow.quality_detail_{normalize_live2d_quality(profile)}")

    def _build_quality_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.quality_title"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr("SettingsWindow.quality_subtitle"), page)
        layout.addWidget(subtitle)

        quality_label = BodyLabel(_tr("SettingsWindow.quality_profile"), page)
        layout.addWidget(quality_label)

        self._quality_combo = OpaqueDropDownComboBox(page)
        self._quality_combo.setFixedHeight(36)
        current_index = 0
        for index, (profile, label) in enumerate(self._quality_options()):
            self._quality_combo.addItem(label, userData=profile)
            if profile == self._live2d_quality:
                current_index = index
        self._quality_combo.setCurrentIndex(current_index)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        layout.addWidget(self._quality_combo)

        self._quality_detail = BodyLabel(self._quality_detail_text(self._live2d_quality), page)
        self._quality_detail.setWordWrap(True)
        layout.addWidget(self._quality_detail)

        scale_label = BodyLabel(_tr("SettingsWindow.live2d_scale"), page)
        layout.addWidget(scale_label)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(10)
        self._live2d_scale_slider = Slider(Qt.Orientation.Horizontal, page)
        self._live2d_scale_slider.setRange(LIVE2D_SCALE_MIN, LIVE2D_SCALE_MAX)
        self._live2d_scale_slider.setValue(self._live2d_scale)
        self._live2d_scale_slider.setSingleStep(5)
        self._live2d_scale_input = LineEdit(page)
        self._live2d_scale_input.setFixedWidth(76)
        self._live2d_scale_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._live2d_scale_input.setValidator(QIntValidator(LIVE2D_SCALE_MIN, LIVE2D_SCALE_MAX, self))
        self._live2d_scale_input.setText(str(self._live2d_scale))
        self._live2d_scale_slider.valueChanged.connect(self._on_live2d_scale_slider_changed)
        self._live2d_scale_input.editingFinished.connect(self._on_live2d_scale_input_finished)
        scale_row.addWidget(self._live2d_scale_slider, 1)
        scale_row.addWidget(self._live2d_scale_input)
        layout.addLayout(scale_row)

        layout.addStretch()
        return page

    def _build_about_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("aboutPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        hero = QWidget(page)
        hero.setObjectName("aboutHero")
        hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(18)

        icon_path = _app_icon_path()
        if icon_path:
            icon_label = QLabel(hero)
            icon_label.setObjectName("aboutHeroIcon")
            icon_label.setFixedSize(84, 84)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setPixmap(QIcon(icon_path).pixmap(72, 72))
            hero_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        hero_text = QVBoxLayout()
        hero_text.setContentsMargins(0, 0, 0, 0)
        hero_text.setSpacing(8)
        title = TitleLabel(_tr("SettingsWindow.about_title"), hero)
        subtitle = SubtitleLabel(_tr("SettingsWindow.about_subtitle"), hero)
        subtitle.setWordWrap(True)
        desc = BodyLabel(_tr("SettingsWindow.about_desc"), hero)
        desc.setWordWrap(True)
        version = BodyLabel(_tr("SettingsWindow.about_version", version=APP_VERSION), hero)
        version.setObjectName("aboutVersion")
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_text.addWidget(desc)
        hero_text.addWidget(version)
        hero_layout.addLayout(hero_text, 1)
        layout.addWidget(hero)

        info_card = QWidget(page)
        info_card.setObjectName("aboutInfoCard")
        info_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.setSpacing(10)

        license_label = BodyLabel(_tr("SettingsWindow.about_license"), info_card)
        license_label.setWordWrap(True)
        info_layout.addWidget(license_label)

        disclaimer = BodyLabel(_tr("SettingsWindow.about_disclaimer"), info_card)
        disclaimer.setWordWrap(True)
        info_layout.addWidget(disclaimer)
        layout.addWidget(info_card)

        link_label = QLabel(
            _tr(
                "SettingsWindow.about_links",
                repo=PROJECT_REPO_URL,
                license=PROJECT_LICENSE_URL,
            ),
            info_card,
        )
        link_label.setWordWrap(True)
        link_label.setTextFormat(Qt.TextFormat.RichText)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link_label.setOpenExternalLinks(True)
        self._style_about_link(link_label)
        qconfig.themeChanged.connect(lambda: self._style_about_link(link_label))
        info_layout.addWidget(link_label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(10)
        repo_btn = TransparentPushButton(FluentIcon.GITHUB, _tr("SettingsWindow.about_open_repo"), info_card)
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_REPO_URL)))
        license_btn = TransparentPushButton(FluentIcon.HELP, _tr("SettingsWindow.about_open_license"), info_card)
        license_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_LICENSE_URL)))
        btn_row.addWidget(repo_btn)
        btn_row.addWidget(license_btn)
        btn_row.addStretch()
        info_layout.addLayout(btn_row)

        qq_group = "1046229865"
        qq_row = QHBoxLayout()
        qq_row.setContentsMargins(0, 2, 0, 0)
        qq_row.setSpacing(10)
        qq_label = BodyLabel(_tr("SettingsWindow.about_qq_group", qq_group=qq_group), info_card)
        qq_label.setWordWrap(True)
        qq_btn = TransparentPushButton(FluentIcon.PEOPLE, _tr("SettingsWindow.about_open_qq_group"), info_card)
        qq_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_QQ_GROUP_URL)))
        qq_row.addWidget(qq_label)
        qq_row.addWidget(qq_btn)
        qq_row.addStretch()
        info_layout.addLayout(qq_row)

        update_card = QWidget(page)
        update_card.setObjectName("aboutUpdateCard")
        update_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        update_layout = QVBoxLayout(update_card)
        update_layout.setContentsMargins(18, 16, 18, 16)
        update_layout.setSpacing(10)

        update_title = StrongBodyLabel(_tr("SettingsWindow.update_title"), update_card)
        update_layout.addWidget(update_title)

        self._update_status_label = BodyLabel(
            _tr(
                "SettingsWindow.update_idle",
                channel=self._update_channel_label(detect_update_channel()),
            ),
            update_card,
        )
        self._update_status_label.setWordWrap(True)
        update_layout.addWidget(self._update_status_label)

        self._update_detail_label = BodyLabel(_tr("SettingsWindow.update_hint"), update_card)
        self._update_detail_label.setObjectName("aboutUpdateDetail")
        self._update_detail_label.setWordWrap(True)
        update_layout.addWidget(self._update_detail_label)

        update_btn_row = QHBoxLayout()
        update_btn_row.setContentsMargins(0, 2, 0, 0)
        update_btn_row.setSpacing(10)
        self._check_update_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.update_check"), update_card)
        self._check_update_btn.clicked.connect(self._check_for_app_updates)
        self._apply_update_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.update_apply"), update_card)
        self._apply_update_btn.setEnabled(False)
        self._apply_update_btn.clicked.connect(self._apply_pending_app_update)
        update_btn_row.addWidget(self._check_update_btn)
        update_btn_row.addWidget(self._apply_update_btn)
        update_btn_row.addStretch()
        update_layout.addLayout(update_btn_row)
        layout.addWidget(update_card)

        tech = BodyLabel(_tr("SettingsWindow.about_tech"), page)
        tech.setObjectName("aboutTech")
        tech.setWordWrap(True)
        layout.addWidget(tech)

        self._style_about_page(page)
        qconfig.themeChanged.connect(lambda: self._style_about_page(page))
        layout.addStretch()
        return page

    @staticmethod
    def _style_about_page(page: QWidget):
        dark = isDarkTheme()
        hero_bg = "#2b1730" if dark else "#fff0f6"
        hero_border = "#5f2a43" if dark else "#ffd1e2"
        card_bg = "#242424" if dark else "#ffffff"
        card_border = "#3a3a3a" if dark else "#ead8df"
        icon_bg = "#3d1d31" if dark else "#ffffff"
        page_bg = _BG_DARK if dark else _BG_LIGHT
        text = "#f8f4f7" if dark else "#231f24"
        muted = "#cbb8c4" if dark else "#6f5b68"
        page.setStyleSheet(f"""
            QWidget#aboutPage {{
                background: {page_bg};
            }}
            QWidget#aboutHero {{
                background: {hero_bg};
                border: 1px solid {hero_border};
                border-radius: 18px;
            }}
            QLabel#aboutHeroIcon {{
                background: {icon_bg};
                border: 1px solid {hero_border};
                border-radius: 20px;
            }}
            QWidget#aboutInfoCard {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 14px;
            }}
            QWidget#aboutUpdateCard {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 14px;
            }}
            QWidget#aboutHero TitleLabel {{ color: {text}; }}
            QWidget#aboutHero SubtitleLabel {{ color: {text}; font-weight: 700; }}
            QWidget#aboutHero BodyLabel {{ color: {muted}; font-size: 13px; line-height: 1.5; }}
            BodyLabel#aboutVersion {{ color: {text}; font-weight: 700; }}
            QWidget#aboutInfoCard BodyLabel {{ color: {text}; font-size: 13px; }}
            QWidget#aboutUpdateCard BodyLabel {{ color: {text}; font-size: 13px; }}
            QWidget#aboutUpdateCard BodyLabel#aboutUpdateDetail {{ color: {muted}; }}
            BodyLabel#aboutTech {{ color: {muted}; font-size: 13px; padding: 2px 4px; }}
        """)

    @staticmethod
    def _style_about_link(label: QLabel):
        color = BANDORI_PRIMARY_DARK if isDarkTheme() else BANDORI_PRIMARY
        text = "#dcdcdc" if isDarkTheme() else "#303030"
        label.setStyleSheet(f"QLabel {{ color: {text}; font-size: 13px; }} QLabel a {{ color: {color}; }}")

    def _update_channel_label(self, channel: str) -> str:
        return _tr(
            f"SettingsWindow.update_channel_{channel}",
            default=_tr("SettingsWindow.update_channel_unknown"),
        )

    def _check_for_app_updates(self):
        worker = getattr(self, "_update_check_worker", None)
        if worker is not None and worker.isRunning():
            return
        self._pending_update_info = None
        self._check_update_btn.setEnabled(False)
        self._apply_update_btn.setEnabled(False)
        self._apply_update_btn.setText(_tr("SettingsWindow.update_apply"))
        self._update_status_label.setText(_tr("SettingsWindow.update_checking"))
        self._update_detail_label.setText("")

        self._update_check_worker = UpdateCheckWorker(parent=self)
        self._update_check_worker.finished.connect(self._on_app_update_checked)
        self._update_check_worker.error.connect(self._on_app_update_check_error)
        self._update_check_worker.start()

    def _on_app_update_checked(self, info):
        self._update_check_worker = None
        self._check_update_btn.setEnabled(True)
        self._pending_update_info = info if info.can_update else None

        if info.update_available:
            latest = info.latest_version or info.summary
            self._update_status_label.setText(
                _tr("SettingsWindow.update_available", version=latest)
            )
            if info.can_update:
                self._apply_update_btn.setEnabled(True)
                self._apply_update_btn.setText(
                    _tr("SettingsWindow.update_apply_version", version=latest)
                )
            else:
                self._apply_update_btn.setEnabled(False)
                self._apply_update_btn.setText(_tr("SettingsWindow.update_apply"))
        else:
            self._update_status_label.setText(_tr("SettingsWindow.update_none"))
            self._apply_update_btn.setEnabled(False)
            self._apply_update_btn.setText(_tr("SettingsWindow.update_apply"))

        self._update_detail_label.setText(self._format_update_detail(info))

    def _on_app_update_check_error(self, message: str):
        self._update_check_worker = None
        self._check_update_btn.setEnabled(True)
        self._apply_update_btn.setEnabled(False)
        self._update_status_label.setText(_tr("SettingsWindow.update_failed"))
        self._update_detail_label.setText(message)
        InfoBar.error(
            _tr("SettingsWindow.update_failed"),
            message,
            duration=5000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _format_update_detail(self, info) -> str:
        parts = []
        if info.channel:
            parts.append(
                _tr(
                    "SettingsWindow.update_channel_line",
                    channel=self._update_channel_label(info.channel),
                )
            )
        if info.asset_name:
            size = self._format_update_size(info.asset_size)
            parts.append(
                _tr(
                    "SettingsWindow.update_asset_line",
                    asset=info.asset_name,
                    size=size,
                )
            )
        detail = (info.detail or info.summary or "").strip()
        if detail:
            if len(detail) > 420:
                detail = detail[:420].rstrip() + "..."
            parts.append(detail)
        return "\n".join(parts) if parts else _tr("SettingsWindow.update_hint")

    @staticmethod
    def _format_update_size(size: int) -> str:
        if not size:
            return "-"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    def _apply_pending_app_update(self):
        info = getattr(self, "_pending_update_info", None)
        if info is None or not info.can_update:
            return
        worker = getattr(self, "_update_apply_worker", None)
        if worker is not None and worker.isRunning():
            return

        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.update_confirm_title"),
            _tr("SettingsWindow.update_confirm_content"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._check_update_btn.setEnabled(False)
        self._apply_update_btn.setEnabled(False)
        self._update_status_label.setText(_tr("SettingsWindow.update_applying"))
        self._update_detail_label.setText("")

        self._update_apply_worker = UpdateApplyWorker(info, parent=self)
        self._update_apply_worker.finished.connect(self._on_app_update_applied)
        self._update_apply_worker.error.connect(self._on_app_update_apply_error)
        self._update_apply_worker.start()

    def _on_app_update_applied(self, result):
        self._update_apply_worker = None
        self._check_update_btn.setEnabled(True)
        self._apply_update_btn.setEnabled(False)
        self._update_status_label.setText(_tr("SettingsWindow.update_apply_success"))
        self._update_detail_label.setText(result.message)
        InfoBar.success(
            _tr("SettingsWindow.update_apply_success"),
            result.message,
            duration=5000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
        if result.exits_app:
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(800, app.quit)

    def _on_app_update_apply_error(self, message: str):
        self._update_apply_worker = None
        self._check_update_btn.setEnabled(True)
        self._apply_update_btn.setEnabled(getattr(self, "_pending_update_info", None) is not None)
        self._update_status_label.setText(_tr("SettingsWindow.update_apply_failed"))
        self._update_detail_label.setText(message)
        InfoBar.error(
            _tr("SettingsWindow.update_apply_failed"),
            message,
            duration=7000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_quality_changed(self, index: int):
        profile = self._quality_combo.itemData(index)
        self._live2d_quality = normalize_live2d_quality(profile)
        self._quality_detail.setText(self._quality_detail_text(self._live2d_quality))

    def _llm_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_llm_api_url",
                "_llm_api_url_hint",
                "_llm_api_key",
                "_llm_model_id",
                "_llm_aux_api_url",
                "_llm_aux_api_key",
                "_llm_aux_model_id",
                "_llm_aux_enable_thinking",
                "_llm_aux_vision_fallback_enabled",
                "_llm_api_profile_combo",
                "_llm_api_profile_name",
                "_llm_api_mode",
                "_llm_web_search_enabled",
                "_llm_web_search_engine",
                "_llm_web_search_show_sources",
                "_llm_custom_system_prompt",
                "_llm_enable_thinking",
                "_llm_show_reasoning",
                "_user_name",
                "_pov_mode",
                "_pov_custom_prompt",
                "_pov_persona_combo",
                "_pov_role_character",
                "_user_avatar_preview",
                "_user_avatar_reset_btn",
                "_avatar_color_btns",
            )
        )

    def _tts_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_tts_enabled",
                "_tts_api_url",
                "_tts_language",
                "_tts_reference_character",
                "_tts_temperature",
                "_tts_streaming",
                "_tts_translate_to_selected_language",
            )
        )

    def _set_live2d_scale_controls(self, value: int):
        value = _clamp_live2d_scale(value)
        self._live2d_scale = value
        self._live2d_scale_input.blockSignals(True)
        self._live2d_scale_slider.setValue(value)
        self._live2d_scale_input.setText(str(value))
        self._live2d_scale_input.blockSignals(False)

    def _on_live2d_scale_slider_changed(self, value: int):
        self._set_live2d_scale_controls(value)

    def _on_live2d_scale_input_finished(self):
        self._set_live2d_scale_controls(self._live2d_scale_input.text())

    def _style_llm_inputs(self):
        if not self._llm_config_widgets_ready():
            return
        dark = isDarkTheme()
        input_bg = "#282828" if dark else "#ffffff"
        input_border = "#505050" if dark else "#d0d0d0"
        text_color = "#e8e8e8" if dark else "#000000"
        style = f"""
            QLineEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
            QTextEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
        """
        self._llm_api_url.setStyleSheet(style)
        self._llm_api_key.setStyleSheet(style)
        self._llm_model_id.setStyleSheet(style)
        self._llm_aux_api_url.setStyleSheet(style)
        self._llm_aux_api_key.setStyleSheet(style)
        self._llm_aux_model_id.setStyleSheet(style)
        self._llm_api_profile_name.setStyleSheet(style)
        self._llm_custom_system_prompt.setStyleSheet(style)
        self._user_name.setStyleSheet(style)
        self._pov_custom_prompt.setStyleSheet(style)
        hint_color = "#a7b0bf" if dark else "#687385"
        self._llm_api_url_hint.setStyleSheet(f"color: {hint_color}; font-size: 13px;")
        self._llm_active_api_profile_label.setStyleSheet(f"color: {hint_color}; font-size: 13px;")
        self._style_avatar_buttons()
        self._update_user_avatar_preview()

    def _style_tts_inputs(self):
        if not self._tts_config_widgets_ready():
            return
        dark = isDarkTheme()
        input_bg = "#282828" if dark else "#ffffff"
        input_border = "#505050" if dark else "#d0d0d0"
        text_color = "#e8e8e8" if dark else "#000000"
        style = f"""
            QLineEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
            QTextEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
        """
        self._tts_api_url.setStyleSheet(style)
        self._tts_temperature.setStyleSheet(style)
        self._tts_test_text.setStyleSheet(style)

    def _style_avatar_buttons(self):
        for btn in self._avatar_color_btns:
            color = btn.property("avatar_color")
            checked = btn.isChecked()
            btn.setText("\u2713" if checked else "")
            size = 30 if checked else 28
            btn.setFixedSize(size, size)
            border = "3px solid #ffffff" if checked else "2px solid transparent"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: {border};
                    border-radius: {size // 2}px;
                    color: #ffffff;
                    font-weight: 900;
                    font-size: 14px;
                }}
            """)

    def _selected_avatar_color(self) -> str:
        for btn in self._avatar_color_btns:
            if btn.isChecked():
                return btn.property("avatar_color")
        return BANDORI_PRIMARY

    def _avatar_storage_dir(self):
        return app_base_dir() / ".runtime" / "chat_avatars"

    def _choose_user_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.llm_avatar_choose_title"),
            "",
            _tr("SettingsWindow.llm_avatar_image_filter"),
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in _AVATAR_EXTENSIONS:
            return
        try:
            target_dir = self._avatar_storage_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"user_avatar{ext}"
            if os.path.abspath(path) != os.path.abspath(str(target)):
                shutil.copyfile(path, target)
            self._user_avatar_path_pending = str(target)
            self._update_user_avatar_preview()
        except OSError as exc:
            QMessageBox.critical(
                self,
                _tr("SettingsWindow.llm_avatar_save_failed_title"),
                _tr("SettingsWindow.llm_avatar_save_failed_content", error=str(exc)),
            )

    def _reset_user_avatar(self):
        self._user_avatar_path_pending = ""
        self._update_user_avatar_preview()

    def _update_user_avatar_preview(self):
        color = self._selected_avatar_color()
        dark = isDarkTheme()
        border = "#4a4a4a" if dark else "#d8d8d8"
        pixmap = _rounded_avatar_pixmap(self._user_avatar_path_pending, 44)
        if pixmap.isNull():
            name = self._user_name.text().strip()
            self._user_avatar_preview.setPixmap(QPixmap())
            fallback_name = name or _tr("ChatWindow.you")
            self._user_avatar_preview.setText(fallback_name[:1].upper() if fallback_name else "U")
            self._user_avatar_preview.setStyleSheet(f"""
                QLabel {{
                    background: {color};
                    color: #ffffff;
                    border: 1px solid {border};
                    border-radius: 22px;
                    font-size: 17px;
                    font-weight: 800;
                }}
            """)
        else:
            self._user_avatar_preview.setText("")
            self._user_avatar_preview.setPixmap(pixmap)
            self._user_avatar_preview.setStyleSheet(f"""
                QLabel {{
                    background: transparent;
                    border: 1px solid {border};
                    border-radius: 22px;
                }}
            """)
        self._user_avatar_reset_btn.setEnabled(bool(self._user_avatar_path_pending))

    def _on_avatar_color_clicked(self, btn: QPushButton):
        for b in self._avatar_color_btns:
            b.setChecked(False)
        btn.setChecked(True)
        self._style_avatar_buttons()
        self._update_user_avatar_preview()
        self._pulse_button(btn)

    @staticmethod
    def _pulse_button(btn):
        effect = QGraphicsColorizeEffect(btn)
        effect.setColor(QColor(255, 255, 255))
        effect.setStrength(0.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"strength", btn)
        anim.setDuration(120)
        anim.setStartValue(0.7)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: btn.setGraphicsEffect(None))
        anim.start()

    def _load_llm_config(self):
        if self._cfg and self._llm_config_widgets_ready():
            self._llm_api_url.setText(self._cfg.get("llm_api_url", ""))
            self._llm_api_key.setText(self._cfg.get("llm_api_key", ""))
            self._llm_model_id.setText(self._cfg.get("llm_model_id", ""))
            self._llm_aux_api_url.setText(self._cfg.get("llm_aux_api_url", ""))
            self._llm_aux_api_key.setText(self._cfg.get("llm_aux_api_key", ""))
            self._llm_aux_model_id.setText(self._cfg.get("llm_aux_model_id", ""))
            aux_thinking_val = self._cfg.get("llm_aux_enable_thinking", None)
            if aux_thinking_val is True:
                self._llm_aux_enable_thinking.setCurrentIndex(1)
            elif aux_thinking_val is False:
                self._llm_aux_enable_thinking.setCurrentIndex(2)
            else:
                self._llm_aux_enable_thinking.setCurrentIndex(0)
            self._llm_aux_vision_fallback_enabled.setChecked(bool(self._cfg.get("llm_aux_vision_fallback_enabled", False)))
            api_mode = self._cfg.get("llm_api_mode", "chat_completions")
            for i in range(self._llm_api_mode.count()):
                if self._llm_api_mode.itemData(i) == api_mode:
                    self._llm_api_mode.setCurrentIndex(i)
                    break
            self._llm_web_search_enabled.setChecked(bool(self._cfg.get("llm_web_search_enabled", False)))
            web_search_engine = self._cfg.get("llm_web_search_engine", "bing_cn")
            for i in range(self._llm_web_search_engine.count()):
                if self._llm_web_search_engine.itemData(i) == web_search_engine:
                    self._llm_web_search_engine.setCurrentIndex(i)
                    break
            self._llm_web_search_show_sources.setChecked(bool(self._cfg.get("llm_web_search_show_sources", True)))
            self._llm_custom_system_prompt.setPlainText(self._cfg.get("llm_custom_system_prompt", ""))
            self._on_llm_web_search_enabled_changed(self._llm_web_search_enabled.isChecked())
            self._on_llm_api_mode_changed(self._llm_api_mode.currentIndex())
            self._saved_user_name = self._cfg.get("user_name", "")
            self._user_name.setText(self._saved_user_name)
            self._user_avatar_path_pending = str(self._cfg.get("user_avatar_path", "") or "").strip()
            saved_color = self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
            for btn in self._avatar_color_btns:
                btn.setChecked(btn.property("avatar_color") == saved_color)
            self._update_user_avatar_preview()
            thinking_val = self._cfg.get("llm_enable_thinking", None)
            if thinking_val is True:
                self._llm_enable_thinking.setCurrentIndex(1)
            elif thinking_val is False:
                self._llm_enable_thinking.setCurrentIndex(2)
            else:
                self._llm_enable_thinking.setCurrentIndex(0)
            self._llm_show_reasoning.setChecked(bool(self._cfg.get("llm_show_reasoning", True)))
            mode = self._cfg.get("pov_mode", "off")
            for i in range(self._pov_mode.count()):
                if self._pov_mode.itemData(i) == mode:
                    self._pov_mode.setCurrentIndex(i)
                    break
            self._pov_custom_prompt.setPlainText(self._cfg.get("pov_custom_prompt", ""))
            self._reload_pov_persona_combo()
            saved_role = self._cfg.get("pov_role_character", "")
            for i in range(self._pov_role_character.count()):
                if self._pov_role_character.itemData(i) == saved_role:
                    self._pov_role_character.setCurrentIndex(i)
                    break
            self._on_pov_mode_changed(self._pov_mode.currentIndex())
            self._reload_llm_api_profiles(
                self._cfg.get("llm_active_api_profile", "") or self._matching_llm_api_profile_name()
            )
            self._update_current_llm_api_profile_label()

    def _normalized_llm_api_profiles(self) -> list[dict]:
        if not self._cfg:
            return []
        profiles = self._cfg.get("llm_api_profiles", [])
        if not isinstance(profiles, list):
            return []
        normalized = []
        seen = set()
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            name = str(profile.get("name", "") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            api_mode = str(profile.get("llm_api_mode", "chat_completions") or "chat_completions")
            if api_mode not in ("chat_completions", "responses"):
                api_mode = "chat_completions"
            normalized.append({
                "name": name,
                "llm_api_url": str(profile.get("llm_api_url", "") or "").strip(),
                "llm_api_key": str(profile.get("llm_api_key", "") or "").strip(),
                "llm_model_id": str(profile.get("llm_model_id", "") or "").strip(),
                "llm_aux_api_url": str(profile.get("llm_aux_api_url", "") or "").strip(),
                "llm_aux_api_key": str(profile.get("llm_aux_api_key", "") or "").strip(),
                "llm_aux_model_id": str(profile.get("llm_aux_model_id", "") or "").strip(),
                "llm_aux_enable_thinking": profile.get("llm_aux_enable_thinking", None)
                if profile.get("llm_aux_enable_thinking", None) in (True, False, None) else None,
                "llm_aux_vision_fallback_enabled": bool(profile.get("llm_aux_vision_fallback_enabled", False)),
                "llm_api_mode": api_mode,
                "llm_web_search_enabled": bool(profile.get("llm_web_search_enabled", False)),
                "llm_web_search_engine": str(profile.get("llm_web_search_engine", "bing_cn") or "bing_cn"),
                "llm_web_search_show_sources": bool(profile.get("llm_web_search_show_sources", True)),
                "llm_enable_thinking": profile.get("llm_enable_thinking", None)
                if profile.get("llm_enable_thinking", None) in (True, False, None) else None,
                "llm_show_reasoning": bool(profile.get("llm_show_reasoning", True)),
            })
        return normalized

    def _current_llm_api_profile(self, name: str) -> dict:
        thinking_idx = self._llm_enable_thinking.currentIndex()
        thinking = True if thinking_idx == 1 else False if thinking_idx == 2 else None
        aux_thinking_idx = self._llm_aux_enable_thinking.currentIndex()
        aux_thinking = True if aux_thinking_idx == 1 else False if aux_thinking_idx == 2 else None
        return {
            "name": name.strip(),
            "llm_api_url": self._llm_api_url.text().strip(),
            "llm_api_key": self._llm_api_key.text().strip(),
            "llm_model_id": self._llm_model_id.text().strip(),
            "llm_aux_api_url": self._llm_aux_api_url.text().strip(),
            "llm_aux_api_key": self._llm_aux_api_key.text().strip(),
            "llm_aux_model_id": self._llm_aux_model_id.text().strip(),
            "llm_aux_enable_thinking": aux_thinking,
            "llm_aux_vision_fallback_enabled": self._llm_aux_vision_fallback_enabled.isChecked(),
            "llm_api_mode": self._llm_api_mode.itemData(self._llm_api_mode.currentIndex()) or "chat_completions",
            "llm_web_search_enabled": self._llm_web_search_enabled.isChecked(),
            "llm_web_search_engine": self._llm_web_search_engine.itemData(self._llm_web_search_engine.currentIndex()) or "bing_cn",
            "llm_web_search_show_sources": self._llm_web_search_show_sources.isChecked(),
            "llm_enable_thinking": thinking,
            "llm_show_reasoning": self._llm_show_reasoning.isChecked(),
        }

    def _saved_llm_api_profile(self, name: str = "__current__") -> dict:
        if not self._cfg:
            return {"name": name}
        return {
            "name": name.strip(),
            "llm_api_url": str(self._cfg.get("llm_api_url", "") or "").strip(),
            "llm_api_key": str(self._cfg.get("llm_api_key", "") or "").strip(),
            "llm_model_id": str(self._cfg.get("llm_model_id", "") or "").strip(),
            "llm_aux_api_url": str(self._cfg.get("llm_aux_api_url", "") or "").strip(),
            "llm_aux_api_key": str(self._cfg.get("llm_aux_api_key", "") or "").strip(),
            "llm_aux_model_id": str(self._cfg.get("llm_aux_model_id", "") or "").strip(),
            "llm_aux_enable_thinking": self._cfg.get("llm_aux_enable_thinking", None)
            if self._cfg.get("llm_aux_enable_thinking", None) in (True, False, None) else None,
            "llm_aux_vision_fallback_enabled": bool(self._cfg.get("llm_aux_vision_fallback_enabled", False)),
            "llm_api_mode": self._cfg.get("llm_api_mode", "chat_completions") or "chat_completions",
            "llm_web_search_enabled": bool(self._cfg.get("llm_web_search_enabled", False)),
            "llm_web_search_engine": self._cfg.get("llm_web_search_engine", "bing_cn") or "bing_cn",
            "llm_web_search_show_sources": bool(self._cfg.get("llm_web_search_show_sources", True)),
            "llm_enable_thinking": self._cfg.get("llm_enable_thinking", None)
            if self._cfg.get("llm_enable_thinking", None) in (True, False, None) else None,
            "llm_show_reasoning": bool(self._cfg.get("llm_show_reasoning", True)),
        }

    def _llm_profiles_equal(self, left: dict, right: dict) -> bool:
        keys = (
            "llm_api_url",
            "llm_api_key",
            "llm_model_id",
            "llm_aux_api_url",
            "llm_aux_api_key",
            "llm_aux_model_id",
            "llm_aux_enable_thinking",
            "llm_aux_vision_fallback_enabled",
            "llm_api_mode",
            "llm_web_search_enabled",
            "llm_web_search_engine",
            "llm_web_search_show_sources",
            "llm_enable_thinking",
            "llm_show_reasoning",
        )
        return all(left.get(key) == right.get(key) for key in keys)

    def _llm_profile_api_identity_equal(self, left: dict, right: dict) -> bool:
        keys = (
            "llm_api_url",
            "llm_api_key",
            "llm_model_id",
            "llm_aux_api_url",
            "llm_aux_api_key",
            "llm_aux_model_id",
            "llm_aux_enable_thinking",
            "llm_aux_vision_fallback_enabled",
            "llm_api_mode",
        )
        return all(left.get(key) == right.get(key) for key in keys)

    def _matching_llm_api_profile_name(self) -> str:
        current = self._current_llm_api_profile("__current__")
        profiles = self._normalized_llm_api_profiles()
        for profile in profiles:
            if self._llm_profiles_equal(current, profile):
                return profile["name"]

        preferred_names = []
        combo_index = self._llm_api_profile_combo.currentIndex()
        combo_name = ""
        if combo_index >= 0:
            combo_name = self._llm_api_profile_combo.itemData(combo_index) or ""
        if combo_name:
            preferred_names.append(combo_name)
        if self._cfg:
            active_name = str(self._cfg.get("llm_active_api_profile", "") or "").strip()
            if active_name and active_name not in preferred_names:
                preferred_names.append(active_name)

        for name in preferred_names:
            for profile in profiles:
                if profile["name"] == name and self._llm_profile_api_identity_equal(current, profile):
                    return profile["name"]

        for profile in profiles:
            if self._llm_profile_api_identity_equal(current, profile):
                return profile["name"]
        return ""

    def _applied_llm_api_profile_display_name(self) -> tuple[str, bool]:
        if not self._cfg:
            return "", False
        current = self._saved_llm_api_profile("__current__")
        if not (
            current.get("llm_api_url")
            or current.get("llm_api_key")
            or current.get("llm_model_id")
        ):
            return "", False
        profiles = self._normalized_llm_api_profiles()
        for profile in profiles:
            if self._llm_profiles_equal(current, profile):
                return profile["name"], False

        active_name = str(self._cfg.get("llm_active_api_profile", "") or "").strip()
        for profile in profiles:
            if profile["name"] == active_name and self._llm_profile_api_identity_equal(current, profile):
                return profile["name"], True
        for profile in profiles:
            if self._llm_profile_api_identity_equal(current, profile):
                return profile["name"], True
        return "", True

    def _update_current_llm_api_profile_label(self):
        name, modified = self._applied_llm_api_profile_display_name()
        if name:
            key = (
                "SettingsWindow.llm_api_profile_current_modified"
                if modified else
                "SettingsWindow.llm_api_profile_current"
            )
            self._llm_active_api_profile_label.setText(_tr(key, name=name))
        elif modified:
            self._llm_active_api_profile_label.setText(_tr("SettingsWindow.llm_api_profile_current_custom"))
        else:
            self._llm_active_api_profile_label.setText(_tr("SettingsWindow.llm_api_profile_current_none"))

    def _reload_llm_api_profiles(self, selected_name: str = ""):
        self._loading_llm_profile = True
        try:
            profiles = self._normalized_llm_api_profiles()
            current_name = selected_name or self._llm_api_profile_name.text().strip()
            self._llm_api_profile_combo.clear()
            self._llm_api_profile_combo.addItem(_tr("SettingsWindow.llm_api_profile_none", default="未选择"), userData="")
            selected_index = 0
            for profile in profiles:
                self._llm_api_profile_combo.addItem(profile["name"], userData=profile["name"])
                if profile["name"] == current_name:
                    selected_index = self._llm_api_profile_combo.count() - 1
            self._llm_api_profile_combo.setCurrentIndex(selected_index)
            if selected_index > 0:
                self._llm_api_profile_name.setText(current_name)
            elif not selected_name:
                self._llm_api_profile_name.clear()
        finally:
            self._loading_llm_profile = False

    def _apply_llm_api_profile(self, profile: dict):
        self._llm_api_url.setText(profile.get("llm_api_url", ""))
        self._llm_api_key.setText(profile.get("llm_api_key", ""))
        self._llm_model_id.setText(profile.get("llm_model_id", ""))
        self._llm_aux_api_url.setText(profile.get("llm_aux_api_url", ""))
        self._llm_aux_api_key.setText(profile.get("llm_aux_api_key", ""))
        self._llm_aux_model_id.setText(profile.get("llm_aux_model_id", ""))
        aux_thinking = profile.get("llm_aux_enable_thinking", None)
        self._llm_aux_enable_thinking.setCurrentIndex(1 if aux_thinking is True else 2 if aux_thinking is False else 0)
        self._llm_aux_vision_fallback_enabled.setChecked(bool(profile.get("llm_aux_vision_fallback_enabled", False)))
        api_mode = profile.get("llm_api_mode", "chat_completions")
        for i in range(self._llm_api_mode.count()):
            if self._llm_api_mode.itemData(i) == api_mode:
                self._llm_api_mode.setCurrentIndex(i)
                break
        self._llm_web_search_enabled.setChecked(bool(profile.get("llm_web_search_enabled", False)))
        web_search_engine = str(profile.get("llm_web_search_engine", "bing_cn") or "bing_cn")
        for i in range(self._llm_web_search_engine.count()):
            if self._llm_web_search_engine.itemData(i) == web_search_engine:
                self._llm_web_search_engine.setCurrentIndex(i)
                break
        self._llm_web_search_show_sources.setChecked(bool(profile.get("llm_web_search_show_sources", True)))
        self._on_llm_web_search_enabled_changed(self._llm_web_search_enabled.isChecked())
        thinking = profile.get("llm_enable_thinking", None)
        self._llm_enable_thinking.setCurrentIndex(1 if thinking is True else 2 if thinking is False else 0)
        self._llm_show_reasoning.setChecked(bool(profile.get("llm_show_reasoning", True)))
        self._on_llm_api_mode_changed(self._llm_api_mode.currentIndex())

    def _on_llm_api_profile_selected(self, index: int):
        if self._loading_llm_profile or index < 0:
            return
        name = self._llm_api_profile_combo.itemData(index) or ""
        self._llm_api_profile_name.setText(name)
        if not name:
            return
        for profile in self._normalized_llm_api_profiles():
            if profile["name"] == name:
                self._apply_llm_api_profile(profile)
                return

    def _save_llm_api_profile(self):
        if not self._cfg or not self._llm_config_widgets_ready():
            return
        name = self._llm_api_profile_name.text().strip()
        if not name:
            current = self._llm_api_profile_combo.itemData(self._llm_api_profile_combo.currentIndex()) or ""
            name = current.strip()
        if not name:
            InfoBar.warning(
                _tr("SettingsWindow.llm_api_profile_name_required_title", default="需要名称"),
                _tr("SettingsWindow.llm_api_profile_name_required_content", default="请先填写配置名称。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        profiles = [p for p in self._normalized_llm_api_profiles() if p["name"] != name]
        profiles.append(self._current_llm_api_profile(name))
        self._cfg.set("llm_api_profiles", profiles)
        try:
            self._cfg.save()
            self._reload_llm_api_profiles(name)
            self._update_current_llm_api_profile_label()
            InfoBar.success(
                _tr("SettingsWindow.llm_api_profile_saved_title", default="档案已保存"),
                _tr("SettingsWindow.llm_api_profile_saved_content", default="当前 API 配置已保存。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception:
            pass

    def _delete_llm_api_profile(self):
        if not self._cfg or not self._llm_config_widgets_ready():
            return
        name = self._llm_api_profile_combo.itemData(self._llm_api_profile_combo.currentIndex()) or self._llm_api_profile_name.text().strip()
        if not name:
            return
        profiles = [p for p in self._normalized_llm_api_profiles() if p["name"] != name]
        self._cfg.set("llm_api_profiles", profiles)
        if self._cfg.get("llm_active_api_profile", "") == name:
            self._cfg.set("llm_active_api_profile", "")
        try:
            self._cfg.save()
            self._llm_api_profile_name.clear()
            self._reload_llm_api_profiles()
            self._update_current_llm_api_profile_label()
            InfoBar.success(
                _tr("SettingsWindow.llm_api_profile_deleted_title", default="档案已删除"),
                _tr("SettingsWindow.llm_api_profile_deleted_content", default="API 配置档案已删除。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception:
            pass

    def _on_llm_api_mode_changed(self, index: int):
        mode = self._llm_api_mode.itemData(index)
        responses = mode == "responses"
        api_url = self._llm_api_url.text().strip()
        self._llm_web_search_enabled.setEnabled(True)
        self._llm_web_search_engine.setEnabled(
            bool(self._llm_web_search_enabled.isChecked())
        )
        self._llm_web_search_show_sources.setEnabled(
            bool(self._llm_web_search_enabled.isChecked())
        )
        if responses:
            if api_url and not self._supports_openai_responses_api(api_url):
                self._llm_api_url_hint.setText(_tr(
                    "SettingsWindow.llm_api_url_hint_responses_fallback",
                    default="此服务商不支持 OpenAI Responses，运行时会自动使用 Chat Completions 兼容模式；联网、MCP 和 Computer Use 会通过 tool_calls/function calling 接入。",
                ))
            else:
                self._llm_api_url_hint.setText(_tr(
                    'SettingsWindow.llm_api_url_hint_responses',
                    default='Responses 模式可填写 https://api.openai.com/v1/responses；OpenAI 官方可用原生工具，MCP/Computer 相关选项在\u201c工具与电脑控制\u201d页配置。',
                ))
        else:
            self._llm_api_url_hint.setText(_tr(
                'SettingsWindow.llm_api_url_hint_chat_tools',
                default='别忘记在 API 地址末尾写 /v1/chat/completions。Chat Completions 兼容接口也可以通过 tool_calls/function calling 使用工具；联网搜索、本地 MCP 代理和 Computer Use 的开关在\u201c工具与电脑控制\u201d页。',
            ))

    def _on_llm_web_search_enabled_changed(self, enabled: bool):
        self._llm_web_search_engine.setEnabled(bool(enabled))
        self._llm_web_search_show_sources.setEnabled(bool(enabled))

    def _supports_openai_responses_api(self, api_url: str) -> bool:
        return "api.openai.com" in (api_url or "").lower()

    def _effective_llm_api_mode(self) -> str:
        mode = self._llm_api_mode.itemData(self._llm_api_mode.currentIndex())
        if mode == "responses" and self._supports_openai_responses_api(self._llm_api_url.text().strip()):
            return "responses"
        return "chat_completions"

    def _load_tts_config(self):
        if self._cfg and self._tts_config_widgets_ready():
            self._tts_enabled.setChecked(bool(self._cfg.get("tts_enabled", False)))
            self._tts_api_url.setText(self._cfg.get("tts_api_url", "http://127.0.0.1:9880/"))
            saved_tts_language = self._cfg.get("tts_language", "Chinese")
            for i in range(self._tts_language.count()):
                if self._tts_language.itemData(i) == saved_tts_language:
                    self._tts_language.setCurrentIndex(i)
                    break
            saved_ref = self._cfg.get("tts_reference_character", "")
            for i in range(self._tts_reference_character.count()):
                if self._tts_reference_character.itemData(i) == saved_ref:
                    self._tts_reference_character.setCurrentIndex(i)
                    break
            self._tts_temperature.setText(str(self._cfg.get("tts_temperature", 0.9)))
            self._tts_streaming.setChecked(bool(self._cfg.get("tts_streaming", True)))
            self._tts_translate_to_selected_language.setChecked(bool(self._cfg.get("tts_translate_to_selected_language", True)))

    def _on_pov_mode_changed(self, index: int):
        mode = self._pov_mode.itemData(index) or "off"
        self._pov_custom_prompt.setEnabled(mode == "custom")
        self._pov_persona_combo.setEnabled(mode == "custom")
        self._pov_role_character.setEnabled(mode == "role")
        self._user_name.setEnabled(mode != "role")
        if mode == "role":
            self._sync_role_display_name()
        else:
            self._user_name.setText(self._saved_user_name)

    def _normalized_pov_personas(self) -> list[dict]:
        if not self._cfg:
            return []
        raw_personas = self._cfg.get("pov_custom_personas", [])
        if not isinstance(raw_personas, list):
            return []
        personas = []
        seen_prompts = set()
        for item in raw_personas:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt", "") or "").strip()
            if not prompt or prompt in seen_prompts:
                continue
            title = str(item.get("title", "") or "").strip() or self._pov_persona_title(prompt)
            personas.append({"title": title, "prompt": prompt})
            seen_prompts.add(prompt)
        return personas

    def _reload_pov_persona_combo(self):
        current_prompt = self._pov_custom_prompt.toPlainText().strip()
        self._pov_persona_combo.blockSignals(True)
        self._pov_persona_combo.clear()
        self._pov_persona_combo.addItem(_tr("SettingsWindow.pov_persona_new"), userData="")
        selected_index = 0
        for persona in self._normalized_pov_personas():
            self._pov_persona_combo.addItem(persona["title"], userData=persona["prompt"])
            if persona["prompt"] == current_prompt:
                selected_index = self._pov_persona_combo.count() - 1
        self._pov_persona_combo.setCurrentIndex(selected_index)
        self._pov_persona_combo.blockSignals(False)

    def _on_pov_persona_selected(self, index: int):
        prompt = self._pov_persona_combo.itemData(index) or ""
        for i in range(self._pov_mode.count()):
            if self._pov_mode.itemData(i) == "custom":
                self._pov_mode.setCurrentIndex(i)
                break
        if not prompt:
            self._pov_custom_prompt.clear()
            return
        self._pov_custom_prompt.setPlainText(prompt)

    @staticmethod
    def _pov_persona_title(prompt: str) -> str:
        title = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
        if len(title) > 24:
            title = title[:24] + "..."
        return title or "Persona"

    def _save_current_pov_persona(self):
        if not self._cfg:
            return
        prompt = self._pov_custom_prompt.toPlainText().strip()
        if not prompt:
            InfoBar.warning(
                _tr("SettingsWindow.pov_persona_empty_title"),
                _tr("SettingsWindow.pov_persona_empty_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        personas = [p for p in self._normalized_pov_personas() if p.get("prompt") != prompt]
        personas.append({"title": self._pov_persona_title(prompt), "prompt": prompt})
        self._cfg.set("pov_custom_personas", personas)
        self._cfg.set("pov_custom_prompt", prompt)
        try:
            self._cfg.save()
        except Exception:
            return
        self._reload_pov_persona_combo()
        InfoBar.success(
            _tr("SettingsWindow.pov_persona_saved_title"),
            _tr("SettingsWindow.pov_persona_saved_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _delete_current_pov_persona(self):
        if not self._cfg:
            return
        prompt = self._pov_persona_combo.itemData(self._pov_persona_combo.currentIndex()) or ""
        if not prompt:
            return
        personas = [p for p in self._normalized_pov_personas() if p.get("prompt") != prompt]
        self._cfg.set("pov_custom_personas", personas)
        try:
            self._cfg.save()
        except Exception:
            return
        self._reload_pov_persona_combo()
        InfoBar.success(
            _tr("SettingsWindow.pov_persona_deleted_title"),
            _tr("SettingsWindow.pov_persona_deleted_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _sync_role_display_name(self):
        if self._pov_mode.itemData(self._pov_mode.currentIndex()) != "role":
            return
        self._user_name.setText(self._pov_role_character.currentText())

    def _save_llm_config(self, source: str = "llm", show_info: bool = True):
        if self._cfg and self._llm_config_widgets_ready():
            self._cfg.set("llm_api_url", self._llm_api_url.text().strip())
            self._cfg.set("llm_api_key", self._llm_api_key.text().strip())
            self._cfg.set("llm_model_id", self._llm_model_id.text().strip())
            self._cfg.set("llm_aux_api_url", self._llm_aux_api_url.text().strip())
            self._cfg.set("llm_aux_api_key", self._llm_aux_api_key.text().strip())
            self._cfg.set("llm_aux_model_id", self._llm_aux_model_id.text().strip())
            aux_thinking_idx = self._llm_aux_enable_thinking.currentIndex()
            if aux_thinking_idx == 1:
                self._cfg.set("llm_aux_enable_thinking", True)
            elif aux_thinking_idx == 2:
                self._cfg.set("llm_aux_enable_thinking", False)
            else:
                self._cfg.set("llm_aux_enable_thinking", None)
            self._cfg.set("llm_aux_vision_fallback_enabled", self._llm_aux_vision_fallback_enabled.isChecked())
            self._cfg.set("llm_api_mode", self._llm_api_mode.itemData(self._llm_api_mode.currentIndex()) or "chat_completions")
            self._cfg.set("llm_web_search_enabled", self._llm_web_search_enabled.isChecked())
            self._cfg.set("llm_web_search_engine", self._llm_web_search_engine.itemData(self._llm_web_search_engine.currentIndex()) or "bing_cn")
            self._cfg.set("llm_web_search_show_sources", self._llm_web_search_show_sources.isChecked())
            self._cfg.set("llm_custom_system_prompt", self._llm_custom_system_prompt.toPlainText().strip())
            pov_mode = self._pov_mode.itemData(self._pov_mode.currentIndex()) or "off"
            if pov_mode == "role":
                user_name = self._pov_role_character.currentText().strip()
            else:
                self._saved_user_name = self._user_name.text().strip()
                user_name = self._saved_user_name
            self._cfg.set("user_name", user_name)
            self._cfg.set("pov_mode", pov_mode)
            self._cfg.set("pov_custom_prompt", self._pov_custom_prompt.toPlainText().strip())
            self._cfg.set("pov_role_character", self._pov_role_character.itemData(self._pov_role_character.currentIndex()) or "")
            self._cfg.set("user_avatar_path", self._user_avatar_path_pending)
            for btn in self._avatar_color_btns:
                if btn.isChecked():
                    self._cfg.set("user_avatar_color", btn.property("avatar_color"))
                    break
            thinking_idx = self._llm_enable_thinking.currentIndex()
            if thinking_idx == 1:
                self._cfg.set("llm_enable_thinking", True)
            elif thinking_idx == 2:
                self._cfg.set("llm_enable_thinking", False)
            else:
                self._cfg.set("llm_enable_thinking", None)
            self._cfg.set("llm_show_reasoning", self._llm_show_reasoning.isChecked())
            active_profile = self._matching_llm_api_profile_name()
            self._cfg.set("llm_active_api_profile", active_profile)
            try:
                self._cfg.save()
                self._reload_llm_api_profiles(active_profile)
                self._update_current_llm_api_profile_label()
                if show_info:
                    title_key = "SettingsWindow.pov_saved_title" if source == "pov" else "SettingsWindow.llm_saved_title"
                    content_key = "SettingsWindow.pov_saved_content" if source == "pov" else "SettingsWindow.llm_saved_content"
                    InfoBar.success(
                        _tr(title_key),
                        _tr(content_key),
                        duration=2000,
                        position=InfoBarPosition.TOP,
                        parent=self,
                    )
            except Exception:
                pass

    def _current_tts_config(self, include_llm: bool = False) -> dict:
        try:
            temperature = max(0.01, min(2.0, float(self._tts_temperature.text().strip() or "0.9")))
        except ValueError:
            temperature = 0.9
        self._tts_temperature.setText(str(temperature))
        config = {
            "tts_enabled": self._tts_enabled.isChecked(),
            "tts_api_url": self._tts_api_url.text().strip() or "http://127.0.0.1:9880/",
            "tts_language": self._tts_language.itemData(self._tts_language.currentIndex()) or "Chinese",
            "tts_reference_character": self._tts_reference_character.itemData(self._tts_reference_character.currentIndex()) or "",
            "tts_temperature": temperature,
            "tts_streaming": self._tts_streaming.isChecked(),
            "tts_translate_to_selected_language": self._tts_translate_to_selected_language.isChecked(),
        }
        if include_llm and self._cfg:
            for key in (
                "llm_api_url",
                "llm_api_key",
                "llm_model_id",
                "llm_aux_api_url",
                "llm_aux_api_key",
                "llm_aux_model_id",
                "llm_aux_enable_thinking",
            ):
                config[key] = self._cfg.get(key, None)
        return config

    def _save_tts_config(self, show_info: bool = True):
        if self._cfg and self._tts_config_widgets_ready():
            config = self._current_tts_config()
            for key, value in config.items():
                self._cfg.set(key, value)
            try:
                self._cfg.save()
                if show_info:
                    InfoBar.success(
                        _tr("SettingsWindow.tts_saved_title"),
                        _tr("SettingsWindow.tts_saved_content"),
                        duration=2000,
                        position=InfoBarPosition.TOP,
                        parent=self,
                    )
            except Exception:
                pass

    def _test_tts(self):
        if getattr(self, "_tts_test_running", False):
            return
        if not _ensure_settings_tts_available():
            self._set_tts_test_running(False)
            InfoBar.warning(
                _tr("SettingsWindow.tts_test_unavailable_title", default="TTS 不可用"),
                _tr("SettingsWindow.tts_test_unavailable_content", default="当前环境缺少 TTS 播放依赖，无法进行测试播放。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not (self._cfg and self._tts_config_widgets_ready()):
            return

        config = self._current_tts_config(include_llm=True)
        test_text = self._tts_test_text.toPlainText().strip()
        if not test_text:
            test_text = _tr("SettingsWindow.tts_test_default_text", default="你好，这是一段 TTS 测试语音。")

        test_character = str(config.get("tts_reference_character", "") or "").strip() or self._current_char
        if not test_character:
            for index in range(self._tts_reference_character.count()):
                candidate = str(self._tts_reference_character.itemData(index) or "").strip()
                if candidate:
                    test_character = candidate
                    break
        if not test_character:
            InfoBar.warning(
                _tr("SettingsWindow.tts_test_missing_reference_title", default="缺少参考音频"),
                _tr("SettingsWindow.tts_test_missing_reference_content", default="请先选择参考音频角色，或确保当前模型角色有对应参考音频。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        self._save_tts_config(show_info=False)
        self._stop_tts_test_playback()
        self._set_tts_test_running(True)
        self._tts_test_failed = False
        self._tts_test_received_audio = False
        if getattr(self, "_tts_test_player", None) is None:
            self._tts_test_player = TTSPlayer(self)
            self._tts_test_player.error.connect(self._on_tts_test_error)
            self._tts_test_player.playback_finished.connect(self._on_tts_test_playback_finished)
        self._tts_test_worker = TTSRequestWorker(0, 0, test_text, test_character, config, self)
        self._tts_test_worker.audio_ready.connect(self._on_tts_test_audio_ready)
        self._tts_test_worker.error.connect(self._on_tts_test_error)
        self._tts_test_worker.finished.connect(self._on_tts_test_finished)
        self._tts_test_worker.start()

    def _set_tts_test_running(self, running: bool):
        self._tts_test_running = running
        button = getattr(self, "_tts_test_button", None)
        if button is not None:
            button.setEnabled(_SETTINGS_TTS_AVAILABLE and not running)

    def _stop_tts_test_playback(self):
        worker = getattr(self, "_tts_test_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(2000)
        player = getattr(self, "_tts_test_player", None)
        if player is not None:
            player.stop()

    def _on_tts_test_audio_ready(self, _sequence: int, _generation: int, audio: bytes, media_type: str):
        if not audio or getattr(self, "_tts_test_player", None) is None:
            return
        self._tts_test_received_audio = True
        self._tts_test_player.enqueue(audio, media_type)

    def _on_tts_test_finished(self):
        if getattr(self, "_tts_test_failed", False):
            self._set_tts_test_running(False)
            return
        if not getattr(self, "_tts_test_received_audio", False):
            self._set_tts_test_running(False)
            InfoBar.warning(
                _tr("SettingsWindow.tts_test_empty_title", default="测试未返回音频"),
                _tr("SettingsWindow.tts_test_empty_content", default="TTS 请求已完成，但没有收到可播放的音频数据。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        InfoBar.success(
            _tr("SettingsWindow.tts_test_success_title", default="正在播放测试语音"),
            _tr("SettingsWindow.tts_test_success_content", default="已收到 TTS 音频并开始播放。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_tts_test_playback_finished(self):
        self._set_tts_test_running(False)

    def _on_tts_test_error(self, msg: str):
        self._tts_test_failed = True
        self._set_tts_test_running(False)
        player = getattr(self, "_tts_test_player", None)
        if player is not None:
            player.stop()
        InfoBar.error(
            _tr("SettingsWindow.tts_test_failed_title", default="TTS 测试失败"),
            msg,
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _default_chat_backup_path(self) -> str:
        name = "bandori-chat-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
        return str(app_base_dir() / name)

    def _export_chat_database(self):
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _tr("SettingsWindow.chat_data_export_dialog"),
            self._default_chat_backup_path(),
            _tr("SettingsWindow.chat_data_filter"),
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".db"

        try:
            from database_manager import export_chat_database

            summary = export_chat_database(path)
            InfoBar.success(
                _tr("SettingsWindow.chat_data_export_title"),
                _tr(
                    "SettingsWindow.chat_data_export_content",
                    conversations=summary["conversations"],
                    messages=summary["messages"],
                    group_messages=summary.get("group_messages", 0),
                ),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            self._show_chat_data_error(exc)

    def _import_chat_database(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.chat_data_import_dialog"),
            str(app_base_dir()),
            _tr("SettingsWindow.chat_data_filter"),
        )
        if not path:
            return

        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.chat_data_import_confirm_title"),
            _tr("SettingsWindow.chat_data_import_confirm_content"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from database_manager import import_chat_database

            summary = import_chat_database(path)
            InfoBar.success(
                _tr("SettingsWindow.chat_data_import_title"),
                _tr(
                    "SettingsWindow.chat_data_import_content",
                    conversations=summary["conversations"],
                    messages=summary["messages"],
                    group_messages=summary.get("group_messages", 0),
                ),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            self._show_chat_data_error(exc)

    def _show_chat_data_error(self, exc: Exception):
        InfoBar.error(
            _tr("SettingsWindow.chat_data_failed_title"),
            str(exc),
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _test_connection(self):
        api_url = self._llm_api_url.text().strip()
        api_key = self._llm_api_key.text().strip()
        model_id = self._llm_model_id.text().strip()

        if not api_url or not api_key or not model_id:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_config_title"),
                _tr("SettingsWindow.llm_missing_config_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        if hasattr(self, '_test_worker') and self._test_worker is not None:
            if self._test_worker.isRunning():
                self._test_worker.quit()
                self._test_worker.wait(2000)

        api_mode = self._effective_llm_api_mode() if hasattr(self, "_llm_api_mode") else "chat_completions"
        self._test_worker = TestConnectionWorker(api_url, api_key, model_id, api_mode, parent=self)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.error.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_finished(self):
        InfoBar.success(
            _tr("SettingsWindow.llm_connected_title"),
            _tr("SettingsWindow.llm_connected_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_test_error(self, msg: str):
        InfoBar.error(
            _tr("SettingsWindow.llm_connection_failed_title"),
            msg,
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _fetch_models(self, target_input=None):
        self._llm_model_fetch_target = target_input or self._llm_model_id
        is_aux_target = target_input is self._llm_aux_model_id
        api_url = (self._llm_aux_api_url.text().strip() if is_aux_target else "") or self._llm_api_url.text().strip()
        api_key = (self._llm_aux_api_key.text().strip() if is_aux_target else "") or self._llm_api_key.text().strip()

        if not api_url or not api_key:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_api_title"),
                _tr("SettingsWindow.llm_missing_api_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        models_url = models_api_url(api_url)

        if hasattr(self, '_fetch_worker') and self._fetch_worker is not None:
            if self._fetch_worker.isRunning():
                self._fetch_worker.quit()
                self._fetch_worker.wait(2000)

        self._fetch_worker = FetchModelsWorker(models_url, api_key, parent=self)
        self._fetch_worker.finished.connect(self._on_models_fetched)
        self._fetch_worker.error.connect(self._on_test_error)
        self._fetch_worker.start()

    def _on_models_fetched(self, models: list[str]):
        target = self._llm_model_fetch_target
        if target is self._llm_aux_model_id:
            label = self._llm_aux_model_combo_label
            scroll = self._llm_aux_model_scroll
        else:
            list_widget = self._llm_primary_model_list
            list_layout = self._llm_primary_model_list_layout
            label = self._llm_primary_model_combo_label
            scroll = self._llm_primary_model_scroll

        while list_layout.count():
            item = list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        dark = isDarkTheme()
        for idx, model_name in enumerate(models):
            btn = QPushButton(model_name, list_widget)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left;
                    padding: 6px 14px;
                    border: none;
                    border-radius: 6px;
                    background: transparent;
                    font-size: 13px;
                    color: {'#e8e8e8' if dark else '#333333'};
                }}
                QPushButton:hover {{
                    background: {BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER};
                }}
            """)
            btn.clicked.connect(lambda checked, mn=model_name: self._set_fetched_model_id(mn))
            list_layout.addWidget(btn)
            QTimer.singleShot(idx * 30, lambda b=btn: self._animate_button_in(b))
        list_layout.addStretch()

        label.show()
        scroll.show()

    def _set_fetched_model_id(self, model_name: str):
        target = self._llm_model_fetch_target
        target.setText(model_name)

    def _build_side_panel(self):
        panel = self._make_theme_widget(QWidget())
        panel.setObjectName("settingsSidePanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(240)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        settings_title = StrongBodyLabel(_tr("SettingsWindow.side_settings"), panel)
        layout.addWidget(settings_title)

        fps_label = BodyLabel(_tr("SettingsWindow.side_fps"), panel)
        layout.addWidget(fps_label)
        self._fps_slider = Slider(Qt.Orientation.Horizontal, panel)
        self._fps_slider.setRange(30, 240)
        self._fps_slider.setValue(self._fps)
        self._fps_slider.setSingleStep(10)
        self._fps_value = BodyLabel(_tr("SettingsWindow.fps_value", v=self._fps), panel)
        self._fps_slider.valueChanged.connect(
            lambda v: self._fps_value.setText(_tr("SettingsWindow.fps_value", v=v))
        )
        layout.addWidget(self._fps_slider)
        layout.addWidget(self._fps_value)

        vsync_label = BodyLabel(_tr("SettingsWindow.side_vsync"), panel)
        self._vsync_switch = SwitchButton(panel)
        self._vsync_switch.setChecked(self._vsync)
        self._vsync_switch.checkedChanged.connect(self._on_vsync_changed)
        vsync_row = QHBoxLayout()
        vsync_row.addWidget(vsync_label)
        vsync_row.addStretch()
        vsync_row.addWidget(self._vsync_switch)
        layout.addLayout(vsync_row)

        if self._vsync:
            self._fps_slider.setEnabled(False)
            self._fps_value.setEnabled(False)

        game_topmost_label = BodyLabel(_tr("SettingsWindow.side_game_topmost"), panel)
        self._game_topmost_switch = SwitchButton(panel)
        self._game_topmost_switch.setChecked(self._game_topmost)
        game_topmost_row = QHBoxLayout()
        game_topmost_row.addWidget(game_topmost_label)
        game_topmost_row.addStretch()
        game_topmost_row.addWidget(self._game_topmost_switch)
        layout.addLayout(game_topmost_row)

        hide_live2d_label = BodyLabel(_tr("SettingsWindow.side_hide_live2d_model"), panel)
        self._hide_live2d_model_switch = SwitchButton(panel)
        self._hide_live2d_model_switch.setChecked(self._hide_live2d_model)
        hide_live2d_row = QHBoxLayout()
        hide_live2d_row.addWidget(hide_live2d_label)
        hide_live2d_row.addStretch()
        hide_live2d_row.addWidget(self._hide_live2d_model_switch)
        layout.addLayout(hide_live2d_row)

        auto_start_label = BodyLabel(_tr("SettingsWindow.side_auto_start"), panel)
        self._auto_start_switch = SwitchButton(panel)
        self._auto_start_switch.setChecked(self._auto_start_enabled)
        self._auto_start_switch.setEnabled(self._auto_start_supported)
        if not self._auto_start_supported:
            self._auto_start_switch.setToolTip(_tr("SettingsWindow.auto_start_unsupported"))
            auto_start_label.setToolTip(_tr("SettingsWindow.auto_start_unsupported"))
        auto_start_row = QHBoxLayout()
        auto_start_row.addWidget(auto_start_label)
        auto_start_row.addStretch()
        auto_start_row.addWidget(self._auto_start_switch)
        layout.addLayout(auto_start_row)

        opacity_label = BodyLabel(_tr("SettingsWindow.side_opacity"), panel)
        layout.addWidget(opacity_label)
        self._opacity_slider = Slider(Qt.Orientation.Horizontal, panel)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_value = BodyLabel(_tr("SettingsWindow.opacity_value", v=int(self._opacity * 100)), panel)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_value.setText(_tr("SettingsWindow.opacity_value", v=v))
        )
        layout.addWidget(self._opacity_slider)
        layout.addWidget(self._opacity_value)

        layout.addSpacing(8)

        theme_label = BodyLabel(_tr("SettingsWindow.side_dark_theme"), panel)
        self._theme_switch = SwitchButton(panel)
        self._theme_switch.setChecked(isDarkTheme())
        self._theme_switch.checkedChanged.connect(
            lambda v: apply_app_theme(v)
        )
        theme_row = QHBoxLayout()
        theme_row.addWidget(theme_label)
        theme_row.addStretch()
        theme_row.addWidget(self._theme_switch)
        layout.addLayout(theme_row)

        lang_label = BodyLabel(_tr("SettingsWindow.language"), panel)
        self._lang_combo = OpaqueDropDownComboBox(panel)
        self._lang_combo.setMinimumWidth(120)
        langs = available_languages()
        current = current_language()
        for lang in langs:
            display = _tr(f"Language.{lang}", default=lang)
            self._lang_combo.addItem(display, userData=lang)
            if lang == current:
                self._lang_combo.setCurrentIndex(self._lang_combo.count() - 1)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row = QHBoxLayout()
        lang_row.addWidget(lang_label)
        lang_row.addStretch()
        lang_row.addWidget(self._lang_combo)
        layout.addLayout(lang_row)

        layout.addStretch()

        btn_text = _tr("SettingsWindow.apply_launch") if self._show_launch else _tr("SettingsWindow.apply")
        self._apply_btn = PrimaryPushButton(FluentIcon.ACCEPT, btn_text, panel)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        list_title = StrongBodyLabel(_tr("SettingsWindow.model_list_title"), panel)
        layout.addWidget(list_title)

        self._model_list_scroll = ScrollArea(panel)
        self._model_list_scroll.setWidgetResizable(True)
        self._model_list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._model_list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._model_list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._model_list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._model_list_widget = QWidget(panel)
        self._model_list_widget.setObjectName("modelListWidget")
        self._model_list_layout = QVBoxLayout(self._model_list_widget)
        self._model_list_layout.setContentsMargins(0, 0, 0, 0)
        self._model_list_layout.setSpacing(6)
        self._model_list_scroll.setWidget(self._model_list_widget)
        layout.addWidget(self._model_list_scroll, 1)
        self._update_model_list_style()
        qconfig.themeChanged.connect(self._update_model_list_style)
        self._update_side_panel_style()
        qconfig.themeChanged.connect(self._update_side_panel_style)

        return panel

    def _update_side_panel_style(self):
        dark = isDarkTheme()
        bg = "#232125" if dark else "#fff8fb"
        border = "#3b343a" if dark else "#f1d7e1"
        title = "#fff6fb" if dark else "#2b2228"
        muted = "#d4c3cc" if dark else "#6a5b63"
        self._model_list_scroll.parentWidget().setStyleSheet(f"""
            QWidget#settingsSidePanel {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 16px;
            }}
            QWidget#settingsSidePanel StrongBodyLabel {{ color: {title}; font-size: 14px; font-weight: 700; }}
            QWidget#settingsSidePanel BodyLabel {{ color: {muted}; font-size: 13px; }}
        """)

    def _update_model_list_style(self):
        self._model_list_widget.setStyleSheet("""
            #modelListWidget {
                background: transparent;
                border: none;
            }
        """)

    def _save_configured_models(self):
        if not self._cfg:
            return
        for item in self._configured_models:
            self._archive_model_action_profile(item)
        selected = self._selected_model_item()
        if selected:
            self._cfg.set("character", selected["character"])
            self._cfg.set("costume", selected["costume"])
        elif self._configured_models:
            self._cfg.set("character", self._configured_models[0]["character"])
            self._cfg.set("costume", self._configured_models[0]["costume"])
        else:
            self._cfg.set("character", "")
            self._cfg.set("costume", "")
        self._cfg.set("models", [dict(item) for item in self._configured_models])
        self._cfg.save()

    def _refresh_model_list(self):
        while self._model_list_layout.count():
            item = self._model_list_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
            if item:
                del item
        for item in self._configured_models:
            character = item["character"]
            costume = item["costume"]
            title = self._model_manager.get_display_name(character)
            subtitle = self._model_manager.get_costume_display_name(character, costume)
            row = ModelListItem(character, title, subtitle, character == self._selected_list_character, self._model_list_widget)
            row.selected.connect(self._select_model_list_item)
            row.remove_requested.connect(self._remove_model_list_item)
            self._model_list_layout.addWidget(row)
        add_row = AddModelListItem(self._model_list_widget)
        add_row.add_requested.connect(self._add_model_from_list)
        self._model_list_layout.addWidget(add_row)

    def _select_model_list_item(self, character: str):
        for item in self._configured_models:
            if item["character"] == character:
                self._activate_char_page_for_model_list()
                self._selected_list_character = character
                self._editing_list_character = ""
                self._editing_model_index = None
                self._adding_model = False
                self._current_char = character
                self._current_costume = item["costume"]
                self._selected_costume = item["costume"]
                self._selected_band = self._model_manager.get_character_band(character)
                self._refresh_model_list()
                self._show_model_detail()
                return

    def _add_model_from_list(self):
        self._activate_char_page_for_model_list()
        self._selected_list_character = ""
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = True
        self._refresh_model_list()
        self._enter_model_selection()

    def _remove_model_list_item(self, character: str):
        self._activate_char_page_for_model_list()
        if len(self._configured_models) <= 1:
            InfoBar.warning(
                _tr("SettingsWindow.model_list_keep_one_title"),
                _tr("SettingsWindow.model_list_keep_one_content"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._configured_models = [item for item in self._configured_models if item["character"] != character]
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = False
        if self._selected_list_character == character:
            if self._configured_models:
                self._select_model_list_item(self._configured_models[0]["character"])
            else:
                self._selected_list_character = ""
        self._refresh_model_list()
        if self._selected_list_character:
            self._show_model_detail()
        else:
            self._enter_model_selection()

    def _upsert_configured_model(self, character: str, costume: str):
        path = self._model_manager.get_model_json_path(character, costume)
        if not path:
            return
        window_width = 400
        window_height = 500
        window_x = -1
        window_y = -1
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            window_x = geo.left() + (geo.width() - window_width) // 2
            window_y = geo.top() + (geo.height() - window_height) // 2
        entry = {
            "character": character,
            "costume": costume,
            "path": path,
            "window_x": window_x,
            "window_y": window_y,
            "window_width": window_width,
            "window_height": window_height,
            "pixel_window_x": -1,
            "pixel_window_y": -1,
            "pet_mode": "live2d",
            "default_motion": "",
            "default_expression": "",
            "click_motion_actions": {},
        }
        self._restore_model_action_profile(entry)
        replace_index = self._editing_model_index
        if replace_index is None and not self._adding_model:
            replace_character = self._editing_list_character or self._selected_list_character
            for idx, item in enumerate(self._configured_models):
                if item["character"] == replace_character:
                    replace_index = idx
                    break
        if replace_index is not None and 0 <= replace_index < len(self._configured_models):
            previous = self._configured_models[replace_index]
            self._archive_model_action_profile(previous)
            preserved = dict(self._configured_models[replace_index])
            preserved.update(entry)
            preserve_keys = (
                "window_x",
                "window_y",
                "window_width",
                "window_height",
                "pixel_window_x",
                "pixel_window_y",
                "pet_mode",
            )
            if previous.get("character") == character and previous.get("costume") == costume:
                preserve_keys += (
                    "default_motion",
                    "default_expression",
                    "click_motion_actions",
                )
            for key in preserve_keys:
                if key in self._configured_models[replace_index]:
                    preserved[key] = self._configured_models[replace_index][key]
            entry = preserved
            self._configured_models[replace_index] = entry
        else:
            for idx, item in enumerate(self._configured_models):
                if item["character"] == character:
                    self._archive_model_action_profile(item)
                    preserved = dict(item)
                    preserved.update(entry)
                    preserve_keys = (
                        "window_x",
                        "window_y",
                        "window_width",
                        "window_height",
                        "pixel_window_x",
                        "pixel_window_y",
                        "pet_mode",
                    )
                    if item.get("costume") == costume:
                        preserve_keys += (
                            "default_motion",
                            "default_expression",
                            "click_motion_actions",
                        )
                    for key in preserve_keys:
                        if key in item:
                            preserved[key] = item[key]
                    entry = preserved
                    self._configured_models[idx] = entry
                    break
            else:
                self._configured_models.append(entry)
        self._selected_list_character = character
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = False
        self._refresh_model_list()
        if not self._selecting_model:
            self._show_model_detail()

    def _on_char_selected(self, char_key: str):
        self._selecting_model = True
        self._current_char = char_key
        self._selected_band = self._model_manager.get_character_band(char_key)
        self._populate_costumes(char_key)
        display = self._model_manager.get_display_name(char_key)
        self._costume_title.setText(_tr("SettingsWindow.costumes_title", display=display))
        self._costume_subtitle.setText(
            _tr("SettingsWindow.costume_subtitle", display=display)
        )
        self._char_page.hide()
        self._costume_page.show()
        self._current_page = "costumes"

    def _on_band_selected(self, band_id: str):
        self._populate_characters(band_id)

    def _populate_costumes(self, char_key: str):
        for btn in self._costume_buttons:
            self._costume_list.removeWidget(btn)
            btn.deleteLater()
        self._costume_buttons.clear()

        costumes = self._model_manager.get_costumes(char_key)
        for idx, costume in enumerate(costumes):
            cid = costume["id"]
            cname = self._model_manager.get_costume_display_name(char_key, cid)
            btn = CostumeItem(cid, cname, self._costume_list_widget)
            btn.clicked.connect(lambda checked, b=btn, c=cid: self._on_costume_clicked(b, c))
            btn.preview_requested.connect(self._show_costume_preview)
            btn.preview_cancelled.connect(self._hide_costume_preview)
            btn.animate_in(delay_ms=idx * 40)
            self._costume_buttons.append(btn)
            self._costume_list.insertWidget(self._costume_list.count() - 1, btn)

        if self._costume_buttons:
            default_id = next(
                (item["costume"] for item in self._configured_models if item["character"] == char_key),
                self._model_manager.get_default_costume(char_key),
            )
            for btn in self._costume_buttons:
                if btn.costume_id == default_id:
                    btn.setChecked(True)
                    self._selected_costume = default_id
                    break

    def _on_costume_clicked(self, btn: CostumeItem, costume_id: str):
        for b in self._costume_buttons:
            b.setChecked(False)
        btn.setChecked(True)
        self._selected_costume = costume_id
        self._current_costume = costume_id
        self._upsert_configured_model(self._current_char, costume_id)
        self._selecting_model = False
        self._costume_page.hide()
        self._char_page.show()
        self._show_model_detail()

    def _show_costume_preview(self, anchor: QWidget, costume_id: str):
        live2d_module = self._ensure_live2d_preview_module()
        if not live2d_module:
            return
        model_path = self._model_manager.get_model_json_path(self._current_char, costume_id)
        if not model_path:
            return
        if self._preview_bubble is None:
            self._preview_bubble = Live2DPreviewBubble(live2d_module, self._live2d_quality, self)
        self._preview_bubble.set_render_quality(self._live2d_quality)
        self._preview_bubble.show_preview(model_path, anchor)

    def _hide_costume_preview(self):
        if self._preview_bubble is not None:
            self._preview_bubble.hide()

    def _go_back_to_chars(self):
        self._costume_page.hide()
        self._char_page.show()
        self._current_page = "characters"
        self._selecting_model = True
        band_id = self._selected_band or self._model_manager.get_character_band(self._current_char)
        if band_id:
            self._populate_characters(band_id)
        else:
            self._populate_bands()
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        self._animate_indicator("characters")

    def _go_back_to_bands(self):
        self._selecting_model = True
        self._populate_bands()

    def _on_vsync_changed(self, checked: bool):
        self._vsync = checked
        self._fps_slider.setEnabled(not checked)
        self._fps_value.setEnabled(not checked)

    def _apply_auto_start_setting(self) -> bool:
        enabled = bool(self._auto_start_switch.isChecked())
        if not self._auto_start_supported:
            if self._cfg:
                self._cfg.set("auto_start", False)
            return True
        try:
            set_startup_enabled(enabled)
            self._auto_start_enabled = enabled
            if self._cfg:
                self._cfg.set("auto_start", enabled)
            return True
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.auto_start_failed_title"),
                _tr("SettingsWindow.auto_start_failed_content", error=str(exc)),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return False

    def _on_apply(self):
        if self._launched:
            return
        self._launched = True
        selected = self._selected_model_item()
        if selected:
            self._current_char = selected["character"]
            self._selected_costume = selected["costume"]
        if self._show_launch and not (self._current_char and self._selected_costume):
            self._launched = False
            InfoBar.warning(
                _tr("SettingsWindow.launch_missing_model_title"),
                _tr("SettingsWindow.launch_missing_model_content"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not self._apply_auto_start_setting():
            self._launched = False
            return
        self._save_llm_config(show_info=False)
        self._save_compact_window_config(show_info=False, emit_update=False)
        self._save_chat_integration_config(show_info=False, emit_update=False)
        self._save_mcp_computer_config(show_info=False)
        self._save_configured_models()
        settings = {
            "language": current_language(),
            "fps": self._fps_slider.value(),
            "opacity": self._opacity_slider.value() / 100.0,
            "dark_theme": self._theme_switch.isChecked(),
            "vsync": self._vsync_switch.isChecked(),
            "game_topmost": self._game_topmost_switch.isChecked(),
            "hide_live2d_model": self._hide_live2d_model_switch.isChecked(),
            "live2d_idle_actions_enabled": self._live2d_idle_actions_switch.isChecked(),
            "auto_start": self._auto_start_supported and self._auto_start_switch.isChecked(),
            "live2d_quality": self._live2d_quality,
            "live2d_scale": self._live2d_scale,
            "compact_ai_window_enabled": self._cfg.get("compact_ai_window_enabled", False) if self._cfg else False,
            "compact_ai_window_opacity": self._cfg.get("compact_ai_window_opacity", 44) if self._cfg else 44,
            "compact_ai_window_font_size": self._cfg.get("compact_ai_window_font_size", 12) if self._cfg else 12,
            "compact_ai_window_background_color": self._cfg.get("compact_ai_window_background_color", "") if self._cfg else "",
            "compact_ai_window_text_color": self._cfg.get("compact_ai_window_text_color", "#24242a") if self._cfg else "#24242a",
            "ai_event_overlay_enabled": self._cfg.get("ai_event_overlay_enabled", False) if self._cfg else False,
            "ai_status_port_enabled": self._cfg.get("ai_status_port_enabled", False) if self._cfg else False,
            "ai_status_port": self._clamp_ai_status_port(self._cfg.get("ai_status_port", 38472)) if self._cfg else 38472,
            "ai_status_token": self._cfg.get("ai_status_token", "") if self._cfg else "",
            "chat_integration_enabled": self._cfg.get("chat_integration_enabled", False) if self._cfg else False,
            "chat_integration_overlay_enabled": self._cfg.get("chat_integration_overlay_enabled", True) if self._cfg else True,
            "chat_integration_include_context": self._cfg.get("chat_integration_include_context", True) if self._cfg else True,
            "chat_integration_port": self._clamp_chat_integration_port(self._cfg.get("chat_integration_port", 38473)) if self._cfg else 38473,
            "chat_integration_token": self._cfg.get("chat_integration_token", "") if self._cfg else "",
            "user_avatar_color": self._cfg.get("user_avatar_color", BANDORI_PRIMARY) if self._cfg else BANDORI_PRIMARY,
            "user_avatar_path": self._cfg.get("user_avatar_path", "") if self._cfg else "",
            "models": [dict(item) for item in self._configured_models],
            "model_action_settings": self._cfg.get("model_action_settings", {}) if self._cfg else {},
        }
        if self._compact_window_reset_position_pending:
            settings["compact_ai_window_reset_position"] = True
        if self._cfg:
            self._cfg.set("language", settings["language"])
            self._cfg.set("fps", settings["fps"])
            self._cfg.set("opacity", settings["opacity"])
            self._cfg.set("dark_theme", settings["dark_theme"])
            self._cfg.set("vsync", settings["vsync"])
            self._cfg.set("game_topmost", settings["game_topmost"])
            self._cfg.set("hide_live2d_model", settings["hide_live2d_model"])
            self._cfg.set("live2d_idle_actions_enabled", settings["live2d_idle_actions_enabled"])
            self._cfg.set("auto_start", settings["auto_start"])
            self._cfg.set("live2d_quality", settings["live2d_quality"])
            self._cfg.set("live2d_scale", settings["live2d_scale"])
            self._cfg.save()
        if self._current_char and self._selected_costume:
            self.model_selected.emit(self._current_char, self._selected_costume)
        self.settings_changed.emit(settings)
        if self._show_launch:
            self.launch_requested.emit()
        self.close()

    def connect_ipc_output(self, send_line):
        self.model_selected.connect(lambda char, costume: send_line(f"MODEL\t{char}\t{costume}"))
        self.settings_changed.connect(lambda data: send_line(f"SETTINGS\t{json.dumps(data, ensure_ascii=False)}"))
        self.launch_requested.connect(lambda: send_line("LAUNCH"))


def _responses_api_url(api_url: str) -> str:
    return responses_api_url(api_url)


def _chat_completions_api_url(api_url: str) -> str:
    return chat_completions_api_url(api_url)


class UpdateCheckWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def run(self):
        try:
            from app_update import check_for_updates

            self.finished.emit(check_for_updates())
        except Exception as exc:
            self.error.emit(str(exc))


class UpdateApplyWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, update_info, parent=None):
        super().__init__(parent)
        self._update_info = update_info

    def run(self):
        try:
            from app_update import apply_update

            self.finished.emit(apply_update(self._update_info))
        except Exception as exc:
            self.error.emit(str(exc))


class McpConnectionTestWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = dict(config or {})

    def run(self):
        try:
            from mcp_bridge import test_mcp_servers

            success, details = test_mcp_servers(self._config)
            if success:
                self.finished.emit(details)
            else:
                self.error.emit(details)
        except Exception as exc:
            self.error.emit(str(exc))


class TestConnectionWorker(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str, api_mode: str = "chat_completions", parent=None):
        super().__init__(parent)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._api_mode = api_mode

    def run(self):
        try:
            ctx = ssl.create_default_context()

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }

            try:
                if self._api_mode == "responses" and not is_google_generative_language_url(self._api_url):
                    self._test_responses_request(urllib.request, json, headers, ctx)
                else:
                    self._test_chat_completions_request(urllib.request, json, headers, ctx)
                self.finished.emit()
            except urllib.error.HTTPError as e:
                if self._api_mode == "responses" and e.code in (400, 403, 404, 422):
                    self._test_chat_completions_request(urllib.request, json, headers, ctx)
                    self.finished.emit()
                    return
                raise
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))

    def _test_responses_request(self, urllib_request, json_module, headers: dict, ctx):
        url = _responses_api_url(self._api_url)
        body = json_module.dumps({
            "model": self._model_id,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "Hi"}]}],
        }).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json_module.loads(resp.read().decode("utf-8"))
            if not data.get("id"):
                raise ValueError("Unexpected response format")

    def _test_chat_completions_request(self, urllib_request, json_module, headers: dict, ctx):
        url = _chat_completions_api_url(self._api_url)
        body_obj = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": "Hi"}],
        }
        sanitize_chat_body_for_url(body_obj, url)
        body = json_module.dumps(body_obj).encode("utf-8")
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json_module.loads(resp.read().decode("utf-8"))
            if not data.get("choices", []):
                raise ValueError("Unexpected response format")


class FetchModelsWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, models_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self._models_url = models_url
        self._api_key = api_key

    def run(self):
        try:
            ctx = ssl.create_default_context()

            headers = {
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._models_url, headers=headers, method="GET"
            )

            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                ids = [m.get("id", "") for m in models if m.get("id")]
                self.finished.emit(sorted(ids))
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))
