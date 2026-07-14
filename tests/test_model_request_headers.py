import io
import json
from unittest.mock import patch

from llm_api_compat import OPENAI_COMPAT_USER_AGENT, openai_compat_headers
from tts_manager import _translate_to_selected_language
from vision_fallback import analyze_images_with_aux_model


def _json_response(content: str):
    return io.BytesIO(json.dumps({
        "choices": [{"message": {"content": content}}],
    }).encode("utf-8"))


def test_openai_compatible_headers_include_browser_identity_and_auth():
    headers = openai_compat_headers("secret")

    assert headers == {
        "User-Agent": OPENAI_COMPAT_USER_AGENT,
        "Content-Type": "application/json",
        "Authorization": "Bearer secret",
    }


def test_aux_vision_request_uses_compatible_user_agent():
    requests = []

    def open_url(request, timeout):
        requests.append((request, timeout))
        return _json_response("用户正在编辑代码。")

    with patch("vision_fallback.urllib.request.urlopen", side_effect=open_url):
        result = analyze_images_with_aux_model(
            "https://example.com/v1",
            "secret",
            "vision-model",
            ["data:image/png;base64,abc"],
        )

    assert result == "用户正在编辑代码。"
    assert requests[0][0].get_header("User-agent") == OPENAI_COMPAT_USER_AGENT


def test_aux_translation_request_uses_compatible_user_agent():
    requests = []

    def open_url(request, timeout):
        requests.append((request, timeout))
        return _json_response("translation")

    config = {
        "llm_aux_api_url": "https://example.com/v1",
        "llm_aux_api_key": "secret",
        "llm_aux_model_id": "translation-model",
    }
    with patch("tts_manager.urllib.request.urlopen", side_effect=open_url):
        result = _translate_to_selected_language(config, "你好", "English")

    assert result == "translation"
    assert requests[0][0].get_header("User-agent") == OPENAI_COMPAT_USER_AGENT
