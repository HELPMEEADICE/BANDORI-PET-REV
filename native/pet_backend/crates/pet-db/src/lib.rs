//! SQLite persistence engine. One connection per manager; no worker, timer or cache
//! with an unbounded lifetime. Lock order: release GIL -> connection mutex -> SQLite.
mod albums;
mod chat;
mod error;
mod external;
pub mod history;
pub mod maintenance;
mod memory;
mod schema;
mod search;
mod statistics;
pub mod value;

pub use error::{Error, Result};
pub use rusqlite::types::Value as SqlValue;
pub use rusqlite::version as sqlite_version;
pub use rusqlite::Error as SqlError;
pub use rusqlite::ErrorCode as SqlErrorCode;
mod raw;
pub use raw::RawOutput;
use rusqlite::{Connection, InterruptHandle};
use serde_json::Value;
use std::{path::Path, sync::Mutex, time::Duration};

pub struct Database {
    connection: Mutex<Option<Connection>>,
    interrupt: InterruptHandle,
    pid: u32,
}

impl Database {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent)?;
        }
        let mut c = Connection::open(path)?;
        c.busy_timeout(Duration::from_secs(10))?;
        c.pragma_update(None, "journal_mode", "WAL")?;
        c.pragma_update(None, "foreign_keys", "ON")?;
        c.set_prepared_statement_cache_capacity(64);
        schema::migrate(&mut c)?;
        Ok(Self {
            interrupt: c.get_interrupt_handle(),
            connection: Mutex::new(Some(c)),
            pid: std::process::id(),
        })
    }
    pub fn with_connection<T>(&self, f: impl FnOnce(&mut Connection) -> Result<T>) -> Result<T> {
        if self.pid != std::process::id() {
            return Err(Error::Process);
        }
        let mut guard = self.connection.lock().map_err(|_| Error::Poisoned)?;
        f(guard.as_mut().ok_or(Error::Closed)?)
    }
    pub fn interrupt(&self) {
        self.interrupt.interrupt();
    }
    pub fn close(&self) -> Result<()> {
        let mut guard = self.connection.lock().map_err(|_| Error::Poisoned)?;
        if let Some(c) = guard.as_mut() {
            if !c.is_autocommit() {
                c.execute_batch("ROLLBACK")?;
            }
        }
        if let Some(c) = guard.take() {
            c.close().map_err(|(_, e)| Error::Sql(e))?;
        }
        Ok(())
    }
    /// All domain writes are one IMMEDIATE transaction, including read/modify/write
    /// and results computed after writing. The Transaction drops on every error.
    pub fn transaction<T>(
        c: &mut Connection,
        write: bool,
        f: impl FnOnce(&Connection) -> Result<T>,
    ) -> Result<T> {
        if !c.is_autocommit() {
            // Compatibility calls may have opened a DB-API transaction.
            let result = f(c);
            if !c.is_autocommit() && (write || result.is_err()) {
                if let Err(error) =
                    c.execute_batch(if result.is_ok() { "COMMIT" } else { "ROLLBACK" })
                {
                    if !c.is_autocommit() {
                        let _ = c.execute_batch("ROLLBACK");
                    }
                    if result.is_ok() {
                        return Err(error.into());
                    }
                }
            }
            return result;
        }
        let tx = c.transaction_with_behavior(if write {
            rusqlite::TransactionBehavior::Immediate
        } else {
            rusqlite::TransactionBehavior::Deferred
        })?;
        let result = f(&tx)?;
        tx.commit()?;
        Ok(result)
    }
    pub fn call(&self, op: &str, args: &Value) -> Result<Value> {
        if !args.is_object() {
            return Err(Error::Invalid(
                "database arguments must be an object".into(),
            ));
        }
        self.with_connection(|c| match op {
            "integrity_check" => value::scalar(c, "PRAGMA integrity_check", &[]),
            "change_revision" => Ok(serde_json::json!([
                c.total_changes(),
                value::scalar(c, "PRAGMA data_version", &[])?
            ])),
            _ => Self::transaction(c, is_write(op), |c| dispatch(c, op, args)),
        })
    }
}

fn is_write(op: &str) -> bool {
    [
        "add_",
        "set_",
        "delete_",
        "update_",
        "upsert_",
        "apply_",
        "assign_",
        "mark_",
        "prune_",
        "purge_",
        "start_",
        "end_",
        "heartbeat_",
        "import_",
        "sanitize_",
    ]
    .iter()
    .any(|prefix| op.starts_with(prefix))
        || op == "create_conversation"
}
fn dispatch(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    match op {
        "chat_database_summary" => maintenance::summary(c),
        "sanitize_attachments" => maintenance::sanitize(c, a),
        "start_usage_session"
        | "end_usage_session"
        | "heartbeat_usage_session"
        | "get_usage_today"
        | "get_usage_week"
        | "get_usage_all_time"
        | "get_usage_daily"
        | "get_chat_summary"
        | "get_mood_events_for_chart"
        | "get_daily_message_counts"
        | "get_messages_per_character_range"
        | "get_hourly_heatmap" => statistics::call(c, op, a),
        "get_character_recent_messages"
        | "get_character_conversation_chain"
        | "get_character_album_days" => albums::call(c, op, a),
        "get_chat_history_filter_options" => search::filters(c),
        "search_chat_history" => search::search(c, a),
        "get_relationship_state"
        | "upsert_relationship_state"
        | "apply_relationship_delta"
        | "add_character_memory"
        | "get_character_memories"
        | "get_character_memories_by_kind"
        | "update_character_memory"
        | "delete_character_memory"
        | "delete_character_memories"
        | "delete_character_memories_like"
        | "export_relationship_data"
        | "import_relationship_data" => memory::call(c, op, a),
        "add_external_chat_message"
        | "get_external_chat_unread_summary"
        | "external_chat_context_text"
        | "mark_external_chat_read"
        | "prune_external_group_chat_limit"
        | "delete_external_chat"
        | "purge_external_chat_older_than" => external::call(c, op, a),
        _ => chat::call(c, op, a),
    }
}
