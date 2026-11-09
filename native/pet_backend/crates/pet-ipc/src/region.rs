//! Compatibility storage for old lock/data/unlock callers. Python receives a
//! transaction snapshot, never an unsafe buffer pointing into a live mapping.
use std::path::Path;

use fs2::FileExt;

use crate::storage::{Lock, Storage};
use crate::{Error, Result};

pub struct MappedRegion {
    storage: Storage,
    locked: bool,
}

impl MappedRegion {
    pub fn create(path: &Path, size: usize) -> Result<Self> {
        Ok(Self {
            storage: Storage::create_region(path, size, None)?,
            locked: false,
        })
    }

    pub fn attach(path: &Path) -> Result<Self> {
        Ok(Self {
            storage: Storage::attach_region(path, false)?,
            locked: false,
        })
    }

    /// Begin a transaction, returning a snapshot while retaining the OS lock.
    pub fn lock(&mut self) -> Result<Vec<u8>> {
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        if !self.locked {
            FileExt::lock_exclusive(file)?;
            self.locked = true;
        }
        Ok(self.storage.map.as_ref().ok_or(Error::Detached)?.to_vec())
    }

    pub fn snapshot(&self) -> Result<Vec<u8>> {
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        let _guard = if self.locked {
            None
        } else {
            Some(Lock::exclusive(file)?)
        };
        Ok(self.storage.map.as_ref().ok_or(Error::Detached)?.to_vec())
    }

    /// Commit a same-size transaction and release its OS lock even on failure.
    pub fn unlock(&mut self, bytes: &[u8]) -> Result<()> {
        let file = self.storage.file.as_ref().ok_or(Error::Detached)?;
        if !self.locked {
            return Err(Error::NotLocked);
        }
        let result = match self.storage.map.as_mut() {
            Some(map) if map.len() == bytes.len() => {
                map.copy_from_slice(bytes);
                Ok(())
            }
            _ => Err(Error::InvalidExtent),
        };
        self.locked = false;
        let unlock = FileExt::unlock(file).map_err(Error::Io);
        result.and(unlock)
    }

    pub fn close(&mut self) -> Result<()> {
        self.locked = false;
        self.storage.close()
    }
}
