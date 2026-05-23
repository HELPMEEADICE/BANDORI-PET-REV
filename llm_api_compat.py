from urllib.parse import urlsplit, urlunsplit


GOOGLE_GENERATIVE_LANGUAGE_HOST = "generativelanguage.googleapis.com"
GOOGLE_OPENAI_BASE_PATH = "/v1beta/openai"


def is_google_generative_language_url(api_url: str) -> bool:
    try:
        return urlsplit(api_url or "").netloc.lower() == GOOGLE_GENERATIVE_LANGUAGE_HOST
    except Exception:
        return False


def chat_completions_api_url(api_url: str) -> str:
    url = (api_url or "").rstrip("/")
    if not url:
        return url
    if is_google_generative_language_url(url):
        return _google_openai_chat_completions_url(url)
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/responses"):
        return url[: -len("/responses")] + "/chat/completions"
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        return urlunsplit((parts.scheme, parts.netloc, path + "/chat/completions", parts.query, parts.fragment))
    return url


def responses_api_url(api_url: str) -> str:
    url = (api_url or "").rstrip("/")
    if not url:
        return url
    if is_google_generative_language_url(url):
        return chat_completions_api_url(url)
    if url.endswith("/responses"):
        return url
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")] + "/responses"
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        return urlunsplit((parts.scheme, parts.netloc, path + "/responses", parts.query, parts.fragment))
    return url + "/responses"


def models_api_url(api_url: str) -> str:
    url = (api_url or "").rstrip("/")
    if not url:
        return url
    if is_google_generative_language_url(url):
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, GOOGLE_OPENAI_BASE_PATH + "/models", parts.query, parts.fragment))
    base_url = chat_completions_api_url(url)
    base_url = base_url.rsplit("/chat/completions", 1)[0]
    base_url = base_url.rsplit("/responses", 1)[0]
    return base_url + "/models"


def sanitize_chat_body_for_url(body: dict, api_url: str) -> dict:
    if not is_google_generative_language_url(api_url):
        return body
    body.pop("enable_thinking", None)
    body.pop("thinking", None)
    return body


def _google_openai_chat_completions_url(api_url: str) -> str:
    parts = urlsplit(api_url)
    path = parts.path.rstrip("/")
    if "/openai/chat/completions" in path:
        new_path = path
    elif "/openai" in path:
        new_path = path.split("/openai", 1)[0] + "/openai/chat/completions"
    else:
        new_path = GOOGLE_OPENAI_BASE_PATH + "/chat/completions"
    return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))
