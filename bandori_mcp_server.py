import json
from pathlib import Path

from action_bus import publish_action, publish_lip_sync
from ai_event_bus import publish_ai_event
from mcp_base import error, handle_tools_message, iter_input_messages, write_message
from app_info import APP_NAME
from process_utils import app_base_dir, configure_debug_logging

configure_debug_logging()


PROTOCOL_VERSION = "2025-06-18"


TOOLS = [
    {
        "name": "bandori_pet_action",
        "description": "Trigger a Live2D/pixel pet action for a BandoriPet character.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "character": {"type": "string", "description": "Character key, for example arisa or kasumi."},
                "action": {"type": "string", "description": "Action tag, for example smile, angry, thinking, bye."},
            },
            "required": ["character", "action"],
        },
    },
    {
        "name": "bandori_ai_event",
        "description": "Show an AI status/event overlay in BandoriPet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "idle, thinking, tool, stream, error, done, clear."},
                "title": {"type": "string", "description": "Short event title."},
                "text": {"type": "string", "description": "Event text."},
                "character": {"type": "string", "description": "Optional character key."},
                "action": {"type": "string", "description": "Optional action hint."},
            },
        },
    },
    {
        "name": "bandori_lip_sync",
        "description": "Set a character lip-sync level from 0 to 1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "character": {"type": "string", "description": "Character key."},
                "level": {"type": "number", "description": "Lip level from 0 to 1."},
            },
            "required": ["character", "level"],
        },
    },
    {
        "name": "bandori_list_characters",
        "description": "List character keys and display names known to BandoriPet.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "bandori_health",
        "description": "Check that the BandoriPet MCP server is running.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def main() -> int:
    for raw in iter_input_messages():
        try:
            message = json.loads(raw)
            response = handle_message(message)
        except Exception as exc:
            response = error(None, -32603, str(exc))
        if response is not None:
            write_message(response)
    return 0


def handle_message(message: dict):
    return handle_tools_message(
        message,
        protocol_version=PROTOCOL_VERSION,
        server_name=APP_NAME,
        tools=TOOLS,
        call_tool=call_tool,
    )


def call_tool(name: str, arguments: dict) -> str:
    if not isinstance(arguments, dict):
        arguments = {}
    if name == "bandori_pet_action":
        character = str(arguments.get("character", "") or "").strip()
        action = str(arguments.get("action", "") or "").strip()
        if not character or not action:
            raise ValueError("character and action are required")
        publish_action(character, action)
        return f"Triggered action {action} for {character}."
    if name == "bandori_ai_event":
        event = {
            "state": str(arguments.get("state", "stream") or "stream"),
            "title": str(arguments.get("title", "") or ""),
            "text": str(arguments.get("text", "") or ""),
        }
        for key in ("character", "action"):
            value = str(arguments.get(key, "") or "").strip()
            if value:
                event[key] = value
        publish_ai_event(event)
        return "AI event published."
    if name == "bandori_lip_sync":
        character = str(arguments.get("character", "") or "").strip()
        try:
            level = float(arguments.get("level", 0) or 0)
        except (TypeError, ValueError):
            level = 0.0
        publish_lip_sync(character, max(0.0, min(1.0, level)))
        return f"Lip-sync level set for {character}."
    if name == "bandori_list_characters":
        return json.dumps(_load_characters(), ensure_ascii=False)
    if name == "bandori_health":
        return "BandoriPet MCP server is running."
    raise ValueError(f"Unknown tool: {name}")


def _load_characters() -> list[dict]:
    path = Path(app_base_dir()) / "band.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    result = []
    for band in data.get("bands", []) if isinstance(data, dict) else []:
        for item in band.get("characters", []) or []:
            if isinstance(item, dict):
                key = str(item.get("id", "") or item.get("key", "") or "").strip()
                name = str(item.get("display", "") or item.get("name", "") or key).strip()
            else:
                key = str(item or "").strip()
                name = key
            if key:
                result.append({"key": key, "name": name, "band": band.get("id", "")})
    return result


if __name__ == "__main__":
    raise SystemExit(main())
