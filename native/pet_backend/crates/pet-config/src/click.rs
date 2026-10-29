//! Click-region identifiers and the per-region motion/expression action type.

use pet_i18n::{Key, Lang};
use serde::{Deserialize, Serialize};

/// The seven clickable body regions, in the order shown by the settings UI.
///
/// The keys and the Chinese display names are taken verbatim from the Python
/// original (`live2d_click_actions.py`, `settings_window/pages/behavior.py`).
pub const CLICK_REGIONS: [ClickRegion; 7] = [
    ClickRegion::Head,
    ClickRegion::UpperBodyLeft,
    ClickRegion::UpperBodyCenter,
    ClickRegion::UpperBodyRight,
    ClickRegion::LowerBodyLeft,
    ClickRegion::LowerBodyCenter,
    ClickRegion::LowerBodyRight,
];

/// One of the seven click regions.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClickRegion {
    /// Face and hair.
    Head,
    /// Left shoulder / left hand area.
    UpperBodyLeft,
    /// Chest / collar area.
    UpperBodyCenter,
    /// Right shoulder / right hand area.
    UpperBodyRight,
    /// Left side of the skirt / leg.
    LowerBodyLeft,
    /// Waist / middle of the skirt.
    LowerBodyCenter,
    /// Right side of the skirt / leg.
    LowerBodyRight,
}

impl ClickRegion {
    /// Stable config key (`head`, `upper_body_left`, …).
    pub fn key(self) -> &'static str {
        match self {
            ClickRegion::Head => "head",
            ClickRegion::UpperBodyLeft => "upper_body_left",
            ClickRegion::UpperBodyCenter => "upper_body_center",
            ClickRegion::UpperBodyRight => "upper_body_right",
            ClickRegion::LowerBodyLeft => "lower_body_left",
            ClickRegion::LowerBodyCenter => "lower_body_center",
            ClickRegion::LowerBodyRight => "lower_body_right",
        }
    }

    /// Catalogue key of the display name.
    pub fn display_name_key(self) -> Key {
        match self {
            ClickRegion::Head => Key::RegionHead,
            ClickRegion::UpperBodyLeft => Key::RegionUpperBodyLeft,
            ClickRegion::UpperBodyCenter => Key::RegionUpperBodyCenter,
            ClickRegion::UpperBodyRight => Key::RegionUpperBodyRight,
            ClickRegion::LowerBodyLeft => Key::RegionLowerBodyLeft,
            ClickRegion::LowerBodyCenter => Key::RegionLowerBodyCenter,
            ClickRegion::LowerBodyRight => Key::RegionLowerBodyRight,
        }
    }

    /// Display name in `lang`.
    pub fn display_name(self, lang: Lang) -> &'static str {
        lang.text(self.display_name_key())
    }

    /// Parses a config key back into a region.
    pub fn from_key(key: &str) -> Option<Self> {
        CLICK_REGIONS.into_iter().find(|region| region.key() == key)
    }
}

/// Per-region action: a motion name and an expression name.
///
/// Both fields accept:
/// * `""` — automatic matching from the motion/expression tag,
/// * [`ClickAction::RANDOM`] — pick a random candidate,
/// * [`ClickAction::NONE`] — do not trigger anything,
/// * any real motion group / expression name of the current model.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ClickAction {
    /// Motion selection.
    pub motion: String,
    /// Expression selection.
    pub expression: String,
}

impl ClickAction {
    /// `__random__` sentinel: choose randomly among matching candidates.
    pub const RANDOM: &'static str = "__random__";
    /// `__none__` sentinel: trigger nothing.
    pub const NONE: &'static str = "__none__";
    /// `""` sentinel: automatic matching.
    pub const AUTO: &'static str = "";

    /// Creates an action from a motion/expression pair.
    pub fn new(motion: impl Into<String>, expression: impl Into<String>) -> Self {
        Self {
            motion: motion.into(),
            expression: expression.into(),
        }
    }

    /// The `auto` action (both fields empty).
    pub fn auto() -> Self {
        Self::default()
    }
}

/// A named profile containing the full seven-region mapping.
pub type ClickProfile = std::collections::BTreeMap<String, ClickAction>;

/// Builds the default seven-region map where every region uses automatic matching.
pub fn default_click_actions() -> ClickProfile {
    CLICK_REGIONS
        .into_iter()
        .map(|region| (region.key().to_owned(), ClickAction::auto()))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn region_keys_are_unique_and_round_trip() {
        let mut seen = std::collections::BTreeSet::new();
        for region in CLICK_REGIONS {
            assert!(seen.insert(region.key()), "duplicate key {}", region.key());
            assert_eq!(ClickRegion::from_key(region.key()), Some(region));
        }
        assert_eq!(seen.len(), 7);
    }

    #[test]
    fn display_names_follow_the_language() {
        assert_eq!(ClickRegion::Head.display_name(Lang::ZhHans), "脸和头发");
        assert_eq!(ClickRegion::Head.display_name(Lang::En), "Face and hair");
        assert_ne!(
            ClickRegion::Head.display_name(Lang::Ja),
            ClickRegion::Head.display_name(Lang::ZhHans)
        );
    }

    #[test]
    fn default_actions_cover_every_region() {
        let actions = default_click_actions();
        assert_eq!(actions.len(), 7);
        for region in CLICK_REGIONS {
            let action = actions.get(region.key()).expect("region present");
            assert_eq!(action, &ClickAction::auto());
        }
    }
}
