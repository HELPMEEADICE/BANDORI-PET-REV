from __future__ import annotations

import base64
import copy
import hmac
import json
import os
import secrets
import shutil
import threading
import time
import urllib.parse
import fnmatch
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtNetwork import QLocalServer

from process_utils import app_base_dir, ipc_server_name, process_program_and_args
from public_network import open_public_url

from .installer import PluginInstaller
from .models import PluginError, PluginManifest, ScanReport
from .paths import PluginPaths, PluginStateStore, plugin_paths
from .protocol import RpcPeer, RpcRemoteError
from .registry import (
    ContributionRegistry,
    PluginEventBus,
    PluginServiceRegistry,
    merge_patch,
    permission_allowed,
)


MAX_STORAGE_BYTES = 1024 * 1024
MAX_NETWORK_INLINE_BYTES = 1024 * 1024
MAX_NETWORK_REQUEST_BYTES = 1024 * 1024
MAX_NETWORK_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_FILESYSTEM_TEXT_BYTES = 2 * 1024 * 1024
FAULT_WINDOW_SECONDS = 10 * 60
FAULT_DISABLE_COUNT = 3
WORKER_STARTUP_TIMEOUT_MS = 10_000
UI_LOCATIONS = frozenset({
    "settings_page", "tray", "radial_menu", "chat_action", "pet_overlay",
})
FORBIDDEN_PLUGIN_REQUEST_HEADERS = frozenset({
    "connection", "content-length", "host", "proxy-connection",
    "te", "trailer", "transfer-encoding", "upgrade",
})


def _require_dict(value: Any, label: str = "parameters") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RpcRemoteError("invalid_params", f"{label} must be an object")
    return value


def _origin_matches(pattern: str, url: str) -> bool:
    if str(pattern or "").strip() == "*":
        return urllib.parse.urlsplit(str(url or "").strip()).scheme.lower() in {"http", "https"}
    expected = urllib.parse.urlsplit(str(pattern or "").strip())
    actual = urllib.parse.urlsplit(str(url or "").strip())
    if expected.scheme.lower() not in {"http", "https"} or actual.scheme.lower() not in {"http", "https"}:
        return False
    if expected.scheme.lower() != actual.scheme.lower():
        return False
    expected_host = str(expected.hostname or "").lower()
    actual_host = str(actual.hostname or "").lower()
    if expected_host.startswith("*."):
        suffix = expected_host[1:]
        if not actual_host.endswith(suffix) or actual_host == expected_host[2:]:
            return False
    elif expected_host != actual_host:
        return False
    expected_port = expected.port or (443 if expected.scheme.lower() == "https" else 80)
    actual_port = actual.port or (443 if actual.scheme.lower() == "https" else 80)
    return expected_port == actual_port


class LocalPluginTransport:
    def __init__(self, supervisor: "PluginSupervisor", plugin_id: str):
        self.supervisor = supervisor
        self.plugin_id = str(plugin_id)
        self.context = None

    def call(self, method: str, params: Any = None, *, timeout_ms: int = 10_000) -> Any:
        del timeout_ms
        data = params if isinstance(params, dict) else {}
        if method == "events.subscribe" and self.context is not None:
            callback_id = str(data.get("subscription_id", ""))
            callback = self.context._callbacks.get(callback_id)
            if callback is None:
                raise KeyError(f"Unknown native callback: {callback_id}")
            self.supervisor.events.subscribe(
                self.plugin_id,
                callback_id,
                str(data.get("event", "")),
                int(data.get("priority", 0)),
                callback,
            )
            return {"ok": True}
        return self.supervisor.handle_plugin_call(self.plugin_id, method, params, peer=None)

    def notify(self, method: str, params: Any = None) -> None:
        self.supervisor.handle_plugin_event(self.plugin_id, method, params)


class PluginSupervisor(QObject):
    plugin_started = Signal(str)
    plugin_stopped = Signal(str)
    plugin_faulted = Signal(str, str)
    contributions_changed = Signal()
    plugin_update_available = Signal(str, str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        paths: PluginPaths | None = None,
        safe_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self.paths = paths or plugin_paths()
        self.state = PluginStateStore(self.paths)
        self.installer = PluginInstaller(self.paths, self.state)
        self.safe_mode = bool(safe_mode)
        self.events = PluginEventBus()
        self.services = PluginServiceRegistry()
        self.contributions = ContributionRegistry()
        self.server = QLocalServer(self)
        self.server_name = f"{ipc_server_name()}-plugin-rpc"
        self.component_token = secrets.token_urlsafe(32)
        self._plugin_tokens: dict[str, str] = {}
        self._peers: set[RpcPeer] = set()
        self._sessions: dict[RpcPeer, dict[str, Any]] = {}
        self._plugin_peers: dict[str, RpcPeer] = {}
        self._component_peers: dict[str, set[RpcPeer]] = {}
        self._native_transports: dict[str, LocalPluginTransport] = {}
        self._processes: dict[str, QProcess] = {}
        self._startup_timers: dict[str, QTimer] = {}
        self._ready_plugins: set[str] = set()
        self._temporary_files: dict[str, dict[str, tuple[Path, float]]] = {}
        self._expected_stops: set[str] = set()
        self._app_started_payload: dict[str, Any] | None = None
        self._update_check_running = False
        self._update_check_lock = threading.Lock()
        self._closing = False
        QLocalServer.removeServer(self.server_name)
        if not self.server.listen(self.server_name):
            raise PluginError(f"Could not start plugin RPC server: {self.server.errorString()}")
        self.server.newConnection.connect(self._accept_connections)
        os.environ["BANDORI_PLUGIN_RPC_NAME"] = self.server_name
        os.environ["BANDORI_PLUGIN_COMPONENT_TOKEN"] = self.component_token

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        for plugin_id in list(self._processes):
            self.stop_plugin(plugin_id, reason="application_shutdown")
        for peer in list(self._peers):
            peer.socket.abort()
        self.server.close()
        QLocalServer.removeServer(self.server_name)

    def local_transport(self, plugin_id: str) -> LocalPluginTransport:
        transport = LocalPluginTransport(self, plugin_id)
        self._native_transports[str(plugin_id)] = transport
        return transport

    def register_service(
        self,
        name: str,
        handler: Callable[[Any], Any],
        *,
        permission: str = "",
        priority: int = 0,
    ) -> None:
        self.services.register(
            name, handler, permission=permission, owner="core", priority=priority
        )

    def start_enabled_plugins(self) -> None:
        if self.safe_mode:
            return
        for item in self.installer.list_installed():
            if item.get("enabled") and item.get("execution") == "managed":
                try:
                    self.start_plugin(item["id"])
                except Exception as exc:
                    self._record_fault(item["id"], f"startup: {exc}")

    def check_updates_async(self) -> bool:
        with self._update_check_lock:
            if self._update_check_running:
                return False
            self._update_check_running = True

        def run():
            try:
                for item in self.installer.list_installed():
                    plugin_id = str(item.get("id", "") or "")
                    manifest = item.get("active", {}).get("manifest", {})
                    if not plugin_id or not isinstance(manifest, dict) or not manifest.get("update_url"):
                        continue
                    try:
                        update = self.installer.check_update(plugin_id)
                    except Exception as exc:
                        self._write_log(plugin_id, {"level": "warning", "message": f"Update check failed: {exc}"})
                        continue
                    if update.get("update_available"):
                        version = str(update.get("latest_version", "") or "")
                        self._write_log(plugin_id, {"level": "info", "message": f"Plugin update available: {version}"})
                        self.plugin_update_available.emit(plugin_id, version)
            finally:
                with self._update_check_lock:
                    self._update_check_running = False

        threading.Thread(target=run, name="plugin-update-check", daemon=True).start()
        return True

    def start_plugin(self, plugin_id: str) -> None:
        plugin_id = str(plugin_id)
        if self.safe_mode:
            raise PluginError("Third-party plugins cannot start while safe mode is active")
        existing = self._processes.get(plugin_id)
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            return
        item = self.state.plugin(plugin_id)
        if not item or item.get("execution") != "managed":
            raise PluginError(f"Managed plugin is not installed: {plugin_id}")
        active_version = str(item.get("active_version", "") or "")
        active = item.get("versions", {}).get(active_version, {})
        report = ScanReport.from_dict(active.get("scan", {}))
        if report.blocked:
            raise PluginError("Plugin security report blocks execution")
        root = Path(active.get("path", "")).resolve()
        manifest = PluginManifest.from_dict(active.get("manifest", {}))
        if not root.is_dir() or manifest.id != plugin_id:
            raise PluginError("Installed plugin files are missing or inconsistent")

        token = secrets.token_urlsafe(32)
        self._plugin_tokens[plugin_id] = token
        process = QProcess(self)
        program, arguments = process_program_and_args(str(app_base_dir()), "plugin_worker.py", [
            "--plugin-id", plugin_id,
            "--plugin-root", str(root),
        ])
        process.setProgram(program)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(root))
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("BANDORI_PLUGIN_RPC_NAME", self.server_name)
        environment.insert("BANDORI_PLUGIN_RPC_TOKEN", token)
        environment.remove("BANDORI_PLUGIN_COMPONENT_TOKEN")
        process.setProcessEnvironment(environment)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(
            lambda p=process, pid=plugin_id: self._read_process_error(pid, p)
        )
        process.finished.connect(
            lambda exit_code, exit_status, pid=plugin_id, p=process: self._process_finished(
                pid, p, exit_code, exit_status
            )
        )
        self._processes[plugin_id] = process
        process.start()
        if not process.waitForStarted(3000):
            self._processes.pop(plugin_id, None)
            raise PluginError(f"Plugin worker could not start: {process.errorString()}")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda pid=plugin_id, p=process: self._startup_timeout(pid, p)
        )
        self._startup_timers[plugin_id] = timer
        timer.start(WORKER_STARTUP_TIMEOUT_MS)

    def stop_plugin(self, plugin_id: str, *, reason: str = "disabled") -> None:
        plugin_id = str(plugin_id)
        self._cancel_startup_timer(plugin_id)
        peer = self._plugin_peers.get(plugin_id)
        process = self._processes.get(plugin_id)
        if peer is not None or process is not None:
            self._expected_stops.add(plugin_id)
        else:
            self._expected_stops.discard(plugin_id)
        if peer is not None and peer.connected:
            try:
                peer.call("plugin.shutdown", {"reason": reason}, timeout_ms=1500)
            except Exception:
                pass
        if process is not None and process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
        self._cleanup_plugin(plugin_id)

    def reload_plugin(self, plugin_id: str) -> None:
        self.stop_plugin(plugin_id, reason="reload")
        self._expected_stops.discard(str(plugin_id))
        self.start_plugin(plugin_id)

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        item = self.installer.set_enabled(plugin_id, enabled)
        if item.get("execution") == "managed":
            if enabled:
                if not self.safe_mode:
                    self.start_plugin(plugin_id)
            else:
                self.stop_plugin(plugin_id)
        return item

    def dispatch_event(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.events.dispatch(name, payload)

    def notify_event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        for subscription in self.events.subscriptions(name):
            self._notify_subscription(subscription, payload)

    def mark_app_started(self, payload: dict[str, Any] | None = None) -> None:
        self._app_started_payload = copy.deepcopy(payload or {})
        self.notify_event("app.started", self._app_started_payload)

    def _notify_subscription(self, subscription, payload: dict[str, Any] | None) -> None:
        try:
            peer = self._plugin_peers.get(subscription.plugin_id)
            if peer is not None and peer.connected:
                peer.notify("callback.notify", {
                    "plugin_id": subscription.plugin_id,
                    "callback_id": subscription.subscription_id,
                    "payload": copy.deepcopy(payload or {}),
                })
            else:
                subscription.invoke(copy.deepcopy(payload or {}))
        except Exception as exc:
            self._record_fault(subscription.plugin_id, f"event {subscription.event}: {exc}")

    def _notify_plugin_event(
        self,
        plugin_id: str,
        name: str,
        payload: dict[str, Any] | None,
    ) -> None:
        for subscription in self.events.subscriptions(name):
            if subscription.plugin_id == str(plugin_id):
                self._notify_subscription(subscription, payload)

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            peer = RpcPeer(socket, self)
            self._peers.add(peer)
            self._sessions[peer] = {"authenticated": False, "role": "", "identity": ""}
            peer.register_handler("auth", lambda params, p=peer: self._authenticate(p, params))
            for method in (
                "events.subscribe", "events.unsubscribe", "events.emit", "services.call",
                "services.call_next",
                "services.register", "services.unregister",
                "commands.register", "commands.unregister", "tools.register", "tools.unregister",
                "ui.register", "ui.update", "ui.remove", "storage.get", "storage.set",
                "storage.delete", "storage.keys", "network.request", "filesystem.read_text",
                "filesystem.write_text", "filesystem.list", "temporary.read", "temporary.release",
            ):
                peer.register_handler(
                    method,
                    lambda params, p=peer, m=method: self._peer_plugin_call(p, m, params),
                )
            peer.register_handler(
                "component.services.register",
                lambda params, p=peer: self._register_component_services(p, params),
            )
            peer.register_handler(
                "component.contributions.list",
                lambda params, p=peer: self._list_component_contributions(p, params),
            )
            peer.register_handler(
                "component.contribution.invoke",
                lambda params, p=peer: self._invoke_component_contribution(p, params),
            )
            peer.register_handler(
                "component.event.dispatch",
                lambda params, p=peer: self._component_dispatch_event(p, params),
            )
            peer.register_handler(
                "component.event.notify",
                lambda params, p=peer: self._component_notify_event(p, params),
            )
            peer.register_handler(
                "component.plugin.call",
                lambda params, p=peer: self._component_plugin_call(p, params),
            )
            peer.register_handler(
                "component.plugin.event",
                lambda params, p=peer: self._component_plugin_event(p, params),
            )
            for method in (
                "list", "stage_local", "stage_url", "commit", "cancel", "set_enabled", "set_permissions",
                "rollback", "uninstall", "check_update",
            ):
                peer.register_handler(
                    f"component.plugins.{method}",
                    lambda params, p=peer, m=method: self._component_plugin_admin(p, m, params),
                )
            peer.register_handler("plugin.ready", lambda params, p=peer: self._plugin_ready(p, params))
            peer.register_handler("plugin.fault", lambda params, p=peer: self._plugin_fault(p, params))
            peer.register_handler("log.write", lambda params, p=peer: self._peer_log(p, params))
            peer.disconnected.connect(lambda p=peer: self._peer_disconnected(p))
            timer = QTimer(peer)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=peer: self._abort_unauthenticated(p))
            timer.start(5000)
            self._sessions[peer]["auth_timer"] = timer

    def _authenticate(self, peer: RpcPeer, params: Any) -> dict[str, Any]:
        data = _require_dict(params, "auth parameters")
        session = self._sessions.get(peer)
        if session is None or session.get("authenticated"):
            raise RpcRemoteError("auth_failed", "RPC peer is already authenticated or unknown")
        role = str(data.get("role", "") or "")
        identity = ""
        if role == "plugin":
            identity = str(data.get("plugin_id", "") or "")
            expected = self._plugin_tokens.get(identity, "")
        elif role == "component":
            identity = str(data.get("component", "") or "")
            expected = self.component_token
        else:
            raise RpcRemoteError("auth_failed", "Unknown RPC peer role")
        if not expected or not hmac.compare_digest(expected, str(data.get("token", "") or "")):
            raise RpcRemoteError("auth_failed", "Plugin RPC authentication failed")
        session.update({"authenticated": True, "role": role, "identity": identity})
        timer = session.pop("auth_timer", None)
        if timer is not None:
            timer.stop()
        if role == "plugin":
            previous = self._plugin_peers.get(identity)
            if previous is not None and previous is not peer:
                previous.socket.abort()
            self._plugin_peers[identity] = peer
        else:
            self._component_peers.setdefault(identity, set()).add(peer)
            session["service_owner"] = f"component:{identity}:{id(peer)}"
        return {"ok": True, "protocol": 1, "identity": identity}

    def _abort_unauthenticated(self, peer: RpcPeer) -> None:
        if not self._sessions.get(peer, {}).get("authenticated"):
            peer.socket.abort()

    def _session(self, peer: RpcPeer, role: str = "") -> dict[str, Any]:
        session = self._sessions.get(peer, {})
        if not session.get("authenticated") or (role and session.get("role") != role):
            raise RpcRemoteError("unauthorized", "Plugin RPC peer is not authorized for this method")
        return session

    def _peer_plugin_call(self, peer: RpcPeer, method: str, params: Any) -> Any:
        session = self._session(peer, "plugin")
        return self.handle_plugin_call(str(session["identity"]), method, params, peer=peer)

    def _plugin_permissions(self, plugin_id: str) -> dict[str, Any]:
        item = self.state.plugin(plugin_id)
        value = item.get("granted_permissions", {})
        return value if isinstance(value, dict) else {}

    def _require_permission(self, plugin_id: str, permission: str) -> None:
        if self.state.plugin(plugin_id).get("execution") == "native":
            return
        if not permission_allowed(self._plugin_permissions(plugin_id), permission):
            raise RpcRemoteError(
                "permission_denied",
                f"Plugin {plugin_id} was not granted permission: {permission}",
            )

    def _require_event_permission(self, plugin_id: str, mode: str, event: str) -> None:
        self._require_permission(plugin_id, f"events.{mode}")
        permissions = self._plugin_permissions(plugin_id)
        value = permissions.get("events", {}) if isinstance(permissions, dict) else {}
        value = value.get(mode) if isinstance(value, dict) else value
        if value is True or self.state.plugin(plugin_id).get("execution") == "native":
            return
        patterns = (
            value if isinstance(value, list)
            else [key for key, allowed in value.items() if allowed] if isinstance(value, dict)
            else []
        )
        if not any(fnmatch.fnmatchcase(str(event), str(pattern)) for pattern in patterns):
            raise RpcRemoteError(
                "permission_denied",
                f"Plugin {plugin_id} was not granted {mode} access to event: {event}",
            )

    def handle_plugin_call(
        self,
        plugin_id: str,
        method: str,
        params: Any,
        *,
        peer: RpcPeer | None,
    ) -> Any:
        data = _require_dict(params or {})
        if method == "events.subscribe":
            event = str(data.get("event", "") or "")
            permission = "intercept" if event.endswith(".before") else "observe"
            self._require_event_permission(plugin_id, permission, event)
            subscription_id = str(data.get("subscription_id", "") or "")
            if not subscription_id:
                raise RpcRemoteError("invalid_params", "subscription_id is required")
            if peer is None:
                raise RpcRemoteError("invalid_state", "Native event callbacks register directly")
            self.events.subscribe(
                plugin_id,
                subscription_id,
                event,
                max(-1000, min(1000, int(data.get("priority", 0)))),
                lambda payload, p=peer, callback_id=subscription_id: self._invoke_plugin_callback(
                    plugin_id, callback_id, payload, timeout_ms=500, peer=p
                ),
            )
            return {"ok": True}
        if method == "events.unsubscribe":
            self.events.unsubscribe(plugin_id, str(data.get("subscription_id", "")))
            return {"ok": True}
        if method == "events.emit":
            event = str(data.get("event", ""))
            self._require_event_permission(plugin_id, "emit", event)
            return self.dispatch_event(event, data.get("payload", {}))
        if method in {"services.call", "services.call_next"}:
            service_name = str(data.get("service", "") or "")
            service = (
                self.services.resolve_after(service_name, f"plugin:{plugin_id}")
                if method == "services.call_next"
                else self.services.resolve(service_name)
            )
            if service is None:
                raise RpcRemoteError(
                    "service_not_found",
                    f"No callable {'next ' if method == 'services.call_next' else ''}plugin service: {service_name}",
                )
            for required_permission in self.services.required_permissions(service_name):
                self._require_permission(plugin_id, required_permission)
            if service_name == "config.get":
                payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
                key = str(payload.get("key", "") or "").lower()
                if any(part in key for part in ("key", "token", "password", "secret", "authorization")):
                    self._require_permission(plugin_id, "secrets.read")
            return service.handler(data.get("payload"))
        if method == "services.register":
            self._require_permission(plugin_id, "services.register")
            name = str(data.get("name", "") or "")
            callback_id = str(data.get("registration_id", "") or "")
            if not name or not callback_id:
                raise RpcRemoteError("invalid_params", "Service name and registration_id are required")
            self.services.register(
                name,
                lambda payload, pid=plugin_id, cid=callback_id, p=peer: self._invoke_plugin_callback(
                    pid, cid, payload, timeout_ms=10_000, peer=p
                ),
                permission=str(data.get("permission", "") or ""),
                owner=f"plugin:{plugin_id}",
                priority=max(-1000, min(1000, int(data.get("priority", 0)))),
            )
            return {"ok": True}
        if method == "services.unregister":
            self.services.unregister(str(data.get("name", "") or ""), f"plugin:{plugin_id}")
            return {"ok": True}
        if method in {"commands.register", "tools.register"}:
            kind = method.split(".", 1)[0]
            self._require_permission(plugin_id, "commands.register" if kind == "commands" else "llm.tools")
            item_id = str(data.get("registration_id", "") or "")
            spec = _require_dict(data.get("spec"), "registration spec")
            self.contributions.register(kind, plugin_id, item_id, spec)
            self._contributions_updated()
            return {"ok": True}
        if method in {"commands.unregister", "tools.unregister"}:
            kind = method.split(".", 1)[0]
            self.contributions.unregister(kind, plugin_id, str(data.get("registration_id", "")))
            self._contributions_updated()
            return {"ok": True}
        if method == "ui.register":
            spec = _require_dict(data.get("spec"), "UI spec")
            location = str(spec.get("location", "") or "")
            if int(spec.get("schema_version", 1) or 1) != 1 or location not in UI_LOCATIONS:
                raise RpcRemoteError("invalid_params", "UI spec schema or location is unsupported")
            self._require_permission(plugin_id, f"ui.{location}")
            item_id = str(spec.get("id", "") or "")
            if not item_id or len(json.dumps(spec, ensure_ascii=False)) > 256 * 1024:
                raise RpcRemoteError("invalid_params", "UI spec has no id or is too large")
            self.contributions.register("ui", plugin_id, item_id, spec)
            self._contributions_updated()
            return {"ok": True}
        if method == "ui.update":
            component_id = str(data.get("component_id", ""))
            patch = _require_dict(data.get("patch"))
            current = self.contributions.get_for_plugin("ui", plugin_id, component_id)
            if current is None:
                raise RpcRemoteError("not_found", f"Unknown UI contribution: {component_id}")
            updated_spec = merge_patch(current.get("spec", {}), patch)
            location = str(updated_spec.get("location", "") or "")
            if int(updated_spec.get("schema_version", 1) or 1) != 1 or location not in UI_LOCATIONS:
                raise RpcRemoteError("invalid_params", "UI spec schema or location is unsupported")
            self._require_permission(plugin_id, f"ui.{location}")
            self.contributions.update("ui", plugin_id, component_id, patch)
            self._contributions_updated()
            return {"ok": True}
        if method == "ui.remove":
            self.contributions.unregister("ui", plugin_id, str(data.get("component_id", "")))
            self._contributions_updated()
            return {"ok": True}
        if method.startswith("storage."):
            return self._storage_call(plugin_id, method, data)
        if method == "network.request":
            return self._network_request(plugin_id, data)
        if method.startswith("filesystem."):
            return self._filesystem_call(plugin_id, method, data)
        if method.startswith("temporary."):
            return self._temporary_call(plugin_id, method, data)
        raise RpcRemoteError("method_not_found", f"Unknown plugin API method: {method}")

    def handle_plugin_event(self, plugin_id: str, method: str, params: Any) -> None:
        if method == "log.write":
            self._write_log(plugin_id, _require_dict(params or {}))
            return
        raise RpcRemoteError("method_not_found", f"Unknown plugin event method: {method}")

    def _storage_path(self, plugin_id: str) -> Path:
        path = (self.paths.data / plugin_id / "storage.json").resolve()
        if not path.is_relative_to(self.paths.data.resolve()):
            raise RpcRemoteError("invalid_path", "Plugin data path is invalid")
        return path

    def _read_storage(self, plugin_id: str) -> dict[str, Any]:
        path = self._storage_path(plugin_id)
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _write_storage(self, plugin_id: str, value: dict[str, Any]) -> None:
        payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        if len(payload) > MAX_STORAGE_BYTES:
            raise RpcRemoteError("storage_limit", "Plugin storage exceeds 1 MiB")
        path = self._storage_path(plugin_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".json.{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _storage_call(self, plugin_id: str, method: str, data: dict[str, Any]) -> Any:
        key = str(data.get("key", "") or "")
        if method != "storage.keys" and (not key or len(key) > 128):
            raise RpcRemoteError("invalid_params", "Storage key must be 1-128 characters")
        storage = self._read_storage(plugin_id)
        if method == "storage.get":
            return storage.get(key)
        if method == "storage.keys":
            return sorted(storage)
        if method == "storage.set":
            storage[key] = data.get("value")
        elif method == "storage.delete":
            storage.pop(key, None)
        self._write_storage(plugin_id, storage)
        return {"ok": True}

    def _network_origins(self, plugin_id: str) -> list[str]:
        network = self._plugin_permissions(plugin_id).get("network", {})
        if network is True:
            return ["*"]
        if not isinstance(network, dict):
            return []
        origins = network.get("origins", [])
        return [str(item) for item in origins] if isinstance(origins, list) else []

    def _network_request(self, plugin_id: str, data: dict[str, Any]) -> dict[str, Any]:
        url = str(data.get("url", "") or "")
        method = str(data.get("method", "GET") or "GET").upper()
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            raise RpcRemoteError("unsupported_method", "Plugin network method is not supported")
        origins = self._network_origins(plugin_id)
        if not any(_origin_matches(pattern, url) for pattern in origins):
            raise RpcRemoteError("permission_denied", "Plugin URL is outside its approved network origins")
        raw_headers = data.get("headers", {}) if isinstance(data.get("headers"), dict) else {}
        headers: dict[str, str] = {}
        for key, value in raw_headers.items():
            name = str(key or "").strip()
            text = str(value or "")
            if (
                not name
                or name.lower() in FORBIDDEN_PLUGIN_REQUEST_HEADERS
                or any(character in name + text for character in ("\r", "\n", "\x00"))
            ):
                raise RpcRemoteError("invalid_params", f"Plugin request header is not allowed: {name}")
            headers[name] = text
        raw_body = data.get("body_base64")
        if raw_body is not None:
            try:
                body = base64.b64decode(str(raw_body), validate=True)
            except (ValueError, base64.binascii.Error) as exc:
                raise RpcRemoteError("invalid_params", "body_base64 is invalid") from exc
        elif data.get("body") is not None:
            body = str(data.get("body", "")).encode("utf-8")
        else:
            body = None
        if body is not None and len(body) > MAX_NETWORK_REQUEST_BYTES:
            raise RpcRemoteError("request_limit", "Plugin network request body exceeds 1 MiB")
        response, final_url = open_public_url(
            url,
            timeout=20,
            max_redirects=5,
            headers=headers,
            method=method,
            body=body,
            url_validator=lambda target: any(
                _origin_matches(pattern, target) for pattern in origins
            ),
            raise_for_status=False,
        )
        payload = bytearray()
        with response:
            while True:
                chunk = response.read(min(512 * 1024, MAX_NETWORK_RESPONSE_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > MAX_NETWORK_RESPONSE_BYTES:
                    break
            response_headers = {str(key): str(value) for key, value in response.headers.items()}
            status = response.status
        if len(payload) > MAX_NETWORK_RESPONSE_BYTES:
            raise RpcRemoteError("response_limit", "Plugin network response exceeds 16 MiB")
        result = {
            "status": status,
            "url": final_url,
            "headers": response_headers,
        }
        if len(payload) <= MAX_NETWORK_INLINE_BYTES:
            result["body_base64"] = base64.b64encode(payload).decode("ascii")
        else:
            reference = secrets.token_urlsafe(24)
            directory = self.paths.data / plugin_id / "temp"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{reference}.bin"
            path.write_bytes(payload)
            self._temporary_files.setdefault(plugin_id, {})[reference] = (path, time.time())
            result["body_ref"] = {"reference": reference, "size": len(payload)}
        return result

    def _temporary_call(self, plugin_id: str, method: str, data: dict[str, Any]) -> Any:
        reference = str(data.get("reference", "") or "")
        registered = self._temporary_files.get(plugin_id, {}).get(reference)
        if registered is None:
            raise RpcRemoteError("not_found", "Temporary file reference is unknown or expired")
        path, created = registered
        if time.time() - created > 10 * 60 or not path.is_file():
            self._temporary_files.get(plugin_id, {}).pop(reference, None)
            path.unlink(missing_ok=True)
            raise RpcRemoteError("not_found", "Temporary file reference is unknown or expired")
        if method == "temporary.release":
            self._temporary_files.get(plugin_id, {}).pop(reference, None)
            path.unlink(missing_ok=True)
            return {"ok": True}
        offset = max(0, int(data.get("offset", 0) or 0))
        size = max(1, min(512 * 1024, int(data.get("size", 512 * 1024) or 512 * 1024)))
        with path.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read(size)
        return {
            "body_base64": base64.b64encode(chunk).decode("ascii"),
            "offset": offset,
            "next_offset": offset + len(chunk),
            "eof": offset + len(chunk) >= path.stat().st_size,
        }

    def _filesystem_roots(self, plugin_id: str, mode: str) -> list[Path]:
        roots = [(self.paths.data / plugin_id).resolve()]
        filesystem = self._plugin_permissions(plugin_id).get("filesystem", {})
        if not isinstance(filesystem, dict):
            return roots
        values = filesystem.get(mode, [])
        if not isinstance(values, list):
            return roots
        for value in values:
            text = str(value or "").replace("$PLUGIN_DATA", str(roots[0]))
            try:
                roots.append(Path(text).expanduser().resolve())
            except OSError:
                continue
        return roots

    def _resolve_filesystem_path(self, plugin_id: str, value: str, mode: str) -> Path:
        data_root = (self.paths.data / plugin_id).resolve()
        raw = Path(str(value or ".")).expanduser()
        path = (data_root / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if not any(path.is_relative_to(root) for root in self._filesystem_roots(plugin_id, mode)):
            raise RpcRemoteError("permission_denied", f"Path is outside approved {mode} roots")
        return path

    def _filesystem_call(self, plugin_id: str, method: str, data: dict[str, Any]) -> Any:
        mode = "write" if method == "filesystem.write_text" else "read"
        path = self._resolve_filesystem_path(plugin_id, str(data.get("path", ".")), mode)
        if method == "filesystem.read_text":
            if path.stat().st_size > MAX_FILESYSTEM_TEXT_BYTES:
                raise RpcRemoteError("file_limit", "Text file exceeds 2 MiB")
            return path.read_text(encoding=str(data.get("encoding", "utf-8") or "utf-8"))
        if method == "filesystem.write_text":
            payload = str(data.get("text", "")).encode(str(data.get("encoding", "utf-8") or "utf-8"))
            if len(payload) > MAX_FILESYSTEM_TEXT_BYTES:
                raise RpcRemoteError("file_limit", "Text file exceeds 2 MiB")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            return {"ok": True}
        if not path.is_dir():
            raise RpcRemoteError("invalid_path", "Filesystem list target is not a directory")
        result = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.casefold())[:500]:
            result.append({
                "name": child.name,
                "path": str(child),
                "is_dir": child.is_dir(),
                "size": child.stat().st_size if child.is_file() else 0,
            })
        return result

    def _register_component_services(self, peer: RpcPeer, params: Any) -> dict[str, Any]:
        session = self._session(peer, "component")
        data = _require_dict(params)
        services = data.get("services", [])
        if not isinstance(services, list):
            raise RpcRemoteError("invalid_params", "services must be an array")
        owner = str(session["service_owner"])
        self.services.unregister_owner(owner)
        for item in services:
            item = _require_dict(item, "component service")
            name = str(item.get("name", "") or "")
            if not name:
                continue
            self.services.register(
                name,
                lambda payload, p=peer, service_name=name: p.call(
                    "component.service.invoke",
                    {"service": service_name, "payload": payload},
                    timeout_ms=10_000,
                ),
                permission=str(item.get("permission", "") or ""),
                owner=owner,
                priority=int(item.get("priority", 0)),
            )
        return {"ok": True}

    def _list_component_contributions(self, peer: RpcPeer, params: Any) -> list[dict[str, Any]]:
        self._session(peer, "component")
        data = _require_dict(params or {})
        return self.contributions.list(
            str(data.get("kind", "ui")), location=str(data.get("location", "") or "")
        )

    def _invoke_component_contribution(self, peer: RpcPeer, params: Any) -> Any:
        self._session(peer, "component")
        data = _require_dict(params)
        kind = str(data.get("kind", "") or "")
        item_id = str(data.get("id", "") or "")
        item = self.contributions.get(kind, item_id)
        if item is None or kind not in {"commands", "tools"}:
            raise RpcRemoteError("not_found", f"Unknown plugin contribution: {kind}/{item_id}")
        plugin_id = str(item.get("plugin_id", "") or "")
        return self._invoke_plugin_callback(
            plugin_id, item_id, data.get("payload"), timeout_ms=10_000,
            peer=self._plugin_peers.get(plugin_id),
        )

    def _invoke_plugin_callback(
        self,
        plugin_id: str,
        callback_id: str,
        payload: Any,
        *,
        timeout_ms: int,
        peer: RpcPeer | None,
    ) -> Any:
        try:
            if peer is not None and peer.connected:
                return peer.call(
                    "callback.invoke",
                    {"plugin_id": plugin_id, "callback_id": callback_id, "payload": payload},
                    timeout_ms=timeout_ms,
                )
            transport = self._native_transports.get(str(plugin_id))
            if transport is not None and transport.context is not None:
                return transport.context.invoke(callback_id, payload)
            raise RpcRemoteError("plugin_unavailable", f"Plugin callback is unavailable: {plugin_id}")
        except TimeoutError:
            if peer is not None:
                peer.socket.abort()
            process = self._processes.get(str(plugin_id))
            if process is not None and process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
            self._record_fault(plugin_id, f"callback timed out after {timeout_ms} ms")
            raise

    def _component_dispatch_event(self, peer: RpcPeer, params: Any) -> dict[str, Any]:
        self._session(peer, "component")
        data = _require_dict(params)
        return self.dispatch_event(str(data.get("event", "")), data.get("payload", {}))

    def _component_notify_event(self, peer: RpcPeer, params: Any) -> None:
        self._session(peer, "component")
        data = _require_dict(params)
        self.notify_event(str(data.get("event", "")), data.get("payload", {}))

    def _component_plugin_call(self, peer: RpcPeer, params: Any) -> Any:
        self._session(peer, "component")
        data = _require_dict(params)
        plugin_id = str(data.get("plugin_id", "") or "")
        item = self.state.plugin(plugin_id)
        if not item.get("enabled") or item.get("execution") != "native":
            raise RpcRemoteError("unauthorized", "Native plugin is not enabled")
        return self.handle_plugin_call(
            plugin_id,
            str(data.get("method", "") or ""),
            data.get("params", {}),
            peer=peer,
        )

    def _component_plugin_event(self, peer: RpcPeer, params: Any) -> None:
        self._session(peer, "component")
        data = _require_dict(params)
        plugin_id = str(data.get("plugin_id", "") or "")
        item = self.state.plugin(plugin_id)
        if not item.get("enabled") or item.get("execution") != "native":
            raise RpcRemoteError("unauthorized", "Native plugin is not enabled")
        self.handle_plugin_event(plugin_id, str(data.get("method", "")), data.get("params"))

    def _component_plugin_admin(self, peer: RpcPeer, method: str, params: Any) -> Any:
        self._session(peer, "component")
        data = _require_dict(params or {})
        if method == "list":
            return self.installer.list_installed()
        if method == "stage_local":
            return self.installer.stage_local(str(data.get("path", ""))).to_dict()
        if method == "stage_url":
            return self.installer.stage_url(
                str(data.get("url", "")),
                allow_insecure_http=bool(data.get("allow_insecure_http", False)),
                expected_sha256=str(data.get("sha256", "") or ""),
            ).to_dict()
        if method == "commit":
            token = str(data.get("token", "") or "")
            preview = self.installer._previews.get(token)
            plugin_id = preview.manifest.id if preview is not None else ""
            previous_item = self.state.plugin(plugin_id) if plugin_id else {}
            installed = self.installer.commit(
                token,
                enable=bool(data.get("enable", False)),
                trust_publisher=bool(data.get("trust_publisher", False)),
                allow_downgrade=bool(data.get("allow_downgrade", False)),
            )
            if plugin_id and previous_item.get("execution") == "managed":
                self.stop_plugin(plugin_id, reason="update")
            if (
                plugin_id
                and installed.get("enabled")
                and installed.get("execution") == "managed"
                and not self.safe_mode
            ):
                self.start_plugin(plugin_id)
            return installed
        if method == "cancel":
            self.installer.cancel(str(data.get("token", "") or ""))
            return {"ok": True}
        plugin_id = str(data.get("plugin_id", "") or "")
        if method == "set_enabled":
            return self.set_enabled(plugin_id, bool(data.get("enabled", False)))
        if method == "set_permissions":
            item = self.installer.set_permissions(plugin_id, data.get("permissions", {}))
            if item.get("execution") == "managed" and item.get("enabled") and not self.safe_mode:
                self.reload_plugin(plugin_id)
            return item
        if method == "rollback":
            previous_item = self.state.plugin(plugin_id)
            item = self.installer.rollback(plugin_id)
            if previous_item.get("execution") == "managed":
                self.stop_plugin(plugin_id, reason="rollback")
            if item.get("execution") == "managed" and item.get("enabled") and not self.safe_mode:
                self.start_plugin(plugin_id)
            return item
        if method == "uninstall":
            self.stop_plugin(plugin_id, reason="uninstall")
            self.installer.uninstall(plugin_id, delete_data=bool(data.get("delete_data", False)))
            return {"ok": True}
        if method == "check_update":
            return self.installer.check_update(plugin_id)
        raise RpcRemoteError("method_not_found", f"Unknown plugin admin method: {method}")

    def _plugin_ready(self, peer: RpcPeer, _params: Any) -> None:
        session = self._session(peer, "plugin")
        plugin_id = str(session["identity"])
        if plugin_id in self._ready_plugins:
            return
        self._ready_plugins.add(plugin_id)
        self._cancel_startup_timer(plugin_id)
        self.plugin_started.emit(plugin_id)
        if self._app_started_payload is not None:
            self._notify_plugin_event(plugin_id, "app.started", self._app_started_payload)

    def _plugin_fault(self, peer: RpcPeer, params: Any) -> None:
        session = self._session(peer, "plugin")
        data = _require_dict(params or {})
        message = str(data.get("message", "Plugin worker fault") or "Plugin worker fault")
        trace = str(data.get("traceback", "") or "")
        self._write_log(str(session["identity"]), {
            "level": "error", "message": message + ("\n" + trace if trace else ""),
        })
        self._record_fault(str(session["identity"]), message)

    def _peer_log(self, peer: RpcPeer, params: Any) -> None:
        session = self._session(peer, "plugin")
        self._write_log(str(session["identity"]), _require_dict(params or {}))

    def _write_log(self, plugin_id: str, data: dict[str, Any]) -> None:
        self.paths.logs.mkdir(parents=True, exist_ok=True)
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"[{str(data.get('level', 'info')).upper()}] {str(data.get('message', ''))}\n"
        )
        path = self.paths.logs / f"{plugin_id}.log"
        try:
            if path.is_file() and path.stat().st_size > 2 * 1024 * 1024:
                backup = path.with_suffix(".log.1")
                backup.unlink(missing_ok=True)
                os.replace(path, backup)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
        except OSError:
            pass

    def _contributions_updated(self) -> None:
        if self._closing:
            return
        self.contributions_changed.emit()
        for peers in self._component_peers.values():
            for peer in list(peers):
                if peer.connected:
                    try:
                        peer.notify("component.contributions.changed", {})
                    except Exception:
                        pass

    def _read_process_error(self, plugin_id: str, process: QProcess) -> None:
        text = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if text:
            self._write_log(plugin_id, {"level": "error", "message": text})

    def _process_finished(self, plugin_id: str, process: QProcess, exit_code: int, _status) -> None:
        is_current = self._processes.get(plugin_id) is process
        if is_current:
            self._cancel_startup_timer(plugin_id)
            self._processes.pop(plugin_id, None)
        expected = plugin_id in self._expected_stops
        self._expected_stops.discard(plugin_id)
        if is_current:
            self._cleanup_plugin(plugin_id)
        try:
            process.deleteLater()
        except RuntimeError:
            # The QObject parent may already have destroyed a delayed QProcess
            # before Qt delivers its queued ``finished`` callback.
            pass
        if is_current and not expected and exit_code != 0:
            self._record_fault(plugin_id, f"worker exited with code {exit_code}")
        if is_current and not self._closing:
            self.plugin_stopped.emit(plugin_id)

    def _cancel_startup_timer(self, plugin_id: str) -> None:
        timer = self._startup_timers.pop(str(plugin_id), None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _startup_timeout(self, plugin_id: str, process: QProcess) -> None:
        self._startup_timers.pop(str(plugin_id), None)
        if self._processes.get(str(plugin_id)) is not process:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
        self._record_fault(plugin_id, "worker did not finish activation within 10 seconds")

    def _record_fault(self, plugin_id: str, message: str) -> None:
        now = time.time()
        disabled = False
        def update(state):
            nonlocal disabled
            item = state["plugins"].get(plugin_id)
            if not isinstance(item, dict):
                return
            faults = [
                float(value) for value in item.get("faults", [])
                if now - float(value) <= FAULT_WINDOW_SECONDS
            ]
            # A worker generally reports the exception and then exits. Treat
            # those two signals as one incident instead of burning two of the
            # three circuit-breaker attempts.
            if not faults or now - faults[-1] > 2.0:
                faults.append(now)
            item["faults"] = faults
            item["last_fault"] = str(message)
            if len(faults) >= FAULT_DISABLE_COUNT:
                item["enabled"] = False
                item["disabled_reason"] = "circuit_breaker"
                disabled = True
        self.state.mutate(update)
        if not self._closing:
            self.plugin_faulted.emit(plugin_id, str(message))
        if disabled:
            self.stop_plugin(plugin_id, reason="circuit_breaker")

    def _cleanup_plugin(self, plugin_id: str) -> None:
        self._cancel_startup_timer(plugin_id)
        self._ready_plugins.discard(str(plugin_id))
        peer = self._plugin_peers.pop(plugin_id, None)
        if peer is not None and peer.connected:
            peer.socket.abort()
        self.events.remove_plugin(plugin_id)
        self.services.unregister_owner(f"plugin:{plugin_id}")
        self.contributions.remove_plugin(plugin_id)
        self._plugin_tokens.pop(plugin_id, None)
        self._native_transports.pop(plugin_id, None)
        for path, _created in self._temporary_files.pop(plugin_id, {}).values():
            path.unlink(missing_ok=True)
        self._contributions_updated()

    def _peer_disconnected(self, peer: RpcPeer) -> None:
        session = self._sessions.pop(peer, {})
        self._peers.discard(peer)
        role = session.get("role")
        identity = str(session.get("identity", "") or "")
        if role == "plugin" and self._plugin_peers.get(identity) is peer:
            self._plugin_peers.pop(identity, None)
            self.events.remove_plugin(identity)
            self.contributions.remove_plugin(identity)
            self._contributions_updated()
        elif role == "component":
            peers = self._component_peers.get(identity, set())
            peers.discard(peer)
            if not peers:
                self._component_peers.pop(identity, None)
            self.services.unregister_owner(str(session.get("service_owner", "")))
