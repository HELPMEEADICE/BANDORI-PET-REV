import json
import sys
from pathlib import Path

from action_bus import publish_action, publish_lip_sync
from ai_event_bus import publish_ai_event
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
    for raw in _iter_input_messages():
        try:
            message = json.loads(raw)
            response = handle_message(message)
        except Exception as exc:
            response = _error(None, -32603, str(exc))
        if response is not None:
            _write(response)
    return 0


def _iter_input_messages():
    stream = sys.stdin.buffer
    reader = getattr(stream, "read1", stream.read)
    buffer = b""
    while True:
        chunk = reader(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            message, buffer = _extract_message_from_buffer(buffer)
            if message is None:
                break
            if message.strip():
                yield message


def _extract_message_from_buffer(buffer: bytes) -> tuple[str | None, bytes]:
    buffer = buffer.lstrip(b"\r\n")
    if not buffer:
        return None, buffer
    if buffer.startswith(b"Content-Length:"):
        header_end = buffer.find(b"\r\n\r\n")
        if header_end < 0:
            return None, buffer
        headers = buffer[:header_end].decode("utf-8", errors="replace").split("\r\n")
        content_length = None
        for line in headers:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            if name.strip().lower() == "content-length":
                content_length = int(value.strip())
                break
        if content_length is None:
            raise ValueError("Missing Content-Length header")
        body_start = header_end + 4
        body_end = body_start + content_length
        if len(buffer) < body_end:
            return None, buffer
        body = buffer[body_start:body_end].decode("utf-8", errors="replace")
        return body, buffer[body_end:]
    line_end = buffer.find(b"\n")
    if line_end < 0:
        return None, buffer
    line = buffer[:line_end].decode("utf-8", errors="replace")
    return line, buffer[line_end + 1:]


def handle_message(message: dict):
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid request")
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "BandoriPet", "version": "1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params", {}) if isinstance(message.get("params"), dict) else {}
        try:
            output = call_tool(str(params.get("name", "") or ""), params.get("arguments", {}) or {})
            return _result(request_id, {"content": [{"type": "text", "text": output}], "isError": False})
        except Exception as exc:
            return _result(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return _error(request_id, -32601, f"Unknown method: {method}")


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


def _result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write(message: dict):
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
