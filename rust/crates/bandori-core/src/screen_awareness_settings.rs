use crate::config::{ConfigDocument, ConfigError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;
use thiserror::Error;

const MIN_INTERVAL_MINUTES: u32 = 5;
const MAX_INTERVAL_MINUTES: u32 = 120;
const MIN_SCREENSHOT_WIDTH: u32 = 640;
const MAX_SCREENSHOT_WIDTH: u32 = 1920;
const MAX_CHARACTER_BYTES: usize = 128;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NativeScreenAwarenessSettings {
    pub enabled: bool,
    pub interval_minutes: u32,
    pub character_mode: String,
    pub character: String,
    pub max_screenshot_width: u32,
    pub model_mode: String,
    pub display_mode: String,
    pub include_process_name: bool,
    pub include_window_title: bool,
}

#[derive(Clone, Debug, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeScreenAwarenessSettingsUpdate {
    enabled: bool,
    interval_minutes: u32,
    character_mode: String,
    character: String,
    max_screenshot_width: u32,
    model_mode: String,
    display_mode: String,
    include_process_name: bool,
    include_window_title: bool,
}

#[derive(Debug, Error)]
pub enum NativeScreenAwarenessSettingsError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("screen-awareness settings JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("unsupported screen-awareness character mode: {0}")]
    UnsupportedCharacterMode(String),
    #[error("screen-awareness fixed character is invalid")]
    InvalidCharacter,
    #[error("unsupported screen-awareness model mode: {0}")]
    UnsupportedModelMode(String),
    #[error("unsupported screen-awareness display mode: {0}")]
    UnsupportedDisplayMode(String),
}

pub fn load_native_screen_awareness_settings(
    config_path: impl AsRef<Path>,
) -> Result<NativeScreenAwarenessSettings, NativeScreenAwarenessSettingsError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(NativeScreenAwarenessSettings::from_config(&config))
}

pub fn save_native_screen_awareness_settings(
    config_path: impl AsRef<Path>,
    settings_json: &str,
) -> Result<NativeScreenAwarenessSettings, NativeScreenAwarenessSettingsError> {
    let update: NativeScreenAwarenessSettingsUpdate = serde_json::from_str(settings_json)?;
    let settings = update.normalize()?;
    let mut config = ConfigDocument::load(config_path.as_ref())?;
    config.set("screen_awareness_enabled", Value::Bool(settings.enabled));
    config.set(
        "screen_awareness_interval_minutes",
        Value::from(settings.interval_minutes),
    );
    config.set(
        "screen_awareness_character_mode",
        Value::String(settings.character_mode.clone()),
    );
    config.set(
        "screen_awareness_character",
        Value::String(settings.character.clone()),
    );
    config.set(
        "screen_awareness_max_screenshot_width",
        Value::from(settings.max_screenshot_width),
    );
    config.set(
        "screen_awareness_model_mode",
        Value::String(settings.model_mode.clone()),
    );
    config.set(
        "screen_awareness_display_mode",
        Value::String(settings.display_mode.clone()),
    );
    config.set(
        "screen_awareness_include_process_name",
        Value::Bool(settings.include_process_name),
    );
    config.set(
        "screen_awareness_include_window_title",
        Value::Bool(settings.include_window_title),
    );
    let mut policy = config
        .get("proactive_care_policy")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    policy.insert(
        "global_cooldown_minutes".into(),
        Value::from(settings.interval_minutes),
    );
    config.set("proactive_care_policy", Value::Object(policy));
    config.save(config_path)?;
    Ok(settings)
}

impl NativeScreenAwarenessSettings {
    pub fn from_config(config: &ConfigDocument) -> Self {
        let interval = config
            .get("proactive_care_policy")
            .and_then(Value::as_object)
            .and_then(|policy| policy.get("global_cooldown_minutes"))
            .and_then(Value::as_u64)
            .or_else(|| {
                config
                    .get("screen_awareness_interval_minutes")
                    .and_then(Value::as_u64)
            })
            .and_then(|value| u32::try_from(value).ok())
            .unwrap_or(30)
            .clamp(MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES);
        let character_mode = supported_character_mode(&string_value(
            config,
            "screen_awareness_character_mode",
            "random_visible",
        ))
        .unwrap_or("random_visible");
        let character = safe_character(&string_value(config, "screen_awareness_character", ""))
            .unwrap_or_default();
        Self {
            enabled: bool_value(config, "screen_awareness_enabled", false),
            interval_minutes: interval,
            character_mode: character_mode.into(),
            character: if character_mode == "fixed" {
                character
            } else {
                String::new()
            },
            max_screenshot_width: integer_value(
                config,
                "screen_awareness_max_screenshot_width",
                1920,
            )
            .clamp(MIN_SCREENSHOT_WIDTH, MAX_SCREENSHOT_WIDTH),
            model_mode: supported_model_mode(&string_value(
                config,
                "screen_awareness_model_mode",
                "main",
            ))
            .unwrap_or("main")
            .into(),
            display_mode: supported_display_mode(&string_value(
                config,
                "screen_awareness_display_mode",
                "floating",
            ))
            .unwrap_or("floating")
            .into(),
            include_process_name: bool_value(config, "screen_awareness_include_process_name", true),
            include_window_title: bool_value(
                config,
                "screen_awareness_include_window_title",
                false,
            ),
        }
    }
}

impl NativeScreenAwarenessSettingsUpdate {
    fn normalize(
        self,
    ) -> Result<NativeScreenAwarenessSettings, NativeScreenAwarenessSettingsError> {
        let character_mode =
            supported_character_mode(self.character_mode.trim()).ok_or_else(|| {
                NativeScreenAwarenessSettingsError::UnsupportedCharacterMode(
                    self.character_mode.clone(),
                )
            })?;
        let character = safe_character(&self.character)
            .ok_or(NativeScreenAwarenessSettingsError::InvalidCharacter)?;
        if character_mode == "fixed" && character.is_empty() {
            return Err(NativeScreenAwarenessSettingsError::InvalidCharacter);
        }
        let model_mode = supported_model_mode(self.model_mode.trim()).ok_or_else(|| {
            NativeScreenAwarenessSettingsError::UnsupportedModelMode(self.model_mode.clone())
        })?;
        let display_mode = supported_display_mode(self.display_mode.trim()).ok_or_else(|| {
            NativeScreenAwarenessSettingsError::UnsupportedDisplayMode(self.display_mode.clone())
        })?;
        Ok(NativeScreenAwarenessSettings {
            enabled: self.enabled,
            interval_minutes: self
                .interval_minutes
                .clamp(MIN_INTERVAL_MINUTES, MAX_INTERVAL_MINUTES),
            character_mode: character_mode.into(),
            character: if character_mode == "fixed" {
                character
            } else {
                String::new()
            },
            max_screenshot_width: self
                .max_screenshot_width
                .clamp(MIN_SCREENSHOT_WIDTH, MAX_SCREENSHOT_WIDTH),
            model_mode: model_mode.into(),
            display_mode: display_mode.into(),
            include_process_name: self.include_process_name,
            include_window_title: self.include_window_title,
        })
    }
}

fn supported_character_mode(source: &str) -> Option<&'static str> {
    match source {
        "random_visible" => Some("random_visible"),
        "default" => Some("default"),
        "fixed" => Some("fixed"),
        _ => None,
    }
}

fn supported_model_mode(source: &str) -> Option<&'static str> {
    match source {
        "main" => Some("main"),
        "aux" => Some("aux"),
        _ => None,
    }
}

fn supported_display_mode(source: &str) -> Option<&'static str> {
    match source {
        "floating" => Some("floating"),
        "system" => Some("system"),
        _ => None,
    }
}

fn safe_character(source: &str) -> Option<String> {
    let value = source.trim();
    (value.len() <= MAX_CHARACTER_BYTES
        && !value.contains(['/', '\\', '\0'])
        && !value.chars().any(char::is_control))
    .then(|| value.to_owned())
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
    fn settings_load_uses_shared_interval_and_privacy_defaults() {
        let config = ConfigDocument::from_value(
            json!({
                "screen_awareness_enabled":true,
                "screen_awareness_interval_minutes":45,
                "proactive_care_policy":{"global_cooldown_minutes":18},
                "screen_awareness_character_mode":"fixed",
                "screen_awareness_character":"ran",
                "screen_awareness_max_screenshot_width":9999,
                "screen_awareness_model_mode":"aux"
            }),
            true,
        )
        .unwrap();
        let settings = NativeScreenAwarenessSettings::from_config(&config);
        assert!(settings.enabled);
        assert_eq!(settings.interval_minutes, 18);
        assert_eq!(settings.character, "ran");
        assert_eq!(settings.max_screenshot_width, 1920);
        assert_eq!(settings.model_mode, "aux");
        assert!(settings.include_process_name);
        assert!(!settings.include_window_title);
    }

    #[test]
    fn settings_save_is_whitelisted_atomic_and_syncs_care_interval() {
        let root = tempdir().unwrap();
        let path = root.path().join("config.json");
        fs::write(&path, br#"{"llm_api_key":"keep"}"#).unwrap();
        let settings = save_native_screen_awareness_settings(
            &path,
            r#"{
                "enabled":true,
                "interval_minutes":7,
                "character_mode":"default",
                "character":"ignored",
                "max_screenshot_width":1280,
                "model_mode":"main",
                "display_mode":"system",
                "include_process_name":false,
                "include_window_title":true
            }"#,
        )
        .unwrap();
        assert!(settings.character.is_empty());
        let document: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(document["llm_api_key"], "keep");
        assert_eq!(document["screen_awareness_interval_minutes"], 7);
        assert_eq!(
            document["proactive_care_policy"]["global_cooldown_minutes"],
            7
        );
    }

    #[test]
    fn settings_reject_unknown_modes_traversal_and_fields() {
        let root = tempdir().unwrap();
        let path = root.path().join("config.json");
        let valid = json!({
            "enabled":true,
            "interval_minutes":30,
            "character_mode":"fixed",
            "character":"ran",
            "max_screenshot_width":1280,
            "model_mode":"main",
            "display_mode":"floating",
            "include_process_name":true,
            "include_window_title":false
        });
        assert!(save_native_screen_awareness_settings(&path, &valid.to_string()).is_ok());
        let mut invalid = valid.clone();
        invalid["character"] = Value::String("../ran".into());
        assert!(save_native_screen_awareness_settings(&path, &invalid.to_string()).is_err());
        let mut invalid = valid;
        invalid["unexpected"] = Value::Bool(true);
        assert!(save_native_screen_awareness_settings(&path, &invalid.to_string()).is_err());
    }
}
