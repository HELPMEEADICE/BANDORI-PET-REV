use crate::database::{Conversation, Database, DatabaseError, Message};
use serde::{Deserialize, Serialize};
use std::path::Path;

pub const DEFAULT_NATIVE_CHAT_MESSAGE_LIMIT: i64 = 200;
pub const MAX_NATIVE_CHAT_MESSAGE_LIMIT: i64 = 1000;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeChatSnapshot {
    pub conversations: Vec<Conversation>,
    pub messages: Vec<Message>,
    pub active_conversation_id: Option<i64>,
    pub has_older_messages: bool,
}

pub fn load_native_chat_snapshot(
    database_path: impl AsRef<Path>,
    character: &str,
    user_key: &str,
    requested_conversation_id: Option<i64>,
    message_limit: i64,
) -> Result<NativeChatSnapshot, DatabaseError> {
    let database = Database::open(database_path)?;
    let conversations = database.get_conversations(
        (!character.trim().is_empty()).then_some(character.trim()),
        Some(user_key),
    )?;
    let active_conversation_id = requested_conversation_id
        .filter(|requested| {
            conversations
                .iter()
                .any(|conversation| conversation.id == *requested)
        })
        .or_else(|| conversations.first().map(|conversation| conversation.id));
    let message_limit = message_limit.clamp(1, MAX_NATIVE_CHAT_MESSAGE_LIMIT);
    let (messages, has_older_messages) = match active_conversation_id {
        Some(conversation_id) => {
            let messages = database.get_messages(conversation_id, Some(message_limit), None)?;
            let has_older = match messages.first() {
                Some(oldest) => !database
                    .get_messages(conversation_id, Some(1), Some(oldest.id))?
                    .is_empty(),
                None => false,
            };
            (messages, has_older)
        }
        None => (Vec::new(), false),
    };
    Ok(NativeChatSnapshot {
        conversations,
        messages,
        active_conversation_id,
        has_older_messages,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn chat_snapshot_selects_requested_or_most_recent_matching_conversation() {
        let root = TempDir::new().unwrap();
        let path = root.path().join("data.db");
        let database = Database::open(&path).unwrap();
        let older = database
            .create_conversation("Ran", "Older", "alice")
            .unwrap();
        database
            .add_message(older, "user", "first", "", None, None)
            .unwrap();
        let newer = database
            .create_conversation("Ran", "Newer", "alice")
            .unwrap();
        database
            .add_message(newer, "assistant", "latest", "", None, None)
            .unwrap();
        let other_user = database.create_conversation("Ran", "Other", "bob").unwrap();
        database
            .add_message(other_user, "user", "private", "", None, None)
            .unwrap();
        drop(database);

        let latest = load_native_chat_snapshot(
            &path,
            "Ran",
            "alice",
            None,
            DEFAULT_NATIVE_CHAT_MESSAGE_LIMIT,
        )
        .unwrap();
        assert_eq!(latest.active_conversation_id, Some(newer));
        assert_eq!(latest.conversations.len(), 2);
        assert_eq!(latest.messages[0].content, "latest");
        assert!(!latest.has_older_messages);

        let requested = load_native_chat_snapshot(
            &path,
            "Ran",
            "alice",
            Some(older),
            DEFAULT_NATIVE_CHAT_MESSAGE_LIMIT,
        )
        .unwrap();
        assert_eq!(requested.active_conversation_id, Some(older));
        assert_eq!(requested.messages[0].content, "first");

        let rejected = load_native_chat_snapshot(
            &path,
            "Ran",
            "alice",
            Some(other_user),
            DEFAULT_NATIVE_CHAT_MESSAGE_LIMIT,
        )
        .unwrap();
        assert_eq!(rejected.active_conversation_id, Some(newer));
    }

    #[test]
    fn chat_snapshot_reports_and_expands_older_message_history() {
        let root = TempDir::new().unwrap();
        let path = root.path().join("data.db");
        let database = Database::open(&path).unwrap();
        let conversation = database
            .create_conversation("Ran", "Long history", "alice")
            .unwrap();
        for index in 0..205 {
            database
                .add_message(
                    conversation,
                    "user",
                    &format!("message-{index}"),
                    "",
                    None,
                    None,
                )
                .unwrap();
        }
        drop(database);

        let first_page = load_native_chat_snapshot(&path, "Ran", "alice", None, 200).unwrap();
        assert_eq!(first_page.messages.len(), 200);
        assert_eq!(first_page.messages[0].content, "message-5");
        assert!(first_page.has_older_messages);

        let expanded = load_native_chat_snapshot(&path, "Ran", "alice", None, 400).unwrap();
        assert_eq!(expanded.messages.len(), 205);
        assert_eq!(expanded.messages[0].content, "message-0");
        assert!(!expanded.has_older_messages);
    }
}
