COMMON_TOOL_CONFIG_KEYS = (
    "llm_hide_tool_call_details",
    "llm_api_url",
    "llm_api_key",
    "llm_model_id",
    "llm_aux_api_url",
    "llm_aux_api_key",
    "llm_aux_model_id",
    "llm_aux_enable_thinking",
    "llm_aux_vision_fallback_enabled",
    "llm_web_search_engine",
    "llm_mcp_enabled",
    "llm_mcp_use_native",
    "llm_mcp_servers",
    "computer_use_enabled",
    "computer_use_auto_detect",
    "computer_use_send_screenshots",
    "computer_use_max_screenshot_width",
    "computer_use_allow_screenshot",
    "computer_use_allow_mouse",
    "computer_use_allow_keyboard",
    "computer_use_allow_clipboard",
    "computer_use_allow_wait",
)

CHAT_TOOL_CONFIG_KEYS = (
    "user_name",
    "user_profiles",
    "active_user_profile",
    "pov_mode",
    "pov_role_character",
)

TTS_CONFIG_KEYS = (
    "tts_api_url",
    "tts_language",
    "tts_reference_character",
    "tts_streaming",
    "tts_temperature",
    "tts_translate_to_selected_language",
    "llm_api_url",
    "llm_api_key",
    "llm_model_id",
    "llm_aux_api_url",
    "llm_aux_api_key",
    "llm_aux_model_id",
    "llm_aux_enable_thinking",
)


def tool_config_snapshot(config, *, include_chat_keys: bool = False, latest_user_text: str | None = None) -> dict:
    if not config:
        return {}
    keys = COMMON_TOOL_CONFIG_KEYS + (CHAT_TOOL_CONFIG_KEYS if include_chat_keys else ())
    snapshot = {key: config.get(key) for key in keys}
    if latest_user_text is not None:
        snapshot["_latest_user_text"] = latest_user_text
    return snapshot


def tts_config_snapshot(config) -> dict:
    return {key: config.get(key, None) for key in TTS_CONFIG_KEYS} if config else {}


def memory_extraction_api_config(config, use_responses_api, chat_completions_api_url) -> tuple[str, str, str]:
    if not config:
        return "", "", ""
    api_url = str(config.get("llm_aux_api_url", "") or "").strip() or str(config.get("llm_api_url", "") or "").strip()
    api_key = str(config.get("llm_aux_api_key", "") or "").strip() or str(config.get("llm_api_key", "") or "").strip()
    model_id = str(config.get("llm_aux_model_id", "") or "").strip() or str(config.get("llm_model_id", "") or "").strip()
    if use_responses_api(api_url):
        api_url = chat_completions_api_url(api_url)
    return api_url, api_key, model_id
