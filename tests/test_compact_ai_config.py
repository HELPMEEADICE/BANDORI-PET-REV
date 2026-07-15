import unittest

from compact_ai_window import _font_size_from_config, _opacity_alpha


class CompactAiConfigTest(unittest.TestCase):
    def test_numeric_config_clamps_normal_values(self):
        self.assertEqual(38, _opacity_alpha(15))
        self.assertEqual(22, _font_size_from_config(30))

    def test_numeric_config_tolerates_infinite_values(self):
        self.assertEqual(112, _opacity_alpha(float("inf")))
        self.assertEqual(12, _font_size_from_config(float("inf")))


if __name__ == "__main__":
    unittest.main()
