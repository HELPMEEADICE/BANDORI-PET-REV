import json
import posixpath
import tarfile
import threading
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path


VIRTUAL_SEP = "::"
INDEX_MEMBER = ".bandori_zst_index.json"
_VIRTUAL_BYTE_CACHE_MAX_ITEMS = 128
_VIRTUAL_BYTE_CACHE_MAX_BYTES = 64 * 1024 * 1024
_VIRTUAL_MEMBER_MAX_BYTES = 64 * 1024 * 1024
_INDEX_MEMBER_MAX_BYTES = 4 * 1024 * 1024
_VIRTUAL_BYTE_CACHE: OrderedDict[str, bytes] = OrderedDict()
_VIRTUAL_BYTE_CACHE_BYTES = 0
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
                _VIRTUAL_BYTE_CACHE.move_to_end(cache_key)
        if cached is not None:
            return cached

    with _open_tar_zst(archive_path) as archive:
        for member in archive:
            try:
                member_name = _normalize_member(member.name)
            except ValueError:
                continue
            if not member.isfile() or member_name != member_path:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                break
            data = _read_member_bytes(extracted, member)
            if cache:
                with _CACHE_LOCK:
                    _store_virtual_bytes(cache_key, data)
            return data
    raise KeyError(path)


def read_virtual_text(path: str, encoding: str = "utf-8") -> str:
    return load_virtual_bytes(path).decode(encoding)


def load_virtual_json(path: str) -> dict:
    return json.loads(read_virtual_text(path))


def clear_virtual_byte_cache():
    global _VIRTUAL_BYTE_CACHE_BYTES
    with _CACHE_LOCK:
        _VIRTUAL_BYTE_CACHE.clear()
        _VIRTUAL_BYTE_CACHE_BYTES = 0


def _store_virtual_bytes(cache_key: str, data: bytes, enforce_limits: bool = True):
    global _VIRTUAL_BYTE_CACHE_BYTES
    old = _VIRTUAL_BYTE_CACHE.pop(cache_key, None)
    if old is not None:
        _VIRTUAL_BYTE_CACHE_BYTES -= len(old)
    _VIRTUAL_BYTE_CACHE[cache_key] = data
    _VIRTUAL_BYTE_CACHE_BYTES += len(data)
    if enforce_limits:
        while (
            len(_VIRTUAL_BYTE_CACHE) > _VIRTUAL_BYTE_CACHE_MAX_ITEMS
            or _VIRTUAL_BYTE_CACHE_BYTES > _VIRTUAL_BYTE_CACHE_MAX_BYTES
        ):
            _, evicted = _VIRTUAL_BYTE_CACHE.popitem(last=False)
            _VIRTUAL_BYTE_CACHE_BYTES -= len(evicted)


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
            try:
                member_name = _normalize_member(member.name)
            except ValueError:
                continue
            if not member.isfile() or member_name not in target_members:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = _read_member_bytes(extracted, member)
            with _CACHE_LOCK:
                _store_virtual_bytes(
                    make_virtual_path(archive_path, member_name),
                    data,
                    enforce_limits=False,
                )
            target_members.remove(member_name)
            if not target_members:
                break


def prefetch_virtual_action_resources(
    model_json_path: str,
    motion_groups: list[str] | tuple[str, ...] | None = None,
    expression_names: list[str] | tuple[str, ...] | None = None,
):
    if not is_virtual_path(model_json_path):
        return

    archive_path, model_member = split_virtual_path(model_json_path)
    model_bytes = load_virtual_bytes(make_virtual_path(archive_path, model_member))
    try:
        model_json = json.loads(model_bytes.decode("utf-8"))
    except Exception:
        return

    target_members = _action_resource_members(
        model_member,
        model_json,
        motion_groups or (),
        expression_names or (),
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
            try:
                member_name = _normalize_member(member.name)
            except ValueError:
                continue
            if not member.isfile() or member_name not in target_members:
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = _read_member_bytes(extracted, member)
            with _CACHE_LOCK:
                _store_virtual_bytes(make_virtual_path(archive_path, member_name), data)
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
    textures = model_json.get("textures", []) or []
    if isinstance(textures, list):
        for texture in textures:
            add(texture)

    add(model_json.get("physics"))
    add(model_json.get("pose"))

    expressions = model_json.get("expressions", []) or []
    if include_expressions and isinstance(expressions, list):
        for expression in expressions:
            if isinstance(expression, dict):
                add(expression.get("file"))

    return members


def _action_resource_members(
    model_member: str,
    model_json: dict,
    motion_groups: list[str] | tuple[str, ...],
    expression_names: list[str] | tuple[str, ...],
) -> set[str]:
    base_dir = posixpath.dirname(model_member)
    members = set()

    def add(path):
        if isinstance(path, str) and path:
            members.add(_join_member(base_dir, path))

    wanted_motions = {str(name) for name in motion_groups if name}
    motions = model_json.get("motions") or {}
    if isinstance(motions, dict):
        for group_name in wanted_motions:
            group = motions.get(group_name) or []
            if not isinstance(group, list):
                continue
            for item in group:
                if isinstance(item, dict):
                    add(item.get("file"))

    wanted_expressions = {str(name) for name in expression_names if name}
    expressions = model_json.get("expressions") or []
    if isinstance(expressions, list):
        for item in expressions:
            if isinstance(item, dict) and str(item.get("name", "")) in wanted_expressions:
                add(item.get("file"))

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
            try:
                first_name = _normalize_member(first.name)
            except ValueError:
                first_name = ""
            if first.isfile() and first_name == INDEX_MEMBER:
                extracted = archive.extractfile(first)
                if extracted is not None:
                    data = json.loads(_read_member_bytes(extracted, first, _INDEX_MEMBER_MAX_BYTES).decode("utf-8"))
                    indexed_files = data.get("files", [])
                    if isinstance(indexed_files, list):
                        files = []
                        for path in indexed_files:
                            try:
                                files.append(_normalize_member(path))
                            except ValueError:
                                continue
                        return sorted(files)
            elif first.isfile() and first_name:
                files.append(first_name)
        for member in members:
            if member.isfile():
                try:
                    files.append(_normalize_member(member.name))
                except ValueError:
                    continue
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
    if not normalized or normalized.startswith("/"):
        raise ValueError(f"Unsafe archive member path: {path}")
    raw_parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError(f"Unsafe archive member path: {path}")
    normalized = posixpath.normpath(normalized.lstrip("/"))
    if normalized == "." or normalized.startswith("../") or normalized == "..":
        raise ValueError(f"Unsafe archive member path: {path}")
    return normalized


def _read_member_bytes(extracted, member, max_bytes: int = _VIRTUAL_MEMBER_MAX_BYTES) -> bytes:
    size = getattr(member, "size", None)
    if size is not None and size > max_bytes:
        raise ValueError(f"Archive member too large: {member.name}")
    data = extracted.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Archive member too large: {member.name}")
    return data
