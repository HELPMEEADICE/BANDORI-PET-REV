import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import custom_model_import
from custom_model_import import CustomModelImportError, import_from_folder


def _write_model(root: Path, model_path: str = "model.moc", texture_path: str = "textures/texture.png") -> None:
    (root / Path(model_path).parent).mkdir(parents=True, exist_ok=True)
    (root / model_path).write_bytes(b"moc")
    (root / Path(texture_path).parent).mkdir(parents=True, exist_ok=True)
    (root / texture_path).write_bytes(b"png")
    (root / "model.json").write_text(
        json.dumps({
            "model": model_path,
            "textures": [texture_path],
        }),
        encoding="utf-8",
    )


def _write_model3(root: Path) -> None:
    (root / "textures").mkdir(parents=True, exist_ok=True)
    (root / "textures" / "texture_00.png").write_bytes(b"png")
    (root / "motions").mkdir(parents=True, exist_ok=True)
    (root / "motions" / "mtn_smile01_C.motion3.json").write_text(
        '{"Version":3,"Meta":{"Duration":1,"Fps":30,"Loop":false,"AreBeziersRestricted":true,"CurveCount":0,"TotalSegmentCount":0,"TotalPointCount":0,"UserDataCount":0,"TotalUserDataSize":0},"Curves":[]}',
        encoding="utf-8",
    )
    (root / "expressions").mkdir(parents=True, exist_ok=True)
    (root / "expressions" / "exp_smile01.exp3.json").write_text(
        '{"Type":"Live2D Expression","Parameters":[]}',
        encoding="utf-8",
    )
    (root / "model.moc3").write_bytes(b"moc3")
    (root / "model.model3.json").write_text(
        json.dumps({
            "Version": 3,
            "FileReferences": {
                "Moc": "model.moc3",
                "Textures": ["textures/texture_00.png"],
                "Motions": {"mtn_smile01_C": [{"File": "motions/mtn_smile01_C.motion3.json"}]},
                "Expressions": [{"Name": "exp_smile01", "File": "expressions/exp_smile01.exp3.json"}],
            },
        }),
        encoding="utf-8",
    )


class CustomModelImportTest(unittest.TestCase):
    def test_import_rejects_display_name_containing_only_control_characters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            _write_model(source)

            with (
                patch.object(custom_model_import, "MODELS_DIR", root / "models"),
                self.assertRaises(CustomModelImportError) as raised,
            ):
                import_from_folder(str(source), "\0\n\t", "default")

            self.assertEqual("invalid_name", raised.exception.code)

    def test_import_strips_control_characters_from_costume_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            models = root / "models"
            source.mkdir()
            _write_model(source)

            with patch.object(custom_model_import, "MODELS_DIR", models):
                _character, costumes = import_from_folder(
                    str(source),
                    "Test Character",
                    "live\0_01",
                )

            self.assertEqual(["live_01"], costumes)
            self.assertTrue((models / "Test Character" / "live_01" / "model.json").is_file())

    def test_delete_removes_marked_character_inside_models_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            models = Path(temp_dir) / "models"
            character = models / "Custom Character"
            character.mkdir(parents=True)
            (character / custom_model_import.CUSTOM_MARKER_FILENAME).write_text(
                "{}",
                encoding="utf-8",
            )

            with patch.object(custom_model_import, "MODELS_DIR", models):
                custom_model_import.delete_custom_character("Custom Character")

            self.assertFalse(character.exists())

    def test_delete_rejects_character_outside_models_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            models = root / "models"
            outside = root / "outside"
            models.mkdir()
            outside.mkdir()
            (outside / custom_model_import.CUSTOM_MARKER_FILENAME).write_text(
                "{}",
                encoding="utf-8",
            )

            with (
                patch.object(custom_model_import, "MODELS_DIR", models),
                self.assertRaises(CustomModelImportError) as raised,
            ):
                custom_model_import.delete_custom_character("../outside")

            self.assertEqual("not_custom", raised.exception.code)
            self.assertTrue(outside.is_dir())

    def test_import_accepts_normal_relative_resources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            models = root / "models"
            source.mkdir()
            _write_model(source)

            with patch.object(custom_model_import, "MODELS_DIR", models):
                character, costumes = import_from_folder(str(source), "Test Character", "default")

            self.assertEqual("Test Character", character)
            self.assertEqual(["default"], costumes)
            self.assertTrue((models / "Test Character" / "default" / "model.json").is_file())
            self.assertTrue((models / "Test Character" / custom_model_import.CUSTOM_MARKER_FILENAME).is_file())

    def test_import_rejects_resource_paths_outside_model_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (root / "outside.png").write_bytes(b"png")
            _write_model(source, texture_path="../outside.png")

            with (
                patch.object(custom_model_import, "MODELS_DIR", root / "models"),
                self.assertRaises(CustomModelImportError) as raised,
            ):
                import_from_folder(str(source), "Unsafe Character", "default")

            self.assertEqual("unsafe_resource_path", raised.exception.code)

    def test_import_rejects_absolute_resource_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "model.moc").write_bytes(b"moc")
            (source / "model.json").write_text(
                json.dumps({
                    "model": "model.moc",
                    "textures": ["C:/outside/texture.png"],
                }),
                encoding="utf-8",
            )

            with (
                patch.object(custom_model_import, "MODELS_DIR", root / "models"),
                self.assertRaises(CustomModelImportError) as raised,
            ):
                import_from_folder(str(source), "Absolute Character", "default")

            self.assertEqual("unsafe_resource_path", raised.exception.code)

    def test_import_accepts_cubism3_model3_resources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            models = root / "models"
            source.mkdir()
            _write_model3(source)

            with patch.object(custom_model_import, "MODELS_DIR", models):
                character, costumes = import_from_folder(str(source), "Moc3 Character", "live_01")

            self.assertEqual("Moc3 Character", character)
            self.assertEqual(["live_01"], costumes)
            self.assertTrue((models / "Moc3 Character" / "live_01" / "model.model3.json").is_file())

if __name__ == "__main__":
    unittest.main()
