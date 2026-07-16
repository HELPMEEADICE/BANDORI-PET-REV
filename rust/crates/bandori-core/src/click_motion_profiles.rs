use crate::config::{ConfigDocument, ConfigError};
use crate::model::{ModelManager, ModelManagerPaths, ModelRoot};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::Path;
use thiserror::Error;

const REGIONS: &[&str] = &[
    "head",
    "upper_body_left",
    "upper_body_center",
    "upper_body_right",
    "lower_body_left",
    "lower_body_center",
    "lower_body_right",
];
const BUILTIN_NAMES: &[&str] = &[
    "auto",
    "genki",
    "tsundere",
    "shy",
    "cool",
    "surprised",
    "random",
];
const MAX_PROFILES: usize = 128;
const MAX_NAME_CHARS: usize = 80;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ClickMotionProfileSummary {
    pub name: String,
    pub is_builtin: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ClickMotionProfile {
    name: String,
    actions: Map<String, Value>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ClickMotionCommand {
    op: String,
    #[serde(default)]
    character: String,
    #[serde(default)]
    costume: String,
    #[serde(default)]
    name: String,
}

#[derive(Debug, Error)]
pub enum ClickMotionProfileError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("click-motion command JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("invalid click-motion operation: {0}")]
    InvalidOperation(String),
    #[error("invalid click-motion profile name: {0}")]
    InvalidName(String),
    #[error("click-motion profile was not found: {0}")]
    ProfileNotFound(String),
    #[error("pet model is not configured: {0}/{1}")]
    ModelNotConfigured(String, String),
}

pub fn click_motion_profile_summaries(config: &ConfigDocument) -> Vec<ClickMotionProfileSummary> {
    let mut result = BUILTIN_NAMES
        .iter()
        .map(|name| ClickMotionProfileSummary {
            name: (*name).to_owned(),
            is_builtin: true,
        })
        .collect::<Vec<_>>();
    result.extend(
        normalized_custom_profiles(config)
            .into_iter()
            .map(|profile| ClickMotionProfileSummary {
                name: profile.name,
                is_builtin: false,
            }),
    );
    result
}

pub fn normalized_active_click_motion_profile(config: &ConfigDocument) -> String {
    let active = config
        .get("click_motion_active_profile")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    if active.is_empty()
        || BUILTIN_NAMES.contains(&active)
        || normalized_custom_profiles(config)
            .iter()
            .any(|profile| profile.name == active)
    {
        active.to_owned()
    } else {
        String::new()
    }
}

pub fn mutate_click_motion_profiles(
    project_root: impl AsRef<Path>,
    user_models_root: impl AsRef<Path>,
    config_path: impl AsRef<Path>,
    command_json: &str,
) -> Result<String, ClickMotionProfileError> {
    if command_json.len() > 64 * 1024 {
        return Err(ClickMotionProfileError::InvalidOperation(
            "command exceeds 64 KiB".into(),
        ));
    }
    let command: ClickMotionCommand = serde_json::from_str(command_json)?;
    let mut config = ConfigDocument::load(config_path.as_ref())?;
    let result = match command.op.trim() {
        "apply" => apply_profile(
            &mut config,
            project_root.as_ref(),
            user_models_root.as_ref(),
            &command.character,
            &command.costume,
            &command.name,
        )?,
        "save_current" => save_current_profile(
            &mut config,
            project_root.as_ref(),
            user_models_root.as_ref(),
            &command.character,
            &command.costume,
            &command.name,
        )?,
        "delete" => delete_profile(&mut config, &command.name)?,
        other => return Err(ClickMotionProfileError::InvalidOperation(other.into())),
    };
    config.save(config_path)?;
    Ok(result)
}

fn apply_profile(
    config: &mut ConfigDocument,
    project_root: &Path,
    user_models_root: &Path,
    character: &str,
    costume: &str,
    raw_name: &str,
) -> Result<String, ClickMotionProfileError> {
    let (character, costume) = checked_model_identity(character, costume)?;
    let name = raw_name.trim();
    let manager = ModelManager::scan(model_paths(project_root, user_models_root));
    let motions = manager.motion_names(character, costume);
    let expressions = manager.expression_names(character, costume);
    let actions = if name.is_empty() {
        current_model_actions(config, character, costume)
            .ok_or_else(|| model_not_configured(character, costume))?
    } else if BUILTIN_NAMES.contains(&name) {
        resolve_builtin_actions(name, character, &motions, &expressions)
            .expect("checked built-in profile must resolve")
    } else {
        checked_profile_name(name, false)?;
        let profile = normalized_custom_profiles(config)
            .into_iter()
            .find(|profile| profile.name == name)
            .ok_or_else(|| ClickMotionProfileError::ProfileNotFound(name.into()))?;
        normalize_actions(
            Value::Object(profile.actions),
            Some(&motions),
            Some(&expressions),
        )
    };
    write_model_profile(config, character, costume, name, actions)?;
    config.set(
        "click_motion_active_profile",
        Value::String(name.to_owned()),
    );
    Ok(if name.is_empty() {
        "Current custom click behavior selected".into()
    } else {
        format!("Click-motion profile applied: {name}")
    })
}

fn save_current_profile(
    config: &mut ConfigDocument,
    project_root: &Path,
    user_models_root: &Path,
    character: &str,
    costume: &str,
    raw_name: &str,
) -> Result<String, ClickMotionProfileError> {
    let (character, costume) = checked_model_identity(character, costume)?;
    let name = checked_profile_name(raw_name, false)?;
    if BUILTIN_NAMES.contains(&name) {
        return Err(ClickMotionProfileError::InvalidName(name.into()));
    }
    let manager = ModelManager::scan(model_paths(project_root, user_models_root));
    let motions = manager.motion_names(character, costume);
    let expressions = manager.expression_names(character, costume);
    let current = current_model_actions(config, character, costume)
        .ok_or_else(|| model_not_configured(character, costume))?;
    let actions = normalize_actions(Value::Object(current), Some(&motions), Some(&expressions));

    let mut profiles = normalized_custom_profiles(config);
    profiles.retain(|profile| profile.name != name);
    if profiles.len() >= MAX_PROFILES {
        profiles.remove(0);
    }
    profiles.push(ClickMotionProfile {
        name: name.to_owned(),
        actions: actions.clone(),
    });
    config.set(
        "click_motion_profiles",
        Value::Array(profiles.into_iter().map(profile_value).collect()),
    );
    write_model_profile(config, character, costume, name, actions)?;
    config.set(
        "click_motion_active_profile",
        Value::String(name.to_owned()),
    );
    Ok(format!("Click-motion profile saved: {name}"))
}

fn delete_profile(
    config: &mut ConfigDocument,
    raw_name: &str,
) -> Result<String, ClickMotionProfileError> {
    let name = checked_profile_name(raw_name, false)?;
    if BUILTIN_NAMES.contains(&name) {
        return Err(ClickMotionProfileError::InvalidName(name.into()));
    }
    let mut profiles = normalized_custom_profiles(config);
    let before = profiles.len();
    profiles.retain(|profile| profile.name != name);
    if before == profiles.len() {
        return Err(ClickMotionProfileError::ProfileNotFound(name.into()));
    }
    config.set(
        "click_motion_profiles",
        Value::Array(profiles.into_iter().map(profile_value).collect()),
    );
    if config
        .get("click_motion_active_profile")
        .and_then(Value::as_str)
        == Some(name)
    {
        config.set("click_motion_active_profile", Value::String(String::new()));
    }
    clear_deleted_profile_references(config, name);
    Ok(format!("Click-motion profile deleted: {name}"))
}

fn current_model_actions(
    config: &ConfigDocument,
    character: &str,
    costume: &str,
) -> Option<Map<String, Value>> {
    let model = config
        .get("models")
        .and_then(Value::as_array)?
        .iter()
        .filter_map(Value::as_object)
        .find(|model| {
            model.get("character").and_then(Value::as_str) == Some(character)
                && model
                    .get("costume")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    == costume
        })?;
    let direct = model
        .get("click_motion_actions")
        .and_then(Value::as_object)
        .filter(|actions| !actions.is_empty())
        .cloned();
    let profile = config
        .get("model_action_settings")
        .and_then(Value::as_object)
        .and_then(|profiles| profiles.get(&format!("{character}\t{costume}")))
        .and_then(|profile| profile.get("click_motion_actions"))
        .and_then(Value::as_object)
        .cloned();
    Some(direct.or(profile).unwrap_or_default())
}

fn write_model_profile(
    config: &mut ConfigDocument,
    character: &str,
    costume: &str,
    name: &str,
    actions: Map<String, Value>,
) -> Result<(), ClickMotionProfileError> {
    let mut models = config
        .get("models")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let Some(model) = models
        .iter_mut()
        .filter_map(Value::as_object_mut)
        .find(|model| {
            model.get("character").and_then(Value::as_str) == Some(character)
                && model
                    .get("costume")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    == costume
        })
    else {
        return Err(model_not_configured(character, costume));
    };
    model.insert(
        "click_motion_profile_name".into(),
        Value::String(name.to_owned()),
    );
    model.insert(
        "click_motion_actions".into(),
        Value::Object(actions.clone()),
    );
    config.set("models", Value::Array(models));

    let mut settings = config
        .get("model_action_settings")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let key = format!("{character}\t{costume}");
    let mut profile = settings
        .remove(&key)
        .and_then(|value| value.as_object().cloned())
        .unwrap_or_default();
    profile.insert(
        "click_motion_profile_name".into(),
        Value::String(name.to_owned()),
    );
    profile.insert("click_motion_actions".into(), Value::Object(actions));
    settings.insert(key, Value::Object(profile));
    config.set("model_action_settings", Value::Object(settings));
    Ok(())
}

fn clear_deleted_profile_references(config: &mut ConfigDocument, name: &str) {
    let mut models = config
        .get("models")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for model in models.iter_mut().filter_map(Value::as_object_mut) {
        if model
            .get("click_motion_profile_name")
            .and_then(Value::as_str)
            == Some(name)
        {
            model.insert(
                "click_motion_profile_name".into(),
                Value::String(String::new()),
            );
        }
    }
    config.set("models", Value::Array(models));

    let mut settings = config
        .get("model_action_settings")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    for profile in settings.values_mut().filter_map(Value::as_object_mut) {
        if profile
            .get("click_motion_profile_name")
            .and_then(Value::as_str)
            == Some(name)
        {
            profile.insert(
                "click_motion_profile_name".into(),
                Value::String(String::new()),
            );
        }
    }
    config.set("model_action_settings", Value::Object(settings));
}

fn normalized_custom_profiles(config: &ConfigDocument) -> Vec<ClickMotionProfile> {
    let mut result = Vec::new();
    for raw in config
        .get("click_motion_profiles")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if result.len() >= MAX_PROFILES {
            break;
        }
        let Some(profile) = raw.as_object() else {
            continue;
        };
        let Some(name) = profile
            .get("name")
            .and_then(Value::as_str)
            .and_then(|name| checked_profile_name(name, false).ok())
        else {
            continue;
        };
        if BUILTIN_NAMES.contains(&name)
            || result
                .iter()
                .any(|item: &ClickMotionProfile| item.name == name)
        {
            continue;
        }
        let actions = normalize_actions(
            profile
                .get("click_motion_actions")
                .cloned()
                .unwrap_or(Value::Null),
            None,
            None,
        );
        result.push(ClickMotionProfile {
            name: name.to_owned(),
            actions,
        });
    }
    result
}

fn normalize_actions(
    value: Value,
    valid_motions: Option<&[String]>,
    valid_expressions: Option<&[String]>,
) -> Map<String, Value> {
    let Some(raw) = value.as_object() else {
        return Map::new();
    };
    let mut actions = Map::new();
    for region in REGIONS {
        let Some(entry) = raw.get(*region) else {
            continue;
        };
        let (mut motion, mut expression) = if let Some(entry) = entry.as_object() {
            (
                bounded_string(entry.get("motion"), 256),
                bounded_string(entry.get("expression"), 256),
            )
        } else {
            (bounded_string(Some(entry), 256), String::new())
        };
        if let Some(valid) = valid_motions {
            if !motion.is_empty()
                && !matches!(motion.as_str(), "__random__" | "__none__")
                && !valid.contains(&motion)
            {
                motion.clear();
            }
        }
        if let Some(valid) = valid_expressions {
            if !expression.is_empty() && !valid.contains(&expression) {
                expression.clear();
            }
        }
        if motion.is_empty() && expression.is_empty() {
            continue;
        }
        actions.insert(
            (*region).into(),
            Value::Object(Map::from_iter([
                ("motion".into(), Value::String(motion)),
                ("expression".into(), Value::String(expression)),
            ])),
        );
    }
    actions
}

fn resolve_builtin_actions(
    name: &str,
    character: &str,
    motions: &[String],
    expressions: &[String],
) -> Option<Map<String, Value>> {
    if name == "auto" {
        return Some(Map::new());
    }
    if name == "random" {
        return Some(Map::from_iter(REGIONS.iter().map(|region| {
            ((*region).to_owned(), feedback_value("__random__", ""))
        })));
    }
    let tags: &[&str] = match name {
        "genki" => &[
            "smile", "nf_left", "smile", "nf_right", "smile", "kime", "smile",
        ],
        "tsundere" => &["shame", "pui", "angry", "pui", "shame", "angry", "serious"],
        "shy" => &[
            "shame",
            "nnf_left",
            "shame",
            "nnf_right",
            "sad",
            "shame",
            "sad",
        ],
        "cool" => &[
            "serious", "kime", "serious", "kime", "serious", "kime", "serious",
        ],
        "surprised" => &["surprised"; 7],
        _ => return None,
    };
    let mut result = Map::new();
    for (region, tag) in REGIONS.iter().zip(tags) {
        let motion = resolve_motion(tag, motions, character).unwrap_or_default();
        let expression = resolve_expression(tag, expressions, character).unwrap_or_default();
        if !motion.is_empty() || !expression.is_empty() {
            result.insert((*region).to_owned(), feedback_value(motion, expression));
        }
    }
    Some(result)
}

fn resolve_motion<'a>(tag: &str, motions: &'a [String], character: &str) -> Option<&'a str> {
    let candidates: &[&str] = if tag == "thinking" {
        &["thinking", "nf", "nnf", "eeto", "odoodo"]
    } else {
        &[tag]
    };
    for candidate in candidates {
        let candidate = candidate.to_lowercase();
        let character_candidate = format!("{}_{}", character.to_lowercase(), candidate);
        if let Some(found) = motions.iter().find(|motion| {
            let motion = motion.to_lowercase();
            motion == candidate
                || motion.starts_with(&candidate)
                || motion == character_candidate
                || motion.starts_with(&character_candidate)
                || contains_action_token(&motion, &candidate)
        }) {
            return Some(found);
        }
    }
    None
}

fn resolve_expression<'a>(
    tag: &str,
    expressions: &'a [String],
    character: &str,
) -> Option<&'a str> {
    let mapped: &[&str] = match tag {
        "sad" => &["sad", "cry"],
        "nf" | "nf_left" | "nf_right" | "nnf" | "nnf_left" | "nnf_right" => &["smile", "idle"],
        "kandou" => &["surprised", "kime"],
        "cry" => &["cry", "sad"],
        "idle" => &["idle", "default"],
        "scared" => &["surprised"],
        "thinking" => &["serious", "idle"],
        "stare" => &["serious", "kime"],
        "bye" | "wink" | "nod" => &["smile", "idle"],
        "odoodo" => &["shame", "serious"],
        _ => &[tag],
    };
    for candidate in mapped {
        let candidate = candidate.to_lowercase();
        let character_candidate = format!("{}_{}", character.to_lowercase(), candidate);
        if let Some(found) = expressions.iter().find(|expression| {
            let expression = expression.to_lowercase();
            expression == candidate
                || expression.starts_with(&candidate)
                || expression == character_candidate
                || expression.starts_with(&character_candidate)
                || contains_action_token(&expression, &candidate)
        }) {
            return Some(found);
        }
    }
    for fallback in ["default", "idle", "smile"] {
        if let Some(found) = expressions
            .iter()
            .find(|expression| expression.to_lowercase().contains(fallback))
        {
            return Some(found);
        }
    }
    expressions.first().map(String::as_str)
}

fn contains_action_token(name: &str, candidate: &str) -> bool {
    name.split(['_', '-']).any(|part| {
        part == candidate
            || part.strip_prefix(candidate).is_some_and(|suffix| {
                !suffix.is_empty() && suffix.chars().all(|value| value.is_ascii_digit())
            })
    })
}

fn feedback_value(motion: impl Into<String>, expression: impl Into<String>) -> Value {
    Value::Object(Map::from_iter([
        ("motion".into(), Value::String(motion.into())),
        ("expression".into(), Value::String(expression.into())),
    ]))
}

fn profile_value(profile: ClickMotionProfile) -> Value {
    Value::Object(Map::from_iter([
        ("name".into(), Value::String(profile.name)),
        (
            "click_motion_actions".into(),
            Value::Object(profile.actions),
        ),
    ]))
}

fn checked_model_identity<'a>(
    character: &'a str,
    costume: &'a str,
) -> Result<(&'a str, &'a str), ClickMotionProfileError> {
    let character = character.trim();
    let costume = costume.trim();
    if character.is_empty()
        || costume.is_empty()
        || character.chars().count() > 128
        || costume.chars().count() > 128
        || [character, costume].iter().any(|value| {
            value
                .chars()
                .any(|character| matches!(character, '/' | '\\' | '\0' | '\t'))
        })
    {
        return Err(model_not_configured(character, costume));
    }
    Ok((character, costume))
}

fn checked_profile_name(name: &str, allow_empty: bool) -> Result<&str, ClickMotionProfileError> {
    let name = name.trim();
    if name.is_empty() && allow_empty {
        return Ok(name);
    }
    if name.is_empty()
        || name.chars().count() > MAX_NAME_CHARS
        || name.chars().any(char::is_control)
    {
        return Err(ClickMotionProfileError::InvalidName(name.into()));
    }
    Ok(name)
}

fn bounded_string(value: Option<&Value>, maximum_chars: usize) -> String {
    value
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .chars()
        .take(maximum_chars)
        .collect()
}

fn model_not_configured(character: &str, costume: &str) -> ClickMotionProfileError {
    ClickMotionProfileError::ModelNotConfigured(character.into(), costume.into())
}

fn model_paths(project_root: &Path, user_models_root: &Path) -> ModelManagerPaths {
    let bundled = project_root.join("models");
    let user = if user_models_root.as_os_str().is_empty() {
        bundled.clone()
    } else {
        user_models_root.to_path_buf()
    };
    let mut search_roots = vec![ModelRoot {
        path: bundled.clone(),
        override_existing: false,
    }];
    if user != bundled {
        search_roots.push(ModelRoot {
            path: user.clone(),
            override_existing: true,
        });
    }
    let mut lookup_roots = vec![user];
    if !lookup_roots.contains(&bundled) {
        lookup_roots.push(bundled);
    }
    ModelManagerPaths {
        base_dir: project_root.to_path_buf(),
        search_roots,
        lookup_roots,
        outfit_json: project_root.join("outfit.json"),
        band_json: project_root.join("band.json"),
        characters_dir: project_root.join("characters"),
        custom_models_label: "Custom Models".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use tempfile::tempdir;

    fn fixture() -> (tempfile::TempDir, std::path::PathBuf, std::path::PathBuf) {
        let root = tempdir().unwrap();
        let model_dir = root.path().join("models/aya/live_01");
        fs::create_dir_all(&model_dir).unwrap();
        fs::write(
            model_dir.join("aya.model3.json"),
            serde_json::to_vec(&json!({
                "Version": 3,
                "FileReferences": {
                    "Moc": "aya.moc3",
                    "Motions": {
                        "kime": [{"File": "motions/kime.motion3.json"}],
                        "nf_left": [{"File": "motions/nf_left.motion3.json"}],
                        "nf_right": [{"File": "motions/nf_right.motion3.json"}],
                        "smile": [{"File": "motions/smile.motion3.json"}]
                    },
                    "Expressions": [
                        {"Name": "smile", "File": "expressions/smile.exp3.json"},
                        {"Name": "default", "File": "expressions/default.exp3.json"}
                    ]
                }
            }))
            .unwrap(),
        )
        .unwrap();
        let config_path = root.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.set(
            "models",
            json!([{
                "character": "aya",
                "costume": "live_01",
                "path": model_dir.join("aya.model3.json").to_string_lossy(),
                "click_motion_actions": {"head": {"motion": "smile", "expression": "smile"}}
            }]),
        );
        config.save(&config_path).unwrap();
        (root, config_path, model_dir)
    }

    #[test]
    fn builtins_and_custom_crud_persist_model_actions_and_active_profile() {
        let (root, config_path, _) = fixture();
        mutate_click_motion_profiles(
            root.path(),
            root.path().join("user-models"),
            &config_path,
            r#"{"op":"apply","character":"aya","costume":"live_01","name":"genki"}"#,
        )
        .unwrap();
        let applied = ConfigDocument::load(&config_path).unwrap();
        assert_eq!(
            applied.get("click_motion_active_profile"),
            Some(&Value::String("genki".into()))
        );
        let model = &applied.get("models").unwrap().as_array().unwrap()[0];
        assert_eq!(model["click_motion_profile_name"], "genki");
        assert_eq!(model["click_motion_actions"]["head"]["motion"], "smile");
        assert_eq!(
            model["click_motion_actions"]["upper_body_left"]["motion"],
            "nf_left"
        );

        mutate_click_motion_profiles(
            root.path(),
            root.path().join("user-models"),
            &config_path,
            r#"{"op":"save_current","character":"aya","costume":"live_01","name":"my profile"}"#,
        )
        .unwrap();
        let saved = ConfigDocument::load(&config_path).unwrap();
        assert_eq!(normalized_active_click_motion_profile(&saved), "my profile");
        assert!(
            click_motion_profile_summaries(&saved)
                .iter()
                .any(|profile| { profile.name == "my profile" && !profile.is_builtin })
        );

        mutate_click_motion_profiles(
            root.path(),
            root.path().join("user-models"),
            &config_path,
            r#"{"op":"delete","name":"my profile"}"#,
        )
        .unwrap();
        let deleted = ConfigDocument::load(&config_path).unwrap();
        assert_eq!(normalized_active_click_motion_profile(&deleted), "");
        assert_eq!(
            deleted.get("models").unwrap().as_array().unwrap()[0]["click_motion_profile_name"],
            ""
        );
        assert!(
            !click_motion_profile_summaries(&deleted)
                .iter()
                .any(|profile| profile.name == "my profile")
        );
    }

    #[test]
    fn invalid_commands_reserved_names_and_unconfigured_models_fail_closed() {
        let (root, config_path, _) = fixture();
        for command in [
            r#"{"op":"save_current","character":"aya","costume":"live_01","name":"auto"}"#,
            r#"{"op":"apply","character":"aya","costume":"missing","name":"genki"}"#,
            r#"{"op":"unknown","name":"x"}"#,
            r#"{"op":"delete","name":"missing"}"#,
        ] {
            assert!(
                mutate_click_motion_profiles(
                    root.path(),
                    root.path().join("user-models"),
                    &config_path,
                    command,
                )
                .is_err()
            );
        }
        let python = include_str!("../../../../click_motion_presets.py");
        for name in BUILTIN_NAMES {
            assert!(python.contains(&format!("\"name\": \"{name}\"")));
        }
    }
}
