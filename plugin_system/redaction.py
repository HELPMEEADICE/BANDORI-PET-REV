from __future__ import annotations

import copy
from typing import Any


SECRET_MARKER_KEY = "__bandoripet_secret_value__"
_SECRET_KEY_PARTS = (
    "api_key", "access_key", "access_token", "auth_token", "authorization",
    "credential", "password", "private_key", "secret", "token",
)


def is_sensitive_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            result[str(key)] = (
                {SECRET_MARKER_KEY: True}
                if is_sensitive_key(key)
                else redact_secrets(child)
            )
        return result
    if isinstance(value, list):
        return [redact_secrets(child) for child in value]
    return copy.deepcopy(value)


def restore_secrets(candidate: Any, original: Any) -> Any:
    """Restore host secrets after applying an untrusted managed-event patch."""
    if isinstance(candidate, dict) and candidate.get(SECRET_MARKER_KEY) is True:
        return copy.deepcopy(original)
    if isinstance(candidate, dict) and isinstance(original, dict):
        result = {}
        for key, child in candidate.items():
            if is_sensitive_key(key):
                if key in original:
                    result[key] = copy.deepcopy(original[key])
                continue
            result[key] = restore_secrets(child, original.get(key)) if key in original else copy.deepcopy(child)
        for key, child in original.items():
            if is_sensitive_key(key) and key not in result:
                result[key] = copy.deepcopy(child)
        return result
    if isinstance(candidate, list) and isinstance(original, list):
        return [
            restore_secrets(child, original[index] if index < len(original) else None)
            for index, child in enumerate(candidate)
        ]
    return copy.deepcopy(candidate)
