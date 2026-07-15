use crate::config::{ConfigDocument, ConfigError};
use crate::database::{
    ChatDatabaseSummary, Database, DatabaseError, RelationshipData, RelationshipImportSummary,
};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use tempfile::Builder;
use thiserror::Error;

pub const DATA_PACKAGE_FORMAT: &str = "bandori_pet_settings_bundle";
pub const DATA_PACKAGE_VERSION: i64 = 1;

const MAX_RELATIONSHIP_STATES: usize = 50_000;
const MAX_CHARACTER_MEMORIES: usize = 100_000;
const MAX_RELATIONSHIP_TEXT_BYTES: usize = 1024 * 1024;

const SECRET_CONFIG_KEYS: &[&str] = &[
    "llm_api_key",
    "llm_aux_api_key",
    "asr_api_key",
    "ai_status_token",
    "chat_integration_token",
    "napcat_access_token",
];

const BUILTIN_CLICK_PROFILE_NAMES: &[&str] = &[
    "auto",
    "genki",
    "tsundere",
    "shy",
    "cool",
    "surprised",
    "random",
];

const LIVE2D_KEYS: &[&str] = &[
    "character",
    "costume",
    "models",
    "model_action_settings",
    "live2d_idle_actions_enabled",
    "live2d_random_actions_enabled",
    "live2d_head_tracking_enabled",
    "live2d_mutual_gaze_enabled",
    "birthday_tray_notifications_enabled",
];
const CLICK_PROFILE_KEYS: &[&str] = &["click_motion_profiles"];
const LLM_KEYS: &[&str] = &[
    "llm_api_url",
    "llm_model_id",
    "llm_aux_api_url",
    "llm_aux_model_id",
    "llm_aux_enable_thinking",
    "llm_aux_vision_fallback_enabled",
    "llm_api_mode",
    "llm_web_search_enabled",
    "llm_web_search_engine",
    "llm_web_search_show_sources",
    "llm_chat_history_message_limit",
    "llm_compact_history_message_limit",
    "llm_cross_chat_history_enabled",
    "llm_custom_system_prompt_enabled",
    "llm_custom_system_prompt",
    "llm_api_profiles",
    "llm_active_api_profile",
    "user_name",
    "user_avatar_color",
    "user_avatar_path",
    "user_profiles",
    "active_user_profile",
    "chat_avatar_paths",
    "group_chat_sidebar_ratio",
    "group_chat_sidebar_collapsed",
    "chat_window_always_on_top",
    "llm_enable_thinking",
    "llm_show_reasoning",
];
const TTS_KEYS: &[&str] = &[
    "tts_enabled",
    "tts_api_url",
    "tts_language",
    "tts_reference_character",
    "tts_streaming",
    "tts_temperature",
    "tts_translate_to_selected_language",
];
const ASR_KEYS: &[&str] = &[
    "asr_enabled",
    "asr_api_url",
    "asr_model_id",
    "asr_language",
    "asr_auto_send",
    "asr_insert_mode",
    "asr_sample_rate",
    "asr_max_record_seconds",
    "asr_timeout_seconds",
];
const POV_KEYS: &[&str] = &[
    "pov_mode",
    "pov_custom_prompt",
    "pov_custom_personas",
    "pov_role_character",
    "user_profiles",
    "active_user_profile",
];
const CHARACTER_PERSONA_KEYS: &[&str] = &["character_persona_presets", "character_persona_active"];
const REMINDER_KEYS: &[&str] = &[
    "alarms",
    "pomodoros",
    "proactive_companion",
    "proactive_care_policy",
    "reminder_display_mode",
];
const SCREEN_AWARENESS_KEYS: &[&str] = &[
    "screen_awareness_enabled",
    "screen_awareness_interval_minutes",
    "screen_awareness_character_mode",
    "screen_awareness_character",
    "screen_awareness_max_screenshot_width",
    "screen_awareness_model_mode",
    "screen_awareness_display_mode",
    "screen_awareness_include_process_name",
    "screen_awareness_include_window_title",
];
const COMPACT_KEYS: &[&str] = &[
    "compact_ai_window_enabled",
    "compact_ai_window_background_color",
    "compact_ai_window_text_color",
    "compact_ai_window_opacity",
    "compact_ai_window_font_size",
    "ai_event_overlay_enabled",
    "ai_status_port_enabled",
    "ai_status_port",
    "ai_status_token",
];
const CHAT_INTEGRATION_KEYS: &[&str] = &[
    "chat_integration_enabled",
    "chat_integration_overlay_enabled",
    "chat_integration_include_context",
    "chat_integration_port",
    "chat_integration_token",
    "napcat_enabled",
    "napcat_ws_url",
    "napcat_access_token",
    "napcat_auto_reply_enabled",
    "napcat_reply_private",
    "napcat_reply_group_at_only",
    "napcat_reply_mention_sender",
    "napcat_reply_character",
    "napcat_save_policy",
    "napcat_group_retention_mode",
    "napcat_group_retention_days",
    "napcat_private_retention_mode",
    "napcat_private_retention_days",
];
const MCP_KEYS: &[&str] = &[
    "llm_hide_tool_call_details",
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
];
const MISC_KEYS: &[&str] = &[
    "language",
    "fps",
    "opacity",
    "dark_theme",
    "vsync",
    "gpu_acceleration",
    "game_topmost",
    "obs_window_capture_compatible",
    "chat_window_normal_window",
    "chat_attachment_auto_cleanup_enabled",
    "chat_attachment_retention_days",
    "hide_live2d_model",
    "auto_start",
    "drag_locked",
    "live2d_quality",
    "live2d_scale",
    "fluent_chat_window_enabled",
    "chat_display_names",
    "pinned_chat_keys",
    "live2d_hit_alpha_threshold",
    "live2d_lip_sync_max_open",
    "window_x",
    "window_y",
    "window_width",
    "window_height",
    "pixel_window_x",
    "pixel_window_y",
    "pet_mode",
];

const CONFIG_SECTIONS: &[(&str, &[&str])] = &[
    ("live2d_models", LIVE2D_KEYS),
    ("click_motion_profiles", CLICK_PROFILE_KEYS),
    ("llm", LLM_KEYS),
    ("tts", TTS_KEYS),
    ("asr", ASR_KEYS),
    ("pov", POV_KEYS),
    ("character_persona", CHARACTER_PERSONA_KEYS),
    ("reminders", REMINDER_KEYS),
    ("screen_awareness", SCREEN_AWARENESS_KEYS),
    ("compact_window", COMPACT_KEYS),
    ("chat_integration", CHAT_INTEGRATION_KEYS),
    ("mcp_computer", MCP_KEYS),
    ("misc", MISC_KEYS),
];

const EXPORT_ORDER: &[&str] = &[
    "live2d_models",
    "click_motion_profiles",
    "llm",
    "tts",
    "asr",
    "pov",
    "character_persona",
    "relationship",
    "reminders",
    "screen_awareness",
    "compact_window",
    "chat_integration",
    "mcp_computer",
    "misc",
];

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
struct DataSection {
    config: Option<Map<String, Value>>,
    relationship: Option<RelationshipData>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SettingsPackage {
    format: String,
    version: i64,
    app_version: String,
    category: String,
    exported_at: String,
    sections: BTreeMap<String, DataSection>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct DataOperationSummary {
    pub operation: String,
    pub category: String,
    pub sections: Vec<String>,
    pub config_keys: i64,
    pub relationship_states: i64,
    pub character_memories: i64,
    pub database: Option<ChatDatabaseSummary>,
}

#[derive(Debug, Error)]
pub enum DataManagementError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error(transparent)]
    Database(#[from] DatabaseError),
    #[error("data package I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("data package JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("data management request is invalid: {0}")]
    Invalid(String),
}

pub fn export_settings_package(
    config_path: &Path,
    database_path: &Path,
    category: &str,
    destination: &Path,
) -> Result<DataOperationSummary, DataManagementError> {
    let category = checked_category(category)?;
    reject_same_file(destination, config_path, "configuration")?;
    reject_same_file(destination, database_path, "database")?;
    let config = ConfigDocument::load(config_path)?;
    let mut sections = BTreeMap::new();
    let mut summary = DataOperationSummary {
        operation: "export_settings".into(),
        category: category.into(),
        ..DataOperationSummary::default()
    };
    for section in selected_sections(category) {
        if section == "relationship" {
            let relationship = Database::open(database_path)?.export_relationship_data()?;
            validate_relationship_data(&relationship)?;
            summary.relationship_states = relationship.relationship_states.len() as i64;
            summary.character_memories = relationship.character_memories.len() as i64;
            sections.insert(
                section.into(),
                DataSection {
                    relationship: Some(relationship),
                    ..DataSection::default()
                },
            );
        } else {
            let values = exported_config_section(&config, section);
            summary.config_keys += values.len() as i64;
            sections.insert(
                section.into(),
                DataSection {
                    config: Some(values),
                    ..DataSection::default()
                },
            );
        }
        summary.sections.push(section.into());
    }
    let package = SettingsPackage {
        format: DATA_PACKAGE_FORMAT.into(),
        version: DATA_PACKAGE_VERSION,
        app_version: env!("CARGO_PKG_VERSION").into(),
        category: category.into(),
        exported_at: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
            .to_string(),
        sections,
    };
    write_json_atomically(destination, &package)?;
    Ok(summary)
}

pub fn import_settings_package(
    config_path: &Path,
    database_path: &Path,
    selected_category: &str,
    source: &Path,
    max_bytes: u64,
) -> Result<DataOperationSummary, DataManagementError> {
    let selected_category = checked_category(selected_category)?;
    reject_same_file(source, config_path, "configuration")?;
    reject_same_file(source, database_path, "database")?;
    let bytes = read_bounded(source, max_bytes)?;
    let package = serde_json::from_slice::<SettingsPackage>(&bytes)?;
    if package.format != DATA_PACKAGE_FORMAT || package.version != DATA_PACKAGE_VERSION {
        return Err(DataManagementError::Invalid(
            "unsupported settings package format or version".into(),
        ));
    }
    let selected = selected_sections(selected_category);
    let mut pending_config = Vec::<(&str, Map<String, Value>)>::new();
    let mut pending_relationship = None;
    for section in selected {
        let Some(content) = package.sections.get(section) else {
            continue;
        };
        if section == "relationship" {
            if let Some(relationship) = content.relationship.clone() {
                validate_relationship_data(&relationship)?;
                pending_relationship = Some(relationship);
            }
        } else if let Some(values) = content.config.clone() {
            pending_config.push((section, values));
        }
    }
    if pending_config.is_empty() && pending_relationship.is_none() {
        return Err(DataManagementError::Invalid(
            "the package has no data for the selected category".into(),
        ));
    }

    let mut summary = DataOperationSummary {
        operation: "import_settings".into(),
        category: selected_category.into(),
        ..DataOperationSummary::default()
    };
    if !pending_config.is_empty() {
        let mut config = ConfigDocument::load(config_path)?;
        for (section, values) in pending_config {
            let applied = apply_config_section(&mut config, section, values);
            if applied > 0 {
                summary.sections.push(section.into());
                summary.config_keys += applied as i64;
            }
        }
        config.save(config_path)?;
    }
    if let Some(relationship) = pending_relationship {
        let imported = Database::open(database_path)?.import_relationship_data(&relationship)?;
        apply_relationship_summary(&mut summary, imported);
        summary.sections.push("relationship".into());
    }
    Ok(summary)
}

pub fn export_chat_database(
    database_path: &Path,
    destination: &Path,
) -> Result<DataOperationSummary, DataManagementError> {
    reject_same_file(destination, database_path, "database")?;
    let database = Database::open(database_path)?;
    let snapshot = database.export_database(destination)?;
    Ok(DataOperationSummary {
        operation: "export_database".into(),
        database: Some(snapshot),
        ..DataOperationSummary::default()
    })
}

pub fn import_chat_database(
    database_path: &Path,
    source: &Path,
) -> Result<DataOperationSummary, DataManagementError> {
    let database = Database::open(database_path)?;
    let snapshot = database.import_database(source)?;
    Ok(DataOperationSummary {
        operation: "import_database".into(),
        database: Some(snapshot),
        ..DataOperationSummary::default()
    })
}

fn selected_sections(category: &str) -> Vec<&'static str> {
    if category == "all" {
        EXPORT_ORDER.to_vec()
    } else {
        vec![
            EXPORT_ORDER
                .iter()
                .copied()
                .find(|candidate| *candidate == category)
                .expect("checked category must exist"),
        ]
    }
}

fn checked_category(category: &str) -> Result<&str, DataManagementError> {
    let category = category.trim();
    if category == "all" || EXPORT_ORDER.contains(&category) {
        Ok(category)
    } else {
        Err(DataManagementError::Invalid(format!(
            "unknown data category: {category}"
        )))
    }
}

fn section_keys(section: &str) -> &'static [&'static str] {
    CONFIG_SECTIONS
        .iter()
        .find_map(|(candidate, keys)| (*candidate == section).then_some(*keys))
        .unwrap_or(&[])
}

fn exported_config_section(config: &ConfigDocument, section: &str) -> Map<String, Value> {
    let mut result = Map::new();
    for key in section_keys(section) {
        if is_secret(key) {
            continue;
        }
        let Some(value) = config.get(key).cloned() else {
            continue;
        };
        let value = match (*key, section) {
            ("llm_api_profiles", "llm") => sanitize_llm_profiles(value, true),
            ("llm_active_api_profile", "llm") => {
                let active = value.as_str().unwrap_or_default();
                if builtin_llm_profile_names().contains(active) {
                    Value::String(String::new())
                } else {
                    value
                }
            }
            ("click_motion_profiles", "click_motion_profiles") => sanitize_click_profiles(value),
            _ => value,
        };
        result.insert((*key).into(), value);
    }
    result
}

fn apply_config_section(
    config: &mut ConfigDocument,
    section: &str,
    mut values: Map<String, Value>,
) -> usize {
    let allowed = section_keys(section);
    if section == "llm" {
        prepare_llm_import(config, &mut values);
    }
    let mut applied = 0;
    for (key, value) in values {
        if allowed.contains(&key.as_str()) && !is_secret(&key) {
            config.set(key, value);
            applied += 1;
        }
    }
    applied
}

fn prepare_llm_import(config: &ConfigDocument, values: &mut Map<String, Value>) {
    let imported = sanitize_llm_profiles(
        values.remove("llm_api_profiles").unwrap_or(Value::Null),
        true,
    );
    let imported = imported.as_array().cloned().unwrap_or_default();
    if !imported.is_empty() {
        let existing = config
            .get("llm_api_profiles")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let imported_names = imported
            .iter()
            .filter_map(profile_name)
            .collect::<BTreeSet<_>>();
        let old_by_name = existing
            .iter()
            .filter_map(|profile| profile_name(profile).map(|name| (name, profile.clone())))
            .collect::<BTreeMap<_, _>>();
        let mut merged = existing
            .into_iter()
            .filter(|profile| {
                profile_name(profile)
                    .map(|name| !imported_names.contains(&name))
                    .unwrap_or(false)
            })
            .collect::<Vec<_>>();
        for mut profile in imported {
            let Some(name) = profile_name(&profile) else {
                continue;
            };
            if let (Some(object), Some(previous)) = (
                profile.as_object_mut(),
                old_by_name.get(&name).and_then(Value::as_object),
            ) {
                for secret in SECRET_CONFIG_KEYS {
                    if let Some(value) =
                        previous.get(*secret).filter(|value| !value_is_empty(value))
                    {
                        object.insert((*secret).into(), value.clone());
                    }
                }
            }
            merged.push(profile);
        }
        values.insert("llm_api_profiles".into(), Value::Array(merged));
    }
    if values
        .get("llm_active_api_profile")
        .and_then(Value::as_str)
        .is_some_and(|name| builtin_llm_profile_names().contains(name))
    {
        values.insert(
            "llm_active_api_profile".into(),
            Value::String(String::new()),
        );
    }
}

fn sanitize_llm_profiles(value: Value, drop_builtins: bool) -> Value {
    let builtins = builtin_llm_profile_names();
    let profiles = value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|profile| {
            let mut object = profile.as_object()?.clone();
            let name = object.get("name")?.as_str()?.trim().to_owned();
            if name.is_empty() || (drop_builtins && builtins.contains(&name)) {
                return None;
            }
            for secret in SECRET_CONFIG_KEYS {
                object.remove(*secret);
            }
            object.insert("name".into(), Value::String(name));
            Some(Value::Object(object))
        })
        .collect();
    Value::Array(profiles)
}

fn sanitize_click_profiles(value: Value) -> Value {
    Value::Array(
        value
            .as_array()
            .into_iter()
            .flatten()
            .filter(|profile| {
                profile_name(profile)
                    .map(|name| !BUILTIN_CLICK_PROFILE_NAMES.contains(&name.as_str()))
                    .unwrap_or(false)
            })
            .cloned()
            .collect(),
    )
}

fn builtin_llm_profile_names() -> BTreeSet<String> {
    ConfigDocument::default()
        .get("llm_api_profiles")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(profile_name)
        .collect()
}

fn profile_name(profile: &Value) -> Option<String> {
    let name = profile.get("name")?.as_str()?.trim();
    (!name.is_empty()).then(|| name.to_owned())
}

fn is_secret(key: &str) -> bool {
    SECRET_CONFIG_KEYS.contains(&key)
}

fn value_is_empty(value: &Value) -> bool {
    match value {
        Value::Null => true,
        Value::String(value) => value.is_empty(),
        Value::Array(value) => value.is_empty(),
        Value::Object(value) => value.is_empty(),
        _ => false,
    }
}

fn validate_relationship_data(data: &RelationshipData) -> Result<(), DataManagementError> {
    if data.relationship_states.len() > MAX_RELATIONSHIP_STATES
        || data.character_memories.len() > MAX_CHARACTER_MEMORIES
    {
        return Err(DataManagementError::Invalid(
            "relationship package contains too many records".into(),
        ));
    }
    for state in &data.relationship_states {
        validate_text(&state.character, 512, "relationship character")?;
        validate_text(&state.user_key, 512, "relationship user key")?;
        validate_text(
            &state.mood,
            MAX_RELATIONSHIP_TEXT_BYTES,
            "relationship mood",
        )?;
        validate_text(
            &state.summary,
            MAX_RELATIONSHIP_TEXT_BYTES,
            "relationship summary",
        )?;
    }
    for memory in &data.character_memories {
        validate_text(&memory.character, 512, "memory character")?;
        validate_text(&memory.user_key, 512, "memory user key")?;
        validate_text(&memory.kind, 512, "memory kind")?;
        validate_text(
            &memory.content,
            MAX_RELATIONSHIP_TEXT_BYTES,
            "memory content",
        )?;
    }
    Ok(())
}

fn validate_text(value: &str, max_bytes: usize, label: &str) -> Result<(), DataManagementError> {
    if value.len() > max_bytes || value.contains('\0') {
        Err(DataManagementError::Invalid(format!(
            "{label} is too long or contains NUL"
        )))
    } else {
        Ok(())
    }
}

fn apply_relationship_summary(
    summary: &mut DataOperationSummary,
    imported: RelationshipImportSummary,
) {
    summary.relationship_states = imported.relationship_states;
    summary.character_memories = imported.character_memories;
}

fn read_bounded(path: &Path, max_bytes: u64) -> Result<Vec<u8>, DataManagementError> {
    let metadata = fs::metadata(path)?;
    if !metadata.is_file() || metadata.len() > max_bytes {
        return Err(DataManagementError::Invalid(format!(
            "data package must be a file no larger than {max_bytes} bytes"
        )));
    }
    Ok(fs::read(path)?)
}

fn write_json_atomically<T: Serialize>(
    destination: &Path,
    value: &T,
) -> Result<(), DataManagementError> {
    let parent = destination.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let file_name = destination
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("bandori-settings.json");
    let mut temp = Builder::new()
        .prefix(&format!("{file_name}."))
        .suffix(".tmp")
        .tempfile_in(parent)?;
    serde_json::to_writer_pretty(&mut temp, value)?;
    temp.write_all(b"\n")?;
    temp.flush()?;
    temp.as_file().sync_all()?;
    temp.persist(destination)
        .map_err(|error| DataManagementError::Io(error.error))?;
    Ok(())
}

fn reject_same_file(left: &Path, right: &Path, label: &str) -> Result<(), DataManagementError> {
    let left = absolute_path(left)?;
    let right = absolute_path(right)?;
    if left == right {
        Err(DataManagementError::Invalid(format!(
            "destination cannot overwrite the active {label} file"
        )))
    } else {
        Ok(())
    }
}

fn absolute_path(path: &Path) -> Result<std::path::PathBuf, std::io::Error> {
    if path.exists() {
        return dunce::canonicalize(path);
    }
    if path.is_absolute() {
        Ok(path.to_path_buf())
    } else {
        Ok(std::env::current_dir()?.join(path))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    fn save_config(path: &Path, values: &[(&str, Value)]) {
        let mut config = ConfigDocument::default();
        for (key, value) in values {
            config.set(*key, value.clone());
        }
        config.save(path).unwrap();
    }

    #[test]
    fn settings_package_round_trip_preserves_secrets_and_rejects_unknown_keys() {
        let directory = tempdir().unwrap();
        let source_config = directory.path().join("source.json");
        let target_config = directory.path().join("target.json");
        let database_path = directory.path().join("data.db");
        let package_path = directory.path().join("settings.json");
        save_config(
            &source_config,
            &[
                ("llm_api_key", json!("source-root-secret")),
                ("llm_model_id", json!("source-model")),
                (
                    "llm_api_profiles",
                    json!([
                        {"name":"openai","llm_api_key":"builtin-secret"},
                        {"name":"custom","llm_model_id":"custom-model","llm_api_key":"source-profile-secret"}
                    ]),
                ),
            ],
        );
        save_config(
            &target_config,
            &[
                ("llm_api_key", json!("target-root-secret")),
                ("llm_model_id", json!("target-model")),
                (
                    "llm_api_profiles",
                    json!([
                        {"name":"openai","llm_api_key":"target-builtin-secret"},
                        {"name":"custom","llm_model_id":"old-model","llm_api_key":"target-profile-secret"}
                    ]),
                ),
            ],
        );

        export_settings_package(&source_config, &database_path, "llm", &package_path).unwrap();
        assert!(!database_path.exists());
        let exported = fs::read_to_string(&package_path).unwrap();
        assert!(!exported.contains("source-root-secret"));
        assert!(!exported.contains("source-profile-secret"));
        assert!(!exported.contains("builtin-secret"));

        let mut package = serde_json::from_str::<Value>(&exported).unwrap();
        package["sections"]["llm"]["config"]["unknown"] = json!("ignored");
        package["sections"]["llm"]["config"]["llm_api_key"] = json!("attacker");
        package["sections"]["llm"]["config"]["llm_api_profiles"][0]["llm_api_key"] =
            json!("attacker-profile");
        fs::write(&package_path, serde_json::to_vec(&package).unwrap()).unwrap();

        let summary = import_settings_package(
            &target_config,
            &database_path,
            "llm",
            &package_path,
            1024 * 1024,
        )
        .unwrap();
        assert_eq!(summary.sections, vec!["llm"]);
        let imported = ConfigDocument::load(&target_config).unwrap();
        assert_eq!(
            imported.get("llm_api_key"),
            Some(&json!("target-root-secret"))
        );
        assert_eq!(imported.get("llm_model_id"), Some(&json!("source-model")));
        let profiles = imported
            .get("llm_api_profiles")
            .unwrap()
            .as_array()
            .unwrap();
        let custom = profiles
            .iter()
            .find(|profile| profile["name"] == "custom")
            .unwrap();
        assert_eq!(custom["llm_model_id"], "custom-model");
        assert_eq!(custom["llm_api_key"], "target-profile-secret");
        assert!(
            import_settings_package(
                &target_config,
                &database_path,
                "llm",
                &target_config,
                1024 * 1024,
            )
            .is_err()
        );
    }

    #[test]
    fn relationship_package_merges_and_database_backup_restores() {
        let directory = tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        let package_path = directory.path().join("relationship.json");
        let backup_path = directory.path().join("backup.db");
        save_config(&config_path, &[]);
        let database = Database::open(&database_path).unwrap();
        let memory_id = database
            .add_character_memory("ran", "alice", "note", "remember me", 80, None, None)
            .unwrap();
        drop(database);

        let exported =
            export_settings_package(&config_path, &database_path, "relationship", &package_path)
                .unwrap();
        assert_eq!(exported.character_memories, 1);
        fs::remove_file(&database_path).unwrap();
        let imported = import_settings_package(
            &config_path,
            &database_path,
            "relationship",
            &package_path,
            1024 * 1024,
        )
        .unwrap();
        assert_eq!(imported.character_memories, 1);

        export_chat_database(&database_path, &backup_path).unwrap();
        Database::open(&database_path)
            .unwrap()
            .delete_character_memories(&[memory_id], "ran", "alice")
            .unwrap();
        let restored = import_chat_database(&database_path, &backup_path).unwrap();
        assert_eq!(restored.database.unwrap().messages, 0);
        assert_eq!(
            Database::open(&database_path)
                .unwrap()
                .character_memories("ran", "alice", 10)
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn import_rejects_unknown_categories_versions_and_oversized_packages() {
        let directory = tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        let package_path = directory.path().join("settings.json");
        fs::write(
            &package_path,
            br#"{"format":"bandori_pet_settings_bundle","version":2,"app_version":"x","category":"all","exported_at":"0","sections":{}}"#,
        )
        .unwrap();
        assert!(
            import_settings_package(
                &config_path,
                &database_path,
                "all",
                &package_path,
                1024 * 1024
            )
            .is_err()
        );
        assert!(
            export_settings_package(
                &config_path,
                &database_path,
                "secrets",
                directory.path().join("out.json").as_path()
            )
            .is_err()
        );
        assert!(
            import_settings_package(&config_path, &database_path, "all", &package_path, 4).is_err()
        );
    }
}
