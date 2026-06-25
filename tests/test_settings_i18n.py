import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LANG_DIR = ROOT / "lang"

RECENT_SETTINGS_KEYS = {
    "SettingsWindow.poke_feedback_section",
    "SettingsWindow.poke_feedback_hint",
    "SettingsWindow.poke_motion_follow_head",
    "SettingsWindow.poke_expression_follow_head",
    "SettingsWindow.llm_web_fetch_enabled",
    "SettingsWindow.llm_web_fetch_hint",
    "SettingsWindow.llm_auto_continue_enabled",
    "SettingsWindow.llm_auto_continue_max_turns",
    "SettingsWindow.llm_auto_continue_hint",
    "SettingsWindow.llm_api_profile_save_hint",
    "SettingsWindow.llm_chat_history_message_limit",
    "SettingsWindow.llm_compact_history_message_limit",
    "SettingsWindow.llm_history_message_limit_hint",
    "SettingsWindow.llm_history_message_limit_unlimited",
    "SettingsWindow.screen_awareness_title",
    "SettingsWindow.screen_awareness_hint",
    "SettingsWindow.screen_awareness_interval",
    "SettingsWindow.screen_awareness_speaker",
    "SettingsWindow.screen_awareness_max_width",
    "SettingsWindow.screen_awareness_speaker_random",
    "SettingsWindow.screen_awareness_speaker_default",
    "SettingsWindow.screen_awareness_test",
    "SettingsWindow.screen_awareness_test_disabled_title",
    "SettingsWindow.screen_awareness_test_disabled_content",
    "SettingsWindow.screen_awareness_test_sent_title",
    "SettingsWindow.screen_awareness_test_sent_content",
    "SettingsWindow.care_policy_saved_title",
    "SettingsWindow.care_policy_saved_content",
}

DATE_PICKER_MONTH_KEYS = [
    f"SettingsWindow.date_picker_month_{month}"
    for month in range(1, 13)
]


class SettingsI18nTests(unittest.TestCase):
    def test_recent_settings_strings_exist_in_every_language(self):
        for path in sorted(LANG_DIR.glob("*.json")):
            with self.subTest(language=path.stem):
                translations = json.loads(path.read_text(encoding="utf-8-sig"))
                missing = sorted(
                    key
                    for key in RECENT_SETTINGS_KEYS
                    if not str(translations.get(key, "")).strip()
                )
                self.assertEqual([], missing)

    def test_date_picker_month_strings_exist_in_every_language(self):
        for path in sorted(LANG_DIR.glob("*.json")):
            with self.subTest(language=path.stem):
                translations = json.loads(path.read_text(encoding="utf-8-sig"))
                missing = sorted(
                    key
                    for key in DATE_PICKER_MONTH_KEYS
                    if not str(translations.get(key, "")).strip()
                )
                self.assertEqual([], missing)

    def test_date_picker_months_follow_current_language(self):
        from i18n_manager import date_picker_months, current_language, set_language

        original_language = current_language()
        try:
            set_language("zh_CN")
            self.assertEqual("1月", date_picker_months()[0])
            self.assertEqual("12月", date_picker_months()[11])

            set_language("en_US")
            self.assertEqual("January", date_picker_months()[0])
            self.assertEqual("December", date_picker_months()[11])
        finally:
            set_language(original_language)

    def test_chat_history_month_formatter_uses_translated_months(self):
        from i18n_manager import current_language, set_language
        from settings_window.pages.chat_history import _I18nMonthFormatter

        original_language = current_language()
        try:
            set_language("zh_CN")
            formatter = _I18nMonthFormatter()
            self.assertEqual("6月", formatter.encode(6))
            self.assertEqual(6, formatter.decode("6月"))
        finally:
            set_language(original_language)


if __name__ == "__main__":
    unittest.main()
