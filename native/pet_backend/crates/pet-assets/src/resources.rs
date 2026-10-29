use std::path::Path;

use serde::Serialize;

use crate::virtual_path::ModelPath;
use crate::{ArchiveCache, CacheError};

#[derive(Debug, Serialize)]
pub(crate) struct Costume {
    id: String,
    path: String,
    format: &'static str,
}

#[derive(Debug, Serialize)]
pub(crate) struct CatalogEntry {
    character: String,
    costumes: Vec<Costume>,
    image_path: String,
    model_paths: Vec<(String, String, String)>,
}

impl ArchiveCache {
    /// Enumerates manifest names without reading model JSON or textures.
    pub(crate) fn scan_model_archive(
        &mut self,
        archive: &Path,
    ) -> Result<Option<CatalogEntry>, CacheError> {
        let files = self.list_files(archive)?;
        let archive = std::fs::canonicalize(archive).map_err(|e| CacheError::Io(e.to_string()))?;
        let character = archive
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        let mut costumes = Vec::new();
        let mut model_paths = Vec::new();
        for member in &files {
            let name = member
                .rsplit('/')
                .next()
                .unwrap_or(member)
                .to_ascii_lowercase();
            if name != "model.json" && !name.ends_with(".model3.json") {
                continue;
            }
            let costume = member
                .rsplit_once('/')
                .map(|(parent, _)| parent.rsplit('/').next().unwrap())
                .unwrap_or("default");
            let path = spec(&archive, member)?;
            costumes.push(Costume {
                id: costume.into(),
                path: path.clone(),
                format: if name.ends_with(".model3.json") {
                    "moc3"
                } else {
                    "moc"
                },
            });
            model_paths.push((character.clone(), costume.into(), path));
        }
        if costumes.is_empty() {
            return Ok(None);
        }
        costumes.sort_by(|a, b| a.id.cmp(&b.id));
        let mut image_path = String::new();
        'portrait: for ext in ["png", "jpg", "webp"] {
            for candidate in [
                format!("character.{ext}"),
                format!("{character}/character.{ext}"),
            ] {
                if files.binary_search(&candidate).is_ok() {
                    image_path = spec(&archive, &candidate)?;
                    break 'portrait;
                }
            }
        }
        Ok(Some(CatalogEntry {
            character,
            costumes,
            image_path,
            model_paths,
        }))
    }
}

fn spec(archive: &Path, member: &str) -> Result<String, CacheError> {
    let archive = archive.to_string_lossy();
    // canonicalize uses extended Windows paths for IO; keep the public virtual
    // path compatible with pathlib.resolve and existing config/catalog files.
    let archive = if let Some(unc) = archive.strip_prefix("\\\\?\\UNC\\") {
        format!("\\\\{unc}")
    } else {
        archive
            .strip_prefix("\\\\?\\")
            .unwrap_or(&archive)
            .to_owned()
    };
    ModelPath::new(archive, member)
        .map(|path| path.to_spec())
        .map_err(|e| CacheError::Path(e.to_string()))
}
