"""Exercise the real Rust library, including binary/Unicode ABI round trips."""

import io
import json
import tarfile
from concurrent.futures import ThreadPoolExecutor

import pytest
import zstandard

from bandori_models import zst_model_archive as assets


def _virtual_path(archive, member):
    return f"{archive.resolve()}::{member}"


def write_archive(path, members, index=True):
    with path.open("wb") as output:
        with zstandard.ZstdCompressor().stream_writer(output) as encoder:
            with tarfile.open(fileobj=encoder, mode="w|") as archive:
                if index:
                    content = json.dumps({"files": list(members)}, ensure_ascii=False).encode("utf-8")
                    info = tarfile.TarInfo(assets.INDEX_MEMBER)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
                for name, content in members.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))


@pytest.fixture(autouse=True)
def empty_native_cache():
    assets.clear_virtual_byte_cache()
    yield
    assets.clear_virtual_byte_cache()


def test_batch_binary_unicode_and_missing(tmp_path):
    archive = tmp_path / "角色.zst"
    payload = bytes(range(256)) + b"\0\xff"
    write_archive(archive, {"服装/模型.moc3": payload, "character.png": b"avatar", "empty": b""})
    assert assets.list_archive_files(archive) == ["character.png", "empty", "服装/模型.moc3"]
    assert assets.load_archive_resources(archive, ["服装/模型.moc3", "empty", "absent"]) == {"服装/模型.moc3": payload, "empty": b""}
    virtual = _virtual_path(archive, "服装\\模型.moc3")
    assert assets.load_virtual_bytes(virtual) == payload
    assert assets.load_virtual_bytes(virtual, cache=False) == payload
    with pytest.raises(KeyError):
        assets.load_virtual_bytes(_virtual_path(archive, "absent"))


@pytest.mark.parametrize("index", [True, False])
def test_catalog_portrait_priority_and_manifest_format(tmp_path, index):
    archive = tmp_path / "角色.zst"
    write_archive(archive, {
        "character.jpg": b"jpg", "角色/character.png": b"nested png", "character.png": b"root png",
        "folder/live/model.json": b"not JSON: listing must not parse this",
        "live3/角色.model3.json": b"{}", "irrelevant.json": b"{}",
    }, index=index)
    result = assets.scan_model_archive(archive)
    assert result["character"] == "角色"
    assert [(item["id"], item["format"]) for item in result["costumes"]] == [("live", "moc"), ("live3", "moc3")]
    assert result["image_path"] == _virtual_path(archive, "character.png")
    assert result["model_paths"][0] == ("角色", "live", _virtual_path(archive, "folder/live/model.json"))


def test_archive_replacement_invalidates_listing_and_bytes(tmp_path):
    archive = tmp_path / "model.zst"
    write_archive(archive, {"model.json": b"old"})
    virtual = _virtual_path(archive, "model.json")
    assert assets.load_virtual_bytes(virtual) == b"old"
    assert assets.list_archive_files(archive) == ["model.json"]
    before = assets.virtual_resource_revision(virtual)
    write_archive(archive, {"model.json": b"new data", "extra": b"x"})
    assert assets.virtual_resource_revision(virtual) != before
    assert assets.load_virtual_bytes(virtual) == b"new data"
    assert assets.list_archive_files(archive) == ["extra", "model.json"]


@pytest.mark.parametrize("member", ["../x", "/x", "C:/x", "./C:/x", "\\\\server\\share", "x//y", "x/./y", "x/../y", "x:stream", "x\0y"])
def test_native_path_validation(tmp_path, member):
    with pytest.raises(ValueError):
        assets.load_virtual_bytes(_virtual_path(tmp_path / "missing.zst", member))
    with pytest.raises(ValueError):
        assets.load_archive_resources(tmp_path / "missing.zst", [member])


def test_invalid_tar_members_are_filtered(tmp_path):
    archive = tmp_path / "unsafe.zst"
    write_archive(archive, {"../outside": b"bad", "C:/outside": b"bad", "valid": b"good"}, index=False)
    assert assets.list_archive_files(archive) == ["valid"]
    assert assets.load_archive_resources(archive, ["valid"]) == {"valid": b"good"}


def test_parallel_requests_share_native_cache_safely(tmp_path):
    archive = tmp_path / "parallel.zst"
    write_archive(archive, {"data": bytes(range(256))})
    virtual = _virtual_path(archive, "data")
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(assets.load_virtual_bytes, [virtual] * 40))
    assert all(data == bytes(range(256)) for data in results)


def test_model_manager_parsed_json_cache_observes_archive_changes(tmp_path):
    pytest.importorskip("PySide6")
    from bandori_models.model_manager import ModelManager

    archive = tmp_path / "model.zst"
    write_archive(archive, {"live/model.json": b'{"motions":{"old":[]}}'})
    manager = ModelManager(discover_models=False)
    manager._model_paths[("model", "live")] = _virtual_path(archive, "live/model.json")
    assert manager.get_motion_names("model", "live") == ["old"]
    write_archive(archive, {"live/model.json": b'{"motions":{"new_action":[]}}'})
    assert manager.get_motion_names("model", "live") == ["new_action"]


def test_portrait_loading_prefetches_default_manifest_through_rust(tmp_path):
    pytest.importorskip("PySide6")
    from bandori_models.model_manager import ModelManager
    from unittest.mock import patch

    archive = tmp_path / "model.zst"
    write_archive(archive, {"character.png": b"avatar", "live_default/model.json": b'{"motions":{"idle":[]}}'})
    manager = ModelManager(discover_models=False)
    manager._apply_archive_scan_result(assets.scan_model_archive(archive))
    with patch("bandori_models.model_manager.prefetch_virtual_resources", wraps=assets.prefetch_virtual_resources) as prefetch:
        assert manager.get_character_image_data("model") == b"avatar"
    prefetch.assert_called_once_with([
        _virtual_path(archive, "character.png"),
        _virtual_path(archive, "live_default/model.json"),
    ])
    assert manager.get_motion_names("model", "live_default") == ["idle"]
