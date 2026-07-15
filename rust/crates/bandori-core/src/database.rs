use fs2::FileExt;
use rusqlite::types::Value as SqlValue;
use rusqlite::{Connection, MAIN_DB, OptionalExtension, params, params_from_iter};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};
use tempfile::Builder;
use thiserror::Error;

const DEFAULT_USER_PROFILE_KEY: &str = "__default__";
const LOCK_TIMEOUT: Duration = Duration::from_secs(10);
const LOCK_RETRY: Duration = Duration::from_millis(50);
const EXTERNAL_GROUP_CHAT_MESSAGE_LIMIT: i64 = 50;
type MoodChartSource = (String, i64, i64, i64, Option<i64>, Option<i64>, Option<i64>);

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

const CHAT_HISTORY_SQL: &str = r#"
SELECT
    'private' AS source,
    m.id AS source_id,
    CAST(c.id AS TEXT) AS conversation_id,
    c.character AS character,
    '' AS group_key,
    c.title AS chat_title,
    c.user_key AS user_key,
    m.role AS role,
    m.content AS content,
    m.created_at AS created_at,
    '|' || c.character || '|' AS member_keys
FROM messages m
JOIN conversations c ON c.id=m.conversation_id
UNION ALL
SELECT
    'group' AS source,
    gm.id AS source_id,
    CAST(gm.conversation_id AS TEXT) AS conversation_id,
    '' AS character,
    gm.group_key AS group_key,
    COALESCE(meta.display_name, '') AS chat_title,
    gm.user_key AS user_key,
    gm.role AS role,
    gm.content AS content,
    gm.created_at AS created_at,
    CASE
        WHEN gm.group_key LIKE '__group__:%'
        THEN '|' || substr(gm.group_key, 11) || '|'
        ELSE '|' || gm.group_key || '|'
    END AS member_keys
FROM group_messages gm
LEFT JOIN group_chat_meta meta ON meta.group_key=gm.group_key
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
    #[error("external chat event is invalid: {0}")]
    InvalidExternalEvent(String),
    #[error("database operation is invalid: {0}")]
    InvalidOperation(String),
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
pub struct PrivateChatTurn {
    pub conversation_id: i64,
    pub user_message_id: i64,
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

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct RelationshipState {
    pub id: i64,
    pub character: String,
    pub user_key: String,
    pub affection: i64,
    pub trust: i64,
    pub familiarity: i64,
    pub mood: String,
    pub mood_intensity: i64,
    pub summary: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct RelationshipUpdate<'a> {
    pub affection: Option<i64>,
    pub trust: Option<i64>,
    pub familiarity: Option<i64>,
    pub mood: Option<&'a str>,
    pub mood_intensity: Option<i64>,
    pub summary: Option<&'a str>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RelationshipDelta<'a> {
    pub affection: i64,
    pub trust: i64,
    pub familiarity: i64,
    pub mood: &'a str,
    pub mood_intensity: Option<i64>,
    pub event_type: &'a str,
    pub reason: &'a str,
}

impl Default for RelationshipDelta<'_> {
    fn default() -> Self {
        Self {
            affection: 0,
            trust: 0,
            familiarity: 0,
            mood: "",
            mood_intensity: None,
            event_type: "interaction",
            reason: "",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CharacterMemory {
    pub id: i64,
    pub character: String,
    pub user_key: String,
    pub kind: String,
    pub content: String,
    pub importance: i64,
    pub source_message_id: Option<i64>,
    pub source_group_message_id: Option<i64>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct MoodChartPoint {
    pub day: String,
    pub affection: i64,
    pub trust: i64,
    pub familiarity: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct UsageDay {
    pub day: String,
    pub seconds: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalChatMessage {
    pub id: i64,
    pub platform: String,
    pub thread_id: String,
    pub external_message_id: String,
    pub sender_id: String,
    pub sender_name: String,
    pub direction: String,
    pub content: String,
    pub unread: bool,
    pub raw_json: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalThreadSummary {
    pub platform: String,
    pub thread_id: String,
    pub thread_name: String,
    pub unread_count: i64,
    pub last_message_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalUnreadThread {
    pub platform: String,
    pub thread_id: String,
    pub thread_name: String,
    pub unread_count: i64,
    pub last_message_at: String,
    pub messages: Vec<ExternalChatMessage>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalUnreadSummary {
    pub total_unread: i64,
    pub threads: Vec<ExternalUnreadThread>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalAddResult {
    pub duplicate: bool,
    pub message_id: i64,
    pub pruned_messages: i64,
    pub thread: ExternalThreadSummary,
    pub unread: ExternalUnreadSummary,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalMarkReadResult {
    pub marked_read: i64,
    pub unread: ExternalUnreadSummary,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ExternalDeleteResult {
    pub deleted_messages: i64,
    pub deleted_threads: i64,
    pub unread: Option<ExternalUnreadSummary>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatHistoryFilterOptions {
    pub characters: Vec<String>,
    pub user_keys: Vec<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChatHistoryQuery<'a> {
    pub keyword: &'a str,
    pub date_from: &'a str,
    pub date_to: &'a str,
    pub character: &'a str,
    pub user_key: &'a str,
    pub role: &'a str,
    pub source: &'a str,
    pub limit: i64,
    pub offset: i64,
    pub skip_count: bool,
}

impl Default for ChatHistoryQuery<'_> {
    fn default() -> Self {
        Self {
            keyword: "",
            date_from: "",
            date_to: "",
            character: "",
            user_key: "",
            role: "",
            source: "",
            limit: 300,
            offset: 0,
            skip_count: false,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatHistoryRecord {
    pub source: String,
    pub id: i64,
    pub conversation_id: String,
    pub character: String,
    pub group_key: String,
    pub chat_title: String,
    pub user_key: String,
    pub role: String,
    pub content: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatHistorySearchResult {
    pub total: i64,
    pub has_more: bool,
    pub records: Vec<ChatHistoryRecord>,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GroupConversation {
    pub group_key: String,
    pub conversation_id: String,
    pub user_key: String,
    pub message_id: i64,
    pub role: String,
    pub content: String,
    pub created_at: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatSummary {
    pub total_conversations: i64,
    pub total_messages: i64,
    pub total_group_messages: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct DailyMessageCount {
    pub day: String,
    pub count: i64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct ChatDatabaseSummary {
    pub conversations: i64,
    pub messages: i64,
    pub group_messages: i64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct RelationshipData {
    pub relationship_states: Vec<RelationshipState>,
    pub character_memories: Vec<CharacterMemory>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct RelationshipImportSummary {
    pub relationship_states: i64,
    pub character_memories: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CharacterMessageCount {
    pub character: String,
    pub count: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AlbumMessage {
    pub id: i64,
    pub source: String,
    pub conversation_id: Value,
    pub group_key: String,
    pub role: String,
    pub content: String,
    pub reasoning_content: String,
    pub attachments_json: String,
    pub tool_trace_json: String,
    pub created_at: String,
    pub speaker: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ConversationChainItem {
    pub source: String,
    pub conversation_id: Value,
    pub group_key: String,
    pub user_key: String,
    pub title: String,
    pub created_at: String,
    pub first_message_at: String,
    pub last_message_at: String,
    pub message_count: i64,
    pub first_user: String,
    pub preview: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct AlbumSnippet {
    pub role: String,
    pub content: String,
    pub source: String,
    pub speaker: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct CharacterAlbumDay {
    pub day: String,
    pub message_count: i64,
    pub user_count: i64,
    pub assistant_count: i64,
    pub memory_count: i64,
    pub favorite_count: i64,
    pub first_at: String,
    pub last_at: String,
    pub snippets: Vec<String>,
    pub snippet_items: Vec<AlbumSnippet>,
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
    path: PathBuf,
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
            path,
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

    pub fn resolve_chat_attachment(&self, path: &str) -> Option<PathBuf> {
        let safe_root = self.attachment_dir.canonicalize().ok()?;
        let resolved = Path::new(path).canonicalize().ok()?;
        (resolved.is_file() && resolved.strip_prefix(safe_root).is_ok()).then_some(resolved)
    }

    pub fn begin_private_chat_turn(
        &self,
        character: &str,
        user_key: &str,
        requested_conversation_id: Option<i64>,
        content: &str,
        attachments: Option<&Value>,
    ) -> Result<PrivateChatTurn, DatabaseError> {
        let character = character.trim();
        let content = content.trim();
        if character.is_empty() {
            return Err(DatabaseError::InvalidOperation(
                "chat character cannot be empty".to_owned(),
            ));
        }
        if content.is_empty() {
            return Err(DatabaseError::InvalidOperation(
                "chat message cannot be empty".to_owned(),
            ));
        }
        let user_key = normalize_user_key(user_key);
        let attachments = sanitize_attachments(attachments, &self.attachment_dir);
        let attachments_json = json_text(Some(&attachments))?;
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let conversation_id = match requested_conversation_id.filter(|value| *value > 0) {
                Some(conversation_id) => transaction
                    .query_row(
                        concat!(
                            "SELECT id FROM conversations ",
                            "WHERE id=? AND character=? AND user_key=?"
                        ),
                        params![conversation_id, character, user_key],
                        |row| row.get::<_, i64>(0),
                    )
                    .optional()?
                    .ok_or_else(|| {
                        DatabaseError::InvalidOperation(
                            "conversation does not belong to the selected character and user"
                                .to_owned(),
                        )
                    })?,
                None => {
                    transaction.execute(
                        "INSERT INTO conversations (character, user_key, title) VALUES (?, ?, '')",
                        params![character, user_key],
                    )?;
                    transaction.last_insert_rowid()
                }
            };
            transaction.execute(
                concat!(
                    "INSERT INTO messages ",
                    "(conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json) ",
                    "VALUES (?, 'user', ?, '', ?, '')"
                ),
                params![conversation_id, content, attachments_json],
            )?;
            let user_message_id = transaction.last_insert_rowid();
            transaction.commit()?;
            Ok(PrivateChatTurn {
                conversation_id,
                user_message_id,
            })
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

    pub fn relationship_state(
        &self,
        character: &str,
        user_key: &str,
    ) -> Result<RelationshipState, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            relationship_state_from_connection(connection, character, &user_key)
        })
    }

    pub fn upsert_relationship_state(
        &self,
        character: &str,
        user_key: &str,
        update: &RelationshipUpdate<'_>,
    ) -> Result<RelationshipState, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let current = relationship_state_from_connection(&transaction, character, &user_key)?;
            let mood = nonempty_mood(update.mood.unwrap_or(&current.mood).to_owned());
            let next = RelationshipState {
                id: current.id,
                character: character.to_owned(),
                user_key: user_key.clone(),
                affection: update.affection.unwrap_or(current.affection).clamp(0, 100),
                trust: update.trust.unwrap_or(current.trust).clamp(0, 100),
                familiarity: update
                    .familiarity
                    .unwrap_or(current.familiarity)
                    .clamp(0, 100),
                mood,
                mood_intensity: update
                    .mood_intensity
                    .unwrap_or(current.mood_intensity)
                    .clamp(0, 100),
                summary: update.summary.unwrap_or(&current.summary).to_owned(),
                updated_at: now_text(&transaction)?,
            };
            let numeric_changed = update.affection.is_some() && next.affection != current.affection
                || update.trust.is_some() && next.trust != current.trust
                || update.familiarity.is_some() && next.familiarity != current.familiarity;
            let mood_changed = update.mood.is_some() && next.mood != current.mood
                || update.mood_intensity.is_some()
                    && next.mood_intensity != current.mood_intensity;

            write_relationship_state(&transaction, &next)?;
            if numeric_changed || mood_changed {
                transaction.execute(
                    concat!(
                        "INSERT INTO mood_events ",
                        "(character, user_key, event_type, affection_delta, trust_delta, familiarity_delta, ",
                        "affection, trust, familiarity, mood, mood_intensity, reason, created_at) ",
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    params![
                        character,
                        user_key,
                        "manual_set",
                        next.affection - current.affection,
                        next.trust - current.trust,
                        next.familiarity - current.familiarity,
                        next.affection,
                        next.trust,
                        next.familiarity,
                        if mood_changed { next.mood.as_str() } else { "" },
                        if mood_changed { next.mood_intensity } else { 0 },
                        "manual relationship state update",
                        next.updated_at,
                    ],
                )?;
            }
            let stored = relationship_state_from_connection(&transaction, character, &user_key)?;
            transaction.commit()?;
            Ok(stored)
        })
    }

    pub fn apply_relationship_delta(
        &self,
        character: &str,
        user_key: &str,
        delta: &RelationshipDelta<'_>,
    ) -> Result<RelationshipState, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let current = relationship_state_from_connection(&transaction, character, &user_key)?;
            let mood_intensity = delta.mood_intensity.unwrap_or_else(|| {
                if delta.mood.is_empty() {
                    (current.mood_intensity - 3).max(10)
                } else {
                    (current.mood_intensity + 8).clamp(25, 85)
                }
            });
            let now = now_text(&transaction)?;
            let next = RelationshipState {
                id: current.id,
                character: character.to_owned(),
                user_key: user_key.clone(),
                affection: (current.affection + delta.affection).clamp(0, 100),
                trust: (current.trust + delta.trust).clamp(0, 100),
                familiarity: (current.familiarity + delta.familiarity).clamp(0, 100),
                mood: if delta.mood.is_empty() {
                    nonempty_mood(current.mood.clone())
                } else {
                    delta.mood.to_owned()
                },
                mood_intensity: mood_intensity.clamp(0, 100),
                summary: current.summary.clone(),
                updated_at: now.clone(),
            };
            write_relationship_state(&transaction, &next)?;
            transaction.execute(
                concat!(
                    "INSERT INTO mood_events ",
                    "(character, user_key, event_type, affection_delta, trust_delta, familiarity_delta, ",
                    "affection, trust, familiarity, mood, mood_intensity, reason, created_at) ",
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                params![
                    character,
                    user_key,
                    if delta.event_type.is_empty() {
                        "interaction"
                    } else {
                        delta.event_type
                    },
                    delta.affection.clamp(-100, 100),
                    delta.trust.clamp(-100, 100),
                    delta.familiarity.clamp(-100, 100),
                    next.affection,
                    next.trust,
                    next.familiarity,
                    delta.mood,
                    mood_intensity.clamp(0, 100),
                    truncate_chars(delta.reason, 500),
                    now,
                ],
            )?;
            let stored = relationship_state_from_connection(&transaction, character, &user_key)?;
            transaction.commit()?;
            Ok(stored)
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn add_character_memory(
        &self,
        character: &str,
        user_key: &str,
        kind: &str,
        content: &str,
        importance: i64,
        source_message_id: Option<i64>,
        source_group_message_id: Option<i64>,
    ) -> Result<i64, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        let content = content.trim();
        if content.is_empty() {
            return Ok(0);
        }
        let kind = if kind.trim().is_empty() {
            "note"
        } else {
            kind.trim()
        };
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let now = now_text(&transaction)?;
            transaction.execute(
                concat!(
                    "INSERT INTO character_memories ",
                    "(character, user_key, kind, content, importance, source_message_id, ",
                    "source_group_message_id, created_at, updated_at) ",
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ",
                    "ON CONFLICT(character, user_key, content) DO UPDATE SET ",
                    "kind=excluded.kind, importance=max(character_memories.importance, excluded.importance), ",
                    "source_message_id=coalesce(excluded.source_message_id, character_memories.source_message_id), ",
                    "source_group_message_id=coalesce(excluded.source_group_message_id, character_memories.source_group_message_id), ",
                    "updated_at=excluded.updated_at"
                ),
                params![
                    character,
                    user_key,
                    kind,
                    content,
                    importance.clamp(1, 100),
                    source_message_id,
                    source_group_message_id,
                    now,
                    now,
                ],
            )?;
            let id = transaction.query_row(
                "SELECT id FROM character_memories WHERE character=? AND user_key=? AND content=?",
                params![character, user_key, content],
                |row| row.get(0),
            )?;
            transaction.commit()?;
            Ok(id)
        })
    }

    pub fn character_memories(
        &self,
        character: &str,
        user_key: &str,
        limit: i64,
    ) -> Result<Vec<CharacterMemory>, DatabaseError> {
        self.character_memories_by_kind(character, user_key, "", limit.clamp(1, 100))
    }

    pub fn character_memories_by_kind(
        &self,
        character: &str,
        user_key: &str,
        kind: &str,
        limit: i64,
    ) -> Result<Vec<CharacterMemory>, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        let kind = kind.trim();
        self.with_connection(|connection| {
            let (sql, values) = if kind.is_empty() {
                (
                    concat!(
                        "SELECT id, character, user_key, kind, content, importance, source_message_id, ",
                        "source_group_message_id, created_at, updated_at FROM character_memories ",
                        "WHERE character=? AND user_key=? ",
                        "ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?"
                    ),
                    vec![
                        SqlValue::Text(character.to_owned()),
                        SqlValue::Text(user_key.clone()),
                        SqlValue::Integer(limit.clamp(1, 100)),
                    ],
                )
            } else {
                (
                    concat!(
                        "SELECT id, character, user_key, kind, content, importance, source_message_id, ",
                        "source_group_message_id, created_at, updated_at FROM character_memories ",
                        "WHERE character=? AND user_key=? AND kind=? ",
                        "ORDER BY updated_at DESC, id DESC LIMIT ?"
                    ),
                    vec![
                        SqlValue::Text(character.to_owned()),
                        SqlValue::Text(user_key.clone()),
                        SqlValue::Text(kind.to_owned()),
                        SqlValue::Integer(limit.clamp(1, 200)),
                    ],
                )
            };
            let mut statement = connection.prepare(sql)?;
            let rows = statement.query_map(params_from_iter(values), row_to_character_memory)?;
            rows.collect::<Result<Vec<_>, _>>().map_err(DatabaseError::from)
        })
    }

    pub fn update_character_memory(
        &self,
        memory_id: i64,
        character: &str,
        user_key: &str,
        kind: &str,
        content: &str,
        importance: i64,
    ) -> Result<bool, DatabaseError> {
        let content = content.trim();
        if memory_id == 0 || content.is_empty() {
            return Ok(false);
        }
        let user_key = normalize_user_key(user_key);
        let kind = if kind.trim().is_empty() {
            "note"
        } else {
            kind.trim()
        };
        self.with_connection(|connection| {
            connection
                .execute(
                    concat!(
                        "UPDATE character_memories SET kind=?, content=?, importance=?, ",
                        "updated_at=datetime('now','localtime') ",
                        "WHERE id=? AND character=? AND user_key=?"
                    ),
                    params![
                        kind,
                        content,
                        importance.clamp(1, 100),
                        memory_id,
                        character,
                        user_key,
                    ],
                )
                .map(|changed| changed != 0)
                .map_err(DatabaseError::from)
        })
    }

    pub fn delete_character_memories(
        &self,
        memory_ids: &[i64],
        character: &str,
        user_key: &str,
    ) -> Result<usize, DatabaseError> {
        let mut ids = memory_ids
            .iter()
            .copied()
            .filter(|id| *id > 0)
            .collect::<Vec<_>>();
        ids.sort_unstable();
        ids.dedup();
        if ids.is_empty() {
            return Ok(0);
        }
        let user_key = if user_key.is_empty() {
            String::new()
        } else {
            normalize_user_key(user_key)
        };
        self.with_connection(|connection| {
            let placeholders = std::iter::repeat_n("?", ids.len())
                .collect::<Vec<_>>()
                .join(",");
            let sql = format!(
                "DELETE FROM character_memories WHERE id IN ({placeholders}) \
                 AND (?='' OR character=?) AND (?='' OR user_key=?)"
            );
            let mut values = ids.into_iter().map(SqlValue::Integer).collect::<Vec<_>>();
            values.extend([
                SqlValue::Text(character.to_owned()),
                SqlValue::Text(character.to_owned()),
                SqlValue::Text(user_key.clone()),
                SqlValue::Text(user_key),
            ]);
            connection
                .execute(&sql, params_from_iter(values))
                .map_err(DatabaseError::from)
        })
    }

    pub fn delete_character_memories_like(
        &self,
        character: &str,
        user_key: &str,
        query: &str,
    ) -> Result<usize, DatabaseError> {
        let query = query.trim();
        if query.is_empty() {
            return Ok(0);
        }
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            connection
                .execute(
                    "DELETE FROM character_memories WHERE character=? AND user_key=? AND content LIKE ? ESCAPE '\\'",
                    params![character, user_key, format!("%{}%", escape_like(query))],
                )
                .map_err(DatabaseError::from)
        })
    }

    pub fn mood_events_for_chart(
        &self,
        character: &str,
        user_key: &str,
        days: i64,
    ) -> Result<Vec<MoodChartPoint>, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            mood_events_for_chart(connection, character, &user_key, days)
        })
    }

    pub fn start_usage_session(&self) -> Result<i64, DatabaseError> {
        self.with_connection(|connection| {
            connection.execute(
                "INSERT INTO usage_sessions (start_time) VALUES (datetime('now','localtime'))",
                [],
            )?;
            Ok(connection.last_insert_rowid())
        })
    }

    pub fn end_usage_session(&self, session_id: i64) -> Result<usize, DatabaseError> {
        self.with_connection(|connection| {
            connection
                .execute(
                    concat!(
                        "UPDATE usage_sessions SET end_time=datetime('now','localtime'), ",
                        "duration_seconds=CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) ",
                        "WHERE id=? AND end_time IS NULL"
                    ),
                    params![session_id],
                )
                .map_err(DatabaseError::from)
        })
    }

    pub fn heartbeat_usage_session(&self, session_id: i64) -> Result<usize, DatabaseError> {
        self.with_connection(|connection| {
            connection
                .execute(
                    concat!(
                        "UPDATE usage_sessions SET ",
                        "duration_seconds=CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) ",
                        "WHERE id=? AND end_time IS NULL"
                    ),
                    params![session_id],
                )
                .map_err(DatabaseError::from)
        })
    }

    pub fn usage_today(&self) -> Result<i64, DatabaseError> {
        self.with_connection(|connection| {
            usage_total(connection, "date(start_time)=date('now','localtime')")
        })
    }

    pub fn usage_week(&self) -> Result<i64, DatabaseError> {
        self.with_connection(|connection| {
            usage_total(
                connection,
                "start_time>=datetime('now','localtime','-6 days','start of day')",
            )
        })
    }

    pub fn usage_all_time(&self) -> Result<i64, DatabaseError> {
        self.with_connection(|connection| usage_total(connection, "1=1"))
    }

    pub fn usage_daily(&self, days: i64) -> Result<Vec<UsageDay>, DatabaseError> {
        self.with_connection(|connection| {
            let mut statement = connection.prepare(concat!(
                "SELECT date(start_time), COALESCE(SUM(duration_seconds),0) FROM usage_sessions ",
                "WHERE start_time>=datetime('now','localtime',?,'start of day') ",
                "GROUP BY date(start_time) ORDER BY date(start_time) ASC"
            ))?;
            let modifier = format!("-{} days", days.max(0));
            let rows = statement.query_map(params![modifier], |row| {
                Ok(UsageDay {
                    day: row.get(0)?,
                    seconds: row.get(1)?,
                })
            })?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(DatabaseError::from)
        })
    }

    pub fn chat_history_filter_options(&self) -> Result<ChatHistoryFilterOptions, DatabaseError> {
        self.with_connection(|connection| {
            let mut characters = BTreeSet::new();
            {
                let mut statement = connection.prepare(
                    "SELECT DISTINCT character FROM conversations WHERE character != ''",
                )?;
                for character in statement
                    .query_map([], |row| row.get::<_, String>(0))?
                    .collect::<Result<Vec<_>, _>>()?
                {
                    let character = character.trim();
                    if !character.is_empty() && character != "__group__" {
                        characters.insert(character.to_owned());
                    }
                }
            }
            {
                let mut statement = connection.prepare(
                    "SELECT DISTINCT group_key FROM group_messages WHERE group_key != ''",
                )?;
                for group_key in statement
                    .query_map([], |row| row.get::<_, String>(0))?
                    .collect::<Result<Vec<_>, _>>()?
                {
                    characters.extend(group_key_characters(&group_key));
                }
            }
            let mut user_keys = {
                let mut statement = connection.prepare(concat!(
                    "SELECT user_key FROM conversations WHERE user_key != '' ",
                    "UNION SELECT user_key FROM group_messages WHERE user_key != ''"
                ))?;
                statement
                    .query_map([], |row| row.get::<_, String>(0))?
                    .collect::<Result<Vec<_>, _>>()?
            };
            user_keys.retain(|key| !key.trim().is_empty());
            user_keys.sort_by_key(|value| value.to_lowercase());
            user_keys.dedup();
            let mut characters = characters.into_iter().collect::<Vec<_>>();
            characters.sort_by_key(|value| value.to_lowercase());
            Ok(ChatHistoryFilterOptions {
                characters,
                user_keys,
            })
        })
    }

    pub fn search_chat_history(
        &self,
        query: &ChatHistoryQuery<'_>,
    ) -> Result<ChatHistorySearchResult, DatabaseError> {
        let keyword = truncate_chars(query.keyword.trim(), 500);
        let date_from = truncate_chars(query.date_from.trim(), 10);
        let date_to = truncate_chars(query.date_to.trim(), 10);
        let character = query.character.trim();
        let user_key = query.user_key.trim();
        let role = query.role.trim();
        let source = query.source.trim();
        let limit = query.limit.clamp(1, 1000);
        let offset = query.offset.clamp(0, 1_000_000);
        self.with_connection(|connection| {
            let mut clauses = Vec::new();
            let mut values = Vec::new();
            if !keyword.is_empty() {
                clauses.push("content LIKE ? ESCAPE '\\' COLLATE NOCASE");
                values.push(SqlValue::Text(format!("%{}%", escape_like(&keyword))));
            }
            if !date_from.is_empty() {
                clauses.push("created_at >= ?");
                values.push(SqlValue::Text(format!("{date_from} 00:00:00")));
            }
            if !date_to.is_empty() {
                clauses.push("created_at <= ?");
                values.push(SqlValue::Text(format!("{date_to} 23:59:59")));
            }
            if !character.is_empty() {
                clauses.push("instr(member_keys, ?) > 0");
                values.push(SqlValue::Text(format!("|{character}|")));
            }
            if !user_key.is_empty() {
                clauses.push("user_key = ?");
                values.push(SqlValue::Text(user_key.to_owned()));
            }
            if matches!(role, "user" | "assistant" | "system") {
                clauses.push("role = ?");
                values.push(SqlValue::Text(role.to_owned()));
            }
            if matches!(source, "private" | "group") {
                clauses.push("source = ?");
                values.push(SqlValue::Text(source.to_owned()));
            }
            let where_sql = if clauses.is_empty() {
                String::new()
            } else {
                format!(" WHERE {}", clauses.join(" AND "))
            };
            let total = if query.skip_count {
                -1
            } else {
                connection.query_row(
                    &format!("SELECT COUNT(*) FROM ({CHAT_HISTORY_SQL}) history{where_sql}"),
                    params_from_iter(values.clone()),
                    |row| row.get::<_, i64>(0),
                )?
            };
            let probe = if query.skip_count { limit + 1 } else { limit };
            let mut page_values = values;
            page_values.push(SqlValue::Integer(probe));
            page_values.push(SqlValue::Integer(offset));
            let mut statement = connection.prepare(&format!(
                concat!(
                    "SELECT source, source_id, conversation_id, character, group_key, ",
                    "chat_title, user_key, role, content, created_at FROM ({}) history",
                    "{} ORDER BY created_at DESC, source_id DESC LIMIT ? OFFSET ?"
                ),
                CHAT_HISTORY_SQL, where_sql
            ))?;
            let mut records = statement
                .query_map(params_from_iter(page_values), row_to_chat_history_record)?
                .collect::<Result<Vec<_>, _>>()?;
            let has_more = query.skip_count && records.len() > limit as usize;
            if has_more {
                records.truncate(limit as usize);
            }
            Ok(ChatHistorySearchResult {
                total,
                has_more,
                records,
                limit,
                offset,
            })
        })
    }

    pub fn first_user_message_content(
        &self,
        conversation_id: i64,
    ) -> Result<String, DatabaseError> {
        self.with_connection(|connection| {
            connection
                .query_row(
                    concat!(
                        "SELECT content FROM messages WHERE conversation_id=? ",
                        "AND role='user' AND content != '' ORDER BY id ASC LIMIT 1"
                    ),
                    params![conversation_id],
                    |row| row.get::<_, String>(0),
                )
                .optional()
                .map(|value| value.unwrap_or_default().trim().to_owned())
                .map_err(DatabaseError::from)
        })
    }

    pub fn group_conversations(
        &self,
        group_key: &str,
        user_key: Option<&str>,
    ) -> Result<Vec<GroupConversation>, DatabaseError> {
        self.with_connection(|connection| {
            let mut sql = concat!(
                "SELECT g.conversation_id, g.user_key, g.id, g.role, g.content, g.created_at ",
                "FROM group_messages g JOIN (SELECT conversation_id, MAX(id) AS latest_id ",
                "FROM group_messages WHERE group_key=? "
            )
            .to_owned();
            let mut values = vec![SqlValue::Text(group_key.to_owned())];
            if let Some(user_key) = user_key {
                sql.push_str("AND user_key=? ");
                values.push(SqlValue::Text(normalize_user_key(user_key)));
            }
            sql.push_str(concat!(
                "AND role IN ('user','assistant','system') GROUP BY conversation_id) latest ",
                "ON g.id=latest.latest_id ORDER BY latest.latest_id DESC"
            ));
            let mut statement = connection.prepare(&sql)?;
            let rows = statement.query_map(params_from_iter(values), |row| {
                row_to_group_conversation(row, group_key, false)
            })?;
            rows.collect::<Result<Vec<_>, _>>()
                .map_err(DatabaseError::from)
        })
    }

    pub fn group_chats(
        &self,
        user_key: Option<&str>,
    ) -> Result<Vec<GroupConversation>, DatabaseError> {
        self.with_connection(|connection| {
            let mut sql = concat!(
                "SELECT g.group_key, g.conversation_id, g.user_key, g.id, g.role, g.content, g.created_at ",
                "FROM group_messages g JOIN (SELECT group_key, MAX(id) AS latest_id ",
                "FROM group_messages WHERE "
            )
            .to_owned();
            let mut values = Vec::new();
            if let Some(user_key) = user_key {
                sql.push_str("user_key=? AND ");
                values.push(SqlValue::Text(normalize_user_key(user_key)));
            }
            sql.push_str(concat!(
                "role IN ('user','assistant','system') GROUP BY group_key) latest ",
                "ON g.id=latest.latest_id ORDER BY latest.latest_id DESC"
            ));
            let mut statement = connection.prepare(&sql)?;
            let rows = statement.query_map(params_from_iter(values), |row| {
                row_to_group_conversation(row, "", true)
            })?;
            rows.collect::<Result<Vec<_>, _>>().map_err(DatabaseError::from)
        })
    }

    pub fn delete_empty_conversations(
        &self,
        character: &str,
        user_key: Option<&str>,
    ) -> Result<usize, DatabaseError> {
        self.with_connection(|connection| {
            let mut clauses = Vec::new();
            let mut values = Vec::new();
            if !character.is_empty() {
                clauses.push("character=?");
                values.push(SqlValue::Text(character.to_owned()));
            }
            if let Some(user_key) = user_key {
                clauses.push("user_key=?");
                values.push(SqlValue::Text(normalize_user_key(user_key)));
            }
            clauses.push(
                "NOT EXISTS (SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id)",
            );
            connection
                .execute(
                    &format!("DELETE FROM conversations WHERE {}", clauses.join(" AND ")),
                    params_from_iter(values),
                )
                .map_err(DatabaseError::from)
        })
    }

    pub fn chat_summary(&self) -> Result<ChatSummary, DatabaseError> {
        self.with_connection(|connection| {
            Ok(ChatSummary {
                total_conversations: table_count(connection, "conversations")?,
                total_messages: table_count(connection, "messages")?,
                total_group_messages: table_count(connection, "group_messages")?,
            })
        })
    }

    pub fn daily_message_counts(
        &self,
        days: i64,
        user_key: Option<&str>,
    ) -> Result<Vec<DailyMessageCount>, DatabaseError> {
        self.with_connection(|connection| {
            let modifier = format!("-{} days", days.max(0));
            let private = daily_counts_for_source(connection, true, &modifier, user_key)?;
            let group = daily_counts_for_source(connection, false, &modifier, user_key)?;
            let mut counts = BTreeMap::new();
            for (day, count) in private.into_iter().chain(group) {
                if !day.is_empty() {
                    *counts.entry(day).or_insert(0) += count;
                }
            }
            Ok(counts
                .into_iter()
                .map(|(day, count)| DailyMessageCount { day, count })
                .collect())
        })
    }

    pub fn hourly_heatmap(
        &self,
        days: i64,
        user_key: Option<&str>,
    ) -> Result<Vec<Vec<i64>>, DatabaseError> {
        self.with_connection(|connection| {
            let modifier = format!("-{} days", days.max(0));
            let mut grid = vec![vec![0; 24]; 7];
            for (weekday, hour, count) in hourly_counts(connection, true, &modifier, user_key)?
                .into_iter()
                .chain(hourly_counts(connection, false, &modifier, user_key)?)
            {
                let iso_day = (weekday - 1).rem_euclid(7);
                if (0..7).contains(&iso_day) && (0..24).contains(&hour) {
                    grid[iso_day as usize][hour as usize] += count;
                }
            }
            Ok(grid)
        })
    }

    pub fn add_external_chat_message(
        &self,
        event: &Value,
    ) -> Result<ExternalAddResult, DatabaseError> {
        let event = event.as_object().ok_or_else(|| {
            DatabaseError::InvalidExternalEvent("event must be a JSON object".into())
        })?;
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let platform = clean_external_text(
                first_event_value(event, &["platform", "source"]),
                "external",
                500,
            );
            let platform = if platform.is_empty() {
                "external".to_owned()
            } else {
                platform
            };
            let thread_id = clean_external_text(
                first_event_value(
                    event,
                    &["thread_id", "conversation_id", "chat_id", "room_id"],
                ),
                "default",
                500,
            );
            let thread_id = if thread_id.is_empty() {
                "default".to_owned()
            } else {
                thread_id
            };
            let thread_name = clean_external_text(
                first_event_value(
                    event,
                    &["thread_name", "conversation_name", "chat_name", "room_name"],
                ),
                &thread_id,
                500,
            );
            let external_message_id = clean_external_text(
                first_event_value(event, &["message_id", "external_message_id", "id"]),
                "",
                500,
            );
            let sender_id = clean_external_text(
                first_event_value(event, &["sender_id", "author_id"]),
                "",
                500,
            );
            let sender_name = clean_external_text(
                first_event_value(event, &["sender_name", "author_name", "sender", "from"]),
                if sender_id.is_empty() {
                    "unknown"
                } else {
                    &sender_id
                },
                500,
            );
            let content = clean_external_text(
                first_event_value(event, &["text", "content", "message", "body"]),
                "",
                20_000,
            );
            if content.is_empty() {
                return Err(DatabaseError::InvalidExternalEvent(
                    "text/content is required".into(),
                ));
            }
            let mut direction = clean_external_text(event.get("direction"), "inbound", 500)
                .to_lowercase();
            if !matches!(direction.as_str(), "inbound" | "outbound" | "draft") {
                direction = "inbound".into();
            }
            let mut chat_type =
                clean_external_text(event.get("chat_type"), "", 500).to_lowercase();
            if !matches!(chat_type.as_str(), "group" | "private") {
                chat_type.clear();
            }
            let unread = direction == "inbound"
                && event
                    .get("unread")
                    .map_or(direction == "inbound", json_truthy);
            let now = now_text(&transaction)?;
            let created_at = clean_external_text(
                first_event_value(event, &["timestamp", "created_at"]),
                &now,
                500,
            );

            if !external_message_id.is_empty() {
                let duplicate = transaction
                    .query_row(
                        concat!(
                            "SELECT id FROM external_chat_messages WHERE platform=? ",
                            "AND thread_id=? AND external_message_id=? LIMIT 1"
                        ),
                        params![platform, thread_id, external_message_id],
                        |row| row.get::<_, i64>(0),
                    )
                    .optional()?;
                if let Some(message_id) = duplicate {
                    let result = ExternalAddResult {
                        duplicate: true,
                        message_id,
                        pruned_messages: 0,
                        thread: external_thread_summary(&transaction, &platform, &thread_id)?,
                        unread: external_unread_summary(&transaction, 5, 3)?,
                    };
                    transaction.commit()?;
                    return Ok(result);
                }
            }

            let raw_json = serde_json::to_string(&Value::Object(event.clone()))?;
            transaction.execute(
                concat!(
                    "INSERT INTO external_chat_messages ",
                    "(platform, thread_id, external_message_id, sender_id, sender_name, direction, ",
                    "content, unread, chat_type, raw_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                params![
                    platform,
                    thread_id,
                    external_message_id,
                    sender_id,
                    sender_name,
                    direction,
                    content,
                    i64::from(unread),
                    chat_type,
                    raw_json,
                    created_at,
                ],
            )?;
            let message_id = transaction.last_insert_rowid();
            transaction.execute(
                concat!(
                    "INSERT INTO external_chat_threads ",
                    "(platform, thread_id, thread_name, chat_type, unread_count, last_message_id, last_message_at, updated_at) ",
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ",
                    "ON CONFLICT(platform, thread_id) DO UPDATE SET ",
                    "thread_name=CASE WHEN excluded.thread_name != '' THEN excluded.thread_name ELSE external_chat_threads.thread_name END, ",
                    "chat_type=CASE WHEN excluded.chat_type != '' THEN excluded.chat_type ELSE external_chat_threads.chat_type END, ",
                    "unread_count=external_chat_threads.unread_count + ?, ",
                    "last_message_id=excluded.last_message_id, last_message_at=excluded.last_message_at, ",
                    "updated_at=excluded.updated_at"
                ),
                params![
                    platform,
                    thread_id,
                    thread_name,
                    chat_type,
                    i64::from(unread),
                    message_id,
                    created_at,
                    now,
                    i64::from(unread),
                ],
            )?;
            let pruned_messages = if chat_type == "group" {
                prune_external_group_thread_messages(&transaction, &platform, &thread_id)?
            } else {
                0
            };
            let result = ExternalAddResult {
                duplicate: false,
                message_id,
                pruned_messages,
                thread: external_thread_summary(&transaction, &platform, &thread_id)?,
                unread: external_unread_summary(&transaction, 5, 3)?,
            };
            transaction.commit()?;
            Ok(result)
        })
    }

    pub fn external_chat_unread_summary(
        &self,
        limit_threads: i64,
        limit_messages: i64,
    ) -> Result<ExternalUnreadSummary, DatabaseError> {
        self.with_connection(|connection| {
            external_unread_summary(connection, limit_threads, limit_messages)
        })
    }

    pub fn external_chat_context_text(
        &self,
        limit_threads: i64,
        limit_messages: i64,
    ) -> Result<String, DatabaseError> {
        self.with_connection(|connection| {
            external_context_text(connection, limit_threads, limit_messages)
        })
    }

    pub fn mark_external_chat_read(
        &self,
        platform: &str,
        thread_id: &str,
    ) -> Result<ExternalMarkReadResult, DatabaseError> {
        let platform = truncate_chars(platform.trim(), 500);
        let thread_id = truncate_chars(thread_id.trim(), 500);
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let marked_read = transaction.execute(
                concat!(
                    "UPDATE external_chat_messages SET unread=0 WHERE unread=1 ",
                    "AND (?='' OR platform=?) AND (?='' OR thread_id=?)"
                ),
                params![platform, platform, thread_id, thread_id],
            )? as i64;
            let now = now_text(&transaction)?;
            match (platform.is_empty(), thread_id.is_empty()) {
                (false, false) => transaction.execute(
                    concat!(
                        "UPDATE external_chat_threads SET unread_count=0, updated_at=? ",
                        "WHERE platform=? AND thread_id=?"
                    ),
                    params![now, platform, thread_id],
                )?,
                (false, true) => transaction.execute(
                    concat!(
                        "UPDATE external_chat_threads SET unread_count=0, updated_at=? ",
                        "WHERE platform=?"
                    ),
                    params![now, platform],
                )?,
                (true, false) => transaction.execute(
                    concat!(
                        "UPDATE external_chat_threads SET unread_count=0, updated_at=? ",
                        "WHERE thread_id=?"
                    ),
                    params![now, thread_id],
                )?,
                (true, true) => transaction.execute(
                    "UPDATE external_chat_threads SET unread_count=0, updated_at=?",
                    params![now],
                )?,
            };
            let unread = external_unread_summary(&transaction, 5, 3)?;
            transaction.commit()?;
            Ok(ExternalMarkReadResult {
                marked_read,
                unread,
            })
        })
    }

    pub fn prune_external_group_chat_limit(&self) -> Result<i64, DatabaseError> {
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let threads = {
                let mut statement = transaction.prepare(concat!(
                    "SELECT platform, thread_id FROM external_chat_threads WHERE chat_type='group' ",
                    "UNION SELECT platform, thread_id FROM external_chat_messages WHERE chat_type='group'"
                ))?;
                statement
                    .query_map([], |row| {
                        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
                    })?
                    .collect::<Result<Vec<_>, _>>()?
            };
            let mut deleted = 0;
            for (platform, thread_id) in threads {
                deleted +=
                    prune_external_group_thread_messages(&transaction, &platform, &thread_id)?;
            }
            transaction.commit()?;
            Ok(deleted)
        })
    }

    pub fn delete_external_chat(
        &self,
        chat_type: &str,
        platform: &str,
    ) -> Result<ExternalDeleteResult, DatabaseError> {
        let chat_type = truncate_chars(chat_type.trim(), 500);
        let platform = truncate_chars(platform.trim(), 500);
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let deleted_messages = transaction.execute(
                concat!(
                    "DELETE FROM external_chat_messages ",
                    "WHERE (?='' OR chat_type=?) AND (?='' OR platform=?)"
                ),
                params![chat_type, chat_type, platform, platform],
            )? as i64;
            let deleted_threads = transaction.execute(
                concat!(
                    "DELETE FROM external_chat_threads ",
                    "WHERE (?='' OR chat_type=?) AND (?='' OR platform=?)"
                ),
                params![chat_type, chat_type, platform, platform],
            )? as i64;
            if deleted_messages != 0 {
                resync_external_chat_threads(&transaction)?;
            }
            let unread = external_unread_summary(&transaction, 5, 3)?;
            transaction.commit()?;
            Ok(ExternalDeleteResult {
                deleted_messages,
                deleted_threads,
                unread: Some(unread),
            })
        })
    }

    pub fn purge_external_chat_older_than(
        &self,
        days: i64,
        chat_type: &str,
        platform: &str,
    ) -> Result<i64, DatabaseError> {
        let days = days.clamp(1, 3650);
        let chat_type = truncate_chars(chat_type.trim(), 500);
        let platform = truncate_chars(platform.trim(), 500);
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let deleted = transaction.execute(
                concat!(
                    "DELETE FROM external_chat_messages WHERE ",
                    "created_at < datetime('now','localtime',?) ",
                    "AND (?='' OR chat_type=?) AND (?='' OR platform=?)"
                ),
                params![
                    format!("-{days} days"),
                    chat_type,
                    chat_type,
                    platform,
                    platform,
                ],
            )? as i64;
            if deleted != 0 {
                resync_external_chat_threads(&transaction)?;
            }
            transaction.commit()?;
            Ok(deleted)
        })
    }

    pub fn messages_per_character_range(
        &self,
        days: i64,
        user_key: &str,
        display_aliases: &BTreeMap<String, Vec<String>>,
    ) -> Result<Vec<CharacterMessageCount>, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            let mut private_sql = concat!(
                "SELECT c.character, COUNT(m.id) FROM conversations c ",
                "JOIN messages m ON m.conversation_id=c.id WHERE c.user_key=? ",
                "AND c.character!='' AND c.character!='__group__' "
            )
            .to_owned();
            let mut private_values = vec![SqlValue::Text(user_key.clone())];
            if days > 0 {
                private_sql.push_str("AND m.created_at>=datetime('now','localtime',?) ");
                private_values.push(SqlValue::Text(format!("-{days} days")));
            }
            private_sql.push_str("GROUP BY c.character ORDER BY COUNT(m.id) DESC");
            let mut counts = {
                let mut statement = connection.prepare(&private_sql)?;
                statement
                    .query_map(params_from_iter(private_values), |row| {
                        Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
                    })?
                    .collect::<Result<BTreeMap<_, _>, _>>()?
            };

            let mut group_sql = concat!(
                "SELECT group_key, role, content FROM group_messages ",
                "WHERE user_key=? AND group_key LIKE '__group__:%'"
            )
            .to_owned();
            let mut group_values = vec![SqlValue::Text(user_key)];
            if days > 0 {
                group_sql.push_str(" AND created_at>=datetime('now','localtime',?)");
                group_values.push(SqlValue::Text(format!("-{days} days")));
            }
            let mut statement = connection.prepare(&group_sql)?;
            let rows = statement
                .query_map(params_from_iter(group_values), |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, String>(2)?,
                    ))
                })?
                .collect::<Result<Vec<_>, _>>()?;
            for (group_key, role, content) in rows {
                for character in
                    group_message_count_characters(&group_key, &role, &content, display_aliases)
                {
                    *counts.entry(character).or_insert(0) += 1;
                }
            }
            let mut result = counts
                .into_iter()
                .map(|(character, count)| CharacterMessageCount { character, count })
                .collect::<Vec<_>>();
            result.sort_by(|left, right| {
                right
                    .count
                    .cmp(&left.count)
                    .then_with(|| left.character.cmp(&right.character))
            });
            Ok(result)
        })
    }

    pub fn character_recent_messages(
        &self,
        character: &str,
        user_key: &str,
        limit: i64,
        character_aliases: &[String],
    ) -> Result<Vec<AlbumMessage>, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            character_recent_messages(connection, character, &user_key, limit, character_aliases)
        })
    }

    pub fn character_conversation_chain(
        &self,
        character: &str,
        user_key: &str,
        limit: i64,
        character_aliases: &[String],
    ) -> Result<Vec<ConversationChainItem>, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            character_conversation_chain(connection, character, &user_key, limit, character_aliases)
        })
    }

    pub fn character_album_days(
        &self,
        character: &str,
        user_key: &str,
        limit: i64,
        character_aliases: &[String],
    ) -> Result<Vec<CharacterAlbumDay>, DatabaseError> {
        let user_key = normalize_user_key(user_key);
        self.with_connection(|connection| {
            let messages = character_recent_messages(
                connection,
                character,
                &user_key,
                600,
                character_aliases,
            )?;
            let mut by_day: BTreeMap<String, CharacterAlbumDay> = BTreeMap::new();
            for message in messages {
                let day = message.created_at.chars().take(10).collect::<String>();
                if day.chars().count() != 10 {
                    continue;
                }
                let entry = by_day
                    .entry(day.clone())
                    .or_insert_with(|| CharacterAlbumDay {
                        day,
                        message_count: 0,
                        user_count: 0,
                        assistant_count: 0,
                        memory_count: 0,
                        favorite_count: 0,
                        first_at: message.created_at.clone(),
                        last_at: message.created_at.clone(),
                        snippets: Vec::new(),
                        snippet_items: Vec::new(),
                    });
                entry.message_count += 1;
                match message.role.as_str() {
                    "user" => entry.user_count += 1,
                    "assistant" => entry.assistant_count += 1,
                    _ => {}
                }
                if message.created_at < entry.first_at {
                    entry.first_at = message.created_at.clone();
                }
                if message.created_at > entry.last_at {
                    entry.last_at = message.created_at.clone();
                }
                let content = collapse_whitespace(&message.content);
                if !content.is_empty() && entry.snippets.len() < 3 {
                    entry.snippets.push(truncate_chars(&content, 120));
                }
                if !content.is_empty() && entry.snippet_items.len() < 3 {
                    entry.snippet_items.push(AlbumSnippet {
                        role: message.role,
                        content: truncate_chars(&content, 160),
                        source: message.source,
                        speaker: message.speaker,
                    });
                }
            }

            let memories =
                character_memories_from_connection(connection, character, &user_key, "", 100)?;
            for memory in memories {
                let timestamp = if memory.created_at.is_empty() {
                    memory.updated_at
                } else {
                    memory.created_at
                };
                let day = timestamp.chars().take(10).collect::<String>();
                if day.chars().count() != 10 {
                    continue;
                }
                let entry = by_day
                    .entry(day.clone())
                    .or_insert_with(|| CharacterAlbumDay {
                        day,
                        message_count: 0,
                        user_count: 0,
                        assistant_count: 0,
                        memory_count: 0,
                        favorite_count: 0,
                        first_at: timestamp.clone(),
                        last_at: timestamp.clone(),
                        snippets: Vec::new(),
                        snippet_items: Vec::new(),
                    });
                entry.memory_count += 1;
                if memory.kind == "favorite" {
                    entry.favorite_count += 1;
                }
            }
            let mut days = by_day.into_values().collect::<Vec<_>>();
            days.sort_by(|left, right| right.day.cmp(&left.day));
            days.truncate(limit.clamp(1, 120) as usize);
            Ok(days)
        })
    }

    pub fn database_summary(&self) -> Result<ChatDatabaseSummary, DatabaseError> {
        self.with_connection(|connection| chat_database_summary(connection))
    }

    pub fn sanitize_attachment_references(&self) -> Result<i64, DatabaseError> {
        let attachment_dir = self.attachment_dir.clone();
        self.with_connection(|connection| {
            sanitize_database_attachments(connection, &attachment_dir)
        })
    }

    pub fn export_database(
        &self,
        destination: impl AsRef<Path>,
    ) -> Result<ChatDatabaseSummary, DatabaseError> {
        let destination = destination.as_ref().to_path_buf();
        if same_path(&self.path, &destination)? {
            return Err(DatabaseError::InvalidOperation(
                "source and destination are the same file".into(),
            ));
        }
        let parent = destination.parent().unwrap_or_else(|| Path::new("."));
        fs::create_dir_all(parent)?;
        self.with_connection(|connection| {
            validate_chat_database(connection)?;
            let temp = Builder::new()
                .prefix(
                    destination
                        .file_name()
                        .and_then(|name| name.to_str())
                        .unwrap_or("data.db"),
                )
                .suffix(".tmp")
                .tempfile_in(parent)?;
            let temp_path = temp.into_temp_path();
            connection.backup(MAIN_DB, &temp_path, None)?;
            {
                let exported = Connection::open(&temp_path)?;
                exported.pragma_update(None, "journal_mode", "DELETE")?;
            }
            temp_path
                .persist(&destination)
                .map_err(|error| DatabaseError::Io(error.error))?;
            let exported = Connection::open(&destination)?;
            chat_database_summary(&exported)
        })
    }

    pub fn import_database(
        &self,
        source: impl AsRef<Path>,
    ) -> Result<ChatDatabaseSummary, DatabaseError> {
        let source = source.as_ref().to_path_buf();
        if !source.is_file() {
            return Err(DatabaseError::InvalidOperation(format!(
                "source database does not exist: {}",
                source.display()
            )));
        }
        if same_path(&source, &self.path)? {
            return Err(DatabaseError::InvalidOperation(
                "source and destination are the same file".into(),
            ));
        }
        let staging = tempfile::tempdir()?;
        let local_source = staging.path().join(
            source
                .file_name()
                .unwrap_or_else(|| std::ffi::OsStr::new("data.db")),
        );
        fs::copy(&source, &local_source)?;
        for suffix in ["-wal", "-shm"] {
            let source_sidecar = PathBuf::from(format!("{}{suffix}", source.display()));
            if source_sidecar.is_file() {
                fs::copy(
                    &source_sidecar,
                    PathBuf::from(format!("{}{suffix}", local_source.display())),
                )?;
            }
        }
        {
            let source_connection = Connection::open(&local_source)?;
            validate_chat_database(&source_connection)?;
        }
        let attachment_dir = self.attachment_dir.clone();
        self.with_connection(|connection| {
            connection.restore(
                MAIN_DB,
                &local_source,
                None::<fn(rusqlite::backup::Progress)>,
            )?;
            connection.pragma_update(None, "foreign_keys", "ON")?;
            sanitize_database_attachments(connection, &attachment_dir)?;
            validate_chat_database(connection)?;
            let _ = connection.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |_| Ok(()));
            chat_database_summary(connection)
        })
    }

    pub fn export_relationship_data(&self) -> Result<RelationshipData, DatabaseError> {
        self.with_connection(|connection| {
            let relationship_states = {
                let mut statement = connection.prepare(concat!(
                    "SELECT id, character, user_key, affection, trust, familiarity, mood, ",
                    "mood_intensity, summary, updated_at FROM relationship_states ",
                    "ORDER BY character, user_key"
                ))?;
                statement
                    .query_map([], row_to_relationship_state)?
                    .collect::<Result<Vec<_>, _>>()?
            };
            let character_memories = {
                let mut statement = connection.prepare(concat!(
                    "SELECT id, character, user_key, kind, content, importance, source_message_id, ",
                    "source_group_message_id, created_at, updated_at FROM character_memories ",
                    "ORDER BY character, user_key, importance DESC, updated_at DESC, id DESC"
                ))?;
                statement
                    .query_map([], row_to_character_memory)?
                    .collect::<Result<Vec<_>, _>>()?
            };
            Ok(RelationshipData {
                relationship_states,
                character_memories,
            })
        })
    }

    pub fn import_relationship_data(
        &self,
        data: &RelationshipData,
    ) -> Result<RelationshipImportSummary, DatabaseError> {
        self.with_connection(|connection| {
            let transaction = connection.transaction()?;
            let now = now_text(&transaction)?;
            let mut state_count = 0;
            for state in &data.relationship_states {
                let character = state.character.trim();
                if character.is_empty() {
                    continue;
                }
                let imported = RelationshipState {
                    id: 0,
                    character: character.to_owned(),
                    user_key: normalize_user_key(&state.user_key),
                    affection: state.affection.clamp(0, 100),
                    trust: state.trust.clamp(0, 100),
                    familiarity: state.familiarity.clamp(0, 100),
                    mood: nonempty_mood(state.mood.trim().to_owned()),
                    mood_intensity: state.mood_intensity.clamp(0, 100),
                    summary: state.summary.clone(),
                    updated_at: if state.updated_at.is_empty() {
                        now.clone()
                    } else {
                        state.updated_at.clone()
                    },
                };
                write_relationship_state(&transaction, &imported)?;
                state_count += 1;
            }

            let mut memory_count = 0;
            for memory in &data.character_memories {
                let character = memory.character.trim();
                let content = memory.content.trim();
                if character.is_empty() || content.is_empty() {
                    continue;
                }
                let created_at = if memory.created_at.is_empty() {
                    now.clone()
                } else {
                    memory.created_at.clone()
                };
                let updated_at = if memory.updated_at.is_empty() {
                    created_at.clone()
                } else {
                    memory.updated_at.clone()
                };
                transaction.execute(
                    concat!(
                        "INSERT INTO character_memories ",
                        "(character, user_key, kind, content, importance, source_message_id, ",
                        "source_group_message_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ",
                        "ON CONFLICT(character, user_key, content) DO UPDATE SET ",
                        "kind=excluded.kind, importance=excluded.importance, ",
                        "source_message_id=coalesce(excluded.source_message_id, character_memories.source_message_id), ",
                        "source_group_message_id=coalesce(excluded.source_group_message_id, character_memories.source_group_message_id), ",
                        "updated_at=excluded.updated_at"
                    ),
                    params![
                        character,
                        normalize_user_key(&memory.user_key),
                        if memory.kind.trim().is_empty() {
                            "note"
                        } else {
                            memory.kind.trim()
                        },
                        content,
                        memory.importance.clamp(1, 100),
                        memory.source_message_id,
                        memory.source_group_message_id,
                        created_at,
                        updated_at,
                    ],
                )?;
                memory_count += 1;
            }
            transaction.commit()?;
            Ok(RelationshipImportSummary {
                relationship_states: state_count,
                character_memories: memory_count,
            })
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

fn first_event_value<'a>(event: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a Value> {
    keys.iter()
        .find_map(|key| event.get(*key).filter(|value| json_truthy(value)))
}

fn clean_external_text(value: Option<&Value>, default: &str, limit: usize) -> String {
    let text = match value {
        Some(Value::String(value)) => value.clone(),
        Some(Value::Bool(value)) => {
            if *value {
                "True".into()
            } else {
                "False".into()
            }
        }
        Some(Value::Number(value)) => value.to_string(),
        Some(Value::Array(value)) => serde_json::to_string(value).unwrap_or_default(),
        Some(Value::Object(value)) => serde_json::to_string(value).unwrap_or_default(),
        Some(Value::Null) | None => default.to_owned(),
    };
    truncate_chars(text.trim(), limit)
}

fn external_thread_summary(
    connection: &Connection,
    platform: &str,
    thread_id: &str,
) -> Result<ExternalThreadSummary, DatabaseError> {
    let summary = connection
        .query_row(
            concat!(
                "SELECT platform, thread_id, thread_name, unread_count, last_message_at ",
                "FROM external_chat_threads WHERE platform=? AND thread_id=?"
            ),
            params![platform, thread_id],
            |row| {
                let row_platform = row.get::<_, Option<String>>(0)?.unwrap_or_default();
                let row_thread_id = row.get::<_, Option<String>>(1)?.unwrap_or_default();
                let thread_name = row.get::<_, Option<String>>(2)?.unwrap_or_default();
                Ok(ExternalThreadSummary {
                    platform: if row_platform.is_empty() {
                        "external".into()
                    } else {
                        row_platform
                    },
                    thread_id: if row_thread_id.is_empty() {
                        "default".into()
                    } else {
                        row_thread_id.clone()
                    },
                    thread_name: if thread_name.is_empty() {
                        if row_thread_id.is_empty() {
                            "default".into()
                        } else {
                            row_thread_id
                        }
                    } else {
                        thread_name
                    },
                    unread_count: row.get::<_, Option<i64>>(3)?.unwrap_or(0),
                    last_message_at: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                })
            },
        )
        .optional()?;
    Ok(summary.unwrap_or_else(|| ExternalThreadSummary {
        platform: platform.to_owned(),
        thread_id: thread_id.to_owned(),
        thread_name: thread_id.to_owned(),
        unread_count: 0,
        last_message_at: String::new(),
    }))
}

fn row_to_external_message(row: &rusqlite::Row<'_>) -> rusqlite::Result<ExternalChatMessage> {
    let platform = row.get::<_, Option<String>>(1)?.unwrap_or_default();
    let thread_id = row.get::<_, Option<String>>(2)?.unwrap_or_default();
    let direction = row.get::<_, Option<String>>(6)?.unwrap_or_default();
    Ok(ExternalChatMessage {
        id: row.get::<_, Option<i64>>(0)?.unwrap_or(0),
        platform: if platform.is_empty() {
            "external".into()
        } else {
            platform
        },
        thread_id: if thread_id.is_empty() {
            "default".into()
        } else {
            thread_id
        },
        external_message_id: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
        sender_id: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
        sender_name: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
        direction: if direction.is_empty() {
            "inbound".into()
        } else {
            direction
        },
        content: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
        unread: row.get::<_, Option<i64>>(8)?.unwrap_or(0) != 0,
        raw_json: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
        created_at: row.get::<_, Option<String>>(10)?.unwrap_or_default(),
    })
}

fn external_unread_summary(
    connection: &Connection,
    limit_threads: i64,
    limit_messages: i64,
) -> Result<ExternalUnreadSummary, DatabaseError> {
    let limit_threads = limit_threads.clamp(1, 20);
    let limit_messages = limit_messages.clamp(1, 10);
    let total_unread = connection
        .query_row(
            "SELECT COALESCE(SUM(unread_count),0) FROM external_chat_threads",
            [],
            |row| row.get::<_, Option<i64>>(0),
        )?
        .unwrap_or(0);
    let thread_rows = {
        let mut statement = connection.prepare(concat!(
            "SELECT platform, thread_id, thread_name, unread_count, last_message_at ",
            "FROM external_chat_threads WHERE unread_count > 0 ",
            "ORDER BY last_message_at DESC, updated_at DESC LIMIT ?"
        ))?;
        statement
            .query_map(params![limit_threads], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, i64>(3)?,
                    row.get::<_, String>(4)?,
                ))
            })?
            .collect::<Result<Vec<_>, _>>()?
    };

    let mut threads = Vec::new();
    for (platform, thread_id, thread_name, unread_count, last_message_at) in thread_rows {
        let mut statement = connection.prepare(concat!(
            "SELECT id, platform, thread_id, external_message_id, sender_id, sender_name, ",
            "direction, content, unread, raw_json, created_at FROM external_chat_messages ",
            "WHERE platform=? AND thread_id=? AND unread=1 ORDER BY id DESC LIMIT ?"
        ))?;
        let mut messages = statement
            .query_map(
                params![platform, thread_id, limit_messages],
                row_to_external_message,
            )?
            .collect::<Result<Vec<_>, _>>()?;
        messages.reverse();
        threads.push(ExternalUnreadThread {
            platform,
            thread_id: thread_id.clone(),
            thread_name: if thread_name.is_empty() {
                thread_id
            } else {
                thread_name
            },
            unread_count,
            last_message_at,
            messages,
        });
    }
    Ok(ExternalUnreadSummary {
        total_unread,
        threads,
    })
}

fn external_context_text(
    connection: &Connection,
    limit_threads: i64,
    limit_messages: i64,
) -> Result<String, DatabaseError> {
    let limit_threads = limit_threads.clamp(1, 12);
    let limit_messages = limit_messages.clamp(1, 20);
    let rows = {
        let mut statement = connection.prepare(concat!(
            "SELECT platform, thread_id, thread_name, unread_count, last_message_at ",
            "FROM external_chat_threads ORDER BY last_message_at DESC, updated_at DESC LIMIT ?"
        ))?;
        statement
            .query_map(params![limit_threads], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, i64>(3)?,
                ))
            })?
            .collect::<Result<Vec<_>, _>>()?
    };
    if rows.is_empty() {
        return Ok(String::new());
    }
    let mut lines = vec![
        "【外部聊天软件上下文】".to_owned(),
        "以下是 BandoriPet 最近从外部聊天软件收到的消息。可以用于理解用户当前可能在处理的对话；除非用户要求代写或总结，不要主动暴露隐私细节。".to_owned(),
    ];
    for (platform, thread_id, thread_name, unread_count) in rows {
        let thread_name = if thread_name.is_empty() {
            thread_id.clone()
        } else {
            thread_name
        };
        lines.push(format!(
            "[{platform} / {thread_name} / 未读 {unread_count}]"
        ));
        let mut statement = connection.prepare(concat!(
            "SELECT id, platform, thread_id, external_message_id, sender_id, sender_name, ",
            "direction, content, unread, raw_json, created_at FROM external_chat_messages ",
            "WHERE platform=? AND thread_id=? ORDER BY id DESC LIMIT ?"
        ))?;
        let mut messages = statement
            .query_map(
                params![platform, thread_id, limit_messages],
                row_to_external_message,
            )?
            .collect::<Result<Vec<_>, _>>()?;
        messages.reverse();
        for message in messages {
            let sender = if !message.sender_name.is_empty() {
                message.sender_name
            } else if !message.sender_id.is_empty() {
                message.sender_id
            } else {
                "unknown".into()
            };
            let content = message.content.replace(['\r', '\n'], " ").trim().to_owned();
            let content = if content.chars().count() > 500 {
                format!("{}...", truncate_chars(&content, 500))
            } else {
                content
            };
            let marker = if message.unread { "未读" } else { "已读" };
            lines.push(format!(
                "- {} {}（{}）：{}",
                message.created_at, sender, marker, content
            ));
        }
    }
    Ok(lines.join("\n"))
}

fn resync_external_chat_threads(connection: &Connection) -> Result<(), DatabaseError> {
    connection.execute(
        concat!(
            "DELETE FROM external_chat_threads WHERE NOT EXISTS (",
            "SELECT 1 FROM external_chat_messages m WHERE ",
            "m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id)"
        ),
        [],
    )?;
    let now = now_text(connection)?;
    connection.execute(
        concat!(
            "UPDATE external_chat_threads SET ",
            "unread_count=(SELECT COUNT(*) FROM external_chat_messages m WHERE ",
            "m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id AND m.unread=1), ",
            "last_message_id=(SELECT MAX(m.id) FROM external_chat_messages m WHERE ",
            "m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id), ",
            "last_message_at=(SELECT m.created_at FROM external_chat_messages m WHERE ",
            "m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id ",
            "ORDER BY m.id DESC LIMIT 1), updated_at=?"
        ),
        params![now],
    )?;
    Ok(())
}

fn prune_external_group_thread_messages(
    connection: &Connection,
    platform: &str,
    thread_id: &str,
) -> Result<i64, DatabaseError> {
    let deleted = connection.execute(
        concat!(
            "DELETE FROM external_chat_messages WHERE platform=? AND thread_id=? ",
            "AND chat_type='group' AND id NOT IN (SELECT id FROM external_chat_messages ",
            "WHERE platform=? AND thread_id=? AND chat_type='group' ORDER BY id DESC LIMIT ?)"
        ),
        params![
            platform,
            thread_id,
            platform,
            thread_id,
            EXTERNAL_GROUP_CHAT_MESSAGE_LIMIT,
        ],
    )? as i64;
    if deleted != 0 {
        resync_external_chat_threads(connection)?;
    }
    Ok(deleted)
}

fn group_key_characters(group_key: &str) -> Vec<String> {
    group_key
        .strip_prefix("__group__:")
        .map(|members| {
            members
                .split('|')
                .filter(|member| !member.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

fn row_to_chat_history_record(row: &rusqlite::Row<'_>) -> rusqlite::Result<ChatHistoryRecord> {
    Ok(ChatHistoryRecord {
        source: row.get::<_, Option<String>>(0)?.unwrap_or_default(),
        id: row.get::<_, Option<i64>>(1)?.unwrap_or(0),
        conversation_id: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
        character: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
        group_key: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
        chat_title: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
        user_key: row.get::<_, Option<String>>(6)?.unwrap_or_default(),
        role: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
        content: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
        created_at: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
    })
}

fn row_to_group_conversation(
    row: &rusqlite::Row<'_>,
    fixed_group_key: &str,
    includes_group_key: bool,
) -> rusqlite::Result<GroupConversation> {
    let base = usize::from(includes_group_key);
    let group_key = if includes_group_key {
        row.get::<_, Option<String>>(0)?.unwrap_or_default()
    } else {
        fixed_group_key.to_owned()
    };
    let conversation_id = row
        .get::<_, Option<String>>(base)?
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "default".into());
    Ok(GroupConversation {
        group_key,
        conversation_id,
        user_key: row.get::<_, Option<String>>(base + 1)?.unwrap_or_default(),
        message_id: row.get::<_, Option<i64>>(base + 2)?.unwrap_or(0),
        role: row
            .get::<_, Option<String>>(base + 3)?
            .unwrap_or_default()
            .trim()
            .to_owned(),
        content: row.get::<_, Option<String>>(base + 4)?.unwrap_or_default(),
        created_at: row.get::<_, Option<String>>(base + 5)?.unwrap_or_default(),
    })
}

fn table_count(connection: &Connection, table: &str) -> Result<i64, DatabaseError> {
    connection
        .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
            row.get(0)
        })
        .map_err(DatabaseError::from)
}

fn daily_counts_for_source(
    connection: &Connection,
    private: bool,
    modifier: &str,
    user_key: Option<&str>,
) -> Result<Vec<(String, i64)>, DatabaseError> {
    let mut sql = if private {
        concat!(
            "SELECT date(m.created_at), COUNT(*) FROM messages m ",
            "JOIN conversations c ON c.id=m.conversation_id ",
            "WHERE m.created_at>=datetime('now','localtime',?) "
        )
        .to_owned()
    } else {
        concat!(
            "SELECT date(created_at), COUNT(*) FROM group_messages ",
            "WHERE created_at>=datetime('now','localtime',?) "
        )
        .to_owned()
    };
    let mut values = vec![SqlValue::Text(modifier.to_owned())];
    if let Some(user_key) = user_key {
        sql.push_str(if private {
            "AND c.user_key=? "
        } else {
            "AND user_key=? "
        });
        values.push(SqlValue::Text(normalize_user_key(user_key)));
    }
    sql.push_str(if private {
        "GROUP BY date(m.created_at)"
    } else {
        "GROUP BY date(created_at)"
    });
    let mut statement = connection.prepare(&sql)?;
    statement
        .query_map(params_from_iter(values), |row| {
            Ok((
                row.get::<_, Option<String>>(0)?.unwrap_or_default(),
                row.get::<_, Option<i64>>(1)?.unwrap_or(0),
            ))
        })?
        .collect::<Result<Vec<_>, _>>()
        .map_err(DatabaseError::from)
}

fn hourly_counts(
    connection: &Connection,
    private: bool,
    modifier: &str,
    user_key: Option<&str>,
) -> Result<Vec<(i64, i64, i64)>, DatabaseError> {
    let mut sql = if private {
        concat!(
            "SELECT CAST(strftime('%w',m.created_at) AS INTEGER), ",
            "CAST(strftime('%H',m.created_at) AS INTEGER), COUNT(*) FROM messages m ",
            "JOIN conversations c ON c.id=m.conversation_id ",
            "WHERE m.created_at>=datetime('now','localtime',?) "
        )
        .to_owned()
    } else {
        concat!(
            "SELECT CAST(strftime('%w',created_at) AS INTEGER), ",
            "CAST(strftime('%H',created_at) AS INTEGER), COUNT(*) FROM group_messages ",
            "WHERE created_at>=datetime('now','localtime',?) "
        )
        .to_owned()
    };
    let mut values = vec![SqlValue::Text(modifier.to_owned())];
    if let Some(user_key) = user_key {
        sql.push_str(if private {
            "AND c.user_key=? "
        } else {
            "AND user_key=? "
        });
        values.push(SqlValue::Text(normalize_user_key(user_key)));
    }
    sql.push_str("GROUP BY 1, 2");
    let mut statement = connection.prepare(&sql)?;
    statement
        .query_map(params_from_iter(values), |row| {
            Ok((row.get(0)?, row.get(1)?, row.get(2)?))
        })?
        .collect::<Result<Vec<_>, _>>()
        .map_err(DatabaseError::from)
}

fn row_to_relationship_state(row: &rusqlite::Row<'_>) -> rusqlite::Result<RelationshipState> {
    Ok(RelationshipState {
        id: row.get::<_, Option<i64>>(0)?.unwrap_or(0),
        character: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
        user_key: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
        affection: row.get::<_, Option<i64>>(3)?.unwrap_or(50),
        trust: row.get::<_, Option<i64>>(4)?.unwrap_or(50),
        familiarity: row.get::<_, Option<i64>>(5)?.unwrap_or(0),
        mood: nonempty_mood(row.get::<_, Option<String>>(6)?.unwrap_or_default()),
        mood_intensity: row.get::<_, Option<i64>>(7)?.unwrap_or(20),
        summary: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
        updated_at: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
    })
}

fn chat_database_summary(connection: &Connection) -> Result<ChatDatabaseSummary, DatabaseError> {
    validate_chat_database(connection)?;
    Ok(ChatDatabaseSummary {
        conversations: table_count(connection, "conversations")?,
        messages: table_count(connection, "messages")?,
        group_messages: table_count(connection, "group_messages")?,
    })
}

fn validate_chat_database(connection: &Connection) -> Result<(), DatabaseError> {
    let tables = {
        let mut statement =
            connection.prepare("SELECT name FROM sqlite_master WHERE type='table'")?;
        statement
            .query_map([], |row| row.get::<_, String>(0))?
            .collect::<Result<BTreeSet<_>, _>>()?
    };
    for table in ["conversations", "messages", "group_messages"] {
        if !tables.contains(table) {
            return Err(DatabaseError::InvalidOperation(format!(
                "missing table: {table}"
            )));
        }
    }
    let requirements = [
        (
            "conversations",
            ["id", "character", "title", "created_at"].as_slice(),
        ),
        (
            "messages",
            ["id", "conversation_id", "role", "content", "created_at"].as_slice(),
        ),
        (
            "group_messages",
            [
                "id",
                "group_key",
                "conversation_id",
                "role",
                "content",
                "created_at",
            ]
            .as_slice(),
        ),
    ];
    for (table, required) in requirements {
        let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
        let columns = statement
            .query_map([], |row| row.get::<_, String>(1))?
            .collect::<Result<BTreeSet<_>, _>>()?;
        for column in required {
            if !columns.contains(*column) {
                return Err(DatabaseError::InvalidOperation(format!(
                    "table {table} missing column: {column}"
                )));
            }
        }
    }
    Ok(())
}

fn sanitize_database_attachments(
    connection: &Connection,
    attachment_dir: &Path,
) -> Result<i64, DatabaseError> {
    let mut removed = 0;
    for table in ["messages", "group_messages"] {
        let rows = {
            let mut statement = connection.prepare(&format!(
                "SELECT id, attachments_json FROM {table} WHERE attachments_json != ''"
            ))?;
            statement
                .query_map([], |row| {
                    Ok((
                        row.get::<_, i64>(0)?,
                        row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    ))
                })?
                .collect::<Result<Vec<_>, _>>()?
        };
        for (id, raw) in rows {
            let original = serde_json::from_str::<Value>(&raw).unwrap_or(Value::Array(Vec::new()));
            let cleaned = sanitize_attachments(Some(&original), attachment_dir);
            if let Some(original) = original.as_array() {
                let cleaned_len = cleaned.as_array().map_or(0, Vec::len);
                removed += original.len().saturating_sub(cleaned_len) as i64;
            }
            connection.execute(
                &format!("UPDATE {table} SET attachments_json=? WHERE id=?"),
                params![json_text(Some(&cleaned))?, id],
            )?;
        }
    }
    Ok(removed)
}

fn same_path(left: &Path, right: &Path) -> Result<bool, DatabaseError> {
    fn normalized(path: &Path) -> io::Result<PathBuf> {
        if path.exists() {
            return dunce::canonicalize(path);
        }
        let parent = path.parent().unwrap_or_else(|| Path::new("."));
        Ok(dunce::canonicalize(parent)?.join(
            path.file_name()
                .unwrap_or_else(|| std::ffi::OsStr::new("data.db")),
        ))
    }
    let left = normalized(left)?;
    let right = normalized(right)?;
    if cfg!(windows) {
        Ok(left.to_string_lossy().to_lowercase() == right.to_string_lossy().to_lowercase())
    } else {
        Ok(left == right)
    }
}

fn group_message_speaker(content: &str) -> String {
    let first_line = content.lines().next().unwrap_or_default().trim();
    first_line
        .strip_prefix('【')
        .and_then(|value| value.split_once('】').map(|(speaker, _)| speaker.trim()))
        .unwrap_or_default()
        .to_owned()
}

fn character_alias_set(character: &str, aliases: &[String]) -> BTreeSet<String> {
    let mut result = BTreeSet::new();
    if !character.trim().is_empty() {
        result.insert(character.trim().to_owned());
    }
    result.extend(
        aliases
            .iter()
            .map(|alias| alias.trim())
            .filter(|alias| !alias.is_empty())
            .map(str::to_owned),
    );
    result
}

fn group_message_matches_character(role: &str, content: &str, aliases: &BTreeSet<String>) -> bool {
    if role != "assistant" {
        return true;
    }
    let speaker = group_message_speaker(content);
    speaker.is_empty() || aliases.contains(&speaker)
}

fn group_message_count_characters(
    group_key: &str,
    role: &str,
    content: &str,
    display_aliases: &BTreeMap<String, Vec<String>>,
) -> Vec<String> {
    let members = group_key_characters(group_key);
    if members.is_empty() || role != "assistant" {
        return members;
    }
    let speaker = group_message_speaker(content);
    if speaker.is_empty() {
        return members;
    }
    let matched = members
        .iter()
        .filter(|character| {
            let aliases = display_aliases
                .get(*character)
                .map(Vec::as_slice)
                .unwrap_or_default();
            character_alias_set(character, aliases).contains(&speaker)
        })
        .cloned()
        .collect::<Vec<_>>();
    if matched.is_empty() { members } else { matched }
}

fn character_recent_messages(
    connection: &Connection,
    character: &str,
    user_key: &str,
    limit: i64,
    character_aliases: &[String],
) -> Result<Vec<AlbumMessage>, DatabaseError> {
    let limit = limit.clamp(1, 200);
    let aliases = character_alias_set(character, character_aliases);
    let mut messages = {
        let mut statement = connection.prepare(concat!(
            "SELECT m.id, m.conversation_id, m.role, m.content, m.reasoning_content, ",
            "m.attachments_json, m.tool_trace_json, m.created_at FROM conversations c ",
            "JOIN messages m ON m.conversation_id=c.id WHERE c.character=? AND c.user_key=? ",
            "ORDER BY m.id DESC LIMIT ?"
        ))?;
        statement
            .query_map(params![character, user_key, limit], |row| {
                Ok(AlbumMessage {
                    id: row.get(0)?,
                    source: "private".into(),
                    conversation_id: Value::Number(row.get::<_, i64>(1)?.into()),
                    group_key: String::new(),
                    role: row.get(2)?,
                    content: row.get(3)?,
                    reasoning_content: row.get(4)?,
                    attachments_json: row.get(5)?,
                    tool_trace_json: row.get(6)?,
                    created_at: row.get(7)?,
                    speaker: String::new(),
                })
            })?
            .collect::<Result<Vec<_>, _>>()?
    };

    let group_limit = (limit * 8).clamp(120, 1000);
    let group_rows = {
        let mut statement = connection.prepare(concat!(
            "SELECT id, group_key, conversation_id, role, content, reasoning_content, ",
            "attachments_json, tool_trace_json, created_at FROM group_messages ",
            "WHERE user_key=? AND group_key LIKE '__group__:%' ORDER BY id DESC LIMIT ?"
        ))?;
        statement
            .query_map(params![user_key, group_limit], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, String>(4)?,
                    row.get::<_, String>(5)?,
                    row.get::<_, String>(6)?,
                    row.get::<_, String>(7)?,
                    row.get::<_, String>(8)?,
                ))
            })?
            .collect::<Result<Vec<_>, _>>()?
    };
    for row in group_rows {
        if !group_key_characters(&row.1)
            .iter()
            .any(|member| member == character)
            || !group_message_matches_character(&row.3, &row.4, &aliases)
        {
            continue;
        }
        let speaker = if row.3 == "assistant" {
            group_message_speaker(&row.4)
        } else {
            String::new()
        };
        messages.push(AlbumMessage {
            id: row.0,
            source: "group".into(),
            conversation_id: Value::String(if row.2.is_empty() {
                "default".into()
            } else {
                row.2
            }),
            group_key: row.1,
            role: row.3,
            content: row.4,
            reasoning_content: row.5,
            attachments_json: row.6,
            tool_trace_json: row.7,
            created_at: row.8,
            speaker,
        });
    }
    messages.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| right.id.cmp(&left.id))
    });
    messages.truncate(limit as usize);
    messages.reverse();
    Ok(messages)
}

fn group_conversation_album_preview(
    connection: &Connection,
    group_key: &str,
    conversation_id: &str,
    user_key: &str,
    aliases: &BTreeSet<String>,
) -> Result<(String, i64), DatabaseError> {
    let rows = {
        let mut statement = connection.prepare(concat!(
            "SELECT role, content FROM group_messages WHERE group_key=? ",
            "AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) ",
            "AND user_key=? ORDER BY id DESC"
        ))?;
        statement
            .query_map(
                params![group_key, conversation_id, conversation_id, user_key],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )?
            .collect::<Result<Vec<_>, _>>()?
    };
    let mut preview = String::new();
    let mut count = 0;
    for (role, content) in rows {
        if !group_message_matches_character(&role, &content, aliases) {
            continue;
        }
        count += 1;
        if preview.is_empty() {
            preview = content;
        }
    }
    Ok((preview, count))
}

fn character_conversation_chain(
    connection: &Connection,
    character: &str,
    user_key: &str,
    limit: i64,
    character_aliases: &[String],
) -> Result<Vec<ConversationChainItem>, DatabaseError> {
    let limit = limit.clamp(1, 100);
    let aliases = character_alias_set(character, character_aliases);
    let mut result = {
        let mut statement = connection.prepare(concat!(
            "SELECT c.id, c.user_key, c.title, c.created_at, MIN(m.created_at), MAX(m.created_at), ",
            "COUNT(m.id), (SELECT content FROM messages WHERE conversation_id=c.id AND role='user' ",
            "AND content!='' ORDER BY id ASC LIMIT 1), (SELECT content FROM messages ",
            "WHERE conversation_id=c.id AND content!='' ORDER BY id DESC LIMIT 1) ",
            "FROM conversations c JOIN messages m ON m.conversation_id=c.id ",
            "WHERE c.character=? AND c.user_key=? GROUP BY c.id, c.user_key, c.title, c.created_at ",
            "ORDER BY MAX(m.id) DESC LIMIT ?"
        ))?;
        statement
            .query_map(params![character, user_key, limit], |row| {
                Ok(ConversationChainItem {
                    source: "private".into(),
                    conversation_id: Value::Number(row.get::<_, i64>(0)?.into()),
                    group_key: String::new(),
                    user_key: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    title: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    created_at: row.get::<_, Option<String>>(3)?.unwrap_or_default(),
                    first_message_at: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
                    last_message_at: row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                    message_count: row.get::<_, Option<i64>>(6)?.unwrap_or(0),
                    first_user: row.get::<_, Option<String>>(7)?.unwrap_or_default(),
                    preview: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                })
            })?
            .collect::<Result<Vec<_>, _>>()?
    };

    let group_limit = (limit * 6).clamp(60, 300);
    let group_rows = {
        let mut statement = connection.prepare(concat!(
            "SELECT group_key, conversation_id, MIN(created_at), MAX(created_at), COUNT(id), ",
            "(SELECT content FROM group_messages gm2 WHERE gm2.group_key=gm.group_key ",
            "AND gm2.conversation_id=gm.conversation_id AND gm2.user_key=gm.user_key ",
            "AND gm2.role='user' AND gm2.content!='' ORDER BY gm2.id ASC LIMIT 1), ",
            "(SELECT content FROM group_messages gm2 WHERE gm2.group_key=gm.group_key ",
            "AND gm2.conversation_id=gm.conversation_id AND gm2.user_key=gm.user_key ",
            "AND gm2.content!='' ORDER BY gm2.id DESC LIMIT 1) FROM group_messages gm ",
            "WHERE gm.user_key=? AND gm.group_key LIKE '__group__:%' ",
            "GROUP BY group_key, conversation_id, user_key ORDER BY MAX(id) DESC LIMIT ?"
        ))?;
        statement
            .query_map(params![user_key, group_limit], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, String>(3)?,
                    row.get::<_, i64>(4)?,
                    row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                    row.get::<_, Option<String>>(6)?.unwrap_or_default(),
                ))
            })?
            .collect::<Result<Vec<_>, _>>()?
    };
    for row in group_rows {
        if !group_key_characters(&row.0)
            .iter()
            .any(|member| member == character)
        {
            continue;
        }
        let conversation_id = if row.1.is_empty() { "default" } else { &row.1 };
        let (preview, message_count) = group_conversation_album_preview(
            connection,
            &row.0,
            conversation_id,
            user_key,
            &aliases,
        )?;
        result.push(ConversationChainItem {
            source: "group".into(),
            conversation_id: Value::String(conversation_id.to_owned()),
            group_key: row.0,
            user_key: user_key.to_owned(),
            title: String::new(),
            created_at: row.2.clone(),
            first_message_at: row.2,
            last_message_at: row.3,
            message_count: if message_count == 0 {
                row.4
            } else {
                message_count
            },
            first_user: row.5,
            preview: if preview.is_empty() { row.6 } else { preview },
        });
    }
    result.sort_by(|left, right| right.last_message_at.cmp(&left.last_message_at));
    result.truncate(limit as usize);
    Ok(result)
}

fn character_memories_from_connection(
    connection: &Connection,
    character: &str,
    user_key: &str,
    kind: &str,
    limit: i64,
) -> Result<Vec<CharacterMemory>, DatabaseError> {
    let (sql, values) = if kind.is_empty() {
        (
            concat!(
                "SELECT id, character, user_key, kind, content, importance, source_message_id, ",
                "source_group_message_id, created_at, updated_at FROM character_memories ",
                "WHERE character=? AND user_key=? ",
                "ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?"
            ),
            vec![
                SqlValue::Text(character.to_owned()),
                SqlValue::Text(user_key.to_owned()),
                SqlValue::Integer(limit.clamp(1, 100)),
            ],
        )
    } else {
        (
            concat!(
                "SELECT id, character, user_key, kind, content, importance, source_message_id, ",
                "source_group_message_id, created_at, updated_at FROM character_memories ",
                "WHERE character=? AND user_key=? AND kind=? ",
                "ORDER BY updated_at DESC, id DESC LIMIT ?"
            ),
            vec![
                SqlValue::Text(character.to_owned()),
                SqlValue::Text(user_key.to_owned()),
                SqlValue::Text(kind.to_owned()),
                SqlValue::Integer(limit.clamp(1, 200)),
            ],
        )
    };
    let mut statement = connection.prepare(sql)?;
    statement
        .query_map(params_from_iter(values), row_to_character_memory)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(DatabaseError::from)
}

fn collapse_whitespace(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn relationship_state_from_connection(
    connection: &Connection,
    character: &str,
    user_key: &str,
) -> Result<RelationshipState, DatabaseError> {
    connection
        .query_row(
            concat!(
                "SELECT id, character, user_key, affection, trust, familiarity, mood, ",
                "mood_intensity, summary, updated_at FROM relationship_states ",
                "WHERE character=? AND user_key=?"
            ),
            params![character, user_key],
            |row| {
                Ok(RelationshipState {
                    id: row.get(0)?,
                    character: row.get(1)?,
                    user_key: row.get(2)?,
                    affection: row.get::<_, Option<i64>>(3)?.unwrap_or(50),
                    trust: row.get::<_, Option<i64>>(4)?.unwrap_or(50),
                    familiarity: row.get::<_, Option<i64>>(5)?.unwrap_or(0),
                    mood: nonempty_mood(row.get::<_, Option<String>>(6)?.unwrap_or_default()),
                    mood_intensity: row.get::<_, Option<i64>>(7)?.unwrap_or(20),
                    summary: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
                    updated_at: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
                })
            },
        )
        .optional()?
        .map_or_else(
            || {
                Ok(RelationshipState {
                    id: 0,
                    character: character.to_owned(),
                    user_key: user_key.to_owned(),
                    affection: 50,
                    trust: 50,
                    familiarity: 0,
                    mood: "calm".into(),
                    mood_intensity: 20,
                    summary: String::new(),
                    updated_at: String::new(),
                })
            },
            Ok,
        )
}

fn write_relationship_state(
    connection: &Connection,
    state: &RelationshipState,
) -> Result<(), DatabaseError> {
    connection.execute(
        concat!(
            "INSERT INTO relationship_states ",
            "(character, user_key, affection, trust, familiarity, mood, mood_intensity, summary, updated_at) ",
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ",
            "ON CONFLICT(character, user_key) DO UPDATE SET ",
            "affection=excluded.affection, trust=excluded.trust, familiarity=excluded.familiarity, ",
            "mood=excluded.mood, mood_intensity=excluded.mood_intensity, summary=excluded.summary, ",
            "updated_at=excluded.updated_at"
        ),
        params![
            state.character,
            state.user_key,
            state.affection,
            state.trust,
            state.familiarity,
            state.mood,
            state.mood_intensity,
            state.summary,
            state.updated_at,
        ],
    )?;
    Ok(())
}

fn row_to_character_memory(row: &rusqlite::Row<'_>) -> rusqlite::Result<CharacterMemory> {
    Ok(CharacterMemory {
        id: row.get::<_, Option<i64>>(0)?.unwrap_or(0),
        character: row.get::<_, Option<String>>(1)?.unwrap_or_default(),
        user_key: row.get::<_, Option<String>>(2)?.unwrap_or_default(),
        kind: row
            .get::<_, Option<String>>(3)?
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "note".into()),
        content: row.get::<_, Option<String>>(4)?.unwrap_or_default(),
        importance: row.get::<_, Option<i64>>(5)?.unwrap_or(0),
        source_message_id: row.get(6)?,
        source_group_message_id: row.get(7)?,
        created_at: row.get::<_, Option<String>>(8)?.unwrap_or_default(),
        updated_at: row.get::<_, Option<String>>(9)?.unwrap_or_default(),
    })
}

fn now_text(connection: &Connection) -> Result<String, DatabaseError> {
    connection
        .query_row("SELECT datetime('now','localtime')", [], |row| row.get(0))
        .map_err(DatabaseError::from)
}

fn nonempty_mood(mood: String) -> String {
    if mood.is_empty() { "calm".into() } else { mood }
}

fn escape_like(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('%', "\\%")
        .replace('_', "\\_")
}

fn mood_events_for_chart(
    connection: &Connection,
    character: &str,
    user_key: &str,
    days: i64,
) -> Result<Vec<MoodChartPoint>, DatabaseError> {
    let rows = if days <= 0 {
        let mut statement = connection.prepare(concat!(
            "SELECT created_at, affection_delta, trust_delta, familiarity_delta, ",
            "affection, trust, familiarity FROM mood_events ",
            "WHERE character=? AND user_key=? ORDER BY created_at ASC, id ASC"
        ))?;
        statement
            .query_map(params![character, user_key], row_to_mood_chart_source)?
            .collect::<Result<Vec<MoodChartSource>, _>>()?
    } else {
        let mut statement = connection.prepare(concat!(
            "SELECT created_at, affection_delta, trust_delta, familiarity_delta, ",
            "affection, trust, familiarity FROM mood_events ",
            "WHERE character=? AND user_key=? AND created_at>=datetime('now','localtime',?) ",
            "ORDER BY created_at ASC, id ASC"
        ))?;
        statement
            .query_map(
                params![character, user_key, format!("-{days} days")],
                row_to_mood_chart_source,
            )?
            .collect::<Result<Vec<MoodChartSource>, _>>()?
    };
    let state = relationship_state_from_connection(connection, character, user_key)?;
    if rows.is_empty() {
        let today = connection.query_row("SELECT date('now','localtime')", [], |row| row.get(0))?;
        return Ok(vec![MoodChartPoint {
            day: today,
            affection: state.affection,
            trust: state.trust,
            familiarity: state.familiarity,
        }]);
    }
    let Some(first_snapshot) = rows
        .iter()
        .position(|row| row.4.is_some() && row.5.is_some() && row.6.is_some())
    else {
        let day = if state.updated_at.is_empty() {
            connection.query_row("SELECT date('now','localtime')", [], |row| row.get(0))?
        } else {
            state.updated_at.clone()
        };
        return Ok(vec![MoodChartPoint {
            day,
            affection: state.affection,
            trust: state.trust,
            familiarity: state.familiarity,
        }]);
    };

    let mut result = Vec::new();
    let (mut affection, mut trust, mut familiarity) = (0, 0, 0);
    for row in &rows[first_snapshot..] {
        if let (Some(next_affection), Some(next_trust), Some(next_familiarity)) =
            (row.4, row.5, row.6)
        {
            affection = next_affection.clamp(0, 100);
            trust = next_trust.clamp(0, 100);
            familiarity = next_familiarity.clamp(0, 100);
        } else {
            affection = (affection + row.1).clamp(0, 100);
            trust = (trust + row.2).clamp(0, 100);
            familiarity = (familiarity + row.3).clamp(0, 100);
        }
        result.push(MoodChartPoint {
            day: row.0.clone(),
            affection,
            trust,
            familiarity,
        });
    }
    if let Some(last) = result.last() {
        let append_current = !state.updated_at.is_empty()
            && state.updated_at.as_str() >= last.day.as_str()
            && (state.updated_at != last.day
                || state.affection != last.affection
                || state.trust != last.trust
                || state.familiarity != last.familiarity);
        if append_current {
            result.push(MoodChartPoint {
                day: state.updated_at,
                affection: state.affection,
                trust: state.trust,
                familiarity: state.familiarity,
            });
        }
    }
    Ok(result)
}

fn row_to_mood_chart_source(row: &rusqlite::Row<'_>) -> rusqlite::Result<MoodChartSource> {
    Ok((
        row.get(0)?,
        row.get::<_, Option<i64>>(1)?.unwrap_or(0),
        row.get::<_, Option<i64>>(2)?.unwrap_or(0),
        row.get::<_, Option<i64>>(3)?.unwrap_or(0),
        row.get(4)?,
        row.get(5)?,
        row.get(6)?,
    ))
}

fn usage_total(connection: &Connection, predicate: &str) -> Result<i64, DatabaseError> {
    let total = connection.query_row(
        &format!("SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions WHERE {predicate}"),
        [],
        |row| row.get::<_, i64>(0),
    )?;
    let current = connection
        .query_row(
            &format!(
                "SELECT id, COALESCE(duration_seconds,0) FROM usage_sessions \
                 WHERE end_time IS NULL AND {predicate} ORDER BY id DESC LIMIT 1"
            ),
            [],
            |row| Ok((row.get::<_, i64>(0)?, row.get::<_, i64>(1)?)),
        )
        .optional()?;
    let Some((session_id, stored)) = current else {
        return Ok(total);
    };
    let live = connection
        .query_row(
            concat!(
                "SELECT CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) ",
                "FROM usage_sessions WHERE id=?"
            ),
            params![session_id],
            |row| row.get::<_, Option<i64>>(0),
        )?
        .unwrap_or(0);
    Ok(total - stored + live)
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

    fn without_times(value: impl Serialize) -> Value {
        let mut value = serde_json::to_value(value).unwrap();
        if let Some(object) = value.as_object_mut() {
            object.remove("created_at");
            object.remove("updated_at");
            object.remove("last_message_at");
        }
        value
    }

    fn normalize_message_contract(mut value: Value) -> Value {
        if let Some(object) = value.as_object_mut() {
            object.remove("created_at");
            if let Some(Value::String(raw)) = object.get("tool_trace_json") {
                if !raw.is_empty() {
                    object.insert("tool_trace_json".into(), serde_json::from_str(raw).unwrap());
                }
            }
        }
        value
    }

    fn normalize_external_unread(mut value: Value) -> Value {
        if let Some(threads) = value.get_mut("threads").and_then(Value::as_array_mut) {
            for thread in threads {
                if let Some(thread) = thread.as_object_mut() {
                    thread.remove("last_message_at");
                    if let Some(messages) = thread.get_mut("messages").and_then(Value::as_array_mut)
                    {
                        for message in messages {
                            if let Some(message) = message.as_object_mut() {
                                message.remove("raw_json");
                                message.remove("created_at");
                            }
                        }
                    }
                }
            }
        }
        value
    }

    fn normalize_external_result(result: &ExternalAddResult) -> Value {
        json!({
            "duplicate": result.duplicate,
            "message_id": result.message_id,
            "thread": {
                "platform": result.thread.platform,
                "thread_id": result.thread.thread_id,
                "thread_name": result.thread.thread_name,
                "unread_count": result.thread.unread_count,
            },
            "unread": normalize_external_unread(json!(result.unread)),
        })
    }

    fn normalize_history_search(result: &ChatHistorySearchResult) -> Value {
        let records = result.records.iter().map(without_times).collect::<Vec<_>>();
        json!({
            "total": result.total,
            "has_more": result.has_more,
            "records": records,
            "limit": result.limit,
            "offset": result.offset,
        })
    }

    fn normalize_album_message(message: AlbumMessage) -> Value {
        json!({
            "id": message.id,
            "source": message.source,
            "conversation_id": message.conversation_id,
            "group_key": message.group_key,
            "role": message.role,
            "content": message.content,
            "speaker": message.speaker,
        })
    }

    fn normalize_chain_item(item: ConversationChainItem) -> Value {
        json!({
            "source": item.source,
            "conversation_id": item.conversation_id,
            "group_key": item.group_key,
            "user_key": item.user_key,
            "title": item.title,
            "message_count": item.message_count,
            "first_user": item.first_user,
            "preview": item.preview,
        })
    }

    fn normalize_album_day(day: CharacterAlbumDay) -> Value {
        json!({
            "message_count": day.message_count,
            "user_count": day.user_count,
            "assistant_count": day.assistant_count,
            "snippets": day.snippets,
            "snippet_items": day.snippet_items,
            "memory_count": day.memory_count,
            "favorite_count": day.favorite_count,
        })
    }

    #[test]
    fn schema_matches_the_python_contract() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let expected: Value =
            serde_json::from_str(include_str!("../../../compat/database_schema.json")).unwrap();
        assert_eq!(database.schema_contract().unwrap(), expected);
    }

    #[test]
    fn generated_python_database_vectors_match_rust_repositories() {
        let expected: Value =
            serde_json::from_str(include_str!("../../../compat/database_vectors.json")).unwrap();
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();

        assert_eq!(
            without_times(database.relationship_state("Ran", "").unwrap()),
            expected["relationship"]["default"]
        );
        let zero = database
            .upsert_relationship_state(
                "Ran",
                "",
                &RelationshipUpdate {
                    affection: Some(0),
                    trust: Some(0),
                    mood_intensity: Some(0),
                    ..RelationshipUpdate::default()
                },
            )
            .unwrap();
        assert_eq!(without_times(zero), expected["relationship"]["zero"]);
        let delta = database
            .apply_relationship_delta(
                "Moca",
                "alice",
                &RelationshipDelta {
                    affection: 7,
                    trust: -3,
                    familiarity: 2,
                    mood: "happy",
                    ..RelationshipDelta::default()
                },
            )
            .unwrap();
        assert_eq!(without_times(delta), expected["relationship"]["delta"]);

        let memory_ids = vec![
            database
                .add_character_memory("Ran", "", "note", "first", 50, None, None)
                .unwrap(),
            database
                .add_character_memory("Ran", "", "note", "second", 50, None, None)
                .unwrap(),
            database
                .add_character_memory("Ran", "", "preference", "first", 90, None, None)
                .unwrap(),
        ];
        assert_eq!(json!(memory_ids), expected["memory"]["ids"]);
        let memories = database
            .character_memories("Ran", "", 8)
            .unwrap()
            .into_iter()
            .map(without_times)
            .collect::<Vec<_>>();
        assert_eq!(json!(memories), expected["memory"]["records"]);

        let conversation = database.create_conversation("Ran", "fixture", "").unwrap();
        let first = database
            .add_message(conversation, "user", "hello", "", None, None)
            .unwrap();
        let second = database
            .add_message(
                conversation,
                "assistant",
                "tracked",
                "",
                None,
                Some(&json!({
                    "llm_usage": {
                        "input_tokens": 100,
                        "output_tokens": 25,
                        "total_tokens": 125
                    }
                })),
            )
            .unwrap();
        let third = database
            .add_message(conversation, "assistant", "legacy", "", None, None)
            .unwrap();
        assert_eq!(json!([first, second, third]), expected["chat"]["ids"]);

        let page = database
            .get_messages(conversation, Some(2), None)
            .unwrap()
            .into_iter()
            .map(|message| normalize_message_contract(json!(message)))
            .collect::<Vec<_>>();
        let expected_page = expected["chat"]["page"]
            .as_array()
            .unwrap()
            .iter()
            .cloned()
            .map(normalize_message_contract)
            .collect::<Vec<_>>();
        assert_eq!(page, expected_page);
        assert_eq!(
            json!(
                database
                    .conversation_token_usage(Some(conversation))
                    .unwrap()
            ),
            expected["chat"]["usage"]
        );

        let group_ids = vec![
            database
                .add_group_message(
                    "__group__:Ran|Moca",
                    "group-1",
                    "user",
                    "group hello",
                    "",
                    None,
                    None,
                    "alice",
                )
                .unwrap(),
            database
                .add_group_message(
                    "__group__:Ran|Moca",
                    "group-1",
                    "assistant",
                    "【Ran】\ngroup reply",
                    "",
                    None,
                    None,
                    "alice",
                )
                .unwrap(),
        ];
        database
            .set_group_display_name("__group__:Ran|Moca", "Band chat")
            .unwrap();
        assert_eq!(json!(group_ids), expected["queries"]["group_ids"]);
        assert_eq!(
            json!(database.chat_history_filter_options().unwrap()),
            expected["queries"]["filter_options"]
        );
        let history = database
            .search_chat_history(&ChatHistoryQuery {
                keyword: "group hello",
                character: "Ran",
                user_key: "alice",
                source: "group",
                limit: 10,
                ..ChatHistoryQuery::default()
            })
            .unwrap();
        assert_eq!(
            normalize_history_search(&history),
            expected["queries"]["history_search"]
        );
        let group_conversations = database
            .group_conversations("__group__:Ran|Moca", Some("alice"))
            .unwrap()
            .into_iter()
            .map(without_times)
            .collect::<Vec<_>>();
        assert_eq!(
            json!(group_conversations),
            expected["queries"]["group_conversations"]
        );
        let group_chats = database
            .group_chats(Some("alice"))
            .unwrap()
            .into_iter()
            .map(without_times)
            .collect::<Vec<_>>();
        assert_eq!(json!(group_chats), expected["queries"]["group_chats"]);
        assert_eq!(
            database.first_user_message_content(conversation).unwrap(),
            expected["queries"]["first_user_content"]
        );
        assert_eq!(
            json!(database.chat_summary().unwrap()),
            expected["queries"]["chat_summary"]
        );

        let album_conversation = database
            .create_conversation("Ran", "album", "alice")
            .unwrap();
        database
            .add_message(album_conversation, "user", "album private", "", None, None)
            .unwrap();
        database
            .add_message(
                album_conversation,
                "assistant",
                "album reply",
                "",
                None,
                None,
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:Ran|Moca",
                "group-1",
                "assistant",
                "【Moca】\nother reply",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        database
            .add_character_memory(
                "Ran",
                "alice",
                "favorite",
                "favorite memory",
                75,
                None,
                None,
            )
            .unwrap();
        let aliases = vec!["美竹蘭".to_owned()];
        let album_recent = database
            .character_recent_messages("Ran", "alice", 24, &aliases)
            .unwrap()
            .into_iter()
            .map(normalize_album_message)
            .collect::<Vec<_>>();
        assert_eq!(json!(album_recent), expected["album"]["recent"]);
        let album_chain = database
            .character_conversation_chain("Ran", "alice", 20, &aliases)
            .unwrap()
            .into_iter()
            .map(normalize_chain_item)
            .collect::<Vec<_>>();
        assert_eq!(json!(album_chain), expected["album"]["chain"]);
        let album_days = database
            .character_album_days("Ran", "alice", 30, &aliases)
            .unwrap()
            .into_iter()
            .map(normalize_album_day)
            .collect::<Vec<_>>();
        assert_eq!(json!(album_days), expected["album"]["days"]);
        assert_eq!(
            json!(
                database
                    .messages_per_character_range(0, "alice", &BTreeMap::new())
                    .unwrap()
            ),
            expected["album"]["character_counts"]
        );

        let external_event = json!({
            "platform": "napcat",
            "thread_id": "group-1",
            "thread_name": "Band",
            "message_id": "external-1",
            "sender_id": "42",
            "sender_name": "Kasumi",
            "content": "hello from chat",
            "chat_type": "group",
        });
        let external_first = database.add_external_chat_message(&external_event).unwrap();
        assert_eq!(
            normalize_external_result(&external_first),
            expected["external"]["first"]
        );
        let external_duplicate = database.add_external_chat_message(&external_event).unwrap();
        assert_eq!(
            normalize_external_result(&external_duplicate),
            expected["external"]["duplicate"]
        );
        let marked = database
            .mark_external_chat_read("napcat", "group-1")
            .unwrap();
        assert_eq!(
            json!({
                "marked_read": marked.marked_read,
                "unread": normalize_external_unread(json!(marked.unread)),
            }),
            expected["external"]["marked_read"]
        );
        let mut last_pruned = 0;
        for index in 0..51 {
            last_pruned = database
                .add_external_chat_message(&json!({
                    "platform": "napcat",
                    "thread_id": "limit",
                    "message_id": format!("limit-{index}"),
                    "content": index.to_string(),
                    "chat_type": "group",
                    "unread": false,
                }))
                .unwrap()
                .pruned_messages;
        }
        let retained = database
            .with_connection(|connection| {
                connection
                    .query_row(
                        concat!(
                            "SELECT COUNT(*), MIN(CAST(content AS INTEGER)), MAX(CAST(content AS INTEGER)) ",
                            "FROM external_chat_messages WHERE platform='napcat' AND thread_id='limit'"
                        ),
                        [],
                        |row| {
                            Ok((
                                row.get::<_, i64>(0)?,
                                row.get::<_, i64>(1)?,
                                row.get::<_, i64>(2)?,
                            ))
                        },
                    )
                    .map_err(DatabaseError::from)
            })
            .unwrap();
        assert_eq!(
            json!({
                "last_pruned": last_pruned,
                "retained": retained.0,
                "oldest": retained.1,
                "newest": retained.2,
            }),
            expected["external"]["prune"]
        );
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
    fn private_chat_turn_is_atomic_and_enforces_conversation_ownership() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let first = database
            .begin_private_chat_turn(" Ran ", "alice", None, " hello ", None)
            .unwrap();
        let messages = database
            .get_messages(first.conversation_id, None, None)
            .unwrap();
        assert_eq!(messages.len(), 1);
        assert_eq!(messages[0].id, first.user_message_id);
        assert_eq!(messages[0].content, "hello");

        let second = database
            .begin_private_chat_turn("Ran", "alice", Some(first.conversation_id), "again", None)
            .unwrap();
        assert_eq!(second.conversation_id, first.conversation_id);
        assert!(second.user_message_id > first.user_message_id);

        let error = database
            .begin_private_chat_turn("Ran", "bob", Some(first.conversation_id), "private", None)
            .unwrap_err();
        assert!(matches!(error, DatabaseError::InvalidOperation(_)));
        assert_eq!(
            database
                .get_messages(first.conversation_id, None, None)
                .unwrap()
                .len(),
            2
        );
        assert!(
            database
                .begin_private_chat_turn("", "alice", None, "hello", None)
                .is_err()
        );
        assert!(
            database
                .begin_private_chat_turn("Ran", "alice", None, "  ", None)
                .is_err()
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
    fn relationship_memory_and_usage_mutations_preserve_edge_cases() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let state = database
            .upsert_relationship_state(
                "Ran",
                "",
                &RelationshipUpdate {
                    affection: Some(0),
                    trust: Some(0),
                    familiarity: Some(0),
                    mood_intensity: Some(0),
                    ..RelationshipUpdate::default()
                },
            )
            .unwrap();
        assert_eq!(
            (state.affection, state.trust, state.mood_intensity),
            (0, 0, 0)
        );
        let state = database
            .apply_relationship_delta(
                "Ran",
                "",
                &RelationshipDelta {
                    affection: 150,
                    trust: 4,
                    familiarity: 2,
                    mood: "joy",
                    reason: &"r".repeat(600),
                    ..RelationshipDelta::default()
                },
            )
            .unwrap();
        assert_eq!(
            (state.affection, state.trust, state.familiarity),
            (100, 4, 2)
        );
        let chart = database.mood_events_for_chart("Ran", "", 0).unwrap();
        assert_eq!(chart.last().unwrap().affection, 100);

        let literal = database
            .add_character_memory("Ran", "", "note", "literal 100%", 20, None, None)
            .unwrap();
        let other = database
            .add_character_memory("Ran", "", "note", "literal 100x", 20, None, None)
            .unwrap();
        assert_eq!(
            database
                .delete_character_memories_like("Ran", "", "100%")
                .unwrap(),
            1
        );
        assert!(
            database
                .character_memories("Ran", "", 8)
                .unwrap()
                .iter()
                .any(|memory| memory.id == other)
        );
        assert_eq!(
            database
                .delete_character_memories(&[literal, other, other], "Ran", "")
                .unwrap(),
            1
        );

        database
            .with_connection(|connection| {
                connection.execute(
                    "INSERT INTO usage_sessions (start_time, end_time, duration_seconds) VALUES ('2020-01-01 00:00:00', '2020-01-01 00:00:15', 15)",
                    [],
                )?;
                Ok(())
            })
            .unwrap();
        assert_eq!(database.usage_all_time().unwrap(), 15);
        let live = database.start_usage_session().unwrap();
        assert_eq!(database.heartbeat_usage_session(live).unwrap(), 1);
        assert_eq!(database.end_usage_session(live).unwrap(), 1);
    }

    #[test]
    fn external_chat_context_retention_and_deletion_stay_consistent() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        assert!(matches!(
            database.add_external_chat_message(&json!([])),
            Err(DatabaseError::InvalidExternalEvent(_))
        ));
        database
            .add_external_chat_message(&json!({
                "platform": "napcat",
                "thread_id": "old",
                "message_id": "old-1",
                "sender_name": "Old",
                "content": "expired",
                "chat_type": "private",
                "timestamp": "2000-01-01 00:00:00",
            }))
            .unwrap();
        database
            .add_external_chat_message(&json!({
                "platform": "napcat",
                "thread_id": "new",
                "thread_name": "Current",
                "message_id": "new-1",
                "sender_name": "Kasumi",
                "content": "line one\nline two",
                "chat_type": "private",
                "timestamp": "2999-01-01 00:00:00",
            }))
            .unwrap();

        let context = database.external_chat_context_text(4, 6).unwrap();
        assert!(context.contains("【外部聊天软件上下文】"));
        assert!(context.contains("Kasumi（未读）：line one line two"));
        assert_eq!(
            database
                .purge_external_chat_older_than(7, "private", "napcat")
                .unwrap(),
            1
        );
        let summary = database.external_chat_unread_summary(5, 3).unwrap();
        assert_eq!(summary.total_unread, 1);
        assert_eq!(summary.threads[0].thread_id, "new");

        let deleted = database.delete_external_chat("private", "napcat").unwrap();
        assert_eq!(deleted.deleted_messages, 1);
        assert_eq!(deleted.deleted_threads, 1);
        assert_eq!(deleted.unread.unwrap().total_unread, 0);
    }

    #[test]
    fn history_search_and_analytics_respect_literal_filters_and_user_scope() {
        let temp = tempdir().unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let conversation = database.create_conversation("Ran", "", "").unwrap();
        let other = database.create_conversation("Ran", "", "other").unwrap();
        let empty = database.create_conversation("Ran", "", "").unwrap();
        database
            .add_message(conversation, "user", "literal 100%", "", None, None)
            .unwrap();
        database
            .add_message(
                conversation,
                "assistant",
                "literal 100% again",
                "",
                None,
                None,
            )
            .unwrap();
        database
            .add_message(other, "user", "literal 100x", "", None, None)
            .unwrap();
        database
            .add_group_message("group", "1", "user", "group", "", None, None, "")
            .unwrap();

        let first_page = database
            .search_chat_history(&ChatHistoryQuery {
                keyword: "100%",
                user_key: DEFAULT_USER_PROFILE_KEY,
                limit: 1,
                skip_count: true,
                ..ChatHistoryQuery::default()
            })
            .unwrap();
        assert_eq!(first_page.total, -1);
        assert!(first_page.has_more);
        assert_eq!(first_page.records.len(), 1);

        let daily = database
            .daily_message_counts(1, Some(DEFAULT_USER_PROFILE_KEY))
            .unwrap();
        assert_eq!(daily.iter().map(|day| day.count).sum::<i64>(), 3);
        let heatmap = database
            .hourly_heatmap(1, Some(DEFAULT_USER_PROFILE_KEY))
            .unwrap();
        assert_eq!(heatmap.iter().flatten().sum::<i64>(), 3);
        assert_eq!(
            database
                .delete_empty_conversations("Ran", Some(DEFAULT_USER_PROFILE_KEY))
                .unwrap(),
            1
        );
        assert_ne!(empty, conversation);
    }

    #[test]
    fn database_backup_restore_and_relationship_transfer_round_trip() {
        let temp = tempdir().unwrap();
        let source_path = temp.path().join("source.db");
        let export_path = temp.path().join("export.db");
        let target_path = temp.path().join("target.db");
        let source = Database::open(&source_path).unwrap();
        let conversation = source.create_conversation("Ran", "backup", "").unwrap();
        source
            .add_message(conversation, "user", "persisted", "", None, None)
            .unwrap();
        source
            .upsert_relationship_state(
                "Ran",
                "",
                &RelationshipUpdate {
                    affection: Some(87),
                    summary: Some("trusted"),
                    ..RelationshipUpdate::default()
                },
            )
            .unwrap();
        source
            .add_character_memory("Ran", "", "preference", "likes bread", 80, None, None)
            .unwrap();

        assert!(matches!(
            source.export_database(&source_path),
            Err(DatabaseError::InvalidOperation(_))
        ));
        assert_eq!(
            source.export_database(&export_path).unwrap(),
            ChatDatabaseSummary {
                conversations: 1,
                messages: 1,
                group_messages: 0,
            }
        );

        let target = Database::open(&target_path).unwrap();
        target.create_conversation("discard", "", "").unwrap();
        assert_eq!(
            target.import_database(&export_path).unwrap(),
            ChatDatabaseSummary {
                conversations: 1,
                messages: 1,
                group_messages: 0,
            }
        );
        assert_eq!(
            target.get_messages(conversation, None, None).unwrap()[0].content,
            "persisted"
        );

        let relationship_data = source.export_relationship_data().unwrap();
        let relationship_target = Database::open(temp.path().join("relationship.db")).unwrap();
        assert_eq!(
            relationship_target
                .import_relationship_data(&relationship_data)
                .unwrap(),
            RelationshipImportSummary {
                relationship_states: 1,
                character_memories: 1,
            }
        );
        assert_eq!(
            relationship_target
                .relationship_state("Ran", "")
                .unwrap()
                .affection,
            87
        );
        assert_eq!(
            relationship_target
                .character_memories("Ran", "", 8)
                .unwrap()[0]
                .content,
            "likes bread"
        );
    }

    #[test]
    fn attachment_reference_cleanup_removes_files_that_disappeared() {
        let temp = tempdir().unwrap();
        let attachment_dir = temp.path().join("chat_attachments");
        fs::create_dir(&attachment_dir).unwrap();
        let attachment = attachment_dir.join("temporary.png");
        fs::write(&attachment, b"image").unwrap();
        let database = Database::open(temp.path().join("data.db")).unwrap();
        let conversation = database.create_conversation("Ran", "", "").unwrap();
        database
            .add_message(
                conversation,
                "user",
                "attachment",
                "",
                Some(&json!([{"type": "image", "path": attachment}])),
                None,
            )
            .unwrap();
        fs::remove_file(&attachment).unwrap();
        assert_eq!(database.sanitize_attachment_references().unwrap(), 1);
        assert_eq!(
            database.get_messages(conversation, None, None).unwrap()[0].attachments_json,
            ""
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
