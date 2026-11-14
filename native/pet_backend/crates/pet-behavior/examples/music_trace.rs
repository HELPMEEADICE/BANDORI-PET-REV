//! Deterministic parity runner: stdin contains `peak dt` pairs (or `reset`).
use pet_behavior::music::MusicSpring;
use std::io::{self, BufRead};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut spring = MusicSpring::new();
    for line in io::stdin().lock().lines() {
        let line = line?;
        if line == "reset" {
            spring.reset();
            continue;
        }
        let mut values = line.split_whitespace().map(str::parse::<f64>);
        let peak = values.next().ok_or("missing peak")??;
        let dt = values.next().ok_or("missing dt")??;
        println!("{:.17}", spring.step(peak, dt));
    }
    Ok(())
}
