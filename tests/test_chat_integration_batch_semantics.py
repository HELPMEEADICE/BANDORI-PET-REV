import unittest
from unittest.mock import Mock

from chat_integration_server import _prepare_chat_event_batch


class ChatIntegrationBatchSemanticsTest(unittest.TestCase):
    def test_invalid_later_item_rejects_batch_before_normalization(self):
        normalize = Mock(side_effect=lambda event: event)

        with self.assertRaisesRegex(ValueError, "index 1"):
            _prepare_chat_event_batch([{"text": "first"}, "invalid"], normalize)

        normalize.assert_not_called()

    def test_batch_is_fully_normalized_before_processing(self):
        normalize = Mock(side_effect=lambda event: event if event.get("text") else None)

        prepared = _prepare_chat_event_batch(
            [{"text": "first"}, {"post_type": "notice"}],
            normalize,
        )

        self.assertEqual([{"text": "first"}, None], prepared)
        self.assertEqual(2, normalize.call_count)


if __name__ == "__main__":
    unittest.main()
