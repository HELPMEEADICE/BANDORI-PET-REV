import sys

from live2d_lua_adapter_base import (
    LIVE2D_LUA_DIR,
    MODEL_FORMAT_MOC,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
    _require_bundled_lua_module,
)


class LuaLive2DModuleMOC(LuaLive2DRuntimeBase):

    def _ensure_runtime(self):
        if self._initialized:
            return
        super()._ensure_runtime()
        lua = self._lua
        self._embed = lua.execute(b'return require("live2d_embed")')
        self._embed.init()

    def dispose(self):
        if self._embed is not None:
            try:
                self._embed.dispose()
            except Exception:
                pass
        super().dispose()

    def _new_renderer(self, width: int, height: int):
        self._ensure_runtime()
        return self._embed.new(width, height)

    def LAppModel(self):
        return LuaLAppModelMOC(self)


class LuaLAppModelMOC(LuaLAppModelBase):

    def LoadModelJson(self, model_json_path: str):
        self._dispose_renderer()
        self._renderer_format = MODEL_FORMAT_MOC
        self._renderer = self._module._new_renderer(self._width, self._height)
        opts = self._module._new_options(model_json_path, decode_textures=False)
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


live2d_moc = LuaLive2DModuleMOC()
