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
