use crate::database::{
    CharacterMessageCount, ChatSummary, DailyMessageCount, Database, DatabaseError, MoodChartPoint,
    UsageDay,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;
use thiserror::Error;

const MAX_CHARACTER_BYTES: usize = 512;
const MAX_USER_KEY_BYTES: usize = 512;
const MAX_ALIAS_CHARACTERS: usize = 256;
const MAX_ALIASES_PER_CHARACTER: usize = 32;
const MAX_ALIAS_BYTES: usize = 512;
const MAX_RELATIONSHIP_TREND_POINTS: usize = 366;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct NativeStatisticsQuery {
    pub days: i64,
    pub character: String,
    pub user_key: String,
    pub display_aliases: BTreeMap<String, Vec<String>>,
}

impl Default for NativeStatisticsQuery {
    fn default() -> Self {
        Self {
            days: 30,
            character: String::new(),
            user_key: String::new(),
            display_aliases: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeStatisticsSnapshot {
    pub query: NativeStatisticsQuery,
    pub summary: ChatSummary,
    pub total_messages: i64,
    pub usage_today_seconds: i64,
    pub usage_week_seconds: i64,
    pub usage_all_seconds: i64,
    pub relationship_trend: Vec<MoodChartPoint>,
    pub messages_per_character: Vec<CharacterMessageCount>,
    pub daily_messages: Vec<DailyMessageCount>,
    pub daily_usage: Vec<UsageDay>,
    pub hourly_heatmap: Vec<Vec<i64>>,
}

#[derive(Debug, Error)]
pub enum NativeStatisticsError {
    #[error(transparent)]
    Database(#[from] DatabaseError),
    #[error("native statistics query JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("native statistics query is invalid: {0}")]
    Invalid(String),
}

pub fn load_native_statistics(
    database_path: &Path,
    query_json: &str,
    max_bytes: usize,
) -> Result<NativeStatisticsSnapshot, NativeStatisticsError> {
    if query_json.len() > max_bytes {
        return Err(NativeStatisticsError::Invalid(format!(
            "query exceeds the {max_bytes} byte limit"
        )));
    }
    let query = checked_query(serde_json::from_str::<NativeStatisticsQuery>(query_json)?)?;
    let database = Database::open(database_path)?;
    let summary = database.chat_summary()?;
    let daily_message_days = if query.days > 0 { query.days } else { 30 };
    let daily_usage_days = if query.days > 0 { query.days } else { 14 };
    let relationship_trend = if query.character.is_empty() {
        Vec::new()
    } else {
        compact_relationship_trend(database.mood_events_for_chart(
            &query.character,
            &query.user_key,
            query.days,
        )?)
    };
    Ok(NativeStatisticsSnapshot {
        total_messages: summary.total_messages + summary.total_group_messages,
        usage_today_seconds: database.usage_today()?,
        usage_week_seconds: database.usage_week()?,
        usage_all_seconds: database.usage_all_time()?,
        relationship_trend,
        messages_per_character: database.messages_per_character_range(
            query.days,
            &query.user_key,
            &query.display_aliases,
        )?,
        daily_messages: database.daily_message_counts(daily_message_days, Some(&query.user_key))?,
        daily_usage: database.usage_daily(daily_usage_days)?,
        hourly_heatmap: database.hourly_heatmap(7, Some(&query.user_key))?,
        query,
        summary,
    })
}

fn compact_relationship_trend(points: Vec<MoodChartPoint>) -> Vec<MoodChartPoint> {
    let mut daily = Vec::<MoodChartPoint>::new();
    for point in points {
        let day = point.day.chars().take(10).collect::<String>();
        let replaces_current_day = daily
            .last()
            .map(|current| current.day.chars().take(10).eq(day.chars()))
            .unwrap_or(false);
        if replaces_current_day {
            if let Some(current) = daily.last_mut() {
                *current = point;
            }
        } else {
            daily.push(point);
        }
    }
    let remove = daily.len().saturating_sub(MAX_RELATIONSHIP_TREND_POINTS);
    if remove > 0 {
        daily.drain(..remove);
    }
    daily
}

fn checked_query(
    mut query: NativeStatisticsQuery,
) -> Result<NativeStatisticsQuery, NativeStatisticsError> {
    if !matches!(query.days, 0 | 7 | 30) {
        return Err(NativeStatisticsError::Invalid(
            "statistics range must be 0, 7, or 30 days".to_owned(),
        ));
    }
    query.character = checked_text(&query.character, MAX_CHARACTER_BYTES, "character")?;
    query.user_key = checked_text(&query.user_key, MAX_USER_KEY_BYTES, "user key")?;
    if query.display_aliases.len() > MAX_ALIAS_CHARACTERS {
        return Err(NativeStatisticsError::Invalid(format!(
            "at most {MAX_ALIAS_CHARACTERS} character alias sets are allowed"
        )));
    }
    let mut aliases = BTreeMap::new();
    for (character, values) in query.display_aliases {
        let character = checked_text(&character, MAX_CHARACTER_BYTES, "alias character")?;
        if character.is_empty() {
            continue;
        }
        if values.len() > MAX_ALIASES_PER_CHARACTER {
            return Err(NativeStatisticsError::Invalid(format!(
                "at most {MAX_ALIASES_PER_CHARACTER} aliases are allowed per character"
            )));
        }
        let mut normalized = Vec::new();
        for value in values {
            let value = checked_text(&value, MAX_ALIAS_BYTES, "character alias")?;
            if !value.is_empty() && !normalized.contains(&value) {
                normalized.push(value);
            }
        }
        aliases.insert(character, normalized);
    }
    query.display_aliases = aliases;
    Ok(query)
}

fn checked_text(
    value: &str,
    max_bytes: usize,
    label: &str,
) -> Result<String, NativeStatisticsError> {
    let value = value.trim();
    if value.len() > max_bytes || value.chars().any(|character| character == '\0') {
        Err(NativeStatisticsError::Invalid(format!(
            "statistics {label} is too long or contains NUL"
        )))
    } else {
        Ok(value.to_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::database::RelationshipUpdate;
    use serde_json::json;
    use tempfile::tempdir;

    fn query(value: serde_json::Value) -> String {
        serde_json::to_string(&value).unwrap()
    }

    #[test]
    fn statistics_snapshot_is_user_scoped_and_attributes_group_speakers() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("data.db");
        let database = Database::open(&path).unwrap();
        let conversation = database
            .create_conversation("ran", "Practice", "alice")
            .unwrap();
        database
            .add_message(conversation, "user", "hello", "", None, None)
            .unwrap();
        database
            .add_message(conversation, "assistant", "reply", "", None, None)
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "group-1",
                "assistant",
                "【Moca】\nMoca reply",
                "",
                None,
                None,
                "alice",
            )
            .unwrap();
        database
            .add_group_message(
                "__group__:moca|ran",
                "group-2",
                "user",
                "other user",
                "",
                None,
                None,
                "bob",
            )
            .unwrap();
        database
            .upsert_relationship_state(
                "ran",
                "alice",
                &RelationshipUpdate {
                    affection: Some(72),
                    trust: Some(64),
                    familiarity: Some(55),
                    ..RelationshipUpdate::default()
                },
            )
            .unwrap();
        drop(database);

        let snapshot = load_native_statistics(
            &path,
            &query(json!({
                "days":30,
                "character":"ran",
                "user_key":"alice",
                "display_aliases":{
                    "ran":["Ran"],
                    "moca":["Moca"]
                }
            })),
            64 * 1024,
        )
        .unwrap();
        assert_eq!(snapshot.total_messages, 4);
        assert_eq!(snapshot.relationship_trend.last().unwrap().affection, 72);
        assert_eq!(
            snapshot
                .messages_per_character
                .iter()
                .find(|item| item.character == "ran")
                .unwrap()
                .count,
            2
        );
        assert_eq!(
            snapshot
                .messages_per_character
                .iter()
                .find(|item| item.character == "moca")
                .unwrap()
                .count,
            1
        );
        assert_eq!(
            snapshot
                .daily_messages
                .iter()
                .map(|item| item.count)
                .sum::<i64>(),
            3
        );
        assert_eq!(snapshot.hourly_heatmap.iter().flatten().sum::<i64>(), 3);
    }

    #[test]
    fn statistics_query_rejects_unknown_ranges_fields_and_oversized_alias_sets() {
        let directory = tempdir().unwrap();
        let path = directory.path().join("data.db");
        for value in [
            json!({"days":1}),
            json!({"unknown":true}),
            json!({"character":"\u{0000}"}),
            json!({"display_aliases":{"ran":vec!["alias"; 33]}}),
        ] {
            assert!(load_native_statistics(&path, &query(value), 64 * 1024).is_err());
        }
    }

    #[test]
    fn relationship_trend_keeps_the_last_state_per_day_and_is_bounded() {
        let mut points = Vec::new();
        for day in 0..=MAX_RELATIONSHIP_TREND_POINTS {
            points.push(MoodChartPoint {
                day: format!("day{day:07} morning"),
                affection: 10,
                trust: 20,
                familiarity: 30,
            });
            points.push(MoodChartPoint {
                day: format!("day{day:07} evening"),
                affection: 40,
                trust: 50,
                familiarity: 60,
            });
        }

        let compact = compact_relationship_trend(points);
        assert_eq!(compact.len(), MAX_RELATIONSHIP_TREND_POINTS);
        assert_eq!(compact.first().unwrap().day, "day0000001 evening");
        assert_eq!(compact.last().unwrap().day, "day0000366 evening");
        assert_eq!(compact.last().unwrap().affection, 40);
    }
}
