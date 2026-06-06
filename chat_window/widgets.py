import json
import math
import urllib.error
from pathlib import Path

from PySide6.QtCore import (
    Qt, QObject, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QRectF, QSize,
)
from PySide6.QtGui import (
    QFont, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QImage, QRegion,
    QTextCursor, QKeyEvent,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QToolButton, QMenu,
    QApplication, QGraphicsOpacityEffect, QWidgetAction,
    QGraphicsColorizeEffect, QFrame, QFileDialog, QMessageBox,
    QSplitter, QSplitterHandle, QCheckBox,
)

from i18n_manager import tr as _tr
from qfluentwidgets import Action, BodyLabel, StrongBodyLabel, FluentIcon, RoundMenu, LineEdit, MessageBoxBase, TransparentToolButton, isDarkTheme
from qfluentwidgets.common.config import qconfig

from app_theme import (
    BANDORI_PRIMARY,
    BANDORI_PRIMARY_HOVER,
    BANDORI_PRIMARY_PRESSED,
    BANDORI_PRIMARY_DARK,
    BANDORI_PRIMARY_DARK_HOVER,
    BANDORI_PRIMARY_DARK_PRESSED,
    accent_color,
)
from vision_fallback import analyze_images_with_aux_model

from .constants import _HISTORY_ROW_WIDTH, _HISTORY_ROW_HEIGHT, _prepare_fluent_round_menu


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


class FluentContextLabel(QLabel):
    def contextMenuEvent(self, event):
        full_text = self.text()
        if not full_text:
            return

        menu = RoundMenu(parent=self)
        selected_text = self.selectedText()
        copy_text = selected_text or full_text

        copy_action = Action(FluentIcon.COPY, _tr("Common.copy"), self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(copy_text))
        menu.addAction(copy_action)

        copy_all_action = Action(FluentIcon.SAVE_COPY, _tr("Common.copy_all"), self)
        copy_all_action.triggered.connect(lambda: QApplication.clipboard().setText(full_text))
        copy_all_action.setEnabled(bool(full_text))
        menu.addAction(copy_all_action)

        _prepare_fluent_round_menu(menu)
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
        if not self._hovered and not self._pressed:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        if self._pressed:
            color = QColor("#8f98ad" if dark else "#9aa8c2")
            width = 2
            alpha = 130
        else:
            color = QColor("#8f98ad" if dark else "#9aa8c2")
            width = 1
            alpha = 90
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
        self._pinned = bool(pinned)
        self._current = current
        self._hovered = False
        self._pressed = False
        self._avatar_has_pixmap = avatar_pixmap is not None and not avatar_pixmap.isNull()
        self._bg_color = QColor("transparent")
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
        self.apply_theme()
        self._update_elided_texts()

    def characters(self) -> list[str]:
        return list(self._characters)

    def set_current(self, current: bool):
        current = bool(current)
        if self._current == current:
            return
        self._current = current
        self.apply_theme()

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


class _PickerRow(QWidget):
    def __init__(self, checkbox: QCheckBox, parent=None):
        super().__init__(parent)
        self._check = checkbox
        self._checked_bg = ""
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        checkbox.setParent(self)
        checkbox.setTristate(False)
        checkbox.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(checkbox)
        checkbox.stateChanged.connect(self._on_state_changed)

    def set_checked_bg(self, color: str):
        self._checked_bg = color
        self._on_state_changed(self._check.checkState())

    def _on_state_changed(self, _state):
        if self._check.isChecked() and self._checked_bg:
            self.setStyleSheet(f"_PickerRow {{ background: {self._checked_bg}; border-radius: 7px; }}")
        else:
            self.setStyleSheet("")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._check.toggle()
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def contextMenuEvent(self, event):
        event.accept()


class ChatCharacterPickerPanel(QWidget):
    open_requested = Signal(object)

    def __init__(self, characters: list[str], display_name_for, selected=None, bands=None, parent=None):
        super().__init__(parent)
        self._characters = list(characters)
        self._display_name_for = display_name_for
        self._checks: dict[str, QCheckBox] = {}
        self._picker_rows: list[_PickerRow] = []
        selected_set = set(selected or [])
        self.setObjectName("ChatCharacterPickerPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)

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
        scroll.setMaximumHeight(360)

        list_widget = QWidget(scroll)
        list_widget.setObjectName("ChatPickerList")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(2)

        char_set = set(self._characters)
        if bands:
            band_char_set = set()
            for band in bands:
                members = [c for c in band.get("characters", []) if c in char_set]
                if not members:
                    continue
                band_label = QLabel(band.get("display", ""), list_widget)
                band_label.setObjectName("ChatPickerBandLabel")
                list_layout.addWidget(band_label)
                for character in members:
                    check = QCheckBox(self._display_name_for(character))
                    check.setObjectName("ChatPickerCheck")
                    check.setChecked(character in selected_set)
                    check.stateChanged.connect(self._sync_action_button)
                    self._checks[character] = check
                    row = _PickerRow(check, list_widget)
                    self._picker_rows.append(row)
                    list_layout.addWidget(row)
                    band_char_set.add(character)
            others = [c for c in self._characters if c not in band_char_set]
            if others:
                band_label = QLabel(_tr("ChatWindow.new_chat_picker_others", default="其他"), list_widget)
                band_label.setObjectName("ChatPickerBandLabel")
                list_layout.addWidget(band_label)
                for character in others:
                    check = QCheckBox(self._display_name_for(character))
                    check.setObjectName("ChatPickerCheck")
                    check.setChecked(character in selected_set)
                    check.stateChanged.connect(self._sync_action_button)
                    self._checks[character] = check
                    row = _PickerRow(check, list_widget)
                    self._picker_rows.append(row)
                    list_layout.addWidget(row)
        else:
            for character in self._characters:
                check = QCheckBox(self._display_name_for(character))
                check.setObjectName("ChatPickerCheck")
                check.setChecked(character in selected_set)
                check.stateChanged.connect(self._sync_action_button)
                self._checks[character] = check
                row = _PickerRow(check, list_widget)
                self._picker_rows.append(row)
                list_layout.addWidget(row)
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
            QLabel#ChatPickerBandLabel {{
                color: {muted};
                background: transparent;
                font-size: 11px;
                font-weight: 700;
                padding: 6px 8px 2px 8px;
            }}
            QScrollArea#ChatPickerScroll {{
                background: {bg};
                border: none;
            }}
            QWidget#ChatPickerList {{
                background: {bg};
            }}
            _PickerRow {{
                background: transparent;
                border-radius: 7px;
                padding: 0px;
            }}
            _PickerRow:hover {{
                background: {hover};
            }}
            QCheckBox#ChatPickerCheck {{
                color: {text};
                background: transparent;
                border-radius: 7px;
                padding: 7px 8px;
                font-size: 13px;
            }}
            QCheckBox#ChatPickerCheck:hover {{
                background: transparent;
            }}
            QCheckBox#ChatPickerCheck:checked {{
                background: transparent;
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
        for row in self._picker_rows:
            row.set_checked_bg(hover)


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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
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
        self._bg = QColor(bg)
        self._border = QColor(border)
        self.setStyleSheet(f"""
            QFrame#SearchSourcePopup {{
                background: transparent;
                border: none;
            }}
            QFrame#SearchSourcePopup QLabel {{ color: {text}; background: transparent; }}
            QFrame#SearchSourcePopup QLabel#SearchSourceUrl {{ color: {muted}; }}
        """)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, self._bg)
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        super().paintEvent(event)


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
    _FILE_HEIGHT = 54

    def __init__(self, attachment: dict, parent=None):
        super().__init__(parent)
        self._attachment = dict(attachment or {})
        self._type = str(self._attachment.get("type", "") or "").strip().lower()
        self._path = str(self._attachment.get("path", "") or "")
        self._name = self._attachment.get("name") or Path(self._path).name or ("image" if self._type == "image" else "file")
        self._pixmap = QPixmap(self._path) if self._type == "image" and self._path else QPixmap()
        self._bg = QColor("transparent")
        self._border = QColor("transparent")
        self._empty_text = QColor("#657089")
        self._file_text = QColor("#1f2328")
        self._file_meta = QColor("#657089")
        self.setToolTip(self._name)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.set_preview_width(self._DEFAULT_WIDTH)

    def preferred_width(self) -> int:
        if self._type != "image":
            return self._DEFAULT_WIDTH
        if self._pixmap.isNull():
            return 180
        return self._scaled_outer_size(self._DEFAULT_WIDTH).width()

    def _scaled_outer_size(self, max_width: int) -> QSize:
        max_width = max(96, int(max_width))
        if self._type != "image":
            return QSize(min(max_width, self._DEFAULT_WIDTH), self._FILE_HEIGHT)
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
        self._file_text = QColor("#f7f7fb" if dark else "#1f2328")
        self._file_meta = QColor("#a9b0c3" if dark else "#657089")
        self.update()

    @staticmethod
    def _format_size(size) -> str:
        try:
            value = int(size)
        except (TypeError, ValueError):
            return ""
        if value < 1024:
            return f"{value} B"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value / (1024 * 1024):.1f} MB"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, self._bg)

        if self._type != "image":
            icon_rect = rect.adjusted(10, 12, -rect.width() + 34, -12)
            icon_path = QPainterPath()
            icon_path.addRoundedRect(icon_rect, 4, 4)
            painter.setPen(QPen(self._border, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(icon_path)
            painter.drawLine(int(icon_rect.right() - 7), int(icon_rect.top()), int(icon_rect.right()), int(icon_rect.top() + 7))

            name_rect = rect.adjusted(42, 8, -10, -26)
            meta_rect = rect.adjusted(42, 28, -10, -6)
            painter.setPen(self._file_text)
            name = self.fontMetrics().elidedText(self._name, Qt.TextElideMode.ElideRight, max(24, int(name_rect.width())))
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            mime = str(self._attachment.get("mime", "") or "file")
            size = self._format_size(self._attachment.get("size", ""))
            meta = " · ".join(part for part in (mime, size) if part)
            painter.setPen(self._file_meta)
            meta = self.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideRight, max(24, int(meta_rect.width())))
            painter.drawText(meta_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, meta)
        elif self._pixmap.isNull():
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


class AttachmentRemoveButton(QToolButton):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        if self.isDown():
            bg = QColor("#252a33" if dark else "#111214")
        elif self.underMouse():
            bg = QColor("#4a5261" if dark else "#34373b")
        else:
            bg = QColor("#343a46" if dark else "#202124")
        border = QColor("#4b5363" if dark else "#ffffff")

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(border, 1))
        painter.setBrush(bg)
        painter.drawEllipse(rect)

        inset = 6.5
        painter.setPen(QPen(QColor("#ffffff"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(
            int(rect.left() + inset),
            int(rect.top() + inset),
            int(rect.right() - inset),
            int(rect.bottom() - inset),
        )
        painter.drawLine(
            int(rect.right() - inset),
            int(rect.top() + inset),
            int(rect.left() + inset),
            int(rect.bottom() - inset),
        )


class ComposerAttachmentCard(QWidget):
    remove_requested = Signal(str)

    _IMAGE_SIZE = QSize(64, 64)
    _FILE_SIZE = QSize(190, 64)

    def __init__(self, attachment: dict, parent=None):
        super().__init__(parent)
        self._attachment = dict(attachment or {})
        self._type = str(self._attachment.get("type", "") or "").strip().lower()
        self._path = str(self._attachment.get("path", "") or "")
        self._name = str(
            self._attachment.get("name")
            or Path(self._path).name
            or ("image" if self._type == "image" else "file")
        )
        self._pixmap = QPixmap(self._path) if self._type == "image" and self._path else QPixmap()
        self._bg = QColor("#ffffff")
        self._border = QColor("#dde4f0")
        self._icon_bg = QColor("#f3f5f9")
        self._text = QColor("#1f2328")
        self._muted = QColor("#657089")

        self.setFixedSize(self._IMAGE_SIZE if self._type == "image" else self._FILE_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip(self._name)

        self._name_label = None
        self._meta_label = None
        if self._type != "image":
            self._name_label = QLabel(self._name, self)
            self._name_label.setObjectName("AttachmentName")
            self._name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._meta_label = QLabel(
                self._file_kind(self._name, self._attachment.get("mime", "")),
                self,
            )
            self._meta_label.setObjectName("AttachmentMeta")
            self._meta_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._remove_btn = AttachmentRemoveButton(self)
        self._remove_btn.setObjectName("AttachmentRemoveButton")
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.setToolTip(_tr("ChatWindow.attachment_remove", default="移除附件"))
        self._remove_btn.setFixedSize(20, 20)
        self._remove_btn.clicked.connect(lambda: self.remove_requested.emit(self._path))
        self.apply_theme()

    def resizeEvent(self, event):
        self._remove_btn.move(self.width() - self._remove_btn.width() - 3, 3)
        self._remove_btn.raise_()
        if self._name_label is not None and self._meta_label is not None:
            self._name_label.setGeometry(60, 9, self.width() - 88, 24)
            self._meta_label.setGeometry(60, 32, self.width() - 72, 20)
            self._name_label.setText(
                self._name_label.fontMetrics().elidedText(
                    self._name,
                    Qt.TextElideMode.ElideRight,
                    max(24, self._name_label.width()),
                )
            )
        super().resizeEvent(event)

    def apply_theme(self):
        dark = isDarkTheme()
        self._bg = QColor("#20242d" if dark else "#ffffff")
        self._border = QColor("#3a4150" if dark else "#dfe3ea")
        self._icon_bg = QColor("#292e39" if dark else "#f4f5f7")
        self._text = QColor("#f7f7fb" if dark else "#202124")
        self._muted = QColor("#a9b0c3" if dark else "#70757d")
        self._remove_btn.setStyleSheet("background: transparent; border: none;")
        if self._name_label is not None and self._meta_label is not None:
            self._name_label.setStyleSheet(f"""
                QLabel#AttachmentName {{
                    color: {self._text.name()};
                    background: transparent;
                    border: none;
                    font-size: 12px;
                    font-weight: 600;
                }}
            """)
            self._meta_label.setStyleSheet(f"""
                QLabel#AttachmentMeta {{
                    color: {self._muted.name()};
                    background: transparent;
                    border: none;
                    font-size: 11px;
                }}
            """)
        self._remove_btn.update()
        self.update()

    @staticmethod
    def _file_kind(name: str, mime: str) -> str:
        suffix = Path(name).suffix.lstrip(".").upper()
        if suffix:
            return suffix[:12]
        major = str(mime or "").split("/", 1)[0].strip().upper()
        return major or "FILE"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        card_path = QPainterPath()
        card_path.addRoundedRect(rect, 11, 11)
        painter.fillPath(card_path, self._bg)

        if self._type == "image" and not self._pixmap.isNull():
            painter.save()
            image_path = QPainterPath()
            image_path.addRoundedRect(rect.adjusted(1, 1, -1, -1), 10, 10)
            painter.setClipPath(image_path)
            scaled = self._pixmap.scaled(
                max(1, int(rect.width())),
                max(1, int(rect.height())),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = int(rect.center().x() - scaled.width() / 2)
            y = int(rect.center().y() - scaled.height() / 2)
            painter.drawPixmap(x, y, scaled)
            painter.restore()
        elif self._type == "image":
            painter.setPen(self._muted)
            text = self.fontMetrics().elidedText(
                self._name,
                Qt.TextElideMode.ElideRight,
                max(24, self.width() - 16),
            )
            painter.drawText(rect.adjusted(8, 8, -8, -8), Qt.AlignmentFlag.AlignCenter, text)
        else:
            icon_rect = QRectF(8, 8, 42, 48)
            icon_path = QPainterPath()
            icon_path.addRoundedRect(icon_rect, 9, 9)
            painter.fillPath(icon_path, self._icon_bg)

            glyph_rect = QRectF(19, 18, 18, 23)
            painter.setPen(QPen(self._muted, 1.7))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(glyph_rect, 3, 3)
            painter.drawLine(int(glyph_rect.left() + 5), int(glyph_rect.top() + 8), int(glyph_rect.right() - 4), int(glyph_rect.top() + 8))
            painter.drawLine(int(glyph_rect.left() + 5), int(glyph_rect.top() + 14), int(glyph_rect.right() - 6), int(glyph_rect.top() + 14))

        painter.setPen(QPen(self._border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(card_path)
        super().paintEvent(event)
