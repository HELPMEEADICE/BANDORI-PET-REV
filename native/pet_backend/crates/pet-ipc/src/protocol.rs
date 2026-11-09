//! BDIPC01! version 1. All integers are little endian; no native struct casts.
use serde::{Deserialize, Serialize};

use crate::{Error, Result};

pub const HEADER_SIZE: usize = 28;
pub const SLOT_HEADER_SIZE: usize = 12;
pub const MAGIC: &[u8; 8] = b"BDIPC01!";
pub const VERSION: u32 = 1;
// Bound mappings and allocations even on 64-bit hosts. Existing channels use < 3 MiB.
pub const MAX_MAPPING_SIZE: usize = 256 * 1024 * 1024;

#[derive(Clone, Copy, Debug)]
pub(crate) struct Header {
    pub count: u32,
    pub size: u32,
    pub next: u64,
}

pub fn memory_size(count: u32, size: u32) -> Result<usize> {
    if count == 0 || size < 64 {
        return Err(Error::InvalidExtent);
    }
    (size as usize)
        .checked_add(SLOT_HEADER_SIZE)
        .and_then(|stride| stride.checked_mul(count as usize))
        .and_then(|n| n.checked_add(HEADER_SIZE))
        .filter(|&n| n <= MAX_MAPPING_SIZE)
        .ok_or(Error::InvalidExtent)
}

pub(crate) fn integer<const N: usize>(bytes: &[u8], offset: usize) -> Result<[u8; N]> {
    bytes
        .get(offset..offset.checked_add(N).ok_or(Error::InvalidExtent)?)
        .and_then(|slice| slice.try_into().ok())
        .ok_or(Error::InvalidExtent)
}

impl Header {
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        if bytes.get(..8) != Some(MAGIC.as_slice()) {
            return Err(Error::InvalidHeader);
        }
        let version = u32::from_le_bytes(integer(bytes, 8)?);
        if version != VERSION {
            return Err(Error::Version(version));
        }
        let header = Self {
            count: u32::from_le_bytes(integer(bytes, 12)?),
            size: u32::from_le_bytes(integer(bytes, 16)?),
            next: u64::from_le_bytes(integer(bytes, 20)?),
        };
        if memory_size(header.count, header.size)? != bytes.len() {
            return Err(Error::InvalidExtent);
        }
        Ok(header)
    }

    pub fn encode(self, bytes: &mut [u8]) {
        // Only called on a validated mapping created with memory_size().
        bytes[..8].copy_from_slice(MAGIC);
        bytes[8..12].copy_from_slice(&VERSION.to_le_bytes());
        bytes[12..16].copy_from_slice(&self.count.to_le_bytes());
        bytes[16..20].copy_from_slice(&self.size.to_le_bytes());
        bytes[20..28].copy_from_slice(&self.next.to_le_bytes());
    }

    pub fn offset(self, seq: u64) -> usize {
        HEADER_SIZE
            + (seq % u64::from(self.count)) as usize * (SLOT_HEADER_SIZE + self.size as usize)
    }
}

/// JSON envelope used by all main channels. Routing remains in the applications.
#[derive(Default, Debug, Deserialize, Serialize)]
#[serde(default)]
pub struct Envelope {
    pub sender: String,
    pub exclude: String,
    pub line: String,
    pub message_id: String,
    pub reliable: bool,
}
