SCREEN_AWARENESS_MIN_INTERVAL_MINUTES = 5
SCREEN_AWARENESS_MAX_INTERVAL_MINUTES = 120
SCREEN_AWARENESS_MODEL_MODE_MAIN = "main"
SCREEN_AWARENESS_MODEL_MODE_AUX = "aux"


def clamp_screen_awareness_interval(value) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError, OverflowError):
        minutes = 30
    return max(
        SCREEN_AWARENESS_MIN_INTERVAL_MINUTES,
        min(SCREEN_AWARENESS_MAX_INTERVAL_MINUTES, minutes),
    )


def clamp_screen_awareness_screenshot_width(value) -> int:
    try:
        width = int(value)
    except (TypeError, ValueError, OverflowError):
        width = 1920
    return max(640, min(1920, width))


def normalize_screen_awareness_model_mode(value) -> str:
    mode = str(value or SCREEN_AWARENESS_MODEL_MODE_MAIN).strip().lower()
    if mode == SCREEN_AWARENESS_MODEL_MODE_AUX:
        return SCREEN_AWARENESS_MODEL_MODE_AUX
    return SCREEN_AWARENESS_MODEL_MODE_MAIN
