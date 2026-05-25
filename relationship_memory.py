import json
import re

from i18n_manager import tr as _tr


DEFAULT_USER_KEY = "__default__"
ROLE_USER_KEY_PREFIX = "__role__:"

MOOD_LABELS = {
    "calm": "平静",
    "happy": "开心",
    "excited": "兴奋",
    "soft": "柔和",
    "concerned": "担心",
    "sad": "低落",
    "hurt": "受伤",
    "annoyed": "有点生气",
    "angry": "生气",
    "shy": "害羞",
    "thoughtful": "思考中",
    "surprised": "惊讶",
    "tired": "疲惫",
}

_MOOD_INTENSITY_MAP = [
    (10, "angry"),
    (25, "annoyed"),
    (35, "hurt"),
    (45, "sad"),
    (55, "concerned"),
    (65, "tired"),
    (75, "calm"),
    (85, "thoughtful"),
    (92, "soft"),
    (97, "shy"),
    (99, "happy"),
    (100, "excited"),
]

MEMORY_KIND_LABELS = {
    "manual": "手动记忆",
    "profile": "用户信息",
    "preference": "偏好",
    "relationship": "关系",
    "note": "记录",
}

MEMORY_EXTRACTOR_SYSTEM_PROMPT = (
    "You are a multilingual interaction analysis component for a role-play chat app. "
    "Read the latest user message and the assistant reply. Extract durable facts that the character "
    "should remember about the user or the user's relationship with the character, and estimate a small "
    "relationship-state update. Understand any language, including "
    "Simplified Chinese, Traditional Chinese, English, Japanese, Korean, and mixed-language messages. "
    "Do not extract temporary requests, one-off topics, greetings, assistant facts, role instructions, "
    "or anything merely implied. Prefer user profile facts, stable preferences, boundaries, recurring "
    "habits, relationship notes, and explicit requests to remember durable information. "
    "Write memory content in concise Chinese so it fits the existing UI. "
    "Return only valid JSON with this exact shape: "
    "{\"relationship\":{\"affection_delta\":0,\"trust_delta\":0,\"familiarity_delta\":1,"
    "\"mood\":\"calm\",\"mood_intensity\":24,\"reason\":\"...\"},"
    "\"memories\":[{\"kind\":\"profile|preference|relationship|note\",\"content\":\"...\","
    "\"importance\":1-100}]}. "
    "Use small relationship deltas from -5 to 5. familiarity_delta is usually 1 when the user sent a "
    "substantive message, otherwise 0. mood must be one of calm, happy, excited, soft, concerned, sad, "
    "hurt, annoyed, angry, shy, thoughtful, surprised, tired. If there is nothing worth saving, use an "
    "empty memories array."
)

_POSITIVE_TERMS = (
    "谢谢",
    "感谢",
    "辛苦了",
    "喜欢你",
    "爱你",
    "想你",
    "可爱",
    "真好",
    "好棒",
    "厉害",
    "开心",
    "高兴",
    "抱抱",
)
_STRONG_AFFECTION_TERMS = ("喜欢你", "爱你", "最喜欢你", "想你", "抱抱")
_THANKS_TERMS = ("谢谢", "感谢", "辛苦了", "帮大忙")
_DISTRESS_TERMS = ("难过", "伤心", "痛苦", "害怕", "焦虑", "压力", "好累", "累死", "孤独", "失眠", "不开心")
_NEGATIVE_DIRECT_TERMS = ("讨厌你", "烦死你", "闭嘴", "滚", "笨蛋", "没用", "失望", "生气了")
_APOLOGY_TERMS = ("对不起", "抱歉", "不好意思", "我错了")

_ACTION_MOOD = {
    "smile": "happy",
    "gattsu": "excited",
    "jaan": "excited",
    "wink": "happy",
    "kandou": "soft",
    "sad": "sad",
    "cry": "sad",
    "angry": "annoyed",
    "pui": "annoyed",
    "thinking": "thoughtful",
    "nf": "thoughtful",
    "nnf": "thoughtful",
    "eeto": "thoughtful",
    "odoodo": "thoughtful",
    "shame": "shy",
    "surprised": "surprised",
    "scared": "surprised",
    "sleep": "tired",
}


def user_key_from_config(config_manager) -> str:
    if not config_manager:
        return DEFAULT_USER_KEY
    pov_mode = str(config_manager.get("pov_mode", "off") or "off")
    if pov_mode == "role":
        role_character = str(config_manager.get("pov_role_character", "") or "").strip()
        if role_character:
            return ROLE_USER_KEY_PREFIX + role_character
    user_name = str(config_manager.get("user_name", "") or "").strip()
    return user_name or DEFAULT_USER_KEY


def role_character_from_user_key(user_key: str) -> str:
    key = str(user_key or "")
    if key.startswith(ROLE_USER_KEY_PREFIX):
        return key[len(ROLE_USER_KEY_PREFIX):]
    return ""


def display_user_name(user_key: str) -> str:
    if not user_key or user_key == DEFAULT_USER_KEY:
        return ""
    role_character = role_character_from_user_key(user_key)
    if role_character:
        return _tr("Relationship.role_user_display", "皮上角色：{role}", role=role_character)
    return user_key


def mood_label(mood: str) -> str:
    if not mood:
        return _tr("Relationship.mood_calm", "平静")
    key = str(mood).strip()
    return _tr(f"Relationship.mood_{key}", MOOD_LABELS.get(key, key))


def mood_from_intensity(value: int) -> str:
    value = max(0, min(100, value))
    for threshold, mood_key in _MOOD_INTENSITY_MAP:
        if value <= threshold:
            return mood_key
    return "calm"


def affection_label(value: int) -> str:
    if value >= 85:
        return _tr("Relationship.affection_very_close", "非常亲近")
    if value >= 70:
        return _tr("Relationship.affection_close", "亲近")
    if value >= 55:
        return _tr("Relationship.affection_familiar", "熟悉")
    if value >= 40:
        return _tr("Relationship.affection_normal", "普通")
    if value >= 25:
        return _tr("Relationship.affection_distant", "疏离")
    return _tr("Relationship.affection_tense", "紧张")


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _trim_text(value: str, limit: int = 180) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" ：:，,。. ")
    if len(value) > limit:
        value = value[:limit].rstrip() + "..."
    return value


def build_memory_extraction_messages(
    user_text: str,
    assistant_text: str = "",
    existing_memories: list[dict] | None = None,
) -> list[dict]:
    existing_lines = []
    for memory in (existing_memories or [])[:12]:
        content = _trim_text(memory.get("content", ""), 160)
        if content:
            existing_lines.append("- " + content)
    existing_text = "\n".join(existing_lines) or "无"
    user_payload = (
        "现有长期记忆：\n"
        + existing_text
        + "\n\n用户最新消息：\n"
        + str(user_text or "").strip()
    )
    assistant_text = str(assistant_text or "").strip()
    if assistant_text:
        user_payload += "\n\n助手刚才的回复（仅用于判断语境，不要抽取助手事实）：\n" + assistant_text[:1200]
    return [
        {"role": "system", "content": MEMORY_EXTRACTOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_payload},
    ]


def _json_object_from_text(text: str) -> dict:
    source = str(text or "").strip()
    if not source:
        return {}
    try:
        data = json.loads(source)
    except (TypeError, ValueError):
        match = re.search(r"\{.*\}", source, flags=re.S)
        if match:
            try:
                data = json.loads(match.group(0))
            except (TypeError, ValueError):
                data = {}
        else:
            data = {}
    return data if isinstance(data, dict) else {}


def parse_relationship_analysis_response(text: str) -> dict:
    data = _json_object_from_text(text)
    if "relationship" not in data:
        return {}
    relationship = data.get("relationship", {})
    if not isinstance(relationship, dict):
        return {}
    mood = str(relationship.get("mood", "") or "").strip()
    if mood not in MOOD_LABELS:
        mood = "calm"

    def bounded_int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(relationship.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    return {
        "affection_delta": bounded_int("affection_delta", 0, -5, 5),
        "trust_delta": bounded_int("trust_delta", 0, -5, 5),
        "familiarity_delta": bounded_int("familiarity_delta", 1, 0, 3),
        "mood": mood,
        "mood_intensity": bounded_int("mood_intensity", 24, 0, 100),
        "reason": _trim_text(relationship.get("reason", "模型互动分析"), 100) or "模型互动分析",
    }


def parse_memory_extraction_response(text: str) -> list[dict]:
    data = _json_object_from_text(text)

    memories = []
    seen = set()
    for item in data.get("memories", []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "note") or "note").strip()
        if kind not in MEMORY_KIND_LABELS:
            kind = "note"
        content = _trim_text(item.get("content", ""), 180)
        if len(content) < 3 or content in seen:
            continue
        seen.add(content)
        try:
            importance = int(item.get("importance", 60))
        except (TypeError, ValueError):
            importance = 60
        memories.append({
            "kind": kind,
            "content": content,
            "importance": max(1, min(100, importance)),
        })
        if len(memories) >= 5:
            break
    return memories


def _mood_from_actions(actions: list[str]) -> str:
    for action in reversed(actions or []):
        key = str(action or "").strip().lower().strip("[]")
        if key in _ACTION_MOOD:
            return _ACTION_MOOD[key]
    return ""


def analyze_interaction(user_text: str, assistant_text: str = "", actions: list[str] | None = None) -> dict:
    del assistant_text
    text = str(user_text or "")
    affection_delta = 0
    trust_delta = 0
    familiarity_delta = 1 if text.strip() else 0
    mood = _mood_from_actions(actions or [])
    mood_intensity = None
    reasons = []

    if _contains_any(text, _STRONG_AFFECTION_TERMS):
        affection_delta += 5
        trust_delta += 2
        mood = "shy" if not mood else mood
        mood_intensity = 70
        reasons.append("用户表达了亲近感")
    elif _contains_any(text, _POSITIVE_TERMS):
        affection_delta += 2
        trust_delta += 1
        mood = "happy" if not mood else mood
        mood_intensity = 55
        reasons.append("用户语气积极")

    if _contains_any(text, _THANKS_TERMS):
        affection_delta += 1
        trust_delta += 2
        mood = "soft" if not mood else mood
        mood_intensity = max(mood_intensity or 0, 45) or None
        reasons.append("用户表达感谢")

    if _contains_any(text, _DISTRESS_TERMS):
        trust_delta += 1
        mood = "concerned"
        mood_intensity = 65
        reasons.append("用户表达了压力或低落")

    if _contains_any(text, _NEGATIVE_DIRECT_TERMS):
        affection_delta -= 5
        trust_delta -= 3
        mood = "hurt"
        mood_intensity = 70
        reasons.append("用户语气伤人")

    if _contains_any(text, _APOLOGY_TERMS):
        affection_delta += 1
        trust_delta += 2
        mood = "soft" if mood in {"hurt", "annoyed", "angry", ""} else mood
        mood_intensity = max(mood_intensity or 0, 45) or None
        reasons.append("用户表达歉意")

    if not mood:
        mood = "calm"
    if mood_intensity is None:
        mood_intensity = 35 if reasons else 24

    return {
        "affection_delta": affection_delta,
        "trust_delta": trust_delta,
        "familiarity_delta": familiarity_delta,
        "mood": mood,
        "mood_intensity": mood_intensity,
        "reason": "；".join(reasons) or "普通互动",
        "memories": [],
    }


def build_relationship_context(db, character: str, user_key: str, display_name: str = "") -> str:
    state = db.get_relationship_state(character, user_key)
    memories = db.get_character_memories(character, user_key, limit=8)
    user_label = display_name or display_user_name(user_key) or _tr("Relationship.default_user", "当前用户")
    lines = [
        _tr("Relationship.context_title", "【长期记忆与关系状态】"),
        _tr("Relationship.context_instruction", "这些内容是程序保存的长期互动状态。把它当作背景，只在自然相关时使用，不要主动逐条复述。"),
        _tr("Relationship.context_object", "互动对象：{user_label}", user_label=user_label),
        _tr("Relationship.context_relationship",
            "关系：好感度 {affection}/100（{affection_label}），信任 {trust}/100，熟悉度 {familiarity}/100。",
            affection=state['affection'], affection_label=affection_label(state['affection']),
            trust=state['trust'], familiarity=state['familiarity']),
        _tr("Relationship.context_mood", "当前心情：{mood}，强度 {intensity}/100。",
            mood=mood_label(state['mood']), intensity=state['mood_intensity']),
    ]
    if memories:
        lines.append(_tr("Relationship.context_memories_label", "长期记忆："))
        for memory in memories:
            kind = _tr(f"Relationship.kind_{memory['kind']}", MEMORY_KIND_LABELS.get(memory["kind"], memory["kind"]))
            lines.append(f"- {kind}：{memory['content']}")
    else:
        lines.append(_tr("Relationship.context_memories_empty", "长期记忆：暂无明确记录。"))
    lines.append(_tr("Relationship.context_instruction_footer", "互动要求：随着好感、信任和心情变化调整语气亲近度，但仍必须保持角色本人的性格边界。"))
    return "\n".join(lines)


def format_character_status(db, character: str, user_key: str, display_name: str = "", limit: int = 6) -> str:
    state = db.get_relationship_state(character, user_key)
    memories = db.get_character_memories(character, user_key, limit=limit)
    title = display_name or character
    lines = [
        _tr("Relationship.status_title", "【{title} 的长期状态】", title=title),
        _tr("SettingsWindow.memory_affection_value", "{value}/100（{label}）",
            value=state['affection'], label=affection_label(state['affection'])),
        _tr("Relationship.status_trust", "信任：{value}/100", value=state['trust']),
        _tr("Relationship.status_familiarity", "熟悉度：{value}/100", value=state['familiarity']),
        _tr("SettingsWindow.memory_mood_value", "{mood}（{value}/100）",
            mood=mood_label(state['mood']), value=state['mood_intensity']),
    ]
    if memories:
        lines.append(_tr("Relationship.status_memories_label", "记住的事："))
        for memory in memories:
            kind = _tr(f"Relationship.kind_{memory['kind']}", MEMORY_KIND_LABELS.get(memory["kind"], memory["kind"]))
            lines.append(f"- {kind}：{memory['content']}")
    else:
        lines.append(_tr("Relationship.status_memories_empty", "记住的事：暂无。"))
    return "\n".join(lines)
