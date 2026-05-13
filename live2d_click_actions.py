CLICK_MOTION_AUTO = ""
CLICK_MOTION_RANDOM = "__random__"
CLICK_MOTION_NONE = "__none__"

CLICK_MOTION_REGIONS = (
    "head",
    "upper_body_left",
    "upper_body_center",
    "upper_body_right",
    "lower_body_left",
    "lower_body_center",
    "lower_body_right",
)

CLICK_MOTION_SPECIAL_VALUES = {
    CLICK_MOTION_AUTO,
    CLICK_MOTION_RANDOM,
    CLICK_MOTION_NONE,
}

_AUTO_BUCKETS = {
    "head": (
        ("surprised", "shame", "pui", "smile"),
        ("kandou", "kime", "nf"),
    ),
    "upper_body_left": (
        ("nf_left", "nnf_left"),
        ("shame", "surprised", "smile"),
    ),
    "upper_body_center": (
        ("smile", "kime", "surprised", "shame"),
        ("angry", "pui", "nf"),
    ),
    "upper_body_right": (
        ("nf_right", "nnf_right"),
        ("shame", "surprised", "smile"),
    ),
    "lower_body_left": (
        ("nf_left", "nnf_left"),
        ("surprised", "sad", "smile"),
    ),
    "lower_body_center": (
        ("shame", "surprised", "angry"),
        ("smile", "kime"),
    ),
    "lower_body_right": (
        ("nf_right", "nnf_right"),
        ("surprised", "sad", "smile"),
    ),
}


def normalize_click_motion_actions(actions, valid_motions=None, valid_expressions=None) -> dict[str, dict[str, str]]:
    if not isinstance(actions, dict):
        return {}

    valid_regions = set(CLICK_MOTION_REGIONS)
    valid_motion_set = set(str(motion) for motion in valid_motions) if valid_motions is not None else None
    valid_expression_set = (
        set(str(expression) for expression in valid_expressions)
        if valid_expressions is not None
        else None
    )
    normalized = {}
    for region, raw_value in actions.items():
        region = str(region)
        if region not in valid_regions:
            continue

        if isinstance(raw_value, dict):
            motion = str(raw_value.get("motion", "") or "").strip()
            expression = str(raw_value.get("expression", "") or "").strip()
        else:
            motion = str(raw_value or "").strip()
            expression = ""

        if not motion and not expression:
            continue
        if valid_motion_set is not None and motion not in CLICK_MOTION_SPECIAL_VALUES and motion not in valid_motion_set:
            motion = ""
        if valid_expression_set is not None and expression not in valid_expression_set:
            expression = ""
        if not motion and not expression:
            continue
        normalized[region] = {
            "motion": motion,
            "expression": expression,
        }
    return normalized


def click_motion_region_for_point(
    x: float,
    y: float,
    width: int,
    height: int,
    area_name: str = "",
    area_bounds=None,
) -> str:
    width = max(1, int(width or 1))
    height = max(1, int(height or 1))
    area = str(area_name or "").strip().lower()

    if area in {"head", "face"}:
        return "head"

    if area_bounds:
        try:
            min_x, max_x, min_y, max_y = (float(v) for v in area_bounds)
            bounds_w = max_x - min_x
            bounds_h = max_y - min_y
            if bounds_w > 1 and bounds_h > 1:
                x_ratio = (float(x) - min_x) / bounds_w
                y_ratio = (float(y) - min_y) / bounds_h
            else:
                x_ratio = float(x) / width
                y_ratio = float(y) / height
        except (TypeError, ValueError):
            x_ratio = float(x) / width
            y_ratio = float(y) / height
    else:
        x_ratio = float(x) / width
        y_ratio = float(y) / height

    x_ratio = max(0.0, min(1.0, x_ratio))
    y_ratio = max(0.0, min(1.0, y_ratio))

    if area in {"", "body", "hit"} and y_ratio < 0.38:
        return "head"

    vertical = "upper_body" if y_ratio < 0.64 else "lower_body"
    if x_ratio < 0.38:
        horizontal = "left"
    elif x_ratio > 0.62:
        horizontal = "right"
    else:
        horizontal = "center"
    return f"{vertical}_{horizontal}"


def click_motion_auto_buckets(region: str):
    return _AUTO_BUCKETS.get(region, _AUTO_BUCKETS["upper_body_center"])
