use crate::config::{ConfigDocument, ConfigError};
use crate::model::{ModelCatalogEntry, ModelManager, ModelManagerPaths, ModelRoot};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::path::Path;

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
    pub drag_locked: bool,
    pub click_motion_actions: Map<String, Value>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct NativeRuntimeSnapshot {
    pub selected_character: String,
    pub selected_costume: String,
    pub language: String,
    pub fps: i64,
    pub opacity: f64,
    pub lip_sync_max_open: f64,
    pub hit_alpha_threshold: i64,
    pub head_tracking_enabled: bool,
    pub mutual_gaze_enabled: bool,
    pub move_all_roles_together: bool,
    pub drag_locked: bool,
    pub poke_motion: String,
    pub poke_expression: String,
    pub configured_pets: Vec<ConfiguredPetSnapshot>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DashboardSnapshot {
    pub config_loaded_from_file: bool,
    pub config_key_count: usize,
    pub model_catalog: Vec<ModelCatalogEntry>,
    pub runtime: NativeRuntimeSnapshot,
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
                let path = object_string(entry, "path", "");
                if character.is_empty() || path.is_empty() {
                    return None;
                }
                Some(ConfiguredPetSnapshot {
                    character,
                    costume: object_string(entry, "costume", ""),
                    path,
                    pet_mode: object_string(entry, "pet_mode", "live2d"),
                    window_x: object_int(entry, "window_x", global_x),
                    window_y: object_int(entry, "window_y", global_y),
                    window_width: object_int(entry, "window_width", global_width),
                    window_height: object_int(entry, "window_height", global_height),
                    drag_locked: object_bool(entry, "drag_locked", global_drag_locked),
                    click_motion_actions: entry
                        .get("click_motion_actions")
                        .and_then(Value::as_object)
                        .cloned()
                        .unwrap_or_default(),
                })
            })
            .collect();

        Self {
            selected_character: string_value(values, "character", ""),
            selected_costume: string_value(values, "costume", ""),
            language: string_value(values, "language", ""),
            fps: int_value(values, "fps", 120).clamp(1, 1000),
            opacity: float_value(values, "opacity", 1.0).clamp(0.05, 1.0),
            lip_sync_max_open: float_value(values, "live2d_lip_sync_max_open", 0.55)
                .clamp(0.0, 1.0),
            hit_alpha_threshold: int_value(values, "live2d_hit_alpha_threshold", 8).clamp(0, 255),
            head_tracking_enabled: bool_value(values, "live2d_head_tracking_enabled", true),
            mutual_gaze_enabled: bool_value(values, "live2d_mutual_gaze_enabled", false),
            move_all_roles_together: bool_value(values, "move_all_roles_together", false),
            drag_locked: global_drag_locked,
            poke_motion: string_value(values, "poke_motion", ""),
            poke_expression: string_value(values, "poke_expression", ""),
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
                "drag_locked": true,
                "llm_api_key": "must-not-leak",
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
        assert_eq!(snapshot.configured_pets[0].window_x, 42);
        assert!(snapshot.configured_pets[0].drag_locked);
        assert!(!serialized.contains("must-not-leak"));
        assert!(!serialized.contains("llm_api_key"));
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
}
