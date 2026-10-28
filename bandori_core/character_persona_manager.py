from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any


CHARACTER_PERSONA_PRESETS_KEY = "character_persona_presets"
CHARACTER_PERSONA_ACTIVE_KEY = "character_persona_active"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_persona_id() -> str:
    return uuid.uuid4().hex


def normalize_character_persona_presets(value: Any) -> dict[str, list[dict]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[dict]] = {}
    for character, raw_presets in value.items():
        char_key = str(character or "").strip()
        if not char_key or not isinstance(raw_presets, list):
            continue
        presets = []
        seen_ids = set()
        for item in raw_presets:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt", "") or "").strip()
            if not prompt:
                continue
            preset_id = str(item.get("id", "") or "").strip() or new_persona_id()
            if preset_id in seen_ids:
                preset_id = new_persona_id()
            title = str(item.get("title", "") or "").strip() or persona_title_from_prompt(prompt)
            created_at = str(item.get("created_at", "") or "").strip() or now_iso()
            updated_at = str(item.get("updated_at", "") or "").strip() or created_at
            presets.append({
                "id": preset_id,
                "title": title,
                "prompt": prompt,
                "created_at": created_at,
                "updated_at": updated_at,
            })
            seen_ids.add(preset_id)
        if presets:
            result[char_key] = presets
    return result


def normalize_character_persona_active(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(character or "").strip(): str(preset_id or "").strip()
        for character, preset_id in value.items()
        if str(character or "").strip()
    }


def persona_title_from_prompt(prompt: str) -> str:
    title = next((line.strip("# \t") for line in prompt.splitlines() if line.strip()), "")
    if len(title) > 32:
        title = title[:32] + "..."
    return title or "Persona"


def active_character_persona_prompt(config_manager, character: str) -> str:
    if not config_manager or not character:
        return ""
    presets_by_character = normalize_character_persona_presets(
        config_manager.get(CHARACTER_PERSONA_PRESETS_KEY, {})
    )
    active_by_character = normalize_character_persona_active(
        config_manager.get(CHARACTER_PERSONA_ACTIVE_KEY, {})
    )
    active_id = active_by_character.get(character, "")
    if not active_id:
        return ""
    for preset in presets_by_character.get(character, []):
        if preset.get("id") == active_id:
            return str(preset.get("prompt", "") or "").strip()
    return ""
