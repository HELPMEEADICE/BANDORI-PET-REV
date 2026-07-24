from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Callable


def permission_allowed(permissions: dict[str, Any], permission: str) -> bool:
    if not permission:
        return True
    if not isinstance(permissions, dict):
        return False
    parts = [part for part in str(permission).split(".") if part]
    current: Any = permissions
    for index, part in enumerate(parts):
        if current is True:
            return True
        if isinstance(current, list):
            remainder = ".".join(parts[index:])
            return part in current or remainder in current or "*" in current
        if not isinstance(current, dict):
            return False
        if "*" in current and current["*"] is True:
            return True
        if part not in current:
            return False
        current = current[part]
    return current is True or (isinstance(current, (list, dict)) and bool(current))


def merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(target)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_patch(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


@dataclass(frozen=True)
class EventSubscription:
    plugin_id: str
    subscription_id: str
    event: str
    priority: int
    invoke: Callable[[dict[str, Any]], Any]


class PluginEventBus:
    def __init__(self):
        self._lock = threading.RLock()
        self._subscriptions: dict[str, EventSubscription] = {}

    @staticmethod
    def _key(plugin_id: str, subscription_id: str) -> str:
        return f"{plugin_id}\x00{subscription_id}"

    def subscribe(
        self,
        plugin_id: str,
        subscription_id: str,
        event: str,
        priority: int,
        invoke: Callable[[dict[str, Any]], Any],
    ) -> None:
        subscription = EventSubscription(
            str(plugin_id), str(subscription_id), str(event), int(priority), invoke
        )
        with self._lock:
            self._subscriptions[
                self._key(subscription.plugin_id, subscription.subscription_id)
            ] = subscription

    def unsubscribe(self, plugin_id: str, subscription_id: str) -> None:
        with self._lock:
            self._subscriptions.pop(
                self._key(str(plugin_id), str(subscription_id)), None
            )

    def remove_plugin(self, plugin_id: str) -> None:
        with self._lock:
            stale = [
                key for key, item in self._subscriptions.items()
                if item.plugin_id == str(plugin_id)
            ]
            for key in stale:
                self._subscriptions.pop(key, None)

    def subscriptions(self, event: str) -> list[EventSubscription]:
        with self._lock:
            selected = [item for item in self._subscriptions.values() if item.event == event]
        return sorted(selected, key=lambda item: (-item.priority, item.plugin_id, item.subscription_id))

    def dispatch(self, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        current = copy.deepcopy(payload or {})
        cancelled = False
        reason = ""
        errors: list[dict[str, str]] = []
        for subscription in self.subscriptions(str(event)):
            try:
                result = subscription.invoke(copy.deepcopy(current))
            except Exception as exc:
                errors.append({"plugin_id": subscription.plugin_id, "error": str(exc)})
                continue
            if result is None:
                continue
            if not isinstance(result, dict):
                errors.append({
                    "plugin_id": subscription.plugin_id,
                    "error": "event callback result must be an object or null",
                })
                continue
            action = str(result.get("action", "continue") or "continue").lower()
            patch = result.get("patch")
            if isinstance(patch, dict):
                current = merge_patch(current, patch)
            if action == "cancel":
                cancelled = True
                reason = str(result.get("reason", "") or "")
                break
        return {
            "event": str(event),
            "payload": current,
            "cancelled": cancelled,
            "reason": reason,
            "errors": errors,
        }


@dataclass
class ServiceRegistration:
    name: str
    handler: Callable[[Any], Any]
    permission: str = ""
    owner: str = "core"
    priority: int = 0


class PluginServiceRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._services: dict[str, list[ServiceRegistration]] = {}

    def register(
        self,
        name: str,
        handler: Callable[[Any], Any],
        *,
        permission: str = "",
        owner: str = "core",
        priority: int = 0,
    ) -> None:
        registration = ServiceRegistration(str(name), handler, str(permission), str(owner), int(priority))
        with self._lock:
            items = [item for item in self._services.get(registration.name, []) if item.owner != registration.owner]
            items.append(registration)
            items.sort(key=lambda item: (-item.priority, item.owner))
            self._services[registration.name] = items

    def unregister_owner(self, owner: str) -> None:
        with self._lock:
            for name in list(self._services):
                items = [item for item in self._services[name] if item.owner != owner]
                if items:
                    self._services[name] = items
                else:
                    self._services.pop(name, None)

    def unregister(self, name: str, owner: str) -> None:
        with self._lock:
            items = [item for item in self._services.get(str(name), []) if item.owner != str(owner)]
            if items:
                self._services[str(name)] = items
            else:
                self._services.pop(str(name), None)

    def resolve(self, name: str) -> ServiceRegistration | None:
        with self._lock:
            items = self._services.get(str(name), [])
            return items[0] if items else None

    def resolve_after(self, name: str, owner: str) -> ServiceRegistration | None:
        with self._lock:
            items = self._services.get(str(name), [])
            for index, item in enumerate(items):
                if item.owner == str(owner):
                    return items[index + 1] if index + 1 < len(items) else None
            return None

    def required_permissions(self, name: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted({
                item.permission
                for item in self._services.get(str(name), [])
                if item.permission
            }))

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._services)


class ContributionRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, dict[str, Any]]] = {
            "commands": {}, "tools": {}, "ui": {},
        }

    @staticmethod
    def _key(plugin_id: str, item_id: str) -> str:
        return f"{plugin_id}\x00{item_id}"

    def register(self, kind: str, plugin_id: str, item_id: str, spec: dict[str, Any]) -> None:
        with self._lock:
            self._items.setdefault(kind, {})[self._key(str(plugin_id), str(item_id))] = {
                "plugin_id": str(plugin_id),
                "id": str(item_id),
                "spec": copy.deepcopy(spec),
            }

    def update(self, kind: str, plugin_id: str, item_id: str, patch: dict[str, Any]) -> None:
        with self._lock:
            item = self._items.setdefault(kind, {}).get(self._key(str(plugin_id), str(item_id)))
            if item is None:
                raise KeyError(f"Unknown {kind} contribution: {item_id}")
            item["spec"] = merge_patch(item.get("spec", {}), patch)

    def unregister(self, kind: str, plugin_id: str, item_id: str) -> None:
        with self._lock:
            self._items.setdefault(kind, {}).pop(
                self._key(str(plugin_id), str(item_id)), None
            )

    def remove_plugin(self, plugin_id: str) -> None:
        with self._lock:
            for values in self._items.values():
                stale = [key for key, item in values.items() if item.get("plugin_id") == str(plugin_id)]
                for key in stale:
                    values.pop(key, None)

    def list(self, kind: str, *, location: str = "") -> list[dict[str, Any]]:
        with self._lock:
            result = [copy.deepcopy(item) for item in self._items.get(kind, {}).values()]
        if location:
            result = [item for item in result if item.get("spec", {}).get("location") == location]
        return sorted(result, key=lambda item: (int(item.get("spec", {}).get("order", 0)), item["plugin_id"], item["id"]))

    def get(self, kind: str, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            matches = [
                item for item in self._items.get(str(kind), {}).values()
                if item.get("id") == str(item_id)
            ]
            return copy.deepcopy(matches[0]) if len(matches) == 1 else None

    def get_for_plugin(self, kind: str, plugin_id: str, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(str(kind), {}).get(
                self._key(str(plugin_id), str(item_id))
            )
            return copy.deepcopy(item) if item is not None else None
