pub mod backend;

// Keep the C ABI dependency reachable from the final Rust static library. The
// exported symbols themselves live in the Qt-independent Live2D crate so they
// can be tested on machines without a Qt SDK.
pub use bandori_live2d::ffi as live2d_ffi;
