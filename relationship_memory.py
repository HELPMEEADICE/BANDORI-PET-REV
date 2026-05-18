import re

from i18n_manager import tr as _tr


DEFAULT_USER_KEY = "__default__"

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

_MEMORY_PATTERNS = (
    (r"(?:请|帮我)?记住[：:，,\s]*(.{2,120})", "manual", 90, "用户希望我记住：{value}"),
    (r"(?:我叫|我的名字是|你可以叫我)[：:，,\s]*(.{1,24})", "profile", 85, "用户的称呼是：{value}"),
    (r"我的生日(?:是|在)?[：:，,\s]*(.{2,40})", "profile", 85, "用户的生日是：{value}"),
    (r"我(?:很|最|超)?喜欢[：:，,\s]*(.{1,50})", "preference", 72, "用户喜欢：{value}"),
    (r"我(?:不喜欢|讨厌)[：:，,\s]*(.{1,50})", "preference", 72, "用户不喜欢：{value}"),
    (r"我住在[：:，,\s]*(.{2,50})", "profile", 70, "用户住在：{value}"),
    (r"我是[：:，,\s]*(.{2,60})", "profile", 58, "用户自我描述：{value}"),
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
    user_name = str(config_manager.get("user_name", "") or "").strip()
    return user_name or DEFAULT_USER_KEY


def display_user_name(user_key: str) -> str:
    return "" if not user_key or user_key == DEFAULT_USER_KEY else user_key


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


def _clean_value(value: str, limit: int = 80) -> str:
    value = re.split(r"[。！？!?;\n\r]", value.strip(), 1)[0].strip(" ：:，,。. ")
    if len(value) > limit:
        value = value[:limit].rstrip() + "..."
    return value


def extract_memories(user_text: str) -> list[dict]:
    text = str(user_text or "").strip()
    memories = []
    seen = set()
    for pattern, kind, importance, template in _MEMORY_PATTERNS:
        for match in re.finditer(pattern, text):
            value = _clean_value(match.group(1))
            if not value:
                continue
            content = template.format(value=value)
            if content in seen:
                continue
            seen.add(content)
            memories.append({
                "kind": kind,
                "content": content,
                "importance": importance,
            })
    return memories[:5]


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
        "memories": extract_memories(text),
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
