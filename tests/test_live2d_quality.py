import unittest

from bandori_live2d.live2d_quality import clamp_live2d_scale, clamp_moc3_visible_height


class Live2DQualityTest(unittest.TestCase):
    def test_scale_clamps_normal_values(self):
        self.assertEqual(25, clamp_live2d_scale(1))
        self.assertEqual(250, clamp_live2d_scale(250))
        self.assertEqual(500, clamp_live2d_scale(999))

    def test_scale_tolerates_infinite_config_value(self):
        self.assertEqual(100, clamp_live2d_scale(float("inf")))

    def test_moc3_visible_height_is_clamped_to_supported_range(self):
        self.assertEqual(500, clamp_moc3_visible_height(0))
        self.assertEqual(640, clamp_moc3_visible_height(640))
        self.assertEqual(800, clamp_moc3_visible_height(999))
        self.assertEqual(500, clamp_moc3_visible_height(float("inf")))


if __name__ == "__main__":
    unittest.main()
