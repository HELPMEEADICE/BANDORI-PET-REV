//! The six emotion window displacements (spec §2.7).
//!
//! Keyframes, clamping formulas, durations and easing are copied from the Python
//! `_play_emotion_window_feedback` (see `BANDORI-PET-REV-behavior-spec.md` §5.3):
//! every value is a fraction of the duration, offsets are relative to the window
//! position when the animation started, and each segment is OutCubic-eased.

/// Which displacement to play.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WindowMotionKind {
    /// Nudge toward the cursor.
    Forward,
    /// Nudge away from the cursor.
    Back,
    /// Small jump.
    Hop,
    /// Horizontal jitter.
    Shake,
    /// Horizontal wobble with a vertical component.
    Wobble,
    /// Drop and return.
    Settle,
}

impl WindowMotionKind {
    /// Duration in milliseconds.
    pub fn duration_ms(self) -> f32 {
        match self {
            WindowMotionKind::Forward | WindowMotionKind::Back => 300.0,
            WindowMotionKind::Hop => 420.0,
            WindowMotionKind::Shake => 360.0,
            WindowMotionKind::Wobble => 420.0,
            WindowMotionKind::Settle => 340.0,
        }
    }

    /// `true` when the motion needs a cursor direction vector.
    pub fn needs_direction(self) -> bool {
        matches!(self, WindowMotionKind::Forward | WindowMotionKind::Back)
    }

    /// Config-independent name.
    pub fn key(self) -> &'static str {
        match self {
            WindowMotionKind::Forward => "forward",
            WindowMotionKind::Back => "back",
            WindowMotionKind::Hop => "hop",
            WindowMotionKind::Shake => "shake",
            WindowMotionKind::Wobble => "wobble",
            WindowMotionKind::Settle => "settle",
        }
    }
}

/// One running displacement animation.
#[derive(Debug, Clone)]
struct Running {
    #[allow(dead_code)]
    kind: WindowMotionKind,
    started_at: f64,
    duration_secs: f64,
    keyframes: Vec<(f32, (f32, f32))>,
}

/// Plays window displacements and yields integer offsets.
#[derive(Debug, Clone, Default)]
pub struct WindowMotionPlayer {
    running: Option<Running>,
    last: (i32, i32),
    finished_flag: bool,
}

impl WindowMotionPlayer {
    /// `true` while an animation is active.
    pub fn is_running(&self) -> bool {
        self.running.is_some()
    }

    /// `true` exactly once, on the tick after the animation ended.
    pub fn just_finished(&mut self) -> bool {
        std::mem::take(&mut self.finished_flag)
    }

    /// Current offset (used when the window is re-anchored mid-animation).
    pub fn offset(&self) -> (i32, i32) {
        self.last
    }

    /// Starts an animation. `direction` is only used by forward/back.
    pub fn start(
        &mut self,
        kind: WindowMotionKind,
        intensity: u8,
        now: f64,
        direction: (f32, f32),
    ) {
        let intensity = intensity as f32;
        let distance = (10.0 + intensity * 0.32).clamp(8.0, 42.0) as i32;
        let keyframes: Vec<(f32, (f32, f32))> = match kind {
            WindowMotionKind::Forward | WindowMotionKind::Back => {
                let (mut dx, mut dy) = direction;
                let length = (dx * dx + dy * dy).sqrt();
                if length < 8.0 {
                    (dx, dy) = (0.0, -1.0);
                } else {
                    dx /= length;
                    dy /= length;
                }
                if kind == WindowMotionKind::Back {
                    dx = -dx;
                    dy = -dy;
                }
                vec![
                    (0.0, (0.0, 0.0)),
                    (1.0, (dx * distance as f32, dy * distance as f32)),
                ]
            }
            WindowMotionKind::Hop => {
                let lift = (8.0 + intensity * 0.24).clamp(10.0, 34.0) as i32;
                let down = (lift / 5).max(2) as f32;
                vec![
                    (0.0, (0.0, 0.0)),
                    (0.38, (0.0, -(lift as f32))),
                    (0.72, (0.0, down)),
                    (1.0, (0.0, 0.0)),
                ]
            }
            WindowMotionKind::Shake => {
                let amp = (6.0 + intensity * 0.20).clamp(8.0, 26.0) as i32 as f32;
                vec![
                    (0.0, (0.0, 0.0)),
                    (0.18, (-amp, 0.0)),
                    (0.36, (amp, 0.0)),
                    (0.55, (-(amp / 2.0).round(), 0.0)),
                    (0.74, ((amp / 2.0).round(), 0.0)),
                    (1.0, (0.0, 0.0)),
                ]
            }
            WindowMotionKind::Wobble => {
                let amp = (4.0 + intensity * 0.12).clamp(5.0, 16.0) as i32 as f32;
                vec![
                    (0.0, (0.0, 0.0)),
                    (0.25, (amp, 2.0)),
                    (0.50, (-amp, -1.0)),
                    (0.75, ((amp / 2.0).round(), 0.0)),
                    (1.0, (0.0, 0.0)),
                ]
            }
            WindowMotionKind::Settle => {
                let drop = (2.0 + intensity * 0.08).clamp(3.0, 10.0) as i32 as f32;
                vec![(0.0, (0.0, 0.0)), (0.45, (0.0, drop)), (1.0, (0.0, 0.0))]
            }
        };
        self.running = Some(Running {
            kind,
            started_at: now,
            duration_secs: kind.duration_ms() as f64 / 1000.0,
            keyframes,
        });
        self.finished_flag = false;
    }

    /// Advances the animation; returns the new integer offset while running.
    pub fn tick(&mut self, now: f64) -> Option<(i32, i32)> {
        let running = self.running.as_ref()?;
        let elapsed = (now - running.started_at).max(0.0);
        let progress = (elapsed / running.duration_secs).clamp(0.0, 1.0) as f32;
        let offset = evaluate(&running.keyframes, progress);
        let rounded = (offset.0.round() as i32, offset.1.round() as i32);
        self.last = rounded;
        if progress >= 1.0 {
            self.running = None;
            self.finished_flag = true;
            self.last = (0, 0);
        }
        Some(rounded)
    }

    /// Stops the animation immediately.
    pub fn stop(&mut self) {
        self.running = None;
        self.finished_flag = true;
        self.last = (0, 0);
    }
}

/// OutCubic easing, matching `QEasingCurve.Type.OutCubic`.
pub fn out_cubic(t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    1.0 - (1.0 - t).powi(3)
}

/// Evaluates keyframes at `progress`, easing within the active segment.
fn evaluate(keyframes: &[(f32, (f32, f32))], progress: f32) -> (f32, f32) {
    if keyframes.is_empty() {
        return (0.0, 0.0);
    }
    if progress <= keyframes[0].0 {
        return keyframes[0].1;
    }
    for pair in keyframes.windows(2) {
        let (start_t, start_value) = pair[0];
        let (end_t, end_value) = pair[1];
        if progress <= end_t {
            let span = (end_t - start_t).max(1e-6);
            let local = out_cubic((progress - start_t) / span);
            return (
                start_value.0 + (end_value.0 - start_value.0) * local,
                start_value.1 + (end_value.1 - start_value.1) * local,
            );
        }
    }
    keyframes
        .last()
        .map(|(_, value)| *value)
        .unwrap_or((0.0, 0.0))
}

impl WindowMotionKind {
    /// Convenience: start with a screen-space cursor direction.
    pub fn from_emotion(emotion: &str) -> Option<Self> {
        Some(match emotion {
            "happy" | "excited" => WindowMotionKind::Hop,
            "angry" => WindowMotionKind::Forward,
            "shy" | "hurt" => WindowMotionKind::Back,
            "annoyed" => WindowMotionKind::Wobble,
            "surprised" => WindowMotionKind::Shake,
            "soft" | "sad" | "concerned" | "tired" => WindowMotionKind::Settle,
            _ => return None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hop_returns_to_the_origin() {
        let mut player = WindowMotionPlayer::default();
        player.start(WindowMotionKind::Hop, 64, 0.0, (0.0, -1.0));
        let mut peak = 0i32;
        for step in 0..30 {
            if let Some((_, y)) = player.tick(step as f64 * 0.016) {
                peak = peak.min(y);
            }
        }
        assert!(peak < 0, "hop lifts upward: {peak}");
        assert!(!player.is_running(), "the hop finished inside the loop");
        assert!(player.just_finished());
        assert_eq!(player.offset(), (0, 0));
    }

    #[test]
    fn shake_stays_within_amplitude() {
        let mut player = WindowMotionPlayer::default();
        player.start(WindowMotionKind::Shake, 100, 0.0, (0.0, -1.0));
        let mut max = 0i32;
        for step in 0..30 {
            if let Some((x, _)) = player.tick(step as f64 * 0.012) {
                max = max.max(x.abs());
            }
        }
        assert!(max <= 26, "shake amplitude is clamped: {max}");
    }

    #[test]
    fn intensity_scales_displacement() {
        let mut weak = WindowMotionPlayer::default();
        weak.start(WindowMotionKind::Settle, 20, 0.0, (0.0, -1.0));
        weak.tick(0.15);
        let weak_drop = weak.offset().1;

        let mut strong = WindowMotionPlayer::default();
        strong.start(WindowMotionKind::Settle, 100, 0.0, (0.0, -1.0));
        strong.tick(0.15);
        let strong_drop = strong.offset().1;
        assert!(strong_drop > weak_drop, "{strong_drop} vs {weak_drop}");
    }

    #[test]
    fn out_cubic_shape_matches_qt() {
        assert!((out_cubic(0.0) - 0.0).abs() < 1e-6);
        assert!((out_cubic(1.0) - 1.0).abs() < 1e-6);
        // OutCubic is fast at the start: half time covers 87.5% of the distance.
        assert!((out_cubic(0.5) - 0.875).abs() < 1e-6);
    }
}
