//! Automatic blink / breath for Cubism 3+ models.
//!
//! `Moc2RuntimeModel::update` already blinks and breathes internally. For `.moc3`
//! Neocari exposes raw parameters only, so the LITE runtime reimplements the two
//! behaviors that the original pet had: an irregular blink every few seconds and
//! a slow breathing sway on `ParamBreath`.

use pet_util::Rng;

/// Blink phase of the automatic blink controller.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Phase {
    /// Eyes open, waiting for the next blink.
    Idle,
    /// Eyelids closing.
    Closing,
    /// Eyes shut (brief hold).
    Closed,
    /// Eyelids opening.
    Opening,
}

/// Drives `ParamEyeLOpen` / `ParamEyeROpen` and `ParamBreath`.
#[derive(Debug, Clone)]
pub struct BlinkBreath {
    enabled: bool,
    phase: Phase,
    phase_time: f32,
    next_blink_in: f32,
    open_amount: f32,
    breath_time: f32,
    breath_enabled: bool,
    rng: Rng,
}

impl BlinkBreath {
    /// Closing duration in seconds (Cubism's standard 0.1 s close + 0.05 s hold + 0.15 s open).
    const CLOSE_SECS: f32 = 0.10;
    /// Hold duration with the eyes shut.
    const HOLD_SECS: f32 = 0.05;
    /// Reopening duration.
    const OPEN_SECS: f32 = 0.15;
    /// Average interval between blinks.
    const MEAN_INTERVAL_SECS: f32 = 3.6;

    /// Creates a controller with default settings, seeded for deterministic tests.
    pub fn new(seed: u64) -> Self {
        let mut rng = Rng::seeded(seed);
        let next_blink_in = rng.range_f32(1.5, 5.0);
        Self {
            enabled: true,
            phase: Phase::Idle,
            phase_time: 0.0,
            next_blink_in,
            open_amount: 1.0,
            breath_time: 0.0,
            breath_enabled: true,
            rng,
        }
    }

    /// Enables or disables automatic blinking.
    pub fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
        if !enabled {
            self.phase = Phase::Idle;
            self.open_amount = 1.0;
        }
    }

    /// Enables or disables the breathing sway.
    pub fn set_breath_enabled(&mut self, enabled: bool) {
        self.breath_enabled = enabled;
    }

    /// Advances the controller and returns the current eyelid open amount (0..1)
    /// and breath value (0..1).
    pub fn tick(&mut self, delta_seconds: f32) -> BlinkOutput {
        let delta = delta_seconds.clamp(0.0, 0.1);

        if self.enabled {
            self.phase_time += delta;
            match self.phase {
                Phase::Idle => {
                    self.next_blink_in -= delta;
                    self.open_amount = 1.0;
                    if self.next_blink_in <= 0.0 {
                        self.phase = Phase::Closing;
                        self.phase_time = 0.0;
                    }
                }
                Phase::Closing => {
                    let progress = (self.phase_time / Self::CLOSE_SECS).clamp(0.0, 1.0);
                    self.open_amount = 1.0 - progress;
                    if progress >= 1.0 {
                        self.phase = Phase::Closed;
                        self.phase_time = 0.0;
                    }
                }
                Phase::Closed => {
                    self.open_amount = 0.0;
                    if self.phase_time >= Self::HOLD_SECS {
                        self.phase = Phase::Opening;
                        self.phase_time = 0.0;
                    }
                }
                Phase::Opening => {
                    let progress = (self.phase_time / Self::OPEN_SECS).clamp(0.0, 1.0);
                    self.open_amount = progress;
                    if progress >= 1.0 {
                        self.phase = Phase::Idle;
                        self.phase_time = 0.0;
                        // Occasionally double-blink, like the original pet's idle loop.
                        let double = self.rng.chance(0.15);
                        self.next_blink_in = if double {
                            0.18
                        } else {
                            self.rng.range_f32(
                                Self::MEAN_INTERVAL_SECS * 0.4,
                                Self::MEAN_INTERVAL_SECS * 1.6,
                            )
                        };
                    }
                }
            }
        }

        if self.breath_enabled {
            self.breath_time += delta;
        }
        let breath = 0.5 + 0.5 * (self.breath_time * 1.35).sin();

        BlinkOutput {
            eye_open: self.open_amount.clamp(0.0, 1.0),
            breath: if self.breath_enabled { breath } else { 0.0 },
        }
    }
}

/// Output of one [`BlinkBreath::tick`].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct BlinkOutput {
    /// Eyelid opening amount, `0.0` closed, `1.0` open.
    pub eye_open: f32,
    /// Breathing value in `0.0..=1.0`.
    pub breath: f32,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blinking_closes_and_reopens() {
        let mut blink = BlinkBreath::new(11);
        blink.set_breath_enabled(false);
        let mut minimum = 1.0f32;
        for _ in 0..600 {
            let output = blink.tick(1.0 / 60.0);
            minimum = minimum.min(output.eye_open);
        }
        assert!(minimum < 0.05, "eyes should fully close, got {minimum}");
    }

    #[test]
    fn disabled_blink_keeps_eyes_open() {
        let mut blink = BlinkBreath::new(3);
        blink.set_enabled(false);
        for _ in 0..600 {
            assert_eq!(blink.tick(1.0 / 60.0).eye_open, 1.0);
        }
    }

    #[test]
    fn breath_oscillates_within_unit_range() {
        let mut blink = BlinkBreath::new(5);
        blink.set_enabled(false);
        let mut minimum = f32::MAX;
        let mut maximum = f32::MIN;
        for _ in 0..600 {
            let breath = blink.tick(1.0 / 60.0).breath;
            minimum = minimum.min(breath);
            maximum = maximum.max(breath);
        }
        assert!(minimum >= 0.0 && maximum <= 1.0);
        assert!(maximum - minimum > 0.5, "breath should swing");
    }
}
