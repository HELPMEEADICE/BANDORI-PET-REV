import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager


class _ImmediateThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class ConfigSaveResultTests(unittest.TestCase):
    def test_save_returns_true_after_file_is_written(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            config = ConfigManager(path)
            config.set("language", "ja")

            with patch("config_manager.threading.Thread", _ImmediateThread):
                self.assertIs(config.save(), True)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("ja", saved["language"])

    def test_save_returns_false_when_existing_config_cannot_be_merged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
            config = ConfigManager(path)
            config.set("dark_theme", True)

            with patch.object(config, "_merged_data_for_save", side_effect=OSError("busy")):
                result = config.save()

            self.assertIs(result, False)
            self.assertEqual({"language": "zh_CN"}, json.loads(path.read_text(encoding="utf-8")))

    def test_save_returns_false_when_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"language": "zh_CN"}), encoding="utf-8")
            config = ConfigManager(path)
            config.set("language", "ja")

            with patch("config_manager._try_replace_file", return_value=OSError("locked")), \
                 patch("config_manager.time.sleep", return_value=None), \
                 patch("config_manager.threading.Thread", _ImmediateThread):
                result = config.save()

            self.assertIs(result, False)
            self.assertEqual("zh_CN", json.loads(path.read_text(encoding="utf-8"))["language"])
            self.assertEqual([], list(path.parent.glob("config.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
