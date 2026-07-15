use fs2::FileExt;
use rusqlite::types::Value as SqlValue;
use rusqlite::{Connection, OptionalExtension, params, params_from_iter};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use thiserror::Error;

const DEFAULT_USER_PROFILE_KEY: &str = "__default__";
const LOCK_TIMEOUT: Duration = Duration::from_secs(10);
const LOCK_RETRY: Duration = Duration::from_millis(50);

const TABLE_SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character TEXT NOT NULL,
    user_key TEXT NOT NULL DEFAULT '',
    title TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    reasoning_content TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '',
    tool_trace_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_key TEXT NOT NULL,
    conversation_id TEXT NOT NULL DEFAULT 'default',
    user_key TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    reasoning_content TEXT NOT NULL DEFAULT '',
    attachments_json TEXT NOT NULL DEFAULT '',
    tool_trace_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS group_chat_meta (
    group_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS relationship_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character TEXT NOT NULL,
    user_key TEXT NOT NULL DEFAULT '',
    affection INTEGER NOT NULL DEFAULT 50,
    trust INTEGER NOT NULL DEFAULT 50,
    familiarity INTEGER NOT NULL DEFAULT 0,
    mood TEXT NOT NULL DEFAULT 'calm',
    mood_intensity INTEGER NOT NULL DEFAULT 20,
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(character, user_key)
);
CREATE TABLE IF NOT EXISTS character_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character TEXT NOT NULL,
    user_key TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'note',
    content TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 50,
    source_message_id INTEGER,
    source_group_message_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(character, user_key, content)
);
CREATE TABLE IF NOT EXISTS mood_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character TEXT NOT NULL,
    user_key TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT 'interaction',
    affection_delta INTEGER NOT NULL DEFAULT 0,
    trust_delta INTEGER NOT NULL DEFAULT 0,
    familiarity_delta INTEGER NOT NULL DEFAULT 0,
    affection INTEGER,
    trust INTEGER,
    familiarity INTEGER,
    mood TEXT NOT NULL DEFAULT '',
    mood_intensity INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE IF NOT EXISTS usage_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    end_time TEXT,
    duration_seconds INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS external_chat_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    thread_name TEXT NOT NULL DEFAULT '',
    chat_type TEXT NOT NULL DEFAULT '',
    unread_count INTEGER NOT NULL DEFAULT 0,
    last_message_id INTEGER,
    last_message_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(platform, thread_id)
);
CREATE TABLE IF NOT EXISTS external_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    external_message_id TEXT NOT NULL DEFAULT '',
    sender_id TEXT NOT NULL DEFAULT '',
    sender_name TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'inbound' CHECK(direction IN ('inbound', 'outbound', 'draft')),
    content TEXT NOT NULL,
    unread INTEGER NOT NULL DEFAULT 1,
    chat_type TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"#;

const INDEX_SCHEMA: &str = r#"
CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_conv_role_id ON messages(conversation_id, role, id);
CREATE INDEX IF NOT EXISTS idx_conversations_character_user ON conversations(character, user_key, id);
CREATE INDEX IF NOT EXISTS idx_group_messages_key_user_conv_id ON group_messages(group_key, user_key, conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_character_memories_lookup ON character_memories(character, user_key, importance, updated_at);
CREATE INDEX IF NOT EXISTS idx_mood_events_lookup ON mood_events(character, user_key, created_at);
CREATE INDEX IF NOT EXISTS idx_external_chat_messages_thread ON external_chat_messages(platform, thread_id, id);
CREATE INDEX IF NOT EXISTS idx_external_chat_messages_unread ON external_chat_messages(unread, id);
CREATE INDEX IF NOT EXISTS idx_external_chat_messages_external_id ON external_chat_messages(platform, thread_id, external_message_id);
CREATE INDEX IF NOT EXISTS idx_external_chat_messages_chat_type ON external_chat_messages(chat_type, created_at);
"#;

#[derive(Debug, Error)]
pub enum DatabaseError {
    #[error("database I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("SQLite operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("database JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("timed out waiting for database lock: {0}")]
    LockTimeout(PathBuf),
    #[error("database connection mutex was poisoned")]
    Poisoned,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Conversation {
    pub id: i64,
    pub character: String,
    pub user_key: String,
    pub title: String,
    pub created_at: String,
    pub last_message_at: String,
    pub last_message_content: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Message {
    pub id: i64,
    pub conversation_id: i64,
    pub role: String,
    pub content: String,
    pub reasoning_content: String,
    pub attachments_json: String,
    pub tool_trace_json: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GroupMessage {
    pub id: i64,
    pub group_key: String,
    pub conversation_id: String,
    pub role: String,
    pub content: String,
    pub reasoning_content: String,
    pub attachments_json: String,
    pub tool_trace_json: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct TokenUsage {
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub total_tokens: i64,
    pub estimated: bool,
    pub request_count: i64,
    pub untracked_count: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct ColumnContract {
    name: String,
    #[serde(rename = "type")]
    data_type: String,
    not_null: bool,
    default: Option<String>,
    primary_key: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
struct IndexContract {
    table: String,
    unique: bool,
    columns: Vec<String>,
}

/// SQLite compatibility layer used while Python and Rust processes coexist.
///
/// Every public operation takes the same adjacent `data.db.lock` file used by
/// the Python implementation before entering SQLite. The database stays in WAL
/// mode so existing Python readers and Rust writers can share one file during
/// the staged migration.
pub struct Database {
    connection: Mutex<Connection>,
    lock_path: PathBuf,
    attachment_dir: PathBuf,
}

impl Database {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, DatabaseError> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let lock_path = database_lock_path(&path);
        let _file_lock = DatabaseFileLock::acquire(&lock_path)?;
        let mut connection = Connection::open(&path)?;
        connection.busy_timeout(Duration::from_secs(2))?;
        connection.pragma_update(None, "journal_mode", "WAL")?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        ensure_schema(&mut connection)?;

        let attachment_dir = path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("chat_attachments");
        Ok(Self {
            connection: Mutex::new(connection),
            lock_path,
            attachment_dir,
        })
    }

    pub fn create_conversation(
        &self,
        character: &str,
        title: &str,
        user_key: &str,
    ) -> Result<i64, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            connection.execute(
                "INSERT INTO conversations (character, user_key, title) VALUES (?, ?, ?)",
                params![character, user_key, title],
            )?;
            Ok(connection.last_insert_rowid())
        })
    }

    pub fn get_conversations(
        &self,
        character: Option<&str>,
        user_key: Option<&str>,
    ) -> Result<Vec<Conversation>, DatabaseError> {
        self.with_connection(|connection| {
            let mut clauses = Vec::new();
            let mut values = Vec::new();
            if let Some(character) = character.filter(|value| !value.is_empty()) {
                clauses.push("c.character=?");
                values.push(SqlValue::Text(character.to_owned()));
            }
            if let Some(user_key) = user_key {
                clauses.push("c.user_key=?");
                values.push(SqlValue::Text(normalize_user_key(user_key)));
            }

            let mut sql = concat!(
                "SELECT c.id, c.character, c.user_key, c.title, c.created_at, ",
                "latest.created_at, latest.content FROM conversations c ",
                "JOIN messages latest ON latest.id=(SELECT MAX(m.id) FROM messages m ",
                "WHERE m.conversation_id=c.id)"
            )
            .to_owned();
            if !clauses.is_empty() {
                sql.push_str(" WHERE ");
                sql.push_str(&clauses.join(" AND "));
            }
            sql.push_str(" ORDER BY latest.id DESC");

            let mut statement = connection.prepare(&sql)?;
            let rows = statement.query_map(params_from_iter(values), row_to_conversation)?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(DatabaseError::from)
        })
    }

    pub fn get_last_conversation(
        &self,
        character: &str,
        user_key: Option<&str>,
    ) -> Result<Option<Conversation>, DatabaseError> {
        Ok(self
            .get_conversations(Some(character), user_key)?
            .into_iter()
            .next())
    }

    #[allow(clippy::too_many_arguments)]
    pub fn add_message(
        &self,
        conversation_id: i64,
        role: &str,
        content: &str,
        reasoning_content: &str,
        attachments: Option<&Value>,
        tool_trace: Option<&Value>,
    ) -> Result<i64, DatabaseError> {
        let attachments = sanitize_attachments(attachments, &self.attachment_dir);
        let attachments_json = json_text(Some(&attachments))?;
        let tool_trace_json = json_text(tool_trace)?;
        self.with_connection(|connection| {
            connection.execute(
                concat!(
                    "INSERT INTO messages ",
                    "(conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json) ",
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                params![
                    conversation_id,
                    role,
                    content,
                    reasoning_content,
                    attachments_json,
                    tool_trace_json
                ],
            )?;
            Ok(connection.last_insert_rowid())
        })
    }

    pub fn get_messages(
        &self,
        conversation_id: i64,
        limit: Option<i64>,
        before_id: Option<i64>,
    ) -> Result<Vec<Message>, DatabaseError> {
        self.with_connection(|connection| {
            let mut sql = concat!(
                "SELECT id, conversation_id, role, content, reasoning_content, ",
                "attachments_json, tool_trace_json, created_at FROM messages ",
                "WHERE conversation_id=?"
            )
            .to_owned();
            let mut values = vec![SqlValue::Integer(conversation_id)];
            if let Some(before_id) = before_id.filter(|value| *value > 0) {
                sql.push_str(" AND id<?");
                values.push(SqlValue::Integer(before_id));
            }
            if let Some(limit) = limit {
                sql.push_str(" ORDER BY id DESC LIMIT ?");
                values.push(SqlValue::Integer(limit.clamp(1, 1000)));
            } else {
                sql.push_str(" ORDER BY id ASC");
            }

            let mut statement = connection.prepare(&sql)?;
            let rows = statement.query_map(params_from_iter(values), row_to_message)?;
            let mut messages = rows.collect::<Result<Vec<_>, _>>()?;
            if limit.is_some() {
                messages.reverse();
            }
            Ok(messages)
        })
    }

    pub fn conversation_token_usage(
        &self,
        conversation_id: Option<i64>,
    ) -> Result<TokenUsage, DatabaseError> {
        let Some(conversation_id) = conversation_id.filter(|value| *value != 0) else {
            return Ok(TokenUsage::default());
        };
        self.with_connection(|connection| {
            let mut statement = connection.prepare(concat!(
                "SELECT tool_trace_json FROM messages ",
                "WHERE conversation_id=? AND role='assistant'"
            ))?;
            let traces = statement
                .query_map(params![conversation_id], |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?;
            Ok(token_usage_from_traces(traces.iter().map(String::as_str)))
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn add_group_message(
        &self,
        group_key: &str,
        conversation_id: &str,
        role: &str,
        content: &str,
        reasoning_content: &str,
        attachments: Option<&Value>,
        tool_trace: Option<&Value>,
        user_key: &str,
    ) -> Result<i64, DatabaseError> {
        let conversation_id = if conversation_id.is_empty() {
            "default"
        } else {
            conversation_id
        };
        let user_key = normalize_user_key(user_key);
        let attachments = sanitize_attachments(attachments, &self.attachment_dir);
        let attachments_json = json_text(Some(&attachments))?;
        let tool_trace_json = json_text(tool_trace)?;
        self.with_connection(|connection| {
            connection.execute(
                concat!(
                    "INSERT INTO group_messages ",
                    "(group_key, conversation_id, user_key, role, content, reasoning_content, attachments_json, tool_trace_json) ",
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                params![
                    group_key,
                    conversation_id,
                    user_key,
                    role,
                    content,
                    reasoning_content,
                    attachments_json,
                    tool_trace_json
                ],
            )?;
            Ok(connection.last_insert_rowid())
        })
    }

    pub fn get_group_messages(
        &self,
        group_key: &str,
        conversation_id: &str,
        limit: Option<i64>,
        user_key: Option<&str>,
        before_id: Option<i64>,
    ) -> Result<Vec<GroupMessage>, DatabaseError> {
        let conversation_id = if conversation_id.is_empty() {
            "default"
        } else {
            conversation_id
        };
        self.with_connection(|connection| {
            let mut sql = concat!(
                "SELECT id, group_key, conversation_id, role, content, reasoning_content, ",
                "attachments_json, tool_trace_json, created_at FROM group_messages ",
                "WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)"
            )
            .to_owned();
            let mut values = vec![
                SqlValue::Text(group_key.to_owned()),
                SqlValue::Text(conversation_id.to_owned()),
                SqlValue::Text(conversation_id.to_owned()),
            ];
            if let Some(user_key) = user_key {
                sql.push_str(" AND user_key=?");
                values.push(SqlValue::Text(normalize_user_key(user_key)));
            }
            if let Some(before_id) = before_id.filter(|value| *value > 0) {
                sql.push_str(" AND id<?");
                values.push(SqlValue::Integer(before_id));
            }
            if let Some(limit) = limit {
                sql.push_str(" ORDER BY id DESC LIMIT ?");
                values.push(SqlValue::Integer(limit.clamp(1, 1000)));
            } else {
                sql.push_str(" ORDER BY id ASC");
            }

            let mut statement = connection.prepare(&sql)?;
            let rows = statement.query_map(params_from_iter(values), row_to_group_message)?;
            let mut messages = rows.collect::<Result<Vec<_>, _>>()?;
            if limit.is_some() {
                messages.reverse();
            }
            Ok(messages)
        })
    }

    pub fn group_conversation_token_usage(
        &self,
        group_key: &str,
        conversation_id: &str,
        user_key: Option<&str>,
    ) -> Result<TokenUsage, DatabaseError> {
        if group_key.is_empty() || conversation_id.is_empty() {
            return Ok(TokenUsage::default());
        }
        self.with_connection(|connection| {
            let mut sql = concat!(
                "SELECT tool_trace_json FROM group_messages WHERE group_key=? ",
                "AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) ",
                "AND role='assistant'"
            )
            .to_owned();
            let mut values = vec![
                SqlValue::Text(group_key.to_owned()),
                SqlValue::Text(conversation_id.to_owned()),
                SqlValue::Text(conversation_id.to_owned()),
            ];
            if let Some(user_key) = user_key {
                sql.push_str(" AND user_key=?");
                values.push(SqlValue::Text(normalize_user_key(user_key)));
            }
            let mut statement = connection.prepare(&sql)?;
            let traces = statement
                .query_map(params_from_iter(values), |row| row.get::<_, String>(0))?
                .collect::<Result<Vec<_>, _>>()?;
            Ok(token_usage_from_traces(traces.iter().map(String::as_str)))
        })
    }

    pub fn set_group_display_name(
        &self,
        group_key: &str,
        display_name: &str,
    ) -> Result<(), DatabaseError> {
        let display_name = display_name.trim();
        self.with_connection(|connection| {
            if display_name.is_empty() {
                connection.execute(
                    "DELETE FROM group_chat_meta WHERE group_key=?",
                    params![group_key],
                )?;
            } else {
                connection.execute(
                    concat!(
                        "INSERT INTO group_chat_meta (group_key, display_name) VALUES (?, ?) ",
                        "ON CONFLICT(group_key) DO UPDATE SET ",
                        "display_name=excluded.display_name, ",
                        "updated_at=datetime('now', 'localtime')"
                    ),
                    params![group_key, display_name],
                )?;
            }
            Ok(())
        })
    }

    pub fn get_group_display_name(&self, group_key: &str) -> Result<String, DatabaseError> {
        self.with_connection(|connection| {
            connection
                .query_row(
                    "SELECT display_name FROM group_chat_meta WHERE group_key=?",
                    params![group_key],
                    |row| row.get(0),
                )
                .optional()
                .map(|value| value.unwrap_or_default())
                .map_err(DatabaseError::from)
        })
    }

    pub fn delete_conversation(&self, conversation_id: i64) -> Result<usize, DatabaseError> {
        self.with_connection(|connection| {
            connection
                .execute(
                    "DELETE FROM conversations WHERE id=?",
                    params![conversation_id],
                )
                .map_err(DatabaseError::from)
        })
    }

    pub fn delete_group_conversation(
        &self,
        group_key: &str,
        conversation_id: &str,
        user_key: Option<&str>,
    ) -> Result<usize, DatabaseError> {
        let conversation_id = if conversation_id.is_empty() {
            "default"
        } else {
            conversation_id
        };
        self.with_connection(|connection| {
            if let Some(user_key) = user_key {
                connection
                    .execute(
                        concat!(
                            "DELETE FROM group_messages WHERE group_key=? ",
                            "AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) ",
                            "AND user_key=?"
                        ),
                        params![
                            group_key,
                            conversation_id,
                            conversation_id,
                            normalize_user_key(user_key)
                        ],
                    )
                    .map_err(DatabaseError::from)
            } else {
                connection
                    .execute(
                        concat!(
                            "DELETE FROM group_messages WHERE group_key=? ",
                            "AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)"
                        ),
                        params![group_key, conversation_id, conversation_id],
                    )
                    .map_err(DatabaseError::from)
            }
        })
    }

    pub fn assign_legacy_chat_history_user(&self, user_key: &str) -> Result<usize, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let conversations = transaction.execute(
                "UPDATE conversations SET user_key=? WHERE user_key='' OR user_key IS NULL",
                params![user_key],
            )?;
            let groups = transaction.execute(
                "UPDATE group_messages SET user_key=? WHERE user_key='' OR user_key IS NULL",
                params![user_key],
            )?;
            transaction.commit()?;
            Ok(conversations + groups)
        })
    }

    pub fn schema_contract(&self) -> Result<Value, DatabaseError> {
        self.with_connection(schema_contract)
    }

    fn with_connection<T>(
        &self,
        operation: impl FnOnce(&mut Connection) -> Result<T, DatabaseError>,
    ) -> Result<T, DatabaseError> {
        let _file_lock = DatabaseFileLock::acquire(&self.lock_path)?;
        let mut connection = self
            .connection
            .lock()
            .map_err(|_| DatabaseError::Poisoned)?;
        operation(&mut connection)
    }
}

fn ensure_schema(connection: &mut Connection) -> Result<(), DatabaseError> {
    connection.execute_batch(TABLE_SCHEMA)?;
    ensure_column(
        connection,
        "messages",
        "reasoning_content",
        "ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "messages",
        "attachments_json",
        "ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "messages",
        "tool_trace_json",
        "ALTER TABLE messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "conversations",
        "user_key",
        "ALTER TABLE conversations ADD COLUMN user_key TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "group_messages",
        "conversation_id",
        "ALTER TABLE group_messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'",
    )?;
    ensure_column(
        connection,
        "group_messages",
        "user_key",
        "ALTER TABLE group_messages ADD COLUMN user_key TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "group_messages",
        "reasoning_content",
        "ALTER TABLE group_messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "group_messages",
        "attachments_json",
        "ALTER TABLE group_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "group_messages",
        "tool_trace_json",
        "ALTER TABLE group_messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "external_chat_messages",
        "chat_type",
        "ALTER TABLE external_chat_messages ADD COLUMN chat_type TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "external_chat_threads",
        "chat_type",
        "ALTER TABLE external_chat_threads ADD COLUMN chat_type TEXT NOT NULL DEFAULT ''",
    )?;
    ensure_column(
        connection,
        "mood_events",
        "affection",
        "ALTER TABLE mood_events ADD COLUMN affection INTEGER",
    )?;
    ensure_column(
        connection,
        "mood_events",
        "trust",
        "ALTER TABLE mood_events ADD COLUMN trust INTEGER",
    )?;
    ensure_column(
        connection,
        "mood_events",
        "familiarity",
        "ALTER TABLE mood_events ADD COLUMN familiarity INTEGER",
    )?;
    connection.execute_batch(INDEX_SCHEMA)?;
    Ok(())
}

fn ensure_column(
    connection: &Connection,
    table: &str,
    column: &str,
    alter_sql: &str,
) -> Result<(), DatabaseError> {
    let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
    let columns = statement
        .query_map([], |row| row.get::<_, String>(1))?
        .collect::<Result<Vec<_>, _>>()?;
    if !columns.iter().any(|candidate| candidate == column) {
        connection.execute_batch(alter_sql)?;
    }
    Ok(())
}

fn row_to_conversation(row: &rusqlite::Row<'_>) -> rusqlite::Result<Conversation> {
    Ok(Conversation {
        id: row.get(0)?,
        character: row.get(1)?,
        user_key: row.get(2)?,
        title: row.get(3)?,
        created_at: row.get(4)?,
        last_message_at: row.get(5)?,
        last_message_content: row.get(6)?,
    })
}

fn row_to_message(row: &rusqlite::Row<'_>) -> rusqlite::Result<Message> {
    Ok(Message {
        id: row.get(0)?,
        conversation_id: row.get(1)?,
        role: row.get(2)?,
        content: row.get(3)?,
        reasoning_content: row.get(4)?,
        attachments_json: row.get(5)?,
        tool_trace_json: row.get(6)?,
        created_at: row.get(7)?,
    })
}

fn row_to_group_message(row: &rusqlite::Row<'_>) -> rusqlite::Result<GroupMessage> {
    Ok(GroupMessage {
        id: row.get(0)?,
        group_key: row.get(1)?,
        conversation_id: row.get(2)?,
        role: row.get(3)?,
        content: row.get(4)?,
        reasoning_content: row.get(5)?,
        attachments_json: row.get(6)?,
        tool_trace_json: row.get(7)?,
        created_at: row.get(8)?,
    })
}

fn normalize_user_key(user_key: &str) -> String {
    let user_key = user_key.trim();
    if user_key.is_empty() {
        DEFAULT_USER_PROFILE_KEY.to_owned()
    } else {
        user_key.to_owned()
    }
}

fn json_text(value: Option<&Value>) -> Result<String, serde_json::Error> {
    let Some(value) = value else {
        return Ok(String::new());
    };
    if !json_truthy(value) {
        return Ok(String::new());
    }
    if let Value::String(text) = value {
        return Ok(text.clone());
    }
    serde_json::to_string(value)
}

fn json_truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64().is_some_and(|number| number != 0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}

fn value_i64(value: Option<&Value>) -> Option<i64> {
    match value? {
        Value::Number(value) => value
            .as_i64()
            .or_else(|| value.as_u64().and_then(|raw| i64::try_from(raw).ok()))
            .or_else(|| value.as_f64().map(|raw| raw as i64)),
        Value::String(value) => value.parse().ok(),
        Value::Bool(value) => Some(i64::from(*value)),
        _ => None,
    }
}

fn token_usage_from_traces<'a>(traces: impl IntoIterator<Item = &'a str>) -> TokenUsage {
    let mut totals = TokenUsage::default();
    for raw in traces {
        let trace = serde_json::from_str::<Value>(raw).unwrap_or(Value::Null);
        let Some(usage) = trace.get("llm_usage").and_then(Value::as_object) else {
            totals.untracked_count += 1;
            continue;
        };
        let input = value_i64(usage.get("input_tokens"))
            .unwrap_or_default()
            .max(0);
        let output = value_i64(usage.get("output_tokens"))
            .unwrap_or_default()
            .max(0);
        let raw_total = value_i64(usage.get("total_tokens")).unwrap_or(input + output);
        let total = if raw_total == 0 {
            input + output
        } else {
            raw_total
        }
        .max(0);
        totals.input_tokens += input;
        totals.output_tokens += output;
        totals.total_tokens += total;
        totals.estimated |= usage.get("estimated").is_some_and(json_truthy);
        totals.request_count += 1;
    }
    totals
}

fn sanitize_attachments(value: Option<&Value>, attachment_dir: &Path) -> Value {
    let parsed;
    let value = match value {
        Some(Value::String(raw)) => {
            parsed = serde_json::from_str(raw).unwrap_or(Value::Null);
            &parsed
        }
        Some(value) => value,
        None => return Value::Array(Vec::new()),
    };
    let Some(items) = value.as_array() else {
        return Value::Array(Vec::new());
    };
    let Ok(safe_root) = attachment_dir.canonicalize() else {
        return Value::Array(Vec::new());
    };

    let mut cleaned = Vec::new();
    for item in items {
        let Some(item) = item.as_object() else {
            continue;
        };
        let item_type = item
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_lowercase();
        if item_type != "image" && item_type != "file" {
            continue;
        }
        let path = item
            .get("path")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim();
        let Ok(resolved) = Path::new(path).canonicalize() else {
            continue;
        };
        if !resolved.is_file() || resolved.strip_prefix(&safe_root).is_err() {
            continue;
        }

        let fallback_name = resolved
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or_default();
        let name = item
            .get("name")
            .and_then(Value::as_str)
            .filter(|name| !name.is_empty())
            .unwrap_or(fallback_name);
        let fallback_mime = if item_type == "image" {
            "image/png"
        } else {
            "application/octet-stream"
        };
        let mime = item
            .get("mime")
            .and_then(Value::as_str)
            .filter(|mime| !mime.is_empty())
            .unwrap_or(fallback_mime);

        let mut cleaned_item = Map::new();
        cleaned_item.insert("type".into(), Value::String(item_type.clone()));
        cleaned_item.insert("path".into(), Value::String(path.to_owned()));
        cleaned_item.insert("name".into(), Value::String(truncate_chars(name, 240)));
        cleaned_item.insert("mime".into(), Value::String(truncate_chars(mime, 160)));
        if let Some(size) = value_i64(item.get("size")).or_else(|| {
            resolved
                .metadata()
                .ok()
                .and_then(|meta| i64::try_from(meta.len()).ok())
        }) {
            cleaned_item.insert("size".into(), Value::Number(size.into()));
        }
        copy_trimmed_field(item, &mut cleaned_item, "uploaded_at", 40);
        if item_type == "image" {
            copy_trimmed_field(item, &mut cleaned_item, "vision_summary", 6000);
            copy_trimmed_field(item, &mut cleaned_item, "vision_error", 600);
        }
        cleaned.push(Value::Object(cleaned_item));
    }
    Value::Array(cleaned)
}

fn copy_trimmed_field(
    source: &Map<String, Value>,
    target: &mut Map<String, Value>,
    key: &str,
    limit: usize,
) {
    let Some(value) = source.get(key).and_then(Value::as_str) else {
        return;
    };
    let value = value.trim();
    if !value.is_empty() {
        target.insert(key.into(), Value::String(truncate_chars(value, limit)));
    }
}

fn truncate_chars(value: &str, limit: usize) -> String {
    value.chars().take(limit).collect()
}

fn schema_contract(connection: &mut Connection) -> Result<Value, DatabaseError> {
    let table_names = {
        let mut statement = connection.prepare(concat!(
            "SELECT name FROM sqlite_master ",
            "WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
        ))?;
        statement
            .query_map([], |row| row.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?
    };

    let mut tables = BTreeMap::new();
    for table in table_names {
        let columns = {
            let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
            statement
                .query_map([], |row| {
                    Ok(ColumnContract {
                        name: row.get(1)?,
                        data_type: row.get(2)?,
                        not_null: row.get::<_, i64>(3)? != 0,
                        default: row.get(4)?,
                        primary_key: row.get::<_, i64>(5)? != 0,
                    })
                })?
                .collect::<Result<Vec<_>, _>>()?
        };
        tables.insert(table, columns);
    }

    let index_rows = {
        let mut statement = connection.prepare(concat!(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ",
            "AND name NOT LIKE 'sqlite_autoindex_%' ORDER BY name"
        ))?;
        statement
            .query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })?
            .collect::<Result<Vec<_>, _>>()?
    };
    let mut indexes = BTreeMap::new();
    for (name, table) in index_rows {
        let unique = {
            let mut statement = connection.prepare(&format!("PRAGMA index_list({table})"))?;
            let rows = statement
                .query_map([], |row| {
                    Ok((row.get::<_, String>(1)?, row.get::<_, i64>(2)? != 0))
                })?
                .collect::<Result<Vec<_>, _>>()?;
            rows.into_iter()
                .find_map(|(candidate, unique)| (candidate == name).then_some(unique))
                .unwrap_or(false)
        };
        let columns = {
            let mut statement = connection.prepare(&format!("PRAGMA index_info({name})"))?;
            statement
                .query_map([], |row| row.get::<_, String>(2))?
                .collect::<Result<Vec<_>, _>>()?
        };
        indexes.insert(
            name,
            IndexContract {
                table,
                unique,
                columns,
            },
        );
    }

    Ok(serde_json::json!({"tables": tables, "indexes": indexes}))
}

fn database_lock_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("data.db");
    path.with_file_name(format!("{name}.lock"))
}

struct DatabaseFileLock {
    file: File,
}

impl DatabaseFileLock {
    fn acquire(path: &Path) -> Result<Self, DatabaseError> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let file = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .open(path)?;
        let deadline = Instant::now() + LOCK_TIMEOUT;
        loop {
            match file.try_lock_exclusive() {
                Ok(()) => return Ok(Self { file }),
                Err(error) if lock_is_contended(&error) => {
                    if Instant::now() >= deadline {
                        return Err(DatabaseError::LockTimeout(path.to_path_buf()));
                    }
                    thread::sleep(LOCK_RETRY);
                }
                Err(error) => return Err(DatabaseError::Io(error)),
            }
        }
    }
}

impl Drop for DatabaseFileLock {
    fn drop(&mut self) {
        let _ = FileExt::unlock(&self.file);
    }
}

fn lock_is_contended(error: &io::Error) -> bool {
    error.kind() == io::ErrorKind::WouldBlock
        || matches!(error.raw_os_error(), Some(13 | 32 | 33 | 36))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    #[test]
    fn schema_matches_the_python_contract() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let expected: Value =
            serde_json::from_str(include_str!("../../../compat/database_schema.json")).unwrap();
        assert_eq!(database.schema_contract().unwrap(), expected);
    }

    #[test]
    fn private_chat_pagination_and_usage_match_python() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let conversation = database.create_conversation("Ran", "first", "").unwrap();
        database
            .create_conversation("Ran", "empty", "other")
            .unwrap();
        let first = database
            .add_message(conversation, "user", "hello", "", None, None)
            .unwrap();
        let second = database
            .add_message(
                conversation,
                "assistant",
                "tracked",
                "thinking",
                None,
                Some(&json!({
                    "llm_usage": {
                        "input_tokens": 100,
                        "output_tokens": 25,
                        "total_tokens": 125,
                        "estimated": false
                    }
                })),
            )
            .unwrap();
        let third = database
            .add_message(conversation, "assistant", "legacy", "", None, None)
            .unwrap();

        let conversations = database.get_conversations(Some("Ran"), None).unwrap();
        assert_eq!(conversations.len(), 1);
        assert_eq!(conversations[0].user_key, DEFAULT_USER_PROFILE_KEY);
        assert_eq!(conversations[0].last_message_content, "legacy");

        let page = database.get_messages(conversation, Some(2), None).unwrap();
        assert_eq!(
            page.iter().map(|message| message.id).collect::<Vec<_>>(),
            vec![second, third]
        );
        let before = database
            .get_messages(conversation, Some(10), Some(third))
            .unwrap();
        assert_eq!(
            before.iter().map(|message| message.id).collect::<Vec<_>>(),
            vec![first, second]
        );

        assert_eq!(
            database
                .conversation_token_usage(Some(conversation))
                .unwrap(),
            TokenUsage {
                input_tokens: 100,
                output_tokens: 25,
                total_tokens: 125,
                estimated: false,
                request_count: 1,
                untracked_count: 1,
            }
        );
        assert_eq!(database.delete_conversation(conversation).unwrap(), 1);
        assert!(
            database
                .get_messages(conversation, None, None)
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn group_chat_filters_users_and_tracks_usage() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        database
            .add_group_message("Ran|Moca", "1", "user", "hi", "", None, None, "alice")
            .unwrap();
        database
            .add_group_message(
                "Ran|Moca",
                "1",
                "assistant",
                "reply",
                "",
                None,
                Some(&json!({"llm_usage": {"input_tokens": 7, "output_tokens": 3}})),
                "alice",
            )
            .unwrap();
        database
            .add_group_message("Ran|Moca", "1", "assistant", "other", "", None, None, "bob")
            .unwrap();

        let messages = database
            .get_group_messages("Ran|Moca", "1", None, Some("alice"), None)
            .unwrap();
        assert_eq!(messages.len(), 2);
        assert_eq!(
            database
                .group_conversation_token_usage("Ran|Moca", "1", Some("alice"))
                .unwrap(),
            TokenUsage {
                input_tokens: 7,
                output_tokens: 3,
                total_tokens: 10,
                estimated: false,
                request_count: 1,
                untracked_count: 0,
            }
        );
    }

    #[test]
    fn attachments_are_restricted_to_the_application_attachment_directory() {
        let temp = tempdir().unwrap();
        let attachments = temp.path().join("chat_attachments");
        fs::create_dir(&attachments).unwrap();
        let safe = attachments.join("safe.png");
        fs::write(&safe, b"png").unwrap();
        let unsafe_path = temp.path().join("outside.png");
        fs::write(&unsafe_path, b"png").unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let conversation = database.create_conversation("Ran", "", "").unwrap();
        database
            .add_message(
                conversation,
                "user",
                "image",
                "",
                Some(&json!([
                    {"type": "image", "path": safe, "name": "safe"},
                    {"type": "image", "path": unsafe_path, "name": "unsafe"}
                ])),
                None,
            )
            .unwrap();
        let messages = database.get_messages(conversation, None, None).unwrap();
        let stored: Value = serde_json::from_str(&messages[0].attachments_json).unwrap();
        assert_eq!(stored.as_array().unwrap().len(), 1);
        assert_eq!(stored[0]["name"], "safe");
    }

    #[test]
    fn legacy_chat_tables_receive_all_current_columns() {
        let temp = tempdir().unwrap();
        let path = temp.path().join("legacy.db");
        let connection = Connection::open(&path).unwrap();
        connection
            .execute_batch(
                "CREATE TABLE conversations (id INTEGER PRIMARY KEY, character TEXT NOT NULL, title TEXT, created_at TEXT);\
                 CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER, role TEXT, content TEXT, created_at TEXT);\
                 CREATE TABLE group_messages (id INTEGER PRIMARY KEY, group_key TEXT, role TEXT, content TEXT, created_at TEXT);",
            )
            .unwrap();
        drop(connection);

        let database = Database::open(&path).unwrap();
        let contract = database.schema_contract().unwrap();
        let message_columns = contract["tables"]["messages"].as_array().unwrap();
        for name in ["reasoning_content", "attachments_json", "tool_trace_json"] {
            assert!(message_columns.iter().any(|column| column["name"] == name));
        }
        let group_columns = contract["tables"]["group_messages"].as_array().unwrap();
        for name in [
            "conversation_id",
            "user_key",
            "reasoning_content",
            "attachments_json",
            "tool_trace_json",
        ] {
            assert!(group_columns.iter().any(|column| column["name"] == name));
        }
    }
}
