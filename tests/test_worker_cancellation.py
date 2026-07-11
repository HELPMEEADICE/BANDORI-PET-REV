import unittest
from unittest.mock import patch
from types import SimpleNamespace

from llm_manager import LLMStreamWorker, NonStreamWorker, ResponsesStreamWorker
from asr_manager import ASRRequestWorker
from tts_manager import TTSRequestWorker, TTSTranslationWorker
from pet_window import PetWindow
from network_worker import CancelableNetworkWorker


class _ClosableResponse:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class WorkerCancellationTests(unittest.TestCase):
    def test_stream_workers_close_the_active_response_when_cancelled(self):
        for worker in (
            LLMStreamWorker("https://example.com/v1", "key", "model", []),
            ResponsesStreamWorker("https://example.com/v1/responses", "key", "model", []),
        ):
            response = _ClosableResponse()
            self.assertTrue(worker._track_response(response))

            worker.cancel()

            self.assertTrue(response.closed)
            self.assertTrue(worker._cancel_event.is_set())

    def test_shared_network_worker_closes_active_response(self):
        worker = CancelableNetworkWorker()
        response = _ClosableResponse()
        self.assertTrue(worker._track_response(response))

        worker.requestInterruption()

        self.assertTrue(response.closed)
        self.assertTrue(worker.cancelled())

    def test_non_stream_worker_close_and_suppresses_result_after_cancel(self):
        worker = NonStreamWorker("https://example.com/v1", "key", "model", [])
        response = _ClosableResponse()
        self.assertTrue(worker._track_response(response))

        worker.cancel()

        self.assertTrue(response.closed)
        self.assertTrue(worker._cancel_event.is_set())

    def test_cancelled_worker_does_not_open_a_new_response(self):
        worker = NonStreamWorker("https://example.com/v1", "key", "model", [])
        worker.cancel()

        with patch("llm_manager.urllib.request.urlopen") as urlopen:
            self.assertIsNone(worker._open_response(object(), 120))

        urlopen.assert_not_called()

    def test_speech_workers_close_the_active_response_when_cancelled(self):
        workers = (
            ASRRequestWorker(b"audio", "audio/wav", {}),
            TTSRequestWorker(0, 1, "text", "character", {}),
            TTSTranslationWorker(0, 1, "text", "character", {}),
        )
        for worker in workers:
            response = _ClosableResponse()
            self.assertTrue(worker._track_response(response))

            worker.cancel()

            self.assertTrue(response.closed)

    def test_cancel_stops_remaining_tool_calls_in_same_round(self):
        worker = LLMStreamWorker(
            "https://example.com/v1",
            "key",
            "model",
            [],
            tool_config={"llm_mcp_enabled": True},
        )
        calls = []

        def fake_stream_once(_messages, _use_tools):
            worker._stream_tool_calls = [
                {"id": "one", "function": {"name": "first", "arguments": "{}"}},
                {"id": "two", "function": {"name": "second", "arguments": "{}"}},
            ]

        def fake_tool_call(name, _arguments, _config):
            calls.append(name)
            worker.cancel()
            return {"content": "done", "extra_messages": []}

        worker._stream_once = fake_stream_once
        with patch("llm_manager.run_local_tool_call", side_effect=fake_tool_call):
            worker.run()

        self.assertEqual(calls, ["first"])

    def test_compact_window_is_not_deleted_before_close_is_accepted(self):
        class _Window:
            def __init__(self):
                self.close_calls = 0

            def close(self):
                self.close_calls += 1
                return False

            def deleteLater(self):
                raise AssertionError("window was deleted while close was deferred")

        window = _Window()
        harness = SimpleNamespace(_compact_ai_window=window)

        PetWindow._close_compact_ai_window(harness)

        self.assertIs(harness._compact_ai_window, window)
        self.assertEqual(window.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
