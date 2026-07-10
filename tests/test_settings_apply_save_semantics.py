import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from settings_window.pages.behavior import BehaviorPageMixin


class _ConfigStub:
    def __init__(self):
        self.data = {}
        self.saved = False

    def set(self, key, value):
        self.data[key] = value

    def get(self, key, default=None):
        return self.data.get(key, default)

    def save(self):
        self.saved = True


class _SwitchStub:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked


class _BehaviorHarness(BehaviorPageMixin, QWidget):
    def __init__(self):
        super().__init__()
        self._cfg = _ConfigStub()
        self._live2d_idle_actions_enabled = True
        self._live2d_random_actions_enabled = False
        self._live2d_head_tracking_enabled = True
        self._live2d_mutual_gaze_enabled = False
        self._emotion_behavior_enabled = True
        self._move_all_roles_together = True
        self._birthday_tray_notifications_enabled = False
        self.emitted_settings = []

        class _Signal:
            def __init__(self, owner):
                self._owner = owner

            def emit(self, data):
                self._owner.emitted_settings.append(dict(data))

        self.settings_changed = _Signal(self)


class _ApplyHarness(QWidget):
    from settings_window.settings_window import SettingsWindow

    _on_apply = SettingsWindow._on_apply
    _current_fps_setting = SettingsWindow._current_fps_setting
    _current_opacity_setting = SettingsWindow._current_opacity_setting
    _current_theme_setting = SettingsWindow._current_theme_setting
    _current_vsync_setting = SettingsWindow._current_vsync_setting
    _current_gpu_acceleration_setting = SettingsWindow._current_gpu_acceleration_setting

    def __init__(self):
        super().__init__()
        self._launched = False
        self._show_launch = False
        self._current_char = "kasumi"
        self._selected_costume = "default"
        self._cfg = _ConfigStub()
        self._auto_start_supported = False
        self._compact_window_reset_position_pending = False
        self._pet_positions_reset_pending = False
        self.closed = False
        self.settings_payloads = []
        self.model_payloads = []
        self.launches = 0
        self.fail_llm = False
        self._fps = 120
        self._opacity = 1.0
        self._vsync = True
        self._gpu_acceleration = True
        self._game_topmost = False
        self._obs_window_capture_compatible = False
        self._chat_window_normal_window = False
        self._hide_live2d_model = False
        self._live2d_idle_actions_enabled = True
        self._live2d_random_actions_enabled = True
        self._live2d_head_tracking_enabled = True
        self._live2d_mutual_gaze_enabled = False
        self._emotion_behavior_enabled = True
        self._poke_motion = ""
        self._poke_expression = ""
        self._move_all_roles_together = False
        self._birthday_tray_notifications_enabled = True
        self._live2d_quality = "balanced"
        self._live2d_scale = 0
        self._configured_models = []
        self._game_topmost_switch = _SwitchStub(False)
        self._obs_window_capture_compatible_switch = _SwitchStub(False)
        self._chat_window_normal_window_switch = _SwitchStub(False)
        self._hide_live2d_model_switch = _SwitchStub(False)
        self._auto_start_switch = _SwitchStub(False)

        class _Signal:
            def __init__(self, sink):
                self._sink = sink

            def emit(self, *args):
                self._sink(*args)

        self.settings_changed = _Signal(lambda data: self.settings_payloads.append(dict(data)))
        self.model_selected = _Signal(lambda char, costume: self.model_payloads.append((char, costume)))
        self.launch_requested = _Signal(lambda: setattr(self, "launches", self.launches + 1))

    def _selected_model_item(self):
        return None

    def _apply_auto_start_setting(self):
        return True

    def _save_llm_config(self, show_info=True):
        return not self.fail_llm

    def _save_tts_config(self, show_info=True):
        return True

    def _save_asr_config(self, show_info=True):
        return True

    def _save_compact_window_config(self, show_info=True, emit_update=False):
        return True

    def _save_chat_integration_config(self, show_info=True, emit_update=False):
        return True

    def _save_mcp_computer_config(self, show_info=True):
        return True

    def _save_reminder_config(self, show_info=True, emit_update=True):
        return True

    def _save_screen_awareness_config(self, show_info=True, emit_update=True):
        return True

    def _save_configured_models(self, emit_update=True):
        return True

    def _screen_awareness_settings_data(self):
        return {}

    def _should_emit_model_selection_on_apply(self):
        return True

    def close(self):
        self.closed = True


class SettingsApplySaveSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_live2d_behavior_save_emits_runtime_settings(self):
        harness = _BehaviorHarness()

        harness._save_live2d_behavior_config()

        self.assertTrue(harness._cfg.saved)
        self.assertEqual(1, len(harness.emitted_settings))
        self.assertEqual({
            "live2d_idle_actions_enabled": True,
            "live2d_random_actions_enabled": False,
            "live2d_head_tracking_enabled": True,
            "live2d_mutual_gaze_enabled": False,
            "emotion_behavior_enabled": True,
            "move_all_roles_together": True,
            "birthday_tray_notifications_enabled": False,
        }, harness.emitted_settings[0])

    def test_apply_failure_does_not_emit_or_close(self):
        harness = _ApplyHarness()
        harness.fail_llm = True

        with patch("settings_window.settings_window.InfoBar.error") as error_bar:
            harness._on_apply()

        self.assertFalse(harness.closed)
        self.assertFalse(harness.settings_payloads)
        self.assertFalse(harness.model_payloads)
        self.assertEqual(0, harness.launches)
        self.assertFalse(harness._launched)
        self.assertTrue(error_bar.called)

    def test_apply_success_still_emits_and_closes(self):
        harness = _ApplyHarness()

        harness._on_apply()

        self.assertTrue(harness.closed)
        self.assertEqual(1, len(harness.settings_payloads))
        self.assertEqual([("kasumi", "default")], harness.model_payloads)


if __name__ == "__main__":
    unittest.main()
