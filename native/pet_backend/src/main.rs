#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]
#![allow(dead_code)] // Shared LITE components also expose preview/diagnostic APIs.

mod config;
mod ipc;
mod role;

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use pet_assets::ModelCache;
use pet_behavior::{BehaviorContext, WindowMotionKind};
use pet_config::{Config, ModelEntry, Paths};
use serde_json::{json, Value};
use winit::application::ApplicationHandler;
use winit::event::{ElementState, MouseButton, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::window::WindowId;

struct Args {
    character: String,
    costume: String,
    path: String,
    config: PathBuf,
    root: PathBuf,
    queues: Vec<String>,
    parent: u32,
    headless: bool,
    exit_after: Option<f64>,
    assets_root: PathBuf,
    index: usize,
    restart: Option<(String, Vec<String>)>,
}

impl Args {
    fn parse() -> Result<Self, String> {
        let mut values = HashMap::new();
        let mut args = std::env::args().skip(1);
        while let Some(key) = args.next() {
            if key == "--headless" {
                values.insert(key, "true".into());
            } else {
                values.insert(
                    key.clone(),
                    args.next()
                        .ok_or_else(|| format!("missing value for {key}"))?,
                );
            }
        }
        let mut required =
            |name: &str| values.remove(name).ok_or_else(|| format!("missing {name}"));
        let character = required("--character")?;
        let costume = required("--costume")?;
        let path = required("--model-path")?;
        let config = PathBuf::from(required("--config")?);
        let root = PathBuf::from(required("--root")?);
        let queues = [
            "--inbound",
            "--reliable-inbound",
            "--broadcast",
            "--control",
        ]
        .iter()
        .map(|k| required(k))
        .collect::<Result<Vec<_>, _>>()?;
        Ok(Self {
            character,
            costume,
            path,
            config,
            root,
            queues,
            parent: values
                .get("--parent-pid")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0),
            headless: values.contains_key("--headless"),
            exit_after: values.get("--exit-after").and_then(|s| s.parse().ok()),
            assets_root: values
                .get("--assets-root")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(".")),
            index: values
                .get("--index")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0),
            restart: values
                .get("--restart-command")
                .and_then(|s| serde_json::from_str(s).ok()),
        })
    }
}

struct App {
    args: Args,
    raw_config: Value,
    config: Config,
    entry: ModelEntry,
    bus: ipc::Bus,
    role: Option<role::Role>,
    started: Instant,
    last_frame: Instant,
    last_heartbeat: Instant,
    last_position: Instant,
    last_interaction: Instant,
    expression_until: Option<Instant>,
    mouth: (f32, f32),
    mouth_at: Instant,
    peers: HashMap<String, (f32, f32)>,
    peer_drags: HashMap<String, (String, i32, i32)>,
    drag_start: Option<(String, i32, i32)>,
    pressed: bool,
    last_click: Instant,
    fatal: Option<String>,
    shutdown: bool,
}

impl App {
    fn new(args: Args) -> Result<Self, Box<dyn std::error::Error>> {
        let mut raw_config: Value = serde_json::from_slice(&std::fs::read(&args.config)?)?;
        if !raw_config.is_object() {
            return Err("config root must be an object".into());
        }
        raw_config["_native_assets_root"] = json!(args.assets_root);
        let (config, entry) =
            config::translate(&raw_config, &args.character, &args.costume, &args.path);
        let mut bus = ipc::Bus::attach(&args.queues)?;
        bus.send(&format!("REGISTER\tPET\t{}", args.character), true)?;
        Ok(Self {
            args,
            raw_config,
            config,
            entry,
            bus,
            role: None,
            started: Instant::now(),
            last_frame: Instant::now(),
            last_heartbeat: Instant::now(),
            last_position: Instant::now(),
            last_interaction: Instant::now(),
            expression_until: None,
            mouth: (0.0, 0.0),
            mouth_at: Instant::now(),
            peers: HashMap::new(),
            peer_drags: HashMap::new(),
            drag_start: None,
            pressed: false,
            last_click: Instant::now() - Duration::from_secs(1),
            fatal: None,
            shutdown: false,
        })
    }

    fn emit(&mut self, event: &str, data: Value) {
        let line = format!(
            "NATIVE_EVENT\t{}",
            json!({"character": self.args.character, "costume": self.args.costume, "event": event, "data": data})
        );
        if let Err(error) = self.bus.send(&line, true) {
            eprintln!("native IPC: {error}");
        }
    }

    fn position(&mut self, save: bool) {
        let Some(role) = self.role.as_mut() else {
            return;
        };
        if save {
            role.record_placement();
        }
        if let Some((x, y, w, h)) = role.window_rect() {
            let payload = json!({"character": self.args.character, "x": x, "y": y, "w": w, "h": h});
            let _ = self.bus.send(&format!("PEER_POS\t{payload}"), false);
            if save {
                let placement = serde_json::to_value(&role.placement).unwrap();
                self.emit("placement", placement);
            }
        }
    }

    fn action(&mut self, tag: &str) {
        let Some(role) = self.role.as_mut() else {
            return;
        };
        let normalized = tag
            .trim_matches(['[', ']', ' ', '\r', '\n'])
            .rsplit(['/', '\\'])
            .next()
            .unwrap_or(tag);
        let normalized = normalized
            .rsplit_once('.')
            .map_or(normalized, |(name, _)| name);
        let mut rng = pet_util::Rng::from_entropy();
        let motion = pet_input::resolve_motion_by_tag(
            normalized,
            role.motion_names(),
            &role.character,
            &mut rng,
        );
        let expression = pet_input::resolve_expression_by_tag(
            normalized,
            role.expression_names(),
            &role.character,
        );
        if !motion.is_empty() && role.model.play_motion(&motion) {
            role.behavior
                .note_triggered_motion(self.started.elapsed().as_secs_f64());
        }
        if !expression.is_empty() {
            role.model.play_expression(&expression);
            self.expression_until = Some(Instant::now() + Duration::from_secs(3));
        }
        self.last_interaction = Instant::now();
    }

    fn handle(&mut self, line: &str) {
        let parts: Vec<&str> = line.split('\t').collect();
        let command = parts[0];
        let payload: Value = parts
            .get(1)
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or(Value::Null);
        match command {
            "SHUTDOWN" => self.shutdown = true,
            "SETTINGS" if payload.is_object() => {
                self.raw_config
                    .as_object_mut()
                    .unwrap()
                    .extend(payload.as_object().unwrap().clone());
                let (config, entry) = config::translate(
                    &self.raw_config,
                    &self.args.character,
                    &self.args.costume,
                    &self.args.path,
                );
                if let Some(role) = self.role.as_mut() {
                    let defaults_changed = role.entry.default_motion != entry.default_motion
                        || role.entry.default_expression != entry.default_expression;
                    if role.entry.pet_mode != entry.pet_mode {
                        let cache = ModelCache::new(
                            self.args.root.join(".cache/neocari"),
                            self.args.root.join("models"),
                        );
                        if let Err(error) = role.swap_model(&entry, &cache, &config) {
                            eprintln!("model switch failed: {error}");
                        }
                    }
                    role.entry.default_motion = entry.default_motion.clone();
                    role.entry.default_expression = entry.default_expression.clone();
                    role.set_behavior_config(&config);
                    if defaults_changed {
                        for command in role.behavior.start(self.started.elapsed().as_secs_f64()) {
                            role.apply_external_command(&command);
                        }
                        if entry.default_expression.is_empty() {
                            role.model.clear_expression();
                        }
                    }
                    role.apply_display_settings(&config);
                    role.apply_obs_capture(config.obs_window_capture_compatible);
                    let _ = role.apply_scale(&config, role.window.scale_factor());
                }
                self.config = config;
            }
            "ACTION" if parts.len() >= 2 => {
                if parts.len() == 2 {
                    self.action(parts[1]);
                } else if parts[1] == self.args.character {
                    self.action(parts[2]);
                }
            }
            "LIP" if parts.len() >= 3 && parts[1] == self.args.character => {
                let number = |s: Option<&&str>| {
                    s.and_then(|s| s.parse::<f32>().ok())
                        .filter(|v| v.is_finite())
                        .unwrap_or(0.0)
                };
                self.mouth = (
                    number(parts.get(2)).clamp(0.0, 1.0),
                    number(parts.get(3)).clamp(-1.0, 1.0),
                );
                self.mouth_at = Instant::now();
            }
            "PREVIEW_MOTION" if parts.len() >= 4 && parts[1] == self.args.character => {
                if let Some(role) = self.role.as_mut() {
                    if !parts[2].is_empty() {
                        role.model.play_motion(parts[2]);
                        role.behavior
                            .note_triggered_motion(self.started.elapsed().as_secs_f64());
                    }
                    if !parts[3].is_empty() {
                        role.model.play_expression(parts[3]);
                        self.expression_until = Some(Instant::now() + Duration::from_secs(3));
                    }
                }
            }
            "AI_EVENT" | "CHAT_EVENT" | "REMINDER_EVENT" | "EMOTION" | "POKE_USER"
                if payload.is_object() =>
            {
                let target = payload
                    .get("character")
                    .or_else(|| payload.get("target_character"))
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if !target.is_empty() && target != self.args.character {
                    return;
                }
                if command == "AI_EVENT" && self.raw_config["ai_event_overlay_enabled"] == false {
                    return;
                }
                let action = payload["action"].as_str().unwrap_or_else(|| {
                    match payload["state"].as_str().unwrap_or("") {
                        "thinking" | "tool" => "thinking",
                        "error" => "surprised",
                        "done" => "smile",
                        _ => "",
                    }
                });
                if !action.is_empty() {
                    self.action(action);
                }
                if command == "EMOTION" && self.config.emotion_behavior_enabled {
                    if let Some(role) = self.role.as_mut() {
                        let mut rng = pet_util::Rng::from_entropy();
                        if let Some(tags) = payload["expression_tags"].as_array() {
                            for tag in tags.iter().filter_map(Value::as_str) {
                                let expression = pet_input::resolve_expression_by_tag(
                                    tag,
                                    role.expression_names(),
                                    &role.character,
                                );
                                if !expression.is_empty() && role.model.play_expression(&expression)
                                {
                                    self.expression_until = Some(
                                        Instant::now()
                                            + Duration::from_millis(
                                                2600 + payload["intensity"]
                                                    .as_u64()
                                                    .unwrap_or(60)
                                                    .clamp(20, 100)
                                                    * 38,
                                            ),
                                    );
                                    break;
                                }
                            }
                        }
                        if let Some(tags) = payload["motion_tags"].as_array() {
                            for tag in tags.iter().filter_map(Value::as_str) {
                                let motion = pet_input::resolve_motion_by_tag(
                                    tag,
                                    role.motion_names(),
                                    &role.character,
                                    &mut rng,
                                );
                                if !motion.is_empty() && role.model.play_motion(&motion) {
                                    role.behavior.note_triggered_motion(
                                        self.started.elapsed().as_secs_f64(),
                                    );
                                    break;
                                }
                            }
                        }
                    }
                    let kind = match payload["window"]
                        .as_str()
                        .or_else(|| payload["kind"].as_str())
                        .unwrap_or("")
                    {
                        "forward" => WindowMotionKind::Forward,
                        "back" => WindowMotionKind::Back,
                        "hop" => WindowMotionKind::Hop,
                        "wobble" => WindowMotionKind::Wobble,
                        "settle" => WindowMotionKind::Settle,
                        _ => WindowMotionKind::Shake,
                    };
                    if let Some(role) = self.role.as_mut() {
                        role.trigger_window_motion(
                            kind,
                            payload["intensity"].as_u64().unwrap_or(60).clamp(20, 100) as u8,
                            self.started.elapsed().as_secs_f64(),
                        );
                    }
                }
            }
            "PEER_POS" => {
                if let Some(character) = payload["character"]
                    .as_str()
                    .filter(|c| *c != self.args.character)
                {
                    if let (Some(x), Some(y)) = (payload["x"].as_f64(), payload["y"].as_f64()) {
                        let w = payload["w"].as_f64().unwrap_or(0.0);
                        let h = payload["h"].as_f64().unwrap_or(0.0);
                        self.peers.insert(
                            character.into(),
                            ((x + w * 0.5) as f32, (y + h * 0.5) as f32),
                        );
                    }
                }
            }
            "PEER_OFFLINE" => {
                if let Some(c) = payload["character"].as_str() {
                    self.peers.remove(c);
                    self.peer_drags.remove(c);
                }
            }
            "PEER_DRAG" | "PEER_DRAG_END" if self.config.move_all_roles_together => {
                self.peer_drag(&payload, command == "PEER_DRAG_END")
            }
            "NATIVE_CONTROL" if payload["character"] == self.args.character => {
                match payload["command"].as_str().unwrap_or("") {
                    "motion" => { if let Some(role) = self.role.as_mut() { role.play_menu_motion(self.started.elapsed().as_secs_f64()); } }
                    "action" => { if let Some(action) = payload["action"].as_str() { self.action(action); } }
                    "expression" => { if let Some(role) = self.role.as_mut() { role.model.play_expression(payload["expression"].as_str().unwrap_or("")); } }
                    "position" => { if let Some(role) = self.role.as_mut() { role.set_position(payload["x"].as_i64().unwrap_or(0) as i32, payload["y"].as_i64().unwrap_or(0) as i32); } self.position(true); }
                    "visibility" => { if let Some(role) = self.role.as_mut() { role.set_hidden(!payload["visible"].as_bool().unwrap_or(true)); } }
                    "reset" => { if let Some(role) = self.role.as_mut() { role.place_apart(&[]); } self.position(true); }
                    "shutdown" => self.shutdown = true,
                    "status" => self.emit("status", json!({"backend":"neocari", "fps":self.config.fps, "opacity":self.config.opacity, "mouth":self.mouth, "models":self.config.models})),
                    "snapshot" => {
                        if let (Some(role), Some(path)) = (self.role.as_ref(), payload["path"].as_str()) {
                            let (width, height) = role.size();
                            let factor = (1024.0 / width.max(height) as f32).min(1.0);
                            let (width, height) = ((width as f32 * factor).max(1.0) as u32, (height as f32 * factor).max(1.0) as u32);
                            match role.renderer.capture_rgba(&role.model_gpu, width, height)
                                .map_err(|e| e.to_string()).and_then(|rgba| image::save_buffer(path, &rgba, width, height, image::ColorType::Rgba8).map_err(|e| e.to_string())) {
                                Ok(()) => self.emit("snapshot", json!({"path":path})),
                                Err(error) => eprintln!("frame capture failed: {error}"),
                            }
                        }
                    }
                    "music_scale" => { if let Some(role) = self.role.as_mut() { role.set_music_scale(payload["scale"].as_f64().unwrap_or(1.0) as f32); } }
                    _ => {}
                }
            }
            _ => {}
        }
    }

    fn peer_drag(&mut self, data: &Value, finished: bool) {
        let Some(character) = data["character"]
            .as_str()
            .filter(|c| *c != self.args.character)
        else {
            return;
        };
        let id = data["drag_id"].as_str().unwrap_or("");
        if id.is_empty() {
            return;
        }
        let dx = data["total_dx"].as_i64().unwrap_or(0) as i32;
        let dy = data["total_dy"].as_i64().unwrap_or(0) as i32;
        let state = self
            .peer_drags
            .entry(character.into())
            .or_insert_with(|| (id.into(), 0, 0));
        if state.0 != id {
            *state = (id.into(), 0, 0);
        }
        if let Some(role) = self.role.as_mut() {
            if let Some((x, y, ..)) = role.window_rect() {
                role.set_position(x + dx - state.1, y + dy - state.2);
            }
        }
        state.1 = dx;
        state.2 = dy;
        if finished {
            self.position(true);
        }
    }

    fn click(&mut self) {
        let now = self.started.elapsed().as_secs_f64();
        let Some(role) = self.role.as_mut() else {
            return;
        };
        let Some(cursor) = role.cursor_local() else {
            return;
        };
        if !role.hit_test(
            cursor,
            self.config.live2d_hit_alpha_threshold,
            (now * 1000.0) as u64,
        ) {
            return;
        }
        if self.last_click.elapsed() < Duration::from_millis(350) {
            self.emit("double_click", json!({}));
            self.last_click = Instant::now() - Duration::from_secs(1);
            return;
        }
        self.last_click = Instant::now();
        let region = role.region_at(cursor);
        let motions = role.motion_names().to_vec();
        let expressions = role.expression_names().to_vec();
        let character = role.character.clone();
        let context = BehaviorContext {
            now,
            dt: 0.0,
            cursor_local: Some(cursor),
            surface: role.size(),
            idle_seconds: 0.0,
            hour: pet_util::time_of_day::local_hour(),
            peer_center: None,
            own_center: role.center(),
            motion_names: &motions,
            expression_names: &expressions,
            character: &character,
            motion_finished: role.model.is_motion_finished(),
        };
        for command in role.on_click(region, &context) {
            role.apply_external_command(&command);
        }
        role.note_interaction(now);
        self.last_interaction = Instant::now();
        self.emit(
            "clicked",
            json!({"region":region.key(), "x":cursor.0, "y":cursor.1}),
        );
    }

    fn stop(&mut self, event_loop: &ActiveEventLoop) {
        self.position(true);
        let _ = self
            .bus
            .send(&format!("UNREGISTER\tPET\t{}", self.args.character), true);
        event_loop.exit();
    }
}

impl ApplicationHandler for App {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.args.headless {
            self.emit("ready", json!({"backend":"neocari", "headless":true}));
            return;
        }
        if self.role.is_some() {
            return;
        }
        let cache = ModelCache::new(
            self.args.root.join(".cache/neocari"),
            self.args.root.join("models"),
        );
        match role::Role::create(
            event_loop,
            &self.entry,
            &self.config,
            &Paths::with_root(&self.args.root),
            &cache,
            None,
        ) {
            Ok(mut role) => {
                if self.entry.window_placement.is_unset() && self.args.index > 0 {
                    let offset = self.args.index as i32 * 36;
                    role.set_position(role.base_position.0 - offset, role.base_position.1 - offset);
                    role.record_placement();
                }
                self.role = Some(role);
                let _ = self
                    .bus
                    .send(&format!("REGISTER\tPET\t{}", self.args.character), true);
                self.emit("ready", json!({"backend":"neocari"}));
                self.position(false);
            }
            Err(error) => {
                self.fatal = Some(error.to_string());
                self.emit("error", json!({"message":error.to_string()}));
                self.stop(event_loop);
            }
        }
    }

    fn window_event(
        &mut self,
        event_loop: &ActiveEventLoop,
        window_id: WindowId,
        event: WindowEvent,
    ) {
        let Some(role) = self.role.as_mut().filter(|r| r.window.id() == window_id) else {
            return;
        };
        let now_ms = self.started.elapsed().as_millis() as u64;
        match event {
            WindowEvent::CloseRequested => {
                self.shutdown = true;
                self.stop(event_loop);
            }
            WindowEvent::RedrawRequested => {
                role.render();
            }
            WindowEvent::Resized(size) => role.renderer.resize(size, role.window.scale_factor()),
            WindowEvent::ScaleFactorChanged { scale_factor, .. } => {
                let _ = role.apply_scale(&self.config, scale_factor);
            }
            WindowEvent::CursorLeft { .. } => role.set_cursor(None),
            WindowEvent::CursorMoved { position, .. } => {
                let cursor = (position.x as f32, position.y as f32);
                role.set_cursor(Some(cursor));
                if role.on_cursor_moved_drag(cursor) {
                    if let (Some((id, x, y)), Some((nx, ny, ..))) =
                        (&self.drag_start, role.window_rect())
                    {
                        let payload = json!({"character":self.args.character,"drag_id":id,"total_dx":nx-x,"total_dy":ny-y});
                        let _ = self.bus.send(&format!("PEER_DRAG\t{payload}"), false);
                    }
                }
            }
            WindowEvent::MouseInput {
                state,
                button: MouseButton::Left,
                ..
            } => {
                if state == ElementState::Pressed {
                    if let Some(cursor) = role.cursor_local() {
                        self.pressed = role.on_left_press(cursor, &self.config, now_ms);
                        self.drag_start = role
                            .window_rect()
                            .map(|(x, y, ..)| (format!("{}-{now_ms}", self.bus.id), x, y));
                    }
                } else {
                    let (moved, total) = role.on_left_release();
                    if moved {
                        if let Some((id, ..)) = self.drag_start.take() {
                            let payload = json!({"character":self.args.character,"drag_id":id,"total_dx":total.0.round() as i32,"total_dy":total.1.round() as i32});
                            let _ = self.bus.send(&format!("PEER_DRAG_END\t{payload}"), true);
                        }
                        self.position(true);
                    } else if self.pressed {
                        self.click();
                    }
                    self.pressed = false;
                }
            }
            WindowEvent::MouseInput {
                state: ElementState::Released,
                button: MouseButton::Right,
                ..
            } => {
                if let Some(cursor) = role.cursor_local() {
                    if role.hit_test(cursor, self.config.live2d_hit_alpha_threshold, now_ms) {
                        if let Some(position) = role.context_menu_position() {
                            self.emit("context_menu", position);
                        }
                    }
                }
            }
            _ => {}
        }
    }

    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        match self.bus.read() {
            Ok(lines) => {
                for line in lines {
                    self.handle(&line);
                }
            }
            Err(error) => {
                self.fatal = Some(format!("IPC disconnected: {error}"));
                self.shutdown = true;
            }
        }
        if self.shutdown
            || self
                .args
                .exit_after
                .is_some_and(|s| self.started.elapsed().as_secs_f64() >= s)
        {
            self.stop(event_loop);
            return;
        }
        if self.last_heartbeat.elapsed() >= Duration::from_secs(1) {
            if self.args.parent != 0 && !parent_alive(self.args.parent) {
                if self.args.index == 0 {
                    if let Some((program, arguments)) = &self.args.restart {
                        let mut command = std::process::Command::new(program);
                        command
                            .args(arguments)
                            .env_remove("BANDORI_PET_IPC_SERVER_NAME")
                            .env("BANDORI_PET_RESTARTED_FROM_CHILD", "1")
                            .current_dir(&self.args.assets_root)
                            .stdin(std::process::Stdio::null())
                            .stdout(std::process::Stdio::null())
                            .stderr(std::process::Stdio::null());
                        #[cfg(windows)]
                        {
                            use std::os::windows::process::CommandExt;
                            command.creation_flags(0x08000000);
                        }
                        if let Err(error) = command.spawn() {
                            eprintln!("could not restart main process: {error}");
                        }
                    }
                }
                self.shutdown = true;
                self.stop(event_loop);
                return;
            }
            let _ = self
                .bus
                .send(&format!("REGISTER\tPET\t{}", self.args.character), true);
            self.last_heartbeat = Instant::now();
        }
        let budget = Duration::from_secs_f64(1.0 / self.config.fps as f64);
        if self.last_frame.elapsed() >= budget {
            let dt = self.last_frame.elapsed().as_secs_f32().min(0.1);
            self.last_frame = Instant::now();
            if let Some(role) = self.role.as_mut() {
                if self.expression_until.is_some_and(|at| Instant::now() >= at) {
                    if role.entry.default_expression.is_empty() {
                        role.model.clear_expression();
                    } else {
                        role.model.play_expression(&role.entry.default_expression);
                    }
                    self.expression_until = None;
                }
                let center = role.center();
                let peer = self
                    .peers
                    .values()
                    .min_by(|a, b| {
                        let dist =
                            |p: &&(f32, f32)| (p.0 - center.0).powi(2) + (p.1 - center.1).powi(2);
                        dist(a).total_cmp(&dist(b))
                    })
                    .copied();
                role.tick_behavior(
                    self.started.elapsed().as_secs_f64(),
                    dt,
                    self.last_interaction.elapsed().as_secs_f64(),
                    peer,
                    center,
                );
                let mouth = if self.mouth_at.elapsed() > Duration::from_millis(750) {
                    (0.0, 0.0)
                } else {
                    self.mouth
                };
                role.model.set_lip_sync(mouth.0, mouth.1);
                role.advance_model(dt);
                role.poll_passthrough(&self.config, self.started.elapsed().as_millis() as u64);
                role.guard_topmost(self.config.game_topmost);
                role.window.request_redraw();
                if role.renderer.is_fused() {
                    self.fatal = Some("GPU rendering stopped after repeated draw failures".into());
                    self.shutdown = true;
                }
            }
        }
        if self.last_position.elapsed() >= Duration::from_millis(250) {
            self.position(false);
            self.last_position = Instant::now();
        }
        event_loop.set_control_flow(ControlFlow::WaitUntil(
            (self.last_frame + budget).min(Instant::now() + Duration::from_millis(30)),
        ));
    }
}

fn parent_alive(pid: u32) -> bool {
    #[cfg(windows)]
    unsafe {
        use windows::Win32::Foundation::CloseHandle;
        use windows::Win32::System::Threading::{
            GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
        };
        if let Ok(handle) = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            let mut code = 0;
            let alive = GetExitCodeProcess(handle, &mut code).is_ok() && code == 259;
            let _ = CloseHandle(handle);
            alive
        } else {
            false
        }
    }
    #[cfg(unix)]
    {
        unsafe {
            libc::kill(pid as i32, 0) == 0
                || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
        }
    }
}

fn main() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "warn".into()),
        )
        .with_writer(std::io::stderr)
        .init();
    let result = (|| -> Result<(), Box<dyn std::error::Error>> {
        let command: Vec<String> = std::env::args().collect();
        if command.get(1).is_some_and(|arg| arg == "--render-preview") {
            let path = command.get(2).ok_or("missing preview model")?;
            let option = |flag: &str| {
                command
                    .iter()
                    .position(|arg| arg == flag)
                    .and_then(|index| command.get(index + 1))
            };
            let output = option("--output").ok_or("missing preview output")?;
            let root = PathBuf::from(option("--root").map(String::as_str).unwrap_or("."));
            let cache = ModelCache::new(root.join(".cache/neocari"), root.join("models"));
            let resolved = cache.resolve(path)?;
            let model = pet_live2d::ModelHandle::load(&resolved.model_path)?;
            let bounds = pet_window::content_size(model.meshes()).ok_or("model has no bounds")?;
            let matrix = pet_window::fit_matrix(bounds, 0.95, model.flips_y());
            let width = (720.0 * bounds.aspect()).clamp(1.0, 2048.0) as u32;
            let rgba =
                pet_render::render_preview(model.meshes(), model.textures(), matrix, width, 720)?;
            image::save_buffer(output, &rgba, width, 720, image::ColorType::Rgba8)?;
            return Ok(());
        }
        let args = Args::parse().map_err(std::io::Error::other)?;
        let mut app = App::new(args)?;
        let mut builder = EventLoop::builder();
        #[cfg(target_os = "linux")]
        {
            use winit::platform::x11::EventLoopBuilderExtX11;
            builder.with_x11();
        }
        #[cfg(target_os = "macos")]
        {
            use winit::platform::macos::{ActivationPolicy, EventLoopBuilderExtMacOS};
            builder.with_activation_policy(ActivationPolicy::Accessory);
        }
        builder.build()?.run_app(&mut app)?;
        if let Some(error) = app.fatal {
            return Err(error.into());
        }
        Ok(())
    })();
    if let Err(error) = result {
        eprintln!("Neocari pet backend: {error}");
        std::process::exit(1);
    }
}
