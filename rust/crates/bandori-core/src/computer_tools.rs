use crate::config::ConfigDocument;
use serde_json::{Value, json};

pub const COMPUTER_TOOL_PREFIX: &str = "computer_";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeComputerSettings {
    pub enabled: bool,
    pub auto_detect: bool,
    pub send_screenshots: bool,
    pub max_screenshot_width: i64,
    pub allow_screenshot: bool,
    pub allow_mouse: bool,
    pub allow_keyboard: bool,
    pub allow_clipboard: bool,
    pub allow_wait: bool,
}

impl NativeComputerSettings {
    pub fn from_config(config: &ConfigDocument) -> Self {
        Self {
            enabled: config_bool(config, "computer_use_enabled", false),
            auto_detect: config_bool(config, "computer_use_auto_detect", true),
            send_screenshots: config_bool(config, "computer_use_send_screenshots", true),
            max_screenshot_width: config_i64(config, "computer_use_max_screenshot_width", 1280)
                .clamp(640, 1920),
            allow_screenshot: config_bool(config, "computer_use_allow_screenshot", true),
            allow_mouse: config_bool(config, "computer_use_allow_mouse", false),
            allow_keyboard: config_bool(config, "computer_use_allow_keyboard", false),
            allow_clipboard: config_bool(config, "computer_use_allow_clipboard", false),
            allow_wait: config_bool(config, "computer_use_allow_wait", true),
        }
    }

    pub fn allows(&self, tool_name: &str) -> bool {
        self.enabled
            && match tool_name {
                "computer_screenshot" => self.allow_screenshot,
                "computer_move"
                | "computer_click"
                | "computer_double_click"
                | "computer_scroll" => self.allow_mouse,
                "computer_type" | "computer_key" => self.allow_keyboard,
                "computer_set_clipboard" => self.allow_clipboard,
                "computer_wait" => self.allow_wait,
                _ => false,
            }
    }
}

pub fn is_computer_tool_name(name: &str) -> bool {
    name.starts_with(COMPUTER_TOOL_PREFIX)
}

pub fn computer_tool_definitions(config: &ConfigDocument) -> Vec<Value> {
    let settings = NativeComputerSettings::from_config(config);
    if !settings.enabled {
        return Vec::new();
    }
    let mut tools = Vec::new();
    if settings.allow_screenshot {
        tools.push(tool(
            "computer_screenshot",
            "Capture the current desktop screen. Use this before deciding where to click, move, type, or inspect the UI.",
            json!({}),
            &[],
        ));
    }
    if settings.allow_mouse {
        let point = json!({
            "x":{"type":"integer","description":"X coordinate in pixels on the latest screenshot image."},
            "y":{"type":"integer","description":"Y coordinate in pixels on the latest screenshot image."}
        });
        tools.push(tool(
            "computer_move",
            "Move the mouse pointer. Use coordinates from the latest screenshot image; the app maps them to real desktop coordinates.",
            point.clone(),
            &["x", "y"],
        ));
        let mut click = point.as_object().cloned().unwrap_or_default();
        click.insert(
            "button".to_owned(),
            json!({"type":"string","enum":["left","right","middle"],"description":"Mouse button."}),
        );
        tools.push(tool(
            "computer_click",
            "Click at a point from the latest screenshot image. Use this when the user asks to press, tap, choose, open, close, or interact with something on screen.",
            Value::Object(click.clone()),
            &["x", "y"],
        ));
        tools.push(tool(
            "computer_double_click",
            "Double-click at a point from the latest screenshot image.",
            Value::Object(click),
            &["x", "y"],
        ));
        let mut scroll = point.as_object().cloned().unwrap_or_default();
        scroll.insert(
            "delta".to_owned(),
            json!({"type":"integer","description":"Positive scrolls up, negative scrolls down."}),
        );
        tools.push(tool(
            "computer_scroll",
            "Scroll at a point from the latest screenshot image.",
            Value::Object(scroll),
            &["x", "y", "delta"],
        ));
    }
    if settings.allow_keyboard {
        tools.push(tool(
            "computer_type",
            "Type text into the active focused UI element.",
            json!({"text":{"type":"string","description":"Text to type."}}),
            &["text"],
        ));
        tools.push(tool(
            "computer_key",
            "Press a key or shortcut. Examples: enter, esc, ctrl+l, ctrl+shift+s.",
            json!({"keys":{"type":"string","description":"Key name or shortcut."}}),
            &["keys"],
        ));
    }
    if settings.allow_clipboard {
        tools.push(tool(
            "computer_set_clipboard",
            "Set the system clipboard text. This does not paste automatically.",
            json!({"text":{"type":"string","description":"Text to place on the clipboard."}}),
            &["text"],
        ));
    }
    if settings.allow_wait {
        tools.push(tool(
            "computer_wait",
            "Wait for the UI to settle.",
            json!({"seconds":{"type":"number","description":"Seconds to wait, from 0.1 to 10."}}),
            &[],
        ));
    }
    tools
}

fn tool(name: &str, description: &str, properties: Value, required: &[&str]) -> Value {
    let mut parameters = serde_json::Map::from_iter([
        ("type".to_owned(), Value::String("object".to_owned())),
        ("properties".to_owned(), properties),
    ]);
    if !required.is_empty() {
        parameters.insert("required".to_owned(), json!(required));
    }
    json!({
        "type":"function",
        "function":{
            "name":name,
            "description":description,
            "parameters":parameters,
        }
    })
}

fn config_bool(config: &ConfigDocument, key: &str, default: bool) -> bool {
    config.get(key).and_then(Value::as_bool).unwrap_or(default)
}

fn config_i64(config: &ConfigDocument, key: &str, default: i64) -> i64 {
    config
        .get(key)
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
        })
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_computer_use_exposes_no_tools() {
        assert!(computer_tool_definitions(&ConfigDocument::default()).is_empty());
    }

    #[test]
    fn permissions_control_definitions_and_runtime_checks() {
        let mut config = ConfigDocument::default();
        config.set("computer_use_enabled", Value::Bool(true));
        config.set("computer_use_allow_screenshot", Value::Bool(true));
        config.set("computer_use_allow_mouse", Value::Bool(true));
        config.set("computer_use_allow_keyboard", Value::Bool(false));
        config.set("computer_use_allow_clipboard", Value::Bool(true));
        config.set("computer_use_allow_wait", Value::Bool(false));
        config.set("computer_use_max_screenshot_width", Value::from(9999));
        let settings = NativeComputerSettings::from_config(&config);
        assert_eq!(settings.max_screenshot_width, 1920);
        assert!(settings.allows("computer_screenshot"));
        assert!(settings.allows("computer_click"));
        assert!(!settings.allows("computer_type"));
        assert!(settings.allows("computer_set_clipboard"));
        assert!(!settings.allows("computer_wait"));
        let names = computer_tool_definitions(&config)
            .into_iter()
            .map(|tool| tool["function"]["name"].as_str().unwrap().to_owned())
            .collect::<Vec<_>>();
        assert_eq!(
            names,
            [
                "computer_screenshot",
                "computer_move",
                "computer_click",
                "computer_double_click",
                "computer_scroll",
                "computer_set_clipboard"
            ]
        );
    }
}
