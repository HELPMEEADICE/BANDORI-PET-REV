import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULTS = {
    "character": "",
    "costume": "",
    "language": "",
    "fps": 120,
    "opacity": 1.0,
    "dark_theme": False,
    "vsync": True,
    "drag_locked": False,
    "window_x": -1,
    "window_y": -1,
    "window_width": 400,
    "window_height": 500,
    "llm_api_url": "",
    "llm_api_key": "",
    "llm_model_id": "",
    "user_name": "",
    "user_avatar_color": "#2aabee",
    "llm_enable_thinking": None,
}


class ConfigManager:
    def __init__(self, path=CONFIG_PATH):
        self._path = Path(path)
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for k in DEFAULTS:
                    if k in loaded:
                        self._data[k] = loaded[k]
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def update(self, d: dict):
        self._data.update(d)

    @property
    def data(self):
        return dict(self._data)
