//! Tag → motion/expression name matching (spec §2.6, extracted verbatim in
//! `BANDORI-PET-REV-behavior-spec.md` §3).
//!
//! Motion resolution keeps the original three-branch `elif` chain, the extra
//! candidates for the `thinking` tag, and uniform random choice over the candidate
//! pool. Expression resolution is deterministic: first match wins, with the
//! `default → idle → smile → expression_names[0]` fallback chain.

use pet_config::{preset, ClickAction, ClickProfile, ClickRegion, PresetMode, CLICK_REGIONS};
use pet_util::Rng;

/// Tag → expression candidate tags (24 entries, verbatim from
/// `_EXPRESSION_TAG_MAP`).
pub fn expression_candidates(tag: &str) -> Vec<&str> {
    let list: &[&str] = match tag.to_ascii_lowercase().as_str() {
        "surprised" => &["surprised"],
        "shame" => &["shame"],
        "smile" => &["smile"],
        "angry" => &["angry"],
        "sad" => &["sad", "cry"],
        "serious" => &["serious"],
        "kime" => &["kime"],
        "pui" => &["pui"],
        "nf" | "nf_left" | "nf_right" | "nnf" | "nnf_left" | "nnf_right" => &["smile", "idle"],
        "kandou" => &["surprised", "kime"],
        "cry" => &["cry", "sad"],
        "idle" => &["idle", "default"],
        "scared" => &["surprised"],
        "thinking" => &["serious", "idle"],
        "stare" => &["serious", "kime"],
        "bye" => &["smile", "idle"],
        "odoodo" => &["shame", "serious"],
        "wink" => &["smile"],
        "nod" => &["smile", "idle"],
        _ => return vec![],
    };
    list.to_vec()
}

/// Two-tier automatic buckets per region (`_AUTO_BUCKETS`).
pub fn auto_buckets(region: ClickRegion) -> (&'static [&'static str], &'static [&'static str]) {
    match region {
        ClickRegion::Head => (
            &["surprised", "shame", "pui", "smile"],
            &["kandou", "kime", "nf"],
        ),
        ClickRegion::UpperBodyLeft | ClickRegion::LowerBodyLeft => {
            (&["nf_left", "nnf_left"], &["shame", "surprised", "smile"])
        }
        ClickRegion::UpperBodyRight | ClickRegion::LowerBodyRight => {
            (&["nf_right", "nnf_right"], &["shame", "surprised", "smile"])
        }
        ClickRegion::UpperBodyCenter => (
            &["smile", "kime", "surprised", "shame"],
            &["angry", "pui", "nf"],
        ),
        ClickRegion::LowerBodyCenter => (&["shame", "surprised", "angry"], &["smile", "kime"]),
    }
}

/// `(^|[_\-])tag($|[_\-]?\d)` tested against an already lower-cased name.
///
/// Implemented without a regex engine: the pattern only needs a boundary before
/// the tag and "end, digit, or separator+digit" after it.
pub fn boundary_match(name: &str, tag: &str) -> bool {
    if tag.is_empty() || name.len() < tag.len() {
        return false;
    }
    let bytes = name.as_bytes();
    let mut search_from = 0usize;
    while let Some(found) = name[search_from..].find(tag) {
        let start = search_from + found;
        let end = start + tag.len();
        let before_ok = start == 0 || matches!(bytes.get(start - 1), Some(b'_') | Some(b'-'));
        let rest = &bytes[end..];
        let after_ok = match rest.first() {
            None => true,
            Some(byte) if byte.is_ascii_digit() => true,
            Some(b'_') | Some(b'-') => rest.get(1).is_some_and(u8::is_ascii_digit),
            Some(_) => false,
        };
        if before_ok && after_ok {
            return true;
        }
        search_from = start + 1;
        if search_from >= name.len() {
            break;
        }
    }
    false
}

fn matches_tag(name_lower: &str, candidate: &str, candidate_prefix: &str) -> bool {
    if name_lower == candidate || name_lower.starts_with(candidate) {
        return true;
    }
    if name_lower == candidate_prefix || name_lower.starts_with(candidate_prefix) {
        return true;
    }
    boundary_match(name_lower, candidate)
}

/// Resolves a motion tag to a concrete motion name.
///
/// Returns an empty string when nothing matches (callers treat `""` as AUTO).
pub fn resolve_motion_by_tag(
    tag: &str,
    motion_names: &[String],
    char_name: &str,
    rng: &mut Rng,
) -> String {
    let tag_low = tag.to_ascii_lowercase();
    if tag_low.is_empty() {
        return String::new();
    }
    let char_lower = char_name.to_ascii_lowercase();
    let mut candidates = vec![tag_low.clone()];
    if tag_low == "thinking" {
        candidates.extend(["nf", "nnf", "eeto", "odoodo"].map(str::to_owned));
    }

    let mut matches: Vec<&String> = Vec::new();
    for candidate in &candidates {
        let candidate_prefix = if char_lower.is_empty() {
            candidate.clone()
        } else {
            format!("{char_lower}_{candidate}")
        };
        for name in motion_names {
            let name_lower = name.to_ascii_lowercase();
            if matches_tag(&name_lower, candidate, &candidate_prefix) {
                matches.push(name);
            }
        }
    }

    match rng.pick(&matches) {
        Some(name) => (*name).clone(),
        None => String::new(),
    }
}

/// Resolves a motion tag to *all* matching names (used by the settings preview).
pub fn resolve_motion_pool(tag: &str, motion_names: &[String], char_name: &str) -> Vec<String> {
    let tag_low = tag.to_ascii_lowercase();
    if tag_low.is_empty() {
        return Vec::new();
    }
    let char_lower = char_name.to_ascii_lowercase();
    let mut candidates = vec![tag_low.clone()];
    if tag_low == "thinking" {
        candidates.extend(["nf", "nnf", "eeto", "odoodo"].map(str::to_owned));
    }
    let mut pool = Vec::new();
    for candidate in &candidates {
        let candidate_prefix = if char_lower.is_empty() {
            candidate.clone()
        } else {
            format!("{char_lower}_{candidate}")
        };
        for name in motion_names {
            let name_lower = name.to_ascii_lowercase();
            if matches_tag(&name_lower, candidate, &candidate_prefix) {
                pool.push(name.clone());
            }
        }
    }
    pool
}

/// Resolves a tag to an expression name (deterministic, first match wins).
pub fn resolve_expression_by_tag(
    tag: &str,
    expression_names: &[String],
    char_name: &str,
) -> String {
    let tag_low = tag.to_ascii_lowercase();
    if tag_low.is_empty() || expression_names.is_empty() {
        return String::new();
    }
    let char_lower = char_name.to_ascii_lowercase();
    let mut target_tags = expression_candidates(&tag_low);
    if target_tags.is_empty() {
        target_tags = vec![tag_low.as_str()];
    }

    for expr_tag in target_tags {
        let mut candidates = vec![expr_tag];
        if expr_tag == "default" {
            candidates.push("idle");
        }
        for candidate in candidates {
            let candidate_prefix = if char_lower.is_empty() {
                candidate.to_owned()
            } else {
                format!("{char_lower}_{candidate}")
            };
            for name in expression_names {
                let name_lower = name.to_ascii_lowercase();
                if matches_tag(&name_lower, candidate, &candidate_prefix) {
                    return name.clone();
                }
            }
        }
    }

    for fallback in ["default", "idle", "smile"] {
        if let Some(name) = expression_names
            .iter()
            .find(|name| name.to_ascii_lowercase().contains(fallback))
        {
            return name.clone();
        }
    }
    expression_names.first().cloned().unwrap_or_default()
}

/// Picks an automatic motion for a region (two tiers, then random non-idle).
pub fn choose_auto_motion(
    region: ClickRegion,
    motion_names: &[String],
    char_name: &str,
    rng: &mut Rng,
) -> String {
    if motion_names.is_empty() {
        return String::new();
    }
    let (first, second) = auto_buckets(region);
    for bucket in [first, second] {
        let mut available: Vec<String> = bucket
            .iter()
            .map(|tag| resolve_motion_by_tag(tag, motion_names, char_name, rng))
            .filter(|name| !name.is_empty())
            .collect();
        if !available.is_empty() {
            available.sort();
            available.dedup();
            return rng.pick(&available).cloned().unwrap_or_default();
        }
    }
    let non_idle: Vec<String> = motion_names
        .iter()
        .filter(|name| {
            let lower = name.to_ascii_lowercase();
            !lower.starts_with("idle") && !lower.starts_with("sys-")
        })
        .cloned()
        .collect();
    if let Some(name) = rng.pick(&non_idle) {
        return name.clone();
    }
    rng.pick(motion_names).cloned().unwrap_or_default()
}

/// Resolves a stored click action into the concrete motion/expression to play.
///
/// * `None` when the action is `__none__` (nothing at all happens).
/// * `Some((motion, expression))` where `motion` may be empty (caller decides
///   between "random non-idle" and "automatic"), mirroring the original
///   `_trigger_click_motion` control flow.
pub fn resolve_click_action(
    region: ClickRegion,
    action: &ClickAction,
    motion_names: &[String],
    expression_names: &[String],
    char_name: &str,
    rng: &mut Rng,
) -> Option<(String, String)> {
    if action.motion == ClickAction::NONE {
        return None;
    }
    let expression = if action.expression.is_empty() {
        String::new()
    } else if action.expression == ClickAction::RANDOM {
        rng.pick(expression_names).cloned().unwrap_or_default()
    } else {
        action.expression.clone()
    };

    let motion = match action.motion.as_str() {
        ClickAction::NONE => return None,
        // `__random__`: play any non-idle motion.
        ClickAction::RANDOM => String::new(),
        ClickAction::AUTO => choose_auto_motion(region, motion_names, char_name, rng),
        other => other.to_owned(),
    };
    Some((motion, expression))
}

/// Expands a built-in preset into literal `click_motion_actions` for one model.
///
/// Mirrors `resolve_preset_to_actions`: tags are resolved once at apply time and
/// stored as literal names; the runtime never re-resolves them.
pub fn resolve_preset(
    preset_name: &str,
    motion_names: &[String],
    expression_names: &[String],
    char_name: &str,
    rng: &mut Rng,
) -> ClickProfile {
    let Some(preset) = preset(preset_name) else {
        return ClickProfile::new();
    };
    let mut actions = ClickProfile::new();
    match preset.mode {
        PresetMode::Auto => {
            for region in CLICK_REGIONS {
                actions.insert(region.key().to_owned(), ClickAction::auto());
            }
        }
        PresetMode::Random => {
            for region in CLICK_REGIONS {
                actions.insert(
                    region.key().to_owned(),
                    ClickAction::new(ClickAction::RANDOM, ""),
                );
            }
        }
        PresetMode::Tags => {
            for region in CLICK_REGIONS {
                let tag = preset.tag_for(region.key()).unwrap_or_default();
                if tag.is_empty() {
                    actions.insert(region.key().to_owned(), ClickAction::auto());
                    continue;
                }
                let motion = resolve_motion_by_tag(tag, motion_names, char_name, rng);
                let expression = resolve_expression_by_tag(tag, expression_names, char_name);
                actions.insert(
                    region.key().to_owned(),
                    ClickAction::new(motion, expression),
                );
            }
        }
    }
    actions
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(list: &[&str]) -> Vec<String> {
        list.iter().map(|name| (*name).to_owned()).collect()
    }

    #[test]
    fn boundary_match_follows_the_python_regex() {
        assert!(boundary_match("mtn_smile01_c", "smile"));
        assert!(boundary_match("smile1", "smile"));
        assert!(boundary_match("mtn-smile", "smile"));
        assert!(!boundary_match("smilex", "smile"));
        assert!(!boundary_match("mtnsmile01", "smile"));
        assert!(boundary_match("smile", "smile"));
        assert!(boundary_match("nf_left01", "nf_left"));
    }

    #[test]
    fn motion_tag_matches_prefix_and_regex_branches() {
        let motions = names(&["angry01", "smile01", "smile02", "mtn_smile03_C", "idle01"]);
        let mut rng = Rng::seeded(1);
        for _ in 0..20 {
            let name = resolve_motion_by_tag("smile", &motions, "kasumi", &mut rng);
            assert!(
                name.starts_with("smile") || name.contains("smile"),
                "{name}"
            );
        }
        let pool = resolve_motion_pool("smile", &motions, "kasumi");
        assert!(pool.contains(&"mtn_smile03_C".to_owned()));
    }

    #[test]
    fn thinking_expands_candidates() {
        let motions = names(&["eeto01", "odoodo01", "nf01"]);
        let pool = resolve_motion_pool("thinking", &motions, "");
        // Candidate order is [thinking, nf, nnf, eeto, odoodo], so `nf01` comes first.
        assert_eq!(pool, names(&["nf01", "eeto01", "odoodo01"]));
    }

    #[test]
    fn unknown_tag_yields_empty_motion() {
        let motions = names(&["smile01"]);
        let mut rng = Rng::seeded(2);
        assert_eq!(
            resolve_motion_by_tag("pui", &motions, "kasumi", &mut rng),
            ""
        );
    }

    #[test]
    fn character_prefixed_names_match() {
        let motions = names(&["kasumi_smile01", "smile02"]);
        let pool = resolve_motion_pool("smile", &motions, "kasumi");
        assert!(pool.contains(&"kasumi_smile01".to_owned()));
    }

    #[test]
    fn expression_resolution_falls_back_to_first_name() {
        // Bandori moc packs name expressions f01..f18: every tag yields f01.
        let expressions = names(&["f01", "f02", "f03"]);
        assert_eq!(
            resolve_expression_by_tag("smile", &expressions, "kasumi"),
            "f01"
        );
        assert_eq!(
            resolve_expression_by_tag("shame", &expressions, "kasumi"),
            "f01"
        );
    }

    #[test]
    fn expression_resolution_prefers_matching_names() {
        let expressions = names(&["angry01", "smile01", "default"]);
        assert_eq!(
            resolve_expression_by_tag("angry", &expressions, ""),
            "angry01"
        );
        assert_eq!(
            resolve_expression_by_tag("sad", &expressions, ""),
            "default"
        );
        let zero_shot = names(&["sad01", "cry01", "smile01"]);
        assert_eq!(resolve_expression_by_tag("sad", &zero_shot, ""), "sad01");
    }

    #[test]
    fn expression_candidates_cover_the_map() {
        assert_eq!(expression_candidates("nf_left"), vec!["smile", "idle"]);
        assert_eq!(expression_candidates("kandou"), vec!["surprised", "kime"]);
        assert!(expression_candidates("banana").is_empty());
    }

    #[test]
    fn auto_motion_prefers_bucket_one() {
        let motions = names(&["surprised01", "smile01", "kime01", "idle01"]);
        let mut rng = Rng::seeded(9);
        for _ in 0..10 {
            let motion = choose_auto_motion(ClickRegion::Head, &motions, "kasumi", &mut rng);
            assert!(
                motion == "surprised01" || motion == "smile01",
                "head bucket should stay in tier 1: {motion}"
            );
        }
    }

    #[test]
    fn auto_motion_falls_back_when_buckets_empty() {
        let motions = names(&["idle01", "idle02", "kime01"]);
        let mut rng = Rng::seeded(4);
        // Body-left buckets resolve to nothing for these names, so the non-idle
        // fallback must produce kime01.
        assert_eq!(
            choose_auto_motion(ClickRegion::UpperBodyLeft, &motions, "kasumi", &mut rng),
            "kime01"
        );
    }

    #[test]
    fn none_action_does_nothing() {
        let motions = names(&["smile01"]);
        let expressions = names(&["f01"]);
        let mut rng = Rng::seeded(3);
        let action = ClickAction::new(ClickAction::NONE, "f01");
        assert_eq!(
            resolve_click_action(
                ClickRegion::Head,
                &action,
                &motions,
                &expressions,
                "kasumi",
                &mut rng
            ),
            None
        );
    }

    #[test]
    fn presets_expand_to_literal_names() {
        let motions = names(&["smile01", "smile02", "kime01", "shame01", "angry01"]);
        let expressions = names(&["f01", "f02"]);
        let mut rng = Rng::seeded(12);
        let auto = resolve_preset("auto", &motions, &expressions, "kasumi", &mut rng);
        assert!(auto.values().all(|action| action.motion.is_empty()));
        let genki = resolve_preset("genki", &motions, &expressions, "kasumi", &mut rng);
        assert!(genki["head"].motion.starts_with("smile"));
        assert_eq!(genki["lower_body_center"].motion, "kime01");
        // `nf_left` has no match in this model -> stored as "" (auto).
        assert_eq!(genki["upper_body_left"].motion, "");
        let random = resolve_preset("random", &motions, &expressions, "kasumi", &mut rng);
        assert!(random
            .values()
            .all(|action| action.motion == ClickAction::RANDOM));
    }
}
