use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::HashSet;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

pub const FOCUS_SECONDS: i64 = 25 * 60;
pub const SHORT_BREAK_SECONDS: i64 = 5 * 60;
pub const LONG_BREAK_SECONDS: i64 = 15 * 60;

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

#[derive(Debug, Error, Eq, PartialEq)]
pub enum ReminderError {
    #[error("time is required")]
    TimeRequired,
    #[error("cannot compute next alarm time")]
    CannotComputeNextAlarm,
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
}
