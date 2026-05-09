import math
import os
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import (
    Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve,
    QParallelAnimationGroup, QVariantAnimation,
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QMouseEvent,
    QRadialGradient, QFontMetrics, QPixmap,
)
from PySide6.QtWidgets import (
    QWidget, QGraphicsOpacityEffect,
)


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

        gradient = QRadialGradient(cx, cy - r * 0.3, r * 1.2)
        gradient.setColorAt(0, color.lighter(150))
        gradient.setColorAt(0.7, color)
        gradient.setColorAt(1, color.darker(120))
        p.setBrush(QBrush(gradient))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

        p.setBrush(QColor(255, 255, 255, 40 if self._hover else 10))
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r * 0.85), int(r * 0.85))

        if self._icon and not self._icon.isNull():
            icon_size = int(r * 0.7)
            scaled = self._icon.scaled(
                icon_size, icon_size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            p.drawPixmap(int(cx - icon_size / 2), int(cy - icon_size / 2 - r * 0.15), scaled)
        elif self._glyph:
            font = p.font()
            font.setPointSize(22)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 240))
            fm = QFontMetrics(font)
            g_w = fm.horizontalAdvance(self._glyph)
            p.drawText(int(cx - g_w / 2), int(cy - 2), self._glyph)

        font = p.font()
        font.setPointSize(9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255, 230))
        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(self._label)
        p.drawText(int(cx - text_w / 2), int(cy + r * 0.55), self._label)

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
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

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

        self.setMouseTracking(True)

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

    def show_at(self, center: QPoint):
        if self._is_showing:
            return

        n = len(self._items)
        if n == 0:
            return

        self._center = center
        self._is_showing = True
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
        self.setFocus()
        self._play_show_animation()

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
        self._is_showing = False
        self.hide()
        self.closed.emit()

    def _on_item_clicked(self):
        self.dismiss()

    def dismiss(self):
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
        cx = self.width() // 2
        cy = self.height() // 2
        dx = event.pos().x() - cx
        dy = event.pos().y() - cy
        dist = (dx * dx + dy * dy) ** 0.5

        if dist < 40:
            self._toggle_locked()
        elif dist > self._radius + 50:
            self.dismiss()
        else:
            super().mousePressEvent(event)

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
