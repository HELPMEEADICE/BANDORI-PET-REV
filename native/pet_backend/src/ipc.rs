//! Byte-for-byte BDIPC01 queues shared with bandori_core.shared_memory_ipc.
use std::fs::{File, OpenOptions};
use std::io;
use std::path::Path;

use fs2::FileExt;
use memmap2::MmapMut;
use serde::{Deserialize, Serialize};

const HEADER: usize = 28;
const SLOT: usize = 12;

pub struct Queue {
    file: File,
    map: MmapMut,
    cursor: u64,
    pub dropped: u64,
}

impl Queue {
    pub fn attach(path: &Path, tail: bool) -> io::Result<Self> {
        let file = OpenOptions::new().read(true).write(true).open(path)?;
        // The creator fixes the extent before publishing the queue name and
        // retains its lifetime lock until all child processes are stopped.
        let map = unsafe { MmapMut::map_mut(&file)? };
        let mut result = Self {
            file,
            map,
            cursor: 0,
            dropped: 0,
        };
        result.file.lock_exclusive()?;
        let header = result.header();
        FileExt::unlock(&result.file)?;
        let (count, _, next) = header?;
        result.cursor = if tail {
            next
        } else {
            next.saturating_sub(count as u64)
        };
        Ok(result)
    }

    fn header(&self) -> io::Result<(usize, usize, u64)> {
        if self.map.len() < HEADER || &self.map[..8] != b"BDIPC01!" || self.u32(8) != 1 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid IPC header",
            ));
        }
        let count = self.u32(12) as usize;
        let size = self.u32(16) as usize;
        if count == 0
            || size < 64
            || count
                .checked_mul(SLOT + size)
                .and_then(|n| n.checked_add(HEADER))
                != Some(self.map.len())
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "invalid IPC extent",
            ));
        }
        Ok((count, size, self.u64(20)))
    }

    fn u32(&self, at: usize) -> u32 {
        u32::from_le_bytes(self.map[at..at + 4].try_into().unwrap())
    }
    fn u64(&self, at: usize) -> u64 {
        u64::from_le_bytes(self.map[at..at + 8].try_into().unwrap())
    }

    pub fn read(&mut self) -> io::Result<Vec<String>> {
        self.file.lock_exclusive()?;
        let result = self.read_locked();
        FileExt::unlock(&self.file)?;
        result
    }

    fn read_locked(&mut self) -> io::Result<Vec<String>> {
        let (count, size, next) = self.header()?;
        let first = next.saturating_sub(count as u64);
        if self.cursor < first {
            self.dropped += first - self.cursor;
            self.cursor = first;
        }
        let mut lines = Vec::new();
        while self.cursor < next {
            let at = HEADER + (self.cursor % count as u64) as usize * (SLOT + size);
            let len = self.u32(at + 8) as usize;
            if self.u64(at) == self.cursor && len > 0 && len <= size {
                lines.push(
                    String::from_utf8_lossy(&self.map[at + SLOT..at + SLOT + len]).into_owned(),
                );
            }
            self.cursor += 1;
        }
        Ok(lines)
    }

    pub fn publish(&mut self, line: &str) -> io::Result<()> {
        self.file.lock_exclusive()?;
        let result = self.publish_locked(line.trim_end_matches(['\r', '\n']));
        FileExt::unlock(&self.file)?;
        result
    }

    fn publish_locked(&mut self, line: &str) -> io::Result<()> {
        let (count, size, next) = self.header()?;
        if line.is_empty() || line.len() > size {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "IPC payload exceeds slot size",
            ));
        }
        let at = HEADER + (next % count as u64) as usize * (SLOT + size);
        self.map[at..at + 8].copy_from_slice(&next.to_le_bytes());
        self.map[at + 8..at + 12].copy_from_slice(&(line.len() as u32).to_le_bytes());
        self.map[at + SLOT..at + SLOT + line.len()].copy_from_slice(line.as_bytes());
        self.map[20..28].copy_from_slice(&(next + 1).to_le_bytes());
        Ok(())
    }
}

#[derive(Default, Deserialize, Serialize)]
#[serde(default)]
pub struct Envelope {
    pub sender: String,
    pub exclude: String,
    pub line: String,
    pub message_id: String,
    pub reliable: bool,
}

pub struct Bus {
    inbound: Queue,
    reliable: Queue,
    broadcast: Queue,
    control: Queue,
    pub id: String,
}

impl Bus {
    pub fn attach(paths: &[String]) -> io::Result<Self> {
        Ok(Self {
            inbound: Queue::attach(Path::new(&paths[0]), true)?,
            reliable: Queue::attach(Path::new(&paths[1]), true)?,
            broadcast: Queue::attach(Path::new(&paths[2]), true)?,
            control: Queue::attach(Path::new(&paths[3]), true)?,
            id: format!("native-pet-{}", std::process::id()),
        })
    }

    pub fn send(&mut self, line: &str, reliable: bool) -> io::Result<()> {
        let raw = serde_json::to_string(&Envelope {
            sender: self.id.clone(),
            line: line.into(),
            reliable,
            ..Default::default()
        })?;
        if reliable {
            self.reliable.publish(&raw)
        } else {
            self.inbound.publish(&raw)
        }
    }

    pub fn read(&mut self) -> io::Result<Vec<String>> {
        // Process lifecycle/control messages after older lossy positions.
        let mut raw = self.broadcast.read()?;
        raw.extend(self.control.read()?);
        Ok(raw
            .into_iter()
            .filter_map(|line| {
                let e: Envelope = serde_json::from_str(&line).ok()?;
                (e.exclude != self.id).then_some(e.line)
            })
            .collect())
    }
}
