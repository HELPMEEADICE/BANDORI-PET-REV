"""Decode settings thumbnails without retaining full-size source images."""

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader


def read_scaled_image(path: str, data: bytes, size: QSize) -> QImage:
    def read(reader):
        reader.setAutoTransform(True)
        source_size = reader.size()
        if source_size.isValid() and size.isValid():
            reader.setScaledSize(source_size.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if not image.isNull() and size.isValid():
            image = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        return image

    if path:
        image = read(QImageReader(path))
        if not image.isNull():
            return image
    if data:
        buffer = QBuffer()
        buffer.setData(data)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        return read(QImageReader(buffer))
    return QImage()
