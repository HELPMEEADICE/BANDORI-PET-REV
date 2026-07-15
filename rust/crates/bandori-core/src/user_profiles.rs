use crate::config::{ConfigDocument, ConfigError};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::path::Path;
use thiserror::Error;

pub const DEFAULT_USER_PROFILE_KEY: &str = "__default__";
const ROLE_USER_KEY_PREFIX: &str = "__role__:";
const DEFAULT_AVATAR_COLOR: &str = "#e4004f";
const MAX_PROFILE_COUNT: usize = 64;
const MAX_PROFILE_KEY_BYTES: usize = 80;
const MAX_PROFILE_NAME_BYTES: usize = 256;
const MAX_AVATAR_PATH_BYTES: usize = 4096;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeUserProfile {
    pub key: String,
    pub name: String,
    pub avatar_color: String,
    pub avatar_path: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeUserProfilesState {
    pub active_key: String,
    pub profiles: Vec<NativeUserProfile>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum NativeUserProfileMutation {
    CreateProfile {
        name: String,
        #[serde(default)]
        avatar_color: String,
        #[serde(default)]
        avatar_path: String,
    },
    UpdateProfile {
        key: String,
        name: String,
        avatar_color: String,
        #[serde(default)]
        avatar_path: String,
    },
    ActivateProfile {
        key: String,
    },
    DeleteProfile {
        key: String,
    },
}

#[derive(Debug, Error)]
pub enum NativeUserProfileError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("native user profile command JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native user profile operation is invalid: {0}")]
    Invalid(String),
}

pub fn load_native_user_profiles(
    config_path: &Path,
) -> Result<NativeUserProfilesState, NativeUserProfileError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(normalized_state(&config))
}

pub fn mutate_native_user_profiles(
    config_path: &Path,
    command_json: &str,
    max_bytes: usize,
) -> Result<NativeUserProfilesState, NativeUserProfileError> {
    if command_json.len() > max_bytes {
        return Err(NativeUserProfileError::Invalid(format!(
            "command exceeds the {max_bytes} byte limit"
        )));
    }
    let command = serde_json::from_str::<NativeUserProfileMutation>(command_json)?;
    let mut config = ConfigDocument::load(config_path)?;
    let mut state = normalized_state(&config);
    match command {
        NativeUserProfileMutation::CreateProfile {
            name,
            avatar_color,
            avatar_path,
        } => {
            if state.profiles.len() >= MAX_PROFILE_COUNT {
                return Err(NativeUserProfileError::Invalid(format!(
                    "at most {MAX_PROFILE_COUNT} user profiles can be saved"
                )));
            }
            let name = checked_name(&name)?;
            let existing = state
                .profiles
                .iter()
                .map(|profile| profile.key.as_str())
                .collect::<HashSet<_>>();
            let key = make_profile_key(&name, &existing);
            state.profiles.push(NativeUserProfile {
                key: key.clone(),
                name,
                avatar_color: checked_color(&avatar_color)?,
                avatar_path: checked_avatar_path(&avatar_path)?,
            });
            state.active_key = key;
        }
        NativeUserProfileMutation::UpdateProfile {
            key,
            name,
            avatar_color,
            avatar_path,
        } => {
            let key = checked_key(&key)?;
            let profile = state
                .profiles
                .iter_mut()
                .find(|profile| profile.key == key)
                .ok_or_else(|| {
                    NativeUserProfileError::Invalid(
                        "selected user profile does not exist".to_owned(),
                    )
                })?;
            profile.name = checked_name_allow_empty(&name)?;
            profile.avatar_color = checked_color(&avatar_color)?;
            profile.avatar_path = checked_avatar_path(&avatar_path)?;
        }
        NativeUserProfileMutation::ActivateProfile { key } => {
            let key = checked_key(&key)?;
            if !state.profiles.iter().any(|profile| profile.key == key) {
                return Err(NativeUserProfileError::Invalid(
                    "selected user profile does not exist".to_owned(),
                ));
            }
            state.active_key = key;
        }
        NativeUserProfileMutation::DeleteProfile { key } => {
            let key = checked_key(&key)?;
            let previous = state.profiles.len();
            state.profiles.retain(|profile| profile.key != key);
            if state.profiles.len() == previous {
                return Err(NativeUserProfileError::Invalid(
                    "selected user profile does not exist".to_owned(),
                ));
            }
            if state.profiles.is_empty() {
                state.profiles.push(default_profile());
            }
            if state.active_key == key {
                state.active_key = state.profiles[0].key.clone();
            }
        }
    }
    persist_state(&mut config, &state);
    config.save(config_path)?;
    Ok(state)
}

fn normalized_state(config: &ConfigDocument) -> NativeUserProfilesState {
    let legacy_name = config_string(config, "user_name");
    let legacy_profile = NativeUserProfile {
        key: if legacy_name.is_empty() {
            DEFAULT_USER_PROFILE_KEY.to_owned()
        } else {
            legacy_name.clone()
        },
        name: legacy_name.clone(),
        avatar_color: normalized_color(&config_string(config, "user_avatar_color")),
        avatar_path: normalized_avatar_path(&config_string(config, "user_avatar_path")),
    };
    let mut profiles = Vec::new();
    let mut seen = HashSet::new();
    for value in config
        .get("user_profiles")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let Some(object) = value.as_object() else {
            continue;
        };
        let Some(profile) = profile_from_object(object) else {
            continue;
        };
        if seen.insert(profile.key.clone()) {
            profiles.push(profile);
        }
        if profiles.len() >= MAX_PROFILE_COUNT {
            break;
        }
    }
    let configured_active = clean_key(&config_string(config, "active_user_profile"));
    if profiles.is_empty() {
        seen.insert(legacy_profile.key.clone());
        profiles.push(legacy_profile);
    } else if !legacy_name.is_empty()
        && !seen.contains(&legacy_name)
        && configured_active.is_empty()
    {
        profiles.insert(0, legacy_profile);
    }
    if profiles.is_empty() {
        profiles.push(default_profile());
    }
    let active_key = if profiles
        .iter()
        .any(|profile| profile.key == configured_active)
    {
        configured_active
    } else if !legacy_name.is_empty() && profiles.iter().any(|profile| profile.key == legacy_name) {
        legacy_name
    } else {
        profiles[0].key.clone()
    };
    NativeUserProfilesState {
        active_key,
        profiles,
    }
}

fn persist_state(config: &mut ConfigDocument, state: &NativeUserProfilesState) {
    config.set("active_user_profile", json!(state.active_key));
    config.set(
        "user_profiles",
        serde_json::to_value(&state.profiles).unwrap(),
    );
    if let Some(active) = state
        .profiles
        .iter()
        .find(|profile| profile.key == state.active_key)
    {
        config.set("user_name", json!(active.name));
        config.set("user_avatar_color", json!(active.avatar_color));
        config.set("user_avatar_path", json!(active.avatar_path));
    }
}

fn profile_from_object(object: &Map<String, Value>) -> Option<NativeUserProfile> {
    let name = object
        .get("name")
        .or_else(|| object.get("display_name"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .chars()
        .take(MAX_PROFILE_NAME_BYTES)
        .collect::<String>();
    let raw_key = object
        .get("key")
        .or_else(|| object.get("id"))
        .and_then(Value::as_str)
        .unwrap_or(if name.is_empty() {
            DEFAULT_USER_PROFILE_KEY
        } else {
            &name
        });
    let key = clean_key(raw_key);
    if key.is_empty() {
        return None;
    }
    Some(NativeUserProfile {
        key,
        name,
        avatar_color: normalized_color(
            object
                .get("avatar_color")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        ),
        avatar_path: normalized_avatar_path(
            object
                .get("avatar_path")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        ),
    })
}

fn default_profile() -> NativeUserProfile {
    NativeUserProfile {
        key: DEFAULT_USER_PROFILE_KEY.to_owned(),
        name: String::new(),
        avatar_color: DEFAULT_AVATAR_COLOR.to_owned(),
        avatar_path: String::new(),
    }
}

fn make_profile_key(name: &str, existing: &HashSet<&str>) -> String {
    let mut base = clean_key(name);
    if base.is_empty() || base == DEFAULT_USER_PROFILE_KEY {
        base = "user".to_owned();
    }
    let mut key = base.clone();
    let mut index = 2;
    while existing.contains(key.as_str()) {
        key = format!("{base}#{index}");
        index += 1;
    }
    key
}

fn clean_key(value: &str) -> String {
    let mut key = value.trim().replace(['\r', '\n', '\t'], " ");
    if let Some(suffix) = key.strip_prefix(ROLE_USER_KEY_PREFIX) {
        key = format!("role-{suffix}");
    }
    key.chars().take(MAX_PROFILE_KEY_BYTES).collect()
}

fn checked_key(value: &str) -> Result<String, NativeUserProfileError> {
    let key = clean_key(value);
    if key.is_empty() {
        Err(NativeUserProfileError::Invalid(
            "user profile key cannot be empty".to_owned(),
        ))
    } else {
        Ok(key)
    }
}

fn checked_name(value: &str) -> Result<String, NativeUserProfileError> {
    let name = checked_name_allow_empty(value)?;
    if name.is_empty() {
        Err(NativeUserProfileError::Invalid(
            "new user profile name cannot be empty".to_owned(),
        ))
    } else {
        Ok(name)
    }
}

fn checked_name_allow_empty(value: &str) -> Result<String, NativeUserProfileError> {
    let value = value.trim();
    if value.len() > MAX_PROFILE_NAME_BYTES || value.chars().any(char::is_control) {
        Err(NativeUserProfileError::Invalid(
            "user profile name is too long or contains control characters".to_owned(),
        ))
    } else {
        Ok(value.to_owned())
    }
}

fn checked_color(value: &str) -> Result<String, NativeUserProfileError> {
    let value = if value.trim().is_empty() {
        DEFAULT_AVATAR_COLOR
    } else {
        value.trim()
    };
    if value.len() == 7
        && value.starts_with('#')
        && value[1..]
            .chars()
            .all(|character| character.is_ascii_hexdigit())
    {
        Ok(value.to_ascii_lowercase())
    } else {
        Err(NativeUserProfileError::Invalid(
            "avatar color must use #RRGGBB".to_owned(),
        ))
    }
}

fn normalized_color(value: &str) -> String {
    checked_color(value).unwrap_or_else(|_| DEFAULT_AVATAR_COLOR.to_owned())
}

fn checked_avatar_path(value: &str) -> Result<String, NativeUserProfileError> {
    let value = value.trim();
    if value.len() > MAX_AVATAR_PATH_BYTES || value.chars().any(char::is_control) {
        Err(NativeUserProfileError::Invalid(
            "avatar path is too long or contains control characters".to_owned(),
        ))
    } else {
        Ok(value.to_owned())
    }
}

fn normalized_avatar_path(value: &str) -> String {
    checked_avatar_path(value).unwrap_or_default()
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn user_profiles_normalize_switch_sync_and_recover_after_last_delete() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.set("user_name", json!("Legacy"));
        config.set("user_avatar_color", json!("#ABCDEF"));
        config.save(&path).unwrap();

        let state = load_native_user_profiles(&path).unwrap();
        assert_eq!(state.active_key, "Legacy");
        assert_eq!(state.profiles[0].avatar_color, "#abcdef");

        let state = mutate_native_user_profiles(
            &path,
            r##"{"op":"create_profile","name":"Alice","avatar_color":"#112233"}"##,
            4096,
        )
        .unwrap();
        assert_eq!(state.active_key, "Alice");
        assert_eq!(state.profiles.len(), 2);
        let state = mutate_native_user_profiles(
            &path,
            r##"{"op":"create_profile","name":"Alice","avatar_color":"#445566"}"##,
            4096,
        )
        .unwrap();
        assert_eq!(state.active_key, "Alice#2");

        let state = mutate_native_user_profiles(
            &path,
            r##"{"op":"update_profile","key":"Alice#2","name":"Alice 2","avatar_color":"#778899","avatar_path":"avatars/alice.png"}"##,
            4096,
        )
        .unwrap();
        assert_eq!(state.profiles.last().unwrap().name, "Alice 2");
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(saved.get("user_name"), Some(&json!("Alice 2")));
        assert_eq!(saved.get("active_user_profile"), Some(&json!("Alice#2")));

        for key in ["Legacy", "Alice", "Alice#2"] {
            mutate_native_user_profiles(
                &path,
                &json!({"op":"delete_profile","key":key}).to_string(),
                4096,
            )
            .unwrap();
        }
        let state = load_native_user_profiles(&path).unwrap();
        assert_eq!(state.profiles, vec![default_profile()]);
        assert_eq!(state.active_key, DEFAULT_USER_PROFILE_KEY);
        assert!(
            mutate_native_user_profiles(
                &path,
                r#"{"op":"activate_profile","key":"missing"}"#,
                4096,
            )
            .is_err()
        );
    }
}
