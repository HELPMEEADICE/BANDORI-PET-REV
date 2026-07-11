import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from special_event_manager import SpecialEventManager


class SpecialEventManagerErrorTest(unittest.TestCase):
    def test_repeated_failure_logs_are_rate_limited(self):
        scheduler = SimpleNamespace(
            event_db=SimpleNamespace(get_today_events=Mock(side_effect=ValueError("bad event"))),
            last_checked_date=None,
            _last_error_log_at=None,
            check_timer=SimpleNamespace(start=Mock()),
            event_detected=SimpleNamespace(emit=Mock()),
            _schedule_next_check=Mock(),
        )

        with (
            patch("special_event_manager.QDate.currentDate", return_value="today"),
            patch("special_event_manager.time.monotonic", side_effect=[100.0, 120.0]),
            patch("special_event_manager._log.exception") as log_exception,
        ):
            SpecialEventManager._check_events(scheduler)
            SpecialEventManager._check_events(scheduler)

        log_exception.assert_called_once()
        self.assertEqual(2, scheduler.check_timer.start.call_count)
        scheduler.check_timer.start.assert_called_with(60_000)

    def test_success_resets_error_log_throttle(self):
        scheduler = SimpleNamespace(
            event_db=SimpleNamespace(get_today_events=Mock(return_value=[])),
            last_checked_date=None,
            _last_error_log_at=100.0,
            check_timer=SimpleNamespace(start=Mock()),
            event_detected=SimpleNamespace(emit=Mock()),
            _schedule_next_check=Mock(),
        )

        with patch("special_event_manager.QDate.currentDate", return_value="today"):
            SpecialEventManager._check_events(scheduler)

        self.assertIsNone(scheduler._last_error_log_at)
        self.assertEqual("today", scheduler.last_checked_date)
        scheduler._schedule_next_check.assert_called_once()


if __name__ == "__main__":
    unittest.main()
