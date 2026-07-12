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
