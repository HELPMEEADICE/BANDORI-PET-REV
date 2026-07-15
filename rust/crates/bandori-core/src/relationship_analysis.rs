use crate::database::{Database, DatabaseError, RelationshipDelta, RelationshipState};
use serde::{Deserialize, Serialize};

#[cfg(test)]
const PROMPT_CONTRACT_JSON: &str = include_str!("../../../compat/chat_prompt_vectors.json");

const POSITIVE_TERMS: &[&str] = &[
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
];
const STRONG_AFFECTION_TERMS: &[&str] = &["喜欢你", "爱你", "最喜欢你", "想你", "抱抱"];
const THANKS_TERMS: &[&str] = &["谢谢", "感谢", "辛苦了", "帮大忙"];
const DISTRESS_TERMS: &[&str] = &[
    "难过",
    "伤心",
    "痛苦",
    "害怕",
    "焦虑",
    "压力",
    "好累",
    "累死",
    "孤独",
    "失眠",
    "不开心",
];
const NEGATIVE_DIRECT_TERMS: &[&str] = &[
    "讨厌你",
    "烦死你",
    "闭嘴",
    "滚",
    "笨蛋",
    "没用",
    "失望",
    "生气了",
];
const APOLOGY_TERMS: &[&str] = &["对不起", "抱歉", "不好意思", "我错了"];

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct InteractionAnalysis {
    pub affection_delta: i64,
    pub trust_delta: i64,
    pub familiarity_delta: i64,
    pub mood: String,
    pub mood_intensity: i64,
    pub reason: String,
}

pub fn analyze_interaction(user_text: &str, actions: &[String]) -> InteractionAnalysis {
    let mut affection_delta = 0;
    let mut trust_delta = 0;
    let familiarity_delta = i64::from(!user_text.trim().is_empty());
    let mut mood = mood_from_actions(actions).to_owned();
    let mut mood_intensity = None;
    let mut reasons = Vec::new();

    if contains_any(user_text, STRONG_AFFECTION_TERMS) {
        affection_delta += 5;
        trust_delta += 2;
        if mood.is_empty() {
            mood = "shy".to_owned();
        }
        mood_intensity = Some(70);
        reasons.push("用户表达了亲近感");
    } else if contains_any(user_text, POSITIVE_TERMS) {
        affection_delta += 2;
        trust_delta += 1;
        if mood.is_empty() {
            mood = "happy".to_owned();
        }
        mood_intensity = Some(55);
        reasons.push("用户语气积极");
    }
    if contains_any(user_text, THANKS_TERMS) {
        affection_delta += 1;
        trust_delta += 2;
        if mood.is_empty() {
            mood = "soft".to_owned();
        }
        mood_intensity = Some(mood_intensity.unwrap_or_default().max(45));
        reasons.push("用户表达感谢");
    }
    if contains_any(user_text, DISTRESS_TERMS) {
        trust_delta += 1;
        mood = "concerned".to_owned();
        mood_intensity = Some(65);
        reasons.push("用户表达了压力或低落");
    }
    if contains_any(user_text, NEGATIVE_DIRECT_TERMS) {
        affection_delta -= 5;
        trust_delta -= 3;
        mood = "hurt".to_owned();
        mood_intensity = Some(70);
        reasons.push("用户语气伤人");
    }
    if contains_any(user_text, APOLOGY_TERMS) {
        affection_delta += 1;
        trust_delta += 2;
        if matches!(mood.as_str(), "hurt" | "annoyed" | "angry" | "") {
            mood = "soft".to_owned();
        }
        mood_intensity = Some(mood_intensity.unwrap_or_default().max(45));
        reasons.push("用户表达歉意");
    }
    if mood.is_empty() {
        mood = "calm".to_owned();
    }
    InteractionAnalysis {
        affection_delta,
        trust_delta,
        familiarity_delta,
        mood,
        mood_intensity: mood_intensity.unwrap_or(if reasons.is_empty() { 24 } else { 35 }),
        reason: if reasons.is_empty() {
            "普通互动".to_owned()
        } else {
            reasons.join("；")
        },
    }
}

pub fn apply_interaction_analysis(
    database: &Database,
    character: &str,
    user_key: &str,
    user_text: &str,
    actions: &[String],
    event_type: &str,
) -> Result<RelationshipState, DatabaseError> {
    let analysis = analyze_interaction(user_text, actions);
    database.apply_relationship_delta(
        character,
        user_key,
        &RelationshipDelta {
            affection: analysis.affection_delta,
            trust: analysis.trust_delta,
            familiarity: analysis.familiarity_delta,
            mood: &analysis.mood,
            mood_intensity: Some(analysis.mood_intensity),
            event_type,
            reason: &analysis.reason,
        },
    )
}

fn contains_any(text: &str, terms: &[&str]) -> bool {
    terms.iter().any(|term| text.contains(term))
}

fn mood_from_actions(actions: &[String]) -> &'static str {
    for action in actions.iter().rev() {
        let key = action.trim().trim_matches(['[', ']']).to_ascii_lowercase();
        let mood = match key.as_str() {
            "smile" | "wink" => "happy",
            "gattsu" | "jaan" => "excited",
            "kandou" => "soft",
            "sad" | "cry" => "sad",
            "angry" | "pui" => "annoyed",
            "thinking" | "nf" | "nnf" | "eeto" | "odoodo" => "thoughtful",
            "shame" => "shy",
            "surprised" | "scared" => "surprised",
            "sleep" => "tired",
            _ => continue,
        };
        return mood;
    }
    ""
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Deserialize)]
    struct Vectors {
        interaction_cases: Vec<InteractionCase>,
    }

    #[derive(Deserialize)]
    struct InteractionCase {
        user_text: String,
        actions: Vec<String>,
        expected: ExpectedAnalysis,
    }

    #[derive(Deserialize)]
    struct ExpectedAnalysis {
        affection_delta: i64,
        trust_delta: i64,
        familiarity_delta: i64,
        mood: String,
        mood_intensity: i64,
        reason: String,
    }

    #[test]
    fn generated_python_interaction_vectors_match_rust() {
        let vectors: Vectors = serde_json::from_str(PROMPT_CONTRACT_JSON).unwrap();
        for case in vectors.interaction_cases {
            let actual = analyze_interaction(&case.user_text, &case.actions);
            assert_eq!(actual.affection_delta, case.expected.affection_delta);
            assert_eq!(actual.trust_delta, case.expected.trust_delta);
            assert_eq!(actual.familiarity_delta, case.expected.familiarity_delta);
            assert_eq!(actual.mood, case.expected.mood);
            assert_eq!(actual.mood_intensity, case.expected.mood_intensity);
            assert_eq!(actual.reason, case.expected.reason);
        }
    }

    #[test]
    fn interaction_analysis_updates_the_compatible_database_state() {
        let directory = tempfile::tempdir().unwrap();
        let database = Database::open(directory.path().join("data.db")).unwrap();
        let state = apply_interaction_analysis(
            &database,
            "ran",
            "alice",
            "谢谢你",
            &["smile".to_owned()],
            "chat",
        )
        .unwrap();
        assert_eq!(
            (state.affection, state.trust, state.familiarity),
            (53, 53, 1)
        );
        assert_eq!((state.mood.as_str(), state.mood_intensity), ("happy", 55));
    }
}
