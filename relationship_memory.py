import json
import re

from i18n_manager import tr as _tr
from config_manager import DEFAULT_USER_PROFILE_KEY


DEFAULT_USER_KEY = DEFAULT_USER_PROFILE_KEY
ROLE_USER_KEY_PREFIX = "__role__:"

# Reserved "character" key for cross-character (global) user-profile memories.
# These memories describe the user themselves and apply to every character the
# user talks to, so they are stored under this sentinel character key and merged
# into every character's context.
GLOBAL_MEMORY_CHARACTER = "__global__"

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
    "You are the long-term memory and relationship analyzer for a role-play desktop companion app. "
    "Every turn you read the user's latest message (the character's reply is given only as context) and "
    "decide what is worth remembering for the long term, then estimate a small relationship-state update. "
    "You understand every language (Simplified/Traditional Chinese, English, Japanese, Korean, and "
    "mixed-language text) and always write the saved memory content in concise Chinese so it fits the UI.\n"
    "\n"
    "WHAT TO REMEMBER — save a memory whenever the user reveals durable information, even when it is stated "
    "briefly, casually, or in passing. Do NOT ignore a clear memory point just because the message is short "
    "or informal:\n"
    "- Identity & profile: the name or nickname they want to be called, age range, location/timezone, "
    "job or studies, languages they use.\n"
    "- Stable preferences & dislikes: foods, hobbies, games, music, favorite BanG Dream! bands/characters, "
    "topics they enjoy or want avoided, the tone or way they like to be spoken to and addressed.\n"
    "- Boundaries & sensitivities: things that upset them, subjects not to bring up, emotional support they need.\n"
    "- Lasting life facts & ongoing situations: family, pets, partner, health constraints, recurring "
    "schedule, exams/projects or goals they are working toward.\n"
    "- Relationship-specific facts about THIS character: nicknames they use for the character, inside jokes, "
    "promises, shared plans or recurring rituals with this character.\n"
    "- Anything the user explicitly asks you to remember.\n"
    "\n"
    "WHAT TO SKIP: one-off or momentary things (today's weather, what they are doing right now, a single "
    "question, a passing mood), pure task requests already handled in the reply (translate this, write code, "
    "look something up), greetings and filler, facts about the character/assistant, role-play stage "
    "directions, and anything you would only be guessing at — never invent facts the user did not state.\n"
    "Quick test: if a thoughtful friend would still find it useful to know next week, remember it; otherwise skip it.\n"
    "\n"
    "SCOPE every memory:\n"
    "- \"user\": true about the person no matter which character they talk to (identity, global preferences, "
    "boundaries, life facts). These build a shared cross-character user profile.\n"
    "- \"relationship\": only meaningful for the current character (nicknames for this character, shared "
    "memories, promises made to it).\n"
    "\n"
    "AVOID DUPLICATES & MAINTAIN THE PROFILE: you are shown the memories already saved. Never repeat a fact "
    "that is already stored. If a new statement corrects or replaces an old fact (the user moved, changed a "
    "favorite, updated how they want to be called), put the corrected fact in \"memories\" AND copy the "
    "outdated existing line verbatim into \"outdated\" so it gets removed.\n"
    "\n"
    "Return ONLY valid JSON with this exact shape:\n"
    "{\"relationship\":{\"affection_delta\":0,\"trust_delta\":0,\"familiarity_delta\":1,\"mood\":\"calm\","
    "\"mood_intensity\":24,\"reason\":\"...\"},"
    "\"memories\":[{\"scope\":\"user|relationship\",\"kind\":\"profile|preference|relationship|note\","
    "\"content\":\"...\",\"importance\":1-100}],"
    "\"outdated\":[\"<verbatim existing memory line to delete>\"]}.\n"
    "Relationship deltas range -5..5. familiarity_delta is 1 for a substantive user message, otherwise 0. "
    "mood must be one of calm, happy, excited, soft, concerned, sad, hurt, annoyed, angry, shy, thoughtful, "
    "surprised, tired. importance: 80-100 for core identity/boundaries, 55-79 for stable preferences and "
    "relationship facts, 30-54 for minor notes. If nothing is worth saving use \"memories\":[] and \"outdated\":[].\n"
    "\n"
    "Examples (saved content is illustrative):\n"
    "User: \"以后叫我小K就好，我不太喜欢别人喊全名\" -> memories:[{\"scope\":\"user\",\"kind\":\"preference\","
    "\"content\":\"希望被称呼为“小K”，不喜欢被叫全名\",\"importance\":85}].\n"
    "User: \"今天好累，刚加完班\" -> memories:[] (momentary state, nothing durable).\n"
    "User: \"我最喜欢的乐队是MyGO，尤其是灯\" -> memories:[{\"scope\":\"user\",\"kind\":\"preference\","
    "\"content\":\"最喜欢的乐队是MyGO，最喜欢的角色是高松灯\",\"importance\":80}].\n"
    "User: \"我们之前说好周末一起看演唱会直播对吧\" -> memories:[{\"scope\":\"relationship\","
    "\"kind\":\"relationship\",\"content\":\"和用户约好周末一起看演唱会直播\",\"importance\":70}]."
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
    active_profile = str(config_manager.get("active_user_profile", "") or "").strip()
    profiles = config_manager.get("user_profiles", [])
    if active_profile and isinstance(profiles, list):
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            key = str(profile.get("key", "") or "").strip()
            if key == active_profile:
                return key or DEFAULT_USER_KEY
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


def _format_memory_lines(memories: list[dict] | None, limit: int = 12) -> str:
    lines = []
    for memory in (memories or [])[:limit]:
        # Keep the content verbatim (it is already short) so the model can copy a
        # line into "outdated" for an exact match when a fact is superseded.
        content = re.sub(r"\s+", " ", str(memory.get("content", "") or "")).strip()
        if content:
            lines.append("- " + content)
    return "\n".join(lines) or "（无）"


def build_memory_extraction_messages(
    user_text: str,
    assistant_text: str = "",
    existing_memories: list[dict] | None = None,
    *,
    global_memories: list[dict] | None = None,
    character_name: str = "",
) -> list[dict]:
    user_payload = (
        "当前角色：" + (str(character_name or "").strip() or "（未指定）") + "\n\n"
        + "已保存的用户档案（跨角色，scope=user）：\n"
        + _format_memory_lines(global_memories)
        + "\n\n已保存的与当前角色相关的记忆（scope=relationship）：\n"
        + _format_memory_lines(existing_memories)
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


def _scope_for(scope: str, kind: str) -> str:
    value = str(scope or "").strip().lower()
    if value in ("user", "global", "profile", "shared"):
        return "user"
    if value in ("relationship", "character", "local", "char"):
        return "relationship"
    # Derive from the memory kind when the model did not give an explicit scope.
    return "user" if kind in ("profile", "preference") else "relationship"


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
            "scope": _scope_for(item.get("scope", ""), kind),
            "kind": kind,
            "content": content,
            "importance": max(1, min(100, importance)),
        })
        if len(memories) >= 6:
            break
    return memories


def _normalize_memory_match_key(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip().lower()


def parse_memory_supersede_response(text: str) -> list[str]:
    """Existing memory contents the model flagged as outdated/replaced."""
    data = _json_object_from_text(text)
    raw = data.get("outdated")
    if raw is None:
        raw = data.get("superseded") or data.get("remove") or []
    results = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            item = item.get("content", "")
        content = re.sub(r"\s+", " ", str(item or "")).strip()
        key = _normalize_memory_match_key(content)
        if len(content) < 3 or key in seen:
            continue
        seen.add(key)
        results.append(content)
        if len(results) >= 6:
            break
    return results


def store_extracted_memories(
    db,
    character: str,
    user_key: str,
    response_text: str,
    *,
    source_message_id: int | None = None,
    source_group_message_id: int | None = None,
) -> None:
    """Persist memories from an extractor response, routing by scope and
    removing any existing lines the model marked as outdated."""
    memories = parse_memory_extraction_response(response_text)
    outdated = parse_memory_supersede_response(response_text)

    if outdated:
        # Match the model's verbatim lines against stored memories in both the
        # current character's scope and the shared global profile, then delete.
        index: dict[str, tuple[int, str]] = {}
        for owner in (character, GLOBAL_MEMORY_CHARACTER):
            for existing in db.get_character_memories(owner, user_key, limit=100):
                key = _normalize_memory_match_key(existing.get("content", ""))
                if key and key not in index:
                    index[key] = (existing.get("id", 0), owner)
        for line in outdated:
            hit = index.get(_normalize_memory_match_key(line))
            if hit and hit[0]:
                db.delete_character_memory(hit[0], hit[1], user_key)

    for memory in memories:
        owner = GLOBAL_MEMORY_CHARACTER if memory["scope"] == "user" else character
        db.add_character_memory(
            owner,
            user_key,
            memory["kind"],
            memory["content"],
            memory["importance"],
            source_message_id=source_message_id,
            source_group_message_id=source_group_message_id,
        )


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
    global_memories = db.get_character_memories(GLOBAL_MEMORY_CHARACTER, user_key, limit=8)
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
    if global_memories:
        lines.append(_tr("Relationship.context_global_label",
                         "用户档案（跨角色长期偏好，对每位角色都适用）："))
        for memory in global_memories:
            kind = _tr(f"Relationship.kind_{memory['kind']}", MEMORY_KIND_LABELS.get(memory["kind"], memory["kind"]))
            lines.append(f"- {kind}：{memory['content']}")
    if memories:
        lines.append(_tr("Relationship.context_memories_label", "长期记忆："))
        for memory in memories:
            kind = _tr(f"Relationship.kind_{memory['kind']}", MEMORY_KIND_LABELS.get(memory["kind"], memory["kind"]))
            lines.append(f"- {kind}：{memory['content']}")
    elif not global_memories:
        lines.append(_tr("Relationship.context_memories_empty", "长期记忆：暂无明确记录。"))
    lines.append(_tr("Relationship.context_instruction_footer", "互动要求：随着好感、信任和心情变化调整语气亲近度，但仍必须保持角色本人的性格边界。"))
    return "\n".join(lines)


def _format_memory_block(memories: list[dict], empty_text: str) -> list[str]:
    if not memories:
        return [empty_text]
    block = []
    for memory in memories:
        kind = _tr(f"Relationship.kind_{memory['kind']}", MEMORY_KIND_LABELS.get(memory["kind"], memory["kind"]))
        block.append(f"- {kind}：{memory['content']}")
    return block


def format_character_status(
    db,
    character: str,
    user_key: str,
    display_name: str = "",
    limit: int = 6,
    sections: tuple[str, ...] | None = None,
) -> str:
    """Render the long-term status. ``sections`` selects which blocks to show:
    ``"state"`` (relationship stats), ``"global"`` (cross-character preferences),
    ``"memories"`` (this character's memories). Defaults to all three."""
    sections = tuple(sections) if sections else ("state", "global", "memories")
    title = display_name or character
    empty_text = _tr("Relationship.status_block_empty", "（暂无）")

    lines = [_tr("Relationship.status_title", "【{title} 的长期状态】", title=title)]

    # Block 1 — relationship stats (this character).
    if "state" in sections:
        state = db.get_relationship_state(character, user_key)
        lines.append("")
        lines.append(_tr("Relationship.status_section_state", "── 关系数值 ──"))
        lines.append(_tr("Relationship.status_affection", "好感度：{value}/100（{label}）",
                         value=state['affection'], label=affection_label(state['affection'])))
        lines.append(_tr("Relationship.status_trust", "信任：{value}/100", value=state['trust']))
        lines.append(_tr("Relationship.status_familiarity", "熟悉度：{value}/100", value=state['familiarity']))
        lines.append(_tr("Relationship.status_mood", "当前心情：{mood}（{value}/100）",
                         mood=mood_label(state['mood']), value=state['mood_intensity']))

    # Block 2 — global user preferences (shared across every character).
    if "global" in sections:
        global_memories = db.get_character_memories(GLOBAL_MEMORY_CHARACTER, user_key, limit=limit)
        lines.append("")
        lines.append(_tr("Relationship.status_global_label", "── 全局用户偏好（对所有角色生效）──"))
        lines.extend(_format_memory_block(global_memories, empty_text))

    # Block 3 — memories specific to this character.
    if "memories" in sections:
        memories = db.get_character_memories(character, user_key, limit=limit)
        lines.append("")
        lines.append(_tr("Relationship.status_memories_label", "── 角色专属记忆 ──"))
        lines.extend(_format_memory_block(memories, empty_text))

    return "\n".join(lines)
