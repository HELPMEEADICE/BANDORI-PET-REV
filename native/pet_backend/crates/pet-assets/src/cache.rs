//! Extraction cache: `%LOCALAPPDATA%\BandoriPetLite\cache\<archive-stem>\<costume>\`.
//!
//! Neocari's loaders are path based, so a compressed costume has to exist on disk
//! before it can be rendered. Extraction is guarded against path traversal and
//! symlinks, and the cache keeps the eight most recently used costumes.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use pet_config::ModelFormat;
use serde::{Deserialize, Serialize};
use tracing::{debug, info, warn};

use crate::archive::{entry_name, open_archive, read_entry_bytes};
use crate::virtual_path::{normalize_member, ModelPath};
use crate::{ArchiveRevision, MAX_MEMBER_BYTES};

/// Default number of costumes kept on disk (spec §2.2).
pub const DEFAULT_CAPACITY: usize = 8;

const STAMP_FILE: &str = ".bandori_cache.json";
const LRU_FILE: &str = ".lru.json";

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum CacheError {
    /// Invalid `archive::member` reference.
    #[error("invalid model reference: {0}")]
    Path(String),
    /// Archive operations failed.
    #[error("archive io error: {0}")]
    Io(String),
    /// The requested member does not exist in the archive.
    #[error("member {member} not found in {archive}")]
    MissingMember {
        /// Archive path.
        archive: String,
        /// Member path.
        member: String,
    },
    /// zstd decode failure.
    #[error("zstd error: {0}")]
    Zstd(String),
    /// Tar parse failure.
    #[error("tar error: {0}")]
    Tar(String),
    /// A member or returned batch exceeded the configured byte limit.
    #[error("archive resource too large: {0}")]
    TooLarge(String),
}

/// A costume that exists on disk and can be handed to Neocari.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedModel {
    /// Absolute path to `model.json` / `*.model3.json`.
    pub model_path: PathBuf,
    /// Costume directory on disk.
    pub costume_dir: PathBuf,
    /// Detected container format.
    pub format: ModelFormat,
}

/// Extracting cache for `.zst` model archives.
#[derive(Debug, Clone)]
pub struct ModelCache {
    cache_root: PathBuf,
    models_root: PathBuf,
    capacity: usize,
}

#[derive(Debug, Serialize, Deserialize, Default)]
struct LruState {
    #[serde(default)]
    entries: BTreeMap<String, u64>,
}

#[derive(Debug, Serialize, Deserialize, PartialEq, Eq)]
struct Stamp {
    archive_path: PathBuf,
    archive_size: u64,
    archive_mtime_ns: u128,
    costume: String,
}

impl ModelCache {
    /// Creates a cache rooted at `cache_root`, resolving archives under `models_root`.
    pub fn new(cache_root: impl Into<PathBuf>, models_root: impl Into<PathBuf>) -> Self {
        Self {
            cache_root: cache_root.into(),
            models_root: models_root.into(),
            capacity: DEFAULT_CAPACITY,
        }
    }

    /// Overrides the LRU capacity (used by tests and by the advanced config).
    pub fn with_capacity(mut self, capacity: usize) -> Self {
        self.capacity = capacity;
        self
    }

    /// Cache root directory.
    pub fn cache_root(&self) -> &Path {
        &self.cache_root
    }

    /// Resolves the archive part of a virtual path.
    ///
    /// `config.json` stores `models/<archive>.zst` relative to the installation
    /// root, while `models_root` already points at `…/models`, so the leading
    /// `models/` segment is stripped before joining.
    fn archive_path(&self, model_path: &ModelPath) -> PathBuf {
        let raw = PathBuf::from(model_path.archive.replace('\\', "/"));
        if raw.is_absolute() {
            return raw;
        }
        let relative = model_path
            .archive
            .replace('\\', "/")
            .strip_prefix("models/")
            .map(|rest| rest.to_owned())
            .unwrap_or_else(|| model_path.archive.clone());
        let candidate = self.models_root.join(&relative);
        if candidate.exists() {
            return candidate;
        }
        if let Some(name) = raw.file_name() {
            let fallback = self.models_root.join(name);
            if fallback.exists() {
                return fallback;
            }
        }
        candidate
    }

    /// Makes sure the costume behind `spec` is unpacked and returns its model path.
    pub fn resolve(&self, spec: &str) -> Result<ResolvedModel, CacheError> {
        if !spec.contains("::") {
            let supplied = PathBuf::from(spec);
            let model_path = if supplied.is_absolute() {
                supplied
            } else {
                self.models_root
                    .parent()
                    .unwrap_or(&self.models_root)
                    .join(supplied)
            };
            if !model_path.is_file() {
                return Err(CacheError::Io(format!(
                    "model not found: {}",
                    model_path.display()
                )));
            }
            return Ok(ResolvedModel {
                format: ModelFormat::from_path(spec),
                costume_dir: model_path.parent().unwrap().to_path_buf(),
                model_path,
            });
        }
        let model_path =
            ModelPath::parse(spec).map_err(|error| CacheError::Path(error.to_string()))?;
        let costume = model_path
            .costume()
            .ok_or_else(|| CacheError::Path(spec.to_owned()))?;
        let archive = self.archive_path(&model_path);
        if !archive.exists() {
            return Err(CacheError::Io(format!(
                "archive not found: {}",
                archive.display()
            )));
        }
        let stem = archive
            .file_stem()
            .map(|stem| stem.to_string_lossy().to_string())
            .ok_or_else(|| CacheError::Path(spec.to_owned()))?;
        let revision = ArchiveRevision::read(&archive)?;
        let target_dir = self.cache_root.join(&stem).join(costume);

        let stamp_path = target_dir.join(STAMP_FILE);
        let expected = Stamp {
            archive_path: fs::canonicalize(&archive).map_err(|e| CacheError::Io(e.to_string()))?,
            archive_size: revision.size,
            archive_mtime_ns: revision.mtime_ns,
            costume: costume.to_owned(),
        };
        let current = read_stamp(&stamp_path);
        let needs_extract = current.as_ref() != Some(&expected) || !target_dir.is_dir();

        if needs_extract {
            debug!(
                archive = %archive.display(),
                costume,
                "extracting costume into cache"
            );
            let started = std::time::Instant::now();
            self.extract_prefix(
                &archive,
                &format!("{costume}/"),
                &self.cache_root.join(&stem),
            )?;
            write_json(&stamp_path, &expected)?;
            info!(
                costume,
                archive = %stem,
                ms = started.elapsed().as_millis(),
                "costume extracted"
            );
        }

        self.touch(&format!("{stem}/{costume}"));
        let model_path = target_dir.join(
            model_path
                .member
                .split_once('/')
                .map(|(_, file)| file)
                .unwrap_or("model.json"),
        );
        if !model_path.exists() {
            return Err(CacheError::MissingMember {
                archive: model_path.display().to_string(),
                member: model_path.display().to_string(),
            });
        }
        let format = if model_path
            .to_string_lossy()
            .to_ascii_lowercase()
            .ends_with(".model3.json")
        {
            ModelFormat::Moc3
        } else {
            ModelFormat::Moc
        };

        if needs_extract {
            self.prune(Some(&format!("{stem}/{costume}")));
        }

        Ok(ResolvedModel {
            model_path,
            costume_dir: target_dir,
            format,
        })
    }

    /// Extracts a single member (for example `character.png`) and returns its path.
    pub fn extract_member(&self, spec: &str) -> Result<PathBuf, CacheError> {
        let model_path =
            ModelPath::parse(spec).map_err(|error| CacheError::Path(error.to_string()))?;
        let archive = self.archive_path(&model_path);
        let stem = archive
            .file_stem()
            .map(|stem| stem.to_string_lossy().to_string())
            .ok_or_else(|| CacheError::Path(spec.to_owned()))?;
        let target = self.cache_root.join(&stem).join(&model_path.member);
        let revision = ArchiveRevision::read(&archive)?;
        let stamp_path = target.with_extension("member-stamp.json");
        let expected = Stamp {
            archive_path: fs::canonicalize(&archive).map_err(|e| CacheError::Io(e.to_string()))?,
            archive_size: revision.size,
            archive_mtime_ns: revision.mtime_ns,
            costume: model_path.member.clone(),
        };
        if target.exists() && read_stamp(&stamp_path).as_ref() == Some(&expected) {
            return Ok(target);
        }
        self.extract_prefix(&archive, &model_path.member, &self.cache_root.join(&stem))?;
        if !target.exists() {
            return Err(CacheError::MissingMember {
                archive: archive.display().to_string(),
                member: model_path.member,
            });
        }
        write_json(&stamp_path, &expected)?;
        Ok(target)
    }

    /// Extracts every member whose path equals or starts with `prefix`.
    fn extract_prefix(
        &self,
        archive_path: &Path,
        prefix: &str,
        destination: &Path,
    ) -> Result<(), CacheError> {
        let prefix = normalize_member(prefix.trim_end_matches('/'))
            .map_err(|error| CacheError::Path(error.to_string()))?;
        let mut tar = open_archive(archive_path)?;
        let entries = tar
            .entries()
            .map_err(|error| CacheError::Tar(error.to_string()))?;

        let mut extracted = 0usize;
        for entry in entries {
            let mut entry = entry.map_err(|error| CacheError::Tar(error.to_string()))?;
            let Some(relative) = entry_name(&entry)? else {
                continue;
            };
            if !member_matches(&relative, &prefix) {
                continue;
            }
            if !entry.header().entry_type().is_file() {
                // Directories are recreated implicitly; symlinks are refused.
                continue;
            }
            let relative_path = PathBuf::from(relative);
            if relative_path.components().any(|component| {
                matches!(
                    component,
                    Component::ParentDir | Component::RootDir | Component::Prefix(_)
                )
            }) {
                continue;
            }
            let destination_path = destination.join(&relative_path);
            if !destination_path.starts_with(destination) {
                continue;
            }
            if let Some(parent) = destination_path.parent() {
                fs::create_dir_all(parent)
                    .map_err(|error| CacheError::Io(format!("{}: {error}", parent.display())))?;
            }
            let buffer = read_entry_bytes(&mut entry, MAX_MEMBER_BYTES)?;
            fs::write(&destination_path, &buffer).map_err(|error| {
                CacheError::Io(format!("{}: {error}", destination_path.display()))
            })?;
            extracted += 1;
        }

        if extracted == 0 {
            return Err(CacheError::MissingMember {
                archive: archive_path.display().to_string(),
                member: prefix,
            });
        }
        Ok(())
    }

    fn lru_path(&self) -> PathBuf {
        self.cache_root.join(LRU_FILE)
    }

    fn read_lru(&self) -> LruState {
        fs::read_to_string(self.lru_path())
            .ok()
            .and_then(|raw| serde_json::from_str(&raw).ok())
            .unwrap_or_default()
    }

    fn touch(&self, key: &str) {
        let mut state = self.read_lru();
        state.entries.insert(key.to_owned(), now_secs());
        if let Err(error) = write_json(&self.lru_path(), &state) {
            warn!(%error, "failed to update model cache LRU");
        }
    }

    /// Drops the least recently used costumes, keeping `capacity` of them.
    ///
    /// `keep` is never evicted (the costume that is currently on screen).
    pub fn prune(&self, keep: Option<&str>) {
        if self.capacity == 0 {
            return;
        }
        let mut state = self.read_lru();
        let mut entries: Vec<(String, u64)> = state.entries.clone().into_iter().collect();
        entries.sort_by_key(|entry| std::cmp::Reverse(entry.1));

        let mut kept = 0usize;
        let mut evicted = Vec::new();
        for (key, _) in entries {
            let is_keep = keep == Some(key.as_str());
            if is_keep || kept < self.capacity {
                kept += 1;
                continue;
            }
            evicted.push(key);
        }

        for key in evicted {
            let directory = self
                .cache_root
                .join(key.replace('/', std::path::MAIN_SEPARATOR_STR));
            if directory.starts_with(&self.cache_root) {
                debug!(key = %key, "evicting cached costume");
                let _ = fs::remove_dir_all(&directory);
            }
            state.entries.remove(&key);
        }
        if let Err(error) = write_json(&self.lru_path(), &state) {
            warn!(%error, "failed to persist model cache LRU");
        }
    }

    /// Total bytes currently used by the cache (for the About page).
    pub fn size_on_disk(&self) -> u64 {
        fn walk(path: &Path) -> u64 {
            let Ok(entries) = fs::read_dir(path) else {
                return 0;
            };
            entries
                .flatten()
                .map(|entry| match entry.metadata() {
                    Ok(meta) if meta.is_dir() => walk(&entry.path()),
                    Ok(meta) => meta.len(),
                    Err(_) => 0,
                })
                .sum()
        }
        walk(&self.cache_root)
    }
}

fn member_matches(raw_path: &str, prefix: &str) -> bool {
    if raw_path == prefix {
        return true;
    }
    raw_path
        .strip_prefix(prefix)
        .map(|rest| rest.starts_with('/') || prefix.ends_with('/'))
        .unwrap_or(false)
}

fn read_stamp(path: &Path) -> Option<Stamp> {
    let raw = fs::read_to_string(path).ok()?;
    serde_json::from_str(&raw).ok()
}

fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<(), CacheError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| CacheError::Io(format!("{}: {error}", parent.display())))?;
    }
    let bytes =
        serde_json::to_vec_pretty(value).map_err(|error| CacheError::Io(error.to_string()))?;
    fs::write(path, bytes).map_err(|error| CacheError::Io(format!("{}: {error}", path.display())))
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ARCHIVE_INDEX_MEMBER;

    fn build_archive(dir: &Path, stem: &str, members: &[(&str, &str)]) -> PathBuf {
        let archive_path = dir.join(format!("{stem}.zst"));
        let file = fs::File::create(&archive_path).unwrap();
        let encoder = zstd::stream::write::Encoder::new(file, 3).unwrap();
        let mut builder = tar::Builder::new(encoder);
        let index = format!(
            "{{\"files\":[{}]}}",
            members
                .iter()
                .map(|(name, _)| format!("\"{name}\""))
                .collect::<Vec<_>>()
                .join(",")
        );
        let mut header = tar::Header::new_gnu();
        header.set_size(index.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        builder
            .append_data(&mut header, ARCHIVE_INDEX_MEMBER, index.as_bytes())
            .unwrap();
        for (name, contents) in members {
            let mut header = tar::Header::new_gnu();
            header.set_size(contents.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            builder
                .append_data(&mut header, *name, contents.as_bytes())
                .unwrap();
        }
        builder.into_inner().unwrap().finish().unwrap();
        archive_path
    }

    #[test]
    fn extracted_portraits_refresh_after_package_replacement() {
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("models");
        fs::create_dir_all(&models).unwrap();
        build_archive(&models, "kasumi", &[("character.png", "old")]);
        let cache = ModelCache::new(dir.path().join("portraits"), &models);
        let spec = "models/kasumi.zst::character.png";
        // extract_member accepts a fully resolved archive path from the picker.
        let spec = spec.replace(
            "models/kasumi.zst",
            &models.join("kasumi.zst").to_string_lossy(),
        );
        let portrait = cache.extract_member(&spec).unwrap();
        assert_eq!(fs::read_to_string(&portrait).unwrap(), "old");
        build_archive(
            &models,
            "kasumi",
            &[("character.png", "new portrait contents")],
        );
        cache.extract_member(&spec).unwrap();
        assert_eq!(
            fs::read_to_string(portrait).unwrap(),
            "new portrait contents"
        );
    }

    #[test]
    fn resolves_and_reuses_extracted_costume() {
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("models");
        fs::create_dir_all(&models).unwrap();
        build_archive(
            &models,
            "kasumi",
            &[
                ("live_default/model.json", "{\"model\":\"data/model.moc\"}"),
                ("live_default/data/model.moc", "MOC"),
                ("other/model.json", "{}"),
            ],
        );
        let cache = ModelCache::new(dir.path().join("cache"), &models);
        let spec = "models/kasumi.zst::live_default/model.json";
        let resolved = cache.resolve(spec).unwrap();
        assert_eq!(resolved.format, ModelFormat::Moc);
        assert!(resolved.model_path.exists());
        assert!(resolved.costume_dir.join("data/model.moc").exists());
        assert!(
            !cache.cache_root().join("kasumi").join("other").exists(),
            "only the requested costume is extracted"
        );

        let again = cache.resolve(spec).unwrap();
        assert_eq!(again.model_path, resolved.model_path);
    }

    #[test]
    fn stale_cache_is_reextracted_when_archive_changes() {
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("models");
        fs::create_dir_all(&models).unwrap();
        let archive = build_archive(
            &models,
            "kasumi",
            &[("live_default/model.json", "{\"v\":1}")],
        );
        let cache = ModelCache::new(dir.path().join("cache"), &models);
        let spec = "models/kasumi.zst::live_default/model.json";
        let resolved = cache.resolve(spec).unwrap();
        assert_eq!(
            fs::read_to_string(&resolved.model_path).unwrap(),
            "{\"v\":1}"
        );

        // Rewrite the archive with different content and a different size.
        fs::remove_file(&archive).unwrap();
        build_archive(
            &models,
            "kasumi",
            &[("live_default/model.json", "{\"v\":2,\"pad\":true}")],
        );
        let resolved = cache.resolve(spec).unwrap();
        assert!(fs::read_to_string(&resolved.model_path)
            .unwrap()
            .contains("\"v\":2"));
    }

    #[test]
    fn same_stem_archives_with_identical_stats_have_distinct_stamps() {
        let dir = tempfile::tempdir().unwrap();
        let bundled = dir.path().join("bundled");
        let user = dir.path().join("user");
        fs::create_dir_all(&bundled).unwrap();
        fs::create_dir_all(&user).unwrap();
        let original = build_archive(&bundled, "kasumi", &[("live/model.json", "original")]);
        let replacement = user.join("kasumi.zst");
        fs::copy(&original, &replacement).unwrap();
        let timestamp = UNIX_EPOCH + std::time::Duration::from_secs(100);
        for archive in [&original, &replacement] {
            fs::OpenOptions::new()
                .write(true)
                .open(archive)
                .unwrap()
                .set_modified(timestamp)
                .unwrap();
        }
        let cache = ModelCache::new(dir.path().join("cache"), &bundled);
        let resolved = cache
            .resolve(&format!("{}::live/model.json", original.display()))
            .unwrap();
        fs::write(&resolved.model_path, "stale").unwrap();
        let resolved = cache
            .resolve(&format!("{}::live/model.json", replacement.display()))
            .unwrap();
        assert_eq!(fs::read_to_string(resolved.model_path).unwrap(), "original");
    }

    #[test]
    fn extraction_refuses_traversal_members() {
        // `tar` itself refuses to *write* `..` members, so the guard is exercised
        // through the spec parser: a traversal path never reaches extraction.
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("models");
        fs::create_dir_all(&models).unwrap();
        build_archive(&models, "evil", &[("evil/model.json", "{}")]);
        let cache = ModelCache::new(dir.path().join("cache"), &models);
        let result = cache.resolve("models/evil.zst::evil/../../pwned.txt");
        assert!(matches!(result, Err(CacheError::Path(_))), "{result:?}");
        assert!(!dir.path().join("cache").join("pwned.txt").exists());
        assert!(!dir.path().join("pwned.txt").exists());
    }

    #[test]
    fn absolute_archive_paths_are_accepted() {
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("models");
        fs::create_dir_all(&models).unwrap();
        let archive = build_archive(&models, "kasumi", &[("live_default/model.json", "{}")]);
        let cache = ModelCache::new(dir.path().join("cache"), &models);
        let spec = format!("{}::live_default/model.json", archive.display());
        let resolved = cache.resolve(&spec).unwrap();
        assert!(resolved.model_path.exists());
    }
    #[test]
    fn lru_keeps_only_capacity_directories() {
        let dir = tempfile::tempdir().unwrap();
        let models = dir.path().join("models");
        fs::create_dir_all(&models).unwrap();
        let cache = ModelCache::new(dir.path().join("cache"), &models).with_capacity(2);
        for index in 0..4 {
            let key = format!("kasumi/live_{index}");
            let directory = cache
                .cache_root()
                .join("kasumi")
                .join(format!("live_{index}"));
            fs::create_dir_all(&directory).unwrap();
            cache.touch(&key);
        }
        cache.prune(None);
        let remaining = fs::read_dir(cache.cache_root().join("kasumi"))
            .unwrap()
            .flatten()
            .count();
        assert_eq!(remaining, 2);
    }
}
