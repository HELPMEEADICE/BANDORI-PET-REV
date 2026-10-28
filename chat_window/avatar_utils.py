import os

import numpy as np
from PySide6.QtGui import QImage, QPixmap

from bandori_ui.ui_helpers import circular_pixmap

from .constants import _AVATAR_PIXMAP_CACHE, _AVATAR_PIXMAP_CACHE_LIMIT


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

    alpha = _qimage_alpha_array(image)[::step, ::step]
    ys, xs = np.nonzero(alpha > 12)
    if xs.size == 0:
        return 0, 0, width, height

    left = int(xs.min()) * step
    right = int(xs.max()) * step
    top = int(ys.min()) * step
    bottom = int(ys.max()) * step
    return (
        max(0, left - step),
        max(0, top - step),
        min(width, right + step + 1),
        min(height, bottom + step + 1),
    )


def _qimage_alpha_array(image: QImage):
    ptr = image.constBits()
    row_bytes = image.bytesPerLine()
    data = np.frombuffer(ptr, dtype=np.uint8, count=row_bytes * image.height())
    rows = data.reshape((image.height(), row_bytes))[:, :image.width() * 4]
    return rows.reshape((image.height(), image.width(), 4))[:, :, 3]


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
    alpha = _qimage_alpha_array(image)
    region = alpha[top:min(bottom, upper_bottom):step, left:right:step]
    _, xs = np.nonzero(region > 12)

    center_x = (left + float(xs.mean()) * step) if xs.size else left + content_w * 0.5
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
