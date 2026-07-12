import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from settings_window.pages.reminder import ReminderPageMixin


class ReminderSettingsSaveFeedbackTest(unittest.TestCase):
    def test_add_alarm_does_not_report_success_when_save_fails(self):
        config = SimpleNamespace(get=Mock(return_value=[]), set=Mock())
        harness = SimpleNamespace(
            _cfg=config,
            _alarm_repeat_days_from_form=Mock(return_value=[]),
            _alarm_repeat_combo=SimpleNamespace(
                currentIndex=Mock(return_value=0),
                itemData=Mock(return_value="none"),
            ),
            _alarm_time_edit=SimpleNamespace(
                time=Mock(return_value=SimpleNamespace(toString=Mock(return_value="12:30")))
            ),
            _alarm_description=SimpleNamespace(text=Mock(return_value="lunch"), clear=Mock()),
            _alarm_character_combo=Mock(),
            _selected_reminder_character=Mock(return_value="kasumi"),
            _save_reminder_config=Mock(return_value=False),
            _refresh_reminder_lists=Mock(),
        )

        with (
            patch("settings_window.pages.reminder.create_alarm", return_value={"id": "alarm-1"}),
            patch("settings_window.pages.reminder.InfoBar.success") as success,
        ):
            result = ReminderPageMixin._add_alarm_from_form(harness)

        self.assertFalse(result)
        harness._alarm_description.clear.assert_not_called()
        success.assert_not_called()


if __name__ == "__main__":
    unittest.main()
