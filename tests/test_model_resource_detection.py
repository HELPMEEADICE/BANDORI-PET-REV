import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import model_manager
from model_manager import ModelManager, models_dir_exists
from settings_window.pages.download_manager import discover_download_model_sources


def _write_model(costume_dir: Path, *, valid: bool = True):
    costume_dir.mkdir(parents=True, exist_ok=True)
    (costume_dir / "model.json").write_text(
        json.dumps({"model": "model.moc", "textures": ["texture.png"]}),
        encoding="utf-8",
    )
    if valid:
        (costume_dir / "model.moc").write_bytes(b"moc")
        (costume_dir / "texture.png").write_bytes(b"png")


def test_models_dir_exists_ignores_partial_empty_and_unrelated_entries():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "kasumi.zst.part").write_bytes(b"partial")
        (root / "empty").mkdir()
        (root / "note.txt").write_text("not a model", encoding="utf-8")

        with patch("model_manager.model_search_dirs", return_value=[root]):
            assert not models_dir_exists()


def test_invalid_model_folder_is_not_discovered_or_scanned():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        models = root / "models"
        _write_model(models / "invalid" / "default", valid=False)
        _write_model(models / "valid" / "default", valid=True)

        with (
            patch("model_manager.model_search_dirs", return_value=[models]),
            patch.object(model_manager, "MODELS_DIR", models),
            patch.object(model_manager, "OUTFIT_JSON", root / "missing-outfit.json"),
            patch.object(model_manager, "BAND_JSON", root / "missing-band.json"),
        ):
            manager = ModelManager()
            assert models_dir_exists()

        assert "invalid" not in manager.characters
        assert manager.get_model_json_path("invalid", "default") == ""
        assert "valid" in manager.characters
        assert set(discover_download_model_sources([models])) == {"valid"}


def test_missing_texture_does_not_count_as_model_resource():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        costume_dir = root / "models" / "kasumi" / "default"
        _write_model(costume_dir, valid=True)
        (costume_dir / "texture.png").unlink()

        with patch("model_manager.model_search_dirs", return_value=[root / "models"]):
            assert not models_dir_exists()
