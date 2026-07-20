from __future__ import annotations

import os
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .protocol import RpcPeer, connect_local_peer


class PluginComponentBridge(QObject):
    """RPC adapter used by pet/chat/settings/radial child processes."""

    connected_changed = Signal(bool)
    contributions_changed = Signal()

    def __init__(self, component: str, parent: QObject | None = None):
        super().__init__(parent)
        self.component = str(component)
        self.peer: RpcPeer | None = None
        self._services: dict[str, tuple[Callable[[Any], Any], str, int]] = {}
        self._native_contexts: dict[str, Any] = {}
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.timeout.connect(self.connect)

    @property
    def available(self) -> bool:
        return bool(self.peer is not None and self.peer.connected)

    def connect(self) -> bool:
        if self.available:
            return True
        server_name = os.environ.get("BANDORI_PLUGIN_RPC_NAME", "").strip()
        token = os.environ.get("BANDORI_PLUGIN_COMPONENT_TOKEN", "").strip()
        if not server_name or not token:
            return False
        try:
            peer = connect_local_peer(server_name, timeout_ms=1000, parent=self)
            peer.register_handler("component.service.invoke", self._invoke_service)
            peer.register_handler("callback.invoke", self._invoke_native_callback)
            peer.register_handler(
                "component.contributions.changed",
                lambda _params: self.contributions_changed.emit(),
            )
            peer.disconnected.connect(self._disconnected)
            peer.call("auth", {
                "role": "component",
                "component": self.component,
                "token": token,
            }, timeout_ms=2000)
            self.peer = peer
            self._sync_services()
            self.connected_changed.emit(True)
            return True
        except Exception:
            self.peer = None
            if not self._connect_timer.isActive():
                self._connect_timer.start(2000)
            return False

    def close(self) -> None:
        self._connect_timer.stop()
        if self.peer is not None:
            self.peer.socket.abort()
        self.peer = None

    def register_service(
        self,
        name: str,
        handler: Callable[[Any], Any],
        *,
        permission: str = "",
        priority: int = 0,
    ) -> None:
        self._services[str(name)] = (handler, str(permission), int(priority))
        if self.available:
            self._sync_services()

    def dispatch_event(self, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.connect() or self.peer is None:
            return {
                "event": str(event), "payload": payload or {},
                "cancelled": False, "reason": "", "errors": [],
            }
        return self.peer.call("component.event.dispatch", {
            "event": str(event), "payload": payload or {},
        }, timeout_ms=10_000)

    def notify_event(self, event: str, payload: dict[str, Any] | None = None) -> None:
        if self.connect() and self.peer is not None:
            try:
                self.peer.notify("component.event.notify", {
                    "event": str(event), "payload": payload or {},
                })
            except Exception:
                pass

    def contributions(self, kind: str = "ui", location: str = "") -> list[dict[str, Any]]:
        if not self.connect() or self.peer is None:
            return []
        return list(self.peer.call("component.contributions.list", {
            "kind": str(kind), "location": str(location),
        }, timeout_ms=2000) or [])

    def invoke_contribution(self, kind: str, item_id: str, payload: Any = None) -> Any:
        if not self.connect() or self.peer is None:
            raise RuntimeError("Plugin supervisor is unavailable")
        return self.peer.call("component.contribution.invoke", {
            "kind": str(kind),
            "id": str(item_id),
            "payload": payload,
        }, timeout_ms=12_000)

    def call(self, method: str, params: Any = None, *, timeout_ms: int = 10_000) -> Any:
        if not self.connect() or self.peer is None:
            raise RuntimeError("Plugin supervisor is unavailable")
        return self.peer.call(method, params, timeout_ms=timeout_ms)

    def notify(self, method: str, params: Any = None) -> None:
        if self.connect() and self.peer is not None:
            self.peer.notify(method, params)

    def native_transport(self, plugin_id: str) -> "NativeComponentTransport":
        return NativeComponentTransport(self, str(plugin_id))

    def plugin_admin(self, method: str, params: dict[str, Any] | None = None, *, timeout_ms: int = 30_000) -> Any:
        return self.call(
            f"component.plugins.{method}",
            params or {},
            timeout_ms=timeout_ms,
        )

    def _sync_services(self) -> None:
        if self.peer is None:
            return
        self.peer.call("component.services.register", {
            "services": [
                {"name": name, "permission": permission, "priority": priority}
                for name, (_handler, permission, priority) in self._services.items()
            ],
        }, timeout_ms=2000)

    def _invoke_service(self, params: Any) -> Any:
        if not isinstance(params, dict):
            raise ValueError("Component service invocation must be an object")
        name = str(params.get("service", "") or "")
        registration = self._services.get(name)
        if registration is None:
            raise KeyError(f"Unknown component plugin service: {name}")
        return registration[0](params.get("payload"))

    def _invoke_native_callback(self, params: Any) -> Any:
        if not isinstance(params, dict):
            raise ValueError("Native callback invocation must be an object")
        plugin_id = str(params.get("plugin_id", "") or "")
        context = self._native_contexts.get(plugin_id)
        if context is None:
            raise KeyError(f"Native plugin context is unavailable: {plugin_id}")
        return context.invoke(str(params.get("callback_id", "")), params.get("payload"))

    def _disconnected(self) -> None:
        self.peer = None
        self.connected_changed.emit(False)
        if not self._connect_timer.isActive():
            self._connect_timer.start(2000)


class NativeComponentTransport:
    def __init__(self, bridge: PluginComponentBridge, plugin_id: str):
        self.bridge = bridge
        self.plugin_id = str(plugin_id)
        self.context = None

    def attach_context(self, context) -> None:
        self.context = context
        self.bridge._native_contexts[self.plugin_id] = context

    def call(self, method: str, params: Any = None, *, timeout_ms: int = 10_000) -> Any:
        return self.bridge.call("component.plugin.call", {
            "plugin_id": self.plugin_id,
            "method": str(method),
            "params": {} if params is None else params,
        }, timeout_ms=timeout_ms)

    def notify(self, method: str, params: Any = None) -> None:
        self.bridge.notify("component.plugin.event", {
            "plugin_id": self.plugin_id,
            "method": str(method),
            "params": {} if params is None else params,
        })

    def invoke_contribution(self, kind: str, item_id: str, payload: Any = None) -> Any:
        return self.bridge.invoke_contribution(kind, item_id, payload)
