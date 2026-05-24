import re

from i18n_manager import tr as _tr


def format_llm_error_message(error_msg: str) -> str:
    raw_error = str(error_msg or "").strip()
    original = raw_error if raw_error.startswith("Error:") else f"Error: {raw_error}"
    return f"{original}\n\n{llm_error_hint(raw_error)}"


def llm_error_hint(error_msg: str) -> str:
    category = _classify_llm_error(error_msg)
    defaults = {
        "api_key": "错误提示（API Key 错误）：API Key 可能无效、过期或没有权限。请检查设置里的 API Key 是否填写正确，并确认当前服务商账号可用。",
        "model_not_found": "错误提示（模型不存在）：当前模型 ID 可能不存在，或这个接口不支持该模型。请检查模型 ID 是否和服务商后台/模型列表一致。",
        "network": "错误提示（网络失败）：请求没有成功连到模型服务。请检查 API 地址、网络连接、代理设置，或稍后重试。",
        "quota": "错误提示（额度不足）：账号余额、免费额度或调用额度可能不足。请检查服务商余额、账单状态或额度限制。",
        "unknown": "错误提示：暂时无法判断具体原因。请根据上方原始报错检查 API Key、模型 ID、API 地址和服务商状态。",
    }
    return _tr(f"LLMErrorHint.{category}", default=defaults[category])


def _classify_llm_error(error_msg: str) -> str:
    text = str(error_msg or "").lower()
    status = _http_status(text)

    quota_terms = (
        "insufficient_quota",
        "quota",
        "exceeded your current quota",
        "billing",
        "balance",
        "credit",
        "credits",
        "payment required",
        "余额",
        "额度",
        "欠费",
        "账单",
        "用量",
    )
    if status == 402 or any(term in text for term in quota_terms):
        return "quota"

    api_key_terms = (
        "api key",
        "apikey",
        "authorization",
        "authentication",
        "auth",
        "unauthorized",
        "forbidden",
        "invalid key",
        "incorrect api key",
        "invalid api_key",
        "invalid token",
        "token is invalid",
        "access token",
        "bearer",
        "密钥",
        "金钥",
        "未授权",
        "鉴权",
        "认证",
        "权限",
    )
    if status in (401, 403) or any(term in text for term in api_key_terms):
        return "api_key"

    model_terms = (
        "model_not_found",
        "model not found",
        "model does not exist",
        "model doesn't exist",
        "invalid model",
        "unknown model",
        "no such model",
        "the model",
        "模型不存在",
        "模型不支持",
        "模型无效",
        "找不到模型",
    )
    if any(term in text for term in model_terms) and ("not found" in text or "exist" in text or "invalid" in text or "模型" in text):
        return "model_not_found"

    network_terms = (
        "urlopen error",
        "timed out",
        "timeout",
        "connection refused",
        "connection reset",
        "connection aborted",
        "network is unreachable",
        "temporary failure in name resolution",
        "name or service not known",
        "getaddrinfo failed",
        "no route to host",
        "ssl:",
        "certificate verify failed",
        "proxy",
        "远程主机强迫关闭",
        "连接失败",
        "连接超时",
        "网络",
    )
    if status in (408, 502, 503, 504) or any(term in text for term in network_terms):
        return "network"

    if status == 404 and "model" in text:
        return "model_not_found"
    if status == 429:
        return "quota"

    return "unknown"


def _http_status(text: str) -> int | None:
    match = re.search(r"\bhttp\s+(\d{3})\b", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
