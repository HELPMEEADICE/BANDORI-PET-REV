//! X11 desktop integration. Coordinates are X server pixels, matching winit's
//! physical positions even when a monitor has a non-unit UI scale.

use std::cell::RefCell;

use winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
use winit::window::Window;
use x11rb::connection::Connection;
use x11rb::protocol::randr::ConnectionExt as _;
use x11rb::protocol::xproto::{
    AtomEnum, ConnectionExt as _, KeyButMask, PropMode, QueryPointerReply,
};
use x11rb::rust_connection::RustConnection;
use x11rb::wrapper::ConnectionExt as _;

use crate::placement::MonitorInfo;

x11rb::atom_manager! {
    Atoms: AtomsCookie {
        _NET_CURRENT_DESKTOP,
        _NET_WORKAREA,
        _NET_WM_STATE,
        _NET_WM_STATE_SKIP_TASKBAR,
        _NET_WM_STATE_SKIP_PAGER,
    }
}

struct Desktop {
    connection: RustConnection,
    screen: usize,
    atoms: Atoms,
}

impl Desktop {
    fn connect() -> Option<Self> {
        let (connection, screen) = x11rb::connect(None).ok()?;
        let atoms = Atoms::new(&connection).ok()?.reply().ok()?;
        Some(Self {
            connection,
            screen,
            atoms,
        })
    }

    fn root(&self) -> u32 {
        self.connection.setup().roots[self.screen].root
    }

    fn property(&self, window: u32, atom: u32, type_: AtomEnum) -> Option<Vec<u32>> {
        let reply = self
            .connection
            .get_property(false, window, atom, type_, 0, 4096)
            .ok()?
            .reply()
            .ok()?;
        let values = reply.value32()?.collect();
        Some(values)
    }

    fn pointer(&self) -> Option<QueryPointerReply> {
        self.connection
            .query_pointer(self.root())
            .ok()?
            .reply()
            .ok()
            .filter(|reply| reply.same_screen)
    }

    fn work_area(&self) -> Option<[i32; 4]> {
        let desktop = self
            .property(
                self.root(),
                self.atoms._NET_CURRENT_DESKTOP,
                AtomEnum::CARDINAL,
            )?
            .first()
            .copied()? as usize;
        let areas = self.property(self.root(), self.atoms._NET_WORKAREA, AtomEnum::CARDINAL)?;
        let offset = desktop.checked_mul(4)?;
        let area = areas.get(offset..offset.checked_add(4)?)?;
        (area[2] > 0 && area[3] > 0).then_some([
            area[0] as i32,
            area[1] as i32,
            i32::try_from(area[2]).ok()?,
            i32::try_from(area[3]).ok()?,
        ])
    }

    fn monitors(&self) -> Vec<MonitorInfo> {
        let work = self.work_area();
        // RandR 1.5 monitor objects also describe tiled displays correctly.
        let mut monitors: Vec<_> = self
            .connection
            .randr_get_monitors(self.root(), true)
            .ok()
            .and_then(|cookie| cookie.reply().ok())
            .map(|reply| {
                reply
                    .monitors
                    .into_iter()
                    .filter(|monitor| monitor.width > 0 && monitor.height > 0)
                    .map(|monitor| {
                        let name = self
                            .connection
                            .get_atom_name(monitor.name)
                            .ok()
                            .and_then(|cookie| cookie.reply().ok())
                            .map(|reply| String::from_utf8_lossy(&reply.name).into_owned())
                            .unwrap_or_else(|| format!("monitor-{}", monitor.name));
                        monitor_info(
                            name,
                            [
                                monitor.x.into(),
                                monitor.y.into(),
                                monitor.width.into(),
                                monitor.height.into(),
                            ],
                            work,
                            monitor.primary,
                        )
                    })
                    .collect()
            })
            .unwrap_or_default();
        // Older X servers may only implement RandR 1.2/1.3.
        if monitors.is_empty() {
            if let Some(resources) = self
                .connection
                .randr_get_screen_resources(self.root())
                .ok()
                .and_then(|cookie| cookie.reply().ok())
            {
                let primary = self
                    .connection
                    .randr_get_output_primary(self.root())
                    .ok()
                    .and_then(|cookie| cookie.reply().ok())
                    .map(|reply| reply.output);
                for output in resources.outputs {
                    let Some(info) = self
                        .connection
                        .randr_get_output_info(output, resources.config_timestamp)
                        .ok()
                        .and_then(|cookie| cookie.reply().ok())
                        .filter(|info| info.crtc != 0)
                    else {
                        continue;
                    };
                    let Some(crtc) = self
                        .connection
                        .randr_get_crtc_info(info.crtc, resources.config_timestamp)
                        .ok()
                        .and_then(|cookie| cookie.reply().ok())
                        .filter(|crtc| crtc.width > 0 && crtc.height > 0)
                    else {
                        continue;
                    };
                    monitors.push(monitor_info(
                        String::from_utf8_lossy(&info.name).into_owned(),
                        [
                            crtc.x.into(),
                            crtc.y.into(),
                            crtc.width.into(),
                            crtc.height.into(),
                        ],
                        work,
                        primary == Some(output),
                    ));
                }
            }
        }
        if monitors.is_empty() {
            let screen = &self.connection.setup().roots[self.screen];
            monitors.push(monitor_info(
                format!("screen-{}", self.screen),
                [
                    0,
                    0,
                    screen.width_in_pixels.into(),
                    screen.height_in_pixels.into(),
                ],
                work,
                true,
            ));
        }
        if !monitors.iter().any(|monitor| monitor.is_primary) {
            monitors[0].is_primary = true;
        }
        monitors
    }
}

thread_local! {
    // Reuse the connection rather than reconnecting for each role on every frame.
    static DESKTOP: RefCell<Option<Desktop>> = RefCell::new(Desktop::connect());
}

/// Global mouse position, also available while a window passes input through.
pub fn cursor_position() -> Option<(f32, f32)> {
    DESKTOP.with(|desktop| {
        let desktop = desktop.borrow();
        let pointer = desktop.as_ref()?.pointer()?;
        Some((pointer.root_x.into(), pointer.root_y.into()))
    })
}

/// Poll the first three buttons without grabbing input or changing focus.
pub fn mouse_down() -> bool {
    DESKTOP.with(|desktop| {
        desktop
            .borrow()
            .as_ref()
            .and_then(Desktop::pointer)
            .is_some_and(|pointer| {
                pointer
                    .mask
                    .intersects(KeyButMask::BUTTON1 | KeyButMask::BUTTON2 | KeyButMask::BUTTON3)
            })
    })
}

/// Current monitor layout, including panel reservations when advertised by the WM.
pub fn monitors() -> Vec<MonitorInfo> {
    DESKTOP.with(|desktop| {
        desktop
            .borrow()
            .as_ref()
            .map(Desktop::monitors)
            .unwrap_or_default()
    })
}

/// Set these hints before mapping a pet window. Preserve winit's ABOVE state.
pub fn apply_overlay_style(window: &Window) {
    let Ok(handle) = window.window_handle() else {
        return;
    };
    let RawWindowHandle::Xlib(handle) = handle.as_raw() else {
        return;
    };
    DESKTOP.with(|desktop| {
        let desktop = desktop.borrow();
        let Some(desktop) = desktop.as_ref() else {
            return;
        };
        let id = handle.window as u32;
        let mut states = desktop
            .property(id, desktop.atoms._NET_WM_STATE, AtomEnum::ATOM)
            .unwrap_or_default();
        for atom in [
            desktop.atoms._NET_WM_STATE_SKIP_TASKBAR,
            desktop.atoms._NET_WM_STATE_SKIP_PAGER,
        ] {
            if !states.contains(&atom) {
                states.push(atom);
            }
        }
        let result = desktop.connection.change_property32(
            PropMode::REPLACE,
            id,
            desktop.atoms._NET_WM_STATE,
            AtomEnum::ATOM,
            &states,
        );
        if let Err(error) = result.and_then(|_| desktop.connection.flush()) {
            tracing::warn!(%error, "could not set X11 overlay hints");
        }
    });
}

fn monitor_info(
    name: String,
    geometry: [i32; 4],
    work: Option<[i32; 4]>,
    is_primary: bool,
) -> MonitorInfo {
    MonitorInfo {
        name,
        manufacturer: String::new(),
        model: String::new(),
        serial: String::new(),
        geometry,
        work: work
            .map(|work| intersect_work_area(geometry, work))
            .unwrap_or(geometry),
        is_primary,
    }
}

fn intersect_work_area(geometry: [i32; 4], work: [i32; 4]) -> [i32; 4] {
    let left = geometry[0].max(work[0]);
    let top = geometry[1].max(work[1]);
    let right = (geometry[0] + geometry[2]).min(work[0].saturating_add(work[2]));
    let bottom = (geometry[1] + geometry[3]).min(work[1].saturating_add(work[3]));
    if right > left && bottom > top {
        [left, top, right - left, bottom - top]
    } else {
        geometry
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn work_area_is_clipped_per_monitor_and_handles_negative_origins() {
        assert_eq!(
            intersect_work_area([0, 0, 1920, 1080], [0, 32, 3840, 1008]),
            [0, 32, 1920, 1008]
        );
        assert_eq!(
            intersect_work_area([1920, 0, 1920, 1080], [0, 32, 3840, 1008]),
            [1920, 32, 1920, 1008]
        );
        assert_eq!(
            intersect_work_area([-1920, 0, 1920, 1080], [-1920, 24, 3840, 1056]),
            [-1920, 24, 1920, 1056]
        );
        assert_eq!(
            intersect_work_area([-1920, 0, 1920, 1080], [0, 0, 1920, 1080]),
            [-1920, 0, 1920, 1080]
        );
    }
}
