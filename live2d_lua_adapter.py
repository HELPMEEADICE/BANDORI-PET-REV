"""Public Live2D adapter with lazy, format-isolated renderer runtimes.

The application-facing API stays compatible with the previous ``live2d``
module.  A model manifest is inspected only when it is loaded; the selected
Cubism 2 or Cubism 3 adapter then owns the Lua runtime, embed module and model
renderer for that model.
"""

from live2d_lua_adapter_base import (
    MODEL_FORMAT_MOC3,
    MotionPriority,
    _model_manifest_format,
)
from live2d_lua_adapter_moc import live2d_moc
from live2d_lua_adapter_moc3 import live2d_moc3

__all__ = [
    "LuaLAppModel",
    "LuaLive2DModule",
    "live2d",
]


class LuaLive2DModule:
    """Compatibility facade that dispatches models to isolated runtimes."""

    MotionPriority = MotionPriority

    def __init__(self, moc_runtime=None, moc3_runtime=None):
        self._moc_runtime = live2d_moc if moc_runtime is None else moc_runtime
        self._moc3_runtime = live2d_moc3 if moc3_runtime is None else moc3_runtime

    def glInit(self):
        """Keep initialization lazy until the model format is known.

        This method is intentionally a no-op.  ``LAppModel.LoadModelJson``
        initializes exactly one runtime while the widget's GL context is
        current.
        """

    def dispose(self):
        disposed = set()
        for runtime in (self._moc_runtime, self._moc3_runtime):
            runtime_id = id(runtime)
            if runtime_id in disposed:
                continue
            disposed.add(runtime_id)
            runtime.dispose()

    def LAppModel(self):
        return LuaLAppModel(self)

    def _runtime_for_format(self, model_format: str):
        if model_format == MODEL_FORMAT_MOC3:
            return self._moc3_runtime
        return self._moc_runtime


class LuaLAppModel:
    """Thin model proxy whose delegate belongs to one renderer runtime."""

    def __init__(self, module: LuaLive2DModule):
        self._module = module
        self._delegate = None
        self._width = 1
        self._height = 1

    def LoadModelJson(self, model_json_path: str):
        self._dispose_renderer()
        model_format = _model_manifest_format(model_json_path)
        runtime = self._module._runtime_for_format(model_format)
        delegate = runtime.LAppModel()
        delegate.Resize(self._width, self._height)
        self._delegate = delegate
        try:
            delegate.LoadModelJson(model_json_path)
        except Exception:
            try:
                self._dispose_renderer()
            except Exception:
                pass
            raise

    @property
    def renderer_format(self) -> str:
        if self._delegate is None:
            return ""
        return self._delegate.renderer_format

    def Resize(self, width: int, height: int):
        self._width = max(int(width), 1)
        self._height = max(int(height), 1)
        if self._delegate is not None:
            self._delegate.Resize(self._width, self._height)

    def _dispose_renderer(self):
        delegate = self._delegate
        self._delegate = None
        if delegate is not None:
            delegate._dispose_renderer()

    def __getattr__(self, name):
        delegate = self.__dict__.get("_delegate")
        if delegate is None:
            raise AttributeError(f"Live2D model is not loaded; attribute {name!r} is unavailable")
        return getattr(delegate, name)


live2d = LuaLive2DModule()
