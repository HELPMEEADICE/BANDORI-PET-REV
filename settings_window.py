import os
from datetime import datetime

import fluent_bootstrap  # noqa: F401
from PySide6.QtCore import Qt, Signal, QThread, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation, QPoint, QEvent, QUrl
from PySide6.QtGui import QFont, QColor, QPalette, QPixmap, QIcon, QCursor, QPainter, QPainterPath, QPen, QBrush, QIntValidator, QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QSizePolicy, QSpacerItem, QScrollArea,
    QLineEdit, QGraphicsOpacityEffect, QGraphicsColorizeEffect, QApplication,
    QTextEdit, QToolButton, QFileDialog, QMessageBox,
)

from qfluentwidgets import (
    CardWidget, PushButton, PrimaryPushButton, TransparentPushButton,
    BodyLabel, StrongBodyLabel, TitleLabel, SubtitleLabel,
    FluentIcon, Slider, SwitchButton, ScrollArea, ComboBox, LineEdit,
    isDarkTheme, InfoBar, InfoBarPosition,
)
from qfluentwidgets.components.widgets.menu import LineEditMenu, TextEditMenu
from qfluentwidgets.common.config import qconfig

from i18n_manager import tr as _tr, set_language, available_languages, current_language
from process_utils import app_base_dir
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

import json

from live2d_click_actions import (
    CLICK_MOTION_NONE,
    CLICK_MOTION_RANDOM,
    CLICK_MOTION_REGIONS,
    normalize_click_motion_actions,
)
from live2d_quality import normalize_live2d_quality

_BG_LIGHT = "#ffffff"
_BG_DARK = "#1e1e1e"

LIVE2D_SCALE_MIN = 25
LIVE2D_SCALE_MAX = 500

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

PROJECT_REPO_URL = "https://github.com/HELPMEEADICE/BANDORI-PET-REV"
PROJECT_LICENSE_URL = f"{PROJECT_REPO_URL}/blob/main/LICENSE"


class FluentContextLineEdit(QLineEdit):
    def contextMenuEvent(self, event):
        menu = LineEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


class FluentContextTextEdit(QTextEdit):
    def contextMenuEvent(self, event):
        menu = TextEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


def _clamp_live2d_scale(value) -> int:
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        pct = 0
    if pct <= 0:
        screen = QApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen else 1.0
        pct = int(round(ratio * 100))
    return max(LIVE2D_SCALE_MIN, min(LIVE2D_SCALE_MAX, pct))


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
        text_col.addWidget(self._title)
        text_col.addWidget(self._subtitle)
        layout.addLayout(text_col, 1)

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("x")
        self._remove_btn.setFixedSize(22, 22)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.clicked.connect(lambda: self.remove_requested.emit(self._character))
        layout.addWidget(self._remove_btn)
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

    def __init__(self, nav_key: str, icon, text: str, parent=None):
        super().__init__(parent)
        self._nav_key = nav_key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        if hasattr(icon, 'icon'):
            self.setIcon(icon.icon())
        else:
            self.setIcon(icon)
        self.setText(f"  {text}")
        self.setCheckable(True)
        self._update_stylesheet()
        qconfig.themeChanged.connect(self._update_stylesheet)
        self.clicked.connect(lambda: self.nav_activated.emit(self._nav_key))

    def enterEvent(self, event):
        if not self._checking_hover_effect():
            self._apply_hover_effect(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_hover_effect(False)
        super().leaveEvent(event)

    def _checking_hover_effect(self):
        eff = self.graphicsEffect()
        return isinstance(eff, QGraphicsColorizeEffect) and eff.strength() > 0.0

    def _apply_hover_effect(self, entering: bool):
        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsColorizeEffect):
            eff = QGraphicsColorizeEffect(self)
            eff.setColor(QColor(BANDORI_PRIMARY_DARK))
            eff.setStrength(0.0)
            self.setGraphicsEffect(eff)
        if hasattr(self, '_hover_anim'):
            self._hover_anim.stop()
        self._hover_anim = QPropertyAnimation(eff, b"strength")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.setStartValue(eff.strength())
        self._hover_anim.setEndValue(0.35 if entering else 0.0)
        if not entering:
            self._hover_anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._hover_anim.start()

    def _update_stylesheet(self):
        dark = isDarkTheme()
        bg = "#2a2a2a" if dark else "#fafafa"
        hover_bg = "#3a3a3a" if dark else "#f3e3e9"
        checked_bg = BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT
        checked_border = accent_color(dark)
        text_color = "#e0e0e0" if dark else "#2a2a2a"
        checked_text = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        border = "1px solid transparent" if dark else "1px solid #e0e0e0"
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 8px 14px;
                border: {border};
                border-radius: 8px;
                background: {bg};
                font-size: 14px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:checked {{
                background: {checked_bg};
                color: {checked_text};
            }}
        """)


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
        self._pov_page = None
        self._compact_window_page = None
        self._quality_page = None
        self._about_page = None
        self._current_page = "characters"
        self._selecting_model = False
        self._vsync = vsync
        self._game_topmost = bool(self._cfg.get("game_topmost", False)) if self._cfg else False
        self._live2d_quality = normalize_live2d_quality(
            self._cfg.get("live2d_quality", "balanced") if self._cfg else "balanced"
        )
        self._live2d_scale = _clamp_live2d_scale(
            self._cfg.get("live2d_scale", 0) if self._cfg else 0
        )
        self._saved_user_name = ""
        self._compact_window_reset_position_pending = False

        icon_path = os.path.join(app_base_dir(), "logo.ico")
        if os.path.exists(icon_path):
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
                result.append(entry)
                seen.add(character)
        if self._current_char and self._current_char not in seen:
            costume = self._current_costume or self._model_manager.get_default_costume(self._current_char)
            path = self._model_manager.get_model_json_path(self._current_char, costume)
            if path:
                result.insert(0, {
                    "character": self._current_char,
                    "costume": costume,
                    "path": path,
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
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def _ensure_live2d_preview_module(self):
        if self._live2d:
            return self._live2d
        try:
            from live2d_lua_adapter import live2d

            live2d.init()
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
        for attr in ('_test_worker', '_fetch_worker'):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(2000)

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

    def _update_all_theme_bgs(self):
        for w in self._theme_widgets:
            self._apply_theme_bg(w)

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
        if key == "compact_window":
            self._compact_window_page = self._add_lazy_page("compact_window", self._build_compact_window_page())
            return self._compact_window_page
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
        if not hasattr(self, '_sidebar'):
            return
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

        title = StrongBodyLabel(_tr("SettingsWindow.nav_title"), sidebar)
        title.setContentsMargins(12, 4, 0, 8)
        layout.addWidget(title)

        btn_chars = NavButton("characters", FluentIcon.EMOJI_TAB_SYMBOLS, _tr("SettingsWindow.nav_chars"), sidebar)
        btn_chars.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["characters"] = btn_chars
        layout.addWidget(btn_chars)

        btn_llm = NavButton("llm", FluentIcon.ROBOT, _tr("SettingsWindow.nav_llm"), sidebar)
        btn_llm.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["llm"] = btn_llm
        layout.addWidget(btn_llm)

        btn_pov = NavButton("pov", FluentIcon.PEOPLE, _tr("SettingsWindow.nav_pov"), sidebar)
        btn_pov.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["pov"] = btn_pov
        layout.addWidget(btn_pov)

        btn_compact = NavButton("compact_window", FluentIcon.ROBOT, _tr("SettingsWindow.nav_compact_window"), sidebar)
        btn_compact.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["compact_window"] = btn_compact
        layout.addWidget(btn_compact)

        btn_quality = NavButton("quality", FluentIcon.PHOTO, _tr("SettingsWindow.nav_quality"), sidebar)
        btn_quality.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["quality"] = btn_quality
        layout.addWidget(btn_quality)

        layout.addStretch()

        btn_about = NavButton("about", FluentIcon.INFO, _tr("SettingsWindow.nav_about"), sidebar)
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
        self._current_page = nav_key
        self._animate_indicator(nav_key)

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

        motion_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.default_motion"), action_container))
        motion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(motion_label)
        motion_row = QHBoxLayout()
        motion_row.setSpacing(8)
        self._default_motion_combo = ComboBox(action_container)
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
        self._default_expression_combo = ComboBox(action_container)
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
            combo = ComboBox(click_grid_widget)
            combo.setMinimumWidth(135)
            combo.setMaximumWidth(140)
            combo.currentIndexChanged.connect(
                lambda index, r=region: self._on_click_motion_changed(r, index)
            )
            expression_combo = ComboBox(click_grid_widget)
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
        action_scroll.setWidget(action_container)

        detail_center.addWidget(self._detail_card, 0, Qt.AlignmentFlag.AlignTop)
        detail_center.addWidget(action_scroll, 0, Qt.AlignmentFlag.AlignTop)
        detail_center.addStretch(1)
        detail_shell.addLayout(detail_center, 1)

        self._detail_action_hint = hint
        self._detail_motion_label = motion_label
        self._detail_expression_label = expression_label
        self._detail_click_motion_label = click_label
        self._detail_click_motion_hint = click_hint
        self._detail_action_scroll = action_scroll
        self._update_switch_button_style()
        qconfig.themeChanged.connect(self._update_switch_button_style)

        layout.addWidget(self._model_detail_widget, 1)
        self._model_detail_widget.hide()
        return page

    def _update_switch_button_style(self):
        if not hasattr(self, "_switch_model_btn"):
            return
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
        self._detail_motion_label.setStyleSheet(f"color: {hint_color};")
        self._detail_expression_label.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_label.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_hint.setStyleSheet(f"color: {hint_color};")
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
        if hasattr(self, "_model_detail_widget"):
            self._model_detail_widget.hide()
        if hasattr(self, "_selection_grid_widget"):
            self._selection_grid_widget.show()
        if hasattr(self, "_selection_scroll"):
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

        api_url_label = BodyLabel(_tr("SettingsWindow.llm_api_url"), page)
        layout.addWidget(api_url_label)
        self._llm_api_url = FluentContextLineEdit(page)
        self._llm_api_url.setPlaceholderText(_tr("SettingsWindow.llm_api_url_placeholder"))
        self._llm_api_url.setFixedHeight(36)
        layout.addWidget(self._llm_api_url)

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

        thinking_label = BodyLabel(_tr("SettingsWindow.llm_enable_thinking"), page)
        layout.addWidget(thinking_label)
        self._llm_enable_thinking = ComboBox(page)
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

        self._llm_model_combo_label = BodyLabel(_tr("SettingsWindow.llm_available_models"), page)
        self._llm_model_combo_label.hide()
        layout.addWidget(self._llm_model_combo_label)

        self._llm_model_scroll = ScrollArea()
        self._llm_model_scroll.setWidgetResizable(True)
        self._llm_model_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._llm_model_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._llm_model_scroll.setMinimumHeight(80)
        self._llm_model_scroll.setMaximumHeight(220)
        self._llm_model_scroll.hide()

        self._llm_model_list = QWidget(page)
        self._llm_model_list_layout = QVBoxLayout(self._llm_model_list)
        self._llm_model_list_layout.setContentsMargins(0, 4, 0, 4)
        self._llm_model_list_layout.setSpacing(2)
        self._llm_model_scroll.setWidget(self._llm_model_list)
        layout.addWidget(self._llm_model_scroll)

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

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_llm_config)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_llm_config()
        self._style_llm_inputs()
        qconfig.themeChanged.connect(self._style_llm_inputs)

        return page

    def _build_pov_page(self):
        page = self._make_theme_widget(QWidget())
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
        layout.addWidget(self._user_name)

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
        self._pov_mode = ComboBox(page)
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

        role_label = BodyLabel(_tr("SettingsWindow.pov_role_character"), page)
        layout.addWidget(role_label)
        self._pov_role_character = ComboBox(page)
        self._pov_role_character.setFixedHeight(36)
        for char_key in self._model_manager.characters:
            self._pov_role_character.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
        self._pov_role_character.currentIndexChanged.connect(self._sync_role_display_name)
        layout.addWidget(self._pov_role_character)

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_llm_config)
        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return page

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

    @staticmethod
    def _clamp_ai_status_port(value) -> int:
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = 38472
        return max(1024, min(65535, port))

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

        self._quality_combo = ComboBox(page)
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
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = TitleLabel(_tr("SettingsWindow.about_title"), page)
        layout.addWidget(title)

        subtitle = SubtitleLabel(_tr("SettingsWindow.about_subtitle"), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        desc = BodyLabel(_tr("SettingsWindow.about_desc"), page)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        license_label = BodyLabel(_tr("SettingsWindow.about_license"), page)
        license_label.setWordWrap(True)
        layout.addWidget(license_label)

        disclaimer = BodyLabel(_tr("SettingsWindow.about_disclaimer"), page)
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)

        link_label = QLabel(
            _tr(
                "SettingsWindow.about_links",
                repo=PROJECT_REPO_URL,
                license=PROJECT_LICENSE_URL,
            ),
            page,
        )
        link_label.setWordWrap(True)
        link_label.setTextFormat(Qt.TextFormat.RichText)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link_label.setOpenExternalLinks(True)
        self._style_about_link(link_label)
        qconfig.themeChanged.connect(lambda: self._style_about_link(link_label))
        layout.addWidget(link_label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(10)
        repo_btn = TransparentPushButton(FluentIcon.GITHUB, _tr("SettingsWindow.about_open_repo"), page)
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_REPO_URL)))
        license_btn = TransparentPushButton(FluentIcon.HELP, _tr("SettingsWindow.about_open_license"), page)
        license_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_LICENSE_URL)))
        btn_row.addWidget(repo_btn)
        btn_row.addWidget(license_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        tech = BodyLabel(_tr("SettingsWindow.about_tech"), page)
        tech.setWordWrap(True)
        layout.addWidget(tech)

        layout.addStretch()
        return page

    @staticmethod
    def _style_about_link(label: QLabel):
        color = BANDORI_PRIMARY_DARK if isDarkTheme() else BANDORI_PRIMARY
        text = "#dcdcdc" if isDarkTheme() else "#303030"
        label.setStyleSheet(f"QLabel {{ color: {text}; font-size: 13px; }} QLabel a {{ color: {color}; }}")

    def _on_quality_changed(self, index: int):
        profile = self._quality_combo.itemData(index)
        self._live2d_quality = normalize_live2d_quality(profile)
        self._quality_detail.setText(self._quality_detail_text(self._live2d_quality))

    def _llm_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_llm_api_url",
                "_llm_api_key",
                "_llm_model_id",
                "_llm_aux_model_id",
                "_llm_enable_thinking",
                "_llm_show_reasoning",
                "_user_name",
                "_pov_mode",
                "_pov_custom_prompt",
                "_pov_role_character",
                "_avatar_color_btns",
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
        self._llm_aux_model_id.setStyleSheet(style)
        self._user_name.setStyleSheet(style)
        self._pov_custom_prompt.setStyleSheet(style)
        self._style_avatar_buttons()

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

    def _on_avatar_color_clicked(self, btn: QPushButton):
        for b in self._avatar_color_btns:
            b.setChecked(False)
        btn.setChecked(True)
        self._style_avatar_buttons()
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
            self._llm_aux_model_id.setText(self._cfg.get("llm_aux_model_id", ""))
            self._saved_user_name = self._cfg.get("user_name", "")
            self._user_name.setText(self._saved_user_name)
            saved_color = self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
            for btn in self._avatar_color_btns:
                btn.setChecked(btn.property("avatar_color") == saved_color)
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
            saved_role = self._cfg.get("pov_role_character", "")
            for i in range(self._pov_role_character.count()):
                if self._pov_role_character.itemData(i) == saved_role:
                    self._pov_role_character.setCurrentIndex(i)
                    break
            self._on_pov_mode_changed(self._pov_mode.currentIndex())

    def _on_pov_mode_changed(self, index: int):
        mode = self._pov_mode.itemData(index) or "off"
        self._pov_custom_prompt.setEnabled(mode == "custom")
        self._pov_role_character.setEnabled(mode == "role")
        self._user_name.setEnabled(mode != "role")
        if mode == "role":
            self._sync_role_display_name()
        else:
            self._user_name.setText(getattr(self, "_saved_user_name", ""))

    def _sync_role_display_name(self):
        if self._pov_mode.itemData(self._pov_mode.currentIndex()) != "role":
            return
        self._user_name.setText(self._pov_role_character.currentText())

    def _save_llm_config(self):
        if self._cfg and self._llm_config_widgets_ready():
            self._cfg.set("llm_api_url", self._llm_api_url.text().strip())
            self._cfg.set("llm_api_key", self._llm_api_key.text().strip())
            self._cfg.set("llm_model_id", self._llm_model_id.text().strip())
            self._cfg.set("llm_aux_model_id", self._llm_aux_model_id.text().strip())
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
            try:
                self._cfg.save()
                InfoBar.success(
                    _tr("SettingsWindow.llm_saved_title"),
                    _tr("SettingsWindow.llm_saved_content"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            except Exception:
                pass

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

        self._test_worker = TestConnectionWorker(api_url, api_key, model_id, parent=self)
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
        api_url = self._llm_api_url.text().strip()
        api_key = self._llm_api_key.text().strip()

        if not api_url or not api_key:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_api_title"),
                _tr("SettingsWindow.llm_missing_api_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        base_url = api_url.rstrip("/")
        base_url = base_url.rsplit("/chat/completions", 1)[0]
        models_url = base_url + "/models"

        if hasattr(self, '_fetch_worker') and self._fetch_worker is not None:
            if self._fetch_worker.isRunning():
                self._fetch_worker.quit()
                self._fetch_worker.wait(2000)

        self._fetch_worker = FetchModelsWorker(models_url, api_key, parent=self)
        self._fetch_worker.finished.connect(self._on_models_fetched)
        self._fetch_worker.error.connect(self._on_test_error)
        self._fetch_worker.start()

    def _on_models_fetched(self, models: list[str]):
        for i in range(self._llm_model_list_layout.count()):
            item = self._llm_model_list_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        dark = isDarkTheme()
        for idx, model_name in enumerate(models):
            btn = QPushButton(model_name, self._llm_model_list)
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
            self._llm_model_list_layout.addWidget(btn)
            QTimer.singleShot(idx * 30, lambda b=btn: self._animate_button_in(b))
        self._llm_model_list_layout.addStretch()

        self._llm_model_combo_label.show()
        self._llm_model_scroll.show()

    def _set_fetched_model_id(self, model_name: str):
        target = getattr(self, "_llm_model_fetch_target", self._llm_model_id)
        target.setText(model_name)

    def _build_side_panel(self):
        panel = self._make_theme_widget(QWidget())
        panel.setFixedWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

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
        self._lang_combo = ComboBox(panel)
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
        self._model_list_widget = QWidget(panel)
        self._model_list_widget.setObjectName("modelListWidget")
        self._model_list_layout = QVBoxLayout(self._model_list_widget)
        self._model_list_layout.setContentsMargins(0, 0, 0, 0)
        self._model_list_layout.setSpacing(6)
        layout.addWidget(self._model_list_widget)
        self._update_model_list_style()
        qconfig.themeChanged.connect(self._update_model_list_style)

        return panel

    def _update_model_list_style(self):
        if not hasattr(self, "_model_list_widget"):
            return
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
        if not hasattr(self, "_model_list_layout"):
            return
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
        self._selected_list_character = ""
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = True
        self._refresh_model_list()
        self._enter_model_selection()

    def _remove_model_list_item(self, character: str):
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
        self._save_llm_config()
        self._save_compact_window_config(show_info=False, emit_update=False)
        self._save_configured_models()
        settings = {
            "language": current_language(),
            "fps": self._fps_slider.value(),
            "opacity": self._opacity_slider.value() / 100.0,
            "dark_theme": self._theme_switch.isChecked(),
            "vsync": self._vsync_switch.isChecked(),
            "game_topmost": self._game_topmost_switch.isChecked(),
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
            "user_avatar_color": self._cfg.get("user_avatar_color", BANDORI_PRIMARY) if self._cfg else BANDORI_PRIMARY,
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


class TestConnectionWorker(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str, parent=None):
        super().__init__(parent)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    def run(self):
        try:
            import urllib.request
            import json
            import ssl

            ctx = ssl.create_default_context()

            body = json.dumps({
                "model": self._model_id,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
            }).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._api_url, data=body, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    self.finished.emit()
                else:
                    self.error.emit("Unexpected response format")
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


class FetchModelsWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, models_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self._models_url = models_url
        self._api_key = api_key

    def run(self):
        try:
            import urllib.request
            import json
            import ssl

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
