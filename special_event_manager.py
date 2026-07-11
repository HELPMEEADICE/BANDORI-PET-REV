import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal, QTime, QDate
from event_db_manager import EventDbManager, SpecialEvent


_log = logging.getLogger(__name__)
_ERROR_LOG_INTERVAL_SECONDS = 10 * 60


class SpecialEventManager(QObject):
    event_detected = Signal(SpecialEvent)

    def __init__(self, data_dir: str = None, parent=None):
        super().__init__(parent)
        self.event_db = EventDbManager(data_dir)
        self.last_checked_date = None
        self._last_error_log_at = None
        self._setup_timer()

    def _setup_timer(self):
        self.check_timer = QTimer(self)
        self.check_timer.timeout.connect(self._check_events)
        self._schedule_next_check()

    def _schedule_next_check(self):
        now = QTime.currentTime()
        next_midnight = QTime(0, 0, 0)
        msecs_until_midnight = now.msecsTo(next_midnight)
        if msecs_until_midnight <= 0:
            msecs_until_midnight += 24 * 60 * 60 * 1000
        self.check_timer.start(msecs_until_midnight)

    def _check_events(self):
        today = QDate.currentDate()
        if self.last_checked_date == today:
            return

        try:
            events = self.event_db.get_today_events()
            for event in events:
                self.event_detected.emit(event)
        except Exception:
            now = time.monotonic()
            if (
                self._last_error_log_at is None
                or now - self._last_error_log_at >= _ERROR_LOG_INTERVAL_SECONDS
            ):
                self._last_error_log_at = now
                _log.exception("Special event check failed; retrying in 60 seconds")
            self.check_timer.start(60 * 1000)
            return

        self._last_error_log_at = None
        self.last_checked_date = today
        self._schedule_next_check()

    def start(self):
        self._check_events()

    def stop(self):
        self.check_timer.stop()
