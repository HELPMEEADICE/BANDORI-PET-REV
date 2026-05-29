"""Shared handlers for the extra ``@`` chat commands.

These commands are recognized by both the full chat window and the compact AI
window. Each handler operates purely on a :class:`ConfigManager` so the two UI
surfaces only need to render the returned message.

Supported commands::

    @cot [bool]              toggle reasoning/thinking display
    @websearch [bool]        toggle web search
    @sys-instruction [bool]  toggle the highest-priority system prompt preset
    @clock HHMM [desc]       add a one-shot alarm within the next 24h
    @pomodoro [count] [desc] start a Pomodoro timer

The boolean argument is optional; when omitted the current value is flipped.
Clocks and Pomodoros default to the first visible Live2D character so that the
reminder system generates that character's personalized text.
"""

from __future__ import annotations

from datetime import timedelta

from i18n_manager import tr as _tr
from reminder_core import (
    ALARM_CONFIG_KEY,
    POMODORO_CONFIG_KEY,
    REMINDER_DISPLAY_MODE_KEY,
    clamp_repeat_count,
    create_alarm,
    create_pomodoro,
    default_reminder_character,
    local_now,
    normalize_alarms,
    normalize_pomodoros,
    parse_iso_datetime,
)


_TRUE_TOKENS = {
    "on", "true", "1", "yes", "y", "enable", "enabled", "show",
    "开", "开启", "启用", "打开", "显示", "是", "要",
}
_FALSE_TOKENS = {
    "off", "false", "0", "no", "n", "disable", "disabled", "hide",
    "关", "关闭", "禁用", "停用", "隐藏", "否", "不要",
}


def _parse_bool(token: str, current: bool):
    """Return True/False for a switch argument, or None if unrecognized.

    An empty argument flips the current value.
    """
    token = str(token or "").strip().lower()
    if not token:
        return not bool(current)
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return None


def _state_label(value: bool) -> str:
    return (
        _tr("ChatCommand.state_on", default="开启")
        if value
        else _tr("ChatCommand.state_off", default="关闭")
    )


def _parse_clock_time(token: str) -> str:
    """Parse a colon-free time such as ``0930`` or ``930`` into ``HH:MM``."""
    digits = str(token or "").strip()
    if not digits.isdigit():
        return ""
    if len(digits) == 4:
        hour, minute = int(digits[:2]), int(digits[2:])
    elif len(digits) == 3:
        hour, minute = int(digits[:1]), int(digits[1:])
    elif len(digits) in (1, 2):
        hour, minute = int(digits), 0
    else:
        return ""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hour:02d}:{minute:02d}"


_TOGGLE_DEFS = (
    {
        "aliases": {"@cot", "/cot", "@思维链", "/思维链", "@reasoning", "/reasoning"},
        "key": "llm_show_reasoning",
        "default": True,
        "label_key": "ChatCommand.label_cot",
        "label_default": "思维链显示",
    },
    {
        "aliases": {"@websearch", "/websearch", "@web", "/web", "@联网", "/联网", "@联网搜索", "/联网搜索"},
        "key": "llm_web_search_enabled",
        "default": False,
        "label_key": "ChatCommand.label_websearch",
        "label_default": "联网搜索",
    },
    {
        "aliases": {
            "@sys-instruction", "/sys-instruction", "@sysinstruction", "/sysinstruction",
            "@系统提示", "/系统提示", "@系统指令", "/系统指令",
        },
        "key": "llm_custom_system_prompt_enabled",
        "default": True,
        "label_key": "ChatCommand.label_sys_instruction",
        "label_default": "最高优先级系统提示词",
    },
)

_CLOCK_ALIASES = {"@clock", "/clock", "@时钟", "/时钟", "@闹钟", "/闹钟"}
_POMODORO_ALIASES = {"@pomodoro", "/pomodoro", "@番茄", "/番茄", "@番茄钟", "/番茄钟"}


def _reminder_payload(cfg, alarms: list[dict], pomodoros: list[dict]) -> dict:
    return {
        ALARM_CONFIG_KEY: alarms,
        POMODORO_CONFIG_KEY: pomodoros,
        REMINDER_DISPLAY_MODE_KEY: cfg.get(REMINDER_DISPLAY_MODE_KEY, "floating"),
    }


def _publish(payload: dict) -> None:
    try:
        from settings_bus import publish_settings
        publish_settings(payload)
    except Exception:
        pass


def _handle_toggle(cfg, definition: dict, arg: str, publish: bool) -> dict:
    key = definition["key"]
    label = _tr(definition["label_key"], default=definition["label_default"])
    current = bool(cfg.get(key, definition["default"]))
    value = _parse_bool(arg, current)
    if value is None:
        return {
            "message": _tr(
                "ChatCommand.toggle_bad_arg",
                default="无法识别的开关参数。请使用 开/关 或 on/off。当前{label}：{state}。",
                label=label,
                state=_state_label(current),
            )
        }
    cfg.set(key, value)
    cfg.save()
    if publish:
        _publish({key: value})
    message = _tr(
        "ChatCommand.toggle_done",
        default="已{state}{label}。",
        state=_state_label(value),
        label=label,
    )
    if (
        key == "llm_custom_system_prompt_enabled"
        and value
        and not str(cfg.get("llm_custom_system_prompt", "") or "").strip()
    ):
        message += "\n" + _tr(
            "ChatCommand.sys_instruction_empty",
            default="（提示：最高优先级系统提示词内容为空，请先在设置中填写后才会生效。）",
        )
    result = {"message": message}
    if key == "llm_show_reasoning":
        result["show_reasoning"] = value
    return result


def _handle_clock(cfg, rest: str, publish: bool, name_resolver) -> dict:
    parts = rest.split(None, 1)
    time_token = parts[0] if parts else ""
    description = parts[1].strip() if len(parts) > 1 else ""
    hhmm = _parse_clock_time(time_token)
    if not hhmm:
        return {
            "message": _tr(
                "ChatCommand.clock_usage",
                default="用法：@clock 0930 [描述]（四位数时间，24 小时制，无冒号；仅支持 24 小时内）。",
            )
        }
    character = default_reminder_character(cfg)
    alarms = normalize_alarms(cfg.get(ALARM_CONFIG_KEY, []))
    pomodoros = normalize_pomodoros(cfg.get(POMODORO_CONFIG_KEY, []))
    try:
        alarm = create_alarm(hhmm, None, description, character, "")
    except ValueError:
        return {"message": _tr("ChatCommand.clock_failed", default="无法创建时钟，请检查时间格式。")}
    now = local_now()
    next_at = parse_iso_datetime(alarm.get("next_at"))
    if next_at is None or next_at - now > timedelta(hours=24):
        return {"message": _tr("ChatCommand.clock_range", default="只能添加 24 小时以内的时钟。")}
    alarms.append(alarm)
    cfg.set(ALARM_CONFIG_KEY, alarms)
    cfg.set(POMODORO_CONFIG_KEY, pomodoros)
    cfg.save()
    if publish:
        _publish(_reminder_payload(cfg, alarms, pomodoros))
    next_text = alarm.get("next_at", "").replace("T", " ")
    char_name = _resolve_name(character, name_resolver)
    if description:
        return {
            "message": _tr(
                "ChatCommand.clock_added",
                default="已为 {character} 添加时钟：{time}，下次响铃 {next_at}，描述：{desc}。",
                character=char_name,
                time=alarm.get("time", hhmm),
                next_at=next_text,
                desc=description,
            )
        }
    return {
        "message": _tr(
            "ChatCommand.clock_added_no_desc",
            default="已为 {character} 添加时钟：{time}，下次响铃 {next_at}。届时将由 {character} 生成个性化提醒。",
            character=char_name,
            time=alarm.get("time", hhmm),
            next_at=next_text,
        )
    }


def _handle_pomodoro(cfg, rest: str, publish: bool, name_resolver) -> dict:
    parts = rest.split(None, 1)
    count_token = parts[0] if parts else ""
    description = parts[1].strip() if len(parts) > 1 else ""
    try:
        repeat_count = int(count_token)
    except (TypeError, ValueError):
        # No leading number: treat the whole argument as the description.
        repeat_count = 1
        description = rest.strip()
    repeat_count = clamp_repeat_count(repeat_count)
    character = default_reminder_character(cfg)
    alarms = normalize_alarms(cfg.get(ALARM_CONFIG_KEY, []))
    pomodoros = normalize_pomodoros(cfg.get(POMODORO_CONFIG_KEY, []))
    pomodoro = create_pomodoro(repeat_count, description, character)
    pomodoros.append(pomodoro)
    cfg.set(ALARM_CONFIG_KEY, alarms)
    cfg.set(POMODORO_CONFIG_KEY, pomodoros)
    cfg.save()
    if publish:
        _publish(_reminder_payload(cfg, alarms, pomodoros))
    char_name = _resolve_name(character, name_resolver)
    if description:
        return {
            "message": _tr(
                "ChatCommand.pomodoro_added",
                default="已为 {character} 启动番茄钟：{count} 次专注循环，描述：{desc}。",
                character=char_name,
                count=pomodoro.get("repeat_count", repeat_count),
                desc=description,
            )
        }
    return {
        "message": _tr(
            "ChatCommand.pomodoro_added_no_desc",
            default="已为 {character} 启动番茄钟：{count} 次专注循环。每个阶段将由 {character} 生成个性化提醒。",
            character=char_name,
            count=pomodoro.get("repeat_count", repeat_count),
        )
    }


def _resolve_name(character: str, name_resolver) -> str:
    if callable(name_resolver):
        try:
            resolved = str(name_resolver(character) or "").strip()
            if resolved:
                return resolved
        except Exception:
            pass
    return character or _tr("ChatCommand.default_character", default="桌宠")


def handle_command(cfg, text: str, *, name_resolver=None, publish: bool = True):
    """Dispatch one of the extra ``@`` commands.

    Returns a result dict with a ``message`` key (and optionally
    ``show_reasoning``) when the text matches a command, otherwise ``None``.
    """
    if cfg is None:
        return None
    stripped = str(text or "").strip()
    if not stripped:
        return None
    parts = stripped.split(None, 1)
    head = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    for definition in _TOGGLE_DEFS:
        if head in definition["aliases"]:
            return _handle_toggle(cfg, definition, rest, publish)
    if head in _CLOCK_ALIASES:
        return _handle_clock(cfg, rest, publish, name_resolver)
    if head in _POMODORO_ALIASES:
        return _handle_pomodoro(cfg, rest, publish, name_resolver)
    return None
