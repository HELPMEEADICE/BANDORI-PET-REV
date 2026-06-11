import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QMessageBox

from i18n_manager import tr as _tr
from process_utils import app_base_dir
from zst_model_archive import (
    VIRTUAL_SEP,
    is_virtual_path,
    list_archive_files,
    load_virtual_bytes,
    load_virtual_json,
    make_virtual_path,
)

BASE_DIR = app_base_dir()
MODELS_DIR = BASE_DIR / "models"
OUTFIT_JSON = BASE_DIR / "outfit.json"
BAND_JSON = BASE_DIR / "band.json"
CHARACTERS_DIR = BASE_DIR / "characters"
MODELS_DOWNLOAD_URL = "https://modelscope.cn/datasets/HELPMEEADICE/BanG-Dream-Live2D/resolve/master/models.zip"
WEBGAL_COMPOSITE_FILENAME = "_webgal_composite.json"
_SKIPPED_TOP_MODEL_DIR_NAMES = {"模型存放"}


def is_webgal_composite_path(path: str) -> bool:
    return not is_virtual_path(path) and Path(path).name == WEBGAL_COMPOSITE_FILENAME
_SKIPPED_MODEL_JSON_NAMES = {
    WEBGAL_COMPOSITE_FILENAME,
    "_custom.json",
    "outfit.json",
    "band.json",
    "config.json",
}
_SKIPPED_MODEL_DIR_NAMES = {"_mtn_emp"}


def models_dir_exists() -> bool:
    return MODELS_DIR.is_dir() and any(MODELS_DIR.iterdir())


def prompt_download_model_resources(parent=None) -> None:
    message_box = QMessageBox(parent)
    message_box.setIcon(QMessageBox.Icon.Warning)
    message_box.setWindowTitle(_tr("ModelResources.missing_title"))
    message_box.setText(_tr("ModelResources.missing_content"))
    message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
    icon_path = BASE_DIR / "logo.ico"
    if icon_path.exists():
        message_box.setWindowIcon(QIcon(str(icon_path)))
    message_box.exec()
    QDesktopServices.openUrl(QUrl(MODELS_DOWNLOAD_URL))


class ModelManager:
    def __init__(self, scan_models: bool = True):
        self._model_paths: dict[tuple[str, str], str] = {}
        self._character_images: dict[str, str] = {}
        self._characters: dict[str, dict] = {}
        self._costume_names: dict[str, dict[str, str]] = {}
        self._bands: list[dict] = []
        self._directory_model_characters: set[str] = set()
        self._archive_model_characters: set[str] = set()
        self._advanced_roleplay_cache: dict[str, bool] | None = None
        if scan_models:
            self._scan()
        else:
            self._scan_model_keys()
        self._parse_outfit_json()
        self._parse_band_json()

    def rescan(self):
        """Re-read the models directory after models are added/removed.

        Mirrors __init__'s full-scan path so newly imported (or deleted)
        characters are picked up without recreating the manager.
        """
        self._characters = {}
        self._costume_names = {}
        self._bands = []
        self._directory_model_characters = set()
        self._archive_model_characters = set()
        self._advanced_roleplay_cache = None
        self._scan()
        self._parse_outfit_json()
        self._parse_band_json()

    def _scan_model_keys(self):
        self._model_paths = {}
        self._character_images = {}
        self._directory_model_characters = set()
        self._archive_model_characters = set()
        if not models_dir_exists():
            return
        for entry in sorted(MODELS_DIR.iterdir()):
            if entry.name.startswith("_") or entry.name in _SKIPPED_TOP_MODEL_DIR_NAMES:
                continue
            if entry.is_dir():
                character = entry.name
                self._directory_model_characters.add(character)
                image_path = self._find_dir_character_image(entry)
            elif entry.is_file() and entry.suffix.lower() == ".zst":
                character = entry.stem
                self._archive_model_characters.add(character)
                try:
                    files = list_archive_files(entry)
                    image_path = self._find_archive_character_image(entry, files, character)
                except Exception:
                    image_path = ""
            else:
                continue
            if image_path and character not in self._character_images:
                self._character_images[character] = image_path
            self._characters.setdefault(character, {"costumes": [{"id": "default", "path": ""}]})

    def _scan_advanced_roleplay_support(self) -> dict[str, bool]:
        support = {character: False for character in self.characters}
        if not CHARACTERS_DIR.exists():
            return support

        display_to_keys: dict[str, list[str]] = {}
        for character in self.characters:
            display_to_keys.setdefault(self.get_display_name(character), []).append(character)
        for entry in sorted(CHARACTERS_DIR.iterdir()):
            if not entry.is_dir():
                continue
            characters = display_to_keys.get(entry.name, [])
            if not characters:
                continue
            has_markdown = any(
                path.is_file() and path.suffix.lower() == ".md"
                for path in entry.iterdir()
            )
            for character in characters:
                support[character] = has_markdown
        return support

    def _scan(self):
        self._model_paths = {}
        self._character_images = {}
        self._directory_model_characters = set()
        self._archive_model_characters = set()
        if not models_dir_exists():
            return
        entries = [
            entry for entry in sorted(MODELS_DIR.iterdir())
            if not entry.name.startswith("_") and entry.name not in _SKIPPED_TOP_MODEL_DIR_NAMES
        ]
        for entry in entries:
            if entry.is_dir():
                self._scan_model_dir(entry)

        archive_paths = []
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() == ".zst":
                archive_paths.append(entry)

        if not archive_paths:
            return

        for archive_path in archive_paths:
            result = self._read_model_archive(archive_path)
            if result is not None:
                self._apply_archive_scan_result(result)

    def _scan_model_dir(self, entry: Path):
        char_name = entry.name
        direct_composite = self._ensure_direct_webgal_composite(entry)
        if direct_composite:
            model_path = str(direct_composite.resolve())
            self._model_paths[(char_name, "default")] = model_path
            self._characters[char_name] = {
                "costumes": [{
                    "id": "default",
                    "path": model_path,
                    "composite": "webgal",
                }],
            }
            image_path = self._find_dir_character_image(entry)
            if image_path:
                self._character_images[char_name] = image_path
            self._directory_model_characters.add(char_name)
            return

        costumes = []
        for costume_dir in sorted(entry.iterdir()):
            if not costume_dir.is_dir():
                continue
            resolved = self._resolve_dir_costume_model(costume_dir)
            if not resolved:
                continue
            model_path, is_composite = resolved
            costume = {
                "id": costume_dir.name,
                "path": model_path,
            }
            if is_composite:
                costume["composite"] = "webgal"
            costumes.append(costume)
            self._model_paths[(char_name, costume_dir.name)] = model_path
        image_path = self._find_dir_character_image(entry)
        if image_path:
            self._character_images[char_name] = image_path
        if costumes:
            self._directory_model_characters.add(char_name)
            self._characters[char_name] = {
                "costumes": costumes,
            }

    @staticmethod
    def _json_has_model_field(path: Path) -> bool:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return False
        if not isinstance(data, dict) or not isinstance(data.get("model"), str):
            return False
        if "FileReferences" in data or str(data.get("Version", "")).startswith("3"):
            return False
        return not str(data.get("model", "")).lower().endswith(".moc3")

    @staticmethod
    def _is_skipped_model_json_path(root: Path, path: Path) -> bool:
        if path.name in _SKIPPED_MODEL_JSON_NAMES:
            return True
        lower = path.name.lower()
        if lower.endswith(".model3.json"):
            return True
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            parts = path.parts
        return any(part in _SKIPPED_MODEL_DIR_NAMES for part in parts)

    @classmethod
    def _find_model_jsons(cls, root: Path) -> list[Path]:
        result = []
        for json_path in sorted(root.rglob("*.json")):
            if not json_path.is_file() or cls._is_skipped_model_json_path(root, json_path):
                continue
            if cls._json_has_model_field(json_path):
                result.append(json_path)
        return result

    @classmethod
    def _find_root_model_json(cls, root: Path) -> Path | None:
        candidates = []
        standard = root / "model.json"
        if standard.is_file():
            candidates.append(standard)
        candidates.extend(
            path for path in sorted(root.glob("*.json"))
            if path != standard and path.is_file()
        )
        for json_path in candidates:
            if (
                not cls._is_skipped_model_json_path(root, json_path)
                and cls._json_has_model_field(json_path)
            ):
                return json_path
        return None

    @classmethod
    def _find_direct_webgal_model_jsons(cls, char_dir: Path) -> list[Path]:
        result = []
        for child in sorted(char_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("_") or child.name in _SKIPPED_MODEL_DIR_NAMES:
                continue
            model_jsons = cls._find_shallow_model_jsons(child)
            if len(model_jsons) == 1:
                result.append(model_jsons[0])
        return result

    @classmethod
    def _find_shallow_model_jsons(cls, root: Path) -> list[Path]:
        result = []
        candidates = list(root.glob("*.json"))
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("_") and child.name not in _SKIPPED_MODEL_DIR_NAMES:
                candidates.extend(child.glob("*.json"))
        for json_path in sorted(candidates):
            if (
                json_path.is_file()
                and not cls._is_skipped_model_json_path(root, json_path)
                and cls._json_has_model_field(json_path)
            ):
                result.append(json_path)
        return result

    @classmethod
    def _webgal_jsonl_order(cls, root: Path) -> dict[str, int]:
        order: dict[str, int] = {}
        index = 0
        for jsonl_path in sorted(root.glob("*.jsonl")):
            try:
                lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in lines:
                try:
                    item = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(item, dict):
                    continue
                relative = str(item.get("path", "") or "").replace("\\", "/").strip()
                if not relative or not relative.lower().endswith(".json"):
                    continue
                order.setdefault(relative, index)
                index += 1
        return order

    @staticmethod
    def _webgal_layer_sort_key(root: Path, path: Path, jsonl_order: dict[str, int] | None = None):
        jsonl_order = jsonl_order or {}
        try:
            relative_path = path.relative_to(root).as_posix()
            relative_parent = path.parent.relative_to(root)
            first_part = relative_parent.parts[0] if relative_parent.parts else path.parent.name
        except ValueError:
            relative_path = path.as_posix()
            first_part = path.parent.name
        prefix = ""
        for ch in first_part:
            if ch.isdigit():
                prefix += ch
            else:
                break
        numeric = int(prefix) if prefix else 999999
        order = jsonl_order.get(relative_path, 999999)
        return order, numeric, first_part.lower(), path.parent.as_posix().lower(), path.name.lower()

    @classmethod
    def _ensure_direct_webgal_composite(cls, char_dir: Path) -> Path | None:
        manifest_path = char_dir / WEBGAL_COMPOSITE_FILENAME
        if manifest_path.is_file():
            return manifest_path

        if cls._find_root_model_json(char_dir):
            return None

        model_jsons = cls._find_direct_webgal_model_jsons(char_dir)
        if len(model_jsons) < 2:
            return None

        jsonl_order = cls._webgal_jsonl_order(char_dir)
        model_jsons = sorted(
            model_jsons,
            key=lambda path: cls._webgal_layer_sort_key(char_dir, path, jsonl_order),
        )
        manifest = {
            "format": "bandori_webgal_composite",
            "version": 1,
            "layers": [
                {
                    "name": model_json.parent.name,
                    "model": model_json.relative_to(char_dir).as_posix(),
                }
                for model_json in model_jsons
            ],
        }
        try:
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"Failed to write WebGal composite manifest {manifest_path}: {exc}")
            return None
        return manifest_path

    @classmethod
    def _resolve_dir_costume_model(cls, costume_dir: Path) -> tuple[str, bool] | None:
        composite_json = costume_dir / WEBGAL_COMPOSITE_FILENAME
        if composite_json.is_file():
            return str(composite_json.resolve()), True

        root_model_json = cls._find_root_model_json(costume_dir)
        if root_model_json:
            return str(root_model_json.resolve()), False

        direct_composite = cls._ensure_direct_webgal_composite(costume_dir)
        if direct_composite:
            return str(direct_composite.resolve()), True

        model_jsons = cls._find_shallow_model_jsons(costume_dir)
        if len(model_jsons) == 1:
            return str(model_jsons[0].resolve()), False
        return None

    def _read_model_archive(self, archive_path: Path):
        char_name = archive_path.stem
        try:
            files = list_archive_files(archive_path)
        except Exception as exc:
            print(f"Failed to scan model archive {archive_path}: {exc}")
            return None

        archive_resolved = str(archive_path.resolve())
        costumes = []
        model_paths = []
        for member in files:
            if member != "model.json" and not member.endswith("/model.json"):
                continue
            parent = member.rsplit("/", 1)[0] if "/" in member else ""
            costume_id = parent.rsplit("/", 1)[-1] if parent else "default"
            model_path = f"{archive_resolved}{VIRTUAL_SEP}{member}"
            costumes.append({
                "id": costume_id,
                "path": model_path,
            })
            model_paths.append((char_name, costume_id, model_path))

        image_path = self._find_archive_character_image(archive_path, files, char_name)
        if not costumes:
            return None
        return {
            "character": char_name,
            "costumes": sorted(costumes, key=lambda item: item["id"]),
            "image_path": image_path,
            "model_paths": model_paths,
        }

    def _apply_archive_scan_result(self, result: dict):
        character = result["character"]
        self._archive_model_characters.add(character)
        existing_costumes = list(self._characters.get(character, {}).get("costumes", []))
        existing_ids = {str(item.get("id", "")) for item in existing_costumes}
        merged_costumes = [
            costume
            for costume in result["costumes"]
            if str(costume.get("id", "")) not in existing_ids
        ]
        merged_costumes.extend(existing_costumes)

        for char_name, costume_id, model_path in result["model_paths"]:
            if costume_id in existing_ids:
                continue
            self._model_paths[(char_name, costume_id)] = model_path
        image_path = result["image_path"]
        if image_path and character not in self._character_images:
            self._character_images[character] = image_path
        self._characters[character] = {
            "costumes": merged_costumes,
        }

    def _parse_outfit_json(self):
        if not OUTFIT_JSON.exists():
            return
        try:
            data = json.loads(OUTFIT_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            print(f"Failed to parse outfit.json: {exc}")
            return
        chars = data.get("characters", {})
        for key, info in chars.items():
            self._characters.setdefault(key, {})
            self._characters[key]["display"] = info.get("display", key)
            costumes = info.get("costumes", {})
            if costumes:
                self._costume_names.setdefault(key, {})
                self._costume_names[key].update(costumes)

    def _parse_band_json(self):
        if BAND_JSON.exists():
            try:
                data = json.loads(BAND_JSON.read_text(encoding="utf-8"))
                configured_bands = data.get("bands", [])
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                print(f"Failed to parse band.json: {exc}")
                configured_bands = []
        else:
            configured_bands = []

        seen = set()
        for band in configured_bands:
            characters = [
                c for c in band.get("characters", [])
                if c in self._characters and self.get_costumes(c)
            ]
            if not characters:
                continue
            seen.update(characters)
            self._bands.append({
                "id": band.get("id", ""),
                "display": band.get("display", band.get("id", "")),
                "logo": str((BASE_DIR / band.get("logo", "")).resolve()) if band.get("logo") else "",
                "characters": characters,
            })

        custom_characters = [
            c for c in self.characters
            if c not in seen and self.get_costumes(c)
            and c in self._directory_model_characters
        ]
        if custom_characters:
            self._bands.append({
                "id": "custom_models",
                "display": _tr("ModelManager.custom_models_band"),
                "characters": custom_characters,
            })
            seen.update(custom_characters)

        ungrouped = [
            c for c in self.characters
            if c not in seen and self.get_costumes(c)
        ]
        if ungrouped:
            self._bands.append({
                "id": "others",
                "display": _tr("ModelManager.others_band"),
                "characters": ungrouped,
            })

    @property
    def characters(self) -> list[str]:
        return list(self._characters.keys())

    @property
    def bands(self) -> list[dict]:
        return self._bands

    def get_band_display_name(self, band_id: str) -> str:
        for band in self._bands:
            if band["id"] == band_id:
                return band["display"]
        return band_id

    def get_band_characters(self, band_id: str) -> list[str]:
        for band in self._bands:
            if band["id"] == band_id:
                return band["characters"]
        return []

    def get_character_band(self, character: str) -> str:
        for band in self._bands:
            if character in band["characters"]:
                return band["id"]
        return ""

    def has_advanced_roleplay(self, character: str) -> bool:
        if self._advanced_roleplay_cache is None:
            self._advanced_roleplay_cache = self._scan_advanced_roleplay_support()
        return self._advanced_roleplay_cache.get(character, False)

    def get_band_advanced_roleplay_status(self, band_id: str) -> str:
        characters = self.get_band_characters(band_id)
        if not characters:
            return "red"

        supported_count = sum(
            1 for character in characters
            if self.has_advanced_roleplay(character)
        )
        if supported_count == len(characters):
            return "green"
        if supported_count > 0:
            return "yellow"
        return "red"

    def get_display_name(self, character: str) -> str:
        return self._characters.get(character, {}).get("display", character.title())

    def get_character_image_path(self, character: str) -> str:
        image_path = self._character_images.get(character, "")
        if image_path:
            return "" if is_virtual_path(image_path) else image_path
        char_dir = MODELS_DIR / character
        return self._find_dir_character_image(char_dir)

    def get_character_image_data(self, character: str) -> bytes:
        image_path = self._character_images.get(character, "")
        if not is_virtual_path(image_path):
            return b""
        try:
            return load_virtual_bytes(image_path)
        except Exception as exc:
            print(f"Failed to load archive character image {image_path}: {exc}")
            return b""

    @staticmethod
    def _find_dir_character_image(char_dir: Path) -> str:
        for ext in ("png", "jpg", "webp"):
            path = char_dir / f"character.{ext}"
            if path.exists():
                return str(path.resolve())
        return ""

    @staticmethod
    def _find_archive_character_image(archive_path: Path, files: list[str], character: str) -> str:
        candidates = []
        for ext in ("png", "jpg", "webp"):
            candidates.extend([
                f"character.{ext}",
                f"{character}/character.{ext}",
            ])
        file_set = set(files)
        for candidate in candidates:
            if candidate in file_set:
                return make_virtual_path(archive_path, candidate)
        return ""

    def get_costumes(self, character: str) -> list[dict]:
        return self._characters.get(character, {}).get("costumes", [])

    def get_costume_display_name(self, character: str, costume_id: str) -> str:
        return self._costume_names.get(character, {}).get(costume_id, costume_id)

    def is_composite_costume(self, character: str, costume: str) -> bool:
        for item in self.get_costumes(character):
            if item.get("id") == costume and item.get("composite") == "webgal":
                return True
        path = self.get_model_json_path(character, costume)
        return bool(path and self._is_webgal_composite_path(path))

    def get_default_costume(self, character: str) -> str:
        costumes = self.get_costumes(character)
        if not costumes:
            return ""
        preferred = ["live_default", "casual", "school_winter", "school_summer"]
        costume_ids = [c["id"] for c in costumes]
        for pref in preferred:
            if pref in costume_ids:
                return pref
        return costumes[0]["id"]

    def get_model_json_path(self, character: str, costume: str) -> str:
        model_path = self._model_paths.get((character, costume), "")
        if model_path:
            return model_path
        path = MODELS_DIR / character / costume / "model.json"
        if path.exists():
            return str(path.resolve())
        return ""

    @staticmethod
    def _read_model_json(path: str) -> dict:
        if is_virtual_path(path):
            return load_virtual_json(path)
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def _is_webgal_composite_path(path: str) -> bool:
        return is_webgal_composite_path(path)

    @classmethod
    def _read_webgal_layer_jsons(cls, manifest_path: str) -> list[dict]:
        manifest_file = Path(manifest_path)
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
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
            layer_path = (manifest_file.parent / relative).resolve()
            try:
                result.append(json.loads(layer_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError, ValueError):
                continue
        return result

    def get_motion_names(self, character: str, costume: str) -> list[str]:
        path = self.get_model_json_path(character, costume)
        if not path:
            return []
        if self._is_webgal_composite_path(path):
            names = set()
            for data in self._read_webgal_layer_jsons(path):
                motions = data.get("motions", {})
                if isinstance(motions, dict):
                    names.update(str(name) for name in motions if name)
            return sorted(names)
        try:
            data = self._read_model_json(path)
        except (json.JSONDecodeError, OSError, ValueError, KeyError, RuntimeError, UnicodeDecodeError):
            return []
        motions = data.get("motions", {})
        if not isinstance(motions, dict):
            return []
        return sorted(str(name) for name in motions if name)

    def get_expression_names(self, character: str, costume: str) -> list[str]:
        path = self.get_model_json_path(character, costume)
        if not path:
            return []
        if self._is_webgal_composite_path(path):
            names = set()
            for data in self._read_webgal_layer_jsons(path):
                expressions = data.get("expressions", [])
                if isinstance(expressions, list):
                    names.update(
                        str(item["name"])
                        for item in expressions
                        if isinstance(item, dict) and item.get("name")
                    )
            return sorted(names)
        try:
            data = self._read_model_json(path)
        except (json.JSONDecodeError, OSError, ValueError, KeyError, RuntimeError, UnicodeDecodeError):
            return []
        expressions = data.get("expressions", [])
        if not isinstance(expressions, list):
            return []
        names = [str(item["name"]) for item in expressions if isinstance(item, dict) and item.get("name")]
        return sorted(names)
