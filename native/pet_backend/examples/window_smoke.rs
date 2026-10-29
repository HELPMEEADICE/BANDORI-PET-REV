//! Real window lifecycle regression without downloaded character assets.
//! Run on a graphical desktop: cargo run --example window_smoke --locked

#[path = "../src/role.rs"]
#[allow(dead_code)]
mod role;

use std::sync::Arc;
use std::time::{Duration, Instant};

use pet_assets::ModelCache;
use pet_config::{Config, ModelEntry, Paths, PetMode};
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::WindowId;

#[derive(Debug)]
enum Stage {
    Startup,
    TrayRestored,
    #[cfg(target_os = "macos")]
    Occluded,
    #[cfg(target_os = "macos")]
    Unoccluded,
    HiddenStartup,
    SettingsRestored,
}

struct Probe {
    paths: Paths,
    cache: ModelCache,
    config: Config,
    entry: ModelEntry,
    role: Option<role::Role>,
    stage: Stage,
    stage_started: Instant,
    baseline: u64,
    completed: bool,
}

fn assert_hidden(role: &mut role::Role) {
    assert_eq!(role.window.is_visible(), Some(false));
    let frames = role.renderer.frames();
    for _ in 0..pet_render::FAILURE_FUSE + 2 {
        assert!(!role.render());
    }
    assert_eq!(role.renderer.frames(), frames);
    assert!(!role.renderer.is_fused());
}

impl Probe {
    fn transition(&mut self, stage: Stage) {
        self.stage = stage;
        self.stage_started = Instant::now();
        self.baseline = self.role.as_ref().unwrap().renderer.frames();
    }

    fn create_hidden_role(&mut self, event_loop: &ActiveEventLoop) {
        let previous = self.role.take().unwrap();
        let gpu = Arc::clone(previous.renderer.gpu());
        drop(previous);
        self.config.hide_live2d_model = true;
        let mut role = role::Role::create(
            event_loop,
            &self.entry,
            &self.config,
            &self.paths,
            &self.cache,
            Some(gpu),
        )
        .unwrap();
        assert_hidden(&mut role);
        assert_eq!(role.renderer.frames(), 0);
        self.role = Some(role);
        self.transition(Stage::HiddenStartup);
    }
}

impl ApplicationHandler for Probe {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.role.is_none() {
            let role = role::Role::create(
                event_loop,
                &self.entry,
                &self.config,
                &self.paths,
                &self.cache,
                None,
            )
            .unwrap();
            println!("Window smoke adapter: {:?}", role.renderer.adapter_info());
            self.role = Some(role);
            self.stage_started = Instant::now();
        }
    }

    fn window_event(&mut self, _: &ActiveEventLoop, window_id: WindowId, event: WindowEvent) {
        let Some(role) = self
            .role
            .as_mut()
            .filter(|role| role.window.id() == window_id)
        else {
            return;
        };
        match event {
            WindowEvent::RedrawRequested => {
                role.render();
            }
            WindowEvent::Resized(size) => role.renderer.resize(size, role.window.scale_factor()),
            _ => {}
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        if self.completed {
            event_loop.exit();
            return;
        }
        assert!(
            self.stage_started.elapsed() < Duration::from_secs(15),
            "window smoke timed out in {:?}",
            self.stage
        );
        let role = self.role.as_mut().unwrap();
        assert!(
            !role.renderer.is_fused(),
            "renderer fused in {:?}",
            self.stage
        );
        let presented = role.renderer.frames() >= self.baseline + 3
            && self.stage_started.elapsed() >= Duration::from_millis(100);
        match self.stage {
            Stage::Startup if presented => {
                assert_eq!(role.window.is_visible(), Some(true));
                role.set_hidden(true);
                assert_hidden(role);
                role.set_hidden(false);
                self.transition(Stage::TrayRestored);
            }
            Stage::TrayRestored if presented => {
                assert_eq!(role.window.is_visible(), Some(true));
                #[cfg(target_os = "macos")]
                {
                    // Bypass Role's hide guard to exercise real Metal Occluded
                    // results, including more retries than the failure fuse.
                    pet_window::macos::set_visible(&role.window, false);
                    self.transition(Stage::Occluded);
                }
                #[cfg(not(target_os = "macos"))]
                self.create_hidden_role(event_loop);
            }
            #[cfg(target_os = "macos")]
            Stage::Occluded if self.stage_started.elapsed() >= Duration::from_millis(300) => {
                let frames = role.renderer.frames();
                for _ in 0..pet_render::FAILURE_FUSE + 2 {
                    assert!(!role.renderer.render(&role.model_gpu).unwrap());
                }
                assert_eq!(role.renderer.frames(), frames);
                assert!(!role.renderer.is_fused());
                pet_window::macos::set_visible(&role.window, true);
                self.transition(Stage::Unoccluded);
            }
            #[cfg(target_os = "macos")]
            Stage::Unoccluded if presented => self.create_hidden_role(event_loop),
            Stage::HiddenStartup if self.stage_started.elapsed() >= Duration::from_millis(100) => {
                assert_hidden(role);
                assert_eq!(role.renderer.frames(), 0);
                self.config.hide_live2d_model = false;
                role.apply_display_settings(&self.config);
                self.transition(Stage::SettingsRestored);
            }
            Stage::SettingsRestored if presented => {
                assert_eq!(role.window.is_visible(), Some(true));
                self.config.hide_live2d_model = true;
                role.apply_display_settings(&self.config);
                assert_hidden(role);
                self.completed = true;
                event_loop.exit();
                return;
            }
            _ => {}
        }
        self.role.as_mut().unwrap().request_redraw();
        event_loop.set_control_flow(ControlFlow::WaitUntil(
            Instant::now() + Duration::from_millis(10),
        ));
    }
}

fn main() {
    // Some window backends catch callback panics at their FFI boundary. A smoke
    // assertion must fail the process even if the event loop would recover.
    let panic_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |panic| {
        panic_hook(panic);
        std::process::exit(1);
    }));
    let directory = tempfile::tempdir().unwrap();
    let sprite = directory.path().join("probe.webp");
    image::RgbaImage::from_fn(128, 128, |x, y| {
        image::Rgba([40, 180, 220, if x > 16 && y > 16 { 255 } else { 0 }])
    })
    .save(&sprite)
    .unwrap();
    std::fs::write(
        directory.path().join("frames.json"),
        r#"{"spriteSheet":{"totalCols":1,"totalRows":1},"animations":{"idle":{"frames":1,"row":0,"loop":true}}}"#,
    )
    .unwrap();
    let mut entry = ModelEntry {
        character: "window-smoke".into(),
        costume: "generated-sprite".into(),
        pet_mode: PetMode::Pixel,
        ..Default::default()
    };
    entry
        .extras
        .insert("pixel_path".into(), serde_json::json!(sprite));
    let mut probe = Probe {
        paths: Paths::with_root(directory.path()),
        cache: ModelCache::new(
            directory.path().join("cache"),
            directory.path().join("models"),
        ),
        config: Config {
            vsync: false,
            ..Default::default()
        },
        entry,
        role: None,
        stage: Stage::Startup,
        stage_started: Instant::now(),
        baseline: 0,
        completed: false,
    };
    let mut builder = EventLoop::builder();
    #[cfg(target_os = "macos")]
    {
        use winit::platform::macos::{ActivationPolicy, EventLoopBuilderExtMacOS};
        builder.with_activation_policy(ActivationPolicy::Accessory);
    }
    #[cfg(target_os = "linux")]
    {
        use winit::platform::x11::EventLoopBuilderExtX11;
        builder.with_x11();
    }
    builder.build().unwrap().run_app(&mut probe).unwrap();
    assert!(probe.completed);
    println!("Window startup, hide/show and rendering recovery passed");
}
