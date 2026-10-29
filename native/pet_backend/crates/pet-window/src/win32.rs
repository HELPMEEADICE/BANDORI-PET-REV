//! Win32 window behaviour: styles, click-through, DWM decorations, topmost guard.

use std::ffi::c_void;

use tracing::debug;
use windows::core::{s, w, PCWSTR};
use windows::Win32::Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, WPARAM};
use windows::Win32::Graphics::Dwm::{DwmSetWindowAttribute, DWMWINDOWATTRIBUTE};
use windows::Win32::UI::Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass};
use windows::Win32::UI::WindowsAndMessaging::{
    GetCursorPos, GetWindowLongPtrW, GetWindowRect, SetCursorPos, SetWindowLongPtrW, SetWindowPos,
    ShowWindow, GWL_EXSTYLE, HWND_TOPMOST, MA_NOACTIVATE, STYLESTRUCT, SWP_FRAMECHANGED,
    SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOOWNERZORDER, SWP_NOSIZE, SWP_NOZORDER, SW_SHOWNOACTIVATE,
    WM_MOUSEACTIVATE, WM_NCDESTROY, WM_STYLECHANGING, WS_EX_APPWINDOW, WS_EX_LAYERED,
    WS_EX_NOACTIVATE, WS_EX_NOREDIRECTIONBITMAP, WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT,
};

use winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};

/// `DWMWA_WINDOW_CORNER_PREFERENCE`.
const DWMWA_WINDOW_CORNER_PREFERENCE: DWMWINDOWATTRIBUTE = DWMWINDOWATTRIBUTE(33);
/// `DWMWA_BORDER_COLOR`.
const DWMWA_BORDER_COLOR: DWMWINDOWATTRIBUTE = DWMWINDOWATTRIBUTE(34);
/// `DWMWCP_DONOTROUND`.
const DWMWCP_DONOTROUND: i32 = 1;
/// `DWMWA_COLOR_NONE` — removes the 1 px border Windows 11 draws on popups.
const DWMWA_COLOR_NONE: u32 = 0xFFFF_FFFE;

const PET_SUBCLASS_ID: usize = 1;
const OBS_CAPTURE: usize = 1;
const POPUP_STYLE: usize = 2;

fn pet_ex_style(mut style: u32, obs_capture: bool) -> u32 {
    // DWM supplies visual alpha; LAYERED + TRANSPARENT supplies cross-process
    // mouse passthrough. Keep LAYERED even while the model accepts input.
    style |= WS_EX_NOACTIVATE.0 | WS_EX_LAYERED.0;
    if obs_capture {
        style &= !WS_EX_TOOLWINDOW.0;
        style |= WS_EX_APPWINDOW.0;
    } else {
        style &= !WS_EX_APPWINDOW.0;
        style |= WS_EX_TOOLWINDOW.0;
    }
    style
}

fn overlay_ex_style(style: u32, flags: usize) -> u32 {
    let style = pet_ex_style(style, flags & OBS_CAPTURE != 0);
    if flags & POPUP_STYLE != 0 {
        // Slint presents through WGL/GDI, not UpdateLayeredWindow. Its shaped
        // popup already excludes transparent gaps from the native input region.
        style & !(WS_EX_LAYERED.0 | WS_EX_TRANSPARENT.0)
    } else {
        style
    }
}

unsafe extern "system" fn pet_subclass_proc(
    hwnd: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
    subclass_id: usize,
    style_flags: usize,
) -> LRESULT {
    match message {
        WM_STYLECHANGING if wparam.0 as i32 == GWL_EXSTYLE.0 => {
            // winit rewrites the entire EXSTYLE on visibility, hit-test and other
            // flag changes. Amend its proposed style before Windows applies it;
            // reapplying afterwards leaves a taskbar/focus race.
            if let Some(styles) = unsafe { (lparam.0 as *mut STYLESTRUCT).as_mut() } {
                // NOREDIRECTIONBITMAP must be set at creation. Preserve it for
                // DirectComposition pets without adding it to WGL/GDI popups.
                styles.styleNew = overlay_ex_style(
                    styles.styleNew | (styles.styleOld & WS_EX_NOREDIRECTIONBITMAP.0),
                    style_flags,
                );
            }
            return LRESULT(0);
        }
        WM_MOUSEACTIVATE => return LRESULT(MA_NOACTIVATE as isize),
        WM_NCDESTROY => {
            // No heap state or raw Role pointer survives the native window.
            let _ = unsafe { RemoveWindowSubclass(hwnd, Some(pet_subclass_proc), subclass_id) };
        }
        _ => {}
    }
    unsafe { DefSubclassProc(hwnd, message, wparam, lparam) }
}

/// Extracts the `HWND` of a winit window.
pub fn hwnd_of(window: &winit::window::Window) -> Option<HWND> {
    let handle = window.window_handle().ok()?;
    match handle.as_raw() {
        RawWindowHandle::Win32(win32) => Some(HWND(win32.hwnd.get() as *mut c_void)),
        _ => None,
    }
}

fn ex_style(hwnd: HWND) -> isize {
    unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) }
}

fn set_ex_style(hwnd: HWND, style: isize) {
    unsafe {
        SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style);
    }
    unsafe {
        let _ = SetWindowPos(
            hwnd,
            None,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        );
    }
}

/// Applies the desktop-pet window styles and the Windows 11 decoration fixes.
///
/// * never activates (`WS_EX_NOACTIVATE`), stays out of the taskbar
///   (`WS_EX_TOOLWINDOW`), unless OBS capture compatibility asks for
///   `WS_EX_APPWINDOW`;
/// * `WS_EX_LAYERED` makes `WS_EX_TRANSPARENT` pass input to other processes;
/// * corner preference `DO_NOT_ROUND` and border colour `NONE` remove the 1 px
///   white edge and the rounded corners Windows 11 adds to popups.
///
/// Must be called on the window's event-loop thread before its first show.
/// Repeated calls update the existing subclass's OBS setting.
pub fn apply_pet_style(hwnd: HWND, obs_capture: bool) -> windows::core::Result<()> {
    apply_overlay_style(hwnd, obs_capture as usize)
}

/// Styles a shaped Slint popup without adding the pet surface's layered flag.
/// Input passthrough is supplied by its native window region.
pub fn apply_popup_style(hwnd: HWND) -> windows::core::Result<()> {
    apply_overlay_style(hwnd, POPUP_STYLE)
}

fn apply_overlay_style(hwnd: HWND, style_flags: usize) -> windows::core::Result<()> {
    unsafe { SetWindowSubclass(hwnd, Some(pet_subclass_proc), PET_SUBCLASS_ID, style_flags) }
        .ok()?;
    set_ex_style(
        hwnd,
        overlay_ex_style(ex_style(hwnd) as u32, style_flags) as isize,
    );

    if is_windows_11() {
        let corner = DWMWCP_DONOTROUND;
        unsafe {
            let _ = DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                &corner as *const i32 as *const c_void,
                std::mem::size_of::<i32>() as u32,
            );
        }
    }
    let border = DWMWA_COLOR_NONE;
    unsafe {
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_BORDER_COLOR,
            &border as *const u32 as *const c_void,
            std::mem::size_of::<u32>() as u32,
        );
    }
    Ok(())
}

/// `true` when click-through is currently enabled.
pub fn click_through(hwnd: HWND) -> bool {
    ex_style(hwnd) & (WS_EX_TRANSPARENT.0 as isize) != 0
}

/// Re-asserts `HWND_TOPMOST` (the only reliable defence against games that reset
/// the z-order of every overlay window).
pub fn reassert_topmost(hwnd: HWND) {
    unsafe {
        let _ = SetWindowPos(
            hwnd,
            Some(HWND_TOPMOST),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
        );
    }
}

/// Global cursor position in physical pixels.
pub fn cursor_position() -> Option<(f32, f32)> {
    let mut point = POINT::default();
    if unsafe { GetCursorPos(&mut point) }.is_ok() {
        Some((point.x as f32, point.y as f32))
    } else {
        None
    }
}

/// Moves the cursor (used to keep the grip while the window is re-anchored).
pub fn set_cursor_position(x: f32, y: f32) -> bool {
    unsafe { SetCursorPos(x as i32, y as i32).is_ok() }
}

/// Current window rect `(x, y, width, height)` in physical pixels.
pub fn window_rect(hwnd: HWND) -> Option<(i32, i32, u32, u32)> {
    let mut rect = RECT::default();
    if unsafe { GetWindowRect(hwnd, &mut rect) }.is_err() {
        return None;
    }
    Some((
        rect.left,
        rect.top,
        (rect.right - rect.left).max(0) as u32,
        (rect.bottom - rect.top).max(0) as u32,
    ))
}

/// Moves / resizes a window without activating it.
pub fn set_window_rect(hwnd: HWND, x: i32, y: i32, width: u32, height: u32) {
    unsafe {
        let _ = SetWindowPos(
            hwnd,
            None,
            x,
            y,
            width as i32,
            height as i32,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
        );
    }
}

/// Shows a window without stealing focus.
pub fn show_no_activate(hwnd: HWND) {
    unsafe {
        let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);
    }
}

/// Windows 11 (build ≥ 22000) detection using `RtlGetVersion`.
///
/// `GetVersionEx` lies under a compatibility manifest, `RtlGetVersion` does not.
pub fn is_windows_11() -> bool {
    use windows::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};

    #[repr(C)]
    struct OsVersionInfoW {
        os_version_info_size: u32,
        major_version: u32,
        minor_version: u32,
        build_number: u32,
        platform_id: u32,
        sz_csd_version: [u16; 128],
    }

    type RtlGetVersionFn = unsafe extern "system" fn(*mut OsVersionInfoW) -> i32;

    let module = match unsafe { GetModuleHandleW(w!("ntdll.dll")) } {
        Ok(module) => module,
        Err(error) => {
            debug!(%error, "failed to load ntdll");
            return false;
        }
    };
    let Some(address) = (unsafe { GetProcAddress(module, s!("RtlGetVersion")) }) else {
        debug!("RtlGetVersion missing");
        return false;
    };
    let rtl_get_version: RtlGetVersionFn = unsafe { std::mem::transmute(address) };
    let mut info = OsVersionInfoW {
        os_version_info_size: std::mem::size_of::<OsVersionInfoW>() as u32,
        major_version: 0,
        minor_version: 0,
        build_number: 0,
        platform_id: 0,
        sz_csd_version: [0; 128],
    };
    let status = unsafe { rtl_get_version(&mut info) };
    status == 0 && info.major_version >= 10 && info.build_number >= 22_000
}

/// Unused import guard for `PCWSTR` on non-Windows builds.
#[allow(dead_code)]
fn _pcwstr_guard(value: PCWSTR) -> PCWSTR {
    value
}

#[cfg(test)]
mod tests {
    use super::*;
    use windows::Win32::UI::WindowsAndMessaging::{
        CreateWindowExW, DestroyWindow, SendMessageW, WS_EX_ACCEPTFILES, WS_POPUP,
    };

    struct TestWindow(HWND);

    impl TestWindow {
        fn new(no_redirection_bitmap: bool) -> Self {
            Self(unsafe {
                CreateWindowExW(
                    // Like winit, set this at creation: Windows rejects adding
                    // NOREDIRECTIONBITMAP later through SetWindowLongPtrW.
                    WS_EX_APPWINDOW
                        | if no_redirection_bitmap {
                            WS_EX_NOREDIRECTIONBITMAP
                        } else {
                            Default::default()
                        },
                    w!("STATIC"),
                    w!("pet-style-regression"),
                    WS_POPUP,
                    0,
                    0,
                    100,
                    100,
                    None,
                    None,
                    None,
                    None,
                )
                .unwrap()
            })
        }
    }

    impl Drop for TestWindow {
        fn drop(&mut self) {
            let _ = unsafe { DestroyWindow(self.0) };
        }
    }

    #[test]
    fn pet_styles_survive_replacement_without_freezing_cursor_hit_testing() {
        let window = TestWindow::new(true);
        apply_pet_style(window.0, false).unwrap();
        for passthrough in [true, false, true] {
            // Simulate winit replacing the complete style from its cached flags.
            let proposed = WS_EX_APPWINDOW.0
                | WS_EX_ACCEPTFILES.0
                | if passthrough { WS_EX_TRANSPARENT.0 } else { 0 };
            unsafe { SetWindowLongPtrW(window.0, GWL_EXSTYLE, proposed as isize) };
            let actual = ex_style(window.0) as u32;
            assert_ne!(actual & WS_EX_NOACTIVATE.0, 0);
            assert_ne!(actual & WS_EX_LAYERED.0, 0);
            assert_ne!(actual & WS_EX_NOREDIRECTIONBITMAP.0, 0);
            assert_ne!(actual & WS_EX_TOOLWINDOW.0, 0);
            assert_ne!(actual & WS_EX_ACCEPTFILES.0, 0);
            assert_eq!(actual & WS_EX_APPWINDOW.0, 0);
            assert_eq!(click_through(window.0), passthrough);
        }
    }

    #[test]
    fn obs_updates_existing_style_guard_and_mouse_clicks_do_not_activate() {
        let window = TestWindow::new(true);
        for obs in [false, true, false] {
            apply_pet_style(window.0, obs).unwrap();
            unsafe { SetWindowLongPtrW(window.0, GWL_EXSTYLE, WS_EX_ACCEPTFILES.0 as isize) };
            let actual = ex_style(window.0) as u32;
            assert_ne!(actual & WS_EX_NOACTIVATE.0, 0);
            assert_ne!(actual & WS_EX_LAYERED.0, 0);
            assert_ne!(actual & WS_EX_NOREDIRECTIONBITMAP.0, 0);
            assert_eq!(actual & WS_EX_APPWINDOW.0 != 0, obs);
            assert_eq!(actual & WS_EX_TOOLWINDOW.0 != 0, !obs);
            let activation = unsafe { SendMessageW(window.0, WM_MOUSEACTIVATE, None, None) };
            assert_eq!(activation.0, MA_NOACTIVATE as isize);
        }
    }

    #[test]
    fn shaped_popup_keeps_native_presentation_styles_after_winit_replacement() {
        let window = TestWindow::new(false);
        apply_pet_style(window.0, false).unwrap();
        apply_popup_style(window.0).unwrap();
        for proposed in [
            WS_EX_APPWINDOW.0,
            WS_EX_LAYERED.0 | WS_EX_TRANSPARENT.0 | WS_EX_ACCEPTFILES.0,
        ] {
            unsafe {
                SetWindowLongPtrW(window.0, GWL_EXSTYLE, proposed as isize);
            }
            let actual = ex_style(window.0) as u32;
            assert_ne!(actual & WS_EX_NOACTIVATE.0, 0);
            assert_ne!(actual & WS_EX_TOOLWINDOW.0, 0);
            assert_eq!(
                actual
                    & (WS_EX_LAYERED.0
                        | WS_EX_TRANSPARENT.0
                        | WS_EX_NOREDIRECTIONBITMAP.0
                        | WS_EX_APPWINDOW.0),
                0
            );
            assert_eq!(
                unsafe { SendMessageW(window.0, WM_MOUSEACTIVATE, None, None) }.0,
                MA_NOACTIVATE as isize
            );
        }
        // The same guard can still apply the model surface's own style.
        apply_pet_style(window.0, false).unwrap();
        assert_ne!(ex_style(window.0) as u32 & WS_EX_LAYERED.0, 0);
    }
}
