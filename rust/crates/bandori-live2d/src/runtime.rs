use crate::module_catalog::{ModuleCatalog, ModuleError};
use crate::resource::{ModelResourceLoader, ResourceError};
use mlua::{Function, Lua, ObjectLike, RegistryKey, Table, Value};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use std::cell::RefCell;
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

static HEAD_INTERACTION_BUCKETS: &[&[&str]] = &[
    &["surprised", "shame", "pui", "smile"],
    &["kandou", "kime", "nf"],
];
static UPPER_LEFT_INTERACTION_BUCKETS: &[&[&str]] =
    &[&["nf_left", "nnf_left"], &["shame", "surprised", "smile"]];
static UPPER_CENTER_INTERACTION_BUCKETS: &[&[&str]] = &[
    &["smile", "kime", "surprised", "shame"],
    &["angry", "pui", "nf"],
];
static UPPER_RIGHT_INTERACTION_BUCKETS: &[&[&str]] =
    &[&["nf_right", "nnf_right"], &["shame", "surprised", "smile"]];
static LOWER_LEFT_INTERACTION_BUCKETS: &[&[&str]] =
    &[&["nf_left", "nnf_left"], &["surprised", "sad", "smile"]];
static LOWER_CENTER_INTERACTION_BUCKETS: &[&[&str]] =
    &[&["shame", "surprised", "angry"], &["smile", "kime"]];
static LOWER_RIGHT_INTERACTION_BUCKETS: &[&[&str]] =
    &[&["nf_right", "nnf_right"], &["surprised", "sad", "smile"]];

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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DefaultStateOptions {
    pub idle_actions_enabled: bool,
    pub choice: usize,
    pub apply_motion: bool,
    pub apply_expression: bool,
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
    model_info: RefCell<Option<Live2dModelInfo>>,
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
            model_info: RefCell::new(None),
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
        let manifest = self.resource_loader.read(model_path)?;
        let options = self.model_options(model_path, quality, &manifest)?;
        self.renderer_table()?.call_method::<Value>(
            "load_model",
            (model_path, width.max(1), height.max(1), options),
        )?;
        let info = self
            .renderer_model_info()?
            .unwrap_or_else(|| model_info_from_manifest(&manifest));
        *self.model_info.borrow_mut() = Some(info.clone());
        Ok(info)
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
        let renderer = self.renderer_table()?;
        if renderer
            .get::<Option<Function>>("is_motion_finished")?
            .is_some()
        {
            return Ok(renderer.call_method::<bool>("is_motion_finished", ())?);
        }
        let model: Table = renderer.call_method("get_model", ())?;
        let motion_manager: Table = model.get("mainMotionManager")?;
        Ok(motion_manager.call_method::<bool>("isFinished", ())?)
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

    pub fn trigger_action(&self, action: &str, character: &str) -> Result<bool, Live2dError> {
        let info = self.model_info()?;
        let mut normalized = action
            .trim()
            .trim_matches(|value: char| matches!(value, '[' | ']' | ' ' | '\t' | '\r' | '\n'))
            .replace('\\', "/")
            .rsplit('/')
            .next()
            .unwrap_or_default()
            .to_lowercase();
        if normalized.is_empty() {
            return Ok(false);
        }

        if let Some((base, extension)) = normalized.rsplit_once('.') {
            if let Some(expression) = find_expression(&info.expressions, base, character) {
                self.set_expression(expression)?;
                return Ok(true);
            }
            if matches!(extension, "mtn" | "motion") {
                normalized = base.to_owned();
            } else {
                return Ok(false);
            }
        }

        let candidates = if normalized == "thinking" {
            vec!["thinking", "nf", "nnf", "eeto", "odoodo"]
        } else {
            vec![normalized.as_str()]
        };
        let character = character.to_lowercase();
        let motion = find_motion(&info.motion_names, &candidates, &character);
        let mut triggered = false;
        if let Some(motion) = motion {
            self.start_motion(motion, 0, MotionPriority::Force, false)?;
            triggered = true;
        }
        if let Some(expression) = find_expression(&info.expressions, &normalized, &character) {
            self.set_expression(expression)?;
            triggered = true;
        }
        Ok(triggered)
    }

    pub fn trigger_expression_tag(
        &self,
        action: &str,
        character: &str,
    ) -> Result<bool, Live2dError> {
        let info = self.model_info()?;
        let normalized = action
            .trim()
            .trim_matches(|value: char| matches!(value, '[' | ']' | ' ' | '\t' | '\r' | '\n'))
            .replace('\\', "/")
            .rsplit('/')
            .next()
            .unwrap_or_default()
            .to_lowercase();
        let Some(expression) = find_expression(&info.expressions, &normalized, character) else {
            return Ok(false);
        };
        self.set_expression(expression)?;
        Ok(true)
    }

    pub fn trigger_motion_tag(&self, action: &str, character: &str) -> Result<bool, Live2dError> {
        let info = self.model_info()?;
        let normalized = action
            .trim()
            .trim_matches(|value: char| matches!(value, '[' | ']' | ' ' | '\t' | '\r' | '\n'))
            .replace('\\', "/")
            .rsplit('/')
            .next()
            .unwrap_or_default()
            .to_lowercase();
        if normalized.is_empty() {
            return Ok(false);
        }
        let candidates = if normalized == "thinking" {
            vec!["thinking", "nf", "nnf", "eeto", "odoodo"]
        } else {
            vec![normalized.as_str()]
        };
        let Some(motion) = find_motion(&info.motion_names, &candidates, &character.to_lowercase())
        else {
            return Ok(false);
        };
        self.start_motion(motion, 0, MotionPriority::Force, false)?;
        Ok(true)
    }

    pub fn apply_default_state(
        &self,
        configured_motion: &str,
        configured_expression: &str,
        character: &str,
        options: DefaultStateOptions,
    ) -> Result<bool, Live2dError> {
        let info = self.model_info()?;
        let character = character.to_lowercase();
        let mut applied = false;
        let configured_motion = configured_motion.trim();
        if options.apply_motion && configured_motion != "__none__" {
            if !options.idle_actions_enabled {
                self.clear_motions()?;
                applied = true;
            } else if let Some(motion) = select_default_motion(
                &info.motion_names,
                configured_motion,
                &character,
                options.choice,
            ) {
                self.start_motion(motion, 0, MotionPriority::Force, true)?;
                applied = true;
            }
        }
        if options.apply_expression {
            self.reset_expression()?;
            if let Some(expression) =
                select_default_expression(&info.expressions, configured_expression, &character)
            {
                self.set_expression(expression)?;
                applied = true;
            }
        }
        Ok(applied)
    }

    pub fn trigger_interaction_feedback(
        &self,
        region: &str,
        configured_motion: &str,
        configured_expression: &str,
        character: &str,
        choice: usize,
    ) -> Result<bool, Live2dError> {
        let configured_motion = configured_motion.trim();
        if configured_motion == "__none__" {
            return Ok(false);
        }
        let info = self.model_info()?;
        let mut triggered = false;
        if let Some(motion) = select_interaction_motion(
            &info.motion_names,
            region,
            character,
            configured_motion,
            choice,
        ) {
            self.start_motion(motion, 0, MotionPriority::Force, false)?;
            triggered = true;
        }
        let configured_expression = configured_expression.trim();
        if !configured_expression.is_empty() {
            if let Some(expression) =
                find_expression(&info.expressions, configured_expression, character)
            {
                self.set_expression(expression)?;
                triggered = true;
            }
        }
        Ok(triggered)
    }

    pub fn hit_test(&self, x: f64, y: f64) -> Result<Vec<String>, Live2dError> {
        let hits: Table = self.renderer_table()?.call_method("hit_test", (x, y))?;
        hits.sequence_values::<String>()
            .collect::<Result<Vec<_>, _>>()
            .map_err(Live2dError::from)
    }

    pub fn model_info(&self) -> Result<Live2dModelInfo, Live2dError> {
        if let Some(info) = self.model_info.borrow().as_ref() {
            return Ok(info.clone());
        }
        Ok(self.renderer_model_info()?.unwrap_or_default())
    }

    fn renderer_model_info(&self) -> Result<Option<Live2dModelInfo>, Live2dError> {
        let renderer = self.renderer_table()?;
        let function: Option<Function> = renderer.get("model_info")?;
        if function.is_none() {
            return Ok(None);
        }
        let info: Table = renderer.call_method("model_info", ())?;
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
        Ok(Some(Live2dModelInfo {
            motion_names,
            motions,
            expressions,
            hit_area_count: info.get::<Option<usize>>("hit_area_count")?.unwrap_or(0),
        }))
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
        manifest: &[u8],
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
        resources.set(model_path, self.lua.create_string(manifest)?)?;

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

fn model_info_from_manifest(source: &[u8]) -> Live2dModelInfo {
    let Ok(manifest) = serde_json::from_slice::<JsonValue>(source) else {
        return Live2dModelInfo::default();
    };
    let references = manifest.get("FileReferences");
    let motion_value = references
        .and_then(|value| value.get("Motions"))
        .or_else(|| manifest.get("motions"));
    let mut motions = BTreeMap::new();
    if let Some(groups) = motion_value.and_then(JsonValue::as_object) {
        for (name, group) in groups {
            let files = group
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|entry| {
                    entry
                        .get("File")
                        .or_else(|| entry.get("file"))
                        .and_then(JsonValue::as_str)
                        .map(str::to_owned)
                })
                .collect();
            motions.insert(name.clone(), files);
        }
    }

    let expression_value = references
        .and_then(|value| value.get("Expressions"))
        .or_else(|| manifest.get("expressions"));
    let mut expressions = match expression_value {
        Some(JsonValue::Array(entries)) => entries
            .iter()
            .filter_map(|entry| {
                entry
                    .get("Name")
                    .or_else(|| entry.get("name"))
                    .and_then(JsonValue::as_str)
                    .map(str::to_owned)
            })
            .collect::<Vec<_>>(),
        Some(JsonValue::Object(entries)) => entries.keys().cloned().collect(),
        _ => Vec::new(),
    };
    expressions.sort();
    expressions.dedup();
    let hit_area_count = manifest
        .get("HitAreas")
        .or_else(|| manifest.get("hit_areas"))
        .and_then(JsonValue::as_array)
        .map_or(0, Vec::len);
    let motion_names = motions.keys().cloned().collect();
    Live2dModelInfo {
        motion_names,
        motions,
        expressions,
        hit_area_count,
    }
}

fn find_expression<'a>(
    expressions: &'a [String],
    action: &str,
    character: &str,
) -> Option<&'a str> {
    let action = action.to_lowercase();
    let action_base = action
        .rsplit_once('.')
        .map_or(action.as_str(), |(base, _)| base);
    let character_prefix = format!("{}_{}", character.to_lowercase(), action_base);
    expressions.iter().find_map(|expression| {
        let lower = expression.to_lowercase();
        let base = lower
            .rsplit_once('.')
            .map_or(lower.as_str(), |(base, _)| base);
        (lower == action
            || base == action_base
            || base.starts_with(&character_prefix)
            || base.starts_with(action_base))
        .then_some(expression.as_str())
    })
}

fn find_motion<'a>(
    motion_names: &'a [String],
    candidates: &[&str],
    character: &str,
) -> Option<&'a str> {
    candidates.iter().find_map(|candidate| {
        let candidate = candidate.to_lowercase();
        let character_candidate = format!("{character}_{candidate}");
        motion_names.iter().find_map(|name| {
            let normalized = name.to_lowercase();
            (normalized == candidate
                || normalized.starts_with(&candidate)
                || normalized == character_candidate
                || normalized.starts_with(&character_candidate)
                || contains_action_token(&normalized, &candidate))
            .then_some(name.as_str())
        })
    })
}

fn select_default_motion<'a>(
    motion_names: &'a [String],
    configured_motion: &str,
    character: &str,
    choice: usize,
) -> Option<&'a str> {
    if !configured_motion.is_empty() {
        if let Some(motion) = find_motion(motion_names, &[configured_motion], character) {
            return Some(motion);
        }
    }
    let idle = motion_names
        .iter()
        .filter(|name| is_idle_motion_name(name))
        .collect::<Vec<_>>();
    (!idle.is_empty()).then(|| idle[choice % idle.len()].as_str())
}

fn is_idle_motion_name(name: &str) -> bool {
    let normalized = name.to_lowercase();
    normalized.starts_with("idle") || normalized.contains("_idle") || normalized.contains("-idle")
}

fn select_default_expression<'a>(
    expressions: &'a [String],
    configured_expression: &str,
    character: &str,
) -> Option<&'a str> {
    let configured_expression = configured_expression.trim();
    if !configured_expression.is_empty() {
        if let Some(expression) = find_expression(expressions, configured_expression, character) {
            return Some(expression);
        }
    }
    expressions.iter().find_map(|expression| {
        let normalized = expression.to_lowercase();
        (normalized == "default"
            || normalized.ends_with("_default")
            || normalized.ends_with("-default"))
        .then_some(expression.as_str())
    })
}

fn select_interaction_motion<'a>(
    motion_names: &'a [String],
    region: &str,
    character: &str,
    configured_motion: &str,
    choice: usize,
) -> Option<&'a str> {
    if configured_motion == "__none__" {
        return None;
    }
    let character = character.to_lowercase();
    if !configured_motion.is_empty() && configured_motion != "__random__" {
        return find_motion(motion_names, &[configured_motion], &character);
    }
    if configured_motion.is_empty() {
        for bucket in interaction_buckets(region) {
            let available = bucket
                .iter()
                .filter_map(|tag| find_motion(motion_names, &[*tag], &character))
                .collect::<Vec<_>>();
            if !available.is_empty() {
                return Some(available[choice % available.len()]);
            }
        }
    }
    let available = motion_names
        .iter()
        .filter(|name| {
            let normalized = name.to_lowercase();
            !normalized.starts_with("idle") && !normalized.starts_with("sys-")
        })
        .collect::<Vec<_>>();
    (!available.is_empty()).then(|| available[choice % available.len()].as_str())
}

fn interaction_buckets(region: &str) -> &'static [&'static [&'static str]] {
    match region {
        "head" => HEAD_INTERACTION_BUCKETS,
        "upper_body_left" => UPPER_LEFT_INTERACTION_BUCKETS,
        "upper_body_right" => UPPER_RIGHT_INTERACTION_BUCKETS,
        "lower_body_left" => LOWER_LEFT_INTERACTION_BUCKETS,
        "lower_body_center" => LOWER_CENTER_INTERACTION_BUCKETS,
        "lower_body_right" => LOWER_RIGHT_INTERACTION_BUCKETS,
        _ => UPPER_CENTER_INTERACTION_BUCKETS,
    }
}

fn contains_action_token(name: &str, candidate: &str) -> bool {
    name.split(['_', '-']).any(|part| {
        part == candidate
            || part.strip_prefix(candidate).is_some_and(|suffix| {
                !suffix.is_empty() && suffix.chars().all(|value| value.is_ascii_digit())
            })
    })
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
    renderer.mainMotionManager = { finished = false }
    function renderer.mainMotionManager:isFinished() return self.finished end
    function renderer:get_model() return self end
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
    function renderer:start_motion(name, _index, _priority, looping)
        self.motion = true
        self.motion_name = name
        self.motion_looping = looping
        return self
    end
    function renderer:clear_motions() self.motion = false return self end
    function renderer:is_motion_finished() return not self.motion end
    function renderer:set_expression(name) self.expression_name = name return self end
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

    #[test]
    fn action_tags_resolve_motion_extensions_and_expression_files() {
        let (_temp, runtime) = runtime(Live2dFormat::Moc3);
        assert!(
            !runtime
                .trigger_interaction_feedback("head", "__none__", "smile", "aya", 0)
                .unwrap()
        );
        assert_eq!(
            runtime
                .renderer_table()
                .unwrap()
                .get::<Option<String>>("expression_name")
                .unwrap(),
            None
        );
        assert!(runtime.trigger_action("[idle.motion]", "aya").unwrap());
        assert_eq!(
            runtime
                .renderer_table()
                .unwrap()
                .get::<String>("motion_name")
                .unwrap(),
            "Idle"
        );
        assert!(runtime.trigger_action("smile.exp3.json", "aya").unwrap());
        assert_eq!(
            runtime
                .renderer_table()
                .unwrap()
                .get::<String>("expression_name")
                .unwrap(),
            "smile"
        );
        assert!(runtime.trigger_expression_tag("smile", "aya").unwrap());
        assert!(!runtime.trigger_expression_tag("Idle", "aya").unwrap());
        assert!(runtime.trigger_motion_tag("Idle", "aya").unwrap());
        assert!(!runtime.trigger_motion_tag("smile", "aya").unwrap());
    }

    #[test]
    fn configured_default_state_loops_motion_and_applies_expression() {
        let (_temp, runtime) = runtime(Live2dFormat::Moc3);
        assert!(
            runtime
                .apply_default_state(
                    "Idle",
                    "smile",
                    "aya",
                    DefaultStateOptions {
                        idle_actions_enabled: true,
                        choice: 0,
                        apply_motion: true,
                        apply_expression: true,
                    },
                )
                .unwrap()
        );
        let renderer = runtime.renderer_table().unwrap();
        assert_eq!(renderer.get::<String>("motion_name").unwrap(), "Idle");
        assert!(renderer.get::<bool>("motion_looping").unwrap());
        assert_eq!(renderer.get::<String>("expression_name").unwrap(), "smile");
        assert!(
            runtime
                .apply_default_state(
                    "missing",
                    "",
                    "aya",
                    DefaultStateOptions {
                        idle_actions_enabled: true,
                        choice: 0,
                        apply_motion: true,
                        apply_expression: false,
                    },
                )
                .unwrap()
        );
        assert!(
            runtime
                .apply_default_state(
                    "",
                    "",
                    "aya",
                    DefaultStateOptions {
                        idle_actions_enabled: false,
                        choice: 0,
                        apply_motion: true,
                        apply_expression: false,
                    },
                )
                .unwrap()
        );
        assert!(!renderer.get::<bool>("motion").unwrap());
    }

    #[test]
    fn motion_finished_falls_back_to_cubism2_motion_manager() {
        let (_temp, runtime) = runtime(Live2dFormat::Moc);
        let renderer = runtime.renderer_table().unwrap();
        renderer.set("is_motion_finished", Value::Nil).unwrap();
        let manager: Table = renderer.get("mainMotionManager").unwrap();
        manager.set("finished", true).unwrap();
        assert!(runtime.is_motion_finished().unwrap());
    }

    #[test]
    fn interaction_feedback_matches_regions_and_special_motion_values() {
        let motions = vec![
            "Idle".to_owned(),
            "kasumi_smile_01".to_owned(),
            "nf_left_02".to_owned(),
            "wave".to_owned(),
        ];
        assert_eq!(
            select_interaction_motion(&motions, "head", "kasumi", "", 0),
            Some("kasumi_smile_01")
        );
        assert_eq!(
            select_interaction_motion(&motions, "upper_body_left", "kasumi", "", 0),
            Some("nf_left_02")
        );
        assert_eq!(
            select_interaction_motion(&motions, "head", "kasumi", "__random__", 2),
            Some("wave")
        );
        assert_eq!(
            select_interaction_motion(&motions, "head", "kasumi", "__none__", 0),
            None
        );
        assert_eq!(
            select_interaction_motion(&motions, "head", "kasumi", "wave", 0),
            Some("wave")
        );
    }

    #[test]
    fn manifest_metadata_supports_both_cubism_generations() {
        let moc = model_info_from_manifest(
            br#"{
                "motions":{"smile01":[{"file":"smile.mtn"}]},
                "expressions":[{"name":"aya_smile","file":"smile.exp.json"}],
                "hit_areas":[{"name":"head","id":"HEAD"}]
            }"#,
        );
        assert_eq!(moc.motion_names, ["smile01"]);
        assert_eq!(moc.motions["smile01"], ["smile.mtn"]);
        assert_eq!(moc.expressions, ["aya_smile"]);
        assert_eq!(moc.hit_area_count, 1);

        let moc3 = model_info_from_manifest(
            br#"{
                "FileReferences":{
                    "Motions":{"TapBody":[{"File":"motions/tap.motion3.json"}]},
                    "Expressions":[{"Name":"surprised","File":"surprised.exp3.json"}]
                },
                "HitAreas":[{"Name":"Head","Id":"HitAreaHead"}]
            }"#,
        );
        assert_eq!(moc3.motion_names, ["TapBody"]);
        assert_eq!(moc3.motions["TapBody"], ["motions/tap.motion3.json"]);
        assert_eq!(moc3.expressions, ["surprised"]);
        assert_eq!(moc3.hit_area_count, 1);
    }
}
