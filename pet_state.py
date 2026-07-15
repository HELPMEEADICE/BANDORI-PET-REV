import json


def persist_pet_window_state(config, line: str) -> bool:
    try:
        state = json.loads(str(line).split("\t", 1)[1])
    except (json.JSONDecodeError, IndexError):
        return False
    if not isinstance(state, dict):
        return False
    character = str(state.get("character", "") or "").strip()
    model_path = str(state.get("model_path", "") or "").strip()
    if not character:
        return False
    try:
        x = max(-2_147_483_648, min(int(state.get("x", -1)), 2_147_483_647))
        y = max(-2_147_483_648, min(int(state.get("y", -1)), 2_147_483_647))
        width = max(1, min(int(state.get("width", 400)), 16_384))
        height = max(1, min(int(state.get("height", 500)), 16_384))
    except (TypeError, ValueError):
        return False
    placement = state.get("placement", {})
    if not isinstance(placement, dict):
        placement = {}
    window_fields = {
        "window_x": x,
        "window_y": y,
        "window_width": width,
        "window_height": height,
        "window_placement": placement,
    }
    config.load()
    models = config.get("models", [])
    model_count = len(models) if isinstance(models, list) else 0
    updated_models = list(models) if isinstance(models, list) else []
    matching_index = next((
        index
        for index, item in enumerate(updated_models)
        if isinstance(item, dict)
        and item.get("character") == character
        and model_path
        and str(item.get("path", "") or "") == model_path
    ), None)
    if matching_index is None:
        matching_index = next((
            index
            for index, item in enumerate(updated_models)
            if isinstance(item, dict) and item.get("character") == character
        ), None)
    if matching_index is not None:
        entry = dict(updated_models[matching_index])
        entry.update(window_fields)
        updated_models[matching_index] = entry
        config.set("models", updated_models)
    if model_count <= 1:
        for key, value in window_fields.items():
            config.set(key, value)
    if matching_index is None and model_count > 1:
        return False
    config.save()
    return True
