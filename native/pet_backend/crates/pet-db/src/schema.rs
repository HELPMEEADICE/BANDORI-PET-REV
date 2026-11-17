//! Additive, transactional upgrades retain the pre-existing SQLite format.
use crate::Result;
use rusqlite::{Connection, TransactionBehavior};
pub fn migrate(c: &mut Connection) -> Result<()> {
    let tx = c.transaction_with_behavior(TransactionBehavior::Immediate)?;
    tx.execute_batch(include_str!("schema.sql"))?;
    {
        let mut stmt = tx.prepare("PRAGMA table_info(messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "reasoning_content") {
            tx.execute_batch(
                "ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "attachments_json") {
            tx.execute_batch(
                "ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "tool_trace_json") {
            tx.execute_batch(
                "ALTER TABLE messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(conversations)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "user_key") {
            tx.execute_batch(
                "ALTER TABLE conversations ADD COLUMN user_key TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(conversations)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "temporary_background") {
            tx.execute_batch("ALTER TABLE conversations ADD COLUMN temporary_background TEXT NOT NULL DEFAULT ''")?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(group_messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "conversation_id") {
            tx.execute_batch("ALTER TABLE group_messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(group_messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "user_key") {
            tx.execute_batch(
                "ALTER TABLE group_messages ADD COLUMN user_key TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(group_messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "reasoning_content") {
            tx.execute_batch(
                "ALTER TABLE group_messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(group_messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "attachments_json") {
            tx.execute_batch(
                "ALTER TABLE group_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(group_messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "tool_trace_json") {
            tx.execute_batch(
                "ALTER TABLE group_messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(external_chat_messages)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "chat_type") {
            tx.execute_batch(
                "ALTER TABLE external_chat_messages ADD COLUMN chat_type TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(external_chat_threads)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "chat_type") {
            tx.execute_batch(
                "ALTER TABLE external_chat_threads ADD COLUMN chat_type TEXT NOT NULL DEFAULT ''",
            )?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(mood_events)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "affection") {
            tx.execute_batch("ALTER TABLE mood_events ADD COLUMN affection INTEGER")?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(mood_events)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "trust") {
            tx.execute_batch("ALTER TABLE mood_events ADD COLUMN trust INTEGER")?;
        }
    }
    {
        let mut stmt = tx.prepare("PRAGMA table_info(mood_events)")?;
        let columns = stmt
            .query_map([], |r| r.get::<_, String>(1))?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        if !columns.iter().any(|c| c == "familiarity") {
            tx.execute_batch("ALTER TABLE mood_events ADD COLUMN familiarity INTEGER")?;
        }
    }
    tx.execute_batch(
        "CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id, id);",
    )?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_messages_conv_role_id ON messages(conversation_id, role, id);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_conversations_character_user ON conversations(character, user_key, id);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_group_messages_key_user_conv_id ON group_messages(group_key, user_key, conversation_id, id);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_group_backgrounds_user_key ON group_conversation_backgrounds(user_key, group_key, updated_at);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_character_memories_lookup ON character_memories(character, user_key, importance, updated_at);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_mood_events_lookup ON mood_events(character, user_key, created_at);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_thread ON external_chat_messages(platform, thread_id, id);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_unread ON external_chat_messages(unread, id);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_external_id ON external_chat_messages(platform, thread_id, external_message_id);")?;
    tx.execute_batch("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_chat_type ON external_chat_messages(chat_type, created_at);")?;
    tx.commit()?;
    Ok(())
}
