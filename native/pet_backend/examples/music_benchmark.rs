//! Headless render-loop cost/resource probe. Deliberately excludes model/GPU cost.
use pet_behavior::music::MusicSpring;
use pet_ipc::level::{timestamp_ms, LevelReader};
use std::hint::black_box;
use std::path::Path;
use std::time::{Duration, Instant};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).is_some_and(|s| s == "physics") {
        let mut spring = MusicSpring::new();
        let count = 1_000_000;
        let start = Instant::now();
        for i in 0..count {
            black_box(spring.step(
                black_box(if i % 30 < 5 { 0.8 } else { 0.0 }),
                black_box(1.0 / 60.0),
            ));
        }
        println!(
            "{}",
            serde_json::json!({"updates":count,"mean_physics_ns":start.elapsed().as_nanos() as f64 / f64::from(count)})
        );
        return Ok(());
    }
    let path = args.get(1).ok_or("missing mapping path")?;
    let seconds: f64 = args.get(2).ok_or("missing seconds")?.parse()?;
    let fps: f64 = args.get(3).ok_or("missing fps")?.parse()?;
    let active = path != "disabled";
    let reader = if active {
        Some(LevelReader::attach(Path::new(path))?)
    } else {
        None
    };
    let mut spring = MusicSpring::new();
    let (mut frames, mut read_ns, mut physics_ns) = (0_u64, 0_u128, 0_u128);
    let start = Instant::now();
    let mut previous = start;
    while start.elapsed().as_secs_f64() < seconds {
        let now = Instant::now();
        let peak = reader
            .as_ref()
            .map_or(0.0, |r| f64::from(r.level(timestamp_ms())));
        let read = Instant::now();
        black_box(spring.update(active, peak, now.duration_since(previous).as_secs_f64()));
        physics_ns += read.elapsed().as_nanos();
        read_ns += read.duration_since(now).as_nanos();
        previous = now;
        frames += 1;
        let next = start + Duration::from_secs_f64(frames as f64 / fps);
        std::thread::sleep(next.saturating_duration_since(Instant::now()));
    }
    println!(
        "{}",
        serde_json::json!({"frames":frames,"mean_read_ns":read_ns as f64 / frames as f64,
        "mean_physics_ns":physics_ns as f64 / frames as f64})
    );
    Ok(())
}
