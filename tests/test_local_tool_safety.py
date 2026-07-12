import socket
import threading
import unittest
from unittest.mock import patch

import computer_tools
import local_tools


class LocalToolSafetyTests(unittest.TestCase):
    @staticmethod
    def _address(ip: str):
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (ip, 443, 0, 0) if family == socket.AF_INET6 else (ip, 443))]

    def test_web_fetch_rejects_private_resolved_addresses(self):
        with patch("local_tools.socket.getaddrinfo", return_value=self._address("192.168.1.5")):
            self.assertEqual("", local_tools._normalize_fetch_url("http://example.test/private"))

    def test_web_fetch_accepts_public_resolved_addresses(self):
        with patch("local_tools.socket.getaddrinfo", return_value=self._address("93.184.216.34")):
            self.assertEqual(
                "https://example.com/page",
                local_tools._normalize_fetch_url("https://example.com/page"),
            )

    def test_web_fetch_rejects_invalid_port_without_raising(self):
        self.assertEqual("", local_tools._normalize_fetch_url("http://example.com:bad/path"))

    def test_web_search_prefetch_is_disabled_in_favor_of_explicit_tool_calls(self):
        self.assertFalse(local_tools.should_prefetch_web_search("search latest news"))
        self.assertFalse(local_tools.should_prefetch_web_search("今天天气"))

    def test_invalid_json_never_reaches_side_effecting_tool_handlers(self):
        invalid = '{"value":'
        with (
            patch("local_tools._run_reminder_tool_call") as reminder,
            patch("local_tools.call_mcp_tool") as mcp,
            patch("local_tools.run_computer_tool") as computer,
            patch("local_tools.web_search") as web_search,
        ):
            results = [
                local_tools.run_local_tool_call(local_tools.CREATE_ALARM_TOOL_NAME, invalid),
                local_tools.run_local_tool_call("mcp__server__tool", invalid),
                local_tools.run_local_tool_call("computer_click", invalid),
                local_tools.run_local_tool_call(local_tools.WEB_SEARCH_TOOL_NAME, invalid),
            ]

        reminder.assert_not_called()
        mcp.assert_not_called()
        computer.assert_not_called()
        web_search.assert_not_called()
        for result in results:
            self.assertIn("was not executed", result["content"])
            self.assertIn("invalid JSON", result["content"])

    def test_non_object_tool_arguments_are_rejected(self):
        for arguments in ('["value"]', '42', ['value'], None):
            with self.subTest(arguments=arguments):
                result = local_tools.run_local_tool_call(
                    local_tools.POKE_USER_TOOL_NAME,
                    arguments,
                )
                self.assertIn("must be a JSON object", result["content"])

    def test_valid_json_object_is_dispatched_as_parsed_arguments(self):
        with patch("local_tools.web_search", return_value="result") as web_search:
            result = local_tools.run_local_tool_call(
                local_tools.WEB_SEARCH_TOOL_NAME,
                '{"query":"Bandori","max_results":2}',
            )

        web_search.assert_called_once_with("Bandori", max_results=2, engine="bing_cn")
        self.assertEqual("result", result["content"])

    def test_computer_wait_is_cancelled_without_sleeping_full_duration(self):
        cancelled = threading.Event()
        cancelled.set()

        result = computer_tools.run_computer_tool(
            "computer_wait",
            {"seconds": 10},
            {
                "computer_use_enabled": True,
                "computer_use_allow_wait": True,
                "_cancel_event": cancelled,
            },
        )

        self.assertIn("cancel", result["content"].lower())

    def test_computer_type_limits_text_length(self):
        fake = unittest.mock.Mock()
        with patch("computer_tools._pyautogui", return_value=fake):
            result = computer_tools.run_computer_tool(
                "computer_type",
                {"text": "x" * 100_000},
                {
                    "computer_use_enabled": True,
                    "computer_use_allow_keyboard": True,
                    "computer_use_send_screenshots": False,
                },
            )

        typed = "".join(call.args[0] for call in fake.write.call_args_list)
        self.assertLessEqual(len(typed), computer_tools._MAX_TYPE_CHARS)
        self.assertIn("truncated", result["content"].lower())


if __name__ == "__main__":
    unittest.main()
