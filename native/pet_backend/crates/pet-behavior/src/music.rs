//! Audio envelopes and underdamped squash/stretch. Constants and operation order
//! match the frozen Python oracle in tests/baselines/music_spring.py.
//! f64 preserves Python arithmetic; only the final bounded scale becomes f32.

#[derive(Debug, Clone)]
pub struct MusicSpring {
    position: f64,
    velocity: f64,
    fast: f64,
    slow: f64,
    reference: f64,
    cooldown: f64,
}

impl Default for MusicSpring {
    fn default() -> Self {
        Self::new()
    }
}

impl MusicSpring {
    pub fn new() -> Self {
        Self {
            position: 0.0,
            velocity: 0.0,
            fast: 0.0,
            slow: 0.0,
            reference: 0.08,
            cooldown: 0.0,
        }
    }

    pub fn reset(&mut self) {
        *self = Self::new();
    }

    pub fn step(&mut self, peak: f64, dt: f64) -> f64 {
        if !dt.is_finite() || dt <= 0.0 {
            return self.position;
        }
        let dt = dt.min(0.1);
        let peak = if peak.is_finite() {
            peak.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let peak = if peak < 0.003 { 0.0 } else { peak };
        self.reference = 0.08_f64.max(peak).max(self.reference * (-dt / 2.0).exp());
        let level = (peak / self.reference).min(1.0);
        self.fast += (level - self.fast) * (1.0 - (-dt / 0.025).exp());
        self.slow += (level - self.slow) * (1.0 - (-dt / 0.22).exp());
        self.cooldown = (self.cooldown - dt).max(0.0);
        let attack = self.fast - self.slow;
        if peak != 0.0 && attack > 0.075 && self.cooldown <= 0.0 {
            self.velocity -= 4.0 + (attack * 3.0).min(1.0) * 6.0;
            self.cooldown = 0.18;
        }
        let target = -0.32 * self.fast;
        let steps = (dt * 240.0).ceil().max(1.0) as u32;
        let h = dt / f64::from(steps);
        for _ in 0..steps {
            self.velocity += (-225.0 * (self.position - target) - 6.9 * self.velocity) * h;
            self.position += self.velocity * h;
        }
        self.position = self.position.clamp(-1.6, 0.9);
        if peak == 0.0 && self.position.abs() < 0.001 && self.velocity.abs() < 0.01 {
            self.position = 0.0;
            self.velocity = 0.0;
        }
        self.position
    }

    pub fn scale(&self) -> f32 {
        (1.0 + self.position * 0.32).clamp(0.65, 1.20) as f32
    }

    /// Disabled/paused roles discard envelope and momentum immediately.
    pub fn update(&mut self, active: bool, peak: f64, dt: f64) -> f32 {
        if active {
            self.step(peak, dt);
        } else {
            self.reset();
        }
        self.scale()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn silence_and_noise_are_still() {
        let mut spring = MusicSpring::new();
        for _ in 0..120 {
            assert_eq!(spring.step(0.002, 1.0 / 60.0), 0.0);
        }
    }

    #[test]
    fn beats_rebound_and_settle_at_all_frame_rates() {
        for fps in [30, 60, 144] {
            let mut spring = MusicSpring::new();
            let (mut low, mut high) = (0.0_f64, 0.0_f64);
            for frame in 0..fps * 12 {
                let t = f64::from(frame) / f64::from(fps);
                let peak = if t < 8.0 && t % 0.5 < 0.08 { 0.7 } else { 0.0 };
                let x = spring.step(peak, 1.0 / f64::from(fps));
                assert!(x.is_finite() && (-1.6..=0.9).contains(&x));
                low = low.min(x);
                high = high.max(x);
            }
            assert!(low < -0.4 && high > 0.15);
            assert_eq!(spring.position, 0.0);
            assert_eq!(spring.velocity, 0.0);
        }
    }

    #[test]
    fn invalid_inputs_and_extreme_dt_remain_safe() {
        let mut spring = MusicSpring::new();
        for peak in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -1.0, 2.0] {
            for dt in [f64::NAN, f64::INFINITY, -1.0, 0.0, f64::MIN_POSITIVE, 10.0] {
                assert!(spring.step(peak, dt).is_finite());
                assert!((0.65..=1.20).contains(&spring.scale()));
            }
        }
        let previous = spring.position;
        assert_eq!(spring.step(1.0, f64::NAN), previous);
    }

    #[test]
    fn reset_disable_and_independent_roles() {
        let mut a = MusicSpring::new();
        let mut b = MusicSpring::new();
        for _ in 0..5 {
            a.update(true, 0.8, 1.0 / 60.0);
            b.update(true, 0.8, 1.0 / 60.0);
        }
        assert!(a.scale() < 0.85);
        assert_eq!(a.update(false, 0.8, 1.0 / 60.0), 1.0);
        assert!(b.scale() < 0.85);
        assert_eq!(
            a.step(0.8, 1.0 / 60.0),
            MusicSpring::new().step(0.8, 1.0 / 60.0)
        );
        b.reset();
        assert_eq!(b.scale(), 1.0);
        assert_eq!(b.reference, 0.08);
    }
}
