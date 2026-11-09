//! The single BDIPC01! shared-memory queue implementation for Python and Rust.
//!
//! A Queue owns an independent cursor. Use &mut access (or a Mutex) per handle;
//! separate handles/processes synchronize through OS file locks. No workers or
//! polling loops are created. The v1 ring is bounded and overwrites old entries.
mod protocol;
mod region;
mod storage;

use std::path::Path;

use protocol::{integer, Header};
pub use protocol::{
    memory_size, Envelope, HEADER_SIZE, MAGIC, MAX_MAPPING_SIZE, SLOT_HEADER_SIZE, VERSION,
};
pub use region::MappedRegion;
use storage::{Lock, Storage};

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("{0}")]
    Io(#[from] std::io::Error),
    #[error("queue already has a live owner or attached participants")]
    InUse,
    #[error("queue header is invalid")]
    InvalidHeader,
    #[error("unsupported queue version {0}")]
    Version(u32),
    #[error("queue extent is invalid (maximum 256 MiB)")]
    InvalidExtent,
    #[error("queue is detached")]
    Detached,
    #[error("empty payload")]
    Empty,
    #[error("payload exceeds {0} bytes")]
    Oversize(u32),
    #[error("queue sequence exhausted")]
    SequenceExhausted,
    #[error("queue sequence moved backwards")]
    SequenceReset,
    #[error("queue transaction is not locked")]
    NotLocked,
}

/// A mapped ring and independent reader cursor. close() is idempotent.
pub struct Queue {
    storage: Storage,
    count: u32,
    size: u32,
    cursor: u64,
    dropped: u64,
}

impl Queue {
    pub fn create(path: &Path, count: u32, size: u32) -> Result<Self> {
        let extent = memory_size(count, size)?;
        let storage = Storage::create(
            path,
            Header {
                count,
                size,
                next: 0,
            },
            extent,
        )?;
        Ok(Self {
            storage,
            count,
            size,
            cursor: 0,
            dropped: 0,
        })
    }

    pub fn attach(path: &Path, tail: bool) -> Result<Self> {
        let storage = Storage::attach(path)?;
        let file = storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = Lock::exclusive(file)?;
        let h = Header::decode(storage.map.as_ref().ok_or(Error::Detached)?)?;
        drop(_lock);
        Ok(Self {
            storage,
            count: h.count,
            size: h.size,
            cursor: if tail {
                h.next
            } else {
                h.next.saturating_sub(u64::from(h.count))
            },
            dropped: 0,
        })
    }

    pub fn slot_count(&self) -> u32 {
        self.count
    }
    pub fn slot_size(&self) -> u32 {
        self.size
    }
    pub fn cursor(&self) -> u64 {
        self.cursor
    }
    pub fn dropped_messages(&self) -> u64 {
        self.dropped
    }
    /// Reset diagnostic accounting, matching the legacy Python attribute.
    pub fn set_dropped_messages(&mut self, value: u64) {
        self.dropped = value;
    }
    pub fn is_attached(&self) -> bool {
        self.storage.map.is_some()
    }
    pub fn close(&mut self) -> Result<()> {
        self.storage.close()
    }

    /// Publish one UTF-8 line; the sequence counter is committed last. Exhaustion
    /// returns an error rather than wrapping into an ambiguous generation.
    pub fn publish(&mut self, line: &str) -> Result<()> {
        let line = line.trim_end_matches(['\r', '\n']);
        if line.is_empty() {
            return Err(Error::Empty);
        }
        if line.len() > self.size as usize {
            return Err(Error::Oversize(self.size));
        }
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = Lock::exclusive(file)?;
        let map = self.storage.map.as_mut().ok_or(Error::Detached)?;
        let h = Header::decode(map)?;
        if h.count != self.count || h.size != self.size {
            return Err(Error::InvalidExtent);
        }
        let next = h.next.checked_add(1).ok_or(Error::SequenceExhausted)?;
        let at = h.offset(h.next);
        // Invalidate the overwritten entry first so a killed publisher cannot
        // leave an old sequence pointing at partially replaced bytes.
        map[at + 8..at + 12].copy_from_slice(&0u32.to_le_bytes());
        std::sync::atomic::fence(std::sync::atomic::Ordering::Release);
        map[at + SLOT_HEADER_SIZE..at + SLOT_HEADER_SIZE + line.len()]
            .copy_from_slice(line.as_bytes());
        map[at..at + 8].copy_from_slice(&h.next.to_le_bytes());
        map[at + 8..at + 12].copy_from_slice(&(line.len() as u32).to_le_bytes());
        std::sync::atomic::fence(std::sync::atomic::Ordering::Release);
        map[20..28].copy_from_slice(&next.to_le_bytes());
        Ok(())
    }

    /// Read a batch with one OS lock. Bad slots are skipped and counted; invalid
    /// UTF-8 is replaced, matching Python's errors="replace" compatibility rule.
    pub fn read_available(&mut self, max_messages: Option<usize>) -> Result<Vec<String>> {
        if max_messages == Some(0) || !self.is_attached() {
            return Ok(Vec::new());
        }
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = Lock::exclusive(file)?;
        let map = self.storage.map.as_ref().ok_or(Error::Detached)?;
        let h = Header::decode(map)?;
        if h.count != self.count || h.size != self.size {
            return Err(Error::InvalidExtent);
        }
        if h.next < self.cursor {
            return Err(Error::SequenceReset);
        }
        let first = h.next.saturating_sub(u64::from(h.count));
        if self.cursor < first {
            self.dropped = self.dropped.saturating_add(first - self.cursor);
            self.cursor = first;
        }
        let mut lines = Vec::new();
        while self.cursor < h.next && max_messages.is_none_or(|limit| lines.len() < limit) {
            let at = h.offset(self.cursor);
            let seq = u64::from_le_bytes(integer(map, at)?);
            let len = u32::from_le_bytes(integer(map, at + 8)?) as usize;
            if seq == self.cursor && len > 0 && len <= h.size as usize {
                lines.push(
                    String::from_utf8_lossy(
                        &map[at + SLOT_HEADER_SIZE..at + SLOT_HEADER_SIZE + len],
                    )
                    .into_owned(),
                );
            } else {
                self.dropped = self.dropped.saturating_add(1);
            }
            self.cursor += 1;
        }
        Ok(lines)
    }

    pub fn read(&mut self) -> Result<Vec<String>> {
        self.read_available(None)
    }
}
