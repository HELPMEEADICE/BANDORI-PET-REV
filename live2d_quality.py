from typing import Any

from PySide6.QtWidgets import QApplication


LIVE2D_SCALE_MIN = 25
LIVE2D_SCALE_MAX = 500

LIVE2D_QUALITY_PROFILES = {
    "performance": {
        "texture_scale": 0.5,
        "use_mipmap": False,
        "bleed_passes": 0,
    },
    "balanced": {
        "texture_scale": 1.0,
        "use_mipmap": True,
        "bleed_passes": 1,
    },
}


def normalize_live2d_quality(profile: str) -> str:
    return profile if profile in LIVE2D_QUALITY_PROFILES else "balanced"


def clamp_live2d_scale(value: Any, default: int = 100, use_device_pixel_ratio_default: bool = False) -> int:
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        pct = 0 if use_device_pixel_ratio_default else default
    if pct <= 0:
        if use_device_pixel_ratio_default:
            screen = QApplication.primaryScreen()
            ratio = screen.devicePixelRatio() if screen else 1.0
            pct = int(round(ratio * 100))
        else:
            pct = default
    return max(LIVE2D_SCALE_MIN, min(LIVE2D_SCALE_MAX, pct))
