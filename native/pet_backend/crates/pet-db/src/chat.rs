use crate::{value::*, Error, Result};
use rusqlite::Connection;
use serde_json::{json, Value};

pub const MESSAGE: &str = "id, conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at";
pub const GROUP: &str = "id, group_key, conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at";

pub fn message(mut row: Value, grouped: bool) -> Option<Value> {
    let role = text(&row["role"]).trim().to_owned();
    if !["user", "assistant", "system"].contains(&role.as_str()) {
        return None;
    }
    row["id"] = json!(integer(&row["id"])?);
    if grouped {
        row["conversation_id"] = json!(if text(&row["conversation_id"]).is_empty() {
            "default".into()
        } else {
            text(&row["conversation_id"])
        });
        row["group_key"] = json!(text(&row["group_key"]));
    } else {
        row["conversation_id"] = json!(integer(&row["conversation_id"])?);
    }
    normalize_strings(
        &mut row,
        &[
            "content",
            "reasoning_content",
            "attachments_json",
            "tool_trace_json",
            "created_at",
        ],
    );
    row["role"] = json!(role);
    Some(row)
}

pub fn messages(c: &Connection, a: &Value, grouped: bool) -> Result<Value> {
    let (table, columns, mut clause, mut p) = if grouped {
        let conv = conversation(a);
        (
            "group_messages",
            GROUP,
            "group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)".into(),
            vec![a["group_key"].clone(), json!(conv), json!(conv)],
        )
    } else {
        (
            "messages",
            MESSAGE,
            "conversation_id=?".into(),
            vec![a["conversation_id"].clone()],
        )
    };
    if grouped {
        scope(a, "user_key", &mut clause, &mut p);
    }
    if int(a, "before_id") > 0 {
        clause.push_str(" AND id<?");
        p.push(json!(int(a, "before_id")));
    }
    let limited = !a["limit"].is_null();
    let order = if limited { "DESC LIMIT ?" } else { "ASC" };
    if limited {
        p.push(json!(clamp(&a["limit"], 1, 1000, 1000)));
    }
    let mut rows: Vec<_> = query(
        c,
        &format!("SELECT {columns} FROM {table} WHERE {clause} ORDER BY id {order}"),
        &p,
    )?
    .into_iter()
    .filter_map(|r| message(r, grouped))
    .collect();
    if limited {
        rows.reverse();
    }
    Ok(json!(rows))
}

pub fn conversation(a: &Value) -> String {
    let s = string(a, "conversation_id");
    if s.is_empty() {
        "default".into()
    } else {
        s
    }
}

fn mutate_messages(c: &Connection, op: &str, a: &Value, grouped: bool) -> Result<Value> {
    let (table, cols, mut clause, mut p) = if grouped {
        (
            "group_messages",
            GROUP,
            "group_key=? AND conversation_id=?".to_owned(),
            vec![a["group_key"].clone(), json!(conversation(a))],
        )
    } else {
        (
            "messages",
            MESSAGE,
            "conversation_id=?".into(),
            vec![a["conversation_id"].clone()],
        )
    };
    if grouped {
        scope(a, "user_key", &mut clause, &mut p);
    }
    if op.contains("update_") {
        clause.push_str(" AND id=?");
        p.push(a["message_id"].clone());
        p.insert(0, json!(trim(a, "content")));
        return Ok(json!(
            exec(
                c,
                &format!("UPDATE {table} SET content=? WHERE {clause}"),
                &p
            )? > 0
        ));
    }
    let operator = if op.ends_with("messages_from") {
        if a["include_selected"] == false {
            ">"
        } else {
            ">="
        }
    } else {
        "="
    };
    clause.push_str(&format!(" AND id{operator}?"));
    p.push(a["message_id"].clone());
    let rows: Vec<_> = query(
        c,
        &format!("SELECT {cols} FROM {table} WHERE {clause} ORDER BY id ASC"),
        &p,
    )?
    .into_iter()
    .filter_map(|r| message(r, grouped))
    .collect();
    exec(c, &format!("DELETE FROM {table} WHERE {clause}"), &p)?;
    Ok(json!(rows))
}

fn conversations(c: &Connection, a: &Value, last: bool) -> Result<Value> {
    let mut clause = "(latest.id IS NOT NULL OR c.temporary_background!='')".to_owned();
    let mut p = vec![];
    if truth(&a["character"]) || last {
        clause.push_str(" AND c.character=?");
        p.push(a["character"].clone());
    }
    scope(a, "c.user_key", &mut clause, &mut p);
    let limit = if last { " LIMIT 1" } else { "" };
    let mut rows = query(c,&format!("SELECT c.id,c.character,c.user_key,c.title,c.created_at,latest.created_at AS last_message_at,latest.content AS last_message_content FROM conversations c LEFT JOIN messages latest ON latest.id=(SELECT MAX(m.id) FROM messages m WHERE m.conversation_id=c.id) WHERE {clause} ORDER BY COALESCE(latest.created_at,c.created_at) DESC,c.id DESC{limit}"),&p)?;
    for row in &mut rows {
        normalize_strings(
            row,
            &[
                "character",
                "user_key",
                "title",
                "created_at",
                "last_message_at",
                "last_message_content",
            ],
        );
    }
    if last {
        Ok(rows.into_iter().next().unwrap_or(Value::Null))
    } else {
        Ok(json!(rows))
    }
}

pub fn token_usage<'a>(rows: impl Iterator<Item = &'a Value>) -> Value {
    let mut totals = json!({"input_tokens":0,"output_tokens":0,"total_tokens":0,"estimated":false,"request_count":0,"untracked_count":0});
    for row in rows {
        accumulate_tokens(&mut totals, row);
    }
    totals
}

fn accumulate_tokens(totals: &mut Value, row: &Value) {
    let parsed = parse_json(&text(&row["tool_trace_json"]));
    let usage = &parsed["llm_usage"];
    if !usage.is_object() {
        totals["untracked_count"] = json!(int(totals, "untracked_count") + 1);
        return;
    }
    let input = int(usage, "input_tokens").max(0);
    let output = int(usage, "output_tokens").max(0);
    let total = integer(&usage["total_tokens"])
        .filter(|n| *n != 0)
        .unwrap_or(input.saturating_add(output))
        .max(0);
    for (key, n) in [
        ("input_tokens", input),
        ("output_tokens", output),
        ("total_tokens", total),
        ("request_count", 1),
    ] {
        totals[key] = json!(int(totals, key).saturating_add(n));
    }
    totals["estimated"] = json!(truth(&totals["estimated"]) || truth(&usage["estimated"]));
}

fn metadata(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    let group = string(a, "group_key");
    match op {
        "get_group_display_name" => Ok(json!(text(&scalar(
            c,
            "SELECT display_name FROM group_chat_meta WHERE group_key=?",
            &[json!(group)]
        )?))),
        "set_group_display_name" => {
            let name = trim(a, "display_name");
            if name.is_empty() {
                exec(
                    c,
                    "DELETE FROM group_chat_meta WHERE group_key=?",
                    &[json!(group)],
                )?;
            } else {
                exec(c,"INSERT INTO group_chat_meta(group_key,display_name,updated_at) VALUES(?,?,?) ON CONFLICT(group_key) DO UPDATE SET display_name=excluded.display_name,updated_at=excluded.updated_at",&[json!(group),json!(name),now(c)?])?;
            }
            Ok(Value::Null)
        }
        "get_conversation_temporary_background" => Ok(json!(text(&scalar(
            c,
            "SELECT temporary_background FROM conversations WHERE id=?",
            &[a["conversation_id"].clone()]
        )?)
        .trim())),
        "set_conversation_temporary_background" => {
            let id = integer(&a["conversation_id"])
                .ok_or_else(|| Error::Invalid("conversation_id must be an integer".into()))?;
            exec(
                c,
                "UPDATE conversations SET temporary_background=? WHERE id=?",
                &[json!(trim(a, "content")), json!(id)],
            )?;
            Ok(Value::Null)
        }
        "get_group_conversation_temporary_background" => {
            let mut clause = "group_key=? AND conversation_id=?".into();
            let mut p = vec![json!(group), json!(conversation(a))];
            scope(a, "user_key", &mut clause, &mut p);
            Ok(json!(text(&scalar(c,&format!("SELECT temporary_background FROM group_conversation_backgrounds WHERE {clause} LIMIT 1"),&p)?).trim()))
        }
        "set_group_conversation_temporary_background" => {
            let p = vec![json!(group), json!(conversation(a)), json!(user(a))];
            let content = trim(a, "content");
            if content.is_empty() {
                exec(c,"DELETE FROM group_conversation_backgrounds WHERE group_key=? AND conversation_id=? AND user_key=?",&p)?;
            } else {
                let mut p = p;
                p.extend([json!(content), now(c)?]);
                exec(c,"INSERT INTO group_conversation_backgrounds(group_key,conversation_id,user_key,temporary_background,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(group_key,conversation_id,user_key) DO UPDATE SET temporary_background=excluded.temporary_background,updated_at=excluded.updated_at",&p)?;
            }
            Ok(Value::Null)
        }
        _ => Err(Error::Invalid(op.into())),
    }
}

fn groups(c: &Connection, a: &Value, all: bool) -> Result<Value> {
    let mut clause = String::from("role IN ('user','assistant','system')");
    let mut p = vec![];
    if !all {
        clause.push_str(" AND group_key=?");
        p.push(a["group_key"].clone());
    }
    scope(a, "user_key", &mut clause, &mut p);
    let group_by = if all { "group_key" } else { "conversation_id" };
    let mut rows=query(c,&format!("SELECT g.group_key,g.conversation_id,g.user_key,g.id AS message_id,g.role,g.content,g.created_at FROM group_messages g JOIN (SELECT MAX(id) AS latest_id FROM group_messages WHERE {clause} GROUP BY {group_by}) latest ON g.id=latest.latest_id ORDER BY latest.latest_id DESC"),&p)?;
    for r in &mut rows {
        normalize_strings(
            r,
            &[
                "group_key",
                "conversation_id",
                "user_key",
                "role",
                "content",
                "created_at",
            ],
        );
        if r["conversation_id"] == "" {
            r["conversation_id"] = json!("default");
        }
    }
    if !all {
        let mut clause = "group_key=? AND temporary_background!=''".into();
        let mut p = vec![a["group_key"].clone()];
        scope(a, "user_key", &mut clause, &mut p);
        for r in query(c,&format!("SELECT conversation_id,user_key,updated_at FROM group_conversation_backgrounds WHERE {clause}"),&p)? {
            if rows.iter().any(|v| text(&v["conversation_id"])==text(&r["conversation_id"])) { continue; }
            rows.push(json!({"group_key":a["group_key"],"conversation_id":text(&r["conversation_id"]),"user_key":text(&r["user_key"]),"message_id":0,"role":"system","content":"","created_at":text(&r["updated_at"])}));
        }
        rows.sort_by(|a, b| {
            text(&b["created_at"])
                .cmp(&text(&a["created_at"]))
                .then_with(|| int(b, "message_id").cmp(&int(a, "message_id")))
        });
    }
    Ok(json!(rows))
}

pub fn call(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    match op {
        "create_conversation" => { exec(c,"INSERT INTO conversations(character,user_key,title,created_at) VALUES(?,?,?,?)",&[a["character"].clone(),json!(user(a)),a["title"].clone(),now(c)?])?; Ok(json!(c.last_insert_rowid())) }
        "get_conversations" | "get_last_conversation" => conversations(c,a,op=="get_last_conversation"),
        "add_message" | "add_group_message" => {
            let mut p=vec![];
            let (table,cols,marks)=if op=="add_group_message" { p.extend([a["group_key"].clone(),json!(conversation(a)),json!(user(a))]); ("group_messages","group_key,conversation_id,user_key,role,content,reasoning_content,attachments_json,tool_trace_json,created_at","?,?,?,?,?,?,?,?,?") }
            else { p.push(a["conversation_id"].clone()); ("messages","conversation_id,role,content,reasoning_content,attachments_json,tool_trace_json,created_at","?,?,?,?,?,?,?") };
            p.extend([a["role"].clone(),a["content"].clone(),a["reasoning_content"].clone(),a["attachments_json"].clone(),a["tool_trace_json"].clone(),now(c)?]);
            exec(c,&format!("INSERT INTO {table}({cols}) VALUES({marks})"),&p)?; Ok(json!(c.last_insert_rowid()))
        }
        "add_messages" => {
            let items=a["messages"].as_array().ok_or_else(|| Error::Invalid("messages must be a list".into()))?;
            items.iter().map(|item| { let mut args=item.clone(); args["conversation_id"]=a["conversation_id"].clone(); call(c,"add_message",&args) }).collect::<Result<Vec<_>>>().map(|v| json!(v))
        }
        "get_messages" | "get_group_messages" => messages(c,a,op=="get_group_messages"),
        "update_message_content" | "delete_messages_from" | "delete_message" => mutate_messages(c,op,a,false),
        "update_group_message_content" | "delete_group_messages_from" | "delete_group_message" => mutate_messages(c,op,a,true),
        "get_first_user_message_content" => Ok(json!(text(&scalar(c,"SELECT content FROM messages WHERE conversation_id=? AND role='user' AND content!='' ORDER BY id ASC LIMIT 1",&[a["conversation_id"].clone()])?).trim())),
        "get_conversation_attachment_payloads" | "get_group_conversation_attachment_payloads" | "get_conversation_token_usage" | "get_group_conversation_token_usage" => {
            let grouped=op.contains("group_"); let usage=op.ends_with("token_usage");
            if usage && !truth(&a["conversation_id"]) { return Ok(token_usage([].iter())); }
            let (table,mut clause,mut p)=if grouped { ("group_messages","group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)".into(),vec![a["group_key"].clone(),json!(conversation(a)),json!(conversation(a))]) } else { ("messages","conversation_id=?".into(),vec![a["conversation_id"].clone()]) };
            if grouped { scope(a,"user_key",&mut clause,&mut p); }
            let column=if usage { clause.push_str(" AND role='assistant'"); "tool_trace_json" } else { clause.push_str(" AND attachments_json!=''"); "attachments_json" };
            let q=format!("SELECT {column} FROM {table} WHERE {clause}");
            if usage {
                let mut totals=token_usage([].iter());
                visit(c,&q,&p,|row|{accumulate_tokens(&mut totals,&row);Ok(())})?;
                Ok(totals)
            } else { Ok(json!(query(c,&q,&p)?.into_iter().map(|r| text(&r[column])).collect::<Vec<_>>())) }
        }
        "assign_legacy_chat_history_user" => {
            let p=[json!(user(a))]; let n=exec(c,"UPDATE conversations SET user_key=? WHERE user_key='' OR user_key IS NULL",&p)?;
            Ok(json!(n+exec(c,"UPDATE group_messages SET user_key=? WHERE user_key='' OR user_key IS NULL",&p)?))
        }
        "delete_conversation" => { exec(c,"DELETE FROM conversations WHERE id=?",&[a["conv_id"].clone()])?; Ok(Value::Null) }
        "delete_empty_conversations" => {
            let mut clause=String::from("NOT EXISTS (SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id) AND temporary_background=''"); let mut p=vec![];
            if truth(&a["character"]) { clause.push_str(" AND character=?"); p.push(a["character"].clone()); } scope(a,"user_key",&mut clause,&mut p);
            exec(c,&format!("DELETE FROM conversations WHERE {clause}"),&p)?; Ok(Value::Null)
        }
        "delete_group_conversation" => {
            let mut clause="group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)".into(); let mut p=vec![a["group_key"].clone(),json!(conversation(a)),json!(conversation(a))]; scope(a,"user_key",&mut clause,&mut p);
            exec(c,&format!("DELETE FROM group_messages WHERE {clause}"),&p)?;
            exec(c,&format!("DELETE FROM group_conversation_backgrounds WHERE {clause}"),&p)?; Ok(Value::Null)
        }
        "get_group_conversations" | "get_group_chats" => groups(c,a,op=="get_group_chats"),
        "get_group_display_name" | "set_group_display_name" | "get_conversation_temporary_background" | "set_conversation_temporary_background" | "get_group_conversation_temporary_background" | "set_group_conversation_temporary_background" => metadata(c,op,a),
        _ => Err(Error::Invalid(format!("unknown chat operation: {op}"))),
    }
}
