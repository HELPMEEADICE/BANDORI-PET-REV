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

    def test_load_reads_latest_file_without_pending_save_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            new_data = {
                "character": "kasumi",
                "costume": "new_costume",
                "models": [{"character": "kasumi", "costume": "new_costume"}],
            }
            path.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
            config = ConfigManager(path)
            path.write_text(json.dumps(new_data), encoding="utf-8")

            config.load()

            self.assertEqual("new_costume", config.get("costume"))
            self.assertEqual("new_costume", config.get("models")[0]["costume"])

    def test_save_does_not_overwrite_existing_file_after_default_startup_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            config = ConfigManager(path)
            path.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")

            with patch("builtins.open", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    config._merged_data_for_save()

            self.assertEqual({"language": "zh_CN"}, json.loads(path.read_text(encoding="utf-8")))

    def test_save_uses_loaded_snapshot_on_transient_read_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
            config = ConfigManager(path)
            config.set("dark_theme", True)

            with patch("builtins.open", side_effect=OSError("busy")):
                merged = config._merged_data_for_save()

            self.assertEqual("zh_CN", merged["language"])
            self.assertTrue(merged["dark_theme"])


if __name__ == "__main__":
    unittest.main()
