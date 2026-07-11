import threading
import unittest
from unittest.mock import patch

import mcp_bridge


class McpCancellationTests(unittest.TestCase):
    def tearDown(self):
        mcp_bridge.close_mcp_clients()

    def test_stdio_request_stops_when_cancelled(self):
        client = object.__new__(mcp_bridge.StdioMcpClient)
        client._server = {"timeout_seconds": 30}
        client._lock = threading.RLock()
        client._next_id = 1
        client._reader_error = None
        client._responses = __import__("queue").Queue()
        client._process = type("Process", (), {"poll": lambda self: None})()
        client._write = lambda _message: None
        cancelled = threading.Event()
        cancelled.set()

        with self.assertRaises(InterruptedError):
            client._request("tools/call", {}, cancelled)

    def test_http_transport_failure_is_not_retried_as_initialization(self):
        with patch("mcp_bridge._request_http_json", side_effect=OSError("offline")) as request:
            with self.assertRaises(OSError):
                mcp_bridge._http_request_with_init({"url": "http://localhost"}, "tools/list", {})

        self.assertEqual(request.call_count, 1)

    def test_http_initialization_retry_requires_explicit_server_error(self):
        responses = [
            {"error": {"code": -32002, "message": "Server not initialized"}},
            {"result": {}},
            {"result": {"tools": []}},
        ]
        with patch("mcp_bridge._request_http_json", side_effect=responses) as request:
            response = mcp_bridge._http_request_with_init(
                {"url": "http://localhost"},
                "tools/list",
                {},
            )

        self.assertEqual(response, {"result": {"tools": []}})
        self.assertEqual(request.call_count, 3)

    def test_tool_discovery_stops_on_cancellation(self):
        cancelled = threading.Event()
        cancelled.set()
        config = {"llm_mcp_enabled": True, "_cancel_event": cancelled}
        server = {"enabled": True, "transport": "http", "label": "test"}

        with (
            patch("mcp_bridge._enabled_servers", return_value=[server]),
            patch("mcp_bridge._list_server_tools", side_effect=InterruptedError),
        ):
            self.assertEqual(mcp_bridge.mcp_proxy_tools(config), [])


if __name__ == "__main__":
    unittest.main()
