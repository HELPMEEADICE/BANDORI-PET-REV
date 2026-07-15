use crate::database::{
    CharacterMemory, Database, DatabaseError, RelationshipDelta, RelationshipState,
};
use crate::relationship_analysis::InteractionAnalysis;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

const PROMPT_CONTRACT_JSON: &str = include_str!("../../../compat/chat_prompt_vectors.json");
pub const GLOBAL_MEMORY_CHARACTER: &str = "__global__";

#[derive(Debug, Deserialize)]
struct PromptContract {
    memory_extraction: MemoryPromptContract,
}

#[derive(Debug, Deserialize)]
struct MemoryPromptContract {
    system_prompt: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExtractedMemory {
    pub scope: String,
    pub kind: String,
    pub content: String,
    pub importance: i64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ParsedMemoryExtraction {
    pub relationship: Option<InteractionAnalysis>,
    pub memories: Vec<ExtractedMemory>,
    pub outdated: Vec<String>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct MemoryPersistenceResult {
    pub added: usize,
    pub removed: usize,
}

pub fn memory_extractor_system_prompt() -> &'static str {
    static CONTRACT: OnceLock<PromptContract> = OnceLock::new();
    CONTRACT
        .get_or_init(|| {
            serde_json::from_str(PROMPT_CONTRACT_JSON)
                .expect("generated memory prompt contract must be valid")
        })
        .memory_extraction
        .system_prompt
        .as_str()
}

pub fn build_memory_extraction_messages(
    user_text: &str,
    assistant_text: &str,
    existing_memories: &[CharacterMemory],
    global_memories: &[CharacterMemory],
    character_name: &str,
) -> Vec<Value> {
    let mut user_payload = format!(
        "当前角色：{}\n\n已保存的用户档案（跨角色，scope=user）：\n{}\n\n已保存的与当前角色相关的记忆（scope=relationship）：\n{}\n\n用户最新消息：\n{}",
        nonempty_or(character_name.trim(), "（未指定）"),
        format_memory_lines(global_memories),
        format_memory_lines(existing_memories),
        user_text.trim(),
    );
    let assistant_text = assistant_text.trim();
    if !assistant_text.is_empty() {
        user_payload.push_str("\n\n助手刚才的回复（仅用于判断语境，不要抽取助手事实）：\n");
        user_payload.extend(assistant_text.chars().take(1200));
    }
    vec![
        json!({"role": "system", "content": memory_extractor_system_prompt()}),
        json!({"role": "user", "content": user_payload}),
    ]
}

pub fn parse_memory_extraction(source: &str) -> ParsedMemoryExtraction {
    let Some(data) = json_object_from_text(source) else {
        return ParsedMemoryExtraction::default();
    };
    ParsedMemoryExtraction {
        relationship: parse_relationship(&data),
        memories: parse_memories(&data),
        outdated: parse_outdated(&data),
    }
}

pub fn apply_model_relationship_analysis(
    database: &Database,
    character: &str,
    user_key: &str,
    analysis: &InteractionAnalysis,
) -> Result<RelationshipState, DatabaseError> {
    apply_relationship_analysis(database, character, user_key, analysis, "chat_model")
}

pub fn apply_relationship_analysis(
    database: &Database,
    character: &str,
    user_key: &str,
    analysis: &InteractionAnalysis,
    event_type: &str,
) -> Result<RelationshipState, DatabaseError> {
    database.apply_relationship_delta(
        character,
        user_key,
        &RelationshipDelta {
            affection: analysis.affection_delta,
            trust: analysis.trust_delta,
            familiarity: analysis.familiarity_delta,
            mood: &analysis.mood,
            mood_intensity: Some(analysis.mood_intensity),
            event_type,
            reason: &analysis.reason,
        },
    )
}

pub fn store_extracted_memories(
    database: &Database,
    character: &str,
    user_key: &str,
    parsed: &ParsedMemoryExtraction,
    source_message_id: Option<i64>,
    source_group_message_id: Option<i64>,
) -> Result<MemoryPersistenceResult, DatabaseError> {
    let mut result = MemoryPersistenceResult::default();
    if !parsed.outdated.is_empty() {
        let mut index = HashMap::<String, (i64, String)>::new();
        for owner in [character, GLOBAL_MEMORY_CHARACTER] {
            for memory in database.character_memories(owner, user_key, 100)? {
                let key = normalize_memory_match_key(&memory.content);
                if !key.is_empty() {
                    index.entry(key).or_insert((memory.id, owner.to_owned()));
                }
            }
        }
        for line in &parsed.outdated {
            if let Some((memory_id, owner)) = index.get(&normalize_memory_match_key(line)) {
                result.removed +=
                    database.delete_character_memories(&[*memory_id], owner, user_key)?;
            }
        }
    }
    for memory in &parsed.memories {
        let owner = if memory.scope == "user" {
            GLOBAL_MEMORY_CHARACTER
        } else {
            character
        };
        let memory_id = database.add_character_memory(
            owner,
            user_key,
            &memory.kind,
            &memory.content,
            memory.importance,
            source_message_id,
            source_group_message_id,
        )?;
        result.added += usize::from(memory_id > 0);
    }
    Ok(result)
}

fn format_memory_lines(memories: &[CharacterMemory]) -> String {
    let lines = memories
        .iter()
        .take(12)
        .filter_map(|memory| {
            let content = collapse_whitespace(&memory.content);
            (!content.is_empty()).then(|| format!("- {content}"))
        })
        .collect::<Vec<_>>();
    if lines.is_empty() {
        "（无）".to_owned()
    } else {
        lines.join("\n")
    }
}

fn json_object_from_text(source: &str) -> Option<serde_json::Map<String, Value>> {
    let source = source.trim();
    if source.is_empty() {
        return None;
    }
    if let Ok(Value::Object(object)) = serde_json::from_str::<Value>(source) {
        return Some(object);
    }
    for (index, character) in source.char_indices() {
        if character != '{' {
            continue;
        }
        let mut deserializer = serde_json::Deserializer::from_str(&source[index..]);
        if let Ok(Value::Object(object)) = Value::deserialize(&mut deserializer) {
            return Some(object);
        }
    }
    None
}

fn parse_relationship(data: &serde_json::Map<String, Value>) -> Option<InteractionAnalysis> {
    let relationship = data.get("relationship")?.as_object()?;
    let mood = value_string(relationship.get("mood"));
    let mood = if matches!(
        mood.as_str(),
        "calm"
            | "happy"
            | "excited"
            | "soft"
            | "concerned"
            | "sad"
            | "hurt"
            | "annoyed"
            | "angry"
            | "shy"
            | "thoughtful"
            | "surprised"
            | "tired"
    ) {
        mood
    } else {
        "calm".to_owned()
    };
    let reason = trim_text(
        relationship
            .get("reason")
            .map(|value| value_string(Some(value)))
            .unwrap_or_else(|| "模型互动分析".to_owned()),
        100,
    );
    Some(InteractionAnalysis {
        affection_delta: bounded_int(relationship.get("affection_delta"), 0, -5, 5),
        trust_delta: bounded_int(relationship.get("trust_delta"), 0, -5, 5),
        familiarity_delta: bounded_int(relationship.get("familiarity_delta"), 1, 0, 3),
        mood,
        mood_intensity: bounded_int(relationship.get("mood_intensity"), 24, 0, 100),
        reason: nonempty_or(&reason, "模型互动分析").to_owned(),
    })
}

fn parse_memories(data: &serde_json::Map<String, Value>) -> Vec<ExtractedMemory> {
    let Some(items) = data.get("memories").and_then(Value::as_array) else {
        return Vec::new();
    };
    let mut memories = Vec::new();
    let mut seen = HashSet::new();
    for item in items {
        let Some(item) = item.as_object() else {
            continue;
        };
        let kind = value_string(item.get("kind"));
        let kind = if matches!(
            kind.as_str(),
            "manual" | "favorite" | "profile" | "preference" | "relationship" | "note"
        ) {
            kind
        } else {
            "note".to_owned()
        };
        let content = trim_text(value_string(item.get("content")), 180);
        if content.chars().count() < 3 || !seen.insert(content.clone()) {
            continue;
        }
        let scope = memory_scope(&value_string(item.get("scope")), &kind).to_owned();
        memories.push(ExtractedMemory {
            scope,
            kind,
            content,
            importance: bounded_int(item.get("importance"), 60, 1, 100),
        });
        if memories.len() >= 6 {
            break;
        }
    }
    memories
}

fn parse_outdated(data: &serde_json::Map<String, Value>) -> Vec<String> {
    let raw = match data.get("outdated") {
        Some(value) if !value.is_null() => Some(value),
        _ => data
            .get("superseded")
            .filter(|value| value_truthy(value))
            .or_else(|| data.get("remove").filter(|value| value_truthy(value))),
    };
    let Some(items) = raw.and_then(Value::as_array) else {
        return Vec::new();
    };
    let mut results = Vec::new();
    let mut seen = HashSet::new();
    for item in items {
        let content = if let Some(object) = item.as_object() {
            value_string(object.get("content"))
        } else {
            value_string(Some(item))
        };
        let content = collapse_whitespace(&content);
        let key = normalize_memory_match_key(&content);
        if content.chars().count() < 3 || !seen.insert(key) {
            continue;
        }
        results.push(content);
        if results.len() >= 6 {
            break;
        }
    }
    results
}

fn memory_scope<'a>(scope: &str, kind: &'a str) -> &'a str {
    match scope.trim().to_ascii_lowercase().as_str() {
        "user" | "global" | "profile" | "shared" => "user",
        "relationship" | "character" | "local" | "char" => "relationship",
        _ if matches!(kind, "profile" | "preference") => "user",
        _ => "relationship",
    }
}

fn bounded_int(value: Option<&Value>, default: i64, low: i64, high: i64) -> i64 {
    python_int(value).unwrap_or(default).clamp(low, high)
}

fn python_int(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(number) => number
            .as_i64()
            .or_else(|| number.as_f64().map(|number| number as i64)),
        Value::String(value) => value.trim().parse().ok(),
        Value::Bool(value) => Some(i64::from(*value)),
        _ => None,
    }
}

fn value_string(value: Option<&Value>) -> String {
    match value {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(value)) => value.clone(),
        Some(Value::Bool(value)) => if *value { "True" } else { "False" }.to_owned(),
        Some(Value::Number(value)) => value.to_string(),
        Some(value) => value.to_string(),
    }
}

fn value_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
        Value::Number(_) => true,
    }
}

fn trim_text(value: String, limit: usize) -> String {
    let value = collapse_whitespace(&value);
    let value = value
        .trim_matches(|character| " ：:，,。.".contains(character))
        .to_owned();
    if value.chars().count() <= limit {
        return value;
    }
    let mut truncated = value.chars().take(limit).collect::<String>();
    truncated = truncated.trim_end().to_owned();
    truncated.push_str("...");
    truncated
}

fn collapse_whitespace(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn normalize_memory_match_key(value: &str) -> String {
    value
        .chars()
        .filter(|character| !character.is_whitespace())
        .flat_map(char::to_lowercase)
        .collect()
}

fn nonempty_or<'a>(value: &'a str, fallback: &'a str) -> &'a str {
    if value.is_empty() { fallback } else { value }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Deserialize)]
    struct Vectors {
        memory_extraction: TestMemoryContract,
    }

    #[derive(Deserialize)]
    struct TestMemoryContract {
        system_prompt: String,
        message_cases: Vec<MessageCase>,
        response_cases: Vec<ResponseCase>,
    }

    #[derive(Deserialize)]
    struct MessageCase {
        user_text: String,
        assistant_text: String,
        existing_memories: Vec<TestMemory>,
        global_memories: Vec<TestMemory>,
        character_name: String,
        expected: Value,
    }

    #[derive(Deserialize)]
    struct TestMemory {
        content: String,
    }

    #[derive(Deserialize)]
    struct ResponseCase {
        source: String,
        relationship: Value,
        memories: Value,
        outdated: Value,
    }

    fn fixture_memory(index: usize, memory: TestMemory) -> CharacterMemory {
        CharacterMemory {
            id: index as i64 + 1,
            character: String::new(),
            user_key: String::new(),
            kind: "note".to_owned(),
            content: memory.content,
            importance: 50,
            source_message_id: None,
            source_group_message_id: None,
            created_at: String::new(),
            updated_at: String::new(),
        }
    }

    #[test]
    fn generated_python_memory_contract_matches_rust() {
        let vectors: Vectors = serde_json::from_str(PROMPT_CONTRACT_JSON).unwrap();
        assert_eq!(
            memory_extractor_system_prompt(),
            vectors.memory_extraction.system_prompt
        );
        for case in vectors.memory_extraction.message_cases {
            let existing = case
                .existing_memories
                .into_iter()
                .enumerate()
                .map(|(index, memory)| fixture_memory(index, memory))
                .collect::<Vec<_>>();
            let global = case
                .global_memories
                .into_iter()
                .enumerate()
                .map(|(index, memory)| fixture_memory(index, memory))
                .collect::<Vec<_>>();
            assert_eq!(
                Value::Array(build_memory_extraction_messages(
                    &case.user_text,
                    &case.assistant_text,
                    &existing,
                    &global,
                    &case.character_name,
                )),
                case.expected,
            );
        }
        for case in vectors.memory_extraction.response_cases {
            let parsed = parse_memory_extraction(&case.source);
            assert_eq!(
                parsed
                    .relationship
                    .as_ref()
                    .map(|value| serde_json::to_value(value).unwrap())
                    .unwrap_or_else(|| json!({})),
                case.relationship,
            );
            assert_eq!(
                serde_json::to_value(parsed.memories).unwrap(),
                case.memories
            );
            assert_eq!(
                serde_json::to_value(parsed.outdated).unwrap(),
                case.outdated
            );
        }
    }

    #[test]
    fn extracted_memories_replace_exact_scoped_lines() {
        let directory = tempfile::tempdir().unwrap();
        let database = Database::open(directory.path().join("data.db")).unwrap();
        database
            .add_character_memory(
                GLOBAL_MEMORY_CHARACTER,
                "alice",
                "profile",
                "旧 昵称是 A",
                80,
                None,
                None,
            )
            .unwrap();
        database
            .add_character_memory("ran", "alice", "relationship", "共同计划", 60, None, None)
            .unwrap();
        let parsed = ParsedMemoryExtraction {
            relationship: None,
            memories: vec![ExtractedMemory {
                scope: "user".to_owned(),
                kind: "profile".to_owned(),
                content: "昵称是小K".to_owned(),
                importance: 90,
            }],
            outdated: vec!["旧昵称是A".to_owned()],
        };
        let result =
            store_extracted_memories(&database, "ran", "alice", &parsed, Some(42), None).unwrap();
        assert_eq!(
            result,
            MemoryPersistenceResult {
                added: 1,
                removed: 1
            }
        );
        let global = database
            .character_memories(GLOBAL_MEMORY_CHARACTER, "alice", 100)
            .unwrap();
        assert_eq!(global.len(), 1);
        assert_eq!(global[0].content, "昵称是小K");
        assert_eq!(global[0].source_message_id, Some(42));
        assert_eq!(
            database
                .character_memories("ran", "alice", 100)
                .unwrap()
                .len(),
            1
        );
    }
}
