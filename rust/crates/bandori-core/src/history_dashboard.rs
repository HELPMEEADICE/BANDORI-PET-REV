use crate::database::{
    ChatHistoryFilterOptions, ChatHistoryQuery, ChatHistorySearchResult, Database, DatabaseError,
};
use serde::{Deserialize, Serialize};
use std::path::Path;
use thiserror::Error;

const MAX_HISTORY_KEYWORD_BYTES: usize = 4096;
const MAX_HISTORY_FILTER_BYTES: usize = 512;
const MAX_HISTORY_PAGE_SIZE: i64 = 200;
const MAX_HISTORY_OFFSET: i64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct NativeHistoryQuery {
    pub keyword: String,
    pub date_from: String,
    pub date_to: String,
    pub character: String,
    pub user_key: String,
    pub role: String,
    pub source: String,
    pub limit: i64,
    pub offset: i64,
    pub skip_count: bool,
}

impl Default for NativeHistoryQuery {
    fn default() -> Self {
        Self {
            keyword: String::new(),
            date_from: String::new(),
            date_to: String::new(),
            character: String::new(),
            user_key: String::new(),
            role: String::new(),
            source: String::new(),
            limit: 50,
            offset: 0,
            skip_count: false,
        }
    }
}

#[derive(Debug, Error)]
pub enum NativeHistoryError {
    #[error(transparent)]
    Database(#[from] DatabaseError),
    #[error("native history query JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native history query is invalid: {0}")]
    Invalid(String),
}

pub fn load_native_history_filters(
    database_path: &Path,
) -> Result<ChatHistoryFilterOptions, NativeHistoryError> {
    Ok(Database::open(database_path)?.chat_history_filter_options()?)
}

pub fn search_native_history(
    database_path: &Path,
    query_json: &str,
    max_bytes: usize,
) -> Result<ChatHistorySearchResult, NativeHistoryError> {
    if query_json.len() > max_bytes {
        return Err(NativeHistoryError::Invalid(format!(
            "query exceeds the {max_bytes} byte limit"
        )));
    }
    let query = checked_query(serde_json::from_str::<NativeHistoryQuery>(query_json)?)?;
    let database = Database::open(database_path)?;
    Ok(database.search_chat_history(&ChatHistoryQuery {
        keyword: &query.keyword,
        date_from: &query.date_from,
        date_to: &query.date_to,
        character: &query.character,
        user_key: &query.user_key,
        role: &query.role,
        source: &query.source,
        limit: query.limit,
        offset: query.offset,
        skip_count: query.skip_count,
    })?)
}

fn checked_query(mut query: NativeHistoryQuery) -> Result<NativeHistoryQuery, NativeHistoryError> {
    query.keyword = checked_text(&query.keyword, MAX_HISTORY_KEYWORD_BYTES, "history keyword")?;
    query.character = checked_text(
        &query.character,
        MAX_HISTORY_FILTER_BYTES,
        "history character",
    )?;
    query.user_key = checked_text(
        &query.user_key,
        MAX_HISTORY_FILTER_BYTES,
        "history user key",
    )?;
    query.date_from = checked_date(&query.date_from)?;
    query.date_to = checked_date(&query.date_to)?;
    if !query.date_from.is_empty() && !query.date_to.is_empty() && query.date_from > query.date_to {
        return Err(NativeHistoryError::Invalid(
            "history start date cannot be after the end date".to_owned(),
        ));
    }
    query.role = query.role.trim().to_ascii_lowercase();
    if !matches!(query.role.as_str(), "" | "user" | "assistant" | "system") {
        return Err(NativeHistoryError::Invalid(
            "history role must be user, assistant, system, or empty".to_owned(),
        ));
    }
    query.source = query.source.trim().to_ascii_lowercase();
    if !matches!(query.source.as_str(), "" | "private" | "group") {
        return Err(NativeHistoryError::Invalid(
            "history source must be private, group, or empty".to_owned(),
        ));
    }
    if !(1..=MAX_HISTORY_PAGE_SIZE).contains(&query.limit) {
        return Err(NativeHistoryError::Invalid(format!(
            "history page size must be between 1 and {MAX_HISTORY_PAGE_SIZE}"
        )));
    }
    if !(0..=MAX_HISTORY_OFFSET).contains(&query.offset) {
        return Err(NativeHistoryError::Invalid(format!(
            "history offset must be between 0 and {MAX_HISTORY_OFFSET}"
        )));
    }
    Ok(query)
}

fn checked_text(value: &str, max_bytes: usize, label: &str) -> Result<String, NativeHistoryError> {
    let value = value.trim();
    if value.len() > max_bytes || value.chars().any(|character| character == '\0') {
        Err(NativeHistoryError::Invalid(format!(
            "{label} is too long or contains NUL"
        )))
    } else {
        Ok(value.to_owned())
    }
}

fn checked_date(value: &str) -> Result<String, NativeHistoryError> {
    let value = value.trim();
    if value.is_empty() {
        return Ok(String::new());
    }
    let bytes = value.as_bytes();
    let shape = bytes.len() == 10
        && bytes[4] == b'-'
        && bytes[7] == b'-'
        && bytes
            .iter()
            .enumerate()
            .all(|(index, byte)| matches!(index, 4 | 7) || byte.is_ascii_digit());
    if !shape {
        return Err(NativeHistoryError::Invalid(
            "history dates must use yyyy-MM-dd".to_owned(),
        ));
    }
    let year = value[0..4].parse::<i32>().unwrap_or_default();
    let month = value[5..7].parse::<u32>().unwrap_or_default();
    let day = value[8..10].parse::<u32>().unwrap_or_default();
    let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    let max_day = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => 0,
    };
    if day == 0 || day > max_day {
        Err(NativeHistoryError::Invalid(
            "history date is not a valid calendar day".to_owned(),
        ))
    } else {
        Ok(value.to_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::tempdir;

    fn query(value: serde_json::Value) -> String {
        serde_json::to_string(&value).unwrap()
    }

    #[test]
    fn history_dashboard_searches_private_and_group_records_with_literal_filters() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("chat.db");
        let database = Database::open(&path).unwrap();
        let conversation = database
            .create_conversation("ran", "Practice", "alice")
            .unwrap();
        database
            .add_message(conversation, "user", "literal 100% effort", "", None, None)
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "group-1",
                "assistant",
                "group reply",
                "ran",
                None,
                None,
                "alice",
            )
            .unwrap();
        drop(database);

        let filters = load_native_history_filters(&path).unwrap();
        assert!(filters.characters.contains(&"ran".to_owned()));
        assert!(filters.user_keys.contains(&"alice".to_owned()));
        let result = search_native_history(
            &path,
            &query(json!({
                "keyword":"100%",
                "user_key":"alice",
                "source":"private",
                "limit":50
            })),
            64 * 1024,
        )
        .unwrap();
        assert_eq!(result.total, 1);
        assert_eq!(result.records.len(), 1);
        assert_eq!(result.records[0].content, "literal 100% effort");

        let group = search_native_history(
            &path,
            &query(json!({
                "character":"moca",
                "source":"group",
                "role":"assistant",
                "limit":50
            })),
            64 * 1024,
        )
        .unwrap();
        assert_eq!(group.total, 1);
        assert_eq!(group.records[0].group_key, "__group__:moca|ran");
        assert!(group.records[0].character.is_empty());
    }

    #[test]
    fn history_dashboard_rejects_unknown_fields_dates_and_unbounded_pages() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("chat.db");
        for value in [
            json!({"unknown":true}),
            json!({"date_from":"2026-02-30"}),
            json!({"date_from":"2026-07-20", "date_to":"2026-07-01"}),
            json!({"role":"tool"}),
            json!({"source":"external"}),
            json!({"limit":1000}),
            json!({"offset":-1}),
        ] {
            assert!(
                search_native_history(&path, &query(value), 64 * 1024).is_err(),
                "invalid query should be rejected"
            );
        }
    }
}
