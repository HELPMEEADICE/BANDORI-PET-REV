use crate::config::ConfigDocument;
use crate::reminder::{
    LocalDateTime, create_alarm, create_pomodoro, normalize_alarms, normalize_pomodoros,
    repeat_days_label,
};
use bandori_llm_protocol::LlmStreamEvent;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::OnceLock;

pub const POKE_USER_TOOL_NAME: &str = "poke_user";
pub const CREATE_ALARM_TOOL_NAME: &str = "create_alarm";
pub const START_POMODORO_TOOL_NAME: &str = "start_pomodoro";
const MAX_STREAM_TOOL_CALLS: usize = 16;
const MAX_TOOL_ARGUMENT_BYTES: usize = 16 * 1024;
const MAX_TOOL_NAME_BYTES: usize = 128;
const MAX_TOOL_ID_BYTES: usize = 512;
const MAX_POKE_MESSAGE_CHARS: usize = 280;
const MAX_SAVED_REMINDERS: usize = 256;

fn chat_tool_contract() -> &'static Value {
    static CONTRACT: OnceLock<Value> = OnceLock::new();
    CONTRACT.get_or_init(|| {
        serde_json::from_str(include_str!("../../../compat/chat_prompt_vectors.json"))
            .expect("generated chat tool compatibility contract must be valid")
    })
}

pub fn native_chat_tools() -> Vec<Value> {
    let mut tools = chat_tool_contract()["chat_tools"]["reminders"]
        .as_array()
        .expect("generated reminder tool contract must be an array")
        .clone();
    tools.push(chat_tool_contract()["chat_tools"]["poke_user"].clone());
    tools
}

pub fn native_tool_system_hint() -> &'static str {
    chat_tool_contract()["chat_tools"]["native_system_hint"]
        .as_str()
        .expect("generated native tool prompt contract must be a string")
}

pub fn with_native_tool_system_hint(prompt: &str) -> String {
    let prompt = prompt.trim();
    if prompt.is_empty() {
        native_tool_system_hint().to_owned()
    } else {
        format!("{prompt}\n\n{}", native_tool_system_hint())
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeToolCall {
    pub output_index: usize,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub item_id: String,
    pub call_id: String,
    pub name: String,
    pub arguments: String,
    #[serde(default, skip_serializing_if = "is_false")]
    pub arguments_truncated: bool,
}

impl NativeToolCall {
    pub fn chat_completions_value(&self) -> Value {
        json!({
            "id": self.call_id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        })
    }
}

#[derive(Clone, Debug, Default)]
pub struct NativeToolCallAccumulator {
    calls: BTreeMap<usize, NativeToolCall>,
}

impl NativeToolCallAccumulator {
    pub fn absorb(&mut self, event: &LlmStreamEvent) {
        let LlmStreamEvent::ToolCallDelta {
            output_index,
            item_id,
            call_id,
            name,
            arguments,
            replace_arguments,
        } = event
        else {
            return;
        };
        if *output_index >= MAX_STREAM_TOOL_CALLS {
            return;
        }
        let call = self
            .calls
            .entry(*output_index)
            .or_insert_with(|| NativeToolCall {
                output_index: *output_index,
                ..NativeToolCall::default()
            });
        replace_if_nonempty(&mut call.item_id, item_id, MAX_TOOL_ID_BYTES);
        replace_if_nonempty(&mut call.call_id, call_id, MAX_TOOL_ID_BYTES);
        merge_tool_name(&mut call.name, name, *replace_arguments);
        merge_tool_arguments(call, arguments, *replace_arguments);
    }

    pub fn finish(self) -> Vec<NativeToolCall> {
        self.calls
            .into_iter()
            .filter_map(|(index, mut call)| {
                call.name = call.name.trim().to_owned();
                if call.name.is_empty() {
                    return None;
                }
                if call.call_id.trim().is_empty() {
                    call.call_id = format!("call_{index}");
                }
                if call.arguments.trim().is_empty() {
                    call.arguments = "{}".to_owned();
                }
                Some(call)
            })
            .collect()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum NativeToolEffect {
    PokeUser { message: String },
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeToolResult {
    pub call_id: String,
    pub name: String,
    pub arguments: String,
    pub content: String,
    pub succeeded: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub effect: Option<NativeToolEffect>,
}

pub struct NativeToolExecutionContext<'a> {
    pub config_path: &'a Path,
    pub now: LocalDateTime,
    pub active_character: &'a str,
}

pub fn execute_native_tool_call(call: &NativeToolCall) -> NativeToolResult {
    execute_native_tool_call_with_context(call, None)
}

pub fn execute_native_tool_call_with_context(
    call: &NativeToolCall,
    context: Option<&NativeToolExecutionContext<'_>>,
) -> NativeToolResult {
    let failure = |content: String| NativeToolResult {
        call_id: call.call_id.clone(),
        name: call.name.clone(),
        arguments: call.arguments.clone(),
        content,
        succeeded: false,
        effect: None,
    };
    if call.arguments_truncated {
        return failure(format!(
            "Tool call {} was not executed because its arguments exceed the {} byte limit.",
            call.name, MAX_TOOL_ARGUMENT_BYTES
        ));
    }
    let arguments = match serde_json::from_str::<Value>(&call.arguments) {
        Ok(Value::Object(arguments)) => arguments,
        Ok(_) => {
            return failure(format!(
                "Tool call {} was not executed because its arguments must be a JSON object.",
                call.name
            ));
        }
        Err(error) => {
            return failure(format!(
                "Tool call {} was not executed because its arguments are invalid JSON: {error}.",
                call.name
            ));
        }
    };
    match call.name.as_str() {
        POKE_USER_TOOL_NAME => execute_poke_user(call, &arguments, failure),
        CREATE_ALARM_TOOL_NAME | START_POMODORO_TOOL_NAME => {
            let Some(context) = context else {
                return failure(format!(
                    "Tool call {} was not executed because the native reminder service context is unavailable.",
                    call.name
                ));
            };
            execute_reminder_tool(call, &arguments, context, failure)
        }
        _ => failure(format!("Unsupported native tool: {}", call.name)),
    }
}

fn execute_poke_user(
    call: &NativeToolCall,
    arguments: &Map<String, Value>,
    failure: impl FnOnce(String) -> NativeToolResult,
) -> NativeToolResult {
    let message = match arguments.get("message") {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(message)) => message.trim().to_owned(),
        Some(_) => {
            return failure(format!(
                "Tool call {} was not executed because message must be a string.",
                call.name
            ));
        }
    };
    if message.chars().count() > MAX_POKE_MESSAGE_CHARS {
        return failure(format!(
            "Tool call {} was not executed because message exceeds the {} character limit.",
            call.name, MAX_POKE_MESSAGE_CHARS
        ));
    }
    NativeToolResult {
        call_id: call.call_id.clone(),
        name: call.name.clone(),
        arguments: call.arguments.clone(),
        content: "已戳了戳用户。请用角色口吻自然承接，不要提到工具调用细节。".to_owned(),
        succeeded: true,
        effect: Some(NativeToolEffect::PokeUser { message }),
    }
}

fn execute_reminder_tool(
    call: &NativeToolCall,
    arguments: &Map<String, Value>,
    context: &NativeToolExecutionContext<'_>,
    failure: impl FnOnce(String) -> NativeToolResult,
) -> NativeToolResult {
    let active_character = context.active_character.trim();
    if active_character.is_empty() {
        return failure(format!(
            "Tool call {} was not executed because no active character is available.",
            call.name
        ));
    }
    let mut config = match ConfigDocument::load(context.config_path) {
        Ok(config) => config,
        Err(error) => {
            return failure(format!("创建提醒失败：{error}"));
        }
    };
    let mut alarms = normalize_alarms(config.get("alarms").unwrap_or(&Value::Null), context.now);
    let mut pomodoros =
        normalize_pomodoros(config.get("pomodoros").unwrap_or(&Value::Null), context.now);
    let content = if call.name == CREATE_ALARM_TOOL_NAME {
        if alarms.len() >= MAX_SAVED_REMINDERS {
            return failure("创建闹钟失败：已达到 256 个提醒的安全上限。".to_owned());
        }
        let time = match required_string(arguments, "time") {
            Ok(value) => value,
            Err(error) => return failure(error),
        };
        let date = match optional_string(arguments, "date") {
            Ok(value) => value,
            Err(error) => return failure(error),
        };
        let description = match optional_string(arguments, "description") {
            Ok(value) => value,
            Err(error) => return failure(error),
        };
        let repeat_days = arguments.get("repeat_days").filter(|value| match value {
            Value::Array(values) => !values.is_empty(),
            Value::String(value) => !value.trim().is_empty(),
            Value::Null => false,
            _ => true,
        });
        let repeat = repeat_days
            .or_else(|| arguments.get("repeat"))
            .unwrap_or(&Value::Null);
        let alarm = match create_alarm(
            &time,
            repeat,
            &description,
            active_character,
            &date,
            context.now,
        ) {
            Ok(alarm) => alarm,
            Err(error) => return failure(format!("创建闹钟失败：{error}")),
        };
        let description_label = if alarm.description.is_empty() {
            "无描述"
        } else {
            alarm.description.as_str()
        };
        let content = format!(
            "已创建闹钟：{}，{}，下次 {}，描述：{}。",
            alarm.time,
            repeat_days_label(&alarm.repeat_days),
            alarm.next_at.replace('T', " "),
            description_label
        );
        alarms.push(alarm);
        content
    } else {
        if pomodoros.len() >= MAX_SAVED_REMINDERS {
            return failure("启动番茄钟失败：已达到 256 个计时器的安全上限。".to_owned());
        }
        let repeat_count = match optional_i64(arguments, "repeat_count", 1) {
            Ok(value) => value,
            Err(error) => return failure(error),
        };
        let description = match optional_string(arguments, "description") {
            Ok(value) => value,
            Err(error) => return failure(error),
        };
        let pomodoro = create_pomodoro(repeat_count, &description, active_character, context.now);
        let description_label = if pomodoro.description.is_empty() {
            "无描述"
        } else {
            pomodoro.description.as_str()
        };
        let content = format!(
            "已启动番茄钟：{} 次专注循环，描述：{}。",
            pomodoro.repeat_count, description_label
        );
        pomodoros.push(pomodoro);
        content
    };
    config.set(
        "alarms",
        serde_json::to_value(alarms).expect("alarm serialization cannot fail"),
    );
    config.set(
        "pomodoros",
        serde_json::to_value(pomodoros).expect("pomodoro serialization cannot fail"),
    );
    if let Err(error) = config.save(context.config_path) {
        return failure(format!("创建提醒失败：{error}"));
    }
    NativeToolResult {
        call_id: call.call_id.clone(),
        name: call.name.clone(),
        arguments: call.arguments.clone(),
        content,
        succeeded: true,
        effect: None,
    }
}

fn required_string(arguments: &Map<String, Value>, key: &str) -> Result<String, String> {
    let value = optional_string(arguments, key)?;
    if value.is_empty() {
        Err(format!("Tool call argument {key} is required."))
    } else {
        Ok(value)
    }
}

fn optional_string(arguments: &Map<String, Value>, key: &str) -> Result<String, String> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(String::new()),
        Some(Value::String(value)) => Ok(value.trim().to_owned()),
        Some(_) => Err(format!("Tool call argument {key} must be a string.")),
    }
}

fn optional_i64(arguments: &Map<String, Value>, key: &str, default: i64) -> Result<i64, String> {
    match arguments.get(key) {
        None | Some(Value::Null) => Ok(default),
        Some(Value::Number(value)) => value
            .as_i64()
            .or_else(|| value.as_f64().map(|value| value as i64))
            .ok_or_else(|| format!("Tool call argument {key} must be an integer.")),
        Some(Value::String(value)) => value
            .trim()
            .parse()
            .map_err(|_| format!("Tool call argument {key} must be an integer.")),
        Some(_) => Err(format!("Tool call argument {key} must be an integer.")),
    }
}

pub fn chat_tool_followup_messages(
    calls: &[NativeToolCall],
    results: &[NativeToolResult],
    assistant_content: &str,
) -> Vec<Value> {
    if calls.is_empty() {
        return Vec::new();
    }
    let mut messages = Vec::with_capacity(results.len() + 1);
    let assistant_content = assistant_content.trim();
    messages.push(json!({
        "role": "assistant",
        "content": if assistant_content.is_empty() {
            Value::Null
        } else {
            Value::String(assistant_content.to_owned())
        },
        "tool_calls": calls
            .iter()
            .map(NativeToolCall::chat_completions_value)
            .collect::<Vec<_>>(),
    }));
    messages.extend(results.iter().map(|result| {
        json!({
            "role": "tool",
            "tool_call_id": result.call_id,
            "content": result.content,
        })
    }));
    messages
}

pub fn native_tool_trace(outcome: &Value) -> Option<Value> {
    let mut trace = serde_json::Map::new();
    if let Some(usage) = outcome.get("usage").and_then(Value::as_object) {
        trace.insert("llm_usage".to_owned(), Value::Object(usage.clone()));
    }
    if let Some(calls) = outcome.get("tool_calls").and_then(Value::as_array) {
        let calls = calls
            .iter()
            .filter_map(|call| {
                Some(json!({
                    "name": call.get("name")?.as_str()?,
                    "arguments": call.get("arguments")?.as_str()?,
                    "succeeded": call.get("succeeded").and_then(Value::as_bool).unwrap_or(false),
                }))
            })
            .collect::<Vec<_>>();
        if !calls.is_empty() {
            trace.insert("tool_calls".to_owned(), Value::Array(calls));
        }
    }
    (!trace.is_empty()).then_some(Value::Object(trace))
}

fn is_false(value: &bool) -> bool {
    !*value
}

fn replace_if_nonempty(target: &mut String, value: &str, max_bytes: usize) {
    if !value.is_empty() {
        *target = bounded_string(value, max_bytes);
    }
}

fn merge_tool_name(target: &mut String, fragment: &str, replace: bool) {
    if fragment.is_empty() {
        return;
    }
    if replace || target.is_empty() || fragment.starts_with(target.as_str()) {
        *target = bounded_string(fragment, MAX_TOOL_NAME_BYTES);
    } else if target != fragment {
        target.push_str(fragment);
        target.truncate(floor_char_boundary(target, MAX_TOOL_NAME_BYTES));
    }
}

fn merge_tool_arguments(call: &mut NativeToolCall, fragment: &str, replace: bool) {
    if replace {
        call.arguments.clear();
        call.arguments_truncated = false;
    }
    if fragment.is_empty() {
        return;
    }
    let remaining = MAX_TOOL_ARGUMENT_BYTES.saturating_sub(call.arguments.len());
    if fragment.len() > remaining {
        call.arguments_truncated = true;
    }
    let boundary = floor_char_boundary(fragment, remaining);
    call.arguments.push_str(&fragment[..boundary]);
}

fn bounded_string(value: &str, max_bytes: usize) -> String {
    value[..floor_char_boundary(value, max_bytes)].to_owned()
}

fn floor_char_boundary(value: &str, max_bytes: usize) -> usize {
    let mut boundary = value.len().min(max_bytes);
    while boundary > 0 && !value.is_char_boundary(boundary) {
        boundary -= 1;
    }
    boundary
}

#[cfg(test)]
mod tests {
    use super::*;

    fn delta(
        output_index: usize,
        item_id: &str,
        call_id: &str,
        name: &str,
        arguments: &str,
        replace_arguments: bool,
    ) -> LlmStreamEvent {
        LlmStreamEvent::ToolCallDelta {
            output_index,
            item_id: item_id.to_owned(),
            call_id: call_id.to_owned(),
            name: name.to_owned(),
            arguments: arguments.to_owned(),
            replace_arguments,
        }
    }

    #[test]
    fn generated_python_tool_contract_matches_native_definitions_and_hint() {
        assert_eq!(native_chat_tools().len(), 3);
        assert_eq!(
            native_chat_tools()[0]["function"]["name"],
            CREATE_ALARM_TOOL_NAME
        );
        assert_eq!(
            native_chat_tools()[1]["function"]["name"],
            START_POMODORO_TOOL_NAME
        );
        assert_eq!(
            native_chat_tools()[2]["function"]["name"],
            POKE_USER_TOOL_NAME
        );
        assert_eq!(
            native_chat_tools()[2],
            chat_tool_contract()["chat_tools"]["poke_user"]
        );
        assert_eq!(
            native_tool_system_hint(),
            chat_tool_contract()["chat_tools"]["native_system_hint"]
        );
    }

    #[test]
    fn chat_completion_fragments_merge_by_output_index() {
        let mut calls = NativeToolCallAccumulator::default();
        calls.absorb(&delta(1, "", "call_b", "poke_", "{\"message\":", false));
        calls.absorb(&delta(0, "", "call_a", "poke_user", "{}", false));
        calls.absorb(&delta(1, "", "", "user", "\"hi\"}", false));
        let calls = calls.finish();
        assert_eq!(calls.len(), 2);
        assert_eq!(calls[0].call_id, "call_a");
        assert_eq!(calls[1].name, POKE_USER_TOOL_NAME);
        assert_eq!(calls[1].arguments, r#"{"message":"hi"}"#);
    }

    #[test]
    fn responses_done_event_replaces_accumulated_arguments() {
        let mut calls = NativeToolCallAccumulator::default();
        calls.absorb(&delta(0, "item_1", "call_1", "poke_user", "{\"mess", false));
        calls.absorb(&delta(0, "item_1", "", "", "age\":\"old\"}", false));
        calls.absorb(&delta(
            0,
            "item_1",
            "call_1",
            "poke_user",
            r#"{"message":"final"}"#,
            true,
        ));
        let calls = calls.finish();
        assert_eq!(calls[0].arguments, r#"{"message":"final"}"#);
        assert_eq!(calls[0].item_id, "item_1");
    }

    #[test]
    fn executor_rejects_invalid_and_unsupported_calls_without_effects() {
        let invalid = execute_native_tool_call(&NativeToolCall {
            call_id: "call_1".to_owned(),
            name: POKE_USER_TOOL_NAME.to_owned(),
            arguments: "[]".to_owned(),
            ..NativeToolCall::default()
        });
        assert!(!invalid.succeeded);
        assert!(invalid.content.contains("must be a JSON object"));
        assert_eq!(invalid.effect, None);

        let unsupported = execute_native_tool_call(&NativeToolCall {
            call_id: "call_2".to_owned(),
            name: "web_search".to_owned(),
            arguments: "{}".to_owned(),
            ..NativeToolCall::default()
        });
        assert!(!unsupported.succeeded);
        assert!(unsupported.content.contains("Unsupported native tool"));
        assert_eq!(unsupported.effect, None);
    }

    #[test]
    fn executor_returns_a_bounded_poke_effect_and_followup_messages() {
        let call = NativeToolCall {
            output_index: 0,
            call_id: "call_1".to_owned(),
            name: POKE_USER_TOOL_NAME.to_owned(),
            arguments: r#"{"message":"  回戳！  "}"#.to_owned(),
            ..NativeToolCall::default()
        };
        let result = execute_native_tool_call(&call);
        assert!(result.succeeded);
        assert_eq!(
            result.effect,
            Some(NativeToolEffect::PokeUser {
                message: "回戳！".to_owned()
            })
        );
        let messages = chat_tool_followup_messages(&[call], &[result], "先戳一下");
        assert_eq!(messages[0]["role"], "assistant");
        assert_eq!(messages[0]["content"], "先戳一下");
        assert_eq!(
            messages[0]["tool_calls"][0]["function"]["name"],
            POKE_USER_TOOL_NAME
        );
        assert_eq!(messages[1]["role"], "tool");
        assert_eq!(messages[1]["tool_call_id"], "call_1");
    }

    #[test]
    fn excessive_arguments_and_output_indexes_are_bounded() {
        let mut calls = NativeToolCallAccumulator::default();
        calls.absorb(&delta(
            MAX_STREAM_TOOL_CALLS,
            "",
            "ignored",
            POKE_USER_TOOL_NAME,
            "{}",
            false,
        ));
        calls.absorb(&delta(
            0,
            "",
            "call_1",
            POKE_USER_TOOL_NAME,
            &"x".repeat(MAX_TOOL_ARGUMENT_BYTES + 1),
            false,
        ));
        let calls = calls.finish();
        assert_eq!(calls.len(), 1);
        assert!(calls[0].arguments_truncated);
        assert_eq!(calls[0].arguments.len(), MAX_TOOL_ARGUMENT_BYTES);
        assert!(!execute_native_tool_call(&calls[0]).succeeded);
    }

    #[test]
    fn persisted_trace_keeps_usage_and_sanitized_tool_metadata() {
        let trace = native_tool_trace(&json!({
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            "tool_calls": [{
                "call_id": "call_1",
                "name": "poke_user",
                "arguments": "{}",
                "content": "internal result",
                "succeeded": true,
                "effect": {"kind": "poke_user", "message": "hi"},
            }],
        }))
        .unwrap();
        assert_eq!(trace["llm_usage"]["total_tokens"], 5);
        assert_eq!(trace["tool_calls"][0]["name"], "poke_user");
        assert!(trace["tool_calls"][0].get("content").is_none());
        assert!(trace["tool_calls"][0].get("effect").is_none());
    }

    #[test]
    fn reminder_tools_persist_bounded_active_character_state() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let mut config = ConfigDocument::default();
        config.save(&path).unwrap();
        let context = NativeToolExecutionContext {
            config_path: &path,
            now: LocalDateTime::parse("2026-07-15T10:30:00").unwrap(),
            active_character: "ran",
        };
        let alarm = execute_native_tool_call_with_context(
            &NativeToolCall {
                call_id: "call_alarm".to_owned(),
                name: CREATE_ALARM_TOOL_NAME.to_owned(),
                arguments: json!({
                    "time":"21:45",
                    "repeat":"weekdays",
                    "description":"练琴",
                    "character":"moca"
                })
                .to_string(),
                ..NativeToolCall::default()
            },
            Some(&context),
        );
        assert!(alarm.succeeded);
        assert!(alarm.content.contains("已创建闹钟：21:45，工作日"));

        let pomodoro = execute_native_tool_call_with_context(
            &NativeToolCall {
                call_id: "call_pomodoro".to_owned(),
                name: START_POMODORO_TOOL_NAME.to_owned(),
                arguments: r#"{"repeat_count":3,"description":"编曲"}"#.to_owned(),
                ..NativeToolCall::default()
            },
            Some(&context),
        );
        assert!(pomodoro.succeeded);
        assert!(pomodoro.content.contains("3 次专注循环"));

        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(saved.get("alarms").unwrap().as_array().unwrap().len(), 1);
        assert_eq!(saved.get("alarms").unwrap()[0]["character"], "ran");
        assert_eq!(saved.get("pomodoros").unwrap().as_array().unwrap().len(), 1);
        assert_eq!(saved.get("pomodoros").unwrap()[0]["character"], "ran");
    }
}
