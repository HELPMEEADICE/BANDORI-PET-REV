from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from i18n_manager import tr as _tr


ALARM_CONFIG_KEY = "alarms"
POMODORO_CONFIG_KEY = "pomodoros"
REMINDER_DISPLAY_MODE_KEY = "reminder_display_mode"
SCREEN_AWARENESS_DISPLAY_MODE_KEY = "screen_awareness_display_mode"
PROACTIVE_COMPANION_CONFIG_KEY = "proactive_companion"
PROACTIVE_CARE_POLICY_CONFIG_KEY = "proactive_care_policy"

DISPLAY_MODE_FLOATING = "floating"
DISPLAY_MODE_SYSTEM = "system"
DISPLAY_MODES = {DISPLAY_MODE_FLOATING, DISPLAY_MODE_SYSTEM}

FOCUS_SECONDS = 25 * 60
SHORT_BREAK_SECONDS = 5 * 60
LONG_BREAK_SECONDS = 15 * 60

PROACTIVE_DAILY = "daily"
PROACTIVE_INTERVAL = "interval"

DEFAULT_PROACTIVE_ITEMS = (
    {
        "id": "morning",
        "enabled": True,
        "kind": "morning",
        "title": "早安问候",
        "description": "早上问候用户，轻轻确认今天要做什么。",
        "schedule_type": PROACTIVE_DAILY,
        "time": "08:30",
    },
    {
        "id": "water",
        "enabled": True,
        "kind": "water",
        "title": "喝水提醒",
        "description": "提醒用户喝水，语气自然一点。",
        "schedule_type": PROACTIVE_INTERVAL,
        "interval_minutes": 90,
        "active_start": "09:00",
        "active_end": "22:00",
    },
    {
        "id": "sedentary",
        "enabled": True,
        "kind": "sedentary",
        "title": "久坐提醒",
        "description": "提醒用户站起来活动一下，照顾肩颈和眼睛。",
        "schedule_type": PROACTIVE_INTERVAL,
        "interval_minutes": 60,
        "active_start": "09:00",
        "active_end": "22:00",
    },
    {
        "id": "evening_review",
        "enabled": True,
        "kind": "evening_review",
        "title": "计划复盘",
        "description": "提醒用户简单复盘今天的计划、完成情况和明天要处理的事。",
        "schedule_type": PROACTIVE_DAILY,
        "time": "21:30",
    },
    {
        "id": "bedtime",
        "enabled": True,
        "kind": "bedtime",
        "title": "睡前提醒",
        "description": "提醒用户差不多该收尾休息了。",
        "schedule_type": PROACTIVE_DAILY,
        "time": "23:30",
    },
)


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
        "mon": 0, "monday": 0, "周一": 0, "星期一": 0,
        "tue": 1, "tuesday": 1, "周二": 1, "星期二": 1,
        "wed": 2, "wednesday": 2, "周三": 2, "星期三": 2,
        "thu": 3, "thursday": 3, "周四": 3, "星期四": 3,
        "fri": 4, "friday": 4, "周五": 4, "星期五": 4,
        "sat": 5, "saturday": 5, "周六": 5, "星期六": 5,
        "sun": 6, "sunday": 6, "周日": 6, "周天": 6, "星期日": 6, "星期天": 6,
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
        return _tr("ReminderCore.repeat_no_repeat", default="不重复")
    if days == list(range(7)):
        return _tr("ReminderCore.repeat_daily", default="每天")
    if days == [0, 1, 2, 3, 4]:
        return _tr("ReminderCore.repeat_weekdays", default="工作日")
    if days == [5, 6]:
        return _tr("ReminderCore.repeat_weekends", default="周末")
    weekday_labels = (
        _tr("ReminderCore.weekday_mon", default="周一"),
        _tr("ReminderCore.weekday_tue", default="周二"),
        _tr("ReminderCore.weekday_wed", default="周三"),
        _tr("ReminderCore.weekday_thu", default="周四"),
        _tr("ReminderCore.weekday_fri", default="周五"),
        _tr("ReminderCore.weekday_sat", default="周六"),
        _tr("ReminderCore.weekday_sun", default="周日"),
    )
    separator = _tr("ReminderCore.weekday_separator", default="、")
    return separator.join(weekday_labels[day] for day in days)


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


def _clamp_minutes(value, default: int, minimum: int, maximum: int) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = default
    return max(minimum, min(maximum, minutes))


def _coerce_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "enabled", "enable", "开", "开启", "启用", "是"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "disable", "关", "关闭", "禁用", "否"}:
        return False
    return default


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _minutes_of_day(time_text: str) -> int | None:
    normalized = normalize_time(time_text)
    if not normalized:
        return None
    hour, minute = [int(part) for part in normalized.split(":", 1)]
    return hour * 60 + minute


def _is_in_active_window(dt: datetime, active_start: str, active_end: str) -> bool:
    start = _minutes_of_day(active_start)
    end = _minutes_of_day(active_end)
    if start is None or end is None:
        return True
    current = dt.hour * 60 + dt.minute
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _next_active_window_start(after: datetime, active_start: str, active_end: str) -> datetime | None:
    start = _minutes_of_day(active_start)
    end = _minutes_of_day(active_end)
    if start is None or end is None:
        return after
    for offset in range(0, 3):
        date = (after + timedelta(days=offset)).date()
        candidate = datetime.combine(date, datetime.min.time()) + timedelta(minutes=start)
        if candidate <= after:
            continue
        return candidate
    return None


def compute_next_proactive_at(item: dict, after: datetime | None = None) -> datetime | None:
    if not isinstance(item, dict):
        return None
    after = (after or local_now()).replace(microsecond=0)
    schedule_type = str(item.get("schedule_type") or PROACTIVE_DAILY).strip().lower()
    if schedule_type == PROACTIVE_DAILY:
        return compute_next_alarm_at(item.get("time", ""), list(range(7)), after)

    interval = _clamp_minutes(item.get("interval_minutes"), 60, 10, 480)
    active_start = normalize_time(item.get("active_start") or "09:00") or "09:00"
    active_end = normalize_time(item.get("active_end") or "22:00") or "22:00"
    candidate = after + timedelta(minutes=interval)
    if _is_in_active_window(candidate, active_start, active_end):
        return candidate
    return _next_active_window_start(after, active_start, active_end)


def normalize_alarm(item, now: datetime | None = None) -> dict | None:
    if not isinstance(item, dict):
        return None
    now = now or local_now()
    time_text = normalize_time(item.get("time", ""))
    if not time_text:
        return None
    repeat_days = normalize_repeat_days(item.get("repeat_days", item.get("repeat", [])))
    enabled = _coerce_bool(item.get("enabled", True), True)
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


def _default_proactive_item_map() -> dict[str, dict]:
    return {str(item["id"]): dict(item) for item in DEFAULT_PROACTIVE_ITEMS}


def normalize_proactive_item(item, template: dict | None = None, now: datetime | None = None) -> dict | None:
    if not isinstance(item, dict):
        item = {}
    template = dict(template or {})
    merged = dict(template)
    merged.update(item)
    item_id = str(merged.get("id") or "").strip()
    if not item_id:
        return None
    now = now or local_now()
    schedule_type = str(merged.get("schedule_type") or PROACTIVE_DAILY).strip().lower()
    if schedule_type not in {PROACTIVE_DAILY, PROACTIVE_INTERVAL}:
        schedule_type = PROACTIVE_DAILY
    normalized = {
        "id": item_id,
        "enabled": _coerce_bool(merged.get("enabled", True), True),
        "kind": str(merged.get("kind") or item_id).strip(),
        "title": str(merged.get("title") or item_id).strip()[:80],
        "description": str(merged.get("description") or "").strip()[:240],
        "schedule_type": schedule_type,
        "character": str(merged.get("character", "") or "").strip(),
        "next_at": str(merged.get("next_at", "") or ""),
        "last_triggered_at": str(merged.get("last_triggered_at", "") or ""),
    }
    if schedule_type == PROACTIVE_DAILY:
        normalized["time"] = normalize_time(merged.get("time", "")) or normalize_time(template.get("time", "")) or "08:30"
    else:
        normalized["interval_minutes"] = _clamp_minutes(merged.get("interval_minutes"), template.get("interval_minutes", 60), 10, 480)
        normalized["active_start"] = normalize_time(merged.get("active_start", "")) or normalize_time(template.get("active_start", "")) or "09:00"
        normalized["active_end"] = normalize_time(merged.get("active_end", "")) or normalize_time(template.get("active_end", "")) or "22:00"

    if normalized["enabled"]:
        next_at = parse_iso_datetime(normalized.get("next_at"))
        if next_at is None:
            next_at = compute_next_proactive_at(normalized, now)
        normalized["next_at"] = isoformat(next_at)
    else:
        normalized["next_at"] = ""
    return normalized


def normalize_proactive_companion(value, now: datetime | None = None) -> dict:
    now = now or local_now()
    raw = value if isinstance(value, dict) else {}
    templates = _default_proactive_item_map()
    raw_items = raw.get("items", [])
    raw_by_id = {
        str(item.get("id") or "").strip(): item
        for item in raw_items
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    } if isinstance(raw_items, list) else {}
    items = []
    seen = set()
    for item_id, template in templates.items():
        normalized = normalize_proactive_item(raw_by_id.get(item_id, {}), template, now)
        if normalized:
            items.append(normalized)
            seen.add(item_id)
    for item in raw_by_id.values():
        item_id = str(item.get("id") or "").strip()
        item_kind = str(item.get("kind") or item_id).strip()
        if item_id == "desktop_state" or item_kind == "desktop_state":
            continue
        if item_id in seen:
            continue
        normalized = normalize_proactive_item(item, None, now)
        if normalized:
            items.append(normalized)
            seen.add(item_id)
    return {
        "enabled": _coerce_bool(raw.get("enabled", False), False),
        "character": str(raw.get("character", "") or "").strip(),
        "items": items,
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
    completed = max(0, min(repeat_count, _coerce_int(item.get("completed_focus_count", 0), 0)))
    status = str(item.get("status", "running") or "running").strip().lower()
    if status not in {"running", "paused", "completed", "cancelled"}:
        status = "running"
    phase = str(item.get("phase", "focus") or "focus").strip().lower()
    if phase not in {"focus", "short_break", "long_break", "completed"}:
        phase = "focus"
    duration = _coerce_int(item.get("phase_duration_sec", 0), 0)
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
        "focus": _tr("ReminderCore.phase_focus", default="专注中"),
        "short_break": _tr("ReminderCore.phase_short_break", default="短休息"),
        "long_break": _tr("ReminderCore.phase_long_break", default="长休息"),
        "completed": _tr("ReminderCore.phase_completed", default="已完成"),
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


def normalize_proactive_care_policy(value) -> dict:
    from proactive_care_policy import normalize_proactive_care_policy as _normalize

    return _normalize(value)
