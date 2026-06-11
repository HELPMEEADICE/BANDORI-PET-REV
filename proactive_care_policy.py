from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

from reminder_core import isoformat, normalize_time, parse_iso_datetime


PROACTIVE_CARE_POLICY_CONFIG_KEY = "proactive_care_policy"

CARE_RULE_MODES = {"normal", "quiet", "silent", "encourage"}
CARE_DESKTOP_STATES = (
    "gaming",
    "media",
    "coding",
    "writing",
    "chatting",
    "web",
    "desktop",
    "idle",
    "unknown",
)

_IMPORTANT_LIFESTYLE_KINDS = {"bedtime", "sedentary"}

_DEFAULT_STATE_RULES = {
    "gaming": {
        "mode": "normal",
        "cooldown_multiplier": 1.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "media": {
        "mode": "normal",
        "cooldown_multiplier": 1.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "coding": {
        "mode": "quiet",
        "cooldown_multiplier": 2.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "writing": {
        "mode": "quiet",
        "cooldown_multiplier": 2.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "chatting": {
        "mode": "normal",
        "cooldown_multiplier": 1.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "web": {
        "mode": "normal",
        "cooldown_multiplier": 1.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "desktop": {
        "mode": "normal",
        "cooldown_multiplier": 1.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "idle": {
        "mode": "encourage",
        "cooldown_multiplier": 0.7,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
    "unknown": {
        "mode": "normal",
        "cooldown_multiplier": 1.0,
        "allow_screen_awareness": True,
        "allow_lifestyle_reminders": True,
    },
}


def default_proactive_care_policy() -> dict:
    return {
        "enabled": True,
        "global_cooldown_minutes": 30,
        "quiet_hours_enabled": False,
        "quiet_start": "23:30",
        "quiet_end": "08:00",
        "screen_awareness_respect_policy": True,
        "last_care_at": "",
        "last_screen_awareness_at": "",
        "last_skip_reason": "",
        "state_rules": deepcopy(_DEFAULT_STATE_RULES),
    }


def _bool_value(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _int_value(value, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _float_value(value, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize_proactive_care_policy(value) -> dict:
    raw = value if isinstance(value, dict) else {}
    defaults = default_proactive_care_policy()
    rules = {}
    raw_rules = raw.get("state_rules", {})
    raw_rules = raw_rules if isinstance(raw_rules, dict) else {}
    for state in CARE_DESKTOP_STATES:
        template = defaults["state_rules"][state]
        item = raw_rules.get(state, {})
        item = item if isinstance(item, dict) else {}
        mode = str(item.get("mode", template["mode"]) or "").strip().lower()
        if mode not in CARE_RULE_MODES:
            mode = template["mode"]
        rules[state] = {
            "mode": mode,
            "cooldown_multiplier": _float_value(
                item.get("cooldown_multiplier", template["cooldown_multiplier"]),
                template["cooldown_multiplier"],
                0.25,
                4.0,
            ),
            "allow_screen_awareness": _bool_value(
                item.get("allow_screen_awareness", template["allow_screen_awareness"]),
                template["allow_screen_awareness"],
            ),
            "allow_lifestyle_reminders": _bool_value(
                item.get("allow_lifestyle_reminders", template["allow_lifestyle_reminders"]),
                template["allow_lifestyle_reminders"],
            ),
        }

    return {
        "enabled": _bool_value(raw.get("enabled", defaults["enabled"]), defaults["enabled"]),
        "global_cooldown_minutes": _int_value(raw.get("global_cooldown_minutes", 30), 30, 5, 240),
        "quiet_hours_enabled": _bool_value(raw.get("quiet_hours_enabled", False), False),
        "quiet_start": normalize_time(raw.get("quiet_start", defaults["quiet_start"])) or defaults["quiet_start"],
        "quiet_end": normalize_time(raw.get("quiet_end", defaults["quiet_end"])) or defaults["quiet_end"],
        "screen_awareness_respect_policy": _bool_value(
            raw.get("screen_awareness_respect_policy", True),
            True,
        ),
        "last_care_at": str(raw.get("last_care_at", "") or ""),
        "last_screen_awareness_at": str(raw.get("last_screen_awareness_at", "") or ""),
        "last_skip_reason": str(raw.get("last_skip_reason", "") or "")[:160],
        "state_rules": rules,
    }


def _minutes_of_day(time_text: str) -> int:
    normalized = normalize_time(time_text)
    if not normalized:
        return 0
    hour, minute = [int(part) for part in normalized.split(":", 1)]
    return hour * 60 + minute


def _in_quiet_hours(policy: dict, now: datetime) -> bool:
    if not policy.get("quiet_hours_enabled"):
        return False
    start = _minutes_of_day(policy.get("quiet_start", "23:30"))
    end = _minutes_of_day(policy.get("quiet_end", "08:00"))
    current = now.hour * 60 + now.minute
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _state_from_desktop(desktop_state: dict | None) -> str:
    if not isinstance(desktop_state, dict):
        return "unknown"
    state = str(desktop_state.get("state", "") or "").strip().lower()
    return state if state in CARE_DESKTOP_STATES else "unknown"


def _cooldown_minutes(policy: dict, rule: dict) -> int:
    base = int(policy.get("global_cooldown_minutes", 30) or 30)
    value = base * float(rule.get("cooldown_multiplier", 1.0) or 1.0)
    return max(1, int(round(value)))


def _cooldown_remaining(policy: dict, rule: dict, now: datetime) -> int:
    last_at = parse_iso_datetime(policy.get("last_care_at"))
    if last_at is None:
        return 0
    cooldown = _cooldown_minutes(policy, rule)
    elapsed = max(0.0, (now - last_at).total_seconds() / 60.0)
    remaining = cooldown - elapsed
    if remaining <= 0:
        return 0
    return max(1, int(round(remaining)))


def _result(allow: bool, reason: str = "", delay: int | None = None, tone_hint: str = "") -> dict:
    return {
        "allow": bool(allow),
        "reason": reason,
        "next_delay_minutes": delay,
        "tone_hint": tone_hint,
    }


def evaluate_proactive_care(
    policy,
    *,
    kind: str,
    proactive_kind: str = "",
    desktop_state: dict | None = None,
    now: datetime | None = None,
    bypass: bool = False,
) -> dict:
    now = now or datetime.now().replace(microsecond=0)
    policy = normalize_proactive_care_policy(policy)
    kind = str(kind or "").strip()
    proactive_kind = str(proactive_kind or "").strip()
    if bypass or not policy.get("enabled"):
        return _result(True, tone_hint="自然、简短，不要解释触发机制。")
    if kind == "screen_awareness" and not policy.get("screen_awareness_respect_policy", True):
        return _result(True, tone_hint="根据屏幕上下文判断是否值得开口。")

    state = _state_from_desktop(desktop_state)
    rule = policy["state_rules"].get(state) or policy["state_rules"]["unknown"]
    mode = str(rule.get("mode", "normal") or "normal")

    if _in_quiet_hours(policy, now):
        return _result(False, "quiet_hours", _cooldown_minutes(policy, rule), "勿扰时段内保持安静。")

    if kind == "screen_awareness" and not rule.get("allow_screen_awareness", True):
        return _result(False, f"{state}_blocks_screen_awareness", _cooldown_minutes(policy, rule))

    if kind == "proactive_companion" and not rule.get("allow_lifestyle_reminders", True):
        if proactive_kind not in _IMPORTANT_LIFESTYLE_KINDS:
            return _result(False, f"{state}_blocks_lifestyle", _cooldown_minutes(policy, rule))

    if mode == "silent":
        if kind != "proactive_companion" or proactive_kind not in _IMPORTANT_LIFESTYLE_KINDS:
            return _result(False, f"{state}_silent", _cooldown_minutes(policy, rule))

    remaining = _cooldown_remaining(policy, rule, now)
    if remaining > 0:
        return _result(False, "cooldown", remaining)

    tone = {
        "quiet": "用户可能正在专注，语气要轻，不要要求立即回应。",
        "silent": "只在重要健康或睡前提醒时开口，语气要短。",
        "encourage": "用户可能空闲或离开过，语气可以更温和主动。",
        "normal": "自然、简短，像日常关心。",
    }.get(mode, "自然、简短，像日常关心。")
    return _result(True, tone_hint=tone)


def mark_proactive_care_result(policy, *, kind: str, now: datetime | None = None, skip_reason: str = "") -> dict:
    now = now or datetime.now().replace(microsecond=0)
    policy = normalize_proactive_care_policy(policy)
    if skip_reason:
        policy["last_skip_reason"] = str(skip_reason)[:160]
        if str(kind or "") == "screen_awareness":
            policy["last_care_at"] = isoformat(now)
            policy["last_screen_awareness_at"] = isoformat(now)
    else:
        policy["last_care_at"] = isoformat(now)
        policy["last_skip_reason"] = ""
        if str(kind or "") == "screen_awareness":
            policy["last_screen_awareness_at"] = isoformat(now)
    return policy
