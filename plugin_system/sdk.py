from __future__ import annotations

import json
import threading
import types
import uuid
from pathlib import Path
from typing import Any, Callable, Protocol


class Transport(Protocol):
    def call(self, method: str, params: Any = None, *, timeout_ms: int = 10_000) -> Any: ...
    def notify(self, method: str, params: Any = None) -> None: ...


def _coerce_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _coerce_json_value(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_json_value(child) for child in value]
    # Lupa tables expose ``items`` but are intentionally not Python dicts.
    items = getattr(value, "items", None)
    if callable(items):
        pairs = list(items())
        integer_keys = [key for key, _child in pairs if isinstance(key, int) and key >= 1]
        if len(integer_keys) == len(pairs) and sorted(integer_keys) == list(range(1, len(pairs) + 1)):
            values = {int(key): child for key, child in pairs}
            return [_coerce_json_value(values[index]) for index in range(1, len(pairs) + 1)]
        return {str(key): _coerce_json_value(child) for key, child in pairs}
    raise TypeError(f"Plugin API value is not JSON compatible: {type(value).__name__}")


def _json_value(value: Any) -> Any:
    try:
        return json.loads(json.dumps(_coerce_json_value(value), ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise TypeError("Plugin API values must be JSON serializable") from exc


class EventsApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def on(self, name: str, callback: Callable[[dict[str, Any]], Any], priority: int = 0) -> str:
        if not callable(callback):
            raise TypeError("Event callback must be callable")
        subscription_id = uuid.uuid4().hex
        self._context._callbacks[subscription_id] = callback
        self._context._transport.call("events.subscribe", {
            "subscription_id": subscription_id,
            "event": str(name),
            "priority": max(-1000, min(1000, int(priority))),
        })
        return subscription_id

    def off(self, subscription_id: str) -> None:
        self._context._callbacks.pop(str(subscription_id), None)
        self._context._transport.call("events.unsubscribe", {
            "subscription_id": str(subscription_id),
        })

    def emit(self, name: str, payload: dict[str, Any] | None = None) -> Any:
        return self._context._transport.call("events.emit", {
            "event": str(name),
            "payload": _json_value(payload or {}),
        })


class ServicesApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def call(self, name: str, payload: Any = None, timeout_ms: int = 10_000) -> Any:
        return self._context._transport.call("services.call", {
            "service": str(name),
            "payload": _json_value(payload),
        }, timeout_ms=int(timeout_ms))

    def call_next(self, name: str, payload: Any = None, timeout_ms: int = 10_000) -> Any:
        """Call the next lower-priority implementation from a service wrapper."""
        return self._context._transport.call("services.call_next", {
            "service": str(name),
            "payload": _json_value(payload),
        }, timeout_ms=int(timeout_ms))

    def register(
        self,
        name: str,
        handler: Callable[[Any], Any],
        *,
        priority: int = 0,
        permission: str = "",
    ) -> str:
        if not callable(handler):
            raise TypeError("Service handler must be callable")
        registration_id = uuid.uuid4().hex
        self._context._callbacks[registration_id] = handler
        self._context._transport.call("services.register", {
            "registration_id": registration_id,
            "name": str(name),
            "priority": int(priority),
            "permission": str(permission),
        })
        return registration_id

    def unregister(self, name: str, registration_id: str) -> None:
        self._context._callbacks.pop(str(registration_id), None)
        self._context._transport.call("services.unregister", {
            "name": str(name),
            "registration_id": str(registration_id),
        })


class _RegistrationApi:
    def __init__(self, context: "PluginContext", kind: str):
        self._context = context
        self._kind = kind

    def register(self, spec: dict[str, Any], handler: Callable[[Any], Any]) -> str:
        spec = _json_value(spec)
        if not isinstance(spec, dict) or not callable(handler):
            raise TypeError("Registration requires a JSON object and a callable handler")
        registration_id = uuid.uuid4().hex
        self._context._callbacks[registration_id] = handler
        self._context._transport.call(f"{self._kind}.register", {
            "registration_id": registration_id,
            "spec": _json_value(spec),
        })
        return registration_id

    def unregister(self, registration_id: str) -> None:
        self._context._callbacks.pop(str(registration_id), None)
        self._context._transport.call(f"{self._kind}.unregister", {
            "registration_id": str(registration_id),
        })


class UiApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def register(self, spec: dict[str, Any]) -> str:
        spec = _json_value(spec)
        if not isinstance(spec, dict):
            raise TypeError("UI registration requires a JSON object")
        component_id = str(spec.get("id", "")).strip() or uuid.uuid4().hex
        payload = dict(spec)
        payload["id"] = component_id
        self._context._transport.call("ui.register", {"spec": _json_value(payload)})
        return component_id

    def update(self, component_id: str, patch: dict[str, Any]) -> None:
        self._context._transport.call("ui.update", {
            "component_id": str(component_id),
            "patch": _json_value(patch),
        })

    def remove(self, component_id: str) -> None:
        self._context._transport.call("ui.remove", {"component_id": str(component_id)})


class StorageApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def get(self, key: str, default: Any = None) -> Any:
        result = self._context._transport.call("storage.get", {"key": str(key)})
        return default if result is None else result

    def set(self, key: str, value: Any) -> None:
        self._context._transport.call("storage.set", {
            "key": str(key),
            "value": _json_value(value),
        })

    def delete(self, key: str) -> None:
        self._context._transport.call("storage.delete", {"key": str(key)})

    def keys(self) -> list[str]:
        return list(self._context._transport.call("storage.keys", {}) or [])


class NetworkApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._context._transport.call("network.request", _json_value(request), timeout_ms=30_000)


class FilesystemApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return str(self._context._transport.call("filesystem.read_text", {
            "path": str(path), "encoding": str(encoding),
        }))

    def write_text(self, path: str, text: str, encoding: str = "utf-8") -> None:
        self._context._transport.call("filesystem.write_text", {
            "path": str(path), "text": str(text), "encoding": str(encoding),
        })

    def list(self, path: str = ".") -> list[dict[str, Any]]:
        return list(self._context._transport.call("filesystem.list", {"path": str(path)}) or [])


class TemporaryApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def read(self, reference: str, offset: int = 0, size: int = 512 * 1024) -> dict[str, Any]:
        return dict(self._context._transport.call("temporary.read", {
            "reference": str(reference),
            "offset": max(0, int(offset)),
            "size": max(1, min(512 * 1024, int(size))),
        }) or {})

    def release(self, reference: str) -> None:
        self._context._transport.call("temporary.release", {"reference": str(reference)})


class LogApi:
    def __init__(self, context: "PluginContext"):
        self._context = context

    def _write(self, level: str, message: Any) -> None:
        self._context._transport.notify(
            "log.write", {"level": level, "message": str(message)[:65_536]}
        )

    def debug(self, message: Any) -> None: self._write("debug", message)
    def info(self, message: Any) -> None: self._write("info", message)
    def warning(self, message: Any) -> None: self._write("warning", message)
    def error(self, message: Any) -> None: self._write("error", message)


class PluginContext:
    """Language-neutral public API passed to managed plugin entrypoints."""

    PUBLIC_ATTRIBUTES = frozenset({
        "plugin_id", "events", "services", "commands", "tools", "ui",
        "storage", "network", "filesystem", "temporary", "log",
    })

    def __init__(self, plugin_id: str, transport: Transport):
        self.plugin_id = str(plugin_id)
        self._transport = transport
        self._callbacks: dict[str, Callable[[Any], Any]] = {}
        self._callback_lock = threading.RLock()
        self.events = EventsApi(self)
        self.services = ServicesApi(self)
        self.commands = _RegistrationApi(self, "commands")
        self.tools = _RegistrationApi(self, "tools")
        self.ui = UiApi(self)
        self.storage = StorageApi(self)
        self.network = NetworkApi(self)
        self.filesystem = FilesystemApi(self)
        self.temporary = TemporaryApi(self)
        self.log = LogApi(self)

    def invoke(self, callback_id: str, payload: Any) -> Any:
        with self._callback_lock:
            callback = self._callbacks.get(str(callback_id))
        if callback is None:
            raise KeyError(f"Plugin callback is no longer registered: {callback_id}")
        return _json_value(callback(payload))

    def close(self) -> None:
        with self._callback_lock:
            self._callbacks.clear()


class _PublicObjectView:
    __slots__ = ("_target", "_allowed")

    def __init__(self, target: Any, allowed: set[str] | frozenset[str]):
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_allowed", frozenset(allowed))

    def __getattribute__(self, name: str) -> Any:
        if name in {"__class__", "__dir__"}:
            return object.__getattribute__(self, name)
        allowed = object.__getattribute__(self, "_allowed")
        if name not in allowed:
            raise AttributeError(f"Managed plugin attribute access denied: {name}")
        return getattr(object.__getattribute__(self, "_target"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"Managed plugin attribute writes are denied: {name}")

    def __dir__(self):
        return sorted(object.__getattribute__(self, "_allowed"))


def managed_context_view(context: PluginContext) -> _PublicObjectView:
    api_methods = {
        "events": {"on", "off", "emit"},
        "services": {"call", "call_next", "register", "unregister"},
        "commands": {"register", "unregister"},
        "tools": {"register", "unregister"},
        "ui": {"register", "update", "remove"},
        "storage": {"get", "set", "delete", "keys"},
        "network": {"request"},
        "filesystem": {"read_text", "write_text", "list"},
        "temporary": {"read", "release"},
        "log": {"debug", "info", "warning", "error"},
    }
    public = {"plugin_id": context.plugin_id}
    for name, methods in api_methods.items():
        public[name] = _PublicObjectView(getattr(context, name), methods)
    return _PublicObjectView(types.SimpleNamespace(**public), PluginContext.PUBLIC_ATTRIBUTES)


SDK_PUBLIC_ATTRIBUTE_NAMES = frozenset({
    *PluginContext.PUBLIC_ATTRIBUTES,
    "on", "off", "emit", "call", "call_next", "register", "unregister", "update", "remove",
    "get", "set", "delete", "keys", "request", "read_text", "write_text", "list",
    "read", "release", "debug", "info", "warning", "error",
})
