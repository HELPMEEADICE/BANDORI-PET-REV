import tempfile
from pathlib import Path
from unittest.mock import patch

from model_manager import ARCHIVE_SCAN_CACHE_NAME, ModelManager, VIRTUAL_SEP


def _archive_result(path: Path) -> dict:
    resolved = str(path.resolve())
    model_path = f"{resolved}{VIRTUAL_SEP}live_default/model.json"
    return {
        "character": path.stem,
        "costumes": [{"id": "live_default", "path": model_path, "format": "moc"}],
        "image_path": "",
        "model_paths": [(path.stem, "live_default", model_path)],
    }


def test_archive_scan_cache_is_reused_and_invalidated_by_file_changes():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "kasumi.zst"
        archive.write_bytes(b"first")
        result = _archive_result(archive)

        with (
            patch("model_manager.model_search_dirs", return_value=[root]),
            patch.object(ModelManager, "_read_model_archive", return_value=result) as read_archive,
        ):
            first = ModelManager()
            assert first.get_model_json_path("kasumi", "live_default")
            assert read_archive.call_count == 1

        assert (root / ARCHIVE_SCAN_CACHE_NAME).is_file()

        with (
            patch("model_manager.model_search_dirs", return_value=[root]),
            patch.object(ModelManager, "_read_model_archive", side_effect=AssertionError("cache miss")),
        ):
            cached = ModelManager()
            assert cached.get_model_json_path("kasumi", "live_default")

        archive.write_bytes(b"changed-size")
        with (
            patch("model_manager.model_search_dirs", return_value=[root]),
            patch.object(ModelManager, "_read_model_archive", return_value=result) as read_archive,
        ):
            ModelManager()
            assert read_archive.call_count == 1


def test_lightweight_model_scan_reuses_archive_cache_for_character_images():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        archive = root / "kasumi.zst"
        archive.write_bytes(b"archive")
        result = _archive_result(archive)
        result["image_path"] = f"{archive.resolve()}{VIRTUAL_SEP}character.png"

        with (
            patch("model_manager.model_search_dirs", return_value=[root]),
            patch.object(ModelManager, "_read_model_archive", return_value=result),
        ):
            ModelManager()

        with (
            patch("model_manager.model_search_dirs", return_value=[root]),
            patch("model_manager.list_archive_files", side_effect=AssertionError("archive was reopened")),
        ):
            manager = ModelManager(scan_models=False)

        assert "kasumi" in manager.characters
        with patch("model_manager.load_virtual_bytes", return_value=b"avatar"):
            assert manager.get_character_image_data("kasumi") == b"avatar"
