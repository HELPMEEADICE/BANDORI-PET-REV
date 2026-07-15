use crate::reminder::LocalDateTime;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use thiserror::Error;

const MAX_EVENT_DATABASE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_EVENT_TEXT_BYTES: usize = 8 * 1024;
const MAX_EVENT_DURATION_DAYS: u32 = 31;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct SpecialEvent {
    pub event_type: String,
    pub name_zh: String,
    pub month: u32,
    pub day: u32,
    pub duration_days: u32,
    pub prompt_template: String,
    pub notification_text: String,
    pub character: String,
    pub band: String,
    pub keywords: Vec<String>,
}

#[derive(Debug, Error)]
pub enum SpecialEventError {
    #[error("could not read special-event database {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("special-event database exceeds 2 MiB: {0}")]
    TooLarge(PathBuf),
    #[error("special-event database JSON is invalid in {path}: {source}")]
    Json {
        path: PathBuf,
        #[source]
        source: serde_json::Error,
    },
    #[error("special-event entry is invalid: {0}")]
    InvalidEntry(String),
}

#[derive(Default, Deserialize)]
struct BirthdayDatabaseFile {
    #[serde(default)]
    birthdays: BTreeMap<String, BTreeMap<String, BirthdayEntry>>,
}

#[derive(Deserialize)]
struct BirthdayEntry {
    month: u32,
    day: u32,
    name_zh: String,
}

#[derive(Default, Deserialize)]
struct FestivalDatabaseFile {
    #[serde(default)]
    festivals: BTreeMap<String, FestivalEntry>,
}

#[derive(Deserialize)]
struct FestivalEntry {
    name_zh: String,
    month: u32,
    day: u32,
    #[serde(default = "default_duration_days")]
    duration_days: u32,
    #[serde(default)]
    prompt_template: String,
    #[serde(default)]
    keywords: Vec<String>,
}

#[derive(Default)]
struct SpecialEventDatabase {
    birthdays: BTreeMap<String, BTreeMap<String, BirthdayEntry>>,
    festivals: BTreeMap<String, FestivalEntry>,
}

pub fn load_today_special_events(
    events_dir: impl AsRef<Path>,
    local_datetime: LocalDateTime,
) -> Result<Vec<SpecialEvent>, SpecialEventError> {
    load_database(events_dir.as_ref())?.events_for_date(local_datetime)
}

pub fn build_special_event_context(
    events_dir: impl AsRef<Path>,
    local_datetime: LocalDateTime,
    current_character: &str,
) -> Result<String, SpecialEventError> {
    let database = load_database(events_dir.as_ref())?;
    let events = database.events_for_date(local_datetime)?;
    let current_character = checked_identifier(current_character, "current character")?;
    let current_band = database.character_band(&current_character);
    let mut parts = Vec::new();
    for event in events {
        let text = if event.event_type == "birthday" && event.character == current_character {
            format!(
                "【{}】\n今天是{}，也就是你自己的生日。你心里知道这件事，但只有用户明确问起生日相关话题时才回答。",
                event.name_zh, event.name_zh
            )
        } else if event.event_type == "birthday"
            && !event.band.is_empty()
            && current_band == Some(event.band.as_str())
        {
            format!(
                "【{}】\n今天是{}。你知道这件事，但只有用户明确问起生日相关话题时才回答。",
                event.name_zh, event.name_zh
            )
        } else if event.event_type == "festival" {
            format!(
                "【{}】\n今天是{}（{}月{}日）。你知道今天是这个特殊的日子，但只有用户主动提起相关话题时才主动回应。",
                event.name_zh, event.name_zh, event.month, event.day
            )
        } else {
            continue;
        };
        parts.push(text);
    }
    Ok(parts.join("\n\n"))
}

impl SpecialEventDatabase {
    fn events_for_date(
        &self,
        local_datetime: LocalDateTime,
    ) -> Result<Vec<SpecialEvent>, SpecialEventError> {
        let mut events = Vec::new();
        for (band, characters) in &self.birthdays {
            let band = checked_identifier(band, "birthday band")?;
            for (character, entry) in characters {
                validate_month_day(entry.month, entry.day, "birthday")?;
                if entry.month != local_datetime.month || entry.day != local_datetime.day {
                    continue;
                }
                let character = checked_identifier(character, "birthday character")?;
                let person = checked_text(&entry.name_zh, 256, "birthday name")?;
                let name_zh = format!("{person}的生日");
                let prompt_template =
                    "今天是{name_zh}！你可以祝福她生日快乐，或者讨论她的故事。".to_owned();
                events.push(SpecialEvent {
                    event_type: "birthday".into(),
                    name_zh: name_zh.clone(),
                    month: entry.month,
                    day: entry.day,
                    duration_days: 1,
                    notification_text: render_prompt(
                        &prompt_template,
                        &name_zh,
                        entry.month,
                        entry.day,
                    ),
                    prompt_template,
                    character,
                    band: band.clone(),
                    keywords: Vec::new(),
                });
            }
        }
        for entry in self.festivals.values() {
            validate_month_day(entry.month, entry.day, "festival")?;
            let duration_days = entry.duration_days.clamp(1, MAX_EVENT_DURATION_DAYS);
            let Some(start) =
                LocalDateTime::new(local_datetime.year, entry.month, entry.day, 0, 0, 0)
            else {
                // A valid recurring February 29 event is simply inactive in a
                // non-leap year; it must not invalidate the whole database.
                continue;
            };
            let active = (0..duration_days).any(|offset| {
                let candidate = start.add_days(i64::from(offset));
                candidate.year == local_datetime.year
                    && candidate.month == local_datetime.month
                    && candidate.day == local_datetime.day
            });
            if !active {
                continue;
            }
            let name_zh = checked_text(&entry.name_zh, 256, "festival name")?;
            let prompt_template = checked_text(
                &entry.prompt_template,
                MAX_EVENT_TEXT_BYTES,
                "festival prompt",
            )?;
            let keywords = entry
                .keywords
                .iter()
                .take(64)
                .map(|keyword| checked_text(keyword, 256, "festival keyword"))
                .collect::<Result<Vec<_>, _>>()?;
            events.push(SpecialEvent {
                event_type: "festival".into(),
                name_zh: name_zh.clone(),
                month: entry.month,
                day: entry.day,
                duration_days,
                notification_text: render_prompt(
                    &prompt_template,
                    &name_zh,
                    entry.month,
                    entry.day,
                ),
                prompt_template,
                character: String::new(),
                band: String::new(),
                keywords,
            });
        }
        Ok(events)
    }

    fn character_band(&self, character: &str) -> Option<&str> {
        self.birthdays.iter().find_map(|(band, characters)| {
            characters.contains_key(character).then_some(band.as_str())
        })
    }
}

fn load_database(events_dir: &Path) -> Result<SpecialEventDatabase, SpecialEventError> {
    let birthday_path = events_dir.join("birthday_db.json");
    let festival_path = events_dir.join("festival_db.json");
    let birthdays = read_optional_json::<BirthdayDatabaseFile>(&birthday_path)?.birthdays;
    let festivals = read_optional_json::<FestivalDatabaseFile>(&festival_path)?.festivals;
    Ok(SpecialEventDatabase {
        birthdays,
        festivals,
    })
}

fn read_optional_json<T>(path: &Path) -> Result<T, SpecialEventError>
where
    T: Default + for<'de> Deserialize<'de>,
{
    let metadata = match fs::metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(T::default()),
        Err(source) => {
            return Err(SpecialEventError::Io {
                path: path.to_owned(),
                source,
            });
        }
    };
    if metadata.len() > MAX_EVENT_DATABASE_BYTES {
        return Err(SpecialEventError::TooLarge(path.to_owned()));
    }
    let source = fs::read(path).map_err(|source| SpecialEventError::Io {
        path: path.to_owned(),
        source,
    })?;
    serde_json::from_slice(&source).map_err(|source| SpecialEventError::Json {
        path: path.to_owned(),
        source,
    })
}

fn render_prompt(template: &str, name_zh: &str, month: u32, day: u32) -> String {
    template
        .replace("{name_zh}", name_zh)
        .replace("{month}", &month.to_string())
        .replace("{day}", &day.to_string())
}

fn validate_month_day(month: u32, day: u32, label: &str) -> Result<(), SpecialEventError> {
    // The databases describe annual events rather than a concrete year. Using
    // a leap year accepts February 29 while still rejecting impossible dates.
    LocalDateTime::new(2000, month, day, 0, 0, 0)
        .map(|_| ())
        .ok_or_else(|| SpecialEventError::InvalidEntry(format!("{label} date {month}-{day}")))
}

fn checked_identifier(source: &str, label: &str) -> Result<String, SpecialEventError> {
    let source = source.trim();
    if source.len() > 128
        || source.contains(['/', '\\', '\0'])
        || source.chars().any(char::is_control)
    {
        Err(SpecialEventError::InvalidEntry(label.to_owned()))
    } else {
        Ok(source.to_owned())
    }
}

fn checked_text(
    source: &str,
    maximum_bytes: usize,
    label: &str,
) -> Result<String, SpecialEventError> {
    let source = source.trim();
    if source.len() > maximum_bytes || source.chars().any(|character| character == '\0') {
        Err(SpecialEventError::InvalidEntry(label.to_owned()))
    } else {
        Ok(source.to_owned())
    }
}

const fn default_duration_days() -> u32 {
    1
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    fn write_fixture(root: &Path) {
        fs::write(
            root.join("birthday_db.json"),
            r#"{
                "birthdays":{
                    "poppin_party":{"kasumi":{"month":7,"day":14,"name_zh":"户山香澄"}},
                    "afterglow":{
                        "ran":{"month":4,"day":10,"name_zh":"美竹兰"},
                        "moca":{"month":4,"day":10,"name_zh":"青叶摩卡"}
                    }
                }
            }"#
            .as_bytes(),
        )
        .unwrap();
        fs::write(
            root.join("festival_db.json"),
            r#"{
                "festivals":{
                    "summer":{"name_zh":"夏日祭","month":7,"day":13,"duration_days":3,"prompt_template":"现在是{name_zh}（{month}月{day}日）。","keywords":["烟花"]}
                }
            }"#
                .as_bytes(),
        )
        .unwrap();
    }

    #[test]
    fn today_events_match_birthdays_and_multi_day_festivals() {
        let root = tempdir().unwrap();
        write_fixture(root.path());
        let at = LocalDateTime::new(2026, 7, 14, 9, 30, 0).unwrap();
        let events = load_today_special_events(root.path(), at).unwrap();
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].character, "kasumi");
        assert_eq!(
            events[0].notification_text,
            "今天是户山香澄的生日！你可以祝福她生日快乐，或者讨论她的故事。"
        );
        assert_eq!(events[1].name_zh, "夏日祭");
        assert_eq!(events[1].notification_text, "现在是夏日祭（7月13日）。");
    }

    #[test]
    fn event_context_includes_self_bandmates_and_festivals_only() {
        let root = tempdir().unwrap();
        write_fixture(root.path());
        let at = LocalDateTime::new(2026, 4, 10, 12, 0, 0).unwrap();
        let ran = build_special_event_context(root.path(), at, "ran").unwrap();
        assert!(ran.contains("也就是你自己的生日"));
        assert!(ran.contains("青叶摩卡的生日"));
        let kasumi = build_special_event_context(root.path(), at, "kasumi").unwrap();
        assert!(!kasumi.contains("美竹兰"));
        assert!(!kasumi.contains("青叶摩卡"));
    }

    #[test]
    fn missing_files_are_empty_but_invalid_entries_fail_closed() {
        let root = tempdir().unwrap();
        let at = LocalDateTime::new(2026, 1, 1, 0, 0, 0).unwrap();
        assert!(
            load_today_special_events(root.path(), at)
                .unwrap()
                .is_empty()
        );
        fs::write(
            root.path().join("festival_db.json"),
            br#"{"festivals":{"bad":{"name_zh":"bad","month":13,"day":1}}}"#,
        )
        .unwrap();
        assert!(load_today_special_events(root.path(), at).is_err());
    }

    #[test]
    fn leap_day_events_are_valid_and_inactive_in_non_leap_years() {
        let root = tempdir().unwrap();
        fs::write(
            root.path().join("festival_db.json"),
            r#"{"festivals":{"leap":{"name_zh":"闰日","month":2,"day":29}}}"#.as_bytes(),
        )
        .unwrap();
        let ordinary_year = LocalDateTime::new(2026, 2, 28, 0, 0, 0).unwrap();
        assert!(
            load_today_special_events(root.path(), ordinary_year)
                .unwrap()
                .is_empty()
        );
        let leap_year = LocalDateTime::new(2028, 2, 29, 0, 0, 0).unwrap();
        assert_eq!(
            load_today_special_events(root.path(), leap_year)
                .unwrap()
                .len(),
            1
        );
    }
}
