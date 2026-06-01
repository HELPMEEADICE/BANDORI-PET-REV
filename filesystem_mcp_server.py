import json
import sys
from pathlib import Path

from mcp_base import error, handle_tools_message, iter_input_messages, write_message
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
    for raw in iter_input_messages():
        try:
            message = json.loads(raw)
            response = handle_message(message, roots)
        except Exception as exc:
            response = error(None, -32603, str(exc))
        if response is not None:
            write_message(response)
    return 0


def handle_message(message: dict, roots: list[Path]):
    return handle_tools_message(
        message,
        protocol_version=PROTOCOL_VERSION,
        server_name="BandoriPet Readonly Filesystem",
        tools=TOOLS,
        call_tool=lambda name, arguments: call_tool(name, arguments, roots),
    )


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


def _resolve_allowed_path(value, roots: list[Path]) -> Path:
    text = str(value or ".").strip() or "."
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = roots[0] / candidate
    resolved = candidate.resolve()
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved
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
        if path.is_relative_to(root):
            return str(path.relative_to(root)).replace("\\", "/")
    return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
