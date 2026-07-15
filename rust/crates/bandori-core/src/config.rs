use fs2::FileExt;
use serde_json::{Map, Value};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::{Duration, Instant};
use tempfile::Builder;
use thiserror::Error;

const DEFAULTS_JSON: &str = include_str!("../../../compat/config_defaults.json");
const LOCK_TIMEOUT: Duration = Duration::from_secs(10);
const LOCK_RETRY: Duration = Duration::from_millis(50);

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("configuration I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("configuration JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("configuration root must be a JSON object")]
    RootNotObject,
    #[error("timed out waiting for configuration lock: {0}")]
    LockTimeout(PathBuf),
}

/// A three-way-merge configuration document compatible with `ConfigManager`.
///
/// Only keys present in the checked-in Python default snapshot are persisted,
/// matching the current Python save semantics.  `loaded_values` is retained so
/// concurrent processes can merge non-overlapping edits without overwriting one
/// another.
#[derive(Clone, Debug)]
pub struct ConfigDocument {
    values: Map<String, Value>,
    loaded_values: Map<String, Value>,
    loaded_from_file: bool,
}

impl Default for ConfigDocument {
    fn default() -> Self {
        let values = defaults();
        Self {
            loaded_values: values.clone(),
            values,
            loaded_from_file: false,
        }
    }
}

impl ConfigDocument {
    pub fn load(path: impl AsRef<Path>) -> Result<Self, ConfigError> {
        let path = path.as_ref();
        if !path.exists() {
            return Ok(Self::default());
        }

        let mut source = String::new();
        File::open(path)?.read_to_string(&mut source)?;
        let raw: Value = serde_json::from_str(&source)?;
        Self::from_value(raw, true)
    }

    pub fn from_value(raw: Value, loaded_from_file: bool) -> Result<Self, ConfigError> {
        let loaded = raw.as_object().ok_or(ConfigError::RootNotObject)?;
        let mut values = defaults();
        for key in values.keys().cloned().collect::<Vec<_>>() {
            if let Some(value) = loaded.get(&key) {
                values.insert(key, value.clone());
            }
        }

        // Compatibility migrations performed by the Python loader.
        if truthy(loaded.get("desktop_state_awareness_enabled")) {
            values.insert("screen_awareness_enabled".into(), Value::Bool(true));
        }
        if !loaded.contains_key("screen_awareness_display_mode") {
            let fallback = loaded
                .get("reminder_display_mode")
                .cloned()
                .unwrap_or_else(|| Value::String("floating".into()));
            values.insert(
                "screen_awareness_display_mode".into(),
                normalize_display_mode(fallback),
            );
        }

        Ok(Self {
            loaded_values: values.clone(),
            values,
            loaded_from_file,
        })
    }

    pub fn values(&self) -> &Map<String, Value> {
        &self.values
    }

    pub fn get(&self, key: &str) -> Option<&Value> {
        self.values.get(key)
    }

    pub fn set(&mut self, key: impl Into<String>, value: Value) {
        self.values.insert(key.into(), value);
    }

    pub fn loaded_from_file(&self) -> bool {
        self.loaded_from_file
    }

    pub fn merged_for_save(&self, current_disk: Option<&Map<String, Value>>) -> Map<String, Value> {
        let defaults = defaults();
        let current_disk = current_disk.unwrap_or(&self.loaded_values);
        let mut merged = defaults.clone();

        for (key, default) in defaults {
            let value = self.values.get(&key).unwrap_or(&default);
            let loaded = self.loaded_values.get(&key).unwrap_or(&default);
            let disk = current_disk.get(&key).unwrap_or(&default);

            let preserve_local_migration = (key == "screen_awareness_enabled"
                && truthy(current_disk.get("desktop_state_awareness_enabled")))
                || (key == "screen_awareness_display_mode" && !current_disk.contains_key(&key));
            let selected = if preserve_local_migration {
                value
            } else if value == loaded && disk != loaded {
                disk
            } else {
                value
            };
            merged.insert(key, selected.clone());
        }
        merged
    }

    /// Persist using the same lock filename, three-way merge, durable temporary
    /// file and atomic replacement strategy as the Python implementation.
    pub fn save(&mut self, path: impl AsRef<Path>) -> Result<(), ConfigError> {
        let path = path.as_ref();
        let parent = path.parent().unwrap_or_else(|| Path::new("."));
        fs::create_dir_all(parent)?;

        let lock_path = lock_path(path);
        let lock = OpenOptions::new()
            .create(true)
            .read(true)
            .write(true)
            .truncate(false)
            .open(&lock_path)?;
        lock_with_timeout(&lock, &lock_path)?;

        let result = (|| {
            let current = read_current_object(path, self.loaded_from_file)?;
            let merged = self.merged_for_save(current.as_ref());
            let bytes = serde_json::to_vec_pretty(&Value::Object(merged.clone()))?;

            let file_name = path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("config.json");
            let mut temp = Builder::new()
                .prefix(&format!("{file_name}."))
                .suffix(".tmp")
                .tempfile_in(parent)?;
            temp.write_all(&bytes)?;
            temp.flush()?;
            temp.as_file().sync_all()?;
            temp.persist(path).map_err(|error| error.error)?;

            self.values = merged.clone();
            self.loaded_values = merged;
            self.loaded_from_file = true;
            Ok(())
        })();

        let _ = FileExt::unlock(&lock);
        result
    }
}

fn defaults() -> Map<String, Value> {
    serde_json::from_str::<Value>(DEFAULTS_JSON)
        .expect("checked-in config defaults must be valid JSON")
        .as_object()
        .expect("checked-in config defaults must be an object")
        .clone()
}

fn lock_path(path: &Path) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("config.json");
    path.with_file_name(format!("{file_name}.lock"))
}

fn lock_with_timeout(file: &File, path: &Path) -> Result<(), ConfigError> {
    let deadline = Instant::now() + LOCK_TIMEOUT;
    loop {
        match file.try_lock_exclusive() {
            Ok(()) => return Ok(()),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                if Instant::now() >= deadline {
                    return Err(ConfigError::LockTimeout(path.to_path_buf()));
                }
                thread::sleep(LOCK_RETRY);
            }
            Err(error) => return Err(ConfigError::Io(error)),
        }
    }
}

fn read_current_object(
    path: &Path,
    loaded_from_file: bool,
) -> Result<Option<Map<String, Value>>, ConfigError> {
    if !path.exists() {
        return Ok(None);
    }
    let mut source = String::new();
    match File::open(path).and_then(|mut file| file.read_to_string(&mut source)) {
        Ok(_) => {
            let value: Value = serde_json::from_str(&source)?;
            Ok(Some(
                value.as_object().ok_or(ConfigError::RootNotObject)?.clone(),
            ))
        }
        Err(error) if !loaded_from_file => Err(ConfigError::Io(error)),
        Err(error) => Err(ConfigError::Io(error)),
    }
}

fn normalize_display_mode(value: Value) -> Value {
    match value.as_str() {
        Some("floating" | "system") => value,
        _ => Value::String("floating".into()),
    }
}

fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(value)) => *value,
        Some(Value::Number(value)) => value.as_f64().is_some_and(|number| number != 0.0),
        Some(Value::String(value)) => !value.is_empty(),
        Some(Value::Array(value)) => !value.is_empty(),
        Some(Value::Object(value)) => !value.is_empty(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn missing_file_uses_complete_defaults() {
        let temp = tempfile::tempdir().unwrap();
        let config = ConfigDocument::load(temp.path().join("config.json")).unwrap();
        assert!(!config.loaded_from_file());
        assert_eq!(config.get("fps"), Some(&json!(120)));
        assert!(config.values().len() > 100);
    }

    #[test]
    fn legacy_screen_awareness_keys_are_migrated() {
        let config = ConfigDocument::from_value(
            json!({
                "desktop_state_awareness_enabled": true,
                "reminder_display_mode": "system"
            }),
            true,
        )
        .unwrap();
        assert_eq!(config.get("screen_awareness_enabled"), Some(&json!(true)));
        assert_eq!(
            config.get("screen_awareness_display_mode"),
            Some(&json!("system"))
        );
    }

    #[test]
    fn concurrent_non_overlapping_changes_are_merged() {
        let mut config = ConfigDocument::from_value(json!({"fps": 60}), true).unwrap();
        config.set("opacity", json!(0.75));
        let disk = json!({"fps": 144}).as_object().expect("object").clone();
        let merged = config.merged_for_save(Some(&disk));
        assert_eq!(merged.get("fps"), Some(&json!(144)));
        assert_eq!(merged.get("opacity"), Some(&json!(0.75)));
    }

    #[test]
    fn save_round_trips_with_atomic_temp_file() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.set("language", json!("zh_CN"));
        config.save(&path).unwrap();

        let loaded = ConfigDocument::load(&path).unwrap();
        assert_eq!(loaded.get("language"), Some(&json!("zh_CN")));
        assert!(temp.path().join("config.json.lock").exists());
        assert_eq!(
            fs::read_dir(temp.path())
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry.file_name().to_string_lossy().ends_with(".tmp"))
                .count(),
            0
        );
    }
}
