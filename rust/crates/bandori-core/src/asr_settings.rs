use crate::config::{ConfigDocument, ConfigError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use thiserror::Error;

const DEFAULT_API_URL: &str = "http://127.0.0.1:8000/v1/audio/transcriptions";
const DEFAULT_MODEL: &str = "whisper-large-v3";
const MAX_URL_BYTES: usize = 2048;
const MAX_MODEL_BYTES: usize = 256;
const MAX_API_KEY_BYTES: usize = 16 * 1024;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NativeAsrSettings {
    pub enabled: bool,
    pub api_url: String,
    pub has_api_key: bool,
    pub model_id: String,
    pub language: String,
    pub auto_send: bool,
    pub insert_mode: String,
    pub sample_rate: u32,
    pub max_record_seconds: u32,
    pub timeout_seconds: u32,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeAsrSettingsUpdate {
    enabled: bool,
    api_url: String,
    api_key: String,
    clear_api_key: bool,
    model_id: String,
    language: String,
    auto_send: bool,
    insert_mode: String,
    sample_rate: u32,
    max_record_seconds: u32,
    timeout_seconds: u32,
}

#[derive(Debug, Error)]
pub enum NativeAsrSettingsError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("ASR settings JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("ASR API URL is invalid")]
    InvalidApiUrl,
    #[error("ASR model name is invalid")]
    InvalidModel,
    #[error("ASR API key is too long or contains control characters")]
    InvalidApiKey,
    #[error("unsupported ASR language: {0}")]
    UnsupportedLanguage(String),
    #[error("unsupported ASR insertion mode: {0}")]
    UnsupportedInsertMode(String),
}

pub fn load_native_asr_settings(
    config_path: impl AsRef<Path>,
) -> Result<NativeAsrSettings, NativeAsrSettingsError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(NativeAsrSettings::from_config(&config))
}

pub fn save_native_asr_settings(
    config_path: impl AsRef<Path>,
    settings_json: &str,
) -> Result<NativeAsrSettings, NativeAsrSettingsError> {
    let update: NativeAsrSettingsUpdate = serde_json::from_str(settings_json)?;
    let normalized = update.normalize()?;
    let mut config = ConfigDocument::load(config_path.as_ref())?;
    let existing_key = string_value(&config, "asr_api_key", "");
    let api_key = if normalized.clear_api_key {
        String::new()
    } else if normalized.api_key.is_empty() {
        existing_key
    } else {
        normalized.api_key.clone()
    };
    config.set("asr_enabled", Value::Bool(normalized.settings.enabled));
    config.set(
        "asr_api_url",
        Value::String(normalized.settings.api_url.clone()),
    );
    config.set("asr_api_key", Value::String(api_key));
    config.set(
        "asr_model_id",
        Value::String(normalized.settings.model_id.clone()),
    );
    config.set(
        "asr_language",
        Value::String(normalized.settings.language.clone()),
    );
    config.set("asr_auto_send", Value::Bool(normalized.settings.auto_send));
    config.set(
        "asr_insert_mode",
        Value::String(normalized.settings.insert_mode.clone()),
    );
    config.set(
        "asr_sample_rate",
        Value::from(normalized.settings.sample_rate),
    );
    config.set(
        "asr_max_record_seconds",
        Value::from(normalized.settings.max_record_seconds),
    );
    config.set(
        "asr_timeout_seconds",
        Value::from(normalized.settings.timeout_seconds),
    );
    config.save(config_path)?;
    Ok(NativeAsrSettings {
        has_api_key: !config
            .get("asr_api_key")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .is_empty(),
        ..normalized.settings
    })
}

impl NativeAsrSettings {
    pub fn from_config(config: &ConfigDocument) -> Self {
        let language = string_value(config, "asr_language", "zh");
        let insert_mode = string_value(config, "asr_insert_mode", "append");
        Self {
            enabled: bool_value(config, "asr_enabled", false),
            api_url: normalize_api_url(&string_value(config, "asr_api_url", DEFAULT_API_URL))
                .unwrap_or_else(|| DEFAULT_API_URL.into()),
            has_api_key: !string_value(config, "asr_api_key", "").is_empty(),
            model_id: safe_model(&string_value(config, "asr_model_id", DEFAULT_MODEL))
                .unwrap_or_else(|| DEFAULT_MODEL.into()),
            language: supported_language(&language).unwrap_or("zh").into(),
            auto_send: bool_value(config, "asr_auto_send", false),
            insert_mode: supported_insert_mode(&insert_mode)
                .unwrap_or("append")
                .into(),
            sample_rate: integer_value(config, "asr_sample_rate", 16_000).clamp(8_000, 48_000),
            max_record_seconds: integer_value(config, "asr_max_record_seconds", 60).clamp(3, 300),
            timeout_seconds: integer_value(config, "asr_timeout_seconds", 60).clamp(5, 300),
        }
    }
}

struct NormalizedUpdate {
    settings: NativeAsrSettings,
    api_key: String,
    clear_api_key: bool,
}

impl NativeAsrSettingsUpdate {
    fn normalize(self) -> Result<NormalizedUpdate, NativeAsrSettingsError> {
        let api_url =
            normalize_api_url(&self.api_url).ok_or(NativeAsrSettingsError::InvalidApiUrl)?;
        let model_id = safe_model(&self.model_id).ok_or(NativeAsrSettingsError::InvalidModel)?;
        let api_key = self.api_key.trim().to_owned();
        if api_key.len() > MAX_API_KEY_BYTES || api_key.chars().any(char::is_control) {
            return Err(NativeAsrSettingsError::InvalidApiKey);
        }
        let language = supported_language(self.language.trim())
            .ok_or_else(|| NativeAsrSettingsError::UnsupportedLanguage(self.language.clone()))?;
        let insert_mode = supported_insert_mode(self.insert_mode.trim()).ok_or_else(|| {
            NativeAsrSettingsError::UnsupportedInsertMode(self.insert_mode.clone())
        })?;
        Ok(NormalizedUpdate {
            settings: NativeAsrSettings {
                enabled: self.enabled,
                api_url,
                has_api_key: !api_key.is_empty(),
                model_id,
                language: language.into(),
                auto_send: self.auto_send,
                insert_mode: insert_mode.into(),
                sample_rate: self.sample_rate.clamp(8_000, 48_000),
                max_record_seconds: self.max_record_seconds.clamp(3, 300),
                timeout_seconds: self.timeout_seconds.clamp(5, 300),
            },
            api_key,
            clear_api_key: self.clear_api_key,
        })
    }
}

fn normalize_api_url(source: &str) -> Option<String> {
    let source = source.trim();
    let mut source = if source.is_empty() {
        DEFAULT_API_URL.to_owned()
    } else if source.contains("://") {
        source.to_owned()
    } else {
        format!("http://{source}")
    };
    if source.len() > MAX_URL_BYTES
        || source.chars().any(char::is_control)
        || !(source.starts_with("http://") || source.starts_with("https://"))
    {
        return None;
    }
    let scheme_end = source.find("://")? + 3;
    let authority_end = source[scheme_end..]
        .find('/')
        .map(|index| scheme_end + index)
        .unwrap_or(source.len());
    let authority = &source[scheme_end..authority_end];
    if authority.is_empty()
        || authority.contains(['?', '#'])
        || authority.chars().any(char::is_whitespace)
        || source[scheme_end..].starts_with('/')
    {
        return None;
    }
    let path_start = source[scheme_end..]
        .find('/')
        .map(|index| scheme_end + index);
    match path_start {
        None => source.push_str("/v1/audio/transcriptions"),
        Some(index) if &source[index..] == "/" => {
            source.truncate(index);
            source.push_str("/v1/audio/transcriptions");
        }
        Some(index)
            if source[index..]
                .trim_end_matches('/')
                .eq_ignore_ascii_case("/v1") =>
        {
            source.truncate(index);
            source.push_str("/v1/audio/transcriptions");
        }
        Some(index)
            if source[index..]
                .trim_end_matches('/')
                .eq_ignore_ascii_case("/v1/audio") =>
        {
            source.truncate(index);
            source.push_str("/v1/audio/transcriptions");
        }
        Some(_) if source.ends_with('/') => source.push_str("v1/audio/transcriptions"),
        Some(_) => {}
    }
    Some(source)
}

fn safe_model(source: &str) -> Option<String> {
    let value = source.trim();
    (!value.is_empty() && value.len() <= MAX_MODEL_BYTES && !value.chars().any(char::is_control))
        .then(|| value.to_owned())
}

fn supported_language(source: &str) -> Option<&'static str> {
    match source {
        "" => Some(""),
        "zh" | "Chinese" | "中文" => Some("zh"),
        "ja" | "Japanese" | "日文" => Some("ja"),
        "en" | "English" | "英文" => Some("en"),
        _ => None,
    }
}

fn supported_insert_mode(source: &str) -> Option<&'static str> {
    match source {
        "append" => Some("append"),
        "replace" => Some("replace"),
        _ => None,
    }
}

fn string_value(config: &ConfigDocument, key: &str, default: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(default)
        .trim()
        .to_owned()
}

fn bool_value(config: &ConfigDocument, key: &str, default: bool) -> bool {
    config.get(key).and_then(Value::as_bool).unwrap_or(default)
}

fn integer_value(config: &ConfigDocument, key: &str, default: u32) -> u32 {
    config
        .get(key)
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn state_is_redacted_normalized_and_bounded() {
        let config = ConfigDocument::from_value(
            json!({
                "asr_enabled":true,
                "asr_api_url":"localhost:8000",
                "asr_api_key":"secret",
                "asr_model_id":" whisper-large-v3 ",
                "asr_language":"Japanese",
                "asr_insert_mode":"replace",
                "asr_sample_rate":96000,
                "asr_max_record_seconds":999,
                "asr_timeout_seconds":1
            }),
            true,
        )
        .unwrap();
        let state = NativeAsrSettings::from_config(&config);
        assert!(state.has_api_key);
        assert_eq!(
            state.api_url,
            "http://localhost:8000/v1/audio/transcriptions"
        );
        assert_eq!(state.language, "ja");
        assert_eq!(state.sample_rate, 48_000);
        assert_eq!(state.max_record_seconds, 300);
        assert_eq!(state.timeout_seconds, 5);
        assert!(!serde_json::to_string(&state).unwrap().contains("secret"));
    }

    #[test]
    fn blank_key_preserves_secret_and_explicit_clear_removes_it() {
        let root = tempdir().unwrap();
        let path = root.path().join("config.json");
        fs::write(&path, br#"{"asr_api_key":"keep-me","llm_api_key":"other"}"#).unwrap();
        let update = |clear: bool| {
            json!({
                "enabled":true,
                "api_url":"http://localhost:8000",
                "api_key":"",
                "clear_api_key":clear,
                "model_id":"whisper-large-v3",
                "language":"zh",
                "auto_send":false,
                "insert_mode":"append",
                "sample_rate":16000,
                "max_record_seconds":60,
                "timeout_seconds":60
            })
            .to_string()
        };
        let kept = save_native_asr_settings(&path, &update(false)).unwrap();
        assert!(kept.has_api_key);
        let document: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(document["asr_api_key"], "keep-me");
        assert_eq!(document["llm_api_key"], "other");
        let cleared = save_native_asr_settings(&path, &update(true)).unwrap();
        assert!(!cleared.has_api_key);
        let document: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(document["asr_api_key"], "");
    }

    #[test]
    fn invalid_or_unknown_settings_are_rejected_without_rewrite() {
        let root = tempdir().unwrap();
        let path = root.path().join("config.json");
        fs::write(&path, br#"{"sentinel":true}"#).unwrap();
        let invalid = json!({
            "enabled":true,
            "api_url":"file:///tmp",
            "api_key":"",
            "clear_api_key":false,
            "model_id":"whisper-large-v3",
            "language":"zh",
            "auto_send":false,
            "insert_mode":"append",
            "sample_rate":16000,
            "max_record_seconds":60,
            "timeout_seconds":60,
            "unexpected":true
        })
        .to_string();
        assert!(save_native_asr_settings(&path, &invalid).is_err());
        let document: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(document, json!({"sentinel":true}));
    }
}
