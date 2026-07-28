from __future__ import annotations

import os
import time
import uuid

from PySide6.QtCore import QObject, Signal, Slot

from .types import PointerSample, StackMode, SurfacePlacement, SurfaceRole


DBUS_INTERFACE = "io.github.bandoripet.PetWayland1"
DBUS_PATH = "/io/github/bandoripet/PetWayland1"
DBUS_SERVICE_PREFIX = "io.github.bandoripet.PetWayland.p"


class WaylandCompanionService(QObject):
    PointerReceived = Signal(object)
    GeometryReceived = Signal(str, object)
    CompanionConnected = Signal(str)
    CompanionDisconnected = Signal()
    SurfaceUpsert = Signal(str, str, str, int, int, int, int, str, str)
    SurfaceRemoved = Signal(str, str)
    SurfaceCommand = Signal(str, str, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.token = uuid.uuid4().hex
        self.service_name = f"{DBUS_SERVICE_PREFIX}{os.getpid()}"
        self._connection = None
        self._registered = False
        self.error = ""
        self._register()

    @property
    def registered(self) -> bool:
        return self._registered

    def _register(self):
        try:
            from PySide6.QtDBus import QDBusConnection

            connection = QDBusConnection.sessionBus()
            if not connection.isConnected():
                self.error = connection.lastError().message()
                return
            if not connection.registerService(self.service_name):
                self.error = connection.lastError().message()
                return
            flags = (
                QDBusConnection.RegisterOption.ExportAllSlots
                | QDBusConnection.RegisterOption.ExportAllSignals
            )
            if not connection.registerObject(DBUS_PATH, self, flags):
                self.error = connection.lastError().message()
                connection.unregisterService(self.service_name)
                return
            self._connection = connection
            self._registered = True
        except Exception as exc:
            self.error = str(exc)

    @Slot(float, float, int, int, str, result=bool)
    def PushPointer(self, x: float, y: float, buttons: int, monotonic_ms: int, token: str) -> bool:
        if str(token) != self.token:
            return False
        del monotonic_ms
        self.PointerReceived.emit(
            PointerSample(
                float(x),
                float(y),
                int(buttons),
                time.monotonic_ns() // 1000,
                "compositor-companion",
            )
        )
        return True

    @Slot(str, str, result=bool)
    def CompanionReady(self, version: str, token: str) -> bool:
        if str(token) != self.token:
            return False
        self.CompanionConnected.emit(str(version))
        return True

    @Slot(str, result=bool)
    def CompanionGone(self, token: str) -> bool:
        if str(token) != self.token:
            return False
        self.CompanionDisconnected.emit()
        return True

    @Slot(str, str, int, int, int, int, str, result=bool)
    def GeometryApplied(
        self,
        surface_id: str,
        output_id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        token: str,
    ) -> bool:
        if str(token) != self.token:
            return False
        self.GeometryReceived.emit(
            str(surface_id),
            SurfacePlacement(
                str(output_id),
                int(x),
                int(y),
                max(1, int(width)),
                max(1, int(height)),
            ),
        )
        return True

    def announce(
        self,
        surface_id: str,
        role: SurfaceRole,
        placement: SurfacePlacement,
        stack_mode: StackMode,
    ) -> None:
        if not self._registered:
            return
        self.SurfaceUpsert.emit(
            str(surface_id),
            role.value,
            placement.output_id,
            placement.x,
            placement.y,
            placement.width,
            placement.height,
            stack_mode.value,
            self.token,
        )

    def remove(self, surface_id: str) -> None:
        if self._registered:
            self.SurfaceRemoved.emit(str(surface_id), self.token)

    def command(self, surface_id: str, command: str, payload: str = "") -> None:
        if self._registered:
            self.SurfaceCommand.emit(
                str(surface_id),
                str(command),
                str(payload),
                self.token,
            )

    def marker(self, surface_id: str, role: SurfaceRole) -> str:
        return (
            "[bandoripet:"
            f"p{os.getpid()}:{self.token}:{surface_id}:{role.value}"
            "]"
        )

    def close(self):
        if self._connection is not None:
            self._connection.unregisterObject(DBUS_PATH)
            self._connection.unregisterService(self.service_name)
        self._connection = None
        self._registered = False
