from bandori_live2d.live2d_lua_adapter_base import (
    MODEL_FORMAT_MOC3,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
)
from bandori_live2d.live2d_lua_moc3_source_patch import (
    _patch_lua_moc3_pet_embed_delta,
    patch_live2d_lua_moc3_module as _patch_lua_moc3_module,
)


class LuaLive2DModuleMOC3(LuaLive2DRuntimeBase):
    def __init__(self):
        super().__init__()
        self._get_canvas_size = None
        self._get_canvas_content_bounds = None

    def _get_extra_module_patch(self):
        return _patch_lua_moc3_module

    def _ensure_runtime(self):
        if self._initialized:
            return
        super()._ensure_runtime()
        try:
            self._get_canvas_size = self._lua.eval(
                b"function(renderer) "
                b"local runtime_renderer = renderer and (renderer.renderer or renderer) or nil; "
                b"local runtime = runtime_renderer and runtime_renderer:get_runtime() or nil; "
                b"local canvas = runtime and runtime.canvas or nil; "
                b"if canvas == nil then return nil, nil end; "
                b"return canvas.width, canvas.height "
                b"end"
            )
            self._get_canvas_content_bounds = self._lua.eval(
                b"function(renderer) "
                b"local runtime_renderer = renderer and (renderer.renderer or renderer) or nil; "
                b"local runtime = runtime_renderer and runtime_renderer:get_runtime() or nil; "
                b"local canvas = runtime and runtime.canvas or nil; "
                b"local pixels_per_unit = canvas and tonumber(canvas.pixels_per_unit) or nil; "
                b"if runtime == nil or canvas == nil or pixels_per_unit == nil or pixels_per_unit <= 0 then "
                b"return nil, nil, nil, nil, nil end; "
                b"local min_x, max_x = math.huge, -math.huge; "
                b"local min_y, max_y = math.huge, -math.huge; "
                b"for _, mesh in ipairs(runtime.meshes or {}) do "
                b"if (tonumber(mesh.opacity) or 0) > 0 then "
                b"for _, vertex in ipairs(mesh.vertices or {}) do "
                b"local position = vertex and vertex.position or nil; "
                b"local x = position and tonumber(position[1]) or nil; "
                b"local y = position and tonumber(position[2]) or nil; "
                b"if x ~= nil and y ~= nil then "
                b"min_x, max_x = math.min(min_x, x), math.max(max_x, x); "
                b"min_y, max_y = math.min(min_y, y), math.max(max_y, y); "
                b"end end end end; "
                b"if min_x == math.huge then return nil, nil, nil, nil, nil end; "
                b"return canvas.height / pixels_per_unit, min_x, max_x, min_y, max_y "
                b"end"
            )
            self._embed = self._lua.execute(b'return require("live2d_moc3_pet_embed")')
            self._embed.init()
            self._render_frame = self._lua.eval(
                b"function(renderer, opts) return renderer:render_frame(opts) end"
            )
        except Exception:
            self.dispose()
            raise

    def dispose(self):
        self._get_canvas_size = None
        self._get_canvas_content_bounds = None
        super().dispose()

    def LAppModel(self):
        self._ensure_runtime()
        return LuaLAppModelMOC3(self)


class LuaLAppModelMOC3(LuaLAppModelBase):
    def __init__(self, module: LuaLive2DRuntimeBase):
        super().__init__(module, MODEL_FORMAT_MOC3)

    def LoadModelJson(self, model_json_path: str):
        self._load_model_json(model_json_path, decode_textures=True)

    def GetCanvasSize(self) -> tuple[float, float] | None:
        if self._renderer is None:
            return None
        get_canvas_size = getattr(self._module, "_get_canvas_size", None)
        if not callable(get_canvas_size):
            return None
        try:
            width, height = get_canvas_size(self._renderer)
            if width is None or height is None:
                return None
            return float(width), float(height)
        except (TypeError, ValueError, RuntimeError):
            return None

    def GetCanvasContentBounds(self) -> tuple[float, float, float, float, float] | None:
        if self._renderer is None:
            return None
        get_content_bounds = getattr(self._module, "_get_canvas_content_bounds", None)
        if not callable(get_content_bounds):
            return None
        try:
            values = get_content_bounds(self._renderer)
            if not isinstance(values, (tuple, list)) or len(values) < 5:
                return None
            if any(value is None for value in values[:5]):
                return None
            return tuple(float(value) for value in values[:5])
        except (TypeError, ValueError, RuntimeError):
            return None


live2d_moc3 = LuaLive2DModuleMOC3()
