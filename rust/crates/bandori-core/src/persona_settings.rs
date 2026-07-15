use crate::chat_prompt::load_character_markdown;
use crate::config::{ConfigDocument, ConfigError};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha1::{Digest, Sha1};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

const MAX_POV_PERSONAS: usize = 128;
const MAX_CHARACTER_PERSONAS: usize = 128;
const MAX_CHARACTER_COUNT: usize = 256;
const MAX_CHARACTER_BYTES: usize = 128;
const MAX_TITLE_BYTES: usize = 512;
const MAX_PROMPT_BYTES: usize = 512 * 1024;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativePovPersona {
    pub title: String,
    pub prompt: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeCharacterPersona {
    pub id: String,
    pub title: String,
    pub prompt: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeCharacterPersonaCollection {
    pub character: String,
    pub active_id: String,
    pub default_prompt: String,
    pub presets: Vec<NativeCharacterPersona>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativePersonaSettingsState {
    pub pov_mode: String,
    pub pov_custom_prompt: String,
    pub pov_role_character: String,
    pub pov_personas: Vec<NativePovPersona>,
    pub characters: Vec<NativeCharacterPersonaCollection>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum NativePersonaMutation {
    SavePov {
        mode: String,
        custom_prompt: String,
        role_character: String,
        now: String,
    },
    SavePovPersona {
        #[serde(default)]
        title: String,
        prompt: String,
        now: String,
    },
    DeletePovPersona {
        prompt: String,
        now: String,
    },
    ActivateCharacterPersona {
        character: String,
        preset_id: String,
        now: String,
    },
    SaveCharacterPersona {
        character: String,
        #[serde(default)]
        preset_id: String,
        #[serde(default)]
        title: String,
        prompt: String,
        now: String,
    },
    DeleteCharacterPersona {
        character: String,
        preset_id: String,
        now: String,
    },
}

impl NativePersonaMutation {
    fn timestamp(&self) -> &str {
        match self {
            Self::SavePov { now, .. }
            | Self::SavePovPersona { now, .. }
            | Self::DeletePovPersona { now, .. }
            | Self::ActivateCharacterPersona { now, .. }
            | Self::SaveCharacterPersona { now, .. }
            | Self::DeleteCharacterPersona { now, .. } => now,
        }
    }
}

#[derive(Debug, Error)]
pub enum NativePersonaSettingsError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("native persona command JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native persona operation is invalid: {0}")]
    Invalid(String),
}

pub fn load_native_persona_settings(
    config_path: &Path,
    project_root: &Path,
    known_characters: &[String],
) -> Result<NativePersonaSettingsState, NativePersonaSettingsError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(normalized_state(
        &config,
        project_root,
        known_characters,
        "",
    ))
}

pub fn mutate_native_persona_settings(
    config_path: &Path,
    project_root: &Path,
    known_characters: &[String],
    command_json: &str,
    max_bytes: usize,
) -> Result<NativePersonaSettingsState, NativePersonaSettingsError> {
    if command_json.len() > max_bytes {
        return Err(NativePersonaSettingsError::Invalid(format!(
            "command exceeds the {max_bytes} byte limit"
        )));
    }
    let command = serde_json::from_str::<NativePersonaMutation>(command_json)?;
    let now = checked_timestamp(command.timestamp())?;
    let mut config = ConfigDocument::load(config_path)?;
    let mut state = normalized_state(&config, project_root, known_characters, &now);

    match command {
        NativePersonaMutation::SavePov {
            mode,
            custom_prompt,
            role_character,
            ..
        } => {
            let mode = checked_pov_mode(&mode)?;
            let role_character = checked_character_allow_empty(&role_character)?;
            if mode == "role" && role_character.is_empty() {
                return Err(NativePersonaSettingsError::Invalid(
                    "role POV requires a character".to_owned(),
                ));
            }
            state.pov_mode = mode;
            state.pov_custom_prompt = checked_prompt_allow_empty(&custom_prompt)?;
            state.pov_role_character = role_character;
        }
        NativePersonaMutation::SavePovPersona { title, prompt, .. } => {
            let prompt = checked_prompt(&prompt)?;
            let title = checked_title_or_derive(&title, &prompt, 24)?;
            state
                .pov_personas
                .retain(|persona| persona.prompt != prompt);
            if state.pov_personas.len() >= MAX_POV_PERSONAS {
                return Err(NativePersonaSettingsError::Invalid(format!(
                    "at most {MAX_POV_PERSONAS} POV personas can be saved"
                )));
            }
            state.pov_personas.push(NativePovPersona {
                title,
                prompt: prompt.clone(),
            });
            state.pov_custom_prompt = prompt;
        }
        NativePersonaMutation::DeletePovPersona { prompt, .. } => {
            let prompt = checked_prompt(&prompt)?;
            let previous = state.pov_personas.len();
            state
                .pov_personas
                .retain(|persona| persona.prompt != prompt);
            if state.pov_personas.len() == previous {
                return Err(NativePersonaSettingsError::Invalid(
                    "selected POV persona does not exist".to_owned(),
                ));
            }
        }
        NativePersonaMutation::ActivateCharacterPersona {
            character,
            preset_id,
            ..
        } => {
            let character = checked_character(&character)?;
            let preset_id = checked_id_allow_empty(&preset_id)?;
            let collection = ensure_collection(&mut state, project_root, &character)?;
            if !preset_id.is_empty()
                && !collection
                    .presets
                    .iter()
                    .any(|preset| preset.id == preset_id)
            {
                return Err(NativePersonaSettingsError::Invalid(
                    "selected character persona does not exist".to_owned(),
                ));
            }
            collection.active_id = preset_id;
        }
        NativePersonaMutation::SaveCharacterPersona {
            character,
            preset_id,
            title,
            prompt,
            ..
        } => {
            let character = checked_character(&character)?;
            let prompt = checked_prompt(&prompt)?;
            let title = checked_title_or_derive(&title, &prompt, 32)?;
            let preset_id = checked_id_allow_empty(&preset_id)?;
            let collection = ensure_collection(&mut state, project_root, &character)?;
            let id = if preset_id.is_empty() {
                if collection.presets.len() >= MAX_CHARACTER_PERSONAS {
                    return Err(NativePersonaSettingsError::Invalid(format!(
                        "at most {MAX_CHARACTER_PERSONAS} personas can be saved per character"
                    )));
                }
                let existing = collection
                    .presets
                    .iter()
                    .map(|preset| preset.id.as_str())
                    .collect::<HashSet<_>>();
                let id = new_persona_id(&character, &title, &prompt, &now, &existing);
                collection.presets.push(NativeCharacterPersona {
                    id: id.clone(),
                    title,
                    prompt,
                    created_at: now.clone(),
                    updated_at: now.clone(),
                });
                id
            } else if let Some(preset) = collection
                .presets
                .iter_mut()
                .find(|preset| preset.id == preset_id)
            {
                preset.title = title;
                preset.prompt = prompt;
                preset.updated_at = now.clone();
                preset.id.clone()
            } else {
                return Err(NativePersonaSettingsError::Invalid(
                    "selected character persona does not exist".to_owned(),
                ));
            };
            collection.active_id = id;
        }
        NativePersonaMutation::DeleteCharacterPersona {
            character,
            preset_id,
            ..
        } => {
            let character = checked_character(&character)?;
            let preset_id = checked_id(&preset_id)?;
            let collection = ensure_collection(&mut state, project_root, &character)?;
            let previous = collection.presets.len();
            collection.presets.retain(|preset| preset.id != preset_id);
            if collection.presets.len() == previous {
                return Err(NativePersonaSettingsError::Invalid(
                    "selected character persona does not exist".to_owned(),
                ));
            }
            if collection.active_id == preset_id {
                collection.active_id.clear();
            }
        }
    }

    persist_state(&mut config, &state);
    config.save(config_path)?;
    Ok(state)
}

fn normalized_state(
    config: &ConfigDocument,
    project_root: &Path,
    known_characters: &[String],
    fallback_timestamp: &str,
) -> NativePersonaSettingsState {
    let pov_mode = match config_string(config, "pov_mode").as_str() {
        "custom" => "custom",
        "role" => "role",
        _ => "off",
    }
    .to_owned();
    let pov_custom_prompt = normalized_prompt(&config_string(config, "pov_custom_prompt"));
    let pov_role_character = clean_character(&config_string(config, "pov_role_character"));
    let pov_personas = normalized_pov_personas(config.get("pov_custom_personas"));
    let presets =
        normalized_character_presets(config.get("character_persona_presets"), fallback_timestamp);
    let active = normalized_character_active(config.get("character_persona_active"), &presets);
    let mut character_keys = BTreeSet::new();
    for character in known_characters {
        insert_character(&mut character_keys, character);
    }
    insert_character(&mut character_keys, &config_string(config, "character"));
    insert_character(&mut character_keys, &pov_role_character);
    for model in config
        .get("models")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        insert_character(
            &mut character_keys,
            model
                .get("character")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        );
    }
    character_keys.extend(presets.keys().cloned());
    character_keys.extend(active.keys().cloned());
    let characters = character_keys
        .into_iter()
        .take(MAX_CHARACTER_COUNT)
        .map(|character| NativeCharacterPersonaCollection {
            active_id: active.get(&character).cloned().unwrap_or_default(),
            default_prompt: load_character_markdown(project_root, &character),
            presets: presets.get(&character).cloned().unwrap_or_default(),
            character,
        })
        .collect();

    NativePersonaSettingsState {
        pov_mode,
        pov_custom_prompt,
        pov_role_character,
        pov_personas,
        characters,
    }
}

fn normalized_pov_personas(value: Option<&Value>) -> Vec<NativePovPersona> {
    let mut personas = Vec::new();
    let mut seen = HashSet::new();
    for item in value.and_then(Value::as_array).into_iter().flatten() {
        let Some(object) = item.as_object() else {
            continue;
        };
        let prompt = normalized_prompt(object_string(object, "prompt"));
        if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES || !seen.insert(prompt.clone()) {
            continue;
        }
        let title = normalized_title(object_string(object, "title"));
        personas.push(NativePovPersona {
            title: if title.is_empty() {
                title_from_prompt(&prompt, 24)
            } else {
                title
            },
            prompt,
        });
        if personas.len() >= MAX_POV_PERSONAS {
            break;
        }
    }
    personas
}

fn normalized_character_presets(
    value: Option<&Value>,
    fallback_timestamp: &str,
) -> BTreeMap<String, Vec<NativeCharacterPersona>> {
    let mut result = BTreeMap::new();
    let Some(root) = value.and_then(Value::as_object) else {
        return result;
    };
    for (raw_character, raw_presets) in root {
        let character = clean_character(raw_character);
        if character.is_empty() || character.len() > MAX_CHARACTER_BYTES {
            continue;
        }
        let mut presets = Vec::new();
        let mut seen = HashSet::new();
        for item in raw_presets.as_array().into_iter().flatten() {
            let Some(object) = item.as_object() else {
                continue;
            };
            let prompt = normalized_prompt(object_string(object, "prompt"));
            if prompt.is_empty() || prompt.len() > MAX_PROMPT_BYTES {
                continue;
            }
            let raw_id = clean_id(object_string(object, "id"));
            let id = if raw_id.is_empty() || seen.contains(&raw_id) {
                new_persona_id(
                    &character,
                    object_string(object, "title"),
                    &prompt,
                    fallback_timestamp,
                    &seen.iter().map(String::as_str).collect(),
                )
            } else {
                raw_id
            };
            seen.insert(id.clone());
            let title = normalized_title(object_string(object, "title"));
            let created_at = normalized_timestamp(object_string(object, "created_at"));
            let created_at = if created_at.is_empty() {
                fallback_timestamp.to_owned()
            } else {
                created_at
            };
            let updated_at = normalized_timestamp(object_string(object, "updated_at"));
            let updated_at = if updated_at.is_empty() {
                created_at.clone()
            } else {
                updated_at
            };
            presets.push(NativeCharacterPersona {
                id,
                title: if title.is_empty() {
                    title_from_prompt(&prompt, 32)
                } else {
                    title
                },
                prompt,
                created_at,
                updated_at,
            });
            if presets.len() >= MAX_CHARACTER_PERSONAS {
                break;
            }
        }
        if !presets.is_empty() {
            result.insert(character, presets);
        }
        if result.len() >= MAX_CHARACTER_COUNT {
            break;
        }
    }
    result
}

fn normalized_character_active(
    value: Option<&Value>,
    presets: &BTreeMap<String, Vec<NativeCharacterPersona>>,
) -> BTreeMap<String, String> {
    let mut active = BTreeMap::new();
    for (raw_character, raw_id) in value.and_then(Value::as_object).into_iter().flatten() {
        let character = clean_character(raw_character);
        let id = clean_id(raw_id.as_str().unwrap_or_default());
        if !character.is_empty()
            && !id.is_empty()
            && presets
                .get(&character)
                .is_some_and(|items| items.iter().any(|preset| preset.id == id))
        {
            active.insert(character, id);
        }
    }
    active
}

fn ensure_collection<'a>(
    state: &'a mut NativePersonaSettingsState,
    project_root: &Path,
    character: &str,
) -> Result<&'a mut NativeCharacterPersonaCollection, NativePersonaSettingsError> {
    if let Some(index) = state
        .characters
        .iter()
        .position(|collection| collection.character == character)
    {
        return Ok(&mut state.characters[index]);
    }
    if state.characters.len() >= MAX_CHARACTER_COUNT {
        return Err(NativePersonaSettingsError::Invalid(format!(
            "at most {MAX_CHARACTER_COUNT} characters can have persona state"
        )));
    }
    state.characters.push(NativeCharacterPersonaCollection {
        character: character.to_owned(),
        active_id: String::new(),
        default_prompt: load_character_markdown(project_root, character),
        presets: Vec::new(),
    });
    state
        .characters
        .sort_by(|left, right| left.character.cmp(&right.character));
    let index = state
        .characters
        .iter()
        .position(|collection| collection.character == character)
        .expect("inserted character persona collection must exist");
    Ok(&mut state.characters[index])
}

fn persist_state(config: &mut ConfigDocument, state: &NativePersonaSettingsState) {
    config.set("pov_mode", json!(state.pov_mode));
    config.set("pov_custom_prompt", json!(state.pov_custom_prompt));
    config.set("pov_role_character", json!(state.pov_role_character));
    config.set(
        "pov_custom_personas",
        serde_json::to_value(&state.pov_personas).unwrap(),
    );
    let mut presets = Map::new();
    let mut active = Map::new();
    for collection in &state.characters {
        if !collection.presets.is_empty() {
            presets.insert(
                collection.character.clone(),
                serde_json::to_value(&collection.presets).unwrap(),
            );
        }
        if !collection.active_id.is_empty() {
            active.insert(
                collection.character.clone(),
                Value::String(collection.active_id.clone()),
            );
        }
    }
    config.set("character_persona_presets", Value::Object(presets));
    config.set("character_persona_active", Value::Object(active));
}

fn checked_pov_mode(value: &str) -> Result<String, NativePersonaSettingsError> {
    match value.trim() {
        "off" | "custom" | "role" => Ok(value.trim().to_owned()),
        _ => Err(NativePersonaSettingsError::Invalid(
            "POV mode must be off, custom, or role".to_owned(),
        )),
    }
}

fn checked_character(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = checked_character_allow_empty(value)?;
    if value.is_empty() {
        Err(NativePersonaSettingsError::Invalid(
            "character cannot be empty".to_owned(),
        ))
    } else {
        Ok(value)
    }
}

fn checked_character_allow_empty(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = clean_character(value);
    if value.len() > MAX_CHARACTER_BYTES || value.chars().any(char::is_control) {
        Err(NativePersonaSettingsError::Invalid(
            "character key is too long or contains control characters".to_owned(),
        ))
    } else {
        Ok(value)
    }
}

fn checked_prompt(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = checked_prompt_allow_empty(value)?;
    if value.is_empty() {
        Err(NativePersonaSettingsError::Invalid(
            "persona prompt cannot be empty".to_owned(),
        ))
    } else {
        Ok(value)
    }
}

fn checked_prompt_allow_empty(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = value.trim();
    if value.len() > MAX_PROMPT_BYTES {
        Err(NativePersonaSettingsError::Invalid(format!(
            "persona prompt exceeds the {MAX_PROMPT_BYTES} byte limit"
        )))
    } else {
        Ok(value.to_owned())
    }
}

fn checked_title_or_derive(
    value: &str,
    prompt: &str,
    max_chars: usize,
) -> Result<String, NativePersonaSettingsError> {
    let title = normalized_title(value);
    if title.len() > MAX_TITLE_BYTES || title.chars().any(char::is_control) {
        return Err(NativePersonaSettingsError::Invalid(
            "persona title is too long or contains control characters".to_owned(),
        ));
    }
    Ok(if title.is_empty() {
        title_from_prompt(prompt, max_chars)
    } else {
        title
    })
}

fn checked_id(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = checked_id_allow_empty(value)?;
    if value.is_empty() {
        Err(NativePersonaSettingsError::Invalid(
            "persona id cannot be empty".to_owned(),
        ))
    } else {
        Ok(value)
    }
}

fn checked_id_allow_empty(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = clean_id(value);
    if value.len() > 128 || value.chars().any(char::is_control) {
        Err(NativePersonaSettingsError::Invalid(
            "persona id is too long or contains control characters".to_owned(),
        ))
    } else {
        Ok(value)
    }
}

fn checked_timestamp(value: &str) -> Result<String, NativePersonaSettingsError> {
    let value = normalized_timestamp(value);
    let bytes = value.as_bytes();
    let shape = bytes.len() == 19
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes[10] == b'T'
        && bytes[13] == b':'
        && bytes[16] == b':'
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| matches!(index, 4 | 7 | 10 | 13 | 16) || byte.is_ascii_digit());
    if shape {
        Ok(value)
    } else {
        Err(NativePersonaSettingsError::Invalid(
            "timestamp must use yyyy-MM-ddTHH:mm:ss".to_owned(),
        ))
    }
}

fn title_from_prompt(prompt: &str, max_chars: usize) -> String {
    let mut title = prompt
        .lines()
        .find(|line| !line.trim().is_empty())
        .unwrap_or_default()
        .trim_matches(|character: char| character == '#' || character.is_whitespace())
        .chars()
        .take(max_chars + 1)
        .collect::<String>();
    if title.chars().count() > max_chars {
        title = title.chars().take(max_chars).collect::<String>();
        title.push_str("...");
    }
    if title.is_empty() {
        "Persona".to_owned()
    } else {
        title
    }
}

fn new_persona_id(
    character: &str,
    title: &str,
    prompt: &str,
    timestamp: &str,
    existing: &HashSet<&str>,
) -> String {
    static NEXT_ID: AtomicU64 = AtomicU64::new(1);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let mut nonce = NEXT_ID.fetch_add(1, Ordering::Relaxed);
    loop {
        let mut digest = Sha1::new();
        digest.update(character.as_bytes());
        digest.update(title.as_bytes());
        digest.update(prompt.as_bytes());
        digest.update(timestamp.as_bytes());
        digest.update(nanos.to_le_bytes());
        digest.update(nonce.to_le_bytes());
        let id = format!("{:x}", digest.finalize())[..32].to_owned();
        if !existing.contains(id.as_str()) {
            return id;
        }
        nonce = nonce.wrapping_add(1);
    }
}

fn insert_character(target: &mut BTreeSet<String>, value: &str) {
    let value = clean_character(value);
    if !value.is_empty() && value.len() <= MAX_CHARACTER_BYTES {
        target.insert(value);
    }
}

fn normalized_title(value: &str) -> String {
    value.trim().to_owned()
}

fn normalized_prompt(value: &str) -> String {
    value.trim().to_owned()
}

fn normalized_timestamp(value: &str) -> String {
    value.trim().to_owned()
}

fn clean_character(value: &str) -> String {
    value.trim().to_owned()
}

fn clean_id(value: &str) -> String {
    value.trim().to_owned()
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn object_string<'a>(object: &'a Map<String, Value>, key: &str) -> &'a str {
    object.get(key).and_then(Value::as_str).unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    const NOW: &str = "2026-07-15T12:34:56";

    fn command(value: Value) -> String {
        serde_json::to_string(&value).unwrap()
    }

    #[test]
    fn normalizes_pov_personas_and_character_active_ids() {
        let config = ConfigDocument::from_value(
            json!({
                "pov_mode": "broken",
                "pov_custom_personas": [
                    {"title":"", "prompt":"  First persona  "},
                    {"title":"duplicate", "prompt":"First persona"},
                    {"prompt":""}
                ],
                "character_persona_presets": {
                    "ran": [
                        {"id":"ran-1", "title":"", "prompt":"# Cool Ran"},
                        {"id":"ran-1", "title":"Duplicate id", "prompt":"Second"}
                    ]
                },
                "character_persona_active": {"ran":"missing"}
            }),
            true,
        )
        .unwrap();
        let state = normalized_state(&config, Path::new("."), &["ran".to_owned()], NOW);
        assert_eq!(state.pov_mode, "off");
        assert_eq!(state.pov_personas.len(), 1);
        assert_eq!(state.pov_personas[0].title, "First persona");
        assert_eq!(state.characters.len(), 1);
        assert_eq!(state.characters[0].presets.len(), 2);
        assert_ne!(
            state.characters[0].presets[0].id,
            state.characters[0].presets[1].id
        );
        assert!(state.characters[0].active_id.is_empty());
    }

    #[test]
    fn saves_and_deletes_pov_personas_without_duplicates() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("config.json");
        let project = directory.path();
        let save = |value| {
            mutate_native_persona_settings(&path, project, &[], &command(value), 1024 * 1024)
                .unwrap()
        };
        let state = save(json!({
            "op":"save_pov_persona",
            "title":"",
            "prompt":"  Longtime Roselia fan  ",
            "now":NOW
        }));
        assert_eq!(state.pov_personas.len(), 1);
        assert_eq!(state.pov_custom_prompt, "Longtime Roselia fan");
        let state = save(json!({
            "op":"save_pov_persona",
            "title":"Fan",
            "prompt":"Longtime Roselia fan",
            "now":NOW
        }));
        assert_eq!(state.pov_personas.len(), 1);
        assert_eq!(state.pov_personas[0].title, "Fan");
        let state = save(json!({
            "op":"save_pov",
            "mode":"custom",
            "custom_prompt":"Longtime Roselia fan",
            "role_character":"",
            "now":NOW
        }));
        assert_eq!(state.pov_mode, "custom");
        let state = save(json!({
            "op":"delete_pov_persona",
            "prompt":"Longtime Roselia fan",
            "now":NOW
        }));
        assert!(state.pov_personas.is_empty());
    }

    #[test]
    fn character_persona_crud_activates_and_falls_back_to_default() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("config.json");
        let created = mutate_native_persona_settings(
            &path,
            directory.path(),
            &["ran".to_owned()],
            &command(json!({
                "op":"save_character_persona",
                "character":"ran",
                "preset_id":"",
                "title":"",
                "prompt":"# Alternate Ran\nDirect but kind.",
                "now":NOW
            })),
            1024 * 1024,
        )
        .unwrap();
        let collection = &created.characters[0];
        assert_eq!(collection.presets.len(), 1);
        assert_eq!(collection.active_id, collection.presets[0].id);
        assert_eq!(collection.presets[0].title, "Alternate Ran");
        let id = collection.active_id.clone();

        let updated = mutate_native_persona_settings(
            &path,
            directory.path(),
            &["ran".to_owned()],
            &command(json!({
                "op":"save_character_persona",
                "character":"ran",
                "preset_id":id,
                "title":"Updated",
                "prompt":"Updated prompt",
                "now":"2026-07-15T12:35:00"
            })),
            1024 * 1024,
        )
        .unwrap();
        assert_eq!(updated.characters[0].presets[0].title, "Updated");

        let deleted = mutate_native_persona_settings(
            &path,
            directory.path(),
            &["ran".to_owned()],
            &command(json!({
                "op":"delete_character_persona",
                "character":"ran",
                "preset_id":id,
                "now":NOW
            })),
            1024 * 1024,
        )
        .unwrap();
        assert!(deleted.characters[0].presets.is_empty());
        assert!(deleted.characters[0].active_id.is_empty());
    }

    #[test]
    fn invalid_role_or_unknown_preset_does_not_rewrite_config() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("config.json");
        fs::write(&path, "{\"pov_mode\":\"off\"}").unwrap();
        let before = fs::read(&path).unwrap();
        let error = mutate_native_persona_settings(
            &path,
            directory.path(),
            &["ran".to_owned()],
            &command(json!({
                "op":"save_pov",
                "mode":"role",
                "custom_prompt":"",
                "role_character":"",
                "now":NOW
            })),
            1024,
        )
        .unwrap_err();
        assert!(error.to_string().contains("requires a character"));
        assert_eq!(fs::read(&path).unwrap(), before);

        let error = mutate_native_persona_settings(
            &path,
            directory.path(),
            &["ran".to_owned()],
            &command(json!({
                "op":"activate_character_persona",
                "character":"ran",
                "preset_id":"missing",
                "now":NOW
            })),
            1024,
        )
        .unwrap_err();
        assert!(error.to_string().contains("does not exist"));
        assert_eq!(fs::read(&path).unwrap(), before);
    }
}
