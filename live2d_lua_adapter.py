import io
import json
import os
import random
import time
from pathlib import Path

try:
    from lupa.luajit21 import LuaRuntime
except ModuleNotFoundError:
    from lupa.lua import LuaRuntime
from PIL import Image

from platform_patch import get_live2d_texture_quality
from process_utils import app_base_dir
from zst_model_archive import is_virtual_path, load_virtual_bytes


BASE_DIR = Path(app_base_dir())
LIVE2D_LUA_DIR = BASE_DIR / "third_party" / "Live2D-v2-Lua"
MODELS_DIR = BASE_DIR / "models"


def _normalize_lua_path(path) -> str:
    if isinstance(path, bytes):
        path = path.decode("utf-8")
    return str(path).replace("\\", "/")


def _read_lua_chunk_bytes(path: Path) -> bytes:
    return path.read_bytes()


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


def _preload_lua_modules(lua: LuaRuntime, root: Path):
    register = lua.eval(
        b"function(name, chunk, chunk_name) "
        b"local loader, err = load(chunk, chunk_name); "
        b"assert(loader, err); "
        b"package.preload[name] = loader "
        b"end"
    )
    for module_name, module_path in _iter_lua_module_files(root):
        register(
            module_name.encode("utf-8"),
            _read_lua_chunk_bytes(module_path),
            ("@" + module_path.as_posix()).encode("utf-8"),
        )


def _load_model_bytes(path: str) -> bytes:
    path = _normalize_lua_path(path)
    if is_virtual_path(path):
        try:
            return load_virtual_bytes(path)
        except KeyError:
            fixed = _fix_mtn_path(path)
            if fixed:
                return Path(fixed).read_bytes()
            raise

    fs_path = Path(path)
    if not fs_path.exists():
        fixed = _fix_mtn_path(path)
        if fixed:
            fs_path = Path(fixed)
    return fs_path.read_bytes()


def _load_model_json(path: str) -> dict:
    return json.loads(_load_model_bytes(path).decode("utf-8"))


def _texture_options(profile: str) -> tuple[float, bool, int]:
    if profile == "performance":
        return 0.5, False, 0
    return 1.0, False, 0


def _bleed_transparent_edges(image: Image.Image, passes: int) -> Image.Image:
    if passes <= 0:
        return image

    pixels = image.load()
    width, height = image.size
    for _ in range(passes):
        updates = []
        for y in range(height):
            for x in range(width):
                alpha = pixels[x, y][3]
                if alpha >= 255:
                    continue

                red = green = blue = count = 0
                for nx, ny in (
                    (x - 1, y),
                    (x + 1, y),
                    (x, y - 1),
                    (x, y + 1),
                ):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    nr, ng, nb, na = pixels[nx, ny]
                    if na <= alpha:
                        continue
                    red += nr
                    green += ng
                    blue += nb
                    count += 1

                if count:
                    updates.append((x, y, red // count, green // count, blue // count, alpha))

        if not updates:
            break
        for x, y, red, green, blue, alpha in updates:
            pixels[x, y] = (red, green, blue, alpha)
    return image


def _resize_for_quality(image: Image.Image, scale: float) -> Image.Image:
    if scale >= 1.0:
        return image
    width = max(1, int(image.width * scale))
    height = max(1, int(image.height * scale))
    resampling = getattr(Image, "Resampling", Image).BILINEAR
    return image.resize((width, height), resampling)


def _texture_rgba(path: str, profile: str) -> tuple[int, int, bytes, bool]:
    scale, use_mipmap, bleed_passes = _texture_options(profile)
    source = io.BytesIO(load_virtual_bytes(path, cache=False)) if is_virtual_path(path) else Path(path)
    with Image.open(source) as image:
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        try:
            image = _resize_for_quality(image, scale)
            image = _bleed_transparent_edges(image, bleed_passes)
            return image.width, image.height, image.tobytes(), use_mipmap
        finally:
            image.close()


def _fix_mtn_path(path: str) -> str:
    basename = os.path.basename(path)
    mtn_emp_dir = MODELS_DIR / "_mtn_emp"
    if not basename or not mtn_emp_dir.is_dir():
        return ""
    for root, _dirs, files in os.walk(mtn_emp_dir):
        if basename in files:
            return str(Path(root) / basename)
    return ""


class _ModelSetting:
    def __init__(self, data: dict):
        self.json = data

    def getMotionNames(self) -> list[str]:
        motions = self.json.get("motions") or {}
        if not isinstance(motions, dict):
            return []
        return [str(name) for name in motions if name]

    def getMotionNum(self, name: str) -> int:
        group = self._motion_group(name)
        return len(group)

    def resolveMotion(self, name: str, no: int = 0) -> tuple[str, int] | None:
        group = self._motion_group(name)
        if group:
            return name, max(0, min(int(no), len(group) - 1))

        target = Path(str(name).replace("\\", "/")).name.lower()
        target_stem = Path(target).stem
        motions = self.json.get("motions") or {}
        if not isinstance(motions, dict):
            return None
        for group_name, group in motions.items():
            if not isinstance(group, list):
                continue
            for idx, item in enumerate(group):
                if not isinstance(item, dict):
                    continue
                motion_file = Path(str(item.get("file", "")).replace("\\", "/")).name.lower()
                if motion_file == target or Path(motion_file).stem == target_stem:
                    return str(group_name), idx
        return None

    def _motion_group(self, name: str) -> list:
        motions = self.json.get("motions") or {}
        if not isinstance(motions, dict):
            return []
        group = motions.get(name) or []
        return group if isinstance(group, list) else []

    def getHitAreaNum(self) -> int:
        hit_areas = self.json.get("hit_areas") or []
        return len(hit_areas) if isinstance(hit_areas, list) else 0


class MotionPriority:
    NONE = 0
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
        self.MotionPriority = MotionPriority

    def init(self):
        return True

    def glInit(self):
        self._ensure_runtime()

    def clearBuffer(self):
        return True

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
        _preload_lua_modules(lua, LIVE2D_LUA_DIR)
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
            b"return function(renderer, profile) "
            b"local model = renderer:get_model(); "
            b"if model == nil or model.live2DModel == nil or model.live2DModel.drawParamGL == nil then return end; "
            b"local textures = model.live2DModel.drawParamGL.textures or {}; "
            b"local min_filter = gl.LINEAR; "
            b"local mag_filter = gl.LINEAR; "
            b"local use_mipmap = false; "
            b"if profile == 'performance' then "
            b"min_filter = GL_NEAREST; mag_filter = GL_NEAREST; "
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
            w, h, rgba, use_mipmap = _texture_rgba(_normalize_lua_path(path), profile)
            entry = lua.table()
            entry[b"width"] = w
            entry[b"height"] = h
            entry[b"data"] = rgba
            entry[b"mipmap"] = use_mipmap
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

    def LoadModelJson(self, model_json_path: str, disable_precision=False):
        del disable_precision
        model_json = _load_model_json(model_json_path)
        self.modelSetting = _ModelSetting(model_json)
        self.expressions = self._read_expression_names(model_json)
        self._renderer = self._module._new_renderer(self._width, self._height)
        opts = self._module._new_options(model_json_path)
        self._module._load_model(
            self._renderer,
            _normalize_lua_path(model_json_path).encode("utf-8"),
            self._width,
            self._height,
            opts,
        )
        self._module._apply_texture_quality(self._renderer, get_live2d_texture_quality().encode("utf-8"))

    def Resize(self, width: int, height: int):
        self._width = max(int(width), 1)
        self._height = max(int(height), 1)
        self.matrixManager.on_resize(self._width, self._height)
        if self._renderer is not None:
            self._module._resize(self._renderer, self._width, self._height)

    def Update(self):
        return True

    def Draw(self):
        if self._renderer is None:
            return
        opts = self._module._lua.table()
        opts[b"clear"] = False
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
        self._module._draw(self._renderer, opts)

    def Drag(self, x: float, y: float):
        if self._renderer is not None:
            self._module._drag(self._renderer, float(x), float(y))

    def SetOffset(self, x: float, y: float):
        if self._renderer is not None:
            self._module._set_offset(self._renderer, float(x), float(y))

    def SetParameterValue(self, param_id: str, value: float, weight: float = 1.0):
        self._pending_parameters[str(param_id)] = (str(param_id), float(value), float(weight))

    def HitTest(self, _area_name: str, x: float, y: float):
        if self._renderer is None:
            return None
        hits = self._module._hit_test(self._renderer, float(x), float(y))
        try:
            return "hit" if len(hits) > 0 else None
        except Exception:
            return None

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

    def ClearMotions(self):
        if self._renderer is not None:
            self._module._clear_motions(self._renderer)

    def IsMotionFinished(self) -> bool:
        if self._renderer is None:
            return True
        return bool(self._module._is_motion_finished(self._renderer))

    def SetExpression(self, name: str):
        if self._renderer is not None:
            self._module._set_expression(self._renderer, str(name).encode("utf-8"))

    def ResetExpression(self):
        if self._renderer is not None:
            self._module._reset_expression(self._renderer)

    @staticmethod
    def _read_expression_names(model_json: dict) -> dict[str, None]:
        expressions = model_json.get("expressions") or []
        if not isinstance(expressions, list):
            return {}
        names = {}
        for item in expressions:
            if isinstance(item, dict) and item.get("name"):
                names[str(item["name"])] = None
        return names


live2d = LuaLive2DModule()
