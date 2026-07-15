use crate::database::{CharacterMemory, Database, DatabaseError, RelationshipState};
use crate::memory_extraction::GLOBAL_MEMORY_CHARACTER;
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;

const MAX_CHARACTER_BYTES: usize = 128;
const MAX_USER_KEY_BYTES: usize = 256;
const MAX_MEMORY_CONTENT_BYTES: usize = 16 * 1024;
const MAX_DELETE_IDS: usize = 100;
const ALLOWED_KINDS: [&str; 6] = [
    "manual",
    "favorite",
    "profile",
    "preference",
    "relationship",
    "note",
];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeMemorySnapshot {
    pub character: String,
    pub user_key: String,
    pub relationship: Option<RelationshipState>,
    pub memories: Vec<CharacterMemory>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum NativeMemoryMutation {
    SaveMemory {
        #[serde(default)]
        id: i64,
        kind: String,
        content: String,
        importance: i64,
    },
    DeleteMemories {
        ids: Vec<i64>,
    },
}

#[derive(Debug, Error)]
pub enum NativeMemoryError {
    #[error(transparent)]
    Database(#[from] DatabaseError),
    #[error("native memory command JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native memory operation is invalid: {0}")]
    Invalid(String),
}

pub fn load_native_memory_snapshot(
    database_path: &Path,
    character: &str,
    user_key: &str,
    limit: i64,
) -> Result<NativeMemorySnapshot, NativeMemoryError> {
    let character = checked_partition(character, MAX_CHARACTER_BYTES, "character")?;
    let user_key = checked_partition(user_key, MAX_USER_KEY_BYTES, "user key")?;
    let database = Database::open(database_path)?;
    snapshot_from_database(&database, &character, &user_key, limit)
}

pub fn mutate_native_memories(
    database_path: &Path,
    character: &str,
    user_key: &str,
    command_json: &str,
    max_bytes: usize,
) -> Result<NativeMemorySnapshot, NativeMemoryError> {
    if command_json.len() > max_bytes {
        return Err(NativeMemoryError::Invalid(format!(
            "command exceeds the {max_bytes} byte limit"
        )));
    }
    let character = checked_partition(character, MAX_CHARACTER_BYTES, "character")?;
    let user_key = checked_partition(user_key, MAX_USER_KEY_BYTES, "user key")?;
    let command = serde_json::from_str::<NativeMemoryMutation>(command_json)?;
    let database = Database::open(database_path)?;
    match command {
        NativeMemoryMutation::SaveMemory {
            id,
            kind,
            content,
            importance,
        } => {
            let kind = checked_kind(&kind)?;
            let content = checked_content(&content)?;
            if id > 0 {
                if !database.update_character_memory(
                    id, &character, &user_key, &kind, &content, importance,
                )? {
                    return Err(NativeMemoryError::Invalid(
                        "selected memory does not exist in this character/user partition"
                            .to_owned(),
                    ));
                }
            } else if id == 0 {
                database.add_character_memory(
                    &character, &user_key, &kind, &content, importance, None, None,
                )?;
            } else {
                return Err(NativeMemoryError::Invalid(
                    "memory id cannot be negative".to_owned(),
                ));
            }
        }
        NativeMemoryMutation::DeleteMemories { ids } => {
            if ids.is_empty() || ids.len() > MAX_DELETE_IDS || ids.iter().any(|id| *id <= 0) {
                return Err(NativeMemoryError::Invalid(format!(
                    "delete needs 1-{MAX_DELETE_IDS} positive memory ids"
                )));
            }
            let requested = ids
                .iter()
                .copied()
                .collect::<std::collections::HashSet<_>>();
            let owned = database
                .character_memories(&character, &user_key, 100)?
                .into_iter()
                .map(|memory| memory.id)
                .collect::<std::collections::HashSet<_>>();
            if !requested.is_subset(&owned) {
                return Err(NativeMemoryError::Invalid(
                    "one or more selected memories do not exist in this character/user partition"
                        .to_owned(),
                ));
            }
            let deleted = database.delete_character_memories(&ids, &character, &user_key)?;
            if deleted != requested.len() {
                return Err(NativeMemoryError::Invalid(
                    "one or more selected memories do not exist in this character/user partition"
                        .to_owned(),
                ));
            }
        }
    }
    snapshot_from_database(&database, &character, &user_key, 100)
}

fn snapshot_from_database(
    database: &Database,
    character: &str,
    user_key: &str,
    limit: i64,
) -> Result<NativeMemorySnapshot, NativeMemoryError> {
    let relationship = if character == GLOBAL_MEMORY_CHARACTER {
        None
    } else {
        Some(database.relationship_state(character, user_key)?)
    };
    Ok(NativeMemorySnapshot {
        character: character.to_owned(),
        user_key: user_key.to_owned(),
        relationship,
        memories: database.character_memories(character, user_key, limit.clamp(1, 100))?,
    })
}

fn checked_partition(
    value: &str,
    max_bytes: usize,
    label: &str,
) -> Result<String, NativeMemoryError> {
    let value = value.trim();
    if value.is_empty() || value.len() > max_bytes || value.chars().any(char::is_control) {
        Err(NativeMemoryError::Invalid(format!(
            "{label} is empty, too long, or contains control characters"
        )))
    } else {
        Ok(value.to_owned())
    }
}

fn checked_kind(value: &str) -> Result<String, NativeMemoryError> {
    let value = value.trim().to_ascii_lowercase();
    if ALLOWED_KINDS.contains(&value.as_str()) {
        Ok(value)
    } else {
        Err(NativeMemoryError::Invalid(format!(
            "unsupported memory kind: {value}"
        )))
    }
}

fn checked_content(value: &str) -> Result<String, NativeMemoryError> {
    let value = value.trim();
    if value.is_empty() || value.len() > MAX_MEMORY_CONTENT_BYTES {
        Err(NativeMemoryError::Invalid(
            "memory content is empty or too long".to_owned(),
        ))
    } else {
        Ok(value.to_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn memory_dashboard_is_partitioned_whitelisted_and_supports_global_memories() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("data.db");

        let snapshot = mutate_native_memories(
            &path,
            "ran",
            "alice",
            r#"{"op":"save_memory","kind":"preference","content":"喜欢面包","importance":80}"#,
            4096,
        )
        .unwrap();
        assert_eq!(snapshot.memories.len(), 1);
        assert!(snapshot.relationship.is_some());
        let memory_id = snapshot.memories[0].id;

        let snapshot = mutate_native_memories(
            &path,
            "ran",
            "alice",
            &json!({
                "op":"save_memory",
                "id":memory_id,
                "kind":"profile",
                "content":"昵称是 Alice",
                "importance":95
            })
            .to_string(),
            4096,
        )
        .unwrap();
        assert_eq!(snapshot.memories[0].kind, "profile");
        assert_eq!(snapshot.memories[0].importance, 95);

        assert!(
            mutate_native_memories(
                &path,
                "ran",
                "bob",
                &json!({
                    "op":"save_memory",
                    "id":memory_id,
                    "kind":"note",
                    "content":"cross-user overwrite",
                    "importance":10
                })
                .to_string(),
                4096,
            )
            .is_err()
        );
        assert!(
            mutate_native_memories(
                &path,
                "ran",
                "alice",
                r#"{"op":"save_memory","kind":"unknown","content":"x","importance":1}"#,
                4096,
            )
            .is_err()
        );
        assert!(
            mutate_native_memories(
                &path,
                "ran",
                "bob",
                &json!({"op":"delete_memories","ids":[memory_id]}).to_string(),
                4096,
            )
            .is_err()
        );
        assert_eq!(
            load_native_memory_snapshot(&path, "ran", "alice", 100)
                .unwrap()
                .memories
                .len(),
            1
        );

        let global = mutate_native_memories(
            &path,
            GLOBAL_MEMORY_CHARACTER,
            "alice",
            r#"{"op":"save_memory","kind":"preference","content":"全局偏好","importance":70}"#,
            4096,
        )
        .unwrap();
        assert!(global.relationship.is_none());
        assert_eq!(global.memories.len(), 1);

        let snapshot = mutate_native_memories(
            &path,
            "ran",
            "alice",
            &json!({"op":"delete_memories","ids":[memory_id]}).to_string(),
            4096,
        )
        .unwrap();
        assert!(snapshot.memories.is_empty());
    }
}
