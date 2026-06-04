import base64
import gzip
import json
import re
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime
from html import unescape

from computer_tools import computer_tools, is_computer_tool_name, run_computer_tool
from mcp_bridge import call_mcp_tool, is_mcp_tool_name, mcp_native_tools, mcp_proxy_tools
from process_utils import run_off_gui_thread
from reminder_core import (
    ALARM_CONFIG_KEY,
    POMODORO_CONFIG_KEY,
    REMINDER_DISPLAY_MODE_KEY,
    create_alarm,
    create_pomodoro,
    default_reminder_character,
    normalize_alarms,
    normalize_pomodoros,
    repeat_days_label,
)


WEB_SEARCH_TOOL_NAME = "web_search"
WEB_FETCH_TOOL_NAME = "web_fetch"
AUTO_CONTINUE_TOOL_NAME = "continue_conversation"
CREATE_ALARM_TOOL_NAME = "create_alarm"
START_POMODORO_TOOL_NAME = "start_pomodoro"
POKE_USER_TOOL_NAME = "poke_user"
_FORCE_WEB_SEARCH_PATTERN = re.compile(
    r"(联网|上网|搜(?:索|一下)?|查(?:一下|找)?|帮我(?:搜|查|找)|"
    r"最新|实时|现在|当前|今天|今日|昨天|明天|新闻|价格|股价|汇率|"
    r"日程|赛程|天气|版本|发布|公告|官网|文档|API|api|"
    r"latest|current|today|news|price|version|release|weather|schedule)",
    re.IGNORECASE,
)
_MAX_PAGE_EXCERPT_CHARS = 700

WEB_SEARCH_ENGINE_LABELS = {
    "bing": "Bing",
    "bing_cn": "Bing CN",
    "google": "Google",
    "duckduckgo": "DuckDuckGo",
    "baidu": "Baidu",
}


CHAT_COMPLETIONS_WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": WEB_SEARCH_TOOL_NAME,
        "description": (
            "Search the public web for current or external information. "
            "Use this for news, latest facts, prices, schedules, software/API "
            "details, or anything that may have changed recently."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query, including enough keywords to be specific.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "How many search results to return, from 1 to 8.",
                },
            },
            "required": ["query"],
        },
    },
}

CHAT_COMPLETIONS_REMINDER_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": CREATE_ALARM_TOOL_NAME,
            "description": (
                "Create an alarm/reminder in BandoriPet when the user asks to set an alarm. "
                "Time is required. Use the user's local current date from context when resolving relative dates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "Required local time, preferably HH:MM in 24-hour format.",
                    },
                    "date": {
                        "type": "string",
                        "description": "Optional one-time local date as YYYY-MM-DD, for requests like tomorrow or a specific date.",
                    },
                    "repeat": {
                        "type": "string",
                        "description": "Repeat rule: none, daily, weekdays, weekends, or custom.",
                    },
                    "repeat_days": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "For custom weekly repeat, use values such as mon/tue/wed/thu/fri/sat/sun.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional alarm purpose, such as drink water, meeting, wake up, study.",
                    },
                    "character": {
                        "type": "string",
                        "description": "Optional reminder character key or display name. Omit to use the first visible Live2D character.",
                    },
                },
                "required": ["time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": START_POMODORO_TOOL_NAME,
            "description": (
                "Start a Pomodoro timer in BandoriPet when the user asks for a Pomodoro/focus timer. "
                "Each small cycle is 25 minutes focus plus a break; a 15-minute long break is inserted after every 4 focus cycles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "repeat_count": {
                        "type": "integer",
                        "description": "Number of 25-minute focus cycles to run. Default 1.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional Pomodoro purpose, such as writing, coding, homework.",
                    },
                    "character": {
                        "type": "string",
                        "description": "Optional reminder character key or display name. Omit to use the first visible Live2D character.",
                    },
                },
            },
        },
    },
]

CHAT_COMPLETIONS_POKE_USER_TOOL = {
    "type": "function",
    "function": {
        "name": POKE_USER_TOOL_NAME,
        "description": (
            "Playfully poke/nudge the user through BandoriPet, similar to QQ's poke interaction. "
            "Use this when the character wants to poke the user back or initiate a playful poke."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Optional short natural reason or line for the poke.",
                },
            },
        },
    },
}

CHAT_COMPLETIONS_AUTO_CONTINUE_TOOL = {
    "type": "function",
    "function": {
        "name": AUTO_CONTINUE_TOOL_NAME,
        "description": (
            "Continue the current one-on-one character conversation after already sending a natural partial reply. "
            "Use this only when the character should add another short follow-up message without waiting for the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason why another short follow-up is needed.",
                },
            },
        },
    },
}

CHAT_COMPLETIONS_WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": WEB_FETCH_TOOL_NAME,
        "description": (
            "Fetch and extract readable text from a public http/https URL. "
            "Use this when the user provides a link and asks about its content. "
            "If web_search is enabled, you may also fetch URLs returned by web_search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full http or https URL to fetch.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of extracted page text to return, from 500 to 12000.",
                },
            },
            "required": ["url"],
        },
    },
}


def web_search_system_hint(include_sources: bool = True) -> str:
    source_rule = (
        "工具返回搜索结果后，请基于结果作答，并在回复末尾输出严格 JSON 来源块，"
        "格式为 {\"web_search_sources\":[{\"title\":\"网页标题\",\"url\":\"https://...\"}]}；"
        "不要用 Markdown 列表展示来源。"
        if include_sources
        else "工具返回搜索结果后，请自然消化资料并保持角色口吻；除非用户明确要求来源，不要列出 URL 或引用列表。"
    )
    return (
        "【联网搜索工具】\n"
        "如果用户询问最新、实时、新闻、价格、日程、版本、API 文档、外部事实，"
        "或任何可能随时间变化的信息，你可以调用 web_search 工具。"
        "普通闲聊、角色扮演、情感陪伴、改写润色、总结已有上下文时，不要为了保险起见就去搜索。"
        "只有当搜索结果会明显提升正确性时才调用。"
        "调用 web_search 时，query 必须直接包含用户真正想查询的主体、时间或关键词，不要使用“你/我/它/这个”等代词，也不要把整段提示词原样塞进去。"
        f"{source_rule}"
        "如果没有收到真实工具结果，不要声称自己已经联网搜索；如果工具结果显示搜索失败或结果不足，必须直接说明没有查到可靠结果。"
    )


def chat_completion_tools(web_search_enabled: bool, tool_config: dict | None = None) -> list[dict]:
    tools = [CHAT_COMPLETIONS_WEB_SEARCH_TOOL] if web_search_enabled else []
    config = tool_config or {}
    if config.get("llm_web_fetch_enabled", False):
        tools.append(CHAT_COMPLETIONS_WEB_FETCH_TOOL)
    if config.get("llm_auto_continue_enabled", False):
        tools.append(CHAT_COMPLETIONS_AUTO_CONTINUE_TOOL)
    if reminder_tools_enabled(config):
        tools.extend(CHAT_COMPLETIONS_REMINDER_TOOLS)
    tools.append(CHAT_COMPLETIONS_POKE_USER_TOOL)
    tools.extend(mcp_proxy_tools(config))
    tools.extend(computer_tools(config))
    return tools


def reminder_tools_enabled(tool_config: dict | None = None) -> bool:
    return True


def responses_native_tools(tool_config: dict | None = None) -> list[dict]:
    return mcp_native_tools(tool_config or {})


def local_tool_system_hint(tool_config: dict | None = None) -> str:
    config = tool_config or {}
    hints = []
    if config.get("llm_hide_tool_call_details", True):
        hints.append(
            "最终回复请保持角色口吻，不要主动提到 MCP、tool_calls、function calling、Computer Use、工具调用、JSON schema 等实现细节；"
            "如果工具失败，也用自然语言轻描淡写地说明做不到或信息不足。"
        )
    if config.get("llm_mcp_enabled", False):
        hints.append(
            "可用外部能力时，优先根据用户意图谨慎调用；不要编造工具执行结果。"
        )
    if reminder_tools_enabled(config):
        hints.append(
            "当用户表达设置闹钟、提醒、番茄钟、专注计时等明确意图时，可以直接调用对应工具创建；"
            "时间不明确时先追问，不要凭空编造具体时间。工具成功后，用角色口吻简短确认。"
        )
    hints.append(
        f"当你想像 QQ 一样玩笑式地戳一戳用户，或用户戳你之后你想回戳，可以调用 {POKE_USER_TOOL_NAME}；"
        "调用后仍要用角色口吻自然回应，不要解释工具细节。"
    )
    if config.get("llm_auto_continue_enabled", False):
        max_turns = _normalize_auto_continue_max_turns(config.get("llm_auto_continue_max_turns", 5))
        hints.append(
            f"单人对话中，如果你已经说完一小段但角色还应该主动补充下一句，可以调用 {AUTO_CONTINUE_TOOL_NAME}；"
            "如果用户明确要求一次发两条、多条、连续几条消息，必须在每条回复后调用这个工具，直到达到用户要求或硬上限。"
            "调用前必须先输出当前这句自然回复，不要空内容只调用工具。"
            f"本轮最多连续输出 {max_turns} 条，达到上限后继续工具调用会被忽略。"
        )
    if config.get("llm_web_fetch_enabled", False):
        if config.get("llm_web_search_enabled", False):
            hints.append(
                f"当用户提供网页链接并询问内容，或你已经通过 {WEB_SEARCH_TOOL_NAME} 拿到候选网页且需要阅读全文时，可以调用 {WEB_FETCH_TOOL_NAME}。"
                "只抓取 http/https 公网链接；不要声称访问了未实际调用工具的网页。"
            )
        else:
            hints.append(
                f"当用户明确提供网页链接并询问内容时，可以调用 {WEB_FETCH_TOOL_NAME} 读取页面；"
                "没有用户提供的链接时不要自行编造 URL，也不要把它当作搜索工具使用。"
            )
    if config.get("computer_use_enabled", False):
        if config.get("computer_use_auto_detect", True):
            hints.append(
                "当用户用自然语言表达与当前屏幕、窗口、光标、按钮、输入框、复制粘贴、打开/关闭/切换窗口、"
                "移动到某处、点一下、看一下这里/那边/这个界面等相关意图时，可以自行判断是否需要使用 Computer Use；"
                "不要求用户说出“工具”“操作鼠标”“查看屏幕”等精确词。"
            )
        else:
            hints.append(
                "只有当用户明确要求查看屏幕或操作电脑时才使用 Computer Use。"
            )
        hints.append(
            "使用 Computer Use 前优先截图确认界面；如果坐标不确定，先截图再行动。"
            "鼠标移动/点击/滚动请使用最近一次截图图片上的像素坐标，程序会自动映射到真实桌面坐标。"
            "不要执行购买、支付、删除、发送消息、发布内容、登录、修改安全设置等高风险操作。"
        )
    if config.get("desktop_state_awareness_enabled", False):
        hints.append(
            "如果需要判断用户当前是在写代码、看网页、打游戏、发呆/离开等桌面状态，可以调用 computer_desktop_state；"
            "这只读取前台窗口类别和键鼠空闲时长，不截屏。最终回复要把它自然融入角色反应，不要主动暴露窗口标题或进程名。"
        )
    if not hints:
        return ""
    return "【工具使用边界】\n" + "\n".join(hints)


def with_local_tool_system_hint(messages: list[dict], tool_config: dict | None = None) -> list[dict]:
    hint_text = local_tool_system_hint(tool_config)
    if not hint_text:
        return [dict(item) for item in messages]
    copied = [dict(item) for item in messages]
    hint = {"role": "system", "content": hint_text}
    if copied and copied[0].get("role") == "system":
        copied.insert(1, hint)
    else:
        copied.insert(0, hint)
    return copied


def with_web_search_system_hint(messages: list[dict], include_sources: bool = True) -> list[dict]:
    copied = [dict(item) for item in messages]
    hint = {"role": "system", "content": web_search_system_hint(include_sources)}
    if copied and copied[0].get("role") == "system":
        copied.insert(1, hint)
    else:
        copied.insert(0, hint)
    return copied


def run_local_tool_call(name: str, arguments, tool_config: dict | None = None) -> dict:
    if name == AUTO_CONTINUE_TOOL_NAME:
        return _run_auto_continue_tool_call(arguments, tool_config or {})
    if name == POKE_USER_TOOL_NAME:
        return _run_poke_user_tool_call(arguments, tool_config or {})
    if name in {CREATE_ALARM_TOOL_NAME, START_POMODORO_TOOL_NAME}:
        return _run_reminder_tool_call(name, arguments, tool_config or {})
    if name == WEB_FETCH_TOOL_NAME:
        return _run_web_fetch_tool_call(arguments, tool_config or {})
    if name != WEB_SEARCH_TOOL_NAME:
        if is_mcp_tool_name(name):
            return {"content": call_mcp_tool(name, arguments), "extra_messages": []}
        if is_computer_tool_name(name):
            return run_computer_tool(name, arguments, tool_config or {})
        return {"content": f"Unsupported tool: {name}", "extra_messages": []}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"query": arguments}
    if not isinstance(arguments, dict):
        arguments = {}
    query = _normalize_web_search_query(
        arguments.get("query", ""),
        (tool_config or {}).get("_latest_user_text", ""),
    )
    try:
        max_results = int(arguments.get("max_results", 5) or 5)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(8, max_results))
    engine = _normalize_search_engine((tool_config or {}).get("llm_web_search_engine", "bing_cn"))
    return {"content": web_search(query, max_results=max_results, engine=engine), "extra_messages": []}


def _run_web_fetch_tool_call(arguments, tool_config: dict | None = None) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"url": arguments}
    if not isinstance(arguments, dict):
        arguments = {}
    url = str(arguments.get("url", "") or "").strip()
    try:
        max_chars = int(arguments.get("max_chars", 6000) or 6000)
    except (TypeError, ValueError):
        max_chars = 6000
    max_chars = max(500, min(12000, max_chars))
    return {"content": web_fetch(url, max_chars=max_chars), "extra_messages": []}


def _run_reminder_tool_call(name: str, arguments, tool_config: dict | None = None) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    try:
        from config_manager import ConfigManager
        from settings_bus import publish_settings
    except Exception as exc:
        return {"content": f"提醒工具不可用：{exc}", "extra_messages": []}

    cfg = ConfigManager()
    cfg.load()
    character = _resolve_reminder_character(arguments.get("character", ""), cfg)
    alarms = normalize_alarms(cfg.get(ALARM_CONFIG_KEY, []))
    pomodoros = normalize_pomodoros(cfg.get(POMODORO_CONFIG_KEY, []))

    try:
        if name == CREATE_ALARM_TOOL_NAME:
            repeat_value = arguments.get("repeat_days")
            if not repeat_value:
                repeat_value = arguments.get("repeat", "")
            alarm = create_alarm(
                arguments.get("time", ""),
                repeat_value,
                arguments.get("description", ""),
                character,
                arguments.get("date", ""),
            )
            alarms.append(alarm)
            cfg.set(ALARM_CONFIG_KEY, alarms)
            cfg.set(POMODORO_CONFIG_KEY, pomodoros)
            cfg.save()
            payload = _reminder_settings_payload(cfg, alarms, pomodoros)
            publish_settings(payload)
            next_at = alarm.get("next_at", "").replace("T", " ")
            repeat_label = repeat_days_label(alarm.get("repeat_days", []))
            desc = alarm.get("description", "") or "无描述"
            return {
                "content": f"已创建闹钟：{alarm['time']}，{repeat_label}，下次 {next_at}，描述：{desc}。",
                "extra_messages": [],
            }
        if name == START_POMODORO_TOOL_NAME:
            pomodoro = create_pomodoro(
                arguments.get("repeat_count", 1),
                arguments.get("description", ""),
                character,
            )
            pomodoros.append(pomodoro)
            cfg.set(ALARM_CONFIG_KEY, alarms)
            cfg.set(POMODORO_CONFIG_KEY, pomodoros)
            cfg.save()
            payload = _reminder_settings_payload(cfg, alarms, pomodoros)
            publish_settings(payload)
            desc = pomodoro.get("description", "") or "无描述"
            return {
                "content": f"已启动番茄钟：{pomodoro['repeat_count']} 次专注循环，描述：{desc}。",
                "extra_messages": [],
            }
    except Exception as exc:
        return {"content": f"创建提醒失败：{exc}", "extra_messages": []}
    return {"content": "未知提醒工具。", "extra_messages": []}


def _run_poke_user_tool_call(arguments, tool_config: dict | None = None) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    character = str((tool_config or {}).get("_active_character", "") or "").strip()
    message = str(arguments.get("message", "") or "").strip()
    try:
        from action_bus import publish_user_poke
        publish_user_poke(character, message, source="llm_tool", direction="to_user")
    except Exception as exc:
        return {"content": f"戳一戳失败：{exc}", "extra_messages": []}
    return {
        "content": "已戳了戳用户。请用角色口吻自然承接，不要提到工具调用细节。",
        "extra_messages": [],
    }


def _normalize_auto_continue_max_turns(value) -> int:
    try:
        return max(1, min(20, int(value)))
    except (TypeError, ValueError):
        return 5


def _run_auto_continue_tool_call(arguments, tool_config: dict) -> dict:
    del arguments
    max_turns = _normalize_auto_continue_max_turns(tool_config.get("llm_auto_continue_max_turns", 5))
    try:
        current = max(0, int(tool_config.get("_auto_continue_count", 0) or 0))
    except (TypeError, ValueError):
        current = 0
    remaining = max(0, max_turns - current - 1)
    return {
        "content": (
            "可以继续以当前角色口吻补充下一句。"
            f"本轮剩余可继续输出条数：{remaining}。"
            "如果已经表达完整，请不要再次调用工具，直接结束回复。"
        ),
        "extra_messages": [],
    }


def _reminder_settings_payload(cfg, alarms: list[dict], pomodoros: list[dict]) -> dict:
    return {
        ALARM_CONFIG_KEY: alarms,
        POMODORO_CONFIG_KEY: pomodoros,
        REMINDER_DISPLAY_MODE_KEY: cfg.get(REMINDER_DISPLAY_MODE_KEY, "floating"),
    }


def _resolve_reminder_character(value: str, cfg) -> str:
    requested = str(value or "").strip()
    fallback = default_reminder_character(cfg)
    if not requested:
        return fallback
    try:
        from model_manager import ModelManager
        manager = ModelManager(scan_models=False)
        if requested in manager.characters:
            return requested
        requested_lower = requested.lower()
        for character in manager.characters:
            display = manager.get_display_name(character)
            if requested == display or requested_lower == str(display).lower():
                return character
    except Exception:
        pass
    return fallback


def should_prefetch_web_search(text: str) -> bool:
    text = str(text or "").strip()
    if not text:
        return False
    return bool(_FORCE_WEB_SEARCH_PATTERN.search(text))


def web_search_prefetch_context(latest_user_text: str, tool_config: dict | None = None, max_results: int = 5) -> str:
    query = _normalize_web_search_query(latest_user_text, latest_user_text)
    if not query:
        return ""
    engine = _normalize_search_engine((tool_config or {}).get("llm_web_search_engine", "bing_cn"))
    result = web_search(query, max_results=max_results, engine=engine)
    if result.startswith(("搜索失败：", "没有找到")):
        return (
            "【程序已尝试联网搜索，但没有拿到可靠结果】\n"
            f"{result}\n"
            "回答时不要声称已经查到外部资料；请明确说明当前联网检索没有可用结果。"
        )
    return (
        "【程序已实际执行联网搜索】\n"
        "下面是本次问题对应的真实搜索结果。回答实时、最新或外部事实时必须优先依据这些结果；"
        "不要编造这些结果之外的来源，也不要声称打开了未出现在结果中的网页。\n"
        f"{result}"
    )


def web_search(query: str, max_results: int = 5, engine: str = "bing_cn") -> str:
    query = str(query or "").strip()
    if not query:
        return "搜索失败：query 不能为空。"

    errors = []
    searcher = _searcher_for_engine(engine)
    try:
        results = searcher(query, max_results=max_results)
    except Exception as exc:
        errors.append(str(exc))
        results = []
    if results:
        _enrich_results_with_page_excerpts(results)
        return _format_search_results(query, results[:max_results], engine)
    for fallback in (_search_duckduckgo_html, _search_duckduckgo_instant_answer):
        if fallback is searcher:
            continue
        try:
            results = fallback(query, max_results=max_results)
        except Exception as exc:
            errors.append(str(exc))
            results = []
        if results:
            _enrich_results_with_page_excerpts(results)
            return _format_search_results(query, results[:max_results], "duckduckgo")
    if errors:
        return "搜索失败：" + "；".join(errors[:2])
    return f"没有找到与 “{query}” 相关的搜索结果。"


def web_fetch(url: str, max_chars: int = 6000) -> str:
    url = _normalize_fetch_url(url)
    if not url:
        return "网页读取失败：url 必须是完整的 http/https 链接。"
    try:
        text = _fetch_page_text(url, max_chars=max_chars)
    except Exception as exc:
        return f"网页读取失败：{exc}"
    if not text:
        return "网页读取失败：没有提取到可读正文，或页面不是文本/HTML 内容。"
    title = _extract_html_title(text) or url
    body = _extract_readable_text(text, max_chars=max_chars)
    if not body:
        return "网页读取失败：没有提取到可读正文，或页面不是文本/HTML 内容。"
    return "\n".join([
        f"1. {title}",
        f"URL: {url}",
        "读取时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"正文：{body}",
    ])


def _normalize_search_engine(engine: str) -> str:
    engine = str(engine or "").strip().lower()
    return engine if engine in WEB_SEARCH_ENGINE_LABELS else "bing_cn"


def _searcher_for_engine(engine: str):
    return {
        "bing": _search_bing_html,
        "bing_cn": _search_bing_cn_html,
        "google": _search_google_html,
        "duckduckgo": _search_duckduckgo_html,
        "baidu": _search_baidu_html,
    }.get(_normalize_search_engine(engine), _search_bing_cn_html)


def _content_to_text(content) -> str:
    if isinstance(content, list):
        parts = [
            str(item.get("text", "") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") in ("text", "input_text")
        ]
        return "\n".join(parts)
    return str(content or "")


_BAD_SEARCH_QUERIES = {
    "你", "我", "他", "她", "它", "这", "那", "这个", "那个", "这里", "那里",
    "啥", "什么", "吗", "么", "呢", "知道", "搜索", "查", "搜",
}


def _normalize_web_search_query(query, fallback_text: str = "") -> str:
    raw = _strip_prompt_suffix(str(query or ""))
    fallback = _extract_search_query(fallback_text)
    extracted = _extract_search_query(raw)
    candidate = extracted or raw.strip()
    if _is_bad_search_query(candidate) and fallback:
        candidate = fallback
    return _clean_search_query(candidate)


def _strip_prompt_suffix(text: str) -> str:
    text = str(text or "").strip()
    marker = "【后置提示词】"
    if marker in text:
        text = text.split(marker, 1)[0].strip()
    return text


def _extract_search_query(text: str) -> str:
    text = _strip_prompt_suffix(text)
    if not text:
        return ""
    quoted = re.search(r"[\"'“”‘’]([^\"'“”‘’]{2,80})[\"'“”‘’]", text)
    if quoted:
        return _clean_search_query(quoted.group(1))

    patterns = (
        r"(?:什么是|啥是|何为)\s*([^？?。！!，,\n]{2,80})",
        r"(?:知道|了解|听说过)\s*(?:什么是|啥是)?\s*([^？?。！!，,\n]{2,80})",
        r"(?:帮我查一下|帮我搜一下|查一下|查找|搜索|搜一下|帮我查|帮我搜|找一下|查|搜)\s*([^？?。！!，,\n]{2,80})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _clean_search_query(match.group(1))

    latin_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.+\-]{1,80}", text)
    cleaned = _clean_search_query(text)
    if len(latin_tokens) >= 2 or re.search(r"\d", cleaned):
        return cleaned[:120]
    if latin_tokens:
        return max(latin_tokens, key=len)
    return ""


def _clean_search_query(query: str) -> str:
    query = _strip_prompt_suffix(query)
    query = re.sub(r"^[\s，,。？?！!：:;；]+|[\s，,。？?！!：:;；]+$", "", query)
    query = re.sub(
        r"^(?:请|麻烦)?(?:帮我)?(?:查一下|查找|搜索|搜一下|帮我查一下|帮我搜一下|帮我查|帮我搜|找一下|查|搜)\s*",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"^(?:你知道|知道|请问|问一下|这个|那个|啥是|什么是)\s*", "", query)
    query = re.sub(r"(?:是什么|是啥|吗|么|呢)$", "", query).strip()
    return query


def _is_bad_search_query(query: str) -> bool:
    query = _clean_search_query(query)
    if not query:
        return True
    if query in _BAD_SEARCH_QUERIES:
        return True
    return len(query) <= 1 and not re.search(r"[A-Za-z0-9]", query)


def _request_text(url: str, timeout: int = 12) -> str:
    return run_off_gui_thread(lambda: _request_text_direct(url, timeout))


def _request_text_direct(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _normalize_fetch_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    host = (parsed.hostname or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return ""
    return urllib.parse.urlunsplit(parsed)


def _fetch_page_text(url: str, max_chars: int = 6000) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return ""

    def fetch():
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,application/json;q=0.7,*/*;q=0.4",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if content_type and not any(token in content_type for token in ("text/", "html", "xml", "json")):
                return ""
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(max(250_000, max_chars * 40))
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(charset, errors="replace")

    return run_off_gui_thread(fetch)


def _extract_html_title(text: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", str(text or ""))
    return _clean_html(match.group(1))[:120] if match else ""


def _extract_readable_text(text: str, max_chars: int = 6000) -> str:
    text = str(text or "")
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style|noscript|svg|canvas|template)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>", "\n", text)
    text = _clean_html(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    if len(text) < 40:
        return ""
    return text[:max_chars].rstrip()


def _enrich_results_with_page_excerpts(results: list[dict], max_pages: int = 2):
    enriched = 0
    for result in results:
        if enriched >= max_pages:
            return
        url = str(result.get("url", "") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        try:
            excerpt = _fetch_page_excerpt(url)
        except Exception:
            excerpt = ""
        if excerpt:
            result["page_excerpt"] = excerpt
            enriched += 1


def _fetch_page_excerpt(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if content_type and not any(token in content_type for token in ("text/", "html", "xml", "json")):
                return ""
            charset = resp.headers.get_content_charset() or "utf-8"
            raw = resp.read(250_000)
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = gzip.decompress(raw)
        text = raw.decode(charset, errors="replace")
    except (OSError, UnicodeError, urllib.error.URLError, urllib.error.HTTPError):
        return ""
    return _extract_readable_excerpt(text)


def _extract_readable_excerpt(text: str) -> str:
    text = str(text or "")
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style|noscript|svg|canvas|template)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", text)
    text = _clean_html(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 80:
        return ""
    return text[:_MAX_PAGE_EXCERPT_CHARS].rstrip()


def _search_duckduckgo_html(query: str, max_results: int = 5) -> list[dict]:
    url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    html = _request_text(url)
    link_matches = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    snippet_matches = re.findall(
        r'<(?:a|div)[^>]+class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    results = []
    for idx, (raw_url, raw_title) in enumerate(link_matches):
        title = _clean_html(raw_title)
        link = _clean_duckduckgo_url(raw_url)
        snippet = _clean_html(snippet_matches[idx]) if idx < len(snippet_matches) else ""
        if not title or not link:
            continue
        results.append({"title": title, "url": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _search_bing_html(query: str, max_results: int = 5) -> list[dict]:
    url = "https://www.bing.com/search?" + urllib.parse.urlencode({"q": query})
    return _parse_bing_html(_request_text(url), max_results)


def _search_bing_cn_html(query: str, max_results: int = 5) -> list[dict]:
    url = "https://cn.bing.com/search?" + urllib.parse.urlencode({
        "q": query,
        "mkt": "zh-CN",
        "setlang": "zh-CN",
    })
    return _parse_bing_html(_request_text(url), max_results)


def _parse_bing_html(html: str, max_results: int = 5) -> list[dict]:
    blocks = re.findall(r'<li\s+class="b_algo"[^>]*>.*?</li>', html, re.IGNORECASE | re.DOTALL)
    results = []
    for block in blocks:
        title_match = re.search(
            r"<h2[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>",
            block,
            re.IGNORECASE | re.DOTALL,
        )
        if not title_match:
            continue
        raw_url, raw_title = title_match.groups()
        title = _clean_html(raw_title)
        link = _clean_bing_url(raw_url)
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.IGNORECASE | re.DOTALL)
        snippet = _clean_html(snippet_match.group(1)) if snippet_match else ""
        if not title or not link:
            continue
        results.append({"title": title, "url": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _search_google_html(query: str, max_results: int = 5) -> list[dict]:
    url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query, "hl": "zh-CN"})
    html = _request_text(url)
    blocks = re.findall(r'<div\s+class="g"[^>]*>.*?</div>\s*</div>\s*</div>', html, re.IGNORECASE | re.DOTALL)
    results = []
    for block in blocks:
        title_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>', block, re.IGNORECASE | re.DOTALL)
        if not title_match:
            continue
        raw_url, raw_title = title_match.groups()
        title = _clean_html(raw_title)
        link = _clean_google_url(raw_url)
        snippet_match = re.search(r'<div[^>]+(?:class="[^"]*VwiC3b[^"]*"|data-sncf="[^"]*")[^>]*>(.*?)</div>', block, re.IGNORECASE | re.DOTALL)
        snippet = _clean_html(snippet_match.group(1)) if snippet_match else ""
        if title and link and not _is_google_internal_url(link):
            results.append({"title": title, "url": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _search_baidu_html(query: str, max_results: int = 5) -> list[dict]:
    url = "https://www.baidu.com/s?" + urllib.parse.urlencode({"wd": query})
    html = _request_text(url)
    blocks = re.findall(r'<div[^>]+class="[^"]*(?:result|c-container)[^"]*"[^>]*>.*?</div>\s*</div>', html, re.IGNORECASE | re.DOTALL)
    results = []
    for block in blocks:
        title_match = re.search(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.IGNORECASE | re.DOTALL)
        if not title_match:
            continue
        raw_url, raw_title = title_match.groups()
        title = _clean_html(raw_title)
        snippet_match = re.search(r'<span[^>]+class="[^"]*content-right[^"]*"[^>]*>(.*?)</span>|<div[^>]+class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>', block, re.IGNORECASE | re.DOTALL)
        snippet = _clean_html(next((part for part in snippet_match.groups() if part), "")) if snippet_match else ""
        link = unescape(raw_url or "").strip()
        if title and link:
            results.append({"title": title, "url": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _search_duckduckgo_instant_answer(query: str, max_results: int = 5) -> list[dict]:
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    })
    data = json.loads(_request_text(url))
    results = []
    abstract = str(data.get("AbstractText", "") or "").strip()
    abstract_url = str(data.get("AbstractURL", "") or "").strip()
    heading = str(data.get("Heading", "") or "").strip() or query
    if abstract and abstract_url:
        results.append({"title": heading, "url": abstract_url, "snippet": abstract})
    _collect_related_topics(data.get("RelatedTopics", []), results, max_results)
    return results[:max_results]


def _collect_related_topics(items, results: list[dict], max_results: int):
    for item in items or []:
        if len(results) >= max_results:
            return
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("Topics"), list):
            _collect_related_topics(item["Topics"], results, max_results)
            continue
        text = str(item.get("Text", "") or "").strip()
        url = str(item.get("FirstURL", "") or "").strip()
        if text and url:
            title = text.split(" - ", 1)[0][:80]
            results.append({"title": title, "url": url, "snippet": text})


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_duckduckgo_url(raw_url: str) -> str:
    link = unescape(raw_url or "").strip()
    if link.startswith("//"):
        link = "https:" + link
    parsed = urllib.parse.urlsplit(link)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return target
    return link


def _clean_bing_url(raw_url: str) -> str:
    link = unescape(raw_url or "").strip()
    parsed = urllib.parse.urlsplit(link)
    if "bing.com" in parsed.netloc and parsed.path.startswith("/ck/"):
        encoded = urllib.parse.parse_qs(parsed.query).get("u", [""])[0]
        encoded = encoded.removeprefix("a1")
        if encoded:
            padding = "=" * ((4 - len(encoded) % 4) % 4)
            try:
                decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            if decoded.startswith(("http://", "https://")):
                return decoded
    return link


def _clean_google_url(raw_url: str) -> str:
    link = unescape(raw_url or "").strip()
    parsed = urllib.parse.urlsplit(link)
    if parsed.path == "/url":
        target = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
        if target:
            return target
    return link


def _is_google_internal_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.netloc.endswith("google.com") and parsed.path.startswith(("/search", "/preferences", "/settings"))


def _format_search_results(query: str, results: list[dict], engine: str = "bing_cn") -> str:
    lines = [
        f"查询：{query}",
        f"搜索引擎：{WEB_SEARCH_ENGINE_LABELS.get(_normalize_search_engine(engine), 'Bing CN')}",
        "检索时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ]
    for index, result in enumerate(results, 1):
        lines.append(
            f"{index}. {result.get('title', '').strip()}\n"
            f"   URL: {result.get('url', '').strip()}\n"
            f"   摘要：{result.get('snippet', '').strip()}"
        )
        page_excerpt = str(result.get("page_excerpt", "") or "").strip()
        if page_excerpt:
            lines.append(f"   正文摘录：{page_excerpt}")
    return "\n".join(lines)
