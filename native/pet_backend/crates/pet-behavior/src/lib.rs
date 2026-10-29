//! The local behavior state machine (spec §2.7).
//!
//! Everything here is deterministic given a seed and a clock: the engine turns
//! cursor position, clicks and elapsed time into [`Command`]s that the pet
//! process executes. No model inference is involved — the original script used an
//! LLM for chat, LITE only needs the local half.
//!
//! * [`head_track`] — 600 px radial clamp, 4 px dead zone, 0.3 s recenter, plus
//!   mutual gaze over peer window centers.
//! * [`idle`] — 5 s ambient tick, 180 s cooldown, morning/sleep/late-night/daze
//!   buckets, random-motion selection.
//! * [`window_motion`] — the six emotion displacements with OutCubic keyframes.
pub mod head_track;
pub mod idle;
pub mod window_motion;

use pet_config::{ClickAction, ClickProfile, ClickRegion};
use pet_input::matching::{choose_auto_motion, resolve_click_action, resolve_motion_by_tag};
use pet_util::Rng;
use tracing::trace;

pub use head_track::{GazeTarget, HeadTracker};
pub use idle::{AmbientKind, IdlePlanner};
pub use window_motion::{WindowMotionKind, WindowMotionPlayer};

/// An action the pet process should perform.
#[derive(Debug, Clone, PartialEq)]
pub enum Command {
    /// Play a motion group by exact name.
    PlayMotion(String),
    /// Play an expression by exact name.
    PlayExpression(String),
    /// Play any non-idle motion (`__random__`).
    PlayRandomMotion,
    /// Set the head/eye drag target in normalized `-1..=1` coordinates.
    SetDrag(f32, f32),
    /// Move the window to `(x, y)` in physical pixels (emotion displacement).
    MoveWindow(i32, i32),
}

/// Everything the behavior machine needs to know this tick.
#[derive(Debug, Clone)]
pub struct BehaviorContext<'a> {
    /// Seconds since the pet process started (monotonic).
    pub now: f64,
    /// Frame delta in seconds.
    pub dt: f32,
    /// Cursor position relative to this window in physical pixels; may be outside its bounds.
    pub cursor_local: Option<(f32, f32)>,
    /// Window size in physical pixels.
    pub surface: (u32, u32),
    /// Seconds since the last user interaction with this role.
    pub idle_seconds: f64,
    /// Local hour (0–23) for the time-of-day buckets.
    pub hour: u32,
    /// Nearest other role's window center in screen coordinates.
    pub peer_center: Option<(f32, f32)>,
    /// This window's center in screen coordinates.
    pub own_center: (f32, f32),
    /// Motion group names of the current model.
    pub motion_names: &'a [String],
    /// Expression names of the current model.
    pub expression_names: &'a [String],
    /// Character key, used by the `<char>_<tag>` matching level.
    pub character: &'a str,
    /// Whether the motion started last time has finished (no motion counts as finished).
    pub motion_finished: bool,
}

/// Config subset that drives behavior (copied from `Config` on change).
#[derive(Debug, Clone, Default)]
pub struct RoleBehaviorConfig {
    /// Dragging disabled.
    pub drag_locked: bool,
    /// Look at the cursor.
    pub head_tracking: bool,
    /// Look at the nearest other role.
    pub mutual_gaze: bool,
    /// Play idle motions.
    pub idle_actions: bool,
    /// Play periodic random motions.
    pub random_actions: bool,
    /// Window-level emotion displacement.
    pub emotion_enabled: bool,
    /// Seven-region click mapping.
    pub click_actions: ClickProfile,
    /// Default motion group (empty = model default idle).
    pub default_motion: String,
    /// Default expression (empty = none).
    pub default_expression: String,
}

impl From<&pet_config::Config> for RoleBehaviorConfig {
    fn from(config: &pet_config::Config) -> Self {
        Self {
            drag_locked: config.drag_locked,
            head_tracking: config.live2d_head_tracking_enabled,
            mutual_gaze: config.live2d_mutual_gaze_enabled,
            idle_actions: config.live2d_idle_actions_enabled,
            random_actions: config.live2d_random_actions_enabled,
            emotion_enabled: config.emotion_behavior_enabled,
            click_actions: config.click_motion_actions.clone(),
            default_motion: config
                .active_entry()
                .map(|entry| entry.default_motion.clone())
                .unwrap_or_default(),
            default_expression: config
                .active_entry()
                .map(|entry| entry.default_expression.clone())
                .unwrap_or_default(),
        }
    }
}

/// Timers created by triggered motions (spec §3.3: 9000 / 3200 / 5000 ms).
#[derive(Debug, Clone, Default)]
struct FeedbackTimers {
    /// Hard stop for a clip that never ends on its own (9 s / 8 s after the trigger).
    clear_motion_at: Option<f64>,
    /// Earliest point at which a finished clip may hand back to the resting motion.
    settle_motion_at: Option<f64>,
    revert_expression_at: Option<f64>,
}

/// The per-role behavior machine.
pub struct RoleBehavior {
    config: RoleBehaviorConfig,
    rng: Rng,
    head: HeadTracker,
    idle: IdlePlanner,
    window_motion: WindowMotionPlayer,
    timers: FeedbackTimers,
    last_interaction: f64,
    started: bool,
    default_motion_playing: bool,
}

impl RoleBehavior {
    /// Creates a behavior machine seeded for reproducible tests.
    pub fn new(seed: u64) -> Self {
        Self {
            config: RoleBehaviorConfig::default(),
            rng: Rng::seeded(seed),
            head: HeadTracker::default(),
            idle: IdlePlanner::default(),
            window_motion: WindowMotionPlayer::default(),
            timers: FeedbackTimers::default(),
            last_interaction: 0.0,
            started: false,
            default_motion_playing: false,
        }
    }

    /// Replaces the behavior config (called whenever settings change).
    pub fn set_config(&mut self, config: RoleBehaviorConfig) {
        if self.config.head_tracking && !config.head_tracking {
            self.head.recenter_immediately();
        }
        self.config = config;
    }

    /// Current config.
    pub fn config(&self) -> &RoleBehaviorConfig {
        &self.config
    }

    /// Whether a window displacement animation is currently running.
    pub fn window_motion_active(&self) -> bool {
        self.window_motion.is_running()
    }

    /// Called when the user interacts with this role (drag, click, wheel…).
    pub fn note_interaction(&mut self, now: f64) {
        self.last_interaction = now;
        self.idle.mark_activity(now);
    }

    /// First frame: play the default motion/expression.
    pub fn start(&mut self, now: f64) -> Vec<Command> {
        self.started = true;
        self.last_interaction = now;
        let mut commands = Vec::new();
        if !self.config.default_motion.is_empty() {
            commands.push(Command::PlayMotion(self.config.default_motion.clone()));
            self.default_motion_playing = true;
        } else if self.config.idle_actions {
            commands.push(Command::PlayMotion(String::new()));
        }
        if !self.config.default_expression.is_empty() {
            commands.push(Command::PlayExpression(
                self.config.default_expression.clone(),
            ));
        }
        commands
    }

    /// Handles a single click on one of the seven regions.
    pub fn on_click(
        &mut self,
        region: ClickRegion,
        now: f64,
        ctx: &BehaviorContext<'_>,
    ) -> Vec<Command> {
        self.note_interaction(now);
        let entry = ctx
            .motion_names
            .iter()
            .position(|_| false)
            .unwrap_or(usize::MAX);
        let _ = entry;

        let action = self
            .config
            .click_actions
            .get(region.key())
            .cloned()
            .unwrap_or_else(ClickAction::auto);
        let resolved = resolve_click_action(
            region,
            &action,
            ctx.motion_names,
            ctx.expression_names,
            ctx.character,
            &mut self.rng,
        );
        let Some((motion, expression)) = resolved else {
            trace!(
                region = region.key(),
                "click region configured to do nothing"
            );
            return Vec::new();
        };

        let mut commands = Vec::new();
        if motion.is_empty() {
            commands.push(Command::PlayRandomMotion);
        } else {
            commands.push(Command::PlayMotion(motion));
        }
        if !expression.is_empty() {
            commands.push(Command::PlayExpression(expression));
            self.timers.revert_expression_at = Some(now + 5.0);
        }
        self.timers.clear_motion_at = Some(now + 9.0);
        self.timers.settle_motion_at = Some(now + 3.2);
        commands
    }

    /// Per-frame tick: head tracking, ambient motions, window displacement.
    pub fn tick(&mut self, ctx: &BehaviorContext<'_>, base_position: (i32, i32)) -> Vec<Command> {
        let mut commands = Vec::new();

        // 1. Head tracking / mutual gaze.
        if let Some((x, y)) = self.compute_drag(ctx) {
            commands.push(Command::SetDrag(x, y));
        }

        // 2. Feedback timers.
        if let Some(at) = self.timers.revert_expression_at {
            if ctx.now >= at {
                self.timers.revert_expression_at = None;
                if self.config.default_expression.is_empty() {
                    commands.push(Command::PlayExpression(String::new()));
                } else {
                    commands.push(Command::PlayExpression(
                        self.config.default_expression.clone(),
                    ));
                }
            }
        }
        // A triggered clip ends on its own: hand back to the resting motion as soon
        // as the settle window opens. A clip that never ends is cut at the hard
        // stop instead. Either way exactly one motion command is emitted, so the
        // pet never restarts twice in a row.
        let clear_due = self.timers.clear_motion_at.is_some_and(|at| ctx.now >= at);
        let settle_due = self
            .timers
            .settle_motion_at
            .is_some_and(|at| ctx.now >= at && ctx.motion_finished);
        if clear_due || settle_due {
            self.timers.clear_motion_at = None;
            self.timers.settle_motion_at = None;
            commands.push(Command::PlayMotion(self.rest_motion()));
            self.default_motion_playing = true;
        }

        // 3. Ambient random / idle motions.
        if self.config.random_actions || self.config.idle_actions {
            if let Some(plan) = self.idle.tick(
                ctx,
                &mut self.rng,
                self.config.random_actions,
                self.config.idle_actions,
            ) {
                if let Some(motion) = plan.motion {
                    commands.push(Command::PlayMotion(motion));
                }
                if let Some(expression) = plan.expression {
                    commands.push(Command::PlayExpression(expression));
                    self.timers.revert_expression_at = Some(ctx.now + 6.0);
                }
                self.timers.clear_motion_at = Some(ctx.now + 9.0);
                self.timers.settle_motion_at = Some(ctx.now + 1.8);
            }
        }

        // 4. Window displacement animation.
        if self.config.emotion_enabled {
            if let Some(offset) = self.window_motion.tick(ctx.now) {
                commands.push(Command::MoveWindow(
                    base_position.0 + offset.0,
                    base_position.1 + offset.1,
                ));
            } else if self.window_motion.just_finished() {
                commands.push(Command::MoveWindow(base_position.0, base_position.1));
            }
        }

        commands
    }

    /// Plays a random non-idle motion (radial menu "动作").
    pub fn random_motion(&mut self, ctx: &BehaviorContext<'_>, now: f64) -> Option<Command> {
        self.note_interaction(now);
        let motion = choose_auto_motion(
            ClickRegion::UpperBodyCenter,
            ctx.motion_names,
            ctx.character,
            &mut self.rng,
        );
        if motion.is_empty() {
            None
        } else {
            self.note_triggered_motion(now);
            Some(Command::PlayMotion(motion))
        }
    }

    /// Registers a motion the caller started on its own (radial menu, IPC).
    ///
    /// The pet returns to its resting motion as soon as the clip ends (2 s grace)
    /// or after the 8 s hard stop, matching the click feedback timers.
    pub fn note_triggered_motion(&mut self, now: f64) {
        self.note_interaction(now);
        self.timers.clear_motion_at = Some(now + 8.0);
        self.timers.settle_motion_at = Some(now + 2.0);
    }

    /// Motion played once a triggered clip is over; empty means the model's idle group.
    fn rest_motion(&self) -> String {
        self.config.default_motion.clone()
    }

    /// Triggers a window displacement (used by the tray / tests).
    pub fn trigger_window_motion(&mut self, kind: WindowMotionKind, intensity: u8, now: f64) {
        if self.config.emotion_enabled {
            self.window_motion.start(kind, intensity, now, (0.0, -1.0));
        }
    }

    fn compute_drag(&mut self, ctx: &BehaviorContext<'_>) -> Option<(f32, f32)> {
        if self.config.mutual_gaze {
            if let Some(peer) = ctx.peer_center {
                let target = GazeTarget::Screen(peer);
                return self.head.gaze(ctx, target, ctx.own_center);
            }
        }
        if self.config.head_tracking {
            let cursor = ctx.cursor_local?;
            return self.head.track_local(ctx, cursor);
        }
        if !self.config.head_tracking {
            return self.head.recenter(ctx.dt);
        }
        None
    }

    /// Seconds since the last user interaction with this role.
    pub fn idle_seconds(&self, now: f64) -> f64 {
        (now - self.last_interaction).max(0.0)
    }
}

/// Resolves a stored click action's motion against the current model (settings preview).
pub fn preview_click_motion(
    action: &ClickAction,
    region: ClickRegion,
    motion_names: &[String],
    character: &str,
    rng: &mut Rng,
) -> String {
    match action.motion.as_str() {
        ClickAction::NONE => String::new(),
        ClickAction::AUTO => choose_auto_motion(region, motion_names, character, rng),
        ClickAction::RANDOM => rng.pick(motion_names).cloned().unwrap_or_default(),
        other => resolve_motion_by_tag(other, motion_names, character, rng),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pet_config::ClickAction;

    fn ctx<'a>(now: f64, motions: &'a [String], expressions: &'a [String]) -> BehaviorContext<'a> {
        BehaviorContext {
            now,
            dt: 1.0 / 60.0,
            cursor_local: None,
            surface: (400, 500),
            idle_seconds: 0.0,
            hour: 12,
            peer_center: None,
            own_center: (200.0, 250.0),
            motion_names: motions,
            expression_names: expressions,
            character: "kasumi",
            motion_finished: true,
        }
    }

    #[test]
    fn click_plays_configured_motion_and_expression() {
        let motions = vec!["smile01".to_owned(), "idle01".to_owned()];
        let expressions = vec!["f01".to_owned()];
        let mut behavior = RoleBehavior::new(7);
        let mut config = RoleBehaviorConfig::default();
        config
            .click_actions
            .insert("head".to_owned(), ClickAction::new("smile01", "f01"));
        behavior.set_config(config);

        let commands = behavior.on_click(ClickRegion::Head, 1.0, &ctx(1.0, &motions, &expressions));
        assert!(commands.contains(&Command::PlayMotion("smile01".to_owned())));
        assert!(commands.contains(&Command::PlayExpression("f01".to_owned())));
    }

    #[test]
    fn none_action_emits_nothing() {
        let motions = vec!["smile01".to_owned()];
        let expressions = vec!["f01".to_owned()];
        let mut behavior = RoleBehavior::new(8);
        let mut config = RoleBehaviorConfig::default();
        config
            .click_actions
            .insert("head".to_owned(), ClickAction::new(ClickAction::NONE, ""));
        behavior.set_config(config);
        let commands = behavior.on_click(ClickRegion::Head, 1.0, &ctx(1.0, &motions, &expressions));
        assert!(commands.is_empty(), "{commands:?}");
    }

    #[test]
    fn motion_is_cleared_after_the_feedback_window() {
        let motions = vec!["smile01".to_owned(), "idle01".to_owned()];
        let expressions = vec![String::new()];
        let mut behavior = RoleBehavior::new(10);
        let mut config = RoleBehaviorConfig::default();
        config
            .click_actions
            .insert("head".to_owned(), ClickAction::new("smile01", ""));
        behavior.set_config(config);
        behavior.on_click(ClickRegion::Head, 0.0, &ctx(0.0, &motions, &expressions));
        let commands = behavior.tick(&ctx(9.5, &motions, &expressions), (0, 0));
        assert!(commands.contains(&Command::PlayMotion(String::new())));
    }

    #[test]
    fn head_tracking_emits_drag() {
        let motions = vec!["idle01".to_owned()];
        let expressions = vec!["f01".to_owned()];
        let mut behavior = RoleBehavior::new(11);
        behavior.set_config(RoleBehaviorConfig {
            head_tracking: true,
            ..RoleBehaviorConfig::default()
        });
        let mut context = ctx(1.0, &motions, &expressions);
        context.cursor_local = Some((380.0, 40.0));
        let commands = behavior.tick(&context, (0, 0));
        assert!(
            commands
                .iter()
                .any(|command| matches!(command, Command::SetDrag(_, _))),
            "{commands:?}"
        );
    }

    fn played_motions(commands: &[Command]) -> Vec<String> {
        commands
            .iter()
            .filter_map(|command| match command {
                Command::PlayMotion(name) => Some(name.clone()),
                _ => None,
            })
            .collect()
    }

    fn settled_context<'a>(
        now: f64,
        finished: bool,
        motions: &'a [String],
        expressions: &'a [String],
    ) -> BehaviorContext<'a> {
        let mut context = ctx(now, motions, expressions);
        context.motion_finished = finished;
        context
    }

    /// Config with a resting motion and a `head` click motion.
    fn resting_config(rest: &str, clicked: &str) -> RoleBehaviorConfig {
        let mut config = RoleBehaviorConfig {
            default_motion: rest.to_owned(),
            ..RoleBehaviorConfig::default()
        };
        config
            .click_actions
            .insert("head".to_owned(), ClickAction::new(clicked, ""));
        config
    }

    #[test]
    fn a_finished_clip_returns_to_the_default_motion_exactly_once() {
        let motions = vec!["smile01".to_owned(), "idle02".to_owned()];
        let expressions = vec![String::new()];
        let mut behavior = RoleBehavior::new(12);
        behavior.set_config(resting_config("idle02", "smile01"));
        behavior.on_click(ClickRegion::Head, 0.0, &ctx(0.0, &motions, &expressions));

        // Inside the settle window the clip is still running: hands off.
        let commands = behavior.tick(&settled_context(2.0, false, &motions, &expressions), (0, 0));
        assert!(played_motions(&commands).is_empty(), "{commands:?}");

        // Once it ended, the resting motion starts once.
        let commands = behavior.tick(&settled_context(3.3, true, &motions, &expressions), (0, 0));
        assert_eq!(played_motions(&commands), vec!["idle02".to_owned()]);

        // The 9 s fallback went with it: no restart one frame later.
        let commands = behavior.tick(&settled_context(9.2, true, &motions, &expressions), (0, 0));
        assert!(played_motions(&commands).is_empty(), "{commands:?}");
    }

    #[test]
    fn a_clip_that_never_ends_is_cut_once_at_the_hard_stop() {
        let motions = vec!["smile01".to_owned(), "idle01".to_owned()];
        let expressions = vec![String::new()];
        let mut behavior = RoleBehavior::new(13);
        behavior.set_config(resting_config("idle01", "smile01"));
        behavior.on_click(ClickRegion::Head, 0.0, &ctx(0.0, &motions, &expressions));

        let commands = behavior.tick(&settled_context(9.1, false, &motions, &expressions), (0, 0));
        assert_eq!(played_motions(&commands), vec!["idle01".to_owned()]);
        let commands = behavior.tick(&settled_context(9.2, false, &motions, &expressions), (0, 0));
        assert!(played_motions(&commands).is_empty(), "{commands:?}");
    }

    #[test]
    fn the_radial_menu_motion_also_settles_after_it_ends() {
        let motions = vec!["smile01".to_owned(), "idle01".to_owned()];
        let expressions = vec![String::new()];
        let mut behavior = RoleBehavior::new(14);
        behavior.set_config(resting_config("idle01", "smile01"));
        let command = behavior
            .random_motion(&ctx(0.0, &motions, &expressions), 0.0)
            .expect("a random motion");
        assert!(matches!(
            command,
            Command::PlayMotion(_) | Command::PlayRandomMotion
        ));

        let commands = behavior.tick(&settled_context(2.1, true, &motions, &expressions), (0, 0));
        assert_eq!(played_motions(&commands), vec!["idle01".to_owned()]);
    }
}
