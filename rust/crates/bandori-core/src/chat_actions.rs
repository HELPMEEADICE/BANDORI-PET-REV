use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[cfg(test)]
const PROMPT_CONTRACT_JSON: &str = include_str!("../../../compat/chat_prompt_vectors.json");

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ParsedChatResponse {
    pub content: String,
    pub reasoning: String,
    pub actions: Vec<String>,
}

pub fn parse_chat_response(content: &str, reasoning: &str) -> ParsedChatResponse {
    ParsedChatResponse {
        content: strip_action_tags(content),
        reasoning: strip_action_tags(reasoning),
        actions: parse_action_tags(content),
    }
}

pub fn parse_action_tags(text: &str) -> Vec<String> {
    let mut actions = Vec::new();
    let mut seen = HashSet::new();
    for (_, _, candidate) in bracketed_segments(text) {
        let action = candidate.trim();
        if action.eq_ignore_ascii_case("done")
            || action.eq_ignore_ascii_case("d o n e")
            || !is_action_token(action)
        {
            continue;
        }
        if seen.insert(action.to_owned()) {
            actions.push(action.to_owned());
        }
    }
    actions
}

pub fn strip_action_tags(text: &str) -> String {
    let mut result = String::with_capacity(text.len());
    let mut scan = 0;
    let mut copied = 0;
    while let Some(open_offset) = text[scan..].find('[') {
        let start = scan + open_offset;
        let content_start = start + 1;
        let Some(close_offset) = text[content_start..].find(']') else {
            break;
        };
        let end = content_start + close_offset + 1;
        let candidate = &text[content_start..end - 1];
        if candidate.eq_ignore_ascii_case("done") || is_action_token(candidate) {
            result.push_str(&text[copied..start]);
            copied = end;
            scan = end;
        } else {
            scan = content_start;
        }
    }
    result.push_str(&text[copied..]);
    result.trim().to_owned()
}

fn bracketed_segments(text: &str) -> Vec<(usize, usize, &str)> {
    let mut segments = Vec::new();
    let mut cursor = 0;
    while let Some(open_offset) = text[cursor..].find('[') {
        let start = cursor + open_offset;
        let content_start = start + 1;
        let Some(close_offset) = text[content_start..].find(']') else {
            break;
        };
        let close = content_start + close_offset;
        segments.push((start, close + 1, &text[content_start..close]));
        cursor = close + 1;
    }
    segments
}

fn is_action_token(value: &str) -> bool {
    !value.is_empty()
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Deserialize)]
    struct Vectors {
        action_cases: Vec<ActionCase>,
    }

    #[derive(Deserialize)]
    struct ActionCase {
        input: String,
        actions: Vec<String>,
        stripped: String,
    }

    #[test]
    fn generated_python_action_vectors_match_rust() {
        let vectors: Vectors = serde_json::from_str(PROMPT_CONTRACT_JSON).unwrap();
        for case in vectors.action_cases {
            assert_eq!(parse_action_tags(&case.input), case.actions);
            assert_eq!(strip_action_tags(&case.input), case.stripped);
        }
    }

    #[test]
    fn response_only_takes_actions_from_visible_content() {
        let parsed = parse_chat_response("hello[smile]", "thinking[angry]");
        assert_eq!(parsed.content, "hello");
        assert_eq!(parsed.reasoning, "thinking");
        assert_eq!(parsed.actions, ["smile"]);
    }
}
