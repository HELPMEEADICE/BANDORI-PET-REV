//! UI languages and the compiled-in string catalogue.
//!
//! The desktop pet ships five UI language variants: Simplified Chinese,
//! Traditional Chinese, Japanese, Korean and English. The catalogue is compiled
//! into the binary, so switching language never touches the disk and every
//! process (pet, settings window) renders the same strings from the same table.
//!
//! ```
//! use pet_i18n::{Lang, Key};
//!
//! let lang = Lang::from_tag("ja_JP");
//! assert_eq!(lang, Lang::Ja);
//! assert_eq!(lang.native_name(), "日本語");
//! assert_eq!(lang.tag(), "ja_JP");
//! let line = lang.format(Key::StatusSaveRejected, &["scale"]);
//! assert!(line.contains("scale") && line != Lang::En.format(Key::StatusSaveRejected, &["scale"]));
//! ```
//!
//! Translation tables live in one file per language; `Key` is generated from the
//! same catalogue order, and every table matches on all keys, so a missing
//! translation is a compile error rather than a silent fallback.

mod en;
mod ja;
mod key;
mod ko;
mod zh_cn;
mod zh_hant;

pub use key::Key;

/// A shipped UI language.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Lang {
    /// Simplified Chinese (`zh_CN`).
    #[default]
    ZhHans,
    /// Traditional Chinese (`zh_TW`).
    ZhHant,
    /// Japanese (`ja_JP`).
    Ja,
    /// Korean (`ko_KR`).
    Ko,
    /// English (`en_US`).
    En,
}

impl Lang {
    /// Every language, in the order of the settings dropdown.
    pub const ALL: [Lang; 5] = [Lang::ZhHans, Lang::ZhHant, Lang::Ja, Lang::Ko, Lang::En];

    /// Tag used for a configuration without an explicit language.
    pub const DEFAULT_TAG: &'static str = "zh_CN";

    /// Configuration tag written back to `config.json`.
    pub fn tag(self) -> &'static str {
        match self {
            Lang::ZhHans => "zh_CN",
            Lang::ZhHant => "zh_TW",
            Lang::Ja => "ja_JP",
            Lang::Ko => "ko_KR",
            Lang::En => "en_US",
        }
    }

    /// Name shown in the language dropdown, written in that language.
    pub fn native_name(self) -> &'static str {
        match self {
            Lang::ZhHans => "简体中文",
            Lang::ZhHant => "繁體中文",
            Lang::Ja => "日本語",
            Lang::Ko => "한국어",
            Lang::En => "English",
        }
    }

    /// Parses a language tag or locale name.
    ///
    /// Accepts both separator styles (`zh-CN`, `zh_CN`), script and region
    /// subtags (`zh-Hant`, `zh-HK`), and bare language codes (`ja`). Anything
    /// unknown falls back to [`Lang::ZhHans`], the default of this project.
    pub fn from_tag(tag: &str) -> Self {
        let normalized = tag.trim().replace('_', "-").to_ascii_lowercase();
        let mut parts = normalized.split('-');
        let Some(primary) = parts.next() else {
            return Lang::ZhHans;
        };
        let rest: Vec<&str> = parts.collect();
        match primary {
            "zh" => {
                let traditional = rest
                    .iter()
                    .any(|part| matches!(*part, "hant" | "tw" | "hk" | "mo"));
                if traditional {
                    Lang::ZhHant
                } else {
                    Lang::ZhHans
                }
            }
            "ja" => Lang::Ja,
            "ko" => Lang::Ko,
            "en" => Lang::En,
            _ => Lang::ZhHans,
        }
    }

    /// Position in the language dropdown.
    pub fn index(self) -> usize {
        match self {
            Lang::ZhHans => 0,
            Lang::ZhHant => 1,
            Lang::Ja => 2,
            Lang::Ko => 3,
            Lang::En => 4,
        }
    }

    /// Language for a dropdown position; out-of-range values use the default.
    pub fn from_index(index: usize) -> Self {
        Self::ALL.get(index).copied().unwrap_or_default()
    }

    /// Language for a Slint dropdown property.
    pub fn from_slint_index(index: i32) -> Self {
        usize::try_from(index)
            .map(Self::from_index)
            .unwrap_or_default()
    }

    /// The string behind `key`.
    pub fn text(self, key: Key) -> &'static str {
        match self {
            Lang::ZhHans => zh_cn::text(key),
            Lang::ZhHant => zh_hant::text(key),
            Lang::Ja => ja::text(key),
            Lang::Ko => ko::text(key),
            Lang::En => en::text(key),
        }
    }

    /// `key` with `{0}`, `{1}`, … and bare `{}` placeholders filled in.
    ///
    /// Placeholders may appear in any order, so a translation can move the
    /// verb or the subject without touching the call site. Unknown indices are
    /// left verbatim, which keeps a bad translation visible instead of dropping
    /// the value.
    pub fn format(self, key: Key, args: &[&str]) -> String {
        substitute(self.text(key), args)
    }

    /// `3 characters` / `3 名角色` / `キャラクター 3 名` / `캐릭터 3명`.
    pub fn character_count(self, count: usize) -> String {
        match self {
            Lang::ZhHans => zh_cn::character_count(count),
            Lang::ZhHant => zh_hant::character_count(count),
            Lang::Ja => ja::character_count(count),
            Lang::Ko => ko::character_count(count),
            Lang::En => en::character_count(count),
        }
    }

    /// `3 outfits` / `3 套服装` / `衣装 3 着` / `의상 3벌`.
    pub fn costume_count(self, count: usize) -> String {
        match self {
            Lang::ZhHans => zh_cn::costume_count(count),
            Lang::ZhHant => zh_hant::costume_count(count),
            Lang::Ja => ja::costume_count(count),
            Lang::Ko => ko::costume_count(count),
            Lang::En => en::costume_count(count),
        }
    }

    /// `3 packages` / `3 个模型包` / `3 個のパッケージ` / `패키지 3개`.
    pub fn package_count(self, count: usize) -> String {
        match self {
            Lang::ZhHans => zh_cn::package_count(count),
            Lang::ZhHant => zh_hant::package_count(count),
            Lang::Ja => ja::package_count(count),
            Lang::Ko => ko::package_count(count),
            Lang::En => en::package_count(count),
        }
    }

    /// Download row detail of an installed package.
    pub fn installed_row(self, costumes: usize, size: &str) -> String {
        match self {
            Lang::ZhHans => zh_cn::installed_row(costumes, size),
            Lang::ZhHant => zh_hant::installed_row(costumes, size),
            Lang::Ja => ja::installed_row(costumes, size),
            Lang::Ko => ko::installed_row(costumes, size),
            Lang::En => en::installed_row(costumes, size),
        }
    }
}

/// Fills `{}` (sequential) and `{n}` (explicit) placeholders.
fn substitute(template: &str, args: &[&str]) -> String {
    let mut output = String::with_capacity(template.len() + 16);
    let mut chars = template.char_indices().peekable();
    let mut sequential = 0usize;
    while let Some((_, ch)) = chars.next() {
        if ch != '{' {
            output.push(ch);
            continue;
        }
        let mut explicit = String::new();
        let mut closed = false;
        while let Some((index, inner)) = chars.peek().copied() {
            if inner == '}' {
                chars.next();
                let _ = index;
                closed = true;
                break;
            }
            if inner.is_ascii_digit() && explicit.len() < 4 {
                explicit.push(inner);
                chars.next();
                continue;
            }
            break;
        }
        if !closed {
            output.push('{');
            output.push_str(&explicit);
            continue;
        }
        let slot = if explicit.is_empty() {
            let slot = sequential;
            sequential += 1;
            slot
        } else {
            explicit.parse::<usize>().unwrap_or(usize::MAX)
        };
        match args.get(slot) {
            Some(value) => output.push_str(value),
            None => {
                output.push('{');
                output.push_str(&explicit);
                output.push('}');
            }
        }
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tags_round_trip_for_every_language() {
        for lang in Lang::ALL {
            assert_eq!(Lang::from_tag(lang.tag()), lang);
            assert_eq!(Lang::from_index(lang.index()), lang);
            assert!(!lang.native_name().is_empty());
        }
    }

    #[test]
    fn locale_variants_map_to_a_shipped_language() {
        for (tag, expected) in [
            ("zh", Lang::ZhHans),
            ("zh-CN", Lang::ZhHans),
            ("zh_CN", Lang::ZhHans),
            ("zh-Hans", Lang::ZhHans),
            ("zh-SG", Lang::ZhHans),
            ("zh-TW", Lang::ZhHant),
            ("zh_TW", Lang::ZhHant),
            ("zh-Hant", Lang::ZhHant),
            ("zh-HK", Lang::ZhHant),
            ("zh-MO", Lang::ZhHant),
            ("ja", Lang::Ja),
            ("ja-JP", Lang::Ja),
            ("ko-KR", Lang::Ko),
            ("en-US", Lang::En),
            ("en", Lang::En),
            ("de-DE", Lang::ZhHans),
            ("", Lang::ZhHans),
        ] {
            assert_eq!(Lang::from_tag(tag), expected, "tag {tag}");
        }
    }

    #[test]
    fn every_key_is_translated_in_every_language() {
        for lang in Lang::ALL {
            for key in Key::ALL {
                assert!(
                    !lang.text(*key).trim().is_empty(),
                    "{} has no text for {}",
                    lang.tag(),
                    key.name()
                );
            }
        }
    }

    #[test]
    fn non_chinese_tables_are_not_left_in_english() {
        // Brand names and units stay identical across languages; everything
        // else must actually be translated.
        const ALLOWED: &[&str] = &["DownloadSource"];
        for key in Key::ALL {
            if ALLOWED.contains(&key.name()) {
                continue;
            }
            let english = Lang::En.text(*key);
            for lang in [Lang::Ja, Lang::Ko] {
                assert_ne!(
                    lang.text(*key),
                    english,
                    "{} was not translated for {}",
                    key.name(),
                    lang.tag()
                );
            }
        }
    }

    #[test]
    fn traditional_chinese_is_a_real_conversion() {
        // Traditional and Simplified share many words (表情, 版本, 收藏), so a
        // per-key difference check would force unnatural wording. Instead the
        // table must differ broadly, and print characters the Simplified table
        // never uses.
        let mut converted = 0;
        for key in Key::ALL {
            if Lang::ZhHant.text(*key) != Lang::ZhHans.text(*key) {
                converted += 1;
            }
        }
        assert!(
            converted >= 150,
            "only {converted} of {} strings were converted",
            Key::ALL.len()
        );
        let simplified: std::collections::HashSet<char> = Key::ALL
            .iter()
            .flat_map(|key| Lang::ZhHans.text(*key).chars())
            .collect();
        let traditional_only = Key::ALL
            .iter()
            .flat_map(|key| Lang::ZhHant.text(*key).chars())
            .filter(|ch| !simplified.contains(ch))
            .collect::<std::collections::HashSet<_>>();
        assert!(
            traditional_only.len() >= 15,
            "Traditional Chinese only adds {} characters: {traditional_only:?}",
            traditional_only.len()
        );
        for key in [Key::SettingsTitle, Key::NavDisplay, Key::RegionHead] {
            assert_ne!(
                Lang::ZhHant.text(key),
                Lang::ZhHans.text(key),
                "{} was not converted",
                key.name()
            );
        }
    }

    #[test]
    fn placeholders_fill_in_order_and_by_index() {
        assert_eq!(
            Lang::ZhHans.format(Key::StatusSaveRejected, &["scale"]),
            "保存被拒绝：scale"
        );
        assert_eq!(
            Lang::En.format(Key::ModelInfo, &["moc3", "28", "18", "100", "4"]),
            "Format moc3 · Motions 28 · Expressions 18 · Drawables 100 · Textures 4"
        );
        // Outfit name before character name in English, character first in zh.
        assert_eq!(
            Lang::En.format(Key::AppCostumeLoadFailed, &["anon", "school", "boom"]),
            "Cannot load outfit school of character anon: boom"
        );
        assert_eq!(
            Lang::ZhHans.format(Key::AppCostumeLoadFailed, &["anon", "school", "boom"]),
            "无法加载角色 anon 的服装 school：boom"
        );
        assert_eq!(
            substitute("{} and {1} and {0}", &["a", "b"]),
            "a and b and a"
        );
        assert_eq!(substitute("{9} missing", &["a"]), "{9} missing");
        assert_eq!(substitute("plain", &[]), "plain");
        assert_eq!(substitute("{x}", &["a"]), "{x}");
    }

    #[test]
    fn counts_use_the_plural_form_of_each_language() {
        assert_eq!(Lang::En.character_count(1), "1 character");
        assert_eq!(Lang::En.character_count(12), "12 characters");
        assert_eq!(Lang::ZhHans.character_count(12), "12 名角色");
        assert_eq!(Lang::En.costume_count(1), "1 outfit");
        assert_eq!(
            Lang::En.installed_row(1, "12.0 MB"),
            "Installed · 1 outfit · 12.0 MB"
        );
        assert_eq!(
            Lang::ZhHans.installed_row(3, "12.0 MB"),
            "已安装 · 3 套服装 · 12.0 MB"
        );
        for lang in Lang::ALL {
            assert!(lang.package_count(3).contains('3'));
        }
    }
}
