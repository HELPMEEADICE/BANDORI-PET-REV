//! Settings patches and the apply-level routing table (spec §3.5, §3.6).
//!
//! The settings window never writes `config.json`. It sends a patch; the pet
//! process deserializes the merged document, validates it, writes atomically, and
//! then performs the cheapest action that makes the change visible.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::config::Config;

/// How a changed key becomes visible in the running app.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ApplyLevel {
    /// Mutate the running state immediately.
    Instant,
    /// Release GPU resources, re-extract/decode, render the first frame again.
    ReloadModel,
    /// Resize/restyle the window, rebuild the surface and mask target.
    RebuildWindow,
    /// Only takes effect on the next launch (renderer backend is fixed at startup).
    RestartApp,
}

impl ApplyLevel {
    /// Config token used by the UI.
    pub fn key(self) -> &'static str {
        match self {
            ApplyLevel::Instant => "instant",
            ApplyLevel::ReloadModel => "reload_model",
            ApplyLevel::RebuildWindow => "rebuild_window",
            ApplyLevel::RestartApp => "restart_app",
        }
    }
}

/// Maps a (possibly dotted) config key to its apply level.
///
/// Prefix matching keeps call sites simple: `click_motion_actions.head.motion`
/// and `click_motion_actions` both resolve to [`ApplyLevel::Instant`].
pub fn apply_level_for(key: &str) -> ApplyLevel {
    let root = key.split('.').next().unwrap_or(key);
    match root {
        "fps"
        | "opacity"
        | "drag_locked"
        | "live2d_head_tracking_enabled"
        | "live2d_mutual_gaze_enabled"
        | "live2d_idle_actions_enabled"
        | "live2d_random_actions_enabled"
        | "click_motion_actions"
        | "click_motion_profiles"
        | "click_motion_active_profile"
        | "model_action_settings"
        | "emotion_behavior_enabled"
        | "game_topmost"
        | "hide_live2d_model"
        | "dark_theme"
        | "language"
        | "move_all_roles_together"
        | "auto_start"
        | "live2d_hit_alpha_threshold"
        | "model_picker_state" => ApplyLevel::Instant,

        "character" | "costume" | "live2d_quality" | "models" => ApplyLevel::ReloadModel,

        "live2d_scale" | "obs_window_capture_compatible" => ApplyLevel::RebuildWindow,

        "gpu_acceleration" | "vsync" | "schema_version" => ApplyLevel::RestartApp,

        _ => ApplyLevel::Instant,
    }
}

/// A batch of settings changes keyed by dotted config path.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SettingsPatch {
    /// `"live2d_scale" -> 125`, `"click_motion_actions.head.motion" -> "smile01"`.
    pub values: BTreeMap<String, Value>,
}

impl SettingsPatch {
    /// Builds a patch from an iterator of pairs.
    pub fn from_pairs<I, K>(pairs: I) -> Self
    where
        I: IntoIterator<Item = (K, Value)>,
        K: Into<String>,
    {
        Self {
            values: pairs
                .into_iter()
                .map(|(key, value)| (key.into(), value))
                .collect(),
        }
    }

    /// `true` when there is nothing to do.
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }

    /// Highest apply level contained in the patch (restart wins over rebuild, …).
    pub fn highest_apply_level(&self) -> ApplyLevel {
        self.values
            .keys()
            .map(|key| apply_level_for(key))
            .max()
            .unwrap_or(ApplyLevel::Instant)
    }

    /// Applies every key to `config`, returning the keys that were rejected.
    pub fn apply_to(&self, config: &mut Config) -> Vec<String> {
        let mut rejected = Vec::new();
        for (path, value) in &self.values {
            let mut document = match serde_json::to_value(&*config) {
                Ok(document) => document,
                Err(_) => {
                    rejected.push(path.clone());
                    continue;
                }
            };
            if !set_path(&mut document, path, value.clone()) {
                rejected.push(path.clone());
                continue;
            }
            match serde_json::from_value::<Config>(document) {
                Ok(next) => *config = next,
                Err(_) => rejected.push(path.clone()),
            }
        }
        rejected
    }

    /// Strips keys the config schema cannot represent, returning them.
    pub fn retain_known_keys(&mut self, config: &Config) -> Vec<String> {
        let document = serde_json::to_value(config).unwrap_or(Value::Null);
        let mut rejected = Vec::new();
        self.values.retain(|path, _| {
            let known = path_exists(&document, path);
            if !known {
                rejected.push(path.clone());
            }
            known
        });
        rejected
    }
}

/// Sets a dotted path inside a JSON document, creating intermediate objects.
///
/// Returns `false` when a segment cannot be traversed (for example indexing a
/// scalar or appending to an array with a non-numeric segment).
pub fn set_path(document: &mut Value, path: &str, value: Value) -> bool {
    let segments: Vec<&str> = path.split('.').filter(|part| !part.is_empty()).collect();
    if segments.is_empty() {
        return false;
    }
    let mut cursor = document;
    for (index, segment) in segments.iter().enumerate() {
        let last = index + 1 == segments.len();
        if last {
            match cursor {
                Value::Object(map) => {
                    if value.is_null() {
                        map.remove(*segment);
                    } else {
                        map.insert((*segment).to_owned(), value);
                    }
                    return true;
                }
                Value::Array(items) => {
                    let Ok(position) = segment.parse::<usize>() else {
                        return false;
                    };
                    if position >= items.len() {
                        return false;
                    }
                    if value.is_null() {
                        items.remove(position);
                    } else {
                        items[position] = value;
                    }
                    return true;
                }
                _ => return false,
            }
        }

        let next = match cursor {
            Value::Object(map) => {
                if !map.contains_key(*segment) {
                    let next_is_index = segments[index + 1].parse::<usize>().is_ok();
                    let fresh = if next_is_index {
                        Value::Array(Vec::new())
                    } else {
                        Value::Object(Default::default())
                    };
                    map.insert((*segment).to_owned(), fresh);
                }
                map.get_mut(*segment).expect("just inserted")
            }
            Value::Array(items) => {
                let Ok(position) = segment.parse::<usize>() else {
                    return false;
                };
                if position >= items.len() {
                    return false;
                }
                &mut items[position]
            }
            _ => return false,
        };
        cursor = next;
    }
    false
}

/// `true` when the dotted path resolves to an existing value.
pub fn path_exists(document: &Value, path: &str) -> bool {
    let mut cursor = document;
    for segment in path.split('.').filter(|part| !part.is_empty()) {
        cursor = match cursor {
            Value::Object(map) => match map.get(segment) {
                Some(next) => next,
                None => return false,
            },
            Value::Array(items) => {
                let Ok(position) = segment.parse::<usize>() else {
                    return false;
                };
                match items.get(position) {
                    Some(next) => next,
                    None => return false,
                }
            }
            _ => return false,
        };
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::Live2dQuality;

    #[test]
    fn apply_levels_follow_the_spec_table() {
        assert_eq!(apply_level_for("fps"), ApplyLevel::Instant);
        assert_eq!(
            apply_level_for("click_motion_actions.head.motion"),
            ApplyLevel::Instant
        );
        assert_eq!(apply_level_for("live2d_quality"), ApplyLevel::ReloadModel);
        assert_eq!(
            apply_level_for("models.0.window_x"),
            ApplyLevel::ReloadModel
        );
        assert_eq!(apply_level_for("live2d_scale"), ApplyLevel::RebuildWindow);
        assert_eq!(apply_level_for("gpu_acceleration"), ApplyLevel::RestartApp);
    }

    #[test]
    fn highest_level_wins() {
        let patch = SettingsPatch::from_pairs([
            ("fps", serde_json::json!(60)),
            ("live2d_scale", serde_json::json!(150)),
            ("character", serde_json::json!("anon")),
        ]);
        assert_eq!(patch.highest_apply_level(), ApplyLevel::RebuildWindow);
    }

    #[test]
    fn nested_patch_reaches_into_click_actions() {
        let mut config = Config::default();
        let patch = SettingsPatch::from_pairs([(
            "click_motion_actions.lower_body_left.expression",
            serde_json::json!("smile02"),
        )]);
        let rejected = patch.apply_to(&mut config);
        assert!(rejected.is_empty(), "{rejected:?}");
        assert_eq!(
            config.click_motion_actions["lower_body_left"].expression,
            "smile02"
        );
    }

    #[test]
    fn invalid_type_is_rejected_and_config_untouched() {
        let mut config = Config::default();
        let before = config.clone();
        let patch = SettingsPatch::from_pairs([("fps", serde_json::json!("fast"))]);
        let rejected = patch.apply_to(&mut config);
        assert_eq!(rejected, vec!["fps".to_owned()]);
        assert_eq!(config, before);
    }

    #[test]
    fn enum_patch_accepts_config_tokens() {
        let mut config = Config::default();
        let patch =
            SettingsPatch::from_pairs([("live2d_quality", serde_json::json!("performance"))]);
        assert!(patch.apply_to(&mut config).is_empty());
        assert_eq!(config.live2d_quality, Live2dQuality::Performance);
    }

    #[test]
    fn unknown_key_is_reported_by_retain_known_keys() {
        let config = Config::default();
        let mut patch = SettingsPatch::from_pairs([
            ("fps", serde_json::json!(75)),
            ("totally_unknown", serde_json::json!(1)),
        ]);
        let rejected = patch.retain_known_keys(&config);
        assert_eq!(rejected, vec!["totally_unknown".to_owned()]);
        assert!(patch.values.contains_key("fps"));
    }
}
