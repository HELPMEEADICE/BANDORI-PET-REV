import os
import unittest
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
warnings.filterwarnings(
    "ignore",
    message=r"Failed to disconnect .* from signal .*",
    category=RuntimeWarning,
)

from PySide6.QtWidgets import QApplication, QWidget

from settings_window.settings_window import SettingsWindow


EXPECTED_NAV_ORDER = [
    "characters",
    "behavior",
    "memory",
    "relationship_guide",
    "reminders",
    "chat_history",
    "memory_album",
    "statistics",
    "llm",
    "compact_window",
    "quality",
    "screen_awareness",
    "tts",
    "asr",
    "pov",
    "chat_integration",
    "mcp_computer",
    "data_management",
]


class SidebarHarness(QWidget):
    _build_sidebar = SettingsWindow._build_sidebar
    _reserve_overlay_scrollbar = staticmethod(SettingsWindow._reserve_overlay_scrollbar)

    def __init__(self):
        super().__init__()
        self._nav_buttons = {}
        self._theme_widgets = []
        self._current_page = "characters"

    def _on_nav_selected(self, _nav_key):
        pass

    def _position_nav_indicator(self, _nav_key):
        pass

    def _update_sidebar_style(self):
        pass

    def _connect_theme_changed(self, _callback):
        pass


class SettingsNavigationOrderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sidebar_navigation_order_and_about_placement(self):
        harness = SidebarHarness()
        sidebar = harness._build_sidebar()
        nav_content = sidebar.findChild(QWidget, "sidebarNavContent")

        self.assertIsNotNone(nav_content)
        layout_order = [
            nav_content.layout().itemAt(index).widget()._nav_key
            for index in range(nav_content.layout().count())
            if nav_content.layout().itemAt(index).widget() is not None
        ]
        self.assertEqual(EXPECTED_NAV_ORDER, layout_order)

        button_order = list(harness._nav_buttons)
        self.assertEqual(EXPECTED_NAV_ORDER, button_order[:18])
        self.assertEqual("about", button_order[-1])
        self.assertIs(sidebar, harness._nav_buttons["about"].parent())


if __name__ == "__main__":
    unittest.main()
