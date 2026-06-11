import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import DEFAULTS, ConfigManager


class ConfigLoadSafetyTests(unittest.TestCase):
    def test_transient_read_error_does_not_move_valid_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"language": "zh_CN"}),
                encoding="utf-8",
            )

            with patch("config_manager.json.load", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    ConfigManager(path)

            self.assertTrue(path.exists())
            self.assertEqual([], list(path.parent.glob("config.json.corrupt-*.bak")))

    def test_invalid_json_is_backed_up(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            config = ConfigManager(path)

            self.assertFalse(path.exists())
            self.assertEqual(DEFAULTS["language"], config.get("language"))
            self.assertEqual(1, len(list(path.parent.glob("config.json.corrupt-*.bak"))))


if __name__ == "__main__":
    unittest.main()
