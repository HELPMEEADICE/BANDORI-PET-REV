import sys
import unittest
from pathlib import Path

try:
    import resource
except ImportError:  # Windows has no resource module
    resource = None

import filesystem_mcp_server


class ReadTextFileTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_small_file_is_returned_verbatim(self):
        target = self.root / "small.txt"
        target.write_text("香澄的日记\nsecond line", encoding="utf-8")

        self.assertEqual(
            "香澄的日记\nsecond line",
            filesystem_mcp_server._read_text_file(target, max_chars=20_000),
        )

    def test_long_file_is_truncated_with_notice(self):
        target = self.root / "long.txt"
        target.write_text("a" * 5_000, encoding="utf-8")

        result = filesystem_mcp_server._read_text_file(target, max_chars=1_000)

        self.assertTrue(result.startswith("a" * 1_000))
        self.assertIn("[truncated to 1000 characters]", result)

    def test_file_exactly_at_limit_has_no_truncation_notice(self):
        target = self.root / "exact.txt"
        target.write_text("b" * 1_000, encoding="utf-8")

        result = filesystem_mcp_server._read_text_file(target, max_chars=1_000)

        self.assertEqual("b" * 1_000, result)

    @unittest.skipIf(resource is None, "resource module is Unix-only")
    def test_huge_file_does_not_load_fully_into_memory(self):
        target = self.root / "huge.log"
        chunk = b"x" * (1 << 20)
        with target.open("wb") as handle:
            for _ in range(200):  # 200 MB, written sparsely in chunks
                handle.write(chunk)

        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result = filesystem_mcp_server._read_text_file(target, max_chars=100_000)
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

        self.assertIn("[truncated to 100000 characters]", result)
        # ru_maxrss is bytes on macOS, kilobytes on Linux; either way the
        # 200 MB file must not appear in the process high-water mark.
        scale = 1 if sys.platform == "darwin" else 1024
        self.assertLess((after - before) * scale, 100 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
