use crate::module_catalog::{ModuleCatalog, ModuleError};
use crate::resource::{ModelResourceLoader, ResourceError};
use mlua::{Function, Lua, ObjectLike, RegistryKey, Table, Value};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::Arc;
use thiserror::Error;

const INSTALL_SEARCHER: &str = r#"
local loader = function(name)
    local chunk, chunk_name = __bandori_lazy_lua_module_source(name)
    if chunk == nil then return "\n\tno bundled Live2D module " .. name end
    local fn, err = load(chunk, chunk_name)
    if fn == nil then return "\n\t" .. tostring(err) end
    return fn
end
local loaders = package.searchers or package.loaders
table.insert(loaders, 1, loader)
"#;

pub type GlProcResolver = Arc<dyn Fn(&str) -> Option<usize> + Send + Sync>;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Live2dFormat {
    Moc,
    Moc3,
}

impl Live2dFormat {
    fn embed_module(self) -> &'static str {
        match self {
            Self::Moc => "live2d_embed",
            Self::Moc3 => "live2d_moc3_pet_embed",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(i32)]
pub enum MotionPriority {
    Idle = 1,
    Normal = 2,
    Force = 3,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum TextureQuality {
    Performance,
    #[default]
    Balanced,
}

impl TextureQuality {
    fn scale(self) -> f64 {
        match self {
            Self::Performance => 0.5,
            Self::Balanced => 1.0,
        }
    }

    fn mipmap(self) -> bool {
        self == Self::Balanced
    }

    fn bleed_passes(self) -> u8 {
        match self {
            Self::Performance => 0,
            Self::Balanced => 1,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ParameterValue {
    pub id: String,
    pub value: f64,
    pub weight: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FrameInput {
    pub time_msec: f64,
    pub delta_seconds: Option<f64>,
    pub frame_number: u64,
    pub parameters: Vec<ParameterValue>,
    pub clear: bool,
    pub clear_color: [f64; 4],
    pub gc_interval: u32,
    pub gc_step: u32,
}

impl Default for FrameInput {
    fn default() -> Self {
        Self {
            time_msec: 0.0,
            delta_seconds: None,
            frame_number: 0,
            parameters: Vec::new(),
            clear: false,
            clear_color: [0.0; 4],
            gc_interval: 20,
            gc_step: 400,
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
pub struct Live2dModelInfo {
    pub motion_names: Vec<String>,
    pub motions: BTreeMap<String, Vec<String>>,
    pub expressions: Vec<String>,
    pub hit_area_count: usize,
}

#[derive(Debug, Error)]
pub enum Live2dError {
    #[error("LuaJIT runtime failed: {0}")]
    Lua(#[from] mlua::Error),
    #[error("Live2D Lua module catalog failed: {0}")]
    Module(#[from] ModuleError),
    #[error("Live2D model resource failed: {0}")]
    Resource(#[from] ResourceError),
    #[error("renderer has already been disposed")]
    Disposed,
    #[error("render-only replay is only supported by the Cubism 3 pipeline")]
    RenderOnlyUnsupported,
}

pub struct Live2dRuntime {
    lua: Lua,
    format: Live2dFormat,
    renderer: Option<RegistryKey>,
    resource_loader: ModelResourceLoader,
}

impl Live2dRuntime {
    /// Creates one isolated LuaJIT state and renderer. Call this only while the
    /// owning Qt OpenGL context is current.
    pub fn new(
        format: Live2dFormat,
        module_root: impl AsRef<Path>,
        resource_loader: ModelResourceLoader,
        gl_resolver: GlProcResolver,
        width: u32,
        height: u32,
    ) -> Result<Self, Live2dError> {
        let module_root = module_root.as_ref();
        let mut catalog = ModuleCatalog::scan(module_root)?;
        if format == Live2dFormat::Moc && !catalog.contains("live2d_platform_manager_override") {
            if let Some(path) =
                find_host_module(module_root, "live2d_platform_manager_override.lua")
            {
                catalog.add_module_file("live2d_platform_manager_override", path)?;
            }
        }
        // Live2D-v2-Lua requires LuaJIT's FFI library. `unsafe_new` enables
        // native modules, so the catalog root must contain only application-
        // bundled, trusted Lua code. Model files never enter the module loader.
        let lua = unsafe { Lua::unsafe_new() };
        install_module_searcher(&lua, catalog)?;
        install_gl_resolver(&lua, gl_resolver)?;
        lua.load(r#"assert(require("ffi"), "LuaJIT FFI is required")"#)
            .exec()?;

        if format == Live2dFormat::Moc {
            lua.load(
                r#"
                local source = require("live2d_platform_manager_override")
                package.loaded["live2d.platform_manager"] = source
                "#,
            )
            .exec()?;
        }

        let embed: Table = require_module(&lua, format.embed_module())?;
        let init: Function = embed.get("init")?;
        init.call::<()>(())?;
        let new_renderer: Function = embed.get("new")?;
        let renderer: Table = new_renderer.call((width.max(1), height.max(1)))?;
        let renderer = lua.create_registry_value(renderer)?;
        Ok(Self {
            lua,
            format,
            renderer: Some(renderer),
            resource_loader,
        })
    }

    pub fn format(&self) -> Live2dFormat {
        self.format
    }

    pub fn load_model(
        &self,
        model_path: &str,
        width: u32,
        height: u32,
    ) -> Result<Live2dModelInfo, Live2dError> {
        self.load_model_with_quality(model_path, width, height, TextureQuality::Balanced)
    }

    pub fn load_model_with_quality(
        &self,
        model_path: &str,
        width: u32,
        height: u32,
        quality: TextureQuality,
    ) -> Result<Live2dModelInfo, Live2dError> {
        let options = self.model_options(model_path, quality)?;
        self.renderer_table()?.call_method::<Value>(
            "load_model",
            (model_path, width.max(1), height.max(1), options),
        )?;
        self.model_info()
    }

    pub fn resize(&self, width: u32, height: u32) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("resize", (width.max(1), height.max(1)))?;
        Ok(())
    }

    pub fn resize_renderer(&self, width: u32, height: u32) -> Result<(), Live2dError> {
        let renderer = self.renderer_table()?;
        let function: Option<Function> = renderer.get("resize_renderer")?;
        let method = if function.is_some() {
            "resize_renderer"
        } else {
            "resize"
        };
        renderer.call_method::<Value>(method, (width.max(1), height.max(1)))?;
        Ok(())
    }

    pub fn draw(&self, frame: &FrameInput) -> Result<(), Live2dError> {
        let options = self.frame_options(frame)?;
        self.renderer_table()?
            .call_method::<Value>("draw", options)?;
        Ok(())
    }

    pub fn render_only(&self, frame: &FrameInput) -> Result<(), Live2dError> {
        if self.format != Live2dFormat::Moc3 {
            return Err(Live2dError::RenderOnlyUnsupported);
        }
        let options = self.frame_options(frame)?;
        self.renderer_table()?
            .call_method::<Value>("render_frame", options)?;
        Ok(())
    }

    pub fn drag(&self, x: f64, y: f64) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("drag", (x, y))?;
        Ok(())
    }

    pub fn set_offset(&self, x: f64, y: f64) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("set_offset", (x, y))?;
        Ok(())
    }

    pub fn set_scale(&self, scale: f64) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("set_scale", scale)?;
        Ok(())
    }

    pub fn set_parameter(&self, parameter: &ParameterValue) -> Result<(), Live2dError> {
        self.renderer_table()?.call_method::<Value>(
            "set_parameter",
            (parameter.id.as_str(), parameter.value, parameter.weight),
        )?;
        Ok(())
    }

    pub fn start_motion(
        &self,
        group: &str,
        index: usize,
        priority: MotionPriority,
        looping: bool,
    ) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("start_motion", (group, index, priority as i32, looping))?;
        Ok(())
    }

    pub fn clear_motions(&self) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("clear_motions", ())?;
        Ok(())
    }

    pub fn is_motion_finished(&self) -> Result<bool, Live2dError> {
        Ok(self
            .renderer_table()?
            .call_method::<bool>("is_motion_finished", ())?)
    }

    pub fn set_expression(&self, expression: &str) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("set_expression", expression)?;
        Ok(())
    }

    pub fn reset_expression(&self) -> Result<(), Live2dError> {
        self.renderer_table()?
            .call_method::<Value>("reset_expression", ())?;
        Ok(())
    }

    pub fn hit_test(&self, x: f64, y: f64) -> Result<Vec<String>, Live2dError> {
        let hits: Table = self.renderer_table()?.call_method("hit_test", (x, y))?;
        hits.sequence_values::<String>()
            .collect::<Result<Vec<_>, _>>()
            .map_err(Live2dError::from)
    }

    pub fn model_info(&self) -> Result<Live2dModelInfo, Live2dError> {
        let info: Table = self.renderer_table()?.call_method("model_info", ())?;
        let motion_names = table_strings(info.get::<Table>("motion_names")?)?;
        let motion_table: Table = info.get("motions")?;
        let mut motions = BTreeMap::new();
        for name in &motion_names {
            let group = motion_table
                .get::<Option<Table>>(name.as_str())?
                .map(table_strings)
                .transpose()?
                .unwrap_or_default();
            motions.insert(name.clone(), group);
        }
        let expression_table: Table = info.get("expressions")?;
        let mut expressions = expression_table
            .pairs::<String, Value>()
            .filter_map(|entry| entry.ok().map(|(name, _)| name))
            .collect::<Vec<_>>();
        expressions.sort();
        Ok(Live2dModelInfo {
            motion_names,
            motions,
            expressions,
            hit_area_count: info.get::<Option<usize>>("hit_area_count")?.unwrap_or(0),
        })
    }

    pub fn dispose(&mut self) -> Result<(), Live2dError> {
        let Some(key) = self.renderer.take() else {
            return Ok(());
        };
        let renderer: Table = self.lua.registry_value(&key)?;
        let result = renderer.call_method::<Value>("dispose", ());
        self.lua.remove_registry_value(key)?;
        result?;
        Ok(())
    }

    fn renderer_table(&self) -> Result<Table, Live2dError> {
        let key = self.renderer.as_ref().ok_or(Live2dError::Disposed)?;
        self.lua.registry_value(key).map_err(Live2dError::from)
    }

    fn frame_options(&self, frame: &FrameInput) -> Result<Table, Live2dError> {
        let options = self.lua.create_table()?;
        options.set("time_msec", frame.time_msec)?;
        options.set("delta_seconds", frame.delta_seconds)?;
        options.set("frame_number", frame.frame_number)?;
        options.set("clear", frame.clear)?;
        options.set("r", frame.clear_color[0])?;
        options.set("g", frame.clear_color[1])?;
        options.set("b", frame.clear_color[2])?;
        options.set("a", frame.clear_color[3])?;
        options.set("gc_interval", frame.gc_interval)?;
        options.set("gc_step", frame.gc_step)?;
        let parameters = self.lua.create_table()?;
        for (index, parameter) in frame.parameters.iter().enumerate() {
            let entry = self.lua.create_table()?;
            entry.set("id", parameter.id.as_str())?;
            entry.set("value", parameter.value)?;
            entry.set("weight", parameter.weight)?;
            parameters.set(index + 1, entry)?;
        }
        options.set("parameters", parameters)?;
        Ok(options)
    }

    fn model_options(
        &self,
        model_path: &str,
        quality: TextureQuality,
    ) -> Result<Table, Live2dError> {
        let resources = self.lua.create_table()?;
        let resource_loader = self.resource_loader.clone();
        resources.set(
            "__loader",
            self.lua.create_function(move |lua, path: mlua::String| {
                let path = path.to_string_lossy();
                let bytes = resource_loader.read(&path).map_err(mlua::Error::external)?;
                lua.create_string(&bytes)
            })?,
        )?;
        resources.set(
            model_path,
            self.lua
                .create_string(&self.resource_loader.read(model_path)?)?,
        )?;

        let textures = self.lua.create_table()?;
        let texture_loader = self.resource_loader.clone();
        textures.set(
            "__loader",
            self.lua
                .create_function(move |lua, (_index, path): (usize, mlua::String)| {
                    let path = path.to_string_lossy();
                    let bytes = texture_loader.read(&path).map_err(mlua::Error::external)?;
                    let entry = lua.create_table()?;
                    entry.set("path", path.as_str())?;
                    entry.set("bytes", lua.create_string(&bytes)?)?;
                    entry.set("scale", quality.scale())?;
                    entry.set("mipmap", quality.mipmap())?;
                    entry.set("bleed_passes", quality.bleed_passes())?;
                    Ok(entry)
                })?,
        )?;

        let options = self.lua.create_table()?;
        options.set("resource_streams", resources)?;
        options.set("texture_streams", textures)?;
        options.set("center", false)?;
        options.set("defer_expressions", true)?;
        Ok(options)
    }
}

impl Drop for Live2dRuntime {
    fn drop(&mut self) {
        let _ = self.dispose();
    }
}

fn install_module_searcher(lua: &Lua, catalog: ModuleCatalog) -> Result<(), mlua::Error> {
    let catalog = Arc::new(catalog);
    let source = lua.create_function(move |lua, name: String| {
        let Some(source) = catalog.source(&name).map_err(mlua::Error::external)? else {
            return Ok((Value::Nil, Value::Nil));
        };
        Ok((
            Value::String(lua.create_string(&source.bytes)?),
            Value::String(lua.create_string(&source.chunk_name)?),
        ))
    })?;
    lua.globals()
        .set("__bandori_lazy_lua_module_source", source)?;
    lua.load(INSTALL_SEARCHER).exec()
}

fn install_gl_resolver(lua: &Lua, resolver: GlProcResolver) -> Result<(), mlua::Error> {
    let function = lua.create_function(move |_lua, name: String| {
        Ok(resolver(&name).map(|address| format!("{address:x}")))
    })?;
    lua.globals().set("__bandori_gl_get_proc_address", function)
}

fn require_module(lua: &Lua, name: &str) -> Result<Table, mlua::Error> {
    let require: Function = lua.globals().get("require")?;
    require.call(name)
}

fn table_strings(table: Table) -> Result<Vec<String>, mlua::Error> {
    table.sequence_values::<String>().collect()
}

fn find_host_module(module_root: &Path, filename: &str) -> Option<std::path::PathBuf> {
    module_root
        .ancestors()
        .take(4)
        .map(|ancestor| ancestor.join(filename))
        .find(|path| path.is_file())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::resource::ResourceRoots;
    use std::fs;
    use tempfile::tempdir;

    const FAKE_EMBED: &str = r#"
local M = {}
function M.init() return true end
function M.new(width, height)
    local renderer = { width = width, height = height, updates = 0, renders = 0 }
    function renderer:load_model(path, width2, height2, _opts)
        self.path, self.width, self.height = path, width2, height2
        return self
    end
    function renderer:resize(w, h) self.width, self.height = w, h return self end
    function renderer:resize_renderer(w, h) self.render_width, self.render_height = w, h return self end
    function renderer:draw(_opts) self.updates = self.updates + 1 self.renders = self.renders + 1 return self end
    function renderer:render_frame(_opts) self.renders = self.renders + 1 return self end
    function renderer:drag(x, y) self.x, self.y = x, y return self end
    function renderer:set_offset() return self end
    function renderer:set_scale() return self end
    function renderer:set_parameter() return self end
    function renderer:start_motion() self.motion = true return self end
    function renderer:clear_motions() self.motion = false return self end
    function renderer:is_motion_finished() return not self.motion end
    function renderer:set_expression() return self end
    function renderer:reset_expression() return self end
    function renderer:hit_test() return { "Head" } end
    function renderer:model_info()
        return { motion_names = { "Idle" }, motions = { Idle = { "idle.motion" } }, expressions = { smile = true }, hit_area_count = 1 }
    end
    function renderer:dispose() self.disposed = true return true end
    return renderer
end
return M
"#;

    fn runtime(format: Live2dFormat) -> (tempfile::TempDir, Live2dRuntime) {
        let temp = tempdir().unwrap();
        let modules = temp.path().join("modules");
        let bundled = temp.path().join("models");
        let user = temp.path().join("user-models");
        fs::create_dir_all(&modules).unwrap();
        fs::create_dir_all(&bundled).unwrap();
        fs::create_dir_all(&user).unwrap();
        fs::write(modules.join("live2d_embed.lua"), FAKE_EMBED).unwrap();
        fs::write(modules.join("live2d_moc3_pet_embed.lua"), FAKE_EMBED).unwrap();
        fs::write(
            modules.join("live2d_platform_manager_override.lua"),
            "return {}",
        )
        .unwrap();
        let loader = ModelResourceLoader::new(ResourceRoots {
            bundled_models: bundled,
            user_models: user,
        });
        let runtime =
            Live2dRuntime::new(format, &modules, loader, Arc::new(|_| None), 400, 650).unwrap();
        (temp, runtime)
    }

    #[test]
    fn moc3_render_replay_does_not_tick_update_twice() {
        let (_temp, runtime) = runtime(Live2dFormat::Moc3);
        runtime.draw(&FrameInput::default()).unwrap();
        runtime.render_only(&FrameInput::default()).unwrap();
        let renderer = runtime.renderer_table().unwrap();
        assert_eq!(renderer.get::<usize>("updates").unwrap(), 1);
        assert_eq!(renderer.get::<usize>("renders").unwrap(), 2);
    }

    #[test]
    fn formats_and_runtime_state_are_isolated() {
        let (_moc_temp, moc) = runtime(Live2dFormat::Moc);
        let (_moc3_temp, moc3) = runtime(Live2dFormat::Moc3);
        moc.draw(&FrameInput::default()).unwrap();
        assert_eq!(moc.format(), Live2dFormat::Moc);
        assert_eq!(moc3.format(), Live2dFormat::Moc3);
        assert_eq!(
            moc.renderer_table()
                .unwrap()
                .get::<usize>("updates")
                .unwrap(),
            1
        );
        assert_eq!(
            moc3.renderer_table()
                .unwrap()
                .get::<usize>("updates")
                .unwrap(),
            0
        );
        assert!(matches!(
            moc.render_only(&FrameInput::default()),
            Err(Live2dError::RenderOnlyUnsupported)
        ));
    }

    #[test]
    fn model_metadata_and_hit_tests_cross_the_host_boundary() {
        let (temp, runtime) = runtime(Live2dFormat::Moc3);
        fs::write(temp.path().join("models/model.json"), b"{}").unwrap();
        let info = runtime.load_model("model.json", 300, 500).unwrap();
        assert_eq!(info.motion_names, ["Idle"]);
        assert_eq!(info.motions["Idle"], ["idle.motion"]);
        assert_eq!(info.expressions, ["smile"]);
        assert_eq!(runtime.hit_test(0.0, 0.0).unwrap(), ["Head"]);
    }
}
