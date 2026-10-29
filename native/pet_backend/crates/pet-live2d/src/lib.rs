//! Neocari adapter: one uniform facade over Cubism 2 (`.moc`) and Cubism 3+
//! (`.moc3`) models.
//!
//! The two generations differ in what Neocari does for us:
//!
//! * `.moc` — [`neocari::assets::load_moc2_runtime`] already runs drag, blinking,
//!   breathing, expressions, physics and pose inside `update(dt)`.
//! * `.moc3` — [`neocari::assets::load_model_runtime`] gives raw parameters only;
//!   motion players, expressions, blinking and the frame order have to be
//!   assembled here, following `examples/show_model.rs::advance_model_frame`.

mod blink;
mod framing;
mod moc2;
mod moc3;
mod sprite;
mod transition;

use std::path::Path;

pub use blink::{BlinkBreath, BlinkOutput};
pub use moc2::Moc2Adapter;
pub use moc3::Moc3Adapter;
pub use transition::{PoseTransition, DEFAULT_POSE_FADE_SECONDS};

use neocari::assets::DecodedTexture;
use neocari::moc3::Moc3DrawableMesh;
use pet_config::ModelFormat;

/// Errors raised while loading or driving a model.
#[derive(Debug, thiserror::Error)]
pub enum Live2dError {
    /// Neocari could not load the model folder.
    #[error("failed to load model {path}: {source}")]
    Load {
        /// Model file that failed.
        path: String,
        /// Neocari error.
        #[source]
        source: neocari::assets::AssetLoadError,
    },
    /// The model file name did not identify a supported format.
    #[error("unsupported model file: {0}")]
    Unsupported(String),
    /// The model folder was missing from the extracted costume.
    #[error("model path has no parent directory: {0}")]
    NoParent(String),
}

/// Static facts about a loaded model, used to fill the settings dropdowns.
#[derive(Debug, Clone, PartialEq)]
pub struct ModelInfo {
    /// Container format.
    pub format: ModelFormat,
    /// Motion group names in declaration order.
    pub motion_groups: Vec<String>,
    /// Expression names in declaration order.
    pub expression_names: Vec<String>,
    /// Number of decoded textures.
    pub texture_count: usize,
    /// Logical canvas width (moc/moc3).
    pub canvas_width: f32,
    /// Logical canvas height.
    pub canvas_height: f32,
}

impl ModelInfo {
    /// First motion group that looks like an idle loop, else the first group.
    pub fn default_motion_group(&self) -> Option<&str> {
        self.motion_groups
            .iter()
            .find(|group| group.to_ascii_lowercase().contains("idle"))
            .or_else(|| self.motion_groups.first())
            .map(String::as_str)
    }

    /// `true` when a motion group with this exact name exists.
    pub fn has_motion_group(&self, group: &str) -> bool {
        self.motion_groups.iter().any(|name| name == group)
    }

    /// `true` when an expression with this exact name exists.
    pub fn has_expression(&self, name: &str) -> bool {
        self.expression_names.iter().any(|entry| entry == name)
    }
}

/// A loaded, animatable model of either Cubism generation.
// Keep the adapters inline; loading a model should not require another allocation.
#[allow(clippy::large_enum_variant)]
pub enum ModelHandle {
    /// Cubism 2.1 `.moc` runtime.
    Moc2(Moc2Adapter),
    /// Cubism 3/4/5 `.moc3` runtime.
    Moc3(Moc3Adapter),
    Sprite(sprite::SpriteAdapter),
}

impl ModelHandle {
    /// TTS mouth pose, applied after motion/expression evaluation.
    pub fn set_lip_sync(&mut self, open: f32, form: f32) {
        match self {
            Self::Moc2(adapter) => adapter.set_lip_sync(open, form),
            Self::Moc3(adapter) => adapter.set_lip_sync(open, form),
            Self::Sprite(adapter) => adapter.set_lip_sync(open, form),
        }
    }
    /// Loads a model, choosing the adapter from the file name / declared format.
    pub fn load(model_path: &Path) -> Result<Self, Live2dError> {
        let path = model_path.display().to_string();
        if !model_path.exists() {
            return Err(Live2dError::NoParent(path));
        }
        if model_path.extension().is_some_and(|e| e == "webp") {
            return Ok(Self::Sprite(sprite::SpriteAdapter::load(model_path)?));
        }
        let is_moc3 = model_path
            .to_string_lossy()
            .to_ascii_lowercase()
            .ends_with("model3.json")
            || std::fs::read(model_path)
                .ok()
                .and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok())
                .is_some_and(|manifest| manifest.get("FileReferences").is_some());
        if is_moc3 {
            Ok(ModelHandle::Moc3(Moc3Adapter::load(model_path)?))
        } else {
            Ok(ModelHandle::Moc2(Moc2Adapter::load(model_path)?))
        }
    }

    /// Static model facts.
    pub fn info(&self) -> &ModelInfo {
        match self {
            ModelHandle::Moc2(adapter) => adapter.info(),
            ModelHandle::Moc3(adapter) => adapter.info(),
            Self::Sprite(adapter) => adapter.info(),
        }
    }

    /// Current drawable meshes, in model order.
    pub fn meshes(&self) -> &[Moc3DrawableMesh] {
        match self {
            ModelHandle::Moc2(adapter) => adapter.meshes(),
            ModelHandle::Moc3(adapter) => adapter.meshes(),
            Self::Sprite(adapter) => adapter.meshes(),
        }
    }

    /// Decoded RGBA textures in manifest order.
    pub fn textures(&self) -> &[DecodedTexture] {
        match self {
            ModelHandle::Moc2(adapter) => adapter.textures(),
            ModelHandle::Moc3(adapter) => adapter.textures(),
            Self::Sprite(adapter) => adapter.textures(),
        }
    }

    /// Transfers the original CPU pixels after upload so the caller can keep
    /// only the alpha channel for hit testing. Animation remains usable;
    /// `textures()` is empty afterwards. Model info retains the texture count.
    pub fn take_textures(&mut self) -> Vec<DecodedTexture> {
        match self {
            ModelHandle::Moc2(adapter) => adapter.take_textures(),
            ModelHandle::Moc3(adapter) => adapter.take_textures(),
            Self::Sprite(adapter) => adapter.take_textures(),
        }
    }

    /// Advances the model by `delta_seconds`; `false` means the mesh rebuild failed.
    pub fn update(&mut self, delta_seconds: f32) -> bool {
        match self {
            ModelHandle::Moc2(adapter) => adapter.update(delta_seconds),
            ModelHandle::Moc3(adapter) => adapter.update(delta_seconds),
            Self::Sprite(adapter) => adapter.update(delta_seconds),
        }
    }

    /// Plays the first motion of `group`; `false` when the group is unknown.
    pub fn play_motion(&mut self, group: &str) -> bool {
        match self {
            ModelHandle::Moc2(adapter) => adapter.play_motion(group),
            ModelHandle::Moc3(adapter) => adapter.play_motion(group),
            Self::Sprite(adapter) => adapter.play_motion(group),
        }
    }

    /// Plays an expression by name; `false` when unknown.
    pub fn play_expression(&mut self, name: &str) -> bool {
        match self {
            ModelHandle::Moc2(adapter) => adapter.play_expression(name),
            ModelHandle::Moc3(adapter) => adapter.play_expression(name),
            Self::Sprite(adapter) => adapter.play_expression(name),
        }
    }

    /// Fades every active expression out, returning to the neutral face.
    pub fn clear_expression(&mut self) {
        match self {
            ModelHandle::Moc2(adapter) => adapter.clear_expression(),
            ModelHandle::Moc3(adapter) => adapter.clear_expression(),
            Self::Sprite(adapter) => adapter.clear_expression(),
        }
    }

    /// Number of expressions still being blended (including fading ones).
    pub fn active_expression_count(&self) -> usize {
        match self {
            ModelHandle::Moc2(adapter) => adapter.active_expression_count(),
            ModelHandle::Moc3(adapter) => adapter.active_expression_count(),
            Self::Sprite(adapter) => adapter.active_expression_count(),
        }
    }

    /// Stops every running motion.
    pub fn stop_motions(&mut self) {
        match self {
            ModelHandle::Moc2(adapter) => adapter.stop_motions(),
            ModelHandle::Moc3(adapter) => adapter.stop_motions(),
            Self::Sprite(adapter) => adapter.stop_motions(),
        }
    }

    /// `true` when the currently playing motion (if any) has finished.
    pub fn is_motion_finished(&self) -> bool {
        match self {
            ModelHandle::Moc2(adapter) => adapter.is_motion_finished(),
            ModelHandle::Moc3(adapter) => adapter.is_motion_finished(),
            Self::Sprite(adapter) => adapter.is_motion_finished(),
        }
    }

    /// Motion group currently playing, if any.
    pub fn active_motion_group(&self) -> Option<&str> {
        match self {
            ModelHandle::Moc2(adapter) => adapter.active_motion_group(),
            ModelHandle::Moc3(adapter) => adapter.active_motion_group(),
            Self::Sprite(adapter) => adapter.active_motion_group(),
        }
    }

    /// Sets the head/eye drag target in normalized `-1..=1` screen coordinates.
    pub fn set_drag(&mut self, x: f32, y: f32) {
        match self {
            ModelHandle::Moc2(adapter) => adapter.set_drag(x, y),
            ModelHandle::Moc3(adapter) => adapter.set_drag(x, y),
            Self::Sprite(adapter) => adapter.set_drag(x, y),
        }
    }

    /// Enables or disables automatic blinking.
    pub fn set_auto_blink(&mut self, enabled: bool) {
        match self {
            ModelHandle::Moc2(adapter) => adapter.set_auto_blink(enabled),
            ModelHandle::Moc3(adapter) => adapter.set_auto_blink(enabled),
            Self::Sprite(adapter) => adapter.set_auto_blink(enabled),
        }
    }

    /// Enables or disables the breathing sway.
    pub fn set_auto_breath(&mut self, enabled: bool) {
        match self {
            ModelHandle::Moc2(adapter) => adapter.set_auto_breath(enabled),
            ModelHandle::Moc3(adapter) => adapter.set_auto_breath(enabled),
            Self::Sprite(adapter) => adapter.set_auto_breath(enabled),
        }
    }

    /// Injects a one-shot mouth opening value (`0.0..=1.0`).
    pub fn set_mouth_open(&mut self, value: f32) {
        match self {
            ModelHandle::Moc2(adapter) => adapter.set_mouth_open(value),
            ModelHandle::Moc3(adapter) => adapter.set_mouth_open(value),
            Self::Sprite(adapter) => adapter.set_mouth_open(value),
        }
    }

    /// Named hit area (moc: `head`/`body` from `hit_areas_custom`; moc3: `None`).
    pub fn hit_test_area(&mut self, x: f32, y: f32) -> Option<String> {
        match self {
            ModelHandle::Moc2(adapter) => adapter.hit_test_area(x, y),
            ModelHandle::Moc3(adapter) => adapter.hit_test_area(x, y),
            Self::Sprite(adapter) => adapter.hit_test_area(x, y),
        }
    }

    /// Model format of this handle.
    pub fn format(&self) -> ModelFormat {
        self.info().format
    }

    /// Neutral face height, independent of hair, costume, and full/bust framing.
    pub fn face_height(&self) -> Option<f32> {
        match self {
            ModelHandle::Moc2(adapter) => adapter.face_height(),
            ModelHandle::Moc3(adapter) => adapter.face_height(),
            Self::Sprite(adapter) => adapter.face_height(),
        }
    }

    /// `true` when the model's y axis points down (Cubism 2 `.moc`).
    ///
    /// Cubism 2 coordinates are canvas pixels measured from the top-left corner
    /// with y growing downwards; Cubism 3/4/5 use a y-up model space. The renderer
    /// has to flip y for the former, exactly like Neocari's `render_moc2` example.
    pub fn flips_y(&self) -> bool {
        matches!(self, ModelHandle::Moc2(_) | Self::Sprite(_))
    }
}
