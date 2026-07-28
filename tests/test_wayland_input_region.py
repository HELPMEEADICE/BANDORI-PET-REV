import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage

from wayland.input_region import qimage_frame_region, rgba_bytes_to_region


class WaylandInputRegionTest(unittest.TestCase):
    def test_rgba_mask_builds_only_opaque_rectangles(self):
        width, height = 4, 3
        rgba = bytearray(width * height * 4)
        for x, y in ((1, 0), (2, 0), (1, 1), (2, 1)):
            rgba[(y * width + x) * 4 + 3] = 255

        region, _mask_hash = rgba_bytes_to_region(
            rgba,
            width,
            height,
            width,
            height,
            8,
            flip_y=False,
            dilation=0,
        )

        self.assertTrue(region.contains(QPoint(1, 0)))
        self.assertTrue(region.contains(QPoint(2, 1)))
        self.assertFalse(region.contains(QPoint(0, 0)))
        self.assertFalse(region.contains(QPoint(3, 2)))

    def test_framebuffer_is_flipped_to_qt_top_left_coordinates(self):
        rgba = bytearray(2 * 2 * 4)
        rgba[(0 * 2 + 0) * 4 + 3] = 255

        region, _mask_hash = rgba_bytes_to_region(
            rgba,
            2,
            2,
            2,
            2,
            8,
            flip_y=True,
            dilation=0,
        )

        self.assertTrue(region.contains(QPoint(0, 1)))
        self.assertFalse(region.contains(QPoint(0, 0)))

    def test_qimage_frame_uses_selected_sprite_cell(self):
        image = QImage(4, 2, QImage.Format.Format_RGBA8888)
        image.fill(0)
        image.setPixelColor(3, 0, 0xFFFFFFFF)

        region = qimage_frame_region(
            image,
            QRect(2, 0, 2, 2),
            2,
            2,
            8,
            dilation=0,
        )

        self.assertTrue(region.contains(QPoint(1, 0)))
        self.assertFalse(region.contains(QPoint(0, 0)))

    def test_fractional_downscale_and_edge_expansion_use_logical_pixels(self):
        physical_width = physical_height = 5
        rgba = bytearray(physical_width * physical_height * 4)
        rgba[(2 * physical_width + 2) * 4 + 3] = 255

        region, _mask_hash = rgba_bytes_to_region(
            rgba,
            physical_width,
            physical_height,
            3,
            3,
            8,
            flip_y=False,
            dilation=1,
        )

        self.assertTrue(region.contains(QPoint(1, 1)))
        self.assertTrue(region.contains(QPoint(0, 1)))
        self.assertTrue(region.contains(QPoint(2, 1)))

    def test_alpha_threshold_is_strict(self):
        rgba = bytearray(4)
        rgba[3] = 8
        equal_region, _ = rgba_bytes_to_region(
            rgba, 1, 1, 1, 1, 8, flip_y=False, dilation=0
        )
        rgba[3] = 9
        above_region, _ = rgba_bytes_to_region(
            rgba, 1, 1, 1, 1, 8, flip_y=False, dilation=0
        )

        self.assertTrue(equal_region.isEmpty())
        self.assertFalse(above_region.isEmpty())


if __name__ == "__main__":
    unittest.main()
