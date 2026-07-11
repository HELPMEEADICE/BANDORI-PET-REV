import unittest
from unittest.mock import Mock, patch

import local_tools


class _Config:
    def __init__(self, save_result):
        self._data = {}
        self.save_result = save_result

    def load(self):
        return None

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        return self.save_result


class LocalReminderToolSaveSemanticsTest(unittest.TestCase):
    def test_create_alarm_save_failure_does_not_publish_or_report_success(self):
        cfg = _Config(False)
        publish = Mock()
        with (
            patch("config_manager.ConfigManager", return_value=cfg),
            patch("settings_bus.publish_settings", publish),
            patch("local_tools._resolve_reminder_character", return_value="kasumi"),
        ):
            result = local_tools._run_reminder_tool_call(
                local_tools.CREATE_ALARM_TOOL_NAME,
                {"time": "12:30", "description": "lunch"},
            )

        publish.assert_not_called()
        self.assertIn("失败", result["content"])

    def test_start_pomodoro_save_failure_does_not_publish_or_report_success(self):
        cfg = _Config(False)
        publish = Mock()
        with (
            patch("config_manager.ConfigManager", return_value=cfg),
            patch("settings_bus.publish_settings", publish),
            patch("local_tools._resolve_reminder_character", return_value="kasumi"),
        ):
            result = local_tools._run_reminder_tool_call(
                local_tools.START_POMODORO_TOOL_NAME,
                {"repeat_count": 2, "description": "work"},
            )

        publish.assert_not_called()
        self.assertIn("失败", result["content"])

    def test_create_alarm_publish_failure_reports_restart_fallback(self):
        cfg = _Config(True)
        with (
            patch("config_manager.ConfigManager", return_value=cfg),
            patch("settings_bus.publish_settings", return_value=False),
            patch("local_tools._resolve_reminder_character", return_value="kasumi"),
        ):
            result = local_tools._run_reminder_tool_call(
                local_tools.CREATE_ALARM_TOOL_NAME,
                {"time": "12:30", "description": "lunch"},
            )

        self.assertIn("重启", result["content"])


if __name__ == "__main__":
    unittest.main()
