//! Idle / random / time-of-day ambient motions (spec §2.7).
//!
//! Constants come from the original client (`BANDORI-PET-REV-behavior-spec.md`
//! §9): 5 s tick, 180 s ambient cooldown, 7 min daze, 18 min sleep, morning
//! 05:00–09:59 once per day, late night 23:00–04:59 after 90 s idle.

use pet_input::matching::{resolve_expression_by_tag, resolve_motion_by_tag};
use pet_util::Rng;
use tracing::trace;

use crate::BehaviorContext;

/// Why an ambient motion is being played.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AmbientKind {
    /// No ambient action this tick.
    None,
    /// Early-morning greeting, once per day.
    Morning,
    /// Long inactivity: sleep motions.
    Sleep,
    /// Late night, short idle: quieter motions.
    LateNight,
    /// 7+ minutes idle: dazed.
    Daze,
    /// Ordinary random action.
    Random,
}

impl AmbientKind {
    /// Motion tags tried in order.
    pub fn motion_tags(self) -> &'static [&'static str] {
        match self {
            AmbientKind::Morning => &["stretch", "akubi", "sigh", "smile", "kime", "idle02"],
            AmbientKind::Sleep | AmbientKind::LateNight => {
                &["sleep", "akubi", "sigh", "sad", "idle02"]
            }
            AmbientKind::Daze => &[
                "stare", "mitore", "thinking", "eeto", "odoodo", "nf", "idle02",
            ],
            AmbientKind::Random | AmbientKind::None => &[],
        }
    }

    /// Expression tags tried in order.
    pub fn expression_tags(self) -> &'static [&'static str] {
        match self {
            AmbientKind::Morning => &["smile", "default", "idle"],
            AmbientKind::Sleep | AmbientKind::LateNight => &["sad", "sleep", "idle", "default"],
            AmbientKind::Daze => &["idle", "default", "sad"],
            AmbientKind::Random | AmbientKind::None => &[],
        }
    }

    /// Config-independent name for logs.
    pub fn key(self) -> &'static str {
        match self {
            AmbientKind::None => "none",
            AmbientKind::Morning => "morning",
            AmbientKind::Sleep => "sleep",
            AmbientKind::LateNight => "late_night",
            AmbientKind::Daze => "daze",
            AmbientKind::Random => "random",
        }
    }
}

/// What the planner wants to play this tick.
#[derive(Debug, Clone, PartialEq)]
pub struct AmbientPlan {
    /// Motion to play.
    pub motion: Option<String>,
    /// Expression to apply.
    pub expression: Option<String>,
    /// Why it fired.
    pub kind: AmbientKind,
}

/// Schedules ambient motions.
#[derive(Debug, Clone)]
pub struct IdlePlanner {
    next_tick_at: f64,
    last_ambient_at: f64,
    started: bool,
    morning_day: Option<u32>,
}

impl Default for IdlePlanner {
    fn default() -> Self {
        Self {
            next_tick_at: 0.0,
            // Start "long ago" so the first ambient action is not gated by the
            // 180 s cooldown (the original timers start unset, i.e. infinite past).
            last_ambient_at: f64::NEG_INFINITY,
            started: false,
            morning_day: None,
        }
    }
}

impl IdlePlanner {
    /// Ambient tick interval in seconds.
    pub const TICK_SECS: f64 = 5.0;
    /// Minimum gap between two ambient actions in seconds.
    pub const AMBIENT_COOLDOWN_SECS: f64 = 180.0;
    /// Idle seconds before the "daze" bucket.
    pub const DAZE_SECS: f64 = 7.0 * 60.0;
    /// Idle seconds before the "sleep" bucket.
    pub const SLEEP_SECS: f64 = 18.0 * 60.0;
    /// Idle seconds required for the late-night bucket.
    pub const LATE_NIGHT_IDLE_SECS: f64 = 90.0;

    /// Marks user activity so the idle clock restarts.
    pub fn mark_activity(&mut self, now: f64) {
        self.next_tick_at = now + Self::TICK_SECS;
    }

    /// Classifies the current context bucket (morning > sleep > late night > daze).
    pub fn context_kind(&mut self, ctx: &BehaviorContext<'_>, day_of_year: u32) -> AmbientKind {
        if (5..10).contains(&ctx.hour) && self.morning_day != Some(day_of_year) {
            self.morning_day = Some(day_of_year);
            return AmbientKind::Morning;
        }
        if ctx.idle_seconds >= Self::SLEEP_SECS {
            return AmbientKind::Sleep;
        }
        if (ctx.hour >= 23 || ctx.hour < 5) && ctx.idle_seconds >= Self::LATE_NIGHT_IDLE_SECS {
            return AmbientKind::LateNight;
        }
        if ctx.idle_seconds >= Self::DAZE_SECS {
            return AmbientKind::Daze;
        }
        AmbientKind::None
    }

    /// Advances the planner; returns an [`AmbientPlan`] when a motion should play.
    pub fn tick(
        &mut self,
        ctx: &BehaviorContext<'_>,
        rng: &mut Rng,
        random_enabled: bool,
        idle_enabled: bool,
    ) -> Option<AmbientPlan> {
        if !self.started {
            self.started = true;
            self.next_tick_at = ctx.now + Self::TICK_SECS;
            return None;
        }
        if ctx.now < self.next_tick_at {
            return None;
        }
        self.next_tick_at = ctx.now + Self::TICK_SECS;

        if ctx.motion_names.is_empty() {
            return None;
        }

        let day_of_year = day_of_year(ctx.now);
        let kind = self.context_kind(ctx, day_of_year);
        if kind != AmbientKind::None {
            if ctx.now - self.last_ambient_at < Self::AMBIENT_COOLDOWN_SECS {
                return None;
            }
            let motion = self.first_tagged_motion(kind.motion_tags(), ctx, rng);
            let expression = self.first_tagged_expression(kind.expression_tags(), ctx);
            self.last_ambient_at = ctx.now;
            trace!(
                kind = kind.key(),
                ?motion,
                ?expression,
                "context idle action"
            );
            return Some(AmbientPlan {
                motion,
                expression,
                kind,
            });
        }

        if !random_enabled && !idle_enabled {
            return None;
        }
        if ctx.now - self.last_ambient_at < Self::AMBIENT_COOLDOWN_SECS {
            return None;
        }
        let phase = pet_util::time_of_day::DayPhase::from_hour(ctx.hour);
        let mut motion = None;
        for tag in phase.motion_tags() {
            let resolved = resolve_motion_by_tag(tag, ctx.motion_names, ctx.character, rng);
            if !resolved.is_empty() {
                motion = Some(resolved);
                break;
            }
        }
        let motion = motion.or_else(|| {
            ctx.motion_names
                .iter()
                .find(|name| {
                    let lower = name.to_ascii_lowercase();
                    !lower.starts_with("sys-") && !lower.starts_with("idle")
                })
                .cloned()
        });
        motion.as_ref()?;
        self.last_ambient_at = ctx.now;
        Some(AmbientPlan {
            motion,
            expression: None,
            kind: AmbientKind::Random,
        })
    }

    fn first_tagged_motion(
        &self,
        tags: &[&str],
        ctx: &BehaviorContext<'_>,
        rng: &mut Rng,
    ) -> Option<String> {
        for tag in tags {
            let resolved = resolve_motion_by_tag(tag, ctx.motion_names, ctx.character, rng);
            if !resolved.is_empty() {
                return Some(resolved);
            }
        }
        None
    }

    fn first_tagged_expression(&self, tags: &[&str], ctx: &BehaviorContext<'_>) -> Option<String> {
        for tag in tags {
            let resolved = resolve_expression_by_tag(tag, ctx.expression_names, ctx.character);
            if !resolved.is_empty() {
                return Some(resolved);
            }
        }
        None
    }
}

/// Day index derived from the monotonic clock is meaningless, so use the local
/// date hour counter (seconds / 86400) — good enough to gate "once per morning".
fn day_of_year(now: f64) -> u32 {
    (now / 86_400.0) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    fn context<'a>(
        now: f64,
        idle_seconds: f64,
        hour: u32,
        motion_names: &'a [String],
        expression_names: &'a [String],
    ) -> BehaviorContext<'a> {
        BehaviorContext {
            now,
            dt: 1.0 / 60.0,
            cursor_local: None,
            surface: (400, 500),
            idle_seconds,
            hour,
            peer_center: None,
            own_center: (200.0, 250.0),
            motion_names,
            expression_names,
            character: "kasumi",
            motion_finished: true,
        }
    }

    #[test]
    fn bucket_priority_is_morning_then_sleep_then_late_night_then_daze() {
        let motions: Vec<String> = vec![];
        let expressions: Vec<String> = vec![];
        let mut planner = IdlePlanner::default();
        assert_eq!(
            planner.context_kind(&context(0.0, 2000.0, 7, &motions, &expressions), 1),
            AmbientKind::Morning
        );
        // Second call on the same day falls through to sleep.
        assert_eq!(
            planner.context_kind(&context(1.0, 2000.0, 7, &motions, &expressions), 1),
            AmbientKind::Sleep
        );
        assert_eq!(
            planner.context_kind(&context(2.0, 100.0, 1, &motions, &expressions), 1),
            AmbientKind::LateNight
        );
        assert_eq!(
            planner.context_kind(&context(3.0, 500.0, 15, &motions, &expressions), 1),
            AmbientKind::Daze
        );
        assert_eq!(
            planner.context_kind(&context(4.0, 10.0, 15, &motions, &expressions), 1),
            AmbientKind::None
        );
    }

    #[test]
    fn ambient_actions_respect_the_cooldown() {
        let motions = vec![
            "idle01".to_owned(),
            "smile01".to_owned(),
            "sleep01".to_owned(),
        ];
        let expressions = vec!["f01".to_owned()];
        let mut planner = IdlePlanner::default();
        let mut rng = Rng::seeded(4);
        // First tick only arms the timer.
        assert!(planner
            .tick(
                &context(0.0, 10.0, 12, &motions, &expressions),
                &mut rng,
                true,
                true
            )
            .is_none());
        let plan = planner
            .tick(
                &context(6.0, 10.0, 12, &motions, &expressions),
                &mut rng,
                true,
                true,
            )
            .expect("a random motion");
        assert_eq!(plan.kind, AmbientKind::Random);
        // Within the 180 s cooldown nothing else fires.
        assert!(planner
            .tick(
                &context(20.0, 10.0, 12, &motions, &expressions),
                &mut rng,
                true,
                true
            )
            .is_none());
        // After the cooldown a daze action is possible.
        let plan = planner
            .tick(
                &context(200.0, 600.0, 12, &motions, &expressions),
                &mut rng,
                true,
                true,
            )
            .expect("daze action");
        assert_eq!(plan.kind, AmbientKind::Daze);
    }
}
