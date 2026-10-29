use std::time::{Duration, Instant};

pub(crate) struct FpsMeter {
    started: Instant,
    frames: u32,
    pub(crate) text: String,
}

impl FpsMeter {
    pub(crate) fn new(now: Instant) -> Self {
        Self {
            started: now,
            frames: 0,
            text: "FPS: --".into(),
        }
    }

    pub(crate) fn record(&mut self, now: Instant) -> bool {
        self.frames += 1;
        let elapsed = now.saturating_duration_since(self.started);
        if elapsed < Duration::from_secs(1) {
            return false;
        }
        self.text = format!("FPS: {:.1}", self.frames as f64 / elapsed.as_secs_f64());
        self.started = now;
        self.frames = 0;
        true
    }
}

// A small fixed bitmap keeps the overlay independent of system fonts.
fn glyph(c: char) -> [u8; 7] {
    match c {
        'F' => [31, 16, 16, 30, 16, 16, 16],
        'P' => [30, 17, 17, 30, 16, 16, 16],
        'S' => [15, 16, 16, 14, 1, 1, 30],
        '0' => [14, 17, 19, 21, 25, 17, 14],
        '1' => [4, 12, 4, 4, 4, 4, 14],
        '2' => [14, 17, 1, 2, 4, 8, 31],
        '3' => [30, 1, 1, 14, 1, 1, 30],
        '4' => [2, 6, 10, 18, 31, 2, 2],
        '5' => [31, 16, 16, 30, 1, 1, 30],
        '6' => [14, 16, 16, 30, 17, 17, 14],
        '7' => [31, 1, 2, 4, 8, 8, 8],
        '8' => [14, 17, 17, 14, 17, 17, 14],
        '9' => [14, 17, 17, 15, 1, 1, 14],
        ':' => [0, 4, 4, 0, 4, 4, 0],
        '.' => [0, 0, 0, 0, 0, 4, 4],
        '-' => [0, 0, 0, 31, 0, 0, 0],
        _ => [0; 7],
    }
}

pub(crate) fn rasterize(text: &str) -> (u32, u32, Vec<u8>) {
    let width = (text.chars().count() as u32 * 6 + 4) * 2;
    let height = 22;
    let mut pixels = vec![0; (width * height * 4) as usize];
    for px in pixels.chunks_exact_mut(4) {
        px.copy_from_slice(&[0, 0, 0, 170]);
    }
    for (index, c) in text.chars().enumerate() {
        for (y, row) in glyph(c).iter().enumerate() {
            for x in 0..5 {
                if row & (1 << (4 - x)) == 0 {
                    continue;
                }
                for dy in 0..2 {
                    for dx in 0..2 {
                        let px = 4 + index as u32 * 12 + x * 2 + dx;
                        let py = 4 + y as u32 * 2 + dy;
                        let offset = ((py * width + px) * 4) as usize;
                        pixels[offset..offset + 4].copy_from_slice(&[255, 255, 255, 255]);
                    }
                }
            }
        }
    }
    (width, height, pixels)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn meter_counts_presented_frames_over_elapsed_time() {
        let start = Instant::now();
        let mut meter = FpsMeter::new(start);
        assert!(!meter.record(start + Duration::from_millis(500)));
        assert!(meter.record(start + Duration::from_secs(1)));
        assert_eq!(meter.text, "FPS: 2.0");
        assert!(meter.record(start + Duration::from_secs(3)));
        assert_eq!(meter.text, "FPS: 0.5");
    }
    #[test]
    fn raster_contains_readable_foreground_and_background() {
        let (width, height, pixels) = rasterize("FPS: 60.0");
        assert_eq!(pixels.len(), (width * height * 4) as usize);
        assert!(pixels.chunks_exact(4).any(|p| p == [255, 255, 255, 255]));
        assert!(pixels.chunks_exact(4).any(|p| p == [0, 0, 0, 170]));
    }
}
