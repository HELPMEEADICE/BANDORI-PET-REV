use std::fs::OpenOptions;
use std::io::{Seek, SeekFrom, Write};
use std::sync::{Arc, Mutex};

use pet_ipc::{memory_size, Error, Queue};

fn patch(path: &std::path::Path, at: u64, bytes: &[u8]) {
    let mut file = OpenOptions::new().write(true).open(path).unwrap();
    fs2::FileExt::lock_exclusive(&file).unwrap();
    file.seek(SeekFrom::Start(at)).unwrap();
    file.write_all(bytes).unwrap();
    fs2::FileExt::unlock(&file).unwrap();
}

#[test]
fn layout_and_extent_limits() {
    assert_eq!(memory_size(2, 64).unwrap(), 28 + 2 * 76);
    assert!(memory_size(0, 64).is_err());
    assert!(memory_size(1, 63).is_err());
    assert!(memory_size(u32::MAX, u32::MAX).is_err());
}

#[test]
fn independent_cursors_overwrite_limits_and_utf8() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("queue");
    let mut writer = Queue::create(&path, 2, 64).unwrap();
    let mut first = Queue::attach(&path, false).unwrap();
    let mut second = Queue::attach(&path, false).unwrap();
    writer.publish("one").unwrap();
    writer.publish("中文・愛音🐈\n").unwrap();
    assert_eq!(first.read_available(Some(0)).unwrap(), Vec::<String>::new());
    assert_eq!(first.read_available(Some(1)).unwrap(), ["one"]);
    writer.publish("three").unwrap();
    assert_eq!(first.read().unwrap(), ["中文・愛音🐈", "three"]);
    assert_eq!(first.dropped_messages(), 0);
    assert_eq!(second.read().unwrap(), ["中文・愛音🐈", "three"]);
    assert_eq!(second.dropped_messages(), 1);
    assert!(matches!(writer.publish("\r\n"), Err(Error::Empty)));
    assert!(writer.publish(&"x".repeat(64)).is_ok());
    assert!(matches!(
        writer.publish(&"x".repeat(65)),
        Err(Error::Oversize(64))
    ));
}

#[test]
fn lifetime_surviving_reader_prevents_recreate_and_final_reader_cleans_up() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("queue");
    let mut owner = Queue::create(&path, 2, 64).unwrap();
    let mut reader = Queue::attach(&path, false).unwrap();
    assert!(matches!(Queue::create(&path, 1, 128), Err(Error::InUse)));
    owner.publish("survives").unwrap();
    owner.close().unwrap();
    owner.close().unwrap();
    assert!(owner.read().unwrap().is_empty());
    assert!(matches!(owner.publish("x"), Err(Error::Detached)));
    assert!(path.exists());
    assert!(matches!(Queue::create(&path, 1, 128), Err(Error::InUse)));
    assert_eq!(reader.read().unwrap(), ["survives"]);
    reader.close().unwrap();
    assert!(!path.exists());
    Queue::create(&path, 1, 128).unwrap().close().unwrap();
}

#[test]
fn malformed_headers_and_sequence_exhaustion_are_errors() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("queue");
    let mut queue = Queue::create(&path, 2, 64).unwrap();
    patch(&path, 20, &u64::MAX.to_le_bytes());
    assert!(matches!(
        queue.publish("last"),
        Err(Error::SequenceExhausted)
    ));
    patch(&path, 12, &u32::MAX.to_le_bytes());
    assert!(queue.publish("bad").is_err());
    assert!(queue.read().is_err());
    assert!(Queue::attach(&path, false).is_err());
    patch(&path, 12, &2u32.to_le_bytes());
    patch(&path, 8, &2u32.to_le_bytes());
    assert!(matches!(
        Queue::attach(&path, false),
        Err(Error::Version(2))
    ));
    patch(&path, 0, b"BADMAGIC");
    assert!(matches!(queue.read(), Err(Error::InvalidHeader)));
}

#[test]
fn corrupted_slots_count_loss_and_utf8_replaces() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("queue");
    let mut queue = Queue::create(&path, 2, 64).unwrap();
    queue.publish("a").unwrap();
    queue.publish("b").unwrap();
    patch(&path, 40, &[0xff]);
    patch(&path, 28 + 76 + 8, &u32::MAX.to_le_bytes());
    assert_eq!(queue.read().unwrap(), ["�"]);
    assert_eq!(queue.dropped_messages(), 1);
}

#[test]
fn threads_and_separate_handles_serialize_writes() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("queue");
    let queue = Arc::new(Mutex::new(Queue::create(&path, 1000, 64).unwrap()));
    let mut threads = Vec::new();
    for thread in 0..4 {
        let queue = Arc::clone(&queue);
        let path = path.clone();
        threads.push(std::thread::spawn(move || {
            let mut own = Queue::attach(&path, true).unwrap();
            for n in 0..100 {
                if thread % 2 == 0 {
                    own.publish(&format!("{thread}:{n}")).unwrap();
                } else {
                    queue
                        .lock()
                        .unwrap()
                        .publish(&format!("{thread}:{n}"))
                        .unwrap();
                }
            }
        }));
    }
    for thread in threads {
        thread.join().unwrap();
    }
    let lines = queue.lock().unwrap().read().unwrap();
    assert_eq!(lines.len(), 400);
    assert_eq!(
        lines
            .into_iter()
            .collect::<std::collections::HashSet<_>>()
            .len(),
        400
    );
}
