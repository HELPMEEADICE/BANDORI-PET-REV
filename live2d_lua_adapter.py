import sys

from live2d_lua_adapter_base import (
    LIVE2D_PROFILE_ENABLED,
    MODEL_FORMAT_MOC,
    MODEL_FORMAT_MOC3,
    MotionPriority,
    LuaLAppModelBase,
    LuaLive2DRuntimeBase,
    _first_error_line,
    _model_manifest_format,
)
from live2d_lua_adapter_moc3 import _patch_lua_moc3_pet_embed_delta


class LuaLive2DModule(LuaLive2DRuntimeBase):
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
        lua = self._lua
        self._embed = lua.execute(b'return require("live2d_embed")')
        self._embed.init()
        try:
            self._moc3_embed = lua.execute(b'return require("live2d_moc3_pet_embed")')
            self._moc3_embed.init()
            self._moc3_error = ""
        except Exception as exc:
            self._moc3_embed = None
            self._moc3_error = _first_error_line(exc)
            print(
                f"[Live2D] MOC3 renderer unavailable; Cubism 2 models remain enabled: {self._moc3_error}",
                file=sys.stderr,
                flush=True,
            )

    def dispose(self):
        self._moc3_embed = None
        self._moc3_error = ""
        super().dispose()

    def LAppModel(self):
        return LuaLAppModel(self)

    def _new_renderer(self, width: int, height: int, model_format: str = MODEL_FORMAT_MOC):
        self._ensure_runtime()
        if model_format == MODEL_FORMAT_MOC3:
            if self._moc3_embed is None:
                detail = f": {self._moc3_error}" if self._moc3_error else ""
                raise RuntimeError(f"Live2D MOC3 renderer is unavailable{detail}")
            embed = self._moc3_embed
        else:
            embed = self._embed
        return embed.new(width, height)


class LuaLAppModel(LuaLAppModelBase):

    def LoadModelJson(self, model_json_path: str):
        self._dispose_renderer()
        self._renderer_format = _model_manifest_format(model_json_path)
        self._renderer = self._module._new_renderer(self._width, self._height, self._renderer_format)
        from live2d_lua_adapter_base import _normalize_lua_path
        decode_textures = self._renderer_format == MODEL_FORMAT_MOC3
        opts = self._module._new_options(model_json_path, decode_textures=decode_textures)
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


live2d = LuaLive2DModule()
