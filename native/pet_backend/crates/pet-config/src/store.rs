//! Loading, validation and atomic persistence of `config.json`.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use pet_i18n::{Key, Lang};
use tracing::{info, warn};

use crate::config::Config;
use crate::patch::SettingsPatch;
use crate::{bounds, SCHEMA_VERSION};

/// Errors surfaced to the caller (the settings window shows them in an InfoBar).
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    /// Filesystem failure while reading or writing.
    #[error("config io error at {path}: {source}")]
    Io {
        /// Offending path.
        path: PathBuf,
        /// Underlying error.
        #[source]
        source: std::io::Error,
    },
    /// The document was not valid JSON or did not match the schema.
    #[error("config parse error: {0}")]
    Parse(#[from] serde_json::Error),
    /// Atomic replace failed after all retries.
    #[error("failed to replace {path} after {attempts} attempts")]
    Replace {
        /// Target path.
        path: PathBuf,
        /// Number of attempts made.
        attempts: u32,
    },
}

/// Where a successfully loaded config came from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoadSource {
    /// No file existed; defaults were used and the first-run flag is set.
    Missing,
    /// The file parsed cleanly.
    Loaded,
    /// The file was corrupt; it was renamed to `.corrupt-<ts>.bak` and defaults were used.
    Recovered {
        /// Backup file that received the unreadable bytes.
        backup: PathBuf,
    },
}

/// Result of [`load_config`].
#[derive(Debug, Clone)]
pub struct LoadOutcome {
    /// Parsed (and sanitized) configuration.
    pub config: Config,
    /// Provenance of the configuration.
    pub source: LoadSource,
    /// Non-fatal validation messages, already applied as clamps.
    pub warnings: Vec<String>,
}

impl LoadOutcome {
    /// `true` on the very first run, when the settings UI should open on the model page.
    pub fn is_first_run(&self) -> bool {
        matches!(self.source, LoadSource::Missing)
    }
}

/// Outcome of [`save_config`].
#[derive(Debug, Clone, PartialEq)]
pub struct SaveOutcome {
    /// `true` when the bytes on disk changed.
    pub written: bool,
    /// Rejected patch keys, if the save came from a patch.
    pub rejected: Vec<String>,
}

/// Loads `config.json`, recovering from corruption instead of failing.
pub fn load_config(path: &Path) -> LoadOutcome {
    let mut warnings = Vec::new();
    let raw = match fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            info!(path = %path.display(), "config missing, using defaults");
            let mut config = Config::default();
            warnings.extend(sanitize(&mut config));
            return LoadOutcome {
                config,
                source: LoadSource::Missing,
                warnings,
            };
        }
        Err(error) => {
            warn!(path = %path.display(), %error, "config unreadable, using defaults");
            let mut config = Config::default();
            warnings.extend(sanitize(&mut config));
            return LoadOutcome {
                config,
                source: LoadSource::Missing,
                warnings,
            };
        }
    };

    match serde_json::from_str::<Config>(raw.trim_start_matches('\u{feff}')) {
        Ok(mut config) => {
            warnings.extend(sanitize(&mut config));
            LoadOutcome {
                config,
                source: LoadSource::Loaded,
                warnings,
            }
        }
        Err(error) => {
            warn!(path = %path.display(), %error, "config corrupt, backing up");
            let backup = corrupt_backup_path(path);
            let source = match fs::rename(path, &backup) {
                Ok(()) => LoadSource::Recovered {
                    backup: backup.clone(),
                },
                Err(rename_error) => {
                    warn!(%rename_error, "failed to move corrupt config aside");
                    LoadSource::Recovered {
                        backup: backup.clone(),
                    }
                }
            };
            let mut config = Config::default();
            warnings.extend(sanitize(&mut config));
            warnings.push(
                Lang::default().format(Key::ConfigRecovered, &[&backup.display().to_string()]),
            );
            LoadOutcome {
                config,
                source,
                warnings,
            }
        }
    }
}

fn corrupt_backup_path(path: &Path) -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
        .unwrap_or_else(|| "config.json".to_owned());
    path.with_file_name(format!("{name}.corrupt-{stamp}.bak"))
}

/// Clamps every out-of-range value and reports what was changed.
///
/// Invalid values never abort startup: the spec asks for a silent fallback plus a
/// log line, because a crash dialog is worse than a slightly wrong number.
pub fn sanitize(config: &mut Config) -> Vec<String> {
    let mut warnings = Vec::new();

    let removed_poke_motion = config.extras.remove("poke_motion").is_some();
    let removed_poke_expression = config.extras.remove("poke_expression").is_some();
    let removed_poke_settings = removed_poke_motion || removed_poke_expression;
    if removed_poke_settings {
        warnings.push("removed obsolete poke settings".to_owned());
    }

    if config.schema_version != SCHEMA_VERSION {
        warnings.push(format!(
            "schema_version {} -> {}",
            config.schema_version, SCHEMA_VERSION
        ));
        config.schema_version = SCHEMA_VERSION;
    }

    let fps = config.fps.clamp(bounds::FPS_MIN, bounds::FPS_MAX);
    if fps != config.fps {
        warnings.push(format!("fps {} out of range, clamped to {fps}", config.fps));
        config.fps = fps;
    }

    if !config.opacity.is_finite() {
        config.opacity = bounds::OPACITY_MAX;
        warnings.push("opacity not finite, reset to 1.0".to_owned());
    }
    let opacity = config
        .opacity
        .clamp(bounds::OPACITY_MIN, bounds::OPACITY_MAX);
    if (opacity - config.opacity).abs() > f32::EPSILON {
        warnings.push(format!(
            "opacity {:.2} out of range, clamped to {opacity:.2}",
            config.opacity
        ));
        config.opacity = opacity;
    }

    if config.live2d_scale != bounds::SCALE_UNSET
        && !(bounds::SCALE_MIN..=bounds::SCALE_MAX).contains(&config.live2d_scale)
    {
        warnings.push(format!(
            "live2d_scale {} out of range, clamped",
            config.live2d_scale
        ));
        config.live2d_scale = config
            .live2d_scale
            .clamp(bounds::SCALE_MIN, bounds::SCALE_MAX);
    }

    // Tags written by other builds ("zh-Hant", "en", …) collapse to the shipped
    // tag so the language dropdown always finds the configured entry.
    config.language = Lang::from_tag(&config.language).tag().to_owned();

    config.normalize_models();

    for entry in &mut config.models {
        // Older configs only stored the mirrored window coordinates.
        if entry.window_placement.is_unset() && (entry.window_x != -1 || entry.window_y != -1) {
            entry.window_placement.x = entry.window_x;
            entry.window_placement.y = entry.window_y;
            entry.window_placement.width = entry.window_width;
            entry.window_placement.height = entry.window_height;
        }
        entry.sync_placement_mirror();
    }

    // Make sure every region has an action, without inventing overrides.
    for region in crate::CLICK_REGIONS {
        config
            .click_motion_actions
            .entry(region.key().to_owned())
            .or_default();
    }

    warnings
}

/// Applies a settings patch, validating the result and writing it atomically.
///
/// On write failure the previous file stays intact and the in-memory config is
/// rolled back by the caller (it still owns the old value).
pub fn apply_patch(
    path: &Path,
    config: &mut Config,
    patch: &SettingsPatch,
) -> Result<SaveOutcome, ConfigError> {
    let mut candidate = config.clone();
    let rejected = patch.apply_to(&mut candidate);
    let _ = sanitize(&mut candidate);
    let written = candidate != *config || !path.exists();
    if written {
        save_config(path, &candidate)?;
        *config = candidate;
    }
    Ok(SaveOutcome { written, rejected })
}

/// Writes `config.json` atomically: temp file → fsync → replace → fsync directory.
pub fn save_config(path: &Path, config: &Config) -> Result<(), ConfigError> {
    let bytes = serde_json::to_vec_pretty(config)?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|source| ConfigError::Io {
            path: parent.to_path_buf(),
            source,
        })?;
    }
    let tmp = path.with_extension(format!("json.tmp{}", std::process::id()));

    {
        let mut file = fs::File::create(&tmp).map_err(|source| ConfigError::Io {
            path: tmp.clone(),
            source,
        })?;
        file.write_all(&bytes).map_err(|source| ConfigError::Io {
            path: tmp.clone(),
            source,
        })?;
        file.write_all(b"\n").map_err(|source| ConfigError::Io {
            path: tmp.clone(),
            source,
        })?;
        file.sync_all().map_err(|source| ConfigError::Io {
            path: tmp.clone(),
            source,
        })?;
    }

    // `std::fs::rename` uses MoveFileExW(MOVEFILE_REPLACE_EXISTING) on Windows, so
    // this is an atomic replace; antivirus/file-indexer locks are retried briefly.
    let mut last_error = None;
    for attempt in 0..6 {
        match fs::rename(&tmp, path) {
            Ok(()) => {
                let _ = cleanup_stale_temp_files(path);
                return Ok(());
            }
            Err(error) => {
                last_error = Some(error);
                std::thread::sleep(std::time::Duration::from_millis(20 * (attempt + 1)));
            }
        }
    }
    let _ = fs::remove_file(&tmp);
    warn!(path = %path.display(), error = ?last_error, "atomic replace failed");
    Err(ConfigError::Replace {
        path: path.to_path_buf(),
        attempts: 6,
    })
}

/// Removes `config.json.tmp*` leftovers older than 24h (spec §3.6).
pub fn cleanup_stale_temp_files(path: &Path) -> std::io::Result<()> {
    let Some(parent) = path.parent() else {
        return Ok(());
    };
    let Some(stem) = path
        .file_name()
        .map(|name| name.to_string_lossy().to_string())
    else {
        return Ok(());
    };
    let cutoff = SystemTime::now() - std::time::Duration::from_secs(24 * 60 * 60);
    for entry in fs::read_dir(parent)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().to_string();
        if !name.starts_with(&format!("{stem}.tmp")) {
            continue;
        }
        if let Ok(metadata) = entry.metadata() {
            if metadata
                .modified()
                .map(|time| time < cutoff)
                .unwrap_or(false)
            {
                let _ = fs::remove_file(entry.path());
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ClickAction, DarkTheme};

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "bandori-pet-lite-test-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        dir
    }

    #[test]
    fn missing_config_reports_first_run() {
        let dir = temp_dir("missing");
        let outcome = load_config(&dir.join("config.json"));
        assert!(outcome.is_first_run());
        assert_eq!(outcome.config.fps, 120);
    }

    #[test]
    fn corrupt_config_is_backed_up() {
        let dir = temp_dir("corrupt");
        let path = dir.join("config.json");
        fs::write(&path, b"{ this is not json").expect("write");
        let outcome = load_config(&path);
        match outcome.source {
            LoadSource::Recovered { backup } => assert!(backup.exists()),
            other => panic!("expected recovery, got {other:?}"),
        }
        assert!(!path.exists());
    }

    #[test]
    fn save_then_load_round_trips() {
        let dir = temp_dir("roundtrip");
        let path = dir.join("config.json");
        let mut config = Config {
            fps: 90,
            dark_theme: DarkTheme::On,
            ..Default::default()
        };
        config
            .click_motion_actions
            .insert("head".to_owned(), ClickAction::new("smile01", "smile01"));
        save_config(&path, &config).expect("save");
        let loaded = load_config(&path);
        assert_eq!(loaded.config.fps, 90);
        assert_eq!(loaded.config.dark_theme, DarkTheme::On);
        assert_eq!(
            loaded.config.click_motion_actions.get("head"),
            Some(&ClickAction::new("smile01", "smile01"))
        );
        // no temp files left behind
        let leftovers: Vec<_> = fs::read_dir(&dir)
            .unwrap()
            .filter_map(Result::ok)
            .filter(|entry| entry.file_name().to_string_lossy().contains(".tmp"))
            .collect();
        assert!(leftovers.is_empty());
    }

    #[test]
    fn sanitize_clamps_out_of_range_values() {
        let mut config = Config {
            fps: 5000,
            opacity: 0.05,
            live2d_scale: 9000,
            ..Default::default()
        };
        let warnings = sanitize(&mut config);
        assert_eq!(config.fps, 240);
        assert!((config.opacity - 0.2).abs() < f32::EPSILON);
        assert_eq!(config.live2d_scale, 500);
        assert_eq!(warnings.len(), 3);
    }

    #[test]
    fn patch_apply_is_atomic_and_reports_rejections() {
        let dir = temp_dir("patch");
        let path = dir.join("config.json");
        let mut config = Config::default();
        save_config(&path, &config).expect("initial save");

        let patch = SettingsPatch::from_pairs([
            ("fps", serde_json::json!(60)),
            (
                "click_motion_actions.head.motion",
                serde_json::json!("smile01"),
            ),
        ]);
        let outcome = apply_patch(&path, &mut config, &patch).expect("apply");
        assert!(outcome.written);
        assert_eq!(config.fps, 60);
        assert_eq!(
            config.click_motion_actions["head"].motion,
            "smile01".to_owned()
        );
        let reloaded = load_config(&path).config;
        assert_eq!(reloaded.fps, 60);
    }

    #[test]
    fn active_role_and_independent_legacy_positions_survive_reload() {
        let dir = temp_dir("multi-role-legacy");
        let path = dir.join("config.json");
        fs::write(&path, concat!("\u{feff}", r#"{
            "character":"anon", "costume":"school",
            "models":[
                {"character":"kasumi","costume":"live","path":"models/kasumi.zst::live/model.json","window_x":100,"window_y":200},
                {"character":"anon","costume":"school","path":"models/anon.zst::school/model3.json","window_x":700,"window_y":250,"future_role_setting":{"enabled":true}}
            ]
        }"#)).unwrap();
        let loaded = load_config(&path);
        assert_eq!(loaded.source, LoadSource::Loaded);
        assert_eq!(loaded.config.character, "anon");
        assert_eq!(loaded.config.models[0].window_placement.x, 100);
        assert_eq!(loaded.config.models[1].window_placement.x, 700);
        assert_eq!(
            loaded.config.models[1].extras["future_role_setting"]["enabled"],
            true
        );
        save_config(&path, &loaded.config).unwrap();
        assert_eq!(load_config(&path).config, loaded.config);
    }

    #[test]
    fn unchanged_patch_creates_missing_config() {
        let dir = temp_dir("patch-missing");
        let path = dir.join("config.json");
        let mut config = Config::default();
        let outcome = apply_patch(&path, &mut config, &SettingsPatch::default()).unwrap();
        assert!(outcome.written);
        assert!(path.exists());
    }
}
