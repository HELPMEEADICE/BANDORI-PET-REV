import re


EMOTION_MOODS = {
    "calm",
    "happy",
    "excited",
    "soft",
    "concerned",
    "sad",
    "hurt",
    "annoyed",
    "angry",
    "shy",
    "thoughtful",
    "surprised",
    "tired",
}

ACTION_EMOTION = {
    "smile": "happy",
    "f": "happy",
    "wink": "happy",
    "gattsu": "excited",
    "jaan": "excited",
    "oowarai": "excited",
    "kandou": "soft",
    "ando": "soft",
    "sad": "sad",
    "cry": "sad",
    "angry": "angry",
    "pui": "angry",
    "kuyasii": "annoyed",
    "sigh": "annoyed",
    "thinking": "thoughtful",
    "nf": "thoughtful",
    "nnf": "thoughtful",
    "eeto": "thoughtful",
    "odoodo": "thoughtful",
    "mitore": "thoughtful",
    "shame": "shy",
    "surprised": "surprised",
    "scared": "surprised",
    "awate": "surprised",
    "sleep": "tired",
    "akubi": "tired",
}

EMOTION_BEHAVIOR = {
    "happy": {
        "expressions": ("smile", "f", "wink"),
        "motions": ("smile", "gattsu", "jaan"),
        "window": "hop",
        "tts_rate": 1.06,
    },
    "excited": {
        "expressions": ("smile", "surprised"),
        "motions": ("gattsu", "jaan", "smile"),
        "window": "hop",
        "tts_rate": 1.12,
    },
    "soft": {
        "expressions": ("smile", "default"),
        "motions": ("kandou", "ando", "smile"),
        "window": "settle",
        "tts_rate": 0.96,
    },
    "shy": {
        "expressions": ("shame", "smile"),
        "motions": ("shame", "odoodo", "eeto"),
        "window": "back",
        "tts_rate": 0.92,
    },
    "angry": {
        "expressions": ("angry", "serious"),
        "motions": ("angry", "pui", "kuyasii"),
        "window": "forward",
        "tts_rate": 1.10,
    },
    "annoyed": {
        "expressions": ("angry", "serious", "sad"),
        "motions": ("pui", "sigh", "angry"),
        "window": "wobble",
        "tts_rate": 1.04,
    },
    "sad": {
        "expressions": ("sad", "cry"),
        "motions": ("sad", "cry", "sigh"),
        "window": "settle",
        "tts_rate": 0.88,
    },
    "hurt": {
        "expressions": ("sad", "cry"),
        "motions": ("sad", "cry", "sigh"),
        "window": "back",
        "tts_rate": 0.86,
    },
    "concerned": {
        "expressions": ("sad", "serious", "default"),
        "motions": ("thinking", "eeto", "nf"),
        "window": "settle",
        "tts_rate": 0.94,
    },
    "thoughtful": {
        "expressions": ("default", "serious"),
        "motions": ("thinking", "nf", "nnf", "eeto", "odoodo"),
        "window": "",
        "tts_rate": 0.98,
    },
    "surprised": {
        "expressions": ("surprised", "scared"),
        "motions": ("surprised", "awate", "scared"),
        "window": "shake",
        "tts_rate": 1.08,
    },
    "tired": {
        "expressions": ("sleep", "sad", "default"),
        "motions": ("sleep", "akubi", "sigh"),
        "window": "settle",
        "tts_rate": 0.84,
    },
    "calm": {
        "expressions": ("default",),
        "motions": (),
        "window": "",
        "tts_rate": 1.0,
    },
}

_EMOTION_KEYWORDS = (
    ("shy", ("害羞", "脸红", "不好意思", "羞", "欸嘿", "诶嘿")),
    ("angry", ("生气", "气死", "笨蛋", "不许", "哼", "过分")),
    ("annoyed", ("烦", "讨厌", "真是的", "没办法", "无语")),
    ("sad", ("难过", "伤心", "哭", "呜", "低落", "寂寞")),
    ("hurt", ("受伤", "心痛", "委屈", "失望")),
    ("concerned", ("担心", "没事吧", "还好吗", "小心", "注意身体")),
    ("surprised", ("惊讶", "吓", "欸", "诶", "什么", "不会吧", "真的假的")),
    ("excited", ("太棒", "超开心", "最棒", "冲呀", "好耶", "哇")),
    ("happy", ("开心", "高兴", "喜欢", "可爱", "谢谢", "真好", "太好", "加油", "嘿嘿", "哈哈")),
    ("thoughtful", ("想想", "思考", "也许", "可能", "让我想")),
    ("tired", ("困", "累", "晚安", "睡", "哈欠")),
    ("soft", ("安心", "温柔", "没关系", "放心", "抱抱")),
)

_INTENSE_PUNCT_RE = re.compile(r"[!！?？]{2,}")


def infer_emotion_behavior(text: str, actions: list[str] | None = None) -> dict:
    text = str(text or "")
    normalized_actions = [
        str(action or "").strip().lower().strip("[]")
        for action in (actions or [])
        if str(action or "").strip()
    ]
    emotion = _emotion_from_actions(normalized_actions) or _emotion_from_text(text)
    if not emotion:
        return {}

    intensity = _emotion_intensity(text, normalized_actions, emotion)
    base = EMOTION_BEHAVIOR.get(emotion, EMOTION_BEHAVIOR["calm"])
    return {
        "emotion": emotion,
        "intensity": intensity,
        "expression_tags": list(base.get("expressions", ())),
        "motion_tags": list(base.get("motions", ())),
        "window": base.get("window", ""),
        "tts_rate": _scaled_tts_rate(float(base.get("tts_rate", 1.0)), intensity),
        "source_actions": normalized_actions,
    }


def emotion_tts_rate(text: str, actions: list[str] | None = None) -> float:
    behavior = infer_emotion_behavior(text, actions)
    try:
        return max(0.75, min(1.25, float(behavior.get("tts_rate", 1.0))))
    except (TypeError, ValueError):
        return 1.0


def _emotion_from_actions(actions: list[str]) -> str:
    for action in reversed(actions):
        if action in ACTION_EMOTION:
            return ACTION_EMOTION[action]
        base = action.rsplit(".", 1)[0]
        if base in ACTION_EMOTION:
            return ACTION_EMOTION[base]
    return ""


def _emotion_from_text(text: str) -> str:
    lowered = text.lower()
    best_emotion = ""
    best_score = 0
    for emotion, terms in _EMOTION_KEYWORDS:
        score = sum(1 for term in terms if term and term.lower() in lowered)
        if score > best_score:
            best_emotion = emotion
            best_score = score
    return best_emotion


def _emotion_intensity(text: str, actions: list[str], emotion: str) -> int:
    intensity = 56 if emotion in {"calm", "thoughtful", "soft"} else 64
    if actions:
        intensity += 10
    if _INTENSE_PUNCT_RE.search(text):
        intensity += 12
    if any(mark in text for mark in ("...", "……")) and emotion in {"sad", "hurt", "shy", "tired"}:
        intensity += 8
    if len(text) <= 12 and emotion in {"shy", "surprised", "angry"}:
        intensity += 5
    return max(20, min(100, intensity))


def _scaled_tts_rate(base_rate: float, intensity: int) -> float:
    delta = base_rate - 1.0
    scale = max(0.45, min(1.0, intensity / 82.0))
    return round(max(0.75, min(1.25, 1.0 + delta * scale)), 3)
