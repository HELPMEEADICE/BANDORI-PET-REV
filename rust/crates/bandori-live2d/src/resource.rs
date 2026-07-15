use bandori_core::model::{ModelError, is_virtual_path, load_virtual_bytes, split_virtual_path};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Clone, Debug)]
pub struct ResourceRoots {
    pub bundled_models: PathBuf,
    pub user_models: PathBuf,
}

#[derive(Clone, Debug)]
pub struct ModelResourceLoader {
    roots: ResourceRoots,
}

#[derive(Debug, Error)]
pub enum ResourceError {
    #[error("model resource I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("model archive read failed: {0}")]
    Model(#[from] ModelError),
    #[error("model resource is outside configured model roots: {0}")]
    OutsideRoots(PathBuf),
}

impl ModelResourceLoader {
    pub fn new(roots: ResourceRoots) -> Self {
        Self { roots }
    }

    pub fn roots(&self) -> &ResourceRoots {
        &self.roots
    }

    pub fn read(&self, path: &str) -> Result<Vec<u8>, ResourceError> {
        let normalized = path.replace('\\', "/");
        if is_virtual_path(&normalized) {
            let (archive_path, _) = split_virtual_path(&normalized)?;
            self.require_allowed_existing(&archive_path)?;
            return load_virtual_bytes(&normalized).map_err(ResourceError::from);
        }

        let candidate = self.candidate_path(&normalized);
        match self.require_allowed_existing(&candidate) {
            Ok(path) => fs::read(path).map_err(ResourceError::from),
            Err(ResourceError::Io(error)) if error.kind() == io::ErrorKind::NotFound => {
                if let Some(fallback) = self.motion_fallback(&candidate) {
                    return fs::read(fallback).map_err(ResourceError::from);
                }
                Err(ResourceError::Io(error))
            }
            Err(error) => Err(error),
        }
    }

    pub fn resolve_existing(&self, path: &str) -> Result<PathBuf, ResourceError> {
        self.require_allowed_existing(&self.candidate_path(&path.replace('\\', "/")))
    }

    fn candidate_path(&self, path: &str) -> PathBuf {
        let candidate = PathBuf::from(path);
        if candidate.is_absolute() {
            candidate
        } else {
            self.roots.bundled_models.join(candidate)
        }
    }

    fn require_allowed_existing(&self, path: &Path) -> Result<PathBuf, ResourceError> {
        let resolved = dunce::canonicalize(path)?;
        let allowed = [&self.roots.bundled_models, &self.roots.user_models]
            .into_iter()
            .filter_map(|root| dunce::canonicalize(root).ok())
            .any(|root| resolved.starts_with(root));
        if allowed {
            Ok(resolved)
        } else {
            Err(ResourceError::OutsideRoots(resolved))
        }
    }

    fn motion_fallback(&self, original: &Path) -> Option<PathBuf> {
        let basename = original.file_name()?;
        let fallback_root = self.roots.bundled_models.join("_mtn_emp");
        let fallback_root = dunce::canonicalize(fallback_root).ok()?;
        find_named_file(&fallback_root, basename)
            .and_then(|path| self.require_allowed_existing(&path).ok())
    }
}

fn find_named_file(directory: &Path, basename: &std::ffi::OsStr) -> Option<PathBuf> {
    let mut entries = fs::read_dir(directory)
        .ok()?
        .filter_map(Result::ok)
        .collect::<Vec<_>>();
    entries.sort_by_key(fs::DirEntry::path);
    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            if let Some(found) = find_named_file(&path, basename) {
                return Some(found);
            }
        } else if path.file_name() == Some(basename) {
            return Some(path);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::File;
    use tar::{Builder as TarBuilder, Header};
    use tempfile::tempdir;

    fn loader(bundled: &Path, user: &Path) -> ModelResourceLoader {
        ModelResourceLoader::new(ResourceRoots {
            bundled_models: bundled.to_path_buf(),
            user_models: user.to_path_buf(),
        })
    }

    #[test]
    fn reads_relative_bundled_and_absolute_user_resources() {
        let temp = tempdir().unwrap();
        let bundled = temp.path().join("bundled");
        let user = temp.path().join("user");
        fs::create_dir_all(bundled.join("aya")).unwrap();
        fs::create_dir_all(user.join("ran")).unwrap();
        fs::write(bundled.join("aya/model.json"), b"aya").unwrap();
        fs::write(user.join("ran/model.json"), b"ran").unwrap();
        let loader = loader(&bundled, &user);

        assert_eq!(loader.read("aya/model.json").unwrap(), b"aya");
        assert_eq!(
            loader
                .read(&user.join("ran/model.json").to_string_lossy())
                .unwrap(),
            b"ran"
        );
    }

    #[test]
    fn an_absent_optional_user_root_does_not_block_bundled_resources() {
        let temp = tempdir().unwrap();
        let bundled = temp.path().join("bundled");
        let missing_user = temp.path().join("missing-user");
        fs::create_dir_all(&bundled).unwrap();
        fs::write(bundled.join("model.json"), b"model").unwrap();

        assert_eq!(
            loader(&bundled, &missing_user).read("model.json").unwrap(),
            b"model"
        );
    }

    #[test]
    fn rejects_files_outside_model_roots() {
        let temp = tempdir().unwrap();
        let bundled = temp.path().join("bundled");
        let user = temp.path().join("user");
        fs::create_dir_all(&bundled).unwrap();
        fs::create_dir_all(&user).unwrap();
        let outside = temp.path().join("secret.txt");
        fs::write(&outside, b"secret").unwrap();

        assert!(matches!(
            loader(&bundled, &user).read(&outside.to_string_lossy()),
            Err(ResourceError::OutsideRoots(_))
        ));
    }

    #[test]
    fn reads_virtual_resources_only_from_allowed_archives() {
        let temp = tempdir().unwrap();
        let bundled = temp.path().join("bundled");
        let user = temp.path().join("user");
        fs::create_dir_all(&bundled).unwrap();
        fs::create_dir_all(&user).unwrap();
        let archive_path = user.join("model.zst");
        let output = File::create(&archive_path).unwrap();
        let mut encoder = zstd::stream::write::Encoder::new(output, 1).unwrap();
        {
            let mut archive = TarBuilder::new(&mut encoder);
            let bytes = b"moc3";
            let mut header = Header::new_gnu();
            header.set_size(bytes.len() as u64);
            header.set_mode(0o644);
            header.set_cksum();
            archive
                .append_data(&mut header, "aya/model.moc3", &bytes[..])
                .unwrap();
            archive.finish().unwrap();
        }
        encoder.finish().unwrap();
        let virtual_path = format!("{}::aya/model.moc3", archive_path.to_string_lossy());

        assert_eq!(
            loader(&bundled, &user).read(&virtual_path).unwrap(),
            b"moc3"
        );
    }

    #[test]
    fn missing_motion_can_fall_back_to_shared_motion_directory() {
        let temp = tempdir().unwrap();
        let bundled = temp.path().join("bundled");
        let user = temp.path().join("user");
        fs::create_dir_all(bundled.join("_mtn_emp/nested")).unwrap();
        fs::create_dir_all(&user).unwrap();
        fs::write(bundled.join("_mtn_emp/nested/idle.mtn"), b"idle").unwrap();

        assert_eq!(
            loader(&bundled, &user).read("missing/idle.mtn").unwrap(),
            b"idle"
        );
    }
}
