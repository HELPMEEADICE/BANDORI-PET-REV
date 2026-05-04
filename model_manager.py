import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
OUTFIT_MD = BASE_DIR / "OUTFIT.md"


class ModelManager:
    def __init__(self):
        self._characters: dict[str, dict] = {}
        self._costume_names: dict[str, dict[str, str]] = {}
        self._scan()
        self._parse_outfit_md()

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

    def _parse_outfit_md(self):
        if not OUTFIT_MD.exists():
            return
        text = OUTFIT_MD.read_text(encoding="utf-8")
        sections = re.split(r"\n## \d+\. ", text)
        for section in sections[1:]:
            lines = section.strip().split("\n")
            header = lines[0].strip()
            m = re.match(r"(.+?)\s*\((\w+)\)", header)
            if not m:
                continue
            display_name = m.group(1).strip()
            key = m.group(2).strip()
            self._characters.setdefault(key, {})
            self._characters[key]["display"] = display_name
            self._costume_names.setdefault(key, {})
            for line in lines[2:]:
                m2 = re.match(r"\|\s*`(\S+?)`\s*\|\s*(.+?)\s*\|", line)
                if m2:
                    cid = m2.group(1)
                    cname = m2.group(2)
                    self._costume_names[key][cid] = cname

    @property
    def characters(self) -> list[str]:
        return list(self._characters.keys())

    def get_display_name(self, character: str) -> str:
        return self._characters.get(character, {}).get("display", character.title())

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
