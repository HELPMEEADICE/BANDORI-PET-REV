//! Head tracking and mutual gaze (spec §2.7, constants verified in
//! `BANDORI-PET-REV-behavior-spec.md` §9).

use crate::BehaviorContext;

/// Where the character should look.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum GazeTarget {
    /// A screen-space point (peer window center).
    Screen((f32, f32)),
    /// A point in this window's local pixel space.
    Local((f32, f32)),
}

/// Maps cursor / peer positions onto the model's drag parameters.
#[derive(Debug, Clone, Default)]
pub struct HeadTracker {
    drag: (f32, f32),
    last_local: Option<(f32, f32)>,
    recenter_from: Option<(f32, f32)>,
    recenter_elapsed: f64,
    recentering: bool,
}

impl HeadTracker {
    /// Maximum tracking radius in pixels: beyond this the target is projected
    /// onto the circle instead of being ignored.
    pub const MAX_RADIUS: f32 = 600.0;
    /// Dead zone (squared): 4 px.
    pub const DEADZONE_SQ: f32 = 16.0;
    /// Recenter duration in seconds.
    pub const RECENTER_SECS: f64 = 0.3;

    /// Current drag value in normalized `-1..=1` coordinates.
    pub fn drag(&self) -> (f32, f32) {
        self.drag
    }

    /// Tracks a cursor position given in this window's local pixel space.
    pub fn track_local(
        &mut self,
        ctx: &BehaviorContext<'_>,
        cursor: (f32, f32),
    ) -> Option<(f32, f32)> {
        let (width, height) = (ctx.surface.0 as f32, ctx.surface.1 as f32);
        if width <= 0.0 || height <= 0.0 {
            return None;
        }
        let half_w = width * 0.5;
        let half_h = height * 0.5;

        let mut dx = cursor.0 - half_w;
        let mut dy = cursor.1 - half_h;
        let distance_sq = dx * dx + dy * dy;
        if distance_sq > Self::MAX_RADIUS * Self::MAX_RADIUS {
            let distance = distance_sq.sqrt();
            let factor = Self::MAX_RADIUS / distance;
            dx *= factor;
            dy *= factor;
        }

        if let Some((last_x, last_y)) = self.last_local {
            let delta_sq = (cursor.0 - last_x).powi(2) + (cursor.1 - last_y).powi(2);
            if delta_sq < Self::DEADZONE_SQ && !self.recentering {
                return None;
            }
        }
        self.last_local = Some(cursor);
        self.recentering = false;
        self.recenter_from = None;

        let drag = (
            (dx / self.scale_for(width)).clamp(-1.0, 1.0),
            // Screen y grows downwards, model y grows upwards.
            (-dy / self.scale_for(height)).clamp(-1.0, 1.0),
        );
        if (drag.0 - self.drag.0).abs() < 1e-4 && (drag.1 - self.drag.1).abs() < 1e-4 {
            return None;
        }
        self.drag = drag;
        Some(drag)
    }

    fn scale_for(&self, extent: f32) -> f32 {
        // Normalize against half the window extent so the 600 px clamp maps to a
        // sane [-1, 1] range even for tall pet windows.
        (extent * 0.5).max(1.0)
    }

    /// Looks at a gaze target (peer window center) instead of the cursor.
    pub fn gaze(
        &mut self,
        ctx: &BehaviorContext<'_>,
        target: GazeTarget,
        own_center: (f32, f32),
    ) -> Option<(f32, f32)> {
        let (width, height) = (ctx.surface.0 as f32, ctx.surface.1 as f32);
        if width <= 0.0 || height <= 0.0 {
            return None;
        }
        let local = match target {
            GazeTarget::Local(point) => point,
            GazeTarget::Screen(point) => (
                width * 0.5 + (point.0 - own_center.0),
                height * 0.5 + (point.1 - own_center.1),
            ),
        };
        self.last_local = None;
        self.recentering = false;
        self.recenter_from = None;
        let dx = (local.0 - width * 0.5) / (width * 0.5).max(1.0);
        let dy = -(local.1 - height * 0.5) / (height * 0.5).max(1.0);
        let drag = (dx.clamp(-1.0, 1.0), dy.clamp(-1.0, 1.0));
        if drag == self.drag {
            return None;
        }
        self.drag = drag;
        Some(drag)
    }

    /// Linearly recenters over `RECENTER_SECS`; returns a new drag value while
    /// the animation runs, and once at the end.
    pub fn recenter(&mut self, dt: f32) -> Option<(f32, f32)> {
        if self.drag == (0.0, 0.0) && !self.recentering {
            return None;
        }
        if !self.recentering {
            self.recentering = true;
            self.recenter_from = Some(self.drag);
            self.recenter_elapsed = 0.0;
            self.last_local = None;
        }
        self.recenter_elapsed += dt.max(0.0) as f64;
        let progress = (self.recenter_elapsed / Self::RECENTER_SECS).clamp(0.0, 1.0) as f32;
        let (from_x, from_y) = self.recenter_from.unwrap_or((0.0, 0.0));
        self.drag = (from_x * (1.0 - progress), from_y * (1.0 - progress));
        if progress >= 1.0 {
            self.drag = (0.0, 0.0);
            self.recentering = false;
            self.recenter_from = None;
        }
        Some(self.drag)
    }

    /// Snaps back to neutral (used when head tracking is switched off).
    pub fn recenter_immediately(&mut self) {
        self.drag = (0.0, 0.0);
        self.last_local = None;
        self.recentering = false;
        self.recenter_from = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn context<'a>(
        surface: (u32, u32),
        motion_names: &'a [String],
        expression_names: &'a [String],
    ) -> BehaviorContext<'a> {
        BehaviorContext {
            now: 1.0,
            dt: 1.0 / 60.0,
            cursor_local: None,
            surface,
            idle_seconds: 0.0,
            hour: 12,
            peer_center: None,
            own_center: (surface.0 as f32 / 2.0, surface.1 as f32 / 2.0),
            motion_names,
            expression_names,
            character: "kasumi",
            motion_finished: true,
        }
    }

    #[test]
    fn cursor_right_of_center_looks_right() {
        let motions: Vec<String> = vec![];
        let expressions: Vec<String> = vec![];
        let ctx = context((400, 500), &motions, &expressions);
        let mut tracker = HeadTracker::default();
        let drag = tracker.track_local(&ctx, (300.0, 250.0)).unwrap();
        assert!(drag.0 > 0.0, "cursor right should look right: {drag:?}");
        assert!(drag.1.abs() < 1e-6);
    }

    #[test]
    fn cursor_above_center_looks_up() {
        let motions: Vec<String> = vec![];
        let expressions: Vec<String> = vec![];
        let ctx = context((400, 500), &motions, &expressions);
        let mut tracker = HeadTracker::default();
        let drag = tracker.track_local(&ctx, (200.0, 100.0)).unwrap();
        assert!(drag.1 > 0.0, "cursor above should look up: {drag:?}");
    }

    #[test]
    fn dead_zone_ignores_tiny_moves() {
        let motions: Vec<String> = vec![];
        let expressions: Vec<String> = vec![];
        let ctx = context((400, 500), &motions, &expressions);
        let mut tracker = HeadTracker::default();
        assert!(tracker.track_local(&ctx, (300.0, 250.0)).is_some());
        // 1 px move stays inside the 4 px dead zone.
        assert!(tracker.track_local(&ctx, (301.0, 250.0)).is_none());
        // 20 px move updates.
        assert!(tracker.track_local(&ctx, (320.0, 250.0)).is_some());
    }

    #[test]
    fn far_cursor_is_projected_onto_the_radius() {
        let motions: Vec<String> = vec![];
        let expressions: Vec<String> = vec![];
        let ctx = context((400, 500), &motions, &expressions);
        let mut tracker = HeadTracker::default();
        let near = tracker.track_local(&ctx, (300.0, 250.0)).unwrap();
        let mut tracker = HeadTracker::default();
        let far = tracker.track_local(&ctx, (30_000.0, 250.0)).unwrap();
        assert!((near.0 - 0.5).abs() < 1e-6, "{near:?}");
        assert!(
            (far.0 - 1.0).abs() < 1e-6,
            "projected then clamped: {far:?}"
        );
    }

    #[test]
    fn recenter_returns_to_neutral() {
        let motions: Vec<String> = vec![];
        let expressions: Vec<String> = vec![];
        let ctx = context((400, 500), &motions, &expressions);
        let mut tracker = HeadTracker::default();
        tracker.track_local(&ctx, (300.0, 250.0)).unwrap();
        let mut last = (1.0, 0.0);
        for _ in 0..30 {
            if let Some(value) = tracker.recenter(1.0 / 60.0) {
                last = value;
            }
        }
        assert_eq!(last, (0.0, 0.0));
        assert_eq!(tracker.drag(), (0.0, 0.0));
    }
}
