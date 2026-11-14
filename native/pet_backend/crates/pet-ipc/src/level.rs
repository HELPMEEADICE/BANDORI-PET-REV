//! Single-producer, many-reader latest output level, version 1, 40 bytes LE:
//! magic[8], version:u32, committed:u32, sequence:u64, unix_ms:u64,
//! peak:f32, reserved:u32. Never cast mapped bytes to a Rust struct or float.
//! OS data locks + acquire/release fences serialize access across processes.
//! The commit flag is cleared first so a killed writer cannot expose a torn slot.
//! Readers never wait on the writer; contention/malformed/stale data means silence.
//! Storage's owner/lease protocol prevents resize while any consumer is mapped.
use std::path::Path;
use std::sync::atomic::{fence, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::protocol::integer;
use crate::storage::{Lock, Storage};
use crate::{Error, Result};

const MAGIC: &[u8; 8] = b"BDLEVEL!";
const SIZE: usize = 40;
pub const MAX_AGE_MS: u64 = 250;

pub fn timestamp_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or(0)
}

fn validate(bytes: &[u8]) -> Result<()> {
    if bytes.len() != SIZE || bytes.get(..8) != Some(MAGIC.as_slice()) {
        return Err(Error::InvalidHeader);
    }
    let version = u32::from_le_bytes(integer(bytes, 8)?);
    if version != 1 {
        return Err(Error::Version(version));
    }
    Ok(())
}

pub struct LevelPublisher {
    storage: Storage,
    sequence: u64,
}

impl LevelPublisher {
    pub fn create(path: &Path) -> Result<Self> {
        let mut storage = Storage::create_region(path, SIZE, None)?;
        let file = storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = Lock::exclusive(file)?;
        let map = storage.map.as_mut().ok_or(Error::Detached)?;
        map[..8].copy_from_slice(MAGIC);
        map[8..12].copy_from_slice(&1u32.to_le_bytes());
        drop(_lock);
        Ok(Self {
            storage,
            sequence: 0,
        })
    }

    /// False means contention: this replaceable sample was intentionally dropped.
    pub fn publish(&mut self, peak: f32, sampled_at_ms: u64) -> Result<bool> {
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = match Lock::try_exclusive(file) {
            Ok(lock) => lock,
            Err(Error::InUse) => return Ok(false),
            Err(e) => return Err(e),
        };
        let map = self.storage.map.as_mut().ok_or(Error::Detached)?;
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or(Error::SequenceExhausted)?;
        map[12..16].copy_from_slice(&0u32.to_le_bytes());
        fence(Ordering::Release);
        map[16..24].copy_from_slice(&self.sequence.to_le_bytes());
        map[24..32].copy_from_slice(&sampled_at_ms.to_le_bytes());
        let peak = if peak.is_finite() {
            peak.clamp(0.0, 1.0)
        } else {
            0.0
        };
        map[32..36].copy_from_slice(&peak.to_le_bytes());
        fence(Ordering::Release);
        map[12..16].copy_from_slice(&1u32.to_le_bytes());
        Ok(true)
    }
}

pub struct LevelReader {
    storage: Storage,
}

impl LevelReader {
    pub fn attach(path: &Path) -> Result<Self> {
        let storage = Storage::try_attach_region(path)?;
        let file = storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = Lock::try_exclusive(file)?;
        validate(storage.map.as_ref().ok_or(Error::Detached)?)?;
        drop(_lock);
        Ok(Self { storage })
    }

    /// No allocations or blocking data lock on the render path. Caller may use
    /// an injected timestamp for deterministic expiry/recovery tests.
    pub fn level(&self, now_ms: u64) -> f32 {
        self.sample(now_ms).unwrap_or(0.0)
    }

    fn sample(&self, now_ms: u64) -> Result<f32> {
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        let _lock = Lock::try_exclusive(file)?;
        fence(Ordering::Acquire);
        let map = self.storage.map.as_ref().ok_or(Error::Detached)?;
        validate(map)?;
        let committed = u32::from_le_bytes(integer(map, 12)?);
        let sequence = u64::from_le_bytes(integer(map, 16)?);
        let stamp = u64::from_le_bytes(integer(map, 24)?);
        let peak = f32::from_le_bytes(integer(map, 32)?);
        let fresh = now_ms
            .checked_sub(stamp)
            .is_some_and(|age| age <= MAX_AGE_MS);
        Ok(
            if committed == 1 && sequence != 0 && stamp != 0 && fresh && peak.is_finite() {
                peak.clamp(0.0, 1.0)
            } else {
                0.0
            },
        )
    }
}
