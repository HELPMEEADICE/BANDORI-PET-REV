//! Cubism 3/4/5 (`.moc3`) adapter.
//!
//! Neocari's [`neocari::assets::RuntimeModel`] exposes parameters, physics, pose and
//! meshes but no animation players, so this adapter owns motion playback,
//! expressions, blinking and breathing, and reproduces the frame order from
//! `examples/show_model.rs::advance_model_frame` (spec §2.3):
//!
//! ```text
//! reset_parameters → reset_part_opacities
//!   → drag/blink/breath overrides → motion tick/apply → expression tick/apply
//!   → apply_parameter_overrides → apply_physics(dt) → apply_pose(dt) → update_meshes
//! ```

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use neocari::assets::{load_model_runtime, DecodedTexture, RuntimeModel};
use neocari::expression::{load_expression, ExpressionManager};
use neocari::json::{Expression3, Motion3};
use neocari::moc3::Moc3DrawableMesh;
use neocari::motion::{load_motion, MotionPlayer};
use pet_config::ModelFormat;
use pet_util::Rng;

use crate::blink::BlinkBreath;
use crate::transition::PoseTransition;
use crate::{Live2dError, ModelInfo};

/// Parameter ids used for cursor tracking on Bandori `.moc3` models.
const PARAM_ANGLE_X: &str = "ParamAngleX";
const PARAM_ANGLE_Y: &str = "ParamAngleY";
const PARAM_ANGLE_Z: &str = "ParamAngleZ";
const PARAM_BODY_ANGLE_X: &str = "ParamBodyAngleX";
const PARAM_EYE_BALL_X: &str = "ParamEyeBallX";
const PARAM_EYE_BALL_Y: &str = "ParamEyeBallY";
const PARAM_BREATH: &str = "ParamBreath";
const PARAM_MOUTH_OPEN_Y: &str = "ParamMouthOpenY";
/// Fallback eye ids when `model3.json` declares no `EyeBlink` group.
const FALLBACK_EYE_IDS: [&str; 2] = ["ParamEyeLOpen", "ParamEyeROpen"];
/// Maximum head yaw/pitch in degrees (matches Cubism's default parameter range).
const MAX_ANGLE_DEGREES: f32 = 30.0;

struct PlayingMotion {
    group: String,
    player: MotionPlayer,
}

/// Cubism 3+ model plus motion/expression/blink plumbing.
pub struct Moc3Adapter {
    model: RuntimeModel,
    model_dir: PathBuf,
    info: ModelInfo,
    face_height: Option<f32>,
    motion_paths: HashMap<String, Vec<PathBuf>>,
    expression_paths: HashMap<String, PathBuf>,
    motion_cache: HashMap<PathBuf, Motion3>,
    expression_cache: HashMap<String, Expression3>,
    player: Option<PlayingMotion>,
    /// Cross-fades the pose across motion starts, ends and replacements.
    transition: PoseTransition,
    expressions: ExpressionManager,
    blink: BlinkBreath,
    eye_blink_ids: Vec<String>,
    has_breath: bool,
    view: (f32, f32),
    mouth_open: f32,
    mouth_form: f32,
}

impl Moc3Adapter {
    /// Loads a `.model3.json` and indexes its motions and expressions.
    pub fn load(model_path: &Path) -> Result<Self, Live2dError> {
        let model = load_model_runtime(model_path).map_err(|source| Live2dError::Load {
            path: model_path.display().to_string(),
            source,
        })?;
        let model_dir = model_path
            .parent()
            .ok_or_else(|| Live2dError::NoParent(model_path.display().to_string()))?
            .to_path_buf();

        let mut motion_paths: HashMap<String, Vec<PathBuf>> = HashMap::new();
        let mut motion_groups = Vec::new();
        let mut expression_paths = HashMap::new();
        let mut expression_names = Vec::new();
        {
            let json = model.runtime().model();
            for (group, references) in json.motions() {
                let files: Vec<PathBuf> = references
                    .iter()
                    .map(|reference| model_dir.join(reference.file()))
                    .collect();
                if files.is_empty() {
                    continue;
                }
                motion_groups.push(group.clone());
                motion_paths.insert(group.clone(), files);
            }
            for reference in json.expressions() {
                expression_names.push(reference.name().to_owned());
                expression_paths.insert(
                    reference.name().to_owned(),
                    model_dir.join(reference.file()),
                );
            }
        }

        let canvas = model.runtime().canvas();
        let mut eye_blink_ids = Vec::new();
        for group in model.runtime().model().groups() {
            if group.name().eq_ignore_ascii_case("EyeBlink") {
                eye_blink_ids.extend(group.ids().iter().cloned());
            }
        }
        if eye_blink_ids.is_empty() {
            eye_blink_ids.extend(FALLBACK_EYE_IDS.iter().map(|id| (*id).to_owned()));
        }
        let has_breath = model
            .runtime()
            .parameter_ids()
            .iter()
            .any(|id| id == PARAM_BREATH);

        let info = ModelInfo {
            format: ModelFormat::Moc3,
            motion_groups,
            expression_names,
            texture_count: model.textures().len(),
            canvas_width: canvas.width() as f32,
            canvas_height: canvas.height() as f32,
        };

        let face_height = crate::framing::moc3_face_height(&model, &model_dir);
        let seed = pet_util::Rng::from_entropy().next_u64();
        Ok(Self {
            model,
            model_dir,
            info,
            face_height,
            motion_paths,
            expression_paths,
            motion_cache: HashMap::new(),
            expression_cache: HashMap::new(),
            player: None,
            transition: PoseTransition::default(),
            expressions: ExpressionManager::new(),
            blink: BlinkBreath::new(seed),
            eye_blink_ids,
            has_breath,
            view: (0.0, 0.0),
            mouth_open: 0.0,
            mouth_form: 0.0,
        })
    }

    /// Static model facts.
    pub fn info(&self) -> &ModelInfo {
        &self.info
    }

    /// Face height measured once in the neutral pose.
    pub fn face_height(&self) -> Option<f32> {
        self.face_height
    }

    /// Current meshes.
    pub fn meshes(&self) -> &[Moc3DrawableMesh] {
        self.model.runtime().meshes()
    }

    /// Decoded textures.
    pub fn textures(&self) -> &[DecodedTexture] {
        self.model.textures()
    }

    /// Transfers CPU texture pixels out of the runtime after GPU upload.
    pub fn take_textures(&mut self) -> Vec<DecodedTexture> {
        self.model.take_textures()
    }

    /// Advances one frame (see the module docs for the exact order).
    pub fn update(&mut self, delta_seconds: f32) -> bool {
        let delta = delta_seconds.clamp(0.0, 0.25);
        let mut rng = Rng::seeded(
            self.player
                .as_ref()
                .map_or(1, |player| player.player.time() as u64 + 7),
        );
        let _ = &mut rng; // blink has its own generator
        let blink = self.blink.tick(delta);

        let Self {
            model,
            player,
            transition,
            expressions,
            eye_blink_ids,
            view,
            mouth_open,
            mouth_form,
            has_breath,
            ..
        } = self;
        let runtime = model.runtime_mut();
        runtime.reset_parameters();
        runtime.reset_part_opacities();

        // Tracking / blink / breath / mouth go through the override channel so the
        // motion curves cannot fight them (spec §2.3: overrides are applied last).
        runtime.set_parameter_override(PARAM_ANGLE_X, view.0 * MAX_ANGLE_DEGREES);
        runtime.set_parameter_override(PARAM_ANGLE_Y, view.1 * MAX_ANGLE_DEGREES);
        runtime.set_parameter_override(PARAM_ANGLE_Z, 0.0);
        runtime.set_parameter_override(PARAM_BODY_ANGLE_X, view.0 * MAX_ANGLE_DEGREES * 0.3);
        runtime.set_parameter_override(PARAM_EYE_BALL_X, view.0);
        runtime.set_parameter_override(PARAM_EYE_BALL_Y, view.1);
        for id in eye_blink_ids.iter() {
            runtime.set_parameter_override(id, blink.eye_open);
        }
        if *has_breath {
            runtime.set_parameter_override(PARAM_BREATH, blink.breath);
        }
        if *mouth_open > 0.0 {
            runtime.set_parameter_override(PARAM_MOUTH_OPEN_Y, *mouth_open);
            runtime.set_parameter_override("ParamMouthForm", *mouth_form);
        }

        let mut motion_ended = false;
        if let Some(playing) = player.as_mut() {
            playing.player.tick(delta);
            playing.player.apply(runtime);
            if playing.player.is_finished() {
                *player = None;
                motion_ended = true;
            }
        }

        expressions.tick(delta);
        expressions.apply(runtime);

        // Ease the pose that was on screen into the live one. This runs before the
        // overrides so drag/blink stay immediate, and before physics so the sway is
        // still simulated on the blended pose.
        if let Some(weight) = transition.advance(delta) {
            let parameter_count = runtime.parameter_values().len();
            for index in 0..parameter_count {
                let Some(live) = runtime.parameter_value_by_index(index) else {
                    continue;
                };
                let value = transition.blend_parameter(index, live, weight);
                runtime.set_parameter_by_index(index, value);
            }
            let part_count = runtime.part_count();
            for index in 0..part_count {
                let live = runtime.part_opacity_override_by_index(index);
                if let Some(value) = transition.blend_part_opacity(index, live, weight) {
                    runtime.set_part_opacity_by_index(index, value);
                }
            }
        }

        runtime.apply_parameter_overrides();
        runtime.apply_physics(delta);
        runtime.apply_pose(delta);

        if runtime.update_meshes().is_none() {
            tracing::warn!("moc3 mesh rebuild failed");
            return false;
        }

        // A clip that ended on its own keeps its final pose for this frame; start
        // the fade from there so dropping the player cannot snap to the default.
        if motion_ended {
            begin_pose_fade(transition, model);
        }
        true
    }

    /// Plays the first motion of a group.
    ///
    /// The pose on screen is kept as the source of a short cross-fade, so
    /// replacing a running clip never snaps.
    pub fn play_motion(&mut self, group: &str) -> bool {
        let Some(paths) = self.motion_paths.get(group) else {
            tracing::warn!(group, "unknown moc3 motion group");
            return false;
        };
        let Some(path) = paths.first().cloned() else {
            return false;
        };
        let motion = match self.motion_cache.get(&path) {
            Some(motion) => motion.clone(),
            None => match load_motion(&path) {
                Ok(motion) => {
                    self.motion_cache.insert(path.clone(), motion.clone());
                    motion
                }
                Err(error) => {
                    tracing::warn!(group, path = %path.display(), %error, "failed to load motion");
                    return false;
                }
            },
        };
        self.begin_pose_fade();
        self.player = Some(PlayingMotion {
            group: group.to_owned(),
            player: MotionPlayer::with_looping(motion, false),
        });
        true
    }

    /// Cross-fade length for motion changes, in seconds.
    pub fn motion_fade_seconds(&self) -> f32 {
        self.transition.duration()
    }

    /// Replaces the cross-fade length; `0.0` restores instant switching.
    pub fn set_motion_fade_seconds(&mut self, seconds: f32) {
        self.transition.set_duration(seconds);
    }

    /// Whether a motion change is currently being cross-faded.
    pub fn is_transitioning(&self) -> bool {
        self.transition.is_active()
    }

    /// Captures the current pose as the source of the next cross-fade.
    fn begin_pose_fade(&mut self) {
        begin_pose_fade(&mut self.transition, &self.model);
    }

    /// Plays an expression by name.
    pub fn play_expression(&mut self, name: &str) -> bool {
        let Some(path) = self.expression_paths.get(name).cloned() else {
            tracing::warn!(name, "unknown moc3 expression");
            return false;
        };
        let expression = match self.expression_cache.get(name) {
            Some(expression) => expression.clone(),
            None => match load_expression(&path) {
                Ok(expression) => {
                    self.expression_cache
                        .insert(name.to_owned(), expression.clone());
                    expression
                }
                Err(error) => {
                    tracing::warn!(name, path = %path.display(), %error, "failed to load expression");
                    return false;
                }
            },
        };
        self.expressions.play(expression);
        true
    }

    /// Fades every active expression out.
    pub fn clear_expression(&mut self) {
        self.expressions.stop_all();
    }

    /// Number of expressions still being blended (including fading ones).
    pub fn active_expression_count(&self) -> usize {
        self.expressions.active_expression_count()
    }

    /// Stops motions and expressions, fading the current pose out.
    pub fn stop_motions(&mut self) {
        self.begin_pose_fade();
        self.player = None;
        self.expressions.stop_all();
    }

    /// Whether the running motion finished (no motion counts as finished).
    pub fn is_motion_finished(&self) -> bool {
        self.player
            .as_ref()
            .map(|playing| playing.player.is_finished())
            .unwrap_or(true)
    }

    /// Group currently playing.
    pub fn active_motion_group(&self) -> Option<&str> {
        self.player.as_ref().map(|playing| playing.group.as_str())
    }

    /// Drag target in normalized coordinates.
    pub fn set_drag(&mut self, x: f32, y: f32) {
        self.view = (x.clamp(-1.0, 1.0), y.clamp(-1.0, 1.0));
    }

    /// Automatic blink toggle.
    pub fn set_auto_blink(&mut self, enabled: bool) {
        self.blink.set_enabled(enabled);
    }

    /// Automatic breath toggle.
    pub fn set_auto_breath(&mut self, enabled: bool) {
        self.blink.set_breath_enabled(enabled);
    }

    /// One-shot mouth opening.
    pub fn set_mouth_open(&mut self, value: f32) {
        self.mouth_open = value.clamp(0.0, 1.0);
    }

    pub fn set_lip_sync(&mut self, open: f32, form: f32) {
        self.set_mouth_open(open);
        self.mouth_form = form.clamp(-1.0, 1.0);
    }

    /// Bandori `.moc3` assets ship no `HitAreas`, so region detection uses
    /// coordinates only (spec §2.4 item 5).
    pub fn hit_test_area(&mut self, _x: f32, _y: f32) -> Option<String> {
        None
    }

    /// Folder containing the model file.
    pub fn model_dir(&self) -> &Path {
        &self.model_dir
    }

    /// Access to the raw Neocari runtime (tests, diagnostics).
    pub fn runtime(&self) -> &RuntimeModel {
        &self.model
    }
}

/// Snapshots the visible pose (parameters and part opacities) for a cross-fade.
fn begin_pose_fade(transition: &mut PoseTransition, model: &RuntimeModel) {
    let runtime = model.runtime();
    let parameters = runtime.parameter_values().to_vec();
    let part_opacities = (0..runtime.part_count())
        .map(|index| runtime.part_opacity_override_by_index(index))
        .collect::<Vec<_>>();
    transition.begin(&parameters, &part_opacities);
}
