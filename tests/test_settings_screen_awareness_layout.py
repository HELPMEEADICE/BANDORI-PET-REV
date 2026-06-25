import inspect
import unittest

from settings_window.pages.mcp import MCPPageMixin
from settings_window.pages.reminder import ReminderPageMixin
from settings_window.pages.screen_awareness import ScreenAwarenessPageMixin


class ScreenAwarenessSettingsLayoutTest(unittest.TestCase):
    def test_care_policy_is_grouped_with_screen_awareness(self):
        mcp_source = inspect.getsource(MCPPageMixin._build_mcp_computer_page)
        screen_source = inspect.getsource(ScreenAwarenessPageMixin._build_screen_awareness_section)
        reminder_source = inspect.getsource(ReminderPageMixin._build_reminder_page)

        self.assertIn("self._build_screen_awareness_section(page)", mcp_source)
        self.assertIn("self._build_care_policy_panel(screen_panel)", screen_source)
        self.assertNotIn("self._build_care_policy_panel(page)", mcp_source)
        self.assertNotIn("_build_care_policy_panel", reminder_source)


if __name__ == "__main__":
    unittest.main()
