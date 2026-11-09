//! Non-graphical protocol peer for cross-language tests and reproducible probes.
use std::io::{self, BufRead, Write};
use std::path::Path;

use pet_ipc::Queue;
use serde_json::{json, Value};

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        return Err("usage: ipc_peer <create|attach> <path> [count size]".into());
    }
    let mut queue = match args[1].as_str() {
        "create" if args.len() == 5 => {
            Queue::create(Path::new(&args[2]), args[3].parse()?, args[4].parse()?)?
        }
        "attach" => Queue::attach(Path::new(&args[2]), false)?,
        _ => return Err("invalid operation".into()),
    };
    println!("{}", json!({"ready": true}));
    io::stdout().flush()?;
    for request in io::stdin().lock().lines() {
        let request: Value = serde_json::from_str(&request?)?;
        let response = match request["op"].as_str() {
            Some("publish") => {
                let line = request["line"].as_str().ok_or("line must be a string")?;
                match queue.publish(line) {
                    Ok(()) => json!({"ok": true}),
                    Err(e) => json!({"ok": false, "error": e.to_string()}),
                }
            }
            Some("read") => json!({"lines": queue.read()?, "dropped": queue.dropped_messages()}),
            Some("bench") => {
                let count = request["count"]
                    .as_u64()
                    .filter(|&n| n > 0 && n <= 1_000_000)
                    .ok_or("invalid count")?;
                let line = request["line"].as_str().ok_or("line must be a string")?;
                let mut samples = Vec::with_capacity(count as usize);
                let start = std::time::Instant::now();
                for _ in 0..count {
                    let before = std::time::Instant::now();
                    queue.publish(line)?;
                    let batch = queue.read()?;
                    if batch != [line] {
                        return Err("benchmark verification failed".into());
                    }
                    samples.push(before.elapsed().as_nanos() as u64);
                }
                let elapsed = start.elapsed().as_secs_f64();
                samples.sort_unstable();
                json!({"messages_per_second": count as f64 / elapsed,
                       "wall_seconds": elapsed,
                       "mean_us": samples.iter().map(|&n| n as f64).sum::<f64>() / count as f64 / 1000.0,
                       "p95_us": samples[(count as usize * 95 / 100).min(samples.len() - 1)] as f64 / 1000.0,
                       "p99_us": samples[(count as usize * 99 / 100).min(samples.len() - 1)] as f64 / 1000.0})
            }
            Some("close") => {
                queue.close()?;
                json!({"closed": true})
            }
            _ => return Err("unknown request".into()),
        };
        println!("{response}");
        io::stdout().flush()?;
    }
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        std::process::exit(1);
    }
}
