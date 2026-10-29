//! The seven built-in click-motion presets (spec §2.6).
//!
//! A preset is nothing but a 7-region → tag map; the bands come verbatim from the
//! Python original (`click_motion_presets.py::BUILTIN_CLICK_MOTION_PROFILES`,
//! extracted in `BANDORI-PET-REV-behavior-spec.md` §1). Resolution of a tag into a
//! real motion/expression name lives in `pet-input`, because it needs the loaded
//! model's name lists.

use pet_i18n::{Key, Lang};

use crate::click::CLICK_REGIONS;

/// How a preset expands into `click_motion_actions`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PresetMode {
    /// Every region uses automatic matching (`""`).
    Auto,
    /// Every region plays a random non-idle motion (`__random__`).
    Random,
    /// Every region maps to the tag below.
    Tags,
}

/// One built-in preset.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Preset {
    /// Config token, also the profile name (`genki`).
    pub name: &'static str,
    /// Catalogue key of the display name.
    pub label_key: Key,
    /// Catalogue key of the one-line description.
    pub description_key: Key,
    /// `(region key, motion/expression tag)` pairs, in `CLICK_REGIONS` order.
    pub tags: &'static [(&'static str, &'static str)],
    /// Expansion mode.
    pub mode: PresetMode,
}

/// Preset order used by the settings dropdown.
pub const PRESET_NAMES: [&str; 7] = [
    "auto",
    "genki",
    "tsundere",
    "shy",
    "cool",
    "surprised",
    "random",
];

const GENKI: [(&str, &str); 7] = [
    ("head", "smile"),
    ("upper_body_left", "nf_left"),
    ("upper_body_center", "smile"),
    ("upper_body_right", "nf_right"),
    ("lower_body_left", "smile"),
    ("lower_body_center", "kime"),
    ("lower_body_right", "smile"),
];

const TSUNDERE: [(&str, &str); 7] = [
    ("head", "shame"),
    ("upper_body_left", "pui"),
    ("upper_body_center", "angry"),
    ("upper_body_right", "pui"),
    ("lower_body_left", "shame"),
    ("lower_body_center", "angry"),
    ("lower_body_right", "serious"),
];

const SHY: [(&str, &str); 7] = [
    ("head", "shame"),
    ("upper_body_left", "nnf_left"),
    ("upper_body_center", "shame"),
    ("upper_body_right", "nnf_right"),
    ("lower_body_left", "sad"),
    ("lower_body_center", "shame"),
    ("lower_body_right", "sad"),
];

const COOL: [(&str, &str); 7] = [
    ("head", "serious"),
    ("upper_body_left", "kime"),
    ("upper_body_center", "serious"),
    ("upper_body_right", "kime"),
    ("lower_body_left", "serious"),
    ("lower_body_center", "kime"),
    ("lower_body_right", "serious"),
];

const SURPRISED: [(&str, &str); 7] = [
    ("head", "surprised"),
    ("upper_body_left", "surprised"),
    ("upper_body_center", "surprised"),
    ("upper_body_right", "surprised"),
    ("lower_body_left", "surprised"),
    ("lower_body_center", "surprised"),
    ("lower_body_right", "surprised"),
];

/// All built-in presets in dropdown order.
pub const PRESETS: [Preset; 7] = [
    Preset {
        name: "auto",
        label_key: Key::PresetAuto,
        description_key: Key::PresetAutoDescription,
        tags: &[],
        mode: PresetMode::Auto,
    },
    Preset {
        name: "genki",
        label_key: Key::PresetGenki,
        description_key: Key::PresetGenkiDescription,
        tags: &GENKI,
        mode: PresetMode::Tags,
    },
    Preset {
        name: "tsundere",
        label_key: Key::PresetTsundere,
        description_key: Key::PresetTsundereDescription,
        tags: &TSUNDERE,
        mode: PresetMode::Tags,
    },
    Preset {
        name: "shy",
        label_key: Key::PresetShy,
        description_key: Key::PresetShyDescription,
        tags: &SHY,
        mode: PresetMode::Tags,
    },
    Preset {
        name: "cool",
        label_key: Key::PresetCool,
        description_key: Key::PresetCoolDescription,
        tags: &COOL,
        mode: PresetMode::Tags,
    },
    Preset {
        name: "surprised",
        label_key: Key::PresetSurprised,
        description_key: Key::PresetSurprisedDescription,
        tags: &SURPRISED,
        mode: PresetMode::Tags,
    },
    Preset {
        name: "random",
        label_key: Key::PresetRandom,
        description_key: Key::PresetRandomDescription,
        tags: &[],
        mode: PresetMode::Random,
    },
];

/// Looks a preset up by name.
pub fn preset(name: &str) -> Option<&'static Preset> {
    PRESETS.iter().find(|preset| preset.name == name)
}

/// Preset names, in dropdown order.
pub fn preset_names() -> &'static [&'static str; 7] {
    &PRESET_NAMES
}

/// `true` when `name` is a built-in preset (custom profiles may not reuse it).
pub fn is_builtin_name(name: &str) -> bool {
    PRESET_NAMES.contains(&name)
}

impl Preset {
    /// Display name in `lang`.
    pub fn label(self, lang: Lang) -> &'static str {
        lang.text(self.label_key)
    }

    /// One-line description in `lang`.
    pub fn description(self, lang: Lang) -> &'static str {
        lang.text(self.description_key)
    }

    /// Tag for one region, if the preset defines it.
    pub fn tag_for(&self, region_key: &str) -> Option<&'static str> {
        self.tags
            .iter()
            .find(|(region, _)| *region == region_key)
            .map(|(_, tag)| *tag)
    }

    /// `true` when the preset covers all seven regions with tags.
    pub fn covers_every_region(&self) -> bool {
        CLICK_REGIONS
            .into_iter()
            .all(|region| self.tag_for(region.key()).is_some())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_tag_preset_covers_all_seven_regions() {
        for preset in PRESETS
            .iter()
            .filter(|preset| preset.mode == PresetMode::Tags)
        {
            assert!(
                preset.covers_every_region(),
                "{} misses a region",
                preset.name
            );
        }
    }

    #[test]
    fn lookup_and_builtin_names_behave() {
        assert_eq!(preset("genki").unwrap().label(Lang::ZhHans), "元气开朗");
        assert_eq!(preset("genki").unwrap().label(Lang::En), "Cheerful");
        assert!(!preset("genki").unwrap().description(Lang::Ja).is_empty());
        assert!(preset("nope").is_none());
        assert!(is_builtin_name("random"));
        assert!(!is_builtin_name("my_profile"));
        assert_eq!(preset_names().len(), 7);
    }

    #[test]
    fn tsundere_table_matches_the_original() {
        let tsundere = preset("tsundere").unwrap();
        assert_eq!(tsundere.tag_for("head"), Some("shame"));
        assert_eq!(tsundere.tag_for("upper_body_left"), Some("pui"));
        assert_eq!(tsundere.tag_for("lower_body_right"), Some("serious"));
    }
}
