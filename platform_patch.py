_LIVE2D_TEXTURE_QUALITY = "balanced"


def set_live2d_texture_quality(profile: str):
    global _LIVE2D_TEXTURE_QUALITY
    if profile in {"performance", "balanced", "quality", "ultra"}:
        _LIVE2D_TEXTURE_QUALITY = profile
    else:
        _LIVE2D_TEXTURE_QUALITY = "balanced"
