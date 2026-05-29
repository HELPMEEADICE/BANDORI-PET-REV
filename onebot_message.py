"""Shared OneBot v11 event helpers.

Used by both the inbound HTTP webhook (``chat_integration_server``) and the
NapCat forward-WebSocket adapter (``napcat_adapter``) so message parsing stays
consistent across接入方式.
"""

import re
from datetime import datetime

_CQ_CODE_PATTERN = re.compile(r"\[CQ:([a-zA-Z]+)(?:,[^\]]*)?\]")

# Friendly placeholders for non-text content, keyed by CQ/segment type.
_SEGMENT_PLACEHOLDERS = {
    "image": "[图片]",
    "record": "[语音]",
    "video": "[视频]",
    "file": "[文件]",
    "face": "[表情]",
    "mface": "[表情]",
    "emoji": "[表情]",
    "reply": "[引用]",
    "forward": "[合并转发]",
    "json": "[卡片]",
    "xml": "[卡片]",
    "markdown": "[卡片]",
    "music": "[音乐]",
    "dice": "[骰子]",
    "rps": "[猜拳]",
    "poke": "[戳一戳]",
    "share": "[链接]",
    "location": "[位置]",
    "contact": "[名片]",
}


def normalize_onebot_event(event: dict) -> dict | None:
    """Normalize a raw OneBot v11 event into BandoriPet's chat event shape.

    Returns ``None`` when the event is not a usable text message (heartbeats,
    notices, empty messages, ...). When ``post_type`` is absent the event is
    assumed to already be in BandoriPet's own format and is returned as-is.
    """
    if not isinstance(event, dict):
        return None
    post_type = str(event.get("post_type") or "").lower()
    if not post_type:
        return event
    if post_type != "message":
        return None
    text = onebot_message_text(event)
    if not text:
        return None
    message_type = str(event.get("message_type") or "").lower()
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = str(event.get("user_id") or sender.get("user_id") or "")
    sender_name = (
        str(sender.get("card") or "").strip()
        or str(sender.get("nickname") or "").strip()
        or sender_id
        or "unknown"
    )
    group_id = str(event.get("group_id") or "")
    if message_type == "group" and group_id:
        thread_id = group_id
        thread_name = str(event.get("group_name") or event.get("group_id") or "QQ 群聊")
    else:
        thread_id = sender_id or str(event.get("target_id") or "private")
        thread_name = sender_name or "QQ 私聊"
    normalized = {
        "platform": "qq",
        "thread_id": thread_id or "default",
        "thread_name": thread_name,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "text": text,
        "message_id": str(event.get("message_id") or event.get("message_seq") or ""),
        "raw_event": event,
    }
    if event.get("time"):
        try:
            normalized["timestamp"] = datetime.fromtimestamp(int(event["time"])).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, TypeError, ValueError, OverflowError):
            pass
    return normalized


def onebot_message_text(event: dict) -> str:
    """Extract a clean, human-readable text for a OneBot message event.

    Prefers the structured ``message`` segment array (so images/replies become
    friendly placeholders like ``[图片]`` instead of raw ``[CQ:image,...]``
    source). Falls back to ``raw_message`` with CQ codes cleaned up.
    """
    message = event.get("message")
    if isinstance(message, list):
        parts = [onebot_segment_text(item) for item in message]
        text = "".join(part for part in parts if part).strip()
        if text:
            return text
    if isinstance(message, str) and message.strip():
        return clean_cq_codes(message)
    raw_message = event.get("raw_message")
    if raw_message:
        return clean_cq_codes(str(raw_message))
    return str(event.get("content") or event.get("text") or "").strip()


def clean_cq_codes(text: str) -> str:
    """Replace inline ``[CQ:type,...]`` codes with friendly placeholders."""
    def _replace(match: "re.Match") -> str:
        seg_type = match.group(1).lower()
        if seg_type == "at":
            return "@ "
        return _SEGMENT_PLACEHOLDERS.get(seg_type, f"[{seg_type}]")

    return _CQ_CODE_PATTERN.sub(_replace, str(text or "")).strip()


def onebot_segment_text(segment) -> str:
    """Render a single OneBot message segment as readable text."""
    if isinstance(segment, str):
        return segment
    if not isinstance(segment, dict):
        return ""
    seg_type = str(segment.get("type") or "").lower()
    data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
    if seg_type == "text":
        return str(data.get("text") or "")
    if seg_type == "at":
        qq = str(data.get("qq") or "").strip()
        name = str(data.get("name") or "").strip()
        if name:
            return f"@{name} "
        return f"@{qq} " if qq and qq != "all" else ("@全体成员 " if qq == "all" else "@ ")
    if seg_type in _SEGMENT_PLACEHOLDERS:
        return _SEGMENT_PLACEHOLDERS[seg_type]
    return f"[{seg_type}]" if seg_type else ""


def onebot_event_mentions_self(event: dict) -> bool:
    """Return True if the event's message @-mentions the logged-in account."""
    if not isinstance(event, dict):
        return False
    self_id = str(event.get("self_id") or "")
    if not self_id:
        return False
    message = event.get("message")
    if isinstance(message, list):
        for segment in message:
            if not isinstance(segment, dict):
                continue
            if str(segment.get("type") or "").lower() != "at":
                continue
            data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
            if str(data.get("qq") or "").strip() == self_id:
                return True
    raw_message = str(event.get("raw_message") or "")
    if raw_message and f"[CQ:at,qq={self_id}" in raw_message:
        return True
    return False
