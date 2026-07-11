import unittest

from reply_stream import ReplyStreamBinding, is_active_reply_stream


class GroupReplyStreamBindingTests(unittest.TestCase):
    @staticmethod
    def _stream(generation, character):
        stream = ReplyStreamBinding(generation, character, object())
        stream.worker = object()
        return stream

    def test_late_chunk_cannot_write_into_the_next_characters_bubble(self):
        first = self._stream(1, "character-a")
        second = self._stream(2, "character-b")

        self.assertTrue(is_active_reply_stream(first, first, first.worker, first.bubble))
        self.assertFalse(is_active_reply_stream(first, second, second.worker, second.bubble))

    def test_old_flush_timer_cannot_append_into_the_next_characters_bubble(self):
        first = self._stream(1, "character-a")
        second = self._stream(2, "character-b")

        self.assertFalse(is_active_reply_stream(first, second, second.worker, second.bubble))
        self.assertTrue(is_active_reply_stream(second, second, second.worker, second.bubble))


if __name__ == "__main__":
    unittest.main()
