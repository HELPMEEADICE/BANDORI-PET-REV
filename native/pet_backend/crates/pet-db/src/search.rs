use crate::{value::*, Result};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::collections::BTreeSet;

const HISTORY: &str = "SELECT 'private' AS source,m.id AS source_id,CAST(c.id AS TEXT) AS conversation_id,c.character AS character,'' AS group_key,c.title AS chat_title,c.user_key AS user_key,m.role AS role,m.content AS content,m.created_at AS created_at,'|'||c.character||'|' AS member_keys FROM messages m JOIN conversations c ON c.id=m.conversation_id UNION ALL SELECT 'group' AS source,gm.id AS source_id,CAST(gm.conversation_id AS TEXT) AS conversation_id,'' AS character,gm.group_key AS group_key,COALESCE(meta.display_name,'') AS chat_title,gm.user_key AS user_key,gm.role AS role,gm.content AS content,gm.created_at AS created_at,CASE WHEN gm.group_key LIKE '__group__:%' THEN '|'||substr(gm.group_key,11)||'|' ELSE '|'||gm.group_key||'|' END AS member_keys FROM group_messages gm LEFT JOIN group_chat_meta meta ON meta.group_key=gm.group_key";

pub fn members(key: &str) -> Vec<String> {
    key.strip_prefix("__group__:")
        .map(|s| {
            s.split('|')
                .filter(|s| !s.is_empty())
                .map(String::from)
                .collect()
        })
        .unwrap_or_default()
}
pub fn speaker(content: &str) -> String {
    let first = content.lines().next().unwrap_or("").trim();
    first
        .strip_prefix('【')
        .and_then(|s| s.split_once('】'))
        .map(|(s, _)| s.trim().into())
        .unwrap_or_default()
}
pub fn filters(c: &Connection) -> Result<Value> {
    let mut characters = BTreeSet::new();
    for row in query(
        c,
        "SELECT DISTINCT character FROM conversations WHERE character!=''",
        &[],
    )? {
        let s = trim(&row, "character");
        if !s.is_empty() && s != "__group__" {
            characters.insert(s);
        }
    }
    for row in query(
        c,
        "SELECT DISTINCT group_key FROM group_messages WHERE group_key!=''",
        &[],
    )? {
        characters.extend(members(&string(&row, "group_key")));
    }
    let mut users = BTreeSet::new();
    for row in query(c,"SELECT user_key FROM conversations WHERE user_key!='' UNION SELECT user_key FROM group_messages WHERE user_key!=''",&[])? { let s=trim(&row,"user_key"); if !s.is_empty(){users.insert(s);} }
    let mut characters = characters.into_iter().collect::<Vec<_>>();
    let mut users = users.into_iter().collect::<Vec<_>>();
    // Exact Python casefold order is applied by the compatibility adapter to this
    // small metadata result (never to message rows).
    characters.sort_by_key(|s| s.to_lowercase());
    users.sort_by_key(|s| s.to_lowercase());
    Ok(json!({"characters":characters,"user_keys":users}))
}
pub fn search(c: &Connection, a: &Value) -> Result<Value> {
    let keyword = short(&trim(a, "keyword"), 500);
    let from = short(&trim(a, "date_from"), 10);
    let to = short(&trim(a, "date_to"), 10);
    let mut clauses = vec![];
    let mut p = vec![];
    if !keyword.is_empty() {
        clauses.push("content LIKE ? ESCAPE '\\' COLLATE NOCASE");
        p.push(json!(like(&keyword)));
    }
    if !from.is_empty() {
        clauses.push("created_at>=?");
        p.push(json!(format!("{from} 00:00:00")));
    }
    if !to.is_empty() {
        clauses.push("created_at<=?");
        p.push(json!(format!("{to} 23:59:59")));
    }
    if !trim(a, "character").is_empty() {
        clauses.push("instr(member_keys,?)>0");
        p.push(json!(format!("|{}|", trim(a, "character"))));
    }
    if !trim(a, "user_key").is_empty() {
        clauses.push("user_key=?");
        p.push(json!(trim(a, "user_key")));
    }
    if ["user", "assistant", "system"].contains(&trim(a, "role").as_str()) {
        clauses.push("role=?");
        p.push(json!(trim(a, "role")));
    }
    if ["private", "group"].contains(&trim(a, "source").as_str()) {
        clauses.push("source=?");
        p.push(json!(trim(a, "source")));
    }
    let where_sql = if clauses.is_empty() {
        String::new()
    } else {
        format!(" WHERE {}", clauses.join(" AND "))
    };
    let skip = truth(&a["skip_count"]);
    let limit = clamp(&a["limit"], 1, 1000, 300);
    let offset = clamp(&a["offset"], 0, 1_000_000, 0);
    let total = if skip {
        json!(-1)
    } else {
        scalar(
            c,
            &format!("SELECT COUNT(*) FROM ({HISTORY}) history{where_sql}"),
            &p,
        )?
    };
    p.extend([json!(limit + i64::from(skip)), json!(offset)]);
    let mut records=query(c,&format!("SELECT source,source_id AS id,conversation_id,character,group_key,chat_title,user_key,role,content,created_at FROM ({HISTORY}) history{where_sql} ORDER BY created_at DESC,source_id DESC LIMIT ? OFFSET ?"),&p)?;
    let more = skip && records.len() > limit as usize;
    records.truncate(limit as usize);
    for r in &mut records {
        normalize_strings(
            r,
            &[
                "source",
                "conversation_id",
                "character",
                "group_key",
                "chat_title",
                "user_key",
                "role",
                "content",
                "created_at",
            ],
        );
        r["id"] = json!(int(r, "id"));
    }
    Ok(json!({"total":total,"has_more":more,"records":records,"limit":limit,"offset":offset}))
}
