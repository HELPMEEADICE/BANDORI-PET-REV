import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QUrlQuery

from napcat_adapter import NapcatClient
from onebot_message import onebot_event_mentions_self


class NapcatDeliverySemanticsTest(unittest.TestCase):
    def test_raw_cq_mention_does_not_match_account_id_prefix(self):
        event = {
            "self_id": 123,
            "raw_message": "[CQ:at,qq=1234] 这条消息不是发给机器人",
        }

        self.assertFalse(onebot_event_mentions_self(event))

    def test_raw_cq_mention_accepts_exact_id_with_extra_parameters(self):
        event = {
            "self_id": 123,
            "raw_message": "[CQ:at,qq=123,name=BandoriPet] 你好",
        }

        self.assertTrue(onebot_event_mentions_self(event))

    def test_raw_cq_mention_accepts_qq_after_other_parameters(self):
        event = {
            "self_id": 123,
            "raw_message": "[CQ:at,name=BandoriPet,qq=123] 你好",
        }

        self.assertTrue(onebot_event_mentions_self(event))

    def test_main_does_not_auto_reply_to_duplicate_saved_messages(self):
        from pathlib import Path

        source = Path("main.py").read_text(encoding="utf-8")
        handler = source.split("    def handle_napcat_message", 1)[1].split(
            "    def _napcat_generate_reply", 1
        )[0]

        self.assertIn('duplicate = bool(stored.get("duplicate"))', handler)
        self.assertIn("if not duplicate and _napcat_should_reply(event):", handler)

    def test_access_token_is_encoded_as_query_item(self):
        socket = Mock()
        client = SimpleNamespace(
            _stopping=False,
            _ws_url="ws://127.0.0.1:3001/onebot?client=bandori",
            _access_token="a&b#c=d",
            _socket=socket,
            _set_status=Mock(),
        )

        NapcatClient._connect_now(client)

        request = socket.open.call_args.args[0]
        query = QUrlQuery(request.url())
        self.assertEqual("bandori", query.queryItemValue("client"))
        self.assertEqual("a&b#c=d", query.queryItemValue("access_token"))

    def test_call_action_reports_socket_rejection(self):
        client = SimpleNamespace(_status="connected", _socket=Mock())
        client._socket.sendTextMessage.return_value = 0

        self.assertFalse(NapcatClient.call_action(client, "send_private_msg", {"user_id": 1}))


if __name__ == "__main__":
    unittest.main()
