from __future__ import annotations

import os
import time
import uuid
import weakref
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QRegion

from .backends import select_surface_backend
from .companion_service import WaylandCompanionService
from .environment import detect_compositor
from .native_bridge import LayerShellBridge
from .pointer import HyprlandPointerThread
from .types import PointerSample, StackMode, SurfacePlacement, SurfaceRole, WaylandCapabilities


@dataclass
class _SurfaceState:
    widget_ref: weakref.ReferenceType
    surface_id: str
    role: SurfaceRole
    placement: SurfacePlacement
    stack_mode: StackMode
    region: QRegion | None = None
    qwindow_ref: weakref.ReferenceType | None = None


def _screen_id(screen) -> str:
    if screen is None:
        return ""
    try:
        serial = str(screen.serialNumber() or "")
    except Exception:
        serial = ""
    try:
        name = str(screen.name() or "")
    except Exception:
        name = ""
    return serial or name


def _screen_for_id(output_id: str):
    screens = QGuiApplication.screens()
    if output_id:
        for screen in screens:
            if _screen_id(screen) == output_id:
                return screen
    return QGuiApplication.primaryScreen() or (screens[0] if screens else None)


class DesktopSurfaceController(QObject):
    pointer_sampled = Signal(object)
    capabilities_changed = Signal(object)
    status_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        platform = str(QGuiApplication.platformName() or "").lower()
        self.native_wayland = platform.startswith("wayland")
        self.compositor = detect_compositor() if self.native_wayland else "legacy"
        self.backend = select_surface_backend(platform, self.compositor)
        self._states: dict[int, _SurfaceState] = {}
        self._latest_pointer: PointerSample | None = None
        self._companion_version = ""
        self._bridge = LayerShellBridge() if self.compositor in {"plasma", "hyprland"} else None
        self._service = WaylandCompanionService(self) if self.native_wayland else None
        self._hypr_pointer = None
        self._status_error = ""
        self._pending_placement_keys: set[int] = set()
        self._pending_previous_outputs: dict[int, str] = {}
        self._placement_apply_timer = QTimer(self)
        self._placement_apply_timer.setSingleShot(True)
        self._placement_apply_timer.setInterval(16)
        self._placement_apply_timer.timeout.connect(self._flush_placement_updates)
        if self._service is not None:
            self._service.PointerReceived.connect(self._accept_pointer)
            self._service.GeometryReceived.connect(self._geometry_applied)
            self._service.CompanionConnected.connect(self._companion_connected)
            self._service.CompanionDisconnected.connect(
                self._companion_disconnected
            )
        if self.compositor == "hyprland":
            self._hypr_pointer = HyprlandPointerThread(self)
            self._hypr_pointer.sample.connect(self._accept_pointer)
            self._hypr_pointer.status_changed.connect(self._on_hypr_status)
            self._hypr_pointer.start()
        if self._bridge is not None and not self._bridge.status.available:
            self._status_error = self._bridge.status.reason

    def _layer_shell_available(self) -> bool:
        return bool(self._bridge is not None and self._bridge.status.available)

    def capabilities(self) -> WaylandCapabilities:
        layer_shell = self._layer_shell_available()
        companion_connected = bool(
            self._service is not None
            and self._service.registered
            and self._companion_version
        )
        global_pointer = bool(
            (
                self.compositor == "hyprland"
                and self._latest_pointer is not None
            )
            or (
                self.compositor in {"plasma", "gnome"}
                and companion_connected
            )
        )
        return self.backend.capabilities(
            layer_shell_available=layer_shell,
            companion_connected=companion_connected,
            global_pointer_available=global_pointer,
        )

    def status(self) -> dict:
        bridge_status = self._bridge.status if self._bridge is not None else None
        return {
            "native_wayland": self.native_wayland,
            "platform": str(QGuiApplication.platformName() or ""),
            "compositor": self.compositor,
            "backend": self.backend.name,
            "bridge_available": bool(bridge_status and bridge_status.available),
            "bridge_error": bridge_status.reason if bridge_status else "",
            "companion_bus": bool(self._service and self._service.registered),
            "companion_version": self._companion_version,
            "companion_error": self._service.error if self._service else "",
            "pointer_error": self._status_error,
            "capabilities": self.capabilities(),
        }

    def _default_placement(self, widget) -> SurfacePlacement:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return SurfacePlacement("", 0, 0, max(1, widget.width()), max(1, widget.height()))
        geo = screen.availableGeometry()
        width, height = max(1, widget.width()), max(1, widget.height())
        return SurfacePlacement(
            _screen_id(screen),
            geo.left() + (geo.width() - width) // 2,
            geo.top() + (geo.height() - height) // 2,
            width,
            height,
        )

    def register_surface(
        self,
        window,
        role: SurfaceRole,
        placement: SurfacePlacement | None = None,
        stack_mode: StackMode = StackMode.TOP,
    ) -> SurfacePlacement:
        key = id(window)
        existing = self._states.get(key)
        if existing is not None:
            return existing.placement
        placement = placement or self._default_placement(window)
        surface_id = uuid.uuid4().hex[:12]
        state = _SurfaceState(weakref.ref(window), surface_id, role, placement, stack_mode)
        self._states[key] = state
        if not self.native_wayland:
            window.move(placement.x, placement.y)
            return placement

        if self._service is not None:
            marker = self._service.marker(surface_id, role)
            title = str(window.windowTitle() or "BandoriPet").split(" [bandoripet:", 1)[0]
            window.setWindowTitle(f"{title} {marker}")

        if self._layer_shell_available():
            self._prepare_layer_surface(window, state)
        elif self.backend.uses_companion_geometry:
            self._announce(state)
        return placement

    def unregister_surface(self, window) -> None:
        key = id(window)
        self._pending_placement_keys.discard(key)
        self._pending_previous_outputs.pop(key, None)
        state = self._states.pop(key, None)
        if state is not None and self._service is not None:
            self._service.remove(state.surface_id)

    def _qwindow(self, window, state: _SurfaceState | None = None):
        try:
            window.winId()
            qwindow = window.windowHandle()
        except Exception:
            return None
        if qwindow is not None and state is not None:
            state.qwindow_ref = weakref.ref(qwindow)
        return qwindow

    def _prepare_layer_surface(self, window, state: _SurfaceState):
        screen = _screen_for_id(state.placement.output_id)
        qwindow = self._qwindow(window, state)
        if qwindow is None:
            self._status_error = "Qt did not create a QWindow for the surface"
            return
        if screen is not None:
            qwindow.setScreen(screen)
        keyboard = "on_demand" if state.role == SurfaceRole.AI_PANEL else "none"
        self._bridge.prepare(
            qwindow,
            x=state.placement.x - (screen.geometry().left() if screen else 0),
            y=state.placement.y - (screen.geometry().top() if screen else 0),
            width=state.placement.width,
            height=state.placement.height,
            layer="overlay" if state.stack_mode == StackMode.GAME_OVERLAY else "top",
            keyboard=keyboard,
            scope=f"bandoripet-{state.role.value}",
        )

    def _announce(self, state: _SurfaceState):
        if self._service is not None:
            self._service.announce(
                state.surface_id,
                state.role,
                state.placement,
                state.stack_mode,
            )

    def placement(self, window) -> SurfacePlacement:
        state = self._states.get(id(window))
        if state is not None:
            if not self.native_wayland:
                state.placement = SurfacePlacement(
                    _screen_id(window.screen()),
                    int(window.x()),
                    int(window.y()),
                    max(1, int(window.width())),
                    max(1, int(window.height())),
                )
            return state.placement
        return SurfacePlacement(
            _screen_id(window.screen()),
            int(window.x()),
            int(window.y()),
            max(1, int(window.width())),
            max(1, int(window.height())),
        )

    def geometry(self, window) -> QRect:
        placement = self.placement(window)
        return QRect(
            placement.x,
            placement.y,
            placement.width,
            placement.height,
        )

    def set_placement(self, window, placement: SurfacePlacement) -> None:
        state = self._states.get(id(window))
        if state is None:
            self.register_surface(window, SurfaceRole.PET, placement)
            return
        previous = state.placement
        state.placement = placement
        if not self.native_wayland:
            window.move(placement.x, placement.y)
            if window.size().width() != placement.width or window.size().height() != placement.height:
                window.resize(placement.width, placement.height)
            return
        if window.isVisible():
            key = id(window)
            self._pending_placement_keys.add(key)
            self._pending_previous_outputs.setdefault(
                key,
                previous.output_id,
            )
            if not self._placement_apply_timer.isActive():
                self._placement_apply_timer.start()
        else:
            self._apply_native_placement(
                window,
                state,
                previous_output=previous.output_id,
            )

    def _apply_native_placement(
        self,
        window,
        state: _SurfaceState,
        *,
        previous_output: str | None = None,
    ):
        placement = state.placement
        if self._layer_shell_available():
            qwindow = self._qwindow(window, state)
            if qwindow is not None:
                new_screen = _screen_for_id(placement.output_id)
                origin = new_screen.geometry().topLeft() if new_screen is not None else QPoint()
                self._bridge.set_margins(
                    qwindow,
                    placement.x - origin.x(),
                    placement.y - origin.y(),
                )
                self._bridge.set_size(qwindow, placement.width, placement.height)
                output_changed = (
                    previous_output is not None
                    and previous_output != placement.output_id
                )
                if new_screen is not None:
                    qwindow.setScreen(new_screen)
                if output_changed:
                    self._bridge.rebind_output(qwindow)
                    if state.region is not None:
                        qwindow.setMask(state.region)
        elif self.backend.uses_companion_geometry:
            self._announce(state)
        self.status_changed.emit()

    def _flush_placement_updates(self):
        keys = tuple(self._pending_placement_keys)
        self._pending_placement_keys.clear()
        for key in keys:
            previous_output = self._pending_previous_outputs.pop(key, None)
            state = self._states.get(key)
            if state is None:
                continue
            window = state.widget_ref()
            if window is None:
                continue
            self._apply_native_placement(
                window,
                state,
                previous_output=previous_output,
            )

    def move(self, window, x: int, y: int) -> None:
        current = self.placement(window)
        screen = QGuiApplication.screenAt(QPoint(int(x), int(y))) or _screen_for_id(current.output_id)
        self.set_placement(
            window,
            SurfacePlacement(
                _screen_id(screen),
                int(x),
                int(y),
                max(1, int(window.width())),
                max(1, int(window.height())),
            ),
        )

    def resize(self, window, width: int, height: int) -> None:
        current = self.placement(window)
        self.set_placement(window, current.resized(width, height))

    def move_by(self, window, dx: int, dy: int) -> tuple[int, int]:
        current = self.placement(window)
        self.move(window, current.x + int(dx), current.y + int(dy))
        updated = self.placement(window)
        return updated.x - current.x, updated.y - current.y

    def set_input_region(self, window, region: QRegion) -> bool:
        state = self._states.get(id(window))
        if state is not None and state.region == region:
            return False
        qwindow = self._qwindow(window, state)
        if qwindow is None:
            return False
        qwindow.setMask(region)
        if state is not None:
            state.region = QRegion(region)
        return True

    def set_stack_mode(self, window, mode: StackMode) -> None:
        state = self._states.get(id(window))
        if state is None or state.stack_mode == mode:
            return
        state.stack_mode = mode
        if self._layer_shell_available():
            qwindow = self._qwindow(window, state)
            if qwindow is not None:
                self._bridge.set_layer(
                    qwindow,
                    "overlay" if mode == StackMode.GAME_OVERLAY else "top",
                )
        elif self.backend.uses_companion_geometry:
            self._announce(state)
        self.status_changed.emit()

    def begin_drag(self, window, local_position: QPoint) -> bool:
        del local_position
        if not self.native_wayland or self.capabilities().absolute_placement:
            return False
        qwindow = self._qwindow(window)
        return bool(qwindow is not None and qwindow.startSystemMove())

    def global_from_local(self, window, local_position: QPoint) -> QPoint:
        placement = self.placement(window)
        return QPoint(placement.x + local_position.x(), placement.y + local_position.y())

    def latest_pointer(self, *, max_age_ms: int = 250) -> PointerSample | None:
        sample = self._latest_pointer
        if sample is None:
            return None
        age_us = time.monotonic_ns() // 1000 - sample.monotonic_us
        if age_us < 0:
            return sample
        return sample if age_us <= max(0, int(max_age_ms)) * 1000 else None

    def set_pointer_tracking_active(self, active: bool):
        if self._hypr_pointer is not None:
            self._hypr_pointer.set_active(bool(active))

    def _accept_pointer(self, sample: PointerSample):
        first_sample = self._latest_pointer is None
        self._latest_pointer = sample
        self.pointer_sampled.emit(sample)
        if first_sample:
            self.capabilities_changed.emit(self.capabilities())
            self.status_changed.emit()

    def _companion_connected(self, version: str):
        self._companion_version = str(version)
        for state in self._states.values():
            self._announce(state)
        self.capabilities_changed.emit(self.capabilities())
        self.status_changed.emit()

    def _companion_disconnected(self):
        if not self._companion_version:
            return
        self._companion_version = ""
        self.capabilities_changed.emit(self.capabilities())
        self.status_changed.emit()

    def _geometry_applied(self, surface_id: str, placement: SurfacePlacement):
        for state in self._states.values():
            if state.surface_id == surface_id:
                state.placement = placement
                self.status_changed.emit()
                return

    def _on_hypr_status(self, ok: bool, message: str):
        self._status_error = "" if ok else str(message)
        self.status_changed.emit()

    def close(self):
        self._placement_apply_timer.stop()
        self._pending_placement_keys.clear()
        self._pending_previous_outputs.clear()
        if self._service is not None:
            for state in tuple(self._states.values()):
                self._service.remove(state.surface_id)
        self._states.clear()
        if self._hypr_pointer is not None:
            self._hypr_pointer.stop()
            self._hypr_pointer = None
        if self._service is not None:
            self._service.close()
            self._service = None


def create_surface_controller(parent=None) -> DesktopSurfaceController:
    return DesktopSurfaceController(parent)
