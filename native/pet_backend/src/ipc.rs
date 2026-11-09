//! Application routing over the shared pet-ipc core.
use std::io;
use std::path::Path;

use pet_ipc::{Envelope, Queue};

fn io_error(error: pet_ipc::Error) -> io::Error {
    io::Error::other(error)
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
        if paths.len() != 4 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "IPC needs four queue paths",
            ));
        }
        Ok(Self {
            inbound: Queue::attach(Path::new(&paths[0]), true).map_err(io_error)?,
            reliable: Queue::attach(Path::new(&paths[1]), true).map_err(io_error)?,
            broadcast: Queue::attach(Path::new(&paths[2]), true).map_err(io_error)?,
            control: Queue::attach(Path::new(&paths[3]), true).map_err(io_error)?,
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
        let result = if reliable {
            self.reliable.publish(&raw).map_err(io_error)
        } else {
            self.inbound.publish(&raw).map_err(io_error)
        };
        if reliable {
            if let Err(error) = &result {
                eprintln!("native IPC: reliable publish failed: {error}");
            }
        }
        result
    }

    pub fn read(&mut self) -> io::Result<Vec<String>> {
        // Process lifecycle/control messages after older lossy positions.
        let broadcast_drops = self.broadcast.dropped_messages();
        let control_drops = self.control.dropped_messages();
        let mut raw = self.broadcast.read().map_err(io_error)?;
        raw.extend(self.control.read().map_err(io_error)?);
        if self.broadcast.dropped_messages() > broadcast_drops {
            eprintln!(
                "native IPC: broadcast ring lost {} messages",
                self.broadcast.dropped_messages() - broadcast_drops
            );
        }
        if self.control.dropped_messages() > control_drops {
            // v1 has no acknowledgments. Never hide a control-lane overrun.
            eprintln!(
                "native IPC: CONTROL ring lost {} messages",
                self.control.dropped_messages() - control_drops
            );
        }
        Ok(raw
            .into_iter()
            .filter_map(|line| {
                let e: Envelope = match serde_json::from_str(&line) {
                    Ok(envelope) => envelope,
                    Err(error) => {
                        eprintln!("native IPC: invalid envelope: {error}");
                        return None;
                    }
                };
                (e.exclude != self.id).then_some(e.line)
            })
            .collect())
    }
}
