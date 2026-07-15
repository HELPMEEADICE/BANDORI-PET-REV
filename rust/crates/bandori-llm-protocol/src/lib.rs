//! Provider-compatible LLM request construction and streaming event decoding.
//!
//! The protocol crate is intentionally independent from database and UI code
//! so native transports, bridges, and compatibility tests can share it without
//! pulling in unrelated native dependencies.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use thiserror::Error;

const GOOGLE_GENERATIVE_LANGUAGE_HOST: &str = "generativelanguage.googleapis.com";
const GOOGLE_OPENAI_BASE_PATH: &str = "/v1beta/openai";

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LlmApiMode {
    #[default]
    ChatCompletions,
    Responses,
}

impl LlmApiMode {
    pub fn from_config(value: &str) -> Self {
        if value.trim().eq_ignore_ascii_case("responses") {
            Self::Responses
        } else {
            Self::ChatCompletions
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct TokenUsage {
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub total_tokens: i64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum LlmStreamEvent {
    TextDelta {
        text: String,
    },
    ReasoningDelta {
        text: String,
    },
    ToolCallDelta {
        output_index: usize,
        item_id: String,
        call_id: String,
        name: String,
        arguments: String,
        replace_arguments: bool,
    },
    ResponseId {
        id: String,
    },
    Usage {
        usage: TokenUsage,
    },
    Completed,
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum LlmProtocolError {
    #[error("invalid JSON in {mode} stream: {details}")]
    InvalidJson { mode: &'static str, details: String },
    #[error("LLM stream failed: {0}")]
    Stream(String),
}

#[derive(Clone, Debug)]
pub struct LlmSseDecoder {
    mode: LlmApiMode,
    saw_text: bool,
    completed: bool,
}

impl LlmSseDecoder {
    pub fn new(mode: LlmApiMode) -> Self {
        Self {
            mode,
            saw_text: false,
            completed: false,
        }
    }

    pub fn is_completed(&self) -> bool {
        self.completed
    }

    pub fn feed_line(&mut self, line: &str) -> Result<Vec<LlmStreamEvent>, LlmProtocolError> {
        let line = line.trim();
        let Some(payload) = line.strip_prefix("data:").map(str::trim) else {
            return Ok(Vec::new());
        };
        if payload == "[DONE]" {
            if self.mode == LlmApiMode::ChatCompletions && !self.completed {
                self.completed = true;
                return Ok(vec![LlmStreamEvent::Completed]);
            }
            return Ok(Vec::new());
        }
        let data: Value =
            serde_json::from_str(payload).map_err(|error| LlmProtocolError::InvalidJson {
                mode: match self.mode {
                    LlmApiMode::ChatCompletions => "Chat Completions",
                    LlmApiMode::Responses => "Responses API",
                },
                details: error.to_string(),
            })?;
        match self.mode {
            LlmApiMode::ChatCompletions => self.decode_chat_completions(&data),
            LlmApiMode::Responses => self.decode_responses(&data),
        }
    }

    fn decode_chat_completions(
        &mut self,
        data: &Value,
    ) -> Result<Vec<LlmStreamEvent>, LlmProtocolError> {
        let mut events = Vec::new();
        if let Some(usage) = data.get("usage").and_then(normalize_usage) {
            events.push(LlmStreamEvent::Usage { usage });
        }
        let Some(choice) = data
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
        else {
            return Ok(events);
        };
        let delta = choice.get("delta").and_then(Value::as_object);
        if let Some(delta) = delta {
            append_chat_tool_call_events(delta, &mut events);
            if let Some(reasoning) =
                first_string(delta, &["reasoning_content", "reasoning", "thinking"])
                && !reasoning.is_empty()
            {
                events.push(LlmStreamEvent::ReasoningDelta {
                    text: reasoning.to_owned(),
                });
            }
            if let Some(text) = delta.get("content").and_then(Value::as_str)
                && !text.is_empty()
            {
                self.saw_text = true;
                events.push(LlmStreamEvent::TextDelta {
                    text: text.to_owned(),
                });
            }
        }
        if !choice
            .get("finish_reason")
            .unwrap_or(&Value::Null)
            .is_null()
            && !self.completed
        {
            self.completed = true;
            events.push(LlmStreamEvent::Completed);
        }
        Ok(events)
    }

    fn decode_responses(&mut self, data: &Value) -> Result<Vec<LlmStreamEvent>, LlmProtocolError> {
        let event_type = data.get("type").and_then(Value::as_str).unwrap_or_default();
        match event_type {
            "error" => Err(LlmProtocolError::Stream(
                data.get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("Responses API stream error")
                    .to_owned(),
            )),
            "response.failed" | "response.incomplete" => {
                Err(LlmProtocolError::Stream(responses_failure_message(data)))
            }
            "response.created" | "response.queued" | "response.in_progress" => {
                let id = response_id(data);
                Ok((!id.is_empty())
                    .then_some(LlmStreamEvent::ResponseId { id })
                    .into_iter()
                    .collect())
            }
            "response.output_text.delta" | "response.text.delta" => {
                let text = data
                    .get("delta")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if text.is_empty() {
                    Ok(Vec::new())
                } else {
                    self.saw_text = true;
                    Ok(vec![LlmStreamEvent::TextDelta {
                        text: text.to_owned(),
                    }])
                }
            }
            "response.reasoning_summary_text.delta" | "response.reasoning_text.delta" => {
                let text = data
                    .get("delta")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                Ok((!text.is_empty())
                    .then(|| LlmStreamEvent::ReasoningDelta {
                        text: text.to_owned(),
                    })
                    .into_iter()
                    .collect())
            }
            "response.output_item.added" | "response.output_item.done" => Ok(data
                .get("item")
                .and_then(|item| responses_tool_call_event(item, output_index(data), false))
                .into_iter()
                .collect()),
            "response.function_call_arguments.delta" => Ok(vec![LlmStreamEvent::ToolCallDelta {
                output_index: output_index(data),
                item_id: string_field(data, "item_id"),
                call_id: String::new(),
                name: String::new(),
                arguments: string_field(data, "delta"),
                replace_arguments: false,
            }]),
            "response.function_call_arguments.done" => Ok(vec![LlmStreamEvent::ToolCallDelta {
                output_index: output_index(data),
                item_id: string_field(data, "item_id"),
                call_id: String::new(),
                name: string_field(data, "name"),
                arguments: string_field(data, "arguments"),
                replace_arguments: true,
            }]),
            "response.completed" | "response.done" => {
                let mut events = Vec::new();
                let response = data.get("response").unwrap_or(&Value::Null);
                let id = response
                    .get("id")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if !id.is_empty() {
                    events.push(LlmStreamEvent::ResponseId { id: id.to_owned() });
                }
                if let Some(output) = response.get("output").and_then(Value::as_array) {
                    for (index, item) in output.iter().enumerate() {
                        if let Some(event) = responses_tool_call_event(item, index, true) {
                            events.push(event);
                        }
                    }
                }
                if !self.saw_text {
                    let text = extract_response_output_text(response);
                    if !text.is_empty() {
                        self.saw_text = true;
                        events.push(LlmStreamEvent::TextDelta { text });
                    }
                }
                if let Some(usage) = response.get("usage").and_then(normalize_usage) {
                    events.push(LlmStreamEvent::Usage { usage });
                }
                if !self.completed {
                    self.completed = true;
                    events.push(LlmStreamEvent::Completed);
                }
                Ok(events)
            }
            _ => Ok(Vec::new()),
        }
    }
}

pub fn chat_completions_api_url(api_url: &str) -> String {
    let url = api_url.trim_end_matches('/');
    if url.is_empty() {
        return String::new();
    }
    if is_google_generative_language_url(url) {
        return google_chat_completions_url(url);
    }
    replace_or_append_endpoint(url, "/chat/completions", "/responses")
}

pub fn responses_api_url(api_url: &str) -> String {
    let url = api_url.trim_end_matches('/');
    if url.is_empty() {
        return String::new();
    }
    if is_google_generative_language_url(url) {
        return chat_completions_api_url(url);
    }
    replace_or_append_endpoint(url, "/responses", "/chat/completions")
}

pub fn models_api_url(api_url: &str) -> String {
    if is_google_generative_language_url(api_url) {
        let (base, suffix) = split_url_suffix(api_url);
        let scheme_end = base.find("://").map(|index| index + 3).unwrap_or(0);
        let path_start = base[scheme_end..]
            .find('/')
            .map(|index| scheme_end + index)
            .unwrap_or(base.len());
        return format!(
            "{}{GOOGLE_OPENAI_BASE_PATH}/models{suffix}",
            &base[..path_start]
        );
    }
    let mut chat_url = chat_completions_api_url(api_url);
    if chat_url.is_empty() {
        return String::new();
    }
    if let Some(position) = chat_url.rfind("/chat/completions") {
        chat_url.truncate(position);
    }
    if let Some(position) = chat_url.rfind("/responses") {
        chat_url.truncate(position);
    }
    format!("{chat_url}/models")
}

pub fn supports_openai_responses_api(api_url: &str) -> bool {
    api_url.to_ascii_lowercase().contains("api.openai.com")
}

pub fn build_chat_completions_body(
    api_url: &str,
    model: &str,
    messages: &[Value],
    stream: bool,
    enable_thinking: Option<bool>,
    tools: &[Value],
) -> Value {
    let mut body = Map::from_iter([
        ("model".to_owned(), Value::String(model.to_owned())),
        ("messages".to_owned(), Value::Array(messages.to_vec())),
        ("stream".to_owned(), Value::Bool(stream)),
    ]);
    if !tools.is_empty() {
        body.insert("tools".to_owned(), Value::Array(tools.to_vec()));
        body.insert("tool_choice".to_owned(), Value::String("auto".to_owned()));
    }
    apply_chat_thinking_options(&mut body, enable_thinking);
    if is_google_generative_language_url(api_url) {
        body.remove("enable_thinking");
        body.remove("thinking");
    }
    if stream && api_url.to_ascii_lowercase().contains("api.openai.com") {
        body.insert("stream_options".to_owned(), json!({"include_usage": true}));
    }
    Value::Object(body)
}

pub fn build_responses_body(
    model: &str,
    messages: &[Value],
    stream: bool,
    enable_thinking: Option<bool>,
    tools: &[Value],
    previous_response_id: &str,
) -> Value {
    let (instructions, input) = messages_to_responses_input(messages);
    let mut body = Map::from_iter([
        ("model".to_owned(), Value::String(model.to_owned())),
        ("input".to_owned(), Value::Array(input)),
        ("stream".to_owned(), Value::Bool(stream)),
    ]);
    if !instructions.is_empty() {
        body.insert("instructions".to_owned(), Value::String(instructions));
    }
    if !previous_response_id.trim().is_empty() {
        body.insert(
            "previous_response_id".to_owned(),
            Value::String(previous_response_id.trim().to_owned()),
        );
    }
    if !tools.is_empty() {
        body.insert("tools".to_owned(), Value::Array(tools.to_vec()));
        body.insert("tool_choice".to_owned(), Value::String("auto".to_owned()));
    }
    if let Some(enabled) = enable_thinking {
        body.insert(
            "reasoning".to_owned(),
            json!({"effort": if enabled { "medium" } else { "none" }}),
        );
    }
    Value::Object(body)
}

pub fn messages_to_responses_input(messages: &[Value]) -> (String, Vec<Value>) {
    let mut instructions = String::new();
    let mut input = Vec::new();
    for message in messages {
        let role = message
            .get("role")
            .and_then(Value::as_str)
            .unwrap_or("user");
        let content = responses_content(message.get("content").unwrap_or(&Value::Null));
        if role == "system" {
            let text = content_to_text(&content);
            if !text.is_empty() {
                if !instructions.is_empty() {
                    instructions.push_str("\n\n");
                }
                instructions.push_str(&text);
            }
            continue;
        }
        if role == "tool" {
            let call_id = message
                .get("tool_call_id")
                .or_else(|| message.get("call_id"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .trim();
            if !call_id.is_empty() {
                input.push(json!({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content_to_text(&content),
                }));
            }
            continue;
        }
        let role = if matches!(role, "user" | "assistant" | "developer") {
            role
        } else {
            "user"
        };
        input.push(json!({"role": role, "content": content}));
    }
    (instructions, input)
}

fn apply_chat_thinking_options(body: &mut Map<String, Value>, enable_thinking: Option<bool>) {
    let Some(enabled) = enable_thinking else {
        return;
    };
    body.insert("enable_thinking".to_owned(), Value::Bool(enabled));
    body.insert(
        "thinking".to_owned(),
        json!({"type": if enabled { "enabled" } else { "disabled" }}),
    );
    if enabled {
        body.insert(
            "reasoning_effort".to_owned(),
            Value::String("medium".to_owned()),
        );
    }
}

fn responses_content(content: &Value) -> Value {
    let Some(parts) = content.as_array() else {
        return json!([{"type": "input_text", "text": value_as_text(content)}]);
    };
    let mut result = Vec::new();
    for part in parts {
        let part_type = part.get("type").and_then(Value::as_str).unwrap_or_default();
        match part_type {
            "text" | "input_text" => {
                if let Some(text) = part.get("text").and_then(Value::as_str)
                    && !text.is_empty()
                {
                    result.push(json!({"type": "input_text", "text": text}));
                }
            }
            "image_url" | "input_image" => {
                let image_url = part.get("image_url").and_then(|value| {
                    value
                        .as_str()
                        .or_else(|| value.get("url").and_then(Value::as_str))
                });
                if let Some(image_url) = image_url
                    && !image_url.is_empty()
                {
                    result.push(json!({"type": "input_image", "image_url": image_url}));
                }
            }
            _ => {}
        }
    }
    if result.is_empty() {
        json!([{"type": "input_text", "text": ""}])
    } else {
        Value::Array(result)
    }
}

fn content_to_text(content: &Value) -> String {
    content
        .as_array()
        .into_iter()
        .flatten()
        .filter(|part| {
            matches!(
                part.get("type").and_then(Value::as_str),
                Some("text" | "input_text")
            )
        })
        .filter_map(|part| part.get("text").and_then(Value::as_str))
        .filter(|text| !text.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_owned()
}

fn value_as_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        other => other.to_string(),
    }
}

fn append_chat_tool_call_events(delta: &Map<String, Value>, events: &mut Vec<LlmStreamEvent>) {
    if let Some(calls) = delta.get("tool_calls").and_then(Value::as_array) {
        for (position, call) in calls.iter().enumerate() {
            let function = call.get("function").unwrap_or(&Value::Null);
            events.push(LlmStreamEvent::ToolCallDelta {
                output_index: call
                    .get("index")
                    .and_then(Value::as_u64)
                    .and_then(|value| usize::try_from(value).ok())
                    .unwrap_or(position),
                item_id: String::new(),
                call_id: string_field(call, "id"),
                name: string_field(function, "name"),
                arguments: string_field(function, "arguments"),
                replace_arguments: false,
            });
        }
    }
    if let Some(function) = delta.get("function_call").filter(|value| value.is_object()) {
        events.push(LlmStreamEvent::ToolCallDelta {
            output_index: 0,
            item_id: String::new(),
            call_id: String::new(),
            name: string_field(function, "name"),
            arguments: string_field(function, "arguments"),
            replace_arguments: false,
        });
    }
}

fn responses_tool_call_event(
    item: &Value,
    output_index: usize,
    replace_arguments: bool,
) -> Option<LlmStreamEvent> {
    (item.get("type").and_then(Value::as_str) == Some("function_call")).then(|| {
        LlmStreamEvent::ToolCallDelta {
            output_index,
            item_id: string_field(item, "id"),
            call_id: string_field(item, "call_id"),
            name: string_field(item, "name"),
            arguments: string_field(item, "arguments"),
            replace_arguments,
        }
    })
}

fn normalize_usage(usage: &Value) -> Option<TokenUsage> {
    let input_tokens = integer_field(usage, &["input_tokens", "prompt_tokens"]);
    let output_tokens = integer_field(usage, &["output_tokens", "completion_tokens"]);
    let total_tokens = integer_field(usage, &["total_tokens"]);
    let total_tokens = if total_tokens > 0 {
        total_tokens
    } else {
        input_tokens + output_tokens
    };
    (input_tokens > 0 || output_tokens > 0 || total_tokens > 0).then_some(TokenUsage {
        input_tokens,
        output_tokens,
        total_tokens,
    })
}

fn integer_field(value: &Value, keys: &[&str]) -> i64 {
    keys.iter()
        .find_map(|key| value.get(key).and_then(Value::as_i64))
        .unwrap_or_default()
        .max(0)
}

fn first_string<'a>(object: &'a Map<String, Value>, keys: &[&str]) -> Option<&'a str> {
    keys.iter()
        .find_map(|key| object.get(*key).and_then(Value::as_str))
}

fn extract_response_output_text(response: &Value) -> String {
    if let Some(text) = response.get("output_text").and_then(Value::as_str) {
        return text.to_owned();
    }
    response
        .get("output")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| item.get("content").and_then(Value::as_array))
        .flatten()
        .filter(|part| {
            matches!(
                part.get("type").and_then(Value::as_str),
                Some("output_text" | "text")
            )
        })
        .filter_map(|part| part.get("text").and_then(Value::as_str))
        .collect()
}

fn responses_failure_message(data: &Value) -> String {
    let details = data
        .get("response")
        .and_then(|response| {
            response
                .get("error")
                .or_else(|| response.get("incomplete_details"))
        })
        .unwrap_or(&Value::Null);
    details
        .get("message")
        .or_else(|| details.get("reason"))
        .and_then(Value::as_str)
        .or_else(|| details.as_str())
        .filter(|message| !message.is_empty())
        .unwrap_or("Responses API did not complete the response")
        .to_owned()
}

fn response_id(data: &Value) -> String {
    data.get("response")
        .map(|response| string_field(response, "id"))
        .unwrap_or_default()
}

fn output_index(data: &Value) -> usize {
    data.get("output_index")
        .and_then(Value::as_u64)
        .and_then(|value| usize::try_from(value).ok())
        .unwrap_or_default()
}

fn string_field(value: &Value, key: &str) -> String {
    value
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned()
}

fn is_google_generative_language_url(api_url: &str) -> bool {
    url_host(api_url).eq_ignore_ascii_case(GOOGLE_GENERATIVE_LANGUAGE_HOST)
}

fn url_host(url: &str) -> &str {
    let rest = url.split_once("://").map(|(_, rest)| rest).unwrap_or(url);
    rest.split(['/', '?', '#']).next().unwrap_or_default()
}

fn split_url_suffix(url: &str) -> (&str, &str) {
    let position = url
        .char_indices()
        .find_map(|(index, value)| matches!(value, '?' | '#').then_some(index));
    position.map_or((url, ""), |position| url.split_at(position))
}

fn replace_or_append_endpoint(url: &str, target: &str, alternate: &str) -> String {
    if url.ends_with(target) {
        return url.to_owned();
    }
    if let Some(base) = url.strip_suffix(alternate) {
        return format!("{base}{target}");
    }
    let (base, suffix) = split_url_suffix(url);
    if base.trim_end_matches('/').ends_with("/v1") {
        return format!("{}{target}{suffix}", base.trim_end_matches('/'));
    }
    format!("{}{target}", url.trim_end_matches('/'))
}

fn google_chat_completions_url(url: &str) -> String {
    let (base, suffix) = split_url_suffix(url);
    let scheme_end = base.find("://").map(|index| index + 3).unwrap_or(0);
    let path_start = base[scheme_end..]
        .find('/')
        .map(|index| scheme_end + index)
        .unwrap_or(base.len());
    let origin = &base[..path_start];
    let path = &base[path_start..];
    let path = if path.contains("/openai/chat/completions") {
        path.to_owned()
    } else if let Some(index) = path.find("/openai") {
        format!("{}/openai/chat/completions", &path[..index])
    } else {
        format!("{GOOGLE_OPENAI_BASE_PATH}/chat/completions")
    };
    format!("{origin}{path}{suffix}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Deserialize)]
    struct PythonProtocolVectors {
        endpoints: Vec<PythonEndpointVector>,
    }

    #[derive(Deserialize)]
    struct PythonEndpointVector {
        input: String,
        chat_completions: String,
        responses: String,
        models: String,
        supports_responses: bool,
    }

    fn python_vectors() -> PythonProtocolVectors {
        serde_json::from_str(include_str!("../../../compat/llm_protocol_vectors.json")).unwrap()
    }

    #[test]
    fn endpoint_normalization_matches_python_compatibility_rules() {
        for vector in python_vectors().endpoints {
            assert_eq!(
                chat_completions_api_url(&vector.input),
                vector.chat_completions
            );
            assert_eq!(responses_api_url(&vector.input), vector.responses);
            assert_eq!(models_api_url(&vector.input), vector.models);
            assert_eq!(
                supports_openai_responses_api(&vector.input),
                vector.supports_responses
            );
        }
        assert_eq!(
            chat_completions_api_url("https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions"
        );
        assert_eq!(
            responses_api_url("https://api.openai.com/v1/chat/completions"),
            "https://api.openai.com/v1/responses"
        );
        assert_eq!(
            models_api_url("https://api.openai.com/v1/responses?tenant=1"),
            "https://api.openai.com/v1/models"
        );
        assert_eq!(
            chat_completions_api_url(
                "https://generativelanguage.googleapis.com/v1beta/models?key=test"
            ),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions?key=test"
        );
        assert!(supports_openai_responses_api(
            "https://api.openai.com/v1/responses"
        ));
        assert!(!supports_openai_responses_api(
            "https://openrouter.ai/api/v1/responses"
        ));
    }

    #[test]
    fn request_bodies_preserve_thinking_tools_and_responses_message_conversion() {
        let messages = vec![
            json!({"role": "system", "content": "Be Ran"}),
            json!({"role": "system", "content": "Stay concise"}),
            json!({"role": "user", "content": [
                {"type": "text", "text": "Look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}
            ]}),
            json!({"role": "tool", "tool_call_id": "call_1", "content": "done"}),
        ];
        let tools = vec![json!({"type": "function", "function": {"name": "search"}})];
        let chat = build_chat_completions_body(
            "https://api.openai.com/v1/chat/completions",
            "gpt-test",
            &messages,
            true,
            Some(true),
            &tools,
        );
        assert_eq!(chat["enable_thinking"], true);
        assert_eq!(chat["thinking"]["type"], "enabled");
        assert_eq!(chat["reasoning_effort"], "medium");
        assert_eq!(chat["stream_options"]["include_usage"], true);
        assert_eq!(chat["tool_choice"], "auto");

        let google = build_chat_completions_body(
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "gemini-test",
            &messages,
            false,
            Some(true),
            &[],
        );
        assert!(google.get("enable_thinking").is_none());
        assert!(google.get("thinking").is_none());
        assert_eq!(google["reasoning_effort"], "medium");

        let responses =
            build_responses_body("gpt-test", &messages, true, Some(false), &tools, "resp_1");
        assert_eq!(responses["instructions"], "Be Ran\n\nStay concise");
        assert_eq!(responses["reasoning"]["effort"], "none");
        assert_eq!(responses["previous_response_id"], "resp_1");
        assert_eq!(responses["input"][0]["content"][0]["type"], "input_text");
        assert_eq!(responses["input"][0]["content"][1]["type"], "input_image");
        assert_eq!(responses["input"][1]["type"], "function_call_output");
    }

    #[test]
    fn chat_sse_normalizes_text_reasoning_tools_usage_and_completion() {
        let mut decoder = LlmSseDecoder::new(LlmApiMode::ChatCompletions);
        let events = decoder
            .feed_line(
                r#"data: {"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5},"choices":[{"delta":{"content":"hello","reasoning_content":"think","tool_calls":[{"index":0,"id":"call_1","function":{"name":"search","arguments":"{\"q\":"}}]},"finish_reason":null}]}"#,
            )
            .unwrap();
        assert!(matches!(events[0], LlmStreamEvent::Usage { .. }));
        assert!(matches!(events[1], LlmStreamEvent::ToolCallDelta { .. }));
        assert_eq!(
            events[2],
            LlmStreamEvent::ReasoningDelta {
                text: "think".to_owned()
            }
        );
        assert_eq!(
            events[3],
            LlmStreamEvent::TextDelta {
                text: "hello".to_owned()
            }
        );
        assert_eq!(
            decoder.feed_line("data: [DONE]").unwrap(),
            vec![LlmStreamEvent::Completed]
        );
        assert!(decoder.is_completed());
    }

    #[test]
    fn responses_sse_avoids_replaying_final_text_after_deltas() {
        let mut decoder = LlmSseDecoder::new(LlmApiMode::Responses);
        assert_eq!(
            decoder
                .feed_line(r#"data: {"type":"response.created","response":{"id":"resp_1"}}"#)
                .unwrap(),
            vec![LlmStreamEvent::ResponseId {
                id: "resp_1".to_owned()
            }]
        );
        decoder
            .feed_line(r#"data: {"type":"response.output_text.delta","delta":"hello"}"#)
            .unwrap();
        let events = decoder
            .feed_line(
                r#"data: {"type":"response.completed","response":{"id":"resp_1","output_text":"hello","usage":{"input_tokens":4,"output_tokens":1,"total_tokens":5}}}"#,
            )
            .unwrap();
        assert!(
            !events
                .iter()
                .any(|event| matches!(event, LlmStreamEvent::TextDelta { .. }))
        );
        assert!(
            events
                .iter()
                .any(|event| matches!(event, LlmStreamEvent::Usage { .. }))
        );
        assert_eq!(events.last(), Some(&LlmStreamEvent::Completed));
        assert!(decoder.is_completed());

        let mut fallback = LlmSseDecoder::new(LlmApiMode::Responses);
        let events = fallback
            .feed_line(
                r#"data: {"type":"response.done","response":{"output":[{"content":[{"type":"output_text","text":"fallback"}]}]}}"#,
            )
            .unwrap();
        assert_eq!(
            events[0],
            LlmStreamEvent::TextDelta {
                text: "fallback".to_owned()
            }
        );
        assert_eq!(events[1], LlmStreamEvent::Completed);
    }

    #[test]
    fn responses_sse_surfaces_provider_errors() {
        let mut decoder = LlmSseDecoder::new(LlmApiMode::Responses);
        assert_eq!(
            decoder.feed_line(r#"data: {"type":"error","message":"denied"}"#),
            Err(LlmProtocolError::Stream("denied".to_owned()))
        );
    }
}
