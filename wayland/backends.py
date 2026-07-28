from __future__ import annotations

from .types import WaylandCapabilities


class SurfaceBackend:
    name = "base"
    native_wayland = True
    uses_layer_shell = False
    uses_companion_geometry = False

    def capabilities(
        self,
        *,
        layer_shell_available: bool = False,
        companion_connected: bool = False,
        global_pointer_available: bool = False,
    ) -> WaylandCapabilities:
        del layer_shell_available, companion_connected, global_pointer_available
        return WaylandCapabilities(True, False, False, False, False)


class LegacySurfaceBackend(SurfaceBackend):
    name = "legacy"
    native_wayland = False

    def capabilities(self, **_state) -> WaylandCapabilities:
        return WaylandCapabilities(True, True, True, True, True)


class LayerShellWaylandBackend(SurfaceBackend):
    name = "layer-shell"
    uses_layer_shell = True

    def capabilities(
        self,
        *,
        layer_shell_available: bool = False,
        companion_connected: bool = False,
        global_pointer_available: bool = False,
    ) -> WaylandCapabilities:
        del companion_connected
        layer_shell_available = bool(layer_shell_available)
        return WaylandCapabilities(
            input_region=True,
            absolute_placement=layer_shell_available,
            global_pointer=bool(global_pointer_available),
            overlay_above_fullscreen=layer_shell_available,
            multi_output=layer_shell_available,
        )


class GnomeWaylandBackend(SurfaceBackend):
    name = "gnome-shell"
    uses_companion_geometry = True

    def capabilities(
        self,
        *,
        layer_shell_available: bool = False,
        companion_connected: bool = False,
        global_pointer_available: bool = False,
    ) -> WaylandCapabilities:
        del layer_shell_available
        companion_connected = bool(companion_connected)
        return WaylandCapabilities(
            input_region=True,
            absolute_placement=companion_connected,
            global_pointer=bool(
                companion_connected and global_pointer_available
            ),
            overlay_above_fullscreen=companion_connected,
            multi_output=companion_connected,
        )


class GenericWaylandBackend(SurfaceBackend):
    name = "generic-wayland"


def select_surface_backend(
    platform_name: str,
    compositor: str,
) -> SurfaceBackend:
    if not str(platform_name or "").lower().startswith("wayland"):
        return LegacySurfaceBackend()
    if compositor in {"plasma", "hyprland"}:
        return LayerShellWaylandBackend()
    if compositor == "gnome":
        return GnomeWaylandBackend()
    return GenericWaylandBackend()
