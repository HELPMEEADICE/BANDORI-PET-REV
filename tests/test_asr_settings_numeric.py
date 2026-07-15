import unittest

from settings_window.pages.asr import ASRPageMixin


class _ValueWidget:
    def __init__(self):
        self.value = None

    def setChecked(self, value):
        self.value = value

    def setText(self, value):
        self.value = value

    def setValue(self, value):
        self.value = value


class _ChoiceWidget:
    def __init__(self, values):
        self._values = values
        self.value = None

    def count(self):
        return len(self._values)

    def itemData(self, index):
        return self._values[index]

    def setCurrentIndex(self, index):
        self.value = index


class _ASRSettingsHarness(ASRPageMixin):
    def __init__(self, max_record_seconds):
        self._cfg = {"asr_max_record_seconds": max_record_seconds}
        self._asr_enabled = _ValueWidget()
        self._asr_api_url = _ValueWidget()
        self._asr_api_key = _ValueWidget()
        self._asr_model_id = _ValueWidget()
        self._asr_language = _ChoiceWidget(["", "zh", "ja", "en"])
        self._asr_insert_mode = _ChoiceWidget(["append", "replace"])
        self._asr_auto_send = _ValueWidget()
        self._asr_max_record_seconds = _ValueWidget()

    def _asr_config_widgets_ready(self):
        return True


class ASRSettingsNumericTest(unittest.TestCase):
    def test_load_config_tolerates_infinite_record_duration(self):
        page = _ASRSettingsHarness(float("inf"))

        page._load_asr_config()

        self.assertEqual(60, page._asr_max_record_seconds.value)


if __name__ == "__main__":
    unittest.main()
