import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QMessageBox

from i18n_manager import tr as _tr
from process_utils import app_base_dir
from zst_model_archive import (
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
    _model_paths: dict[tuple[str, str], str] = {}
    _character_images: dict[str, str] = {}

    def __init__(self):
        self._characters: dict[str, dict] = {}
        self._costume_names: dict[str, dict[str, str]] = {}
        self._bands: list[dict] = []
        self._advanced_roleplay_cache: dict[str, bool] | None = None
        self._scan()
        self._parse_outfit_json()
        self._parse_band_json()

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
        ModelManager._model_paths = {}
        ModelManager._character_images = {}
        if not models_dir_exists():
            return
        entries = [entry for entry in sorted(MODELS_DIR.iterdir()) if not entry.name.startswith("_")]
        for entry in entries:
            if entry.is_dir():
                self._scan_model_dir(entry)

        archive_paths = []
        for entry in entries:
            if entry.is_file() and entry.suffix.lower() == ".zst":
                if entry.stem in self._characters:
                    continue
                archive_paths.append(entry)

        if not archive_paths:
            return

        max_workers = min(len(archive_paths), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for result in executor.map(self._read_model_archive, archive_paths):
                if result is not None:
                    self._apply_archive_scan_result(result)

    def _scan_model_dir(self, entry: Path):
        char_name = entry.name
        costumes = []
        for costume_dir in sorted(entry.iterdir()):
            if not costume_dir.is_dir():
                continue
            model_json = costume_dir / "model.json"
            if model_json.exists():
                model_path = str(model_json.resolve())
                costumes.append({
                    "id": costume_dir.name,
                    "path": model_path,
                })
                ModelManager._model_paths[(char_name, costume_dir.name)] = model_path
        image_path = self._find_dir_character_image(entry)
        if image_path:
            ModelManager._character_images[char_name] = image_path
        if costumes:
            self._characters[char_name] = {
                "costumes": costumes,
            }

    def _read_model_archive(self, archive_path: Path):
        char_name = archive_path.stem
        try:
            files = list_archive_files(archive_path)
        except Exception as exc:
            print(f"Failed to scan model archive {archive_path}: {exc}")
            return None

        costumes = []
        model_paths = []
        for member in files:
            if Path(member).name != "model.json":
                continue
            parent = Path(member).parent
            costume_id = parent.name if str(parent) != "." else "default"
            model_path = make_virtual_path(archive_path, member)
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
        for char_name, costume_id, model_path in result["model_paths"]:
            ModelManager._model_paths[(char_name, costume_id)] = model_path
        image_path = result["image_path"]
        if image_path:
            ModelManager._character_images[result["character"]] = image_path
        self._characters[result["character"]] = {
            "costumes": result["costumes"],
        }

    def _parse_outfit_json(self):
        if not OUTFIT_JSON.exists():
            return
        data = json.loads(OUTFIT_JSON.read_text(encoding="utf-8"))
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
            data = json.loads(BAND_JSON.read_text(encoding="utf-8"))
            configured_bands = data.get("bands", [])
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

    @staticmethod
    def get_character_image_path(character: str) -> str:
        image_path = ModelManager._character_images.get(character, "")
        if image_path:
            return "" if is_virtual_path(image_path) else image_path
        char_dir = MODELS_DIR / character
        return ModelManager._find_dir_character_image(char_dir)

    @staticmethod
    def get_character_image_data(character: str) -> bytes:
        image_path = ModelManager._character_images.get(character, "")
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

    @staticmethod
    def get_model_json_path(character: str, costume: str) -> str:
        model_path = ModelManager._model_paths.get((character, costume), "")
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

    def get_motion_names(self, character: str, costume: str) -> list[str]:
        path = self.get_model_json_path(character, costume)
        if not path:
            return []
        try:
            data = self._read_model_json(path)
        except (json.JSONDecodeError, OSError):
            return []
        motions = data.get("motions", {})
        if not isinstance(motions, dict):
            return []
        return sorted(str(name) for name in motions if name)

    def get_expression_names(self, character: str, costume: str) -> list[str]:
        path = self.get_model_json_path(character, costume)
        if not path:
            return []
        try:
            data = self._read_model_json(path)
        except (json.JSONDecodeError, OSError):
            return []
        expressions = data.get("expressions", [])
        if not isinstance(expressions, list):
            return []
        names = []
        for item in expressions:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        return sorted(names)
