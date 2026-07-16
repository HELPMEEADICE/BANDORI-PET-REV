use crate::config::{ConfigDocument, ConfigError};
use crate::mcp_tools::normalize_mcp_servers;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::Path;
use thiserror::Error;

const MAX_URL_BYTES: usize = 4 * 1024;
const MAX_SECRET_BYTES: usize = 16 * 1024;
const MAX_MODEL_BYTES: usize = 512;
const MAX_SYSTEM_PROMPT_BYTES: usize = 64 * 1024;
const MAX_PROFILE_NAME_BYTES: usize = 80;
const MAX_PROFILE_COUNT: usize = 64;
const LLM_PROFILE_KEYS: [&str; 21] = [
    "llm_api_url",
    "llm_api_key",
    "llm_model_id",
    "llm_aux_api_url",
    "llm_aux_api_key",
    "llm_aux_model_id",
    "llm_aux_enable_thinking",
    "llm_aux_vision_fallback_enabled",
    "llm_live2d_outfit_recognition_enabled",
    "llm_api_mode",
    "llm_web_search_enabled",
    "llm_web_search_engine",
    "llm_web_search_show_sources",
    "llm_web_fetch_enabled",
    "llm_auto_continue_enabled",
    "llm_auto_continue_max_turns",
    "llm_chat_history_message_limit",
    "llm_compact_history_message_limit",
    "llm_cross_chat_history_enabled",
    "llm_enable_thinking",
    "llm_show_reasoning",
];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeLlmProfileSummary {
    pub name: String,
    pub api_url: String,
    pub api_key_configured: bool,
    pub model_id: String,
    pub aux_model_id: String,
    pub api_mode: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeLlmSettingsState {
    pub api_url: String,
    pub api_key_configured: bool,
    pub model_id: String,
    pub api_mode: String,
    pub enable_thinking: Option<bool>,
    pub aux_api_url: String,
    pub aux_api_key_configured: bool,
    pub aux_model_id: String,
    pub aux_enable_thinking: Option<bool>,
    pub aux_vision_fallback_enabled: bool,
    pub live2d_outfit_recognition_enabled: bool,
    pub chat_history_message_limit: i64,
    pub compact_history_message_limit: i64,
    pub cross_chat_history_enabled: bool,
    pub web_search_enabled: bool,
    pub web_search_engine: String,
    pub web_search_show_sources: bool,
    pub web_fetch_enabled: bool,
    pub mcp_enabled: bool,
    pub mcp_use_native: bool,
    pub mcp_servers: Vec<Value>,
    pub computer_use_enabled: bool,
    pub computer_use_auto_detect: bool,
    pub computer_use_send_screenshots: bool,
    pub computer_use_max_screenshot_width: i64,
    pub computer_use_allow_screenshot: bool,
    pub computer_use_allow_mouse: bool,
    pub computer_use_allow_keyboard: bool,
    pub computer_use_allow_clipboard: bool,
    pub computer_use_allow_wait: bool,
    pub custom_system_prompt_enabled: bool,
    pub custom_system_prompt: String,
    pub active_api_profile: String,
    pub profiles: Vec<NativeLlmProfileSummary>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeLlmSettingsUpdate {
    pub api_url: String,
    #[serde(default)]
    pub api_key: Option<String>,
    #[serde(default)]
    pub clear_api_key: bool,
    pub model_id: String,
    pub api_mode: String,
    pub enable_thinking: Option<bool>,
    pub aux_api_url: String,
    #[serde(default)]
    pub aux_api_key: Option<String>,
    #[serde(default)]
    pub clear_aux_api_key: bool,
    pub aux_model_id: String,
    pub aux_enable_thinking: Option<bool>,
    pub aux_vision_fallback_enabled: bool,
    pub live2d_outfit_recognition_enabled: bool,
    pub chat_history_message_limit: i64,
    pub compact_history_message_limit: i64,
    pub cross_chat_history_enabled: bool,
    pub web_search_enabled: bool,
    pub web_search_engine: String,
    pub web_search_show_sources: bool,
    pub web_fetch_enabled: bool,
    pub mcp_enabled: bool,
    pub mcp_use_native: bool,
    pub mcp_servers: Vec<Value>,
    pub computer_use_enabled: bool,
    pub computer_use_auto_detect: bool,
    pub computer_use_send_screenshots: bool,
    pub computer_use_max_screenshot_width: i64,
    pub computer_use_allow_screenshot: bool,
    pub computer_use_allow_mouse: bool,
    pub computer_use_allow_keyboard: bool,
    pub computer_use_allow_clipboard: bool,
    pub computer_use_allow_wait: bool,
    pub custom_system_prompt_enabled: bool,
    pub custom_system_prompt: String,
}

#[derive(Debug, Error)]
pub enum NativeLlmSettingsError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("native LLM settings JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native LLM settings are invalid: {0}")]
    Invalid(String),
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum NativeLlmProfileMutation {
    ApplyProfile { name: String },
    SaveCurrentProfile { name: String },
    DeleteProfile { name: String },
}

pub fn load_native_llm_settings(
    config_path: &Path,
) -> Result<NativeLlmSettingsState, NativeLlmSettingsError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(NativeLlmSettingsState::from_config(&config))
}

pub fn save_native_llm_settings(
    config_path: &Path,
    settings_json: &str,
    max_bytes: usize,
) -> Result<NativeLlmSettingsState, NativeLlmSettingsError> {
    if settings_json.len() > max_bytes {
        return Err(NativeLlmSettingsError::Invalid(format!(
            "settings exceed the {max_bytes} byte limit"
        )));
    }
    let update = serde_json::from_str::<NativeLlmSettingsUpdate>(settings_json)?;
    let mut config = ConfigDocument::load(config_path)?;
    update.apply_to(&mut config)?;
    config.save(config_path)?;
    Ok(NativeLlmSettingsState::from_config(&config))
}

pub fn mutate_native_llm_profiles(
    config_path: &Path,
    command_json: &str,
    max_bytes: usize,
) -> Result<NativeLlmSettingsState, NativeLlmSettingsError> {
    if command_json.len() > max_bytes {
        return Err(NativeLlmSettingsError::Invalid(format!(
            "profile command exceeds the {max_bytes} byte limit"
        )));
    }
    let command = serde_json::from_str::<NativeLlmProfileMutation>(command_json)?;
    let mut config = ConfigDocument::load(config_path)?;
    let mut profiles = normalized_profiles(&config);
    match command {
        NativeLlmProfileMutation::ApplyProfile { name } => {
            let name = checked_profile_name(&name)?;
            let profile = profiles
                .iter()
                .find(|profile| profile.get("name").and_then(Value::as_str) == Some(&name))
                .cloned()
                .ok_or_else(|| {
                    NativeLlmSettingsError::Invalid(
                        "selected LLM profile does not exist".to_owned(),
                    )
                })?;
            let defaults = ConfigDocument::default();
            for key in LLM_PROFILE_KEYS {
                let value = profile
                    .get(key)
                    .cloned()
                    .or_else(|| defaults.get(key).cloned())
                    .unwrap_or(Value::Null);
                config.set(key, value);
            }
            config.set("llm_active_api_profile", Value::String(name));
        }
        NativeLlmProfileMutation::SaveCurrentProfile { name } => {
            let name = checked_profile_name(&name)?;
            profiles.retain(|profile| {
                profile.get("name").and_then(Value::as_str) != Some(name.as_str())
            });
            if profiles.len() >= MAX_PROFILE_COUNT {
                return Err(NativeLlmSettingsError::Invalid(format!(
                    "at most {MAX_PROFILE_COUNT} LLM profiles can be saved"
                )));
            }
            let mut profile = Map::new();
            profile.insert("name".to_owned(), Value::String(name.clone()));
            for key in LLM_PROFILE_KEYS {
                profile.insert(
                    key.to_owned(),
                    config.get(key).cloned().unwrap_or(Value::Null),
                );
            }
            profiles.push(profile);
            config.set("llm_active_api_profile", Value::String(name));
        }
        NativeLlmProfileMutation::DeleteProfile { name } => {
            let name = checked_profile_name(&name)?;
            let previous = profiles.len();
            profiles.retain(|profile| {
                profile.get("name").and_then(Value::as_str) != Some(name.as_str())
            });
            if profiles.len() == previous {
                return Err(NativeLlmSettingsError::Invalid(
                    "selected LLM profile does not exist".to_owned(),
                ));
            }
            if config.get("llm_active_api_profile").and_then(Value::as_str) == Some(name.as_str()) {
                config.set("llm_active_api_profile", Value::String(String::new()));
            }
        }
    }
    config.set(
        "llm_api_profiles",
        Value::Array(profiles.into_iter().map(Value::Object).collect()),
    );
    config.save(config_path)?;
    Ok(NativeLlmSettingsState::from_config(&config))
}

impl NativeLlmSettingsState {
    pub fn from_config(config: &ConfigDocument) -> Self {
        Self {
            api_url: config_string(config, "llm_api_url"),
            api_key_configured: !config_string(config, "llm_api_key").is_empty(),
            model_id: config_string(config, "llm_model_id"),
            api_mode: normalized_api_mode(&config_string(config, "llm_api_mode")),
            enable_thinking: config.get("llm_enable_thinking").and_then(Value::as_bool),
            aux_api_url: config_string(config, "llm_aux_api_url"),
            aux_api_key_configured: !config_string(config, "llm_aux_api_key").is_empty(),
            aux_model_id: config_string(config, "llm_aux_model_id"),
            aux_enable_thinking: config
                .get("llm_aux_enable_thinking")
                .and_then(Value::as_bool),
            aux_vision_fallback_enabled: config_bool(
                config,
                "llm_aux_vision_fallback_enabled",
                false,
            ),
            live2d_outfit_recognition_enabled: config_bool(
                config,
                "llm_live2d_outfit_recognition_enabled",
                false,
            ),
            chat_history_message_limit: history_limit(config, "llm_chat_history_message_limit", 40),
            compact_history_message_limit: history_limit(
                config,
                "llm_compact_history_message_limit",
                12,
            ),
            cross_chat_history_enabled: config_bool(config, "llm_cross_chat_history_enabled", true),
            web_search_enabled: config_bool(config, "llm_web_search_enabled", false),
            web_search_engine: normalized_web_search_engine(&config_string(
                config,
                "llm_web_search_engine",
            )),
            web_search_show_sources: config_bool(config, "llm_web_search_show_sources", true),
            web_fetch_enabled: config_bool(config, "llm_web_fetch_enabled", false),
            mcp_enabled: config_bool(config, "llm_mcp_enabled", false),
            mcp_use_native: config_bool(config, "llm_mcp_use_native", true),
            mcp_servers: config
                .get("llm_mcp_servers")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default(),
            computer_use_enabled: config_bool(config, "computer_use_enabled", false),
            computer_use_auto_detect: config_bool(config, "computer_use_auto_detect", true),
            computer_use_send_screenshots: config_bool(
                config,
                "computer_use_send_screenshots",
                true,
            ),
            computer_use_max_screenshot_width: config
                .get("computer_use_max_screenshot_width")
                .and_then(Value::as_i64)
                .unwrap_or(1280)
                .clamp(640, 1920),
            computer_use_allow_screenshot: config_bool(
                config,
                "computer_use_allow_screenshot",
                true,
            ),
            computer_use_allow_mouse: config_bool(config, "computer_use_allow_mouse", false),
            computer_use_allow_keyboard: config_bool(config, "computer_use_allow_keyboard", false),
            computer_use_allow_clipboard: config_bool(
                config,
                "computer_use_allow_clipboard",
                false,
            ),
            computer_use_allow_wait: config_bool(config, "computer_use_allow_wait", true),
            custom_system_prompt_enabled: config_bool(
                config,
                "llm_custom_system_prompt_enabled",
                true,
            ),
            custom_system_prompt: config_string(config, "llm_custom_system_prompt"),
            active_api_profile: config_string(config, "llm_active_api_profile"),
            profiles: profile_summaries(config),
        }
    }
}

impl NativeLlmSettingsUpdate {
    pub fn apply_to(self, config: &mut ConfigDocument) -> Result<(), NativeLlmSettingsError> {
        let api_url = checked_url(&self.api_url, "primary API URL")?;
        let aux_api_url = checked_url(&self.aux_api_url, "auxiliary API URL")?;
        let model_id = checked_text(&self.model_id, MAX_MODEL_BYTES, "primary model ID")?;
        let aux_model_id = checked_text(&self.aux_model_id, MAX_MODEL_BYTES, "auxiliary model ID")?;
        let api_mode = normalized_api_mode_checked(&self.api_mode)?;
        let web_search_engine = normalized_web_search_engine_checked(&self.web_search_engine)?;
        let mcp_servers = normalize_mcp_servers(&Value::Array(self.mcp_servers))
            .map_err(NativeLlmSettingsError::Invalid)?;
        let custom_system_prompt = checked_prompt(&self.custom_system_prompt)?;

        config.set("llm_api_url", Value::String(api_url));
        apply_secret(
            config,
            "llm_api_key",
            self.api_key,
            self.clear_api_key,
            "primary API key",
        )?;
        config.set("llm_model_id", Value::String(model_id));
        config.set("llm_api_mode", Value::String(api_mode));
        config.set(
            "llm_enable_thinking",
            self.enable_thinking.map(Value::Bool).unwrap_or(Value::Null),
        );
        config.set("llm_aux_api_url", Value::String(aux_api_url));
        apply_secret(
            config,
            "llm_aux_api_key",
            self.aux_api_key,
            self.clear_aux_api_key,
            "auxiliary API key",
        )?;
        config.set("llm_aux_model_id", Value::String(aux_model_id));
        config.set(
            "llm_aux_enable_thinking",
            self.aux_enable_thinking
                .map(Value::Bool)
                .unwrap_or(Value::Null),
        );
        config.set(
            "llm_aux_vision_fallback_enabled",
            Value::Bool(self.aux_vision_fallback_enabled),
        );
        config.set(
            "llm_live2d_outfit_recognition_enabled",
            Value::Bool(self.live2d_outfit_recognition_enabled),
        );
        config.set(
            "llm_chat_history_message_limit",
            Value::from(normalize_history_limit(self.chat_history_message_limit)),
        );
        config.set(
            "llm_compact_history_message_limit",
            Value::from(normalize_history_limit(self.compact_history_message_limit)),
        );
        config.set(
            "llm_cross_chat_history_enabled",
            Value::Bool(self.cross_chat_history_enabled),
        );
        config.set(
            "llm_web_search_enabled",
            Value::Bool(self.web_search_enabled),
        );
        config.set("llm_web_search_engine", Value::String(web_search_engine));
        config.set(
            "llm_web_search_show_sources",
            Value::Bool(self.web_search_show_sources),
        );
        config.set("llm_web_fetch_enabled", Value::Bool(self.web_fetch_enabled));
        config.set("llm_mcp_enabled", Value::Bool(self.mcp_enabled));
        config.set("llm_mcp_use_native", Value::Bool(self.mcp_use_native));
        config.set("llm_mcp_servers", Value::Array(mcp_servers));
        config.set(
            "computer_use_enabled",
            Value::Bool(self.computer_use_enabled),
        );
        config.set(
            "computer_use_auto_detect",
            Value::Bool(self.computer_use_auto_detect),
        );
        config.set(
            "computer_use_send_screenshots",
            Value::Bool(self.computer_use_send_screenshots),
        );
        config.set(
            "computer_use_max_screenshot_width",
            Value::from(self.computer_use_max_screenshot_width.clamp(640, 1920)),
        );
        config.set(
            "computer_use_allow_screenshot",
            Value::Bool(self.computer_use_allow_screenshot),
        );
        config.set(
            "computer_use_allow_mouse",
            Value::Bool(self.computer_use_allow_mouse),
        );
        config.set(
            "computer_use_allow_keyboard",
            Value::Bool(self.computer_use_allow_keyboard),
        );
        config.set(
            "computer_use_allow_clipboard",
            Value::Bool(self.computer_use_allow_clipboard),
        );
        config.set(
            "computer_use_allow_wait",
            Value::Bool(self.computer_use_allow_wait),
        );
        config.set(
            "llm_custom_system_prompt_enabled",
            Value::Bool(self.custom_system_prompt_enabled),
        );
        config.set(
            "llm_custom_system_prompt",
            Value::String(custom_system_prompt),
        );
        // Applying an edited current configuration intentionally detaches it
        // from any named Python profile without mutating the saved profiles.
        config.set("llm_active_api_profile", Value::String(String::new()));
        Ok(())
    }
}

fn apply_secret(
    config: &mut ConfigDocument,
    key: &str,
    replacement: Option<String>,
    clear: bool,
    label: &str,
) -> Result<(), NativeLlmSettingsError> {
    if clear {
        config.set(key, Value::String(String::new()));
        return Ok(());
    }
    let Some(replacement) = replacement else {
        return Ok(());
    };
    let replacement = replacement.trim();
    if replacement.is_empty() {
        return Ok(());
    }
    if replacement.len() > MAX_SECRET_BYTES || replacement.chars().any(char::is_control) {
        return Err(NativeLlmSettingsError::Invalid(format!(
            "{label} is too long or contains control characters"
        )));
    }
    config.set(key, Value::String(replacement.to_owned()));
    Ok(())
}

fn checked_profile_name(value: &str) -> Result<String, NativeLlmSettingsError> {
    let value = value.trim();
    if value.is_empty()
        || value.len() > MAX_PROFILE_NAME_BYTES
        || value.chars().any(char::is_control)
    {
        Err(NativeLlmSettingsError::Invalid(
            "LLM profile name is empty, too long, or contains control characters".to_owned(),
        ))
    } else {
        Ok(value.to_owned())
    }
}

fn normalized_profiles(config: &ConfigDocument) -> Vec<Map<String, Value>> {
    let mut result: Vec<Map<String, Value>> = Vec::new();
    for value in config
        .get("llm_api_profiles")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let Some(profile) = value.as_object() else {
            continue;
        };
        let Some(name) = profile.get("name").and_then(Value::as_str) else {
            continue;
        };
        let Ok(name) = checked_profile_name(name) else {
            continue;
        };
        if result
            .iter()
            .any(|saved| saved.get("name").and_then(Value::as_str) == Some(name.as_str()))
        {
            continue;
        }
        let mut normalized = profile.clone();
        normalized.insert("name".to_owned(), Value::String(name));
        result.push(normalized);
        if result.len() >= MAX_PROFILE_COUNT {
            break;
        }
    }
    result
}

fn profile_summaries(config: &ConfigDocument) -> Vec<NativeLlmProfileSummary> {
    normalized_profiles(config)
        .into_iter()
        .map(|profile| NativeLlmProfileSummary {
            name: profile_string(&profile, "name"),
            api_url: profile_string(&profile, "llm_api_url"),
            api_key_configured: !profile_string(&profile, "llm_api_key").is_empty(),
            model_id: profile_string(&profile, "llm_model_id"),
            aux_model_id: profile_string(&profile, "llm_aux_model_id"),
            api_mode: normalized_api_mode(&profile_string(&profile, "llm_api_mode")),
        })
        .collect()
}

fn profile_string(profile: &Map<String, Value>, key: &str) -> String {
    profile
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn checked_url(value: &str, label: &str) -> Result<String, NativeLlmSettingsError> {
    let value = value.trim();
    if value.len() > MAX_URL_BYTES || value.chars().any(char::is_control) {
        return Err(NativeLlmSettingsError::Invalid(format!(
            "{label} is too long or contains control characters"
        )));
    }
    if !value.is_empty()
        && !value.to_ascii_lowercase().starts_with("http://")
        && !value.to_ascii_lowercase().starts_with("https://")
    {
        return Err(NativeLlmSettingsError::Invalid(format!(
            "{label} must use http:// or https://"
        )));
    }
    Ok(value.to_owned())
}

fn checked_text(
    value: &str,
    max_bytes: usize,
    label: &str,
) -> Result<String, NativeLlmSettingsError> {
    let value = value.trim();
    if value.len() > max_bytes || value.chars().any(char::is_control) {
        return Err(NativeLlmSettingsError::Invalid(format!(
            "{label} is too long or contains control characters"
        )));
    }
    Ok(value.to_owned())
}

fn checked_prompt(value: &str) -> Result<String, NativeLlmSettingsError> {
    let value = value.trim();
    if value.len() > MAX_SYSTEM_PROMPT_BYTES {
        return Err(NativeLlmSettingsError::Invalid(
            "custom system prompt is too long".to_owned(),
        ));
    }
    Ok(value.to_owned())
}

fn normalized_api_mode(value: &str) -> String {
    match value.trim().to_ascii_lowercase().as_str() {
        "responses" => "responses".to_owned(),
        _ => "chat_completions".to_owned(),
    }
}

fn normalized_api_mode_checked(value: &str) -> Result<String, NativeLlmSettingsError> {
    let value = value.trim().to_ascii_lowercase();
    if matches!(value.as_str(), "chat_completions" | "responses") {
        Ok(value)
    } else {
        Err(NativeLlmSettingsError::Invalid(format!(
            "unsupported API mode: {value}"
        )))
    }
}

fn normalized_web_search_engine(value: &str) -> String {
    match value.trim().to_ascii_lowercase().as_str() {
        "bing" => "bing",
        "google" => "google",
        "duckduckgo" => "duckduckgo",
        "baidu" => "baidu",
        _ => "bing_cn",
    }
    .to_owned()
}

fn normalized_web_search_engine_checked(value: &str) -> Result<String, NativeLlmSettingsError> {
    let value = value.trim().to_ascii_lowercase();
    if matches!(
        value.as_str(),
        "bing" | "bing_cn" | "google" | "duckduckgo" | "baidu"
    ) {
        Ok(value)
    } else {
        Err(NativeLlmSettingsError::Invalid(format!(
            "unsupported web search engine: {value}"
        )))
    }
}

fn normalize_history_limit(value: i64) -> i64 {
    if value == 0 { 0 } else { value.clamp(2, 100) }
}

fn history_limit(config: &ConfigDocument, key: &str, default: i64) -> i64 {
    normalize_history_limit(config.get(key).and_then(Value::as_i64).unwrap_or(default))
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn config_bool(config: &ConfigDocument, key: &str, default: bool) -> bool {
    config.get(key).and_then(Value::as_bool).unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn full_update() -> Value {
        json!({
            "api_url":"http://127.0.0.1:8000/v1/chat/completions",
            "model_id":"local-model",
            "api_mode":"chat_completions",
            "enable_thinking":null,
            "aux_api_url":"",
            "aux_model_id":"small-model",
            "aux_enable_thinking":false,
            "aux_vision_fallback_enabled":true,
            "live2d_outfit_recognition_enabled":false,
            "chat_history_message_limit":101,
            "compact_history_message_limit":0,
            "cross_chat_history_enabled":false,
            "web_search_enabled":true,
            "web_search_engine":"duckduckgo",
            "web_search_show_sources":false,
            "web_fetch_enabled":true,
            "mcp_enabled":true,
            "mcp_use_native":true,
            "mcp_servers":[{
                "enabled":true,
                "label":"fixture",
                "transport":"http",
                "url":"http://127.0.0.1:8765/mcp",
                "require_approval":"never"
            }],
            "computer_use_enabled":true,
            "computer_use_auto_detect":false,
            "computer_use_send_screenshots":true,
            "computer_use_max_screenshot_width":9999,
            "computer_use_allow_screenshot":true,
            "computer_use_allow_mouse":true,
            "computer_use_allow_keyboard":false,
            "computer_use_allow_clipboard":true,
            "computer_use_allow_wait":true,
            "custom_system_prompt_enabled":true,
            "custom_system_prompt":"  Always stay in character.  "
        })
    }

    #[test]
    fn state_is_redacted_and_blank_secret_input_preserves_existing_keys() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.set("llm_api_key", json!("primary-secret"));
        config.set("llm_aux_api_key", json!("aux-secret"));
        config.set("llm_active_api_profile", json!("saved-profile"));
        config.save(&path).unwrap();

        let mut update = full_update();
        update["api_key"] = json!("");
        let state = save_native_llm_settings(&path, &update.to_string(), 128 * 1024).unwrap();
        assert!(state.api_key_configured);
        assert!(state.aux_api_key_configured);
        assert_eq!(state.active_api_profile, "");
        assert_eq!(state.chat_history_message_limit, 100);
        assert_eq!(state.compact_history_message_limit, 0);
        assert!(state.web_search_enabled);
        assert_eq!(state.web_search_engine, "duckduckgo");
        assert!(!state.web_search_show_sources);
        assert!(state.web_fetch_enabled);
        assert!(state.mcp_enabled);
        assert!(state.mcp_use_native);
        assert_eq!(state.mcp_servers.len(), 1);
        assert!(state.computer_use_enabled);
        assert!(!state.computer_use_auto_detect);
        assert_eq!(state.computer_use_max_screenshot_width, 1920);
        assert!(state.computer_use_allow_mouse);
        assert!(!state.computer_use_allow_keyboard);
        let serialized = serde_json::to_string(&state).unwrap();
        assert!(!serialized.contains("primary-secret"));
        assert!(!serialized.contains("aux-secret"));
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(saved.get("llm_api_key"), Some(&json!("primary-secret")));
        assert_eq!(saved.get("llm_aux_api_key"), Some(&json!("aux-secret")));
        assert_eq!(
            saved.get("llm_custom_system_prompt"),
            Some(&json!("Always stay in character."))
        );
    }

    #[test]
    fn explicit_secret_clear_and_replacement_are_distinct_and_bounded() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.set("llm_api_key", json!("old-primary"));
        config.set("llm_aux_api_key", json!("old-aux"));
        config.save(&path).unwrap();

        let mut update = full_update();
        update["clear_api_key"] = json!(true);
        update["aux_api_key"] = json!("new-aux");
        let state = save_native_llm_settings(&path, &update.to_string(), 128 * 1024).unwrap();
        assert!(!state.api_key_configured);
        assert!(state.aux_api_key_configured);
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(saved.get("llm_api_key"), Some(&json!("")));
        assert_eq!(saved.get("llm_aux_api_key"), Some(&json!("new-aux")));

        update["unknown"] = json!(true);
        assert!(save_native_llm_settings(&path, &update.to_string(), 128 * 1024).is_err());
        update.as_object_mut().unwrap().remove("unknown");
        update["api_url"] = json!("file:///secret");
        assert!(save_native_llm_settings(&path, &update.to_string(), 128 * 1024).is_err());
    }

    #[test]
    fn profile_mutations_apply_secrets_without_exposing_them_and_preserve_owned_profiles() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.set(
            "llm_api_profiles",
            json!([
                {
                    "name":"remote",
                    "llm_api_url":"https://example.invalid/v1/chat/completions",
                    "llm_api_key":"profile-secret",
                    "llm_model_id":"remote-model",
                    "llm_api_mode":"chat_completions"
                },
                {"name":"keep","llm_model_id":"keep-model"}
            ]),
        );
        config.save(&path).unwrap();

        let state =
            mutate_native_llm_profiles(&path, r#"{"op":"apply_profile","name":"remote"}"#, 4096)
                .unwrap();
        assert_eq!(state.active_api_profile, "remote");
        assert!(state.api_key_configured);
        assert_eq!(state.model_id, "remote-model");
        assert!(
            !serde_json::to_string(&state)
                .unwrap()
                .contains("profile-secret")
        );
        assert_eq!(
            ConfigDocument::load(&path).unwrap().get("llm_api_key"),
            Some(&json!("profile-secret"))
        );

        let mut config = ConfigDocument::load(&path).unwrap();
        config.set("llm_model_id", json!("edited-model"));
        config.save(&path).unwrap();
        let state = mutate_native_llm_profiles(
            &path,
            r#"{"op":"save_current_profile","name":"edited"}"#,
            4096,
        )
        .unwrap();
        assert_eq!(state.active_api_profile, "edited");
        assert!(state.profiles.iter().any(|profile| profile.name == "keep"));
        assert!(
            state
                .profiles
                .iter()
                .any(|profile| profile.name == "edited" && profile.model_id == "edited-model")
        );

        let state =
            mutate_native_llm_profiles(&path, r#"{"op":"delete_profile","name":"remote"}"#, 4096)
                .unwrap();
        assert!(
            !state
                .profiles
                .iter()
                .any(|profile| profile.name == "remote")
        );
        assert!(
            mutate_native_llm_profiles(&path, r#"{"op":"apply_profile","name":"missing"}"#, 4096,)
                .is_err()
        );
    }
}
