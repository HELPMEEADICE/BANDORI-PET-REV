from bandori_live2d.live2d_lua_adapter_base import (
    MODEL_FORMAT_MOC,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
    _require_bundled_lua_module,
)


class LuaLive2DModuleMOC(LuaLive2DRuntimeBase):

    def __init__(self):
        super().__init__()
        self._supports_texture_byte_streams = False

    def _configure_runtime(self, lua):
        _require_bundled_lua_module(lua, "live2d_platform_manager_override")
        lua.execute(
            b"local target, source = ...; package.loaded[target] = package.loaded[source]",
            b"live2d.platform_manager",
            b"live2d_platform_manager_override",
        )
        self._supports_texture_byte_streams = bool(
            lua.execute(
                b"local ffi = require('ffi'); "
                b"local loader = require('live2d.image_loader'); "
                b"return ffi.os == 'Windows' or type(loader.loadImageBytes) == 'function'"
            )
        )

    def requires_python_texture_decode(self) -> bool:
        """Use Pillow when the bundled Lua decoder cannot consume PNG bytes."""
        self._ensure_runtime()
        return not self._supports_texture_byte_streams

    def _load_lua_runtime_functions(self, lua):
        super()._load_lua_runtime_functions(lua)
        # Cubism 2 restores its viewport after drawing clipping masks from
        # the native draw parameter size. Keep that size in physical pixels,
        # without changing the logical projection or pointer coordinates.
        self._resize_renderer = lua.eval(
            b"function(renderer, w, h) "
            b"return renderer:get_model().live2DModel:resize(w, h) end"
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
        self._load_model_json(
            model_json_path,
            decode_textures=self._module.requires_python_texture_decode(),
        )


live2d_moc = LuaLive2DModuleMOC()
