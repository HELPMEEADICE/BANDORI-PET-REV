import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from chat_window.chat_window import ChatWindow
from chat_window.reply_stream import ReplyStreamBinding


class _TimerStub:
    def __init__(self):
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0

    def isActive(self):
        return self.active

    def start(self):
        self.active = True
        self.start_calls += 1

    def stop(self):
        self.active = False
        self.stop_calls += 1


class _BubbleStub:
    def __init__(self):
        self.text = ""
        self.reasoning = ""
        self.streaming = False

    def set_text(self, text):
        self.text = text

    def set_reasoning(self, reasoning):
        self.reasoning = reasoning

    def set_streaming(self, streaming):
        self.streaming = streaming


class _InputStub:
    def __init__(self):
        self.focused = False

    def setFocus(self):
        self.focused = True


class _ReplyStreamHarness:
    _is_active_reply_stream = ChatWindow._is_active_reply_stream
    _clear_active_reply_stream = ChatWindow._clear_active_reply_stream
    _on_chunk_received = ChatWindow._on_chunk_received
    _flush_stream_text = ChatWindow._flush_stream_text
    _start_next_group_response = ChatWindow._start_next_group_response
    _on_response_error = ChatWindow._on_response_error
    _flush_tts_text = ChatWindow._flush_tts_text

    def __init__(self):
        self._worker = None
        self._current_bubble = None
        self._active_reply_stream = None
        self._stream_buffer_owner = None
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._action_tag_stream_buffer = ""
        self._current_response_actions = []
        self._current_tts_rate = 1.0
        self._stream_flush_timer = _TimerStub()
        self._group_queue = []
        self._group_spoken = []
        self._auto_active = False
        self._auto_round = 0
        self._input = _InputStub()
        self.tts_chunks = []
        self.queued_tts = []
        self.scroll_calls = 0
        self.busy_values = []
        self.raw_image_clear_calls = 0
        self.tts_reset_calls = []
        self.sync_input_calls = 0

        self._tts_request_allowed = True
        self._tts_tag_buffer = ""
        self._tts_text_buffer = ""
        self._tts_next_sequence = 0
        self._tts_bubbles = {}
        self._tts_characters = {}

    def activate(self, stream):
        self._worker = stream.worker
        self._current_bubble = stream.bubble
        self._active_reply_stream = stream
        self._stream_buffer_owner = stream

    def _extract_stream_search_sources(self, text):
        return text

    def _clean_tts_stream_text(self, text):
        return text

    def _enqueue_tts_text(self, text, character):
        self.tts_chunks.append((text, character))

    def _scroll_to_bottom_for_stream(self):
        self.scroll_calls += 1

    def _reset_tts_stream(self, stop_player=True):
        self.tts_reset_calls.append(stop_player)

    def _clear_raw_image_inline_state(self):
        self.raw_image_clear_calls += 1

    def _set_busy(self, busy, planning=False):
        self.busy_values.append((busy, planning))

    def _sync_input_height(self):
        self.sync_input_calls += 1

    def _tts_enabled(self):
        return True

    def _clean_tts_payload(self, text):
        return text.strip()

    def _queue_tts_request(self, sequence, text, character):
        self.queued_tts.append((sequence, text, character))

    def _start_next_tts_request(self):
        pass


def _stream(generation, character):
    return ReplyStreamBinding(generation, character, object(), _BubbleStub())


class GroupReplyStreamBindingTests(unittest.TestCase):
    def test_late_chunk_cannot_mutate_the_next_characters_state(self):
        harness = _ReplyStreamHarness()
        first = _stream(1, "character-a")
        second = _stream(2, "character-b")
        harness.activate(second)

        harness._on_chunk_received(first, "late", "old reasoning")

        self.assertEqual("", harness._stream_buffer)
        self.assertEqual("", harness._reasoning_stream_text)
        self.assertEqual([], harness.tts_chunks)
        self.assertFalse(first.bubble.streaming)

        harness._on_chunk_received(second, "hello", "new reasoning")

        self.assertEqual("hello", harness._stream_buffer)
        self.assertEqual("new reasoning", harness._reasoning_stream_text)
        self.assertEqual([("hello", "character-b")], harness.tts_chunks)
        self.assertTrue(second.bubble.streaming)

    def test_stale_flush_owner_discards_old_buffer_instead_of_touching_new_bubble(self):
        harness = _ReplyStreamHarness()
        first = _stream(1, "character-a")
        second = _stream(2, "character-b")
        harness.activate(second)
        harness._stream_buffer_owner = first
        harness._stream_buffer = "late text"
        harness._stream_flush_timer.active = True

        harness._flush_stream_text()

        self.assertEqual("", harness._stream_buffer)
        self.assertIsNone(harness._stream_buffer_owner)
        self.assertEqual("", second.bubble.text)
        self.assertFalse(harness._stream_flush_timer.active)

    def test_active_flush_only_updates_its_bound_bubble(self):
        harness = _ReplyStreamHarness()
        stream = _stream(1, "character-a")
        harness.activate(stream)
        harness._stream_buffer = "abcdef"

        harness._flush_stream_text()

        self.assertEqual("abcd", stream.bubble.text)
        self.assertEqual("ef", harness._stream_buffer)

    def test_detach_releases_worker_and_bubble_references(self):
        harness = _ReplyStreamHarness()
        stream = _stream(1, "character-a")
        harness.activate(stream)

        self.assertTrue(harness._clear_active_reply_stream(stream))

        self.assertIsNone(harness._active_reply_stream)
        self.assertIsNone(harness._stream_buffer_owner)
        self.assertIsNone(stream.worker)
        self.assertIsNone(stream.bubble)

    def test_auto_continue_retargets_the_same_worker_to_the_new_bubble(self):
        stream = _stream(1, "character-a")
        worker = stream.worker
        next_bubble = _BubbleStub()

        stream.retarget(next_bubble)

        self.assertTrue(stream.owns(stream, worker, next_bubble))
        self.assertIs(next_bubble, stream.bubble)

    def test_stale_group_timer_cannot_replace_an_active_reply(self):
        harness = _ReplyStreamHarness()
        stream = _stream(1, "character-a")
        harness.activate(stream)
        harness._group_queue = ["character-b"]

        harness._start_next_group_response()

        self.assertIs(stream, harness._active_reply_stream)
        self.assertIs(stream.worker, harness._worker)
        self.assertIs(stream.bubble, harness._current_bubble)
        self.assertEqual(["character-b"], harness._group_queue)

    def test_tts_flush_uses_explicit_segment_bubble(self):
        harness = _ReplyStreamHarness()
        current_bubble = _BubbleStub()
        segment_bubble = _BubbleStub()
        harness._current_bubble = current_bubble
        harness._tts_text_buffer = "segment speech"

        harness._flush_tts_text("character-a", segment_bubble)

        self.assertIs(segment_bubble, harness._tts_bubbles[0])
        self.assertEqual("character-a", harness._tts_characters[0])
        self.assertEqual([(0, "segment speech", "character-a")], harness.queued_tts)

    def test_stream_error_aborts_remaining_group_queue_and_detaches(self):
        harness = _ReplyStreamHarness()
        stream = _stream(1, "character-a")
        bubble = stream.bubble
        harness.activate(stream)
        harness._group_queue = ["character-b", "character-c"]
        harness._group_spoken = ["Character A"]

        harness._on_response_error(stream, "network failed")

        self.assertIn("network failed", bubble.text)
        self.assertEqual([], harness._group_queue)
        self.assertEqual([], harness._group_spoken)
        self.assertIsNone(harness._active_reply_stream)
        self.assertIsNone(harness._worker)
        self.assertIsNone(harness._current_bubble)
        self.assertTrue(harness._input.focused)


if __name__ == "__main__":
    unittest.main()
