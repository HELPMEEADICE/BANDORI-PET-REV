import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from i18n_manager import current_language, set_language
from settings_window.constants import BodyLabel, _wrap_label
from settings_window.pages.chat_integration import ChatIntegrationPageMixin


class ChatIntegrationHarness(ChatIntegrationPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._cfg = None

    def _make_theme_widget(self, widget):
        return widget

    def _connect_theme_changed(self, _callback):
        pass

    def _refresh_theme_widget_styles(self, _widget):
        pass

    def _refresh_json_code_edit_theme(self, _edit):
        pass

    def _add_switch_row(self, layout: QVBoxLayout, page: QWidget, label: str, switch):
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_wrap_label(BodyLabel(label, page)), 1)
        row.addWidget(switch)
        layout.addLayout(row)


class ChatIntegrationLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_localized_pages_fit_without_horizontal_scrolling(self):
        previous_language = current_language()
        try:
            for language in ("en_US", "ja", "zh_TW"):
                with self.subTest(language=language):
                    set_language(language)
                    harness = ChatIntegrationHarness()
                    page = harness._build_chat_integration_page()
                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    scroll.setWidget(page)
                    scroll.resize(640, 700)
                    scroll.show()
                    self.app.processEvents()

                    self.assertEqual(QSizePolicy.Policy.Ignored, page.sizePolicy().horizontalPolicy())
                    self.assertEqual(0, scroll.horizontalScrollBar().maximum())

                    scroll.close()
                    harness.close()
        finally:
            set_language(previous_language)


if __name__ == "__main__":
    unittest.main()
