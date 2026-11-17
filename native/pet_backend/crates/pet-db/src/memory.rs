use crate::{value::*, Error, Result};
use rusqlite::Connection;
use serde_json::{json, Value};

pub const STATE: &str =
    "id,character,user_key,affection,trust,familiarity,mood,mood_intensity,summary,updated_at";
pub const MEMORY: &str = "id,character,user_key,kind,content,importance,source_message_id,source_group_message_id,created_at,updated_at";

pub fn state_row(mut r: Value) -> Value {
    normalize_strings(
        &mut r,
        &["character", "user_key", "mood", "summary", "updated_at"],
    );
    if r["mood"] == "" {
        r["mood"] = json!("calm");
    }
    for (key, default) in [
        ("id", 0),
        ("affection", 50),
        ("trust", 50),
        ("familiarity", 0),
        ("mood_intensity", 20),
    ] {
        r[key] = json!(integer(&r[key]).unwrap_or(default));
    }
    r
}
pub fn memory_row(mut r: Value) -> Value {
    normalize_strings(
        &mut r,
        &[
            "character",
            "user_key",
            "kind",
            "content",
            "created_at",
            "updated_at",
        ],
    );
    if r["kind"] == "" {
        r["kind"] = json!("note");
    }
    for key in ["id", "importance"] {
        r[key] = json!(int(&r, key));
    }
    for key in ["source_message_id", "source_group_message_id"] {
        r[key] = json!(integer(&r[key]));
    }
    r
}
pub fn state(c: &Connection, a: &Value) -> Result<Value> {
    let row = one(
        c,
        &format!("SELECT {STATE} FROM relationship_states WHERE character=? AND user_key=?"),
        &[a["character"].clone(), json!(user(a))],
    )?;
    if row.is_null() {
        Ok(
            json!({"id":0,"character":a["character"],"user_key":user(a),"affection":50,"trust":50,"familiarity":0,"mood":"calm","mood_intensity":20,"summary":"","updated_at":""}),
        )
    } else {
        Ok(state_row(row))
    }
}
fn write_state(c: &Connection, a: &Value, s: &Value) -> Result<()> {
    exec(c,"INSERT INTO relationship_states(character,user_key,affection,trust,familiarity,mood,mood_intensity,summary,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(character,user_key) DO UPDATE SET affection=excluded.affection,trust=excluded.trust,familiarity=excluded.familiarity,mood=excluded.mood,mood_intensity=excluded.mood_intensity,summary=excluded.summary,updated_at=excluded.updated_at",&[a["character"].clone(),json!(user(a)),s["affection"].clone(),s["trust"].clone(),s["familiarity"].clone(),s["mood"].clone(),s["mood_intensity"].clone(),s["summary"].clone(),s["updated_at"].clone()])?;
    Ok(())
}
pub fn change_state(c: &Connection, a: &Value, delta: bool) -> Result<Value> {
    let current = state(c, a)?;
    let mut next = current.clone();
    for (key, default) in [("affection", 50), ("trust", 50), ("familiarity", 0)] {
        let n = if delta {
            int(&current, key).saturating_add(int(a, &format!("{key}_delta")))
        } else {
            integer(&a[key]).unwrap_or(int(&current, key))
        };
        next[key] = json!(clamp(&json!(n), 0, 100, default));
    }
    let mood = if a["mood"].is_null() || (delta && !truth(&a["mood"])) {
        string(&current, "mood")
    } else {
        string(a, "mood")
    };
    next["mood"] = json!(if mood.is_empty() { "calm" } else { &mood });
    let intensity = if !a["mood_intensity"].is_null() {
        a["mood_intensity"].clone()
    } else if delta {
        json!(if truth(&a["mood"]) {
            (int(&current, "mood_intensity") + 8).clamp(25, 85)
        } else {
            (int(&current, "mood_intensity") - 3).max(10)
        })
    } else {
        current["mood_intensity"].clone()
    };
    next["mood_intensity"] = json!(clamp(&intensity, 0, 100, 20));
    if !delta && !a["summary"].is_null() {
        next["summary"] = json!(string(a, "summary"));
    }
    next["updated_at"] = now(c)?;
    write_state(c, a, &next)?;
    let numeric = ["affection", "trust", "familiarity"]
        .iter()
        .any(|k| !a[*k].is_null() && next[*k] != current[*k]);
    let mood_changed = ["mood", "mood_intensity"]
        .iter()
        .any(|k| !a[*k].is_null() && next[*k] != current[*k]);
    if delta || numeric || mood_changed {
        let changes: Vec<_> = ["affection", "trust", "familiarity"]
            .iter()
            .map(|k| {
                if delta {
                    clamp(&a[format!("{k}_delta")], -100, 100, 0)
                } else {
                    int(&next, k) - int(&current, k)
                }
            })
            .map(|n| json!(n))
            .collect();
        let mut p = vec![
            a["character"].clone(),
            json!(user(a)),
            json!(if delta {
                let t = string(a, "event_type");
                if t.is_empty() {
                    "interaction".into()
                } else {
                    t
                }
            } else {
                "manual_set".into()
            }),
        ];
        p.extend(changes);
        p.extend([
            next["affection"].clone(),
            next["trust"].clone(),
            next["familiarity"].clone(),
            json!(if delta {
                string(a, "mood")
            } else if mood_changed {
                string(&next, "mood")
            } else {
                String::new()
            }),
            if delta || mood_changed {
                next["mood_intensity"].clone()
            } else {
                json!(0)
            },
            json!(if delta {
                short(&string(a, "reason"), 500)
            } else {
                "manual relationship state update".into()
            }),
            next["updated_at"].clone(),
        ]);
        exec(c,"INSERT INTO mood_events(character,user_key,event_type,affection_delta,trust_delta,familiarity_delta,affection,trust,familiarity,mood,mood_intensity,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",&p)?;
    }
    state(c, a)
}

pub fn add(c: &Connection, a: &Value, imported: bool) -> Result<Value> {
    let content = trim(a, "content");
    if content.is_empty() {
        return Ok(json!(0));
    }
    let kind = trim(a, "kind");
    let kind = if kind.is_empty() { "note" } else { &kind };
    let created = if imported && truth(&a["created_at"]) {
        a["created_at"].clone()
    } else {
        now(c)?
    };
    let updated = if imported && truth(&a["updated_at"]) {
        a["updated_at"].clone()
    } else {
        created.clone()
    };
    let importance = if imported {
        "excluded.importance"
    } else {
        "max(character_memories.importance,excluded.importance)"
    };
    exec(c,&format!("INSERT INTO character_memories(character,user_key,kind,content,importance,source_message_id,source_group_message_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(character,user_key,content) DO UPDATE SET kind=excluded.kind,importance={importance},source_message_id=coalesce(excluded.source_message_id,character_memories.source_message_id),source_group_message_id=coalesce(excluded.source_group_message_id,character_memories.source_group_message_id),updated_at=excluded.updated_at"),&[a["character"].clone(),json!(user(a)),json!(kind),json!(content),json!(clamp(&a["importance"],1,100,50)),json!(integer(&a["source_message_id"])),json!(integer(&a["source_group_message_id"])),created,updated])?;
    scalar(
        c,
        "SELECT id FROM character_memories WHERE character=? AND user_key=? AND content=?",
        &[a["character"].clone(), json!(user(a)), json!(content)],
    )
}
pub fn memories(c: &Connection, a: &Value, by_kind: bool) -> Result<Value> {
    let kind = trim(a, "kind");
    let use_kind = by_kind && !kind.is_empty();
    let limit = if by_kind && !kind.is_empty() {
        clamp(&a["limit"], 1, 200, 50)
    } else {
        clamp(&a["limit"], 1, 100, 8)
    };
    let mut p = vec![a["character"].clone(), json!(user(a))];
    let filter = if use_kind {
        p.push(json!(kind));
        " AND kind=?"
    } else {
        ""
    };
    p.push(json!(limit));
    let order = if use_kind {
        "updated_at DESC,id DESC"
    } else {
        "importance DESC,updated_at DESC,id DESC"
    };
    Ok(json!(query(c,&format!("SELECT {MEMORY} FROM character_memories WHERE character=? AND user_key=?{filter} ORDER BY {order} LIMIT ?"),&p)?.into_iter().map(memory_row).collect::<Vec<_>>()))
}

pub fn call(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    match op {
        "get_relationship_state" => state(c, a),
        "upsert_relationship_state" | "apply_relationship_delta" => {
            change_state(c, a, op == "apply_relationship_delta")
        }
        "add_character_memory" => add(c, a, false),
        "get_character_memories" | "get_character_memories_by_kind" => {
            memories(c, a, op.ends_with("by_kind"))
        }
        "update_character_memory" => {
            if !truth(&a["memory_id"]) || trim(a, "content").is_empty() {
                return Ok(json!(false));
            }
            let kind = trim(a, "kind");
            let kind = if kind.is_empty() { "note" } else { &kind };
            Ok(json!(exec(c,"UPDATE character_memories SET kind=?,content=?,importance=?,updated_at=? WHERE id=? AND character=? AND user_key=?",&[json!(kind),json!(trim(a,"content")),json!(clamp(&a["importance"],1,100,50)),now(c)?,a["memory_id"].clone(),a["character"].clone(),json!(user(a))])?>0))
        }
        "delete_character_memories_like" => {
            let q = trim(a, "query");
            if q.is_empty() {
                return Ok(json!(0));
            }
            Ok(json!(exec(c,"DELETE FROM character_memories WHERE character=? AND user_key=? AND content LIKE ? ESCAPE '\\'",&[a["character"].clone(),json!(user(a)),json!(like(&q))])?))
        }
        "delete_character_memory" | "delete_character_memories" => {
            let mut ids = if op == "delete_character_memory" {
                vec![int(a, "memory_id")]
            } else {
                a["memory_ids"]
                    .as_array()
                    .map(|v| v.iter().filter_map(integer).filter(|n| *n > 0).collect())
                    .unwrap_or_default()
            };
            ids.sort_unstable();
            ids.dedup();
            let mut n = 0;
            // Fixed-size parameters avoid SQLite variable-count limits on bulk delete.
            for id in ids {
                let mut clause = String::from("id=?");
                let mut p = vec![json!(id)];
                if truth(&a["character"]) {
                    clause.push_str(" AND character=?");
                    p.push(a["character"].clone());
                }
                if truth(&a["user_key"]) {
                    scope(a, "user_key", &mut clause, &mut p);
                }
                n += exec(
                    c,
                    &format!("DELETE FROM character_memories WHERE {clause}"),
                    &p,
                )?;
            }
            if op == "delete_character_memory" {
                Ok(json!(n > 0))
            } else {
                Ok(json!(n))
            }
        }
        "export_relationship_data" => Ok(
            json!({"relationship_states":query(c,&format!("SELECT {STATE} FROM relationship_states ORDER BY character,user_key"),&[])?.into_iter().map(state_row).collect::<Vec<_>>(),"character_memories":query(c,&format!("SELECT {MEMORY} FROM character_memories ORDER BY character,user_key,importance DESC,updated_at DESC,id DESC"),&[])?.into_iter().map(memory_row).collect::<Vec<_>>()}),
        ),
        "import_relationship_data" => {
            let data = &a["data"];
            if !data.is_object() {
                return Err(Error::Invalid(
                    "relationship data must be a JSON object".into(),
                ));
            }
            let mut states = 0;
            let mut count = 0;
            if let Some(items) = data["relationship_states"].as_array() {
                for item in items
                    .iter()
                    .filter(|v| v.is_object() && !trim(v, "character").is_empty())
                {
                    let mut a = item.clone();
                    a["character"] = json!(trim(item, "character"));
                    let mut s = json!({});
                    for (k, d) in [
                        ("affection", 50),
                        ("trust", 50),
                        ("familiarity", 0),
                        ("mood_intensity", 20),
                    ] {
                        s[k] = json!(clamp(&item[k], 0, 100, d));
                    }
                    let mood = trim(item, "mood");
                    s["mood"] = json!(if mood.is_empty() { "calm" } else { &mood });
                    s["summary"] = json!(string(item, "summary"));
                    s["updated_at"] = if truth(&item["updated_at"]) {
                        item["updated_at"].clone()
                    } else {
                        now(c)?
                    };
                    write_state(c, &a, &s)?;
                    states += 1;
                }
            }
            if let Some(items) = data["character_memories"].as_array() {
                for item in items.iter().filter(|v| {
                    v.is_object()
                        && !trim(v, "character").is_empty()
                        && !trim(v, "content").is_empty()
                }) {
                    let mut a = item.clone();
                    a["character"] = json!(trim(item, "character"));
                    add(c, &a, true)?;
                    count += 1;
                }
            }
            Ok(json!({"relationship_states":states,"character_memories":count}))
        }
        _ => Err(Error::Invalid(format!("unknown memory operation: {op}"))),
    }
}
