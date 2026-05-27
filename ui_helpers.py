import os

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QTextEdit
from qfluentwidgets.components.widgets.menu import TextEditMenu


AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
INTERRUPT_COMMANDS = {"@stop", "/stop", "@停止", "/停止", "@中断", "/中断", "@interrupt", "/interrupt"}


class FluentContextTextEdit(QTextEdit):
    def contextMenuEvent(self, event):
        menu = TextEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


def circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    if source.isNull():
        return QPixmap()

    scaled = source.scaled(
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
    return rounded


def rounded_avatar_pixmap(path: str, size: int) -> QPixmap:
    if not path or not os.path.exists(path):
        return QPixmap()
    source = QPixmap(path)
    if source.isNull():
        return QPixmap()

    side = min(source.width(), source.height())
    crop = source.copy(
        max(0, (source.width() - side) // 2),
        max(0, (source.height() - side) // 2),
        side,
        side,
    )
    return circular_pixmap(crop, size)
