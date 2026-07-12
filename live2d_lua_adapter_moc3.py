from live2d_lua_adapter_base import (
    MODEL_FORMAT_MOC3,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
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
    def _get_extra_module_patch(self):
        return _patch_lua_moc3_pet_embed_delta

    def _ensure_runtime(self):
        if self._initialized:
            return
        super()._ensure_runtime()
        try:
            self._embed = self._lua.execute(b'return require("live2d_moc3_pet_embed")')
            self._embed.init()
            self._render_frame = self._lua.eval(
                b"function(renderer, opts) return renderer:render_frame(opts) end"
            )
        except Exception:
            super().dispose()
            raise

    def LAppModel(self):
        self._ensure_runtime()
        return LuaLAppModelMOC3(self)


class LuaLAppModelMOC3(LuaLAppModelBase):

    def __init__(self, module: LuaLive2DRuntimeBase):
        super().__init__(module, MODEL_FORMAT_MOC3)

    def LoadModelJson(self, model_json_path: str):
        self._load_model_json(model_json_path, decode_textures=True)


live2d_moc3 = LuaLive2DModuleMOC3()
