use rusqlite::Connection;
use serde_json::{Value, json};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

const MIGRATION_MARKER: &str = ".bandoripet-legacy-migrated";
const MAX_CONFIG_BYTES: u64 = 64 * 1024 * 1024;
const COPY_BUFFER_BYTES: usize = 1024 * 1024;

#[derive(Debug, Error)]
pub enum LegacyMigrationError {
    #[error(transparent)]
    Io(#[from] io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Database(#[from] rusqlite::Error),
    #[error("legacy config is larger than the 64 MiB migration bound")]
    OversizedConfig,
    #[error("legacy migration refuses symbolic links: {0}")]
    SymbolicLink(PathBuf),
    #[error("legacy and native data roots resolve to the same directory")]
    SameRoot,
}

pub fn migrate_legacy_data(
    legacy_root: impl AsRef<Path>,
    native_root: impl AsRef<Path>,
) -> Result<bool, LegacyMigrationError> {
    let legacy_root = dunce::canonicalize(legacy_root.as_ref())?;
    fs::create_dir_all(native_root.as_ref())?;
    let native_root = dunce::canonicalize(native_root.as_ref())?;
    if legacy_root == native_root {
        return Err(LegacyMigrationError::SameRoot);
    }
    if native_root.join(MIGRATION_MARKER).is_file() {
        return Ok(false);
    }
    if !legacy_root.join("config.json").is_file() && !legacy_root.join("data.db").is_file() {
        return Ok(false);
    }

    migrate_config(&legacy_root, &native_root)?;
    migrate_database(&legacy_root, &native_root)?;
    for relative in [
        PathBuf::from("chat_attachments"),
        PathBuf::from("models"),
        Path::new(".runtime").join("chat_avatars"),
    ] {
        let source = legacy_root.join(&relative);
        if source.is_dir() {
            copy_directory(&source, &native_root.join(&relative))?;
        }
    }
    let marker = serde_json::to_vec_pretty(&json!({
        "version": 1,
        "source": legacy_root.to_string_lossy(),
    }))?;
    atomic_write(&native_root.join(MIGRATION_MARKER), &marker)?;
    Ok(true)
}

fn migrate_config(legacy_root: &Path, native_root: &Path) -> Result<(), LegacyMigrationError> {
    let source = legacy_root.join("config.json");
    let target = native_root.join("config.json");
    if !source.is_file() || target.exists() {
        return Ok(());
    }
    if source.metadata()?.len() > MAX_CONFIG_BYTES {
        return Err(LegacyMigrationError::OversizedConfig);
    }
    let mut bytes = Vec::new();
    File::open(&source)?
        .take(MAX_CONFIG_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_CONFIG_BYTES {
        return Err(LegacyMigrationError::OversizedConfig);
    }
    let mut config: Value = serde_json::from_slice(&bytes)?;
    rebase_mutable_paths(&mut config, legacy_root, native_root);
    atomic_write(&target, &serde_json::to_vec_pretty(&config)?)
}

fn migrate_database(legacy_root: &Path, native_root: &Path) -> Result<(), LegacyMigrationError> {
    let source = legacy_root.join("data.db");
    let target = native_root.join("data.db");
    if !source.is_file() || target.exists() {
        return Ok(());
    }
    let staging = native_root.join(format!(
        ".legacy-db-{}-{}",
        std::process::id(),
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos()
    ));
    fs::create_dir(&staging)?;
    let staged_database = staging.join("data.db");
    let result: Result<(), LegacyMigrationError> = (|| {
        copy_file(&source, &staged_database)?;
        for suffix in ["-wal", "-shm"] {
            let source_sidecar = PathBuf::from(format!("{}{suffix}", source.display()));
            if source_sidecar.is_file() {
                copy_file(
                    &source_sidecar,
                    &PathBuf::from(format!("{}{suffix}", staged_database.display())),
                )?;
            }
        }
        {
            let connection = Connection::open(&staged_database)?;
            connection.busy_timeout(std::time::Duration::from_secs(2))?;
            rebase_database_attachments(&connection, legacy_root, native_root)?;
            let _ = connection.query_row("PRAGMA wal_checkpoint(TRUNCATE)", [], |_| Ok(()));
            let _ = connection.pragma_update(None, "journal_mode", "DELETE");
        }
        atomic_copy(&staged_database, &target)
    })();
    let _ = fs::remove_dir_all(&staging);
    result
}

fn rebase_database_attachments(
    connection: &Connection,
    legacy_root: &Path,
    native_root: &Path,
) -> Result<(), LegacyMigrationError> {
    for table in ["messages", "group_messages"] {
        if !table_has_column(connection, table, "attachments_json")? {
            continue;
        }
        let mut statement = connection.prepare(&format!(
            "SELECT id, attachments_json FROM {table} WHERE attachments_json != ''"
        ))?;
        let rows = statement
            .query_map([], |row| {
                Ok((row.get::<_, i64>(0)?, row.get::<_, String>(1)?))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        drop(statement);
        for (id, raw) in rows {
            let Ok(mut attachments) = serde_json::from_str::<Value>(&raw) else {
                continue;
            };
            if !rebase_mutable_paths(&mut attachments, legacy_root, native_root) {
                continue;
            }
            connection.execute(
                &format!("UPDATE {table} SET attachments_json=?1 WHERE id=?2"),
                (serde_json::to_string(&attachments)?, id),
            )?;
        }
    }
    Ok(())
}

fn table_has_column(
    connection: &Connection,
    table: &str,
    column: &str,
) -> Result<bool, rusqlite::Error> {
    let mut statement = connection.prepare(&format!("PRAGMA table_info({table})"))?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(1))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(names.iter().any(|name| name == column))
}

fn rebase_mutable_paths(value: &mut Value, legacy_root: &Path, native_root: &Path) -> bool {
    let mut changed = false;
    match value {
        Value::String(text) => {
            if let Some(rebased) = rebase_path(text, legacy_root, native_root) {
                *text = rebased.to_string_lossy().into_owned();
                changed = true;
            }
        }
        Value::Array(values) => {
            for value in values {
                changed |= rebase_mutable_paths(value, legacy_root, native_root);
            }
        }
        Value::Object(values) => {
            for value in values.values_mut() {
                changed |= rebase_mutable_paths(value, legacy_root, native_root);
            }
        }
        _ => {}
    }
    changed
}

fn rebase_path(text: &str, legacy_root: &Path, native_root: &Path) -> Option<PathBuf> {
    let path = Path::new(text);
    let candidate = if path.is_absolute() {
        path.to_path_buf()
    } else {
        legacy_root.join(path)
    };
    let resolved = dunce::canonicalize(&candidate).ok().unwrap_or(candidate);
    let relative = resolved.strip_prefix(legacy_root).ok()?;
    let allowed = relative.starts_with("models")
        || relative.starts_with("chat_attachments")
        || relative.starts_with(Path::new(".runtime").join("chat_avatars"));
    allowed.then(|| native_root.join(relative))
}

fn copy_directory(source: &Path, target: &Path) -> Result<(), LegacyMigrationError> {
    if source.symlink_metadata()?.file_type().is_symlink() {
        return Err(LegacyMigrationError::SymbolicLink(source.to_path_buf()));
    }
    fs::create_dir_all(target)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let path = entry.path();
        let metadata = path.symlink_metadata()?;
        if metadata.file_type().is_symlink() {
            return Err(LegacyMigrationError::SymbolicLink(path));
        }
        let destination = target.join(entry.file_name());
        if metadata.is_dir() {
            copy_directory(&path, &destination)?;
        } else if metadata.is_file() && !destination.exists() {
            atomic_copy(&path, &destination)?;
        }
    }
    Ok(())
}

fn atomic_copy(source: &Path, target: &Path) -> Result<(), LegacyMigrationError> {
    if target.exists() {
        return Ok(());
    }
    let parent = target.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let temporary = temporary_path(target);
    let result: Result<(), LegacyMigrationError> = (|| {
        let mut input = File::open(source)?;
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        let mut buffer = vec![0_u8; COPY_BUFFER_BYTES];
        loop {
            let count = input.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            output.write_all(&buffer[..count])?;
        }
        output.sync_all()?;
        fs::rename(&temporary, target)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn atomic_write(target: &Path, bytes: &[u8]) -> Result<(), LegacyMigrationError> {
    if target.exists() {
        return Ok(());
    }
    let parent = target.parent().unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent)?;
    let temporary = temporary_path(target);
    let result: Result<(), LegacyMigrationError> = (|| {
        let mut output = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        output.write_all(bytes)?;
        output.sync_all()?;
        fs::rename(&temporary, target)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn copy_file(source: &Path, target: &Path) -> Result<(), LegacyMigrationError> {
    let mut input = File::open(source)?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)?;
    io::copy(&mut input, &mut output)?;
    output.sync_all()?;
    Ok(())
}

fn temporary_path(target: &Path) -> PathBuf {
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    target.with_extension(format!("migration-{}-{suffix}.tmp", std::process::id()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rusqlite::params;
    use tempfile::tempdir;

    #[test]
    fn migration_copies_mutable_data_rebases_paths_and_is_idempotent() {
        let temp = tempdir().unwrap();
        let legacy = temp.path().join("legacy");
        let native = temp.path().join("native");
        fs::create_dir_all(legacy.join("chat_attachments")).unwrap();
        fs::create_dir_all(legacy.join("models/ran/live")).unwrap();
        fs::create_dir_all(legacy.join(".runtime/chat_avatars")).unwrap();
        let attachment = legacy.join("chat_attachments/image.png");
        let model = legacy.join("models/ran/live/ran.model3.json");
        let avatar = legacy.join(".runtime/chat_avatars/ran.png");
        fs::write(&attachment, b"png").unwrap();
        fs::write(&model, b"{}").unwrap();
        fs::write(&avatar, b"avatar").unwrap();
        fs::write(
            legacy.join("config.json"),
            serde_json::to_vec(&json!({
                "models": [{"path": model}],
                "user_avatar_path": avatar,
                "prompt": "chat_attachments is only prose"
            }))
            .unwrap(),
        )
        .unwrap();
        {
            let database = Connection::open(legacy.join("data.db")).unwrap();
            database
                .execute_batch(
                    "CREATE TABLE messages (id INTEGER PRIMARY KEY, attachments_json TEXT);\n\
                     CREATE TABLE group_messages (id INTEGER PRIMARY KEY, attachments_json TEXT);",
                )
                .unwrap();
            database
                .execute(
                    "INSERT INTO messages (attachments_json) VALUES (?1)",
                    params![json!([{"type": "image", "path": attachment}]).to_string()],
                )
                .unwrap();
        }

        assert!(migrate_legacy_data(&legacy, &native).unwrap());
        assert!(!migrate_legacy_data(&legacy, &native).unwrap());
        assert_eq!(
            fs::read(native.join("chat_attachments/image.png")).unwrap(),
            b"png"
        );
        assert!(native.join("models/ran/live/ran.model3.json").is_file());
        assert!(native.join(".runtime/chat_avatars/ran.png").is_file());
        let config: Value =
            serde_json::from_slice(&fs::read(native.join("config.json")).unwrap()).unwrap();
        let migrated_model = Path::new(config["models"][0]["path"].as_str().unwrap());
        assert_eq!(
            dunce::canonicalize(migrated_model).unwrap(),
            dunce::canonicalize(native.join("models/ran/live/ran.model3.json")).unwrap()
        );
        assert_eq!(config["prompt"], "chat_attachments is only prose");
        let database = Connection::open(native.join("data.db")).unwrap();
        let raw: String = database
            .query_row("SELECT attachments_json FROM messages", [], |row| {
                row.get(0)
            })
            .unwrap();
        let attachments: Value = serde_json::from_str(&raw).unwrap();
        let migrated_attachment = Path::new(attachments[0]["path"].as_str().unwrap());
        assert_eq!(
            dunce::canonicalize(migrated_attachment).unwrap(),
            dunce::canonicalize(native.join("chat_attachments/image.png")).unwrap()
        );
        assert!(native.join(MIGRATION_MARKER).is_file());
    }

    #[test]
    fn directory_without_legacy_config_or_database_is_not_migrated() {
        let temp = tempdir().unwrap();
        let legacy = temp.path().join("legacy");
        let native = temp.path().join("native");
        fs::create_dir_all(legacy.join("models")).unwrap();

        assert!(!migrate_legacy_data(&legacy, &native).unwrap());
        assert!(!native.join(MIGRATION_MARKER).exists());
    }
}
