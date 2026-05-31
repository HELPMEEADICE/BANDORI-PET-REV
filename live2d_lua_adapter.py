import ctypes
import os
import random
import sys
import time
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from live2d_quality import LIVE2D_QUALITY_PROFILES, normalize_live2d_quality
from platform_patch import get_live2d_texture_quality
from process_utils import app_base_dir
from zst_model_archive import is_virtual_path, load_virtual_bytes, split_virtual_path


BASE_DIR = Path(app_base_dir())
LIVE2D_LUA_DIR = BASE_DIR / "third_party" / "Live2D-v2-Lua"
MODELS_DIR = BASE_DIR / "models"
LIVE2D_PROFILE_ENABLED = os.environ.get("BANDORI_LIVE2D_PROFILE", "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_lua_path(path) -> str:
    if isinstance(path, bytes):
        path = path.decode("utf-8")
    return str(path).replace("\\", "/")


def _read_lua_chunk_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _read_bundled_lua_module_bytes(module_name: str) -> tuple[bytes, bytes]:
    relative = Path(*module_name.split("."))
    for suffix in (".ljbc", ".lua"):
        path = BASE_DIR / relative.with_suffix(suffix)
        if path.exists():
            return path.read_bytes(), ("@" + path.as_posix()).encode("utf-8")
    raise FileNotFoundError(f"Bundled Lua module not found: {module_name}")


def _lua_module_name(path: Path, root: Path) -> str | None:
    relative = path.relative_to(root)
    if relative.suffix not in {".lua", ".ljbc"}:
        return None
    module_path = relative.with_suffix("")
    parts = list(module_path.parts)
    if not parts:
        return None
    if parts[-1] == "init":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def _iter_lua_module_files(root: Path) -> list[tuple[str, Path]]:
    modules: dict[str, Path] = {}
    for pattern in ("**/*.lua", "**/*.ljbc"):
        for path in sorted(root.glob(pattern)):
            module_name = _lua_module_name(path, root)
            if not module_name:
                continue
            current = modules.get(module_name)
            if current is None or (current.suffix != ".ljbc" and path.suffix == ".ljbc"):
                modules[module_name] = path
    return sorted(modules.items())


def _install_lazy_lua_module_loader(lua: LuaRuntime, root: Path):
    module_paths = dict(_iter_lua_module_files(root))

    def load_module_source(name):
        module_name = name.decode("utf-8") if isinstance(name, bytes) else str(name)
        module_path = module_paths.get(module_name)
        if module_path is None:
            return None, None
        return _read_lua_chunk_bytes(module_path), ("@" + module_path.as_posix()).encode("utf-8")

    lua.globals()[b"__bandori_lazy_lua_module_source"] = load_module_source
    lua.execute(
        b"local loader = function(name) "
        b"local chunk, chunk_name = __bandori_lazy_lua_module_source(name); "
        b"if chunk == nil then return '\\n\\tno bundled Live2D module ' .. name end; "
        b"local fn, err = load(chunk, chunk_name); "
        b"if fn == nil then return '\\n\\t' .. tostring(err) end; "
        b"return fn "
        b"end; "
        b"local loaders = package.searchers or package.loaders; "
        b"table.insert(loaders, 1, loader)"
    )


def _install_gl_proc_address_loader(lua: LuaRuntime):
    if sys.platform != "win32":
        return

    try:
        opengl32 = ctypes.WinDLL("opengl32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return

    opengl32.wglGetProcAddress.argtypes = [ctypes.c_char_p]
    opengl32.wglGetProcAddress.restype = ctypes.c_void_p
    kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    kernel32.GetProcAddress.restype = ctypes.c_void_p
    opengl32_handle = ctypes.c_void_p(opengl32._handle)
    invalid_ptrs = {0, 1, 2, 3, ctypes.c_void_p(-1).value}

    def gl_get_proc_address(name):
        if isinstance(name, str):
            name = name.encode("ascii", errors="ignore")
        elif not isinstance(name, bytes):
            name = str(name).encode("ascii", errors="ignore")
        ptr = opengl32.wglGetProcAddress(name)
        if ptr in invalid_ptrs:
            ptr = kernel32.GetProcAddress(opengl32_handle, name)
        if ptr in invalid_ptrs:
            return None
        return format(int(ptr), "x")

    lua.globals()[b"__bandori_gl_get_proc_address"] = gl_get_proc_address


def _require_bundled_lua_module(lua: LuaRuntime, module_name: str):
    chunk, chunk_name = _read_bundled_lua_module_bytes(module_name)
    return lua.execute(
        b"local name, chunk, chunk_name = ...; "
        b"local loaded = package.loaded[name]; "
        b"if loaded ~= nil then return loaded end; "
        b"local fn, err = load(chunk, chunk_name); "
        b"if fn == nil then error(err) end; "
        b"local result = fn(name); "
        b"if result == nil then result = true end; "
        b"package.loaded[name] = result; "
        b"return result",
        module_name.encode("utf-8"),
        chunk,
        chunk_name,
    )


def _load_model_bytes(path: str) -> bytes:
    path = _normalize_lua_path(path)
    if is_virtual_path(path):
        archive_path, _member_path = split_virtual_path(path)
        _safe_model_file_path(archive_path)
        try:
            return load_virtual_bytes(path)
        except KeyError:
            fixed = _fix_mtn_path(path)
            if fixed:
                return _safe_model_file_path(fixed).read_bytes()
            raise

    fs_path = _safe_model_file_path(path)
    if not fs_path.exists():
        fixed = _fix_mtn_path(path)
        if fixed:
            fs_path = _safe_model_file_path(fixed)
    return fs_path.read_bytes()


def _texture_options(profile: str) -> tuple[float, bool, int]:
    options = LIVE2D_QUALITY_PROFILES[normalize_live2d_quality(profile)]
    return (
        float(options["texture_scale"]),
        bool(options["use_mipmap"]),
        int(options["bleed_passes"]),
    )


def _fix_mtn_path(path: str) -> str:
    basename = os.path.basename(path)
    mtn_emp_dir = MODELS_DIR / "_mtn_emp"
    if not basename or not mtn_emp_dir.is_dir():
        return ""
    for root, _dirs, files in os.walk(mtn_emp_dir):
        if basename in files:
            return str(Path(root) / basename)
    return ""


def _safe_model_file_path(path: str | Path) -> Path:
    fs_path = Path(path)
    if not fs_path.is_absolute():
        fs_path = MODELS_DIR / fs_path
    fs_path = fs_path.resolve()
    models_dir = MODELS_DIR.resolve()
    if not fs_path.is_relative_to(models_dir):
        raise ValueError(f"Model resource path is outside models directory: {path}")
    return fs_path


class _ModelSetting:
    def __init__(self, data):
        self._motion_names = _lua_array(data[b"motion_names"] or [])
        motions = data[b"motions"] or {}
        self._motions = {}
        for name in self._motion_names:
            group = motions[name.encode("utf-8")] or motions[name] or []
            self._motions[name] = _lua_array(group)
        self._hit_area_count = int(data[b"hit_area_count"] or 0)
        self._custom_hit_areas = _lua_custom_hit_areas(data[b"hit_areas_custom"] or {})

    def getMotionNames(self) -> list[str]:
        return list(self._motion_names)

    def getMotionNum(self, name: str) -> int:
        group = self._motion_group(name)
        return len(group)

    def resolveMotion(self, name: str, no: int = 0) -> tuple[str, int] | None:
        group = self._motion_group(name)
        if group:
            return name, max(0, min(int(no), len(group) - 1))

        target = Path(str(name).replace("\\", "/")).name.lower()
        target_stem = Path(target).stem
        for group_name, group in self._motions.items():
            for idx, item in enumerate(group):
                motion_file = Path(str(item).replace("\\", "/")).name.lower()
                if motion_file == target or Path(motion_file).stem == target_stem:
                    return group_name, idx
        return None

    def _motion_group(self, name: str) -> list:
        return self._motions.get(name, [])

    def getHitAreaNum(self) -> int:
        return self._hit_area_count

    def getCustomHitAreas(self) -> dict[str, list[float]]:
        return dict(self._custom_hit_areas)


def _decode_lua_string(value) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _lua_array(table) -> list[str]:
    return [_decode_lua_string(table[index]) for index in range(1, len(table) + 1) if table[index]]


def _lua_custom_hit_areas(table) -> dict[str, list[float]]:
    areas = {}
    for key, value in table.items():
        try:
            first = float(value[1])
            second = float(value[2])
        except (TypeError, ValueError, KeyError):
            continue
        areas[_decode_lua_string(key)] = [first, second]
    return areas


class MotionPriority:
    IDLE = 1
    NORMAL = 2
    FORCE = 3


class _MatrixManager:
    def __init__(self):
        self._width = 1.0
        self._height = 1.0

    def on_resize(self, width: float, height: float):
        self._width = max(float(width), 1.0)
        self._height = max(float(height), 1.0)

    def screenToScene(self, x: float, y: float):
        if self._width > self._height:
            scale = 2.0 * (self._width / self._height) / self._width
        else:
            scale = 2.0 / self._height
        return (float(x) - self._width / 2.0) * scale, -(float(y) - self._height / 2.0) * scale


class LuaLive2DModule:
    def __init__(self):
        self._lua = None
        self._embed = None
        self._initialized = False
        self._load_model = None
        self._resize = None
        self._draw = None
        self._drag = None
        self._hit_test = None
        self._set_parameter = None
        self._apply_texture_quality = None
        self._model_info = None
        self.MotionPriority = MotionPriority

    def glInit(self):
        self._ensure_runtime()

    def dispose(self):
        if self._embed is not None:
            try:
                self._embed.dispose()
            except Exception:
                pass
        self._lua = None
        self._embed = None
        self._initialized = False

    def LAppModel(self):
        return LuaLAppModel(self)

    def _ensure_runtime(self):
        if self._initialized:
            return
        lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
        lua.execute(b'assert(require("ffi"), "lupa must be built with LuaJIT FFI")')
        _install_lazy_lua_module_loader(lua, LIVE2D_LUA_DIR)
        _install_gl_proc_address_loader(lua)
        base_dir = BASE_DIR.as_posix().encode("utf-8")
        lua.execute(
            b"local root = ...; "
            b"package.path = package.path .. ';' .. root .. '/?.ljbc;' .. root .. '/?/init.ljbc;' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
            base_dir,
        )
        _require_bundled_lua_module(lua, "live2d_platform_manager_override")
        lua.execute(
            b"local target, source = ...; package.loaded[target] = package.loaded[source]",
            b"live2d.platform_manager",
            b"live2d_platform_manager_override",
        )
        lua_dir = LIVE2D_LUA_DIR.as_posix().encode("utf-8")
        lua.execute(
            b"local root = ...; "
            b"package.path = package.path .. ';' .. root .. '/?.ljbc;' .. root .. '/?/init.ljbc;' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
            lua_dir,
        )
        self._embed = lua.execute(b'return require("live2d_embed")')
        self._embed.init()
        self._load_model = lua.eval(
            b"function(renderer, path, w, h, opts) return renderer:load_model(path, w, h, opts) end"
        )
        self._resize = lua.eval(b"function(renderer, w, h) return renderer:resize(w, h) end")
        self._draw = lua.eval(b"function(renderer, opts) return renderer:draw(opts) end")
        self._drag = lua.eval(b"function(renderer, x, y) return renderer:drag(x, y) end")
        self._hit_test = lua.eval(b"function(renderer, x, y) return renderer:hit_test(x, y) end")
        self._set_parameter = lua.eval(
            b"function(renderer, param_id, value, weight) return renderer:set_parameter(param_id, value, weight) end"
        )
        self._set_offset = lua.eval(b"function(renderer, x, y) return renderer:set_offset(x, y) end")
        self._apply_texture_quality = lua.eval(
            b"(function() "
            b"local gl = require('live2d.core.live2d_gl_wrapper'); "
            b"local GL_NEAREST = 0x2600; "
            b"local GL_LINEAR_MIPMAP_LINEAR = 0x2703; "
            b"return function(renderer, profile) "
            b"local model = renderer:get_model(); "
            b"if model == nil or model.live2DModel == nil or model.live2DModel.drawParamGL == nil then return end; "
            b"local textures = model.live2DModel.drawParamGL.textures or {}; "
            b"local min_filter = gl.LINEAR; "
            b"local mag_filter = gl.LINEAR; "
            b"local use_mipmap = true; "
            b"if profile == 'performance' then "
            b"min_filter = GL_NEAREST; mag_filter = GL_NEAREST; use_mipmap = false; "
            b"else "
            b"min_filter = GL_LINEAR_MIPMAP_LINEAR; "
            b"end; "
            b"for i = 1, #textures do "
            b"local texture = textures[i]; "
            b"if texture ~= nil and texture ~= 0 then "
            b"gl.bindTexture(gl.TEXTURE_2D, texture); "
            b"if use_mipmap then pcall(gl.generateMipmap, gl.TEXTURE_2D); end; "
            b"gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, min_filter); "
            b"gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, mag_filter); "
            b"gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); "
            b"gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE); "
            b"end; "
            b"end; "
            b"gl.bindTexture(gl.TEXTURE_2D, 0); "
            b"end "
            b"end)()"
        )
        self._model_info = lua.eval(
            b"function(renderer) "
            b"local info = { motion_names = {}, motions = {}, expressions = {}, hit_area_count = 0 }; "
            b"local model = renderer:get_model(); "
            b"local setting = model and model.modelSetting; "
            b"if setting == nil then return info end; "
            b"local names = setting:getMotionNames() or {}; "
            b"for i = 1, #names do "
            b"local name = names[i]; info.motion_names[#info.motion_names + 1] = name; "
            b"local group = {}; local count = setting:getMotionNum(name); "
            b"for no = 0, count - 1 do group[#group + 1] = setting:getMotionFile(name, no) or ''; end; "
            b"info.motions[name] = group; "
            b"end; "
            b"for j = 0, setting:getExpressionNum() - 1 do "
            b"local name = setting:getExpressionName(j); if name ~= nil and name ~= '' then info.expressions[name] = true end; "
            b"end; "
            b"local json = setting._json or {}; "
            b"if type(json.hit_areas_custom) == 'table' then info.hit_areas_custom = json.hit_areas_custom; end; "
            b"info.hit_area_count = setting:getHitAreaNum(); "
            b"return info "
            b"end"
        )
        self._start_motion = lua.eval(
            b"function(renderer, name, no, priority) return renderer:start_motion(name, no, priority) end"
        )
        self._clear_motions = lua.eval(b"function(renderer) return renderer:clear_motions() end")
        self._is_motion_finished = lua.eval(
            b"function(renderer) "
            b"local model = renderer:get_model(); "
            b"return model == nil or model.mainMotionManager:isFinished(); "
            b"end"
        )
        self._set_expression = lua.eval(
            b"function(renderer, name) return renderer:set_expression(name) end"
        )
        self._preload_expression = lua.eval(
            b"function(renderer, name) return renderer:preload_expression(name) end"
        )
        self._preload_motion_group = lua.eval(
            b"function(renderer, name) return renderer:preload_motion_group(name) end"
        )
        self._reset_expression = lua.eval(b"function(renderer) return renderer:reset_expression() end")
        self._lua = lua
        self._initialized = True

    def _new_renderer(self, width: int, height: int):
        self._ensure_runtime()
        return self._embed.new(width, height)

    def _new_options(self, model_path: str):
        self._ensure_runtime()
        lua = self._lua

        def resource_loader(path):
            return _load_model_bytes(_normalize_lua_path(path))

        def texture_loader(no, path):
            profile = get_live2d_texture_quality()
            normalized_path = _normalize_lua_path(path)
            scale, use_mipmap, bleed_passes = _texture_options(profile)
            entry = lua.table()
            if is_virtual_path(normalized_path):
                archive_path, _member_path = split_virtual_path(normalized_path)
                _safe_model_file_path(archive_path)
                entry[b"path"] = normalized_path.encode("utf-8")
                entry[b"bytes"] = load_virtual_bytes(normalized_path)
            else:
                entry[b"path"] = _safe_model_file_path(normalized_path).as_posix().encode("utf-8")
            entry[b"scale"] = scale
            entry[b"mipmap"] = use_mipmap
            entry[b"bleed_passes"] = bleed_passes
            return entry

        resources = lua.table()
        resources[b"__loader"] = resource_loader
        resources[_normalize_lua_path(model_path).encode("utf-8")] = _load_model_bytes(model_path)

        textures = lua.table()
        textures[b"__loader"] = texture_loader

        opts = lua.table()
        opts[b"resource_streams"] = resources
        opts[b"texture_streams"] = textures
        opts[b"center"] = False
        opts[b"defer_expressions"] = True
        return opts


class LuaLAppModel:
    def __init__(self, module: LuaLive2DModule):
        self._module = module
        self._renderer = None
        self._width = 1
        self._height = 1
        self.modelSetting = None
        self.matrixManager = _MatrixManager()
        self.expressions = {}
        self._pending_parameters = {}
        self._profile_enabled = LIVE2D_PROFILE_ENABLED
        self.last_lua_update_draw_seconds = 0.0
        self.last_lua_gc_seconds = 0.0

    def LoadModelJson(self, model_json_path: str, disable_precision=False):
        del disable_precision
        self._renderer = self._module._new_renderer(self._width, self._height)
        opts = self._module._new_options(model_json_path)
        self._module._load_model(
            self._renderer,
            _normalize_lua_path(model_json_path).encode("utf-8"),
            self._width,
            self._height,
            opts,
        )
        info = self._module._model_info(self._renderer)
        self.modelSetting = _ModelSetting(info)
        self.expressions = self._read_expression_names(info)
        self._module._apply_texture_quality(self._renderer, get_live2d_texture_quality().encode("utf-8"))
        self._draw_opts = self._module._lua.table()
        self._draw_opts[b"clear"] = False
        self._draw_opts[b"profile"] = self._profile_enabled

    def Resize(self, width: int, height: int):
        self._width = max(int(width), 1)
        self._height = max(int(height), 1)
        self.matrixManager.on_resize(self._width, self._height)
        if self._renderer is not None:
            self._module._resize(self._renderer, self._width, self._height)

    def Draw(self):
        if self._renderer is None:
            return
        opts = self._draw_opts
        opts[b"time_msec"] = time.monotonic() * 1000.0
        if self._pending_parameters:
            params = self._module._lua.table()
            for index, (param_id, value, weight) in enumerate(self._pending_parameters.values(), 1):
                item = self._module._lua.table()
                item[b"id"] = str(param_id).encode("utf-8")
                item[b"value"] = float(value)
                item[b"weight"] = float(weight)
                params[index] = item
            opts[b"parameters"] = params
        else:
            opts[b"parameters"] = None
        self._module._draw(self._renderer, opts)
        if self._profile_enabled:
            self.last_lua_update_draw_seconds = float(opts[b"profile_update_draw_seconds"] or 0.0)
            self.last_lua_gc_seconds = float(opts[b"profile_gc_seconds"] or 0.0)

    def Drag(self, x: float, y: float):
        self._module._drag(self._renderer, float(x), float(y))

    def SetParameterValue(self, param_id: str, value: float, weight: float = 1.0):
        self._pending_parameters[str(param_id)] = (str(param_id), float(value), float(weight))

    def HitTest(self, _area_name: str, x: float, y: float):
        hits = self._module._hit_test(self._renderer, float(x), float(y))
        return "hit" if len(hits) > 0 else None

    def StartMotion(self, name: str, no: int = 0, priority=MotionPriority.FORCE, **_kwargs):
        resolved = self.modelSetting.resolveMotion(str(name), int(no)) if self.modelSetting else None
        if resolved is None:
            return
        group_name, motion_no = resolved
        self._module._start_motion(
            self._renderer,
            group_name.encode("utf-8"),
            int(motion_no),
            int(priority),
        )

    def StartRandomMotion(self, name: str | None = None, priority=MotionPriority.IDLE, **_kwargs):
        if self.modelSetting is None:
            return
        if not name:
            names = self.modelSetting.getMotionNames()
            if not names:
                return
            name = random.choice(names)
        count = self.modelSetting.getMotionNum(name)
        if count <= 0:
            return
        self.StartMotion(name, random.randrange(count), priority)

    def PreloadMotionGroup(self, name: str):
        if self._renderer is None or not name:
            return
        self._module._preload_motion_group(self._renderer, str(name).encode("utf-8"))

    def PreloadExpression(self, name: str):
        if self._renderer is None or not name:
            return
        self._module._preload_expression(self._renderer, str(name).encode("utf-8"))

    def ClearMotions(self):
        self._module._clear_motions(self._renderer)

    def IsMotionFinished(self) -> bool:
        return bool(self._module._is_motion_finished(self._renderer))

    def SetExpression(self, name: str):
        self._module._set_expression(self._renderer, str(name).encode("utf-8"))

    def ResetExpression(self):
        self._module._reset_expression(self._renderer)

    @staticmethod
    def _read_expression_names(info) -> dict[str, None]:
        expressions = info[b"expressions"] or {}
        names = {}
        for name in expressions.keys():
            names[_decode_lua_string(name)] = None
        return names


live2d = LuaLive2DModule()
