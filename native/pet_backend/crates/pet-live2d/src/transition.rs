//! Cross-fades between poses when a motion starts, ends, or is replaced.
//!
//! A [`MotionPlayer`](neocari::motion::MotionPlayer) writes its clip straight into
//! the parameter state: the first frame of the new clip lands at full weight and
//! every parameter the clip does not animate falls back to the model default.
//! Replacing a running clip, or dropping one that just ended, therefore reads as a
//! hard cut between poses.
//!
//! [`PoseTransition`] keeps the pose that was on screen and eases it into the live
//! pose over a short window. The blend runs before the tracking/blink overrides, so
//! head tracking stays immediate, and it covers part opacities as well, so a clip
//! that hides a part cannot pop it back.

use neocari::json::easing_sine;

/// Default cross-fade length for motion changes, in seconds.
///
/// Short enough to keep a click responsive, long enough that a one-frame step is
/// roughly a tenth of the pose difference instead of all of it.
pub const DEFAULT_POSE_FADE_SECONDS: f32 = 0.28;

/// A pose that is being eased into the live pose.
///
/// [`begin`](Self::begin) snapshots the values that are currently on screen;
/// [`advance`](Self::advance) returns the blend weight for this frame; the
/// `blend_*` helpers interpolate one target at a time.
#[derive(Debug, Clone)]
pub struct PoseTransition {
    duration: f32,
    elapsed: f32,
    from_parameters: Vec<f32>,
    from_part_opacities: Vec<Option<f32>>,
    active: bool,
}

impl Default for PoseTransition {
    fn default() -> Self {
        Self::new(DEFAULT_POSE_FADE_SECONDS)
    }
}

impl PoseTransition {
    /// Creates a transition that spreads over `duration_seconds`.
    ///
    /// A duration of `0.0` disables the blend, i.e. motions switch instantly.
    pub fn new(duration_seconds: f32) -> Self {
        Self {
            duration: duration_seconds.max(0.0),
            elapsed: 0.0,
            from_parameters: Vec::new(),
            from_part_opacities: Vec::new(),
            active: false,
        }
    }

    /// Cross-fade length in seconds.
    pub fn duration(&self) -> f32 {
        self.duration
    }

    /// Replaces the cross-fade length; `0.0` disables it.
    pub fn set_duration(&mut self, seconds: f32) {
        self.duration = seconds.max(0.0);
        if self.duration <= 0.0 {
            self.cancel();
        }
    }

    /// Whether a pose is currently being blended.
    pub fn is_active(&self) -> bool {
        self.active
    }

    /// Captures `parameters` and `part_opacities` as the pose to blend from.
    pub fn begin(&mut self, parameters: &[f32], part_opacities: &[Option<f32>]) {
        if self.duration <= 0.0 || (parameters.is_empty() && part_opacities.is_empty()) {
            self.cancel();
            return;
        }
        self.elapsed = 0.0;
        self.from_parameters.clear();
        self.from_parameters.extend_from_slice(parameters);
        self.from_part_opacities.clear();
        self.from_part_opacities.extend_from_slice(part_opacities);
        self.active = true;
    }

    /// Drops the blend, leaving the live pose untouched.
    pub fn cancel(&mut self) {
        self.active = false;
        self.elapsed = 0.0;
        self.from_parameters.clear();
        self.from_part_opacities.clear();
    }

    /// Advances the blend and returns this frame's weight in `0.0..1.0`, or
    /// `None` when nothing is being blended (including the frame that completes).
    pub fn advance(&mut self, delta_seconds: f32) -> Option<f32> {
        if !self.active {
            return None;
        }
        self.elapsed += delta_seconds.max(0.0);
        let progress = self.elapsed / self.duration;
        if progress >= 1.0 {
            self.cancel();
            return None;
        }
        Some(easing_sine(progress))
    }

    /// Interpolates one parameter from the captured pose towards `live`.
    pub fn blend_parameter(&self, index: usize, live: f32, weight: f32) -> f32 {
        match self.from_parameters.get(index) {
            Some(from) => from + (live - from) * weight,
            None => live,
        }
    }

    /// Interpolates one part opacity.
    ///
    /// A part that the new clip leaves alone returns to fully visible; `None` is
    /// reported once it is back at `1.0` so the caller can keep the override
    /// cleared.
    pub fn blend_part_opacity(&self, index: usize, live: Option<f32>, weight: f32) -> Option<f32> {
        let from = self
            .from_part_opacities
            .get(index)
            .copied()
            .flatten()
            .unwrap_or(1.0);
        let target = live.unwrap_or(1.0);
        let value = from + (target - from) * weight;
        if live.is_none() && (value - 1.0).abs() <= f32::EPSILON {
            None
        } else {
            Some(value)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn weight_starts_at_zero_and_finishes_after_the_duration() {
        let mut transition = PoseTransition::new(0.5);
        transition.begin(&[10.0], &[]);
        assert!(transition.is_active());
        // The first frame is still (almost) the captured pose.
        let first = transition.advance(0.0).expect("active");
        assert!(first.abs() < 1e-6, "{first}");
        let middle = transition.advance(0.25).expect("halfway");
        assert!((middle - 0.5).abs() < 1e-6, "{middle}");
        assert!(transition.advance(0.25).is_none());
        assert!(!transition.is_active());
    }

    #[test]
    fn blending_runs_from_the_captured_pose_to_the_live_pose() {
        let mut transition = PoseTransition::new(0.2);
        transition.begin(&[0.0, 100.0], &[Some(0.0)]);

        assert_eq!(transition.blend_parameter(0, 10.0, 0.0), 0.0);
        assert_eq!(transition.blend_parameter(0, 10.0, 0.5), 5.0);
        assert_eq!(transition.blend_parameter(0, 10.0, 1.0), 10.0);
        // Parameters the capture does not cover are passed through untouched.
        assert_eq!(transition.blend_parameter(7, 3.5, 0.5), 3.5);
    }

    #[test]
    fn hidden_parts_fade_back_to_visible() {
        let mut transition = PoseTransition::new(0.2);
        transition.begin(&[], &[Some(0.0), None]);
        assert_eq!(transition.blend_part_opacity(0, None, 0.5), Some(0.5));
        assert_eq!(transition.blend_part_opacity(1, Some(0.25), 0.0), Some(1.0));
        assert_eq!(transition.blend_part_opacity(1, None, 1.0), None);
    }

    #[test]
    fn a_zero_duration_disables_blending() {
        let mut transition = PoseTransition::new(0.0);
        transition.begin(&[1.0], &[]);
        assert!(!transition.is_active());
        assert!(transition.advance(1.0 / 60.0).is_none());
    }

    #[test]
    fn cancelling_clears_the_captured_pose() {
        let mut transition = PoseTransition::new(0.2);
        transition.begin(&[5.0], &[Some(0.0)]);
        transition.cancel();
        assert!(!transition.is_active());
        assert_eq!(transition.blend_parameter(0, 9.0, 0.5), 9.0);
        assert_eq!(transition.blend_part_opacity(0, None, 0.5), None);
    }
}
