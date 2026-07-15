#[cxx_qt::bridge]
pub mod ffi {
    unsafe extern "C++" {
        include!("cxx-qt-lib/qstring.h");
        type QString = cxx_qt_lib::QString;
    }

    #[auto_cxx_name]
    extern "RustQt" {
        #[qobject]
        #[qproperty(QString, status)]
        #[qproperty(QString, config_summary)]
        #[qproperty(QString, model_catalog_json)]
        #[qproperty(QString, runtime_config_json)]
        #[qproperty(QString, chat_conversations_json)]
        #[qproperty(QString, chat_messages_json)]
        #[qproperty(QString, chat_active_conversation_id)]
        #[qproperty(bool, chat_has_older_messages)]
        #[namespace = "bandori"]
        type Backend = super::BackendRust;

        #[qinvokable]
        #[cxx_name = "loadConfig"]
        fn load_config(self: Pin<&mut Self>, path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "reloadState"]
        fn reload_state(
            self: Pin<&mut Self>,
            project_root: &QString,
            user_models_root: &QString,
            config_path: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "saveNativeSettings"]
        fn save_native_settings(
            self: Pin<&mut Self>,
            config_path: &QString,
            settings_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadChatState"]
        fn load_chat_state(
            self: Pin<&mut Self>,
            database_path: &QString,
            character: &QString,
            user_key: &QString,
            requested_conversation_id: &QString,
            message_limit: i32,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "startChatStream"]
        fn start_chat_stream(
            self: Pin<&mut Self>,
            config_path: &QString,
            request_json: &QString,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "cancelChatStream"]
        fn cancel_chat_stream(self: Pin<&mut Self>, request_id: i64) -> bool;

        #[qsignal]
        #[cxx_name = "chatStreamEvent"]
        fn chat_stream_event(self: Pin<&mut Self>, payload_json: &QString);
    }

    impl cxx_qt::Threading for Backend {}
}

use bandori_core::chat_dashboard::load_native_chat_snapshot;
use bandori_core::config::ConfigDocument;
use bandori_core::dashboard::{
    DashboardSnapshot, NativeRuntimeSnapshot, save_native_settings as persist_native_settings,
};
use bandori_llm::{
    LlmApiMode, LlmStreamEvent, LlmTransport, LlmTransportConfig, LlmTransportError,
    LlmTransportRequest,
};
use core::pin::Pin;
use cxx_qt::{CxxQtType, Threading};
use cxx_qt_lib::QString;
use serde_json::{Value, json};
use std::path::Path;
use tokio_util::sync::CancellationToken;

const MAX_CHAT_REQUEST_BYTES: usize = 4 * 1024 * 1024;

pub struct BackendRust {
    status: QString,
    config_summary: QString,
    model_catalog_json: QString,
    runtime_config_json: QString,
    chat_conversations_json: QString,
    chat_messages_json: QString,
    chat_active_conversation_id: QString,
    chat_has_older_messages: bool,
    active_chat_request_id: i64,
    next_chat_request_id: i64,
    active_chat_cancellation: Option<CancellationToken>,
}

impl Default for BackendRust {
    fn default() -> Self {
        Self {
            status: QString::from("Rust core ready"),
            config_summary: QString::from("Configuration has not been loaded"),
            model_catalog_json: QString::from("[]"),
            runtime_config_json: QString::from("{}"),
            chat_conversations_json: QString::from("[]"),
            chat_messages_json: QString::from("[]"),
            chat_active_conversation_id: QString::default(),
            chat_has_older_messages: false,
            active_chat_request_id: 0,
            next_chat_request_id: 1,
            active_chat_cancellation: None,
        }
    }
}

impl Drop for BackendRust {
    fn drop(&mut self) {
        if let Some(cancellation) = self.active_chat_cancellation.take() {
            cancellation.cancel();
        }
    }
}

impl ffi::Backend {
    pub fn load_config(mut self: Pin<&mut Self>, path: &QString) -> bool {
        let path = path.to_string();
        match ConfigDocument::load(Path::new(&path)) {
            Ok(config) => {
                let runtime = NativeRuntimeSnapshot::from_config(&config);
                let runtime_json = serde_json::to_string(&runtime)
                    .expect("native runtime snapshot serialization cannot fail");
                let summary = config_summary(
                    config.loaded_from_file(),
                    config.values().len(),
                    runtime.configured_pets.len(),
                    runtime.fps,
                );
                self.as_mut()
                    .set_status(QString::from("Rust configuration service ready"));
                self.as_mut().set_config_summary(QString::from(&summary));
                self.as_mut()
                    .set_runtime_config_json(QString::from(&runtime_json));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Configuration error: {error}")));
                false
            }
        }
    }

    pub fn reload_state(
        mut self: Pin<&mut Self>,
        project_root: &QString,
        user_models_root: &QString,
        config_path: &QString,
    ) -> bool {
        let project_root = project_root.to_string();
        let user_models_root = user_models_root.to_string();
        let config_path = config_path.to_string();
        match DashboardSnapshot::load(
            Path::new(&project_root),
            Path::new(&user_models_root),
            Path::new(&config_path),
        ) {
            Ok(snapshot) => {
                let catalog_json = serde_json::to_string(&snapshot.model_catalog)
                    .expect("model catalog serialization cannot fail");
                let runtime_json = serde_json::to_string(&snapshot.runtime)
                    .expect("native runtime snapshot serialization cannot fail");
                let status = format!(
                    "Rust services ready · {} characters · {} costumes",
                    snapshot.character_count(),
                    snapshot.model_catalog.len()
                );
                let summary = config_summary(
                    snapshot.config_loaded_from_file,
                    snapshot.config_key_count,
                    snapshot.runtime.configured_pets.len(),
                    snapshot.runtime.fps,
                );
                self.as_mut().set_status(QString::from(&status));
                self.as_mut().set_config_summary(QString::from(&summary));
                self.as_mut()
                    .set_model_catalog_json(QString::from(&catalog_json));
                self.as_mut()
                    .set_runtime_config_json(QString::from(&runtime_json));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("State reload error: {error}")));
                self.as_mut()
                    .set_config_summary(QString::from("Configuration could not be loaded"));
                self.as_mut().set_model_catalog_json(QString::from("[]"));
                self.as_mut().set_runtime_config_json(QString::from("{}"));
                false
            }
        }
    }

    pub fn save_native_settings(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        settings_json: &QString,
    ) -> bool {
        let config_path = config_path.to_string();
        let settings_json = settings_json.to_string();
        match persist_native_settings(Path::new(&config_path), &settings_json) {
            Ok(runtime) => {
                let runtime_json = serde_json::to_string(&runtime)
                    .expect("native runtime snapshot serialization cannot fail");
                let summary = format!(
                    "config.json · {} configured pets · {} FPS",
                    runtime.configured_pets.len(),
                    runtime.fps
                );
                self.as_mut()
                    .set_status(QString::from("Native settings saved atomically"));
                self.as_mut().set_config_summary(QString::from(&summary));
                self.as_mut()
                    .set_runtime_config_json(QString::from(&runtime_json));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Settings save error: {error}")));
                false
            }
        }
    }

    pub fn load_chat_state(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        character: &QString,
        user_key: &QString,
        requested_conversation_id: &QString,
        message_limit: i32,
    ) -> bool {
        let database_path = database_path.to_string();
        let character = character.to_string();
        let user_key = user_key.to_string();
        let requested_conversation_id = requested_conversation_id
            .to_string()
            .trim()
            .parse::<i64>()
            .ok();
        match load_native_chat_snapshot(
            Path::new(&database_path),
            &character,
            &user_key,
            requested_conversation_id,
            i64::from(message_limit),
        ) {
            Ok(snapshot) => {
                let conversations_json = serde_json::to_string(&snapshot.conversations)
                    .expect("chat conversation serialization cannot fail");
                let messages_json = serde_json::to_string(&snapshot.messages)
                    .expect("chat message serialization cannot fail");
                let active_id = snapshot
                    .active_conversation_id
                    .map(|value| value.to_string())
                    .unwrap_or_default();
                self.as_mut()
                    .set_chat_conversations_json(QString::from(&conversations_json));
                self.as_mut()
                    .set_chat_messages_json(QString::from(&messages_json));
                self.as_mut()
                    .set_chat_active_conversation_id(QString::from(&active_id));
                self.as_mut()
                    .set_chat_has_older_messages(snapshot.has_older_messages);
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                self.as_mut()
                    .set_chat_conversations_json(QString::from("[]"));
                self.as_mut().set_chat_messages_json(QString::from("[]"));
                self.as_mut()
                    .set_chat_active_conversation_id(QString::default());
                self.as_mut().set_chat_has_older_messages(false);
                false
            }
        }
    }

    pub fn start_chat_stream(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        request_json: &QString,
    ) -> i64 {
        let config = match load_llm_transport_config(Path::new(&config_path.to_string())) {
            Ok(config) => config,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let request_json = request_json.to_string();
        let request = match parse_llm_request(&request_json) {
            Ok(request) => request,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };

        let request_id;
        let cancellation = CancellationToken::new();
        {
            let state = self.as_mut().rust_mut().get_mut();
            if let Some(previous) = state.active_chat_cancellation.take() {
                previous.cancel();
            }
            request_id = state.next_chat_request_id.max(1);
            state.next_chat_request_id = request_id.checked_add(1).unwrap_or(1);
            state.active_chat_request_id = request_id;
            state.active_chat_cancellation = Some(cancellation.clone());
        }
        self.as_mut()
            .set_status(QString::from("Native LLM request started"));
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-llm-{request_id}"))
            .spawn(move || {
                run_llm_stream(qt_thread, request_id, config, request, cancellation);
            })
        {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_chat_request_id = 0;
            state.active_chat_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start native LLM worker: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn cancel_chat_stream(mut self: Pin<&mut Self>, request_id: i64) -> bool {
        let state = self.as_mut().rust_mut().get_mut();
        if state.active_chat_request_id == 0
            || (request_id > 0 && request_id != state.active_chat_request_id)
        {
            return false;
        }
        let Some(cancellation) = state.active_chat_cancellation.as_ref() else {
            return false;
        };
        cancellation.cancel();
        self.as_mut()
            .set_status(QString::from("Native LLM cancellation requested"));
        true
    }

    fn emit_chat_stream_payload(
        mut self: Pin<&mut Self>,
        request_id: i64,
        payload: String,
        terminal: bool,
    ) {
        if self.as_ref().get_ref().rust().active_chat_request_id != request_id {
            return;
        }
        if terminal {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_chat_request_id = 0;
            state.active_chat_cancellation = None;
        }
        self.as_mut()
            .chat_stream_event(&QString::from(payload.as_str()));
    }
}

fn load_llm_transport_config(path: &Path) -> Result<LlmTransportConfig, String> {
    let config =
        ConfigDocument::load(path).map_err(|error| format!("LLM config error: {error}"))?;
    let api_url = config_string(&config, "llm_api_url");
    let model = config_string(&config, "llm_model_id");
    if api_url.is_empty() {
        return Err("LLM API URL is not configured".to_owned());
    }
    if model.is_empty() {
        return Err("LLM model is not configured".to_owned());
    }
    Ok(LlmTransportConfig {
        api_url,
        api_key: config_string(&config, "llm_api_key"),
        model,
        mode: LlmApiMode::from_config(&config_string(&config, "llm_api_mode")),
        enable_thinking: config.get("llm_enable_thinking").and_then(Value::as_bool),
    })
}

fn config_string(config: &ConfigDocument, key: &str) -> String {
    config
        .get(key)
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned()
}

fn parse_llm_request(source: &str) -> Result<LlmTransportRequest, String> {
    LlmTransportRequest::from_json(source, MAX_CHAT_REQUEST_BYTES)
        .map_err(|error| format!("Invalid native LLM request: {error}"))
}

fn run_llm_stream(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    config: LlmTransportConfig,
    request: LlmTransportRequest,
    cancellation: CancellationToken,
) {
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            queue_terminal_payload(
                &qt_thread,
                request_id,
                json!({"request_id": request_id, "state": "error", "message": format!("Async runtime error: {error}")}),
            );
            return;
        }
    };
    let transport = match LlmTransport::new(config) {
        Ok(transport) => transport,
        Err(error) => {
            queue_terminal_payload(
                &qt_thread,
                request_id,
                json!({"request_id": request_id, "state": "error", "message": error.to_string()}),
            );
            return;
        }
    };
    let event_thread = qt_thread.clone();
    let result = runtime.block_on(transport.stream(&request, &cancellation, move |event| {
        queue_stream_event(&event_thread, request_id, event);
    }));
    let payload = match result {
        Ok(outcome) => json!({
            "request_id": request_id,
            "state": "finished",
            "mode": outcome.mode,
            "response_id": outcome.response_id,
            "usage": outcome.usage,
        }),
        Err(LlmTransportError::Cancelled) => {
            json!({"request_id": request_id, "state": "cancelled"})
        }
        Err(error) => {
            json!({"request_id": request_id, "state": "error", "message": error.to_string()})
        }
    };
    queue_terminal_payload(&qt_thread, request_id, payload);
}

fn queue_stream_event(qt_thread: &ffi::BackendCxxQtThread, request_id: i64, event: LlmStreamEvent) {
    let payload = json!({"request_id": request_id, "state": "event", "event": event}).to_string();
    qt_thread
        .queue(move |backend| {
            backend.emit_chat_stream_payload(request_id, payload, false);
        })
        .ok();
}

fn queue_terminal_payload(qt_thread: &ffi::BackendCxxQtThread, request_id: i64, payload: Value) {
    let payload = payload.to_string();
    qt_thread
        .queue(move |backend| {
            backend.emit_chat_stream_payload(request_id, payload, true);
        })
        .ok();
}

fn config_summary(loaded: bool, keys: usize, pets: usize, fps: i64) -> String {
    let source = if loaded { "config.json" } else { "defaults" };
    format!("{source} · {keys} keys · {pets} configured pets · {fps} FPS")
}
