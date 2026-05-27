import math
import ctypes
import os
import sys
from dataclasses import dataclass

if os.name == "nt":
    import ctypes.wintypes
from typing import Callable

from PySide6.QtCore import (
    Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QTimer,
    QParallelAnimationGroup, QVariantAnimation, QRectF,
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QMouseEvent,
    QRadialGradient, QFontMetrics, QPixmap, QCursor, QGuiApplication,
)
from PySide6.QtWidgets import (
    QWidget, QGraphicsOpacityEffect,
)

from app_theme import BANDORI_UI_FONT_FAMILY
from win32_dwm import apply_windows_11_border_fix, frame_changed

WM_NCCALCSIZE = 0x0083

if os.name == "nt":
    _user32 = ctypes.windll.user32
    _get_async_key_state = _user32.GetAsyncKeyState
    _get_async_key_state.argtypes = [ctypes.c_int]
    _get_async_key_state.restype = ctypes.c_short
else:
    _get_async_key_state = None

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04

if sys.platform == "darwin":
    import macos_patch
else:
    macos_patch = None


class RadialMenuItem(QWidget):
    clicked = Signal()

    def __init__(self, icon_path: str, label: str, color: QColor,
                 glyph: str = "", enabled: bool = True, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._hover = False
        self._glyph = glyph
        self._icon = QPixmap(icon_path) if icon_path and os.path.exists(icon_path) else None
        self._enabled = enabled

        size = 80
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ForbiddenCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_label(self, label: str):
        if self._label == label:
            return
        self._label = label
        self.update()

    def set_glyph(self, glyph: str):
        if self._glyph == glyph:
            return
        self._glyph = glyph
        self.update()

    def set_enabled_state(self, enabled: bool):
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ForbiddenCursor
        )
        self.update()

    def set_color(self, color: QColor):
        if self._color == color:
            return
        self._color = color
        self.update()

    @staticmethod
    def _is_text_badge(glyph: str) -> bool:
        text = str(glyph or "").strip()
        return bool(text) and len(text) <= 5 and all(ch.isascii() and (ch.isalnum() or ch in ".+-") for ch in text)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 4

        color = self._color.lighter(130) if self._hover and self._enabled else self._color
        if not self._enabled:
            color = QColor(120, 120, 120)

        p.setPen(Qt.PenStyle.NoPen)

        p.setBrush(QColor(0, 0, 0, 34 if self._enabled else 18))
        p.drawEllipse(QPoint(int(cx), int(cy + 2)), int(r), int(r))

        gradient = QRadialGradient(cx, cy - r * 0.3, r * 1.2)
        gradient.setColorAt(0, color.lighter(162))
        gradient.setColorAt(0.62, color)
        gradient.setColorAt(1, color.darker(116))
        p.setBrush(QBrush(gradient))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

        p.setPen(QPen(QColor(255, 255, 255, 92 if self._enabled else 42), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r - 1), int(r - 1))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 46 if self._hover and self._enabled else 22))
        p.drawEllipse(QPoint(int(cx), int(cy - r * 0.22)), int(r * 0.64), int(r * 0.42))

        if self._icon and not self._icon.isNull():
            icon_size = int(r * 0.7)
            scaled = self._icon.scaled(
                icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            p.drawPixmap(int(cx - icon_size / 2), int(cy - icon_size / 2 - r * 0.15), scaled)
        elif self._glyph:
            if self._is_text_badge(self._glyph):
                badge = str(self._glyph).strip().upper()
                font = p.font()
                font.setFamily(BANDORI_UI_FONT_FAMILY)
                font.setPointSize(12 if len(badge) <= 3 else 10)
                font.setBold(True)
                p.setFont(font)
                fm = QFontMetrics(font)
                text_w = fm.horizontalAdvance(badge)
                badge_w = min(r * 1.22, max(r * 0.86, text_w + 18))
                badge_h = 24
                badge_rect = QRectF(
                    cx - badge_w / 2,
                    cy - r * 0.34,
                    badge_w,
                    badge_h,
                )
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 46 if self._enabled else 24))
                p.drawRoundedRect(badge_rect, 9, 9)
                p.setPen(QPen(QColor(255, 255, 255, 128 if self._enabled else 64), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(badge_rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
                p.setPen(QColor(255, 255, 255, 242 if self._enabled else 170))
                p.drawText(
                    badge_rect,
                    Qt.AlignmentFlag.AlignCenter,
                    badge,
                )
            else:
                font = p.font()
                font.setPointSize(21)
                p.setFont(font)
                p.setPen(QColor(255, 255, 255, 240 if self._enabled else 170))
                fm = QFontMetrics(font)
                g_w = fm.horizontalAdvance(self._glyph)
                p.drawText(int(cx - g_w / 2), int(cy - 2), self._glyph)

        font = p.font()
        font.setFamily(BANDORI_UI_FONT_FAMILY)
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 232 if self._enabled else 170))
        fm = QFontMetrics(font)
        label = fm.elidedText(self._label, Qt.TextElideMode.ElideRight, int(r * 1.42))
        text_w = fm.horizontalAdvance(label)
        p.drawText(int(cx - text_w / 2), int(cy + r * 0.56), label)

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._enabled:
            self.clicked.emit()


@dataclass
class _ItemData:
    widget: RadialMenuItem
    start_offset: QPoint
    end_offset: QPoint
    opacity_effect: QGraphicsOpacityEffect


class RadialMenu(QWidget):
    closed = Signal()
    lock_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if sys.platform.startswith("linux"):
            flags |= Qt.WindowType.X11BypassWindowManagerHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAutoFillBackground(False)

        self._items: list[_ItemData] = []
        self._is_showing = False
        self._center = QPoint(0, 0)
        self._radius = 110
        self._anim_group = None
        self._fps = 120
        self._locked = False
        self._center_hover = False
        self._center_opacity = 1.0
        self._center_scale = 1.0
        self._center_anim_value = 1.0
        self._lock_anim = None
        self._paint_prewarmed = False
        self._ignore_outside_click_until_release = False
        self._outside_click_timer = QTimer(self)
        self._outside_click_timer.setInterval(25)
        self._outside_click_timer.timeout.connect(self._check_outside_click)

        self.setMouseTracking(True)

    def nativeEvent(self, event_type, message):
        if os.name == "nt":
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
                if msg.message == WM_NCCALCSIZE:
                    return True, 0
            except Exception:
                pass
        return super().nativeEvent(event_type, message)

    def _apply_windows_11_border_fix(self):
        hwnd = int(self.winId())
        apply_windows_11_border_fix(hwnd)
        frame_changed(hwnd)

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_11_border_fix()
        QTimer.singleShot(0, self._apply_windows_11_border_fix)
        if macos_patch is not None:
            QTimer.singleShot(0, lambda: macos_patch.apply_popup_window_polish(self))

    def prepare_for_show(self):
        # Force native window creation during idle time so first popup stays responsive.
        self.winId()
        self._apply_windows_11_border_fix()
        if macos_patch is not None:
            macos_patch.apply_popup_window_polish(self)
        self._prewarm_paint_cache()

    def _prewarm_paint_cache(self):
        if self._paint_prewarmed:
            return

        total_w = self._radius * 2 + 80 * 2
        total_h = self._radius * 2 + 80 * 2
        if self.width() != total_w or self.height() != total_h:
            self.resize(total_w, total_h)

        # Windows can stall the first time Qt resolves emoji fallback fonts and
        # translucent gradients. Render once while hidden so right-click only shows.
        self._set_center_reveal_value(1.0)
        menu_pixmap = QPixmap(total_w, total_h)
        menu_pixmap.fill(Qt.GlobalColor.transparent)
        self.render(menu_pixmap)

        for item in self._items:
            item_pixmap = QPixmap(item.widget.size())
            item_pixmap.fill(Qt.GlobalColor.transparent)
            item.widget.render(item_pixmap)

        self._paint_prewarmed = True

    @property
    def locked(self):
        return self._locked

    def set_locked(self, locked: bool):
        self._locked = locked
        self._center_opacity = 1.0
        self._center_scale = 1.0
        self._center_anim_value = 1.0
        self.update()

    def _set_center_reveal_value(self, value: float):
        self._center_anim_value = value
        self._center_opacity = value
        self._center_scale = 0.72 + 0.28 * value
        self.update()

    def _set_center_anim_value(self, value: float):
        if value < 0.5:
            t = value / 0.5
            self._center_opacity = 1.0 - t
            self._center_scale = 1.0 - 0.16 * t
        else:
            t = (value - 0.5) / 0.5
            self._center_opacity = t
            self._center_scale = 0.84 + 0.16 * t
        self.update()

    def _toggle_locked(self):
        if self._lock_anim and self._lock_anim.state() == QVariantAnimation.State.Running:
            return

        anim = QVariantAnimation(self)
        anim.setDuration(180)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        switched = {"done": False}

        def update(value):
            if value >= 0.5 and not switched["done"]:
                switched["done"] = True
                self._locked = not self._locked
                self.lock_toggled.emit(self._locked)
            self._set_center_anim_value(float(value))

        anim.valueChanged.connect(update)
        anim.finished.connect(lambda: self._set_center_anim_value(1.0))
        self._lock_anim = anim
        anim.start()

    def set_animation_fps(self, fps: int):
        self._fps = max(30, min(fps, 240))

    def _show_duration(self):
        return max(150, int(300 * 120 / self._fps))

    def _hide_duration(self):
        return max(100, int(200 * 120 / self._fps))

    def add_item(self, icon: str, label: str, color: QColor,
                 on_click: Callable, glyph: str = "", enabled: bool = True):
        w = RadialMenuItem(icon, label, color, glyph=glyph, enabled=enabled, parent=self)
        w.clicked.connect(on_click)
        w.clicked.connect(self._on_item_clicked)
        w.hide()

        opacity = QGraphicsOpacityEffect(w)
        opacity.setOpacity(0.0)
        w.setGraphicsEffect(opacity)

        self._items.append(_ItemData(
            widget=w,
            start_offset=QPoint(0, 0),
            end_offset=QPoint(0, 0),
            opacity_effect=opacity,
        ))

    def update_item(self, index: int, *, label: str | None = None,
                    glyph: str | None = None, enabled: bool | None = None,
                    color: QColor | None = None):
        if index < 0 or index >= len(self._items):
            return
        widget = self._items[index].widget
        if label is not None:
            widget.set_label(label)
        if glyph is not None:
            widget.set_glyph(glyph)
        if enabled is not None:
            widget.set_enabled_state(enabled)
        if color is not None:
            widget.set_color(color)

    def show_at(self, center: QPoint):
        if self._is_showing:
            return

        n = len(self._items)
        if n == 0:
            return

        self._center = center
        self._is_showing = True
        self._ignore_outside_click_until_release = self._mouse_buttons_pressed()
        self._set_center_reveal_value(0.0)

        total_w = self._radius * 2 + 80 * 2
        total_h = self._radius * 2 + 80 * 2
        self.setGeometry(
            center.x() - total_w // 2,
            center.y() - total_h // 2,
            total_w, total_h,
        )

        for i, item in enumerate(self._items):
            angle = -math.pi / 2 + (2 * math.pi * i / n)
            dx = int(self._radius * math.cos(angle))
            dy = int(self._radius * math.sin(angle))
            item.end_offset = QPoint(dx, dy)
            item.start_offset = QPoint(0, 0)

            item.widget.move(
                total_w // 2 - item.widget.width() // 2,
                total_h // 2 - item.widget.height() // 2,
            )
            item.widget.show()

        self.show()
        if sys.platform.startswith("linux"):
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(0, self.raise_)
            QTimer.singleShot(0, self.activateWindow)
        else:
            self.setFocus()
        self._play_show_animation()
        self._outside_click_timer.start()

    @staticmethod
    def _mouse_buttons_pressed() -> bool:
        if _get_async_key_state is not None:
            return any(
                bool(_get_async_key_state(button) & 0x8000)
                for button in (VK_LBUTTON, VK_RBUTTON, VK_MBUTTON)
            )
        return bool(QGuiApplication.mouseButtons())

    def _check_outside_click(self):
        if not self._is_showing or not self.isVisible():
            self._outside_click_timer.stop()
            return
        buttons_pressed = self._mouse_buttons_pressed()
        if not buttons_pressed:
            self._ignore_outside_click_until_release = False
            return
        if self._ignore_outside_click_until_release:
            return
        if not self.geometry().contains(QCursor.pos()):
            self.dismiss()

    def _play_show_animation(self):
        group = QParallelAnimationGroup(self)
        for item in self._items:
            anim = QPropertyAnimation(item.widget, b"pos")
            start_pos = item.widget.pos() + item.start_offset
            end_pos = item.widget.pos() + item.end_offset
            anim.setStartValue(start_pos)
            anim.setEndValue(end_pos)
            anim.setDuration(self._show_duration())
            anim.setEasingCurve(QEasingCurve.Type.OutBack)
            group.addAnimation(anim)

            op_anim = QPropertyAnimation(item.opacity_effect, b"opacity")
            op_anim.setStartValue(0.0)
            op_anim.setEndValue(1.0)
            op_anim.setDuration(max(120, self._show_duration() - 50))
            group.addAnimation(op_anim)

        center_anim = QVariantAnimation(self)
        center_anim.setStartValue(0.0)
        center_anim.setEndValue(1.0)
        center_anim.setDuration(max(140, self._show_duration() - 30))
        center_anim.setEasingCurve(QEasingCurve.Type.OutBack)
        center_anim.valueChanged.connect(lambda v: self._set_center_reveal_value(float(v)))
        group.addAnimation(center_anim)

        self._anim_group = group
        group.start()

    def _play_hide_animation(self):
        group = QParallelAnimationGroup(self)
        for item in self._items:
            anim = QPropertyAnimation(item.widget, b"pos")
            start_pos = item.widget.pos()
            end_pos = item.widget.pos() - item.end_offset
            anim.setStartValue(start_pos)
            anim.setEndValue(end_pos)
            anim.setDuration(self._hide_duration())
            anim.setEasingCurve(QEasingCurve.Type.InBack)
            group.addAnimation(anim)

            op_anim = QPropertyAnimation(item.opacity_effect, b"opacity")
            op_anim.setStartValue(1.0)
            op_anim.setEndValue(0.0)
            op_anim.setDuration(max(80, self._hide_duration() - 50))
            group.addAnimation(op_anim)

        center_anim = QVariantAnimation(self)
        center_anim.setStartValue(self._center_anim_value)
        center_anim.setEndValue(0.0)
        center_anim.setDuration(max(90, self._hide_duration() - 20))
        center_anim.setEasingCurve(QEasingCurve.Type.InBack)
        center_anim.valueChanged.connect(lambda v: self._set_center_reveal_value(float(v)))
        group.addAnimation(center_anim)

        group.finished.connect(self._on_hide_finished)
        self._anim_group = group
        group.start()

    def _on_hide_finished(self):
        self._outside_click_timer.stop()
        self._is_showing = False
        self.hide()
        self.closed.emit()

    def _on_item_clicked(self):
        self.dismiss()

    def dismiss(self):
        self._outside_click_timer.stop()
        if self._is_showing:
            if self._anim_group and self._anim_group.state() == QPropertyAnimation.State.Running:
                self._anim_group.stop()
            self._play_hide_animation()
        else:
            self.hide()
            self.closed.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        cx = self.width() // 2
        cy = self.height() // 2
        dx = event.pos().x() - cx
        dy = event.pos().y() - cy
        dist = (dx * dx + dy * dy) ** 0.5
        was_hover = self._center_hover
        self._center_hover = dist < 40
        if was_hover != self._center_hover:
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        if any(item.widget.geometry().contains(event.pos()) for item in self._items):
            super().mousePressEvent(event)
            return

        cx = self.width() // 2
        cy = self.height() // 2
        dx = event.pos().x() - cx
        dy = event.pos().y() - cy
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < 40:
            self._toggle_locked()
        else:
            self.dismiss()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() // 2
        cy = self.height() // 2
        rr = 30 * self._center_scale

        base = QColor("#3a3a3a") if self._center_hover else QColor("#2a2a2a")
        p.setOpacity(self._center_opacity)
        p.setPen(QPen(QColor("#555555"), 2))
        gradient = QRadialGradient(cx, cy - rr * 0.2, rr * 1.2)
        gradient.setColorAt(0, base.lighter(140))
        gradient.setColorAt(0.7, base)
        gradient.setColorAt(1, base.darker(140))
        p.setBrush(QBrush(gradient))
        p.drawEllipse(QPoint(int(cx), int(cy)), rr, rr)

        glyph = "\U0001F512" if self._locked else "\U0001F513"
        font = p.font()
        font.setPointSize(18)
        p.setFont(font)
        fm = QFontMetrics(font)
        g_w = fm.horizontalAdvance(glyph)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(int(cx - g_w / 2), int(cy + 6), glyph)
        p.setOpacity(1.0)
