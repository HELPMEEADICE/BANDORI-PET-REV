import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import model_manager
from model_manager import ModelManager


class ModelManagerArchivePrecedenceTest(unittest.TestCase):
    @staticmethod
    def _write_dir_model(models: Path, character: str, costume: str = "default"):
        costume_dir = models / character / costume
        costume_dir.mkdir(parents=True)
        model_json = costume_dir / "model.json"
        model_json.write_text('{"model": "base.moc", "textures": ["base.png"]}', encoding="utf-8")
        return str(model_json.resolve())

    def test_unrecognized_same_name_folder_does_not_hide_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            models.mkdir()

            character_dir = models / "arisa"
            (character_dir / "default" / "parts").mkdir(parents=True)
            (character_dir / "default" / "parts" / "base.json").write_text(
                '{"model": "base.moc", "textures": ["base.png"]}',
                encoding="utf-8",
            )
            archive_path = models / "arisa.zst"
            archive_path.write_bytes(b"archive")
            archive_model_path = f"{archive_path.resolve()}::model.json"
            archive_result = {
                "character": "arisa",
                "costumes": [{"id": "default", "path": archive_model_path}],
                "image_path": "",
                "model_paths": [("arisa", "default", archive_model_path)],
            }

            with (
                patch.object(model_manager, "MODELS_DIR", models),
                patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
                patch.object(model_manager, "BAND_JSON", root / "missing-band.json"),
                patch.object(ModelManager, "_read_model_archive", return_value=archive_result) as read_archive,
            ):
                manager = ModelManager()

            read_archive.assert_called_once_with(archive_path)
            self.assertEqual(["default"], [item["id"] for item in manager.get_costumes("arisa")])
            self.assertEqual(archive_model_path, manager.get_model_json_path("arisa", "default"))

    def test_same_name_folder_and_archive_costumes_are_merged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            models.mkdir()

            dir_model_path = self._write_dir_model(models, "mutsumi", "folder_costume")
            archive_path = models / "mutsumi.zst"
            archive_path.write_bytes(b"archive")
            archive_model_path = f"{archive_path.resolve()}::archive_costume/model.json"
            archive_result = {
                "character": "mutsumi",
                "costumes": [{"id": "archive_costume", "path": archive_model_path}],
                "image_path": "",
                "model_paths": [("mutsumi", "archive_costume", archive_model_path)],
            }

            with (
                patch.object(model_manager, "MODELS_DIR", models),
                patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
                patch.object(model_manager, "BAND_JSON", root / "missing-band.json"),
                patch.object(ModelManager, "_read_model_archive", return_value=archive_result),
            ):
                manager = ModelManager()

            self.assertEqual(["archive_costume", "folder_costume"], [item["id"] for item in manager.get_costumes("mutsumi")])
            self.assertEqual(dir_model_path, manager.get_model_json_path("mutsumi", "folder_costume"))
            self.assertEqual(archive_model_path, manager.get_model_json_path("mutsumi", "archive_costume"))

    def test_archive_overrides_same_costume_from_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            models.mkdir()

            self._write_dir_model(models, "mutsumi", "default")
            archive_path = models / "mutsumi.zst"
            archive_path.write_bytes(b"archive")
            archive_model_path = f"{archive_path.resolve()}::default/model.json"
            archive_result = {
                "character": "mutsumi",
                "costumes": [{"id": "default", "path": archive_model_path}],
                "image_path": "",
                "model_paths": [("mutsumi", "default", archive_model_path)],
            }

            with (
                patch.object(model_manager, "MODELS_DIR", models),
                patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
                patch.object(model_manager, "BAND_JSON", root / "missing-band.json"),
                patch.object(ModelManager, "_read_model_archive", return_value=archive_result),
            ):
                manager = ModelManager()

            self.assertEqual(["default"], [item["id"] for item in manager.get_costumes("mutsumi")])
            self.assertEqual(archive_model_path, manager.get_model_json_path("mutsumi", "default"))

    def test_fixed_others_and_custom_models_are_separate_groups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            models.mkdir()

            self._write_dir_model(models, "mana")
            self._write_dir_model(models, "asuka")
            self._write_dir_model(models, "mutsumi")
            self._write_dir_model(models, "mutsumi1")
            band_json = root / "band.json"
            band_json.write_text(
                json.dumps({
                    "bands": [
                        {
                            "id": "ave_mujica",
                            "display": "Ave Mujica",
                            "characters": ["mutsumi"],
                        },
                        {
                            "id": "others",
                            "display": "Other Characters",
                            "characters": ["mana", "asuka"],
                        },
                    ]
                }),
                encoding="utf-8",
            )

            with (
                patch.object(model_manager, "MODELS_DIR", models),
                patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
                patch.object(model_manager, "BAND_JSON", band_json),
            ):
                manager = ModelManager()

            self.assertEqual("others", manager.get_character_band("mana"))
            self.assertEqual("others", manager.get_character_band("asuka"))
            self.assertEqual("ave_mujica", manager.get_character_band("mutsumi"))
            self.assertEqual("custom_models", manager.get_character_band("mutsumi1"))
            self.assertEqual(["mutsumi1"], manager.get_band_characters("custom_models"))

    def test_band_json_character_with_same_name_archive_is_not_custom(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            models.mkdir()

            self._write_dir_model(models, "mutsumi", "folder_costume")
            archive_path = models / "mutsumi.zst"
            archive_path.write_bytes(b"archive")
            archive_model_path = f"{archive_path.resolve()}::default/model.json"
            archive_result = {
                "character": "mutsumi",
                "costumes": [{"id": "default", "path": archive_model_path}],
                "image_path": "",
                "model_paths": [("mutsumi", "default", archive_model_path)],
            }
            band_json = root / "band.json"
            band_json.write_text(
                json.dumps({
                    "bands": [
                        {
                            "id": "ave_mujica",
                            "display": "Ave Mujica",
                            "characters": ["mutsumi"],
                        },
                    ]
                }),
                encoding="utf-8",
            )

            with (
                patch.object(model_manager, "MODELS_DIR", models),
                patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
                patch.object(model_manager, "BAND_JSON", band_json),
                patch.object(ModelManager, "_read_model_archive", return_value=archive_result),
            ):
                manager = ModelManager()

            self.assertEqual("ave_mujica", manager.get_character_band("mutsumi"))
            self.assertEqual([], manager.get_band_characters("custom_models"))


if __name__ == "__main__":
    unittest.main()
