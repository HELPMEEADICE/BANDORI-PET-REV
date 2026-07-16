use crate::config::{ConfigDocument, ConfigError};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

pub const FOCUS_SECONDS: i64 = 25 * 60;
pub const SHORT_BREAK_SECONDS: i64 = 5 * 60;
pub const LONG_BREAK_SECONDS: i64 = 15 * 60;

#[derive(Clone, Copy)]
struct ProactiveTemplate {
    id: &'static str,
    title: &'static str,
    description: &'static str,
    schedule_type: &'static str,
    time: Option<&'static str>,
    interval_minutes: Option<i64>,
}

const DEFAULT_PROACTIVE_ITEMS: [ProactiveTemplate; 5] = [
    ProactiveTemplate {
        id: "morning",
        title: "早安问候",
        description: "早上问候用户，轻轻确认今天要做什么。",
        schedule_type: "daily",
        time: Some("08:30"),
        interval_minutes: None,
    },
    ProactiveTemplate {
        id: "water",
        title: "喝水提醒",
        description: "提醒用户喝水，语气自然一点。",
        schedule_type: "interval",
        time: None,
        interval_minutes: Some(90),
    },
    ProactiveTemplate {
        id: "sedentary",
        title: "久坐提醒",
        description: "提醒用户站起来活动一下，照顾肩颈和眼睛。",
        schedule_type: "interval",
        time: None,
        interval_minutes: Some(60),
    },
    ProactiveTemplate {
        id: "evening_review",
        title: "计划复盘",
        description: "提醒用户简单复盘今天的计划、完成情况和明天要处理的事。",
        schedule_type: "daily",
        time: Some("21:30"),
        interval_minutes: None,
    },
    ProactiveTemplate {
        id: "bedtime",
        title: "睡前提醒",
        description: "提醒用户差不多该收尾休息了。",
        schedule_type: "daily",
        time: Some("23:30"),
        interval_minutes: None,
    },
];

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct LocalDateTime {
    pub year: i32,
    pub month: u32,
    pub day: u32,
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
}

impl LocalDateTime {
    pub fn parse(source: &str) -> Option<Self> {
        let source = source.trim();
        let (date, time) = source.split_once('T').or_else(|| source.split_once(' '))?;
        let mut date = date.split('-');
        let year = date.next()?.parse().ok()?;
        let month = date.next()?.parse().ok()?;
        let day = date.next()?.parse().ok()?;
        if date.next().is_some() {
            return None;
        }
        let time = time.split(['+', 'Z']).next().unwrap_or(time);
        let mut time = time.split(':');
        let hour = time.next()?.parse().ok()?;
        let minute = time.next()?.parse().ok()?;
        let second = time
            .next()
            .unwrap_or("0")
            .split('.')
            .next()
            .unwrap_or("0")
            .parse()
            .ok()?;
        if time.next().is_some() {
            return None;
        }
        Self::new(year, month, day, hour, minute, second)
    }

    pub fn new(
        year: i32,
        month: u32,
        day: u32,
        hour: u32,
        minute: u32,
        second: u32,
    ) -> Option<Self> {
        if !(1..=9999).contains(&year)
            || !(1..=12).contains(&month)
            || day == 0
            || day > days_in_month(year, month)
            || hour > 23
            || minute > 59
            || second > 59
        {
            return None;
        }
        Some(Self {
            year,
            month,
            day,
            hour,
            minute,
            second,
        })
    }

    pub fn isoformat(self) -> String {
        format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
            self.year, self.month, self.day, self.hour, self.minute, self.second
        )
    }

    pub fn add_seconds(self, seconds: i64) -> Self {
        Self::from_linear_seconds(self.to_linear_seconds().saturating_add(seconds))
    }

    pub fn add_days(self, days: i64) -> Self {
        self.add_seconds(days.saturating_mul(86_400))
    }

    pub fn weekday(self) -> u32 {
        (days_from_civil(self.year, self.month, self.day) + 3).rem_euclid(7) as u32
    }

    fn to_linear_seconds(self) -> i64 {
        days_from_civil(self.year, self.month, self.day) * 86_400
            + i64::from(self.hour) * 3_600
            + i64::from(self.minute) * 60
            + i64::from(self.second)
    }

    fn from_linear_seconds(seconds: i64) -> Self {
        let days = seconds.div_euclid(86_400);
        let seconds = seconds.rem_euclid(86_400);
        let (year, month, day) = civil_from_days(days);
        Self {
            year,
            month,
            day,
            hour: (seconds / 3_600) as u32,
            minute: ((seconds % 3_600) / 60) as u32,
            second: (seconds % 60) as u32,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Alarm {
    pub id: String,
    pub enabled: bool,
    pub time: String,
    pub repeat_days: Vec<u32>,
    pub description: String,
    pub character: String,
    pub created_at: String,
    pub next_at: String,
    pub last_triggered_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Pomodoro {
    pub id: String,
    pub status: String,
    pub repeat_count: i64,
    pub completed_focus_count: i64,
    pub phase: String,
    pub phase_started_at: String,
    pub phase_duration_sec: i64,
    pub next_at: String,
    pub description: String,
    pub character: String,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProactiveItem {
    pub id: String,
    pub enabled: bool,
    pub kind: String,
    pub title: String,
    pub description: String,
    pub schedule_type: String,
    pub character: String,
    pub next_at: String,
    pub last_triggered_at: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub time: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub interval_minutes: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_start: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_end: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ProactiveCompanion {
    pub enabled: bool,
    pub character: String,
    pub items: Vec<ProactiveItem>,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
struct CareDecision {
    allow: bool,
    reason: String,
    next_delay_minutes: Option<i64>,
    tone_hint: String,
}

#[derive(Debug, Error, Eq, PartialEq)]
pub enum ReminderError {
    #[error("time is required")]
    TimeRequired,
    #[error("cannot compute next alarm time")]
    CannotComputeNextAlarm,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct NativeReminderState {
    pub display_mode: String,
    pub alarms: Vec<Alarm>,
    pub pomodoros: Vec<Pomodoro>,
    pub proactive_companion: ProactiveCompanion,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum NativeReminderMutation {
    AddAlarm {
        time: String,
        #[serde(default)]
        repeat_days: Value,
        #[serde(default)]
        description: String,
        #[serde(default)]
        character: String,
        #[serde(default)]
        date: String,
    },
    ToggleAlarm {
        id: String,
        enabled: bool,
    },
    DeleteAlarm {
        id: String,
    },
    AddPomodoro {
        #[serde(default = "default_repeat_count")]
        repeat_count: i64,
        #[serde(default)]
        description: String,
        #[serde(default)]
        character: String,
    },
    DeletePomodoro {
        id: String,
    },
    SetDisplayMode {
        mode: String,
    },
    SetProactive {
        enabled: bool,
        #[serde(default)]
        character: String,
    },
    UpdateProactiveItem {
        id: String,
        enabled: bool,
        #[serde(default)]
        time: String,
        #[serde(default)]
        interval_minutes: Option<i64>,
        #[serde(default)]
        active_start: String,
        #[serde(default)]
        active_end: String,
    },
}

#[derive(Debug, Error)]
pub enum NativeReminderError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("native reminder command JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Reminder(#[from] ReminderError),
    #[error("native reminder operation is invalid: {0}")]
    InvalidOperation(String),
}

pub fn normalize_time(source: &str) -> String {
    let chars = source.trim().chars().collect::<Vec<_>>();
    if chars.is_empty() {
        return String::new();
    }
    for index in 0..chars.len() {
        if index > 0 && chars[index - 1].is_ascii_digit() {
            continue;
        }
        for (hour, consumed) in hour_candidates(&chars, index) {
            let separator = index + consumed;
            if separator >= chars.len() || !matches!(chars[separator], ':' | '：' | '点' | '时')
            {
                continue;
            }
            let minute = if separator + 2 < chars.len()
                && matches!(chars[separator + 1], '0'..='5')
                && chars[separator + 2].is_ascii_digit()
            {
                digit(chars[separator + 1]) * 10 + digit(chars[separator + 2])
            } else {
                0
            };
            return format!("{hour:02}:{minute:02}");
        }
    }
    for index in 0..chars.len() {
        if index > 0 && chars[index - 1].is_ascii_digit() {
            continue;
        }
        for (hour, consumed) in hour_candidates(&chars, index) {
            if chars[index + consumed..]
                .iter()
                .all(|value| !value.is_ascii_digit())
            {
                return format!("{hour:02}:00");
            }
        }
    }
    String::new()
}

pub fn normalize_repeat_days(value: &Value) -> Vec<u32> {
    let parts = match value {
        Value::Null => return Vec::new(),
        Value::String(text) if text.trim().is_empty() => return Vec::new(),
        Value::String(text) => {
            let lowered = text.trim().to_lowercase();
            match lowered.as_str() {
                "none" | "once" | "no_repeat" | "不重复" | "单次" => return Vec::new(),
                "daily" | "everyday" | "每天" | "每日" => return (0..7).collect(),
                "weekdays" | "workdays" | "工作日" => return (0..5).collect(),
                "weekends" | "周末" => return vec![5, 6],
                _ => lowered
                    .split(|character: char| {
                        character == ','
                            || character == '，'
                            || character == '、'
                            || character.is_whitespace()
                    })
                    .filter(|part| !part.is_empty())
                    .map(|part| Value::String(part.to_owned()))
                    .collect(),
            }
        }
        Value::Array(parts) => parts.clone(),
        other => vec![other.clone()],
    };
    let mut result = parts
        .iter()
        .filter_map(repeat_day)
        .collect::<HashSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    result.sort_unstable();
    result
}

pub fn repeat_days_label(days: &[u32]) -> String {
    let mut days = days.to_vec();
    days.sort_unstable();
    days.dedup();
    match days.as_slice() {
        [] => "不重复".to_owned(),
        [0, 1, 2, 3, 4, 5, 6] => "每天".to_owned(),
        [0, 1, 2, 3, 4] => "工作日".to_owned(),
        [5, 6] => "周末".to_owned(),
        _ => {
            let labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
            days.iter()
                .filter_map(|day| labels.get(*day as usize))
                .copied()
                .collect::<Vec<_>>()
                .join("、")
        }
    }
}

pub fn compute_next_alarm_at(
    time_text: &str,
    repeat_days: &[u32],
    after: LocalDateTime,
    date_text: &str,
) -> Option<LocalDateTime> {
    let time = normalize_time(time_text);
    let (hour, minute) = parse_time_parts(&time)?;
    let mut repeat_days = repeat_days.to_vec();
    repeat_days.retain(|day| *day <= 6);
    repeat_days.sort_unstable();
    repeat_days.dedup();
    if repeat_days.is_empty() && !date_text.trim().is_empty() {
        let (year, month, day) = parse_date(date_text)?;
        let candidate = LocalDateTime::new(year, month, day, hour, minute, 0)?;
        return (candidate > after).then_some(candidate);
    }
    for offset in 0..15 {
        let date = after.add_days(offset);
        let candidate = LocalDateTime::new(date.year, date.month, date.day, hour, minute, 0)?;
        if candidate <= after {
            continue;
        }
        if repeat_days.is_empty() || repeat_days.contains(&candidate.weekday()) {
            return Some(candidate);
        }
    }
    None
}

pub fn create_alarm_with_id(
    id: &str,
    time_text: &str,
    repeat_days: &Value,
    description: &str,
    character: &str,
    date_text: &str,
    now: LocalDateTime,
) -> Result<Alarm, ReminderError> {
    let time = normalize_time(time_text);
    if time.is_empty() {
        return Err(ReminderError::TimeRequired);
    }
    let repeat_days = normalize_repeat_days(repeat_days);
    let next_at = compute_next_alarm_at(&time, &repeat_days, now, date_text)
        .ok_or(ReminderError::CannotComputeNextAlarm)?;
    Ok(Alarm {
        id: id.trim().to_owned(),
        enabled: true,
        time,
        repeat_days,
        description: truncate_chars(description.trim(), 240),
        character: character.trim().to_owned(),
        created_at: now.isoformat(),
        next_at: next_at.isoformat(),
        last_triggered_at: String::new(),
    })
}

pub fn create_alarm(
    time_text: &str,
    repeat_days: &Value,
    description: &str,
    character: &str,
    date_text: &str,
    now: LocalDateTime,
) -> Result<Alarm, ReminderError> {
    create_alarm_with_id(
        &new_reminder_id("alarm"),
        time_text,
        repeat_days,
        description,
        character,
        date_text,
        now,
    )
}

pub fn normalize_alarm(value: &Value, now: LocalDateTime) -> Option<Alarm> {
    let item = value.as_object()?;
    let time = normalize_time(&object_text(item, "time"));
    if time.is_empty() {
        return None;
    }
    let repeat = item
        .get("repeat_days")
        .or_else(|| item.get("repeat"))
        .unwrap_or(&Value::Null);
    let repeat_days = normalize_repeat_days(repeat);
    let enabled = coerce_bool(item.get("enabled"), true);
    let raw_next_at = object_text(item, "next_at");
    let next_at = LocalDateTime::parse(&raw_next_at).or_else(|| {
        enabled
            .then(|| compute_next_alarm_at(&time, &repeat_days, now, ""))
            .flatten()
    });
    Some(Alarm {
        id: nonempty_or_else(object_text(item, "id"), || new_reminder_id("alarm")),
        enabled,
        time,
        repeat_days,
        description: truncate_chars(object_text(item, "description").trim(), 240),
        character: first_nonempty(&[object_text(item, "character"), object_text(item, "role")]),
        created_at: nonempty_or_else(object_text(item, "created_at"), || now.isoformat()),
        next_at: next_at.map(LocalDateTime::isoformat).unwrap_or_default(),
        last_triggered_at: object_text(item, "last_triggered_at"),
    })
}

pub fn normalize_alarms(value: &Value, now: LocalDateTime) -> Vec<Alarm> {
    let Some(items) = value.as_array() else {
        return Vec::new();
    };
    let mut seen = HashSet::new();
    items
        .iter()
        .filter_map(|item| normalize_alarm(item, now))
        .filter(|alarm| seen.insert(alarm.id.clone()))
        .collect()
}

pub fn create_pomodoro_with_id(
    id: &str,
    repeat_count: i64,
    description: &str,
    character: &str,
    now: LocalDateTime,
) -> Pomodoro {
    Pomodoro {
        id: id.trim().to_owned(),
        status: "running".to_owned(),
        repeat_count: repeat_count.clamp(1, 24),
        completed_focus_count: 0,
        phase: "focus".to_owned(),
        phase_started_at: now.isoformat(),
        phase_duration_sec: FOCUS_SECONDS,
        next_at: now.add_seconds(FOCUS_SECONDS).isoformat(),
        description: truncate_chars(description.trim(), 240),
        character: character.trim().to_owned(),
        created_at: now.isoformat(),
        updated_at: now.isoformat(),
    }
}

pub fn create_pomodoro(
    repeat_count: i64,
    description: &str,
    character: &str,
    now: LocalDateTime,
) -> Pomodoro {
    create_pomodoro_with_id(
        &new_reminder_id("pomodoro"),
        repeat_count,
        description,
        character,
        now,
    )
}

pub fn normalize_pomodoro(value: &Value, now: LocalDateTime) -> Option<Pomodoro> {
    let item = value.as_object()?;
    let repeat_count = coerce_i64(item.get("repeat_count"), 1).clamp(1, 24);
    let completed_focus_count =
        coerce_i64(item.get("completed_focus_count"), 0).clamp(0, repeat_count);
    let mut status = object_text(item, "status").trim().to_lowercase();
    if !matches!(
        status.as_str(),
        "running" | "paused" | "completed" | "cancelled"
    ) {
        status = "running".to_owned();
    }
    let mut phase = object_text(item, "phase").trim().to_lowercase();
    if !matches!(
        phase.as_str(),
        "focus" | "short_break" | "long_break" | "completed"
    ) {
        phase = "focus".to_owned();
    }
    let mut duration = coerce_i64(item.get("phase_duration_sec"), 0);
    if duration <= 0 {
        duration = match phase.as_str() {
            "focus" => FOCUS_SECONDS,
            "long_break" => LONG_BREAK_SECONDS,
            _ => SHORT_BREAK_SECONDS,
        };
    }
    let raw_next_at = object_text(item, "next_at");
    let next_at = LocalDateTime::parse(&raw_next_at)
        .or_else(|| (status == "running").then(|| now.add_seconds(duration)));
    Some(Pomodoro {
        id: nonempty_or_else(object_text(item, "id"), || new_reminder_id("pomodoro")),
        status,
        repeat_count,
        completed_focus_count,
        phase,
        phase_started_at: nonempty_or_else(object_text(item, "phase_started_at"), || {
            now.isoformat()
        }),
        phase_duration_sec: duration,
        next_at: next_at.map(LocalDateTime::isoformat).unwrap_or_default(),
        description: truncate_chars(object_text(item, "description").trim(), 240),
        character: first_nonempty(&[object_text(item, "character"), object_text(item, "role")]),
        created_at: nonempty_or_else(object_text(item, "created_at"), || now.isoformat()),
        updated_at: nonempty_or_else(object_text(item, "updated_at"), || now.isoformat()),
    })
}

pub fn normalize_pomodoros(value: &Value, now: LocalDateTime) -> Vec<Pomodoro> {
    let Some(items) = value.as_array() else {
        return Vec::new();
    };
    let mut seen = HashSet::new();
    items
        .iter()
        .filter_map(|item| normalize_pomodoro(item, now))
        .filter(|pomodoro| seen.insert(pomodoro.id.clone()))
        .collect()
}

pub fn compute_next_proactive_at(
    item: &ProactiveItem,
    after: LocalDateTime,
) -> Option<LocalDateTime> {
    if item.schedule_type == "daily" {
        return compute_next_alarm_at(
            item.time.as_deref().unwrap_or("08:30"),
            &[0, 1, 2, 3, 4, 5, 6],
            after,
            "",
        );
    }
    let interval = item.interval_minutes.unwrap_or(60).clamp(10, 480);
    let active_start = item.active_start.as_deref().unwrap_or("09:00");
    let active_end = item.active_end.as_deref().unwrap_or("22:00");
    let candidate = after.add_seconds(interval * 60);
    if is_in_active_window(candidate, active_start, active_end) {
        Some(candidate)
    } else {
        next_active_window_start(after, active_start)
    }
}

pub fn normalize_proactive_companion(value: &Value, now: LocalDateTime) -> ProactiveCompanion {
    let raw = value.as_object();
    let raw_items = raw
        .and_then(|object| object.get("items"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut items = Vec::new();
    let mut seen = HashSet::new();
    for template in DEFAULT_PROACTIVE_ITEMS {
        let raw_item = raw_items.iter().rev().find(|item| {
            item.get("id").and_then(Value::as_str).map(str::trim) == Some(template.id)
        });
        if let Some(item) = normalize_proactive_item(raw_item, Some(template), now) {
            seen.insert(item.id.clone());
            items.push(item);
        }
    }
    for raw_item in &raw_items {
        let Some(object) = raw_item.as_object() else {
            continue;
        };
        let id = object_text(object, "id").trim().to_owned();
        let kind = nonempty_or_else(object_text(object, "kind"), || id.clone());
        if id.is_empty() || id == "desktop_state" || kind == "desktop_state" || seen.contains(&id) {
            continue;
        }
        if let Some(item) = normalize_proactive_item(Some(raw_item), None, now) {
            seen.insert(item.id.clone());
            items.push(item);
        }
    }
    ProactiveCompanion {
        enabled: coerce_bool(raw.and_then(|object| object.get("enabled")), false),
        character: raw
            .map(|object| object_text(object, "character"))
            .unwrap_or_default()
            .trim()
            .to_owned(),
        items,
    }
}

fn normalize_proactive_item(
    value: Option<&Value>,
    template: Option<ProactiveTemplate>,
    now: LocalDateTime,
) -> Option<ProactiveItem> {
    let raw = value.and_then(Value::as_object);
    let template_id = template.map(|item| item.id).unwrap_or_default();
    let id = raw
        .map(|object| object_text(object, "id"))
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| template_id.to_owned())
        .trim()
        .to_owned();
    if id.is_empty() {
        return None;
    }
    let mut schedule_type = raw
        .map(|object| object_text(object, "schedule_type"))
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| {
            template
                .map(|item| item.schedule_type.to_owned())
                .unwrap_or_else(|| "daily".to_owned())
        })
        .trim()
        .to_lowercase();
    if !matches!(schedule_type.as_str(), "daily" | "interval") {
        schedule_type = "daily".to_owned();
    }
    let enabled = coerce_bool(raw.and_then(|object| object.get("enabled")), true);
    let kind = raw
        .map(|object| object_text(object, "kind"))
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| id.clone())
        .trim()
        .to_owned();
    let title = truncate_chars(
        raw.map(|object| object_text(object, "title"))
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| {
                template
                    .map(|item| item.title.to_owned())
                    .unwrap_or_else(|| id.clone())
            })
            .trim(),
        80,
    );
    let description = truncate_chars(
        raw.and_then(|object| object.get("description"))
            .map(value_text)
            .unwrap_or_else(|| {
                template
                    .map(|item| item.description.to_owned())
                    .unwrap_or_default()
            })
            .trim(),
        240,
    );
    let character = raw
        .map(|object| object_text(object, "character"))
        .unwrap_or_default()
        .trim()
        .to_owned();
    let raw_next_at = raw
        .map(|object| object_text(object, "next_at"))
        .unwrap_or_default();
    let last_triggered_at = raw
        .map(|object| object_text(object, "last_triggered_at"))
        .unwrap_or_default();
    let (time, interval_minutes, active_start, active_end) = if schedule_type == "daily" {
        let normalized = raw
            .map(|object| normalize_time(&object_text(object, "time")))
            .filter(|value| !value.is_empty())
            .or_else(|| template.and_then(|item| item.time).map(str::to_owned))
            .unwrap_or_else(|| "08:30".to_owned());
        (Some(normalized), None, None, None)
    } else {
        let interval = raw
            .and_then(|object| object.get("interval_minutes"))
            .map(|value| coerce_i64(Some(value), 60))
            .or_else(|| template.and_then(|item| item.interval_minutes))
            .unwrap_or(60)
            .clamp(10, 480);
        let start = raw
            .map(|object| normalize_time(&object_text(object, "active_start")))
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "09:00".to_owned());
        let end = raw
            .map(|object| normalize_time(&object_text(object, "active_end")))
            .filter(|value| !value.is_empty())
            .unwrap_or_else(|| "22:00".to_owned());
        (None, Some(interval), Some(start), Some(end))
    };
    let mut item = ProactiveItem {
        id,
        enabled,
        kind,
        title,
        description,
        schedule_type,
        character,
        next_at: String::new(),
        last_triggered_at,
        time,
        interval_minutes,
        active_start,
        active_end,
    };
    if item.enabled {
        item.next_at = LocalDateTime::parse(&raw_next_at)
            .or_else(|| compute_next_proactive_at(&item, now))
            .map(LocalDateTime::isoformat)
            .unwrap_or_default();
    }
    Some(item)
}

fn is_in_active_window(at: LocalDateTime, active_start: &str, active_end: &str) -> bool {
    let Some(start) = minutes_of_day(active_start) else {
        return true;
    };
    let Some(end) = minutes_of_day(active_end) else {
        return true;
    };
    let current = i64::from(at.hour) * 60 + i64::from(at.minute);
    if start <= end {
        start <= current && current <= end
    } else {
        current >= start || current <= end
    }
}

fn next_active_window_start(after: LocalDateTime, active_start: &str) -> Option<LocalDateTime> {
    let start = minutes_of_day(active_start)?;
    for offset in 0..3 {
        let date = after.add_days(offset);
        let candidate = LocalDateTime::new(
            date.year,
            date.month,
            date.day,
            (start / 60) as u32,
            (start % 60) as u32,
            0,
        )?;
        if candidate > after {
            return Some(candidate);
        }
    }
    None
}

fn minutes_of_day(value: &str) -> Option<i64> {
    let normalized = normalize_time(value);
    let (hour, minute) = parse_time_parts(&normalized)?;
    Some(i64::from(hour) * 60 + i64::from(minute))
}

fn normalize_proactive_care_policy(value: &Value) -> Value {
    let raw = value.as_object();
    let raw_rules = raw
        .and_then(|object| object.get("state_rules"))
        .and_then(Value::as_object);
    let mut state_rules = Map::new();
    for state in [
        "gaming", "media", "coding", "writing", "chatting", "web", "desktop", "idle", "unknown",
    ] {
        let (default_mode, default_multiplier) = match state {
            "coding" | "writing" => ("quiet", 2.0),
            "idle" => ("encourage", 0.7),
            _ => ("normal", 1.0),
        };
        let rule = raw_rules
            .and_then(|rules| rules.get(state))
            .and_then(Value::as_object);
        let mode = rule
            .map(|object| object_text(object, "mode"))
            .map(|value| value.trim().to_lowercase())
            .filter(|value| matches!(value.as_str(), "normal" | "quiet" | "silent" | "encourage"))
            .unwrap_or_else(|| default_mode.to_owned());
        state_rules.insert(
            state.to_owned(),
            json!({
                "mode": mode,
                "cooldown_multiplier": coerce_f64(
                    rule.and_then(|object| object.get("cooldown_multiplier")),
                    default_multiplier,
                ).clamp(0.25, 4.0),
                "allow_screen_awareness": coerce_bool(
                    rule.and_then(|object| object.get("allow_screen_awareness")),
                    true,
                ),
                "allow_lifestyle_reminders": coerce_bool(
                    rule.and_then(|object| object.get("allow_lifestyle_reminders")),
                    true,
                ),
            }),
        );
    }
    let quiet_start = raw
        .map(|object| normalize_time(&object_text(object, "quiet_start")))
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "23:30".to_owned());
    let quiet_end = raw
        .map(|object| normalize_time(&object_text(object, "quiet_end")))
        .filter(|value| !value.is_empty())
        .unwrap_or_else(|| "08:00".to_owned());
    json!({
        "enabled": coerce_bool(raw.and_then(|object| object.get("enabled")), true),
        "global_cooldown_minutes": coerce_i64(
            raw.and_then(|object| object.get("global_cooldown_minutes")),
            30,
        ).clamp(5, 120),
        "quiet_hours_enabled": coerce_bool(
            raw.and_then(|object| object.get("quiet_hours_enabled")),
            false,
        ),
        "quiet_start": quiet_start,
        "quiet_end": quiet_end,
        "last_care_at": raw.map(|object| object_text(object, "last_care_at")).unwrap_or_default(),
        "last_screen_awareness_at": raw
            .map(|object| object_text(object, "last_screen_awareness_at"))
            .unwrap_or_default(),
        "last_skip_reason": truncate_chars(
            raw.map(|object| object_text(object, "last_skip_reason"))
                .unwrap_or_default()
                .as_str(),
            160,
        ),
        "state_rules": state_rules,
    })
}

fn evaluate_proactive_care(
    policy: &Value,
    proactive_kind: &str,
    desktop_state: &Value,
    now: LocalDateTime,
) -> CareDecision {
    if !policy
        .get("enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true)
    {
        return care_allowed("自然、简短，不要解释触发机制。");
    }
    let state = desktop_state
        .get("state")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|state| {
            matches!(
                *state,
                "gaming"
                    | "media"
                    | "coding"
                    | "writing"
                    | "chatting"
                    | "web"
                    | "desktop"
                    | "idle"
                    | "unknown"
            )
        })
        .unwrap_or("unknown");
    let rule = policy
        .get("state_rules")
        .and_then(|rules| rules.get(state))
        .or_else(|| {
            policy
                .get("state_rules")
                .and_then(|rules| rules.get("unknown"))
        })
        .unwrap_or(&Value::Null);
    let mode = rule.get("mode").and_then(Value::as_str).unwrap_or("normal");
    let cooldown = care_cooldown_minutes(policy, rule);
    if policy
        .get("quiet_hours_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        && is_in_active_window(
            now,
            policy
                .get("quiet_start")
                .and_then(Value::as_str)
                .unwrap_or("23:30"),
            policy
                .get("quiet_end")
                .and_then(Value::as_str)
                .unwrap_or("08:00"),
        )
    {
        return care_blocked("quiet_hours", cooldown, "勿扰时段内保持安静。");
    }
    let important = matches!(proactive_kind, "bedtime" | "sedentary");
    if !rule
        .get("allow_lifestyle_reminders")
        .and_then(Value::as_bool)
        .unwrap_or(true)
        && !important
    {
        return care_blocked(&format!("{state}_blocks_lifestyle"), cooldown, "");
    }
    if mode == "silent" && !important {
        return care_blocked(&format!("{state}_silent"), cooldown, "");
    }
    if let Some(last_at) = policy
        .get("last_care_at")
        .and_then(Value::as_str)
        .and_then(LocalDateTime::parse)
    {
        let elapsed_seconds = now
            .to_linear_seconds()
            .saturating_sub(last_at.to_linear_seconds())
            .max(0);
        let remaining = cooldown as f64 - elapsed_seconds as f64 / 60.0;
        if remaining > 0.0 {
            return care_blocked("cooldown", remaining.round().max(1.0) as i64, "");
        }
    }
    care_allowed(match mode {
        "quiet" => "用户可能正在专注，语气要轻，不要要求立即回应。",
        "silent" => "只在重要健康或睡前提醒时开口，语气要短。",
        "encourage" => "用户可能空闲或离开过，语气可以更温和主动。",
        _ => "自然、简短，像日常关心。",
    })
}

fn care_cooldown_minutes(policy: &Value, rule: &Value) -> i64 {
    let base = policy
        .get("global_cooldown_minutes")
        .and_then(Value::as_i64)
        .unwrap_or(30);
    let multiplier = rule
        .get("cooldown_multiplier")
        .and_then(Value::as_f64)
        .unwrap_or(1.0);
    (base as f64 * multiplier).round().max(1.0) as i64
}

fn care_allowed(tone_hint: &str) -> CareDecision {
    CareDecision {
        allow: true,
        reason: String::new(),
        next_delay_minutes: None,
        tone_hint: tone_hint.to_owned(),
    }
}

fn care_blocked(reason: &str, delay: i64, tone_hint: &str) -> CareDecision {
    CareDecision {
        allow: false,
        reason: reason.to_owned(),
        next_delay_minutes: Some(delay.max(1)),
        tone_hint: tone_hint.to_owned(),
    }
}

fn mark_proactive_care_result(policy: &mut Value, now: LocalDateTime, skip_reason: &str) {
    let Some(policy) = policy.as_object_mut() else {
        return;
    };
    if skip_reason.is_empty() {
        policy.insert("last_care_at".to_owned(), Value::String(now.isoformat()));
        policy.insert("last_skip_reason".to_owned(), Value::String(String::new()));
    } else {
        policy.insert(
            "last_skip_reason".to_owned(),
            Value::String(truncate_chars(skip_reason, 160)),
        );
    }
}

pub fn tick_reminders(
    alarms: &mut [Alarm],
    pomodoros: &mut [Pomodoro],
    now: LocalDateTime,
) -> Vec<Value> {
    let mut events = Vec::new();
    for alarm in alarms {
        if !alarm.enabled {
            continue;
        }
        let Some(next_at) = LocalDateTime::parse(&alarm.next_at) else {
            continue;
        };
        if next_at > now {
            continue;
        }
        events.push(json!({
            "kind": "alarm",
            "title": "闹钟提醒",
            "notification_title": "闹钟提醒",
            "character": alarm.character,
            "description": alarm.description,
            "time": alarm.time,
            "scheduled_at": next_at.isoformat(),
            "repeat_label": repeat_days_label(&alarm.repeat_days),
            "triggered_at": now.isoformat(),
        }));
        alarm.last_triggered_at = now.isoformat();
        if alarm.repeat_days.is_empty() {
            alarm.enabled = false;
            alarm.next_at.clear();
        } else {
            alarm.next_at =
                compute_next_alarm_at(&alarm.time, &alarm.repeat_days, now.add_seconds(30), "")
                    .map(LocalDateTime::isoformat)
                    .unwrap_or_default();
        }
    }
    for pomodoro in pomodoros {
        if pomodoro.status != "running" {
            continue;
        }
        let Some(next_at) = LocalDateTime::parse(&pomodoro.next_at) else {
            continue;
        };
        if next_at > now {
            continue;
        }
        advance_pomodoro(pomodoro, now, &mut events);
    }
    events
}

pub fn tick_config_reminders(
    config_path: &Path,
    now: LocalDateTime,
) -> Result<Vec<Value>, ConfigError> {
    tick_config_reminders_with_desktop_state(config_path, now, &Value::Null, false)
}

pub fn tick_config_reminders_with_desktop_state(
    config_path: &Path,
    now: LocalDateTime,
    desktop_state: &Value,
    defer_overdue_proactive: bool,
) -> Result<Vec<Value>, ConfigError> {
    let mut config = ConfigDocument::load(config_path)?;
    let mut alarms = normalize_alarms(config.get("alarms").unwrap_or(&Value::Null), now);
    let mut pomodoros = normalize_pomodoros(config.get("pomodoros").unwrap_or(&Value::Null), now);
    let mut proactive = normalize_proactive_companion(
        config.get("proactive_companion").unwrap_or(&Value::Null),
        now,
    );
    let mut care_policy = normalize_proactive_care_policy(
        config.get("proactive_care_policy").unwrap_or(&Value::Null),
    );
    let normalized_alarms =
        serde_json::to_value(&alarms).expect("normalized alarm serialization cannot fail");
    let normalized_pomodoros =
        serde_json::to_value(&pomodoros).expect("normalized pomodoro serialization cannot fail");
    let normalized_proactive = serde_json::to_value(&proactive)
        .expect("normalized proactive companion serialization cannot fail");
    let mut changed = config.get("alarms") != Some(&normalized_alarms)
        || config.get("pomodoros") != Some(&normalized_pomodoros)
        || config.get("proactive_companion") != Some(&normalized_proactive)
        || config.get("proactive_care_policy") != Some(&care_policy);
    let mut events = tick_reminders(&mut alarms, &mut pomodoros, now);
    if !events.is_empty() {
        changed = true;
    }
    if proactive.enabled && defer_overdue_proactive {
        for item in &mut proactive.items {
            if item.enabled
                && LocalDateTime::parse(&item.next_at).is_some_and(|next_at| next_at <= now)
            {
                item.next_at = compute_next_proactive_at(item, now)
                    .map(LocalDateTime::isoformat)
                    .unwrap_or_default();
                changed = true;
            }
        }
    } else if proactive.enabled {
        let default_proactive_character = proactive.character.clone();
        for item in &mut proactive.items {
            if !item.enabled {
                continue;
            }
            let Some(next_at) = LocalDateTime::parse(&item.next_at) else {
                continue;
            };
            if next_at > now {
                continue;
            }
            let decision = evaluate_proactive_care(&care_policy, &item.kind, desktop_state, now);
            if decision.allow {
                events.push(json!({
                    "kind": "proactive_companion",
                    "proactive_kind": item.kind,
                    "title": item.title,
                    "notification_title": "生活节奏提醒",
                    "character": first_nonempty(&[
                        item.character.clone(),
                        default_proactive_character.clone(),
                    ]),
                    "description": item.description,
                    "scheduled_at": next_at.isoformat(),
                    "triggered_at": now.isoformat(),
                    "schedule_type": item.schedule_type,
                    "interval_minutes": item.interval_minutes.unwrap_or_default(),
                    "active_start": item.active_start.clone().unwrap_or_default(),
                    "active_end": item.active_end.clone().unwrap_or_default(),
                    "care_policy": decision,
                }));
                item.last_triggered_at = now.isoformat();
                item.next_at = compute_next_proactive_at(item, now.add_seconds(30))
                    .map(LocalDateTime::isoformat)
                    .unwrap_or_default();
                mark_proactive_care_result(&mut care_policy, now, "");
            } else {
                item.next_at = now
                    .add_seconds(decision.next_delay_minutes.unwrap_or(1).max(1) * 60)
                    .isoformat();
                mark_proactive_care_result(&mut care_policy, now, &decision.reason);
            }
            changed = true;
        }
    }
    let display_mode = config
        .get("reminder_display_mode")
        .and_then(Value::as_str)
        .filter(|mode| matches!(*mode, "floating" | "system"))
        .unwrap_or("floating")
        .to_owned();
    let default_character = config
        .get("models")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|model| model.get("character").and_then(Value::as_str))
        .map(str::trim)
        .find(|character| !character.is_empty())
        .unwrap_or_default()
        .to_owned();
    for event in &mut events {
        if let Some(event) = event.as_object_mut() {
            event.insert(
                "display_mode".to_owned(),
                Value::String(display_mode.clone()),
            );
            let missing_character = event
                .get("character")
                .and_then(Value::as_str)
                .is_none_or(|character| character.trim().is_empty());
            if missing_character && !default_character.is_empty() {
                event.insert(
                    "character".to_owned(),
                    Value::String(default_character.clone()),
                );
            }
        }
    }
    if changed {
        config.set(
            "alarms",
            serde_json::to_value(alarms).expect("alarm serialization cannot fail"),
        );
        config.set(
            "pomodoros",
            serde_json::to_value(pomodoros).expect("pomodoro serialization cannot fail"),
        );
        config.set(
            "proactive_companion",
            serde_json::to_value(proactive).expect("proactive companion serialization cannot fail"),
        );
        config.set("proactive_care_policy", care_policy);
        config.save(config_path)?;
    }
    Ok(events)
}

pub fn load_native_reminder_state(
    config_path: &Path,
    now: LocalDateTime,
) -> Result<NativeReminderState, NativeReminderError> {
    let config = ConfigDocument::load(config_path)?;
    Ok(reminder_state_from_config(&config, now))
}

pub fn mutate_native_reminders(
    config_path: &Path,
    now: LocalDateTime,
    command_json: &str,
    max_bytes: usize,
) -> Result<NativeReminderState, NativeReminderError> {
    if command_json.len() > max_bytes {
        return Err(NativeReminderError::InvalidOperation(format!(
            "command exceeds the {max_bytes} byte limit"
        )));
    }
    let command = serde_json::from_str::<NativeReminderMutation>(command_json)?;
    let mut config = ConfigDocument::load(config_path)?;
    let mut state = reminder_state_from_config(&config, now);
    match command {
        NativeReminderMutation::AddAlarm {
            time,
            repeat_days,
            description,
            character,
            date,
        } => {
            if state.alarms.len() >= 256 {
                return Err(NativeReminderError::InvalidOperation(
                    "at most 256 alarms can be saved".to_owned(),
                ));
            }
            let character = resolve_reminder_character(&config, &character)?;
            state.alarms.push(create_alarm(
                &time,
                &repeat_days,
                &description,
                &character,
                &date,
                now,
            )?);
        }
        NativeReminderMutation::ToggleAlarm { id, enabled } => {
            let id = required_id(&id)?;
            let alarm = state
                .alarms
                .iter_mut()
                .find(|alarm| alarm.id == id)
                .ok_or_else(|| {
                    NativeReminderError::InvalidOperation(
                        "selected alarm does not exist".to_owned(),
                    )
                })?;
            alarm.enabled = enabled;
            alarm.next_at.clear();
            state.alarms = normalize_alarms(
                &serde_json::to_value(&state.alarms).expect("alarm serialization cannot fail"),
                now,
            );
        }
        NativeReminderMutation::DeleteAlarm { id } => {
            let id = required_id(&id)?;
            let previous = state.alarms.len();
            state.alarms.retain(|alarm| alarm.id != id);
            if state.alarms.len() == previous {
                return Err(NativeReminderError::InvalidOperation(
                    "selected alarm does not exist".to_owned(),
                ));
            }
        }
        NativeReminderMutation::AddPomodoro {
            repeat_count,
            description,
            character,
        } => {
            if state.pomodoros.len() >= 256 {
                return Err(NativeReminderError::InvalidOperation(
                    "at most 256 Pomodoro timers can be saved".to_owned(),
                ));
            }
            let character = resolve_reminder_character(&config, &character)?;
            state
                .pomodoros
                .push(create_pomodoro(repeat_count, &description, &character, now));
        }
        NativeReminderMutation::DeletePomodoro { id } => {
            let id = required_id(&id)?;
            let previous = state.pomodoros.len();
            state.pomodoros.retain(|pomodoro| pomodoro.id != id);
            if state.pomodoros.len() == previous {
                return Err(NativeReminderError::InvalidOperation(
                    "selected Pomodoro timer does not exist".to_owned(),
                ));
            }
        }
        NativeReminderMutation::SetDisplayMode { mode } => {
            let mode = mode.trim().to_lowercase();
            if !matches!(mode.as_str(), "floating" | "system") {
                return Err(NativeReminderError::InvalidOperation(format!(
                    "unsupported reminder display mode: {mode}"
                )));
            }
            state.display_mode = mode;
        }
        NativeReminderMutation::SetProactive { enabled, character } => {
            state.proactive_companion.enabled = enabled;
            state.proactive_companion.character = if character.trim().is_empty() {
                String::new()
            } else {
                resolve_reminder_character(&config, &character)?
            };
        }
        NativeReminderMutation::UpdateProactiveItem {
            id,
            enabled,
            time,
            interval_minutes,
            active_start,
            active_end,
        } => {
            let id = required_id(&id)?;
            let item = state
                .proactive_companion
                .items
                .iter_mut()
                .find(|item| item.id == id)
                .ok_or_else(|| {
                    NativeReminderError::InvalidOperation(
                        "selected proactive reminder does not exist".to_owned(),
                    )
                })?;
            item.enabled = enabled;
            if item.schedule_type == "interval" {
                item.interval_minutes = Some(interval_minutes.unwrap_or(60).clamp(10, 480));
                item.active_start = Some(nonempty_or_else(normalize_time(&active_start), || {
                    item.active_start
                        .clone()
                        .unwrap_or_else(|| "09:00".to_owned())
                }));
                item.active_end = Some(nonempty_or_else(normalize_time(&active_end), || {
                    item.active_end
                        .clone()
                        .unwrap_or_else(|| "22:00".to_owned())
                }));
            } else {
                let normalized = normalize_time(&time);
                if normalized.is_empty() {
                    return Err(NativeReminderError::InvalidOperation(
                        "proactive reminder time is invalid".to_owned(),
                    ));
                }
                item.time = Some(normalized);
            }
            item.next_at.clear();
            state.proactive_companion = normalize_proactive_companion(
                &serde_json::to_value(&state.proactive_companion)
                    .expect("proactive companion serialization cannot fail"),
                now,
            );
        }
    }
    config.set("reminder_display_mode", json!(state.display_mode));
    config.set(
        "alarms",
        serde_json::to_value(&state.alarms).expect("alarm serialization cannot fail"),
    );
    config.set(
        "pomodoros",
        serde_json::to_value(&state.pomodoros).expect("pomodoro serialization cannot fail"),
    );
    config.set(
        "proactive_companion",
        serde_json::to_value(&state.proactive_companion)
            .expect("proactive companion serialization cannot fail"),
    );
    config.save(config_path)?;
    Ok(state)
}

fn reminder_state_from_config(config: &ConfigDocument, now: LocalDateTime) -> NativeReminderState {
    NativeReminderState {
        display_mode: config
            .get("reminder_display_mode")
            .and_then(Value::as_str)
            .filter(|mode| matches!(*mode, "floating" | "system"))
            .unwrap_or("floating")
            .to_owned(),
        alarms: normalize_alarms(config.get("alarms").unwrap_or(&Value::Null), now),
        pomodoros: normalize_pomodoros(config.get("pomodoros").unwrap_or(&Value::Null), now),
        proactive_companion: normalize_proactive_companion(
            config.get("proactive_companion").unwrap_or(&Value::Null),
            now,
        ),
    }
}

fn resolve_reminder_character(
    config: &ConfigDocument,
    requested: &str,
) -> Result<String, NativeReminderError> {
    let configured = config
        .get("models")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|model| model.get("character").and_then(Value::as_str))
        .map(str::trim)
        .filter(|character| !character.is_empty())
        .collect::<Vec<_>>();
    let requested = requested.trim();
    if requested.is_empty() {
        return Ok(configured.first().copied().unwrap_or_default().to_owned());
    }
    if configured.is_empty() || configured.contains(&requested) {
        Ok(requested.to_owned())
    } else {
        Err(NativeReminderError::InvalidOperation(
            "reminder character is not configured".to_owned(),
        ))
    }
}

fn required_id(value: &str) -> Result<&str, NativeReminderError> {
    let value = value.trim();
    if value.is_empty() || value.len() > 128 {
        Err(NativeReminderError::InvalidOperation(
            "reminder id is invalid".to_owned(),
        ))
    } else {
        Ok(value)
    }
}

fn default_repeat_count() -> i64 {
    1
}

fn advance_pomodoro(pomodoro: &mut Pomodoro, now: LocalDateTime, events: &mut Vec<Value>) {
    let duration;
    if pomodoro.phase == "focus" {
        pomodoro.completed_focus_count =
            (pomodoro.completed_focus_count + 1).min(pomodoro.repeat_count);
        let long_break = pomodoro.completed_focus_count % 4 == 0;
        pomodoro.phase = if long_break {
            "long_break".to_owned()
        } else {
            "short_break".to_owned()
        };
        duration = if long_break {
            LONG_BREAK_SECONDS
        } else {
            SHORT_BREAK_SECONDS
        };
        events.push(json!({
            "kind": "pomodoro_break",
            "title": "番茄钟休息",
            "notification_title": "番茄钟提醒",
            "character": pomodoro.character,
            "description": pomodoro.description,
            "completed": pomodoro.completed_focus_count,
            "repeat_count": pomodoro.repeat_count,
            "phase": pomodoro.phase,
            "is_final_break": pomodoro.completed_focus_count >= pomodoro.repeat_count,
            "triggered_at": now.isoformat(),
        }));
    } else if pomodoro.completed_focus_count >= pomodoro.repeat_count {
        pomodoro.status = "completed".to_owned();
        pomodoro.phase = "completed".to_owned();
        pomodoro.phase_started_at = now.isoformat();
        pomodoro.phase_duration_sec = 0;
        pomodoro.next_at.clear();
        pomodoro.updated_at = now.isoformat();
        events.push(json!({
            "kind": "pomodoro_done",
            "title": "番茄钟完成",
            "notification_title": "番茄钟提醒",
            "character": pomodoro.character,
            "description": pomodoro.description,
            "completed": pomodoro.completed_focus_count,
            "repeat_count": pomodoro.repeat_count,
            "triggered_at": now.isoformat(),
        }));
        return;
    } else {
        pomodoro.phase = "focus".to_owned();
        duration = FOCUS_SECONDS;
        events.push(json!({
            "kind": "pomodoro_focus",
            "title": "番茄钟专注",
            "notification_title": "番茄钟提醒",
            "character": pomodoro.character,
            "description": pomodoro.description,
            "completed": pomodoro.completed_focus_count,
            "repeat_count": pomodoro.repeat_count,
            "phase": "focus",
            "triggered_at": now.isoformat(),
        }));
    }
    pomodoro.phase_started_at = now.isoformat();
    pomodoro.phase_duration_sec = duration;
    pomodoro.next_at = now.add_seconds(duration).isoformat();
    pomodoro.updated_at = now.isoformat();
}

fn hour_candidates(chars: &[char], index: usize) -> Vec<(u32, usize)> {
    let Some(first) = chars.get(index).copied().filter(char::is_ascii_digit) else {
        return Vec::new();
    };
    let mut result = Vec::with_capacity(2);
    if matches!(first, '0' | '1') && chars.get(index + 1).is_some_and(char::is_ascii_digit) {
        result.push((digit(first) * 10 + digit(chars[index + 1]), 2));
    } else {
        result.push((digit(first), 1));
    }
    if first == '2' && matches!(chars.get(index + 1), Some('0'..='3')) {
        result.push((20 + digit(chars[index + 1]), 2));
    }
    result
}

fn digit(value: char) -> u32 {
    value as u32 - '0' as u32
}

fn repeat_day(value: &Value) -> Option<u32> {
    let text = value_text(value).trim().to_lowercase();
    let alias = match text.as_str() {
        "mon" | "monday" | "周一" | "星期一" => Some(0),
        "tue" | "tuesday" | "周二" | "星期二" => Some(1),
        "wed" | "wednesday" | "周三" | "星期三" => Some(2),
        "thu" | "thursday" | "周四" | "星期四" => Some(3),
        "fri" | "friday" | "周五" | "星期五" => Some(4),
        "sat" | "saturday" | "周六" | "星期六" => Some(5),
        "sun" | "sunday" | "周日" | "周天" | "星期日" | "星期天" => Some(6),
        _ => None,
    };
    alias.or_else(|| {
        let raw = text.parse::<i64>().ok()?;
        match raw {
            0..=6 => Some(raw as u32),
            7 => Some(6),
            _ => None,
        }
    })
}

fn parse_time_parts(value: &str) -> Option<(u32, u32)> {
    let (hour, minute) = value.split_once(':')?;
    Some((hour.parse().ok()?, minute.parse().ok()?))
}

fn parse_date(value: &str) -> Option<(i32, u32, u32)> {
    let mut parts = value.trim().split('-');
    let year = parts.next()?.parse().ok()?;
    let month = parts.next()?.parse().ok()?;
    let day = parts.next()?.parse().ok()?;
    if parts.next().is_some() || LocalDateTime::new(year, month, day, 0, 0, 0).is_none() {
        return None;
    }
    Some((year, month, day))
}

fn value_text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::Bool(value) => if *value { "True" } else { "False" }.to_owned(),
        Value::String(value) => value.clone(),
        Value::Number(value) => value.to_string(),
        other => other.to_string(),
    }
}

fn object_text(object: &Map<String, Value>, key: &str) -> String {
    object.get(key).map(value_text).unwrap_or_default()
}

fn coerce_bool(value: Option<&Value>, default: bool) -> bool {
    match value {
        Some(Value::Bool(value)) => *value,
        Some(Value::Number(value)) => value.as_f64().is_some_and(|value| value != 0.0),
        Some(value) => match value_text(value).trim().to_lowercase().as_str() {
            "1" | "true" | "yes" | "y" | "on" | "enabled" | "enable" | "开" | "开启" | "启用"
            | "是" => true,
            "0" | "false" | "no" | "n" | "off" | "disabled" | "disable" | "关" | "关闭"
            | "禁用" | "否" => false,
            _ => default,
        },
        None => default,
    }
}

fn coerce_i64(value: Option<&Value>, default: i64) -> i64 {
    value
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
        })
        .unwrap_or(default)
}

fn coerce_f64(value: Option<&Value>, default: f64) -> f64 {
    value
        .and_then(|value| {
            value
                .as_f64()
                .or_else(|| value.as_str().and_then(|value| value.parse().ok()))
        })
        .unwrap_or(default)
}

fn first_nonempty(values: &[String]) -> String {
    values
        .iter()
        .map(|value| value.trim())
        .find(|value| !value.is_empty())
        .unwrap_or_default()
        .to_owned()
}

fn nonempty_or_else(value: String, fallback: impl FnOnce() -> String) -> String {
    let value = value.trim();
    if value.is_empty() {
        fallback()
    } else {
        value.to_owned()
    }
}

fn truncate_chars(value: &str, max_chars: usize) -> String {
    value.chars().take(max_chars).collect()
}

fn new_reminder_id(prefix: &str) -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos() as u64)
        .unwrap_or_default();
    let value = nanos
        ^ u64::from(std::process::id()).rotate_left(17)
        ^ COUNTER.fetch_add(1, Ordering::Relaxed);
    format!("{prefix}_{:012x}", value & 0x0000_ffff_ffff_ffff)
}

fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        _ => 0,
    }
}

fn days_from_civil(year: i32, month: u32, day: u32) -> i64 {
    let year = i64::from(year) - i64::from(month <= 2);
    let era = year.div_euclid(400);
    let year_of_era = year - era * 400;
    let shifted_month = i64::from(month) + if month > 2 { -3 } else { 9 };
    let day_of_year = (153 * shifted_month + 2) / 5 + i64::from(day) - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

fn civil_from_days(days: i64) -> (i32, u32, u32) {
    let days = days + 719_468;
    let era = days.div_euclid(146_097);
    let day_of_era = days - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_prime + 2) / 5 + 1;
    let month = month_prime + if month_prime < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    (year as i32, month as u32, day as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn contract() -> Value {
        serde_json::from_str(include_str!("../../../compat/reminder_vectors.json")).unwrap()
    }

    #[test]
    fn generated_python_reminder_vectors_match_rust() {
        let contract = contract();
        let now = LocalDateTime::parse(contract["now"].as_str().unwrap()).unwrap();
        for case in contract["normalize_time"].as_array().unwrap() {
            assert_eq!(
                normalize_time(case["input"].as_str().unwrap()),
                case["expected"].as_str().unwrap()
            );
        }
        for case in contract["normalize_repeat_days"].as_array().unwrap() {
            assert_eq!(
                normalize_repeat_days(&case["input"]),
                serde_json::from_value::<Vec<u32>>(case["expected"].clone()).unwrap()
            );
        }
        for case in contract["next_alarm"].as_array().unwrap() {
            let repeat = normalize_repeat_days(&case["repeat"]);
            assert_eq!(
                compute_next_alarm_at(
                    case["time"].as_str().unwrap(),
                    &repeat,
                    now,
                    case["date"].as_str().unwrap(),
                )
                .map(LocalDateTime::isoformat)
                .unwrap_or_default(),
                case["expected"].as_str().unwrap()
            );
        }
        let alarm = create_alarm_with_id(
            "alarm_contract",
            "21:45",
            &json!("weekdays"),
            " 练琴 ",
            "ran",
            "",
            now,
        )
        .unwrap();
        assert_eq!(
            serde_json::to_value(alarm).unwrap(),
            contract["created_alarm"]
        );
        assert_eq!(
            serde_json::to_value(
                normalize_alarm(
                    &json!({
                        "id": "alarm_existing",
                        "enabled": "yes",
                        "time": "7点30",
                        "repeat": "周末",
                        "description": " x ".repeat(130),
                        "role": "kasumi",
                        "created_at": "2026-01-01T00:00:00",
                    }),
                    now,
                )
                .unwrap()
            )
            .unwrap(),
            contract["normalized_alarm"]
        );
        assert_eq!(
            serde_json::to_value(create_pomodoro_with_id(
                "pomodoro_contract",
                3,
                " 编曲 ",
                "moca",
                now,
            ))
            .unwrap(),
            contract["created_pomodoro"]
        );
        assert_eq!(
            serde_json::to_value(
                normalize_pomodoro(
                    &json!({
                        "id": "pomodoro_existing",
                        "status": "unknown",
                        "repeat_count": 99,
                        "completed_focus_count": -5,
                        "phase": "invalid",
                        "phase_duration_sec": 0,
                        "description": " demo ",
                        "role": "ran",
                    }),
                    now,
                )
                .unwrap()
            )
            .unwrap(),
            contract["normalized_pomodoro"]
        );
        assert_eq!(
            serde_json::to_value(normalize_proactive_companion(
                &json!({
                    "enabled":"yes",
                    "character":"anon",
                    "items":[
                        {"id":"water","enabled":false,"interval_minutes":9999},
                        {"id":"custom","kind":"stretch","title":" Custom ","time":"10点15"},
                        {"id":"desktop_state","kind":"desktop_state","time":"12:00"}
                    ]
                }),
                now,
            ))
            .unwrap(),
            contract["normalized_proactive_companion"]
        );
        for case in contract["next_proactive"].as_array().unwrap() {
            let after = LocalDateTime::parse(case["after"].as_str().unwrap()).unwrap();
            let item = normalize_proactive_item(Some(&case["item"]), None, after).unwrap();
            assert_eq!(
                compute_next_proactive_at(&item, after)
                    .map(LocalDateTime::isoformat)
                    .unwrap_or_default(),
                case["expected"].as_str().unwrap()
            );
        }
    }

    #[test]
    fn civil_time_arithmetic_handles_leap_days_and_python_weekdays() {
        let leap = LocalDateTime::parse("2024-02-28T23:59:30").unwrap();
        assert_eq!(leap.add_seconds(90).isoformat(), "2024-02-29T00:01:00");
        assert_eq!(
            LocalDateTime::parse("2026-07-13T00:00:00")
                .unwrap()
                .weekday(),
            0
        );
    }

    #[test]
    fn reminder_tick_advances_alarm_and_complete_pomodoro_state() {
        let now = LocalDateTime::parse("2026-07-15T11:00:00").unwrap();
        let mut alarms = vec![Alarm {
            id: "alarm_1".to_owned(),
            enabled: true,
            time: "11:00".to_owned(),
            repeat_days: Vec::new(),
            description: "练琴".to_owned(),
            character: "ran".to_owned(),
            created_at: "2026-07-15T10:00:00".to_owned(),
            next_at: now.isoformat(),
            last_triggered_at: String::new(),
        }];
        let mut pomodoros = vec![Pomodoro {
            id: "pomodoro_1".to_owned(),
            status: "running".to_owned(),
            repeat_count: 1,
            completed_focus_count: 0,
            phase: "focus".to_owned(),
            phase_started_at: "2026-07-15T10:35:00".to_owned(),
            phase_duration_sec: FOCUS_SECONDS,
            next_at: now.isoformat(),
            description: "编曲".to_owned(),
            character: "moca".to_owned(),
            created_at: "2026-07-15T10:35:00".to_owned(),
            updated_at: "2026-07-15T10:35:00".to_owned(),
        }];
        let events = tick_reminders(&mut alarms, &mut pomodoros, now);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0]["kind"], "alarm");
        assert!(!alarms[0].enabled);
        assert_eq!(events[1]["kind"], "pomodoro_break");
        assert_eq!(pomodoros[0].phase, "short_break");
        assert_eq!(pomodoros[0].completed_focus_count, 1);

        let break_end = now.add_seconds(SHORT_BREAK_SECONDS);
        let events = tick_reminders(&mut alarms, &mut pomodoros, break_end);
        assert_eq!(events[0]["kind"], "pomodoro_done");
        assert_eq!(pomodoros[0].status, "completed");
        assert!(pomodoros[0].next_at.is_empty());
    }

    #[test]
    fn duplicate_and_invalid_saved_reminders_are_dropped() {
        let now = LocalDateTime::parse("2026-07-15T10:30:00").unwrap();
        let alarms = normalize_alarms(
            &json!([
                {"id":"same","time":"11:00"},
                {"id":"same","time":"12:00"},
                {"id":"bad","time":"invalid"}
            ]),
            now,
        );
        assert_eq!(alarms.len(), 1);
        assert_eq!(alarms[0].time, "11:00");
    }

    #[test]
    fn proactive_normalization_restores_defaults_and_preserves_safe_custom_items() {
        let now = LocalDateTime::parse("2026-07-16T08:00:00").unwrap();
        let proactive = normalize_proactive_companion(
            &json!({
                "enabled":"yes",
                "character":"anon",
                "items":[
                    {"id":"water","enabled":false,"interval_minutes":9999},
                    {"id":"custom","kind":"stretch","title":" Custom ","time":"10点15"},
                    {"id":"desktop_state","kind":"desktop_state","time":"12:00"}
                ]
            }),
            now,
        );
        assert!(proactive.enabled);
        assert_eq!(proactive.character, "anon");
        assert_eq!(proactive.items.len(), 6);
        assert_eq!(proactive.items[0].id, "morning");
        assert_eq!(proactive.items[0].next_at, "2026-07-16T08:30:00");
        assert!(!proactive.items[1].enabled);
        assert_eq!(proactive.items[1].interval_minutes, Some(480));
        assert!(proactive.items[1].next_at.is_empty());
        assert_eq!(proactive.items[5].id, "custom");
        assert_eq!(proactive.items[5].time.as_deref(), Some("10:15"));
    }

    #[test]
    fn proactive_interval_respects_daytime_and_cross_midnight_windows() {
        let now = LocalDateTime::parse("2026-07-16T21:30:00").unwrap();
        let daytime = normalize_proactive_item(
            Some(&json!({
                "id":"water",
                "schedule_type":"interval",
                "interval_minutes":90,
                "active_start":"09:00",
                "active_end":"22:00"
            })),
            None,
            now,
        )
        .unwrap();
        assert_eq!(
            compute_next_proactive_at(&daytime, now)
                .unwrap()
                .isoformat(),
            "2026-07-17T09:00:00"
        );
        let overnight = normalize_proactive_item(
            Some(&json!({
                "id":"night",
                "schedule_type":"interval",
                "interval_minutes":60,
                "active_start":"22:00",
                "active_end":"06:00"
            })),
            None,
            now,
        )
        .unwrap();
        assert_eq!(
            compute_next_proactive_at(&overnight, now)
                .unwrap()
                .isoformat(),
            "2026-07-16T22:30:00"
        );
    }

    #[test]
    fn config_tick_persists_state_and_returns_display_delivery_metadata() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let now = LocalDateTime::parse("2026-07-15T11:00:00").unwrap();
        let mut config = ConfigDocument::default();
        config.set(
            "models",
            json!([{"character":"ran","path":"models/ran/model3.json"}]),
        );
        config.set("reminder_display_mode", json!("system"));
        config.set(
            "alarms",
            json!([{
                "id":"alarm_1",
                "enabled":true,
                "time":"11:00",
                "repeat_days":[],
                "description":"练琴",
                "character":"",
                "created_at":"2026-07-15T10:00:00",
                "next_at":"2026-07-15T11:00:00",
                "last_triggered_at":""
            }]),
        );
        config.save(&path).unwrap();

        let events = tick_config_reminders(&path, now).unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["display_mode"], "system");
        assert_eq!(events[0]["character"], "ran");
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(saved.get("alarms").unwrap()[0]["enabled"], false);
        assert_eq!(saved.get("alarms").unwrap()[0]["next_at"], "");
    }

    #[test]
    fn proactive_tick_uses_desktop_policy_and_persists_cooldown_state() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let now = LocalDateTime::parse("2026-07-16T10:30:00").unwrap();
        let mut config = ConfigDocument::default();
        config.set("models", json!([{"character":"anon"}]));
        config.set(
            "proactive_companion",
            json!({
                "enabled":true,
                "character":"anon",
                "items":[{
                    "id":"water",
                    "enabled":true,
                    "kind":"water",
                    "title":"喝水提醒",
                    "description":"喝点水",
                    "schedule_type":"interval",
                    "interval_minutes":90,
                    "active_start":"09:00",
                    "active_end":"22:00",
                    "next_at":"2026-07-16T10:30:00"
                }]
            }),
        );
        config.set(
            "proactive_care_policy",
            json!({"global_cooldown_minutes":30}),
        );
        config.save(&path).unwrap();

        let events =
            tick_config_reminders_with_desktop_state(&path, now, &json!({"state":"coding"}), false)
                .unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0]["kind"], "proactive_companion");
        assert_eq!(events[0]["proactive_kind"], "water");
        assert_eq!(
            events[0]["care_policy"]["tone_hint"],
            "用户可能正在专注，语气要轻，不要要求立即回应。"
        );
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(
            saved.get("proactive_care_policy").unwrap()["last_care_at"],
            now.isoformat()
        );
        assert_eq!(
            saved.get("proactive_companion").unwrap()["items"][1]["next_at"],
            "2026-07-16T12:00:30"
        );
    }

    #[test]
    fn proactive_quiet_hours_reschedule_without_marking_triggered() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let now = LocalDateTime::parse("2026-07-16T23:45:00").unwrap();
        let mut config = ConfigDocument::default();
        config.set(
            "proactive_companion",
            json!({
                "enabled":true,
                "items":[{
                    "id":"bedtime",
                    "enabled":true,
                    "kind":"bedtime",
                    "schedule_type":"daily",
                    "time":"23:30",
                    "next_at":"2026-07-16T23:30:00",
                    "last_triggered_at":""
                }]
            }),
        );
        config.set(
            "proactive_care_policy",
            json!({
                "quiet_hours_enabled":true,
                "quiet_start":"23:30",
                "quiet_end":"08:00",
                "global_cooldown_minutes":30
            }),
        );
        config.save(&path).unwrap();

        let events = tick_config_reminders_with_desktop_state(
            &path,
            now,
            &json!({"state":"desktop"}),
            false,
        )
        .unwrap();
        assert!(events.is_empty());
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(
            saved.get("proactive_care_policy").unwrap()["last_skip_reason"],
            "quiet_hours"
        );
        assert_eq!(
            saved.get("proactive_companion").unwrap()["items"][4]["next_at"],
            "2026-07-17T00:15:00"
        );
        assert_eq!(
            saved.get("proactive_companion").unwrap()["items"][4]["last_triggered_at"],
            ""
        );
    }

    #[test]
    fn first_native_tick_defers_overdue_proactive_items_without_delivery() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let now = LocalDateTime::parse("2026-07-16T10:30:00").unwrap();
        let mut config = ConfigDocument::default();
        config.set(
            "proactive_companion",
            json!({
                "enabled":true,
                "items":[{
                    "id":"water",
                    "enabled":true,
                    "schedule_type":"interval",
                    "interval_minutes":90,
                    "active_start":"09:00",
                    "active_end":"22:00",
                    "next_at":"2026-07-15T10:00:00",
                    "last_triggered_at":""
                }]
            }),
        );
        config.save(&path).unwrap();

        let events =
            tick_config_reminders_with_desktop_state(&path, now, &json!({"state":"desktop"}), true)
                .unwrap();
        assert!(events.is_empty());
        let saved = ConfigDocument::load(&path).unwrap();
        assert_eq!(
            saved.get("proactive_companion").unwrap()["items"][1]["next_at"],
            "2026-07-16T12:00:00"
        );
        assert_eq!(
            saved.get("proactive_companion").unwrap()["items"][1]["last_triggered_at"],
            ""
        );
    }

    #[test]
    fn native_management_commands_are_whitelisted_owned_and_atomic() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let now = LocalDateTime::parse("2026-07-15T10:30:00").unwrap();
        let mut config = ConfigDocument::default();
        config.set(
            "models",
            json!([{"character":"ran","path":"models/ran/model3.json"}]),
        );
        config.save(&path).unwrap();

        let state = mutate_native_reminders(
            &path,
            now,
            r#"{"op":"add_alarm","time":"21:45","repeat_days":"weekdays","description":"练琴","character":"ran"}"#,
            4096,
        )
        .unwrap();
        assert_eq!(state.alarms.len(), 1);
        assert_eq!(state.alarms[0].repeat_days, vec![0, 1, 2, 3, 4]);
        let alarm_id = state.alarms[0].id.clone();

        let state = mutate_native_reminders(
            &path,
            now,
            &json!({"op":"toggle_alarm","id":alarm_id,"enabled":false}).to_string(),
            4096,
        )
        .unwrap();
        assert!(!state.alarms[0].enabled);
        assert!(state.alarms[0].next_at.is_empty());

        let state = mutate_native_reminders(
            &path,
            now,
            r#"{"op":"add_pomodoro","repeat_count":2,"description":"编曲","character":"ran"}"#,
            4096,
        )
        .unwrap();
        assert_eq!(state.pomodoros.len(), 1);
        let pomodoro_id = state.pomodoros[0].id.clone();
        let state = mutate_native_reminders(
            &path,
            now,
            &json!({"op":"delete_pomodoro","id":pomodoro_id}).to_string(),
            4096,
        )
        .unwrap();
        assert!(state.pomodoros.is_empty());

        assert!(
            mutate_native_reminders(
                &path,
                now,
                r#"{"op":"add_alarm","time":"12:00","character":"unknown"}"#,
                4096,
            )
            .is_err()
        );
        assert!(
            mutate_native_reminders(&path, now, r#"{"op":"delete_alarm","id":"missing"}"#, 4096,)
                .is_err()
        );
        assert_eq!(
            load_native_reminder_state(&path, now).unwrap().alarms.len(),
            1
        );
        let state = mutate_native_reminders(
            &path,
            now,
            r#"{"op":"set_display_mode","mode":"system"}"#,
            4096,
        )
        .unwrap();
        assert_eq!(state.display_mode, "system");
        let state = mutate_native_reminders(
            &path,
            now,
            r#"{"op":"set_proactive","enabled":true,"character":"ran"}"#,
            4096,
        )
        .unwrap();
        assert!(state.proactive_companion.enabled);
        assert_eq!(state.proactive_companion.character, "ran");
        let state = mutate_native_reminders(
            &path,
            now,
            r#"{"op":"update_proactive_item","id":"water","enabled":true,"interval_minutes":5,"active_start":"08:00","active_end":"23:00"}"#,
            4096,
        )
        .unwrap();
        assert_eq!(
            state.proactive_companion.items[1].interval_minutes,
            Some(10)
        );
        assert_eq!(
            state.proactive_companion.items[1].active_start.as_deref(),
            Some("08:00")
        );
        assert!(!state.proactive_companion.items[1].next_at.is_empty());
        assert!(
            mutate_native_reminders(
                &path,
                now,
                r#"{"op":"set_display_mode","mode":"system","unexpected":true}"#,
                4096,
            )
            .is_err()
        );
        let state = mutate_native_reminders(
            &path,
            now,
            &json!({"op":"delete_alarm","id":alarm_id}).to_string(),
            4096,
        )
        .unwrap();
        assert!(state.alarms.is_empty());
        assert_eq!(
            ConfigDocument::load(&path)
                .unwrap()
                .get("reminder_display_mode"),
            Some(&json!("system"))
        );
    }
}
