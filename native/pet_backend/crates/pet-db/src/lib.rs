//! SQLite persistence engine. One connection per manager; no worker, timer or cache
//! with an unbounded lifetime. Lock order: release GIL -> connection mutex -> SQLite.
mod error;
mod schema;
pub mod value;

pub use error::{Error, Result};
pub use rusqlite::types::Value as SqlValue;
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
            if write {
                c.execute_batch(if result.is_ok() { "COMMIT" } else { "ROLLBACK" })?;
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
    pub fn call(&self, op: &str, _args: &Value) -> Result<Value> {
        self.with_connection(|c| match op {
            "integrity_check" => value::scalar(c, "PRAGMA integrity_check", &[]),
            "change_revision" => Ok(serde_json::json!([
                c.total_changes(),
                value::scalar(c, "PRAGMA data_version", &[])?
            ])),
            _ => Err(Error::Invalid(format!("unknown database operation: {op}"))),
        })
    }
}
