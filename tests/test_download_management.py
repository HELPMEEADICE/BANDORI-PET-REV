import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from settings_window.pages.download_manager import (
    DownloadManagementPageMixin,
    discover_download_model_sources,
)
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


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class _DownloadWorker:
    def __init__(self, *_args, **_kwargs):
        self.progress = _Signal()
        self.finished = _Signal()
        self.error = _Signal()
        self.started = False

    def start(self):
        self.started = True


class _Widget:
    def __init__(self):
        self.enabled = True
        self.visible = False
        self.text = ""
        self.range = None
        self.value = None

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setRange(self, minimum, maximum):
        self.range = (minimum, maximum)

    def setValue(self, value):
        self.value = value

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def setText(self, text):
        self.text = text


class _DownloadPage(DownloadManagementPageMixin):
    pass


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

    def test_download_manager_starts_independent_workers_per_model(self):
        page = _DownloadPage()
        kasumi_button = _Widget()
        arisa_button = _Widget()
        page._download_manager_workers = {}
        page._download_manager_refresh_btn = _Widget()
        page._download_manager_action_buttons = {
            "kasumi": kasumi_button,
            "arisa": arisa_button,
        }
        page._download_manager_rows = {
            character: {
                "button": button,
                "progress": _Widget(),
                "progress_label": _Widget(),
            }
            for character, button in page._download_manager_action_buttons.items()
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "settings_window.pages.download_manager.MODELS_DIR", Path(temp_dir)
        ), patch(
            "settings_window.pages.download_manager.ModelPackageDownloadWorker",
            _DownloadWorker,
        ):
            page._start_download_manager_package("kasumi", force=True)
            page._start_download_manager_package("arisa", force=True)

        self.assertEqual({"kasumi", "arisa"}, set(page._download_manager_workers))
        self.assertFalse(kasumi_button.enabled)
        self.assertFalse(arisa_button.enabled)
        self.assertTrue(page._download_manager_rows["kasumi"]["progress"].visible)
        self.assertTrue(page._download_manager_rows["arisa"]["progress"].visible)
        self.assertFalse(page._download_manager_refresh_btn.enabled)


if __name__ == "__main__":
    unittest.main()
