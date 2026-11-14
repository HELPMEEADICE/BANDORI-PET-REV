//! Render-side latest-value consumer. No sampler or worker per role process.
use pet_ipc::level::{timestamp_ms, LevelReader};
use std::path::PathBuf;
use std::time::{Duration, Instant};

pub struct MusicSource {
    path: Option<PathBuf>,
    reader: Option<LevelReader>,
    retry_at: Instant,
}

impl MusicSource {
    pub fn new() -> Self {
        Self {
            path: None,
            reader: None,
            retry_at: Instant::now(),
        }
    }

    pub fn replace(&mut self, path: Option<PathBuf>) {
        if self.path != path {
            self.reader = None;
            self.path = path;
            self.retry_at = Instant::now();
        }
    }

    pub fn level(&mut self, active: bool) -> f64 {
        if !active {
            self.reader = None;
            return 0.0;
        }
        if self.reader.is_none() && Instant::now() >= self.retry_at {
            if let Some(path) = &self.path {
                match LevelReader::attach(path) {
                    Ok(reader) => self.reader = Some(reader),
                    Err(error) => {
                        eprintln!("music level source unavailable: {error}");
                        self.retry_at = Instant::now() + Duration::from_secs(1);
                    }
                }
            }
        }
        self.reader
            .as_ref()
            .map_or(0.0, |reader| f64::from(reader.level(timestamp_ms())))
    }
}
