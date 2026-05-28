import re
import random

from live2d_click_actions import CLICK_MOTION_REGIONS, CLICK_MOTION_AUTO

BUILTIN_CLICK_MOTION_PROFILES = [
    {
        "name": "auto",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_auto",
        "is_builtin": True,
        "tags": {},
    },
    {
        "name": "genki",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_genki",
        "is_builtin": True,
        "tags": {
            "head": "smile",
            "upper_body_left": "nf_left",
            "upper_body_center": "smile",
            "upper_body_right": "nf_right",
            "lower_body_left": "smile",
            "lower_body_center": "kime",
            "lower_body_right": "smile",
        },
    },
    {
        "name": "tsundere",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_tsundere",
        "is_builtin": True,
        "tags": {
            "head": "shame",
            "upper_body_left": "pui",
            "upper_body_center": "angry",
            "upper_body_right": "pui",
            "lower_body_left": "shame",
            "lower_body_center": "angry",
            "lower_body_right": "serious",
        },
    },
    {
        "name": "shy",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_shy",
        "is_builtin": True,
        "tags": {
            "head": "shame",
            "upper_body_left": "nnf_left",
            "upper_body_center": "shame",
            "upper_body_right": "nnf_right",
            "lower_body_left": "sad",
            "lower_body_center": "shame",
            "lower_body_right": "sad",
        },
    },
    {
        "name": "cool",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_cool",
        "is_builtin": True,
        "tags": {
            "head": "serious",
            "upper_body_left": "kime",
            "upper_body_center": "serious",
            "upper_body_right": "kime",
            "lower_body_left": "serious",
            "lower_body_center": "kime",
            "lower_body_right": "serious",
        },
    },
    {
        "name": "surprised",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_surprised",
        "is_builtin": True,
        "tags": {
            "head": "surprised",
            "upper_body_left": "surprised",
            "upper_body_center": "surprised",
            "upper_body_right": "surprised",
            "lower_body_left": "surprised",
            "lower_body_center": "surprised",
            "lower_body_right": "surprised",
        },
    },
    {
        "name": "random",
        "i18n_key": "SettingsWindow.click_motion_profile_preset_random",
        "is_builtin": True,
        "tags": {"__mode__": "random"},
    },
]

BUILTIN_PROFILE_NAMES = {p["name"] for p in BUILTIN_CLICK_MOTION_PROFILES}


def resolve_motion_by_tag(tag: str, motion_names: list[str], char_name: str = "") -> str:
    tag_low = tag.lower()
    char_lower = (char_name or "").lower()
    candidates = [tag_low]
    if tag_low == "thinking":
        candidates.extend(["nf", "nnf", "eeto", "odoodo"])

    matches = []
    for candidate in candidates:
        candidate_prefix = f"{char_lower}_{candidate}" if char_lower else candidate
        for motion_name in motion_names:
            motion_low = str(motion_name).lower()
            if motion_low == candidate or motion_low.startswith(candidate):
                matches.append(str(motion_name))
            elif motion_low == candidate_prefix or motion_low.startswith(candidate_prefix):
                matches.append(str(motion_name))
            elif re.search(rf"(^|[_\-]){re.escape(candidate)}($|[_\-]?\d)", motion_low):
                matches.append(str(motion_name))
    return random.choice(matches) if matches else ""


_EXPRESSION_TAG_MAP = {
    "surprised": ["surprised"],
    "shame": ["shame"],
    "smile": ["smile"],
    "angry": ["angry"],
    "sad": ["sad", "cry"],
    "serious": ["serious"],
    "kime": ["kime"],
    "pui": ["pui"],
    "nf": ["smile", "idle"],
    "nf_left": ["smile", "idle"],
    "nf_right": ["smile", "idle"],
    "nnf": ["smile", "idle"],
    "nnf_left": ["smile", "idle"],
    "nnf_right": ["smile", "idle"],
    "kandou": ["surprised", "kime"],
    "cry": ["cry", "sad"],
    "idle": ["idle", "default"],
    "scared": ["surprised"],
    "thinking": ["serious", "idle"],
    "stare": ["serious", "kime"],
    "bye": ["smile", "idle"],
    "odoodo": ["shame", "serious"],
    "wink": ["smile"],
    "nod": ["smile", "idle"],
}


def resolve_expression_by_tag(tag: str, expression_names: list[str], char_name: str = "") -> str:
    tag_low = tag.lower()
    char_lower = (char_name or "").lower()
    target_tags = _EXPRESSION_TAG_MAP.get(tag_low, [tag_low])

    for expr_tag in target_tags:
        candidates = [expr_tag]
        if expr_tag == "default":
            candidates.append("idle")
        for candidate in candidates:
            candidate_prefix = f"{char_lower}_{candidate}" if char_lower else candidate
            for expr_name in expression_names:
                expr_low = str(expr_name).lower()
                if expr_low == candidate or expr_low.startswith(candidate):
                    return str(expr_name)
                elif expr_low == candidate_prefix or expr_low.startswith(candidate_prefix):
                    return str(expr_name)
                elif re.search(rf"(^|[_\-]){re.escape(candidate)}($|[_\-]?\d)", expr_low):
                    return str(expr_name)

    for fallback_tag in ("default", "idle", "smile"):
        for expr_name in expression_names:
            expr_low = str(expr_name).lower()
            if fallback_tag in expr_low:
                return str(expr_name)

    return expression_names[0] if expression_names else ""


def resolve_preset_to_actions(
    preset: dict,
    motion_names: list[str],
    expression_names: list[str],
    char_name: str = "",
) -> dict[str, dict[str, str]]:
    tags = preset.get("tags", {})

    if tags.get("__mode__") == "random":
        return {
            region: {"motion": "__random__", "expression": ""}
            for region in CLICK_MOTION_REGIONS
        }

    if not tags:
        return {
            region: {"motion": CLICK_MOTION_AUTO, "expression": ""}
            for region in CLICK_MOTION_REGIONS
        }

    actions = {}
    for region in CLICK_MOTION_REGIONS:
        tag = tags.get(region, "")
        if not tag:
            actions[region] = {"motion": CLICK_MOTION_AUTO, "expression": ""}
            continue

        motion = resolve_motion_by_tag(tag, motion_names, char_name)
        expression = resolve_expression_by_tag(tag, expression_names, char_name)
        actions[region] = {
            "motion": motion or CLICK_MOTION_AUTO,
            "expression": expression,
        }

    return actions


def normalize_click_motion_profile(profile) -> dict | None:
    if not isinstance(profile, dict):
        return None
    name = str(profile.get("name", "")).strip()
    if not name:
        return None
    actions = {}
    raw_actions = profile.get("click_motion_actions", {})
    if isinstance(raw_actions, dict):
        for region in CLICK_MOTION_REGIONS:
            if region in raw_actions and isinstance(raw_actions[region], dict):
                motion = str(raw_actions[region].get("motion", "")).strip()
                expression = str(raw_actions[region].get("expression", "")).strip()
                if motion or expression:
                    actions[region] = {
                        "motion": motion,
                        "expression": expression,
                    }
    return {
        "name": name,
        "click_motion_actions": actions,
    }


_PRESET_DISPLAY_DEFAULTS = {
    "auto": ("自动选择", "系统根据点击区域自动匹配合适的动作"),
    "genki": ("元气开朗", "充满活力的笑脸与积极反应"),
    "tsundere": ("傲娇", "嘴上不饶人但内心害羞的经典傲娇反应"),
    "shy": ("害羞内向", "容易害羞、轻微社恐的可爱反应"),
    "cool": ("冷静理智", "沉着冷静的认真反应"),
    "surprised": ("惊讶意外", "对各种触碰都感到惊讶的反应"),
    "random": ("随机", "每次点击随机播放动作"),
}


def preset_display_name(preset: dict, tr_func=None) -> str:
    i18n_key = preset.get("i18n_key", "")
    if tr_func and i18n_key:
        return tr_func(i18n_key)
    name = preset["name"]
    return _PRESET_DISPLAY_DEFAULTS.get(name, (name, ""))[0]


def preset_description(preset: dict, tr_func=None) -> str:
    i18n_key = preset.get("i18n_key", "")
    desc_key = f"{i18n_key}_desc" if i18n_key else ""
    if tr_func and desc_key:
        return tr_func(desc_key)
    name = preset["name"]
    return _PRESET_DISPLAY_DEFAULTS.get(name, ("", ""))[1]


def preset_combo_label(preset: dict, tr_func=None) -> str:
    name = preset_display_name(preset, tr_func)
    return f"[{name}]"
