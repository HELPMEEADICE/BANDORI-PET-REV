import unittest
from unittest import mock

from model_manager import ModelManager


class ModelManagerMetadataCacheTest(unittest.TestCase):
    def test_motion_and_expression_names_share_model_json_read(self):
        manager = ModelManager(scan_models=False)
        manager._model_paths[("kasumi", "live_default")] = "kasumi.zst::live_default/model.json"
        model_json = {
            "motions": {"idle": [], "tap": []},
            "expressions": [{"name": "smile"}, {"name": "angry"}],
        }

        with mock.patch("model_manager.load_virtual_json", return_value=model_json) as load_json:
            self.assertEqual(["idle", "tap"], manager.get_motion_names("kasumi", "live_default"))
            self.assertEqual(["angry", "smile"], manager.get_expression_names("kasumi", "live_default"))

        self.assertEqual(1, load_json.call_count)

    def test_scans_do_not_preflight_model_directories(self):
        manager = ModelManager.__new__(ModelManager)
        manager._model_paths = {}
        manager._character_images = {}
        manager._characters = {}

        with mock.patch("model_manager.models_dir_exists", side_effect=AssertionError("preflight")), \
             mock.patch("model_manager.model_search_dirs", return_value=[]):
            manager._scan_model_keys()
            manager._scan()

    def test_missing_character_image_uses_scan_cache_without_disk_fallback(self):
        manager = ModelManager.__new__(ModelManager)
        manager._character_images = {}

        with mock.patch.object(
            manager,
            "_find_dir_character_image",
            side_effect=AssertionError("unexpected disk lookup"),
        ):
            self.assertEqual("", manager.get_character_image_path("missing"))


if __name__ == "__main__":
    unittest.main()
