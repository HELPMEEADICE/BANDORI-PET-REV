import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bandori_live2d.live2d_quality import clamp_live2d_scale, clamp_moc3_visible_height


class Live2DQualityTest(unittest.TestCase):
    def test_scale_clamps_normal_values(self):
        self.assertEqual(25, clamp_live2d_scale(1))
        self.assertEqual(250, clamp_live2d_scale(250))
        self.assertEqual(500, clamp_live2d_scale(999))

    def test_scale_tolerates_infinite_config_value(self):
        self.assertEqual(100, clamp_live2d_scale(float("inf")))

    def test_missing_scale_defaults_to_100(self):
        from bandori_core.config_manager import DEFAULTS

        self.assertEqual(100, DEFAULTS["live2d_scale"])

    def test_settings_scale_reset_does_not_apply_screen_dpi(self):
        from settings_window.pages.quality import QualityPageMixin

        controls = SimpleNamespace(
            _live2d_scale_input=Mock(), _live2d_scale_slider=Mock(),
        )
        for dpr in (1.0, 1.25, 1.5, 2.0, 3.0):
            screen = SimpleNamespace(devicePixelRatio=lambda: dpr)
            with self.subTest(dpr=dpr), patch(
                "PySide6.QtWidgets.QApplication.primaryScreen", return_value=screen,
            ):
                QualityPageMixin._set_live2d_scale_controls(controls, 0)
                self.assertEqual(100, controls._live2d_scale)
                controls._live2d_scale_slider.setValue.assert_called_with(100)
                controls._live2d_scale_input.setText.assert_called_with("100")
                QualityPageMixin._set_live2d_scale_controls(controls, 200)
                self.assertEqual(200, controls._live2d_scale)

    def test_legacy_and_invalid_scale_fall_back_to_100(self):
        for value in (0, -1, None, "bad", float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assertEqual(100, clamp_live2d_scale(value))

    def test_moc3_visible_height_is_clamped_to_supported_range(self):
        self.assertEqual(500, clamp_moc3_visible_height(0))
        self.assertEqual(640, clamp_moc3_visible_height(640))
        self.assertEqual(800, clamp_moc3_visible_height(999))
        self.assertEqual(500, clamp_moc3_visible_height(float("inf")))


if __name__ == "__main__":
    unittest.main()
