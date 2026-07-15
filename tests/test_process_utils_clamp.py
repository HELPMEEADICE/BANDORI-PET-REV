import unittest

from process_utils import clamp_int


class ProcessUtilsClampTest(unittest.TestCase):
    def test_integer_clamp_rounds_and_limits_normal_values(self):
        self.assertEqual(13, clamp_int(12.6, 1, 100, 20))
        self.assertEqual(100, clamp_int(500, 1, 100, 20))

    def test_integer_clamp_tolerates_infinite_value(self):
        self.assertEqual(38472, clamp_int(float("inf"), 1024, 65535, 38472))


if __name__ == "__main__":
    unittest.main()
