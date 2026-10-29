//! Translate the existing Python config without writing or losing unknown keys.
use pet_config::{Config, ModelEntry, ModelFormat};
use serde_json::{json, Value};

pub fn translate(raw: &Value, character: &str, costume: &str, path: &str) -> (Config, ModelEntry) {
    let mut value = raw.clone();
    let map = value
        .as_object_mut()
        .expect("configuration must be an object");
    // Python has a bool theme and wraps per-model action profiles in an object.
    map.remove("dark_theme");
    map.remove("model_action_settings");
    map.remove("click_motion_profiles");
    let mut entry_value = raw
        .get("models")
        .and_then(Value::as_array)
        .and_then(|models| {
            models
                .iter()
                .find(|e| e["character"] == character && e["costume"] == costume)
        })
        .cloned()
        .unwrap_or_else(|| json!({}));
    let entry_map = entry_value.as_object_mut().unwrap();
    if let Some(root) = raw.get("_native_assets_root").and_then(Value::as_str) {
        entry_map.insert(
            "pixel_path".into(),
            json!(std::path::Path::new(root)
                .join("pixels")
                .join(format!("{character}.webp"))),
        );
    }
    entry_map.insert("character".into(), json!(character));
    entry_map.insert("costume".into(), json!(costume));
    entry_map.insert("path".into(), json!(path));
    let key = format!("{character}\t{costume}");
    if let Some(profile) = raw
        .get("model_action_settings")
        .and_then(|v| v.get(&key))
        .and_then(Value::as_object)
    {
        entry_map.extend(profile.clone());
    }
    // Older configurations use -1 as the unsaved position sentinel.
    if entry_map
        .get("window_placement")
        .and_then(Value::as_object)
        .is_none_or(|m| m.is_empty())
    {
        let x = entry_map
            .get("window_x")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        let y = entry_map
            .get("window_y")
            .and_then(Value::as_i64)
            .unwrap_or(-1);
        if x != -1 || y != -1 {
            entry_map.insert(
                "window_placement".into(),
                json!({"x":x,"y":y,"width":400,"height":500}),
            );
        }
    }
    let mut entry: ModelEntry = serde_json::from_value(entry_value).unwrap_or_else(|_| {
        ModelEntry::new(character, costume, path, ModelFormat::from_path(path))
    });
    entry.format = ModelFormat::from_path(path);
    map.insert("models".into(), json!([]));
    // Deserialize independent fields, so a malformed legacy field cannot reset
    // unrelated display and behavior settings to their defaults.
    let mut config_value = serde_json::to_value(Config::default()).unwrap();
    for (key, v) in map.iter() {
        let old = config_value.get(key).cloned();
        config_value[key] = v.clone();
        if serde_json::from_value::<Config>(config_value.clone()).is_err() {
            if let Some(old) = old {
                config_value[key] = old;
            } else {
                config_value.as_object_mut().unwrap().remove(key);
            }
        }
    }
    let mut config: Config = serde_json::from_value(config_value).unwrap();
    config.character = character.into();
    config.costume = costume.into();
    config.fps = config.fps.clamp(15, 240);
    config.opacity = config.opacity.clamp(0.05, 1.0);
    config.models = vec![entry.clone()];
    if let Some(actions) = entry
        .extras
        .get("click_motion_actions")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
    {
        config.click_motion_actions = actions;
    }
    (config, entry)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn show_fps_config_is_loaded_and_updated_independently() {
        let (default, _) = translate(&json!({}), "test", "default", "test.moc3");
        assert!(!default.show_fps);
        let (enabled, _) = translate(&json!({"show_fps": true}), "test", "default", "test.moc3");
        assert!(enabled.show_fps);
        let (disabled, _) = translate(&json!({"show_fps": false}), "test", "default", "test.moc3");
        assert!(!disabled.show_fps);
    }
}
