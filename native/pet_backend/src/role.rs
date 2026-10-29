//! One desktop-pet role: window, renderer, model, behavior, input.

use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use pet_assets::ModelCache;
use pet_behavior::{BehaviorContext, Command, RoleBehavior, RoleBehaviorConfig, WindowMotionKind};
use pet_config::{Config, ModelEntry, Placement};
use pet_input::hit::{AlphaTexture, FrameSnapshot, HitStability};

use pet_live2d::{ModelHandle, ModelInfo};
use pet_render::{ModelGpu, RenderError, SceneRenderer};
use pet_window::placement;
use pet_window::sizing::{content_size, ModelLayout};
#[cfg(windows)]
use pet_window::win32;
use tracing::{error, info, warn};
use winit::dpi::{PhysicalPosition, PhysicalSize};
use winit::event::{ElementState, MouseButton};
use winit::event_loop::ActiveEventLoop;
#[cfg(windows)]
use winit::platform::windows::{WindowAttributesExtWindows, WindowExtWindows};
use winit::window::{Window, WindowLevel};

/// Result alias for role construction.
pub type RoleResult<T> = Result<T, RoleError>;

/// Errors raised while building a role window.
#[derive(Debug, thiserror::Error)]
pub enum RoleError {
    /// Model extraction failed.
    #[error("model cache error: {0}")]
    Cache(#[from] pet_assets::CacheError),
    /// Neocari could not load the model.
    #[error("model load error: {0}")]
    Model(#[from] pet_live2d::Live2dError),
    /// Window creation failed.
    #[error("window error: {0}")]
    Window(String),
    /// Rendering could not start.
    #[error("render error: {0}")]
    Render(#[from] RenderError),
    /// The model had no drawable geometry.
    #[error("model has no drawable bounds")]
    NoBounds,
}

struct DragState {
    /// Global (screen) cursor position when the drag started.
    press_cursor_global: (f32, f32),
    /// Window position when the drag started.
    press_window: (i32, i32),
    #[cfg(target_os = "macos")]
    press_scale: f64,
    moved: bool,
    total: (f32, f32),
}

/// One role window and everything it owns.
pub struct Role {
    /// The winit window.
    pub window: Arc<Window>,
    /// Swapchain + renderer for this window.
    pub renderer: SceneRenderer,
    /// Loaded model (moc or moc3).
    pub model: ModelHandle,
    /// GPU copies of meshes, textures and clipping.
    pub model_gpu: ModelGpu,
    /// Behavior state machine.
    pub behavior: RoleBehavior,
    /// Model-space content bounds.
    pub bounds: pet_window::sizing::Bounds,
    /// Stable model scale and padded animation viewport.
    pub layout: ModelLayout,
    /// Model → clip matrix.
    pub matrix: neocari::core::Matrix44,
    /// Persisted placement record.
    pub placement: Placement,
    /// Config entry this role was created from.
    pub entry: ModelEntry,
    /// Lossless original-resolution alpha channels for hit testing.
    pub textures: Arc<Vec<AlphaTexture>>,
    /// Window position before any emotion displacement.
    pub base_position: (i32, i32),
    /// Last cursor event position in local physical pixels, used for clicks.
    cursor: Option<(f32, f32)>,
    /// Active drag gesture.
    dragging: Option<DragState>,
    /// Hit stability compensation state.
    stability: HitStability,
    /// Whether click-through is currently enabled.
    pub click_through: bool,
    /// Last passthrough poll timestamp.
    last_passthrough_poll: Instant,
    /// Last time the model was advanced.
    last_update: Instant,
    /// Window hidden by the user (tray / radial menu).
    pub hidden: bool,
    /// Global display setting, independent of hiding a role via the tray/menu.
    hide_live2d_model: bool,
    /// Whether the first frame has been presented.
    first_frame_done: bool,
    /// Cached model info for the settings UI.
    info: ModelInfo,
    /// Timestamp of the last topmost re-assert.
    last_topmost: Instant,
    /// Model selection bookkeeping for `MODEL_DATA` messages.
    pub character: String,
    pub costume: String,
}

impl Role {
    /// Keep rendering and inverse hit testing on the same audio transform.
    pub fn set_music_scale(&mut self, scale: f32) {
        let scale = if self.dragging.is_some() || self.behavior.window_motion_active() {
            1.0
        } else {
            scale
        };
        let scale = if scale.is_finite() {
            scale.clamp(0.65, 1.20)
        } else {
            1.0
        };
        let base = self.layout.matrix(self.model.flips_y());
        let mut stretch = neocari::core::Matrix44::identity();
        stretch.scale(1.0, scale);
        stretch.translate(0.0, scale - 1.0);
        self.matrix = neocari::core::Matrix44::multiply_matrices(&stretch, &base);
        self.model_gpu
            .set_matrix(self.renderer.gpu(), self.renderer.renderer(), self.matrix);
    }
    /// Builds a role window for `entry`.
    ///
    /// `gpu` is reused when a second role is added so the process keeps a single
    /// device and queue.
    pub fn create(
        event_loop: &ActiveEventLoop,
        entry: &ModelEntry,
        config: &Config,
        paths: &pet_config::Paths,
        cache: &ModelCache,
        gpu: Option<Arc<pet_render::Gpu>>,
    ) -> RoleResult<Self> {
        let started = Instant::now();
        let mut model = if entry.pet_mode == pet_config::PetMode::Pixel {
            let path = entry
                .extras
                .get("pixel_path")
                .and_then(serde_json::Value::as_str)
                .map(std::path::PathBuf::from)
                .unwrap_or_else(|| {
                    paths
                        .root()
                        .join("pixels")
                        .join(format!("{}.webp", entry.character))
                });
            ModelHandle::load(&path)?
        } else {
            let resolved = cache.resolve(&entry.path)?;
            ModelHandle::load(&resolved.model_path)?
        };
        let info = model.info().clone();

        let bounds = content_size(model.meshes()).ok_or(RoleError::NoBounds)?;
        let layout = layout_for_model(&model, bounds, config, entry);
        let dpr = event_loop
            .primary_monitor()
            .or_else(|| event_loop.available_monitors().next())
            .map(|monitor| monitor.scale_factor())
            .unwrap_or(1.0);
        let monitors = placement::monitors_for_scale(dpr);
        let scale = config.effective_scale_percent(dpr);
        let (width, height) = layout.window_size(scale, dpr);
        let primary = monitors.iter().find(|monitor| monitor.is_primary).cloned();
        let mut stored = entry.window_placement.clone();
        #[cfg(target_os = "macos")]
        {
            stored = placement::placement_at_scale(&stored, dpr);
        }
        stored.width = width;
        stored.height = height;
        let decision =
            placement::resolve_position(&stored, (width, height), &monitors, primary.as_ref());
        stored.x = decision.x;
        stored.y = decision.y;
        if let Some(monitor) = decision.monitor.as_ref() {
            let recorded =
                placement::record_placement((decision.x, decision.y, width, height), dpr, monitor);
            stored.relative_x = recorded.relative_x;
            stored.relative_y = recorded.relative_y;
            stored.right_offset = recorded.right_offset;
            stored.bottom_offset = recorded.bottom_offset;
            stored.screen_name = recorded.screen_name;
            stored.screen_serial = recorded.screen_serial;
            stored.screen_manufacturer = recorded.screen_manufacturer;
            stored.screen_model = recorded.screen_model;
            stored.screen_geometry = recorded.screen_geometry;
            stored.screen_available_geometry = recorded.screen_available_geometry;
            stored.device_pixel_ratio = recorded.device_pixel_ratio;
        }
        info!(
            character = %entry.character,
            costume = %entry.costume,
            ?decision.decision,
            x = decision.x,
            y = decision.y,
            width,
            height,
            "creating role window"
        );

        let attributes = Window::default_attributes()
            .with_title(format!("{}-{}", entry.character, entry.costume))
            .with_transparent(true)
            .with_decorations(false)
            .with_resizable(false)
            .with_window_level(WindowLevel::AlwaysOnTop)
            .with_active(false)
            .with_visible(false)
            .with_inner_size(PhysicalSize::new(width, height))
            .with_position(PhysicalPosition::new(decision.x, decision.y));
        #[cfg(windows)]
        let attributes = attributes.with_skip_taskbar(true);
        #[cfg(target_os = "linux")]
        let attributes = {
            use winit::platform::x11::{WindowAttributesExtX11, WindowType};
            attributes
                .with_name("bandori-pet", "BANDORI-PET-LITE")
                .with_x11_window_type(vec![WindowType::Utility])
        };
        #[cfg(target_os = "macos")]
        let attributes = {
            use winit::platform::macos::WindowAttributesExtMacOS;
            attributes
                .with_has_shadow(false)
                .with_accepts_first_mouse(true)
                .with_position(winit::dpi::LogicalPosition::new(
                    decision.x as f64 / dpr,
                    decision.y as f64 / dpr,
                ))
                .with_inner_size(winit::dpi::LogicalSize::new(
                    width as f64 / dpr,
                    height as f64 / dpr,
                ))
        };
        let window = Arc::new(
            event_loop
                .create_window(attributes)
                .map_err(|error| RoleError::Window(error.to_string()))?,
        );

        #[cfg(target_os = "macos")]
        pet_window::macos::apply_overlay_style(&window);
        #[cfg(target_os = "linux")]
        pet_window::x11::apply_overlay_style(&window);

        #[cfg(windows)]
        {
            if let Some(hwnd) = win32::hwnd_of(&window) {
                win32::apply_pet_style(hwnd, config.obs_window_capture_compatible)
                    .map_err(|error| RoleError::Window(error.to_string()))?;
                win32::set_window_rect(hwnd, decision.x, decision.y, width, height);
            }
        }

        let quality = config.live2d_quality.resolution_scale();
        let renderer = match gpu {
            Some(gpu) => SceneRenderer::with_gpu(
                gpu,
                Arc::clone(&window),
                config.vsync,
                quality,
                config.opacity,
            )?,
            None => SceneRenderer::new(
                Arc::clone(&window),
                config.vsync,
                quality,
                config.opacity,
                config.gpu_acceleration,
            )?,
        };

        let matrix = layout.matrix(model.flips_y());
        if let Ok(output) = std::env::var("BANDORI_PET_SNAPSHOT") {
            let rgba = pet_render::render_preview(
                model.meshes(),
                model.textures(),
                matrix,
                width,
                height,
            )?;
            image::save_buffer(output, &rgba, width, height, image::ColorType::Rgba8)
                .map_err(|error| RoleError::Window(format!("snapshot failed: {error}")))?;
        }
        let model_gpu = renderer.upload_model(model.meshes(), model.textures(), matrix)?;
        let textures = Self::take_hit_textures(&mut model);

        let mut behavior = RoleBehavior::new(pet_util::Rng::from_entropy().next_u64());
        let mut behavior_config = RoleBehaviorConfig::from(config);
        if let Some(actions) = config.model_action_settings.get(&entry.action_key()) {
            behavior_config.click_actions = actions.clone();
        }
        behavior.set_config(behavior_config);

        model.set_auto_blink(true);
        model.set_auto_breath(true);

        info!(
            ms = started.elapsed().as_millis(),
            format = ?info.format,
            motions = info.motion_groups.len(),
            expressions = info.expression_names.len(),
            "role ready"
        );

        let mut role = Self {
            window,
            renderer,
            model,
            model_gpu,
            behavior,
            bounds,
            layout,
            matrix,
            placement: stored,
            entry: entry.clone(),
            textures,
            base_position: (decision.x, decision.y),
            cursor: None,
            dragging: None,
            stability: HitStability::default(),
            click_through: false,
            last_passthrough_poll: Instant::now(),
            last_update: Instant::now(),
            hidden: false,
            hide_live2d_model: config.hide_live2d_model,
            first_frame_done: false,
            info,
            last_topmost: Instant::now(),
            character: entry.character.clone(),
            costume: entry.costume.clone(),
        };
        role.set_hit_alpha_threshold(config.live2d_hit_alpha_threshold);
        role.apply_display_settings(config);
        #[cfg(target_os = "macos")]
        role.record_placement();
        // The configured default motion/expression used to be dropped on the floor
        // here, so the pet stood in the neutral pose until the first ambient action.
        for command in role.behavior.start(0.0) {
            role.apply_command(&command);
        }
        // Start safe even if the cursor is already in a transparent corner.
        let click_through = role.should_be_click_through(config, 0);
        role.set_click_through(click_through);

        // Present the first frame *before* showing the window: a hidden winit
        // window receives no WM_PAINT, so waiting for `RedrawRequested` would
        // deadlock the very first frame (spec: first frame before everything else).
        let presented = role.render();
        #[cfg(windows)]
        if let Some(hwnd) = win32::hwnd_of(&role.window) {
            win32::reassert_topmost(hwnd);
        }
        if !presented {
            warn!("first frame was not presented; the window may need a redraw");
            role.window.request_redraw();
        }
        Ok(role)
    }

    fn set_hit_alpha_threshold(&mut self, _threshold: u8) {
        // The threshold is passed to `hit_test` at call time; kept as a method so
        // the config wiring is obvious.
    }

    /// Model capabilities for the settings window.
    pub fn info(&self) -> &ModelInfo {
        &self.info
    }

    /// Current motion group names.
    pub fn motion_names(&self) -> &[String] {
        &self.info.motion_groups
    }

    /// Current expression names.
    pub fn expression_names(&self) -> &[String] {
        &self.info.expression_names
    }

    /// Replaces the behavior config after a settings change.
    pub fn set_behavior_config(&mut self, config: &Config) {
        let mut behavior_config = RoleBehaviorConfig::from(config);
        if let Some(actions) = config.model_action_settings.get(&self.entry.action_key()) {
            behavior_config.click_actions = actions.clone();
        }
        self.behavior.set_config(behavior_config);
    }

    /// Applies instant-level settings (fps handled by the loop, opacity/quality here).
    pub fn apply_display_settings(&mut self, config: &Config) {
        self.renderer.set_opacity(config.opacity);
        let quality = config.live2d_quality.resolution_scale();
        if (self.renderer.quality() - quality).abs() > f32::EPSILON {
            self.renderer.set_quality(quality);
        }
        if self.renderer.vsync() != config.vsync {
            self.renderer.set_vsync(config.vsync);
        }
        self.hide_live2d_model = config.hide_live2d_model;
        self.sync_visibility();
    }

    /// Rebuilds the window for a scale change (RebuildWindow apply level).
    pub fn apply_scale(&mut self, config: &Config, dpr: f64) -> RoleResult<()> {
        let scale = config.effective_scale_percent(dpr);
        self.layout = layout_for_model(&self.model, self.bounds, config, &self.entry);
        let (width, height) = self.layout.window_size(scale, dpr);
        let (x, y, current_width, current_height) = self.window_rect().unwrap_or((
            self.base_position.0,
            self.base_position.1,
            width,
            height,
        ));
        if current_width == width && current_height == height {
            return Ok(());
        }
        // Keep the bottom-right corner anchored so the pet does not jump off-screen.
        let new_x = x + (current_width as i32 - width as i32);
        let new_y = y + (current_height as i32 - height as i32);
        let _ = self
            .window
            .request_inner_size(PhysicalSize::new(width, height));
        self.base_position = (new_x, new_y);
        self.set_position(new_x, new_y);
        let matrix = self.layout.matrix(self.model.flips_y());
        self.matrix = matrix;
        self.model_gpu
            .set_matrix(self.renderer.gpu(), self.renderer.renderer(), matrix);
        self.renderer.resize(PhysicalSize::new(width, height), dpr);
        self.record_placement();
        Ok(())
    }

    /// Window rect `(x, y, width, height)` in physical pixels.
    pub fn window_rect(&self) -> Option<(i32, i32, u32, u32)> {
        #[cfg(windows)]
        if let Some(hwnd) = win32::hwnd_of(&self.window) {
            return win32::window_rect(hwnd);
        }
        #[cfg(not(windows))]
        {
            let position = self.window.outer_position().ok()?;
            let size = self.window.inner_size();
            Some((position.x, position.y, size.width, size.height))
        }
        #[cfg(windows)]
        None
    }

    /// Moves the window without activating it.
    pub fn set_position(&mut self, x: i32, y: i32) {
        #[cfg(windows)]
        if let Some(hwnd) = win32::hwnd_of(&self.window) {
            let (_, _, width, height) = self.window_rect().unwrap_or((
                x,
                y,
                self.window.inner_size().width,
                self.window.inner_size().height,
            ));
            win32::set_window_rect(hwnd, x, y, width, height);
            return;
        }
        self.window.set_outer_position(PhysicalPosition::new(x, y));
    }

    /// Records the current window rect into the placement record.
    pub fn record_placement(&mut self) {
        let Some((x, y, width, height)) = self.window_rect() else {
            return;
        };
        let monitors = placement::monitors_for_scale(self.window.scale_factor());
        let monitor =
            placement::monitor_at(&monitors, (x + width as i32 / 2, y + height as i32 / 2));
        let Some(monitor) = monitor else {
            return;
        };
        let recorded = placement::record_placement(
            (x, y, width, height),
            self.window.scale_factor(),
            &monitor,
        );
        self.placement = recorded;
        self.entry.window_placement = self.placement.clone();
        self.entry.sync_placement_mirror();
        self.base_position = (x, y);
    }

    /// Places a new/reset role in a free part of the current monitor.
    pub fn place_apart(&mut self, occupied: &[(i32, i32, u32, u32)]) {
        let Some((x, y, width, height)) = self.window_rect() else {
            return;
        };
        let monitors = placement::monitors_for_scale(self.window.scale_factor());
        if let Some(monitor) =
            placement::monitor_at(&monitors, (x + width as i32 / 2, y + height as i32 / 2))
        {
            let (x, y) =
                placement::unoccupied_position((x, y), (width, height), monitor.work, occupied);
            self.set_position(x, y);
            self.base_position = (x, y);
        }
    }

    /// Advances the model by `dt` and uploads the resulting meshes.
    pub fn advance_model(&mut self, dt: f32) {
        if !self.model.update(dt) {
            warn!("model update failed");
            return;
        }
        if let Err(error) = self.model_gpu.update_meshes(
            self.renderer.gpu(),
            self.renderer.renderer(),
            self.model.meshes(),
        ) {
            warn!(%error, "mesh upload failed");
        }
    }

    /// Renders one frame.
    pub fn render(&mut self) -> bool {
        if self.hidden || self.renderer.is_fused() {
            return false;
        }
        match self.renderer.render(&self.model_gpu) {
            Ok(()) => {
                if !self.first_frame_done {
                    self.first_frame_done = true;
                    self.sync_visibility();
                }
                true
            }
            Err(error) => {
                error!(%error, "render failed");
                false
            }
        }
    }

    /// Cursor position in local physical pixels.
    pub fn cursor_local(&self) -> Option<(f32, f32)> {
        self.cursor
    }

    /// Current cursor position in screen physical pixels.
    pub fn cursor_global(&self) -> Option<(f32, f32)> {
        global_cursor(&self.window).or_else(|| {
            let cursor = self.cursor_local()?;
            let origin = self.window.inner_position().ok()?;
            Some((origin.x as f32 + cursor.0, origin.y as f32 + cursor.1))
        })
    }

    /// Preserve the click's native coordinate space across the Qt IPC boundary.
    pub fn context_menu_position(&self) -> Option<serde_json::Value> {
        let (x, y) = self.cursor_global()?;
        #[cfg(target_os = "macos")]
        {
            // AppKit and Qt share desktop points; our cursor helper multiplies
            // all desktop coordinates by this window's backing scale.
            let scale = self.window.scale_factor();
            Some(serde_json::json!({"x": x as f64 / scale, "y": y as f64 / scale}))
        }
        #[cfg(not(target_os = "macos"))]
        {
            let monitors = placement::monitors_for_scale(self.window.scale_factor());
            let mut position =
                serde_json::json!({"x":x, "y":y, "coordinate_space":"native_physical"});
            if let Some(monitor) = placement::monitor_at(&monitors, (x as i32, y as i32)) {
                position["screen_name"] = serde_json::json!(monitor.name);
                position["screen_geometry"] = serde_json::json!(monitor.geometry);
            }
            Some(position)
        }
    }

    /// Remembers that the user interacted (resets idle timers).
    pub fn note_interaction(&mut self, now: f64) {
        self.behavior.note_interaction(now);
    }

    /// Handles a click on `region`, returning the emitted commands.
    pub fn on_click(
        &mut self,
        region: pet_config::ClickRegion,
        context: &BehaviorContext<'_>,
    ) -> Vec<Command> {
        self.behavior.on_click(region, context.now, context)
    }

    /// Applies a command produced outside `tick` (click feedback).
    pub fn apply_external_command(&mut self, command: &Command) {
        self.apply_command(command);
    }

    /// Passthrough duty cycle: 16 ms while the cursor is near, 125 ms when idle.
    pub fn poll_passthrough(&mut self, config: &Config, now_ms: u64) {
        // A click-through window receives no CursorMoved/Entered events. Use the
        // global cursor so it can become interactive again without a 125ms lag.
        let near = global_cursor(&self.window)
            .zip(self.window_rect())
            .is_some_and(|((cx, cy), (x, y, width, height))| {
                cx >= x as f32 - 96.0
                    && cy >= y as f32 - 96.0
                    && cx < x as f32 + width as f32 + 96.0
                    && cy < y as f32 + height as f32 + 96.0
            });
        let interval = if near { 16 } else { 125 };
        if self.last_passthrough_poll.elapsed().as_millis() < interval as u128 {
            return;
        }
        self.last_passthrough_poll = Instant::now();
        let should = self.should_be_click_through(config, now_ms);
        self.set_click_through(should);
    }

    /// Updates the cached cursor position; `None` when the cursor left the window.
    pub fn set_cursor(&mut self, position: Option<(f32, f32)>) {
        self.cursor = position;
    }

    /// Builds a hit-test snapshot of the current frame.
    pub fn snapshot(&self) -> FrameSnapshot {
        FrameSnapshot::new(self.model.meshes(), Arc::clone(&self.textures), self.matrix)
    }

    /// Tests a local physical-pixel cursor position against the model.
    pub fn hit_test(&mut self, cursor: (f32, f32), alpha_threshold: u8, now_ms: u64) -> bool {
        let snapshot = self.snapshot();
        let size = self.window.inner_size();
        let result = snapshot.hit_test(cursor, (size.width, size.height), alpha_threshold);
        self.stability.confirm(result.hit, cursor, now_ms)
    }

    /// Region for a local cursor position.
    ///
    /// The 7-region split uses content bounds, excluding transparent padding.
    pub fn region_at(&mut self, cursor: (f32, f32)) -> pet_config::ClickRegion {
        let size = self.window.inner_size();
        let snapshot = self.snapshot();
        let Some(point) = snapshot.cursor_to_model(cursor, (size.width, size.height)) else {
            return pet_config::ClickRegion::UpperBodyCenter;
        };
        let area = self
            .model
            .hit_test_area(point.0, point.1)
            .unwrap_or_default();
        let x_ratio = ((point.0 - self.bounds.min_x) / self.bounds.width()).clamp(0.0, 1.0);
        let model_y_ratio = (point.1 - self.bounds.min_y) / self.bounds.height();
        let y_ratio = if self.model.flips_y() {
            model_y_ratio
        } else {
            1.0 - model_y_ratio
        }
        .clamp(0.0, 1.0);
        let region = pet_input::classify_region(x_ratio, y_ratio, &area);
        tracing::debug!(
            region = region.key(),
            x_ratio = format_args!("{x_ratio:.2}"),
            y_ratio = format_args!("{y_ratio:.2}"),
            area = area.as_str(),
            "click region"
        );
        region
    }

    /// Handles a left-button press.
    pub fn on_left_press(&mut self, cursor: (f32, f32), config: &Config, now_ms: u64) -> bool {
        let hit = self.hit_test(cursor, config.live2d_hit_alpha_threshold, now_ms);
        if !hit || config.drag_locked {
            return hit;
        }
        let Some((x, y, ..)) = self.window_rect() else {
            return hit;
        };
        // Drag math uses the *global* cursor: moving the window changes the local
        // cursor by the same amount, which would otherwise create a feedback loop
        // that makes the window lag behind the pointer.
        let press_cursor_global = global_cursor(&self.window).unwrap_or_else(|| {
            let (wx, wy) = self.base_position;
            (wx as f32 + cursor.0, wy as f32 + cursor.1)
        });
        self.dragging = Some(DragState {
            press_cursor_global,
            press_window: (x, y),
            #[cfg(target_os = "macos")]
            press_scale: self.window.scale_factor(),
            moved: false,
            total: (0.0, 0.0),
        });
        true
    }

    /// Handles cursor movement while dragging; returns whether the window moved.
    pub fn on_cursor_moved_drag(&mut self, cursor: (f32, f32)) -> bool {
        let Some(global) = global_cursor(&self.window) else {
            return false;
        };
        let Some(drag) = self.dragging.as_mut() else {
            return false;
        };
        // A window's physical desktop coordinates change units as it crosses
        // between Retina and non-Retina screens. Keep drag deltas in the units
        // captured at the press, then convert the destination to current units.
        #[cfg(target_os = "macos")]
        let ratio = self.window.scale_factor() / drag.press_scale;
        #[cfg(target_os = "macos")]
        let global = (
            (global.0 as f64 / ratio) as f32,
            (global.1 as f64 / ratio) as f32,
        );
        let dx = global.0 - drag.press_cursor_global.0;
        let dy = global.1 - drag.press_cursor_global.1;
        drag.total = (dx, dy);
        if dx * dx + dy * dy >= 16.0 {
            drag.moved = true;
        }
        if !drag.moved {
            let _ = cursor;
            return false;
        }
        let new_x = drag.press_window.0 + dx.round() as i32;
        let new_y = drag.press_window.1 + dy.round() as i32;
        #[cfg(target_os = "macos")]
        let (new_x, new_y) = (
            (new_x as f64 * ratio).round() as i32,
            (new_y as f64 * ratio).round() as i32,
        );
        self.set_position(new_x, new_y);
        true
    }

    /// Finishes a drag; returns `(moved, total_delta)`.
    pub fn on_left_release(&mut self) -> (bool, (f32, f32)) {
        match self.dragging.take() {
            Some(drag) => {
                if drag.moved {
                    self.record_placement();
                }
                (drag.moved, drag.total)
            }
            None => (false, (0.0, 0.0)),
        }
    }

    /// Runs one behavior tick and applies its commands.
    pub fn tick_behavior(
        &mut self,
        now: f64,
        dt: f32,
        idle_seconds: f64,
        peer_center: Option<(f32, f32)>,
        own_center: (f32, f32),
    ) -> Vec<Command> {
        let size = self.window.inner_size();
        let hour = pet_util::time_of_day::local_hour();
        let motion_names = self.info.motion_groups.clone();
        let expression_names = self.info.expression_names.clone();
        // Window events stop outside the window and while it is click-through.
        // Sample the screen cursor every tick, keeping out-of-bounds local
        // coordinates so head tracking still sees targets beyond the window.
        let cursor_local = global_cursor(&self.window)
            .zip(self.window_rect())
            .map(|((cx, cy), (x, y, ..))| (cx - x as f32, cy - y as f32))
            .or(self.cursor);
        let context = BehaviorContext {
            now,
            dt,
            cursor_local,
            surface: (size.width, size.height),
            idle_seconds,
            hour,
            peer_center,
            own_center,
            motion_names: &motion_names,
            expression_names: &expression_names,
            character: &self.character,
            motion_finished: self.model.is_motion_finished(),
        };
        let commands = self.behavior.tick(&context, self.base_position);
        for command in &commands {
            self.apply_command(command);
        }
        commands
    }

    fn apply_command(&mut self, command: &Command) {
        match command {
            Command::PlayMotion(group) => {
                tracing::debug!(motion = %group, "play motion");
                if group.is_empty() {
                    if let Some(default) = self.info.default_motion_group() {
                        let default = default.to_owned();
                        self.model.play_motion(&default);
                    }
                } else if !self.model.play_motion(group) {
                    warn!(group, "motion not available on this model");
                }
            }
            Command::PlayExpression(name) => {
                tracing::debug!(expression = %name, "play expression");
                if name.is_empty() {
                    // Bandori models name their expressions after the emotion
                    // (`smile01`, …) and ship no expression called `default`, so a
                    // revert has to fade the active one out instead of looking up
                    // a name that does not exist.
                    self.model.clear_expression();
                } else if !self.model.play_expression(name) {
                    warn!(name, "expression not available on this model");
                }
            }
            Command::PlayRandomMotion => {
                let mut rng = pet_util::Rng::from_entropy();
                let names: Vec<String> = self
                    .info
                    .motion_groups
                    .iter()
                    .filter(|name| {
                        let lower = name.to_ascii_lowercase();
                        !lower.starts_with("idle") && !lower.starts_with("sys-")
                    })
                    .cloned()
                    .collect();
                if let Some(name) = rng.pick(&names).cloned() {
                    self.model.play_motion(&name);
                }
            }
            Command::SetDrag(x, y) => self.model.set_drag(*x, *y),
            Command::MoveWindow(x, y) => {
                if !self.dragging.as_ref().is_some_and(|drag| drag.moved) {
                    self.set_position(*x, *y);
                }
            }
        }
    }

    /// Should the window be click-through right now?
    pub fn should_be_click_through(&mut self, config: &Config, now_ms: u64) -> bool {
        if self.dragging.is_some() {
            return false;
        }
        if self.hide_live2d_model || self.hidden || config.opacity <= 0.0 {
            return true;
        }
        let Some(global) = global_cursor(&self.window) else {
            return false;
        };
        let Some((x, y, width, height)) = self.window_rect() else {
            return false;
        };
        let outside = global.0 < x as f32
            || global.1 < y as f32
            || global.0 >= x as f32 + width as f32
            || global.1 >= y as f32 + height as f32;
        if outside {
            self.stability.reset();
            return true;
        }
        let local = (global.0 - x as f32, global.1 - y as f32);
        let snapshot = self.snapshot();
        let size = self.window.inner_size();
        let raw_hit = snapshot
            .hit_test(
                local,
                (size.width, size.height),
                config.live2d_hit_alpha_threshold,
            )
            .hit;
        let hit = self.stability.confirm_with(raw_hit, local, now_ms, 80);
        !hit
    }

    /// Sets click-through if the state changed.
    pub fn set_click_through(&mut self, enabled: bool) {
        if self.click_through == enabled {
            return;
        }
        // Keep winit's cached IGNORE_CURSOR_EVENT flag in sync with EXSTYLE.
        // Raw SetWindowLongPtrW changes disappear on its next flag update.
        match self.window.set_cursor_hittest(!enabled) {
            Ok(()) => self.click_through = enabled,
            Err(error) => warn!(%error, "could not change cursor hit testing"),
        }
    }

    /// Re-asserts topmost z-order (game compatibility guard).
    pub fn guard_topmost(&mut self, enabled: bool) {
        if !enabled {
            return;
        }
        if self.last_topmost.elapsed().as_millis() < 1000 {
            return;
        }
        self.last_topmost = Instant::now();
        #[cfg(not(windows))]
        self.window.set_window_level(WindowLevel::AlwaysOnTop);
        #[cfg(windows)]
        if let Some(hwnd) = win32::hwnd_of(&self.window) {
            win32::reassert_topmost(hwnd);
        }
    }

    /// Window center in screen coordinates.
    pub fn center(&self) -> (f32, f32) {
        match self.window_rect() {
            Some((x, y, width, height)) => (
                x as f32 + width as f32 * 0.5,
                y as f32 + height as f32 * 0.5,
            ),
            None => (0.0, 0.0),
        }
    }

    /// Hides or shows the role window.
    pub fn set_hidden(&mut self, hidden: bool) {
        self.hidden = hidden;
        self.sync_visibility();
    }

    fn sync_visibility(&self) {
        #[cfg(target_os = "macos")]
        pet_window::macos::set_visible(
            &self.window,
            self.first_frame_done && !self.hidden && !self.hide_live2d_model,
        );
        #[cfg(not(target_os = "macos"))]
        self.window
            .set_visible(self.first_frame_done && !self.hidden && !self.hide_live2d_model);
        // Also applies in OBS mode, where APPWINDOW is retained for capture.
        #[cfg(windows)]
        self.window.set_skip_taskbar(true);
    }

    /// Plays a random motion from the radial menu.
    pub fn play_menu_motion(&mut self, now: f64) {
        let mut rng = pet_util::Rng::from_entropy();
        let names: Vec<String> = self
            .info
            .motion_groups
            .iter()
            .filter(|name| {
                let lower = name.to_ascii_lowercase();
                !lower.starts_with("idle") && !lower.starts_with("sys-")
            })
            .cloned()
            .collect();
        if let Some(name) = rng.pick(&names).cloned() {
            if self.model.play_motion(&name) {
                // Same bookkeeping as a click, so the pet settles back into its
                // resting motion once the clip is over instead of holding a pose.
                self.behavior.note_triggered_motion(now);
            }
        }
    }

    /// Triggers an emotion displacement.
    pub fn trigger_window_motion(&mut self, kind: WindowMotionKind, intensity: u8, now: f64) {
        self.behavior.trigger_window_motion(kind, intensity, now);
    }

    /// Model path of this role for the About page.
    pub fn model_path(&self) -> &Path {
        Path::new(&self.entry.path)
    }

    /// Current FPS estimate helper: last update timestamp.
    pub fn mark_updated(&mut self) {
        self.last_update = Instant::now();
    }

    /// Milliseconds since the last model advance.
    pub fn since_update_ms(&self) -> u128 {
        self.last_update.elapsed().as_millis()
    }

    /// Model entry snapshot with the latest placement.
    pub fn entry(&self) -> ModelEntry {
        let mut entry = self.entry.clone();
        entry.window_placement = self.placement.clone();
        entry.sync_placement_mirror();
        entry
    }

    /// Applies a new model to this role without recreating the window.
    pub fn swap_model(
        &mut self,
        entry: &ModelEntry,
        cache: &ModelCache,
        config: &Config,
    ) -> RoleResult<()> {
        let mut model = if entry.pet_mode == pet_config::PetMode::Pixel {
            let path = entry
                .extras
                .get("pixel_path")
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| RoleError::Window("pixel path missing".into()))?;
            ModelHandle::load(Path::new(path))?
        } else {
            let resolved = cache.resolve(&entry.path)?;
            ModelHandle::load(&resolved.model_path)?
        };
        let info = model.info().clone();
        let bounds = content_size(model.meshes()).ok_or(RoleError::NoBounds)?;
        let layout = layout_for_model(&model, bounds, config, entry);
        let dpr = self.window.scale_factor();
        let scale = config.effective_scale_percent(dpr);
        let (width, height) = layout.window_size(scale, dpr);
        let matrix = layout.matrix(model.flips_y());
        let model_gpu = self
            .renderer
            .upload_model(model.meshes(), model.textures(), matrix)?;
        let textures = Self::take_hit_textures(&mut model);

        self.model = model;
        self.model_gpu = model_gpu;
        self.textures = textures;
        self.bounds = bounds;
        self.layout = layout;
        self.matrix = matrix;
        self.info = info;
        self.entry = entry.clone();
        self.character = entry.character.clone();
        self.costume = entry.costume.clone();
        self.stability.reset();

        let (x, y, old_width, old_height) = self.window_rect().unwrap_or((
            self.base_position.0,
            self.base_position.1,
            width,
            height,
        ));
        let _ = self
            .window
            .request_inner_size(PhysicalSize::new(width, height));
        self.set_position(
            x + old_width as i32 - width as i32,
            y + old_height as i32 - height as i32,
        );
        self.model.set_auto_blink(true);
        self.model.set_auto_breath(true);
        self.behavior.set_config(RoleBehaviorConfig::from(config));
        for command in self.behavior.start(0.0) {
            self.apply_command(&command);
        }
        self.window
            .set_title(&format!("{}-{}", self.character, self.costume));
        self.renderer.resize(PhysicalSize::new(width, height), dpr);
        self.record_placement();
        info!(character = %entry.character, costume = %entry.costume, "model hot-swapped");
        Ok(())
    }

    fn take_hit_textures(model: &mut ModelHandle) -> Arc<Vec<AlphaTexture>> {
        // Consume one texture at a time: release its RGBA allocation as soon as
        // its alpha has been extracted. The GPU owns the unchanged full pixels.
        let mut rgba_bytes = 0;
        let textures: Vec<_> = model
            .take_textures()
            .into_iter()
            .map(|texture| {
                rgba_bytes += texture.rgba().len();
                AlphaTexture::from(texture)
            })
            .collect();
        let alpha_bytes: usize = textures.iter().map(AlphaTexture::byte_len).sum();
        info!(
            alpha_bytes,
            released_rgba_bytes = rgba_bytes,
            "CPU textures reduced to lossless alpha"
        );
        Arc::new(textures)
    }

    /// Applies the OBS capture style without recreating the window.
    pub fn apply_obs_capture(&self, enabled: bool) {
        #[cfg(not(windows))]
        let _ = enabled;
        #[cfg(windows)]
        if let Some(hwnd) = win32::hwnd_of(&self.window) {
            if let Err(error) = win32::apply_pet_style(hwnd, enabled) {
                warn!(%error, "could not apply pet window styles");
            }
            self.window.set_skip_taskbar(true);
        }
    }

    /// Current drawable count for diagnostics.
    pub fn drawable_count(&self) -> usize {
        self.model_gpu.drawable_count()
    }

    /// Radius used by the head-tracking / approach checks.
    pub fn size(&self) -> (u32, u32) {
        let size = self.window.inner_size();
        (size.width, size.height)
    }
}

fn global_cursor(window: &Window) -> Option<(f32, f32)> {
    #[cfg(not(target_os = "macos"))]
    let _ = window;
    #[cfg(windows)]
    {
        win32::cursor_position()
    }
    #[cfg(target_os = "macos")]
    {
        pet_window::macos::cursor_position(window)
    }
    #[cfg(target_os = "linux")]
    {
        pet_window::x11::cursor_position()
    }
    #[cfg(not(any(windows, target_os = "macos", target_os = "linux")))]
    {
        None
    }
}

/// Applies a mouse-button state, returning whether the press was on the model.
pub fn is_left(state: ElementState, button: MouseButton) -> bool {
    state == ElementState::Pressed && button == MouseButton::Left
}

fn layout_for_model(
    model: &ModelHandle,
    bounds: pet_window::sizing::Bounds,
    config: &Config,
    entry: &ModelEntry,
) -> ModelLayout {
    if entry.pet_mode == pet_config::PetMode::Pixel {
        return ModelLayout::pixel(bounds);
    }
    let layout = ModelLayout::new(bounds, model.face_height(), model.format());
    if model.format() == pet_config::ModelFormat::Moc3
        && config
            .extras
            .get("moc3_leg_crop_enabled")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false)
    {
        layout.crop_bottom(
            config
                .extras
                .get("moc3_visible_height")
                .and_then(serde_json::Value::as_f64)
                .unwrap_or(800.0) as f32
                / 800.0,
        )
    } else {
        layout
    }
}
