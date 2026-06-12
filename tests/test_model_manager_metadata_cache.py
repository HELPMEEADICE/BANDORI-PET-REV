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


if __name__ == "__main__":
    unittest.main()
