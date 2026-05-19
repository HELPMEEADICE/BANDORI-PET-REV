import json
import posixpath
import tarfile
import threading
from contextlib import contextmanager
from pathlib import Path


VIRTUAL_SEP = "::"
INDEX_MEMBER = ".bandori_zst_index.json"
_VIRTUAL_BYTE_CACHE: dict[str, bytes] = {}
_CACHE_LOCK = threading.RLock()


def is_virtual_path(path: str) -> bool:
    return VIRTUAL_SEP in str(path)


def make_virtual_path(archive_path: Path | str, member_path: str) -> str:
    return f"{Path(archive_path).resolve()}{VIRTUAL_SEP}{_normalize_member(member_path)}"


def split_virtual_path(path: str) -> tuple[str, str]:
    archive_path, member_path = str(path).split(VIRTUAL_SEP, 1)
    return archive_path, _normalize_member(member_path)


def load_virtual_bytes(path: str, cache: bool = True) -> bytes:
    archive_path, member_path = split_virtual_path(path)
    cache_key = make_virtual_path(archive_path, member_path)
    if cache:
        with _CACHE_LOCK:
            cached = _VIRTUAL_BYTE_CACHE.get(cache_key)
        if cached is not None:
            return cached

    with _open_tar_zst(archive_path) as archive:
        for member in archive:
            if not member.isfile() or _normalize_member(member.name) != member_path:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                break
            data = extracted.read()
            if cache:
                with _CACHE_LOCK:
                    _VIRTUAL_BYTE_CACHE[cache_key] = data
            return data
    raise KeyError(path)


def read_virtual_text(path: str, encoding: str = "utf-8") -> str:
    return load_virtual_bytes(path).decode(encoding)


def load_virtual_json(path: str) -> dict:
    return json.loads(read_virtual_text(path))


def clear_virtual_byte_cache():
    with _CACHE_LOCK:
        _VIRTUAL_BYTE_CACHE.clear()


def prefetch_virtual_model_resources(model_json_path: str, include_deferred_expressions: bool = False):
    if not is_virtual_path(model_json_path):
        return

    archive_path, model_member = split_virtual_path(model_json_path)
    model_cache_key = make_virtual_path(archive_path, model_member)
    model_bytes = load_virtual_bytes(model_cache_key)
    try:
        model_json = json.loads(model_bytes.decode("utf-8"))
    except Exception:
        return

    target_members = _model_resource_members(
        model_member,
        model_json,
        include_expressions=include_deferred_expressions,
    )
    if not target_members:
        return

    with _CACHE_LOCK:
        target_members = {
            member
            for member in target_members
            if make_virtual_path(archive_path, member) not in _VIRTUAL_BYTE_CACHE
        }
    if not target_members:
        return

    with _open_tar_zst(archive_path) as archive:
        for member in archive:
            member_name = _normalize_member(member.name)
            if not member.isfile() or member_name not in target_members:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            with _CACHE_LOCK:
                _VIRTUAL_BYTE_CACHE[make_virtual_path(archive_path, member_name)] = data
            target_members.remove(member_name)
            if not target_members:
                break


def _model_resource_members(model_member: str, model_json: dict, include_expressions: bool = False) -> set[str]:
    base_dir = posixpath.dirname(model_member)
    members = set()

    def add(path):
        if isinstance(path, str) and path:
            members.add(_join_member(base_dir, path))

    add(model_json.get("model"))
    # Textures are large and are decoded directly into GL upload buffers; keeping
    # their compressed bytes in the virtual cache doubles peak resident memory.
    add(model_json.get("physics"))
    add(model_json.get("pose"))

    expressions = model_json.get("expressions", []) or []
    if include_expressions and isinstance(expressions, list):
        for expression in expressions:
            if isinstance(expression, dict):
                add(expression.get("file"))

    return members


def _join_member(base_dir: str, path: str) -> str:
    normalized = str(path).replace("\\", "/")
    if not normalized.startswith("/") and base_dir:
        normalized = posixpath.join(base_dir, normalized)
    return _normalize_member(normalized)


def list_archive_files(archive_path: Path | str) -> list[str]:
    files = []
    with _open_tar_zst(str(Path(archive_path).resolve())) as archive:
        members = iter(archive)
        first = next(members, None)
        if first is not None:
            first_name = _normalize_member(first.name)
            if first.isfile() and first_name == INDEX_MEMBER:
                extracted = archive.extractfile(first)
                if extracted is not None:
                    data = json.loads(extracted.read().decode("utf-8"))
                    indexed_files = data.get("files", [])
                    if isinstance(indexed_files, list):
                        return sorted(str(path) for path in indexed_files)
            elif first.isfile():
                files.append(first_name)
        for member in members:
            if member.isfile():
                files.append(_normalize_member(member.name))
    return sorted(files)


@contextmanager
def _open_tar_zst(archive_path: str):
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError("Reading .zst models requires zstandard: pip install zstandard") from exc

    with Path(archive_path).open("rb") as raw_file:
        with zstd.ZstdDecompressor().stream_reader(raw_file) as reader:
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                yield archive


def _normalize_member(path: str) -> str:
    normalized = str(path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = posixpath.normpath(normalized.lstrip("/"))
    return "" if normalized == "." else normalized
