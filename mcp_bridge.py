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

from PySide6.QtCore import QByteArray, QEventLoop, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from i18n_manager import tr as _tr
from app_info import APP_NAME
from mcp_base import MAX_MCP_CONTENT_LENGTH
from process_utils import app_base_dir, hidden_subprocess_kwargs, run_off_gui_thread
from tool_arguments import parse_tool_arguments

_PROTOCOL_VERSION = "2025-06-18"
_TOOL_PREFIX = "mcp__"
_TOOL_NAME_MAP: dict[str, tuple[dict, str]] = {}
_CLIENTS: dict[str, "StdioMcpClient"] = {}
_HTTP_SESSIONS: dict[str, dict] = {}


_LOCK = threading.RLock()
_thread_local = threading.local()
_APP_DIR = Path(app_base_dir()).resolve()


def _server_timeout_seconds(server: dict) -> int:
    try:
        timeout = int(server.get("timeout_seconds", 30) or 30)
    except (TypeError, ValueError, OverflowError):
        timeout = 30
    return max(1, min(3600, timeout))


def mcp_proxy_tools(config: dict, exclude_native: bool = False) -> list[dict]:
    if not _mcp_enabled(config):
        return []
    tools = []
    tool_name_map_updates = {}
    cancel_event = config.get("_cancel_event")
    for server in _enabled_servers(config):
        if _is_native_only(server):
            continue
        if exclude_native and _can_use_native_server(config, server):
            continue
        try:
            for item in _list_server_tools(server, cancel_event):
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
        except InterruptedError:
            return []
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
        if not _can_use_native_server(config, server):
            continue
        url = str(server.get("url", "") or "").strip()
        connector_id = str(server.get("connector_id", "") or "").strip()
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


def _can_use_native_server(config: dict, server: dict) -> bool:
    if not bool(config.get("llm_mcp_use_native", True)):
        return False
    if server.get("transport") == "stdio":
        return False
    url = str(server.get("url", "") or "").strip()
    connector_id = str(server.get("connector_id", "") or "").strip()
    if not url and not connector_id:
        return False
    require_approval = str(server.get("require_approval", "always") or "always").lower()
    # This app has no interactive mcp_approval_response UI loop yet.
    return require_approval == "never"


def test_mcp_servers(config: dict) -> tuple[bool, str]:
    if not _mcp_enabled(config):
        return False, _tr("McpBridge.disabled", default="MCP is disabled in settings.")
    servers = _enabled_servers(config)
    if not servers:
        return False, _tr("McpBridge.no_enabled_servers", default="No enabled MCP servers were found.")

    lines = []
    cancel_event = config.get("_cancel_event")
    ok_count = 0
    warning_count = 0
    fail_count = 0
    for server in servers:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("MCP test cancelled")
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
                tools = _list_http_tools(server, cancel_event)
            else:
                tools = _list_server_tools(server, cancel_event)
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


def call_mcp_tool(public_name: str, arguments, cancel_event=None) -> str:
    arguments = parse_tool_arguments(arguments)
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
        if cancel_event is not None and cancel_event.is_set():
            return "MCP tool call cancelled."
        if server.get("transport") == "http":
            return _call_http_tool(server, tool_name, arguments, cancel_event=cancel_event)
        return _stdio_client(server).call_tool(tool_name, arguments, cancel_event=cancel_event)
    except InterruptedError:
        return "MCP tool call cancelled."
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


def _list_server_tools(server: dict, cancel_event=None) -> list[dict]:
    allowed = server.get("allowed_tools", [])
    if isinstance(allowed, str):
        allowed = [part.strip() for part in allowed.split(",") if part.strip()]
    if server.get("transport") == "http":
        tools = _list_http_tools(server, cancel_event)
    else:
        tools = _stdio_client(server).list_tools(cancel_event)
    if isinstance(allowed, list) and allowed:
        allowed_set = {str(name) for name in allowed}
        tools = [tool for tool in tools if str(tool.get("name", "")) in allowed_set]
    return tools


def _client_key(server: dict) -> str:
    args = " ".join(_server_args(server))
    env = json.dumps(server.get("env", {}), ensure_ascii=False, sort_keys=True)
    return f"{server.get('label','')}|{server.get('command','')}|{args}|{server.get('cwd','')}|{env}"


def _http_session_key(server: dict) -> str:
    return "|".join((
        str(server.get("url", "") or "").strip(),
        str(server.get("authorization", "") or "").strip(),
    ))


def _http_session(server: dict) -> dict:
    key = _http_session_key(server)
    with _LOCK:
        return _HTTP_SESSIONS.setdefault(key, {
            "initialized": False,
            "session_id": "",
            "protocol_version": _PROTOCOL_VERSION,
        })


def _reset_http_session(server: dict):
    with _LOCK:
        _HTTP_SESSIONS.pop(_http_session_key(server), None)


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
    args = _server_args(server)
    cwd = Path(str(server.get("cwd", "") or _APP_DIR)).expanduser().resolve()
    if not cwd.is_dir():
        raise NotADirectoryError(str(cwd))
    return command, args, str(cwd)


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


def _request_http_json(server: dict, payload: dict, cancel_event=None) -> dict:
    return run_off_gui_thread(lambda: _request_http_json_direct(server, payload, cancel_event))


def _request_http_json_direct(server: dict, payload: dict, cancel_event=None) -> dict:
    url = str(server.get("url", "") or "").strip()
    if not url:
        raise ValueError(_tr("McpBridge.http_url_empty", default="HTTP MCP server url is empty"))
    timeout = _server_timeout_seconds(server)
    auth = str(server.get("authorization", "") or "").strip()
    body = json.dumps(payload).encode("utf-8")

    request = QNetworkRequest(QUrl(url))
    request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
    request.setRawHeader(b"Accept", b"application/json, text/event-stream")
    if auth:
        auth_val = auth if auth.lower().startswith("bearer ") else f"Bearer {auth}"
        request.setRawHeader(b"Authorization", auth_val.encode("utf-8"))
    state = _http_session(server)
    if payload.get("method") != "initialize":
        request.setRawHeader(
            b"MCP-Protocol-Version",
            str(state.get("protocol_version") or _PROTOCOL_VERSION).encode("ascii", errors="ignore"),
        )
        session_id = str(state.get("session_id", "") or "")
        if session_id:
            request.setRawHeader(b"Mcp-Session-Id", session_id.encode("ascii", errors="ignore"))
    request.setTransferTimeout(timeout * 1000)

    nam = _thread_nam()
    loop = QEventLoop()
    reply = nam.post(request, QByteArray(body))
    reply.finished.connect(loop.quit)
    cancel_timer = None
    if cancel_event is not None:
        cancel_timer = QTimer()
        cancel_timer.setInterval(50)
        def abort_if_cancelled():
            if cancel_event.is_set():
                reply.abort()
                loop.quit()
        cancel_timer.timeout.connect(abort_if_cancelled)
        cancel_timer.start()
    loop.exec()
    if cancel_timer is not None:
        cancel_timer.stop()
    if cancel_event is not None and cancel_event.is_set():
        reply.abort()
        reply.deleteLater()
        if payload.get("method") != "initialize":
            _send_http_cancel_notification(server, payload.get("id"))
        raise InterruptedError("MCP request cancelled")

    error_code = reply.error()
    status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute) or 0
    error_string = reply.errorString()
    session_header = bytes(reply.rawHeader("Mcp-Session-Id")).decode("ascii", errors="ignore").strip()
    if payload.get("method") == "initialize" and session_header:
        state["session_id"] = session_header

    if error_code != QNetworkReply.NoError or int(status_code) >= 400:
        raw_bytes = bytes(reply.readAll()) if reply.isOpen() else b""
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        reply.deleteLater()
        if error_code == QNetworkReply.NetworkError.TimeoutError and payload.get("method") != "initialize":
            _send_http_cancel_notification(server, payload.get("id"))
        if int(status_code) >= 400:
            raise urllib.error.HTTPError(
                url, int(status_code), raw_text or error_string,
                dict(reply.rawHeaderPairs()), None,
            )
        raise urllib.error.URLError(error_string)

    raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
    reply.deleteLater()

    raw = raw.strip()
    if not raw:
        return {}
    return _parse_http_response(raw, expected_id=payload.get("id"))


def _send_http_cancel_notification(server: dict, request_id):
    if request_id is None:
        return
    cancellation = {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {
            "requestId": request_id,
            "reason": "User requested cancellation or request timeout",
        },
    }
    retry_server = dict(server)
    retry_server["timeout_seconds"] = min(2, _server_timeout_seconds(server))
    try:
        _request_http_json_direct(retry_server, cancellation, None)
    except Exception:
        pass


def _parse_http_response(raw: str, expected_id=None) -> dict:
    raw = str(raw or "").strip()
    if not (raw.startswith("event:") or "\ndata:" in raw or raw.startswith("data:")):
        return json.loads(raw)
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(
            line.split(":", 1)[1].lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        ).strip()
        if not data or data == "[DONE]":
            continue
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            continue
        if expected_id is None or message.get("id") == expected_id:
            return message
    raise ValueError(_tr("McpBridge.http_empty_event_stream", default="HTTP MCP server returned no matching response event"))


def _http_request_with_init(server: dict, method: str, params: dict | None = None, cancel_event=None) -> dict:
    state = _http_session(server)
    if method != "initialize" and not state.get("initialized", False):
        init = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1_000_000_000,
            "method": "initialize",
            "params": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": APP_NAME, "version": "1.0"},
            },
        }
        init_response = _request_http_json(server, init, cancel_event)
        if init_response.get("error"):
            raise RuntimeError(init_response["error"])
        init_result = init_response.get("result", {}) if isinstance(init_response, dict) else {}
        if isinstance(init_result, dict) and init_result.get("protocolVersion"):
            state["protocol_version"] = str(init_result["protocolVersion"])
        initialized = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
        _request_http_json(server, initialized, cancel_event)
        state["initialized"] = True

    req_id = int(time.time() * 1000) % 1_000_000_000
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    try:
        return _request_http_json(server, payload, cancel_event)
    except urllib.error.HTTPError as exc:
        if exc.code != 404 or not state.get("session_id"):
            raise
        _reset_http_session(server)
        return _http_request_with_init(server, method, params, cancel_event)


def _list_http_tools(server: dict, cancel_event=None) -> list[dict]:
    response = _http_request_with_init(server, "tools/list", {}, cancel_event)
    if response.get("error"):
        raise RuntimeError(response["error"])
    result = response.get("result", {})
    tools = result.get("tools", []) if isinstance(result, dict) else []
    return tools if isinstance(tools, list) else []


def _call_http_tool(server: dict, name: str, arguments: dict, cancel_event=None) -> str:
    response = _http_request_with_init(
        server,
        "tools/call",
        {"name": name, "arguments": arguments},
        cancel_event,
    )
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
        self._reader_error = None
        command, args, cwd = _validated_stdio_command(server)
        self._process = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=cwd,
            text=False,
            bufsize=0,
            env=self._process_environment(),
            **hidden_subprocess_kwargs(),
        )
        self._reader = threading.Thread(target=self._read_stdout, name=f"MCP:{server.get('label','stdio')}", daemon=True)
        try:
            self._reader.start()
            self._initialize()
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def list_tools(self, cancel_event=None) -> list[dict]:
        result = self._request("tools/list", {}, cancel_event)
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict, cancel_event=None) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments}, cancel_event)
        return _mcp_result_text(result)

    def close(self):
        with self._lock:
            process = self._process
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            try:
                if process.stdout is not None:
                    process.stdout.close()
            except Exception:
                pass
        reader = getattr(self, "_reader", None)
        if reader is not None and reader is not threading.current_thread():
            try:
                reader.join(timeout=0.5)
            except RuntimeError:
                pass

    def _process_environment(self) -> dict:
        environment = os.environ.copy()
        configured = self._server.get("env", {})
        if isinstance(configured, dict):
            environment.update({str(key): str(value) for key, value in configured.items()})
        return environment

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

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
            self._reader_error = RuntimeError(_tr("McpBridge.stdout_closed", default="MCP server stdout is closed"))
            return
        reader = getattr(stdout, "read1", stdout.read)
        buffer = b""
        try:
            while True:
                chunk = reader(4096)
                if not chunk:
                    if self.alive:
                        self._reader_error = RuntimeError(_tr("McpBridge.stdout_closed", default="MCP server stdout is closed"))
                    break
                buffer += chunk
                while True:
                    message, buffer = _extract_stdio_message(buffer)
                    if message is None:
                        break
                    self._responses.put(message)
        except Exception as exc:
            self._reader_error = exc

    def _request(self, method: str, params: dict | None = None, cancel_event=None) -> dict:
        with self._lock:
            if not self.alive:
                raise RuntimeError(_tr("McpBridge.process_not_running", default="MCP server process is not running"))
            req_id = self._next_id
            self._next_id += 1
            message = {"jsonrpc": "2.0", "id": req_id, "method": method}
            if params is not None:
                message["params"] = params
            self._write(message)
            deadline = time.monotonic() + _server_timeout_seconds(self._server)
            while time.monotonic() < deadline:
                if self._reader_error is not None:
                    raise RuntimeError(str(self._reader_error))
                if cancel_event is not None and cancel_event.is_set():
                    self._cancel_inflight(req_id, "User requested cancellation")
                    raise InterruptedError("MCP request cancelled")
                try:
                    response = self._responses.get(timeout=max(0.05, min(0.1, deadline - time.monotonic())))
                except queue.Empty:
                    continue
                if response.get("id") != req_id:
                    continue
                if response.get("error"):
                    raise RuntimeError(response["error"])
                return response.get("result", {})
            self._cancel_inflight(req_id, f"MCP request timed out: {method}")
            raise TimeoutError(_tr("McpBridge.request_timeout", default="MCP request timed out: {method}", method=method))

    def _cancel_inflight(self, request_id: int, reason: str):
        try:
            self._notify("notifications/cancelled", {
                "requestId": request_id,
                "reason": reason,
            })
        except Exception:
            pass
        finally:
            self.close()

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
        stdin.write(payload + b"\n")
        stdin.flush()


def close_mcp_clients():
    with _LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
        _TOOL_NAME_MAP.clear()
        _HTTP_SESSIONS.clear()
    for client in clients:
        try:
            client.close()
        except Exception:
            pass


def _extract_stdio_message(buffer: bytes) -> tuple[dict | None, bytes]:
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
                try:
                    content_length = int(value.strip())
                except ValueError:
                    raise RuntimeError(_tr("McpBridge.invalid_content_length", default="MCP server response Content-Length is not a valid integer"))
                break
        if content_length is None:
            raise RuntimeError(_tr("McpBridge.missing_content_length", default="MCP server response missing Content-Length"))
        if not 0 <= content_length <= MAX_MCP_CONTENT_LENGTH:
            raise RuntimeError(_tr(
                "McpBridge.invalid_content_length",
                default="MCP server response Content-Length is outside the allowed range",
            ))
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
