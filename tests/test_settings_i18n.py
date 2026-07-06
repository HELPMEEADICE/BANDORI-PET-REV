import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LANG_DIR = ROOT / "lang"

RECENT_SETTINGS_KEYS = {
    "SettingsWindow.poke_feedback_section",
    "SettingsWindow.poke_feedback_hint",
    "SettingsWindow.poke_motion_follow_head",
    "SettingsWindow.poke_expression_follow_head",
    "SettingsWindow.llm_web_fetch_enabled",
    "SettingsWindow.llm_web_fetch_hint",
    "SettingsWindow.llm_live2d_outfit_recognition_enabled",
    "SettingsWindow.llm_live2d_outfit_recognition_hint",
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

    def test_normalize_language_handles_region_and_script_codes(self):
        from i18n_manager import normalize_language

        cases = {
            "zh-Hans-CN": "zh_CN",
            "zh-Hant-TW": "zh_TW",
            "zh-HK": "zh_TW",
            "zh_SG.UTF-8": "zh_CN",
            "ja-JP": "ja",
            "en-GB": "en_US",
            "C": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(expected, normalize_language(raw))

    def test_detect_system_language_uses_macos_apple_languages(self):
        from i18n_manager import detect_system_language

        def fake_defaults(args, **kwargs):
            key = args[-1]
            if key == "AppleLanguages":
                stdout = '(\n    "zh-Hant-TW",\n    "en-US"\n)\n'
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
            if key == "AppleLocale":
                return subprocess.CompletedProcess(args, 0, stdout="en_US\n", stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

        with patch("i18n_manager.sys.platform", "darwin"), \
             patch("i18n_manager.subprocess.run", side_effect=fake_defaults), \
             patch("i18n_manager.locale.getlocale", return_value=(None, None)), \
             patch("i18n_manager.locale.getdefaultlocale", return_value=("en_US", "UTF-8")):
            self.assertEqual("zh_TW", detect_system_language())

    def test_detect_system_language_uses_macos_apple_locale_fallback(self):
        from i18n_manager import detect_system_language

        def fake_defaults(args, **kwargs):
            key = args[-1]
            if key == "AppleLanguages":
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
            if key == "AppleLocale":
                return subprocess.CompletedProcess(args, 0, stdout="zh_Hans_CN\n", stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="")

        with patch("i18n_manager.sys.platform", "darwin"), \
             patch("i18n_manager.subprocess.run", side_effect=fake_defaults), \
             patch("i18n_manager.locale.getlocale", return_value=(None, None)), \
             patch("i18n_manager.locale.getdefaultlocale", return_value=("en_US", "UTF-8")):
            self.assertEqual("zh_CN", detect_system_language())


if __name__ == "__main__":
    unittest.main()
