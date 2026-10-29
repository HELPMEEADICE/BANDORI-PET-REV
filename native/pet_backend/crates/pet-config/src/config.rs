//! The `config.json` v1 data contract (spec §4.1).

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::click::{default_click_actions, ClickAction, ClickProfile};
use crate::{bounds, SCHEMA_VERSION};

/// Theme selection for the settings window only.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum DarkTheme {
    /// Force the light palette.
    Off,
    /// Force the dark palette.
    On,
    /// Follow the system apps theme.
    #[default]
    System,
}

impl DarkTheme {
    /// Config token (`off` / `on` / `system`).
    pub fn key(self) -> &'static str {
        match self {
            DarkTheme::Off => "off",
            DarkTheme::On => "on",
            DarkTheme::System => "system",
        }
    }

    /// Parses a config token, falling back to [`DarkTheme::System`].
    pub fn parse(value: &str) -> Self {
        match value {
            "off" => DarkTheme::Off,
            "on" => DarkTheme::On,
            _ => DarkTheme::System,
        }
    }
}

/// Rendering quality tier. v0 implements it purely as a render-resolution scale.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Live2dQuality {
    /// 0.75× render resolution: integrated GPUs, remote desktop, many roles.
    Performance,
    /// 1.0× native resolution.
    #[default]
    Balanced,
}

impl Live2dQuality {
    /// Config token (`performance` / `balanced`).
    pub fn key(self) -> &'static str {
        match self {
            Live2dQuality::Performance => "performance",
            Live2dQuality::Balanced => "balanced",
        }
    }

    /// Parses a config token, falling back to [`Live2dQuality::Balanced`].
    pub fn parse(value: &str) -> Self {
        match value {
            "performance" => Live2dQuality::Performance,
            _ => Live2dQuality::Balanced,
        }
    }

    /// Linear render-resolution multiplier (spec §2.3).
    pub fn resolution_scale(self) -> f32 {
        match self {
            Live2dQuality::Performance => 0.75,
            Live2dQuality::Balanced => 1.0,
        }
    }
}

/// Which renderer drives a role window. `pixel` is reserved (only two characters
/// ship sprites) and has no UI in v0.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum PetMode {
    /// Live2D model (the only implemented mode).
    #[default]
    Live2d,
    /// Reserved pixel-art mode.
    Pixel,
}

/// Model container format.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ModelFormat {
    /// Cubism 2.1 `.moc` (loaded through `assets::load_moc2_runtime`).
    #[default]
    Moc,
    /// Cubism 3/4/5 `.moc3` (loaded through `assets::load_model_runtime`).
    Moc3,
}

impl ModelFormat {
    /// Detects the format from a model JSON file name.
    pub fn from_path(path: &str) -> Self {
        if path.to_ascii_lowercase().ends_with(".model3.json") {
            ModelFormat::Moc3
        } else {
            ModelFormat::Moc
        }
    }

    /// Until v0.2 keeps the format stable for the renderer.
    pub fn from_token(value: &str) -> Self {
        match value {
            "moc3" => ModelFormat::Moc3,
            _ => ModelFormat::Moc,
        }
    }
}

/// The 14-field window placement record (spec §2.8).
///
/// Absolute coordinates win when the screen fingerprint matches; otherwise the
/// stored relative position is re-projected onto the current monitor.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Placement {
    /// Window left edge in physical pixels.
    pub x: i32,
    /// Window top edge in physical pixels.
    pub y: i32,
    /// Window width in physical pixels.
    pub width: u32,
    /// Window height in physical pixels.
    pub height: u32,
    /// Monitor device name, e.g. `\\.\DISPLAY1`.
    pub screen_name: String,
    /// Monitor serial number when the backend reports one.
    pub screen_serial: String,
    /// Monitor manufacturer id string.
    pub screen_manufacturer: String,
    /// Monitor model string.
    pub screen_model: String,
    /// Monitor rect `[x, y, width, height]` in physical pixels.
    pub screen_geometry: [i32; 4],
    /// Work-area rect `[x, y, width, height]` (excludes the taskbar).
    pub screen_available_geometry: [i32; 4],
    /// Horizontal position as a fraction of the work area (0.0–1.0).
    pub relative_x: f64,
    /// Vertical position as a fraction of the work area (0.0–1.0).
    pub relative_y: f64,
    /// Distance from the right edge of the work area, in physical pixels.
    pub right_offset: i32,
    /// Distance from the bottom edge of the work area, in physical pixels.
    pub bottom_offset: i32,
    /// Device pixel ratio when the placement was recorded.
    pub device_pixel_ratio: f64,
}

impl Default for Placement {
    fn default() -> Self {
        Self {
            x: -1,
            y: -1,
            width: 500,
            height: 625,
            screen_name: String::new(),
            screen_serial: String::new(),
            screen_manufacturer: String::new(),
            screen_model: String::new(),
            screen_geometry: [0, 0, 1920, 1080],
            screen_available_geometry: [0, 0, 1920, 1040],
            relative_x: 0.9,
            relative_y: 0.95,
            right_offset: 28,
            bottom_offset: 1,
            device_pixel_ratio: 1.0,
        }
    }
}

impl Placement {
    /// `true` when no position or monitor fingerprint has been recorded yet.
    pub fn is_unset(&self) -> bool {
        self.x == -1 && self.y == -1 && self.screen_name.is_empty()
    }

    /// Width / height of the stored work area.
    pub fn work_area(&self) -> [i32; 4] {
        self.screen_available_geometry
    }
}

/// Older name kept for readability at call sites.
pub type WindowPlacement = Placement;

/// One role window's persisted state (spec §4.1 `models[]`).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ModelEntry {
    /// Character key used by `band.json`, e.g. `kasumi`.
    pub character: String,
    /// Costume id used by the archive index, e.g. `live_event_295_ur`.
    pub costume: String,
    /// Virtual path `models/<archive>.zst::<costume>/model.json`.
    pub path: String,
    /// Detected container format.
    pub format: ModelFormat,
    /// Renderer mode for this role.
    pub pet_mode: PetMode,
    /// Window left edge (mirror of `window_placement.x`).
    pub window_x: i32,
    /// Window top edge (mirror of `window_placement.y`).
    pub window_y: i32,
    /// Window width.
    pub window_width: u32,
    /// Window height.
    pub window_height: u32,
    /// Full placement record.
    pub window_placement: Placement,
    /// Reserved placement record for pixel mode.
    pub pixel_window_placement: Value,
    /// Default motion group; empty means the model's first idle motion.
    pub default_motion: String,
    /// Default expression; empty means "no expression".
    pub default_expression: String,
    /// Preserve per-role settings written by other versions.
    #[serde(flatten)]
    pub extras: Map<String, Value>,
}

impl Default for ModelEntry {
    fn default() -> Self {
        Self {
            character: String::new(),
            costume: String::new(),
            path: String::new(),
            format: ModelFormat::Moc,
            pet_mode: PetMode::Live2d,
            window_x: -1,
            window_y: -1,
            window_width: 500,
            window_height: 625,
            window_placement: Placement::default(),
            pixel_window_placement: Value::Object(Map::new()),
            default_motion: String::new(),
            default_expression: String::new(),
            extras: Map::new(),
        }
    }
}

impl ModelEntry {
    /// Builds an entry for a (character, costume, virtual path) triple.
    pub fn new(character: &str, costume: &str, path: &str, format: ModelFormat) -> Self {
        Self {
            character: character.to_owned(),
            costume: costume.to_owned(),
            path: path.to_owned(),
            format,
            ..Self::default()
        }
    }

    /// `true` when the entry can own a role window at all.
    pub fn is_usable(&self) -> bool {
        !self.character.is_empty() && !self.costume.is_empty() && !self.path.is_empty()
    }

    /// Stable key `"<character>\t<costume>"` used by `model_action_settings`.
    pub fn action_key(&self) -> String {
        format!("{}\t{}", self.character, self.costume)
    }

    /// Copies the placement record into the legacy mirrored fields.
    pub fn sync_placement_mirror(&mut self) {
        self.window_x = self.window_placement.x;
        self.window_y = self.window_placement.y;
        self.window_width = self.window_placement.width;
        self.window_height = self.window_placement.height;
    }
}

/// Model picker memory: recent / favourite characters and costumes.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ModelPickerState {
    /// Most recently applied characters, newest first.
    pub recent_characters: Vec<String>,
    /// Characters the user starred.
    pub favorite_characters: Vec<String>,
    /// Most recently applied costumes as `"<character>:<costume>"`.
    pub recent_costumes: Vec<String>,
    /// Costumes the user starred as `"<character>:<costume>"`.
    pub favorite_costumes: Vec<String>,
}

impl ModelPickerState {
    /// Maximum remembered entries per bucket.
    const MAX_ENTRIES: usize = 12;

    /// Records a freshly applied (character, costume) pair.
    pub fn remember(&mut self, character: &str, costume: &str) {
        push_front_unique(&mut self.recent_characters, character, Self::MAX_ENTRIES);
        push_front_unique(
            &mut self.recent_costumes,
            &format!("{character}:{costume}"),
            Self::MAX_ENTRIES,
        );
    }

    /// Toggles a character favourite and reports the new state.
    pub fn toggle_favorite_character(&mut self, character: &str) -> bool {
        toggle(&mut self.favorite_characters, character)
    }

    /// Toggles a costume favourite and reports the new state.
    pub fn toggle_favorite_costume(&mut self, character: &str, costume: &str) -> bool {
        toggle(
            &mut self.favorite_costumes,
            &format!("{character}:{costume}"),
        )
    }
}

fn push_front_unique(list: &mut Vec<String>, value: &str, cap: usize) {
    if value.is_empty() {
        return;
    }
    list.retain(|item| item != value);
    list.insert(0, value.to_owned());
    list.truncate(cap);
}

fn toggle(list: &mut Vec<String>, value: &str) -> bool {
    if let Some(position) = list.iter().position(|item| item == value) {
        list.remove(position);
        false
    } else {
        list.insert(0, value.to_owned());
        true
    }
}

/// A named, importable/exportable seven-region click profile.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ClickMotionProfile {
    /// User supplied profile name.
    pub name: String,
    /// Scope: `global`, `character` or `costume` (spec §2.6).
    pub scope: String,
    /// Character the profile was captured for (empty for global).
    pub character: String,
    /// Costume the profile was captured for (empty for character/global).
    pub costume: String,
    /// Seven region actions keyed by `ClickRegion::key`.
    pub actions: ClickProfile,
}

/// The full `config.json` document.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Document version, currently [`SCHEMA_VERSION`].
    pub schema_version: u32,
    /// Global character key (mirror of `models[0]`).
    pub character: String,
    /// Global costume id (mirror of `models[0]`).
    pub costume: String,
    /// UI language tag.
    pub language: String,
    /// Settings-window theme.
    pub dark_theme: DarkTheme,

    /// Target frame rate (30–240).
    pub fps: u32,
    /// Display the measured FPS in the model window.
    pub show_fps: bool,
    /// Whether the surface uses vsync presentation.
    pub vsync: bool,
    /// GPU acceleration switch; only read at process start.
    pub gpu_acceleration: bool,
    /// Window alpha 0.2–1.0.
    pub opacity: f32,
    /// Render quality tier.
    pub live2d_quality: Live2dQuality,
    /// Model zoom in percent, independent of DPI; legacy `0` defaults to 100%.
    pub live2d_scale: u32,
    /// Alpha threshold (0–255) for CPU hit testing.
    pub live2d_hit_alpha_threshold: u8,

    /// Keep re-asserting `HWND_TOPMOST` for exclusive-fullscreen games.
    pub game_topmost: bool,
    /// Swap `WS_EX_TOOLWINDOW` for `WS_EX_APPWINDOW` so OBS can capture the window.
    pub obs_window_capture_compatible: bool,
    /// Hide the Live2D window contents (role stays alive).
    pub hide_live2d_model: bool,
    /// Disable dragging entirely.
    pub drag_locked: bool,
    /// Register the app in the per-user `Run` key.
    pub auto_start: bool,
    /// Broadcast drags between all role windows.
    pub move_all_roles_together: bool,

    /// Look at the mouse cursor.
    pub live2d_head_tracking_enabled: bool,
    /// Look at the nearest other role.
    pub live2d_mutual_gaze_enabled: bool,
    /// Play idle motions.
    pub live2d_idle_actions_enabled: bool,
    /// Play periodic random motions.
    pub live2d_random_actions_enabled: bool,
    /// Window-level emotion displacement.
    pub emotion_behavior_enabled: bool,

    /// Name of the active click profile (empty = inline `click_motion_actions`).
    pub click_motion_active_profile: String,
    /// Seven-region click mapping.
    pub click_motion_actions: ClickProfile,
    /// Saved profiles.
    pub click_motion_profiles: Vec<ClickMotionProfile>,

    /// Role windows, in z-order.
    pub models: Vec<ModelEntry>,
    /// Model picker memory.
    pub model_picker_state: ModelPickerState,
    /// Per-(character,costume) click mappings overriding the global one.
    pub model_action_settings: BTreeMap<String, ClickProfile>,

    /// Unknown keys from newer/older versions, written back untouched.
    #[serde(flatten)]
    pub extras: Map<String, Value>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            schema_version: SCHEMA_VERSION,
            character: String::new(),
            costume: String::new(),
            language: "zh_CN".to_owned(),
            dark_theme: DarkTheme::System,

            fps: 120,
            show_fps: false,
            vsync: true,
            gpu_acceleration: true,
            opacity: bounds::OPACITY_MAX,
            live2d_quality: Live2dQuality::Balanced,
            live2d_scale: bounds::SCALE_DEFAULT,
            live2d_hit_alpha_threshold: 8,

            game_topmost: false,
            obs_window_capture_compatible: false,
            hide_live2d_model: false,
            drag_locked: true,
            auto_start: false,
            move_all_roles_together: false,

            live2d_head_tracking_enabled: true,
            live2d_mutual_gaze_enabled: false,
            live2d_idle_actions_enabled: false,
            live2d_random_actions_enabled: false,
            emotion_behavior_enabled: false,

            click_motion_active_profile: String::new(),
            click_motion_actions: default_click_actions(),
            click_motion_profiles: Vec::new(),

            models: Vec::new(),
            model_picker_state: ModelPickerState::default(),
            model_action_settings: BTreeMap::new(),
            extras: Map::new(),
        }
    }
}

impl Config {
    /// Returns the entry whose window currently owns the "primary" role.
    pub fn primary_model(&self) -> Option<&ModelEntry> {
        self.models.iter().find(|entry| entry.is_usable())
    }

    /// Click mapping to use for one model, preferring the per-costume override.
    pub fn actions_for(&self, entry: &ModelEntry) -> &ClickProfile {
        self.model_action_settings
            .get(&entry.action_key())
            .unwrap_or(&self.click_motion_actions)
    }

    /// Mutable variant of [`Config::actions_for`].
    pub fn actions_for_mut(&mut self, entry: &ModelEntry) -> &mut ClickProfile {
        let key = entry.action_key();
        self.model_action_settings
            .entry(key)
            .or_insert_with(|| self.click_motion_actions.clone())
    }

    /// Action for a single region, falling back to an empty (auto) action.
    pub fn action_for_region(&self, entry: &ModelEntry, region: crate::ClickRegion) -> ClickAction {
        self.actions_for(entry)
            .get(region.key())
            .cloned()
            .unwrap_or_default()
    }

    /// Keeps one usable entry per character and preserves the selected role.
    /// Empty legacy lists retain the global pair for catalog resolution.
    /// Selected UI language, with unknown tags falling back to the default.
    pub fn lang(&self) -> pet_i18n::Lang {
        pet_i18n::Lang::from_tag(&self.language)
    }

    /// Normalizes the mirrored global role fields against `models`.
    pub fn normalize_models(&mut self) {
        let mut characters = std::collections::HashSet::new();
        self.models
            .retain(|entry| entry.is_usable() && characters.insert(entry.character.clone()));
        if !self.models.is_empty()
            && !self
                .models
                .iter()
                .any(|entry| entry.character == self.character && entry.costume == self.costume)
        {
            self.character = self
                .models
                .first()
                .map(|entry| entry.character.clone())
                .unwrap_or_default();
            self.costume = self
                .models
                .first()
                .map(|entry| entry.costume.clone())
                .unwrap_or_default();
        }
    }

    /// `true` when the app has no usable role and should open the model page.
    pub fn needs_model_selection(&self) -> bool {
        self.active_entry().is_none()
    }

    /// Entry matching the global `character`/`costume` pair, else the first one.
    pub fn active_entry(&self) -> Option<&ModelEntry> {
        self.models
            .iter()
            .find(|entry| entry.character == self.character && entry.costume == self.costume)
            .or_else(|| self.primary_model())
    }

    /// Mutable variant of [`Config::active_entry`].
    pub fn active_entry_mut(&mut self) -> Option<&mut ModelEntry> {
        let character = self.character.clone();
        let costume = self.costume.clone();
        if self
            .models
            .iter()
            .any(|entry| entry.character == character && entry.costume == costume)
        {
            return self
                .models
                .iter_mut()
                .find(|entry| entry.character == character && entry.costume == costume);
        }
        self.models.iter_mut().find(|entry| entry.is_usable())
    }

    /// Resolves model zoom without applying the window's DPI conversion.
    pub fn effective_scale_percent(&self) -> f32 {
        if self.live2d_scale == bounds::SCALE_UNSET {
            bounds::SCALE_DEFAULT as f32
        } else {
            self.live2d_scale
                .clamp(bounds::SCALE_MIN, bounds::SCALE_MAX) as f32
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_config_round_trips_through_json() {
        let config = Config::default();
        let json = serde_json::to_string_pretty(&config).expect("serialize");
        let back: Config = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(config, back);
    }

    #[test]
    fn recorded_negative_coordinates_are_not_the_unset_sentinel() {
        assert!(Placement::default().is_unset());
        let placement = Placement {
            x: -1,
            y: -1,
            screen_name: "primary".to_owned(),
            ..Placement::default()
        };
        assert!(!placement.is_unset());
    }

    #[test]
    fn unknown_keys_survive_a_round_trip() {
        let source =
            r#"{"fps": 90, "future_feature": {"nested": [1, 2, 3]}, "llm_api_key": "secret"}"#;
        let config: Config = serde_json::from_str(source).expect("parse");
        assert_eq!(config.fps, 90);
        assert!(config.extras.contains_key("future_feature"));
        assert!(config.extras.contains_key("llm_api_key"));
        let json: Value = serde_json::to_value(&config).expect("serialize");
        assert_eq!(json["future_feature"]["nested"][2], 3);
        assert_eq!(json["llm_api_key"], "secret");
    }

    #[test]
    fn missing_keys_fall_back_to_defaults() {
        let config: Config = serde_json::from_str("{}").expect("parse");
        assert_eq!(config.fps, 120);
        assert_eq!(config.opacity, 1.0);
        assert_eq!(config.live2d_scale, 100);
        assert!(config.click_motion_actions.contains_key("head"));
        assert_eq!(config.click_motion_actions.len(), 7);
        assert!(!config.live2d_idle_actions_enabled);
        assert!(!config.live2d_random_actions_enabled);
        assert!(!config.emotion_behavior_enabled);
    }

    #[test]
    fn saved_behavior_options_remain_enabled() {
        let config: Config = serde_json::from_str(
            r#"{"live2d_idle_actions_enabled":true,"live2d_random_actions_enabled":true,"emotion_behavior_enabled":true}"#,
        )
        .expect("parse");
        assert!(config.live2d_idle_actions_enabled);
        assert!(config.live2d_random_actions_enabled);
        assert!(config.emotion_behavior_enabled);
    }

    #[test]
    fn unusable_entries_are_dropped() {
        let mut config = Config::default();
        config.models.push(ModelEntry::default());
        config.models.push(ModelEntry::new(
            "kasumi",
            "live_default",
            "models/kasumi.zst::live_default/model.json",
            ModelFormat::Moc,
        ));
        config.normalize_models();
        assert_eq!(config.models.len(), 1);
        assert_eq!(config.character, "kasumi");
        assert_eq!(config.costume, "live_default");
    }

    #[test]
    fn model_zoom_defaults_to_100_and_preserves_explicit_values() {
        let mut config = Config::default();
        assert_eq!(config.effective_scale_percent(), 100.0);
        config.live2d_scale = 0;
        assert_eq!(config.effective_scale_percent(), 100.0);
        config.live2d_scale = 125;
        assert_eq!(config.effective_scale_percent(), 125.0);
        config.live2d_scale = 200;
        assert_eq!(config.effective_scale_percent(), 200.0);
        config.live2d_scale = 1;
        assert_eq!(config.effective_scale_percent(), 25.0);
        config.live2d_scale = 9999;
        assert_eq!(config.effective_scale_percent(), 500.0);
    }
}
