//! Online backup never copies a live WAL file or replaces an open target inode.
use crate::{value::*, Database, Error, Result};
use rusqlite::{
    backup::{Backup, StepResult},
    Connection, OpenFlags,
};
use serde_json::{json, Value};
use std::{
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

pub fn migrate_legacy(source: &Path, target: &Path) -> Result<()> {
    use fs2::FileExt;
    if target.exists() || !source.is_file() {
        return Ok(());
    }
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let lock_path = PathBuf::from(format!("{}.legacy-migration.lock", target.display()));
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(lock_path)?;
    lock.lock_exclusive()?;
    if !target.exists() {
        snapshot(source, target, false)?;
    }
    // File drop releases the lock even on errors. Never unlink a lock inode.
    Ok(())
}

pub fn summary_file(path: &Path) -> Result<Value> {
    summary(&readonly(path)?)
}

fn readonly(path: &Path) -> Result<Connection> {
    let c = Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )?;
    c.busy_timeout(Duration::from_secs(10))?;
    Ok(c)
}
pub fn validate(c: &Connection) -> Result<()> {
    for (table, required) in [
        (
            "conversations",
            &["id", "character", "title", "created_at"][..],
        ),
        (
            "messages",
            &["id", "conversation_id", "role", "content", "created_at"][..],
        ),
        (
            "group_messages",
            &[
                "id",
                "group_key",
                "conversation_id",
                "role",
                "content",
                "created_at",
            ][..],
        ),
    ] {
        let columns = query(c, &format!("PRAGMA table_info({table})"), &[])?;
        if columns.is_empty() {
            return Err(Error::Invalid(format!("missing table(s): {table}")));
        }
        for column in required {
            if !columns.iter().any(|r| r["name"] == *column) {
                return Err(Error::Invalid(format!(
                    "table {table} missing column(s): {column}"
                )));
            }
        }
    }
    for row in query(c, "PRAGMA integrity_check", &[])? {
        if row.as_object().and_then(|o| o.values().next()) != Some(&json!("ok")) {
            return Err(Error::Invalid(format!(
                "database integrity check failed: {row}"
            )));
        }
    }
    Ok(())
}
fn copy(src: &Connection, dst: &mut Connection) -> Result<()> {
    let backup = Backup::new(src, dst)?;
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        match backup.step(256)? {
            StepResult::Done => return Ok(()),
            StepResult::More => {}
            StepResult::Busy | StepResult::Locked => {
                if Instant::now() >= deadline {
                    return Err(Error::Sql(rusqlite::Error::SqliteFailure(
                        rusqlite::ffi::Error::new(rusqlite::ffi::SQLITE_BUSY),
                        Some("database backup lock timeout".into()),
                    )));
                }
                std::thread::sleep(Duration::from_millis(25));
            }
            _ => return Err(Error::Invalid("unknown backup status".into())),
        }
    }
}
pub fn snapshot(source: &Path, destination: &Path, check: bool) -> Result<()> {
    if source.canonicalize().ok() == destination.canonicalize().ok() && source.exists() {
        return Err(Error::Invalid(
            "source and destination are the same file".into(),
        ));
    }
    if let Some(parent) = destination.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    for suffix in ["-wal", "-shm"] {
        if PathBuf::from(format!("{}{suffix}", destination.display())).exists() {
            return Err(Error::Invalid(
                "destination has active SQLite sidecars; close its connections before export"
                    .into(),
            ));
        }
    }
    let src = readonly(source)?;
    if check {
        validate(&src)?;
    }
    let parent = destination
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let temp = tempfile::NamedTempFile::new_in(parent)?;
    {
        let mut dst = Connection::open(temp.path())?;
        copy(&src, &mut dst)?;
        dst.pragma_update(None, "journal_mode", "DELETE")?;
    }
    temp.as_file().sync_all()?;
    temp.persist(destination).map_err(|e| e.error)?;
    Ok(())
}
impl Database {
    pub fn restore(&self, source: &Path) -> Result<()> {
        let src = readonly(source)?;
        validate(&src)?;
        self.with_connection(|dst| {
            if !dst.is_autocommit() {
                return Err(Error::Invalid(
                    "cannot restore during an active transaction".into(),
                ));
            }
            dst.flush_prepared_statement_cache();
            copy(&src, dst)?;
            Ok(())
        })
    }
}
fn attachment_path(raw: &str, root: &Path) -> Option<PathBuf> {
    let path = Path::new(raw).canonicalize().ok()?;
    if path.is_file() && path.starts_with(root) {
        Some(path)
    } else {
        None
    }
}
fn sanitize_payload(payload: &Value, root: &Path) -> Value {
    let mut out = vec![];
    if let Some(items) = payload.as_array() {
        for item in items.iter().filter(|v| v.is_object()) {
            let kind = trim(item, "type").to_lowercase();
            if !["image", "file"].contains(&kind.as_str()) {
                continue;
            }
            let raw = trim(item, "path");
            let Some(path) = attachment_path(&raw, root) else {
                continue;
            };
            let name = if truth(&item["name"]) {
                string(item, "name")
            } else {
                Path::new(&raw)
                    .file_name()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_default()
            };
            let mime = if truth(&item["mime"]) {
                string(item, "mime")
            } else if kind == "image" {
                "image/png".into()
            } else {
                "application/octet-stream".into()
            };
            let mut clean =
                json!({"type":kind,"path":raw,"name":short(&name,240),"mime":short(&mime,160)});
            let size = if truth(&item["size"]) {
                integer(&item["size"])
            } else {
                std::fs::metadata(path)
                    .ok()
                    .and_then(|m| i64::try_from(m.len()).ok())
            };
            if let Some(size) = size {
                clean["size"] = json!(size);
            }
            for (key, limit) in [
                ("uploaded_at", 40),
                ("vision_summary", 6000),
                ("vision_error", 600),
            ] {
                let s = trim(item, key);
                if !s.is_empty() && (key == "uploaded_at" || kind == "image") {
                    clean[key] = json!(short(&s, limit));
                }
            }
            out.push(clean);
        }
    }
    json!(out)
}
pub fn sanitize(c: &Connection, a: &Value) -> Result<Value> {
    let root = PathBuf::from(string(a, "attachment_dir"));
    let root = root.canonicalize().unwrap_or(root);
    let mut removed = 0;
    for table in ["messages", "group_messages"] {
        let mut last = 0_i64;
        loop {
            let rows=query(c,&format!("SELECT id,attachments_json FROM {table} WHERE id>? AND attachments_json!='' ORDER BY id LIMIT 256"),&[json!(last)])?;
            if rows.is_empty() {
                break;
            }
            for r in rows {
                last = int(&r, "id");
                let raw = string(&r, "attachments_json");
                // A malformed field is reported and the whole transaction rolls back.
                // Never turn corrupt JSON into an empty list and silently erase it.
                let payload: Value = serde_json::from_str(&raw).map_err(|e| {
                    Error::Invalid(format!("{table} row {last}: corrupt attachments_json: {e}"))
                })?;
                let original = payload.as_array().ok_or_else(|| {
                    Error::Invalid(format!(
                        "{table} row {last}: attachments_json is not a list"
                    ))
                })?;
                let cleaned = sanitize_payload(&payload, &root);
                removed += original
                    .len()
                    .saturating_sub(cleaned.as_array().map_or(0, Vec::len));
                // Retain bytes and formatting when cleanup has nothing to change.
                if cleaned != payload {
                    exec(
                        c,
                        &format!("UPDATE {table} SET attachments_json=? WHERE id=?"),
                        &[
                            json!(if cleaned.as_array().is_some_and(Vec::is_empty) {
                                String::new()
                            } else {
                                cleaned.to_string()
                            }),
                            json!(last),
                        ],
                    )?;
                }
            }
        }
    }
    Ok(json!(removed))
}
pub fn summary(c: &Connection) -> Result<Value> {
    validate(c)?;
    Ok(
        json!({"conversations":scalar(c,"SELECT COUNT(*) FROM conversations",&[])?,"messages":scalar(c,"SELECT COUNT(*) FROM messages",&[])?,"group_messages":scalar(c,"SELECT COUNT(*) FROM group_messages",&[])?}),
    )
}
