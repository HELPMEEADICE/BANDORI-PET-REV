import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from settings_window.pages.mcp import MCPPageMixin


class _TextEditStub:
    def __init__(self, text):
        self._text = text

    def toPlainText(self):
        return self._text


class _McpHarness(MCPPageMixin, QWidget):
    def __init__(self, text):
        super().__init__()
        self._llm_mcp_servers_text = _TextEditStub(text)

    def _mcp_computer_widgets_ready(self):
        return True


class McpJsonErrorMessageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_invalid_json_error_mentions_position_and_empty_array_escape(self):
        harness = _McpHarness("{\n")

        with patch("settings_window.pages.mcp.InfoBar.error") as error_bar:
            self.assertIsNone(harness._parse_mcp_servers_text())

        self.assertTrue(error_bar.called)
        message = error_bar.call_args.args[1]
        self.assertIn("line", message.lower())
        self.assertIn("column", message.lower())
        self.assertIn("[]", message)


if __name__ == "__main__":
    unittest.main()
