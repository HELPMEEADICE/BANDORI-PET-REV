import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from chat_config_snapshots import tts_config_snapshot
from config_manager import ConfigManager
from settings_window.pages.tts import TTSPageMixin
from tts_manager import TTSRequestWorker


class _SettingsHarness(QWidget, TTSPageMixin):
    def __init__(self, config):
        super().__init__()
        self._cfg = config
        self._model_manager = SimpleNamespace(characters={})

    def _make_theme_widget(self, widget):
        return widget

    def _connect_theme_changed(self, callback):
        pass

    def _config_save_deferred(self):
        return False


class TTSReferenceTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_default_position_save_and_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"tts_enabled": true}', encoding="utf-8")
            config = ConfigManager(path)
            window = _SettingsHarness(config)
            page = window._build_tts_page()
            self.assertFalse(window._tts_use_reference_text.isChecked())
            self.assertFalse(tts_config_snapshot(config)["tts_use_reference_text"])
            rows = [page.layout().itemAt(i).layout() for i in range(page.layout().count())]
            translate_row = next(i for i, row in enumerate(rows) if row and
                                 row.indexOf(window._tts_translate_to_selected_language) >= 0)
            self.assertGreaterEqual(rows[translate_row + 1].indexOf(window._tts_use_reference_text), 0)
            for enabled in (True, False):
                with self.subTest(enabled=enabled):
                    window._tts_use_reference_text.setChecked(enabled)
                    self.assertEqual(enabled, window._current_tts_config(include_llm=True)["tts_use_reference_text"])
                    self.assertTrue(window._save_tts_config(show_info=False))
                    reloaded = ConfigManager(path)
                    self.assertEqual(enabled, tts_config_snapshot(reloaded)["tts_use_reference_text"])
                    window._cfg = reloaded
                    window._tts_use_reference_text.setChecked(not enabled)
                    window._load_tts_config()
                    self.assertEqual(enabled, window._tts_use_reference_text.isChecked())
            page.deleteLater()
            window.deleteLater()

    def test_requests_only_include_reference_text_when_enabled(self):
        for streaming in (True, False):
            for enabled in (None, False, True):
                with self.subTest(streaming=streaming, enabled=enabled):
                    config = {
                        "tts_api_url": "http://tts-reference-test/",
                        "tts_language": "Japanese",
                        "tts_translate_to_selected_language": False,
                        "tts_streaming": streaming,
                    }
                    if enabled is not None:
                        config["tts_use_reference_text"] = enabled
                    worker = TTSRequestWorker(0, 1, "こんにちは", "character", config)
                    session = Mock()
                    session.post.return_value = SimpleNamespace(
                        status_code=200, headers={}, content=b"audio",
                        iter_content=lambda **kwargs: iter([b"audio"]), close=lambda: None,
                    )
                    audio = []
                    errors = []
                    worker.audio_ready.connect(lambda *args: audio.append(args))
                    worker.error.connect(errors.append)
                    with patch("tts_manager._requests", return_value=SimpleNamespace(Session=lambda: session)), \
                         patch.object(worker, "_reference_audio_path", return_value="reference.wav"), \
                         patch.object(worker, "_reference_prompt_text", return_value="参照テキスト") as reference_text, \
                         patch.object(worker, "_apply_qwen_lora"):
                        worker.run()
                    payload = session.post.call_args.kwargs["json"]
                    self.assertEqual("reference.wav", payload["refer_wav_path"])
                    self.assertEqual("こんにちは", payload["text"])
                    self.assertEqual("normal" if streaming else "close", payload["stream_mode"])
                    if enabled:
                        self.assertEqual("参照テキスト", payload["prompt_text"])
                        reference_text.assert_called_once_with("Japanese")
                    else:
                        self.assertNotIn("prompt_text", payload)
                        reference_text.assert_not_called()
                    self.assertEqual([], errors)
                    self.assertEqual(1, len(audio))

    def test_enabled_request_uses_selected_character_reference_text(self):
        with tempfile.TemporaryDirectory() as directory:
            reference_dir = Path(directory) / "audio_reference"
            reference_dir.mkdir()
            (reference_dir / "dialog.json").write_text(
                '{"current": "current text", "selected": "selected text"}', encoding="utf-8")
            worker = TTSRequestWorker(0, 1, "text", "current", {
                "tts_use_reference_text": True, "tts_reference_character": "selected",
            })
            with patch("tts_manager.app_base_dir", return_value=Path(directory)):
                self.assertEqual("selected text", worker._reference_prompt_text("Japanese"))
                self.assertEqual("", worker._reference_prompt_text("Chinese"))
                self.assertEqual("", worker._reference_prompt_text("English"))


if __name__ == "__main__":
    unittest.main()
