import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_manager
from model_manager import ModelManager


def _write_model3(root: Path, name: str = "test.model3.json") -> Path:
    (root / "textures").mkdir(parents=True, exist_ok=True)
    (root / "test.moc3").write_bytes(b"moc3")
    (root / "textures" / "texture_00.png").write_bytes(b"png")
    model3_path = root / name
    model3_path.write_text(
        json.dumps({
            "Version": 3,
            "FileReferences": {
                "Moc": "test.moc3",
                "Textures": ["textures/texture_00.png"],
                "Physics": "test.physics3.json",
                "Motions": {
                    "mtn_smile01_C": [{"File": "motions/mtn_smile01_C.motion3.json"}],
                    "mtn_angry01_C": [{"File": "motions/mtn_angry01_C.motion3.json"}],
                },
                "Expressions": [
                    {"Name": "exp_smile01", "File": "expressions/exp_smile01.exp3.json"},
                    {"Name": "exp_angry01", "File": "expressions/exp_angry01.exp3.json"},
                ],
            },
            "HitAreas": [{"Id": "HitAreaHead", "Name": "Head"}],
        }),
        encoding="utf-8",
    )
    return model3_path


class ModelManagerMoc3Test(unittest.TestCase):
    def test_scan_detects_model3_json_costumes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            costume_dir = models / "anon" / "live_01"
            costume_dir.mkdir(parents=True)
            model3_path = _write_model3(costume_dir)

            with (
                patch.object(model_manager, "MODELS_DIR", models),
                patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
                patch.object(model_manager, "BAND_JSON", root / "missing-band.json"),
            ):
                manager = ModelManager()

            self.assertEqual("moc3", manager.get_model_format("anon", "live_01"))
            self.assertEqual(str(model3_path.resolve()), manager.get_model_json_path("anon", "live_01"))
            self.assertEqual(
                [{"id": "live_01", "path": str(model3_path.resolve()), "format": "moc3"}],
                manager.get_costumes("anon"),
            )

    def test_model3_metadata_uses_file_references(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            model3_path = _write_model3(root)
            manager = ModelManager(scan_models=False)
            manager._model_paths[("anon", "live_01")] = str(model3_path)

            self.assertEqual("moc3", manager.get_model_format("anon", "live_01"))
            self.assertEqual(["mtn_angry01_C", "mtn_smile01_C"], manager.get_motion_names("anon", "live_01"))
            self.assertEqual(["exp_angry01", "exp_smile01"], manager.get_expression_names("anon", "live_01"))

    def test_single_model_manager_exposes_model_format(self):
        from pet_process import SingleModelManager

        with tempfile.TemporaryDirectory() as temp_dir:
            model3_path = _write_model3(Path(temp_dir))
            manager = SingleModelManager("anon", "live_01", str(model3_path))

            self.assertEqual("moc3", manager.get_model_format("anon", "live_01"))

    def test_single_model_manager_uses_controller_format_without_catalog_scan(self):
        from pet_process import SingleModelManager

        manager = SingleModelManager("anon", "live_01", "model.json", "moc3")
        with patch("pet_process.ModelManager", side_effect=AssertionError("catalog scan")):
            self.assertEqual("moc3", manager.get_model_format("anon", "live_01"))
        self.assertIsNone(manager._metadata_manager)

    def test_model_manager_can_load_names_without_model_discovery(self):
        with (
            patch.object(ModelManager, "_scan", side_effect=AssertionError("full scan")),
            patch.object(ModelManager, "_scan_model_keys", side_effect=AssertionError("key scan")),
        ):
            manager = ModelManager(discover_models=False)

        self.assertEqual("仓田真白", manager.get_display_name("mashiro"))
        self.assertEqual({}, manager._model_paths)

    def test_archive_scan_detects_model3_json_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "anon.zst"
            archive.write_bytes(b"archive")
            model_member = "live_01/test.model3.json"

            with patch.object(model_manager, "list_archive_files", return_value=[model_member]):
                result = ModelManager(scan_models=False)._read_model_archive(archive)

            model_path = f"{archive.resolve()}::{model_member}"
            self.assertEqual({
                "character": "anon",
                "costumes": [{"id": "live_01", "path": model_path, "format": "moc3"}],
                "image_path": "",
                "model_paths": [("anon", "live_01", model_path)],
            }, result)

    def test_archive_scan_does_not_read_model_json_members_for_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "anon.zst"
            archive.write_bytes(b"archive")
            model_member = "live_01/model.json"

            with (
                patch.object(model_manager, "list_archive_files", return_value=[model_member]),
                patch.object(model_manager, "load_virtual_json", side_effect=AssertionError("archive model json was read")) as load_json,
            ):
                result = ModelManager(scan_models=False)._read_model_archive(archive)

            model_path = f"{archive.resolve()}::{model_member}"
            self.assertEqual({
                "character": "anon",
                "costumes": [{"id": "live_01", "path": model_path, "format": "moc"}],
                "image_path": "",
                "model_paths": [("anon", "live_01", model_path)],
            }, result)
            load_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
