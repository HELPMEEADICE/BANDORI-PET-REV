from datetime import datetime
import unittest

from alarm_manager import ReminderScheduler


class ReminderSchedulerTest(unittest.TestCase):
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
