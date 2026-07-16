import unittest
from unittest import mock

from model_manager import ModelManager, _MODEL_JSON_CACHE_LIMIT


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

    def test_model_json_cache_is_lru_bounded(self):
        manager = ModelManager(scan_models=False)
        paths = [f"models.zst::costume_{index}/model.json" for index in range(_MODEL_JSON_CACHE_LIMIT + 2)]

        with mock.patch("model_manager.load_virtual_json", side_effect=lambda path: {"path": path}):
            for path in paths[:_MODEL_JSON_CACHE_LIMIT]:
                manager._read_model_json(path)
            manager._read_model_json(paths[0])
            manager._read_model_json(paths[_MODEL_JSON_CACHE_LIMIT])
            manager._read_model_json(paths[_MODEL_JSON_CACHE_LIMIT + 1])

        self.assertEqual(_MODEL_JSON_CACHE_LIMIT, len(manager._model_json_cache))
        self.assertIn(paths[0], manager._model_json_cache)
        self.assertNotIn(paths[1], manager._model_json_cache)
        self.assertNotIn(paths[2], manager._model_json_cache)

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
