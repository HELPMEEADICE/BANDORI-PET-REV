"""Import / manage user-supplied Live2D models.

A custom model is stored exactly like a built-in one: copied into
``models/<character>/<costume>/`` containing a Cubism 2.1 ``model.json``
plus its resources, so the rest of the app (ModelManager scan, band
grouping, costume picker, click-motion config, pet process) reuses it
without any special casing.

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
from pathlib import Path

from model_manager import MODELS_DIR

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


def list_custom_characters() -> list[str]:
    if not MODELS_DIR.is_dir():
        return []
    result = []
    for entry in sorted(MODELS_DIR.iterdir()):
        if entry.is_dir() and (entry / CUSTOM_MARKER_FILENAME).is_file():
            result.append(entry.name)
    return result


def delete_custom_character(character: str) -> None:
    """Delete an imported custom character. Refuses to touch built-ins."""
    target = MODELS_DIR / character
    if not is_custom_character(character):
        raise CustomModelImportError("not_custom")
    shutil.rmtree(target)


def _find_model_jsons(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name.lower() == MODEL_JSON_NAME
    )


def _has_cubism3_artifacts(root: Path) -> bool:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if lower.endswith(".model3.json") or lower.endswith(".moc3"):
            return True
    return False


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
    if not (model_json.parent / moc).is_file():
        raise CustomModelImportError("missing_resource", resource=moc)

    textures = data.get("textures", [])
    if not isinstance(textures, list) or not textures:
        raise CustomModelImportError("missing_textures")
    for texture in textures:
        if not isinstance(texture, str) or not (model_json.parent / texture).is_file():
            raise CustomModelImportError("missing_resource", resource=str(texture))


def _resolve_costumes(source_root: Path, costume_id: str) -> list[tuple[str, Path]]:
    """Map a source tree to a list of (costume_id, costume_dir) to copy.

    One model.json -> a single costume using the user-supplied id.
    Multiple model.json -> one costume per containing folder (ids derived
    from folder names), since the user only names a single costume.
    """
    model_jsons = _find_model_jsons(source_root)
    if not model_jsons:
        if _has_cubism3_artifacts(source_root):
            raise CustomModelImportError("cubism3_unsupported")
        raise CustomModelImportError("no_model_json")

    costumes: list[tuple[str, Path]] = []
    if len(model_jsons) == 1:
        parent = model_jsons[0].parent
        fallback = parent.name if parent != source_root else "default"
        costumes.append((sanitize_costume_id(costume_id, fallback), parent))
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
            costumes.append((cid, parent))

    for _cid, costume_dir in costumes:
        _validate_cubism2_model(costume_dir / MODEL_JSON_NAME)
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
        for cid, costume_dir in costumes:
            shutil.copytree(costume_dir, target_dir / cid)
        _write_marker(target_dir, source_label)
    except CustomModelImportError:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    except (OSError, shutil.Error) as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise CustomModelImportError("copy_failed", detail=str(exc)) from exc

    return character, [cid for cid, _dir in costumes]


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
        return _import_from_dir(tmp_root, display_name, costume_id, archive.name)


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip, rejecting path traversal (Zip Slip) entries."""
    dest = dest.resolve()
    for member in zf.namelist():
        target = (dest / member).resolve()
        if dest != target and dest not in target.parents:
            raise CustomModelImportError("bad_zip", detail="unsafe path in archive")
    zf.extractall(dest)
