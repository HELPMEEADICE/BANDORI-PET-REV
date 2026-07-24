from __future__ import annotations

import importlib.util
import os
import sys
import traceback
import types
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import PluginManifest
from .paths import PluginPaths, PluginStateStore, plugin_paths
from .sdk import PluginContext


@dataclass
class NativeHostContext:
    plugin_id: str
    component: str
    api: PluginContext
    application: Any = None
    controller: Any = None
    window: Any = None
    objects: dict[str, Any] = field(default_factory=dict)
    widget_factories: dict[str, dict[str, Callable[..., Any]]] = field(default_factory=dict)

    def register_widget_factory(
        self,
        location: str,
        factory: Callable[..., Any],
        factory_id: str = "",
    ) -> str:
        if not callable(factory):
            raise TypeError("Native QWidget factory must be callable")
        item_id = str(factory_id or uuid.uuid4().hex)
        self.widget_factories.setdefault(str(location), {})[item_id] = factory
        return item_id

    def unregister_widget_factory(self, location: str, factory_id: str) -> None:
        self.widget_factories.get(str(location), {}).pop(str(factory_id), None)


@dataclass
class LoadedNativePlugin:
    plugin_id: str
    module: types.ModuleType
    context: NativeHostContext
    deactivate: Callable[..., Any] | None = None


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


class NativePluginLoader:
    def __init__(
        self,
        component: str,
        *,
        paths: PluginPaths | None = None,
        transport_factory: Callable[[str], Any] | None = None,
        application: Any = None,
        controller: Any = None,
        window: Any = None,
        objects: dict[str, Any] | None = None,
        safe_mode: bool | None = None,
    ) -> None:
        self.component = str(component)
        self.paths = paths or plugin_paths()
        self.state = PluginStateStore(self.paths)
        self.transport_factory = transport_factory
        self.application = application
        self.controller = controller
        self.window = window
        self.objects = dict(objects or {})
        self.safe_mode = (
            os.environ.get("BANDORI_PLUGIN_SAFE_MODE", "") == "1"
            if safe_mode is None else bool(safe_mode)
        )
        self.loaded: list[LoadedNativePlugin] = []
        self.journal_key = f"{self.component}:{os.getpid()}"
        self._journal_active = False

    def recover_stale_sessions(self) -> list[str]:
        quarantined: list[str] = []
        component = self.component
        snapshot = self.state.load()
        if not snapshot.get("native_startup_journal"):
            return quarantined

        def update(state):
            journals = state.get("native_startup_journal", {})
            if not isinstance(journals, dict):
                state["native_startup_journal"] = {}
                return
            for key, journal in list(journals.items()):
                if not isinstance(journal, dict) or journal.get("component") != component:
                    continue
                pid = int(journal.get("pid", 0) or 0)
                if pid == os.getpid() or _process_exists(pid) or journal.get("clean"):
                    continue
                suspects = (
                    [str(journal.get("loading"))]
                    if not journal.get("ready") and journal.get("loading")
                    else [str(item) for item in journal.get("loaded", [])]
                )
                for plugin_id in suspects:
                    item = state.get("plugins", {}).get(plugin_id)
                    if isinstance(item, dict) and item.get("execution") == "native":
                        item["enabled"] = False
                        item["disabled_reason"] = f"unclean_native_{component}_session"
                        quarantined.append(plugin_id)
                journals.pop(key, None)

        self.state.mutate(update)
        return quarantined

    def load_all(self) -> list[LoadedNativePlugin]:
        state = self.state.load()
        if state.get("native_startup_journal"):
            self.recover_stale_sessions()
            state = self.state.load()
        if self.safe_mode or state.get("native_safe_mode"):
            return []
        candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for plugin_id, item in state.get("plugins", {}).items():
            if not isinstance(item, dict) or not item.get("enabled") or item.get("execution") != "native":
                continue
            active = item.get("versions", {}).get(item.get("active_version", ""), {})
            manifest_raw = active.get("manifest", {}) if isinstance(active, dict) else {}
            try:
                manifest = PluginManifest.from_dict(manifest_raw)
            except Exception:
                continue
            if self.component not in manifest.entrypoints:
                continue
            candidates.append((plugin_id, active, manifest_raw))
        candidates.sort(key=lambda item: item[0])
        if not candidates:
            return []
        self._journal_active = True
        self._write_journal(loaded=[], loading="", ready=False, clean=False)
        for plugin_id, active, manifest_raw in candidates:
            self._write_journal(
                loaded=[item.plugin_id for item in self.loaded],
                loading=plugin_id,
                ready=False,
                clean=False,
            )
            try:
                loaded = self._load_one(plugin_id, active, PluginManifest.from_dict(manifest_raw))
            except Exception as exc:
                self._disable_failed_plugin(plugin_id, exc)
                continue
            self.loaded.append(loaded)
        self._write_journal(
            loaded=[item.plugin_id for item in self.loaded],
            loading="",
            ready=True,
            clean=False,
        )
        return list(self.loaded)

    def close(self) -> None:
        for loaded in reversed(self.loaded):
            if callable(loaded.deactivate):
                try:
                    loaded.deactivate("application_shutdown")
                except Exception:
                    pass
            loaded.context.api.close()
        if self._journal_active:
            def update(state):
                journals = state.get("native_startup_journal", {})
                if isinstance(journals, dict):
                    journals.pop(self.journal_key, None)
            self.state.mutate(update)
            self._journal_active = False
        self.loaded.clear()

    def create_widgets(self, location: str, parent: Any = None) -> list[Any]:
        """Instantiate native QWidget factories in deterministic plugin/id order."""
        widgets: list[Any] = []
        for loaded in sorted(self.loaded, key=lambda item: item.plugin_id):
            factories = loaded.context.widget_factories.get(str(location), {})
            for factory_id in sorted(factories):
                factory = factories[factory_id]
                try:
                    widget = factory(parent)
                    if widget is not None:
                        from PySide6.QtWidgets import QWidget
                        if not isinstance(widget, QWidget):
                            raise TypeError("Native widget factory did not return a QWidget")
                        widgets.append(widget)
                except Exception:
                    loaded.context.api.log.error(traceback.format_exc())
        return widgets

    def _load_one(
        self,
        plugin_id: str,
        active: dict[str, Any],
        manifest: PluginManifest,
    ) -> LoadedNativePlugin:
        root = Path(active.get("path", "")).resolve()
        entry = (root / manifest.entrypoints[self.component]).resolve()
        if not entry.is_file() or not entry.is_relative_to(root):
            raise RuntimeError("Native plugin entrypoint is missing or outside its package")
        transport = self.transport_factory(plugin_id) if self.transport_factory else None
        if transport is None:
            raise RuntimeError("Native plugin API transport is unavailable")
        api = PluginContext(plugin_id, transport)
        if hasattr(transport, "attach_context"):
            transport.attach_context(api)
        elif hasattr(transport, "context"):
            transport.context = api
        host = NativeHostContext(
            plugin_id=plugin_id,
            component=self.component,
            api=api,
            application=self.application,
            controller=self.controller,
            window=self.window,
            objects=dict(self.objects),
        )
        module_name = (
            f"bandoripet_native_{plugin_id.replace('.', '_').replace('-', '_')}_"
            f"{self.component}_{os.getpid()}"
        )
        spec = importlib.util.spec_from_file_location(module_name, entry)
        if spec is None or spec.loader is None:
            raise RuntimeError("Could not create native plugin module loader")
        module = importlib.util.module_from_spec(spec)
        vendor = root / "vendor"
        added_paths = [str(path) for path in (root, vendor) if path.is_dir()]
        for path in reversed(added_paths):
            sys.path.insert(0, path)
        try:
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        finally:
            for path in added_paths:
                try:
                    sys.path.remove(path)
                except ValueError:
                    pass
        activate = getattr(module, "activate_native", None)
        if not callable(activate):
            raise RuntimeError("Native plugin must define activate_native(host)")
        result = activate(host)
        deactivate = result if callable(result) else getattr(module, "deactivate_native", None)
        return LoadedNativePlugin(plugin_id, module, host, deactivate if callable(deactivate) else None)

    def _disable_failed_plugin(self, plugin_id: str, error: BaseException) -> None:
        detail = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        def update(state):
            item = state.get("plugins", {}).get(plugin_id)
            if isinstance(item, dict):
                item["enabled"] = False
                item["disabled_reason"] = f"native_load_failed:{self.component}"
                item["last_fault"] = detail[-8000:]
        self.state.mutate(update)

    def _write_journal(self, *, loaded: list[str], loading: str, ready: bool, clean: bool) -> None:
        def update(state):
            journals = state.setdefault("native_startup_journal", {})
            journals[self.journal_key] = {
                "component": self.component,
                "pid": os.getpid(),
                "loaded": list(loaded),
                "loading": str(loading),
                "ready": bool(ready),
                "clean": bool(clean),
            }
        self.state.mutate(update)
