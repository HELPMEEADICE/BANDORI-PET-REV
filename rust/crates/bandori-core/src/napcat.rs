//! Native NapCat/OneBot policy, persistence and reply preparation.
//!
//! Qt owns the forward WebSocket because it already provides `QWebSocket`.
//! This module keeps every data-bearing decision in Rust: configuration,
//! OneBot normalization, duplicate suppression, retention and prompt creation.

use crate::chat_prompt::{
    build_native_system_prompt, character_display_name, load_character_markdown,
};
use crate::config::{ConfigDocument, ConfigError};
use crate::database::{Database, DatabaseError, ExternalDeleteResult};
use crate::local_integration::{chat_overlay, normalize_onebot_event};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::path::Path;
use thiserror::Error;

const MAX_SETTINGS_BYTES: usize = 64 * 1024;
const MAX_EVENT_BYTES: usize = 1024 * 1024;

#[derive(Debug, Error)]
pub enum NapcatError {
    #[error("NapCat configuration failed: {0}")]
    Config(#[from] ConfigError),
    #[error("NapCat database failed: {0}")]
    Database(#[from] DatabaseError),
    #[error("NapCat JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("NapCat settings exceed {MAX_SETTINGS_BYTES} bytes")]
    SettingsTooLarge,
    #[error("NapCat event exceeds {MAX_EVENT_BYTES} bytes")]
    EventTooLarge,
    #[error("NapCat event root must be an object")]
    EventRoot,
    #[error("NapCat chat type must be group or private")]
    InvalidChatType,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NativeNapcatSettings {
    pub enabled: bool,
    pub ws_url: String,
    pub access_token_configured: bool,
    pub auto_reply_enabled: bool,
    pub reply_private: bool,
    pub reply_group_at_only: bool,
    pub reply_mention_sender: bool,
    pub reply_character: String,
    pub save_policy: String,
    pub group_retention_mode: String,
    pub group_retention_days: i64,
    pub private_retention_mode: String,
    pub private_retention_days: i64,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeNapcatSettingsUpdate {
    #[serde(default)]
    pub enabled: Option<bool>,
    #[serde(default)]
    pub ws_url: Option<String>,
    #[serde(default)]
    pub access_token: Option<String>,
    #[serde(default)]
    pub clear_access_token: bool,
    #[serde(default)]
    pub auto_reply_enabled: Option<bool>,
    #[serde(default)]
    pub reply_private: Option<bool>,
    #[serde(default)]
    pub reply_group_at_only: Option<bool>,
    #[serde(default)]
    pub reply_mention_sender: Option<bool>,
    #[serde(default)]
    pub reply_character: Option<String>,
    #[serde(default)]
    pub save_policy: Option<String>,
    #[serde(default)]
    pub group_retention_mode: Option<String>,
    #[serde(default)]
    pub group_retention_days: Option<i64>,
    #[serde(default)]
    pub private_retention_mode: Option<String>,
    #[serde(default)]
    pub private_retention_days: Option<i64>,
}

#[derive(Clone, Debug, Serialize)]
pub struct NativeNapcatIngestResult {
    pub ignored: bool,
    pub duplicate: bool,
    pub saved: bool,
    pub should_reply: bool,
    pub mention_sender: bool,
    pub normalized_event: Value,
    pub overlay: Value,
}

#[derive(Clone, Debug)]
pub struct NativeNapcatReplyJob {
    pub character: String,
    pub mention_sender: bool,
    pub raw_event: Value,
    pub messages: Vec<Value>,
}

pub fn load_native_napcat_settings(
    config_path: &Path,
) -> Result<NativeNapcatSettings, NapcatError> {
    Ok(settings(&ConfigDocument::load(config_path)?))
}

pub fn save_native_napcat_settings(
    config_path: &Path,
    update_json: &str,
) -> Result<NativeNapcatSettings, NapcatError> {
    if update_json.len() > MAX_SETTINGS_BYTES {
        return Err(NapcatError::SettingsTooLarge);
    }
    let update: NativeNapcatSettingsUpdate = serde_json::from_str(update_json)?;
    let mut config = ConfigDocument::load(config_path)?;
    apply_update(&mut config, update);
    config.save(config_path)?;
    Ok(settings(&config))
}

pub fn napcat_access_token(config_path: &Path) -> Result<String, NapcatError> {
    Ok(config_string(
        &ConfigDocument::load(config_path)?,
        "napcat_access_token",
    ))
}

pub fn delete_native_napcat_records(
    database_path: &Path,
    chat_type: &str,
) -> Result<ExternalDeleteResult, NapcatError> {
    let chat_type = match chat_type.trim().to_ascii_lowercase().as_str() {
        "group" => "group",
        "private" => "private",
        _ => return Err(NapcatError::InvalidChatType),
    };
    Ok(Database::open(database_path)?.delete_external_chat(chat_type, "")?)
}

pub fn ingest_native_napcat_event(
    config_path: &Path,
    database_path: &Path,
    event_json: &str,
) -> Result<NativeNapcatIngestResult, NapcatError> {
    if event_json.len() > MAX_EVENT_BYTES {
        return Err(NapcatError::EventTooLarge);
    }
    let raw: Value = serde_json::from_str(event_json)?;
    let raw_object = raw.as_object().ok_or(NapcatError::EventRoot)?;
    if value_text(raw_object.get("post_type")).is_empty()
        || value_text(raw_object.get("post_type")).eq_ignore_ascii_case("meta_event")
        || !value_text(raw_object.get("post_type")).eq_ignore_ascii_case("message")
        || (!value_text(raw_object.get("self_id")).is_empty()
            && value_text(raw_object.get("self_id")) == value_text(raw_object.get("user_id")))
    {
        return Ok(ignored_result());
    }
    let Some(normalized) = normalize_onebot_event(&raw) else {
        return Ok(ignored_result());
    };
    let config = ConfigDocument::load(config_path)?;
    let view = settings(&config);
    let chat_type = normalized
        .get("chat_type")
        .and_then(Value::as_str)
        .unwrap_or("private");
    let save = match view.save_policy.as_str() {
        "overlay_only" => false,
        "private_only" => chat_type != "group",
        _ => true,
    };
    let database = Database::open(database_path)?;
    let (saved, duplicate, overlay) = if save {
        let stored = database.add_external_chat_message(&normalized)?;
        apply_retention(&database, &view)?;
        let overlay = if !stored.duplicate
            && config_bool(&config, "chat_integration_overlay_enabled", true)
        {
            chat_overlay(&normalized, &stored.unread).unwrap_or(Value::Null)
        } else {
            Value::Null
        };
        (true, stored.duplicate, overlay)
    } else {
        (false, false, transient_overlay(&normalized))
    };
    let should_reply = !duplicate && should_reply(&view, &raw);
    Ok(NativeNapcatIngestResult {
        ignored: false,
        duplicate,
        saved,
        should_reply,
        mention_sender: view.reply_mention_sender,
        normalized_event: normalized,
        overlay,
    })
}

pub fn prepare_native_napcat_reply(
    config_path: &Path,
    project_root: &Path,
    database_path: &Path,
    normalized_event_json: &str,
) -> Result<Option<NativeNapcatReplyJob>, NapcatError> {
    if normalized_event_json.len() > MAX_EVENT_BYTES {
        return Err(NapcatError::EventTooLarge);
    }
    let event: Value = serde_json::from_str(normalized_event_json)?;
    let event = event.as_object().ok_or(NapcatError::EventRoot)?;
    let config = ConfigDocument::load(config_path)?;
    let view = settings(&config);
    if !view.enabled || !view.auto_reply_enabled {
        return Ok(None);
    }
    let raw_event = event.get("raw_event").cloned().unwrap_or(Value::Null);
    if !should_reply(&view, &raw_event) {
        return Ok(None);
    }
    let character = selected_character(&config, &view.reply_character);
    if character.is_empty() {
        return Ok(None);
    }
    let display_name = character_display_name(&character);
    let markdown = load_character_markdown(project_root, &character);
    let system_prompt =
        build_native_system_prompt(&character, &display_name, config.values(), &markdown);
    if system_prompt.trim().is_empty() {
        return Ok(None);
    }
    let sender = value_text(event.get("sender_name"));
    let sender = if sender.is_empty() { "对方" } else { &sender };
    let text = value_text(event.get("text"));
    let mut user_text = format!("{sender}：{text}").trim().to_owned();
    let database = Database::open(database_path)?;
    let context = database.external_chat_context_text(4, 6)?;
    if !context.trim().is_empty() {
        user_text.push_str("\n\n【最近外部聊天上下文】\n");
        user_text.push_str(context.trim());
    }
    Ok(Some(NativeNapcatReplyJob {
        character,
        mention_sender: view.reply_mention_sender,
        raw_event,
        messages: vec![
            json!({"role": "system", "content": system_prompt}),
            json!({"role": "user", "content": user_text}),
        ],
    }))
}

fn apply_update(config: &mut ConfigDocument, update: NativeNapcatSettingsUpdate) {
    if let Some(value) = update.enabled {
        config.set("napcat_enabled", Value::Bool(value));
    }
    if let Some(value) = update.ws_url {
        config.set("napcat_ws_url", Value::String(truncate(value.trim(), 2048)));
    }
    if update.clear_access_token {
        config.set("napcat_access_token", Value::String(String::new()));
    } else if let Some(value) = update.access_token {
        let value = value.trim();
        if !value.is_empty() {
            config.set("napcat_access_token", Value::String(truncate(value, 512)));
        }
    }
    for (key, value) in [
        ("napcat_auto_reply_enabled", update.auto_reply_enabled),
        ("napcat_reply_private", update.reply_private),
        ("napcat_reply_group_at_only", update.reply_group_at_only),
        ("napcat_reply_mention_sender", update.reply_mention_sender),
    ] {
        if let Some(value) = value {
            config.set(key, Value::Bool(value));
        }
    }
    if let Some(value) = update.reply_character {
        config.set(
            "napcat_reply_character",
            Value::String(truncate(value.trim(), 256)),
        );
    }
    if let Some(value) = update.save_policy {
        config.set(
            "napcat_save_policy",
            Value::String(enum_value(
                &value,
                &["all", "private_only", "overlay_only"],
                "all",
            )),
        );
    }
    if let Some(value) = update.group_retention_mode {
        config.set(
            "napcat_group_retention_mode",
            Value::String(enum_value(&value, &["auto", "manual"], "manual")),
        );
    }
    if let Some(value) = update.group_retention_days {
        config.set(
            "napcat_group_retention_days",
            Value::from(value.clamp(1, 3650)),
        );
    }
    if let Some(value) = update.private_retention_mode {
        config.set(
            "napcat_private_retention_mode",
            Value::String(enum_value(&value, &["auto", "manual"], "manual")),
        );
    }
    if let Some(value) = update.private_retention_days {
        config.set(
            "napcat_private_retention_days",
            Value::from(value.clamp(1, 3650)),
        );
    }
}

fn settings(config: &ConfigDocument) -> NativeNapcatSettings {
    NativeNapcatSettings {
        enabled: config_bool(config, "napcat_enabled", false),
        ws_url: config_string(config, "napcat_ws_url"),
        access_token_configured: !config_string(config, "napcat_access_token").is_empty(),
        auto_reply_enabled: config_bool(config, "napcat_auto_reply_enabled", false),
        reply_private: config_bool(config, "napcat_reply_private", true),
        reply_group_at_only: config_bool(config, "napcat_reply_group_at_only", true),
        reply_mention_sender: config_bool(config, "napcat_reply_mention_sender", true),
        reply_character: config_string(config, "napcat_reply_character"),
        save_policy: enum_value(
            &config_string(config, "napcat_save_policy"),
            &["all", "private_only", "overlay_only"],
            "all",
        ),
        group_retention_mode: enum_value(
            &config_string(config, "napcat_group_retention_mode"),
            &["auto", "manual"],
            "manual",
        ),
        group_retention_days: config_i64(config, "napcat_group_retention_days", 7).clamp(1, 3650),
        private_retention_mode: enum_value(
            &config_string(config, "napcat_private_retention_mode"),
            &["auto", "manual"],
            "manual",
        ),
        private_retention_days: config_i64(config, "napcat_private_retention_days", 30)
            .clamp(1, 3650),
    }
}

fn should_reply(settings: &NativeNapcatSettings, raw_event: &Value) -> bool {
    if !settings.auto_reply_enabled {
        return false;
    }
    let Some(raw) = raw_event.as_object() else {
        return false;
    };
    if value_text(raw.get("message_type")).eq_ignore_ascii_case("group") {
        !settings.reply_group_at_only || onebot_event_mentions_self(raw)
    } else {
        settings.reply_private
    }
}

fn onebot_event_mentions_self(event: &Map<String, Value>) -> bool {
    let self_id = value_text(event.get("self_id"));
    if self_id.is_empty() {
        return false;
    }
    if event
        .get("message")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
        .any(|segment| {
            value_text(segment.get("type")).eq_ignore_ascii_case("at")
                && segment
                    .get("data")
                    .and_then(Value::as_object)
                    .is_some_and(|data| value_text(data.get("qq")) == self_id)
        })
    {
        return true;
    }
    value_text(event.get("raw_message")).contains(&format!("[CQ:at,qq={self_id}"))
}

fn apply_retention(
    database: &Database,
    settings: &NativeNapcatSettings,
) -> Result<(), DatabaseError> {
    database.prune_external_group_chat_limit()?;
    if settings.group_retention_mode == "auto" {
        database.purge_external_chat_older_than(settings.group_retention_days, "group", "qq")?;
    }
    if settings.private_retention_mode == "auto" {
        database.purge_external_chat_older_than(
            settings.private_retention_days,
            "private",
            "qq",
        )?;
    }
    Ok(())
}

fn transient_overlay(event: &Value) -> Value {
    let content = value_text(event.get("text")).replace(['\r', '\n'], " ");
    let clean = content.trim();
    if clean.is_empty() {
        return Value::Null;
    }
    let mut content = clean.chars().take(80).collect::<String>();
    if clean.chars().count() > 80 {
        content.push_str("...");
    }
    let sender = first_non_empty(&[
        value_text(event.get("sender_name")),
        value_text(event.get("sender_id")),
    ]);
    let text = if sender.is_empty() {
        content
    } else {
        format!("{sender}: {content}")
    };
    json!({
        "source": first_non_empty(&[value_text(event.get("platform")), "qq".into()]),
        "state": "stream",
        "mode": "replace",
        "title": first_non_empty(&[value_text(event.get("thread_name")), "新消息".into()]),
        "text": text,
        "action": "surprised",
        "ttl_ms": 9000,
        "anchor_to_pet": true
    })
}

fn selected_character(config: &ConfigDocument, explicit: &str) -> String {
    if !explicit.trim().is_empty() {
        return explicit.trim().to_owned();
    }
    config
        .get("models")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_object)
        .find_map(|model| {
            let character = value_text(model.get("character"));
            (!character.is_empty()).then_some(character)
        })
        .unwrap_or_else(|| config_string(config, "character"))
}

fn ignored_result() -> NativeNapcatIngestResult {
    NativeNapcatIngestResult {
        ignored: true,
        duplicate: false,
        saved: false,
        should_reply: false,
        mention_sender: false,
        normalized_event: Value::Null,
        overlay: Value::Null,
    }
}

fn config_bool(config: &ConfigDocument, key: &str, fallback: bool) -> bool {
    config.get(key).and_then(Value::as_bool).unwrap_or(fallback)
}

fn config_i64(config: &ConfigDocument, key: &str, fallback: i64) -> i64 {
    config.get(key).and_then(Value::as_i64).unwrap_or(fallback)
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    value_text(config.get(key))
}

fn value_text(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(value)) => value.trim().to_owned(),
        Some(Value::Number(value)) => value.to_string(),
        Some(Value::Bool(value)) => value.to_string(),
        _ => String::new(),
    }
}

fn first_non_empty(values: &[String]) -> String {
    values
        .iter()
        .find(|value| !value.trim().is_empty())
        .cloned()
        .unwrap_or_default()
}

fn enum_value(value: &str, choices: &[&str], fallback: &str) -> String {
    let value = value.trim().to_ascii_lowercase();
    if choices.contains(&value.as_str()) {
        value
    } else {
        fallback.to_owned()
    }
}

fn truncate(value: &str, limit: usize) -> String {
    value.chars().take(limit).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    fn write_config(path: &Path, updates: Value) {
        let mut config = ConfigDocument::default();
        for (key, value) in updates.as_object().unwrap() {
            config.set(key, value.clone());
        }
        config.save(path).unwrap();
    }

    #[test]
    fn settings_are_redacted_and_updates_are_clamped() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("config.json");
        write_config(&path, json!({"napcat_access_token": "secret"}));
        let view = save_native_napcat_settings(
            &path,
            r#"{"enabled":true,"group_retention_days":99999,"save_policy":"bad"}"#,
        )
        .unwrap();
        assert!(view.enabled);
        assert!(view.access_token_configured);
        assert_eq!(view.group_retention_days, 3650);
        assert_eq!(view.save_policy, "all");
        assert_eq!(napcat_access_token(&path).unwrap(), "secret");
        assert!(!serde_json::to_string(&view).unwrap().contains("secret"));
    }

    #[test]
    fn group_at_policy_stores_once_and_requests_reply() {
        let directory = tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        write_config(
            &config_path,
            json!({
                "napcat_enabled": true,
                "napcat_auto_reply_enabled": true,
                "napcat_reply_group_at_only": true,
                "chat_integration_overlay_enabled": true
            }),
        );
        let event = json!({
            "post_type":"message", "message_type":"group", "self_id":42,
            "user_id":7, "group_id":9, "message_id":11,
            "sender":{"nickname":"Aya"},
            "message":[
                {"type":"at","data":{"qq":"42"}},
                {"type":"text","data":{"text":" hello"}}
            ]
        })
        .to_string();
        let first = ingest_native_napcat_event(&config_path, &database_path, &event).unwrap();
        assert!(first.saved);
        assert!(!first.duplicate);
        assert!(first.should_reply);
        assert!(first.overlay.is_object());
        let duplicate = ingest_native_napcat_event(&config_path, &database_path, &event).unwrap();
        assert!(duplicate.duplicate);
        assert!(!duplicate.should_reply);
        assert!(duplicate.overlay.is_null());
    }

    #[test]
    fn overlay_only_does_not_persist() {
        let directory = tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        write_config(&config_path, json!({"napcat_save_policy":"overlay_only"}));
        let event = json!({
            "post_type":"message", "message_type":"private", "self_id":42,
            "user_id":7, "message_id":12, "raw_message":"hello"
        })
        .to_string();
        let result = ingest_native_napcat_event(&config_path, &database_path, &event).unwrap();
        assert!(!result.saved);
        assert!(result.overlay.is_object());
        let database = Database::open(&database_path).unwrap();
        assert_eq!(
            database
                .external_chat_unread_summary(5, 3)
                .unwrap()
                .total_unread,
            0
        );
    }

    #[test]
    fn reply_job_uses_character_context_and_manual_delete_is_scoped_by_type() {
        let directory = tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        write_config(
            &config_path,
            json!({
                "napcat_enabled": true,
                "napcat_auto_reply_enabled": true,
                "napcat_reply_private": true,
                "models": [{"character":"Aya","costume":"default","path":"models/Aya"}]
            }),
        );
        let event = json!({
            "post_type":"message", "message_type":"private", "self_id":42,
            "user_id":7, "message_id":13,
            "sender":{"nickname":"User"}, "raw_message":"hello"
        })
        .to_string();
        let ingested = ingest_native_napcat_event(&config_path, &database_path, &event).unwrap();
        let job = prepare_native_napcat_reply(
            &config_path,
            directory.path(),
            &database_path,
            &ingested.normalized_event.to_string(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(job.character, "Aya");
        assert!(
            job.messages[1]["content"]
                .as_str()
                .unwrap()
                .contains("最近外部聊天上下文")
        );
        let deleted = delete_native_napcat_records(&database_path, "private").unwrap();
        assert_eq!(deleted.deleted_messages, 1);
        assert!(delete_native_napcat_records(&database_path, "invalid").is_err());
    }
}
