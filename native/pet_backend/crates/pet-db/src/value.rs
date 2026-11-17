//! Row conversion stays on the Rust side. No Python objects enter this crate.
use crate::{Error, Result};
use rusqlite::{params_from_iter, types::Value as SqlValue, Connection};
use serde_json::{json, Map, Value};

pub fn text(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        Value::Bool(b) => if *b { "True" } else { "False" }.into(),
        _ => v.to_string(),
    }
}
pub fn string(a: &Value, key: &str) -> String {
    text(&a[key])
}
pub fn integer(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(i64::from(*b)),
        Value::Number(n) => n.as_i64().or_else(|| {
            n.as_f64()
                .filter(|f| f.is_finite() && *f >= i64::MIN as f64 && *f < i64::MAX as f64)
                .map(|f| f as i64)
        }),
        Value::String(s) => s.trim().parse().ok(),
        _ => None,
    }
}
pub fn int(a: &Value, key: &str) -> i64 {
    integer(&a[key]).unwrap_or(0)
}
pub fn clamp(v: &Value, low: i64, high: i64, default: i64) -> i64 {
    let n = match v {
        Value::Bool(b) => Some(f64::from(u8::from(*b))),
        Value::Number(n) => n.as_f64(),
        Value::String(s) => s.trim().parse::<f64>().ok(),
        _ => None,
    };
    n.filter(|n| n.is_finite())
        .map(|n| n.round_ties_even().clamp(low as f64, high as f64) as i64)
        .unwrap_or(default)
        .clamp(low, high)
}
pub fn truth(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(v) => *v,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(v) => !v.is_empty(),
        Value::Object(v) => !v.is_empty(),
    }
}
pub fn user(a: &Value) -> String {
    user_value(&a["user_key"])
}
pub fn user_value(v: &Value) -> String {
    if !truth(v) {
        return "__default__".into();
    }
    let s = text(v).trim().to_owned();
    if s.is_empty() {
        "__default__".into()
    } else {
        s
    }
}
pub fn trim(a: &Value, key: &str) -> String {
    string(a, key).trim().into()
}
pub fn short(s: &str, max: usize) -> String {
    s.chars().take(max).collect()
}
pub fn like(s: &str) -> String {
    format!(
        "%{}%",
        s.replace('\\', "\\\\")
            .replace('%', "\\%")
            .replace('_', "\\_")
    )
}
pub fn json_text(v: &Value) -> String {
    if !truth(v) {
        String::new()
    } else if let Some(s) = v.as_str() {
        s.into()
    } else {
        v.to_string()
    }
}
pub fn sql(v: &Value) -> Result<SqlValue> {
    Ok(match v {
        Value::Null => SqlValue::Null,
        Value::Bool(v) => SqlValue::Integer(i64::from(*v)),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                SqlValue::Integer(i)
            } else if n.as_u64().is_some() {
                return Err(Error::Invalid(
                    "integer exceeds SQLite INTEGER range".into(),
                ));
            } else {
                SqlValue::Real(
                    n.as_f64()
                        .ok_or_else(|| Error::Invalid("invalid number".into()))?,
                )
            }
        }
        Value::String(s) => SqlValue::Text(s.clone()),
        _ => return Err(Error::Invalid("unsupported SQL parameter".into())),
    })
}
pub fn cell(v: rusqlite::types::ValueRef<'_>) -> Value {
    use rusqlite::types::ValueRef;
    match v {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(i) => json!(i),
        ValueRef::Real(f) => json!(f),
        ValueRef::Text(t) | ValueRef::Blob(t) => json!(String::from_utf8_lossy(t)),
    }
}
pub fn query(c: &Connection, query: &str, params: &[Value]) -> Result<Vec<Value>> {
    let mut out = Vec::new();
    visit(c, query, params, |row| {
        out.push(row);
        Ok(())
    })?;
    Ok(out)
}
/// Stream analytical scans without materializing the database in memory.
pub fn visit(
    c: &Connection,
    query: &str,
    params: &[Value],
    mut visitor: impl FnMut(Value) -> Result<()>,
) -> Result<()> {
    let values = params.iter().map(sql).collect::<Result<Vec<_>>>()?;
    let mut stmt = c.prepare_cached(query)?;
    let names: Vec<String> = stmt.column_names().map(String::from).collect();
    let mut cursor = stmt.query(params_from_iter(values))?;
    while let Some(row) = cursor.next()? {
        let mut value = Map::new();
        for (i, name) in names.iter().enumerate() {
            value.insert(name.clone(), cell(row.get_ref(i)?));
        }
        visitor(Value::Object(value))?;
    }
    Ok(())
}
pub fn one(c: &Connection, q: &str, p: &[Value]) -> Result<Value> {
    Ok(query(c, q, p)?.into_iter().next().unwrap_or(Value::Null))
}
pub fn scalar(c: &Connection, q: &str, p: &[Value]) -> Result<Value> {
    Ok(one(c, q, p)?
        .as_object()
        .and_then(|o| o.values().next())
        .cloned()
        .unwrap_or(Value::Null))
}
pub fn exec(c: &Connection, q: &str, p: &[Value]) -> Result<usize> {
    let values = p.iter().map(sql).collect::<Result<Vec<_>>>()?;
    Ok(c.prepare_cached(q)?.execute(params_from_iter(values))?)
}
pub fn now(c: &Connection) -> Result<Value> {
    scalar(c, "SELECT datetime('now','localtime')", &[])
}
pub fn scope(a: &Value, column: &str, clause: &mut String, params: &mut Vec<Value>) {
    if !a["user_key"].is_null() {
        clause.push_str(&format!(" AND {column}=?"));
        params.push(json!(user(a)));
    }
}
pub fn fields(v: &Value, keys: &[&str]) -> Value {
    let mut out = Map::new();
    for key in keys {
        out.insert((*key).into(), v[*key].clone());
    }
    Value::Object(out)
}

/// Python's json.dumps historically allowed non-finite numeric constants. Treat
/// those constants as absent numeric data, without altering quoted text.
pub fn parse_json(input: &str) -> Value {
    if let Ok(v) = serde_json::from_str(input) {
        return v;
    }
    let mut out = String::with_capacity(input.len());
    let mut inside = false;
    let mut escaped = false;
    let mut i = 0;
    while i < input.len() {
        let tail = &input[i..];
        let Some(ch) = tail.chars().next() else {
            break;
        };
        if inside {
            out.push(ch);
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                inside = false;
            }
            i += ch.len_utf8();
            continue;
        }
        if ch == '"' {
            inside = true;
            out.push(ch);
            i += 1;
            continue;
        }
        if let Some(token) = ["-Infinity", "Infinity", "NaN"]
            .into_iter()
            .find(|t| tail.starts_with(t))
        {
            out.push_str("null");
            i += token.len();
        } else {
            out.push(ch);
            i += ch.len_utf8();
        }
    }
    serde_json::from_str(&out).unwrap_or(Value::Null)
}
pub fn normalize_strings(v: &mut Value, keys: &[&str]) {
    for key in keys {
        v[*key] = json!(text(&v[*key]));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn python_numeric_rounding_and_invalid_values() {
        assert_eq!(clamp(&json!(2.5), 0, 100, 50), 2);
        assert_eq!(clamp(&json!(3.5), 0, 100, 50), 4);
        assert_eq!(clamp(&json!("1.8"), 0, 100, 50), 2);
        assert_eq!(clamp(&json!("inf"), 0, 100, 50), 50);
        assert_eq!(clamp(&json!("bad"), 0, 100, 50), 50);
        assert_eq!(clamp(&json!(-10), 0, 100, 50), 0);
    }
    #[test]
    fn nonfinite_legacy_json_retains_other_fields_and_quoted_text() {
        let value = parse_json(
            r#"{"n":Infinity,"quoted":"Infinity🐈","other":25,"nested":[-Infinity,NaN]}"#,
        );
        assert_eq!(value["other"], 25);
        assert_eq!(value["quoted"], "Infinity🐈");
        assert!(value["n"].is_null());
        assert!(parse_json("{corrupt").is_null());
    }
}
