//! Window plumbing for the pet: native styles, click-through, decorations,
//! opacity, DPI, position persistence and z-order.
//!
//! The transparent wgpu surface lives in `pet-render`; this crate only owns the
//! native window behaviour (spec §2.1, §2.4, §2.8).

pub mod placement;
pub mod sizing;

#[cfg(windows)]
pub mod win32;

#[cfg(target_os = "macos")]
pub mod macos;

#[cfg(target_os = "linux")]
pub mod x11;

#[cfg(any(target_os = "linux", test))]
mod autostart;

#[cfg(any(target_os = "macos", test))]
mod launch_agent;

pub use placement::{
    auto_start_enabled, resolve_position, set_auto_start, MonitorInfo, PositionDecision,
};
pub use sizing::{content_size, fit_matrix, Bounds, ModelLayout};

#[cfg(windows)]
pub use win32::{
    apply_pet_style, cursor_position, hwnd_of, is_windows_11, reassert_topmost, set_window_rect,
    window_rect,
};
