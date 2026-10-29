//! Filesystem layout shared by both processes (spec §4.3).

use std::path::{Path, PathBuf};

/// Environment variable that overrides the application root (used by tests and
/// by running straight out of `target/debug` during development).
pub const ROOT_ENV: &str = "BANDORI_PET_ROOT";

/// Directory layout of one installation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Paths {
    root: PathBuf,
    cache: PathBuf,
    executable_dir: PathBuf,
    bundled_assets: Option<PathBuf>,
}

impl Paths {
    /// Discovers the data root: `$BANDORI_PET_ROOT`, else Application Support on
    /// macOS, XDG data home on Linux or the executable directory on Windows.
    pub fn discover() -> Self {
        #[cfg(target_os = "macos")]
        if let (Ok(exe), Some(home)) = (std::env::current_exe(), std::env::var_os("HOME")) {
            return Self::macos_layout(
                &exe,
                Path::new(&home),
                std::env::var_os(ROOT_ENV).map(PathBuf::from),
            );
        }
        #[cfg(target_os = "linux")]
        if let (Ok(exe), Some(home)) = (std::env::current_exe(), std::env::var_os("HOME")) {
            return Self::linux_layout(
                &exe,
                Path::new(&home),
                std::env::var_os(ROOT_ENV).map(PathBuf::from),
                std::env::var_os("XDG_DATA_HOME").map(PathBuf::from),
                std::env::var_os("XDG_CACHE_HOME").map(PathBuf::from),
            );
        }
        let root = std::env::var_os(ROOT_ENV)
            .map(PathBuf::from)
            .or_else(|| {
                std::env::current_exe()
                    .ok()
                    .and_then(|exe| exe.parent().map(Path::to_path_buf))
            })
            .unwrap_or_else(|| PathBuf::from("."));
        Self::with_root(root)
    }

    /// Builds the layout on top of an explicit root directory.
    pub fn with_root(root: impl Into<PathBuf>) -> Self {
        let root = root.into();
        let cache = local_app_data()
            .unwrap_or_else(|| root.clone())
            .join("BandoriPetLite")
            .join("cache");
        Self {
            executable_dir: root.clone(),
            root,
            cache,
            bundled_assets: None,
        }
    }

    #[cfg(any(target_os = "macos", test))]
    fn macos_layout(exe: &Path, home: &Path, root: Option<PathBuf>) -> Self {
        let executable_dir = exe.parent().unwrap_or(Path::new(".")).to_path_buf();
        let bundled_assets = executable_dir
            .parent()
            .filter(|_| {
                executable_dir
                    .file_name()
                    .is_some_and(|name| name == "MacOS")
            })
            .map(|contents| contents.join("Resources/assets"));
        Self {
            root: root.unwrap_or_else(|| home.join("Library/Application Support/BandoriPetLite")),
            cache: home.join("Library/Caches/BandoriPetLite/cache"),
            executable_dir,
            bundled_assets,
        }
    }

    #[cfg(any(target_os = "linux", test))]
    fn linux_layout(
        exe: &Path,
        home: &Path,
        root: Option<PathBuf>,
        data_home: Option<PathBuf>,
        cache_home: Option<PathBuf>,
    ) -> Self {
        let executable_dir = exe.parent().unwrap_or(Path::new(".")).to_path_buf();
        Self {
            root: root.unwrap_or_else(|| {
                data_home
                    .filter(|path| path.is_absolute())
                    .unwrap_or_else(|| home.join(".local/share"))
                    .join("BandoriPetLite")
            }),
            cache: cache_home
                .filter(|path| path.is_absolute())
                .unwrap_or_else(|| home.join(".cache"))
                .join("BandoriPetLite/cache"),
            bundled_assets: Some(executable_dir.join("assets")),
            executable_dir,
        }
    }

    /// Writable data root (configuration, models and logs).
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// `config.json` — single writer is `bandori-pet`.
    pub fn config(&self) -> PathBuf {
        self.root.join("config.json")
    }

    /// `models/` holding the `.zst` archives and the model index.
    pub fn models(&self) -> PathBuf {
        self.root.join("models")
    }

    /// `models/.bandori_model_index.json`.
    pub fn model_index(&self) -> PathBuf {
        self.models().join(".bandori_model_index.json")
    }

    /// `assets/` holding `band.json`, `outfit.json`, icons and fonts.
    pub fn assets(&self) -> PathBuf {
        let custom = self.root.join("assets");
        if custom.is_dir() {
            custom
        } else {
            self.bundled_assets.clone().unwrap_or(custom)
        }
    }

    /// `logs/`.
    pub fn logs(&self) -> PathBuf {
        self.root.join("logs")
    }

    /// `ui/`.
    pub fn ui(&self) -> PathBuf {
        self.root.join("ui")
    }

    /// Extracted model costumes in the user's platform cache directory.
    pub fn cache(&self) -> &Path {
        &self.cache
    }

    /// User-local cache parent.
    pub fn local_data(&self) -> Option<PathBuf> {
        self.cache.parent().map(Path::to_path_buf)
    }

    /// Path of the settings executable beside the pet executable.
    pub fn ui_executable(&self) -> PathBuf {
        self.executable_dir.join(exe_name("bandori-ui"))
    }

    /// Path of the pet executable.
    pub fn pet_executable(&self) -> PathBuf {
        self.executable_dir.join(exe_name("bandori-pet"))
    }
}

fn exe_name(stem: &str) -> String {
    if cfg!(windows) {
        format!("{stem}.exe")
    } else {
        stem.to_owned()
    }
}

fn local_app_data() -> Option<PathBuf> {
    #[cfg(target_os = "macos")]
    {
        std::env::var_os("HOME").map(|home| PathBuf::from(home).join("Library/Caches"))
    }
    #[cfg(target_os = "linux")]
    {
        std::env::var_os("XDG_CACHE_HOME")
            .map(PathBuf::from)
            .filter(|path| path.is_absolute())
            .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
    }
    #[cfg(not(any(target_os = "macos", target_os = "linux")))]
    std::env::var_os("LOCALAPPDATA").map(PathBuf::from)
}

/// Rows shown on the About page (`label`, `value`).
pub fn about_lines(
    paths: &Paths,
    config: &crate::Config,
    lang: pet_i18n::Lang,
) -> Vec<(String, String)> {
    vec![
        (
            lang.text(pet_i18n::Key::AboutVersion).to_owned(),
            env!("CARGO_PKG_VERSION").to_owned(),
        ),
        (
            lang.text(pet_i18n::Key::AboutModelsDirectory).to_owned(),
            paths.models().display().to_string(),
        ),
        (
            lang.text(pet_i18n::Key::AboutCacheDirectory).to_owned(),
            paths.cache().display().to_string(),
        ),
        (
            lang.text(pet_i18n::Key::AboutLogsDirectory).to_owned(),
            paths.logs().display().to_string(),
        ),
        (
            lang.text(pet_i18n::Key::AboutCurrentCharacter).to_owned(),
            format!("{} / {}", config.character, config.costume),
        ),
        (
            lang.text(pet_i18n::Key::AboutConfigFile).to_owned(),
            paths.config().display().to_string(),
        ),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layout_matches_spec() {
        let paths = Paths::with_root("C:/app");
        assert_eq!(paths.config(), PathBuf::from("C:/app/config.json"));
        assert_eq!(paths.models(), PathBuf::from("C:/app/models"));
        assert!(paths.model_index().ends_with(".bandori_model_index.json"));
        assert!(paths.cache().ends_with("BandoriPetLite/cache"));
    }

    #[test]
    fn macos_bundle_keeps_writable_data_outside_the_app() {
        let paths = Paths::macos_layout(
            Path::new("/Applications/Bandori Pet.app/Contents/MacOS/bandori-pet"),
            Path::new("/Users/test"),
            None,
        );
        assert_eq!(
            paths.config(),
            PathBuf::from("/Users/test/Library/Application Support/BandoriPetLite/config.json")
        );
        assert_eq!(
            paths.cache(),
            Path::new("/Users/test/Library/Caches/BandoriPetLite/cache")
        );
        assert_eq!(
            paths.assets(),
            PathBuf::from("/Applications/Bandori Pet.app/Contents/Resources/assets")
        );
        // The platform suffix varies when this pure layout test runs on Windows.
        assert_eq!(
            paths.ui_executable().parent(),
            Some(Path::new("/Applications/Bandori Pet.app/Contents/MacOS"))
        );
    }

    #[test]
    fn macos_root_override_keeps_the_companion_binary_location() {
        let paths = Paths::macos_layout(
            Path::new("/build/target/debug/bandori-pet"),
            Path::new("/Users/test"),
            Some(PathBuf::from("/custom/data")),
        );
        assert_eq!(paths.models(), PathBuf::from("/custom/data/models"));
        assert_eq!(
            paths.pet_executable().parent(),
            Some(Path::new("/build/target/debug"))
        );
        assert_eq!(paths.assets(), PathBuf::from("/custom/data/assets"));
    }

    #[test]
    fn linux_layout_uses_xdg_and_keeps_binaries_outside_writable_data() {
        let data = std::env::temp_dir().join("bandori-layout-data");
        let cache = std::env::temp_dir().join("bandori-layout-cache");
        let paths = Paths::linux_layout(
            Path::new("/opt/bandori/bandori-pet"),
            Path::new("/home/test"),
            None,
            Some(data.clone()),
            Some(cache.clone()),
        );
        assert_eq!(paths.config(), data.join("BandoriPetLite/config.json"));
        assert_eq!(paths.cache(), cache.join("BandoriPetLite/cache"));
        assert_eq!(paths.assets(), PathBuf::from("/opt/bandori/assets"));
        assert_eq!(
            paths.ui_executable().parent(),
            Some(Path::new("/opt/bandori"))
        );
    }

    #[test]
    fn linux_ignores_relative_xdg_paths_and_preserves_root_override() {
        let paths = Paths::linux_layout(
            Path::new("/opt/bandori/bandori-pet"),
            Path::new("/home/test"),
            None,
            Some(PathBuf::from("relative")),
            Some(PathBuf::new()),
        );
        assert_eq!(
            paths.root(),
            Path::new("/home/test/.local/share/BandoriPetLite")
        );
        assert_eq!(
            paths.cache(),
            Path::new("/home/test/.cache/BandoriPetLite/cache")
        );
        let custom = Paths::linux_layout(
            Path::new("/opt/bandori/bandori-pet"),
            Path::new("/home/test"),
            Some(PathBuf::from("/custom")),
            None,
            None,
        );
        assert_eq!(custom.root(), Path::new("/custom"));
        assert_eq!(
            custom.pet_executable().parent(),
            Some(Path::new("/opt/bandori"))
        );
    }
}
