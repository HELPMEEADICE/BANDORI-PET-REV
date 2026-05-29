import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import urllib.error
from pathlib import Path

from PySide6.QtCore import QByteArray, QEventLoop, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from i18n_manager import tr as _tr
from process_utils import app_base_dir, hidden_subprocess_kwargs

_PROTOCOL_VERSION = "2025-06-18"
_TOOL_PREFIX = "mcp__"
_TOOL_NAME_MAP: dict[str, tuple[dict, str]] = {}
_CLIENTS: dict[str, "StdioMcpClient"] = {}
_LOCK = threading.RLock()
_thread_local = threading.local()
_APP_DIR = Path(app_base_dir()).resolve()
_BUNDLED_STDIO_MCP_SCRIPT = (_APP_DIR / "filesystem_mcp_server.py").resolve()
_ALLOWED_STDIO_PYTHON_COMMANDS = {"python", "python.exe", "pythonw.exe", "py", "py.exe"}


def mcp_proxy_tools(config: dict) -> list[dict]:
    if not _mcp_enabled(config):
        return []
    tools = []
    tool_name_map_updates = {}
    for server in _enabled_servers(config):
        if _is_native_only(server):
            continue
        try:
            for item in _list_server_tools(server):
                public_name = _public_tool_name(server.get("label", ""), item.get("name", ""))
                tool_name_map_updates[public_name] = (server, item.get("name", ""))
                schema = item.get("inputSchema") or item.get("input_schema") or {"type": "object", "properties": {}}
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}
                tools.append({
                    "type": "function",
                    "function": {
                        "name": public_name,
                        "description": _tool_description(server, item),
                        "parameters": schema,
                    },
                })
        except Exception as exc:
            tools.append(_mcp_error_tool(server, exc))
    if tool_name_map_updates:
        with _LOCK:
            _TOOL_NAME_MAP.update(tool_name_map_updates)
    return tools


def mcp_native_tools(config: dict) -> list[dict]:
    if not (_mcp_enabled(config) and bool(config.get("llm_mcp_use_native", True))):
        return []
    native_tools = []
    for server in _enabled_servers(config):
        if server.get("transport") == "stdio":
            continue
        url = str(server.get("url", "") or "").strip()
        connector_id = str(server.get("connector_id", "") or "").strip()
        if not url and not connector_id:
            continue
        require_approval = str(server.get("require_approval", "always") or "always").lower()
        if require_approval != "never":
            # This app does not yet provide an interactive mcp_approval_response
            # UI loop for native provider calls. Skip instead of returning an
            # approval request that the chat renderer cannot complete.
            continue
        item = {
            "type": "mcp",
            "server_label": str(server.get("label", "") or "mcp"),
            "require_approval": "never",
        }
        description = str(server.get("description", "") or "").strip()
        if description:
            item["server_description"] = description
        if connector_id:
            item["connector_id"] = connector_id
        else:
            item["server_url"] = url
        authorization = str(server.get("authorization", "") or "").strip()
        if authorization:
            item["authorization"] = authorization
        allowed = server.get("allowed_tools", [])
        if isinstance(allowed, str):
            allowed = [part.strip() for part in allowed.split(",") if part.strip()]
        if isinstance(allowed, list) and allowed:
            item["allowed_tools"] = [str(name) for name in allowed if str(name)]
        native_tools.append(item)
    return native_tools


def test_mcp_servers(config: dict) -> tuple[bool, str]:
    if not _mcp_enabled(config):
        return False, _tr("McpBridge.disabled", default="MCP is disabled in settings.")
    servers = _enabled_servers(config)
    if not servers:
        return False, _tr("McpBridge.no_enabled_servers", default="No enabled MCP servers were found.")

    lines = []
    ok_count = 0
    warning_count = 0
    fail_count = 0
    for server in servers:
        label = str(server.get("label", "") or "mcp")
        transport = str(server.get("transport", "stdio") or "stdio").lower()
        try:
            if transport == "native" and server.get("connector_id"):
                warning_count += 1
                lines.append(_tr(
                    "McpBridge.warn_native_connector",
                    default="[WARN] {label}: connector_id native MCP can only be verified by the provider at request time.",
                    label=label,
                ))
                continue
            if transport == "native":
                url = str(server.get("url", "") or "").strip()
                if not url:
                    warning_count += 1
                    lines.append(_tr(
                        "McpBridge.warn_native_missing_url",
                        default="[WARN] {label}: native MCP has no server URL or connector_id.",
                        label=label,
                    ))
                    continue
                tools = _list_http_tools(server)
            else:
                tools = _list_server_tools(server)
            names = [str(tool.get("name", "") or "") for tool in tools if isinstance(tool, dict)]
            ok_count += 1
            preview = ", ".join(name for name in names[:6] if name)
            suffix = f" ({preview})" if preview else ""
            lines.append(_tr(
                "McpBridge.ok_tools_discovered",
                default="[OK] {label}: discovered {count} tool(s){suffix}.",
                label=label,
                count=len(names),
                suffix=suffix,
            ))
        except Exception as exc:
            fail_count += 1
            lines.append(_tr(
                "McpBridge.fail_server",
                default="[FAIL] {label}: {error}",
                label=label,
                error=_format_mcp_exception(server, exc),
            ))

    success = ok_count > 0 and fail_count == 0
    if success and warning_count:
        lines.append(_tr(
            "McpBridge.warn_provider_verification_count",
            default="[WARN] {count} native connector item(s) require provider-side verification.",
            count=warning_count,
        ))
    return success, "\n".join(lines)


def is_mcp_tool_name(name: str) -> bool:
    return str(name or "").startswith(_TOOL_PREFIX)


def call_mcp_tool(public_name: str, arguments) -> str:
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    with _LOCK:
        server, tool_name = _TOOL_NAME_MAP.get(public_name, ({}, ""))
    if not server or not tool_name:
        # The process may be fresh; rebuild maps from configured clients is not
        # possible here, so return a clear error instead of guessing.
        return f"MCP tool is not available in this request: {public_name}"
    if server.get("transport") == "error":
        return str(server.get("error", "MCP server is not available."))
    if str(server.get("require_approval", "always")).lower() == "always":
        # Approval is represented as a settings-level permission in this app.
        # If a server requires per-call approval, keep the call blocked until
        # the user switches that server to never/auto in settings.
        return f"MCP tool blocked by approval setting: {server.get('label', '')}/{tool_name}"
    try:
        if server.get("transport") == "http":
            return _call_http_tool(server, tool_name, arguments)
        return _stdio_client(server).call_tool(tool_name, arguments)
    except Exception as exc:
        return f"MCP tool failed: {exc}"


def _mcp_enabled(config: dict) -> bool:
    return bool(config and config.get("llm_mcp_enabled", False))


def _enabled_servers(config: dict) -> list[dict]:
    servers = config.get("llm_mcp_servers", []) if isinstance(config, dict) else []
    if not isinstance(servers, list):
        return []
    return [server for server in servers if isinstance(server, dict) and server.get("enabled", True)]


def _is_native_only(server: dict) -> bool:
    return server.get("transport") == "native"


def _public_tool_name(label: str, tool_name: str) -> str:
    return f"{_TOOL_PREFIX}{_safe_name(label)}__{_safe_name(tool_name)}"[:64]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "tool"


def _tool_description(server: dict, item: dict) -> str:
    label = str(server.get("label", "") or "mcp")
    desc = str(item.get("description", "") or "").strip()
    if desc:
        return f"[MCP:{label}] {desc}"
    return f"Call MCP tool {item.get('name', '')} on server {label}."


def _mcp_error_tool(server: dict, exc: Exception) -> dict:
    label = _safe_name(server.get("label", "mcp"))
    name = f"{_TOOL_PREFIX}{label}__status"[:64]
    error = _format_mcp_exception(server, exc)
    with _LOCK:
        _TOOL_NAME_MAP[name] = ({
            "transport": "error",
            "label": label,
            "require_approval": "never",
            "error": error,
        }, "status")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": error,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _format_mcp_exception(server: dict, exc: Exception) -> str:
    label = _safe_name(server.get("label", "mcp"))
    command = str(server.get("command", "") or "").strip()
    cwd = str(server.get("cwd", "") or os.getcwd())
    detail = str(exc)
    if isinstance(exc, FileNotFoundError) or getattr(exc, "winerror", None) == 2:
        hint = _tr("McpBridge.process_start_hint", default="MCP server process could not be started.")
        if command:
            hint += " " + _tr("McpBridge.command_hint", default="Command: {command}.", command=command)
        if cwd:
            hint += " " + _tr("McpBridge.cwd_hint", default="Working directory: {cwd}.", cwd=cwd)
        if os.name == "nt" and command.lower() in {"npx", "npm", "pnpm", "yarn"}:
            hint += " " + _tr(
                "McpBridge.windows_node_hint",
                default="On Windows, install Node.js/npm and restart the app; if needed, set command to npx.cmd/npm.cmd or the full .cmd path.",
            )
        return _tr(
            "McpBridge.server_unavailable_with_hint",
            default="MCP server {label} is not available: {hint} ({detail})",
            label=label,
            hint=hint,
            detail=detail,
        )
    return _tr(
        "McpBridge.server_unavailable",
        default="MCP server {label} is not available: {detail}",
        label=label,
        detail=detail,
    )


def _list_server_tools(server: dict) -> list[dict]:
    allowed = server.get("allowed_tools", [])
    if isinstance(allowed, str):
        allowed = [part.strip() for part in allowed.split(",") if part.strip()]
    if server.get("transport") == "http":
        tools = _list_http_tools(server)
    else:
        tools = _stdio_client(server).list_tools()
    if isinstance(allowed, list) and allowed:
        allowed_set = {str(name) for name in allowed}
        tools = [tool for tool in tools if str(tool.get("name", "")) in allowed_set]
    return tools


def _client_key(server: dict) -> str:
    args = " ".join(_server_args(server))
    return f"{server.get('label','')}|{server.get('command','')}|{args}|{server.get('cwd','')}"


def _server_args(server: dict) -> list[str]:
    args = server.get("args", []) or []
    if isinstance(args, str):
        return [part for part in args.split(" ") if part]
    if isinstance(args, list):
        return [str(arg) for arg in args if str(arg)]
    return []


def _resolve_command(command: str) -> str:
    command = str(command or "").strip()
    if not command:
        return command
    has_path_part = any(sep in command for sep in ("/", "\\"))
    if has_path_part or os.path.isabs(command):
        if os.path.exists(command):
            return command
        if os.name == "nt" and not os.path.splitext(command)[1]:
            for suffix in (".cmd", ".exe", ".bat"):
                candidate = command + suffix
                if os.path.exists(candidate):
                    return candidate
        return command
    found = shutil.which(command)
    if found:
        return found
    if os.name == "nt":
        for suffix in (".cmd", ".exe", ".bat"):
            found = shutil.which(command + suffix)
            if found:
                return found
    return command


def _validated_stdio_command(server: dict) -> tuple[str, list[str], str]:
    command = str(server.get("command", "") or "").strip()
    if not command:
        raise ValueError(_tr("McpBridge.stdio_command_empty", default="stdio MCP command is empty"))
    command = _resolve_command(command)
    command_name = os.path.basename(command).lower()
    if command_name not in _ALLOWED_STDIO_PYTHON_COMMANDS:
        raise ValueError(_tr(
            "McpBridge.stdio_command_not_allowed",
            default="stdio MCP command is not allowed: {command}",
            command=server.get("command", ""),
        ))

    args = _server_args(server)
    script_index = 0
    if command_name in {"py", "py.exe"} and args and re.fullmatch(r"-\d+(\.\d+)?", args[0]):
        script_index = 1
    if len(args) <= script_index:
        raise ValueError(_tr(
            "McpBridge.stdio_script_missing",
            default="stdio MCP script is missing.",
        ))

    script_path = Path(args[script_index]).expanduser()
    if not script_path.is_absolute():
        cwd = Path(str(server.get("cwd", "") or _APP_DIR)).expanduser()
        script_path = cwd / script_path
    script_path = script_path.resolve()
    if script_path != _BUNDLED_STDIO_MCP_SCRIPT:
        raise ValueError(_tr(
            "McpBridge.stdio_script_not_allowed",
            default="stdio MCP script is not allowed: {script}",
            script=str(args[script_index]),
        ))

    args = list(args)
    args[script_index] = str(_BUNDLED_STDIO_MCP_SCRIPT)
    return command, args, str(_APP_DIR)


def _stdio_client(server: dict) -> "StdioMcpClient":
    key = _client_key(server)
    with _LOCK:
        client = _CLIENTS.get(key)
        if client is None or not client.alive:
            client = StdioMcpClient(server)
            _CLIENTS[key] = client
        return client


def _thread_nam() -> QNetworkAccessManager:
    nam = getattr(_thread_local, "nam", None)
    if nam is None:
        _thread_local.nam = QNetworkAccessManager()
    return _thread_local.nam


def _request_http_json(server: dict, payload: dict) -> dict:
    url = str(server.get("url", "") or "").strip()
    if not url:
        raise ValueError(_tr("McpBridge.http_url_empty", default="HTTP MCP server url is empty"))
    timeout = int(server.get("timeout_seconds", 30) or 30)
    auth = str(server.get("authorization", "") or "").strip()
    body = json.dumps(payload).encode("utf-8")

    request = QNetworkRequest(QUrl(url))
    request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
    request.setRawHeader(b"Accept", b"application/json, text/event-stream")
    if auth:
        auth_val = auth if auth.lower().startswith("bearer ") else f"Bearer {auth}"
        request.setRawHeader(b"Authorization", auth_val.encode("utf-8"))
    request.setTransferTimeout(timeout * 1000)

    nam = _thread_nam()
    loop = QEventLoop()
    reply = nam.post(request, QByteArray(body))
    reply.finished.connect(loop.quit)
    loop.exec()

    error_code = reply.error()
    status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0

    if error_code != QNetworkReply.NoError or int(status_code) >= 400:
        raw_bytes = bytes(reply.readAll()) if reply.isOpen() else b""
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        reply.deleteLater()
        if int(status_code) >= 400:
            raise urllib.error.HTTPError(
                url, int(status_code), raw_text or reply.errorString(),
                dict(reply.rawHeaderPairs()), None,
            )
        raise urllib.error.URLError(reply.errorString())

    raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
    reply.deleteLater()

    raw = raw.strip()
    if raw.startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data and data != "[DONE]":
                return json.loads(data)
        raise ValueError(_tr("McpBridge.http_empty_event_stream", default="HTTP MCP server returned empty event stream"))
    return json.loads(raw)


def _http_request_with_init(server: dict, method: str, params: dict | None = None) -> dict:
    req_id = int(time.time() * 1000) % 1_000_000_000
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    try:
        return _request_http_json(server, payload)
    except urllib.error.HTTPError:
        raise
    except Exception:
        init = {
            "jsonrpc": "2.0",
            "id": req_id + 1,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "BandoriPet", "version": "1.0"},
            },
        }
        _request_http_json(server, init)
        return _request_http_json(server, payload)


def _list_http_tools(server: dict) -> list[dict]:
    response = _http_request_with_init(server, "tools/list", {})
    if response.get("error"):
        raise RuntimeError(response["error"])
    result = response.get("result", {})
    tools = result.get("tools", []) if isinstance(result, dict) else []
    return tools if isinstance(tools, list) else []


def _call_http_tool(server: dict, name: str, arguments: dict) -> str:
    response = _http_request_with_init(server, "tools/call", {"name": name, "arguments": arguments})
    if response.get("error"):
        raise RuntimeError(response["error"])
    return _mcp_result_text(response.get("result", {}))


def _mcp_result_text(result) -> str:
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    if result.get("isError"):
        prefix = "MCP tool returned an error: "
    else:
        prefix = ""
    parts = []
    for item in result.get("content", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        elif item.get("type") == "image":
            parts.append("[MCP image output omitted]")
        elif item:
            parts.append(json.dumps(item, ensure_ascii=False))
    if result.get("structuredContent") is not None:
        parts.append(json.dumps(result.get("structuredContent"), ensure_ascii=False))
    return prefix + ("\n".join(part for part in parts if part).strip() or json.dumps(result, ensure_ascii=False))


class StdioMcpClient:
    def __init__(self, server: dict):
        self._server = dict(server)
        self._lock = threading.RLock()
        self._responses: queue.Queue[dict] = queue.Queue()
        self._next_id = 1
        self._initialized = False
        command, args, cwd = _validated_stdio_command(server)
        self._process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            text=False,
            bufsize=0,
            **hidden_subprocess_kwargs(),
        )
        self._reader = threading.Thread(target=self._read_stdout, name=f"MCP:{server.get('label','stdio')}", daemon=True)
        self._reader.start()
        self._initialize()

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def list_tools(self) -> list[dict]:
        result = self._request("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        return _mcp_result_text(result)

    def _initialize(self):
        if self._initialized:
            return
        self._request("initialize", {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "BandoriPet", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})
        self._initialized = True

    def _read_stdout(self):
        stdout = self._process.stdout
        if stdout is None:
            return
        reader = getattr(stdout, "read1", stdout.read)
        buffer = b""
        while True:
            chunk = reader(4096)
            if not chunk:
                break
            buffer += chunk
            while True:
                message, buffer = _extract_stdio_message(buffer)
                if message is None:
                    break
                self._responses.put(message)

    def _request(self, method: str, params: dict | None = None) -> dict:
        with self._lock:
            if not self.alive:
                raise RuntimeError(_tr("McpBridge.process_not_running", default="MCP server process is not running"))
            req_id = self._next_id
            self._next_id += 1
            message = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                message["params"] = params
            self._write(message)
            deadline = time.monotonic() + int(self._server.get("timeout_seconds", 30) or 30)
            while time.monotonic() < deadline:
                try:
                    response = self._responses.get(timeout=max(0.1, min(1.0, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if response.get("id") != req_id:
                    continue
                if response.get("error"):
                    raise RuntimeError(response["error"])
                return response.get("result", {})
            raise TimeoutError(_tr("McpBridge.request_timeout", default="MCP request timed out: {method}", method=method))

    def _notify(self, method: str, params: dict | None = None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def _write(self, message: dict):
        stdin = self._process.stdin
        if stdin is None:
            raise RuntimeError(_tr("McpBridge.stdin_closed", default="MCP server stdin is closed"))
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        stdin.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        stdin.write(payload)
        stdin.flush()


def _extract_stdio_message(buffer: bytes) -> tuple[dict | None, bytes]:
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
                try:
                    content_length = int(value.strip())
                except ValueError:
                    raise RuntimeError(_tr("McpBridge.invalid_content_length", default="MCP server response Content-Length is not a valid integer"))
                break
        if content_length is None:
            raise RuntimeError(_tr("McpBridge.missing_content_length", default="MCP server response missing Content-Length"))
        body_start = header_end + 4
        body_end = body_start + content_length
        if len(buffer) < body_end:
            return None, buffer
        try:
            message = json.loads(buffer[body_start:body_end].decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None, buffer[body_end:]
        return message, buffer[body_end:]
    line_end = buffer.find(b"\n")
    if line_end < 0:
        return None, buffer
    line = buffer[:line_end].decode("utf-8", errors="replace").strip()
    if not line:
        return None, buffer[line_end + 1:]
    try:
        return json.loads(line), buffer[line_end + 1:]
    except json.JSONDecodeError:
        return None, buffer[line_end + 1:]
