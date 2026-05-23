import json
import os
import tempfile
from pathlib import Path
from app_theme import BANDORI_PRIMARY
from live2d_click_actions import normalize_click_motion_actions
from process_utils import app_base_dir

BASE_DIR = app_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"

BUILTIN_LLM_API_PROFILES = [
    {
        "name": "deepseek",
        "llm_api_url": "https://api.deepseek.com/v1/chat/completions",
        "llm_api_key": "",
        "llm_model_id": "deepseek-v4-pro",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "deepseek-v4-flash",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": False,
        "llm_api_mode": "chat_completions",
        "llm_web_search_enabled": True,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": False,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    },
    {
        "name": "openrouter",
        "llm_api_url": "https://openrouter.ai/api/v1/chat/completions",
        "llm_api_key": "",
        "llm_model_id": "z-ai/glm-5.1",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "x-ai/grok-4.3",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": True,
        "llm_api_mode": "chat_completions",
        "llm_web_search_enabled": True,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": False,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    },
    {
        "name": "claude",
        "llm_api_url": "https://openrouter.ai/api/v1/chat/completions",
        "llm_api_key": "",
        "llm_model_id": "anthropic/claude-sonnet-4.6",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "anthropic/claude-haiku-4.5",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": False,
        "llm_api_mode": "chat_completions",
        "llm_web_search_enabled": True,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": False,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    },
    {
        "name": "openai",
        "llm_api_url": "https://api.openai.com/v1/responses",
        "llm_api_key": "",
        "llm_model_id": "gpt-5.5",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "gpt-5.4-mini",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": False,
        "llm_api_mode": "responses",
        "llm_web_search_enabled": True,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": False,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    },
    {
        "name": "gemini",
        "llm_api_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "llm_api_key": "",
        "llm_model_id": "gemini-3.5-flash",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "gemini-3.5-flash-lite",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": True,
        "llm_api_mode": "chat_completions",
        "llm_web_search_enabled": False,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": False,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    },
    {
        "name": "grok",
        "llm_api_url": "https://api.x.ai/v1/chat/completions",
        "llm_api_key": "",
        "llm_model_id": "grok-4.3",
        "llm_aux_api_url": "",
        "llm_aux_api_key": "",
        "llm_aux_model_id": "grok-4-1-fast",
        "llm_aux_enable_thinking": None,
        "llm_aux_vision_fallback_enabled": False,
        "llm_api_mode": "chat_completions",
        "llm_web_search_enabled": True,
        "llm_web_search_engine": "bing_cn",
        "llm_web_search_show_sources": False,
        "llm_enable_thinking": None,
        "llm_show_reasoning": True,
    },
]

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
    "hide_live2d_model": False,
    "live2d_idle_actions_enabled": True,
    "live2d_quality": "balanced",
    "live2d_scale": 0,
    "auto_start": False,
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
    "llm_aux_api_url": "",
    "llm_aux_api_key": "",
    "llm_aux_model_id": "",
    "llm_aux_enable_thinking": None,
    "llm_aux_vision_fallback_enabled": False,
    "llm_api_mode": "chat_completions",
    "llm_web_search_enabled": False,
    "llm_web_search_engine": "bing_cn",
    "llm_web_search_show_sources": True,
    "llm_custom_system_prompt": "",
    "llm_hide_tool_call_details": True,
    "llm_mcp_enabled": False,
    "llm_mcp_use_native": True,
    "llm_mcp_servers": [],
    "computer_use_enabled": False,
    "computer_use_auto_detect": True,
    "computer_use_send_screenshots": True,
    "computer_use_max_screenshot_width": 1280,
    "computer_use_allow_screenshot": True,
    "computer_use_allow_mouse": False,
    "computer_use_allow_keyboard": False,
    "computer_use_allow_clipboard": False,
    "computer_use_allow_wait": True,
    "llm_api_profiles": BUILTIN_LLM_API_PROFILES,
    "llm_active_api_profile": "",
    "user_name": "",
    "user_avatar_color": BANDORI_PRIMARY,
    "user_avatar_path": "",
    "chat_avatar_paths": {},
    "group_chat_sidebar_ratio": 0.28,
    "group_chat_sidebar_collapsed": False,
    "pov_mode": "off",
    "pov_custom_prompt": "",
    "pov_custom_personas": [],
    "pov_role_character": "",
    "llm_enable_thinking": None,
    "llm_show_reasoning": True,
    "compact_ai_window_enabled": False,
    "compact_ai_window_background_color": "",
    "compact_ai_window_text_color": "#24242a",
    "compact_ai_window_opacity": 44,
    "compact_ai_window_font_size": 12,
    "ai_event_overlay_enabled": False,
    "ai_status_port_enabled": False,
    "ai_status_port": 38472,
    "ai_status_token": "",
    "chat_integration_enabled": False,
    "chat_integration_overlay_enabled": True,
    "chat_integration_include_context": True,
    "chat_integration_port": 38473,
    "chat_integration_token": "",
    "tts_enabled": False,
    "tts_api_url": "http://127.0.0.1:9880/",
    "tts_language": "Chinese",
    "tts_reference_character": "",
    "tts_streaming": True,
    "tts_temperature": 0.9,
    "tts_translate_to_selected_language": True,
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
    default_motion = str(profile.get("default_motion", "")).strip()
    default_expression = str(profile.get("default_expression", "")).strip()
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


def _int_value(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_web_search_engine(value) -> str:
    engine = str(value or "").strip().lower()
    return engine if engine in {"bing", "bing_cn", "google", "duckduckgo", "baidu"} else "bing_cn"


def _normalize_llm_api_profile(profile) -> dict | None:
    if not isinstance(profile, dict):
        return None
    name = str(profile.get("name", "")).strip()
    if not name:
        return None
    api_mode = str(profile.get("llm_api_mode", "chat_completions"))
    if api_mode not in ("chat_completions", "responses"):
        api_mode = "chat_completions"
    return {
        "name": name,
        "llm_api_url": str(profile.get("llm_api_url", "")).strip(),
        "llm_api_key": str(profile.get("llm_api_key", "")).strip(),
        "llm_model_id": str(profile.get("llm_model_id", "")).strip(),
        "llm_aux_api_url": str(profile.get("llm_aux_api_url", "")).strip(),
        "llm_aux_api_key": str(profile.get("llm_aux_api_key", "")).strip(),
        "llm_aux_model_id": str(profile.get("llm_aux_model_id", "")).strip(),
        "llm_aux_enable_thinking": profile.get("llm_aux_enable_thinking", None)
        if profile.get("llm_aux_enable_thinking", None) in (True, False, None) else None,
        "llm_aux_vision_fallback_enabled": bool(profile.get("llm_aux_vision_fallback_enabled", False)),
        "llm_api_mode": api_mode,
        "llm_web_search_enabled": bool(profile.get("llm_web_search_enabled", False)),
        "llm_web_search_engine": _normalize_web_search_engine(
            profile.get("llm_web_search_engine", DEFAULTS["llm_web_search_engine"])
        ),
        "llm_web_search_show_sources": bool(profile.get("llm_web_search_show_sources", True)),
        "llm_enable_thinking": profile.get("llm_enable_thinking", None)
        if profile.get("llm_enable_thinking", None) in (True, False, None) else None,
        "llm_show_reasoning": bool(profile.get("llm_show_reasoning", True)),
    }


def _merge_builtin_llm_api_profiles(profiles: list[dict]) -> list[dict]:
    by_name = {profile["name"]: idx for idx, profile in enumerate(profiles)}
    for preset in BUILTIN_LLM_API_PROFILES:
        normalized = _normalize_llm_api_profile(preset)
        if not normalized:
            continue
        idx = by_name.get(normalized["name"])
        if idx is None:
            by_name[normalized["name"]] = len(profiles)
            profiles.append(normalized)
            continue
        api_key = profiles[idx].get("llm_api_key", "")
        aux_api_url = profiles[idx].get("llm_aux_api_url", "")
        aux_api_key = profiles[idx].get("llm_aux_api_key", "")
        profiles[idx].update(normalized)
        profiles[idx]["llm_api_key"] = api_key
        profiles[idx]["llm_aux_api_url"] = aux_api_url
        profiles[idx]["llm_aux_api_key"] = aux_api_key
    return profiles


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
                    loaded_data = json.load(f)
                loaded = loaded_data if isinstance(loaded_data, dict) else None
                has_action_settings = loaded is not None and "model_action_settings" in loaded
                if loaded is None:
                    raise ValueError("config root must be a JSON object")
                for k in DEFAULTS:
                    if k in loaded:
                        self._data[k] = loaded[k]
            except (json.JSONDecodeError, OSError, ValueError):
                pass
        if loaded is None or not has_action_settings:
            self._data["model_action_settings"] = {}
        self._normalize_model_action_settings()
        self._normalize_models()
        if not has_action_settings:
            self._seed_model_action_settings_from_models()
        if not isinstance(self._data.get("chat_avatar_paths"), dict):
            self._data["chat_avatar_paths"] = {}
        self._data["user_avatar_path"] = str(self._data.get("user_avatar_path", "")).strip()
        self._normalize_llm_api_profiles()
        self._normalize_mcp_servers()
        self._normalize_computer_use_settings()
        self._data["llm_web_search_engine"] = _normalize_web_search_engine(
            self._data.get("llm_web_search_engine", DEFAULTS["llm_web_search_engine"])
        )
        if self._data.get("user_avatar_color") == "#2aabee":
            self._data["user_avatar_color"] = BANDORI_PRIMARY

    def _normalize_llm_api_profiles(self):
        profiles = self._data.get("llm_api_profiles", [])
        if not isinstance(profiles, list):
            profiles = []
        normalized = []
        seen = set()
        for profile in profiles:
            item = _normalize_llm_api_profile(profile)
            if not item:
                continue
            name = item["name"]
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(item)
        normalized = _merge_builtin_llm_api_profiles(normalized)
        self._data["llm_api_profiles"] = normalized
        active = str(self._data.get("llm_active_api_profile", "")).strip()
        names = {profile["name"] for profile in normalized}
        self._data["llm_active_api_profile"] = active if active in names else ""

    def _normalize_mcp_servers(self):
        servers = self._data.get("llm_mcp_servers", [])
        if not isinstance(servers, list):
            self._data["llm_mcp_servers"] = []
            return
        normalized = []
        seen = set()
        for item in servers:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "") or item.get("server_label", "")).strip()
            if not label or label in seen:
                continue
            seen.add(label)
            transport = str(item.get("transport", "stdio")).strip().lower()
            if transport not in ("stdio", "http", "native"):
                transport = "stdio"
            allowed_tools = item.get("allowed_tools", [])
            if isinstance(allowed_tools, str):
                allowed_tools = [part.strip() for part in allowed_tools.split(",") if part.strip()]
            elif isinstance(allowed_tools, list):
                allowed_tools = [str(part or "").strip() for part in allowed_tools if str(part or "").strip()]
            else:
                allowed_tools = []
            args = item.get("args", [])
            if isinstance(args, str):
                args = [part for part in args.split(" ") if part]
            elif isinstance(args, list):
                args = [str(part or "") for part in args if str(part or "")]
            else:
                args = []
            require_approval = str(item.get("require_approval", "always")).strip().lower()
            if require_approval not in ("always", "never"):
                require_approval = "always"
            normalized.append({
                "enabled": bool(item.get("enabled", True)),
                "label": label,
                "description": str(item.get("description", "")).strip(),
                "transport": transport,
                "command": str(item.get("command", "")).strip(),
                "args": args,
                "cwd": str(item.get("cwd", "")).strip(),
                "url": str(item.get("url", "") or item.get("server_url", "")).strip(),
                "connector_id": str(item.get("connector_id", "")).strip(),
                "authorization": str(item.get("authorization", "")).strip(),
                "allowed_tools": allowed_tools,
                "require_approval": require_approval,
                "timeout_seconds": max(3, min(120, _int_value(item.get("timeout_seconds", 30), 30))),
            })
        self._data["llm_mcp_servers"] = normalized

    def _normalize_computer_use_settings(self):
        self._data["computer_use_max_screenshot_width"] = max(
            640,
            min(1920, _int_value(self._data.get("computer_use_max_screenshot_width", 1280), 1280)),
        )
        for key in (
            "llm_hide_tool_call_details",
            "llm_mcp_enabled",
            "llm_mcp_use_native",
            "computer_use_enabled",
            "computer_use_auto_detect",
            "computer_use_send_screenshots",
            "computer_use_allow_screenshot",
            "computer_use_allow_mouse",
            "computer_use_allow_keyboard",
            "computer_use_allow_clipboard",
            "computer_use_allow_wait",
        ):
            self._data[key] = bool(self._data.get(key, DEFAULTS.get(key, False)))

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
            entry = {**MODEL_DEFAULTS, **item}
            if item.get("pet_mode") not in {"live2d", "pixel"}:
                if (
                    character == self._data.get("character", "")
                    and costume == self._data.get("costume", "")
                    and self._data.get("pet_mode") in {"live2d", "pixel"}
                ):
                    entry["pet_mode"] = self._data.get("pet_mode")
                else:
                    entry["pet_mode"] = MODEL_DEFAULTS["pet_mode"]
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
            os.replace(tmp_path, self._path)
        except Exception:
            os.unlink(tmp_path)
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
