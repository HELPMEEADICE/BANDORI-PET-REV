import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from config_manager import DEFAULTS, _normalize_llm_api_profile
from database_manager import DatabaseManager
from i18n_manager import current_language, set_language
from settings_window.pages.llm import LLMPageMixin
from token_usage import history_message_query_limit, normalize_history_message_limit


class _LLMPageHarness(LLMPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._cfg = None
        self._theme_widgets = []
        self._avatar_color_btns = []

    def _make_theme_widget(self, widget):
        return widget

    def _connect_theme_changed(self, _callback):
        pass


class ChatContextLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_defaults_preserve_existing_context_sizes(self):
        self.assertEqual(DEFAULTS["llm_chat_history_message_limit"], 40)
        self.assertEqual(DEFAULTS["llm_compact_history_message_limit"], 12)

    def test_profile_context_limits_are_preserved_and_clamped(self):
        profile = _normalize_llm_api_profile({
            "name": "test",
            "llm_chat_history_message_limit": 80,
            "llm_compact_history_message_limit": 1,
        })

        self.assertEqual(profile["llm_chat_history_message_limit"], 80)
        self.assertEqual(profile["llm_compact_history_message_limit"], 2)

        unlimited_profile = _normalize_llm_api_profile({
            "name": "unlimited",
            "llm_chat_history_message_limit": 0,
            "llm_compact_history_message_limit": 0,
        })
        self.assertEqual(unlimited_profile["llm_chat_history_message_limit"], 0)
        self.assertEqual(unlimited_profile["llm_compact_history_message_limit"], 0)

    def test_invalid_runtime_limits_fall_back_to_defaults(self):
        self.assertEqual(normalize_history_message_limit("bad", 40), 40)
        self.assertEqual(normalize_history_message_limit(None, 12), 12)

    def test_unlimited_query_loads_more_than_slider_numeric_maximum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(os.path.join(temp_dir, "history.db"))
            conversation_id = db.create_conversation("test")
            for index in range(105):
                db.add_message(conversation_id, "user", f"message {index}")

            messages = db.get_messages(
                conversation_id,
                limit=history_message_query_limit(0, 40),
            )
            db.close()

        self.assertEqual(105, len(messages))
        self.assertEqual("message 0", messages[0]["content"])
        self.assertEqual("message 104", messages[-1]["content"])

    def test_llm_context_sliders_fit_localized_page(self):
        previous_language = current_language()
        try:
            for language in ("zh_CN", "zh_TW", "en_US", "ja"):
                with self.subTest(language=language):
                    set_language(language)
                    harness = _LLMPageHarness()
                    page = harness._build_llm_page()
                    scroll = QScrollArea()
                    scroll.setWidgetResizable(True)
                    scroll.setHorizontalScrollBarPolicy(
                        Qt.ScrollBarPolicy.ScrollBarAsNeeded
                    )
                    scroll.setWidget(page)
                    scroll.resize(900, 700)
                    scroll.show()
                    self.app.processEvents()

                    self.assertEqual(0, scroll.horizontalScrollBar().maximum())
                    self.assertEqual(40, harness._llm_chat_history_message_limit.value())
                    self.assertEqual(12, harness._llm_compact_history_message_limit.value())
                    harness._llm_chat_history_message_limit.setValue(65)
                    self.assertEqual(
                        "65",
                        harness._llm_chat_history_message_limit_value.text(),
                    )
                    harness._llm_chat_history_message_limit.setValue(101)
                    self.assertNotEqual(
                        "101",
                        harness._llm_chat_history_message_limit_value.text(),
                    )

                    scroll.close()
                    harness.close()
        finally:
            set_language(previous_language)


if __name__ == "__main__":
    unittest.main()
