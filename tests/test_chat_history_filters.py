import unittest
from unittest.mock import patch

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
        self.started = False
        self.__class__.instances.append(self)

    def isRunning(self):
        return self.started

    def wait(self, _timeout):
        return True

    def start(self):
        self.started = True


class _Harness(ChatHistoryPageMixin):
    def __init__(self):
        self._history_list_view = object()
        self._history_worker = None
        self._history_filter_worker = None

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


if __name__ == "__main__":
    unittest.main()
