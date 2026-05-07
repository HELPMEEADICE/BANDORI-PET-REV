import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
OUTFIT_JSON = BASE_DIR / "outfit.json"
BAND_JSON = BASE_DIR / "band.json"


class ModelManager:
    def __init__(self):
        self._characters: dict[str, dict] = {}
        self._costume_names: dict[str, dict[str, str]] = {}
        self._bands: list[dict] = []
        self._scan()
        self._parse_outfit_json()
        self._parse_band_json()

    def _scan(self):
        for entry in sorted(MODELS_DIR.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            char_name = entry.name
            costumes = []
            for costume_dir in sorted(entry.iterdir()):
                if not costume_dir.is_dir():
                    continue
                model_json = costume_dir / "model.json"
                if model_json.exists():
                    costumes.append({
                        "id": costume_dir.name,
                        "path": str(model_json.resolve()),
                    })
            if costumes:
                self._characters[char_name] = {
                    "costumes": costumes,
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
                "display": "其他角色",
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

    def get_display_name(self, character: str) -> str:
        return self._characters.get(character, {}).get("display", character.title())

    @staticmethod
    def get_character_image_path(character: str) -> str:
        char_dir = MODELS_DIR / character
        for ext in ("png", "jpg", "webp"):
            path = char_dir / f"character.{ext}"
            if path.exists():
                return str(path.resolve())
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
        path = MODELS_DIR / character / costume / "model.json"
        if path.exists():
            return str(path.resolve())
        return ""
