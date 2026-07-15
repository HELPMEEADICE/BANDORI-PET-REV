use crate::database::{Conversation, Database, DatabaseError, Message};
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeChatSnapshot {
    pub conversations: Vec<Conversation>,
    pub messages: Vec<Message>,
    pub active_conversation_id: Option<i64>,
}

pub fn load_native_chat_snapshot(
    database_path: impl AsRef<Path>,
    character: &str,
    user_key: &str,
    requested_conversation_id: Option<i64>,
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
    let messages = match active_conversation_id {
        Some(conversation_id) => database.get_messages(conversation_id, Some(200), None)?,
        None => Vec::new(),
    };
    Ok(NativeChatSnapshot {
        conversations,
        messages,
        active_conversation_id,
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

        let latest = load_native_chat_snapshot(&path, "Ran", "alice", None).unwrap();
        assert_eq!(latest.active_conversation_id, Some(newer));
        assert_eq!(latest.conversations.len(), 2);
        assert_eq!(latest.messages[0].content, "latest");

        let requested = load_native_chat_snapshot(&path, "Ran", "alice", Some(older)).unwrap();
        assert_eq!(requested.active_conversation_id, Some(older));
        assert_eq!(requested.messages[0].content, "first");

        let rejected = load_native_chat_snapshot(&path, "Ran", "alice", Some(other_user)).unwrap();
        assert_eq!(rejected.active_conversation_id, Some(newer));
    }
}
