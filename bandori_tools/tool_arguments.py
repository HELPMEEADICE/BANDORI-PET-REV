import json


def parse_tool_arguments(arguments, fallback_key: str | None = None) -> dict:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {fallback_key: arguments} if fallback_key else {}
    return arguments if isinstance(arguments, dict) else {}
