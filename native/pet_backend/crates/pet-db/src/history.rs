//! High-volume history uses owned typed rows, avoiding intermediate JSON maps.
use crate::{chat, value::*, Database, Result};
use rusqlite::{params_from_iter, types::ValueRef, Connection};
use serde_json::{json, Value};

pub enum ConversationId {
    Private(i64),
    Group(String),
}
pub struct Message {
    pub id: i64,
    pub conversation_id: ConversationId,
    pub group_key: Option<String>,
    pub role: String,
    pub content: String,
    pub reasoning_content: String,
    pub attachments_json: String,
    pub tool_trace_json: String,
    pub created_at: String,
}
impl Message {
    pub fn into_json(self) -> Value {
        let mut r = json!({"id":self.id,"conversation_id":match self.conversation_id{ConversationId::Private(i)=>json!(i),ConversationId::Group(s)=>json!(s)},"role":self.role,"content":self.content,"reasoning_content":self.reasoning_content,"attachments_json":self.attachments_json,"tool_trace_json":self.tool_trace_json,"created_at":self.created_at});
        if let Some(group) = self.group_key {
            r["group_key"] = json!(group);
        }
        r
    }
}
fn row_text(v: ValueRef<'_>) -> String {
    match v {
        ValueRef::Null => String::new(),
        ValueRef::Text(v) | ValueRef::Blob(v) => String::from_utf8_lossy(v).into_owned(),
        _ => text(&cell(v)),
    }
}
pub fn query(c: &Connection, a: &Value, grouped: bool) -> Result<Vec<Message>> {
    let (table, columns, mut clause, mut p) = if grouped {
        let conv = chat::conversation(a);
        (
            "group_messages",
            chat::GROUP,
            "group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)".to_owned(),
            vec![a["group_key"].clone(), json!(conv), json!(conv)],
        )
    } else {
        (
            "messages",
            chat::MESSAGE,
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
    let params = p.iter().map(sql).collect::<Result<Vec<_>>>()?;
    let mut stmt = c.prepare_cached(&format!(
        "SELECT {columns} FROM {table} WHERE {clause} ORDER BY id {order}"
    ))?;
    let mut cursor = stmt.query(params_from_iter(params))?;
    let mut out = vec![];
    while let Some(row) = cursor.next()? {
        let offset = usize::from(grouped);
        let role = row_text(row.get_ref(2 + offset)?).trim().to_owned();
        if !["user", "assistant", "system"].contains(&role.as_str()) {
            continue;
        }
        let Some(id) = integer(&cell(row.get_ref(0)?)) else {
            continue;
        };
        let conversation_id = if grouped {
            let s = row_text(row.get_ref(2)?);
            ConversationId::Group(if s.is_empty() { "default".into() } else { s })
        } else {
            let Some(i) = integer(&cell(row.get_ref(1)?)) else {
                continue;
            };
            ConversationId::Private(i)
        };
        out.push(Message {
            id,
            conversation_id,
            group_key: if grouped {
                Some(row_text(row.get_ref(1)?))
            } else {
                None
            },
            role,
            content: row_text(row.get_ref(3 + offset)?),
            reasoning_content: row_text(row.get_ref(4 + offset)?),
            attachments_json: row_text(row.get_ref(5 + offset)?),
            tool_trace_json: row_text(row.get_ref(6 + offset)?),
            created_at: row_text(row.get_ref(7 + offset)?),
        });
    }
    if limited {
        out.reverse();
    }
    Ok(out)
}
impl Database {
    pub fn history(&self, a: &Value, grouped: bool) -> Result<Vec<Message>> {
        self.with_connection(|c| Self::transaction(c, false, |c| query(c, a, grouped)))
    }
}
