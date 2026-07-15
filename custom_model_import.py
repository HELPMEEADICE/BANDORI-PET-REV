"""Import / manage user-supplied Live2D models.

A custom model is stored exactly like a built-in one: copied into
``models/<character>/<costume>/`` containing a Cubism 2.1 ``model.json``
or Cubism 3 ``*.model3.json`` plus its resources, so the rest of the app (ModelManager scan, band
grouping, costume picker, click-motion config, pet process) reuses it
without any special casing.

A marker file ``_custom.json`` is written at the character-folder level so
imported models can be told apart from built-ins and deleted safely.

Both Cubism 2.1 (``model.json`` + ``.moc``) and Cubism 3
(``*.model3.json`` + ``.moc3``) are supported.
"""

import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PureWindowsPath

from model_manager import MODELS_DIR

CUSTOM_MARKER_FILENAME = "_custom.json"
MODEL_JSON_NAME = "model.json"
MODEL3_JSON_SUFFIX = ".model3.json"
_INVALID_NAME_CHARS = '<>:"/\\|?*'
_MAX_NAME_LENGTH = 64
_MAX_ZIP_MEMBERS = 10_000
_MAX_ZIP_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


class CustomModelImportError(Exception):
    """Raised when a custom model cannot be imported.

    The message is user-facing (already localized by the caller via a
    structured ``code``), so keep ``code`` machine-readable and pass any
    format args through ``params``.
    """

    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code = code
        self.params = params


def _is_safe_folder_name_char(character: str) -> bool:
    return (
        character not in _INVALID_NAME_CHARS
        and ord(character) >= 32
        and ord(character) != 127
    )


def sanitize_character_name(name: str) -> str:
    """Turn a user-entered display name into a safe folder name.

    The folder name doubles as the display name (matching how built-ins
    work), so we only strip what the filesystem or the scanner can't handle.
    ModelManager skips entries starting with ``_``, so those are stripped too.
    """
    cleaned = "".join(ch for ch in str(name or "") if _is_safe_folder_name_char(ch))
    cleaned = cleaned.strip().strip(".")
    while cleaned.startswith("_"):
        cleaned = cleaned[1:].lstrip()
    cleaned = cleaned[:_MAX_NAME_LENGTH].strip()
    return cleaned


def sanitize_costume_id(costume_id: str, fallback: str = "default") -> str:
    cleaned = "".join(ch for ch in str(costume_id or "") if _is_safe_folder_name_char(ch))
    cleaned = cleaned.strip().strip(".")
    while cleaned.startswith("_"):
        cleaned = cleaned[1:].lstrip()
    cleaned = cleaned[:_MAX_NAME_LENGTH].strip()
    return cleaned or fallback


def _custom_character_dir(character: str) -> Path | None:
    raw = str(character or "")
    if not raw or Path(raw).name != raw or PureWindowsPath(raw).name != raw:
        return None
    try:
        models_root = MODELS_DIR.resolve()
        target = (MODELS_DIR / raw).resolve()
    except (OSError, RuntimeError):
        return None
    return target if target.parent == models_root else None


def is_custom_character(character: str) -> bool:
    target = _custom_character_dir(character)
    return bool(target and (target / CUSTOM_MARKER_FILENAME).is_file())


def delete_custom_character(character: str) -> None:
    """Delete an imported custom character. Refuses to touch built-ins."""
    target = _custom_character_dir(character)
    if target is None or not (target / CUSTOM_MARKER_FILENAME).is_file():
        raise CustomModelImportError("not_custom")
    shutil.rmtree(target)


def _is_model_json(json_path: Path) -> bool:
    """检查 JSON 文件是否是 Live2D 模型配置文件"""
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return _is_cubism2_model_data(data) or _is_cubism3_model_data(data)
    except (json.JSONDecodeError, OSError):
        return False


def _is_cubism2_model_data(data: dict) -> bool:
    return isinstance(data, dict) and isinstance(data.get("model"), str)


def _is_cubism3_model_data(data: dict) -> bool:
    if not isinstance(data, dict):
        return False
    refs = data.get("FileReferences")
    return isinstance(refs, dict) and isinstance(refs.get("Moc"), str)


def _find_model_jsons(root: Path) -> list[Path]:
    """查找所有可能的 Live2D 模型配置文件

    支持：
    - model.json（标准名称）
    - *.model.json（变体文件）
    - *.model3.json（Cubism 3）
    - 其他包含 model 字段的 JSON 文件
    """
    result = []
    seen = set()

    # 递归查找所有 JSON 文件
    for json_path in root.rglob("*.json"):
        if not json_path.is_file():
            continue

        # 跳过已知的非模型配置文件
        if json_path.name in ("_custom.json", "outfit.json", "band.json", "config.json"):
            continue

        # 标准 model.json 文件
        if json_path.name.lower() == MODEL_JSON_NAME:
            if json_path not in seen:
                result.append(json_path)
                seen.add(json_path)
            continue

        # *.model.json / *.model3.json 变体文件
        if json_path.name.endswith(".model.json") or json_path.name.endswith(MODEL3_JSON_SUFFIX):
            if json_path not in seen:
                result.append(json_path)
                seen.add(json_path)
            continue

        # 其他 JSON 文件：检查是否是模型配置文件
        if _is_model_json(json_path):
            if json_path not in seen:
                result.append(json_path)
                seen.add(json_path)

    return sorted(result)


def _resolve_relative_resource(base_dir: Path, resource: str) -> Path:
    raw = str(resource or "").strip()
    normalized = raw.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or PureWindowsPath(raw).is_absolute()
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise CustomModelImportError("unsafe_resource_path", resource=raw)
    base = base_dir.resolve()
    target = (base / Path(*normalized.split("/"))).resolve()
    if base != target and base not in target.parents:
        raise CustomModelImportError("unsafe_resource_path", resource=raw)
    return target


def _require_model_resource(model_dir: Path, resource: str) -> Path:
    target = _resolve_relative_resource(model_dir, resource)
    if not target.is_file():
        raise CustomModelImportError("missing_resource", resource=str(resource))
    return target


def _validate_model_manifest(model_json: Path) -> None:
    """Validate a single Live2D manifest describes a loadable model."""
    try:
        data = json.loads(model_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CustomModelImportError("bad_model_json", detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise CustomModelImportError("bad_model_json", detail="not an object")

    if _is_cubism3_model_data(data):
        _validate_cubism3_model(model_json, data)
    else:
        _validate_cubism2_model(model_json, data)


def _validate_cubism2_model(model_json: Path, data: dict) -> None:
    """Validate a single model.json describes a loadable Cubism 2.1 model."""

    moc = data.get("model")
    if not moc or not isinstance(moc, str):
        raise CustomModelImportError("missing_moc")
    _require_model_resource(model_json.parent, moc)

    textures = data.get("textures", [])
    if not isinstance(textures, list) or not textures:
        raise CustomModelImportError("missing_textures")
    for texture in textures:
        if not isinstance(texture, str):
            raise CustomModelImportError("missing_resource", resource=str(texture))
        _require_model_resource(model_json.parent, texture)


def _validate_cubism3_model(model_json: Path, data: dict) -> None:
    refs = data.get("FileReferences", {})
    moc = refs.get("Moc")
    if not moc or not isinstance(moc, str):
        raise CustomModelImportError("missing_moc")
    _require_model_resource(model_json.parent, moc)

    textures = refs.get("Textures", [])
    if not isinstance(textures, list) or not textures:
        raise CustomModelImportError("missing_textures")
    for texture in textures:
        if not isinstance(texture, str):
            raise CustomModelImportError("missing_resource", resource=str(texture))
        _require_model_resource(model_json.parent, texture)

    for resource in _cubism3_optional_resources(refs):
        _require_model_resource(model_json.parent, resource)


def _cubism3_optional_resources(refs: dict) -> list[str]:
    resources: list[str] = []
    for key in ("Physics", "Pose", "DisplayInfo"):
        value = refs.get(key)
        if isinstance(value, str) and value.strip():
            resources.append(value)
    motions = refs.get("Motions", {})
    if isinstance(motions, dict):
        for group in motions.values():
            if not isinstance(group, list):
                continue
            for item in group:
                if isinstance(item, dict) and isinstance(item.get("File"), str):
                    resources.append(item["File"])
    expressions = refs.get("Expressions", [])
    if isinstance(expressions, list):
        for item in expressions:
            if isinstance(item, dict) and isinstance(item.get("File"), str):
                resources.append(item["File"])
    return resources


def _resolve_costumes(source_root: Path, costume_id: str) -> list[tuple[str, Path, Path]]:
    """Map a source tree to a list of (costume_id, costume_dir, model_json_path) to copy.

    One model.json -> a single costume using the user-supplied id.
    Multiple model.json -> one costume per containing folder (ids derived
    from folder names), since the user only names a single costume.
    """
    model_jsons = _find_model_jsons(source_root)
    if not model_jsons:
        raise CustomModelImportError("no_model_json")

    costumes: list[tuple[str, Path, Path]] = []
    if len(model_jsons) == 1:
        model_json = model_jsons[0]
        parent = model_json.parent
        fallback = parent.name if parent != source_root else "default"
        costumes.append((sanitize_costume_id(costume_id, fallback), parent, model_json))
    else:
        used: set[str] = set()
        for model_json in model_jsons:
            parent = model_json.parent
            base = sanitize_costume_id(parent.name, "costume")
            cid = base
            index = 2
            while cid in used:
                cid = f"{base}_{index}"
                index += 1
            used.add(cid)
            costumes.append((cid, parent, model_json))

    for _cid, _costume_dir, model_json_path in costumes:
        _validate_model_manifest(model_json_path)
    return costumes


def _write_marker(character_dir: Path, source_label: str) -> None:
    marker = {
        "custom": True,
        "imported_at": int(time.time()),
        "source": source_label,
    }
    (character_dir / CUSTOM_MARKER_FILENAME).write_text(
        json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _import_from_dir(source_root: Path, display_name: str, costume_id: str,
                     source_label: str) -> tuple[str, list[str]]:
    character = sanitize_character_name(display_name)
    if not character:
        raise CustomModelImportError("invalid_name")

    target_dir = MODELS_DIR / character
    if target_dir.exists():
        raise CustomModelImportError("name_exists", name=character)

    costumes = _resolve_costumes(source_root, costume_id)

    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=False)
        for cid, costume_dir, _model_json_path in costumes:
            shutil.copytree(costume_dir, target_dir / cid)
        _write_marker(target_dir, source_label)
    except CustomModelImportError:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except (OSError, shutil.Error) as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise CustomModelImportError("copy_failed", detail=str(exc)) from exc

    return character, [cid for cid, _dir, _model_json in costumes]


def import_from_folder(folder: str, display_name: str,
                       costume_id: str = "default") -> tuple[str, list[str]]:
    """Import a custom model from a folder. Returns (character, [costume_ids])."""
    source_root = Path(folder)
    if not source_root.is_dir():
        raise CustomModelImportError("source_missing")
    return _import_from_dir(source_root, display_name, costume_id, source_root.name)


def import_from_zip(zip_path: str, display_name: str,
                    costume_id: str = "default") -> tuple[str, list[str]]:
    """Import a custom model from a .zip archive. Returns (character, [costume_ids])."""
    archive = Path(zip_path)
    if not archive.is_file():
        raise CustomModelImportError("source_missing")
    try:
        is_zip = zipfile.is_zipfile(archive)
    except OSError as exc:
        raise CustomModelImportError("bad_zip", detail=str(exc)) from exc
    if not is_zip:
        raise CustomModelImportError("bad_zip")

    with tempfile.TemporaryDirectory(prefix="bandori_custom_model_") as tmp:
        tmp_root = Path(tmp)
        try:
            with zipfile.ZipFile(archive) as zf:
                _safe_extract_zip(zf, tmp_root)
        except (
            zipfile.BadZipFile,
            zipfile.LargeZipFile,
            OSError,
            RuntimeError,
            NotImplementedError,
        ) as exc:
            raise CustomModelImportError("bad_zip", detail=str(exc)) from exc
        return _import_from_dir(tmp_root, display_name, costume_id, archive.name)


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip, rejecting unsafe paths and resource usage."""
    members = zf.infolist()
    if len(members) > _MAX_ZIP_MEMBERS:
        raise CustomModelImportError("bad_zip", detail="too many files in archive")
    unpacked_size = sum(
        max(0, int(member.file_size))
        for member in members
        if not member.is_dir()
    )
    if unpacked_size > _MAX_ZIP_UNCOMPRESSED_BYTES:
        raise CustomModelImportError("bad_zip", detail="archive is too large when extracted")
    dest = dest.resolve()
    for member in members:
        target = (dest / member.filename).resolve()
        if dest != target and dest not in target.parents:
            raise CustomModelImportError("bad_zip", detail="unsafe path in archive")
    zf.extractall(dest)
