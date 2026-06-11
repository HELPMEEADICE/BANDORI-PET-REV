import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config_manager import ConfigManager
from reminder_core import normalize_proactive_companion
from screen_awareness import (
    SCREEN_AWARENESS_MODEL_MODE_AUX,
    SCREEN_AWARENESS_MODEL_MODE_MAIN,
    ScreenAwarenessVisionWorker,
    normalize_screen_awareness_model_mode,
    screen_awareness_aux_config,
    screen_awareness_desktop_state,
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
            patch("screen_awareness.current_desktop_state", return_value={
                "state": "coding",
                "label": "写代码",
                "confidence": 0.9,
                "reason": "前台应用是开发工具",
                "foreground_title": "private.py",
                "process_name": "code.exe",
                "idle_seconds": 5,
                "idle_threshold_seconds": 180,
                "captured_at": "2026-06-09T02:00:00",
            }),
            patch("screen_awareness.analyze_images_with_aux_model") as analyze,
        ):
            worker.run()

        self.assertEqual([], errors)
        self.assertEqual("data:image/png;base64,abc", results[0]["screen_image_data_url"])
        self.assertEqual("", results[0]["screen_observation"])
        self.assertEqual("coding", results[0]["desktop_state"]["state"])
        self.assertEqual("code.exe", results[0]["desktop_state"]["process_name"])
        self.assertNotIn("foreground_title", results[0]["desktop_state"])
        analyze.assert_not_called()

    def test_desktop_state_context_privacy_defaults(self):
        with patch("screen_awareness.current_desktop_state", return_value={
            "state": "coding",
            "label": "写代码",
            "confidence": 0.9,
            "reason": "dev tool",
            "foreground_title": "secret.py - Project",
            "process_name": "code.exe",
            "app_name": "Code",
            "process_path": "C:/Users/name/AppData/Code.exe",
            "idle_seconds": 5,
            "idle_threshold_seconds": 180,
            "captured_at": "2026-06-09T02:00:00",
        }):
            state = screen_awareness_desktop_state({})

        self.assertEqual("code.exe", state["process_name"])
        self.assertEqual("Code", state["app_name"])
        self.assertNotIn("foreground_title", state)
        self.assertNotIn("process_path", state)

    def test_desktop_state_can_hide_process_name(self):
        with patch("screen_awareness.current_desktop_state", return_value={
            "state": "web",
            "process_name": "chrome.exe",
            "app_name": "Chrome",
        }):
            state = screen_awareness_desktop_state({"screen_awareness_include_process_name": False})

        self.assertNotIn("process_name", state)
        self.assertNotIn("app_name", state)

    def test_desktop_state_can_include_window_title(self):
        with patch("screen_awareness.current_desktop_state", return_value={
            "state": "web",
            "foreground_title": "Example Page",
            "process_name": "chrome.exe",
            "app_name": "Chrome",
        }):
            state = screen_awareness_desktop_state({"screen_awareness_include_window_title": True})

        self.assertEqual("Example Page", state["foreground_title"])
        self.assertNotIn("process_path", state)

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
            patch("screen_awareness.current_desktop_state", return_value={}),
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

    def test_legacy_desktop_state_setting_migrates_to_screenshot_awareness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({
                "desktop_state_awareness_enabled": True,
                "desktop_state_include_window_title": True,
                "desktop_state_idle_seconds": 90,
                "screen_awareness_enabled": False,
            }), encoding="utf-8")
            config = ConfigManager(path)
            config.save()
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(config.get("screen_awareness_enabled"))
        self.assertNotIn("desktop_state_awareness_enabled", saved)
        self.assertNotIn("desktop_state_include_window_title", saved)
        self.assertNotIn("desktop_state_idle_seconds", saved)

    def test_legacy_desktop_state_proactive_item_is_removed(self):
        normalized = normalize_proactive_companion({
            "enabled": True,
            "items": [{
                "id": "desktop_state",
                "kind": "desktop_state",
                "enabled": True,
                "schedule_type": "interval",
                "interval_minutes": 45,
            }],
        })

        self.assertNotIn("desktop_state", {item["id"] for item in normalized["items"]})


if __name__ == "__main__":
    unittest.main()
