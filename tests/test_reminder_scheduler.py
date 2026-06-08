from datetime import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
