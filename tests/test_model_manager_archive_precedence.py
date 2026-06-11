import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import model_manager
from model_manager import ModelManager


class ModelManagerArchivePrecedenceTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
