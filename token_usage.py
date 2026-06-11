"""Token usage normalization and lightweight request-size estimation."""

from __future__ import annotations

import json
import math
import re


_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)
_ASCII_RUN_RE = re.compile(r"[A-Za-z0-9_]+|[^\x00-\x7f]")
HISTORY_MESSAGE_LIMIT_UNLIMITED = 0
HISTORY_MESSAGE_LIMIT_SLIDER_MAX = 101


def normalize_history_message_limit(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    if parsed == HISTORY_MESSAGE_LIMIT_UNLIMITED:
        return HISTORY_MESSAGE_LIMIT_UNLIMITED
    return max(2, min(100, parsed))


def history_message_limit_to_slider(value, default: int) -> int:
    normalized = normalize_history_message_limit(value, default)
    return (
        HISTORY_MESSAGE_LIMIT_SLIDER_MAX
        if normalized == HISTORY_MESSAGE_LIMIT_UNLIMITED
        else normalized
    )


def history_message_limit_from_slider(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 2
    if parsed >= HISTORY_MESSAGE_LIMIT_SLIDER_MAX:
        return HISTORY_MESSAGE_LIMIT_UNLIMITED
    return max(2, min(100, parsed))


def history_message_query_limit(value, default: int) -> int | None:
    normalized = normalize_history_message_limit(value, default)
    return None if normalized == HISTORY_MESSAGE_LIMIT_UNLIMITED else normalized


def _non_negative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_token_usage(value) -> dict:
    """Normalize Chat Completions or Responses API usage dictionaries."""
    usage = value if isinstance(value, dict) else {}
    input_tokens = _non_negative_int(
        usage.get("input_tokens", usage.get("prompt_tokens", 0))
    )
    output_tokens = _non_negative_int(
        usage.get("output_tokens", usage.get("completion_tokens", 0))
    )
    total_tokens = _non_negative_int(usage.get("total_tokens", 0))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated": bool(usage.get("estimated", False)),
    }


def merge_token_usage(total: dict, addition: dict) -> dict:
    left = normalize_token_usage(total)
    right = normalize_token_usage(addition)
    return {
        "input_tokens": left["input_tokens"] + right["input_tokens"],
        "output_tokens": left["output_tokens"] + right["output_tokens"],
        "total_tokens": left["total_tokens"] + right["total_tokens"],
        "estimated": left["estimated"] or right["estimated"],
    }


def estimate_text_tokens(value) -> int:
    """Estimate text tokens without depending on a provider-specific tokenizer."""
    text = str(value or "")
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    remaining = _CJK_RE.sub(" ", text)
    ascii_chars = 0
    other_chars = 0
    for token in _ASCII_RUN_RE.findall(remaining):
        if token.isascii():
            ascii_chars += len(token)
        else:
            other_chars += len(token)
    punctuation = sum(
        1
        for char in remaining
        if not char.isspace() and not char.isalnum() and char != "_"
    )
    return max(
        1,
        cjk_count
        + math.ceil(ascii_chars / 4)
        + math.ceil(other_chars / 2)
        + math.ceil(punctuation / 2),
    )


def estimate_value_tokens(value) -> int:
    if isinstance(value, str):
        return estimate_text_tokens(value)
    if isinstance(value, list):
        total = 0
        for item in value:
            if isinstance(item, dict) and item.get("type") in {"image_url", "input_image"}:
                total += 765
            else:
                total += estimate_value_tokens(item)
        return total
    if isinstance(value, dict):
        return sum(
            estimate_text_tokens(key) + estimate_value_tokens(item)
            for key, item in value.items()
        )
    if value is None:
        return 0
    return estimate_text_tokens(json.dumps(value, ensure_ascii=False))


def estimate_messages_tokens(messages: list[dict]) -> int:
    total = 3
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        total += 3
        total += estimate_text_tokens(message.get("role", ""))
        total += estimate_value_tokens(message.get("content", ""))
        if message.get("name"):
            total += estimate_text_tokens(message["name"])
        if message.get("tool_calls"):
            total += estimate_value_tokens(message["tool_calls"])
        if message.get("tool_call_id"):
            total += estimate_text_tokens(message["tool_call_id"])
    return max(0, total)


def estimate_untracked_history_usage(
    messages: list[dict],
    *,
    input_overhead: int,
    history_limit: int,
) -> dict:
    """Reconstruct usage for assistant replies that predate usage tracking."""
    prepared = [message for message in messages or [] if isinstance(message, dict)]
    try:
        history_limit = int(history_limit)
    except (TypeError, ValueError):
        history_limit = 1
    input_overhead = max(0, int(input_overhead or 0))
    input_tokens = 0
    output_tokens = 0
    request_count = 0

    for index, message in enumerate(prepared):
        if message.get("role") != "assistant":
            continue
        trace = message.get("tool_trace")
        if not isinstance(trace, dict):
            try:
                trace = json.loads(str(message.get("tool_trace_json", "") or ""))
            except (TypeError, ValueError):
                trace = {}
        if isinstance(trace.get("llm_usage"), dict):
            continue

        preceding = (
            prepared[:index]
            if history_limit == HISTORY_MESSAGE_LIMIT_UNLIMITED
            else prepared[max(0, index - max(1, history_limit)):index]
        )
        request_messages = [
            {
                "role": item.get("role", ""),
                "content": item.get("content", ""),
            }
            for item in preceding
        ]
        input_tokens += input_overhead + estimate_messages_tokens(request_messages)
        output_tokens += estimate_value_tokens(message.get("content", ""))
        output_tokens += estimate_text_tokens(message.get("reasoning_content", ""))
        request_count += 1

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated": request_count > 0,
        "request_count": request_count,
    }
