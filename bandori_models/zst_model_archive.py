"""Archive API for the UI; pet-assets owns validation, IO and caches."""

import json
from pathlib import Path

from bandori_models.native_assets import request as _request


VIRTUAL_SEP = "::"
INDEX_MEMBER = ".bandori_zst_index.json"


def is_virtual_path(path: str) -> bool:
    return VIRTUAL_SEP in str(path)


def load_virtual_bytes(path: str, cache: bool = True) -> bytes:
    resources = _request("read", path=str(path), cache=cache)
    if not resources:
        raise KeyError(path)
    return next(iter(resources.values()))


def load_archive_resources(archive_path: Path | str, members, cache: bool = True) -> dict[str, bytes]:
    """Read all missing members in one pass; absent members are omitted.

    A returned batch is limited to 64 MiB. Use prefetch for larger sets, whose
    retained bytes are bounded by the native LRU instead of a returned batch.
    """
    return _request("read_batch", archive=str(archive_path), members=list(members), cache=cache)


def prefetch_virtual_resources(paths):
    """Warm known UI resources, grouped by archive and read once per archive."""
    _request("prefetch_paths", paths=list(paths))


def load_virtual_json(path: str) -> dict:
    return json.loads(load_virtual_bytes(path).decode("utf-8"))


def clear_virtual_byte_cache():
    _request("clear")


def virtual_resource_revision(path: str) -> str:
    return _request("revision", path=str(path))


def list_archive_files(archive_path: Path | str) -> list[str]:
    return _request("list", archive=str(archive_path))


def scan_model_archive(archive_path: Path | str):
    result = _request("scan", archive=str(archive_path))
    if result is not None:
        result["model_paths"] = [tuple(item) for item in result["model_paths"]]
    return result
