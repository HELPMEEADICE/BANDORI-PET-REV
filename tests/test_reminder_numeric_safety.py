from datetime import datetime
import unittest

from reminder_core import normalize_pomodoro, normalize_proactive_item


class ReminderNumericSafetyTest(unittest.TestCase):
    def test_interval_reminder_tolerates_infinite_minutes(self):
        item = normalize_proactive_item(
            {
                "id": "custom-interval",
                "schedule_type": "interval",
                "interval_minutes": float("inf"),
            },
            now=datetime(2026, 7, 16, 9, 0, 0),
        )

        self.assertEqual(60, item["interval_minutes"])

    def test_pomodoro_tolerates_infinite_counts_and_duration(self):
        item = normalize_pomodoro(
            {
                "id": "pomodoro-test",
                "repeat_count": float("inf"),
                "completed_focus_count": float("inf"),
                "phase_duration_sec": float("inf"),
            },
            now=datetime(2026, 7, 16, 9, 0, 0),
        )

        self.assertEqual(1, item["repeat_count"])
        self.assertEqual(0, item["completed_focus_count"])
        self.assertGreater(item["phase_duration_sec"], 0)


if __name__ == "__main__":
    unittest.main()
