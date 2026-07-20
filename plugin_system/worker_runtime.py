from __future__ import annotations

import builtins
import importlib.util
import os
import sys
import traceback
import types
from pathlib import Path
from typing import Any

from .models import PluginError, PluginManifest
from .sdk import PluginContext, SDK_PUBLIC_ATTRIBUTE_NAMES, _json_value, managed_context_view


LUA_MAX_MEMORY = 64 * 1024 * 1024
LUA_HOOK_INSTRUCTION_INTERVAL = 10_000
LUA_HOOK_MAX_TICKS = 2_000
SAFE_IMPORT_ROOTS = frozenset({
    "abc", "array", "base64", "binascii", "bisect", "calendar", "collections",
    "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal", "enum",
    "functools", "fractions", "hashlib", "heapq", "hmac", "html", "itertools",
    "json", "math", "numbers", "operator", "random", "re", "statistics", "string",
    "struct", "textwrap", "time", "typing", "unicodedata", "uuid",
})


class ManagedPluginRuntime:
    def __init__(
        self,
        root: Path,
        manifest: PluginManifest,
        transport,
        *,
        install_audit_hook: bool = True,
    ):
        self.root = Path(root).resolve()
        self.manifest = manifest
        self.transport = transport
        self.context = PluginContext(manifest.id, transport)
        self.module = None
        self.deactivate_callback = None
        self._lua = None
        self._lua_begin_hook = None
        self._lua_clear_hook = None
        self._lua_value_converter = lambda value: value
        self._original_import = builtins.__import__
        self._audit_hook_enabled = bool(install_audit_hook)
        self._python_paths = [self.root, self.root / "vendor"]
        self._managed_module_names: set[str] = set()

    def activate(self) -> None:
        if self.manifest.language == "python":
            self._activate_python()
        else:
            self._activate_lua()

    def deactivate(self, reason: str = "disabled") -> None:
        callback = self.deactivate_callback
        self.deactivate_callback = None
        if callable(callback):
            try:
                self._invoke(callback, reason)
            except Exception:
                self.context.log.error(traceback.format_exc())
        self.context.close()
        if self._lua is not None:
            try:
                self._lua.gccollect()
            except Exception:
                pass
            self._lua = None

    def invoke_callback(self, callback_id: str, payload: Any) -> Any:
        callback = self.context._callbacks.get(str(callback_id))
        if callback is None:
            raise KeyError(f"Unknown plugin callback: {callback_id}")
        return _json_value(self._invoke(callback, payload))

    def _invoke(self, callback, *args):
        if self._lua is None:
            return callback(*args)
        self._lua_begin_hook(LUA_HOOK_MAX_TICKS, LUA_HOOK_INSTRUCTION_INTERVAL)
        try:
            return callback(*(self._lua_value_converter(value) for value in args))
        finally:
            self._lua_clear_hook()

    def _plugin_local_import_exists(self, root_name: str) -> bool:
        relative = Path(*root_name.split("."))
        for base in self._python_paths:
            if (base / relative).with_suffix(".py").is_file():
                return True
            if (base / relative / "__init__.py").is_file():
                return True
        return False

    def _safe_import(self, name, globals=None, locals=None, fromlist=(), level=0):
        requested_name = str(name or "")
        root_name = requested_name.split(".", 1)[0]
        if level:
            package = str((globals or {}).get("__package__", "") or "")
            if not package:
                raise ImportError("Relative imports require a plugin package")
            requested_name = importlib.util.resolve_name("." * level + requested_name, package)
            root_name = requested_name.split(".", 1)[0]
        if root_name in SAFE_IMPORT_ROOTS:
            return self._original_import(name, globals, locals, fromlist, level)
        if not self._plugin_local_import_exists(root_name):
            raise ImportError(
                f"Managed plugin import is blocked: {name}. Use the capability API or native mode."
            )
        module = self._load_managed_module(requested_name)
        if fromlist:
            for child in fromlist:
                child_name = str(child or "")
                if not child_name or child_name == "*" or hasattr(module, child_name):
                    continue
                full_name = f"{requested_name}.{child_name}"
                if self._plugin_local_import_exists(full_name):
                    setattr(module, child_name, self._load_managed_module(full_name))
            return module
        return sys.modules.get(root_name, module)

    def _managed_module_source(self, full_name: str) -> tuple[Path, bool] | None:
        relative = Path(*full_name.split("."))
        for base in self._python_paths:
            source = (base / relative).with_suffix(".py")
            if source.is_file():
                return source.resolve(), False
            package = base / relative / "__init__.py"
            if package.is_file():
                return package.resolve(), True
        return None

    def _load_managed_module(self, full_name: str):
        existing = sys.modules.get(full_name)
        if existing is not None:
            module_file = getattr(existing, "__file__", "")
            try:
                if module_file and any(Path(module_file).resolve().is_relative_to(path) for path in self._python_paths):
                    return existing
            except OSError:
                pass
            if full_name in self._managed_module_names:
                return existing
            raise ImportError(f"Managed plugin module collides with a host module: {full_name}")

        parts = full_name.split(".")
        if len(parts) > 1:
            parent_name = ".".join(parts[:-1])
            parent = self._load_managed_module(parent_name)
        else:
            parent_name = ""
            parent = None
        resolved = self._managed_module_source(full_name)
        if resolved is None:
            raise ImportError(f"Managed plugin source module was not found: {full_name}")
        source_path, is_package = resolved
        source = source_path.read_text(encoding="utf-8-sig")
        module = types.ModuleType(full_name)
        module.__file__ = str(source_path)
        module.__package__ = full_name if is_package else parent_name
        if is_package:
            module.__path__ = [str(source_path.parent)]
        module.__dict__["__builtins__"] = self._safe_builtins()
        sys.modules[full_name] = module
        self._managed_module_names.add(full_name)
        if parent is not None:
            setattr(parent, parts[-1], module)
        try:
            code = compile(source, str(source_path), "exec", dont_inherit=True)
            exec(code, module.__dict__, module.__dict__)
        except BaseException:
            sys.modules.pop(full_name, None)
            self._managed_module_names.discard(full_name)
            if parent is not None and getattr(parent, parts[-1], None) is module:
                delattr(parent, parts[-1])
            raise
        return module

    def _safe_builtins(self) -> dict[str, Any]:
        names = {
            "__build_class__", "abs", "all", "any", "ascii", "bin", "bool", "bytearray",
            "bytes", "callable", "chr", "classmethod", "complex", "dict", "dir", "divmod",
            "enumerate", "BaseException", "Exception", "AttributeError", "ImportError",
            "NameError", "StopIteration", "ModuleNotFoundError", "filter", "float", "format", "frozenset", "getattr",
            "hasattr", "hash", "hex", "IndexError", "int", "isinstance", "issubclass", "iter",
            "KeyError", "len", "list", "map", "max", "MemoryError", "min", "next", "object",
            "oct", "ord", "OverflowError", "pow", "print", "property", "range", "repr", "reversed",
            "round", "RuntimeError", "set", "setattr", "slice", "sorted", "staticmethod", "str",
            "sum", "super", "tuple", "TypeError", "ValueError", "zip", "ZeroDivisionError",
        }
        result = {name: getattr(builtins, name) for name in names}
        result["__import__"] = self._safe_import
        return result

    def _install_python_audit_hook(self) -> None:
        allowed_roots = [path.resolve() for path in self._python_paths if path.exists()]
        try:
            allowed_roots.append(Path(sys.base_prefix).resolve())
        except OSError:
            pass

        def audit(event, args):
            if event in {
                "subprocess.Popen", "os.system", "os.posix_spawn", "socket.__new__",
                "ctypes.dlopen", "ctypes.dlsym", "ctypes.call_function",
            }:
                raise PermissionError(
                    f"Managed plugin operation is blocked by the capability boundary: {event}"
                )
            if event == "open" and args:
                raw_path = args[0]
                mode = str(args[1] if len(args) > 1 else "r")
                if isinstance(raw_path, int):
                    return
                try:
                    path = Path(os.fspath(raw_path)).resolve()
                except (TypeError, ValueError, OSError):
                    raise PermissionError("Managed plugin attempted to open an invalid path")
                if any(flag in mode for flag in ("w", "a", "+", "x")):
                    raise PermissionError("Managed plugins must write files through ctx.filesystem")
                if not any(path.is_relative_to(root) for root in allowed_roots):
                    raise PermissionError("Managed plugins must read files through ctx.filesystem")

        sys.addaudithook(audit)

    def _activate_python(self) -> None:
        entry = (self.root / self.manifest.entrypoints["worker"]).resolve()
        if not entry.is_relative_to(self.root) or not entry.is_file():
            raise PluginError("Managed Python entrypoint is outside the plugin root")
        source = entry.read_text(encoding="utf-8-sig")
        if self._audit_hook_enabled:
            self._install_python_audit_hook()
        module_name = f"bandoripet_plugin_{self.manifest.id.replace('.', '_').replace('-', '_')}"
        module = types.ModuleType(module_name)
        module.__file__ = str(entry)
        module.__package__ = ""
        module.__dict__["__builtins__"] = self._safe_builtins()
        sys.modules[module_name] = module
        code = compile(source, str(entry), "exec", dont_inherit=True)
        exec(code, module.__dict__, module.__dict__)
        activate = getattr(module, "activate", None)
        if not callable(activate):
            raise PluginError("Managed Python entrypoint must define activate(ctx)")
        self.module = module
        self.deactivate_callback = getattr(module, "deactivate", None)
        activate(managed_context_view(self.context))

    def _activate_lua(self) -> None:
        try:
            from lupa.luajit21 import LuaRuntime
        except ImportError as exc:
            raise PluginError(f"LuaJIT plugin runtime is unavailable: {exc}") from exc

        converter = {"value": lambda value: value}

        def getter(obj, attribute):
            raw_name = attribute.decode("utf-8") if isinstance(attribute, bytes) else attribute
            if isinstance(obj, dict):
                if raw_name in obj:
                    return obj[raw_name]
                name = str(raw_name)
                if name in obj:
                    return obj[name]
                raise KeyError(name)
            if isinstance(obj, (list, tuple)):
                try:
                    index = int(raw_name)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise IndexError(raw_name) from exc
                if index < 1 or index > len(obj):
                    return None
                return obj[index - 1]
            name = str(raw_name)
            if name.startswith("_") or name not in SDK_PUBLIC_ATTRIBUTE_NAMES:
                raise AttributeError(f"Lua plugin attribute access denied: {name}")
            value = getattr(obj, name)
            if callable(value):
                return lambda *args, _call=value: converter["value"](_call(*args))
            return converter["value"](value)

        def setter(_obj, attribute, _value):
            name = attribute.decode("utf-8") if isinstance(attribute, bytes) else str(attribute)
            raise AttributeError(f"Lua plugin attribute writes are denied: {name}")

        lua = LuaRuntime(
            unpack_returned_tuples=True,
            register_eval=False,
            register_builtins=False,
            attribute_handlers=(getter, setter),
            max_memory=LUA_MAX_MEMORY,
        )

        def to_lua_value(value):
            if isinstance(value, dict):
                table = lua.table()
                for key, child in value.items():
                    table[str(key)] = to_lua_value(child)
                return table
            if isinstance(value, (list, tuple)):
                table = lua.table()
                for index, child in enumerate(value, start=1):
                    table[index] = to_lua_value(child)
                return table
            return value

        converter["value"] = to_lua_value
        self._lua_value_converter = to_lua_value
        self._lua_begin_hook = lua.execute(
            "local d=debug; return function(max_ticks, interval) "
            "local ticks=0; d.sethook(function() ticks=ticks+1; "
            "if ticks>max_ticks then error('plugin instruction limit exceeded', 2) end "
            "end, '', interval) end"
        )
        self._lua_clear_hook = lua.execute(
            "local d=debug; return function() d.sethook() end"
        )

        loaded: dict[str, Any] = {}

        def load_module(name):
            module_name = str(name or "")
            if not module_name or not all(
                part and part.replace("_", "a").isalnum()
                for part in module_name.split(".")
            ):
                raise PluginError(f"Invalid Lua module name: {module_name!r}")
            if module_name in loaded:
                return loaded[module_name]
            relative = Path(*module_name.split("."))
            candidates = [
                (self.root / relative).with_suffix(".lua"),
                self.root / relative / "init.lua",
            ]
            module_path = next((item.resolve() for item in candidates if item.is_file()), None)
            if module_path is None or not module_path.is_relative_to(self.root):
                raise PluginError(f"Lua module was not found in the plugin package: {module_name}")
            source = module_path.read_text(encoding="utf-8-sig")
            self._lua_begin_hook(LUA_HOOK_MAX_TICKS, LUA_HOOK_INSTRUCTION_INTERVAL)
            try:
                value = lua.execute(source, "@" + module_path.as_posix())
            finally:
                self._lua_clear_hook()
            loaded[module_name] = True if value is None else value
            return loaded[module_name]

        lua.globals()["__bandori_plugin_require"] = load_module
        lua.execute(
            "local loader=__bandori_plugin_require; __bandori_plugin_require=nil; "
            "require=function(name) return loader(name) end; "
            "ffi=nil; os=nil; io=nil; debug=nil; package=nil; python=nil; "
            "load=nil; loadstring=nil; loadfile=nil; dofile=nil"
        )
        entry = (self.root / self.manifest.entrypoints["worker"]).resolve()
        if not entry.is_relative_to(self.root) or not entry.is_file():
            raise PluginError("Managed Lua entrypoint is outside the plugin root")
        source = entry.read_text(encoding="utf-8-sig")
        self._lua = lua
        self._lua_begin_hook(LUA_HOOK_MAX_TICKS, LUA_HOOK_INSTRUCTION_INTERVAL)
        try:
            module = lua.execute(source, "@" + entry.as_posix())
        finally:
            self._lua_clear_hook()
        if module is None:
            raise PluginError("Managed Lua entrypoint must return a plugin table")
        activate = module["activate"]
        if activate is None:
            raise PluginError("Managed Lua plugin table must define activate(ctx)")
        self.module = module
        self.deactivate_callback = module["deactivate"]
        self._invoke(activate, self.context)
