LIVE2D_QUALITY_PROFILES = {
    "performance": {"disable_precision": True},
    "balanced": {"disable_precision": True},
    "quality": {"disable_precision": True},
    "ultra": {"disable_precision": True},
}


def normalize_live2d_quality(profile: str) -> str:
    return profile if profile in LIVE2D_QUALITY_PROFILES else "balanced"
