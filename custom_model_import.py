"""Import / manage user-supplied Live2D models.

A custom model is copied into ``models/<character>/<costume>/``. Standard
Cubism 2.1 imports contain a ``model.json`` plus resources; WebGal-style
multi-part folder imports contain a ``_webgal_composite.json`` manifest
that points to multiple Cubism 2.1 layer ``model.json`` files.

A marker file ``_custom.json`` is written at the character-folder level so
imported models can be told apart from built-ins and deleted safely.

Only Cubism 2.1 (``model.json`` + ``.moc``) is supported; the bundled Lua
renderer cannot load Cubism 3/4 (``.model3.json`` / ``.moc3``).
"""

import json
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PureWindowsPath

from model_manager import MODELS_DIR, WEBGAL_COMPOSITE_FILENAME, ModelManager

CUSTOM_MARKER_FILENAME = "_custom.json"
MODEL_JSON_NAME = "model.json"
_INVALID_NAME_CHARS = '<>:"/\\|?*'
_MAX_NAME_LENGTH = 64


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


def sanitize_character_name(name: str) -> str:
    """Turn a user-entered display name into a safe folder name.

    The folder name doubles as the display name (matching how built-ins
    work), so we only strip what the filesystem or the scanner can't handle.
    ModelManager skips entries starting with ``_``, so those are stripped too.
    """
    cleaned = "".join(ch for ch in str(name or "") if ch not in _INVALID_NAME_CHARS)
    cleaned = cleaned.strip().strip(".")
    while cleaned.startswith("_"):
        cleaned = cleaned[1:].lstrip()
    cleaned = cleaned[:_MAX_NAME_LENGTH].strip()
    return cleaned


def sanitize_costume_id(costume_id: str, fallback: str = "default") -> str:
    cleaned = "".join(ch for ch in str(costume_id or "") if ch not in _INVALID_NAME_CHARS)
    cleaned = cleaned.strip().strip(".")
    while cleaned.startswith("_"):
        cleaned = cleaned[1:].lstrip()
    cleaned = cleaned[:_MAX_NAME_LENGTH].strip()
    return cleaned or fallback


def is_custom_character(character: str) -> bool:
    return (MODELS_DIR / character / CUSTOM_MARKER_FILENAME).is_file()


def delete_custom_character(character: str) -> None:
    """Delete an imported custom character. Refuses to touch built-ins."""
    target = MODELS_DIR / character
    if not is_custom_character(character):
        raise CustomModelImportError("not_custom")
    shutil.rmtree(target)


def _is_model_json(json_path: Path) -> bool:
    """Return True when a JSON file is a Cubism 2 model config."""
    return ModelManager._json_has_model_field(json_path)


def _find_model_jsons(root: Path) -> list[Path]:
    """Find Cubism 2 model configs, including non-standard JSON names."""
    return ModelManager._find_model_jsons(root)


def _has_cubism3_artifacts(root: Path) -> bool:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if lower.endswith(".model3.json") or lower.endswith(".moc3"):
            return True
    return False


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


def _validate_cubism2_model(model_json: Path) -> None:
    """Validate a single model.json describes a loadable Cubism 2.1 model."""
    try:
        data = json.loads(model_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CustomModelImportError("bad_model_json", detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise CustomModelImportError("bad_model_json", detail="not an object")

    # Cubism 3/4 manifests use these shapes even if named model.json.
    if "FileReferences" in data or str(data.get("Version", "")).startswith("3"):
        raise CustomModelImportError("cubism3_unsupported")

    moc = data.get("model")
    if not moc or not isinstance(moc, str):
        raise CustomModelImportError("missing_moc")
    if moc.lower().endswith(".moc3"):
        raise CustomModelImportError("cubism3_unsupported")
    _require_model_resource(model_json.parent, moc)

    textures = data.get("textures", [])
    if not isinstance(textures, list) or not textures:
        raise CustomModelImportError("missing_textures")
    for texture in textures:
        if not isinstance(texture, str):
            raise CustomModelImportError("missing_resource", resource=str(texture))
        _require_model_resource(model_json.parent, texture)


def _sort_webgal_layers(model_jsons: list[Path], source_root: Path) -> list[Path]:
    jsonl_order = ModelManager._webgal_jsonl_order(source_root)
    return sorted(
        model_jsons,
        key=lambda path: ModelManager._webgal_layer_sort_key(source_root, path, jsonl_order),
    )


def _write_webgal_composite_manifest(costume_dir: Path, layers: list[tuple[Path, Path]]) -> None:
    manifest = {
        "format": "bandori_webgal_composite",
        "version": 1,
        "layers": [
            {
                "name": source_parent.name,
                "model": model_json.relative_to(costume_dir).as_posix(),
            }
            for source_parent, model_json in layers
        ],
    }
    (costume_dir / WEBGAL_COMPOSITE_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_existing_composite_layers(source_root: Path, manifest_path: Path) -> list[Path]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    layers = manifest.get("layers", [])
    if not isinstance(layers, list):
        return []
    result = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        relative = str(layer.get("model", "") or "").strip()
        if not relative:
            continue
        model_json = _resolve_relative_resource(source_root, relative)
        if model_json.is_file() and _is_model_json(model_json):
            result.append(model_json)
    return result


def _direct_webgal_layers(source_root: Path) -> list[Path]:
    if ModelManager._find_root_model_json(source_root):
        return []
    model_jsons = ModelManager._find_direct_webgal_model_jsons(source_root)
    if len(model_jsons) < 2:
        return []
    return _sort_webgal_layers(model_jsons, source_root)


def _resolve_source_costume(source_root: Path, costume_id: str) -> dict | None:
    root_model_json = ModelManager._find_root_model_json(source_root)
    if root_model_json:
        return {
            "id": sanitize_costume_id(costume_id, source_root.name or "default"),
            "source_dir": source_root,
            "model_json": root_model_json,
            "composite": False,
        }

    composite_manifest = source_root / WEBGAL_COMPOSITE_FILENAME
    layers = _direct_webgal_layers(source_root)
    if composite_manifest.is_file() or layers:
        if not layers:
            layers = _read_existing_composite_layers(source_root, composite_manifest)
        if not layers:
            return None
        return {
            "id": sanitize_costume_id(costume_id, source_root.name or "webgal"),
            "source_dir": source_root,
            "layers": layers,
            "composite": True,
        }

    model_jsons = _find_model_jsons(source_root)
    if len(model_jsons) == 1:
        model_json = model_jsons[0]
        return {
            "id": sanitize_costume_id(costume_id, source_root.name or "default"),
            "source_dir": model_json.parent,
            "model_json": model_json,
            "composite": False,
        }
    return None


def _resolve_costumes(source_root: Path, costume_id: str, allow_webgal_composite: bool = True) -> list[dict]:
    """Map a source tree to a list of (costume_id, costume_dir, model_json_path) to copy.

    One model.json -> a single costume using the user-supplied id.
    WebGal folders can import as one composite costume, or as a multi-costume
    package when each direct child is itself a composite costume.
    """
    if allow_webgal_composite:
        direct_costume = _resolve_source_costume(source_root, costume_id)
        if direct_costume:
            costumes = [direct_costume]
        else:
            costumes = []
            used: set[str] = set()
            for child in sorted(source_root.iterdir()):
                if not child.is_dir() or child.name.startswith("_") or child.name == "_mtn_emp":
                    continue
                costume = _resolve_source_costume(child, child.name)
                if not costume:
                    continue
                base = sanitize_costume_id(child.name, "costume")
                cid = base
                index = 2
                while cid in used:
                    cid = f"{base}_{index}"
                    index += 1
                used.add(cid)
                costume["id"] = cid
                costumes.append(costume)
        if costumes:
            for costume in costumes:
                if costume.get("composite"):
                    for model_json_path in costume["layers"]:
                        _validate_cubism2_model(model_json_path)
                else:
                    _validate_cubism2_model(costume["model_json"])
            return costumes

    model_jsons = _find_model_jsons(source_root)
    if not model_jsons:
        if _has_cubism3_artifacts(source_root):
            raise CustomModelImportError("cubism3_unsupported")
        raise CustomModelImportError("no_model_json")

    costumes: list[dict] = []
    if allow_webgal_composite and len(model_jsons) > 1:
        layers = _sort_webgal_layers(model_jsons, source_root)
        costumes.append({
            "id": sanitize_costume_id(costume_id, source_root.name or "webgal"),
            "source_dir": source_root,
            "layers": layers,
            "composite": True,
        })
    elif len(model_jsons) == 1:
        model_json = model_jsons[0]
        parent = model_json.parent
        fallback = parent.name if parent != source_root else "default"
        costumes.append({
            "id": sanitize_costume_id(costume_id, fallback),
            "source_dir": parent,
            "model_json": model_json,
            "composite": False,
        })
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
            costumes.append({
                "id": cid,
                "source_dir": parent,
                "model_json": model_json,
                "composite": False,
            })

    for costume in costumes:
        if costume.get("composite"):
            for model_json_path in costume["layers"]:
                _validate_cubism2_model(model_json_path)
        else:
            _validate_cubism2_model(costume["model_json"])
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


def _import_from_dir(
    source_root: Path,
    display_name: str,
    costume_id: str,
    source_label: str,
    allow_webgal_composite: bool = True,
) -> tuple[str, list[str]]:
    character = sanitize_character_name(display_name)
    if not character:
        raise CustomModelImportError("invalid_name")

    target_dir = MODELS_DIR / character
    if target_dir.exists():
        raise CustomModelImportError("name_exists", name=character)

    costumes = _resolve_costumes(source_root, costume_id, allow_webgal_composite)

    try:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=False)
        for costume in costumes:
            cid = costume["id"]
            destination = target_dir / cid
            if costume.get("composite"):
                shutil.copytree(costume["source_dir"], destination)
                layers = [
                    (
                        model_json.parent,
                        destination / model_json.relative_to(costume["source_dir"]),
                    )
                    for model_json in costume["layers"]
                ]
                _write_webgal_composite_manifest(destination, layers)
            else:
                shutil.copytree(costume["source_dir"], destination)
        _write_marker(target_dir, source_label)
    except CustomModelImportError:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except (OSError, shutil.Error) as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise CustomModelImportError("copy_failed", detail=str(exc)) from exc

    return character, [costume["id"] for costume in costumes]


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
    if not zipfile.is_zipfile(archive):
        raise CustomModelImportError("bad_zip")

    with tempfile.TemporaryDirectory(prefix="bandori_custom_model_") as tmp:
        tmp_root = Path(tmp)
        try:
            with zipfile.ZipFile(archive) as zf:
                _safe_extract_zip(zf, tmp_root)
        except (zipfile.BadZipFile, OSError) as exc:
            raise CustomModelImportError("bad_zip", detail=str(exc)) from exc
        return _import_from_dir(
            tmp_root,
            display_name,
            costume_id,
            archive.name,
            allow_webgal_composite=False,
        )


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip, rejecting path traversal (Zip Slip) entries."""
    dest = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if dest != target and dest not in target.parents:
            raise CustomModelImportError("bad_zip", detail="unsafe path in archive")
    zf.extractall(dest)
