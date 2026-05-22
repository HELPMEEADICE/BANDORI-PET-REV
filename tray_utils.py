import os
import sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from process_utils import app_base_dir


def load_tray_icon() -> QIcon:
    base_dir = str(app_base_dir())
    for name in ("logo.png", "logo.ico", "logo.icns"):
        path = os.path.join(base_dir, name)
        if not os.path.exists(path):
            continue
        icon = _icon_from_image(path) if sys.platform == "darwin" else QIcon(path)
        if not icon.isNull():
            return icon
    return _fallback_icon()


def keep_tray_icon_visible(tray_icon, attempts: int = 8, interval_ms: int = 350):
    if tray_icon is None:
        return

    def reshow(remaining: int):
        try:
            if tray_icon.icon().isNull():
                tray_icon.setIcon(load_tray_icon())
            tray_icon.setVisible(True)
            tray_icon.show()
        except RuntimeError:
            return
        if sys.platform == "darwin" and remaining > 0:
            QTimer.singleShot(interval_ms, lambda: reshow(remaining - 1))

    reshow(max(0, attempts))


def _icon_from_image(path: str) -> QIcon:
    if QApplication.instance() is None:
        return QIcon(path)
    image = QImage(path)
    if image.isNull():
        return QIcon(path)
    size = 22
    content_size = 17
    dpr = _device_pixel_ratio()
    pixel_size = int(round(size * dpr))
    content_pixels = int(round(content_size * dpr))
    image = image.scaled(
        content_pixels,
        content_pixels,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.drawImage(
        QRectF((size - content_size) * 0.5, (size - content_size) * 0.5, content_size, content_size),
        image,
    )
    painter.end()
    icon = QIcon()
    icon.addPixmap(pixmap)
    return icon


def _device_pixel_ratio() -> float:
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    return max(1.0, float(screen.devicePixelRatio()))


def _fallback_icon() -> QIcon:
    if QApplication.instance() is None:
        return QIcon()
    pixmap = QPixmap(22, 22)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#e84d8a"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, 20, 20)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(11)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "BP")
    painter.end()
    return QIcon(pixmap)
