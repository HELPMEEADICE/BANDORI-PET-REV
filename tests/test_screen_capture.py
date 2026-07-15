import unittest

from screen_capture import _int


class ScreenCaptureTest(unittest.TestCase):
    def test_integer_conversion_rounds_normal_values(self):
        self.assertEqual(13, _int(12.6, 100))

    def test_integer_conversion_tolerates_infinite_value(self):
        self.assertEqual(1280, _int(float("inf"), 1280))


if __name__ == "__main__":
    unittest.main()
