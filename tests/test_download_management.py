import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from settings_window.pages.download_manager import discover_download_model_sources
from settings_window.settings_window import SettingsWindow
from settings_window.workers import ModelPackageDownloadWorker


class _DownloadResponse:
    headers = {"Content-Length": "3"}

    def __init__(self):
        self._chunks = [b"new", b""]

    def read(self, _size):
        return self._chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class DownloadManagementTests(unittest.TestCase):
    def test_discovers_zst_and_folder_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "kasumi.zst").write_bytes(b"archive")
            model_json = root / "custom" / "default" / "model.json"
            model_json.parent.mkdir(parents=True)
            model_json.write_text("{}", encoding="utf-8")

            sources = discover_download_model_sources([root])

        self.assertEqual(["kasumi.zst"], [path.name for path in sources["kasumi"]["archives"]])
        self.assertEqual(["custom"], [path.name for path in sources["custom"]["folders"]])

    def test_overwrite_download_replaces_existing_zst_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models_dir = Path(temp_dir)
            target = models_dir / "kasumi.zst"
            target.write_bytes(b"old")
            worker = ModelPackageDownloadWorker(["kasumi"], models_dir, overwrite=True)
            worker._started_at = time.monotonic()

            with patch("settings_window.workers.urllib.request.urlopen", return_value=_DownloadResponse()):
                worker._download_one("kasumi")

            self.assertEqual(b"new", target.read_bytes())

    def test_wizard_footer_update_is_safe_outside_first_run_wizard(self):
        SettingsWindow._update_wizard_footer(object())


if __name__ == "__main__":
    unittest.main()
