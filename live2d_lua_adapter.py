import ctypes
import json
import os
import random
import sys
import time
from pathlib import Path

from lupa.luajit21 import LuaRuntime
from live2d_quality import LIVE2D_QUALITY_PROFILES, normalize_live2d_quality
from model_manager import WEBGAL_COMPOSITE_FILENAME, is_webgal_composite_path
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


_GL_LOADER_CORE_TYPEDEFS = b"""
ffi.cdef("typedef void (" .. CC .. "*PFNGLCLEARPROC)(GLbitfield mask);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLCLEARCOLORPROC)(GLfloat red, GLfloat green, GLfloat blue, GLfloat alpha);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLVIEWPORTPROC)(GLint x, GLint y, GLsizei width, GLsizei height);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLENABLEPROC)(GLenum cap);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDISABLEPROC)(GLenum cap);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLCOLORMASKPROC)(GLboolean red, GLboolean green, GLboolean blue, GLboolean alpha);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLFRONTFACEPROC)(GLenum mode);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLBINDTEXTUREPROC)(GLenum target, GLuint texture);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDELETETEXTURESPROC)(GLsizei n, const GLuint *textures);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLGETINTEGERVPROC)(GLenum pname, GLint *data);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLGENTEXTURESPROC)(GLsizei n, GLuint *textures);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLTEXPARAMETERIPROC)(GLenum target, GLenum pname, GLint param);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLTEXIMAGE2DPROC)(GLenum target, GLint level, GLint internalformat, GLsizei width, GLsizei height, GLint border, GLenum format, GLenum type, const void *pixels);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDRAWELEMENTSPROC)(GLenum mode, GLsizei count, GLenum type, const void *indices);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLREADPIXELSPROC)(GLint x, GLint y, GLsizei width, GLsizei height, GLenum format, GLenum type, void *pixels);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDRAWARRAYSPROC)(GLenum mode, GLint first, GLsizei count);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLBLENDFUNCPROC)(GLenum sfactor, GLenum dfactor);")
"""


_GL_LOADER_CORE_PATCH = b"""
local function loadCoreFromHostContext()
    if type(_G.__bandori_gl_get_proc_address) ~= "function" then
        return
    end
    local core = {
        {"glClear", "PFNGLCLEARPROC"},
        {"glClearColor", "PFNGLCLEARCOLORPROC"},
        {"glViewport", "PFNGLVIEWPORTPROC"},
        {"glEnable", "PFNGLENABLEPROC"},
        {"glDisable", "PFNGLDISABLEPROC"},
        {"glColorMask", "PFNGLCOLORMASKPROC"},
        {"glFrontFace", "PFNGLFRONTFACEPROC"},
        {"glBindTexture", "PFNGLBINDTEXTUREPROC"},
        {"glDeleteTextures", "PFNGLDELETETEXTURESPROC"},
        {"glGetIntegerv", "PFNGLGETINTEGERVPROC"},
        {"glGenTextures", "PFNGLGENTEXTURESPROC"},
        {"glTexParameteri", "PFNGLTEXPARAMETERIPROC"},
        {"glTexImage2D", "PFNGLTEXIMAGE2DPROC"},
        {"glDrawElements", "PFNGLDRAWELEMENTSPROC"},
        {"glReadPixels", "PFNGLREADPIXELSPROC"},
        {"glDrawArrays", "PFNGLDRAWARRAYSPROC"},
        {"glBlendFunc", "PFNGLBLENDFUNCPROC"},
    }
    for _, item in ipairs(core) do
        local ok, fn = pcall(loadGL, item[1], item[2])
        if ok and fn ~= nil then
            gl[item[1]] = fn
        end
    end
end

loadCoreFromHostContext()
"""


def _patch_lua_gl_loader(module_name: str, chunk: bytes) -> bytes:
    if module_name != "live2d.gl_loader":
        return chunk
    typedef_marker = b'ffi.cdef("typedef void (" .. CC .. "*PFNGLGENERATEMIPMAPPROC)(GLenum target);")'
    if b"PFNGLCLEARPROC" not in chunk and typedef_marker in chunk:
        chunk = chunk.replace(typedef_marker, typedef_marker + _GL_LOADER_CORE_TYPEDEFS, 1)
    ensure_marker = b"\nfunction gl.ensureExtensions()"
    if b"loadCoreFromHostContext()" not in chunk and ensure_marker in chunk:
        chunk = chunk.replace(ensure_marker, _GL_LOADER_CORE_PATCH + ensure_marker, 1)
    return chunk


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
        chunk = module_path.read_bytes()
        return _patch_lua_gl_loader(module_name, chunk), ("@" + module_path.as_posix()).encode("utf-8")

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
    def qt_gl_get_proc_address(name):
        try:
            from qt_gl import qt_gl_proc_address
        except Exception:
            return None
        ptr = qt_gl_proc_address(name)
        return format(ptr, "x").encode("ascii") if ptr else None

    if sys.platform != "win32":
        lua.globals()[b"__bandori_gl_get_proc_address_py"] = qt_gl_get_proc_address
        lua.execute(
            b"function __bandori_gl_get_proc_address(name) "
            b"return __bandori_gl_get_proc_address_py(name) "
            b"end"
        )
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
        ptr = qt_gl_get_proc_address(name)
        if ptr:
            return ptr
        if isinstance(name, str):
            name = name.encode("ascii", errors="ignore")
        elif not isinstance(name, bytes):
            name = str(name).encode("ascii", errors="ignore")
        ptr = opengl32.wglGetProcAddress(name)
        if ptr in invalid_ptrs:
            ptr = kernel32.GetProcAddress(opengl32_handle, name)
        if ptr in invalid_ptrs:
            return None
        return format(int(ptr), "x").encode("ascii")

    lua.globals()[b"__bandori_gl_get_proc_address_py"] = gl_get_proc_address
    lua.execute(
        b"function __bandori_gl_get_proc_address(name) "
        b"return __bandori_gl_get_proc_address_py(name) "
        b"end"
    )


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


def _webgal_composite_layer_paths(manifest_path: str) -> list[str]:
    manifest_file = _safe_model_file_path(manifest_path)
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Invalid WebGal composite manifest: {exc}") from exc
    layers = manifest.get("layers", [])
    if not isinstance(layers, list) or not layers:
        raise ValueError("WebGal composite manifest has no layers")

    result = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        relative = str(layer.get("model", "") or "").strip()
        if not relative:
            continue
        result.append(str(_safe_model_file_path(manifest_file.parent / relative)))
    if not result:
        raise ValueError("WebGal composite manifest has no valid model layers")
    return result


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


class _CompositeModelSetting:
    def __init__(self, settings: list[_ModelSetting]):
        self._settings = [setting for setting in settings if setting is not None]
        self._motion_names = []
        seen = set()
        for setting in self._settings:
            for name in setting.getMotionNames():
                if name not in seen:
                    seen.add(name)
                    self._motion_names.append(name)

    def getMotionNames(self) -> list[str]:
        return list(self._motion_names)

    def getMotionNum(self, name: str) -> int:
        return max((setting.getMotionNum(name) for setting in self._settings), default=0)

    def resolveMotion(self, name: str, no: int = 0) -> tuple[str, int] | None:
        for setting in self._settings:
            resolved = setting.resolveMotion(name, no)
            if resolved is not None:
                return resolved
        return None

    def getHitAreaNum(self) -> int:
        for setting in self._settings:
            count = setting.getHitAreaNum()
            if count:
                return count
        return 0

    def getCustomHitAreas(self) -> dict[str, list[float]]:
        for setting in self._settings:
            areas = setting.getCustomHitAreas()
            if areas:
                return areas
        return {}


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
        self._set_offset = None
        self._apply_texture_quality = None
        self._model_info = None
        self._start_motion = None
        self._clear_motions = None
        self._is_motion_finished = None
        self._set_expression = None
        self._preload_expression = None
        self._preload_motion_group = None
        self._reset_expression = None
        self._dispose_renderer = None
        self.MotionPriority = MotionPriority

    def glInit(self):
        self._ensure_runtime()

    def dispose(self):
        if self._embed is not None:
            try:
                self._embed.dispose()
            except Exception:
                pass
        self._load_model = None
        self._resize = None
        self._draw = None
        self._drag = None
        self._hit_test = None
        self._set_parameter = None
        self._set_offset = None
        self._apply_texture_quality = None
        self._model_info = None
        self._start_motion = None
        self._clear_motions = None
        self._is_motion_finished = None
        self._set_expression = None
        self._preload_expression = None
        self._preload_motion_group = None
        self._reset_expression = None
        self._dispose_renderer = None
        self._lua = None
        self._embed = None
        self._initialized = False

    def LAppModel(self):
        return LuaCompositeLAppModel(self)

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
        self._dispose_renderer = lua.eval(b"function(renderer) return renderer:dispose() end")
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
        self._draw_opts = self._module._lua.table()
        self._draw_opts[b"clear"] = False
        self._draw_opts[b"profile"] = self._profile_enabled
        self.last_lua_update_draw_seconds = 0.0
        self.last_lua_gc_seconds = 0.0

    def LoadModelJson(self, model_json_path: str):
        self._dispose_renderer()
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
        if self._renderer is None:
            return
        self._module._drag(self._renderer, float(x), float(y))

    def SetParameterValue(self, param_id: str, value: float, weight: float = 1.0):
        self._pending_parameters[str(param_id)] = (str(param_id), float(value), float(weight))

    def HitTest(self, _area_name: str, x: float, y: float):
        if self._renderer is None:
            return None
        hits = self._module._hit_test(self._renderer, float(x), float(y))
        return "hit" if len(hits) > 0 else None

    def StartMotion(self, name: str, no: int = 0, priority=MotionPriority.FORCE, **_kwargs):
        if self._renderer is None:
            return
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
        if self._renderer is None:
            return
        self._module._clear_motions(self._renderer)

    def IsMotionFinished(self) -> bool:
        if self._renderer is None:
            return True
        return bool(self._module._is_motion_finished(self._renderer))

    def SetExpression(self, name: str):
        if self._renderer is None:
            return
        self._module._set_expression(self._renderer, str(name).encode("utf-8"))

    def ResetExpression(self):
        if self._renderer is None:
            return
        self._module._reset_expression(self._renderer)

    def ApplyTextureQuality(self, profile: str):
        if self._renderer is None:
            return
        self._module._apply_texture_quality(self._renderer, str(profile).encode("utf-8"))

    def _dispose_renderer(self):
        if self._renderer is None or self._module._dispose_renderer is None:
            self._renderer = None
            return
        try:
            self._module._dispose_renderer(self._renderer)
        finally:
            self._renderer = None

    @staticmethod
    def _read_expression_names(info) -> dict[str, None]:
        expressions = info[b"expressions"] or {}
        names = {}
        for name in expressions.keys():
            names[_decode_lua_string(name)] = None
        return names


class LuaCompositeLAppModel:
    def __init__(self, module: LuaLive2DModule):
        self._module = module
        self._single = LuaLAppModel(module)
        self._layers: list[LuaLAppModel] = []
        self._width = 1
        self._height = 1
        self.modelSetting = None
        self.matrixManager = _MatrixManager()
        self.expressions = {}
        self.last_lua_update_draw_seconds = 0.0
        self.last_lua_gc_seconds = 0.0

    @property
    def _active_models(self) -> list[LuaLAppModel]:
        return self._layers if self._layers else [self._single]

    @property
    def _renderer(self):
        return self._single._renderer if not self._layers else None

    def LoadModelJson(self, model_json_path: str):
        self._dispose_renderer()
        if is_webgal_composite_path(model_json_path):
            self._layers = []
            for layer_path in _webgal_composite_layer_paths(model_json_path):
                layer = LuaLAppModel(self._module)
                layer.Resize(self._width, self._height)
                layer.LoadModelJson(layer_path)
                self._layers.append(layer)
            self._sync_public_model_info()
            return
        self._single.LoadModelJson(model_json_path)
        self._single.Resize(self._width, self._height)
        self._sync_public_model_info()

    def _sync_public_model_info(self):
        models = self._active_models
        settings = [model.modelSetting for model in models if model.modelSetting is not None]
        self.modelSetting = _CompositeModelSetting(settings) if self._layers else self._single.modelSetting
        expressions = {}
        for model in models:
            expressions.update(getattr(model, "expressions", {}) or {})
        self.expressions = expressions

    def Resize(self, width: int, height: int):
        self._width = max(int(width), 1)
        self._height = max(int(height), 1)
        self.matrixManager.on_resize(self._width, self._height)
        for model in self._active_models:
            model.Resize(self._width, self._height)

    def Draw(self):
        self.last_lua_update_draw_seconds = 0.0
        self.last_lua_gc_seconds = 0.0
        for model in self._active_models:
            model.Draw()
            self.last_lua_update_draw_seconds += getattr(model, "last_lua_update_draw_seconds", 0.0)
            self.last_lua_gc_seconds += getattr(model, "last_lua_gc_seconds", 0.0)

    def Drag(self, x: float, y: float):
        for model in self._active_models:
            model.Drag(x, y)

    def SetParameterValue(self, param_id: str, value: float, weight: float = 1.0):
        for model in self._active_models:
            model.SetParameterValue(param_id, value, weight)

    def HitTest(self, area_name: str, x: float, y: float):
        for model in reversed(self._active_models):
            if model.HitTest(area_name, x, y):
                return "hit"
        return None

    def StartMotion(self, name: str, no: int = 0, priority=MotionPriority.FORCE, **kwargs):
        for model in self._active_models:
            setting = getattr(model, "modelSetting", None)
            if setting is None or setting.resolveMotion(str(name), int(no)) is None:
                continue
            model.StartMotion(name, no, priority, **kwargs)

    def StartRandomMotion(self, name: str | None = None, priority=MotionPriority.IDLE, **kwargs):
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
        self.StartMotion(name, random.randrange(count), priority, **kwargs)

    def PreloadMotionGroup(self, name: str):
        for model in self._active_models:
            setting = getattr(model, "modelSetting", None)
            if setting is None or setting.resolveMotion(str(name), 0) is None:
                continue
            model.PreloadMotionGroup(name)

    def PreloadExpression(self, name: str):
        for model in self._active_models:
            if name not in (getattr(model, "expressions", {}) or {}):
                continue
            model.PreloadExpression(name)

    def ClearMotions(self):
        for model in self._active_models:
            model.ClearMotions()

    def IsMotionFinished(self) -> bool:
        return all(model.IsMotionFinished() for model in self._active_models)

    def SetExpression(self, name: str):
        for model in self._active_models:
            if name not in (getattr(model, "expressions", {}) or {}):
                continue
            model.SetExpression(name)

    def ResetExpression(self):
        for model in self._active_models:
            model.ResetExpression()

    def ApplyTextureQuality(self, profile: str):
        for model in self._active_models:
            model.ApplyTextureQuality(profile)

    def _dispose_renderer(self):
        for model in self._layers:
            model._dispose_renderer()
        self._layers = []
        self._single._dispose_renderer()
        self.modelSetting = None
        self.expressions = {}


live2d = LuaLive2DModule()
