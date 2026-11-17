//! Deliberately small DB-API escape hatch for legacy diagnostics and tests.
//! Domain operations never use it. Values and resources remain owned by Rust.
use crate::{Database, Error, Result, SqlValue};
use rusqlite::params_from_iter;

pub struct RawOutput {
    pub rows: Vec<Vec<SqlValue>>,
    pub columns: Vec<String>,
    pub rowcount: i64,
    pub lastrowid: i64,
}

impl Database {
    pub fn raw_execute(&self, sql: &str, parameters: &[SqlValue]) -> Result<RawOutput> {
        self.with_connection(|c| {
            let keyword = sql
                .trim_start()
                .split_whitespace()
                .next()
                .unwrap_or("")
                .to_ascii_uppercase();
            if c.is_autocommit()
                && ["INSERT", "UPDATE", "DELETE", "REPLACE"].contains(&keyword.as_str())
            {
                c.execute_batch("BEGIN DEFERRED")?;
            }
            let mut stmt = c.prepare(sql)?;
            let columns = stmt.column_names().map(String::from).collect::<Vec<_>>();
            let mut rows = vec![];
            let rowcount;
            if columns.is_empty() {
                rowcount = stmt.execute(params_from_iter(parameters))? as i64;
            } else {
                let mut cursor = stmt.query(params_from_iter(parameters))?;
                while let Some(row) = cursor.next()? {
                    rows.push(
                        (0..columns.len())
                            .map(|i| row.get(i))
                            .collect::<rusqlite::Result<Vec<SqlValue>>>()?,
                    );
                }
                rowcount = -1;
            }
            Ok(RawOutput {
                rows,
                columns,
                rowcount,
                lastrowid: c.last_insert_rowid(),
            })
        })
    }
    pub fn control(&self, action: &str) -> Result<serde_json::Value> {
        self.with_connection(|c| match action {
            "commit" | "rollback" => {
                if !c.is_autocommit() {
                    c.execute_batch(if action == "commit" {
                        "COMMIT"
                    } else {
                        "ROLLBACK"
                    })?;
                }
                Ok(serde_json::Value::Null)
            }
            "total_changes" => Ok(serde_json::json!(c.total_changes())),
            "in_transaction" => Ok(serde_json::json!(!c.is_autocommit())),
            _ => Err(Error::Invalid("unknown connection control".into())),
        })
    }
}
