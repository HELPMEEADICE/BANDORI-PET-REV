//! Loopback-only HTTP integration services used by the native Qt frontend.
//!
//! The server intentionally implements a small HTTP/1.1 subset. Requests are
//! bounded before parsing, handled by fixed worker pools, and always close the
//! connection after one response. This keeps local webhooks from turning into
//! an unbounded thread or memory source.

use crate::config::{ConfigDocument, ConfigError};
use crate::database::{Database, ExternalUnreadSummary};
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, mpsc};
use std::thread::{self, JoinHandle};
use std::time::Duration;
use thiserror::Error;
use url::form_urlencoded;

const MAX_HEADER_BYTES: usize = 64 * 1024;
const MAX_BODY_BYTES: usize = 1024 * 1024;
const WORKERS_PER_SERVICE: usize = 4;
const PENDING_CONNECTIONS: usize = 32;
const IO_TIMEOUT: Duration = Duration::from_secs(5);

const CHAT_PATHS: &[&str] = &[
    "/chat-events",
    "/chat-event",
    "/chat-messages",
    "/chat-message",
];

#[derive(Debug, Error)]
pub enum IntegrationError {
    #[error("integration configuration failed: {0}")]
    Config(#[from] ConfigError),
    #[error("integration I/O failed: {0}")]
    Io(#[from] io::Error),
    #[error("integration JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("integration settings root must be a JSON object")]
    SettingsRoot,
    #[error("integration settings exceed {0} bytes")]
    SettingsTooLarge(usize),
    #[error("could not generate a local integration token")]
    TokenGeneration,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NativeIntegrationSettings {
    pub compact_ai_window_enabled: bool,
    pub compact_ai_window_opacity: i64,
    pub compact_ai_window_font_size: i64,
    pub compact_ai_window_background_color: String,
    pub compact_ai_window_text_color: String,
    pub ai_event_overlay_enabled: bool,
    pub ai_status_enabled: bool,
    pub ai_status_port: u16,
    pub ai_status_token_configured: bool,
    pub chat_enabled: bool,
    pub chat_overlay_enabled: bool,
    pub chat_include_context: bool,
    pub chat_port: u16,
    pub chat_token_configured: bool,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NativeIntegrationSettingsInput {
    #[serde(default)]
    compact_ai_window_enabled: Option<bool>,
    #[serde(default)]
    compact_ai_window_opacity: Option<i64>,
    #[serde(default)]
    compact_ai_window_font_size: Option<i64>,
    #[serde(default)]
    compact_ai_window_background_color: Option<String>,
    #[serde(default)]
    compact_ai_window_text_color: Option<String>,
    #[serde(default)]
    ai_event_overlay_enabled: Option<bool>,
    #[serde(default)]
    ai_status_enabled: Option<bool>,
    #[serde(default)]
    ai_status_port: Option<i64>,
    #[serde(default)]
    ai_status_token: Option<String>,
    #[serde(default)]
    clear_ai_status_token: bool,
    #[serde(default)]
    chat_enabled: Option<bool>,
    #[serde(default)]
    chat_overlay_enabled: Option<bool>,
    #[serde(default)]
    chat_include_context: Option<bool>,
    #[serde(default)]
    chat_port: Option<i64>,
    #[serde(default)]
    chat_token: Option<String>,
    #[serde(default)]
    clear_chat_token: bool,
}

#[derive(Clone, Debug)]
struct RuntimeSettings {
    compact_ai_window_enabled: bool,
    compact_ai_window_opacity: i64,
    compact_ai_window_font_size: i64,
    compact_ai_window_background_color: String,
    compact_ai_window_text_color: String,
    ai_event_overlay_enabled: bool,
    ai_status_enabled: bool,
    ai_status_port: u16,
    ai_status_token: String,
    chat_enabled: bool,
    chat_overlay_enabled: bool,
    chat_include_context: bool,
    chat_port: u16,
    chat_token: String,
}

impl RuntimeSettings {
    fn view(&self) -> NativeIntegrationSettings {
        NativeIntegrationSettings {
            compact_ai_window_enabled: self.compact_ai_window_enabled,
            compact_ai_window_opacity: self.compact_ai_window_opacity,
            compact_ai_window_font_size: self.compact_ai_window_font_size,
            compact_ai_window_background_color: self.compact_ai_window_background_color.clone(),
            compact_ai_window_text_color: self.compact_ai_window_text_color.clone(),
            ai_event_overlay_enabled: self.ai_event_overlay_enabled,
            ai_status_enabled: self.ai_status_enabled,
            ai_status_port: self.ai_status_port,
            ai_status_token_configured: !self.ai_status_token.is_empty(),
            chat_enabled: self.chat_enabled,
            chat_overlay_enabled: self.chat_overlay_enabled,
            chat_include_context: self.chat_include_context,
            chat_port: self.chat_port,
            chat_token_configured: !self.chat_token.is_empty(),
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct NativeIntegrationEvent {
    pub kind: String,
    pub payload: Value,
}

#[derive(Clone, Debug, Serialize)]
pub struct NativeIntegrationStatus {
    pub running: bool,
    pub ai_status_running: bool,
    pub ai_status_port: u16,
    pub chat_running: bool,
    pub chat_port: u16,
}

pub fn load_native_integration_settings(
    config_path: &Path,
) -> Result<NativeIntegrationSettings, IntegrationError> {
    Ok(runtime_settings(&ConfigDocument::load(config_path)?).view())
}

pub fn save_native_integration_settings(
    config_path: &Path,
    settings_json: &str,
) -> Result<NativeIntegrationSettings, IntegrationError> {
    if settings_json.len() > 64 * 1024 {
        return Err(IntegrationError::SettingsTooLarge(64 * 1024));
    }
    let input: NativeIntegrationSettingsInput = serde_json::from_str(settings_json)?;
    let mut config = ConfigDocument::load(config_path)?;
    if let Some(value) = input.compact_ai_window_enabled {
        config.set("compact_ai_window_enabled", Value::Bool(value));
    }
    if let Some(value) = input.compact_ai_window_opacity {
        config.set(
            "compact_ai_window_opacity",
            Value::from(value.clamp(10, 100)),
        );
    }
    if let Some(value) = input.compact_ai_window_font_size {
        config.set(
            "compact_ai_window_font_size",
            Value::from(value.clamp(8, 36)),
        );
    }
    if let Some(value) = input.compact_ai_window_background_color {
        config.set(
            "compact_ai_window_background_color",
            Value::String(normalized_overlay_color(&value, "")),
        );
    }
    if let Some(value) = input.compact_ai_window_text_color {
        config.set(
            "compact_ai_window_text_color",
            Value::String(normalized_overlay_color(&value, "#24242a")),
        );
    }
    if let Some(value) = input.ai_event_overlay_enabled {
        config.set("ai_event_overlay_enabled", Value::Bool(value));
    }
    if let Some(value) = input.ai_status_enabled {
        config.set("ai_status_port_enabled", Value::Bool(value));
    }
    if let Some(value) = input.ai_status_port {
        config.set("ai_status_port", Value::from(clamp_port(value)));
    }
    if input.clear_ai_status_token {
        config.set("ai_status_token", Value::String(String::new()));
    } else if let Some(value) = input.ai_status_token {
        let value = value.trim();
        if !value.is_empty() {
            config.set(
                "ai_status_token",
                Value::String(value.chars().take(512).collect()),
            );
        }
    }
    if let Some(value) = input.chat_enabled {
        config.set("chat_integration_enabled", Value::Bool(value));
    }
    if let Some(value) = input.chat_overlay_enabled {
        config.set("chat_integration_overlay_enabled", Value::Bool(value));
    }
    if let Some(value) = input.chat_include_context {
        config.set("chat_integration_include_context", Value::Bool(value));
    }
    if let Some(value) = input.chat_port {
        config.set("chat_integration_port", Value::from(clamp_port(value)));
    }
    if input.clear_chat_token {
        config.set("chat_integration_token", Value::String(String::new()));
    } else if let Some(value) = input.chat_token {
        let value = value.trim();
        if !value.is_empty() {
            config.set(
                "chat_integration_token",
                Value::String(value.chars().take(512).collect()),
            );
        }
    }
    ensure_enabled_tokens(&mut config)?;
    config.save(config_path)?;
    Ok(runtime_settings(&config).view())
}

pub struct NativeIntegrationServer {
    shutdown: Arc<AtomicBool>,
    joins: Vec<JoinHandle<()>>,
    status: NativeIntegrationStatus,
}

impl NativeIntegrationServer {
    pub fn start(
        config_path: &Path,
        database_path: &Path,
        on_event: impl Fn(NativeIntegrationEvent) + Send + Sync + 'static,
    ) -> Result<(Self, NativeIntegrationSettings), IntegrationError> {
        let mut config = ConfigDocument::load(config_path)?;
        if ensure_enabled_tokens(&mut config)? {
            config.save(config_path)?;
        }
        let settings = runtime_settings(&config);
        let view = settings.view();
        let callback: Arc<dyn Fn(NativeIntegrationEvent) + Send + Sync> = Arc::new(on_event);
        let shutdown = Arc::new(AtomicBool::new(false));
        let mut joins = Vec::new();
        let mut status = NativeIntegrationStatus {
            running: false,
            ai_status_running: false,
            ai_status_port: settings.ai_status_port,
            chat_running: false,
            chat_port: settings.chat_port,
        };

        let started = (|| -> Result<(), IntegrationError> {
            if settings.ai_status_enabled {
                let listener = bind_loopback(settings.ai_status_port)?;
                status.ai_status_port = listener.local_addr()?.port();
                joins.extend(spawn_service(
                    "ai-status",
                    listener,
                    shutdown.clone(),
                    Service::Ai {
                        token: settings.ai_status_token.clone(),
                        callback: callback.clone(),
                    },
                )?);
                status.ai_status_running = true;
            }
            if settings.chat_enabled {
                let listener = bind_loopback(settings.chat_port)?;
                status.chat_port = listener.local_addr()?.port();
                joins.extend(spawn_service(
                    "chat-integration",
                    listener,
                    shutdown.clone(),
                    Service::Chat {
                        token: settings.chat_token.clone(),
                        database_path: database_path.to_path_buf(),
                        overlay_enabled: settings.chat_overlay_enabled,
                        callback: callback.clone(),
                    },
                )?);
                status.chat_running = true;
            }
            Ok(())
        })();
        if let Err(error) = started {
            shutdown.store(true, Ordering::Release);
            for join in joins {
                let _ = join.join();
            }
            return Err(error);
        }
        status.running = status.ai_status_running || status.chat_running;
        Ok((
            Self {
                shutdown,
                joins,
                status,
            },
            view,
        ))
    }

    pub fn status(&self) -> &NativeIntegrationStatus {
        &self.status
    }

    pub fn stop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        for join in self.joins.drain(..) {
            let _ = join.join();
        }
        self.status.running = false;
        self.status.ai_status_running = false;
        self.status.chat_running = false;
    }
}

impl Drop for NativeIntegrationServer {
    fn drop(&mut self) {
        self.stop();
    }
}

#[derive(Clone)]
enum Service {
    Ai {
        token: String,
        callback: Arc<dyn Fn(NativeIntegrationEvent) + Send + Sync>,
    },
    Chat {
        token: String,
        database_path: PathBuf,
        overlay_enabled: bool,
        callback: Arc<dyn Fn(NativeIntegrationEvent) + Send + Sync>,
    },
}

fn bind_loopback(port: u16) -> io::Result<TcpListener> {
    let listener = TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port))?;
    listener.set_nonblocking(true)?;
    Ok(listener)
}

fn spawn_service(
    name: &'static str,
    listener: TcpListener,
    shutdown: Arc<AtomicBool>,
    service: Service,
) -> io::Result<Vec<JoinHandle<()>>> {
    let (sender, receiver) = mpsc::sync_channel::<TcpStream>(PENDING_CONNECTIONS);
    let receiver = Arc::new(Mutex::new(receiver));
    let mut joins = Vec::with_capacity(WORKERS_PER_SERVICE + 1);
    for worker in 0..WORKERS_PER_SERVICE {
        let receiver = receiver.clone();
        let worker_shutdown = shutdown.clone();
        let service = service.clone();
        match thread::Builder::new()
            .name(format!("bandori-{name}-worker-{worker}"))
            .spawn(move || worker_loop(receiver, worker_shutdown, service))
        {
            Ok(join) => joins.push(join),
            Err(error) => {
                shutdown.store(true, Ordering::Release);
                drop(sender);
                for join in joins {
                    let _ = join.join();
                }
                return Err(error);
            }
        }
    }
    let accept_shutdown = shutdown.clone();
    match thread::Builder::new()
        .name(format!("bandori-{name}-accept"))
        .spawn(move || {
            while !accept_shutdown.load(Ordering::Acquire) {
                match listener.accept() {
                    Ok((stream, _)) => {
                        if let Err(mpsc::TrySendError::Full(mut stream)) = sender.try_send(stream) {
                            let _ = write_json(
                                &mut stream,
                                503,
                                &json!({"ok": false, "error": "server busy"}),
                            );
                        }
                    }
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(_) => break,
                }
            }
        }) {
        Ok(join) => joins.push(join),
        Err(error) => {
            shutdown.store(true, Ordering::Release);
            for join in joins {
                let _ = join.join();
            }
            return Err(error);
        }
    }
    Ok(joins)
}

fn worker_loop(
    receiver: Arc<Mutex<mpsc::Receiver<TcpStream>>>,
    shutdown: Arc<AtomicBool>,
    service: Service,
) {
    while !shutdown.load(Ordering::Acquire) {
        let received = receiver
            .lock()
            .ok()
            .and_then(|receiver| receiver.recv_timeout(Duration::from_millis(50)).ok());
        if let Some(mut stream) = received {
            let _ = stream.set_read_timeout(Some(IO_TIMEOUT));
            let _ = stream.set_write_timeout(Some(IO_TIMEOUT));
            let response = match read_request(&mut stream) {
                Ok(request) => dispatch(&service, request),
                Err(response) => response,
            };
            let _ = write_json(&mut stream, response.status, &response.payload);
        }
    }
}

#[derive(Debug)]
struct Request {
    method: String,
    path: String,
    query: BTreeMap<String, String>,
    headers: BTreeMap<String, String>,
    body: Vec<u8>,
}

#[derive(Debug)]
struct Response {
    status: u16,
    payload: Value,
}

impl Response {
    fn json(status: u16, payload: Value) -> Self {
        Self { status, payload }
    }

    fn error(status: u16, error: impl Into<String>) -> Self {
        Self::json(status, json!({"ok": false, "error": error.into()}))
    }
}

fn read_request(stream: &mut TcpStream) -> Result<Request, Response> {
    let mut bytes = Vec::with_capacity(4096);
    let header_end = loop {
        if bytes.len() >= MAX_HEADER_BYTES {
            return Err(Response::error(431, "request headers too large"));
        }
        let mut chunk = [0_u8; 4096];
        let count = stream.read(&mut chunk).map_err(|error| {
            if matches!(
                error.kind(),
                io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
            ) {
                Response::error(408, "request timeout")
            } else {
                Response::error(400, "request read failed")
            }
        })?;
        if count == 0 {
            return Err(Response::error(400, "incomplete request"));
        }
        bytes.extend_from_slice(&chunk[..count]);
        if let Some(index) = find_header_end(&bytes) {
            break index;
        }
    };
    let mut headers = [httparse::EMPTY_HEADER; 64];
    let mut parsed = httparse::Request::new(&mut headers);
    parsed
        .parse(&bytes[..header_end])
        .map_err(|_| Response::error(400, "invalid http request"))?;
    let method = parsed
        .method
        .ok_or_else(|| Response::error(400, "missing method"))?
        .to_ascii_uppercase();
    let target = parsed
        .path
        .ok_or_else(|| Response::error(400, "missing path"))?;
    let (path, raw_query) = target.split_once('?').unwrap_or((target, ""));
    let mut owned_headers = BTreeMap::new();
    for header in parsed.headers.iter() {
        let value = std::str::from_utf8(header.value)
            .map_err(|_| Response::error(400, "invalid header encoding"))?;
        owned_headers.insert(header.name.to_ascii_lowercase(), value.trim().to_owned());
    }
    if owned_headers
        .get("transfer-encoding")
        .is_some_and(|value| !value.eq_ignore_ascii_case("identity"))
    {
        return Err(Response::error(400, "transfer encoding is not supported"));
    }
    let content_length = owned_headers
        .get("content-length")
        .map(|value| value.parse::<usize>())
        .transpose()
        .map_err(|_| Response::error(400, "invalid content length"))?
        .unwrap_or(0);
    if content_length > MAX_BODY_BYTES {
        return Err(Response::error(413, "request body too large"));
    }
    let body_start = header_end;
    let mut body = bytes[body_start..].to_vec();
    if body.len() > content_length {
        body.truncate(content_length);
    }
    while body.len() < content_length {
        let remaining = content_length - body.len();
        let mut chunk = vec![0_u8; remaining.min(8192)];
        let count = stream.read(&mut chunk).map_err(|error| {
            if matches!(
                error.kind(),
                io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
            ) {
                Response::error(408, "request body timeout")
            } else {
                Response::error(400, "request body read failed")
            }
        })?;
        if count == 0 {
            return Err(Response::error(400, "incomplete request body"));
        }
        body.extend_from_slice(&chunk[..count]);
    }
    Ok(Request {
        method,
        path: path.to_owned(),
        query: parse_params(raw_query),
        headers: owned_headers,
        body,
    })
}

fn find_header_end(bytes: &[u8]) -> Option<usize> {
    bytes
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|index| index + 4)
}

fn dispatch(service: &Service, request: Request) -> Response {
    if request.method == "OPTIONS" {
        return Response::json(204, Value::Null);
    }
    match service {
        Service::Ai { token, callback } => dispatch_ai(&request, token, callback),
        Service::Chat {
            token,
            database_path,
            overlay_enabled,
            callback,
        } => dispatch_chat(&request, token, database_path, *overlay_enabled, callback),
    }
}

fn dispatch_ai(
    request: &Request,
    token: &str,
    callback: &Arc<dyn Fn(NativeIntegrationEvent) + Send + Sync>,
) -> Response {
    if request.method == "GET" && matches!(request.path.as_str(), "/" | "/health" | "/ai-events") {
        return Response::json(
            200,
            json!({"ok": true, "service": "BandoriPet AI status port"}),
        );
    }
    if request.method != "POST" || !matches!(request.path.as_str(), "/ai-events" | "/ai-event") {
        return Response::error(404, "not found");
    }
    if !authorized(request, token) {
        return Response::error(401, "unauthorized");
    }
    let event: Value = match serde_json::from_slice(&request.body) {
        Ok(Value::Object(event)) => Value::Object(event),
        Ok(_) => return Response::error(400, "json body must be an object"),
        Err(_) => return Response::error(400, "invalid json"),
    };
    callback(NativeIntegrationEvent {
        kind: "ai_event".into(),
        payload: event,
    });
    Response::json(200, json!({"ok": true}))
}

fn dispatch_chat(
    request: &Request,
    token: &str,
    database_path: &Path,
    overlay_enabled: bool,
    callback: &Arc<dyn Fn(NativeIntegrationEvent) + Send + Sync>,
) -> Response {
    if request.method == "GET" && matches!(request.path.as_str(), "/" | "/health") {
        return chat_service_info();
    }
    if CHAT_PATHS.contains(&request.path.as_str()) {
        if request.method == "GET" && !looks_like_chat_event(&request.query) {
            return chat_service_info();
        }
        if request.method != "GET" && request.method != "POST" {
            return Response::error(404, "not found");
        }
        if !authorized(request, token) {
            return Response::error(401, "unauthorized");
        }
        let data = if request.method == "GET" {
            Value::Object(params_object(&request.query, true))
        } else {
            match request_payload(request) {
                Ok(value) => value,
                Err(response) => return response,
            }
        };
        return handle_chat_events(data, database_path, overlay_enabled, callback);
    }
    if request.path == "/chat-read" && matches!(request.method.as_str(), "GET" | "POST") {
        if !authorized(request, token) {
            return Response::error(401, "unauthorized");
        }
        let data = if request.method == "GET" {
            Value::Object(params_object(&request.query, true))
        } else {
            match request_payload(request) {
                Ok(value) => value,
                Err(response) => return response,
            }
        };
        let Value::Object(data) = data else {
            return Response::error(400, "json body must be an object");
        };
        let platform = value_text(data.get("platform"));
        let thread_id = value_text(
            data.get("thread_id")
                .or_else(|| data.get("conversation_id")),
        );
        let database = match Database::open(database_path) {
            Ok(database) => database,
            Err(error) => return Response::error(500, error.to_string()),
        };
        match database.mark_external_chat_read(&platform, &thread_id) {
            Ok(result) => {
                callback(NativeIntegrationEvent {
                    kind: "chat_overlay".into(),
                    payload: json!({
                        "source": "chat",
                        "state": "clear",
                        "mode": "replace_raw",
                        "text": "",
                        "ttl_ms": 1
                    }),
                });
                Response::json(200, json!({"ok": true, "result": result}))
            }
            Err(error) => Response::error(500, error.to_string()),
        }
    } else {
        Response::error(404, "not found")
    }
}

fn chat_service_info() -> Response {
    Response::json(
        200,
        json!({
            "ok": true,
            "service": "BandoriPet chat integration port",
            "endpoints": ["/chat-events", "/chat-read"],
            "formats": [
                "application/json",
                "application/x-www-form-urlencoded",
                "text/plain",
                "query"
            ]
        }),
    )
}

fn handle_chat_events(
    data: Value,
    database_path: &Path,
    overlay_enabled: bool,
    callback: &Arc<dyn Fn(NativeIntegrationEvent) + Send + Sync>,
) -> Response {
    let events = match data {
        Value::Array(events) => events,
        event => vec![event],
    };
    if let Some((index, _)) = events
        .iter()
        .enumerate()
        .find(|(_, event)| !event.is_object())
    {
        return Response::error(400, format!("event at index {index} must be an object"));
    }
    let database = match Database::open(database_path) {
        Ok(database) => database,
        Err(error) => return Response::error(500, error.to_string()),
    };
    let mut results = Vec::with_capacity(events.len());
    for (index, event) in events.into_iter().enumerate() {
        let Some(event) = normalize_onebot_event(&event) else {
            results.push(json!({"ignored": true}));
            continue;
        };
        match database.add_external_chat_message(&event) {
            Ok(stored) => {
                let mut value = serde_json::to_value(&stored)
                    .expect("external chat result serialization cannot fail");
                if !stored.duplicate && overlay_enabled {
                    if let Some(payload) = chat_overlay(&event, &stored.unread) {
                        callback(NativeIntegrationEvent {
                            kind: "chat_overlay".into(),
                            payload,
                        });
                        value
                            .as_object_mut()
                            .expect("serialized result is an object")
                            .insert("overlay_delivered".into(), Value::Bool(true));
                    }
                }
                results.push(value);
            }
            Err(error) => {
                let status = if matches!(
                    error,
                    crate::database::DatabaseError::InvalidExternalEvent(_)
                ) {
                    400
                } else {
                    500
                };
                return Response::json(
                    status,
                    json!({
                        "ok": false,
                        "error": error.to_string(),
                        "failed_index": index,
                        "processed_count": results.len()
                    }),
                );
            }
        }
    }
    let count = results.len();
    if count == 1 {
        Response::json(
            200,
            json!({"ok": true, "count": count, "result": results.remove(0)}),
        )
    } else {
        Response::json(200, json!({"ok": true, "count": count, "results": results}))
    }
}

fn request_payload(request: &Request) -> Result<Value, Response> {
    if request.body.is_empty() {
        return Ok(Value::Object(Map::new()));
    }
    let content_type = request
        .headers
        .get("content-type")
        .and_then(|value| value.split(';').next())
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    match content_type.as_str() {
        "application/x-www-form-urlencoded" => {
            let text = std::str::from_utf8(&request.body)
                .map_err(|_| Response::error(400, "invalid form data"))?;
            Ok(Value::Object(params_object(&parse_params(text), false)))
        }
        "text/plain" => {
            let text = std::str::from_utf8(&request.body)
                .map_err(|_| Response::error(400, "invalid text data"))?;
            Ok(json!({"text": text}))
        }
        _ => {
            serde_json::from_slice(&request.body).map_err(|_| Response::error(400, "invalid json"))
        }
    }
}

fn authorized(request: &Request, expected: &str) -> bool {
    if expected.is_empty() {
        return true;
    }
    let bearer = format!("Bearer {expected}");
    request
        .headers
        .get("authorization")
        .is_some_and(|actual| constant_time_eq(bearer.as_bytes(), actual.as_bytes()))
        || request
            .headers
            .get("x-bandori-token")
            .is_some_and(|actual| constant_time_eq(expected.as_bytes(), actual.as_bytes()))
        || request
            .query
            .get("token")
            .is_some_and(|actual| constant_time_eq(expected.as_bytes(), actual.as_bytes()))
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    let mut difference = left.len() ^ right.len();
    for index in 0..left.len().max(right.len()) {
        difference |= usize::from(
            left.get(index).copied().unwrap_or(0) ^ right.get(index).copied().unwrap_or(0),
        );
    }
    difference == 0
}

fn parse_params(value: &str) -> BTreeMap<String, String> {
    let mut result = BTreeMap::new();
    for (key, value) in form_urlencoded::parse(value.as_bytes()) {
        if !key.is_empty() {
            result.insert(key.into_owned(), value.into_owned());
        }
    }
    result
}

fn params_object(params: &BTreeMap<String, String>, omit_token: bool) -> Map<String, Value> {
    params
        .iter()
        .filter(|(key, _)| !omit_token || key.as_str() != "token")
        .map(|(key, value)| (key.clone(), Value::String(value.clone())))
        .collect()
}

fn looks_like_chat_event(params: &BTreeMap<String, String>) -> bool {
    ["text", "content", "message", "body"]
        .iter()
        .any(|key| params.contains_key(*key))
}

pub(crate) fn normalize_onebot_event(event: &Value) -> Option<Value> {
    let source = event.as_object()?;
    let post_type = value_text(source.get("post_type")).to_ascii_lowercase();
    if post_type.is_empty() {
        return Some(event.clone());
    }
    if post_type != "message" {
        return None;
    }
    let text = onebot_message_text(source);
    if text.is_empty() {
        return None;
    }
    let message_type = value_text(source.get("message_type")).to_ascii_lowercase();
    let sender = source.get("sender").and_then(Value::as_object);
    let sender_id = first_non_empty(&[
        value_text(source.get("user_id")),
        sender.map_or_else(String::new, |sender| value_text(sender.get("user_id"))),
    ]);
    let sender_name = first_non_empty(&[
        sender.map_or_else(String::new, |sender| value_text(sender.get("card"))),
        sender.map_or_else(String::new, |sender| value_text(sender.get("nickname"))),
        sender_id.clone(),
        "unknown".into(),
    ]);
    let group_id = value_text(source.get("group_id"));
    let (thread_id, thread_name, chat_type) = if message_type == "group" && !group_id.is_empty() {
        (
            group_id.clone(),
            first_non_empty(&[
                value_text(source.get("group_name")),
                group_id,
                "QQ 群聊".into(),
            ]),
            "group",
        )
    } else {
        (
            first_non_empty(&[
                sender_id.clone(),
                value_text(source.get("target_id")),
                "private".into(),
            ]),
            first_non_empty(&[sender_name.clone(), "QQ 私聊".into()]),
            "private",
        )
    };
    Some(json!({
        "platform": "qq",
        "thread_id": thread_id,
        "thread_name": thread_name,
        "chat_type": chat_type,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "text": text,
        "message_id": first_non_empty(&[
            value_text(source.get("message_id")),
            value_text(source.get("message_seq"))
        ]),
        "raw_event": event
    }))
}

fn onebot_message_text(event: &Map<String, Value>) -> String {
    if let Some(segments) = event.get("message").and_then(Value::as_array) {
        let text = segments
            .iter()
            .map(onebot_segment_text)
            .collect::<String>()
            .trim()
            .to_owned();
        if !text.is_empty() {
            return text;
        }
    }
    if let Some(message) = event.get("message").and_then(Value::as_str)
        && !message.trim().is_empty()
    {
        return clean_cq_codes(message);
    }
    let raw = value_text(event.get("raw_message"));
    if !raw.is_empty() {
        return clean_cq_codes(&raw);
    }
    first_non_empty(&[
        value_text(event.get("content")),
        value_text(event.get("text")),
    ])
}

fn onebot_segment_text(segment: &Value) -> String {
    let Some(segment) = segment.as_object() else {
        return segment.as_str().unwrap_or_default().to_owned();
    };
    let kind = value_text(segment.get("type")).to_ascii_lowercase();
    let data = segment.get("data").and_then(Value::as_object);
    if kind == "text" {
        return data
            .and_then(|data| data.get("text"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
    }
    if kind == "at" {
        let qq = data.map_or_else(String::new, |data| value_text(data.get("qq")));
        let name = data.map_or_else(String::new, |data| value_text(data.get("name")));
        return if !name.is_empty() {
            format!("@{name} ")
        } else if qq == "all" {
            "@全体成员 ".into()
        } else if !qq.is_empty() {
            format!("@{qq} ")
        } else {
            "@ ".into()
        };
    }
    segment_placeholder(&kind)
}

fn clean_cq_codes(text: &str) -> String {
    let mut output = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(start) = rest.find("[CQ:") {
        output.push_str(&rest[..start]);
        let after = &rest[start + 4..];
        let Some(end) = after.find(']') else {
            output.push_str(&rest[start..]);
            return output.trim().to_owned();
        };
        let kind = after[..end]
            .split(',')
            .next()
            .unwrap_or_default()
            .to_ascii_lowercase();
        if kind == "at" {
            output.push_str("@ ");
        } else {
            output.push_str(&segment_placeholder(&kind));
        }
        rest = &after[end + 1..];
    }
    output.push_str(rest);
    output.trim().to_owned()
}

fn segment_placeholder(kind: &str) -> String {
    match kind {
        "image" => "[图片]",
        "record" => "[语音]",
        "video" => "[视频]",
        "file" => "[文件]",
        "face" | "mface" | "emoji" => "[表情]",
        "reply" => "[引用]",
        "forward" => "[合并转发]",
        "json" | "xml" | "markdown" => "[卡片]",
        "music" => "[音乐]",
        "dice" => "[骰子]",
        "rps" => "[猜拳]",
        "poke" => "[戳一戳]",
        "share" => "[链接]",
        "location" => "[位置]",
        "contact" => "[名片]",
        "" => "",
        other => return format!("[{other}]"),
    }
    .into()
}

pub(crate) fn chat_overlay(event: &Value, summary: &ExternalUnreadSummary) -> Option<Value> {
    if summary.total_unread <= 0 {
        return None;
    }
    let mut lines = Vec::new();
    for thread in summary.threads.iter().take(5) {
        let label = if thread.thread_name.is_empty() {
            &thread.thread_id
        } else {
            &thread.thread_name
        };
        lines.push(format!(
            "[{}] {}（{}）",
            if thread.platform.is_empty() {
                "chat"
            } else {
                &thread.platform
            },
            if label.is_empty() { "default" } else { label },
            thread.unread_count
        ));
        for message in thread
            .messages
            .iter()
            .rev()
            .take(3)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
        {
            let sender = if !message.sender_name.is_empty() {
                &message.sender_name
            } else if !message.sender_id.is_empty() {
                &message.sender_id
            } else {
                "unknown"
            };
            let clean = message.content.replace(['\r', '\n'], " ");
            let mut content: String = clean.trim().chars().take(80).collect();
            if clean.trim().chars().count() > 80 {
                content.push_str("...");
            }
            lines.push(format!("{sender}: {content}"));
        }
    }
    let source = event.as_object();
    let platform = source.map_or_else(
        || "chat".into(),
        |event| {
            first_non_empty(&[
                value_text(event.get("platform")),
                value_text(event.get("source")),
                "chat".into(),
            ])
        },
    );
    let action = source.map_or_else(
        || "surprised".into(),
        |event| first_non_empty(&[value_text(event.get("action")), "surprised".into()]),
    );
    let ttl_ms = source
        .and_then(|event| event.get("ttl_ms"))
        .and_then(Value::as_i64)
        .unwrap_or(9000);
    let mut overlay = json!({
        "source": platform,
        "state": "stream",
        "mode": "replace",
        "title": format!("{} 条未读消息", summary.total_unread),
        "text": lines.join("\n"),
        "action": action,
        "ttl_ms": ttl_ms,
        "anchor_to_pet": true
    });
    if let Some(character) = source.map(|event| {
        first_non_empty(&[
            value_text(event.get("character")),
            value_text(event.get("target_character")),
        ])
    }) && !character.is_empty()
    {
        overlay
            .as_object_mut()
            .expect("overlay is an object")
            .insert("character".into(), Value::String(character));
    }
    Some(overlay)
}

fn write_json(stream: &mut TcpStream, status: u16, payload: &Value) -> io::Result<()> {
    let body = if status == 204 {
        Vec::new()
    } else {
        serde_json::to_vec(payload).unwrap_or_else(|_| b"{\"ok\":false}".to_vec())
    };
    let reason = match status {
        200 => "OK",
        204 => "No Content",
        400 => "Bad Request",
        401 => "Unauthorized",
        404 => "Not Found",
        408 => "Request Timeout",
        413 => "Payload Too Large",
        431 => "Request Header Fields Too Large",
        500 => "Internal Server Error",
        503 => "Service Unavailable",
        _ => "Error",
    };
    let header = format!(
        "HTTP/1.1 {status} {reason}\r\n\
         Access-Control-Allow-Origin: http://127.0.0.1\r\n\
         Access-Control-Allow-Headers: Content-Type, Authorization, X-Bandori-Token\r\n\
         Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n\
         Content-Type: application/json; charset=utf-8\r\n\
         Content-Length: {}\r\n\
         Connection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(header.as_bytes())?;
    stream.write_all(&body)?;
    stream.flush()
}

fn runtime_settings(config: &ConfigDocument) -> RuntimeSettings {
    RuntimeSettings {
        compact_ai_window_enabled: config_bool(config, "compact_ai_window_enabled", false),
        compact_ai_window_opacity: config_i64(config, "compact_ai_window_opacity", 44)
            .clamp(10, 100),
        compact_ai_window_font_size: config_i64(config, "compact_ai_window_font_size", 12)
            .clamp(8, 36),
        compact_ai_window_background_color: {
            let configured = config_string(config, "compact_ai_window_background_color");
            let fallback =
                normalized_overlay_color(&config_string(config, "user_avatar_color"), "#fb7299");
            normalized_overlay_color(&configured, &fallback)
        },
        compact_ai_window_text_color: normalized_overlay_color(
            &config_string(config, "compact_ai_window_text_color"),
            "#24242a",
        ),
        ai_event_overlay_enabled: config_bool(config, "ai_event_overlay_enabled", false),
        ai_status_enabled: config_bool(config, "ai_status_port_enabled", false),
        ai_status_port: config_port(config, "ai_status_port", 38_472),
        ai_status_token: config_string(config, "ai_status_token"),
        chat_enabled: config_bool(config, "chat_integration_enabled", false),
        chat_overlay_enabled: config_bool(config, "chat_integration_overlay_enabled", true),
        chat_include_context: config_bool(config, "chat_integration_include_context", true),
        chat_port: config_port(config, "chat_integration_port", 38_473),
        chat_token: config_string(config, "chat_integration_token"),
    }
}

fn ensure_enabled_tokens(config: &mut ConfigDocument) -> Result<bool, IntegrationError> {
    let mut changed = false;
    for (enabled_key, token_key) in [
        ("ai_status_port_enabled", "ai_status_token"),
        ("chat_integration_enabled", "chat_integration_token"),
    ] {
        if config_bool(config, enabled_key, false) && config_string(config, token_key).is_empty() {
            config.set(token_key, Value::String(generate_token()?));
            changed = true;
        }
    }
    Ok(changed)
}

fn generate_token() -> Result<String, IntegrationError> {
    let mut bytes = [0_u8; 18];
    getrandom::fill(&mut bytes).map_err(|_| IntegrationError::TokenGeneration)?;
    Ok(URL_SAFE_NO_PAD.encode(bytes))
}

fn config_bool(config: &ConfigDocument, key: &str, fallback: bool) -> bool {
    config.get(key).and_then(Value::as_bool).unwrap_or(fallback)
}

fn config_i64(config: &ConfigDocument, key: &str, fallback: i64) -> i64 {
    config
        .get(key)
        .and_then(|value| {
            value
                .as_i64()
                .or_else(|| value.as_f64().map(|number| number.round() as i64))
                .or_else(|| value.as_str().and_then(|text| text.parse::<i64>().ok()))
        })
        .unwrap_or(fallback)
}

fn normalized_overlay_color(value: &str, fallback: &str) -> String {
    let value = value.trim();
    let valid = matches!(value.len(), 4 | 7 | 9)
        && value.starts_with('#')
        && value[1..].bytes().all(|byte| byte.is_ascii_hexdigit());
    if valid {
        value.to_ascii_lowercase()
    } else {
        fallback.to_owned()
    }
}

fn config_port(config: &ConfigDocument, key: &str, fallback: u16) -> u16 {
    let value = config.get(key).and_then(|value| {
        value
            .as_i64()
            .or_else(|| {
                value
                    .as_f64()
                    .filter(|value| value.is_finite())
                    .map(|value| value.round() as i64)
            })
            .or_else(|| {
                value
                    .as_str()
                    .and_then(|value| value.parse::<f64>().ok())
                    .filter(|value| value.is_finite())
                    .map(|value| value.round() as i64)
            })
    });
    let value = value.unwrap_or(i64::from(fallback));
    clamp_port(value)
}

fn clamp_port(value: i64) -> u16 {
    value.clamp(1024, 65_535) as u16
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn value_text(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(value)) => value.trim().to_owned(),
        Some(Value::Number(value)) => value.to_string(),
        Some(Value::Bool(value)) => value.to_string(),
        _ => String::new(),
    }
}

fn first_non_empty(values: &[String]) -> String {
    values
        .iter()
        .find(|value| !value.trim().is_empty())
        .cloned()
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::mpsc;

    fn read_http_response(stream: &mut TcpStream) -> (u16, Value) {
        let mut bytes = Vec::new();
        stream.read_to_end(&mut bytes).unwrap();
        let split = find_header_end(&bytes).unwrap();
        let status = std::str::from_utf8(&bytes[..split])
            .unwrap()
            .split_whitespace()
            .nth(1)
            .unwrap()
            .parse()
            .unwrap();
        let payload = if bytes.len() == split {
            Value::Null
        } else {
            serde_json::from_slice(&bytes[split..]).unwrap()
        };
        (status, payload)
    }

    fn request(port: u16, request: &str) -> (u16, Value) {
        let mut stream = TcpStream::connect((Ipv4Addr::LOCALHOST, port)).unwrap();
        stream.write_all(request.as_bytes()).unwrap();
        stream.shutdown(std::net::Shutdown::Write).unwrap();
        read_http_response(&mut stream)
    }

    #[test]
    fn onebot_message_segments_match_python_placeholders() {
        let event = json!({
            "post_type": "message",
            "message_type": "group",
            "group_id": 12,
            "user_id": 34,
            "message_id": 56,
            "sender": {"card": "Aya"},
            "message": [
                {"type": "at", "data": {"qq": "all"}},
                {"type": "text", "data": {"text": " hello "}},
                {"type": "image", "data": {"file": "x"}}
            ]
        });
        let normalized = normalize_onebot_event(&event).unwrap();
        assert_eq!(normalized["platform"], "qq");
        assert_eq!(normalized["thread_id"], "12");
        assert_eq!(normalized["sender_name"], "Aya");
        assert_eq!(normalized["text"], "@全体成员  hello [图片]");
    }

    #[test]
    fn settings_generate_tokens_without_exposing_them() {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("config.json");
        let view = save_native_integration_settings(
            &path,
            r##"{
                "chat_enabled":true,
                "chat_port":70000,
                "ai_status_enabled":true,
                "ai_status_port":-4,
                "compact_ai_window_opacity":500,
                "compact_ai_window_font_size":2,
                "compact_ai_window_background_color":"#ABCDEF",
                "compact_ai_window_text_color":"not-css"
            }"##,
        )
        .unwrap();
        assert!(view.chat_token_configured);
        assert!(view.ai_status_token_configured);
        assert_eq!(view.chat_port, 65_535);
        assert_eq!(view.ai_status_port, 1024);
        assert_eq!(view.compact_ai_window_opacity, 100);
        assert_eq!(view.compact_ai_window_font_size, 8);
        assert_eq!(view.compact_ai_window_background_color, "#abcdef");
        assert_eq!(view.compact_ai_window_text_color, "#24242a");
        let source = std::fs::read_to_string(path).unwrap();
        let saved: Value = serde_json::from_str(&source).unwrap();
        assert!(saved["chat_integration_token"].as_str().unwrap().len() >= 24);
        assert!(saved["ai_status_token"].as_str().unwrap().len() >= 24);
    }

    #[test]
    fn loopback_server_authenticates_stores_deduplicates_and_marks_read() {
        let directory = tempfile::tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        let available_port = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let mut config = ConfigDocument::default();
        config.set("chat_integration_enabled", Value::Bool(true));
        config.set("chat_integration_port", Value::from(available_port));
        config.set("chat_integration_token", Value::String("secret".into()));
        config.save(&config_path).unwrap();
        let (event_sender, event_receiver) = mpsc::channel();
        let (mut server, _) =
            NativeIntegrationServer::start(&config_path, &database_path, move |event| {
                event_sender.send(event).unwrap();
            })
            .unwrap();
        let port = server.status().chat_port;

        let unauthorized = request(
            port,
            "POST /chat-events HTTP/1.1\r\nHost: localhost\r\nContent-Length: 2\r\n\r\n{}",
        );
        assert_eq!(unauthorized.0, 401);

        let body = r#"{"platform":"test","thread_id":"room","sender_name":"Aya","text":"hello","message_id":"m1"}"#;
        let message = format!(
            "POST /chat-events HTTP/1.1\r\nHost: localhost\r\nX-Bandori-Token: secret\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
            body.len(),
            body
        );
        let stored = request(port, &message);
        assert_eq!(stored.0, 200);
        assert_eq!(stored.1["result"]["duplicate"], false);
        assert_eq!(
            event_receiver
                .recv_timeout(Duration::from_secs(1))
                .unwrap()
                .kind,
            "chat_overlay"
        );
        let duplicate = request(port, &message);
        assert_eq!(duplicate.1["result"]["duplicate"], true);
        assert!(event_receiver.try_recv().is_err());

        let read = request(
            port,
            "GET /chat-read?platform=test&thread_id=room&token=secret HTTP/1.1\r\nHost: localhost\r\n\r\n",
        );
        assert_eq!(read.0, 200);
        assert_eq!(read.1["result"]["marked_read"], 1);
        let clear = event_receiver.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(clear.kind, "chat_overlay");
        assert_eq!(clear.payload["state"], "clear");
        server.stop();
    }

    #[test]
    fn ai_status_server_authenticates_objects_and_rejects_oversized_bodies() {
        let directory = tempfile::tempdir().unwrap();
        let config_path = directory.path().join("config.json");
        let database_path = directory.path().join("data.db");
        let available_port = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let mut config = ConfigDocument::default();
        config.set("ai_status_port_enabled", Value::Bool(true));
        config.set("ai_status_port", Value::from(available_port));
        config.set("ai_status_token", Value::String("secret".into()));
        config.save(&config_path).unwrap();
        let (event_sender, event_receiver) = mpsc::channel();
        let (mut server, _) =
            NativeIntegrationServer::start(&config_path, &database_path, move |event| {
                event_sender.send(event).unwrap();
            })
            .unwrap();
        let port = server.status().ai_status_port;

        let body = r#"{"state":"thinking","text":"working"}"#;
        let accepted = request(
            port,
            &format!(
                "POST /ai-event?token=secret HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n{}",
                body.len(),
                body
            ),
        );
        assert_eq!(accepted, (200, json!({"ok": true})));
        let event = event_receiver.recv_timeout(Duration::from_secs(1)).unwrap();
        assert_eq!(event.kind, "ai_event");
        assert_eq!(event.payload["state"], "thinking");

        let oversized = request(
            port,
            "POST /ai-events?token=secret HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1048577\r\n\r\n",
        );
        assert_eq!(oversized.0, 413);
        assert!(event_receiver.try_recv().is_err());
        server.stop();
    }
}
