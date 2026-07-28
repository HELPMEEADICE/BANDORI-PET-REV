from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QRegion


def _merge_boolean_rows(opaque, *, dilation: int = 0) -> QRegion:
    """Convert a 2-D NumPy boolean array to vertically merged rectangles."""

    import numpy as np

    height, width = opaque.shape
    active: dict[tuple[int, int], list[int]] = {}
    rectangles: list[tuple[int, int, int, int]] = []
    for y in range(height):
        padded = np.empty(width + 2, dtype=np.int8)
        padded[0] = 0
        padded[-1] = 0
        padded[1:-1] = opaque[y]
        changes = np.flatnonzero(padded[1:] != padded[:-1])
        spans = {(int(changes[i]), int(changes[i + 1])) for i in range(0, len(changes), 2)}
        next_active: dict[tuple[int, int], list[int]] = {}
        for span in spans:
            rect = active.pop(span, None)
            if rect is None:
                rect = [span[0], y, span[1] - span[0], 1]
            else:
                rect[3] += 1
            next_active[span] = rect
        rectangles.extend(tuple(rect) for rect in active.values())
        active = next_active
    rectangles.extend(tuple(rect) for rect in active.values())

    region = QRegion()
    pad = max(0, int(dilation))
    bounds = QRect(0, 0, int(width), int(height))
    for x, y, w, h in rectangles:
        rect = QRect(x - pad, y - pad, w + pad * 2, h + pad * 2).intersected(bounds)
        if not rect.isEmpty():
            region = region.united(QRegion(rect))
    return region


def rgba_bytes_to_region(
    rgba,
    physical_width: int,
    physical_height: int,
    logical_width: int,
    logical_height: int,
    threshold: int,
    *,
    flip_y: bool = True,
    dilation: int = 1,
) -> tuple[QRegion, int]:
    """Build a logical input region from an RGBA framebuffer.

    The returned hash is based on the logical boolean mask and can be used to
    suppress redundant ``wl_surface.set_input_region`` commits.
    """

    import numpy as np

    physical_width = max(1, int(physical_width))
    physical_height = max(1, int(physical_height))
    logical_width = max(1, int(logical_width))
    logical_height = max(1, int(logical_height))
    expected = physical_width * physical_height * 4
    pixels = np.frombuffer(rgba, dtype=np.uint8, count=expected)
    if pixels.size != expected:
        raise ValueError(f"expected {expected} RGBA bytes, got {pixels.size}")
    alpha = pixels.reshape((physical_height, physical_width, 4))[:, :, 3]
    if flip_y:
        alpha = alpha[::-1]
    physical_opaque = alpha > max(0, min(int(threshold), 255))
    integral = np.pad(
        physical_opaque.astype(np.uint32),
        ((1, 0), (1, 0)),
        mode="constant",
    ).cumsum(axis=0).cumsum(axis=1)
    y0 = (
        np.arange(logical_height, dtype=np.int64) * physical_height
    ) // logical_height
    y1 = (
        (np.arange(1, logical_height + 1, dtype=np.int64) * physical_height)
        + logical_height
        - 1
    ) // logical_height
    x0 = (
        np.arange(logical_width, dtype=np.int64) * physical_width
    ) // logical_width
    x1 = (
        (np.arange(1, logical_width + 1, dtype=np.int64) * physical_width)
        + logical_width
        - 1
    ) // logical_width
    y1 = np.minimum(physical_height, np.maximum(y0 + 1, y1))
    x1 = np.minimum(physical_width, np.maximum(x0 + 1, x1))
    opaque_counts = (
        integral[y1[:, None], x1[None, :]]
        - integral[y0[:, None], x1[None, :]]
        - integral[y1[:, None], x0[None, :]]
        + integral[y0[:, None], x0[None, :]]
    )
    opaque = opaque_counts > 0
    return _merge_boolean_rows(opaque, dilation=dilation), hash(opaque.tobytes())


def qimage_frame_region(
    image: QImage,
    source: QRect,
    logical_width: int,
    logical_height: int,
    threshold: int,
    *,
    dilation: int = 1,
) -> QRegion:
    if image.isNull() or source.isEmpty():
        return QRegion()
    frame = image.copy(source).convertToFormat(QImage.Format.Format_RGBA8888)
    if frame.width() != logical_width or frame.height() != logical_height:
        frame = frame.scaled(
            max(1, int(logical_width)),
            max(1, int(logical_height)),
        )
    size = frame.sizeInBytes()
    bits = frame.constBits()
    try:
        bits.setsize(size)
    except AttributeError:
        pass
    region, _mask_hash = rgba_bytes_to_region(
        bytes(bits),
        frame.width(),
        frame.height(),
        frame.width(),
        frame.height(),
        threshold,
        flip_y=False,
        dilation=dilation,
    )
    return region
