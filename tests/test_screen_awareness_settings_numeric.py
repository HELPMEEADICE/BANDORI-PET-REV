import unittest

from reminder_core import PROACTIVE_CARE_POLICY_CONFIG_KEY
from settings_window.pages.screen_awareness import ScreenAwarenessPageMixin


class _Config(dict):
    def set(self, key, value):
        self[key] = value


class _ValueWidget:
    def __init__(self):
        self.value = None

    def setChecked(self, value):
        self.value = value

    def setValue(self, value):
        self.value = value


class _ScreenAwarenessHarness(ScreenAwarenessPageMixin):
    def __init__(self, config):
        self._cfg = _Config(config)
        self._screen_awareness_enabled = _ValueWidget()
        self._screen_awareness_interval = _ValueWidget()
        self._screen_awareness_max_width = _ValueWidget()

    def _fill_screen_awareness_character_combo(self, mode="random_visible", selected=""):
        pass

    def _set_screen_awareness_model_mode(self, mode):
        pass

    def _set_screen_awareness_display_mode(self, mode):
        pass


class ScreenAwarenessSettingsNumericTest(unittest.TestCase):
    def test_load_controls_tolerates_infinite_screenshot_width(self):
        page = _ScreenAwarenessHarness(
            {"screen_awareness_max_screenshot_width": float("inf")}
        )

        page._load_screen_awareness_controls()

        self.assertEqual(1920, page._screen_awareness_max_width.value)

    def test_settings_data_tolerates_infinite_numeric_values(self):
        page = _ScreenAwarenessHarness(
            {
                "screen_awareness_interval_minutes": float("inf"),
                "screen_awareness_max_screenshot_width": float("inf"),
            }
        )

        data = page._screen_awareness_settings_data()

        self.assertEqual(30, data["screen_awareness_interval_minutes"])
        self.assertEqual(1920, data["screen_awareness_max_screenshot_width"])

    def test_remote_interval_tolerates_infinite_value(self):
        page = _ScreenAwarenessHarness({"screen_awareness_enabled": False})

        page._apply_screen_awareness_remote_settings(
            {"screen_awareness_interval_minutes": float("inf")}
        )

        policy = page._cfg[PROACTIVE_CARE_POLICY_CONFIG_KEY]
        self.assertEqual(30, policy["global_cooldown_minutes"])


if __name__ == "__main__":
    unittest.main()
