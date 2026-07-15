use crate::chat_attachments::group_chat_message_content;
use crate::chat_context::{
    NativeChatMessage, NativeChatRequest, append_dynamic_context_to_last_user,
    append_external_chat_context, history_message_limit,
};
use crate::chat_prompt::{
    build_native_system_prompt_with_role, build_relationship_context, load_character_markdown,
};
use crate::chat_tools::{native_chat_tools, with_native_tool_system_hint};
use crate::config::ConfigDocument;
use crate::cross_chat_history::build_cross_chat_history;
use crate::database::{Database, DatabaseError, GroupConversation, GroupMessage};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashSet;
use std::path::Path;

pub const GROUP_KEY_PREFIX: &str = "__group__:";
pub const GROUP_PLANNER_SYSTEM_PROMPT: &str = concat!(
    "你是群聊发言调度器。根据用户最新发言、成员关系和最近上下文，决定接下来哪些角色发言以及发言条数。",
    "输出必须是严格 JSON，格式：{\"speakers\":[\"角色key\",...]}。",
    "speakers 长度 1 到 6。可以让同一角色连续或多次出现。",
    "如果 latest_interaction.priority_speaker 不为空，则 speakers 第一项必须是该 key，后续再安排其他成员自然接话。",
    "只允许使用给定成员 key，不要输出解释、Markdown 或多余文字。"
);

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GroupMember {
    pub key: String,
    pub name: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct GroupRecentMessage {
    pub role: String,
    pub content: String,
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeGroupChatSnapshot {
    pub chats: Vec<GroupConversation>,
    pub conversations: Vec<GroupConversation>,
    pub messages: Vec<GroupMessage>,
    pub active_group_key: String,
    pub active_conversation_id: String,
    pub has_older_messages: bool,
}

pub fn normalize_group_characters(characters: &[String]) -> Vec<String> {
    let mut seen = HashSet::new();
    characters
        .iter()
        .filter(|character| !character.is_empty() && seen.insert((*character).clone()))
        .cloned()
        .collect()
}

pub fn conversation_key_for(characters: &[String], fallback_character: &str) -> String {
    let mut normalized = normalize_group_characters(characters);
    if normalized.len() <= 1 {
        return normalized
            .pop()
            .unwrap_or_else(|| fallback_character.to_owned());
    }
    normalized.sort_by_cached_key(|character| character.to_lowercase());
    format!("{GROUP_KEY_PREFIX}{}", normalized.join("|"))
}

pub fn characters_for_group_key(group_key: &str, allowed: &[String]) -> Vec<String> {
    let Some(source) = group_key.strip_prefix(GROUP_KEY_PREFIX) else {
        return Vec::new();
    };
    let allowed = allowed.iter().map(String::as_str).collect::<HashSet<_>>();
    source
        .split('|')
        .filter(|character| allowed.contains(character))
        .map(str::to_owned)
        .collect()
}

pub fn build_group_system_prompt(base_prompt: &str, members: &[GroupMember]) -> String {
    let names = members
        .iter()
        .map(|member| member.name.as_str())
        .collect::<Vec<_>>()
        .join("、");
    format!(
        "{base_prompt}\n\n【群聊规则】\n这是一个多人群聊。当前群聊成员：{names}。\n\
你只扮演自己，不要代替其他角色说话。\n\
本轮只有你一个角色发言；其他角色如果需要回应，程序会在后续轮次单独生成。\n\
你的输出必须是一条仅属于你自己的单人回复，不要写成多人连续对话、对手戏脚本或旁白串场。\n\
严禁输出其他角色的直接台词，严禁替其他角色回答，严禁在同一条回复里模拟别人接话。\n\
如果需要提到其他成员的反应，只能用你自己的视角转述，不能写出对方的原话。\n\
回复时不要添加任何角色名前缀或剧本标签，例如【角色名】、[角色名]、角色名：，程序会自动添加。"
    )
}

pub fn build_group_planner_request(
    members: &[GroupMember],
    latest_user_message: &str,
    priority_speaker: &str,
    recent_history: &[GroupRecentMessage],
) -> NativeChatRequest {
    let priority_speaker = if members.iter().any(|member| member.key == priority_speaker) {
        priority_speaker
    } else {
        ""
    };
    let payload = json!({
        "members": members,
        "latest_user_message": latest_user_message,
        "latest_interaction": {
            "type": if priority_speaker.is_empty() { "" } else { "poke" },
            "priority_speaker": priority_speaker,
        },
        "recent_history": recent_history,
    });
    NativeChatRequest {
        messages: vec![
            NativeChatMessage {
                role: "system".to_owned(),
                content: Value::String(GROUP_PLANNER_SYSTEM_PROMPT.to_owned()),
            },
            NativeChatMessage {
                role: "user".to_owned(),
                content: Value::String(
                    serde_json::to_string(&payload)
                        .expect("group planner payload serialization cannot fail"),
                ),
            },
        ],
        tools: Vec::new(),
    }
}

pub fn parse_group_plan(source: &str, members: &[GroupMember]) -> Vec<String> {
    let json_source = source
        .find('{')
        .zip(source.rfind('}'))
        .filter(|(start, end)| start <= end)
        .map(|(start, end)| &source[start..=end])
        .unwrap_or(source);
    let speakers = serde_json::from_str::<Value>(json_source)
        .ok()
        .and_then(|value| value.get("speakers").cloned())
        .and_then(|value| value.as_array().cloned())
        .unwrap_or_default();
    let allowed = members
        .iter()
        .map(|member| (member.key.as_str(), member.name.as_str()))
        .collect::<Vec<_>>();
    let mut result = Vec::new();
    for speaker in speakers {
        let Some(speaker) = speaker.as_str() else {
            continue;
        };
        if let Some((key, _)) = allowed
            .iter()
            .find(|(key, name)| speaker == *key || speaker == *name)
        {
            result.push((*key).to_owned());
        }
        if result.len() >= 6 {
            break;
        }
    }
    result
}

pub fn apply_group_plan_priority(
    queue: &[String],
    priority_character: &str,
    members: &[GroupMember],
) -> Vec<String> {
    if priority_character.is_empty()
        || !members
            .iter()
            .any(|member| member.key == priority_character)
    {
        return queue.iter().take(6).cloned().collect();
    }
    let mut result = vec![priority_character.to_owned()];
    result.extend(
        queue
            .iter()
            .filter(|character| character.as_str() != priority_character)
            .cloned(),
    );
    if !result
        .iter()
        .any(|character| character != priority_character)
    {
        result.extend(
            members
                .iter()
                .filter(|member| member.key != priority_character)
                .map(|member| member.key.clone()),
        );
    }
    result.truncate(6);
    result
}

pub fn fallback_group_plan(members: &[GroupMember], priority_character: &str) -> Vec<String> {
    let queue = members
        .iter()
        .take(3)
        .map(|member| member.key.clone())
        .collect::<Vec<_>>();
    apply_group_plan_priority(&queue, priority_character, members)
}

pub fn sanitize_group_assistant_reply(
    active_display_name: &str,
    members: &[GroupMember],
    source: &str,
) -> String {
    if source.is_empty() || members.is_empty() {
        return source.to_owned();
    }
    let matches = group_label_matches(source, members);
    if matches.is_empty() {
        return source.trim().to_owned();
    }
    let active_segments = matches
        .iter()
        .enumerate()
        .filter(|(_, item)| item.speaker == active_display_name)
        .filter_map(|(index, item)| {
            let end = matches
                .get(index + 1)
                .map(|next| next.start)
                .unwrap_or(source.len());
            let segment = source[item.content_start..end].trim();
            (!segment.is_empty()).then(|| segment.to_owned())
        })
        .collect::<Vec<_>>();
    if !active_segments.is_empty() {
        return active_segments.join("\n\n").trim().to_owned();
    }
    let mut cleaned = String::with_capacity(source.len());
    let mut cursor = 0;
    for item in matches {
        cleaned.push_str(&source[cursor..item.start]);
        cursor = item.content_start;
    }
    cleaned.push_str(&source[cursor..]);
    cleaned.trim().to_owned()
}

pub fn group_assistant_content(
    character: &str,
    members: &[GroupMember],
    source: &str,
) -> Result<String, DatabaseError> {
    let display_name = members
        .iter()
        .find(|member| member.key == character)
        .map(|member| member.name.as_str())
        .ok_or_else(|| {
            DatabaseError::InvalidOperation(
                "group assistant character is not a member of the selected group".to_owned(),
            )
        })?;
    let reply = sanitize_group_assistant_reply(display_name, members, source);
    Ok(format!("【{display_name}】\n{reply}"))
}

#[allow(clippy::too_many_arguments)]
pub fn build_native_group_chat_request(
    database: &Database,
    config: &ConfigDocument,
    project_root: &Path,
    character: &str,
    character_display_name: &str,
    user_key: &str,
    group_key: &str,
    conversation_id: &str,
    members: &[GroupMember],
    spoken_names: &[String],
    current_time_instruction: &str,
    special_event_context: &str,
) -> Result<NativeChatRequest, DatabaseError> {
    let member_keys = members
        .iter()
        .map(|member| member.key.clone())
        .collect::<Vec<_>>();
    if members.len() < 2
        || conversation_key_for(&member_keys, "") != group_key
        || !members.iter().any(|member| member.key == character)
        || conversation_id.trim().is_empty()
    {
        return Err(DatabaseError::InvalidOperation(
            "native group chat request has an invalid group selection".to_owned(),
        ));
    }
    let owns_conversation = database
        .group_conversations(group_key, Some(user_key))?
        .iter()
        .any(|conversation| conversation.conversation_id == conversation_id);
    if !owns_conversation {
        return Err(DatabaseError::InvalidOperation(
            "group conversation does not belong to the selected group and user".to_owned(),
        ));
    }

    let markdown = load_character_markdown(project_root, character);
    let role_markdown = config
        .get("pov_role_character")
        .and_then(Value::as_str)
        .map(|role| load_character_markdown(project_root, role))
        .unwrap_or_default();
    let mut base_prompt = build_native_system_prompt_with_role(
        character,
        character_display_name,
        config.values(),
        &markdown,
        &role_markdown,
    );
    if !special_event_context.trim().is_empty() {
        base_prompt.push_str("\n\n【今日特殊事件】\n");
        base_prompt.push_str(special_event_context.trim());
    }
    let system_prompt =
        with_native_tool_system_hint(&build_group_system_prompt(&base_prompt, members));
    let user_display_name = config
        .get("user_name")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    let relationship_display_name = if user_display_name.is_empty() {
        "你"
    } else {
        user_display_name
    };
    let mut dynamic_context =
        build_relationship_context(database, character, user_key, relationship_display_name)?;
    if config
        .get("llm_cross_chat_history_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        let cross_chat =
            build_cross_chat_history(database, character, user_key, user_display_name, 18)?;
        if !cross_chat.is_empty() {
            dynamic_context.push_str("\n\n【跨聊天记录】\n");
            dynamic_context.push_str(&cross_chat);
        }
    }
    if !spoken_names.is_empty() {
        dynamic_context.push_str("\n\n【群聊发言顺序】\n你是在");
        dynamic_context.push_str(&spoken_names.join("、"));
        dynamic_context.push_str("之后发言，请自然承接前面角色的内容。");
    }
    append_external_chat_context(database, config, &mut dynamic_context)?;
    let current_time_instruction = current_time_instruction.trim();
    if !current_time_instruction.is_empty() {
        dynamic_context.push_str("\n\n【后置提示词】\n");
        dynamic_context.push_str(current_time_instruction);
    }

    let history = database.get_group_messages(
        group_key,
        conversation_id,
        history_message_limit(config.get("llm_chat_history_message_limit")),
        Some(user_key),
        None,
    )?;
    let latest_user_message_id = history
        .iter()
        .rev()
        .find(|message| message.role == "user")
        .map(|message| message.id);
    let mut messages = Vec::with_capacity(history.len() + 1);
    messages.push(NativeChatMessage {
        role: "system".to_owned(),
        content: Value::String(system_prompt),
    });
    messages.extend(history.into_iter().map(|message| NativeChatMessage {
        role: message.role.clone(),
        content: group_chat_message_content(
            database,
            &message,
            message.role == "user" && Some(message.id) == latest_user_message_id,
        ),
    }));
    append_dynamic_context_to_last_user(&mut messages, &dynamic_context)?;
    Ok(NativeChatRequest {
        messages,
        tools: native_chat_tools(),
    })
}

pub fn build_group_planner_request_from_database(
    database: &Database,
    group_key: &str,
    conversation_id: &str,
    user_key: &str,
    members: &[GroupMember],
    latest_user_message: &str,
    priority_speaker: &str,
) -> Result<NativeChatRequest, DatabaseError> {
    let history = if conversation_id.trim().is_empty() {
        Vec::new()
    } else {
        database.get_group_messages(group_key, conversation_id, Some(12), Some(user_key), None)?
    };
    let recent = history
        .into_iter()
        .map(|message| GroupRecentMessage {
            role: message.role,
            content: message.content,
        })
        .collect::<Vec<_>>();
    Ok(build_group_planner_request(
        members,
        latest_user_message,
        priority_speaker,
        &recent,
    ))
}

pub fn load_native_group_chat_snapshot(
    database_path: impl AsRef<Path>,
    group_key: &str,
    user_key: &str,
    requested_conversation_id: Option<&str>,
    message_limit: i64,
) -> Result<NativeGroupChatSnapshot, DatabaseError> {
    let database = Database::open(database_path)?;
    let chats = database.group_chats(Some(user_key))?;
    let active_group_key = if group_key.trim().is_empty() {
        chats
            .first()
            .map(|chat| chat.group_key.clone())
            .unwrap_or_default()
    } else {
        group_key.trim().to_owned()
    };
    let conversations = if active_group_key.is_empty() {
        Vec::new()
    } else {
        database.group_conversations(&active_group_key, Some(user_key))?
    };
    let active_conversation_id = requested_conversation_id
        .map(str::trim)
        .filter(|requested| {
            conversations
                .iter()
                .any(|conversation| conversation.conversation_id == *requested)
        })
        .map(str::to_owned)
        .or_else(|| {
            conversations
                .first()
                .map(|conversation| conversation.conversation_id.clone())
        })
        .unwrap_or_default();
    let (messages, has_older_messages) = if active_conversation_id.is_empty() {
        (Vec::new(), false)
    } else {
        let messages = database.get_group_messages(
            &active_group_key,
            &active_conversation_id,
            Some(message_limit.clamp(1, 1000)),
            Some(user_key),
            None,
        )?;
        let has_older = match messages.first() {
            Some(oldest) => !database
                .get_group_messages(
                    &active_group_key,
                    &active_conversation_id,
                    Some(1),
                    Some(user_key),
                    Some(oldest.id),
                )?
                .is_empty(),
            None => false,
        };
        (messages, has_older)
    };
    Ok(NativeGroupChatSnapshot {
        chats,
        conversations,
        messages,
        active_group_key,
        active_conversation_id,
        has_older_messages,
    })
}

#[derive(Clone, Debug)]
struct GroupLabelMatch {
    start: usize,
    content_start: usize,
    speaker: String,
}

fn group_label_matches(source: &str, members: &[GroupMember]) -> Vec<GroupLabelMatch> {
    let mut names = members
        .iter()
        .map(|member| member.name.as_str())
        .collect::<Vec<_>>();
    names.sort_by_key(|name| std::cmp::Reverse(name.len()));
    let mut result = Vec::new();
    let mut line_start = 0;
    for line in source.split_inclusive('\n') {
        let leading = line.len() - line.trim_start_matches([' ', '\t']).len();
        let label_source = &line[leading..];
        let mut found = None;
        for name in &names {
            for prefix in [
                format!("【{name}】"),
                format!("[{name}]"),
                format!("{name}："),
                format!("{name}:"),
            ] {
                if label_source.starts_with(&prefix) {
                    found = Some((*name, leading + prefix.len()));
                    break;
                }
            }
            if found.is_some() {
                break;
            }
        }
        if let Some((speaker, prefix_end)) = found {
            let mut content_start = line_start + prefix_end;
            while let Some(character) = source[content_start..].chars().next() {
                if !character.is_whitespace() {
                    break;
                }
                content_start += character.len_utf8();
            }
            result.push(GroupLabelMatch {
                start: line_start,
                content_start,
                speaker: speaker.to_owned(),
            });
        }
        line_start += line.len();
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn contract() -> Value {
        serde_json::from_str(include_str!("../../../compat/chat_prompt_vectors.json")).unwrap()
    }

    fn contract_members() -> Vec<GroupMember> {
        serde_json::from_value(contract()["group_chat"]["members"].clone()).unwrap()
    }

    #[test]
    fn generated_python_group_chat_contract_matches_rust() {
        let contract = contract();
        let group = &contract["group_chat"];
        let members = contract_members();
        for case in group["key_cases"].as_array().unwrap() {
            let characters =
                serde_json::from_value::<Vec<String>>(case["characters"].clone()).unwrap();
            assert_eq!(
                normalize_group_characters(&characters),
                serde_json::from_value::<Vec<String>>(case["normalized"].clone()).unwrap()
            );
            assert_eq!(
                conversation_key_for(&characters, case["fallback"].as_str().unwrap()),
                case["expected"].as_str().unwrap()
            );
        }
        assert_eq!(
            build_group_system_prompt("BASE", &members),
            group["system_prompt"].as_str().unwrap()
        );
        for case in group["plan_cases"].as_array().unwrap() {
            assert_eq!(
                parse_group_plan(case["source"].as_str().unwrap(), &members),
                serde_json::from_value::<Vec<String>>(case["expected"].clone()).unwrap()
            );
        }
        for case in group["priority_cases"].as_array().unwrap() {
            let queue = serde_json::from_value::<Vec<String>>(case["queue"].clone()).unwrap();
            assert_eq!(
                apply_group_plan_priority(&queue, case["priority"].as_str().unwrap(), &members),
                serde_json::from_value::<Vec<String>>(case["expected"].clone()).unwrap()
            );
        }
        for case in group["assistant_cases"].as_array().unwrap() {
            assert_eq!(
                group_assistant_content(
                    case["character"].as_str().unwrap(),
                    &members,
                    case["source"].as_str().unwrap()
                )
                .unwrap(),
                case["expected"].as_str().unwrap()
            );
        }
    }

    #[test]
    fn planner_request_and_group_prompt_use_scoped_history() {
        let directory = tempfile::tempdir().unwrap();
        let database = Database::open(directory.path().join("data.db")).unwrap();
        let members = vec![
            GroupMember {
                key: "ran".to_owned(),
                name: "美竹兰".to_owned(),
            },
            GroupMember {
                key: "moca".to_owned(),
                name: "青叶摩卡".to_owned(),
            },
        ];
        assert!(
            database
                .begin_group_chat_turn(
                    "__group__:ran|moca",
                    "alice",
                    None,
                    "invalid-group",
                    "大家好",
                    None,
                )
                .is_err()
        );
        let turn = database
            .begin_group_chat_turn(
                "__group__:moca|ran",
                "alice",
                None,
                "group-1",
                "大家好",
                None,
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "group-1",
                "assistant",
                "【美竹兰】\n你好",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "group-1",
                "user",
                "不应出现",
                "",
                None,
                None,
                "bob",
            )
            .unwrap();
        let planner = build_group_planner_request_from_database(
            &database,
            &turn.group_key,
            &turn.conversation_id,
            "alice",
            &members,
            "大家好",
            "moca",
        )
        .unwrap();
        let payload: Value =
            serde_json::from_str(planner.messages[1].content.as_str().unwrap()).unwrap();
        assert!(planner.tools.is_empty());
        assert_eq!(payload["latest_interaction"]["type"], "poke");
        assert_eq!(payload["recent_history"].as_array().unwrap().len(), 2);

        let config = ConfigDocument::from_value(
            json!({
                "llm_cross_chat_history_enabled": false,
                "llm_chat_history_message_limit": 40,
            }),
            false,
        )
        .unwrap();
        let request = build_native_group_chat_request(
            &database,
            &config,
            directory.path(),
            "moca",
            "青叶摩卡",
            "alice",
            &turn.group_key,
            &turn.conversation_id,
            &members,
            &["美竹兰".to_owned()],
            "现在是测试时间",
            "【夏日祭】\n今天是夏日祭。",
        )
        .unwrap();
        assert_eq!(request.tools, native_chat_tools());
        assert!(
            request.messages[0]
                .content
                .as_str()
                .unwrap()
                .contains("本轮只有你一个角色发言")
        );
        assert!(
            request.messages[0]
                .content
                .as_str()
                .unwrap()
                .contains("【今日特殊事件】\n【夏日祭】")
        );
        let last_user = request
            .messages
            .iter()
            .rev()
            .find(|message| message.role == "user")
            .unwrap();
        let text = last_user.content.as_str().unwrap();
        assert!(text.contains("【群聊发言顺序】\n你是在美竹兰之后发言"));
        assert!(text.ends_with("【后置提示词】\n现在是测试时间"));
        assert!(
            !request
                .messages
                .iter()
                .any(|message| message.content.as_str() == Some("不应出现"))
        );
    }

    #[test]
    fn group_snapshot_selects_owned_history_and_reports_pagination() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("data.db");
        let database = Database::open(&path).unwrap();
        for index in 0..4 {
            database
                .add_group_message(
                    "__group__:moca|ran",
                    "group-1",
                    "user",
                    &format!("message-{index}"),
                    "",
                    None,
                    None,
                    "alice",
                )
                .unwrap();
        }
        database
            .add_group_message(
                "__group__:moca|ran",
                "group-2",
                "user",
                "newest",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        drop(database);
        let snapshot = load_native_group_chat_snapshot(
            &path,
            "__group__:moca|ran",
            "alice",
            Some("group-1"),
            2,
        )
        .unwrap();
        assert_eq!(snapshot.conversations.len(), 2);
        assert_eq!(snapshot.active_conversation_id, "group-1");
        assert_eq!(snapshot.messages.len(), 2);
        assert_eq!(snapshot.messages[0].content, "message-2");
        assert!(snapshot.has_older_messages);
    }
}
