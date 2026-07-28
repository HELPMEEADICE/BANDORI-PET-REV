from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


HYPRLAND_POINTER_CONSENT_KEY = "wayland_hyprland_global_pointer_allowed"


class SurfaceRole(Enum):
    PET = "pet"
    RADIAL_OVERLAY = "radial_overlay"
    AI_PANEL = "ai_panel"


class StackMode(Enum):
    TOP = "top"
    GAME_OVERLAY = "game_overlay"


@dataclass(frozen=True)
class SurfacePlacement:
    output_id: str
    x: int
    y: int
    width: int
    height: int

    def moved(self, x: int, y: int) -> "SurfacePlacement":
        return SurfacePlacement(
            self.output_id,
            int(x),
            int(y),
            self.width,
            self.height,
        )

    def resized(self, width: int, height: int) -> "SurfacePlacement":
        return SurfacePlacement(
            self.output_id,
            self.x,
            self.y,
            max(1, int(width)),
            max(1, int(height)),
        )


@dataclass(frozen=True)
class PointerSample:
    x: float
    y: float
    buttons: int
    monotonic_us: int
    source: str


@dataclass(frozen=True)
class WaylandCapabilities:
    input_region: bool
    absolute_placement: bool
    global_pointer: bool
    overlay_above_fullscreen: bool
    multi_output: bool
