import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager
from screen_awareness import (
    SCREEN_AWARENESS_MODEL_MODE_AUX,
    SCREEN_AWARENESS_MODEL_MODE_MAIN,
    ScreenAwarenessVisionWorker,
    normalize_screen_awareness_model_mode,
    screen_awareness_aux_config,
)


class ScreenAwarenessTest(unittest.TestCase):
    def test_model_mode_normalization_defaults_to_main(self):
        self.assertEqual(SCREEN_AWARENESS_MODEL_MODE_MAIN, normalize_screen_awareness_model_mode(None))
        self.assertEqual(SCREEN_AWARENESS_MODEL_MODE_MAIN, normalize_screen_awareness_model_mode("unknown"))
        self.assertEqual(SCREEN_AWARENESS_MODEL_MODE_AUX, normalize_screen_awareness_model_mode("aux"))

    def test_aux_config_reuses_main_credentials_but_requires_aux_model(self):
        config = {
            "llm_api_url": "http://localhost:8000/v1",
            "llm_api_key": "main-key",
            "llm_model_id": "main-vl",
            "llm_aux_model_id": "aux-vl",
        }
        self.assertEqual(
            ("http://localhost:8000/v1", "main-key", "aux-vl"),
            screen_awareness_aux_config(config),
        )
        config["llm_aux_model_id"] = ""
        self.assertEqual("", screen_awareness_aux_config(config)[2])

    def test_main_mode_returns_screenshot_without_aux_call(self):
        results = []
        errors = []
        worker = ScreenAwarenessVisionWorker({"screen_awareness_model_mode": "main"})
        worker.finished.connect(results.append)
        worker.error.connect(errors.append)

        with (
            patch("screen_awareness.capture_screenshot_data_url", return_value=("data:image/png;base64,abc", 800, 600, 800, 600)),
            patch("screen_awareness.analyze_images_with_aux_model") as analyze,
        ):
            worker.run()

        self.assertEqual([], errors)
        self.assertEqual("data:image/png;base64,abc", results[0]["screen_image_data_url"])
        self.assertEqual("", results[0]["screen_observation"])
        analyze.assert_not_called()

    def test_aux_mode_returns_summary_without_forwarding_screenshot(self):
        results = []
        errors = []
        worker = ScreenAwarenessVisionWorker({
            "screen_awareness_model_mode": "aux",
            "llm_api_url": "http://localhost:8000/v1",
            "llm_api_key": "key",
            "llm_aux_model_id": "qwen-vl",
        })
        worker.finished.connect(results.append)
        worker.error.connect(errors.append)

        with (
            patch("screen_awareness.capture_screenshot_data_url", return_value=("data:image/png;base64,abc", 800, 600, 800, 600)),
            patch("screen_awareness.analyze_images_with_aux_model", return_value="用户正在查看代码。") as analyze,
        ):
            worker.run()

        self.assertEqual([], errors)
        self.assertEqual("", results[0]["screen_image_data_url"])
        self.assertEqual("用户正在查看代码。", results[0]["screen_observation"])
        self.assertIsNone(analyze.call_args.args[5])

    def test_legacy_vision_fields_are_not_kept_in_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "screen_awareness_model_mode": "aux",
                "screen_awareness_vision_api_url": "http://legacy",
                "screen_awareness_vision_api_key": "legacy-key",
                "screen_awareness_vision_model_id": "legacy-model",
                "screen_awareness_vision_enable_thinking": True,
            }), encoding="utf-8")
            config = ConfigManager(path)

        self.assertEqual("aux", config.get("screen_awareness_model_mode"))
        for key in (
            "screen_awareness_vision_api_url",
            "screen_awareness_vision_api_key",
            "screen_awareness_vision_model_id",
            "screen_awareness_vision_enable_thinking",
        ):
            self.assertNotIn(key, config._data)

    def test_legacy_config_inherits_reminder_display_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "reminder_display_mode": "system",
            }), encoding="utf-8")
            config = ConfigManager(path)

        self.assertEqual("system", config.get("screen_awareness_display_mode"))

    def test_legacy_display_mode_migration_is_persisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "reminder_display_mode": "system",
            }), encoding="utf-8")
            config = ConfigManager(path)
            config.save()
            reloaded = ConfigManager(path)

        self.assertEqual("system", reloaded.get("screen_awareness_display_mode"))


if __name__ == "__main__":
    unittest.main()
