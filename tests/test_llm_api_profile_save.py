import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from settings_window.pages.llm import LLMPageMixin, LLM_API_PROFILE_KEYS


def _profile(**overrides):
    profile = {
        "name": "DS",
        "llm_api_url": "https://example.test/v1/chat/completions",
        "llm_api_key": "secret",
        "llm_model_id": "model-main",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "model-vision",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": True,
        "llm_live2d_outfit_recognition_enabled": False,
        "llm_api_mode": "chat_completions",
        "llm_web_search_enabled": True,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": True,
        "llm_web_fetch_enabled": True,
        "llm_auto_continue_enabled": False,
        "llm_auto_continue_max_turns": 5,
        "llm_chat_history_message_limit": 40,
        "llm_compact_history_message_limit": 12,
        "llm_cross_chat_history_enabled": True,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    }
    profile.update(overrides)
    return profile


class _ConfigStub:
    def __init__(self):
        self.data = {
            "llm_api_profiles": [],
            "llm_active_api_profile": "",
        }
        self.saved = False

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saved = True


class _TextStub:
    def __init__(self, value):
        self.value = value

    def text(self):
        return self.value


class _ComboStub:
    def currentIndex(self):
        return -1

    def itemData(self, _index):
        return ""


class _LLMProfileHarness(LLMPageMixin, QWidget):
    def __init__(self, profile):
        super().__init__()
        self._cfg = _ConfigStub()
        self._profile = profile
        self._llm_api_profile_name = _TextStub(profile["name"])
        self._llm_api_profile_combo = _ComboStub()

    def _llm_config_widgets_ready(self):
        return True

    def _llm_api_profile_widgets_ready(self):
        return True

    def _current_llm_api_profile(self, name):
        return {**self._profile, "name": name}

    def _reload_llm_api_profiles(self, selected_name=""):
        self.reloaded_name = selected_name

    def _update_current_llm_api_profile_label(self):
        pass


class _LLMPageHarness(LLMPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._cfg = None
        self._theme_widgets = []
        self._avatar_color_btns = []
        self.profile_label_updates = 0

    def _make_theme_widget(self, widget):
        return widget

    def _connect_theme_changed(self, _callback):
        pass

    def _update_current_llm_api_profile_label(self):
        self.profile_label_updates += 1


class LLMApiProfileSaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_profile_applies_it_and_clears_modified_state(self):
        profile = _profile()
        harness = _LLMProfileHarness(profile)

        with patch("settings_window.pages.llm.InfoBar.success"):
            harness._save_llm_api_profile()

        self.assertTrue(harness._cfg.saved)
        self.assertEqual("DS", harness._cfg.get("llm_active_api_profile"))
        self.assertEqual("DS", harness.reloaded_name)
        for key in LLM_API_PROFILE_KEYS:
            self.assertEqual(profile[key], harness._cfg.get(key), key)
        self.assertEqual(("DS", False), harness._applied_llm_api_profile_display_name())

        harness.close()

    def test_profile_fields_refresh_modified_state_as_they_change(self):
        harness = _LLMPageHarness()
        page = harness._build_llm_page()
        harness._cfg = _ConfigStub()

        harness._llm_model_id.setText("changed-model")
        self.assertEqual(1, harness.profile_label_updates)

        harness._llm_web_fetch_enabled.setChecked(True)
        self.assertEqual(2, harness.profile_label_updates)

        page.close()
        harness.close()

    def test_live_widget_values_are_compared_with_active_profile(self):
        profile = _profile(llm_model_id="saved-model")
        harness = _LLMProfileHarness(profile)
        harness._cfg.data.update({
            "llm_api_profiles": [profile],
            "llm_active_api_profile": "DS",
        })

        self.assertEqual(("DS", False), harness._applied_llm_api_profile_display_name())
        harness._profile = {**profile, "llm_model_id": "changed-model"}
        self.assertEqual(("DS", True), harness._applied_llm_api_profile_display_name())
        harness._profile = {
            **profile,
            "llm_api_url": "",
            "llm_api_key": "",
            "llm_model_id": "",
        }
        self.assertEqual(("DS", True), harness._applied_llm_api_profile_display_name())

        harness.close()


if __name__ == "__main__":
    unittest.main()
