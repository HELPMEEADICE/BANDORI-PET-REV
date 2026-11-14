use pet_ipc::level::{LevelPublisher, LevelReader};
use std::sync::{Arc, Barrier};

#[test]
fn stale_invalid_and_recovery() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("level");
    let mut writer = LevelPublisher::create(&path).unwrap();
    let reader = LevelReader::attach(&path).unwrap();
    assert_eq!(reader.level(1000), 0.0);
    writer.publish(0.7, 1000).unwrap();
    assert_eq!(reader.level(1100), 0.7);
    assert_eq!(reader.level(1251), 0.0);
    assert_eq!(reader.level(999), 0.0);
    for invalid in [f32::NAN, f32::INFINITY, -1.0] {
        writer.publish(invalid, 1300).unwrap();
        assert_eq!(reader.level(1300), 0.0);
    }
    writer.publish(0.9, 1400).unwrap();
    assert_eq!(reader.level(1400), 0.9);
    drop(writer);
    assert_eq!(reader.level(1651), 0.0);
    assert!(LevelPublisher::create(&path).is_err());
    drop(reader);
    assert!(!path.exists());
    assert!(LevelPublisher::create(&path).is_ok());
}

#[test]
fn many_consumers_observe_coherent_latest_samples() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("level");
    let mut writer = LevelPublisher::create(&path).unwrap();
    let barrier = Arc::new(Barrier::new(5));
    let readers: Vec<_> = (0..4)
        .map(|_| {
            let path = path.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                let reader = LevelReader::attach(&path).unwrap();
                barrier.wait();
                for _ in 0..2000 {
                    let peak = reader.level(1000);
                    assert!(peak == 0.0 || peak == 0.25 || peak == 0.75);
                }
            })
        })
        .collect();
    barrier.wait();
    for i in 0..2000 {
        writer
            .publish(if i % 2 == 0 { 0.25 } else { 0.75 }, 1000)
            .unwrap();
    }
    for reader in readers {
        reader.join().unwrap();
    }
}
