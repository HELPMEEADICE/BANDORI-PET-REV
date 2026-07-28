from __future__ import annotations

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class NativeBridgeStatus:
    available: bool
    reason: str = ""
    compiled_qt: str = ""
    runtime_qt: str = ""


class LayerShellBridge:
    def __init__(self):
        self._module = None
        self._status = self._load()

    @property
    def status(self) -> NativeBridgeStatus:
        return self._status

    def _load(self) -> NativeBridgeStatus:
        try:
            module = importlib.import_module("wayland._native._layer_shell")
        except Exception as exc:
            return NativeBridgeStatus(False, f"native bridge is not built: {exc}")
        try:
            from PySide6.QtCore import qVersion

            required = (
                "initialize",
                "prepare",
                "qt_version",
                "rebind_output",
                "set_keyboard",
                "set_layer",
                "set_margins",
                "set_size",
            )
            missing = [name for name in required if not hasattr(module, name)]
            if missing:
                raise RuntimeError(
                    "native bridge must be rebuilt; missing API: "
                    + ", ".join(missing)
                )
            compiled = str(module.qt_version())
            runtime = str(qVersion())
            compiled_mm = ".".join(compiled.split(".")[:2])
            runtime_mm = ".".join(runtime.split(".")[:2])
            if compiled_mm != runtime_mm:
                return NativeBridgeStatus(
                    False,
                    "Qt private ABI mismatch: "
                    f"bridge={compiled}, PySide6 runtime={runtime}",
                    compiled,
                    runtime,
                )
            module.initialize()
        except Exception as exc:
            return NativeBridgeStatus(False, f"native bridge initialization failed: {exc}")
        self._module = module
        return NativeBridgeStatus(True, "", compiled, runtime)

    def prepare(self, qwindow, *, x: int, y: int, width: int, height: int,
                layer: str, keyboard: str, scope: str) -> None:
        if self._module is None:
            raise RuntimeError(self._status.reason or "native bridge unavailable")
        self._module.prepare(
            qwindow,
            int(x),
            int(y),
            max(1, int(width)),
            max(1, int(height)),
            str(layer),
            str(keyboard),
            str(scope),
        )

    def set_margins(self, qwindow, x: int, y: int) -> None:
        self._module.set_margins(qwindow, int(x), int(y))

    def set_size(self, qwindow, width: int, height: int) -> None:
        self._module.set_size(qwindow, max(1, int(width)), max(1, int(height)))

    def set_layer(self, qwindow, layer: str) -> None:
        self._module.set_layer(qwindow, str(layer))

    def set_keyboard(self, qwindow, keyboard: str) -> None:
        self._module.set_keyboard(qwindow, str(keyboard))

    def rebind_output(self, qwindow) -> None:
        self._module.rebind_output(qwindow)
