import json
import re
import urllib.error
import urllib.request

from llm_api_compat import chat_completions_api_url, sanitize_chat_body_for_url


def _apply_thinking_options(body: dict, enable_thinking):
    if enable_thinking not in (True, False):
        return
    body["enable_thinking"] = enable_thinking
    body["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
    body["reasoning"] = {"effort": "medium" if enable_thinking else "none"}


def _strip_thinking_text(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.S | re.I).strip()


def analyze_images_with_aux_model(
    api_url: str,
    api_key: str,
    model_id: str,
    image_data_urls: list[str],
    user_text: str = "",
    enable_thinking=None,
    timeout: int = 120,
) -> str:
    image_data_urls = [url for url in image_data_urls if url]
    if not api_url or not api_key or not model_id or not image_data_urls:
        return ""

    prompt = (
        "你是视觉理解助手。请根据图片内容和用户原始问题，提取主模型回答所需的视觉信息。"
        "只输出客观、紧凑的中文观察结果；如果用户问题需要读字、识别界面、描述人物、比较差异或定位元素，"
        "请把相关细节写清楚。不要编造看不到的内容。"
    )
    user_prompt = "用户原始问题：\n" + (user_text or "请看这张图片。")
    content = [{"type": "text", "text": user_prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}} for url in image_data_urls)
    body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        "stream": False,
    }
    _apply_thinking_options(body, enable_thinking)
    request_url = chat_completions_api_url(api_url)
    sanitize_chat_body_for_url(body, request_url)
    req = urllib.request.Request(
        request_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    message = data.get("choices", [{}])[0].get("message", {})
    return _strip_thinking_text(message.get("content", ""))
