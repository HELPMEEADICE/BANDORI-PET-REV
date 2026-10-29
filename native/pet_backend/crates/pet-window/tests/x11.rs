//! Run on an isolated X server: xvfb-run cargo test -p pet-window --test x11 -- --ignored
#![cfg(target_os = "linux")]

use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, EventLoop};
use winit::platform::x11::EventLoopBuilderExtX11;
use winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
use winit::window::{Window, WindowId};
use x11rb::connection::Connection;
use x11rb::protocol::shape::{ConnectionExt as _, SK};
use x11rb::protocol::xproto::ConnectionExt as _;

#[derive(Default)]
struct Probe {
    completed: bool,
}

impl ApplicationHandler for Probe {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        let window = event_loop
            .create_window(
                Window::default_attributes()
                    .with_visible(false)
                    .with_active(false)
                    .with_inner_size(winit::dpi::PhysicalSize::new(160, 120)),
            )
            .unwrap();
        let RawWindowHandle::Xlib(handle) = window.window_handle().unwrap().as_raw() else {
            panic!("expected the X11 backend");
        };
        let id = handle.window as u32;
        let (connection, screen) = x11rb::connect(None).unwrap();
        let root = connection.setup().roots[screen].root;
        let before = connection.query_pointer(root).unwrap().reply().unwrap();
        connection
            .warp_pointer(x11rb::NONE, root, 0, 0, 0, 0, 80, 60)
            .unwrap()
            .check()
            .unwrap();
        assert_eq!(pet_window::x11::cursor_position(), Some((80., 60.)));
        connection
            .warp_pointer(x11rb::NONE, root, 0, 0, 0, 0, before.root_x, before.root_y)
            .unwrap()
            .check()
            .unwrap();

        let monitors = pet_window::placement::monitors();
        assert!(!monitors.is_empty());
        assert!(monitors.iter().any(|monitor| monitor.is_primary));
        assert!(monitors
            .iter()
            .all(|monitor| monitor.work[2] > 0 && monitor.work[3] > 0));

        pet_window::x11::apply_overlay_style(&window);
        // Check the server-side input shape, not just winit's cached flag. The
        // query uses another connection, so allow the first connection to flush.
        for enabled in [false, true] {
            window.set_cursor_hittest(enabled).unwrap();
            // A geometry round trip flushes winit's queued shape request before
            // querying the input region from this test's separate connection.
            let _ = window.outer_position().unwrap();
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(2);
            loop {
                let rectangles = connection
                    .shape_get_rectangles(id, SK::INPUT)
                    .unwrap()
                    .reply()
                    .unwrap()
                    .rectangles;
                if rectangles.is_empty() != enabled {
                    break;
                }
                assert!(
                    std::time::Instant::now() < deadline,
                    "X11 click-through did not change"
                );
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
        }
        self.completed = true;
        event_loop.exit();
    }

    fn window_event(&mut self, _: &ActiveEventLoop, _: WindowId, _: WindowEvent) {}
}

#[test]
#[ignore = "requires an isolated X11 server; moves the pointer briefly"]
fn global_pointer_monitors_and_input_passthrough() {
    let mut builder = EventLoop::builder();
    builder.with_x11().with_any_thread(true);
    let event_loop = builder.build().unwrap();
    let mut probe = Probe::default();
    event_loop.run_app(&mut probe).unwrap();
    assert!(probe.completed);
}
