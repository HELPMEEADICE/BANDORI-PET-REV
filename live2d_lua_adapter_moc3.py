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
    chunk = chunk.replace(b"\r\n", b"\n")
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
    chunk = chunk.replace(old_delta, new_delta, 1)

    if b"function Renderer:resize_renderer" in chunk:
        return chunk

    size_fields = (
        b"        height = math.max(tonumber(height) or 1, 1),\n"
        b"        offset_x = 0,\n"
    )
    render_size_fields = (
        b"        height = math.max(tonumber(height) or 1, 1),\n"
        b"        render_width = math.max(tonumber(width) or 1, 1),\n"
        b"        render_height = math.max(tonumber(height) or 1, 1),\n"
        b"        offset_x = 0,\n"
    )
    chunk = chunk.replace(size_fields, render_size_fields, 1)

    old_resize = (
        b"function Renderer:resize(width, height)\n"
        b"    self.width = math.max(tonumber(width) or self.width or 1, 1)\n"
        b"    self.height = math.max(tonumber(height) or self.height or 1, 1)\n"
        b"    gl.glViewport(0, 0, self.width, self.height)\n"
        b"    local runtime = self.renderer and self.renderer:get_runtime() or nil\n"
        b"    self.projection = new_projection(self.width, self.height, runtime, self.offset_x, self.offset_y, self.scale)\n"
        b"    return self\n"
        b"end\n"
    )
    new_resize = (
        b"function Renderer:resize(width, height)\n"
        b"    self.width = math.max(tonumber(width) or self.width or 1, 1)\n"
        b"    self.height = math.max(tonumber(height) or self.height or 1, 1)\n"
        b"    return self:resize_renderer(self.width, self.height)\n"
        b"end\n\n"
        b"function Renderer:resize_renderer(width, height)\n"
        b"    self.render_width = math.max(tonumber(width) or self.render_width or self.width or 1, 1)\n"
        b"    self.render_height = math.max(tonumber(height) or self.render_height or self.height or 1, 1)\n"
        b"    gl.glViewport(0, 0, self.render_width, self.render_height)\n"
        b"    local runtime = self.renderer and self.renderer:get_runtime() or nil\n"
        b"    self.projection = new_projection(self.render_width, self.render_height, runtime, self.offset_x, self.offset_y, self.scale)\n"
        b"    return self\n"
        b"end\n"
    )
    chunk = chunk.replace(old_resize, new_resize, 1)

    old_offset = (
        b"function Renderer:set_offset(x, y)\n"
        b"    self.offset_x = tonumber(x) or 0\n"
        b"    self.offset_y = tonumber(y) or 0\n"
        b"    return self:resize(self.width, self.height)\n"
        b"end\n"
    )
    new_offset = (
        b"function Renderer:set_offset(x, y)\n"
        b"    self.offset_x = tonumber(x) or 0\n"
        b"    self.offset_y = tonumber(y) or 0\n"
        b"    return self:resize_renderer(self.render_width, self.render_height)\n"
        b"end\n"
    )
    chunk = chunk.replace(old_offset, new_offset, 1)

    old_scale = (
        b"function Renderer:set_scale(scale)\n"
        b"    self.scale = tonumber(scale) or 1\n"
        b"    return self:resize(self.width, self.height)\n"
        b"end\n"
    )
    new_scale = (
        b"function Renderer:set_scale(scale)\n"
        b"    self.scale = tonumber(scale) or 1\n"
        b"    return self:resize_renderer(self.render_width, self.render_height)\n"
        b"end\n"
    )
    return chunk.replace(old_scale, new_scale, 1)


def _patch_lua_moc3_physics_zero_delta(module_name: str, chunk: bytes) -> bytes:
    if module_name != "live2d.cubism3.physics":
        return chunk
    chunk = chunk.replace(b"\r\n", b"\n")
    old_guard = (
        b"    delta = tonumber(delta) or 0\n"
        b"    if delta <= 0 then return false end\n"
    )
    new_guard = (
        b"    delta = tonumber(delta) or 0\n"
        b"    self.last_substep_count = 0\n"
        b"    if delta <= 0 then\n"
        b"        local physics_delta = self.data.fps > 0 and 1.0 / self.data.fps or 1.0\n"
        b"        self:_interpolate(runtime, self.remaining_time / physics_delta)\n"
        b"        return false\n"
        b"    end\n"
    )
    if old_guard not in chunk:
        return chunk
    chunk = chunk.replace(old_guard, new_guard, 1)
    substep_marker = b"    while self.remaining_time >= physics_delta do\n"
    return chunk.replace(
        substep_marker,
        substep_marker + b"        self.last_substep_count = self.last_substep_count + 1\n",
        1,
    )


def _patch_lua_moc3_module(module_name: str, chunk: bytes) -> bytes:
    chunk = _patch_lua_moc3_pet_embed_delta(module_name, chunk)
    return _patch_lua_moc3_physics_zero_delta(module_name, chunk)


class LuaLive2DModuleMOC3(LuaLive2DRuntimeBase):
    def _get_extra_module_patch(self):
        return _patch_lua_moc3_module

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
