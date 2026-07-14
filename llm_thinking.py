import re


_REASONING_TAG_NAME = r"(?:think(?:ing)?|reasoning|analysis)"
_CLOSED_REASONING_TAG_PATTERN = re.compile(
    rf"<\s*{_REASONING_TAG_NAME}\b[^>]*>\s*(.*?)\s*"
    rf"<\s*/\s*{_REASONING_TAG_NAME}\s*>",
    re.IGNORECASE | re.DOTALL,
)
_OPEN_REASONING_TAG_PATTERN = re.compile(
    rf"<\s*{_REASONING_TAG_NAME}\b[^>]*>",
    re.IGNORECASE,
)
_CLOSE_REASONING_TAG_PATTERN = re.compile(
    rf"<\s*/\s*{_REASONING_TAG_NAME}\s*>",
    re.IGNORECASE,
)


def apply_thinking_options(body: dict, enable_thinking):
    if enable_thinking is None:
        return
    body["enable_thinking"] = enable_thinking
    body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
    if enable_thinking:
        body["reasoning_effort"] = "medium"


def apply_responses_thinking_options(body: dict, enable_thinking):
    if enable_thinking is None:
        return
    body["reasoning"] = {"effort": "medium" if enable_thinking else "none"}


def split_thinking_text(content: str, reasoning: str = "") -> tuple[str, str]:
    source = str(content or "")
    collected = [str(reasoning).strip()] if reasoning and str(reasoning).strip() else []

    def collect_closed(match):
        text = match.group(1).strip()
        if text:
            collected.append(text)
        return ""

    clean = _CLOSED_REASONING_TAG_PATTERN.sub(collect_closed, source)
    unclosed = _OPEN_REASONING_TAG_PATTERN.search(clean)
    if unclosed is not None:
        text = clean[unclosed.end():].strip()
        if text:
            collected.append(text)
        clean = clean[:unclosed.start()]
    clean = _CLOSE_REASONING_TAG_PATTERN.sub("", clean).strip()
    return clean, "\n\n".join(collected).strip()
