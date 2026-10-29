//! Streaming archive reads shared by the catalog, Python bridge and renderer.
//! An index describes names, not seek offsets: a cold batch still decompresses
//! sequentially, but all its missing members are collected in one pass.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs::{self, File};
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::UNIX_EPOCH;

use crate::virtual_path::normalize_member;
use crate::{CacheError, ARCHIVE_INDEX_MEMBER};

pub const MAX_MEMBER_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_INDEX_BYTES: usize = 4 * 1024 * 1024;
const MAX_CACHE_ITEMS: usize = 512;
const MAX_CACHE_BYTES: usize = 64 * 1024 * 1024;
const MAX_INDEX_CACHE_BYTES: usize = 16 * 1024 * 1024;
const MAX_INDEX_CACHE_ITEMS: usize = 32;

/// File identity used for both resource and enumeration cache invalidation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ArchiveRevision {
    pub size: u64,
    pub mtime_ns: u128,
}

impl ArchiveRevision {
    pub fn read(path: &Path) -> Result<Self, CacheError> {
        let stat = fs::metadata(path).map_err(|e| io_error(path, e))?;
        let mtime_ns = stat
            .modified()
            .map_err(|e| io_error(path, e))?
            .duration_since(UNIX_EPOCH)
            .map_err(|e| CacheError::Io(e.to_string()))?
            .as_nanos();
        Ok(Self {
            size: stat.len(),
            mtime_ns,
        })
    }
}

#[derive(Debug)]
struct ByteEntry {
    archive: PathBuf,
    revision: ArchiveRevision,
    member: String,
    data: Arc<[u8]>,
}

#[derive(Debug)]
struct IndexEntry {
    archive: PathBuf,
    revision: ArchiveRevision,
    files: Vec<String>,
}

/// Bounded LRU of archive enumerations and resource bytes. The owner serializes
/// access (the C bridge uses one process-wide mutex); no Python byte cache exists.
#[derive(Debug, Default)]
pub struct ArchiveCache {
    bytes: VecDeque<ByteEntry>,
    byte_size: usize,
    indexes: VecDeque<IndexEntry>,
    #[cfg(test)]
    scans: usize,
}

pub(crate) type Stream = tar::Archive<zstd::stream::read::Decoder<'static, BufReader<File>>>;
pub type ResourceBatch = BTreeMap<String, Arc<[u8]>>;

pub(crate) fn open_archive(path: &Path) -> Result<Stream, CacheError> {
    let file = File::open(path).map_err(|e| io_error(path, e))?;
    let decoder =
        zstd::stream::read::Decoder::new(file).map_err(|e| CacheError::Zstd(e.to_string()))?;
    Ok(tar::Archive::new(decoder))
}

impl ArchiveCache {
    pub fn clear(&mut self) {
        self.bytes.clear();
        self.byte_size = 0;
        self.indexes.clear();
    }

    fn prepare(&mut self, archive: &Path) -> Result<(PathBuf, ArchiveRevision), CacheError> {
        let path = fs::canonicalize(archive).map_err(|e| io_error(archive, e))?;
        let revision = ArchiveRevision::read(&path)?;
        self.bytes
            .retain(|item| item.archive != path || item.revision == revision);
        self.byte_size = self.bytes.iter().map(|item| item.data.len()).sum();
        self.indexes
            .retain(|item| item.archive != path || item.revision == revision);
        Ok((path, revision))
    }

    fn open(&mut self, path: &Path) -> Result<Stream, CacheError> {
        #[cfg(test)]
        {
            self.scans += 1;
        }
        open_archive(path)
    }

    fn unchanged(&mut self, path: &Path, revision: ArchiveRevision) -> Result<(), CacheError> {
        if ArchiveRevision::read(path)? != revision {
            self.bytes.retain(|item| item.archive != path);
            self.byte_size = self.bytes.iter().map(|item| item.data.len()).sum();
            self.indexes.retain(|item| item.archive != path);
            return Err(CacheError::Io(format!(
                "archive changed during read: {}",
                path.display()
            )));
        }
        Ok(())
    }

    /// Uses a valid first-member index without scanning resource payloads.
    /// Malformed/oversized indexes fall back to tar enumeration.
    pub fn list_files(&mut self, archive: &Path) -> Result<Vec<String>, CacheError> {
        let (archive, revision) = self.prepare(archive)?;
        if let Some(position) = self.indexes.iter().position(|item| item.archive == archive) {
            let item = self.indexes.remove(position).unwrap();
            let files = item.files.clone();
            self.indexes.push_back(item);
            return Ok(files);
        }
        let mut tar = self.open(&archive)?;
        let mut files = Vec::new();
        for (position, entry) in tar.entries().map_err(tar_error)?.enumerate() {
            let mut entry = entry.map_err(tar_error)?;
            if !entry.header().entry_type().is_file() {
                continue;
            }
            let Some(name) = entry_name(&entry)? else {
                continue;
            };
            if position == 0 && name == ARCHIVE_INDEX_MEMBER {
                if let Ok(bytes) = read_entry_bytes(&mut entry, MAX_INDEX_BYTES) {
                    if let Some(index) = parse_index(&bytes) {
                        files = index;
                        break;
                    }
                }
                continue;
            }
            files.push(name);
        }
        files.sort();
        files.dedup();
        self.unchanged(&archive, revision)?;
        self.indexes.push_back(IndexEntry {
            archive,
            revision,
            files: files.clone(),
        });
        while self.indexes.len() > MAX_INDEX_CACHE_ITEMS
            || self
                .indexes
                .iter()
                .map(|item| item.files.iter().map(String::len).sum::<usize>())
                .sum::<usize>()
                > MAX_INDEX_CACHE_BYTES
        {
            self.indexes.pop_front();
        }
        Ok(files)
    }

    /// Missing resources are omitted. Duplicate paths use the first regular tar
    /// member, matching single-resource reads. Returned batches are also bounded.
    pub fn read_batch(
        &mut self,
        archive: &Path,
        members: &[String],
        cache: bool,
    ) -> Result<ResourceBatch, CacheError> {
        self.read_batch_impl(archive, members, cache, true)
    }

    pub fn prefetch(&mut self, archive: &Path, members: &[String]) -> Result<(), CacheError> {
        self.read_batch_impl(archive, members, true, false)?;
        Ok(())
    }

    fn read_batch_impl(
        &mut self,
        archive: &Path,
        members: &[String],
        cache: bool,
        return_data: bool,
    ) -> Result<ResourceBatch, CacheError> {
        let mut wanted: BTreeSet<String> = members
            .iter()
            .map(|name| normalize_member(name).map_err(|e| CacheError::Path(e.to_string())))
            .collect::<Result<_, _>>()?;
        if wanted.is_empty() {
            return Ok(BTreeMap::new());
        }
        let (archive, revision) = self.prepare(archive)?;
        let mut result = BTreeMap::new();
        let mut total = 0usize;
        if cache {
            for name in wanted.clone() {
                if let Some(position) = self
                    .bytes
                    .iter()
                    .position(|item| item.archive == archive && item.member == name)
                {
                    let item = self.bytes.remove(position).unwrap();
                    if return_data {
                        total = checked_batch_size(total, item.data.len())?;
                        result.insert(name.clone(), Arc::clone(&item.data));
                    }
                    wanted.remove(&name);
                    self.bytes.push_back(item);
                }
            }
        }
        if wanted.is_empty() {
            return Ok(result);
        }
        let mut tar = self.open(&archive)?;
        for entry in tar.entries().map_err(tar_error)? {
            let mut entry = entry.map_err(tar_error)?;
            if !entry.header().entry_type().is_file() {
                continue;
            }
            let Some(name) = entry_name(&entry)? else {
                continue;
            };
            if !wanted.remove(&name) {
                continue;
            }
            let data: Arc<[u8]> = read_entry_bytes(&mut entry, MAX_MEMBER_BYTES)?.into();
            if return_data {
                total = checked_batch_size(total, data.len())?;
                result.insert(name.clone(), Arc::clone(&data));
            }
            if cache {
                self.store(&archive, revision, name, data);
            }
            if wanted.is_empty() {
                break;
            }
        }
        self.unchanged(&archive, revision)?;
        Ok(result)
    }

    fn store(
        &mut self,
        archive: &Path,
        revision: ArchiveRevision,
        member: String,
        data: Arc<[u8]>,
    ) {
        self.byte_size += data.len();
        self.bytes.push_back(ByteEntry {
            archive: archive.to_owned(),
            revision,
            member,
            data,
        });
        while self.bytes.len() > MAX_CACHE_ITEMS || self.byte_size > MAX_CACHE_BYTES {
            self.byte_size -= self.bytes.pop_front().unwrap().data.len();
        }
    }
}

fn checked_batch_size(total: usize, next: usize) -> Result<usize, CacheError> {
    let total = total.saturating_add(next);
    if total > MAX_CACHE_BYTES {
        return Err(CacheError::TooLarge("resource batch".into()));
    }
    Ok(total)
}

fn parse_index(bytes: &[u8]) -> Option<Vec<String>> {
    let value: serde_json::Value = serde_json::from_slice(bytes).ok()?;
    let files = value.get("files")?.as_array()?;
    Some(
        files
            .iter()
            .filter_map(|item| normalize_member(item.as_str()?).ok())
            .collect(),
    )
}

pub(crate) fn entry_name<R: Read>(entry: &tar::Entry<'_, R>) -> Result<Option<String>, CacheError> {
    let path = entry.path().map_err(tar_error)?;
    Ok(path.to_str().and_then(|name| normalize_member(name).ok()))
}

pub(crate) fn read_entry_bytes<R: Read>(
    entry: &mut tar::Entry<'_, R>,
    limit: usize,
) -> Result<Vec<u8>, CacheError> {
    if entry.size() > limit as u64 {
        return Err(CacheError::TooLarge(
            entry
                .path()
                .map(|p| p.display().to_string())
                .unwrap_or_default(),
        ));
    }
    let mut bytes = Vec::new();
    entry
        .take(limit as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| CacheError::Io(e.to_string()))?;
    if bytes.len() > limit {
        return Err(CacheError::TooLarge("tar member".into()));
    }
    Ok(bytes)
}

fn io_error(path: &Path, error: std::io::Error) -> CacheError {
    CacheError::Io(format!("{}: {error}", path.display()))
}

fn tar_error(error: std::io::Error) -> CacheError {
    CacheError::Tar(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn build(path: &Path, index: Option<&[u8]>, members: &[(&str, &[u8])]) {
        let encoder = zstd::stream::write::Encoder::new(File::create(path).unwrap(), 1).unwrap();
        let mut tar = tar::Builder::new(encoder);
        if let Some(index) = index {
            append(&mut tar, ARCHIVE_INDEX_MEMBER, index);
        }
        for (name, bytes) in members {
            append(&mut tar, name, bytes);
        }
        tar.into_inner().unwrap().finish().unwrap();
    }

    fn append<W: std::io::Write>(tar: &mut tar::Builder<W>, name: &str, bytes: &[u8]) {
        let mut header = tar::Header::new_gnu();
        header.set_size(bytes.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        tar.append_data(&mut header, name, bytes).unwrap();
    }

    #[test]
    fn batch_and_warm_reads_scan_once() {
        let dir = tempfile::tempdir().unwrap();
        let archive = dir.path().join("model.zst");
        build(
            &archive,
            None,
            &[
                ("character.png", b"png"),
                ("live/model.json", b"{}"),
                ("live/model.json", b"duplicate"),
            ],
        );
        let mut cache = ArchiveCache::default();
        let requested = vec!["character.png".into(), "live/model.json".into()];
        let result = cache.read_batch(&archive, &requested, true).unwrap();
        assert_eq!(&*result["live/model.json"], b"{}");
        assert_eq!(cache.scans, 1);
        cache.read_batch(&archive, &requested, true).unwrap();
        assert_eq!(cache.scans, 1);
        cache
            .read_batch(&archive, &["character.png".into()], false)
            .unwrap();
        assert_eq!(cache.scans, 2, "cache=false bypasses retained bytes");
    }

    #[test]
    fn listing_uses_and_caches_index_and_falls_back_for_bad_indexes() {
        let dir = tempfile::tempdir().unwrap();
        let archive = dir.path().join("model.zst");
        let mut cache = ArchiveCache::default();
        // The embedded index is sufficient; these names need no payload reads.
        build(
            &archive,
            Some(br#"{"files":["z/model.json","../evil","C:/evil",12,"./a/model.json"]}"#),
            &[],
        );
        assert_eq!(
            cache.list_files(&archive).unwrap(),
            ["a/model.json", "z/model.json"]
        );
        cache.list_files(&archive).unwrap();
        assert_eq!(cache.scans, 1);
        build(
            &archive,
            Some(b"malformed JSON"),
            &[("live/model.json", b"{}")],
        );
        assert_eq!(cache.list_files(&archive).unwrap(), ["live/model.json"]);
        build(
            &archive,
            Some(&vec![b' '; MAX_INDEX_BYTES + 1]),
            &[("large/model.json", b"{}")],
        );
        assert_eq!(cache.list_files(&archive).unwrap(), ["large/model.json"]);
    }

    #[test]
    fn size_and_mtime_changes_invalidate_both_caches() {
        let dir = tempfile::tempdir().unwrap();
        let archive = dir.path().join("model.zst");
        build(&archive, None, &[("model.json", b"old")]);
        let mut cache = ArchiveCache::default();
        cache.list_files(&archive).unwrap();
        cache
            .read_batch(&archive, &["model.json".into()], true)
            .unwrap();
        // Same file size, changed timestamp: the previously read bytes must go.
        let size = fs::metadata(&archive).unwrap().len();
        fs::OpenOptions::new()
            .write(true)
            .open(&archive)
            .unwrap()
            .set_modified(UNIX_EPOCH + std::time::Duration::from_secs(100))
            .unwrap();
        cache
            .read_batch(&archive, &["model.json".into()], true)
            .unwrap();
        assert_eq!(fs::metadata(&archive).unwrap().len(), size);
        assert_eq!(cache.scans, 3);
        cache.list_files(&archive).unwrap();
        assert_eq!(cache.scans, 4);
        build(
            &archive,
            None,
            &[("model.json", b"new content"), ("extra", b"yes")],
        );
        let result = cache
            .read_batch(&archive, &["model.json".into()], true)
            .unwrap();
        assert_eq!(&*result["model.json"], b"new content");
        assert_eq!(cache.list_files(&archive).unwrap(), ["extra", "model.json"]);
    }

    #[test]
    fn lru_is_bounded_by_bytes_and_items() {
        let mut cache = ArchiveCache::default();
        let revision = ArchiveRevision {
            size: 0,
            mtime_ns: 0,
        };
        let bytes: Arc<[u8]> = vec![0; 1024 * 1024].into();
        for i in 0..65 {
            cache.store(
                Path::new("test"),
                revision,
                i.to_string(),
                Arc::clone(&bytes),
            );
        }
        assert_eq!(cache.byte_size, MAX_CACHE_BYTES);
        assert_eq!(cache.bytes.front().unwrap().member, "1");
        cache.clear();
        for i in 0..513 {
            cache.store(
                Path::new("test"),
                revision,
                i.to_string(),
                Arc::from(&b"x"[..]),
            );
        }
        assert_eq!(cache.bytes.len(), MAX_CACHE_ITEMS);
        assert_eq!(cache.bytes.front().unwrap().member, "1");
        assert!(checked_batch_size(MAX_CACHE_BYTES, 1).is_err());
    }

    #[test]
    fn metadata_prefetch_warms_portrait_and_manifest_in_one_pass() {
        let dir = tempfile::tempdir().unwrap();
        let archive = dir.path().join("model.zst");
        build(
            &archive,
            None,
            &[("character.png", b"png"), ("live/model.json", b"{}")],
        );
        let mut cache = ArchiveCache::default();
        let members = vec!["character.png".into(), "live/model.json".into()];
        cache.prefetch(&archive, &members).unwrap();
        assert_eq!(cache.scans, 1);
        cache.read_batch(&archive, &members, true).unwrap();
        assert_eq!(cache.scans, 1);
    }

    #[test]
    fn oversized_members_fail_before_allocating_and_links_are_not_resources() {
        let dir = tempfile::tempdir().unwrap();
        let archive = dir.path().join("model.zst");
        let mut header = tar::Header::new_gnu();
        header.set_path("large").unwrap();
        header.set_size(MAX_MEMBER_BYTES as u64 + 1);
        header.set_cksum();
        fs::write(
            &archive,
            zstd::encode_all(header.as_bytes().as_slice(), 1).unwrap(),
        )
        .unwrap();
        let mut cache = ArchiveCache::default();
        assert!(matches!(
            cache.read_batch(&archive, &["large".into()], true),
            Err(CacheError::TooLarge(_))
        ));

        let encoder =
            zstd::stream::write::Encoder::new(File::create(&archive).unwrap(), 1).unwrap();
        let mut tar = tar::Builder::new(encoder);
        let mut link = tar::Header::new_gnu();
        link.set_entry_type(tar::EntryType::Symlink);
        link.set_size(0);
        tar.append_link(&mut link, "model.json", "../outside")
            .unwrap();
        tar.into_inner().unwrap().finish().unwrap();
        assert!(cache.list_files(&archive).unwrap().is_empty());
        assert!(cache
            .read_batch(&archive, &["model.json".into()], true)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn requested_unsafe_paths_fail_before_opening_an_archive() {
        let mut cache = ArchiveCache::default();
        for name in [
            "../outside",
            "/abs",
            "./C:/abs",
            "x//y",
            "x/./y",
            "x/../y",
            "x:stream",
            "x\0y",
        ] {
            assert!(
                matches!(
                    cache.read_batch(Path::new("missing.zst"), &[name.into()], true),
                    Err(CacheError::Path(_))
                ),
                "{name}"
            );
        }
        assert_eq!(cache.scans, 0);
    }
}
