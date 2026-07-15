//! LuaJIT host for the isolated native Live2D pet process.
//!
//! Qt owns the OpenGL context and calls this crate only while that context is
//! current. Cubism 2 and Cubism 3 use separate `Lua` instances; no renderer or
//! package state is shared across formats or pet processes.

pub mod ffi;
pub mod module_catalog;
pub mod resource;
pub mod runtime;

pub use resource::{ModelResourceLoader, ResourceError, ResourceRoots};
pub use runtime::{
    DefaultStateOptions, FrameInput, GlProcResolver, Live2dError, Live2dFormat, Live2dModelInfo,
    Live2dRuntime, MotionPriority, ParameterValue, TextureQuality,
};
