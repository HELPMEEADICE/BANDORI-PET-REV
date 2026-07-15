use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::sync::RwLock;
use tar::Archive;
use thiserror::Error;

pub const VIRTUAL_SEPARATOR: &str = "::";
pub const ARCHIVE_INDEX_MEMBER: &str = ".bandori_zst_index.json";
const ARCHIVE_MEMBER_MAX_BYTES: u64 = 64 * 1024 * 1024;
const ARCHIVE_INDEX_MAX_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ModelFormat {
    Moc,
    Moc3,
}

impl ModelFormat {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Moc => "moc",
            Self::Moc3 => "moc3",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Costume {
    pub id: String,
    pub path: String,
    pub format: ModelFormat,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Band {
    pub id: String,
    pub display: String,
    pub logo: String,
    pub characters: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct ModelRoot {
    pub path: PathBuf,
    pub override_existing: bool,
}

#[derive(Clone, Debug)]
pub struct ModelManagerPaths {
    pub base_dir: PathBuf,
    pub search_roots: Vec<ModelRoot>,
    pub lookup_roots: Vec<PathBuf>,
    pub outfit_json: PathBuf,
    pub band_json: PathBuf,
    pub characters_dir: PathBuf,
    pub custom_models_label: String,
}

impl ModelManagerPaths {
    pub fn for_installation(base_dir: &Path, data_dir: &Path, frozen: bool) -> Self {
        let bundled = base_dir.join("models");
        let user = data_dir.join("models");
        let mut search_roots = Vec::new();
        if frozen {
            search_roots.push(ModelRoot {
                path: bundled.clone(),
                override_existing: false,
            });
        }
        if !search_roots.iter().any(|root| root.path == user) {
            search_roots.push(ModelRoot {
                path: user.clone(),
                override_existing: frozen && user != bundled,
            });
        }

        let mut lookup_roots = vec![user];
        if frozen && !lookup_roots.contains(&bundled) {
            lookup_roots.push(bundled);
        }
        Self {
            base_dir: base_dir.to_path_buf(),
            search_roots,
            lookup_roots,
            outfit_json: base_dir.join("outfit.json"),
            band_json: base_dir.join("band.json"),
            characters_dir: base_dir.join("characters"),
            custom_models_label: "Custom Models".into(),
        }
    }
}

#[derive(Debug, Error)]
pub enum ModelError {
    #[error("model I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("model JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("unsafe archive member path: {0}")]
    UnsafeArchivePath(String),
    #[error("archive member is too large: {0}")]
    ArchiveMemberTooLarge(String),
    #[error("archive member not found: {0}")]
    ArchiveMemberNotFound(String),
    #[error("virtual model path is invalid: {0}")]
    InvalidVirtualPath(String),
}

#[derive(Clone, Debug, Default)]
struct CharacterInfo {
    display: Option<String>,
    costumes: BTreeMap<String, Costume>,
}

#[derive(Debug)]
pub struct ModelManager {
    paths: ModelManagerPaths,
    character_order: Vec<String>,
    characters: HashMap<String, CharacterInfo>,
    model_paths: HashMap<(String, String), String>,
    character_images: HashMap<String, String>,
    costume_names: HashMap<String, HashMap<String, String>>,
    bands: Vec<Band>,
    model_json_cache: RwLock<HashMap<String, Value>>,
}

impl ModelManager {
    pub fn scan(paths: ModelManagerPaths) -> Self {
        let mut manager = Self::empty(paths);
        manager.rescan();
        manager
    }

    pub fn empty(paths: ModelManagerPaths) -> Self {
        Self {
            paths,
            character_order: Vec::new(),
            characters: HashMap::new(),
            model_paths: HashMap::new(),
            character_images: HashMap::new(),
            costume_names: HashMap::new(),
            bands: Vec::new(),
            model_json_cache: RwLock::new(HashMap::new()),
        }
    }

    pub fn rescan(&mut self) {
        self.character_order.clear();
        self.characters.clear();
        self.model_paths.clear();
        self.character_images.clear();
        self.costume_names.clear();
        self.bands.clear();
        self.model_json_cache
            .write()
            .expect("model cache lock poisoned")
            .clear();

        let roots = self.paths.search_roots.clone();
        for root in roots {
            self.scan_root(&root);
        }
        self.parse_outfit_json();
        self.parse_band_json();
    }

    pub fn characters(&self) -> &[String] {
        &self.character_order
    }

    pub fn bands(&self) -> &[Band] {
        &self.bands
    }

    pub fn costumes(&self, character: &str) -> Vec<&Costume> {
        self.characters
            .get(character)
            .map(|info| info.costumes.values().collect())
            .unwrap_or_default()
    }

    pub fn display_name(&self, character: &str) -> String {
        self.characters
            .get(character)
            .and_then(|info| info.display.clone())
            .unwrap_or_else(|| title_case(character))
    }

    pub fn costume_display_name(&self, character: &str, costume: &str) -> String {
        self.costume_names
            .get(character)
            .and_then(|names| names.get(costume))
            .cloned()
            .unwrap_or_else(|| costume.to_owned())
    }

    pub fn default_costume(&self, character: &str) -> String {
        let costumes = self.costumes(character);
        for preferred in ["live_default", "casual", "school_winter", "school_summer"] {
            if costumes.iter().any(|costume| costume.id == preferred) {
                return preferred.into();
            }
        }
        costumes
            .first()
            .map(|costume| costume.id.clone())
            .unwrap_or_default()
    }

    pub fn model_json_path(&self, character: &str, costume: &str) -> String {
        if let Some(path) = self
            .model_paths
            .get(&(character.to_owned(), costume.to_owned()))
        {
            return path.clone();
        }
        for root in &self.paths.lookup_roots {
            if let Some(path) = find_model_manifest(&root.join(character).join(costume)) {
                return absolute_string(&path);
            }
        }
        String::new()
    }

    pub fn model_format(&self, character: &str, costume: &str) -> Option<ModelFormat> {
        let path = self.model_json_path(character, costume);
        (!path.is_empty()).then(|| self.model_format_from_path(&path))
    }

    pub fn motion_names(&self, character: &str, costume: &str) -> Vec<String> {
        let path = self.model_json_path(character, costume);
        let Ok(data) = self.read_model_json(&path) else {
            return Vec::new();
        };
        let motions = data
            .get("motions")
            .filter(|value| value.is_object())
            .or_else(|| data.pointer("/FileReferences/Motions"));
        let Some(motions) = motions.and_then(Value::as_object) else {
            return Vec::new();
        };
        let mut names = motions
            .keys()
            .filter(|name| !name.is_empty())
            .cloned()
            .collect::<Vec<_>>();
        names.sort();
        names
    }

    pub fn expression_names(&self, character: &str, costume: &str) -> Vec<String> {
        let path = self.model_json_path(character, costume);
        let Ok(data) = self.read_model_json(&path) else {
            return Vec::new();
        };
        let expressions = data
            .get("expressions")
            .filter(|value| value.is_array())
            .or_else(|| data.pointer("/FileReferences/Expressions"));
        let Some(expressions) = expressions.and_then(Value::as_array) else {
            return Vec::new();
        };
        let mut names = expressions
            .iter()
            .filter_map(Value::as_object)
            .filter_map(|item| item.get("name").or_else(|| item.get("Name")))
            .filter_map(Value::as_str)
            .filter(|name| !name.is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>();
        names.sort();
        names
    }

    pub fn character_image_path(&self, character: &str) -> String {
        self.character_images
            .get(character)
            .filter(|path| !is_virtual_path(path))
            .cloned()
            .unwrap_or_default()
    }

    pub fn character_image_data(&self, character: &str) -> Vec<u8> {
        self.character_images
            .get(character)
            .filter(|path| is_virtual_path(path))
            .and_then(|path| load_virtual_bytes(path).ok())
            .unwrap_or_default()
    }

    pub fn band_characters(&self, band_id: &str) -> &[String] {
        self.bands
            .iter()
            .find(|band| band.id == band_id)
            .map(|band| band.characters.as_slice())
            .unwrap_or(&[])
    }

    pub fn character_band(&self, character: &str) -> &str {
        self.bands
            .iter()
            .find(|band| band.characters.iter().any(|item| item == character))
            .map(|band| band.id.as_str())
            .unwrap_or("")
    }

    pub fn has_advanced_roleplay(&self, character: &str) -> bool {
        let display = self.display_name(character);
        fs::read_dir(self.paths.characters_dir.join(display))
            .ok()
            .into_iter()
            .flatten()
            .filter_map(Result::ok)
            .any(|entry| {
                entry.path().is_file()
                    && entry
                        .path()
                        .extension()
                        .is_some_and(|extension| extension.eq_ignore_ascii_case("md"))
            })
    }

    fn scan_root(&mut self, root: &ModelRoot) {
        let Ok(entries) = sorted_entries(&root.path) else {
            return;
        };
        for entry in entries.iter().filter(|entry| entry.path().is_dir()) {
            self.scan_model_directory(&entry.path(), root.override_existing);
        }
        for entry in entries.iter().filter(|entry| {
            entry.path().is_file()
                && entry
                    .path()
                    .extension()
                    .is_some_and(|extension| extension.eq_ignore_ascii_case("zst"))
        }) {
            if let Ok(result) = scan_model_archive(&entry.path()) {
                self.apply_archive_result(result);
            }
        }
    }

    fn scan_model_directory(&mut self, character_dir: &Path, override_existing: bool) {
        let Some(character) = character_dir
            .file_name()
            .and_then(|name| name.to_str())
            .map(str::to_owned)
        else {
            return;
        };
        let mut costumes = Vec::new();
        if let Ok(entries) = sorted_entries(character_dir) {
            for entry in entries.into_iter().filter(|entry| entry.path().is_dir()) {
                let costume_dir = entry.path();
                let Some(manifest) = find_model_manifest(&costume_dir) else {
                    continue;
                };
                let Some(costume_id) = costume_dir
                    .file_name()
                    .and_then(|name| name.to_str())
                    .map(str::to_owned)
                else {
                    continue;
                };
                let path = absolute_string(&manifest);
                let format = self.model_format_from_path(&path);
                costumes.push(Costume {
                    id: costume_id.clone(),
                    path: path.clone(),
                    format,
                });
                if override_existing
                    || !self
                        .model_paths
                        .contains_key(&(character.clone(), costume_id.clone()))
                {
                    self.model_paths
                        .insert((character.clone(), costume_id), path);
                }
            }
        }
        if let Some(image) = find_directory_character_image(character_dir) {
            self.character_images.insert(character.clone(), image);
        }
        if !costumes.is_empty() {
            self.merge_costumes(&character, costumes, override_existing);
        }
    }

    fn apply_archive_result(&mut self, result: ArchiveScanResult) {
        for costume in &result.costumes {
            self.model_paths.insert(
                (result.character.clone(), costume.id.clone()),
                costume.path.clone(),
            );
        }
        if !result.image_path.is_empty() {
            self.character_images
                .insert(result.character.clone(), result.image_path);
        }
        self.merge_costumes(&result.character, result.costumes, true);
    }

    fn merge_costumes(&mut self, character: &str, costumes: Vec<Costume>, replace: bool) {
        self.ensure_character(character);
        let info = self
            .characters
            .get_mut(character)
            .expect("character exists");
        for costume in costumes {
            if replace || !info.costumes.contains_key(&costume.id) {
                info.costumes.insert(costume.id.clone(), costume);
            }
        }
    }

    fn ensure_character(&mut self, character: &str) {
        if !self.characters.contains_key(character) {
            self.character_order.push(character.to_owned());
            self.characters
                .insert(character.to_owned(), CharacterInfo::default());
        }
    }

    fn model_format_from_path(&self, path: &str) -> ModelFormat {
        if path.to_ascii_lowercase().ends_with(".model3.json") {
            return ModelFormat::Moc3;
        }
        self.read_model_json(path)
            .ok()
            .map(|value| model_format_from_data(&value))
            .unwrap_or(ModelFormat::Moc)
    }

    fn read_model_json(&self, path: &str) -> Result<Value, ModelError> {
        if path.is_empty() {
            return Err(ModelError::InvalidVirtualPath(path.into()));
        }
        if let Some(value) = self
            .model_json_cache
            .read()
            .expect("model cache lock poisoned")
            .get(path)
            .cloned()
        {
            return Ok(value);
        }
        let data: Value = if is_virtual_path(path) {
            serde_json::from_slice(&load_virtual_bytes(path)?)?
        } else {
            serde_json::from_slice(&fs::read(path)?)?
        };
        self.model_json_cache
            .write()
            .expect("model cache lock poisoned")
            .insert(path.to_owned(), data.clone());
        Ok(data)
    }

    fn parse_outfit_json(&mut self) {
        let Ok(data) = read_json(&self.paths.outfit_json) else {
            return;
        };
        let Some(characters) = data.get("characters").and_then(Value::as_object) else {
            return;
        };
        for (character, value) in characters {
            self.ensure_character(character);
            let Some(info) = value.as_object() else {
                continue;
            };
            let display = info
                .get("display")
                .and_then(Value::as_str)
                .unwrap_or(character)
                .to_owned();
            self.characters
                .get_mut(character)
                .expect("character exists")
                .display = Some(display);
            if let Some(costumes) = info.get("costumes").and_then(Value::as_object) {
                let names = self.costume_names.entry(character.clone()).or_default();
                for (id, name) in costumes {
                    if let Some(name) = name.as_str() {
                        names.insert(id.clone(), name.to_owned());
                    }
                }
            }
        }
    }

    fn parse_band_json(&mut self) {
        let configured = read_json(&self.paths.band_json)
            .ok()
            .and_then(|value| value.get("bands").and_then(Value::as_array).cloned())
            .unwrap_or_default();
        let mut configured_keys = HashSet::new();
        let mut seen = HashSet::new();
        for value in configured {
            let Some(band) = value.as_object() else {
                continue;
            };
            let configured_characters = band
                .get("characters")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            for character in &configured_characters {
                if let Some(character) = character.as_str().filter(|value| !value.is_empty()) {
                    configured_keys.insert(character.to_owned());
                }
            }
            let characters = configured_characters
                .iter()
                .filter_map(Value::as_str)
                .filter(|character| {
                    self.characters.contains_key(*character) && !self.costumes(character).is_empty()
                })
                .map(str::to_owned)
                .collect::<Vec<_>>();
            if characters.is_empty() {
                continue;
            }
            seen.extend(characters.iter().cloned());
            let id = band.get("id").and_then(Value::as_str).unwrap_or_default();
            let display = band.get("display").and_then(Value::as_str).unwrap_or(id);
            let logo = band
                .get("logo")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .map(|value| absolute_string(&self.paths.base_dir.join(value)))
                .unwrap_or_default();
            self.bands.push(Band {
                id: id.into(),
                display: display.into(),
                logo,
                characters,
            });
        }

        let ungrouped = self
            .character_order
            .iter()
            .filter(|character| {
                !configured_keys.contains(*character)
                    && !seen.contains(*character)
                    && !self.costumes(character).is_empty()
            })
            .cloned()
            .collect::<Vec<_>>();
        if !ungrouped.is_empty() {
            self.bands.push(Band {
                id: "custom_models".into(),
                display: self.paths.custom_models_label.clone(),
                logo: String::new(),
                characters: ungrouped,
            });
        }
    }
}

#[derive(Debug)]
struct ArchiveScanResult {
    character: String,
    costumes: Vec<Costume>,
    image_path: String,
}

fn scan_model_archive(path: &Path) -> Result<ArchiveScanResult, ModelError> {
    let files = list_archive_files(path)?;
    let character = path
        .file_stem()
        .and_then(|name| name.to_str())
        .unwrap_or_default()
        .to_owned();
    let archive = absolute_string(path);
    let mut costumes = BTreeMap::new();
    for member in &files {
        if !is_model_manifest_name(member) {
            continue;
        }
        let costume = member
            .rsplit_once('/')
            .map(|(parent, _)| parent.rsplit('/').next().unwrap_or("default"))
            .unwrap_or("default");
        costumes.insert(
            costume.to_owned(),
            Costume {
                id: costume.to_owned(),
                path: format!("{archive}{VIRTUAL_SEPARATOR}{member}"),
                format: if member.to_ascii_lowercase().ends_with(".model3.json") {
                    ModelFormat::Moc3
                } else {
                    ModelFormat::Moc
                },
            },
        );
    }
    let costumes: Vec<Costume> = costumes.into_values().collect();
    if costumes.is_empty() {
        return Err(ModelError::ArchiveMemberNotFound(format!(
            "model manifest in {}",
            path.display()
        )));
    }

    let image_path = ["png", "jpg", "webp"]
        .into_iter()
        .flat_map(|extension| {
            [
                format!("character.{extension}"),
                format!("{character}/character.{extension}"),
            ]
        })
        .find(|candidate| files.contains(candidate))
        .map(|member| format!("{archive}{VIRTUAL_SEPARATOR}{member}"))
        .unwrap_or_default();
    Ok(ArchiveScanResult {
        character,
        costumes,
        image_path,
    })
}

pub fn is_virtual_path(path: &str) -> bool {
    path.contains(VIRTUAL_SEPARATOR)
}

pub fn split_virtual_path(path: &str) -> Result<(PathBuf, String), ModelError> {
    let Some((archive, member)) = path.split_once(VIRTUAL_SEPARATOR) else {
        return Err(ModelError::InvalidVirtualPath(path.into()));
    };
    Ok((PathBuf::from(archive), normalize_archive_member(member)?))
}

pub fn load_virtual_bytes(path: &str) -> Result<Vec<u8>, ModelError> {
    let (archive_path, wanted) = split_virtual_path(path)?;
    let decoder = zstd::stream::read::Decoder::new(File::open(archive_path)?)?;
    let mut archive = Archive::new(decoder);
    for entry in archive.entries()? {
        let mut entry = entry?;
        if !entry.header().entry_type().is_file() {
            continue;
        }
        let Ok(name) = normalize_archive_member(&entry.path()?.to_string_lossy()) else {
            continue;
        };
        if name != wanted {
            continue;
        }
        return read_archive_entry(&mut entry, ARCHIVE_MEMBER_MAX_BYTES, &name);
    }
    Err(ModelError::ArchiveMemberNotFound(wanted))
}

pub fn list_archive_files(path: &Path) -> Result<Vec<String>, ModelError> {
    let decoder = zstd::stream::read::Decoder::new(File::open(path)?)?;
    let mut archive = Archive::new(decoder);
    let mut files = Vec::new();
    let mut entries = archive.entries()?;
    if let Some(first) = entries.next() {
        let mut first = first?;
        if first.header().entry_type().is_file() {
            if let Ok(name) = normalize_archive_member(&first.path()?.to_string_lossy()) {
                if name == ARCHIVE_INDEX_MEMBER {
                    let bytes = read_archive_entry(&mut first, ARCHIVE_INDEX_MAX_BYTES, &name)?;
                    let index: Value = serde_json::from_slice(&bytes).unwrap_or_default();
                    if let Some(indexed) = index.get("files").and_then(Value::as_array) {
                        let mut result = indexed
                            .iter()
                            .filter_map(Value::as_str)
                            .filter_map(|path| normalize_archive_member(path).ok())
                            .collect::<Vec<_>>();
                        result.sort();
                        return Ok(result);
                    }
                } else {
                    files.push(name);
                }
            }
        }
    }
    for entry in entries {
        let entry = entry?;
        if entry.header().entry_type().is_file() {
            if let Ok(name) = normalize_archive_member(&entry.path()?.to_string_lossy()) {
                files.push(name);
            }
        }
    }
    files.sort();
    Ok(files)
}

fn read_archive_entry<R: Read>(
    entry: &mut tar::Entry<'_, R>,
    limit: u64,
    name: &str,
) -> Result<Vec<u8>, ModelError> {
    if entry.size() > limit {
        return Err(ModelError::ArchiveMemberTooLarge(name.into()));
    }
    let mut bytes = Vec::new();
    entry.take(limit + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(ModelError::ArchiveMemberTooLarge(name.into()));
    }
    Ok(bytes)
}

fn normalize_archive_member(path: &str) -> Result<String, ModelError> {
    let mut normalized = path.replace('\\', "/");
    while normalized.starts_with("./") {
        normalized.drain(..2);
    }
    if normalized.is_empty() || normalized.starts_with('/') {
        return Err(ModelError::UnsafeArchivePath(path.into()));
    }
    if normalized
        .split('/')
        .any(|part| part.is_empty() || matches!(part, "." | ".."))
    {
        return Err(ModelError::UnsafeArchivePath(path.into()));
    }
    Ok(normalized)
}

fn sorted_entries(path: &Path) -> io::Result<Vec<fs::DirEntry>> {
    let mut entries = fs::read_dir(path)?
        .filter_map(Result::ok)
        .filter(|entry| !entry.file_name().to_string_lossy().starts_with('_'))
        .collect::<Vec<_>>();
    entries.sort_by_key(fs::DirEntry::file_name);
    Ok(entries)
}

fn find_model_manifest(costume_dir: &Path) -> Option<PathBuf> {
    let legacy = costume_dir.join("model.json");
    if legacy.is_file() {
        return Some(legacy);
    }
    sorted_entries(costume_dir)
        .ok()?
        .into_iter()
        .find_map(|entry| {
            let path = entry.path();
            (path.is_file()
                && path
                    .file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name.to_ascii_lowercase().ends_with(".model3.json")))
            .then_some(path)
        })
}

fn find_directory_character_image(character_dir: &Path) -> Option<String> {
    ["png", "jpg", "webp"]
        .into_iter()
        .map(|extension| character_dir.join(format!("character.{extension}")))
        .find(|path| path.exists())
        .map(|path| absolute_string(&path))
}

fn is_model_manifest_name(path: &str) -> bool {
    let name = path.rsplit('/').next().unwrap_or(path).to_ascii_lowercase();
    name == "model.json" || name.ends_with(".model3.json")
}

fn model_format_from_data(data: &Value) -> ModelFormat {
    if data.get("FileReferences").is_some_and(Value::is_object)
        || data
            .get("Version")
            .is_some_and(|value| value.to_string().trim_matches('"').starts_with('3'))
    {
        ModelFormat::Moc3
    } else {
        ModelFormat::Moc
    }
}

fn read_json(path: &Path) -> Result<Value, ModelError> {
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn absolute_string(path: &Path) -> String {
    dunce::canonicalize(path)
        .unwrap_or_else(|_| {
            if path.is_absolute() {
                path.to_path_buf()
            } else {
                std::env::current_dir().unwrap_or_default().join(path)
            }
        })
        .to_string_lossy()
        .into_owned()
}

fn title_case(value: &str) -> String {
    let mut uppercase_next = true;
    value
        .chars()
        .map(|character| {
            if !character.is_alphabetic() {
                uppercase_next = true;
                character
            } else if uppercase_next {
                uppercase_next = false;
                character.to_ascii_uppercase()
            } else {
                character
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::Cursor;
    use tar::{Builder as TarBuilder, Header};

    fn paths(root: &Path) -> ModelManagerPaths {
        ModelManagerPaths {
            base_dir: root.into(),
            search_roots: vec![ModelRoot {
                path: root.join("models"),
                override_existing: false,
            }],
            lookup_roots: vec![root.join("models")],
            outfit_json: root.join("outfit.json"),
            band_json: root.join("band.json"),
            characters_dir: root.join("characters"),
            custom_models_label: "Custom Models".into(),
        }
    }

    fn write_model(path: &Path, value: Value) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    }

    fn write_archive(path: &Path, members: &[(&str, &[u8])]) {
        let file = File::create(path).unwrap();
        let mut encoder = zstd::stream::write::Encoder::new(file, 1).unwrap();
        {
            let mut archive = TarBuilder::new(&mut encoder);
            let index = serde_json::to_vec(&json!({
                "files": members.iter().map(|(name, _)| name).collect::<Vec<_>>()
            }))
            .unwrap();
            append(&mut archive, ARCHIVE_INDEX_MEMBER, &index);
            for (name, bytes) in members {
                append(&mut archive, name, bytes);
            }
            archive.finish().unwrap();
        }
        encoder.finish().unwrap();
    }

    fn append<W: io::Write>(archive: &mut TarBuilder<W>, name: &str, bytes: &[u8]) {
        let mut header = Header::new_gnu();
        header.set_size(bytes.len() as u64);
        header.set_mode(0o644);
        header.set_cksum();
        archive
            .append_data(&mut header, name, Cursor::new(bytes))
            .unwrap();
    }

    #[test]
    fn directory_scan_detects_moc3_metadata_and_names() {
        let temp = tempfile::tempdir().unwrap();
        let model = temp.path().join("models/anon/live_01/test.model3.json");
        write_model(
            &model,
            json!({
                "Version": 3,
                "FileReferences": {
                    "Motions": {"smile": [], "angry": []},
                    "Expressions": [{"Name": "smile"}, {"Name": "angry"}]
                }
            }),
        );
        let manager = ModelManager::scan(paths(temp.path()));
        assert_eq!(
            manager.model_format("anon", "live_01"),
            Some(ModelFormat::Moc3)
        );
        assert_eq!(manager.motion_names("anon", "live_01"), ["angry", "smile"]);
        assert_eq!(
            manager.expression_names("anon", "live_01"),
            ["angry", "smile"]
        );
    }

    #[test]
    fn archive_overrides_folder_and_exposes_virtual_image() {
        let temp = tempfile::tempdir().unwrap();
        let models = temp.path().join("models");
        fs::create_dir_all(&models).unwrap();
        write_model(
            &models.join("mutsumi/default/model.json"),
            json!({"model": "base.moc"}),
        );
        let archive = models.join("mutsumi.zst");
        write_archive(
            &archive,
            &[
                ("default/test.model3.json", br#"{"Version":3}"#),
                ("character.png", b"image"),
            ],
        );

        let manager = ModelManager::scan(paths(temp.path()));
        let path = manager.model_json_path("mutsumi", "default");
        assert!(path.contains("mutsumi.zst::default/test.model3.json"));
        assert_eq!(
            manager.model_format("mutsumi", "default"),
            Some(ModelFormat::Moc3)
        );
        assert_eq!(manager.character_image_data("mutsumi"), b"image");
        assert!(manager.character_image_path("mutsumi").is_empty());
    }

    #[test]
    fn archive_without_model_manifest_is_ignored() {
        let temp = tempfile::tempdir().unwrap();
        let models = temp.path().join("models");
        fs::create_dir_all(&models).unwrap();
        write_archive(&models.join("invalid.zst"), &[("character.png", b"image")]);

        let manager = ModelManager::scan(paths(temp.path()));
        assert!(!manager.characters().iter().any(|item| item == "invalid"));
    }

    #[test]
    fn outfit_names_bands_and_default_costume_match_python_rules() {
        let temp = tempfile::tempdir().unwrap();
        write_model(
            &temp.path().join("models/kasumi/casual/model.json"),
            json!({"model": "base.moc"}),
        );
        write_model(
            &temp.path().join("models/custom/default/model.json"),
            json!({"model": "base.moc"}),
        );
        fs::write(
            temp.path().join("outfit.json"),
            serde_json::to_vec(&json!({
                "characters": {"kasumi": {"display": "户山香澄", "costumes": {"casual": "便服"}}}
            }))
            .unwrap(),
        )
        .unwrap();
        fs::write(
            temp.path().join("band.json"),
            serde_json::to_vec(&json!({
                "bands": [{"id": "poppinparty", "display": "Poppin'Party", "characters": ["kasumi"]}]
            }))
            .unwrap(),
        )
        .unwrap();

        let manager = ModelManager::scan(paths(temp.path()));
        assert_eq!(manager.display_name("kasumi"), "户山香澄");
        assert_eq!(manager.costume_display_name("kasumi", "casual"), "便服");
        assert_eq!(manager.default_costume("kasumi"), "casual");
        assert_eq!(manager.character_band("kasumi"), "poppinparty");
        assert_eq!(manager.character_band("custom"), "custom_models");
        assert_eq!(manager.display_name("custom_character"), "Custom_Character");
    }

    #[test]
    fn generated_python_metadata_vectors_match_rust() {
        let vectors: Value =
            serde_json::from_str(include_str!("../../../compat/model_vectors.json")).unwrap();
        let cases = vectors.get("cases").and_then(Value::as_array).unwrap();
        let temp = tempfile::tempdir().unwrap();
        for case in cases {
            let name = case.get("name").and_then(Value::as_str).unwrap();
            let manifest = case.get("manifest").and_then(Value::as_str).unwrap();
            write_model(
                &temp.path().join("models/fixture").join(name).join(manifest),
                case.get("data").cloned().unwrap(),
            );
        }
        let manager = ModelManager::scan(paths(temp.path()));
        for case in cases {
            let name = case.get("name").and_then(Value::as_str).unwrap();
            assert_eq!(
                manager
                    .model_format("fixture", name)
                    .map(ModelFormat::as_str),
                case.get("expected_format").and_then(Value::as_str)
            );
            assert_eq!(
                manager.motion_names("fixture", name),
                case.get("expected_motions")
                    .and_then(Value::as_array)
                    .unwrap()
                    .iter()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
            );
            assert_eq!(
                manager.expression_names("fixture", name),
                case.get("expected_expressions")
                    .and_then(Value::as_array)
                    .unwrap()
                    .iter()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
            );
        }
    }
}
