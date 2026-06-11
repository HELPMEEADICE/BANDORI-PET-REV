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


class CustomModelImportTest(unittest.TestCase):
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

    def test_webgal_manifest_rejects_layer_paths_outside_source_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / custom_model_import.WEBGAL_COMPOSITE_FILENAME).write_text(
                json.dumps({"layers": [{"model": "../outside/model.json"}]}),
                encoding="utf-8",
            )

            with (
                patch.object(custom_model_import, "MODELS_DIR", root / "models"),
                self.assertRaises(CustomModelImportError) as raised,
            ):
                import_from_folder(str(source), "WebGal Character", "default")

            self.assertEqual("unsafe_resource_path", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
