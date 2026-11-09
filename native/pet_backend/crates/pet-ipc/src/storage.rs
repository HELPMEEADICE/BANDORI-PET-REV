//! Stable lifetime locks are separate from the legacy data-file transaction lock.
use std::fs::{File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};

use fs2::FileExt;
use memmap2::MmapMut;

use crate::protocol::{Header, MAX_MAPPING_SIZE};
use crate::{Error, Result};

pub(crate) fn sidecar(path: &Path, suffix: &str) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(suffix);
    PathBuf::from(name)
}

pub(crate) fn open(path: &Path, create: bool) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options
        .read(true)
        .write(true)
        .create(create)
        .truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)
}

pub(crate) struct Lock<'a>(&'a File);

impl<'a> Lock<'a> {
    pub fn exclusive(file: &'a File) -> io::Result<Self> {
        FileExt::lock_exclusive(file)?;
        Ok(Self(file))
    }
}

impl Drop for Lock<'_> {
    fn drop(&mut self) {
        // Closing the handle is the final OS-level fallback if unlocking fails.
        let _ = FileExt::unlock(self.0);
    }
}

pub(crate) struct Storage {
    pub map: Option<MmapMut>,
    pub file: Option<File>,
    lease: Option<File>,
    owner: Option<File>,
    path: PathBuf,
}

impl Storage {
    pub fn create(path: &Path, header: Header, size: usize) -> Result<Self> {
        Self::create_region(path, size, Some(header))
    }

    pub fn create_region(path: &Path, size: usize, header: Option<Header>) -> Result<Self> {
        if !(1..=MAX_MAPPING_SIZE).contains(&size) {
            return Err(Error::InvalidExtent);
        }
        let owner = open(&sidecar(path, ".owner"), true)?;
        FileExt::try_lock_exclusive(&owner).map_err(|e| {
            if e.kind() == io::ErrorKind::WouldBlock
                || e.raw_os_error() == fs2::lock_contended_error().raw_os_error()
            {
                Error::InUse
            } else {
                Error::Io(e)
            }
        })?;
        let lease = open(&sidecar(path, ".lease"), true)?;
        // Never truncate a crashed owner's queue while survivors still map it.
        FileExt::try_lock_exclusive(&lease).map_err(|_| Error::InUse)?;
        let file = open(path, true)?;
        let map = {
            let _lock = Lock::exclusive(&file)?;
            file.set_len(size as u64)?;
            // SAFETY: exclusive lease prevents resize/removal by every pet-ipc
            // participant. Data access is serialized by the legacy file lock.
            let mut map = unsafe { MmapMut::map_mut(&file)? };
            map.fill(0);
            if let Some(header) = header {
                header.encode(&mut map);
            }
            map
        };
        // Keep the owner locked during the exclusive -> shared transition.
        FileExt::unlock(&lease)?;
        FileExt::lock_shared(&lease)?;
        Ok(Self {
            map: Some(map),
            file: Some(file),
            lease: Some(lease),
            owner: Some(owner),
            path: path.into(),
        })
    }

    pub fn attach(path: &Path) -> Result<Self> {
        Self::attach_region(path, true)
    }

    pub fn attach_region(path: &Path, validate: bool) -> Result<Self> {
        let lease = open(&sidecar(path, ".lease"), true)?;
        FileExt::lock_shared(&lease)?;
        let file = open(path, false)?;
        let map = {
            let _lock = Lock::exclusive(&file)?;
            let length = file.metadata()?.len();
            if !(1..=MAX_MAPPING_SIZE as u64).contains(&length) {
                return Err(Error::InvalidExtent);
            }
            // SAFETY: see create(); retain the shared lease until after unmap.
            let map = unsafe { MmapMut::map_mut(&file)? };
            if validate {
                Header::decode(&map)?;
            }
            map
        };
        Ok(Self {
            map: Some(map),
            file: Some(file),
            lease: Some(lease),
            owner: None,
            path: path.into(),
        })
    }

    pub fn close(&mut self) -> Result<()> {
        if self.map.take().is_none() {
            return Ok(());
        }
        // Windows requires unmap and file close before unlink. Keep the lease
        // until both are finished, then acquire owner -> exclusive lease.
        self.file.take();
        self.lease.take();
        let owner = match self.owner.take() {
            Some(owner) => owner,
            None => {
                let candidate = open(&sidecar(&self.path, ".owner"), true)?;
                if FileExt::try_lock_exclusive(&candidate).is_err() {
                    return Ok(());
                }
                candidate
            }
        };
        let lease = open(&sidecar(&self.path, ".lease"), true)?;
        if FileExt::try_lock_exclusive(&lease).is_ok() {
            match std::fs::remove_file(&self.path) {
                Ok(()) => {}
                Err(e) if e.kind() == io::ErrorKind::NotFound => {}
                Err(e) => return Err(e.into()),
            }
        }
        drop(owner);
        // Never unlink sidecars: doing so splits the lock namespace on Unix.
        Ok(())
    }
}

impl Drop for Storage {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
