import unittest
from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication
from qfluentwidgets import DatePicker

from settings_window.pages.chat_history import ChatHistoryPageMixin


class _FakeSignal:
    def __init__(self):
        self.callbacks = []
        self.disconnect_count = 0

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self):
        self.disconnect_count += 1
        self.callbacks.clear()


class _FakeWorker:
    instances = []

    def __init__(self, db_factory, query_params, parent=None):
        self.db_factory = db_factory
        self.query_params = query_params
        self.parent = parent
        self.finished = _FakeSignal()
        self.error = _FakeSignal()
        self.completed = _FakeSignal()
        self.started = False
        self.interrupted = False
        self.__class__.instances.append(self)

    def isRunning(self):
        return self.started

    def wait(self, _timeout):
        return True

    def requestInterruption(self):
        self.interrupted = True

    def start(self):
        self.started = True


class _Harness(ChatHistoryPageMixin):
    def __init__(self):
        self._history_list_view = object()
        self._history_worker = None
        self._history_filter_worker = None
        self._history_retired_workers = []

    def _on_history_query_error(self, _message):
        pass


class ChatHistoryFilterWorkerTest(unittest.TestCase):
    def setUp(self):
        _FakeWorker.instances.clear()

    @patch("settings_window.pages.chat_history._ChatHistoryWorker", _FakeWorker)
    def test_search_does_not_cancel_filter_option_loading(self):
        harness = _Harness()

        def filter_result(_result):
            pass

        def search_result(_result):
            pass

        harness._start_history_filter_worker(
            {"action": "filters"},
            on_result=filter_result,
        )
        filter_worker = harness._history_filter_worker

        harness._start_history_worker(
            {"action": "search"},
            on_result=search_result,
        )

        self.assertIsNot(filter_worker, harness._history_worker)
        self.assertEqual([filter_result], filter_worker.finished.callbacks)
        self.assertEqual(0, filter_worker.finished.disconnect_count)
        self.assertTrue(filter_worker.started)
        self.assertTrue(harness._history_worker.started)


class ChatHistoryDatePickerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_history_date_filter_uses_fluent_date_picker(self):
        edit = ChatHistoryPageMixin._make_history_date_edit(None)
        self.addCleanup(edit.deleteLater)

        self.assertIsInstance(edit, DatePicker)
        edit.setDate(QDate(2026, 6, 12))
        self.assertEqual(QDate(2026, 6, 12), edit.date)

    def test_history_date_filter_is_compact_enough_for_grid_cell(self):
        edit = ChatHistoryPageMixin._make_history_date_edit(None)
        self.addCleanup(edit.deleteLater)
        edit.show()
        self._app.processEvents()

        column_width = sum(
            child.minimumWidth()
            for child in edit.children()
            if hasattr(child, "minimumWidth")
        )
        self.assertLessEqual(column_width, 180)


if __name__ == "__main__":
    unittest.main()
