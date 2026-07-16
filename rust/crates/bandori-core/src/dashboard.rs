use crate::config::{ConfigDocument, ConfigError};
use crate::model::{ModelCatalogEntry, ModelManager, ModelManagerPaths, ModelRoot};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::Path;
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ConfiguredPetSnapshot {
    pub character: String,
    pub costume: String,
    pub path: String,
    pub pet_mode: String,
    pub window_x: i64,
    pub window_y: i64,
    pub window_width: i64,
    pub window_height: i64,
    pub pixel_window_x: i64,
    pub pixel_window_y: i64,
    pub drag_locked: bool,
    pub default_motion: String,
    pub default_expression: String,
    pub click_motion_actions: Map<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NativeRuntimeSnapshot {
    pub selected_character: String,
    pub selected_costume: String,
    pub pet_mode: String,
    pub window_x: i64,
    pub window_y: i64,
    pub window_width: i64,
    pub window_height: i64,
    pub pixel_window_x: i64,
    pub pixel_window_y: i64,
    pub chat_window_x: Option<i64>,
    pub chat_window_y: Option<i64>,
    pub chat_window_width: Option<i64>,
    pub chat_window_height: Option<i64>,
    pub language: String,
    pub auto_start: bool,
    pub active_user_key: String,
    pub dark_theme: String,
    pub vsync: bool,
    pub live2d_quality: String,
    pub live2d_scale: i64,
    pub fps: i64,
    pub opacity: f64,
    pub lip_sync_max_open: f64,
    pub hit_alpha_threshold: i64,
    pub idle_actions_enabled: bool,
    pub random_actions_enabled: bool,
    pub head_tracking_enabled: bool,
    pub mutual_gaze_enabled: bool,
    pub emotion_behavior_enabled: bool,
    pub move_all_roles_together: bool,
    pub drag_locked: bool,
    pub poke_motion: String,
    pub poke_expression: String,
    pub chat_attachment_auto_cleanup_enabled: bool,
    pub chat_attachment_retention_days: i64,
    pub birthday_tray_notifications_enabled: bool,
    pub compact_ai_window_enabled: bool,
    pub ai_event_overlay_enabled: bool,
    pub chat_integration_overlay_enabled: bool,
    pub configured_pets: Vec<ConfiguredPetSnapshot>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DashboardSnapshot {
    pub config_loaded_from_file: bool,
    pub config_key_count: usize,
    pub model_catalog: Vec<ModelCatalogEntry>,
    pub runtime: NativeRuntimeSnapshot,
}

#[derive(Clone, Debug, Default, PartialEq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeSettingsUpdate {
    pub fps: Option<i64>,
    pub opacity: Option<f64>,
    pub auto_start: Option<bool>,
    pub dark_theme: Option<String>,
    pub vsync: Option<bool>,
    pub live2d_quality: Option<String>,
    pub live2d_scale: Option<i64>,
    pub live2d_idle_actions_enabled: Option<bool>,
    pub live2d_random_actions_enabled: Option<bool>,
    pub drag_locked: Option<bool>,
    pub move_all_roles_together: Option<bool>,
    pub live2d_head_tracking_enabled: Option<bool>,
    pub live2d_mutual_gaze_enabled: Option<bool>,
    pub emotion_behavior_enabled: Option<bool>,
    pub chat_window_x: Option<i64>,
    pub chat_window_y: Option<i64>,
    pub chat_window_width: Option<i64>,
    pub chat_window_height: Option<i64>,
    pub chat_attachment_auto_cleanup_enabled: Option<bool>,
    pub chat_attachment_retention_days: Option<i64>,
    pub birthday_tray_notifications_enabled: Option<bool>,
}

#[derive(Debug, Error)]
pub enum NativeSettingsError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("native settings JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("unsupported theme mode: {0}")]
    UnsupportedTheme(String),
    #[error("unsupported Live2D quality: {0}")]
    UnsupportedLive2dQuality(String),
}

pub fn save_native_settings(
    config_path: impl AsRef<Path>,
    settings_json: &str,
) -> Result<NativeRuntimeSnapshot, NativeSettingsError> {
    let update: NativeSettingsUpdate = serde_json::from_str(settings_json)?;
    let mut config = ConfigDocument::load(config_path.as_ref())?;
    update.apply_to(&mut config)?;
    config.save(config_path)?;
    Ok(NativeRuntimeSnapshot::from_config(&config))
}

impl NativeSettingsUpdate {
    pub fn apply_to(self, config: &mut ConfigDocument) -> Result<(), NativeSettingsError> {
        if let Some(fps) = self.fps {
            config.set("fps", Value::from(fps.clamp(10, 240)));
        }
        if let Some(opacity) = self.opacity {
            config.set("opacity", Value::from(opacity.clamp(0.05, 1.0)));
        }
        if let Some(enabled) = self.auto_start {
            config.set("auto_start", Value::Bool(enabled));
        }
        if let Some(theme) = self.dark_theme {
            let theme = theme.trim().to_ascii_lowercase();
            if !matches!(theme.as_str(), "on" | "off" | "follow_system") {
                return Err(NativeSettingsError::UnsupportedTheme(theme));
            }
            config.set("dark_theme", Value::String(theme));
        }
        if let Some(vsync) = self.vsync {
            config.set("vsync", Value::Bool(vsync));
        }
        if let Some(quality) = self.live2d_quality {
            let quality = quality.trim().to_ascii_lowercase();
            if !matches!(quality.as_str(), "performance" | "balanced") {
                return Err(NativeSettingsError::UnsupportedLive2dQuality(quality));
            }
            config.set("live2d_quality", Value::String(quality));
        }
        if let Some(scale) = self.live2d_scale {
            let scale = if scale <= 0 {
                100
            } else {
                scale.clamp(25, 500)
            };
            config.set("live2d_scale", Value::from(scale));
        }
        if let Some(enabled) = self.live2d_idle_actions_enabled {
            config.set("live2d_idle_actions_enabled", Value::Bool(enabled));
        }
        if let Some(enabled) = self.live2d_random_actions_enabled {
            config.set("live2d_random_actions_enabled", Value::Bool(enabled));
        }
        if let Some(locked) = self.drag_locked {
            config.set("drag_locked", Value::Bool(locked));
        }
        if let Some(enabled) = self.move_all_roles_together {
            config.set("move_all_roles_together", Value::Bool(enabled));
        }
        if let Some(enabled) = self.live2d_head_tracking_enabled {
            config.set("live2d_head_tracking_enabled", Value::Bool(enabled));
        }
        if let Some(enabled) = self.live2d_mutual_gaze_enabled {
            config.set("live2d_mutual_gaze_enabled", Value::Bool(enabled));
        }
        if let Some(enabled) = self.emotion_behavior_enabled {
            config.set("emotion_behavior_enabled", Value::Bool(enabled));
        }
        if let Some(value) = self.chat_window_x {
            config.set("chat_window_x", Value::from(value.clamp(-100_000, 100_000)));
        }
        if let Some(value) = self.chat_window_y {
            config.set("chat_window_y", Value::from(value.clamp(-100_000, 100_000)));
        }
        if let Some(value) = self.chat_window_width {
            config.set("chat_window_width", Value::from(value.clamp(760, 16_384)));
        }
        if let Some(value) = self.chat_window_height {
            config.set("chat_window_height", Value::from(value.clamp(520, 16_384)));
        }
        if let Some(enabled) = self.chat_attachment_auto_cleanup_enabled {
            config.set("chat_attachment_auto_cleanup_enabled", Value::Bool(enabled));
        }
        if let Some(days) = self.chat_attachment_retention_days {
            config.set(
                "chat_attachment_retention_days",
                Value::from(days.clamp(1, 3650)),
            );
        }
        if let Some(enabled) = self.birthday_tray_notifications_enabled {
            config.set("birthday_tray_notifications_enabled", Value::Bool(enabled));
        }
        Ok(())
    }
}

impl DashboardSnapshot {
    pub fn load(
        project_root: impl AsRef<Path>,
        user_models_root: impl AsRef<Path>,
        config_path: impl AsRef<Path>,
    ) -> Result<Self, ConfigError> {
        let project_root = project_root.as_ref();
        let user_models_root = user_models_root.as_ref();
        let config = ConfigDocument::load(config_path)?;
        let manager = ModelManager::scan(model_paths(project_root, user_models_root));
        Ok(Self {
            config_loaded_from_file: config.loaded_from_file(),
            config_key_count: config.values().len(),
            model_catalog: manager.catalog(),
            runtime: NativeRuntimeSnapshot::from_config(&config),
        })
    }

    pub fn character_count(&self) -> usize {
        self.model_catalog
            .iter()
            .map(|entry| entry.character.as_str())
            .collect::<std::collections::HashSet<_>>()
            .len()
    }
}

impl NativeRuntimeSnapshot {
    pub fn from_config(config: &ConfigDocument) -> Self {
        let values = config.values();
        let global_drag_locked = bool_value(values, "drag_locked", false);
        let global_width = int_value(values, "window_width", 400);
        let global_height = int_value(values, "window_height", 500);
        let global_x = int_value(values, "window_x", -1);
        let global_y = int_value(values, "window_y", -1);
        let configured_pets = values
            .get("models")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_object)
            .filter_map(|entry| {
                let character = object_string(entry, "character", "");
                let costume = object_string(entry, "costume", "");
                let path = object_string(entry, "path", "");
                if character.is_empty() || path.is_empty() {
                    return None;
                }
                let profile = model_action_profile(values, &character, &costume);
                let default_motion = object_string(entry, "default_motion", "");
                let default_expression = object_string(entry, "default_expression", "");
                let click_motion_actions = entry
                    .get("click_motion_actions")
                    .and_then(Value::as_object)
                    .filter(|actions| !actions.is_empty())
                    .cloned()
                    .or_else(|| {
                        profile
                            .and_then(|value| value.get("click_motion_actions"))
                            .and_then(Value::as_object)
                            .cloned()
                    })
                    .unwrap_or_default();
                Some(ConfiguredPetSnapshot {
                    character,
                    costume,
                    path,
                    pet_mode: object_string(entry, "pet_mode", "live2d"),
                    window_x: object_int(entry, "window_x", global_x),
                    window_y: object_int(entry, "window_y", global_y),
                    window_width: object_int(entry, "window_width", global_width),
                    window_height: object_int(entry, "window_height", global_height),
                    pixel_window_x: object_int(
                        entry,
                        "pixel_window_x",
                        int_value(values, "pixel_window_x", -1),
                    ),
                    pixel_window_y: object_int(
                        entry,
                        "pixel_window_y",
                        int_value(values, "pixel_window_y", -1),
                    ),
                    drag_locked: object_bool(entry, "drag_locked", global_drag_locked),
                    default_motion: non_empty_or_profile(default_motion, profile, "default_motion"),
                    default_expression: non_empty_or_profile(
                        default_expression,
                        profile,
                        "default_expression",
                    ),
                    click_motion_actions,
                })
            })
            .collect();
        let role_character = string_value(values, "pov_role_character", "");
        let active_user_key = if string_value(values, "pov_mode", "off") == "role"
            && !role_character.trim().is_empty()
        {
            format!("__role__:{role_character}")
        } else {
            string_value(values, "active_user_profile", "__default__")
        };
        let active_user_key = if active_user_key.trim().is_empty() {
            "__default__".to_owned()
        } else {
            active_user_key
        };

        Self {
            selected_character: string_value(values, "character", ""),
            selected_costume: string_value(values, "costume", ""),
            pet_mode: match string_value(values, "pet_mode", "live2d").as_str() {
                "pixel" => "pixel".to_owned(),
                _ => "live2d".to_owned(),
            },
            window_x: global_x,
            window_y: global_y,
            window_width: global_width,
            window_height: global_height,
            pixel_window_x: int_value(values, "pixel_window_x", -1),
            pixel_window_y: int_value(values, "pixel_window_y", -1),
            chat_window_x: optional_int_value(values, "chat_window_x"),
            chat_window_y: optional_int_value(values, "chat_window_y"),
            chat_window_width: optional_int_value(values, "chat_window_width"),
            chat_window_height: optional_int_value(values, "chat_window_height"),
            language: string_value(values, "language", ""),
            auto_start: bool_value(values, "auto_start", false),
            active_user_key,
            dark_theme: string_value(values, "dark_theme", "follow_system"),
            vsync: bool_value(values, "vsync", true),
            live2d_quality: normalized_live2d_quality(values),
            live2d_scale: normalized_live2d_scale(values),
            fps: int_value(values, "fps", 120).clamp(1, 1000),
            opacity: float_value(values, "opacity", 1.0).clamp(0.05, 1.0),
            lip_sync_max_open: float_value(values, "live2d_lip_sync_max_open", 0.55)
                .clamp(0.0, 1.0),
            hit_alpha_threshold: int_value(values, "live2d_hit_alpha_threshold", 8).clamp(0, 255),
            idle_actions_enabled: bool_value(values, "live2d_idle_actions_enabled", true),
            random_actions_enabled: bool_value(values, "live2d_random_actions_enabled", true),
            head_tracking_enabled: bool_value(values, "live2d_head_tracking_enabled", true),
            mutual_gaze_enabled: bool_value(values, "live2d_mutual_gaze_enabled", false),
            emotion_behavior_enabled: bool_value(values, "emotion_behavior_enabled", true),
            move_all_roles_together: bool_value(values, "move_all_roles_together", false),
            drag_locked: global_drag_locked,
            poke_motion: string_value(values, "poke_motion", ""),
            poke_expression: string_value(values, "poke_expression", ""),
            chat_attachment_auto_cleanup_enabled: bool_value(
                values,
                "chat_attachment_auto_cleanup_enabled",
                false,
            ),
            chat_attachment_retention_days: int_value(values, "chat_attachment_retention_days", 30)
                .clamp(1, 3650),
            birthday_tray_notifications_enabled: bool_value(
                values,
                "birthday_tray_notifications_enabled",
                true,
            ),
            compact_ai_window_enabled: bool_value(values, "compact_ai_window_enabled", false),
            ai_event_overlay_enabled: bool_value(values, "ai_event_overlay_enabled", false),
            chat_integration_overlay_enabled: bool_value(
                values,
                "chat_integration_overlay_enabled",
                true,
            ),
            configured_pets,
        }
    }
}

fn model_paths(project_root: &Path, user_models_root: &Path) -> ModelManagerPaths {
    let bundled_models = project_root.join("models");
    let user_models = if user_models_root.as_os_str().is_empty() {
        bundled_models.clone()
    } else {
        user_models_root.to_path_buf()
    };
    let mut search_roots = vec![ModelRoot {
        path: bundled_models.clone(),
        override_existing: false,
    }];
    if user_models != bundled_models {
        search_roots.push(ModelRoot {
            path: user_models.clone(),
            override_existing: true,
        });
    }
    let mut lookup_roots = vec![user_models];
    if !lookup_roots.contains(&bundled_models) {
        lookup_roots.push(bundled_models);
    }
    ModelManagerPaths {
        base_dir: project_root.to_path_buf(),
        search_roots,
        lookup_roots,
        outfit_json: project_root.join("outfit.json"),
        band_json: project_root.join("band.json"),
        characters_dir: project_root.join("characters"),
        custom_models_label: "Custom Models".into(),
    }
}

fn string_value(values: &Map<String, Value>, key: &str, fallback: &str) -> String {
    values
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or(fallback)
        .to_owned()
}

fn int_value(values: &Map<String, Value>, key: &str, fallback: i64) -> i64 {
    values.get(key).and_then(Value::as_i64).unwrap_or(fallback)
}

fn optional_int_value(values: &Map<String, Value>, key: &str) -> Option<i64> {
    values.get(key).and_then(|value| {
        value
            .as_i64()
            .or_else(|| value.as_f64().map(|number| number.round() as i64))
    })
}

fn float_value(values: &Map<String, Value>, key: &str, fallback: f64) -> f64 {
    values.get(key).and_then(Value::as_f64).unwrap_or(fallback)
}

fn bool_value(values: &Map<String, Value>, key: &str, fallback: bool) -> bool {
    values.get(key).and_then(Value::as_bool).unwrap_or(fallback)
}

fn object_string(values: &Map<String, Value>, key: &str, fallback: &str) -> String {
    string_value(values, key, fallback)
}

fn object_int(values: &Map<String, Value>, key: &str, fallback: i64) -> i64 {
    int_value(values, key, fallback)
}

fn object_bool(values: &Map<String, Value>, key: &str, fallback: bool) -> bool {
    bool_value(values, key, fallback)
}

fn normalized_live2d_quality(values: &Map<String, Value>) -> String {
    match string_value(values, "live2d_quality", "balanced")
        .trim()
        .to_ascii_lowercase()
        .as_str()
    {
        "performance" => "performance".to_owned(),
        _ => "balanced".to_owned(),
    }
}

fn normalized_live2d_scale(values: &Map<String, Value>) -> i64 {
    let scale = int_value(values, "live2d_scale", 0);
    if scale <= 0 {
        100
    } else {
        scale.clamp(25, 500)
    }
}

fn model_action_profile<'a>(
    values: &'a Map<String, Value>,
    character: &str,
    costume: &str,
) -> Option<&'a Map<String, Value>> {
    let key = format!("{character}\t{costume}");
    values
        .get("model_action_settings")
        .and_then(Value::as_object)
        .and_then(|profiles| profiles.get(&key))
        .and_then(Value::as_object)
}

fn non_empty_or_profile(direct: String, profile: Option<&Map<String, Value>>, key: &str) -> String {
    if !direct.trim().is_empty() {
        return direct;
    }
    profile
        .and_then(|value| value.get(key))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use tempfile::TempDir;

    fn write_json(path: &Path, value: Value) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    }

    #[test]
    fn runtime_snapshot_exposes_only_native_launch_fields() {
        let config = ConfigDocument::from_value(
            json!({
                "fps": 240,
                "opacity": 0.7,
                "vsync": false,
                "live2d_quality": "performance",
                "live2d_scale": 250,
                "live2d_idle_actions_enabled": false,
                "live2d_random_actions_enabled": false,
                "drag_locked": true,
                "chat_attachment_auto_cleanup_enabled": true,
                "chat_attachment_retention_days": 45,
                "birthday_tray_notifications_enabled": false,
                "pet_mode": "pixel",
                "pixel_window_x": 77,
                "pixel_window_y": 88,
                "chat_window_x": 101,
                "chat_window_y": 202,
                "chat_window_width": 900,
                "chat_window_height": 700,
                "active_user_profile": "alice",
                "llm_api_key": "must-not-leak",
                "model_action_settings": {
                    "tomorin\tlive_01": {
                        "default_motion": "Idle",
                        "default_expression": "smile",
                        "click_motion_actions": {"upper_body_center": "tap_body"}
                    }
                },
                "models": [{
                    "character": "tomorin",
                    "costume": "live_01",
                    "path": "models/tomorin/live_01/model.json",
                    "window_x": 42,
                    "click_motion_actions": {"head": "tap_head"}
                }]
            }),
            true,
        )
        .unwrap();

        let snapshot = NativeRuntimeSnapshot::from_config(&config);
        let serialized = serde_json::to_string(&snapshot).unwrap();
        assert_eq!(snapshot.fps, 240);
        assert_eq!(snapshot.active_user_key, "alice");
        assert!(!snapshot.vsync);
        assert_eq!(snapshot.live2d_quality, "performance");
        assert_eq!(snapshot.live2d_scale, 250);
        assert!(!snapshot.idle_actions_enabled);
        assert!(!snapshot.random_actions_enabled);
        assert!(snapshot.chat_attachment_auto_cleanup_enabled);
        assert_eq!(snapshot.chat_attachment_retention_days, 45);
        assert!(!snapshot.birthday_tray_notifications_enabled);
        assert_eq!(snapshot.pet_mode, "pixel");
        assert_eq!(snapshot.pixel_window_x, 77);
        assert_eq!(snapshot.pixel_window_y, 88);
        assert_eq!(snapshot.chat_window_x, Some(101));
        assert_eq!(snapshot.chat_window_y, Some(202));
        assert_eq!(snapshot.chat_window_width, Some(900));
        assert_eq!(snapshot.chat_window_height, Some(700));
        assert_eq!(snapshot.configured_pets[0].window_x, 42);
        assert!(snapshot.configured_pets[0].drag_locked);
        assert_eq!(snapshot.configured_pets[0].default_motion, "Idle");
        assert_eq!(snapshot.configured_pets[0].default_expression, "smile");
        assert_eq!(
            snapshot.configured_pets[0].click_motion_actions["head"],
            "tap_head"
        );
        assert!(!serialized.contains("must-not-leak"));
        assert!(!serialized.contains("llm_api_key"));
    }

    #[test]
    fn runtime_snapshot_uses_python_default_user_key() {
        let snapshot = NativeRuntimeSnapshot::from_config(&ConfigDocument::default());
        assert_eq!(snapshot.active_user_key, "__default__");
        assert!(snapshot.birthday_tray_notifications_enabled);
        assert_eq!(snapshot.pet_mode, "live2d");
    }

    #[test]
    fn runtime_snapshot_uses_role_partition_only_for_active_role_pov() {
        let role = ConfigDocument::from_value(
            json!({
                "active_user_profile": "alice",
                "pov_mode": "role",
                "pov_role_character": "moca"
            }),
            true,
        )
        .unwrap();
        assert_eq!(
            NativeRuntimeSnapshot::from_config(&role).active_user_key,
            "__role__:moca"
        );

        let custom = ConfigDocument::from_value(
            json!({
                "active_user_profile": "alice",
                "pov_mode": "custom",
                "pov_role_character": "moca"
            }),
            true,
        )
        .unwrap();
        assert_eq!(
            NativeRuntimeSnapshot::from_config(&custom).active_user_key,
            "alice"
        );
    }

    #[test]
    fn dashboard_merges_bundled_and_user_model_catalogs() {
        let root = TempDir::new().unwrap();
        let user_models = root.path().join("user-models");
        write_json(
            &root.path().join("models/kasumi/casual/model.json"),
            json!({"model": "kasumi.moc"}),
        );
        write_json(
            &user_models.join("ran/live_01/ran.model3.json"),
            json!({"Version": 3}),
        );
        write_json(
            &root.path().join("config.json"),
            json!({"fps": 90, "models": []}),
        );

        let snapshot =
            DashboardSnapshot::load(root.path(), &user_models, root.path().join("config.json"))
                .unwrap();
        assert_eq!(snapshot.character_count(), 2);
        assert_eq!(snapshot.model_catalog.len(), 2);
        assert_eq!(snapshot.runtime.fps, 90);
        assert!(snapshot.config_loaded_from_file);
    }

    #[test]
    fn native_settings_are_whitelisted_clamped_and_saved_atomically() {
        let root = TempDir::new().unwrap();
        let config_path = root.path().join("config.json");
        write_json(
            &config_path,
            json!({
                "fps": 60,
                "opacity": 1.0,
                "dark_theme": "follow_system",
                "llm_api_key": "keep-me"
            }),
        );

        let runtime = save_native_settings(
            &config_path,
            r#"{
                "fps": 999,
                "opacity": 0.01,
                "auto_start": true,
                "dark_theme": "on",
                "vsync": false,
                "live2d_quality": "performance",
                "live2d_scale": 999,
                "live2d_idle_actions_enabled": false,
                "live2d_random_actions_enabled": false,
                "drag_locked": true,
                "move_all_roles_together": true,
                "live2d_head_tracking_enabled": false,
                "live2d_mutual_gaze_enabled": true,
                "emotion_behavior_enabled": false,
                "chat_window_x": -999999,
                "chat_window_y": 999999,
                "chat_window_width": 1,
                "chat_window_height": 999999,
                "chat_attachment_auto_cleanup_enabled": true,
                "chat_attachment_retention_days": 9999,
                "birthday_tray_notifications_enabled": false
            }"#,
        )
        .unwrap();
        let saved: Value = serde_json::from_slice(&fs::read(config_path).unwrap()).unwrap();
        assert_eq!(runtime.fps, 240);
        assert_eq!(runtime.opacity, 0.05);
        assert!(runtime.auto_start);
        assert_eq!(runtime.dark_theme, "on");
        assert!(!runtime.vsync);
        assert_eq!(runtime.live2d_quality, "performance");
        assert_eq!(runtime.live2d_scale, 500);
        assert!(!runtime.idle_actions_enabled);
        assert!(!runtime.random_actions_enabled);
        assert!(runtime.drag_locked);
        assert!(!runtime.emotion_behavior_enabled);
        assert_eq!(runtime.chat_window_x, Some(-100_000));
        assert_eq!(runtime.chat_window_y, Some(100_000));
        assert_eq!(runtime.chat_window_width, Some(760));
        assert_eq!(runtime.chat_window_height, Some(16_384));
        assert!(runtime.chat_attachment_auto_cleanup_enabled);
        assert_eq!(runtime.chat_attachment_retention_days, 3650);
        assert!(!runtime.birthday_tray_notifications_enabled);
        assert_eq!(saved["llm_api_key"], "keep-me");
        assert_eq!(saved["auto_start"], true);
        assert_eq!(saved["live2d_mutual_gaze_enabled"], true);
        assert_eq!(saved["emotion_behavior_enabled"], false);
        assert_eq!(saved["chat_window_x"], -100_000);
        assert_eq!(saved["chat_window_y"], 100_000);
        assert_eq!(saved["chat_window_width"], 760);
        assert_eq!(saved["chat_window_height"], 16_384);
        assert_eq!(saved["chat_attachment_auto_cleanup_enabled"], true);
        assert_eq!(saved["chat_attachment_retention_days"], 3650);
        assert_eq!(saved["birthday_tray_notifications_enabled"], false);
    }

    #[test]
    fn native_settings_reject_unknown_keys_and_invalid_themes() {
        let mut config = ConfigDocument::default();
        let unknown = serde_json::from_str::<NativeSettingsUpdate>(r#"{"llm_api_key":"x"}"#);
        assert!(unknown.is_err());
        let invalid = NativeSettingsUpdate {
            dark_theme: Some("sepia".into()),
            ..NativeSettingsUpdate::default()
        };
        assert!(matches!(
            invalid.apply_to(&mut config),
            Err(NativeSettingsError::UnsupportedTheme(theme)) if theme == "sepia"
        ));
        let invalid_quality = NativeSettingsUpdate {
            live2d_quality: Some("cinematic".into()),
            ..NativeSettingsUpdate::default()
        };
        assert!(matches!(
            invalid_quality.apply_to(&mut config),
            Err(NativeSettingsError::UnsupportedLive2dQuality(quality)) if quality == "cinematic"
        ));
    }
}
