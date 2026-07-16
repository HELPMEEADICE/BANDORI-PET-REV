use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct EmotionBehavior {
    pub emotion: String,
    pub intensity: i64,
    pub expression_tags: Vec<String>,
    pub motion_tags: Vec<String>,
    pub window: String,
    pub tts_rate: f64,
    pub source_actions: Vec<String>,
}

pub fn infer_emotion_behavior(text: &str, actions: &[String]) -> Option<EmotionBehavior> {
    let normalized_actions = actions
        .iter()
        .map(|action| {
            action
                .trim()
                .trim_matches(|value: char| matches!(value, '[' | ']'))
                .to_lowercase()
        })
        .filter(|action| !action.is_empty())
        .collect::<Vec<_>>();
    let emotion = emotion_from_actions(&normalized_actions).or_else(|| emotion_from_text(text))?;
    let intensity = emotion_intensity(text, &normalized_actions, emotion);
    let (expressions, motions, window, base_rate) = behavior_profile(emotion);
    Some(EmotionBehavior {
        emotion: emotion.to_owned(),
        intensity,
        expression_tags: expressions
            .iter()
            .map(|value| (*value).to_owned())
            .collect(),
        motion_tags: motions.iter().map(|value| (*value).to_owned()).collect(),
        window: window.to_owned(),
        tts_rate: scaled_tts_rate(base_rate, intensity),
        source_actions: normalized_actions,
    })
}

pub fn emotion_tts_rate(text: &str, actions: &[String]) -> f64 {
    infer_emotion_behavior(text, actions)
        .map(|behavior| behavior.tts_rate.clamp(0.75, 1.25))
        .unwrap_or(1.0)
}

fn emotion_from_actions(actions: &[String]) -> Option<&'static str> {
    actions.iter().rev().find_map(|action| {
        let base = action
            .rsplit_once('.')
            .map_or(action.as_str(), |value| value.0);
        action_emotion(action).or_else(|| action_emotion(base))
    })
}

fn action_emotion(action: &str) -> Option<&'static str> {
    Some(match action {
        "smile" | "f" | "wink" => "happy",
        "gattsu" | "jaan" | "oowarai" => "excited",
        "kandou" | "ando" => "soft",
        "sad" | "cry" => "sad",
        "angry" | "pui" => "angry",
        "kuyasii" | "sigh" => "annoyed",
        "thinking" | "nf" | "nnf" | "eeto" | "odoodo" | "mitore" => "thoughtful",
        "shame" => "shy",
        "surprised" | "scared" | "awate" => "surprised",
        "sleep" | "akubi" => "tired",
        _ => return None,
    })
}

fn emotion_from_text(text: &str) -> Option<&'static str> {
    const KEYWORDS: &[(&str, &[&str])] = &[
        ("shy", &["害羞", "脸红", "不好意思", "羞", "欸嘿", "诶嘿"]),
        ("angry", &["生气", "气死", "笨蛋", "不许", "哼", "过分"]),
        ("annoyed", &["烦", "讨厌", "真是的", "没办法", "无语"]),
        ("sad", &["难过", "伤心", "哭", "呜", "低落", "寂寞"]),
        ("hurt", &["受伤", "心痛", "委屈", "失望"]),
        (
            "concerned",
            &["担心", "没事吧", "还好吗", "小心", "注意身体"],
        ),
        (
            "surprised",
            &["惊讶", "吓", "欸", "诶", "什么", "不会吧", "真的假的"],
        ),
        ("excited", &["太棒", "超开心", "最棒", "冲呀", "好耶", "哇"]),
        (
            "happy",
            &[
                "开心", "高兴", "喜欢", "可爱", "谢谢", "真好", "太好", "加油", "嘿嘿", "哈哈",
            ],
        ),
        ("thoughtful", &["想想", "思考", "也许", "可能", "让我想"]),
        ("tired", &["困", "累", "晚安", "睡", "哈欠"]),
        ("soft", &["安心", "温柔", "没关系", "放心", "抱抱"]),
    ];
    let lowered = text.to_lowercase();
    let mut best = None;
    let mut best_score = 0;
    for (emotion, terms) in KEYWORDS {
        let score = terms
            .iter()
            .filter(|term| !term.is_empty() && lowered.contains(&term.to_lowercase()))
            .count();
        if score > best_score {
            best = Some(*emotion);
            best_score = score;
        }
    }
    best
}

fn emotion_intensity(text: &str, actions: &[String], emotion: &str) -> i64 {
    let mut intensity = if matches!(emotion, "calm" | "thoughtful" | "soft") {
        56
    } else {
        64
    };
    if !actions.is_empty() {
        intensity += 10;
    }
    if has_intense_punctuation(text) {
        intensity += 12;
    }
    if (text.contains("...") || text.contains("……"))
        && matches!(emotion, "sad" | "hurt" | "shy" | "tired")
    {
        intensity += 8;
    }
    if text.chars().count() <= 12 && matches!(emotion, "shy" | "surprised" | "angry") {
        intensity += 5;
    }
    intensity.clamp(20, 100)
}

fn has_intense_punctuation(text: &str) -> bool {
    let mut run = 0;
    for character in text.chars() {
        if matches!(character, '!' | '！' | '?' | '？') {
            run += 1;
            if run >= 2 {
                return true;
            }
        } else {
            run = 0;
        }
    }
    false
}

fn behavior_profile(
    emotion: &str,
) -> (
    &'static [&'static str],
    &'static [&'static str],
    &'static str,
    f64,
) {
    match emotion {
        "happy" => (
            &["smile", "f", "wink"],
            &["smile", "gattsu", "jaan"],
            "hop",
            1.06,
        ),
        "excited" => (
            &["smile", "surprised"],
            &["gattsu", "jaan", "smile"],
            "hop",
            1.12,
        ),
        "soft" => (
            &["smile", "default"],
            &["kandou", "ando", "smile"],
            "settle",
            0.96,
        ),
        "shy" => (
            &["shame", "smile"],
            &["shame", "odoodo", "eeto"],
            "back",
            0.92,
        ),
        "angry" => (
            &["angry", "serious"],
            &["angry", "pui", "kuyasii"],
            "forward",
            1.10,
        ),
        "annoyed" => (
            &["angry", "serious", "sad"],
            &["pui", "sigh", "angry"],
            "wobble",
            1.04,
        ),
        "sad" => (&["sad", "cry"], &["sad", "cry", "sigh"], "settle", 0.88),
        "hurt" => (&["sad", "cry"], &["sad", "cry", "sigh"], "back", 0.86),
        "concerned" => (
            &["sad", "serious", "default"],
            &["thinking", "eeto", "nf"],
            "settle",
            0.94,
        ),
        "thoughtful" => (
            &["default", "serious"],
            &["thinking", "nf", "nnf", "eeto", "odoodo"],
            "",
            0.98,
        ),
        "surprised" => (
            &["surprised", "scared"],
            &["surprised", "awate", "scared"],
            "shake",
            1.08,
        ),
        "tired" => (
            &["sleep", "sad", "default"],
            &["sleep", "akubi", "sigh"],
            "settle",
            0.84,
        ),
        _ => (&["default"], &[], "", 1.0),
    }
}

fn scaled_tts_rate(base_rate: f64, intensity: i64) -> f64 {
    let scale = ((intensity as f64) / 82.0).clamp(0.45, 1.0);
    let rate = (1.0 + (base_rate - 1.0) * scale).clamp(0.75, 1.25);
    (rate * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn action_priority_intensity_and_tts_rate_match_python_rules() {
        let behavior = infer_emotion_behavior("谢谢！！", &["smile".to_owned()]).unwrap();
        assert_eq!(behavior.emotion, "happy");
        assert_eq!(behavior.intensity, 86);
        assert_eq!(behavior.window, "hop");
        assert_eq!(behavior.tts_rate, 1.06);
        assert_eq!(behavior.motion_tags, ["smile", "gattsu", "jaan"]);
    }

    #[test]
    fn text_fallback_and_ellipsis_scaling_are_compatible() {
        let behavior = infer_emotion_behavior("不好意思……", &[]).unwrap();
        assert_eq!(behavior.emotion, "shy");
        assert_eq!(behavior.intensity, 77);
        assert_eq!(behavior.tts_rate, 0.925);
        assert!(infer_emotion_behavior("ordinary response", &[]).is_none());
        assert_eq!(emotion_tts_rate("ordinary response", &[]), 1.0);
    }

    #[test]
    fn latest_action_wins_like_the_python_action_scan() {
        let behavior = infer_emotion_behavior(
            "text also says 开心",
            &["smile".to_owned(), "cry.exp".to_owned()],
        )
        .unwrap();
        assert_eq!(behavior.emotion, "sad");
        assert_eq!(behavior.source_actions, ["smile", "cry.exp"]);
    }
}
