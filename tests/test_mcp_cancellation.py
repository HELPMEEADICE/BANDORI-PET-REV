import threading
import unittest
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import mcp_bridge
from mcp_base import extract_message_from_buffer


class McpCancellationTests(unittest.TestCase):
    def tearDown(self):
        mcp_bridge.close_mcp_clients()

    def test_server_timeout_is_normalized_for_malformed_and_extreme_values(self):
        self.assertEqual(
            30,
            mcp_bridge._server_timeout_seconds({"timeout_seconds": float("inf")}),
        )
        self.assertEqual(1, mcp_bridge._server_timeout_seconds({"timeout_seconds": -5}))
        self.assertEqual(3600, mcp_bridge._server_timeout_seconds({"timeout_seconds": 9999}))
        self.assertEqual(45, mcp_bridge._server_timeout_seconds({"timeout_seconds": "45"}))

    def test_stdio_request_stops_when_cancelled(self):
        client = object.__new__(mcp_bridge.StdioMcpClient)
        client._server = {"timeout_seconds": 30}
        client._lock = threading.RLock()
        client._next_id = 1
        client._reader_error = None
        client._responses = __import__("queue").Queue()
        client._process = type("Process", (), {"poll": lambda self: None})()
        client._write = lambda _message: None
        client._notify = unittest.mock.Mock()
        client.close = unittest.mock.Mock()
        cancelled = threading.Event()
        cancelled.set()

        with self.assertRaises(InterruptedError):
            client._request("tools/call", {}, cancelled)

        client._notify.assert_called_once_with(
            "notifications/cancelled",
            {"requestId": 1, "reason": "User requested cancellation"},
        )
        client.close.assert_called_once()

    def test_stdio_cancel_still_closes_when_notification_write_fails(self):
        client = object.__new__(mcp_bridge.StdioMcpClient)
        client._server = {"timeout_seconds": 30}
        client._lock = threading.RLock()
        client._next_id = 1
        client._reader_error = None
        client._responses = __import__("queue").Queue()
        client._process = type("Process", (), {"poll": lambda self: None})()
        client._write = lambda _message: None
        client._notify = unittest.mock.Mock(side_effect=BrokenPipeError("closed"))
        client.close = unittest.mock.Mock()
        cancelled = threading.Event()
        cancelled.set()

        with self.assertRaises(InterruptedError):
            client._request("tools/call", {}, cancelled)

        client.close.assert_called_once()

    def test_stdio_messages_use_standard_json_lines(self):
        client = object.__new__(mcp_bridge.StdioMcpClient)
        stdin = io.BytesIO()
        client._process = type("Process", (), {"stdin": stdin})()

        client._write({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        payload = stdin.getvalue()
        self.assertNotIn(b"Content-Length:", payload)
        self.assertTrue(payload.endswith(b"\n"))

    def test_content_length_header_name_is_case_insensitive(self):
        payload = b'{"jsonrpc":"2.0","id":7,"result":{}}'
        framed = (
            b"content-length: " + str(len(payload)).encode("ascii")
            + b"\r\n\r\n" + payload
        )

        server_message, server_remaining = extract_message_from_buffer(framed)
        client_message, client_remaining = mcp_bridge._extract_stdio_message(framed)

        self.assertEqual(payload.decode("utf-8"), server_message)
        self.assertEqual(b"", server_remaining)
        self.assertEqual({"jsonrpc": "2.0", "id": 7, "result": {}}, client_message)
        self.assertEqual(b"", client_remaining)

    def test_content_length_rejects_negative_size(self):
        framed = b"Content-Length: -1\r\n\r\n{}"

        with self.assertRaises(ValueError):
            extract_message_from_buffer(framed)
        with self.assertRaises(RuntimeError):
            mcp_bridge._extract_stdio_message(framed)

    def test_content_length_rejects_oversized_frame(self):
        framed = b"Content-Length: 67108865\r\n\r\n{}"

        with self.assertRaises(ValueError):
            extract_message_from_buffer(framed)
        with self.assertRaises(RuntimeError):
            mcp_bridge._extract_stdio_message(framed)

    def test_stdio_close_terminates_process_before_closing_stdout(self):
        events = []

        class Stream:
            def __init__(self, name):
                self.name = name

            def close(self):
                if self.name == "stdout":
                    self.assert_process_stopped()
                events.append(f"close:{self.name}")

            def assert_process_stopped(self):
                self_test.assertIn("terminate", events)

        class Process:
            stdin = Stream("stdin")
            stdout = Stream("stdout")

            def poll(self):
                return None if "terminate" not in events else 0

            def terminate(self):
                events.append("terminate")

            def wait(self, timeout):
                events.append(f"wait:{timeout}")
                return 0

        self_test = self
        client = object.__new__(mcp_bridge.StdioMcpClient)
        client._lock = threading.RLock()
        client._process = Process()
        client._reader = None

        client.close()

        self.assertLess(events.index("terminate"), events.index("close:stdout"))

    def test_stdio_validation_accepts_user_configured_python_server(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = Path(temp_dir) / "server.py"
            script.write_text("print('server')", encoding="utf-8")
            command, args, cwd = mcp_bridge._validated_stdio_command({
                "command": sys.executable,
                "args": [str(script)],
                "cwd": temp_dir,
            })

        self.assertEqual(Path(command).resolve(), Path(sys.executable).resolve())
        self.assertEqual(args, [str(script)])
        self.assertEqual(Path(cwd).resolve(), Path(temp_dir).resolve())

    def test_http_transport_failure_is_not_retried_as_initialization(self):
        with patch("mcp_bridge._request_http_json", side_effect=OSError("offline")) as request:
            with self.assertRaises(OSError):
                mcp_bridge._http_request_with_init({"url": "http://localhost"}, "tools/list", {})

        self.assertEqual(request.call_count, 1)

    def test_http_transport_initializes_before_first_tool_request(self):
        responses = [
            {"result": {"protocolVersion": "2025-06-18"}},
            {},
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
        self.assertEqual(request.call_args_list[0].args[1]["method"], "initialize")
        self.assertEqual(request.call_args_list[1].args[1]["method"], "notifications/initialized")
        self.assertEqual(request.call_args_list[2].args[1]["method"], "tools/list")

    def test_http_event_stream_selects_response_matching_request_id(self):
        raw = "\n\n".join((
            'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}',
            'event: message\ndata: {"jsonrpc":"2.0","id":7,"result":{"tools":[]}}',
        ))

        self.assertEqual(
            {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}},
            mcp_bridge._parse_http_response(raw, expected_id=7),
        )

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
