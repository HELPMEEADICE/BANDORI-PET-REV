import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from pet_window import PetWindow


class FakeScreen:
    def __init__(self, geometry: QRect):
        self._geometry = geometry

    def availableGeometry(self):
        return QRect(self._geometry)


class PositionHarness(QWidget):
    _constrain_position_to_screen = PetWindow._constrain_position_to_screen


class ScaleHarness(QWidget):
    _live2d_size = PetWindow._live2d_size
    set_live2d_scale = PetWindow.set_live2d_scale

    def __init__(self):
        super().__init__()
        self._pixel_mode = False
        self._live2d_scale = 100

    def _sync_compact_ai_window(self):
        pass


class PetWindowPositioningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_full_constraint_recovers_window_from_right_and_bottom_edges(self):
        harness = PositionHarness()
        harness.resize(400, 500)
        screen = FakeScreen(QRect(0, 0, 1920, 1080))

        self.assertEqual(
            (1520, 580),
            harness._constrain_position_to_screen(
                1900,
                1000,
                screen,
                allow_partial=False,
            ),
        )

    def test_full_constraint_handles_window_larger_than_screen(self):
        harness = PositionHarness()
        harness.resize(2400, 3000)
        screen = FakeScreen(QRect(100, 50, 1920, 1080))

        self.assertEqual(
            (100, 50),
            harness._constrain_position_to_screen(
                -1000,
                -1000,
                screen,
                allow_partial=False,
            ),
        )

    def test_scaling_keeps_saved_window_position(self):
        harness = ScaleHarness()
        harness.resize(400, 500)
        harness.move(1700, 900)

        harness.set_live2d_scale(200)

        self.assertEqual((800, 1000), (harness.width(), harness.height()))
        self.assertEqual((1700, 900), (harness.x(), harness.y()))


if __name__ == "__main__":
    unittest.main()
