import sys

from live2d_lua_adapter_base import (
    MODEL_FORMAT_MOC3,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
    _first_error_line,
)


_MOC3_PET_DELTA_HELPER = b'''
local function compute_delta_seconds(state, time_msec)
    time_msec = tonumber(time_msec)
    if time_msec == nil then
        return 0
    end
    local last_time_msec = state.last_time_msec
    state.last_time_msec = time_msec
    if last_time_msec == nil or time_msec <= last_time_msec then
        return 0
    end
    return math.min((time_msec - last_time_msec) / 1000.0, 0.1)
end
'''


def _patch_lua_moc3_pet_embed_delta(module_name: str, chunk: bytes) -> bytes:
    if module_name != "live2d_moc3_pet_embed":
        return chunk
    insert_after = b"local GL_COLOR_BUFFER_BIT = 0x00004000\n"
    if b"compute_delta_seconds" not in chunk and insert_after in chunk:
        chunk = chunk.replace(insert_after, insert_after + _MOC3_PET_DELTA_HELPER, 1)
    old_delta = (
        b"    local time_msec = tonumber(opts.time_msec) or 0\n"
        b"    local delta = 1 / 60\n"
        b"    if self.last_time_msec ~= nil and time_msec > self.last_time_msec then\n"
        b"        delta = math.min((time_msec - self.last_time_msec) / 1000.0, 0.1)\n"
        b"    end\n"
        b"    self.last_time_msec = time_msec\n"
    )
    new_delta = b"    local delta = compute_delta_seconds(self, opts.time_msec)\n"
    return chunk.replace(old_delta, new_delta, 1)


class LuaLive2DModuleMOC3(LuaLive2DRuntimeBase):

    def __init__(self):
        super().__init__()
        self._moc3_embed = None
        self._moc3_error = ""

    def _get_extra_module_patch(self):
        return _patch_lua_moc3_pet_embed_delta

    def _ensure_runtime(self):
        if self._initialized:
            return
        super()._ensure_runtime()
        try:
            self._moc3_embed = self._lua.execute(b'return require("live2d_moc3_pet_embed")')
            self._moc3_embed.init()
            self._moc3_error = ""
        except Exception as exc:
            self._moc3_embed = None
            self._moc3_error = _first_error_line(exc)
            print(
                f"[Live2D] MOC3 renderer unavailable: {self._moc3_error}",
                file=sys.stderr,
                flush=True,
            )

    def dispose(self):
        self._moc3_embed = None
        self._moc3_error = ""
        super().dispose()

    def _new_renderer(self, width: int, height: int):
        self._ensure_runtime()
        if self._moc3_embed is None:
            detail = f": {self._moc3_error}" if self._moc3_error else ""
            raise RuntimeError(f"Live2D MOC3 renderer is unavailable{detail}")
        return self._moc3_embed.new(width, height)

    def LAppModel(self):
        return LuaLAppModelMOC3(self)


class LuaLAppModelMOC3(LuaLAppModelBase):

    def LoadModelJson(self, model_json_path: str):
        self._dispose_renderer()
        self._renderer_format = MODEL_FORMAT_MOC3
        self._renderer = self._module._new_renderer(self._width, self._height)
        opts = self._module._new_options(model_json_path, decode_textures=True)
        from live2d_lua_adapter_base import _normalize_lua_path
        self._module._load_model(
            self._renderer,
            _normalize_lua_path(model_json_path).encode("utf-8"),
            self._width,
            self._height,
            opts,
        )
        info = self._module._model_info(self._renderer)
        from live2d_lua_adapter_base import _ModelSetting
        self.modelSetting = _ModelSetting(info)
        self.expressions = self._read_expression_names(info)
        from platform_patch import get_live2d_texture_quality
        self._module._apply_texture_quality(self._renderer, get_live2d_texture_quality().encode("utf-8"))


live2d_moc3 = LuaLive2DModuleMOC3()
