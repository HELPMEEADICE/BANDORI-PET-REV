//! Monitor enumeration, placement persistence (14 fields) and autostart.
//!
//! Restore policy from spec §2.8: use the absolute coordinates while the same
//! monitor is present with the same geometry; otherwise re-project the stored
//! relative position onto the current work area; if the monitor is gone, fall back
//! to the primary monitor center.

use std::path::Path;

use pet_config::Placement;
use tracing::debug;

/// One monitor as reported by the OS.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MonitorInfo {
    /// Device name, e.g. `\\.\DISPLAY1`.
    pub name: String,
    /// Adapter / monitor manufacturer string.
    pub manufacturer: String,
    /// Monitor model string.
    pub model: String,
    /// Serial or device-id suffix.
    pub serial: String,
    /// Full rect `[x, y, width, height]` in physical pixels.
    pub geometry: [i32; 4],
    /// Work area rect (taskbar excluded).
    pub work: [i32; 4],
    /// Whether this is the primary monitor.
    pub is_primary: bool,
}

impl MonitorInfo {
    /// Width / height helpers.
    pub fn size(&self) -> (i32, i32) {
        (self.geometry[2], self.geometry[3])
    }
}

/// Why a position was chosen (useful in logs and tests).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PositionDecision {
    /// The stored absolute position was reused (same monitor, same geometry).
    Absolute,
    /// The relative position was re-projected onto the current work area.
    Relative,
    /// Nothing usable was stored: default bottom-right placement.
    Default,
    /// The monitor disappeared: fall back to the primary monitor center.
    Fallback,
}

/// Result of resolving a stored placement.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResolvedPosition {
    /// Left edge in physical pixels.
    pub x: i32,
    /// Top edge in physical pixels.
    pub y: i32,
    /// Which rule produced it.
    pub decision: PositionDecision,
    /// Monitor the window ended up on.
    pub monitor: Option<MonitorInfo>,
}

/// Enumerates all monitors.
#[cfg(windows)]
pub fn monitors() -> Vec<MonitorInfo> {
    win32_monitors::enumerate()
}

/// Enumerates AppKit screens and their visible work areas.
#[cfg(target_os = "macos")]
pub fn monitors() -> Vec<MonitorInfo> {
    crate::macos::monitors(None)
}

/// Enumerates XRandR monitors and EWMH work areas in physical pixels.
#[cfg(target_os = "linux")]
pub fn monitors() -> Vec<MonitorInfo> {
    crate::x11::monitors()
}

/// Enumerates all monitors (unsupported-platform stub).
#[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
pub fn monitors() -> Vec<MonitorInfo> {
    vec![MonitorInfo {
        name: "display1".to_owned(),
        manufacturer: String::new(),
        model: String::new(),
        serial: String::new(),
        geometry: [0, 0, 1920, 1080],
        work: [0, 0, 1920, 1040],
        is_primary: true,
    }]
}

/// Work areas in the coordinate system of one window. On macOS the same
/// backing scale must be applied to all screen origins as to the window origin.
pub fn monitors_for_scale(scale: f64) -> Vec<MonitorInfo> {
    #[cfg(target_os = "macos")]
    {
        crate::macos::monitors(Some(scale))
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = scale;
        monitors()
    }
}

/// Re-expresses a saved physical placement at a different backing scale while
/// preserving its logical desktop position. Used when restoring macOS windows.
pub fn placement_at_scale(placement: &Placement, scale: f64) -> Placement {
    let mut result = placement.clone();
    if placement.is_unset() {
        return result;
    }
    let previous = placement.device_pixel_ratio;
    if previous.is_finite() && previous > 0.0 && scale.is_finite() && scale > 0.0 {
        let ratio = scale / previous;
        let convert = |value: i32| (value as f64 * ratio).round() as i32;
        result.x = convert(result.x);
        result.y = convert(result.y);
        result.width = (result.width as f64 * ratio).round() as u32;
        result.height = (result.height as f64 * ratio).round() as u32;
        result.screen_geometry = result.screen_geometry.map(convert);
        result.screen_available_geometry = result.screen_available_geometry.map(convert);
        result.right_offset = convert(result.right_offset);
        result.bottom_offset = convert(result.bottom_offset);
        result.device_pixel_ratio = scale;
    }
    result
}

fn clamp(value: i32, low: i32, high: i32) -> i32 {
    if high < low {
        low
    } else {
        value.clamp(low, high)
    }
}

/// Resolves the window position for a stored placement.
pub fn resolve_position(
    placement: &Placement,
    size: (u32, u32),
    monitors: &[MonitorInfo],
    primary: Option<&MonitorInfo>,
) -> ResolvedPosition {
    let width = size.0 as i32;
    let height = size.1 as i32;

    let default_for = |monitor: Option<&MonitorInfo>, decision: PositionDecision| {
        let fallback = primary
            .or_else(|| monitors.first())
            .cloned()
            .unwrap_or(MonitorInfo {
                name: "primary".to_owned(),
                manufacturer: String::new(),
                model: String::new(),
                serial: String::new(),
                geometry: [0, 0, 1920, 1080],
                work: [0, 0, 1920, 1040],
                is_primary: true,
            });
        let work = monitor.unwrap_or(&fallback).work;
        let right_offset = if placement.right_offset > 0 {
            placement.right_offset
        } else {
            28
        };
        let bottom_offset = if placement.bottom_offset >= 0 {
            placement.bottom_offset
        } else {
            1
        };
        let x = work[0] + work[2] - width - right_offset;
        let y = work[1] + work[3] - height - bottom_offset;
        ResolvedPosition {
            x: clamp(x, work[0], work[0] + work[2] - width.min(work[2])),
            y: clamp(y, work[1], work[1] + work[3] - height.min(work[3])),
            decision,
            monitor: monitor.cloned().or(Some(fallback)),
        }
    };

    if placement.is_unset() {
        let monitor = primary.cloned().or_else(|| monitors.first().cloned());
        return default_for(monitor.as_ref(), PositionDecision::Default);
    }

    let matching = monitors
        .iter()
        .find(|monitor| monitor.name.eq_ignore_ascii_case(&placement.screen_name))
        .or_else(|| {
            monitors
                .iter()
                .find(|monitor| monitor.geometry == placement.screen_geometry)
        })
        .or_else(|| {
            // Legacy mirrored coordinates have no monitor fingerprint yet.
            placement
                .screen_name
                .is_empty()
                .then(|| {
                    monitors
                        .iter()
                        .find(|monitor| {
                            let [x, y, w, h] = monitor.geometry;
                            placement.x >= x
                                && placement.x < x + w
                                && placement.y >= y
                                && placement.y < y + h
                        })
                        .or(primary)
                })
                .flatten()
        });

    match matching {
        Some(monitor) => {
            let same_geometry =
                placement.screen_name.is_empty() || monitor.geometry == placement.screen_geometry;
            if same_geometry {
                let work = monitor.work;
                // A pet's transparent animation viewport may extend beyond the
                // screen, or even be taller than it. Preserve the user's exact
                // position while any part of the window remains on a monitor;
                // clamping the whole viewport makes pets jump after a restart.
                let visible = monitors.iter().any(|monitor| {
                    let [x, y, w, h] = monitor.geometry.map(i64::from);
                    i64::from(placement.x) < x + w
                        && i64::from(placement.x) + i64::from(size.0) > x
                        && i64::from(placement.y) < y + h
                        && i64::from(placement.y) + i64::from(size.1) > y
                });
                let (x, y) = if visible {
                    (placement.x, placement.y)
                } else {
                    (
                        clamp(placement.x, work[0], work[0] + work[2] - width.min(work[2])),
                        clamp(
                            placement.y,
                            work[1],
                            work[1] + work[3] - height.min(work[3]),
                        ),
                    )
                };
                ResolvedPosition {
                    x,
                    y,
                    decision: PositionDecision::Absolute,
                    monitor: Some(monitor.clone()),
                }
            } else {
                let work = monitor.work;
                let relative_x = placement.relative_x.clamp(0.0, 1.0);
                let relative_y = placement.relative_y.clamp(0.0, 1.0);
                let x = work[0] + ((work[2] - width) as f64 * relative_x).round() as i32;
                let y = work[1] + ((work[3] - height) as f64 * relative_y).round() as i32;
                ResolvedPosition {
                    x: clamp(x, work[0], work[0] + (work[2] - width).max(0)),
                    y: clamp(y, work[1], work[1] + (work[3] - height).max(0)),
                    decision: PositionDecision::Relative,
                    monitor: Some(monitor.clone()),
                }
            }
        }
        None => {
            debug!(
                screen = %placement.screen_name,
                "stored monitor not found, falling back to primary"
            );
            default_for(
                primary.or_else(|| monitors.first()),
                PositionDecision::Fallback,
            )
        }
    }
}

/// Finds a position with the least overlap, keeping new roles inside the work
/// area. Existing windows are left alone; saved positions bypass this helper.
pub fn unoccupied_position(
    preferred: (i32, i32),
    size: (u32, u32),
    work: [i32; 4],
    occupied: &[(i32, i32, u32, u32)],
) -> (i32, i32) {
    let max_x = work[0] + (work[2] - size.0 as i32).max(0);
    let max_y = work[1] + (work[3] - size.1 as i32).max(0);
    let preferred = (
        preferred.0.clamp(work[0], max_x),
        preferred.1.clamp(work[1], max_y),
    );
    let overlap = |(x, y): (i32, i32)| -> i64 {
        occupied
            .iter()
            .map(|&(ox, oy, width, height)| {
                let w = ((x as i64 + size.0 as i64).min(ox as i64 + width as i64)
                    - (x as i64).max(ox as i64))
                .max(0);
                let h = ((y as i64 + size.1 as i64).min(oy as i64 + height as i64)
                    - (y as i64).max(oy as i64))
                .max(0);
                w * h
            })
            .sum()
    };
    let mut best = preferred;
    let mut best_overlap = overlap(best);
    if best_overlap == 0 {
        return best;
    }
    for y in (work[1]..=max_y).rev().step_by(48) {
        for x in (work[0]..=max_x).rev().step_by(48) {
            let candidate_overlap = overlap((x, y));
            if candidate_overlap < best_overlap {
                best = (x, y);
                best_overlap = candidate_overlap;
                if best_overlap == 0 {
                    return best;
                }
            }
        }
    }
    best
}

/// Records the 14 placement fields from the current window rect and monitor.
pub fn record_placement(rect: (i32, i32, u32, u32), dpr: f64, monitor: &MonitorInfo) -> Placement {
    let (x, y, width, height) = rect;
    let work = monitor.work;
    let relative_x = if (work[2] - width as i32).max(1) == 0 {
        0.0
    } else {
        ((x - work[0]) as f64 / (work[2] - width as i32).max(1) as f64).clamp(0.0, 1.0)
    };
    let relative_y = if (work[3] - height as i32).max(1) == 0 {
        0.0
    } else {
        ((y - work[1]) as f64 / (work[3] - height as i32).max(1) as f64).clamp(0.0, 1.0)
    };
    Placement {
        x,
        y,
        width,
        height,
        screen_name: monitor.name.clone(),
        screen_serial: monitor.serial.clone(),
        screen_manufacturer: monitor.manufacturer.clone(),
        screen_model: monitor.model.clone(),
        screen_geometry: monitor.geometry,
        screen_available_geometry: monitor.work,
        relative_x,
        relative_y,
        right_offset: (work[0] + work[2] - (x + width as i32)).max(0),
        bottom_offset: (work[1] + work[3] - (y + height as i32)).max(0),
        device_pixel_ratio: dpr,
    }
}

/// Returns the monitor whose rect contains `point`, else the nearest one.
pub fn monitor_at(monitors: &[MonitorInfo], point: (i32, i32)) -> Option<MonitorInfo> {
    monitors
        .iter()
        .find(|monitor| {
            let [x, y, w, h] = monitor.geometry;
            point.0 >= x && point.0 < x + w && point.1 >= y && point.1 < y + h
        })
        .or_else(|| monitors.first())
        .cloned()
}

/// Reads whether the app is registered for autostart.
pub fn auto_start_enabled(exe: &Path) -> bool {
    #[cfg(windows)]
    {
        registry::read_run_value(exe)
    }
    #[cfg(target_os = "macos")]
    {
        crate::launch_agent::enabled(exe)
    }
    #[cfg(target_os = "linux")]
    {
        crate::autostart::enabled(exe)
    }
    #[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
    {
        let _ = exe;
        false
    }
}

/// Enables or disables autostart for `exe`.
pub fn set_auto_start(exe: &Path, enabled: bool) -> std::io::Result<()> {
    #[cfg(windows)]
    {
        registry::write_run_value(exe, enabled)
    }
    #[cfg(target_os = "macos")]
    {
        crate::launch_agent::set_enabled(exe, enabled)
    }
    #[cfg(target_os = "linux")]
    {
        crate::autostart::set_enabled(exe, enabled)
    }
    #[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
    {
        let _ = (exe, enabled);
        Ok(())
    }
}

#[cfg(windows)]
mod win32_monitors {
    //! `EnumDisplayMonitors` + `EnumDisplayDevicesW` wrappers.

    use super::MonitorInfo;
    use tracing::warn;
    use windows::core::BOOL;
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::{LPARAM, RECT};
    use windows::Win32::Graphics::Gdi::{
        EnumDisplayDevicesW, EnumDisplayMonitors, GetMonitorInfoW, DISPLAY_DEVICEW, HDC, HMONITOR,
        MONITORINFOEXW,
    };

    pub fn enumerate() -> Vec<MonitorInfo> {
        let mut collected: Vec<MonitorInfo> = Vec::new();
        let data = &mut collected as *mut Vec<MonitorInfo>;
        let result = unsafe {
            EnumDisplayMonitors(None, None, Some(monitor_callback), LPARAM(data as isize))
        };
        if !result.as_bool() {
            warn!("EnumDisplayMonitors failed");
        }
        collected
    }

    unsafe extern "system" fn monitor_callback(
        monitor: HMONITOR,
        _hdc: HDC,
        _rect: *mut RECT,
        data: LPARAM,
    ) -> BOOL {
        let collected = unsafe { &mut *(data.0 as *mut Vec<MonitorInfo>) };
        let mut info = MONITORINFOEXW::default();
        info.monitorInfo.cbSize = std::mem::size_of::<MONITORINFOEXW>() as u32;
        if !unsafe { GetMonitorInfoW(monitor, &mut info.monitorInfo) }.as_bool() {
            return BOOL(1);
        }
        let name = wide_to_string(&info.szDevice);
        let geometry = [
            info.monitorInfo.rcMonitor.left,
            info.monitorInfo.rcMonitor.top,
            info.monitorInfo.rcMonitor.right - info.monitorInfo.rcMonitor.left,
            info.monitorInfo.rcMonitor.bottom - info.monitorInfo.rcMonitor.top,
        ];
        let work = [
            info.monitorInfo.rcWork.left,
            info.monitorInfo.rcWork.top,
            info.monitorInfo.rcWork.right - info.monitorInfo.rcWork.left,
            info.monitorInfo.rcWork.bottom - info.monitorInfo.rcWork.top,
        ];
        let (manufacturer, model, serial) = device_strings(&name);
        collected.push(MonitorInfo {
            name,
            manufacturer,
            model,
            serial,
            geometry,
            work,
            is_primary: (info.monitorInfo.dwFlags & 1) != 0,
        });
        BOOL(1)
    }

    fn device_strings(device_name: &str) -> (String, String, String) {
        let wide: Vec<u16> = device_name
            .encode_utf16()
            .chain(std::iter::once(0))
            .collect();
        let mut device = DISPLAY_DEVICEW {
            cb: std::mem::size_of::<DISPLAY_DEVICEW>() as u32,
            ..Default::default()
        };
        let ok = unsafe { EnumDisplayDevicesW(PCWSTR(wide.as_ptr()), 0, &mut device, 0) };
        if !ok.as_bool() {
            return (String::new(), String::new(), String::new());
        }
        let text = wide_to_string(&device.DeviceString);
        let id = wide_to_string(&device.DeviceID);
        let serial = id.rsplit('\\').next().unwrap_or_default().to_owned();
        (text.clone(), text, serial)
    }

    fn wide_to_string(buffer: &[u16]) -> String {
        let end = buffer
            .iter()
            .position(|unit| *unit == 0)
            .unwrap_or(buffer.len());
        String::from_utf16_lossy(&buffer[..end])
    }
}

#[cfg(windows)]
mod registry {
    //! `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` autostart entry.

    use std::path::Path;
    use windows::core::{w, PCWSTR};
    use windows::Win32::Foundation::ERROR_SUCCESS;
    use windows::Win32::System::Registry::{
        RegCloseKey, RegCreateKeyExW, RegDeleteValueW, RegQueryValueExW, RegSetValueExW, HKEY,
        HKEY_CURRENT_USER, KEY_QUERY_VALUE, KEY_SET_VALUE, REG_OPEN_CREATE_OPTIONS, REG_SAM_FLAGS,
        REG_SZ,
    };

    const VALUE_NAME: PCWSTR = w!("BandoriPetLite");
    const KEY_PATH: PCWSTR = w!(r"Software\Microsoft\Windows\CurrentVersion\Run");

    fn open_key(access: REG_SAM_FLAGS) -> Option<HKEY> {
        let mut key = HKEY::default();
        let result = unsafe {
            RegCreateKeyExW(
                HKEY_CURRENT_USER,
                KEY_PATH,
                None,
                PCWSTR::null(),
                REG_OPEN_CREATE_OPTIONS(0),
                access,
                None,
                &mut key,
                None,
            )
        };
        (result == ERROR_SUCCESS).then_some(key)
    }

    pub fn read_run_value(exe: &Path) -> bool {
        let Some(key) = open_key(KEY_QUERY_VALUE) else {
            return false;
        };
        let mut buffer = [0u16; 1024];
        let mut size = (buffer.len() * 2) as u32;
        let status = unsafe {
            RegQueryValueExW(
                key,
                VALUE_NAME,
                None,
                None,
                Some(buffer.as_mut_ptr() as *mut u8),
                Some(&mut size),
            )
        };
        let _ = unsafe { RegCloseKey(key) };
        if status != ERROR_SUCCESS {
            return false;
        }
        let end = buffer
            .iter()
            .position(|unit| *unit == 0)
            .unwrap_or(buffer.len());
        let value = String::from_utf16_lossy(&buffer[..end]);
        value.to_ascii_lowercase().contains(
            &exe.to_string_lossy()
                .to_ascii_lowercase()
                .trim_matches('"')
                .to_owned(),
        )
    }

    pub fn write_run_value(exe: &Path, enabled: bool) -> std::io::Result<()> {
        let Some(key) = open_key(KEY_SET_VALUE) else {
            return Err(std::io::Error::other("failed to open Run key"));
        };
        let status = if enabled {
            let value = format!("\"{}\"", exe.display());
            let wide: Vec<u16> = value.encode_utf16().chain(std::iter::once(0)).collect();
            unsafe {
                RegSetValueExW(
                    key,
                    VALUE_NAME,
                    None,
                    REG_SZ,
                    Some(std::slice::from_raw_parts(
                        wide.as_ptr() as *const u8,
                        wide.len() * 2,
                    )),
                )
            }
        } else {
            unsafe { RegDeleteValueW(key, VALUE_NAME) }
        };
        let _ = unsafe { RegCloseKey(key) };
        if status == ERROR_SUCCESS {
            Ok(())
        } else {
            Err(std::io::Error::other(format!(
                "registry update failed: {status:?}"
            )))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restoring_a_retina_placement_at_another_scale_preserves_desktop_points() {
        let stored = Placement {
            x: -1800,
            y: 600,
            width: 800,
            height: 1200,
            device_pixel_ratio: 2.0,
            screen_geometry: [-2400, 0, 2400, 1800],
            screen_available_geometry: [-2400, 48, 2400, 1652],
            relative_x: 0.25,
            bottom_offset: 2,
            ..Default::default()
        };
        let scaled = placement_at_scale(&stored, 1.0);
        assert_eq!((scaled.x, scaled.y), (-900, 300));
        assert_eq!(scaled.screen_geometry, [-1200, 0, 1200, 900]);
        assert_eq!(scaled.screen_available_geometry, [-1200, 24, 1200, 826]);
        assert_eq!((scaled.width, scaled.height), (400, 600));
        assert_eq!(scaled.relative_x, stored.relative_x);
        assert_eq!(placement_at_scale(&scaled, 2.0), stored);
        assert!(placement_at_scale(&Placement::default(), 2.0).is_unset());
    }

    fn monitor(name: &str, geometry: [i32; 4], work: [i32; 4]) -> MonitorInfo {
        MonitorInfo {
            name: name.to_owned(),
            manufacturer: "ACME".to_owned(),
            model: name.to_owned(),
            serial: "0".to_owned(),
            geometry,
            work,
            is_primary: name == "primary",
        }
    }

    #[test]
    fn unset_placement_goes_bottom_right() {
        let primary = monitor("primary", [0, 0, 1920, 1080], [0, 0, 1920, 1040]);
        let resolved = resolve_position(
            &Placement::default(),
            (500, 625),
            std::slice::from_ref(&primary),
            Some(&primary),
        );
        assert_eq!(resolved.decision, PositionDecision::Default);
        assert_eq!(resolved.x, 1920 - 500 - 28);
        assert_eq!(resolved.y, 1040 - 625 - 1);
    }

    #[test]
    fn new_roles_find_independent_positions_without_moving_existing_roles() {
        let work = [0, 0, 1920, 1040];
        let size = (500, 625);
        let first = (1392, 414);
        let mut occupied = vec![(first.0, first.1, size.0, size.1)];
        for _ in 0..2 {
            let next = unoccupied_position(first, size, work, &occupied);
            assert!(next.0 >= 0 && next.0 + 500 <= 1920);
            assert!(next.1 >= 0 && next.1 + 625 <= 1040);
            assert!(occupied.iter().all(|&(x, y, width, height)| {
                next.0 + 500 <= x
                    || x + width as i32 <= next.0
                    || next.1 + 625 <= y
                    || y + height as i32 <= next.1
            }));
            occupied.push((next.0, next.1, size.0, size.1));
        }
        assert_eq!(occupied[0], (1392, 414, 500, 625));
    }

    #[test]
    fn crowded_monitor_keeps_roles_on_screen() {
        let next = unoccupied_position(
            (900, 900),
            (500, 625),
            [-800, 0, 800, 700],
            &[(-800, 0, 500, 625)],
        );
        assert!((-800..=-500).contains(&next.0));
        assert!((0..=75).contains(&next.1));
        assert_ne!(next, (-800, 0));
    }

    #[test]
    fn same_monitor_reuses_absolute_coordinates() {
        let primary = monitor("primary", [0, 0, 1920, 1080], [0, 0, 1920, 1040]);
        let placement = Placement {
            x: 100,
            y: 200,
            screen_name: "primary".to_owned(),
            screen_geometry: [0, 0, 1920, 1080],
            ..Placement::default()
        };
        let resolved = resolve_position(
            &placement,
            (500, 625),
            std::slice::from_ref(&primary),
            Some(&primary),
        );
        assert_eq!(resolved.decision, PositionDecision::Absolute);
        assert_eq!((resolved.x, resolved.y), (100, 200));
    }

    #[test]
    fn saved_positions_survive_viewports_extending_beyond_the_screen() {
        let primary = monitor("primary", [0, 0, 2560, 1600], [0, 0, 2560, 1540]);
        for rect in [
            (-1, -1, 700, 900),
            (-120, 200, 700, 900),
            (2200, 1000, 700, 900),
            (1100, -400, 1395, 2064),
            (1100, 250, 1395, 2064),
            (200, 950, 500, 625),
        ] {
            let stored = record_placement(rect, 1.5, &primary);
            let resolved = resolve_position(
                &stored,
                (rect.2, rect.3),
                std::slice::from_ref(&primary),
                Some(&primary),
            );
            assert_eq!(resolved.decision, PositionDecision::Absolute);
            assert_eq!((resolved.x, resolved.y), (rect.0, rect.1), "{rect:?}");
        }
    }

    #[test]
    fn negative_coordinates_on_a_secondary_monitor_survive_a_restart() {
        let primary = monitor("primary", [0, 0, 1920, 1080], [0, 0, 1920, 1040]);
        let secondary = monitor(
            "secondary",
            [-1920, -1080, 1920, 1080],
            [-1920, -1080, 1920, 1040],
        );
        let stored = record_placement((-2020, -1180, 700, 900), 1.0, &secondary);
        let resolved = resolve_position(
            &stored,
            (700, 900),
            &[primary.clone(), secondary],
            Some(&primary),
        );
        assert_eq!(resolved.decision, PositionDecision::Absolute);
        assert_eq!((resolved.x, resolved.y), (-2020, -1180));
    }

    #[test]
    fn completely_offscreen_saved_positions_are_recovered() {
        let primary = monitor("primary", [0, 0, 1920, 1080], [0, 0, 1920, 1040]);
        for (x, y, expected) in [
            (-600, 200, (0, 200)),
            (1920, 200, (1420, 200)),
            (100, -625, (100, 0)),
            (100, 1080, (100, 415)),
        ] {
            let stored = record_placement((x, y, 500, 625), 1.0, &primary);
            let resolved = resolve_position(
                &stored,
                (500, 625),
                std::slice::from_ref(&primary),
                Some(&primary),
            );
            assert_eq!((resolved.x, resolved.y), expected);
        }
    }

    #[test]
    fn legacy_coordinates_work_without_a_monitor_fingerprint() {
        let primary = monitor("primary", [0, 0, 2560, 1440], [0, 0, 2560, 1400]);
        let placement = Placement {
            x: 700,
            y: 250,
            ..Placement::default()
        };
        let resolved = resolve_position(
            &placement,
            (500, 625),
            std::slice::from_ref(&primary),
            Some(&primary),
        );
        assert_eq!((resolved.x, resolved.y), (700, 250));
        assert_eq!(resolved.decision, PositionDecision::Absolute);
    }

    #[test]
    fn changed_geometry_uses_relative_position() {
        let primary = monitor("primary", [0, 0, 2560, 1440], [0, 0, 2560, 1400]);
        let placement = Placement {
            x: 100,
            y: 200,
            screen_name: "primary".to_owned(),
            screen_geometry: [0, 0, 1920, 1080],
            relative_x: 1.0,
            relative_y: 1.0,
            ..Placement::default()
        };
        let resolved = resolve_position(
            &placement,
            (500, 625),
            std::slice::from_ref(&primary),
            Some(&primary),
        );
        assert_eq!(resolved.decision, PositionDecision::Relative);
        assert_eq!(resolved.x, 2560 - 500);
        assert_eq!(resolved.y, 1400 - 625);
    }

    #[test]
    fn missing_monitor_falls_back_to_primary() {
        let primary = monitor("primary", [0, 0, 1920, 1080], [0, 0, 1920, 1040]);
        let placement = Placement {
            x: 4000,
            y: 100,
            screen_name: "\\\\.\\DISPLAY9".to_owned(),
            screen_geometry: [3000, 0, 1920, 1080],
            ..Placement::default()
        };
        let resolved = resolve_position(
            &placement,
            (500, 625),
            std::slice::from_ref(&primary),
            Some(&primary),
        );
        assert_eq!(resolved.decision, PositionDecision::Fallback);
        assert!(resolved.x <= 1920 - 500);
    }

    #[test]
    fn recording_round_trips_the_fourteen_fields() {
        let primary = monitor("primary", [0, 0, 1920, 1080], [0, 0, 1920, 1040]);
        let placement = record_placement((1400, 400, 500, 625), 1.5, &primary);
        assert_eq!(placement.screen_name, "primary");
        assert_eq!(placement.width, 500);
        assert_eq!(placement.relative_x, 1400.0 / 1420.0);
        let resolved = resolve_position(
            &placement,
            (500, 625),
            std::slice::from_ref(&primary),
            Some(&primary),
        );
        assert_eq!((resolved.x, resolved.y), (1400, 400));
    }
}
