use crate::{value::*, Error, Result};
use rusqlite::Connection;
use serde_json::{json, Value};

const MESSAGE: &str="id,platform,thread_id,external_message_id,sender_id,sender_name,direction,content,unread,raw_json,created_at";
const THREAD: &str = "platform,thread_id,thread_name,unread_count,last_message_at";
fn clean(v: &Value) -> String {
    short(text(v).trim(), 500)
}
fn first(a: &Value, keys: &[&str], default: &str) -> String {
    keys.iter()
        .map(|k| &a[*k])
        .find(|v| truth(v))
        .map(clean)
        .unwrap_or_else(|| default.into())
}
fn row(mut r: Value) -> Value {
    normalize_strings(
        &mut r,
        &[
            "platform",
            "thread_id",
            "external_message_id",
            "sender_id",
            "sender_name",
            "direction",
            "content",
            "raw_json",
            "created_at",
        ],
    );
    for (k, d) in [
        ("platform", "external"),
        ("thread_id", "default"),
        ("direction", "inbound"),
    ] {
        if r[k] == "" {
            r[k] = json!(d);
        }
    }
    r["id"] = json!(int(&r, "id"));
    r["unread"] = json!(int(&r, "unread") != 0);
    r
}
fn thread_row(mut r: Value) -> Value {
    for (k, d) in [("platform", "external"), ("thread_id", "default")] {
        let s = string(&r, k);
        r[k] = json!(if s.is_empty() { d } else { &s });
    }
    let name = string(&r, "thread_name");
    r["thread_name"] = json!(if name.is_empty() {
        string(&r, "thread_id")
    } else {
        name
    });
    r["last_message_at"] = json!(string(&r, "last_message_at"));
    r["unread_count"] = json!(int(&r, "unread_count"));
    r
}
fn thread(c: &Connection, platform: &str, id: &str) -> Result<Value> {
    let r = one(
        c,
        &format!("SELECT {THREAD} FROM external_chat_threads WHERE platform=? AND thread_id=?"),
        &[json!(platform), json!(id)],
    )?;
    Ok(if r.is_null() {
        json!({"platform":platform,"thread_id":id,"thread_name":id,"unread_count":0,"last_message_at":""})
    } else {
        thread_row(r)
    })
}
pub fn unread(c: &Connection, a: &Value) -> Result<Value> {
    let total = scalar(
        c,
        "SELECT COALESCE(SUM(unread_count),0) FROM external_chat_threads",
        &[],
    )?;
    let mut threads=query(c,&format!("SELECT {THREAD} FROM external_chat_threads WHERE unread_count>0 ORDER BY last_message_at DESC,updated_at DESC LIMIT ?"),&[json!(clamp(&a["limit_threads"],1,20,5))])?;
    for t in &mut threads {
        *t = thread_row(t.clone());
        let mut rows=query(c,&format!("SELECT {MESSAGE} FROM external_chat_messages WHERE platform=? AND thread_id=? AND unread=1 ORDER BY id DESC LIMIT ?"),&[t["platform"].clone(),t["thread_id"].clone(),json!(clamp(&a["limit_messages"],1,10,3))])?;
        rows.reverse();
        t["messages"] = json!(rows.into_iter().map(row).collect::<Vec<_>>());
    }
    Ok(json!({"total_unread":integer(&total).unwrap_or(0),"threads":threads}))
}
fn resync(c: &Connection) -> Result<()> {
    exec(c,"DELETE FROM external_chat_threads WHERE NOT EXISTS(SELECT 1 FROM external_chat_messages m WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id)",&[])?;
    exec(c,"UPDATE external_chat_threads SET unread_count=(SELECT COUNT(*) FROM external_chat_messages m WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id AND m.unread=1),last_message_id=(SELECT MAX(m.id) FROM external_chat_messages m WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id),last_message_at=(SELECT m.created_at FROM external_chat_messages m WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id ORDER BY m.id DESC LIMIT 1),updated_at=?",&[now(c)?])?;
    Ok(())
}
fn prune(c: &Connection, platform: &Value, id: &Value) -> Result<usize> {
    exec(c,"DELETE FROM external_chat_messages WHERE platform=? AND thread_id=? AND chat_type='group' AND id NOT IN(SELECT id FROM external_chat_messages WHERE platform=? AND thread_id=? AND chat_type='group' ORDER BY id DESC LIMIT 50)",&[platform.clone(),id.clone(),platform.clone(),id.clone()])
}
fn add(c: &Connection, a: &Value) -> Result<Value> {
    let e = &a["event"];
    if !e.is_object() {
        return Err(Error::Invalid("chat event must be an object".into()));
    }
    let platform = first(e, &["platform", "source"], "external");
    let platform = if platform.is_empty() {
        "external".into()
    } else {
        platform
    };
    let id = first(
        e,
        &["thread_id", "conversation_id", "chat_id", "room_id"],
        "default",
    );
    let id = if id.is_empty() { "default".into() } else { id };
    let name = first(
        e,
        &["thread_name", "conversation_name", "chat_name", "room_name"],
        &id,
    );
    let external = first(e, &["message_id", "external_message_id", "id"], "");
    let sender = first(e, &["sender_id", "author_id"], "");
    let sender_name = first(
        e,
        &["sender_name", "author_name", "sender", "from"],
        if sender.is_empty() {
            "unknown"
        } else {
            &sender
        },
    );
    let content = e
        .as_object()
        .and_then(|o| {
            ["text", "content", "message", "body"]
                .iter()
                .filter_map(|k| o.get(*k))
                .find(|v| truth(v))
        })
        .map(|v| short(text(v).trim(), 20_000))
        .unwrap_or_default();
    if content.is_empty() {
        return Err(Error::Invalid("chat event text/content is required".into()));
    }
    let direction = first(e, &["direction"], "inbound").to_lowercase();
    let direction = if ["inbound", "outbound", "draft"].contains(&direction.as_str()) {
        direction.as_str()
    } else {
        "inbound"
    };
    let kind = first(e, &["chat_type"], "").to_lowercase();
    let kind = if ["group", "private"].contains(&kind.as_str()) {
        kind.as_str()
    } else {
        ""
    };
    let unread_flag = direction == "inbound" && e.get("unread").map(truth).unwrap_or(true);
    let created = first(e, &["timestamp", "created_at"], &text(&now(c)?));
    if !external.is_empty() {
        let duplicate=scalar(c,"SELECT id FROM external_chat_messages WHERE platform=? AND thread_id=? AND external_message_id=? LIMIT 1",&[json!(platform),json!(id),json!(external)])?;
        if !duplicate.is_null() {
            return Ok(
                json!({"duplicate":true,"message_id":duplicate,"thread":thread(c,&platform,&id)?,"unread":unread(c,&json!({}))?}),
            );
        }
    }
    exec(c,"INSERT INTO external_chat_messages(platform,thread_id,external_message_id,sender_id,sender_name,direction,content,unread,chat_type,raw_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",&[json!(platform),json!(id),json!(external),json!(sender),json!(sender_name),json!(direction),json!(content),json!(unread_flag),json!(kind),a.get("raw_json").cloned().unwrap_or_else(||json!(json_text(e))),json!(created)])?;
    let mid = c.last_insert_rowid();
    exec(c,"INSERT INTO external_chat_threads(platform,thread_id,thread_name,chat_type,unread_count,last_message_id,last_message_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(platform,thread_id) DO UPDATE SET thread_name=CASE WHEN excluded.thread_name!='' THEN excluded.thread_name ELSE external_chat_threads.thread_name END,chat_type=CASE WHEN excluded.chat_type!='' THEN excluded.chat_type ELSE external_chat_threads.chat_type END,unread_count=external_chat_threads.unread_count+?,last_message_id=excluded.last_message_id,last_message_at=excluded.last_message_at,updated_at=excluded.updated_at",&[json!(platform),json!(id),json!(name),json!(kind),json!(unread_flag),json!(mid),json!(created),now(c)?,json!(unread_flag)])?;
    let pruned = if kind == "group" {
        prune(c, &json!(platform), &json!(id))?
    } else {
        0
    };
    if pruned > 0 {
        resync(c)?;
    }
    Ok(
        json!({"duplicate":false,"message_id":mid,"pruned_messages":pruned,"thread":thread(c,&platform,&id)?,"unread":unread(c,&json!({}))?}),
    )
}
fn context(c: &Connection, a: &Value) -> Result<Value> {
    let scoped = ["platform", "thread_id", "chat_type"]
        .iter()
        .any(|k| !a[*k].is_null());
    let platform = clean(&a["platform"]);
    let id = clean(&a["thread_id"]);
    let kind = clean(&a["chat_type"]).to_lowercase();
    if scoped
        && (platform.is_empty() || id.is_empty() || !["group", "private"].contains(&kind.as_str()))
    {
        return Ok(json!(""));
    }
    let mut p = if scoped {
        vec![json!(platform), json!(id), json!(kind)]
    } else {
        vec![]
    };
    p.push(json!(clamp(&a["limit_threads"], 1, 12, 4)));
    let filter = if scoped {
        " WHERE platform=? AND thread_id=? AND chat_type=?"
    } else {
        ""
    };
    let rows=query(c,&format!("SELECT {THREAD} FROM external_chat_threads{filter} ORDER BY last_message_at DESC,updated_at DESC LIMIT ?"),&p)?;
    if rows.is_empty() {
        return Ok(json!(""));
    }
    let mut lines=vec!["【外部聊天软件上下文】".to_owned(),"以下是 BandoriPet 最近从外部聊天软件收到的消息。可以用于理解用户当前可能在处理的对话；除非用户要求代写或总结，不要主动暴露隐私细节。".into()];
    for t in rows.into_iter().map(thread_row) {
        lines.push(format!(
            "[{} / {} / 未读 {}]",
            text(&t["platform"]),
            text(&t["thread_name"]),
            int(&t, "unread_count")
        ));
        let mut p = vec![t["platform"].clone(), t["thread_id"].clone()];
        if scoped {
            p.push(json!(kind));
        }
        p.push(json!(clamp(&a["limit_messages"], 1, 20, 6)));
        let filter = if scoped { " AND chat_type=?" } else { "" };
        let rows=query(c,&format!("SELECT {MESSAGE} FROM external_chat_messages WHERE platform=? AND thread_id=?{filter} ORDER BY id DESC LIMIT ?"),&p)?;
        for m in rows.into_iter().rev().map(row) {
            let sender = first(&m, &["sender_name", "sender_id"], "unknown");
            let content = string(&m, "content")
                .replace(['\r', '\n'], " ")
                .trim()
                .to_owned();
            let content = if content.chars().count() > 500 {
                format!("{}...", short(&content, 500))
            } else {
                content
            };
            lines.push(format!(
                "- {} {}（{}）：{}",
                text(&m["created_at"]),
                sender,
                if truth(&m["unread"]) {
                    "未读"
                } else {
                    "已读"
                },
                content
            ));
        }
    }
    Ok(json!(lines.join("\n")))
}
pub fn call(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    match op {
        "add_external_chat_message" => add(c, a),
        "get_external_chat_unread_summary" => unread(c, a),
        "external_chat_context_text" => context(c, a),
        "mark_external_chat_read" => {
            let platform = clean(&a["platform"]);
            let id = clean(&a["thread_id"]);
            let p = vec![json!(platform), json!(platform), json!(id), json!(id)];
            let n=exec(c,"UPDATE external_chat_messages SET unread=0 WHERE unread=1 AND (?='' OR platform=?) AND (?='' OR thread_id=?)",&p)?;
            let mut p = p;
            p.insert(0, now(c)?);
            exec(c,"UPDATE external_chat_threads SET unread_count=0,updated_at=? WHERE (?='' OR platform=?) AND (?='' OR thread_id=?)",&p)?;
            Ok(json!({"marked_read":n,"unread":unread(c,&json!({}))?}))
        }
        "prune_external_group_chat_limit" => {
            let mut n = 0;
            for t in query(c,"SELECT platform,thread_id FROM external_chat_threads WHERE chat_type='group' UNION SELECT platform,thread_id FROM external_chat_messages WHERE chat_type='group'",&[])?{n+=prune(c,&t["platform"],&t["thread_id"])?;}
            if n > 0 {
                resync(c)?;
            }
            Ok(json!({"deleted_messages":n}))
        }
        "delete_external_chat" | "purge_external_chat_older_than" => {
            let kind = clean(&a["chat_type"]);
            let platform = clean(&a["platform"]);
            let p = vec![json!(kind), json!(kind), json!(platform), json!(platform)];
            let (q, parameters) = if op == "delete_external_chat" {
                ("DELETE FROM external_chat_messages WHERE (?='' OR chat_type=?) AND (?='' OR platform=?)",p.clone())
            } else {
                let mut p = p.clone();
                p.insert(0, json!(format!("-{} days", clamp(&a["days"], 1, 3650, 7))));
                ("DELETE FROM external_chat_messages WHERE created_at<datetime('now','localtime',?) AND (?='' OR chat_type=?) AND (?='' OR platform=?)",p)
            };
            let n = exec(c, q, &parameters)?;
            let threads = if op == "delete_external_chat" {
                exec(c,"DELETE FROM external_chat_threads WHERE (?='' OR chat_type=?) AND (?='' OR platform=?)",&p)?
            } else {
                0
            };
            if n > 0 {
                resync(c)?;
            }
            if op == "delete_external_chat" {
                Ok(
                    json!({"deleted_messages":n,"deleted_threads":threads,"unread":unread(c,&json!({}))?}),
                )
            } else {
                Ok(json!({"deleted_messages":n}))
            }
        }
        _ => Err(Error::Invalid(format!("unknown external operation: {op}"))),
    }
}
