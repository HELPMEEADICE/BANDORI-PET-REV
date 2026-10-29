//! Cubism 2 (`.moc`) adapter.
//!
//! Everything animation related — motions, expressions, eyeblink, breath, drag,
//! physics and pose — lives inside [`neocari::assets::Moc2RuntimeModel::update`],
//! so this adapter only records what is playing.

use std::path::Path;

use neocari::assets::{load_moc2_runtime, DecodedTexture, Moc2RuntimeModel};
use neocari::moc3::Moc3DrawableMesh;
use pet_config::ModelFormat;

use crate::{Live2dError, ModelInfo};

/// Cubism 2 model plus the LITE bookkeeping the runtime does not provide.
pub struct Moc2Adapter {
    model: Moc2RuntimeModel,
    info: ModelInfo,
    face_height: Option<f32>,
    active_group: Option<String>,
    drag: (f32, f32),
    auto_blink: bool,
    auto_breath: bool,
    mouth_open: Option<f32>,
    mouth_form: f32,
}

impl Moc2Adapter {
    /// Loads `model.json` (Cubism 2.1 settings) and its `.moc` + textures.
    pub fn load(model_path: &Path) -> Result<Self, Live2dError> {
        let model = load_moc2_runtime(model_path).map_err(|source| Live2dError::Load {
            path: model_path.display().to_string(),
            source,
        })?;

        let canvas = model.runtime().canvas();
        let motion_groups: Vec<String> = model.motion_groups().map(str::to_owned).collect();
        let expression_names: Vec<String> = model.expression_names().map(str::to_owned).collect();
        let info = ModelInfo {
            format: ModelFormat::Moc,
            motion_groups,
            expression_names,
            texture_count: model.textures().len(),
            canvas_width: canvas.width() as f32,
            canvas_height: canvas.height() as f32,
        };

        let face_height = crate::framing::moc2_face_height(&model);
        Ok(Self {
            model,
            info,
            face_height,
            active_group: None,
            drag: (0.0, 0.0),
            auto_blink: true,
            auto_breath: true,
            mouth_open: None,
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
        self.model.meshes()
    }

    /// Decoded textures.
    pub fn textures(&self) -> &[DecodedTexture] {
        self.model.textures()
    }

    /// Transfers CPU texture pixels out of the runtime after GPU upload.
    pub fn take_textures(&mut self) -> Vec<DecodedTexture> {
        self.model.take_textures()
    }

    /// Advances the model; it internally handles drag, blink, breath, motions,
    /// expressions, physics and pose.
    pub fn update(&mut self, delta_seconds: f32) -> bool {
        let mouth = self.mouth_open.take();
        let mouth_form = self.mouth_form;
        let runtime = self.model.runtime_mut();
        runtime.set_drag(self.drag.0, self.drag.1);
        runtime
            .update_with_parameters(delta_seconds, |runtime| {
                if let Some(value) = mouth.filter(|v| *v > 0.0) {
                    runtime.set_parameter("PARAM_MOUTH_OPEN_Y", value);
                    runtime.set_parameter("PARAM_MOUTH_FORM", mouth_form);
                }
            })
            .is_some()
    }

    /// Plays the first motion of a group.
    pub fn play_motion(&mut self, group: &str) -> bool {
        match self.model.play_motion(group, 0) {
            Ok(true) => {
                self.active_group = Some(group.to_owned());
                true
            }
            Ok(false) => {
                tracing::warn!(group, "motion reference has no file");
                false
            }
            Err(error) => {
                tracing::warn!(group, %error, "failed to start motion");
                false
            }
        }
    }

    /// Plays an expression by name.
    pub fn play_expression(&mut self, name: &str) -> bool {
        match self.model.play_expression(name) {
            Ok(started) => started,
            Err(error) => {
                tracing::warn!(name, %error, "failed to start expression");
                false
            }
        }
    }

    /// Fades every active expression out.
    pub fn clear_expression(&mut self) {
        self.model.runtime_mut().stop_expressions();
    }

    /// Number of expressions still being blended (including fading ones).
    pub fn active_expression_count(&self) -> usize {
        self.model.runtime().active_expressions()
    }

    /// Stops all motions.
    pub fn stop_motions(&mut self) {
        self.model.runtime_mut().stop_all_motions();
        self.active_group = None;
    }

    /// Whether the running motion finished.
    pub fn is_motion_finished(&self) -> bool {
        self.model.runtime().is_motion_finished()
    }

    /// Group currently playing.
    pub fn active_motion_group(&self) -> Option<&str> {
        self.active_group.as_deref()
    }

    /// Drag target in normalized coordinates.
    pub fn set_drag(&mut self, x: f32, y: f32) {
        self.drag = (x.clamp(-1.0, 1.0), y.clamp(-1.0, 1.0));
    }

    /// Automatic blink toggle.
    pub fn set_auto_blink(&mut self, enabled: bool) {
        self.auto_blink = enabled;
        self.model.runtime_mut().set_auto_blink(enabled);
    }

    /// Automatic breath toggle.
    pub fn set_auto_breath(&mut self, enabled: bool) {
        self.auto_breath = enabled;
        self.model.runtime_mut().set_auto_breath(enabled);
    }

    /// One-shot mouth opening.
    pub fn set_mouth_open(&mut self, value: f32) {
        self.mouth_open = Some(value.clamp(0.0, 1.0));
    }

    pub fn set_lip_sync(&mut self, open: f32, form: f32) {
        self.set_mouth_open(open);
        self.mouth_form = form.clamp(-1.0, 1.0);
    }

    /// Named hit area for a model-space point.
    ///
    /// Neocari maps `hit_areas` (the Cubism SDK array) to names, but Bandori ships
    /// `hit_areas_custom` (`head_x/head_y/body_x/body_y`), which it does not parse.
    /// A raw drawable id such as `D_PSD.124` carries no region meaning, so only the
    /// canonical names are forwarded; everything else returns `None` and the caller
    /// falls back to the coordinate buckets (spec §2.4 item 5).
    pub fn hit_test_area(&mut self, x: f32, y: f32) -> Option<String> {
        let name = self.model.hit_test(x, y)?;
        match name.to_ascii_lowercase().as_str() {
            "head" => Some("head".to_owned()),
            "face" => Some("head".to_owned()),
            "body" => Some("body".to_owned()),
            "hit" => Some("hit".to_owned()),
            _ => None,
        }
    }

    /// Access to the raw runtime (tests, diagnostics).
    pub fn runtime(&self) -> &Moc2RuntimeModel {
        &self.model
    }
}
