use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

const GL_TYPEDEF_MARKER: &str =
    r#"ffi.cdef("typedef void (" .. CC .. "*PFNGLGENERATEMIPMAPPROC)(GLenum target);")"#;
const GL_CORE_TYPEDEFS: &str = r#"
ffi.cdef("typedef void (" .. CC .. "*PFNGLCLEARPROC)(GLbitfield mask);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLCLEARCOLORPROC)(GLfloat red, GLfloat green, GLfloat blue, GLfloat alpha);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLVIEWPORTPROC)(GLint x, GLint y, GLsizei width, GLsizei height);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLENABLEPROC)(GLenum cap);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDISABLEPROC)(GLenum cap);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLCOLORMASKPROC)(GLboolean red, GLboolean green, GLboolean blue, GLboolean alpha);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLFRONTFACEPROC)(GLenum mode);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLBINDTEXTUREPROC)(GLenum target, GLuint texture);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDELETETEXTURESPROC)(GLsizei n, const GLuint *textures);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLGETINTEGERVPROC)(GLenum pname, GLint *data);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLGENTEXTURESPROC)(GLsizei n, GLuint *textures);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLTEXPARAMETERIPROC)(GLenum target, GLenum pname, GLint param);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLTEXIMAGE2DPROC)(GLenum target, GLint level, GLint internalformat, GLsizei width, GLsizei height, GLint border, GLenum format, GLenum type, const void *pixels);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDRAWELEMENTSPROC)(GLenum mode, GLsizei count, GLenum type, const void *indices);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLREADPIXELSPROC)(GLint x, GLint y, GLsizei width, GLsizei height, GLenum format, GLenum type, void *pixels);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLDRAWARRAYSPROC)(GLenum mode, GLint first, GLsizei count);")
ffi.cdef("typedef void (" .. CC .. "*PFNGLBLENDFUNCPROC)(GLenum sfactor, GLenum dfactor);")
"#;
const GL_CORE_LOADER: &str = r#"
local function loadCoreFromHostContext()
    if type(_G.__bandori_gl_get_proc_address) ~= "function" then return end
    local core = {
        {"glClear", "PFNGLCLEARPROC"}, {"glClearColor", "PFNGLCLEARCOLORPROC"},
        {"glViewport", "PFNGLVIEWPORTPROC"}, {"glEnable", "PFNGLENABLEPROC"},
        {"glDisable", "PFNGLDISABLEPROC"}, {"glColorMask", "PFNGLCOLORMASKPROC"},
        {"glFrontFace", "PFNGLFRONTFACEPROC"}, {"glBindTexture", "PFNGLBINDTEXTUREPROC"},
        {"glDeleteTextures", "PFNGLDELETETEXTURESPROC"}, {"glGetIntegerv", "PFNGLGETINTEGERVPROC"},
        {"glGenTextures", "PFNGLGENTEXTURESPROC"}, {"glTexParameteri", "PFNGLTEXPARAMETERIPROC"},
        {"glTexImage2D", "PFNGLTEXIMAGE2DPROC"}, {"glDrawElements", "PFNGLDRAWELEMENTSPROC"},
        {"glReadPixels", "PFNGLREADPIXELSPROC"}, {"glDrawArrays", "PFNGLDRAWARRAYSPROC"},
        {"glBlendFunc", "PFNGLBLENDFUNCPROC"},
    }
    for _, item in ipairs(core) do
        local ok, fn = pcall(loadGL, item[1], item[2])
        if ok and fn ~= nil then gl[item[1]] = fn end
    end
end
loadCoreFromHostContext()
"#;

#[derive(Debug, Error)]
pub enum ModuleError {
    #[error("Lua module I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("Lua module root does not exist: {0}")]
    MissingRoot(PathBuf),
}

#[derive(Clone, Debug)]
pub struct ModuleSource {
    pub bytes: Vec<u8>,
    pub chunk_name: String,
}

#[derive(Clone, Debug)]
pub struct ModuleCatalog {
    root: PathBuf,
    modules: BTreeMap<String, PathBuf>,
}

impl ModuleCatalog {
    pub fn scan(root: impl AsRef<Path>) -> Result<Self, ModuleError> {
        let root = root.as_ref().to_path_buf();
        if !root.is_dir() {
            return Err(ModuleError::MissingRoot(root));
        }
        let mut modules = BTreeMap::new();
        scan_directory(&root, &root, &mut modules)?;
        Ok(Self { root, modules })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn contains(&self, module_name: &str) -> bool {
        self.modules.contains_key(module_name)
    }

    pub fn add_module_file(
        &mut self,
        module_name: impl Into<String>,
        path: impl AsRef<Path>,
    ) -> Result<(), ModuleError> {
        let path = path.as_ref();
        if !path.is_file() {
            return Err(ModuleError::Io(io::Error::new(
                io::ErrorKind::NotFound,
                format!("Lua module file does not exist: {}", path.display()),
            )));
        }
        self.modules.insert(module_name.into(), path.to_path_buf());
        Ok(())
    }

    pub fn source(&self, module_name: &str) -> Result<Option<ModuleSource>, ModuleError> {
        let Some(path) = self.modules.get(module_name) else {
            return Ok(None);
        };
        let bytes = fs::read(path)?;
        Ok(Some(ModuleSource {
            bytes: patch_module(module_name, bytes),
            chunk_name: format!("@{}", path.to_string_lossy().replace('\\', "/")),
        }))
    }
}

fn scan_directory(
    root: &Path,
    directory: &Path,
    modules: &mut BTreeMap<String, PathBuf>,
) -> Result<(), io::Error> {
    let mut entries = fs::read_dir(directory)?.collect::<Result<Vec<_>, _>>()?;
    entries.sort_by_key(std::fs::DirEntry::path);
    for entry in entries {
        let path = entry.path();
        if path.is_dir() {
            scan_directory(root, &path, modules)?;
            continue;
        }
        let Some(module_name) = module_name(&path, root) else {
            continue;
        };
        let prefer = modules.get(&module_name).is_none_or(|current| {
            current.extension().and_then(|value| value.to_str()) != Some("ljbc")
        });
        if prefer {
            modules.insert(module_name, path);
        }
    }
    Ok(())
}

fn module_name(path: &Path, root: &Path) -> Option<String> {
    let extension = path.extension()?.to_str()?;
    if !matches!(extension, "lua" | "ljbc") {
        return None;
    }
    let relative = path.strip_prefix(root).ok()?.with_extension("");
    let mut parts = relative
        .components()
        .map(|part| part.as_os_str().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    if parts.last().is_some_and(|part| part == "init") {
        parts.pop();
    }
    (!parts.is_empty()).then(|| parts.join("."))
}

fn patch_module(module_name: &str, bytes: Vec<u8>) -> Vec<u8> {
    let mut source = match String::from_utf8(bytes) {
        Ok(source) => source,
        Err(error) => return error.into_bytes(),
    };
    source = source.replace("\r\n", "\n");
    if module_name == "live2d.gl_loader" {
        if !source.contains("PFNGLCLEARPROC") {
            source = source.replacen(
                GL_TYPEDEF_MARKER,
                &format!("{GL_TYPEDEF_MARKER}{GL_CORE_TYPEDEFS}"),
                1,
            );
        }
        if !source.contains("loadCoreFromHostContext()") {
            source = source.replacen(
                "\nfunction gl.ensureExtensions()",
                &format!("{GL_CORE_LOADER}\nfunction gl.ensureExtensions()"),
                1,
            );
        }
    } else if module_name == "live2d_moc3_pet_embed" {
        source = patch_moc3_pet_embed(source);
    }
    source.into_bytes()
}

fn patch_moc3_pet_embed(mut source: String) -> String {
    if source.contains("function Renderer:resize_renderer") {
        return source;
    }
    source = source.replacen(
        "        height = math.max(tonumber(height) or 1, 1),\n        offset_x = 0,",
        "        height = math.max(tonumber(height) or 1, 1),\n        render_width = math.max(tonumber(width) or 1, 1),\n        render_height = math.max(tonumber(height) or 1, 1),\n        offset_x = 0,",
        1,
    );
    source = source.replacen(
        r#"function Renderer:resize(width, height)
    self.width = math.max(tonumber(width) or self.width or 1, 1)
    self.height = math.max(tonumber(height) or self.height or 1, 1)
    gl.glViewport(0, 0, self.width, self.height)
    local runtime = self.renderer and self.renderer:get_runtime() or nil
    self.projection = new_projection(self.width, self.height, runtime, self.offset_x, self.offset_y, self.scale)
    return self
end"#,
        r#"function Renderer:resize(width, height)
    self.width = math.max(tonumber(width) or self.width or 1, 1)
    self.height = math.max(tonumber(height) or self.height or 1, 1)
    return self:resize_renderer(self.width, self.height)
end

function Renderer:resize_renderer(width, height)
    self.render_width = math.max(tonumber(width) or self.render_width or self.width or 1, 1)
    self.render_height = math.max(tonumber(height) or self.render_height or self.height or 1, 1)
    gl.glViewport(0, 0, self.render_width, self.render_height)
    local runtime = self.renderer and self.renderer:get_runtime() or nil
    self.projection = new_projection(self.render_width, self.render_height, runtime, self.offset_x, self.offset_y, self.scale)
    return self
end"#,
        1,
    );
    source = source.replace(
        "    return self:resize(self.width, self.height)\nend",
        "    return self:resize_renderer(self.render_width, self.render_height)\nend",
    );
    source
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn bytecode_precedes_source_and_init_maps_to_parent_module() {
        let temp = tempdir().unwrap();
        fs::create_dir(temp.path().join("pkg")).unwrap();
        fs::write(temp.path().join("pkg/init.lua"), "return 'source'").unwrap();
        fs::write(temp.path().join("pkg/init.ljbc"), b"bytecode").unwrap();
        let catalog = ModuleCatalog::scan(temp.path()).unwrap();
        assert_eq!(catalog.source("pkg").unwrap().unwrap().bytes, b"bytecode");
    }

    #[test]
    fn non_utf8_bytecode_is_preserved_verbatim() {
        let temp = tempdir().unwrap();
        let bytecode = [0x1b, 0x4c, 0x4a, 0xff, 0x00];
        fs::write(temp.path().join("binary.ljbc"), bytecode).unwrap();
        let catalog = ModuleCatalog::scan(temp.path()).unwrap();
        assert_eq!(catalog.source("binary").unwrap().unwrap().bytes, bytecode);
    }

    #[test]
    fn project_gl_and_moc3_modules_receive_host_patches() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../..")
            .join("third_party/Live2D-v2-Lua");
        let catalog = ModuleCatalog::scan(root).unwrap();
        let gl =
            String::from_utf8(catalog.source("live2d.gl_loader").unwrap().unwrap().bytes).unwrap();
        assert!(gl.contains("PFNGLCLEARPROC"));
        assert!(gl.contains("loadCoreFromHostContext"));
        let moc3 = String::from_utf8(
            catalog
                .source("live2d_moc3_pet_embed")
                .unwrap()
                .unwrap()
                .bytes,
        )
        .unwrap();
        assert!(moc3.contains("function Renderer:resize_renderer"));
        assert!(moc3.contains("render_width"));
    }
}
