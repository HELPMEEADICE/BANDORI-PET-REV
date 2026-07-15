use crate::chat_attachments::chat_message_content;
use crate::chat_prompt::{
    build_native_system_prompt_with_role, build_relationship_context, load_character_markdown,
};
use crate::chat_tools::{native_chat_tools, with_native_tool_system_hint};
use crate::config::ConfigDocument;
use crate::cross_chat_history::build_cross_chat_history;
use crate::database::{Database, DatabaseError};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::Path;

const DEFAULT_HISTORY_MESSAGE_LIMIT: i64 = 40;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeChatMessage {
    pub role: String,
    pub content: Value,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeChatRequest {
    pub messages: Vec<NativeChatMessage>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tools: Vec<Value>,
}

#[allow(clippy::too_many_arguments)]
pub fn build_native_chat_request(
    database: &Database,
    config: &ConfigDocument,
    project_root: &Path,
    character: &str,
    character_display_name: &str,
    user_key: &str,
    conversation_id: i64,
    current_time_instruction: &str,
) -> Result<NativeChatRequest, DatabaseError> {
    let character = character.trim();
    if character.is_empty() || conversation_id <= 0 {
        return Err(DatabaseError::InvalidOperation(
            "native chat request needs a character and conversation".to_owned(),
        ));
    }
    let owns_conversation = database
        .get_conversations(Some(character), Some(user_key))?
        .iter()
        .any(|conversation| conversation.id == conversation_id);
    if !owns_conversation {
        return Err(DatabaseError::InvalidOperation(
            "conversation does not belong to the selected character and user".to_owned(),
        ));
    }

    let markdown = load_character_markdown(project_root, character);
    let role_markdown = config
        .get("pov_role_character")
        .and_then(Value::as_str)
        .map(|role| load_character_markdown(project_root, role))
        .unwrap_or_default();
    let system_prompt = with_native_tool_system_hint(&build_native_system_prompt_with_role(
        character,
        character_display_name,
        config.values(),
        &markdown,
        &role_markdown,
    ));
    let user_display_name = config
        .get("user_name")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    let relationship_display_name = if user_display_name.is_empty() {
        "你"
    } else {
        user_display_name
    };
    let mut dynamic_context =
        build_relationship_context(database, character, user_key, relationship_display_name)?;
    let cross_chat_enabled = config
        .get("llm_cross_chat_history_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    if cross_chat_enabled {
        let cross_chat =
            build_cross_chat_history(database, character, user_key, user_display_name, 18)?;
        if !cross_chat.is_empty() {
            dynamic_context.push_str("\n\n【跨聊天记录】\n");
            dynamic_context.push_str(&cross_chat);
        }
    }
    let current_time_instruction = current_time_instruction.trim();
    if !current_time_instruction.is_empty() {
        dynamic_context.push_str("\n\n【后置提示词】\n");
        dynamic_context.push_str(current_time_instruction);
    }

    let history_limit = history_message_limit(config.get("llm_chat_history_message_limit"));
    let history = database.get_messages(conversation_id, history_limit, None)?;
    let latest_user_message_id = history
        .iter()
        .rev()
        .find(|message| message.role == "user")
        .map(|message| message.id);
    let mut messages = Vec::with_capacity(history.len() + 1);
    messages.push(NativeChatMessage {
        role: "system".to_owned(),
        content: Value::String(system_prompt),
    });
    messages.extend(history.into_iter().map(|message| NativeChatMessage {
        role: message.role.clone(),
        content: chat_message_content(
            database,
            &message,
            message.role == "user" && Some(message.id) == latest_user_message_id,
        ),
    }));
    append_dynamic_context_to_last_user(&mut messages, &dynamic_context)?;
    Ok(NativeChatRequest {
        messages,
        tools: native_chat_tools(),
    })
}

pub(crate) fn history_message_limit(value: Option<&Value>) -> Option<i64> {
    let parsed = value
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
        })
        .unwrap_or(DEFAULT_HISTORY_MESSAGE_LIMIT);
    if parsed == 0 {
        None
    } else {
        Some(parsed.clamp(2, 100))
    }
}

pub(crate) fn append_dynamic_context_to_last_user(
    messages: &mut [NativeChatMessage],
    context: &str,
) -> Result<(), DatabaseError> {
    let context = context.trim();
    let Some(message) = messages
        .iter_mut()
        .rev()
        .find(|message| message.role == "user")
    else {
        return Err(DatabaseError::InvalidOperation(
            "conversation has no user message for dynamic context".to_owned(),
        ));
    };
    if !context.is_empty() {
        append_text_content(&mut message.content, "\n\n【动态上下文】\n");
        append_text_content(&mut message.content, context);
    }
    Ok(())
}

fn append_text_content(content: &mut Value, suffix: &str) {
    if let Some(text) = content.as_str() {
        let mut text = text.to_owned();
        text.push_str(suffix);
        *content = Value::String(text);
        return;
    }
    if let Some(parts) = content.as_array_mut() {
        if let Some(text) = parts.iter_mut().find_map(|part| {
            let object = part.as_object_mut()?;
            (object.get("type").and_then(Value::as_str) == Some("text"))
                .then(|| object.get_mut("text"))
                .flatten()
        }) {
            let mut value = text.as_str().unwrap_or_default().to_owned();
            value.push_str(suffix);
            *text = Value::String(value);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::database::RelationshipUpdate;
    use serde_json::json;
    use std::fs;

    #[test]
    fn request_matches_private_chat_history_and_dynamic_context_order() {
        let project = tempfile::tempdir().unwrap();
        let character_dir = project.path().join("characters").join("美竹兰");
        fs::create_dir_all(&character_dir).unwrap();
        fs::write(
            project.path().join("outfit.json"),
            r#"{"characters":{"ran":{"display":"美竹兰"}}}"#,
        )
        .unwrap();
        fs::write(character_dir.join("profile.md"), "# Rust dossier").unwrap();

        let database = Database::open(project.path().join("data.db")).unwrap();
        let turn = database
            .begin_private_chat_turn("ran", "alice", None, "old user", None)
            .unwrap();
        database
            .add_message(
                turn.conversation_id,
                "assistant",
                "old assistant",
                "",
                None,
                None,
            )
            .unwrap();
        database
            .begin_private_chat_turn(
                "ran",
                "alice",
                Some(turn.conversation_id),
                "latest user",
                None,
            )
            .unwrap();
        database
            .upsert_relationship_state(
                "ran",
                "alice",
                &RelationshipUpdate {
                    affection: Some(86),
                    mood: Some("happy"),
                    ..RelationshipUpdate::default()
                },
            )
            .unwrap();
        database
            .add_character_memory("ran", "alice", "note", "一起练过吉他", 80, None, None)
            .unwrap();

        let mut config = ConfigDocument::default();
        config.set("user_name", Value::String("Alice".to_owned()));
        config.set("llm_chat_history_message_limit", json!(2));
        let request = build_native_chat_request(
            &database,
            &config,
            project.path(),
            "ran",
            "美竹兰",
            "alice",
            turn.conversation_id,
            "当前时间：2026-07-15 12:30（中午）\n现在的时间判断只以上面这条为准。",
        )
        .unwrap();

        assert_eq!(request.tools, native_chat_tools());
        assert!(
            request.messages[0]
                .content
                .as_str()
                .unwrap()
                .contains("【工具使用边界】")
        );
        assert_eq!(request.messages.len(), 3);
        assert!(
            request.messages[0]
                .content
                .as_str()
                .unwrap()
                .starts_with("# Rust dossier\n\n你是Afterglow")
        );
        assert_eq!(request.messages[1].role, "assistant");
        assert_eq!(
            request.messages[1].content,
            Value::String("old assistant".to_owned())
        );
        assert_eq!(request.messages[2].role, "user");
        assert!(
            request.messages[2]
                .content
                .as_str()
                .unwrap()
                .starts_with("latest user\n\n【动态上下文】\n")
        );
        assert!(
            request.messages[2]
                .content
                .as_str()
                .unwrap()
                .contains("互动对象：Alice")
        );
        assert!(
            request.messages[2]
                .content
                .as_str()
                .unwrap()
                .contains("好感度 86/100（非常亲近）")
        );
        assert!(
            request.messages[2]
                .content
                .as_str()
                .unwrap()
                .contains("- 记录：一起练过吉他")
        );
        assert!(request.messages[2].content.as_str().unwrap().ends_with(
            "【后置提示词】\n当前时间：2026-07-15 12:30（中午）\n现在的时间判断只以上面这条为准。"
        ));
    }

    #[test]
    fn zero_history_limit_keeps_the_whole_conversation() {
        let project = tempfile::tempdir().unwrap();
        let database = Database::open(project.path().join("data.db")).unwrap();
        let turn = database
            .begin_private_chat_turn("guest", "", None, "one", None)
            .unwrap();
        database
            .add_message(turn.conversation_id, "assistant", "two", "", None, None)
            .unwrap();
        database
            .begin_private_chat_turn("guest", "", Some(turn.conversation_id), "three", None)
            .unwrap();
        let mut config = ConfigDocument::default();
        config.set("llm_chat_history_message_limit", json!(0));
        let request = build_native_chat_request(
            &database,
            &config,
            project.path(),
            "guest",
            "Guest",
            "",
            turn.conversation_id,
            "",
        )
        .unwrap();
        assert_eq!(
            request
                .messages
                .iter()
                .map(|message| message.role.as_str())
                .collect::<Vec<_>>(),
            ["system", "user", "assistant", "user"]
        );
    }

    #[test]
    fn latest_image_is_multimodal_and_dynamic_context_stays_in_its_text_part() {
        let project = tempfile::tempdir().unwrap();
        let attachment_root = project.path().join("chat_attachments");
        fs::create_dir(&attachment_root).unwrap();
        let image = attachment_root.join("latest.png");
        fs::write(&image, b"image bytes").unwrap();
        let database = Database::open(project.path().join("data.db")).unwrap();
        let turn = database
            .begin_private_chat_turn(
                "ran",
                "alice",
                None,
                "look",
                Some(&json!([{
                    "type": "image",
                    "path": image,
                    "name": "latest.png",
                    "mime": "image/png",
                    "size": 11
                }])),
            )
            .unwrap();
        let request = build_native_chat_request(
            &database,
            &ConfigDocument::default(),
            project.path(),
            "ran",
            "美竹兰",
            "alice",
            turn.conversation_id,
            "now",
        )
        .unwrap();
        let parts = request.messages.last().unwrap().content.as_array().unwrap();
        assert!(
            parts[0]["text"]
                .as_str()
                .unwrap()
                .contains("【动态上下文】")
        );
        assert!(
            parts[0]["text"]
                .as_str()
                .unwrap()
                .ends_with("【后置提示词】\nnow")
        );
        assert!(
            parts[1]["image_url"]["url"]
                .as_str()
                .unwrap()
                .starts_with("data:image/png;base64,")
        );
    }
}
