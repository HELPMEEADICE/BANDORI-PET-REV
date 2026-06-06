import os
import unittest
import warnings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
warnings.filterwarnings(
    "ignore",
    message=r"Failed to disconnect .* from signal .*",
    category=RuntimeWarning,
)

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

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
        self.assertEqual([*EXPECTED_NAV_ORDER, "about"], button_order)

        about_button = harness._nav_buttons["about"]
        about_ancestors = []
        ancestor = about_button.parentWidget()
        while ancestor is not None:
            about_ancestors.append(ancestor)
            ancestor = ancestor.parentWidget()
        self.assertNotIn(nav_content, about_ancestors)

        nav_scroll = nav_content.parentWidget()
        while nav_scroll is not None and nav_scroll.parentWidget() is not sidebar:
            nav_scroll = nav_scroll.parentWidget()
        self.assertIsNotNone(nav_scroll)
        self.assertIs(nav_content, nav_scroll.findChild(QWidget, "sidebarNavContent"))

        sidebar_layout = sidebar.layout()
        scroll_index = sidebar_layout.indexOf(nav_scroll)
        about_rows = [
            (index, sidebar_layout.itemAt(index).layout())
            for index in range(sidebar_layout.count())
            if sidebar_layout.itemAt(index).layout() is not None
            and sidebar_layout.itemAt(index).layout().indexOf(about_button) >= 0
        ]
        self.assertEqual(1, len(about_rows))
        about_row_index, about_row = about_rows[0]
        self.assertIsInstance(about_row, QHBoxLayout)
        self.assertGreaterEqual(scroll_index, 0)
        self.assertLess(scroll_index, about_row_index)


if __name__ == "__main__":
    unittest.main()
