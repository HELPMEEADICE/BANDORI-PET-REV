from live2d_lua_adapter_base import (
    MODEL_FORMAT_MOC,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
    _require_bundled_lua_module,
)


class LuaLive2DModuleMOC(LuaLive2DRuntimeBase):

    def _configure_runtime(self, lua):
        _require_bundled_lua_module(lua, "live2d_platform_manager_override")
        lua.execute(
            b"local target, source = ...; package.loaded[target] = package.loaded[source]",
            b"live2d.platform_manager",
            b"live2d_platform_manager_override",
        )

    def _ensure_runtime(self):
        if self._initialized:
            return
        super()._ensure_runtime()
        try:
            self._embed = self._lua.execute(b'return require("live2d_embed")')
            self._embed.init()
        except Exception:
            super().dispose()
            raise

    def LAppModel(self):
        self._ensure_runtime()
        return LuaLAppModelMOC(self)


class LuaLAppModelMOC(LuaLAppModelBase):

    def __init__(self, module: LuaLive2DRuntimeBase):
        super().__init__(module, MODEL_FORMAT_MOC)

    def LoadModelJson(self, model_json_path: str):
        self._load_model_json(model_json_path, decode_textures=False)


live2d_moc = LuaLive2DModuleMOC()
