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
                    Err(pet_ipc::Error::InUse) => {
                        self.retry_at = Instant::now() + Duration::from_millis(16);
                    }
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

#[cfg(test)]
mod tests {
    use super::*;
    use pet_ipc::level::LevelPublisher;

    #[test]
    fn disable_releases_lease_and_new_generation_replaces_old_source() {
        let directory = tempfile::tempdir().unwrap();
        let first = directory.path().join("first");
        let next = directory.path().join("next");
        let mut a = LevelPublisher::create(&first).unwrap();
        let mut b = LevelPublisher::create(&next).unwrap();
        a.publish(0.75, timestamp_ms()).unwrap();
        b.publish(0.25, timestamp_ms()).unwrap();
        let mut source = MusicSource::new();
        source.replace(Some(first.clone()));
        assert_eq!(source.level(false), 0.0);
        assert!(source.reader.is_none());
        assert_eq!(source.level(true), 0.75);
        drop(a);
        source.replace(Some(next));
        assert!(!first.exists());
        assert_eq!(source.level(true), 0.25);
        assert_eq!(source.level(false), 0.0);
        assert!(source.reader.is_none());
        source.replace(None);
        assert_eq!(source.level(true), 0.0);
    }
}
