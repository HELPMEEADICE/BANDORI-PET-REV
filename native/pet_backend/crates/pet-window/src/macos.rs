//! AppKit desktop overlays. Call these helpers on the event-loop thread.
//!
//! winit expresses desktop positions in points multiplied by the window's own
//! backing scale. Always use that same scale for the cursor and work areas,
//! including when the cursor is on a display with a different Retina scale.

use objc2::rc::Retained;
use objc2::MainThreadMarker;
use objc2_app_kit::{NSEvent, NSScreen, NSView, NSWindow, NSWindowCollectionBehavior};
use objc2_foundation::{NSNumber, NSRect, NSString};
use winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
use winit::window::Window;

use crate::placement::MonitorInfo;

fn native_window(window: &Window) -> Option<Retained<NSWindow>> {
    let _main = MainThreadMarker::new()?;
    let handle = window.window_handle().ok()?;
    let RawWindowHandle::AppKit(handle) = handle.as_raw() else {
        return None;
    };
    // The main-thread marker prevents AppKit access off-thread. winit owns this
    // NSView for the lifetime of `window`; retain its NSWindow before returning.
    let view = unsafe { handle.ns_view.cast::<NSView>().as_ref() };
    view.window()
}

/// Removes the shadow and keeps the pet on desktop Spaces without hiding when
/// another application becomes active.
pub fn apply_overlay_style(window: &Window) {
    if let Some(native) = native_window(window) {
        native.setHasShadow(false);
        native.setHidesOnDeactivate(false);
        native.setCollectionBehavior(
            NSWindowCollectionBehavior::CanJoinAllSpaces
                | NSWindowCollectionBehavior::FullScreenAuxiliary
                | NSWindowCollectionBehavior::Stationary
                | NSWindowCollectionBehavior::IgnoresCycle,
        );
    }
}

/// winit's macOS `set_visible(true)` makes a window key. Order the pet in front
/// without activating it, so first render and tray toggles preserve focus.
pub fn set_visible(window: &Window, visible: bool) {
    if let Some(native) = native_window(window) {
        if visible {
            native.orderFrontRegardless();
        } else {
            native.orderOut(None);
        }
    }
}

/// Global cursor in the physical coordinate system used by `window`.
pub fn cursor_position(window: &Window) -> Option<(f32, f32)> {
    let mtm = MainThreadMarker::new()?;
    let screens = NSScreen::screens(mtm);
    let primary = screens.firstObject()?;
    let point = NSEvent::mouseLocation();
    let scale = window.scale_factor();
    Some((
        (point.x * scale) as f32,
        ((primary.frame().size.height - point.y) * scale) as f32,
    ))
}

/// Polling button state needs no event tap or Accessibility permission.
pub fn mouse_down() -> bool {
    NSEvent::pressedMouseButtons() & 0b111 != 0
}

/// Screen work areas, excluding the Dock and menu bar. `None` uses each screen's
/// native scale; role windows pass their own scale for consistent coordinates.
pub fn monitors(scale: Option<f64>) -> Vec<MonitorInfo> {
    let Some(mtm) = MainThreadMarker::new() else {
        return Vec::new();
    };
    let screens = NSScreen::screens(mtm);
    let Some(primary) = screens.firstObject() else {
        return Vec::new();
    };
    let primary_height = primary.frame().size.height;
    screens
        .iter()
        .enumerate()
        .map(|(index, screen)| {
            let scale = scale.unwrap_or_else(|| screen.backingScaleFactor());
            let convert = |rect: NSRect| {
                [
                    (rect.origin.x * scale).round() as i32,
                    ((primary_height - rect.origin.y - rect.size.height) * scale).round() as i32,
                    (rect.size.width * scale).round() as i32,
                    (rect.size.height * scale).round() as i32,
                ]
            };
            let id = screen
                .deviceDescription()
                .objectForKey(&NSString::from_str("NSScreenNumber"))
                .and_then(|number| number.downcast::<NSNumber>().ok())
                .map(|number| number.unsignedIntValue())
                .unwrap_or(index as u32);
            MonitorInfo {
                name: format!("display-{id}"),
                manufacturer: String::new(),
                model: screen.localizedName().to_string(),
                serial: String::new(),
                geometry: convert(screen.frame()),
                work: convert(screen.visibleFrame()),
                is_primary: index == 0,
            }
        })
        .collect()
}
