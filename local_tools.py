import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape

from computer_tools import computer_tools, is_computer_tool_name, run_computer_tool
from mcp_bridge import call_mcp_tool, is_mcp_tool_name, mcp_native_tools, mcp_proxy_tools


WEB_SEARCH_TOOL_NAME = "web_search"


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


def web_search_system_hint(include_sources: bool = True) -> str:
    source_rule = (
        "工具返回搜索结果后，请基于结果作答，并在回复末尾列出来源链接。"
        if include_sources
        else "工具返回搜索结果后，请自然消化资料并保持角色口吻；除非用户明确要求来源，不要列出 URL 或引用列表。"
    )
    return (
        "【联网搜索工具】\n"
        "如果用户询问最新、实时、新闻、价格、日程、版本、API 文档、外部事实，"
        "或任何可能随时间变化的信息，你可以调用 web_search 工具。"
        f"{source_rule}"
        "如果没有收到真实工具结果，不要声称自己已经联网搜索。"
    )


_SEARCH_INTENT_TERMS = (
    "搜索",
    "联网",
    "网上",
    "查一下",
    "查",
    "查找",
    "搜一下",
    "搜",
    "帮我查",
    "帮我搜",
    "帮忙查",
    "帮忙搜",
    "找一下",
    "Google",
    "google",
    "最新",
    "最近",
    "近期",
    "目前",
    "当下",
    "今年",
    "去年",
    "明年",
    "今天",
    "现在",
    "新闻",
    "消息",
    "资讯",
    "资料",
    "发布",
    "公布",
    "更新",
    "路线图",
    "官方",
    "价格",
    "报价",
    "汇率",
    "天气",
    "日程",
    "赛程",
    "版本",
    "文档",
    "api",
    "current",
    "latest",
    "recent",
    "today",
    "news",
    "price",
    "weather",
    "schedule",
    "version",
    "docs",
    "documentation",
    "release",
    "released",
    "update",
    "roadmap",
    "official",
    "search",
    "web",
    "internet",
    "look up",
)


def chat_completion_tools(web_search_enabled: bool, tool_config: dict | None = None) -> list[dict]:
    tools = [CHAT_COMPLETIONS_WEB_SEARCH_TOOL] if web_search_enabled else []
    config = tool_config or {}
    tools.extend(mcp_proxy_tools(config))
    tools.extend(computer_tools(config))
    return tools


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


def maybe_add_prefetched_web_search(
    messages: list[dict],
    *,
    force: bool = False,
    include_sources: bool = True,
) -> list[dict]:
    copied = [dict(item) for item in messages]
    query = _latest_user_text(copied)
    if not force and not _looks_like_search_intent(query):
        return copied
    if not query.strip():
        return copied
    result = run_local_tool(WEB_SEARCH_TOOL_NAME, {"query": query, "max_results": 4})
    if include_sources:
        source_rule = "只要使用了这些结果，回复末尾必须列出来源 URL；"
    else:
        source_rule = "请不要在回复里列出 URL 或引用列表，除非用户明确要求来源；"
    context = (
        "【自动联网搜索结果】\n"
        "以下是程序在发送给模型前预先检索到的资料。请优先使用这些结果回答；"
        "如果结果不足或不相关，请说明不确定。"
        f"{source_rule}"
        "如果没有看到真实搜索结果，不要声称自己已经联网搜索。\n\n"
        f"{result}"
    )
    context_message = {"role": "system", "content": context}
    if copied and copied[0].get("role") == "system":
        copied.insert(1, context_message)
    else:
        copied.insert(0, context_message)
    return copied


def run_local_tool_call(name: str, arguments, tool_config: dict | None = None) -> dict:
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
    query = str(arguments.get("query", "") or "").strip()
    try:
        max_results = int(arguments.get("max_results", 5) or 5)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(8, max_results))
    return {"content": web_search(query, max_results=max_results), "extra_messages": []}


def run_local_tool(name: str, arguments) -> str:
    return str(run_local_tool_call(name, arguments).get("content", ""))


def web_search(query: str, max_results: int = 5) -> str:
    query = str(query or "").strip()
    if not query:
        return "搜索失败：query 不能为空。"

    errors = []
    for searcher in (_search_bing_html, _search_duckduckgo_html, _search_duckduckgo_instant_answer):
        try:
            results = searcher(query, max_results=max_results)
        except Exception as exc:
            errors.append(str(exc))
            results = []
        if results:
            return _format_search_results(query, results[:max_results])
    if errors:
        return "搜索失败：" + "；".join(errors[:2])
    return f"没有找到与 “{query}” 相关的搜索结果。"


def _latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        return _content_to_text(message.get("content", ""))
    return ""


def _content_to_text(content) -> str:
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") in ("text", "input_text"):
                parts.append(str(item.get("text", "") or ""))
        return "\n".join(parts)
    return str(content or "")


def _looks_like_search_intent(text: str) -> bool:
    lowered = str(text or "").lower()
    if any(term.lower() in lowered for term in _SEARCH_INTENT_TERMS):
        return True
    return bool(re.search(r"\b20[0-9]{2}\b", lowered))


def _request_text(url: str, timeout: int = 12) -> str:
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
    html = _request_text(url)
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
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        if encoded:
            padding = "=" * ((4 - len(encoded) % 4) % 4)
            try:
                decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8", errors="replace")
            except Exception:
                decoded = ""
            if decoded.startswith(("http://", "https://")):
                return decoded
    return link


def _format_search_results(query: str, results: list[dict]) -> str:
    lines = [
        f"查询：{query}",
        "检索时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    ]
    for index, result in enumerate(results, 1):
        lines.append(
            f"{index}. {result.get('title', '').strip()}\n"
            f"   URL: {result.get('url', '').strip()}\n"
            f"   摘要：{result.get('snippet', '').strip()}"
        )
    return "\n".join(lines)
