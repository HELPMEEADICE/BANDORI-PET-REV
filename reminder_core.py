from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta


ALARM_CONFIG_KEY = "alarms"
POMODORO_CONFIG_KEY = "pomodoros"
REMINDER_DISPLAY_MODE_KEY = "reminder_display_mode"

DISPLAY_MODE_FLOATING = "floating"
DISPLAY_MODE_SYSTEM = "system"
DISPLAY_MODES = {DISPLAY_MODE_FLOATING, DISPLAY_MODE_SYSTEM}

WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
FOCUS_SECONDS = 25 * 60
SHORT_BREAK_SECONDS = 5 * 60
LONG_BREAK_SECONDS = 15 * 60


def local_now() -> datetime:
    return datetime.now().replace(microsecond=0)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def parse_iso_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def isoformat(dt: datetime | None) -> str:
    return dt.replace(microsecond=0).isoformat(timespec="seconds") if dt else ""


def normalize_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(?<!\d)([01]?\d|2[0-3])[:：点时]([0-5]\d)?", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        return f"{hour:02d}:{minute:02d}"
    match = re.search(r"(?<!\d)([01]?\d|2[0-3])(?=\D*$)", text)
    if match:
        return f"{int(match.group(1)):02d}:00"
    return ""


def normalize_repeat_days(value) -> list[int]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"none", "once", "no_repeat", "不重复", "单次"}:
            return []
        if lowered in {"daily", "everyday", "每天", "每日"}:
            return list(range(7))
        if lowered in {"weekdays", "workdays", "工作日"}:
            return [0, 1, 2, 3, 4]
        if lowered in {"weekends", "周末"}:
            return [5, 6]
        parts = re.split(r"[,，、\s]+", lowered)
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = [value]

    aliases = {
        "mon": 0, "monday": 0, "周一": 0, "星期一": 0, "1": 0,
        "tue": 1, "tuesday": 1, "周二": 1, "星期二": 1, "2": 1,
        "wed": 2, "wednesday": 2, "周三": 2, "星期三": 2, "3": 2,
        "thu": 3, "thursday": 3, "周四": 3, "星期四": 3, "4": 3,
        "fri": 4, "friday": 4, "周五": 4, "星期五": 4, "5": 4,
        "sat": 5, "saturday": 5, "周六": 5, "星期六": 5, "6": 5,
        "sun": 6, "sunday": 6, "周日": 6, "周天": 6, "星期日": 6, "星期天": 6, "7": 6, "0": 6,
    }
    result = []
    seen = set()
    for part in parts:
        key = str(part).strip().lower() if not isinstance(part, int) else part
        day = aliases.get(key)
        if day is None:
            try:
                raw = int(part)
            except (TypeError, ValueError):
                continue
            day = raw if 0 <= raw <= 6 else raw - 1 if 1 <= raw <= 7 else None
        if day is not None and day not in seen:
            result.append(day)
            seen.add(day)
    result.sort()
    return result


def repeat_days_label(days: list[int]) -> str:
    days = normalize_repeat_days(days)
    if not days:
        return "不重复"
    if days == list(range(7)):
        return "每天"
    if days == [0, 1, 2, 3, 4]:
        return "工作日"
    if days == [5, 6]:
        return "周末"
    return "、".join(WEEKDAY_LABELS[day] for day in days)


def compute_next_alarm_at(time_text: str, repeat_days=None, after: datetime | None = None, date_text: str = "") -> datetime | None:
    time_text = normalize_time(time_text)
    if not time_text:
        return None
    after = (after or local_now()).replace(microsecond=0)
    hour, minute = [int(part) for part in time_text.split(":", 1)]
    repeat_days = normalize_repeat_days(repeat_days)

    if not repeat_days and date_text:
        try:
            date = datetime.strptime(str(date_text).strip(), "%Y-%m-%d").date()
        except ValueError:
            date = None
        if date:
            candidate = datetime.combine(date, datetime.min.time()).replace(hour=hour, minute=minute)
            if candidate > after:
                return candidate

    for offset in range(0, 15):
        date = (after + timedelta(days=offset)).date()
        candidate = datetime.combine(date, datetime.min.time()).replace(hour=hour, minute=minute)
        if candidate <= after:
            continue
        if not repeat_days or candidate.weekday() in repeat_days:
            return candidate
    return None


def normalize_alarm(item, now: datetime | None = None) -> dict | None:
    if not isinstance(item, dict):
        return None
    now = now or local_now()
    time_text = normalize_time(item.get("time", ""))
    if not time_text:
        return None
    repeat_days = normalize_repeat_days(item.get("repeat_days", item.get("repeat", [])))
    enabled = bool(item.get("enabled", True))
    next_at = parse_iso_datetime(item.get("next_at"))
    if enabled and next_at is None:
        next_at = compute_next_alarm_at(time_text, repeat_days, now)
    return {
        "id": str(item.get("id") or new_id("alarm")),
        "enabled": enabled,
        "time": time_text,
        "repeat_days": repeat_days,
        "description": str(item.get("description", "") or "").strip()[:240],
        "character": str(item.get("character", "") or item.get("role", "") or "").strip(),
        "created_at": str(item.get("created_at") or isoformat(now)),
        "next_at": isoformat(next_at),
        "last_triggered_at": str(item.get("last_triggered_at", "") or ""),
    }


def normalize_alarms(value, now: datetime | None = None) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        alarm = normalize_alarm(item, now)
        if not alarm or alarm["id"] in seen:
            continue
        result.append(alarm)
        seen.add(alarm["id"])
    return result


def create_alarm(time_text: str, repeat_days=None, description: str = "", character: str = "", date_text: str = "", now: datetime | None = None) -> dict:
    now = now or local_now()
    normalized_time = normalize_time(time_text)
    if not normalized_time:
        raise ValueError("time is required")
    days = normalize_repeat_days(repeat_days)
    next_at = compute_next_alarm_at(normalized_time, days, now, date_text=date_text)
    if next_at is None:
        raise ValueError("cannot compute next alarm time")
    return {
        "id": new_id("alarm"),
        "enabled": True,
        "time": normalized_time,
        "repeat_days": days,
        "description": str(description or "").strip()[:240],
        "character": str(character or "").strip(),
        "created_at": isoformat(now),
        "next_at": isoformat(next_at),
        "last_triggered_at": "",
    }


def clamp_repeat_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 1
    return max(1, min(24, count))


def normalize_pomodoro(item, now: datetime | None = None) -> dict | None:
    if not isinstance(item, dict):
        return None
    now = now or local_now()
    repeat_count = clamp_repeat_count(item.get("repeat_count", 1))
    completed = max(0, min(repeat_count, int(item.get("completed_focus_count", 0) or 0)))
    status = str(item.get("status", "running") or "running").strip().lower()
    if status not in {"running", "paused", "completed", "cancelled"}:
        status = "running"
    phase = str(item.get("phase", "focus") or "focus").strip().lower()
    if phase not in {"focus", "short_break", "long_break", "completed"}:
        phase = "focus"
    duration = int(item.get("phase_duration_sec", 0) or 0)
    if duration <= 0:
        duration = FOCUS_SECONDS if phase == "focus" else LONG_BREAK_SECONDS if phase == "long_break" else SHORT_BREAK_SECONDS
    next_at = parse_iso_datetime(item.get("next_at"))
    if status == "running" and next_at is None:
        next_at = now + timedelta(seconds=duration)
    return {
        "id": str(item.get("id") or new_id("pomodoro")),
        "status": status,
        "repeat_count": repeat_count,
        "completed_focus_count": completed,
        "phase": phase,
        "phase_started_at": str(item.get("phase_started_at") or isoformat(now)),
        "phase_duration_sec": duration,
        "next_at": isoformat(next_at),
        "description": str(item.get("description", "") or "").strip()[:240],
        "character": str(item.get("character", "") or item.get("role", "") or "").strip(),
        "created_at": str(item.get("created_at") or isoformat(now)),
        "updated_at": str(item.get("updated_at") or isoformat(now)),
    }


def normalize_pomodoros(value, now: datetime | None = None) -> list[dict]:
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        pomodoro = normalize_pomodoro(item, now)
        if not pomodoro or pomodoro["id"] in seen:
            continue
        result.append(pomodoro)
        seen.add(pomodoro["id"])
    return result


def create_pomodoro(repeat_count=1, description: str = "", character: str = "", now: datetime | None = None) -> dict:
    now = now or local_now()
    return {
        "id": new_id("pomodoro"),
        "status": "running",
        "repeat_count": clamp_repeat_count(repeat_count),
        "completed_focus_count": 0,
        "phase": "focus",
        "phase_started_at": isoformat(now),
        "phase_duration_sec": FOCUS_SECONDS,
        "next_at": isoformat(now + timedelta(seconds=FOCUS_SECONDS)),
        "description": str(description or "").strip()[:240],
        "character": str(character or "").strip(),
        "created_at": isoformat(now),
        "updated_at": isoformat(now),
    }


def pomodoro_phase_label(phase: str) -> str:
    return {
        "focus": "专注中",
        "short_break": "短休息",
        "long_break": "长休息",
        "completed": "已完成",
    }.get(str(phase or ""), str(phase or ""))


def normalize_display_mode(value) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in DISPLAY_MODES else DISPLAY_MODE_FLOATING


def default_reminder_character(config) -> str:
    models = config.get("models", []) if config else []
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict):
                character = str(item.get("character", "") or "").strip()
                if character:
                    return character
    return str(config.get("character", "") or "").strip() if config else ""
