from datetime import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from alarm_manager import ReminderScheduler


class ReminderSchedulerTest(unittest.TestCase):
    def test_screen_awareness_uses_its_own_display_mode(self):
        scheduler = SimpleNamespace(
            _cfg=SimpleNamespace(get=lambda key, default=None: {
                "reminder_display_mode": "system",
                "screen_awareness_display_mode": "floating",
            }.get(key, default)),
            _display_name=Mock(return_value="角色"),
            _system_notify=Mock(),
            _broadcast_event=Mock(),
            _speak_tts_text=Mock(),
        )

        ReminderScheduler._show_reminder(
            scheduler,
            {"kind": "screen_awareness", "title": "屏幕感知", "character": "角色"},
            "测试提醒",
            "surprised",
        )

        scheduler._system_notify.assert_not_called()
        scheduler._broadcast_event.assert_called_once()
        self.assertEqual("screen_awareness", scheduler._broadcast_event.call_args.args[0]["source"])

    def test_regular_reminder_does_not_use_screen_awareness_display_mode(self):
        scheduler = SimpleNamespace(
            _cfg=SimpleNamespace(get=lambda key, default=None: {
                "reminder_display_mode": "system",
                "screen_awareness_display_mode": "floating",
            }.get(key, default)),
            _display_name=Mock(return_value="角色"),
            _system_notify=Mock(),
            _broadcast_event=Mock(),
            _speak_tts_text=Mock(),
        )

        ReminderScheduler._show_reminder(
            scheduler,
            {"kind": "alarm", "title": "闹钟", "character": "角色"},
            "测试提醒",
            "surprised",
        )

        scheduler._system_notify.assert_called_once_with("闹钟", "角色", "测试提醒")
        scheduler._broadcast_event.assert_not_called()

    def test_defer_overdue_proactive_items_on_startup(self):
        now = datetime(2026, 6, 8, 20, 0, 0)
        proactive = {
            "enabled": True,
            "items": [
                {
                    "id": "water",
                    "enabled": True,
                    "schedule_type": "interval",
                    "interval_minutes": 90,
                    "active_start": "09:00",
                    "active_end": "22:00",
                    "next_at": "2026-06-08T19:30:00",
                },
                {
                    "id": "evening_review",
                    "enabled": True,
                    "schedule_type": "daily",
                    "time": "21:30",
                    "next_at": "2026-06-08T21:30:00",
                },
            ],
        }

        ReminderScheduler._defer_overdue_proactive_items(None, proactive, now)

        self.assertEqual("2026-06-08T21:30:00", proactive["items"][0]["next_at"])
        self.assertEqual("2026-06-08T21:30:00", proactive["items"][1]["next_at"])

    def test_proactive_policy_skip_does_not_generate_text(self):
        scheduler = SimpleNamespace(
            _cfg=SimpleNamespace(),
            _reminder_character=Mock(return_value="kasumi"),
            _start_text_generation=Mock(),
            _current_desktop_state=Mock(return_value={"state": "gaming"}),
            _care_policy_decision=Mock(return_value={
                "allow": False,
                "reason": "gaming_silent",
                "next_delay_minutes": 60,
            }),
            _record_care_policy_skip=Mock(),
        )

        result = ReminderScheduler._trigger_proactive_item(
            scheduler,
            {"id": "water", "kind": "water", "title": "water", "description": "", "schedule_type": "interval"},
            {"character": "kasumi"},
            datetime(2026, 6, 9, 12, 0, 0),
        )

        self.assertFalse(result["triggered"])
        scheduler._start_text_generation.assert_not_called()
        scheduler._record_care_policy_skip.assert_called_once()

    def test_screen_awareness_test_bypasses_care_policy(self):
        scheduler = SimpleNamespace(
            _cfg=SimpleNamespace(
                get=lambda key, default=None: {
                    "screen_awareness_enabled": True,
                }.get(key, default)
            ),
            _screen_awareness_worker=None,
            _screen_awareness_enabled=Mock(return_value=True),
            _schedule_next_screen_awareness=Mock(),
            _start_screen_awareness_capture=Mock(),
        )

        with patch("alarm_manager.local_now", return_value=datetime(2026, 6, 9, 12, 0, 0)):
            self.assertTrue(ReminderScheduler.trigger_screen_awareness_now(scheduler))

        scheduler._start_screen_awareness_capture.assert_called_once()
        self.assertTrue(scheduler._start_screen_awareness_capture.call_args.kwargs["bypass_policy"])


if __name__ == "__main__":
    unittest.main()
