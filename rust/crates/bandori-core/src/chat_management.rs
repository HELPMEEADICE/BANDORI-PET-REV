use crate::chat_attachments::delete_message_attachment_copies;
use crate::database::{Database, DatabaseError};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ConversationDeleteResult {
    pub deleted: bool,
    pub attachments_removed: usize,
}

pub fn delete_owned_private_conversation(
    database: &Database,
    character: &str,
    user_key: &str,
    conversation_id: i64,
) -> Result<ConversationDeleteResult, DatabaseError> {
    if conversation_id <= 0
        || !database
            .get_conversations(Some(character), Some(user_key))?
            .iter()
            .any(|conversation| conversation.id == conversation_id)
    {
        return Err(DatabaseError::InvalidOperation(
            "conversation does not belong to the selected character and user".to_owned(),
        ));
    }
    let messages = database.get_messages(conversation_id, None, None)?;
    let deleted = database.delete_conversation(conversation_id)? != 0;
    let attachments_removed = if deleted {
        delete_message_attachment_copies(database, &messages)
    } else {
        0
    };
    Ok(ConversationDeleteResult {
        deleted,
        attachments_removed,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;

    #[test]
    fn owned_delete_removes_rows_and_attachment_copies_without_cross_user_access() {
        let directory = tempfile::tempdir().unwrap();
        let attachment_root = directory.path().join("chat_attachments");
        fs::create_dir(&attachment_root).unwrap();
        let attachment = attachment_root.join("saved.txt");
        fs::write(&attachment, "saved").unwrap();
        let database = Database::open(directory.path().join("data.db")).unwrap();
        let turn = database
            .begin_private_chat_turn(
                "ran",
                "alice",
                None,
                "hello",
                Some(&json!([{
                    "type": "file",
                    "path": attachment,
                    "name": "saved.txt",
                    "mime": "text/plain"
                }])),
            )
            .unwrap();
        assert!(
            delete_owned_private_conversation(&database, "ran", "bob", turn.conversation_id)
                .is_err()
        );
        assert!(attachment.exists());
        let result =
            delete_owned_private_conversation(&database, "ran", "alice", turn.conversation_id)
                .unwrap();
        assert_eq!(
            result,
            ConversationDeleteResult {
                deleted: true,
                attachments_removed: 1
            }
        );
        assert!(!attachment.exists());
        assert!(
            database
                .get_messages(turn.conversation_id, None, None)
                .unwrap()
                .is_empty()
        );
    }
}
