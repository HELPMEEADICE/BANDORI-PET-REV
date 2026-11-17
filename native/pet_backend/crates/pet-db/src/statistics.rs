use crate::{memory, search, value::*, Error, Result};
use rusqlite::Connection;
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn usage(c: &Connection, period: &str) -> Result<Value> {
    let filter = match period {
        "today" => "date(start_time)=date('now','localtime')",
        "week" => "start_time>=datetime('now','localtime','-6 days','start of day')",
        _ => "1",
    };
    let total = integer(&scalar(
        c,
        &format!("SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions WHERE {filter}"),
        &[],
    )?)
    .unwrap_or(0);
    let live=one(c,&format!("SELECT COALESCE(duration_seconds,0) AS stored,CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) AS live FROM usage_sessions WHERE end_time IS NULL AND {filter} ORDER BY id DESC LIMIT 1"),&[])?;
    Ok(json!(if live.is_null() {
        total
    } else {
        total - int(&live, "stored") + int(&live, "live")
    }))
}
fn chart(c: &Connection, a: &Value) -> Result<Value> {
    let mut p = vec![a["character"].clone(), json!(user(a))];
    let filter = if int(a, "days") > 0 {
        p.push(json!(format!("-{} days", int(a, "days"))));
        " AND created_at>=datetime('now','localtime',?)"
    } else {
        ""
    };
    let rows=query(c,&format!("SELECT created_at,affection_delta,trust_delta,familiarity_delta,affection,trust,familiarity FROM mood_events WHERE character=? AND user_key=?{filter} ORDER BY created_at ASC,id ASC"),&p)?;
    let state = memory::state(c, a)?;
    let snapshot = |r: &Value| {
        ["affection", "trust", "familiarity"]
            .iter()
            .all(|k| integer(&r[*k]).is_some())
    };
    let point = |day: Value, s: &Value| json!({"day":day,"affection":s["affection"],"trust":s["trust"],"familiarity":s["familiarity"]});
    if rows.is_empty() {
        return Ok(json!([point(
            scalar(c, "SELECT date('now','localtime')", &[])?,
            &state
        )]));
    }
    let Some(start) = rows.iter().position(snapshot) else {
        let day = if truth(&state["updated_at"]) {
            state["updated_at"].clone()
        } else {
            scalar(c, "SELECT date('now','localtime')", &[])?
        };
        return Ok(json!([point(day, &state)]));
    };
    let mut running = json!({"affection":0,"trust":0,"familiarity":0});
    let mut result = vec![];
    for row in &rows[start..] {
        let has = snapshot(row);
        for k in ["affection", "trust", "familiarity"] {
            running[k] = json!(if has {
                int(row, k)
            } else {
                int(&running, k) + int(row, &format!("{k}_delta"))
            }
            .clamp(0, 100));
        }
        result.push(point(row["created_at"].clone(), &running));
    }
    if let Some(last) = result.last() {
        let updated = string(&state, "updated_at");
        if !updated.is_empty()
            && updated >= text(&last["day"])
            && (updated != text(&last["day"])
                || ["affection", "trust", "familiarity"]
                    .iter()
                    .any(|k| last[*k] != state[*k]))
        {
            result.push(point(json!(updated), &state));
        }
    }
    Ok(json!(result))
}
fn daily(c: &Connection, a: &Value, heatmap: bool) -> Result<Value> {
    let modifier = json!(format!("-{} days", int(a, "days")));
    let mut counts = BTreeMap::<String, i64>::new();
    let mut grid = vec![vec![0_i64; 24]; 7];
    for grouped in [false, true] {
        let (mut clause, mut p) = if grouped {
            (
                "created_at>=datetime('now','localtime',?)".into(),
                vec![modifier.clone()],
            )
        } else {
            (
                "m.created_at>=datetime('now','localtime',?)".into(),
                vec![modifier.clone()],
            )
        };
        scope(
            a,
            if grouped { "user_key" } else { "c.user_key" },
            &mut clause,
            &mut p,
        );
        let (table, col) = if grouped {
            ("group_messages", "created_at")
        } else {
            (
                "messages m JOIN conversations c ON c.id=m.conversation_id",
                "m.created_at",
            )
        };
        let q = if heatmap {
            format!("SELECT CAST(strftime('%w',{col}) AS INTEGER) AS wday,CAST(strftime('%H',{col}) AS INTEGER) AS hour,COUNT(*) AS count FROM {table} WHERE {clause} GROUP BY wday,hour")
        } else {
            format!("SELECT date({col}) AS day,COUNT(*) AS count FROM {table} WHERE {clause} GROUP BY day")
        };
        for r in query(c, &q, &p)? {
            if heatmap {
                if let (Some(day), Some(hour)) = (integer(&r["wday"]), integer(&r["hour"])) {
                    if (0..7).contains(&day) && (0..24).contains(&hour) {
                        grid[((day + 6) % 7) as usize][hour as usize] += int(&r, "count");
                    }
                }
            } else {
                let day = string(&r, "day");
                if !day.is_empty() {
                    *counts.entry(day).or_default() += int(&r, "count");
                }
            }
        }
    }
    if heatmap {
        Ok(json!(grid))
    } else {
        Ok(json!(counts
            .into_iter()
            .map(|(day, count)| json!({"day":day,"count":count}))
            .collect::<Vec<_>>()))
    }
}
fn character_counts(c: &Connection, a: &Value) -> Result<Value> {
    let mut p = vec![json!(user(a))];
    let filter = if int(a, "days") > 0 {
        p.push(json!(format!("-{} days", int(a, "days"))));
        " AND m.created_at>=datetime('now','localtime',?)"
    } else {
        ""
    };
    let mut counts = Vec::<(String, i64)>::new();
    for r in query(c,&format!("SELECT c.character,COUNT(m.id) AS count FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.user_key=? AND c.character!='' AND c.character!='__group__'{filter} GROUP BY c.character ORDER BY count DESC"),&p)?{counts.push((string(&r,"character"),int(&r,"count")));}
    let aliases =
        std::fs::read_to_string(std::path::Path::new(&string(a, "asset_dir")).join("outfit.json"))
            .ok()
            .map(|s| parse_json(&s))
            .unwrap_or(Value::Null);
    let filter = filter.replace("m.created_at", "created_at");
    visit(c,&format!("SELECT group_key,role,content FROM group_messages WHERE user_key=? AND group_key LIKE '__group__:%'{filter}"),&p,|row|{
        let members=search::members(&string(&row,"group_key"));let speaker=search::speaker(&string(&row,"content"));
        let matched:Vec<_>=if row["role"]=="assistant" && !speaker.is_empty(){members.iter().filter(|m|**m==speaker || aliases["characters"][*m]["display"].as_str().is_some_and(|s|s.trim()==speaker)).cloned().collect()}else{vec![]};
        for ch in if matched.is_empty(){members}else{matched}{if let Some((_,n))=counts.iter_mut().find(|(k,_)|*k==ch){*n+=1;}else{counts.push((ch,1));}}
        Ok(())
    })?;
    counts.sort_by_key(|a| std::cmp::Reverse(a.1));
    Ok(json!(counts
        .into_iter()
        .map(|(character, count)| json!({"character":character,"count":count}))
        .collect::<Vec<_>>()))
}
pub fn call(c: &Connection, op: &str, a: &Value) -> Result<Value> {
    match op {
        "start_usage_session" => {
            exec(
                c,
                "INSERT INTO usage_sessions(start_time) VALUES(datetime('now','localtime'))",
                &[],
            )?;
            Ok(json!(c.last_insert_rowid()))
        }
        "end_usage_session" => {
            exec(c,"UPDATE usage_sessions SET end_time=datetime('now','localtime'),duration_seconds=CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) WHERE id=? AND end_time IS NULL",&[a["session_id"].clone()])?;
            Ok(Value::Null)
        }
        "heartbeat_usage_session" => {
            exec(c,"UPDATE usage_sessions SET duration_seconds=CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) WHERE id=? AND end_time IS NULL",&[a["session_id"].clone()])?;
            Ok(Value::Null)
        }
        "get_usage_today" => usage(c, "today"),
        "get_usage_week" => usage(c, "week"),
        "get_usage_all_time" => usage(c, "all"),
        "get_usage_daily" => {
            let mut rows=query(c,"SELECT date(start_time) AS day,COALESCE(SUM(duration_seconds),0) AS seconds FROM usage_sessions WHERE start_time>=datetime('now','localtime',?,'start of day') GROUP BY date(start_time) ORDER BY day ASC",&[json!(format!("-{} days",int(a,"days")))])?;
            for r in &mut rows {
                r["seconds"] = json!(int(r, "seconds"));
            }
            Ok(json!(rows))
        }
        "get_chat_summary" => Ok(
            json!({"total_conversations":scalar(c,"SELECT COUNT(*) FROM conversations",&[])?,"total_messages":scalar(c,"SELECT COUNT(*) FROM messages",&[])?,"total_group_messages":scalar(c,"SELECT COUNT(*) FROM group_messages",&[]) ?}),
        ),
        "get_mood_events_for_chart" => chart(c, a),
        "get_daily_message_counts" => daily(c, a, false),
        "get_hourly_heatmap" => daily(c, a, true),
        "get_messages_per_character_range" => character_counts(c, a),
        _ => Err(Error::Invalid(format!(
            "unknown statistics operation: {op}"
        ))),
    }
}
