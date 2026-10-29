//! Configuration schema, defaults, validation, atomic persistence, and the
//! patch/apply-level routing used by the settings window.
//!
//! `bandori-pet` is the single writer of `config.json`; `bandori-ui` only sends
//! patches over IPC. Unknown keys that a future version wrote are preserved
//! verbatim in [`Config::extras`] so downgrading does not destroy user data.

mod click;
mod config;
mod patch;
pub mod paths;
mod presets;
mod store;

/// Current `config.json` document version.
pub const SCHEMA_VERSION: u32 = 1;

pub use click::{default_click_actions, ClickAction, ClickProfile, ClickRegion, CLICK_REGIONS};
pub use config::{
    Config, DarkTheme, Live2dQuality, ModelEntry, ModelFormat, ModelPickerState, PetMode,
    Placement, WindowPlacement,
};
pub use patch::{apply_level_for, ApplyLevel, SettingsPatch};
pub use paths::{about_lines, Paths};
pub use presets::{
    is_builtin_name, preset, preset_names, Preset, PresetMode, PRESETS, PRESET_NAMES,
};
pub use store::{apply_patch, load_config, save_config, ConfigError, LoadOutcome, SaveOutcome};

/// Range-clamp helpers shared by validation and the settings UI.
pub mod bounds {
    /// Allowed FPS range (spec §3.2: slider 30–240, step 10).
    pub const FPS_MIN: u32 = 30;
    /// Upper FPS bound.
    pub const FPS_MAX: u32 = 240;
    /// FPS step.
    pub const FPS_STEP: u32 = 10;
    /// Opacity is stored as 0.2–1.0 (spec §2.1: below 20% the pet can no longer be clicked).
    pub const OPACITY_MIN: f32 = 0.2;
    /// Fully opaque.
    pub const OPACITY_MAX: f32 = 1.0;
    /// `live2d_scale` of 0 means "unset, derive from DPR × 100".
    pub const SCALE_UNSET: u32 = 0;
    /// Minimum explicit model scale in percent.
    pub const SCALE_MIN: u32 = 25;
    /// Maximum model scale in percent.
    pub const SCALE_MAX: u32 = 500;
    /// Alpha threshold used by CPU hit testing (0–255).
    pub const HIT_ALPHA_MAX: u8 = 255;
}
