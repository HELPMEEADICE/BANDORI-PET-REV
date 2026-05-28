import json
import sys
from pathlib import Path

from process_utils import clamp_int as _clamp_int, configure_debug_logging

configure_debug_logging()


PROTOCOL_VERSION = "2025-06-18"
MAX_READ_CHARS = 100_000


TOOLS = [
    {
        "name": "list_directory",
        "description": "List files and folders under an allowed directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path, absolute or relative to the allowed root."},
                "limit": {"type": "integer", "description": "Maximum number of entries to return."},
            },
        },
    },
    {
        "name": "read_text_file",
        "description": "Read a text file under an allowed directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path, absolute or relative to the allowed root."},
                "max_chars": {"type": "integer", "description": "Maximum characters to return."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search file and folder names under an allowed directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive name fragment to search for."},
                "path": {"type": "string", "description": "Search root, absolute or relative to the allowed root."},
                "limit": {"type": "integer", "description": "Maximum number of matches to return."},
            },
            "required": ["query"],
        },
    },
]


def main() -> int:
    roots = _allowed_roots()
    for raw in _iter_input_messages():
        try:
            message = json.loads(raw)
            response = handle_message(message, roots)
        except Exception as exc:
            response = _error(None, -32603, str(exc))
        if response is not None:
            _write(response)
    return 0


def handle_message(message: dict, roots: list[Path]):
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid request")
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "BandoriPet Readonly Filesystem", "version": "1.0"},
        })
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params", {}) if isinstance(message.get("params"), dict) else {}
        try:
            output = call_tool(str(params.get("name", "") or ""), params.get("arguments", {}) or {}, roots)
            return _result(request_id, {"content": [{"type": "text", "text": output}], "isError": False})
        except Exception as exc:
            return _result(request_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
    return _error(request_id, -32601, f"Unknown method: {method}")


def call_tool(name: str, arguments: dict, roots: list[Path]) -> str:
    if not isinstance(arguments, dict):
        arguments = {}
    if name == "list_directory":
        path = _resolve_allowed_path(arguments.get("path", ".") or ".", roots)
        limit = _clamp_int(arguments.get("limit", 200), 1, 1000)
        return _list_directory(path, roots, limit)
    if name == "read_text_file":
        path = _resolve_allowed_path(arguments.get("path", "") or "", roots)
        max_chars = _clamp_int(arguments.get("max_chars", 20_000), 1, MAX_READ_CHARS)
        return _read_text_file(path, max_chars)
    if name == "search_files":
        query = str(arguments.get("query", "") or "").strip().lower()
        if not query:
            raise ValueError("query is required")
        path = _resolve_allowed_path(arguments.get("path", ".") or ".", roots)
        limit = _clamp_int(arguments.get("limit", 100), 1, 1000)
        return _search_files(path, roots, query, limit)
    raise ValueError(f"Unknown tool: {name}")


def _allowed_roots() -> list[Path]:
    roots = []
    for value in sys.argv[1:]:
        text = str(value or "").strip()
        if not text:
            continue
        path = Path(text).expanduser().resolve()
        if path.exists() and path.is_dir():
            roots.append(path)
    if not roots:
        raise RuntimeError("No valid allowed roots were configured for filesystem MCP server")
    return roots


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


def _resolve_allowed_path(value, roots: list[Path]) -> Path:
    text = str(value or ".").strip() or "."
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    allowed = ", ".join(str(root) for root in roots)
    raise PermissionError(f"Path is outside allowed roots. Allowed roots: {allowed}")


def _list_directory(path: Path, roots: list[Path], limit: int) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    items = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:limit]:
        try:
            stat = child.stat()
        except OSError:
            continue
        items.append({
            "name": child.name,
            "path": _display_path(child, roots),
            "type": "directory" if child.is_dir() else "file",
            "size": stat.st_size,
            "modified": int(stat.st_mtime),
        })
    return json.dumps(items, ensure_ascii=False, indent=2)


def _read_text_file(path: Path, max_chars: int) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_file():
        raise IsADirectoryError(str(path))
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > max_chars:
        return data[:max_chars] + f"\n\n[truncated to {max_chars} characters]"
    return data


def _search_files(path: Path, roots: list[Path], query: str, limit: int) -> str:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    matches = []
    for child in path.rglob("*"):
        if len(matches) >= limit:
            break
        if query not in child.name.lower():
            continue
        matches.append({
            "name": child.name,
            "path": _display_path(child, roots),
            "type": "directory" if child.is_dir() else "file",
        })
    return json.dumps(matches, ensure_ascii=False, indent=2)


def _display_path(path: Path, roots: list[Path]) -> str:
    for root in roots:
        try:
            return str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
    return str(path)


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
