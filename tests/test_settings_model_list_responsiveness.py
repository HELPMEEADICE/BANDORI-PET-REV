import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from settings_window.settings_window import SettingsWindow


class _FakeWidget:
    def show(self):
        pass

    def hide(self):
        pass

    def setText(self, _text):
        pass

    def setPixmap(self, _pixmap):
        pass

    def size(self):
        return None


class _FakeModelManager:
    characters = ["kasumi"]

    def get_character_band(self, _character):
        return "poppin_party"

    def get_display_name(self, character):
        return character

    def get_costume_display_name(self, _character, costume):
        return costume

    def get_band_display_name(self, band):
        return band

    def get_character_image_path(self, _character):
        return ""

    def get_character_image_data(self, _character):
        return b""

    def get_motion_names(self, _character, _costume):
        raise AssertionError("model metadata must not be loaded during list selection")


class _FakeConfig:
    def __init__(self):
        self.save_count = 0

    def set(self, _key, _value):
        pass

    def save(self):
        self.save_count += 1


class _CountingImageModelManager(_FakeModelManager):
    def __init__(self):
        self.path_reads = 0
        self.data_reads = 0

    def get_character_image_path(self, _character):
        self.path_reads += 1
        return ""

    def get_character_image_data(self, _character):
        self.data_reads += 1
        return b""


class SettingsModelListResponsivenessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_show_model_detail_defers_slow_metadata_loading(self):
        window = SettingsWindow.__new__(SettingsWindow)
        window._model_manager = _FakeModelManager()
        window._configured_models = [{"character": "kasumi", "costume": "live_default"}]
        window._selected_list_character = "kasumi"
        window._selecting_model = True
        window._selection_scroll = _FakeWidget()
        window._selection_grid_widget = _FakeWidget()
        window._selection_back_btn = _FakeWidget()
        window._selection_title = _FakeWidget()
        window._selection_subtitle = _FakeWidget()
        window._model_detail_widget = _FakeWidget()
        window._detail_name = _FakeWidget()
        window._detail_costume = _FakeWidget()
        window._detail_band = _FakeWidget()
        window._detail_image = _FakeWidget()
        window._clear_selection_cards = lambda: None
        window._set_character_tools_visible = lambda _visible: None
        window._set_model_detail_metadata_loading = lambda: None

        queued = []
        window._queue_model_detail_metadata_load = lambda item: queued.append(dict(item))
        window._populate_default_motion_combo = lambda item: window._model_manager.get_motion_names(item["character"], item["costume"])
        window._populate_default_expression_combo = lambda _item: None
        window._populate_click_motion_combos = lambda _item: None
        window._matching_click_motion_profile_name = lambda _item: ""
        window._reload_click_motion_profiles = lambda select_name="": None

        window._show_model_detail()

        self.assertEqual([{"character": "kasumi", "costume": "live_default"}], queued)

    def test_rapid_metadata_requests_start_only_latest_load(self):
        class FakeTimer:
            def __init__(self):
                self.start_intervals = []

            def start(self, interval):
                self.start_intervals.append(interval)

            def stop(self):
                pass

        window = SettingsWindow.__new__(SettingsWindow)
        window._model_detail_metadata_request_id = 0
        timer = FakeTimer()
        window._model_detail_metadata_timer = timer
        started = []
        window._start_model_detail_metadata_load = lambda item: started.append(dict(item))

        first = {"character": "kasumi", "costume": "live_default"}
        second = {"character": "arisa", "costume": "school_winter"}
        third = {"character": "tae", "costume": "casual"}

        window._queue_model_detail_metadata_load(first)
        window._queue_model_detail_metadata_load(second)
        window._queue_model_detail_metadata_load(third)

        self.assertEqual([], started)
        self.assertEqual([120, 120, 120], timer.start_intervals)
        self.assertEqual(3, window._model_detail_metadata_request_id)

        window._flush_queued_model_detail_metadata_load()

        self.assertEqual([third], started)

    def test_model_list_selection_saves_picker_state_once(self):
        window = SettingsWindow.__new__(SettingsWindow)
        cfg = _FakeConfig()
        window._cfg = cfg
        window._model_manager = _FakeModelManager()
        window._configured_models = [{"character": "kasumi", "costume": "live_default"}]
        window._picker_state = {
            "recent_characters": [],
            "favorite_characters": [],
            "recent_costumes": [],
            "favorite_costumes": [],
        }
        window._activate_char_page_for_model_list = lambda: None
        window._refresh_model_list = lambda: None
        window._show_model_detail = lambda: None

        window._select_model_list_item("kasumi")

        self.assertEqual(1, cfg.save_count)

    def test_model_list_selection_updates_selection_without_rebuilding_rows(self):
        window = SettingsWindow.__new__(SettingsWindow)
        window._cfg = _FakeConfig()
        window._model_manager = _FakeModelManager()
        window._configured_models = [{"character": "kasumi", "costume": "live_default"}]
        window._picker_state = {
            "recent_characters": [],
            "favorite_characters": [],
            "recent_costumes": [],
            "favorite_costumes": [],
        }
        window._activate_char_page_for_model_list = lambda: None
        window._show_model_detail = lambda: None
        window._refresh_model_list = lambda: self.fail("selection must not rebuild model list rows")
        updated = []
        window._update_model_list_selection = lambda: updated.append(True)

        window._select_model_list_item("kasumi")

        self.assertEqual([True], updated)

    def test_detail_character_image_is_cached_per_character(self):
        window = SettingsWindow.__new__(SettingsWindow)
        manager = _CountingImageModelManager()
        window._model_manager = manager
        window._detail_image_pixmap_cache = {}

        self.assertIsNone(window._load_detail_character_pixmap("kasumi"))
        self.assertIsNone(window._load_detail_character_pixmap("kasumi"))

        self.assertEqual(1, manager.path_reads)
        self.assertEqual(1, manager.data_reads)


if __name__ == "__main__":
    unittest.main()
