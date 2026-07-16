import re


OUTFIT_DESCRIPTIONS_KEY = "outfit_descriptions"
OUTFIT_RECOGNITION_ENABLED_KEY = "llm_live2d_outfit_recognition_enabled"
OUTFIT_DESCRIPTION_MAX_LENGTH = 1200


def outfit_description_key(character: str, costume: str) -> str:
    return f"{str(character or '').strip()}\t{str(costume or '').strip()}"


def clean_outfit_description(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r"```(?:\w+)?", "", text)
    text = re.sub(r"^\s*(?:服装描述|描述|当前穿着)\s*[：:]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-*#")
    return text[:OUTFIT_DESCRIPTION_MAX_LENGTH]


def normalize_outfit_descriptions(value) -> dict[str, dict]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for raw_key, raw_entry in value.items():
        if not isinstance(raw_entry, dict):
            continue
        character = str(raw_entry.get("character", "") or "").strip()
        costume = str(raw_entry.get("costume", "") or "").strip()
        description = clean_outfit_description(raw_entry.get("description", ""))
        if not str(raw_key or "").strip() or not character or not costume or not description:
            continue
        key = outfit_description_key(character, costume)
        result[key] = {
            "character": character,
            "costume": costume,
            "costume_name": str(raw_entry.get("costume_name", "") or "").strip()[:200],
            "description": description,
            "model_fingerprint": str(raw_entry.get("model_fingerprint", "") or "").strip()[:160],
            "generated_by": str(raw_entry.get("generated_by", "") or "").strip()[:20],
            "updated_at": str(raw_entry.get("updated_at", "") or "").strip()[:40],
        }
    return result
