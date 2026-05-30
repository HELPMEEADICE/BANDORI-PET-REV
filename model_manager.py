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

    def __init__(self, scan_models: bool = True):
        self._characters: dict[str, dict] = {}
        self._costume_names: dict[str, dict[str, str]] = {}
        self._bands: list[dict] = []
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
        self._advanced_roleplay_cache = None
        self._scan()
        self._parse_outfit_json()
        self._parse_band_json()

    def _scan_model_keys(self):
        ModelManager._model_paths = {}
        ModelManager._character_images = {}
        if not models_dir_exists():
            return
        for entry in sorted(MODELS_DIR.iterdir()):
            if entry.name.startswith("_"):
                continue
            if entry.is_dir():
                character = entry.name
                image_path = self._find_dir_character_image(entry)
            elif entry.is_file() and entry.suffix.lower() == ".zst":
                character = entry.stem
                try:
                    files = list_archive_files(entry)
                    image_path = self._find_archive_character_image(entry, files, character)
                except Exception:
                    image_path = ""
            else:
                continue
            if image_path:
                ModelManager._character_images[character] = image_path
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
                archive_paths.append(entry)

        if not archive_paths:
            return

        max_workers = min(len(archive_paths), os.cpu_count() or 1)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for result in executor.map(self._read_model_archive, archive_paths):
                if result is not None:
                    self._apply_archive_scan_result(result)

    @staticmethod
    def _is_model_json(json_path: Path) -> bool:
        """检查 JSON 文件是否是 Live2D 模型配置文件"""
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            # 模型配置文件必须包含 model 字段（指向 .moc 文件）
            return "model" in data and isinstance(data["model"], str)
        except (json.JSONDecodeError, OSError):
            return False

    def _scan_model_dir(self, entry: Path):
        char_name = entry.name
        costumes = []
        has_model_json = False
        # 扫描子目录中的 model.json
        for costume_dir in sorted(entry.iterdir()):
            if not costume_dir.is_dir():
                continue
            model_json = costume_dir / "model.json"
            if model_json.exists():
                has_model_json = True
                model_path = str(model_json.resolve())
                costumes.append({
                    "id": costume_dir.name,
                    "path": model_path,
                })
                ModelManager._model_paths[(char_name, costume_dir.name)] = model_path
            else:
                # 没有 model.json，扫描子目录内的 *.model.json
                for variant_file in sorted(costume_dir.glob("*.model.json")):
                    has_model_json = True
                    variant_name = f"{costume_dir.name}/{variant_file.stem.replace('.model', '')}"
                    model_path = str(variant_file.resolve())
                    costumes.append({
                        "id": variant_name,
                        "path": model_path,
                    })
                    ModelManager._model_paths[(char_name, variant_name)] = model_path
                # 扫描其他合法模型 JSON 文件
                for json_file in sorted(costume_dir.glob("*.json")):
                    if json_file.name == "model.json" or json_file.name.endswith(".model.json"):
                        continue
                    if json_file.name in ("_custom.json", "outfit.json", "band.json", "config.json"):
                        continue
                    if self._is_model_json(json_file):
                        has_model_json = True
                        variant_name = f"{costume_dir.name}/{json_file.stem}"
                        model_path = str(json_file.resolve())
                        costumes.append({
                            "id": variant_name,
                            "path": model_path,
                        })
                        ModelManager._model_paths[(char_name, variant_name)] = model_path
        # 扫描 *.model.json 变体文件
        for variant_file in sorted(entry.glob("*.model.json")):
            has_model_json = True
            variant_name = variant_file.stem.replace(".model", "")
            model_path = str(variant_file.resolve())
            costumes.append({
                "id": variant_name,
                "path": model_path,
            })
            ModelManager._model_paths[(char_name, variant_name)] = model_path
        # 只在没有找到标准模型文件时才扫描其他 JSON 文件
        if not has_model_json:
            for json_file in sorted(entry.glob("*.json")):
                # 跳过已经处理的 model.json 和 *.model.json
                if json_file.name == "model.json" or json_file.name.endswith(".model.json"):
                    continue
                # 跳过已知的非模型配置文件
                if json_file.name in ("_custom.json", "outfit.json", "band.json", "config.json"):
                    continue
                # 检查是否是模型配置文件
                if self._is_model_json(json_file):
                    variant_name = json_file.stem
                    model_path = str(json_file.resolve())
                    costumes.append({
                        "id": variant_name,
                        "path": model_path,
                    })
                    ModelManager._model_paths[(char_name, variant_name)] = model_path
        # 递归扫描二级子目录中的模型配置文件
        for sub_dir in sorted(entry.iterdir()):
            if not sub_dir.is_dir():
                continue
            for costume_dir in sorted(sub_dir.iterdir()):
                if not costume_dir.is_dir():
                    continue
                # 检查 model.json
                model_json = costume_dir / "model.json"
                if model_json.exists():
                    model_path = str(model_json.resolve())
                    costume_name = f"{sub_dir.name}/{costume_dir.name}"
                    costumes.append({
                        "id": costume_name,
                        "path": model_path,
                    })
                    ModelManager._model_paths[(char_name, costume_name)] = model_path
                else:
                    # 检查 *.model.json 变体文件
                    for variant_file in sorted(costume_dir.glob("*.model.json")):
                        variant_name = f"{sub_dir.name}/{costume_dir.name}/{variant_file.stem.replace('.model', '')}"
                        model_path = str(variant_file.resolve())
                        costumes.append({
                            "id": variant_name,
                            "path": model_path,
                        })
                        ModelManager._model_paths[(char_name, variant_name)] = model_path
                    # 检查其他合法模型 JSON 文件
                    for json_file in sorted(costume_dir.glob("*.json")):
                        if json_file.name == "model.json" or json_file.name.endswith(".model.json"):
                            continue
                        if json_file.name in ("_custom.json", "outfit.json", "band.json", "config.json"):
                            continue
                        if self._is_model_json(json_file):
                            variant_name = f"{sub_dir.name}/{costume_dir.name}/{json_file.stem}"
                            model_path = str(json_file.resolve())
                            costumes.append({
                                "id": variant_name,
                                "path": model_path,
                            })
                            ModelManager._model_paths[(char_name, variant_name)] = model_path
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
        
        # 第一遍：查找 model.json 和 *.model.json（快速检查文件名）
        for member in files:
            member_path = Path(member)
            member_name = member_path.name
            
            # 跳过已知的非模型配置文件
            if member_name in ("_custom.json", "outfit.json", "band.json", "config.json"):
                continue
            
            is_model = False
            costume_id = None
            
            # 标准 model.json
            if member_name == "model.json":
                is_model = True
                parent = member_path.parent
                costume_id = parent.name if str(parent) != "." else "default"
            # *.model.json 变体文件
            elif member_name.endswith(".model.json"):
                is_model = True
                parent = member_path.parent
                variant_name = member_name.replace(".model.json", "")
                if str(parent) != ".":
                    costume_id = f"{parent.name}/{variant_name}"
                else:
                    costume_id = variant_name
            
            if is_model:
                model_path = make_virtual_path(archive_path, member)
                costumes.append({
                    "id": costume_id,
                    "path": model_path,
                })
                model_paths.append((char_name, costume_id, model_path))
        
        # 第二遍：如果没有找到标准模型文件，检查其他 JSON 文件内容
        if not costumes:
            for member in files:
                member_path = Path(member)
                member_name = member_path.name
                
                # 跳过已知的非模型配置文件
                if member_name in ("_custom.json", "outfit.json", "band.json", "config.json"):
                    continue
                
                # 跳过已经检查过的文件
                if member_name == "model.json" or member_name.endswith(".model.json"):
                    continue
                
                # 只检查 JSON 文件
                if not member_name.endswith(".json"):
                    continue
                
                # 检查文件内容是否是模型配置
                try:
                    model_path = make_virtual_path(archive_path, member)
                    data = load_virtual_json(model_path)
                    if isinstance(data, dict) and "model" in data and isinstance(data["model"], str):
                        parent = member_path.parent
                        variant_name = member_name.replace(".json", "")
                        if str(parent) != ".":
                            costume_id = f"{parent.name}/{variant_name}"
                        else:
                            costume_id = variant_name
                        
                        costumes.append({
                            "id": costume_id,
                            "path": model_path,
                        })
                        model_paths.append((char_name, costume_id, model_path))
                except Exception:
                    # 无法解析的 JSON 文件，跳过
                    continue

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
            ModelManager._character_images.setdefault(result["character"], image_path)
        char_name = result["character"]
        new_costumes = result["costumes"]
        if char_name in self._characters:
            existing_costumes = self._characters[char_name].get("costumes", [])
            existing_ids = {c["id"] for c in existing_costumes}
            for costume in new_costumes:
                costume_id = costume["id"]
                if costume_id in existing_ids:
                    suffix = 1
                    while f"{costume_id}_zst{suffix}" in existing_ids:
                        suffix += 1
                    costume["id"] = f"{costume_id}_zst{suffix}"
                    existing_ids.add(costume["id"])
                    ModelManager._model_paths[(char_name, costume["id"])] = costume["path"]
                else:
                    existing_ids.add(costume_id)
            self._characters[char_name]["costumes"] = existing_costumes + new_costumes
        else:
            self._characters[char_name] = {
                "costumes": new_costumes,
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

        # 所有未在 band.json 中配置的角色（自动扫描 + 自定义导入）都放入"自定义模型"分组
        ungrouped = [
            c for c in self.characters
            if c not in seen and self.get_costumes(c)
        ]
        if ungrouped:
            self._bands.append({
                "id": "custom_models",
                "display": _tr("ModelManager.custom_models_band"),
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
