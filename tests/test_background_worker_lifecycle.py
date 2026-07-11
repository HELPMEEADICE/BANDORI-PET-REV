import unittest
from pathlib import Path

from chat_window.chat_window import AttachmentImportWorker
from chat_window.widgets import AuxVisionFallbackWorker
from network_worker import CancelableNetworkWorker
from outfit_description import OutfitDescriptionWorker
from screen_awareness import ScreenAwarenessVisionWorker
from settings_window.pages.chat_history import _ChatHistoryWorker
from settings_window.workers import (
    FetchModelsWorker,
    McpConnectionTestWorker,
    TestConnectionWorker as LlmTestConnectionWorker,
)


class _FakeHistoryDb:
    def __init__(self):
        self.closed = False

    def search_chat_history(self, **_params):
        return {"records": [], "total": 0, "has_more": False}

    def close(self):
        self.closed = True


class BackgroundWorkerLifecycleTests(unittest.TestCase):
    def test_network_workers_share_cooperative_cancellation(self):
        worker_types = (
            AttachmentImportWorker,
            AuxVisionFallbackWorker,
            OutfitDescriptionWorker,
            ScreenAwarenessVisionWorker,
            FetchModelsWorker,
            McpConnectionTestWorker,
            LlmTestConnectionWorker,
        )
        for worker_type in worker_types:
            self.assertTrue(issubclass(worker_type, CancelableNetworkWorker))

    def test_chat_history_worker_always_closes_its_database(self):
        db = _FakeHistoryDb()
        worker = _ChatHistoryWorker(
            db_factory=lambda: db,
            query_params={"action": "search"},
        )
        results = []
        worker.finished.connect(results.append)

        worker.run()

        self.assertTrue(db.closed)
        self.assertEqual(results, [{"records": [], "total": 0, "has_more": False}])

    def test_settings_callbacks_reject_retired_workers(self):
        llm_source = Path("settings_window/pages/llm.py").read_text(encoding="utf-8")
        mcp_source = Path("settings_window/pages/mcp.py").read_text(encoding="utf-8")

        self.assertIn('worker is not getattr(self, "_test_worker", None)', llm_source)
        self.assertIn('worker is not getattr(self, "_fetch_worker", None)', llm_source)
        self.assertIn('self.sender() is not getattr(self, "_mcp_test_worker", None)', mcp_source)


if __name__ == "__main__":
    unittest.main()
