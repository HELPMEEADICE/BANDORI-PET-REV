from PySide6.QtCore import QObject, QTimer, Signal, QTime, QDate
from event_db_manager import EventDbManager, SpecialEvent


class SpecialEventManager(QObject):
    event_detected = Signal(SpecialEvent)

    def __init__(self, data_dir: str = None, parent=None):
        super().__init__(parent)
        self.event_db = EventDbManager(data_dir)
        self.last_checked_date = None
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

        self.last_checked_date = today
        events = self.event_db.get_today_events()

        for event in events:
            self.event_detected.emit(event)

        self._schedule_next_check()

    def start(self):
        self._check_events()

    def stop(self):
        self.check_timer.stop()

    def get_today_events(self):
        return self.event_db.get_today_events()

    def get_upcoming_events(self, days=7):
        return self.event_db.get_upcoming_events(days)
