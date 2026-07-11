import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QUrlQuery

from napcat_adapter import NapcatClient


class NapcatDeliverySemanticsTest(unittest.TestCase):
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
