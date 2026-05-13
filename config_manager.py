import json
import os
import tempfile
from pathlib import Path
from app_theme import BANDORI_PRIMARY
from live2d_click_actions import normalize_click_motion_actions
from process_utils import app_base_dir

BASE_DIR = app_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULTS = {
    "character": "",
    "costume": "",
    "models": [],
    "model_action_settings": {},
    "language": "",
    "fps": 120,
    "opacity": 1.0,
    "dark_theme": False,
    "vsync": True,
    "game_topmost": False,
    "live2d_quality": "balanced",
    "live2d_scale": 0,
    "drag_locked": False,
    "pet_mode": "live2d",
    "window_x": -1,
    "window_y": -1,
    "window_width": 400,
    "window_height": 500,
    "pixel_window_x": -1,
    "pixel_window_y": -1,
    "llm_api_url": "",
    "llm_api_key": "",
    "llm_model_id": "",
    "llm_aux_model_id": "",
    "user_name": "",
    "user_avatar_color": BANDORI_PRIMARY,
    "chat_avatar_paths": {},
    "pov_mode": "off",
    "pov_custom_prompt": "",
    "pov_role_character": "",
    "llm_enable_thinking": None,
    "llm_show_reasoning": True,
    "compact_ai_window_enabled": False,
    "compact_ai_window_background_color": "",
    "compact_ai_window_text_color": "#24242a",
    "compact_ai_window_opacity": 44,
    "compact_ai_window_font_size": 12,
}

MODEL_DEFAULTS = {
    "window_x": -1,
    "window_y": -1,
    "window_width": 400,
    "window_height": 500,
    "pixel_window_x": -1,
    "pixel_window_y": -1,
    "pet_mode": "live2d",
    "default_motion": "",
    "default_expression": "",
    "click_motion_actions": {},
}

MODEL_ACTION_KEYS = (
    "default_motion",
    "default_expression",
    "click_motion_actions",
)


def model_action_settings_key(character: str, costume: str) -> str:
    return f"{character}\t{costume}"


def normalize_model_action_profile(profile) -> dict:
    if not isinstance(profile, dict):
        return {}

    normalized = {}
    default_motion = str(profile.get("default_motion", "") or "").strip()
    default_expression = str(profile.get("default_expression", "") or "").strip()
    click_motion_actions = normalize_click_motion_actions(
        profile.get("click_motion_actions", {})
    )
    if default_motion:
        normalized["default_motion"] = default_motion
    if default_expression:
        normalized["default_expression"] = default_expression
    if click_motion_actions:
        normalized["click_motion_actions"] = click_motion_actions
    return normalized


class ConfigManager:
    def __init__(self, path=CONFIG_PATH):
        self._path = Path(path)
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        loaded = None
        has_action_settings = False
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                has_action_settings = isinstance(loaded, dict) and "model_action_settings" in loaded
                for k in DEFAULTS:
                    if k in loaded:
                        self._data[k] = loaded[k]
            except (json.JSONDecodeError, OSError):
                pass
        if loaded is None or not has_action_settings:
            self._data["model_action_settings"] = {}
        self._normalize_model_action_settings()
        self._normalize_models()
        if not has_action_settings:
            self._seed_model_action_settings_from_models()
        if not isinstance(self._data.get("chat_avatar_paths"), dict):
            self._data["chat_avatar_paths"] = {}
        if self._data.get("user_avatar_color") == "#2aabee":
            self._data["user_avatar_color"] = BANDORI_PRIMARY

    def _normalize_model_action_settings(self):
        profiles = self._data.get("model_action_settings", {})
        if not isinstance(profiles, dict):
            self._data["model_action_settings"] = {}
            return

        normalized = {}
        for key, profile in profiles.items():
            profile = normalize_model_action_profile(profile)
            if profile:
                normalized[str(key)] = profile
        self._data["model_action_settings"] = normalized

    def _seed_model_action_settings_from_models(self):
        profiles = dict(self._data.get("model_action_settings", {}))
        for item in self._data.get("models", []):
            if not isinstance(item, dict):
                continue
            character = item.get("character", "")
            costume = item.get("costume", "")
            profile = normalize_model_action_profile(item)
            if character and costume and profile:
                profiles[model_action_settings_key(character, costume)] = profile
        self._data["model_action_settings"] = profiles

    def _normalize_models(self):
        models = self._data.get("models", [])
        if not isinstance(models, list):
            self._data["models"] = []
            return

        normalized = []
        for item in models:
            if not isinstance(item, dict):
                continue
            character = item.get("character", "")
            costume = item.get("costume", "")
            if not character or not costume:
                continue
            entry = dict(MODEL_DEFAULTS)
            entry.update(item)
            profile = self.get_model_action_profile(character, costume)
            for key in MODEL_ACTION_KEYS:
                if not item.get(key) and profile.get(key):
                    entry[key] = profile[key]
            entry["click_motion_actions"] = normalize_click_motion_actions(
                entry.get("click_motion_actions", {})
            )
            normalized.append(entry)

        self._data["models"] = normalized
        if normalized and not (self._data.get("character") and self._data.get("costume")):
            first = normalized[0]
            self._data["character"] = first["character"]
            self._data["costume"] = first["costume"]

    def save(self):
        # Atomic write: write to a temp file in the same directory, fsync,
        # then os.replace into place. Avoids losing all settings (including
        # llm_api_key) if the process is killed mid-write.
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=self._path.name + ".",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def update(self, d: dict):
        self._data.update(d)

    def get_model_action_profile(self, character: str, costume: str) -> dict:
        profiles = self._data.get("model_action_settings", {})
        if not isinstance(profiles, dict):
            return {}
        key = model_action_settings_key(str(character or ""), str(costume or ""))
        return dict(profiles.get(key, {}))

    def set_model_action_profile(self, character: str, costume: str, profile):
        character = str(character or "")
        costume = str(costume or "")
        if not character or not costume:
            return
        profiles = self._data.get("model_action_settings", {})
        if not isinstance(profiles, dict):
            profiles = {}
        else:
            profiles = dict(profiles)
        key = model_action_settings_key(character, costume)
        normalized = normalize_model_action_profile(profile)
        if normalized:
            profiles[key] = normalized
        else:
            profiles.pop(key, None)
        self._data["model_action_settings"] = profiles

    @property
    def data(self):
        return dict(self._data)
