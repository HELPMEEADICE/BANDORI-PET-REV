import json
import sys
from typing import Callable


def iter_input_messages():
    stream = sys.stdin.buffer
    reader = getattr(stream, "read1", stream.read)
    buffer = b""
    while True:
        chunk = reader(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            message, buffer = extract_message_from_buffer(buffer)
            if message is None:
                break
            if message.strip():
                yield message


def extract_message_from_buffer(buffer: bytes) -> tuple[str | None, bytes]:
    buffer = buffer.lstrip(b"\r\n")
    if not buffer:
        return None, buffer
    if buffer[:15].lower() == b"content-length:":
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


def handle_tools_message(
    message: dict,
    *,
    protocol_version: str,
    server_name: str,
    tools: list[dict],
    call_tool: Callable[[str, dict], str],
):
    if not isinstance(message, dict):
        return error(None, -32600, "Invalid request")
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return result(request_id, {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": server_name, "version": "1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return result(request_id, {"tools": tools})
    if method == "tools/call":
        params = message.get("params", {}) if isinstance(message.get("params"), dict) else {}
        try:
            output = call_tool(str(params.get("name", "") or ""), params.get("arguments", {}) or {})
            return result(request_id, {"content": [{"type": "text", "text": output}], "isError": False})
        except Exception as exc:
            return result(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return error(request_id, -32601, f"Unknown method: {method}")


def result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def write_message(message: dict):
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()
