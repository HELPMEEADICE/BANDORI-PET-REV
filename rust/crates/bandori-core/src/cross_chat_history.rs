use crate::chat_prompt::character_display_name;
use crate::database::{Database, DatabaseError, GroupMessage, Message};
use serde_json::Value;
use std::collections::HashSet;

const DEFAULT_CROSS_CHAT_LIMIT: usize = 18;
#[cfg(test)]
const PROMPT_CONTRACT_JSON: &str = include_str!("../../../compat/chat_prompt_vectors.json");

#[derive(Clone, Debug, Eq, PartialEq)]
struct HistoryItem {
    created_at: String,
    id: i64,
    sequence: usize,
    label: String,
    content: String,
}

pub fn build_cross_chat_history(
    database: &Database,
    character: &str,
    user_key: &str,
    user_display_name: &str,
    limit: usize,
) -> Result<String, DatabaseError> {
    let character = character.trim();
    if character.is_empty() {
        return Ok(String::new());
    }
    let limit = if limit == 0 {
        DEFAULT_CROSS_CHAT_LIMIT
    } else {
        limit.min(100)
    };
    let related = [character.to_owned()];
    let related_set = related.iter().map(String::as_str).collect::<HashSet<_>>();
    let user_label = if user_display_name.trim().is_empty() {
        "你"
    } else {
        user_display_name.trim()
    };
    let mut items = Vec::new();
    let mut seen = HashSet::<(&'static str, i64)>::new();
    let mut sequence = 0;

    for member in &related {
        let display = character_display_name(member);
        for conversation in database
            .get_conversations(Some(member), Some(user_key))?
            .into_iter()
            .take(3)
        {
            for message in database
                .get_messages(conversation.id, Some(6), None)?
                .into_iter()
            {
                let label = match message.role.as_str() {
                    "assistant" => format!("{display}/私聊"),
                    "user" => format!("{user_label}/{display}"),
                    _ => continue,
                };
                append_private_item(&mut items, &mut seen, &mut sequence, message, label);
            }
        }
    }

    for chat in database.group_chats(Some(user_key))?.into_iter().take(24) {
        let members = characters_for_group_key(&chat.group_key);
        if members.is_empty()
            || !members
                .iter()
                .any(|member| related_set.contains(member.as_str()))
        {
            continue;
        }
        for message in database.get_group_messages(
            &chat.group_key,
            &chat.conversation_id,
            Some(8),
            Some(user_key),
            None,
        )? {
            let (label, content) = match message.role.as_str() {
                "assistant" => {
                    let (speaker, body) = split_group_history_message(&message.content, &members);
                    (format!("{speaker}/群聊"), body)
                }
                "user" => (format!("{user_label}/群聊"), message.content.clone()),
                _ => continue,
            };
            append_group_item(
                &mut items,
                &mut seen,
                &mut sequence,
                message,
                label,
                content,
            );
        }
    }

    items.sort_by(|left, right| {
        (&left.created_at, left.id, left.sequence).cmp(&(
            &right.created_at,
            right.id,
            right.sequence,
        ))
    });
    let start = items.len().saturating_sub(limit);
    let recent = &items[start..];
    if recent.is_empty() {
        return Ok(String::new());
    }
    let mut lines = vec![
        "以下是过去聊天摘录，仅供参考；其中提到的晚上、凌晨、昨天等都只代表当时，不代表现在。"
            .to_owned(),
    ];
    lines.extend(recent.iter().map(|item| {
        format!(
            "[{}] {}：{}",
            history_time_label(&item.created_at),
            item.label,
            item.content
        )
    }));
    Ok(lines.join("\n"))
}

fn append_private_item(
    items: &mut Vec<HistoryItem>,
    seen: &mut HashSet<(&'static str, i64)>,
    sequence: &mut usize,
    message: Message,
    label: String,
) {
    if !seen.insert(("private", message.id)) {
        return;
    }
    let content = compact_history_text(&message.content, &message.attachments_json);
    if content.is_empty() {
        return;
    }
    items.push(HistoryItem {
        created_at: message.created_at,
        id: message.id,
        sequence: *sequence,
        label,
        content,
    });
    *sequence += 1;
}

fn append_group_item(
    items: &mut Vec<HistoryItem>,
    seen: &mut HashSet<(&'static str, i64)>,
    sequence: &mut usize,
    message: GroupMessage,
    label: String,
    content: String,
) {
    if !seen.insert(("group", message.id)) {
        return;
    }
    let content = compact_history_text(&content, &message.attachments_json);
    if content.is_empty() {
        return;
    }
    items.push(HistoryItem {
        created_at: message.created_at,
        id: message.id,
        sequence: *sequence,
        label,
        content,
    });
    *sequence += 1;
}

fn compact_history_text(content: &str, attachments_json: &str) -> String {
    let mut text = content.trim().to_owned();
    let attachments = serde_json::from_str::<Value>(attachments_json)
        .ok()
        .and_then(|value| value.as_array().cloned())
        .unwrap_or_default();
    if !attachments.is_empty() {
        let image_count = attachments
            .iter()
            .filter(|item| item.get("type").and_then(Value::as_str) == Some("image"))
            .count();
        let file_count = attachments
            .iter()
            .filter(|item| item.get("type").and_then(Value::as_str) == Some("file"))
            .count();
        let mut labels = Vec::new();
        if image_count > 0 {
            labels.push(format!("图片 {image_count} 张"));
        }
        if file_count > 0 {
            labels.push(format!("文件 {file_count} 个"));
        }
        if !labels.is_empty() {
            if !text.is_empty() {
                text.push('\n');
            }
            text.push('[');
            text.push_str(&labels.join("，"));
            text.push(']');
        }
    }
    let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if text.chars().count() <= 420 {
        text
    } else {
        let mut text = text.chars().take(420).collect::<String>();
        text = text.trim_end().to_owned();
        text.push_str("...");
        text
    }
}

fn characters_for_group_key(group_key: &str) -> Vec<String> {
    group_key
        .strip_prefix("__group__:")
        .map(|members| {
            members
                .split('|')
                .map(str::trim)
                .filter(|member| !member.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

fn split_group_history_message(content: &str, members: &[String]) -> (String, String) {
    let text = content.trim();
    let first_line = text.lines().next().unwrap_or_default().trim();
    if let Some(rest) = first_line.strip_prefix('【') {
        if let Some((speaker, _)) = rest.split_once('】') {
            let body = text.lines().skip(1).collect::<Vec<_>>().join("\n");
            return (
                nonempty_or(speaker.trim(), "AI").to_owned(),
                body.trim().to_owned(),
            );
        }
    }
    for member in members {
        let display = character_display_name(member);
        for prefix in [
            format!("【{display}】"),
            format!("{display}："),
            format!("{display}:"),
        ] {
            if let Some(body) = text.strip_prefix(&prefix) {
                return (display, body.trim().to_owned());
            }
        }
    }
    ("AI".to_owned(), text.to_owned())
}

fn history_time_label(created_at: &str) -> String {
    let text = created_at.trim();
    let bytes = text.as_bytes();
    let valid = bytes.len() == 19
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes[10] == b' '
        && bytes[13] == b':'
        && bytes[16] == b':'
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| matches!(index, 4 | 7 | 10 | 13 | 16) || byte.is_ascii_digit());
    if valid {
        text[..16].to_owned()
    } else if text.is_empty() {
        "未知时间".to_owned()
    } else {
        text.to_owned()
    }
}

fn nonempty_or<'a>(value: &'a str, fallback: &'a str) -> &'a str {
    if value.is_empty() { fallback } else { value }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;
    use serde_json::json;
    use std::fs;

    #[test]
    fn cross_chat_history_filters_user_and_unrelated_groups_and_compacts_attachments() {
        let directory = tempfile::tempdir().unwrap();
        let attachment_root = directory.path().join("chat_attachments");
        fs::create_dir(&attachment_root).unwrap();
        let image = attachment_root.join("image.png");
        fs::write(&image, b"image").unwrap();
        let database = Database::open(directory.path().join("data.db")).unwrap();
        let private = database
            .begin_private_chat_turn(
                "ran",
                "alice",
                None,
                "  私聊里  的消息  ",
                Some(&json!([{"type":"image","path":image,"name":"image.png"}])),
            )
            .unwrap();
        database
            .add_message(
                private.conversation_id,
                "assistant",
                "知道了",
                "",
                None,
                None,
            )
            .unwrap();
        database
            .begin_private_chat_turn("ran", "bob", None, "不应出现的用户", None)
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "g1",
                "user",
                "群聊问题",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "g1",
                "assistant",
                "【青叶摩卡】\n群聊回答",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:arisa|kasumi",
                "g2",
                "user",
                "不相关群聊",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        let context = build_cross_chat_history(&database, "ran", "alice", "Alice", 18).unwrap();
        assert!(context.starts_with("以下是过去聊天摘录"));
        assert!(context.contains("Alice/美竹兰：私聊里 的消息 [图片 1 张]"));
        assert!(context.contains("美竹兰/私聊：知道了"));
        assert!(context.contains("Alice/群聊：群聊问题"));
        assert!(context.contains("青叶摩卡/群聊：群聊回答"));
        assert!(!context.contains("不应出现的用户"));
        assert!(!context.contains("不相关群聊"));
    }

    #[test]
    fn malformed_and_empty_timestamps_match_python_fallback_labels() {
        assert_eq!(
            history_time_label("2026-07-15 23:09:10"),
            "2026-07-15 23:09"
        );
        assert_eq!(history_time_label("bad"), "bad");
        assert_eq!(history_time_label(""), "未知时间");
    }

    #[derive(Deserialize)]
    struct Vectors {
        cross_chat_history: CrossChatContract,
    }

    #[derive(Deserialize)]
    struct CrossChatContract {
        expected: String,
    }

    #[test]
    fn generated_python_cross_chat_history_matches_rust() {
        let directory = tempfile::tempdir().unwrap();
        let database_path = directory.path().join("data.db");
        let database = Database::open(&database_path).unwrap();
        let private = database.create_conversation("ran", "", "alice").unwrap();
        let private_user = database
            .add_message(private, "user", "  私聊里  的消息  ", "", None, None)
            .unwrap();
        let private_assistant = database
            .add_message(private, "assistant", "知道了", "", None, None)
            .unwrap();
        let bob = database.create_conversation("ran", "", "bob").unwrap();
        database
            .add_message(bob, "user", "不应出现的用户", "", None, None)
            .unwrap();
        let group_user = database
            .add_group_message(
                "__group__:moca|ran",
                "g1",
                "user",
                "群聊问题",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        let group_assistant = database
            .add_group_message(
                "__group__:moca|ran",
                "g1",
                "assistant",
                "【青叶摩卡】\n群聊回答",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:arisa|kasumi",
                "g2",
                "user",
                "不相关群聊",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        let connection = rusqlite::Connection::open(&database_path).unwrap();
        for (table, message_id, created_at) in [
            ("messages", private_user, "2026-07-14 08:01:02"),
            ("messages", private_assistant, "2026-07-14 08:02:03"),
            ("group_messages", group_user, "2026-07-15 09:03:04"),
            ("group_messages", group_assistant, "2026-07-15 09:04:05"),
        ] {
            connection
                .execute(
                    &format!("UPDATE {table} SET created_at=? WHERE id=?"),
                    rusqlite::params![created_at, message_id],
                )
                .unwrap();
        }
        drop(connection);
        let vectors: Vectors = serde_json::from_str(PROMPT_CONTRACT_JSON).unwrap();
        assert_eq!(
            build_cross_chat_history(&database, "ran", "alice", "Alice", 18).unwrap(),
            vectors.cross_chat_history.expected
        );
    }
}
