use crate::{
    chat, memory,
    search::{members, speaker},
    value::*,
    Error, Result,
};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

fn aliases(a: &Value) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    out.insert(trim(a, "character"));
    if let Some(items) = a["character_aliases"].as_array() {
        for v in items {
            let s = text(v).trim().to_owned();
            if !s.is_empty() {
                out.insert(s);
            }
        }
    }
    out.remove("");
    out
}
fn matches(role: &str, content: &str, aliases: &BTreeSet<String>) -> bool {
    let who = speaker(content);
    role != "assistant" || who.is_empty() || aliases.contains(&who)
}
fn album(row: Value, grouped: bool) -> Option<Value> {
    let mut r = chat::message(row, grouped)?;
    r["source"] = json!(if grouped { "group" } else { "private" });
    if grouped && r["role"] == "assistant" {
        r["speaker"] = json!(speaker(&string(&r, "content")));
    }
    Some(r)
}
pub fn recent(c: &Connection, a: &Value) -> Result<Value> {
    let limit = clamp(&a["limit"], 1, 200, 24);
    let aliases = aliases(a);
    let character = string(a, "character");
    let user = user(a);
    let mut out=query(c,"SELECT m.id,m.conversation_id,m.role,m.content,m.reasoning_content,m.attachments_json,m.tool_trace_json,m.created_at FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.character=? AND c.user_key=? ORDER BY m.id DESC LIMIT ?",&[json!(character),json!(user),json!(limit)])?.into_iter().filter_map(|r|album(r,false)).collect::<Vec<_>>();
    for r in query(c,&format!("SELECT {} FROM group_messages WHERE user_key=? AND group_key LIKE '__group__:%' ORDER BY id DESC LIMIT ?",chat::GROUP),&[json!(user),json!((limit*8).clamp(120,1000))])?{
        if members(&string(&r,"group_key")).contains(&character)&&matches(&string(&r,"role"),&string(&r,"content"),&aliases){if let Some(r)=album(r,true){out.push(r);}}
    }
    out.sort_by(|a, b| {
        text(&b["created_at"])
            .cmp(&text(&a["created_at"]))
            .then_with(|| int(b, "id").cmp(&int(a, "id")))
    });
    out.truncate(limit as usize);
    out.reverse();
    Ok(json!(out))
}
fn preview(
    c: &Connection,
    group: &str,
    conv: &str,
    user: &str,
    aliases: &BTreeSet<String>,
) -> Result<(String, i64)> {
    let mut preview = String::new();
    let mut count = 0;
    visit(c,"SELECT role,content FROM group_messages WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) AND user_key=? ORDER BY id DESC",&[json!(group),json!(conv),json!(conv),json!(user)],|r|{let content=string(&r,"content");if matches(&string(&r,"role"),&content,aliases){count+=1;if preview.is_empty(){preview=content;}}Ok(())})?;
    Ok((preview, count))
}
fn chain(c: &Connection, a: &Value) -> Result<Value> {
    let limit = clamp(&a["limit"], 1, 100, 20);
    let aliases = aliases(a);
    let character = string(a, "character");
    let user = user(a);
    let rows=query(c,"SELECT c.id,c.character,c.user_key,c.title,c.created_at,MIN(m.created_at) AS first_message_at,MAX(m.created_at) AS last_message_at,COUNT(m.id) AS message_count,(SELECT content FROM messages WHERE conversation_id=c.id AND role='user' AND content!='' ORDER BY id ASC LIMIT 1) AS first_user,(SELECT content FROM messages WHERE conversation_id=c.id AND content!='' ORDER BY id DESC LIMIT 1) AS preview FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.character=? AND c.user_key=? GROUP BY c.id,c.character,c.user_key,c.title,c.created_at ORDER BY MAX(m.id) DESC LIMIT ?",&[json!(character),json!(user),json!(limit)])?;
    let mut out = vec![];
    for r in rows {
        out.push(json!({"source":"private","conversation_id":int(&r,"id"),"group_key":"","user_key":string(&r,"user_key"),"title":string(&r,"title"),"created_at":string(&r,"created_at"),"first_message_at":string(&r,"first_message_at"),"last_message_at":string(&r,"last_message_at"),"message_count":int(&r,"message_count"),"first_user":string(&r,"first_user"),"preview":string(&r,"preview")}));
    }
    let rows=query(c,"SELECT group_key,conversation_id,MIN(created_at) AS first_at,MAX(created_at) AS last_at,COUNT(id) AS count,(SELECT content FROM group_messages gm2 WHERE gm2.group_key=gm.group_key AND gm2.conversation_id=gm.conversation_id AND gm2.user_key=gm.user_key AND gm2.role='user' AND gm2.content!='' ORDER BY gm2.id ASC LIMIT 1) AS first_user,(SELECT content FROM group_messages gm2 WHERE gm2.group_key=gm.group_key AND gm2.conversation_id=gm.conversation_id AND gm2.user_key=gm.user_key AND gm2.content!='' ORDER BY gm2.id DESC LIMIT 1) AS preview FROM group_messages gm WHERE gm.user_key=? AND gm.group_key LIKE '__group__:%' GROUP BY group_key,conversation_id,user_key ORDER BY MAX(id) DESC LIMIT ?",&[json!(user),json!((limit*6).clamp(60,300))])?;
    for r in rows {
        let group = string(&r, "group_key");
        if !members(&group).contains(&character) {
            continue;
        }
        let conv = chat::conversation(&r);
        let (preview, count) = preview(c, &group, &conv, &user, &aliases)?;
        out.push(json!({"source":"group","conversation_id":conv,"group_key":group,"user_key":user,"title":"","created_at":r["first_at"],"first_message_at":r["first_at"],"last_message_at":r["last_at"],"message_count":if count==0{int(&r,"count")}else{count},"first_user":string(&r,"first_user"),"preview":if preview.is_empty(){string(&r,"preview")}else{preview}}));
    }
    out.sort_by(|a, b| text(&b["last_message_at"]).cmp(&text(&a["last_message_at"])));
    out.truncate(limit as usize);
    Ok(json!(out))
}
fn day_entry(day: &str, at: &str) -> Value {
    json!({"day":day,"message_count":0,"user_count":0,"assistant_count":0,"first_at":at,"last_at":at,"snippets":[],"snippet_items":[]})
}
fn days(c: &Connection, a: &Value) -> Result<Value> {
    let limit = clamp(&a["limit"], 1, 120, 30);
    let mut args = a.clone();
    args["limit"] = json!(600);
    let messages = recent(c, &args)?;
    let mut days = BTreeMap::<String, Value>::new();
    if let Some(messages) = messages.as_array() {
        for m in messages {
            let at = string(m, "created_at");
            if at.chars().count() < 10 {
                continue;
            }
            let day = short(&at, 10);
            let entry = days
                .entry(day.clone())
                .or_insert_with(|| day_entry(&day, &at));
            entry["message_count"] = json!(int(entry, "message_count") + 1);
            for (role, key) in [("user", "user_count"), ("assistant", "assistant_count")] {
                if m["role"] == role {
                    entry[key] = json!(int(entry, key) + 1);
                }
            }
            if at < string(entry, "first_at") {
                entry["first_at"] = json!(at);
            }
            if at > string(entry, "last_at") {
                entry["last_at"] = json!(at);
            }
            let content = string(m, "content")
                .split_whitespace()
                .collect::<Vec<_>>()
                .join(" ");
            if content.is_empty() {
                continue;
            }
            if let Some(snips) = entry["snippets"].as_array_mut() {
                if snips.len() < 3 {
                    snips.push(json!(short(&content, 120)));
                }
            }
            if let Some(snips) = entry["snippet_items"].as_array_mut() {
                if snips.len() < 3 {
                    snips.push(json!({"role":m["role"],"content":short(&content,160),"source":m["source"],"speaker":string(m,"speaker")}));
                }
            }
        }
    }
    args["limit"] = json!(100);
    if let Some(memories) = memory::memories(c, &args, false)?.as_array() {
        for m in memories {
            let created = string(m, "created_at");
            let at = if created.is_empty() {
                string(m, "updated_at")
            } else {
                created
            };
            if at.chars().count() < 10 {
                continue;
            }
            let day = short(&at, 10);
            let entry = days
                .entry(day.clone())
                .or_insert_with(|| day_entry(&day, &at));
            entry["memory_count"] = json!(int(entry, "memory_count") + 1);
            if m["kind"] == "favorite" {
                entry["favorite_count"] = json!(int(entry, "favorite_count") + 1);
            }
        }
    }
    Ok(json!(days
        .into_values()
        .rev()
        .take(limit as usize)
        .collect::<Vec<_>>()))
}
pub fn call(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    match op {
        "get_character_recent_messages" => recent(c, a),
        "get_character_conversation_chain" => chain(c, a),
        "get_character_album_days" => days(c, a),
        _ => Err(Error::Invalid(format!("unknown album operation: {op}"))),
    }
}
