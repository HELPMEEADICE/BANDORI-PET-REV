"""Native Wayland integration for BandoriPet.

The package deliberately keeps environment detection importable without Qt so
entry points can select the Wayland QPA plugin before importing PySide6.
"""

from .environment import (
    WaylandStartupError,
    configure_native_wayland,
    detect_compositor,
    is_wayland_session,
    verify_native_wayland_qpa,
)
from .backends import (
    GenericWaylandBackend,
    GnomeWaylandBackend,
    LayerShellWaylandBackend,
    LegacySurfaceBackend,
    select_surface_backend,
)
from .types import (
    HYPRLAND_POINTER_CONSENT_KEY,
    PointerSample,
    StackMode,
    SurfacePlacement,
    SurfaceRole,
    WaylandCapabilities,
)

__all__ = [
    "HYPRLAND_POINTER_CONSENT_KEY",
    "PointerSample",
    "GenericWaylandBackend",
    "GnomeWaylandBackend",
    "LayerShellWaylandBackend",
    "LegacySurfaceBackend",
    "StackMode",
    "SurfacePlacement",
    "SurfaceRole",
    "WaylandCapabilities",
    "WaylandStartupError",
    "configure_native_wayland",
    "detect_compositor",
    "is_wayland_session",
    "select_surface_backend",
    "verify_native_wayland_qpa",
]
