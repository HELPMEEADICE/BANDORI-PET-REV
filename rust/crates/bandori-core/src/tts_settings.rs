use crate::config::{ConfigDocument, ConfigError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use thiserror::Error;

const DEFAULT_API_URL: &str = "http://127.0.0.1:9880/";
const MAX_API_URL_BYTES: usize = 2048;
const MAX_REFERENCE_CHARACTER_BYTES: usize = 128;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NativeTtsSettings {
    pub enabled: bool,
    pub api_url: String,
    pub language: String,
    pub reference_character: String,
    pub streaming: bool,
    pub temperature: f64,
    pub translate_to_selected_language: bool,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeTtsSettingsUpdate {
    enabled: bool,
    api_url: String,
    language: String,
    reference_character: String,
    streaming: bool,
    temperature: f64,
    translate_to_selected_language: bool,
}

#[derive(Debug, Error)]
pub enum NativeTtsSettingsError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("TTS settings JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("TTS API URL must be an HTTP or HTTPS URL no longer than {MAX_API_URL_BYTES} bytes")]
    InvalidApiUrl,
    #[error("unsupported TTS language: {0}")]
    UnsupportedLanguage(String),
    #[error("TTS reference character is not a safe file name")]
    InvalidReferenceCharacter,
    #[error("TTS temperature must be a finite number")]
    InvalidTemperature,
}

pub fn load_native_tts_settings(
    config_path: impl AsRef<Path>,
) -> Result<NativeTtsSettings, NativeTtsSettingsError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(NativeTtsSettings::from_config(&config))
}

pub fn save_native_tts_settings(
    config_path: impl AsRef<Path>,
    settings_json: &str,
) -> Result<NativeTtsSettings, NativeTtsSettingsError> {
    let update: NativeTtsSettingsUpdate = serde_json::from_str(settings_json)?;
    let normalized = update.normalize()?;
    let mut config = ConfigDocument::load(config_path.as_ref())?;
    config.set("tts_enabled", Value::Bool(normalized.enabled));
    config.set("tts_api_url", Value::String(normalized.api_url.clone()));
    config.set("tts_language", Value::String(normalized.language.clone()));
    config.set(
        "tts_reference_character",
        Value::String(normalized.reference_character.clone()),
    );
    config.set("tts_streaming", Value::Bool(normalized.streaming));
    config.set("tts_temperature", Value::from(normalized.temperature));
    config.set(
        "tts_translate_to_selected_language",
        Value::Bool(normalized.translate_to_selected_language),
    );
    config.save(config_path)?;
    Ok(normalized)
}

impl NativeTtsSettings {
    pub fn from_config(config: &ConfigDocument) -> Self {
        let language = string_value(config, "tts_language", "Chinese");
        Self {
            enabled: bool_value(config, "tts_enabled", false),
            api_url: normalized_api_url(&string_value(config, "tts_api_url", DEFAULT_API_URL))
                .unwrap_or_else(|| DEFAULT_API_URL.into()),
            language: supported_language(&language).unwrap_or("Chinese").into(),
            reference_character: safe_reference_character(&string_value(
                config,
                "tts_reference_character",
                "",
            ))
            .unwrap_or_default(),
            streaming: bool_value(config, "tts_streaming", true),
            temperature: float_value(config, "tts_temperature", 0.9).clamp(0.01, 2.0),
            translate_to_selected_language: bool_value(
                config,
                "tts_translate_to_selected_language",
                true,
            ),
        }
    }
}

impl NativeTtsSettingsUpdate {
    fn normalize(self) -> Result<NativeTtsSettings, NativeTtsSettingsError> {
        let api_url =
            normalized_api_url(&self.api_url).ok_or(NativeTtsSettingsError::InvalidApiUrl)?;
        let language = supported_language(self.language.trim())
            .ok_or_else(|| NativeTtsSettingsError::UnsupportedLanguage(self.language.clone()))?;
        let reference_character = safe_reference_character(&self.reference_character)
            .ok_or(NativeTtsSettingsError::InvalidReferenceCharacter)?;
        if !self.temperature.is_finite() {
            return Err(NativeTtsSettingsError::InvalidTemperature);
        }
        Ok(NativeTtsSettings {
            enabled: self.enabled,
            api_url,
            language: language.into(),
            reference_character,
            streaming: self.streaming,
            temperature: self.temperature.clamp(0.01, 2.0),
            translate_to_selected_language: self.translate_to_selected_language,
        })
    }
}

fn normalized_api_url(source: &str) -> Option<String> {
    let source = source.trim();
    let source = if source.is_empty() {
        DEFAULT_API_URL
    } else {
        source
    };
    if source.len() > MAX_API_URL_BYTES
        || !(source.starts_with("http://") || source.starts_with("https://"))
    {
        return None;
    }
    Some(if source.ends_with('/') {
        source.into()
    } else {
        format!("{source}/")
    })
}

fn supported_language(source: &str) -> Option<&'static str> {
    match source {
        "Chinese" | "zh" | "中文" => Some("Chinese"),
        "Japanese" | "ja" | "日文" => Some("Japanese"),
        "English" | "en" | "英文" => Some("English"),
        _ => None,
    }
}

fn safe_reference_character(source: &str) -> Option<String> {
    let value = source.trim();
    if value.is_empty() {
        return Some(String::new());
    }
    if value.len() > MAX_REFERENCE_CHARACTER_BYTES
        || value == "."
        || value == ".."
        || value
            .chars()
            .any(|character| matches!(character, '/' | '\\' | '\0'))
    {
        return None;
    }
    Some(value.into())
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

fn float_value(config: &ConfigDocument, key: &str, default: f64) -> f64 {
    config.get(key).and_then(Value::as_f64).unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn settings_load_with_compatible_defaults_and_normalization() {
        let config = ConfigDocument::from_value(
            json!({
                "tts_enabled": true,
                "tts_api_url": "http://localhost:9880",
                "tts_language": "ja",
                "tts_reference_character": " ran ",
                "tts_temperature": 9.0
            }),
            true,
        )
        .unwrap();
        let settings = NativeTtsSettings::from_config(&config);
        assert!(settings.enabled);
        assert_eq!(settings.api_url, "http://localhost:9880/");
        assert_eq!(settings.language, "Japanese");
        assert_eq!(settings.reference_character, "ran");
        assert_eq!(settings.temperature, 2.0);
        assert!(settings.streaming);
    }

    #[test]
    fn settings_save_is_whitelisted_bounded_and_preserves_unrelated_secrets() {
        let root = tempdir().unwrap();
        let path = root.path().join("config.json");
        fs::write(
            &path,
            serde_json::to_vec_pretty(&json!({"llm_api_key":"keep-me"})).unwrap(),
        )
        .unwrap();
        let saved = save_native_tts_settings(
            &path,
            r#"{
                "enabled":true,
                "api_url":"http://localhost:9880",
                "language":"English",
                "reference_character":"moca",
                "streaming":false,
                "temperature":0.001,
                "translate_to_selected_language":false
            }"#,
        )
        .unwrap();
        assert_eq!(saved.temperature, 0.01);
        assert_eq!(saved.api_url, "http://localhost:9880/");
        let document: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(document["llm_api_key"], "keep-me");
        assert_eq!(document["tts_reference_character"], "moca");
    }

    #[test]
    fn settings_reject_unknown_keys_urls_languages_and_traversal() {
        let root = tempdir().unwrap();
        let path = root.path().join("config.json");
        let valid = |extra: &str| {
            format!(
                r#"{{"enabled":true,"api_url":"http://localhost/","language":"Chinese","reference_character":"ran","streaming":true,"temperature":0.9,"translate_to_selected_language":true{extra}}}"#
            )
        };
        assert!(save_native_tts_settings(&path, &valid(",\"secret\":true")).is_err());
        assert!(save_native_tts_settings(&path, &valid("")).is_ok());
        assert!(
            save_native_tts_settings(
                &path,
                &valid("").replace("http://localhost/", "file:///tmp")
            )
            .is_err()
        );
        assert!(save_native_tts_settings(&path, &valid("").replace("Chinese", "Klingon")).is_err());
        assert!(save_native_tts_settings(&path, &valid("").replace("ran", "../ran")).is_err());
    }
}
