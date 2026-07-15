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
        #[qproperty(QString, chat_turn_json)]
        #[qproperty(QString, chat_request_json)]
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
        #[cxx_name = "prepareChatTurn"]
        fn prepare_chat_turn(
            self: Pin<&mut Self>,
            database_path: &QString,
            character: &QString,
            user_key: &QString,
            requested_conversation_id: &QString,
            content: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "buildChatRequest"]
        fn build_chat_request(
            self: Pin<&mut Self>,
            database_path: &QString,
            config_path: &QString,
            project_root: &QString,
            character_display_name: &QString,
            current_time_instruction: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "saveChatAssistant"]
        fn save_chat_assistant(
            self: Pin<&mut Self>,
            database_path: &QString,
            config_path: &QString,
            character_display_name: &QString,
            request_id: i64,
            content: &QString,
            reasoning: &QString,
            outcome_json: &QString,
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

        #[qsignal]
        #[cxx_name = "chatMemoryEvent"]
        fn chat_memory_event(self: Pin<&mut Self>, payload_json: &QString);
    }

    impl cxx_qt::Threading for Backend {}
}

use bandori_core::chat_actions::parse_chat_response;
use bandori_core::chat_context::build_native_chat_request;
use bandori_core::chat_dashboard::load_native_chat_snapshot;
use bandori_core::config::ConfigDocument;
use bandori_core::dashboard::{
    DashboardSnapshot, NativeRuntimeSnapshot, save_native_settings as persist_native_settings,
};
use bandori_core::database::Database;
use bandori_core::memory_extraction::{
    GLOBAL_MEMORY_CHARACTER, apply_model_relationship_analysis, apply_relationship_analysis,
    build_memory_extraction_messages, parse_memory_extraction, store_extracted_memories,
};
use bandori_core::relationship_analysis::{
    InteractionAnalysis, analyze_interaction, apply_interaction_analysis,
};
use bandori_llm::{
    LlmApiMode, LlmStreamEvent, LlmTransport, LlmTransportConfig, LlmTransportError,
    LlmTransportRequest,
};
use core::pin::Pin;
use cxx_qt::{CxxQtType, Threading};
use cxx_qt_lib::QString;
use serde_json::{Value, json};
use std::collections::HashMap;
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
    chat_turn_json: QString,
    chat_request_json: QString,
    chat_has_older_messages: bool,
    prepared_chat_conversation_id: i64,
    prepared_chat_user_message_id: i64,
    prepared_chat_character: String,
    prepared_chat_user_key: String,
    prepared_chat_user_content: String,
    active_chat_request_id: i64,
    active_chat_request_conversation_id: i64,
    active_chat_user_message_id: i64,
    active_chat_character: String,
    active_chat_user_key: String,
    active_chat_user_content: String,
    completed_chat_request_id: i64,
    completed_chat_conversation_id: i64,
    completed_chat_user_message_id: i64,
    completed_chat_character: String,
    completed_chat_user_key: String,
    completed_chat_user_content: String,
    next_chat_request_id: i64,
    active_chat_cancellation: Option<CancellationToken>,
    memory_cancellations: HashMap<i64, CancellationToken>,
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
            chat_turn_json: QString::from("{}"),
            chat_request_json: QString::from("{}"),
            chat_has_older_messages: false,
            prepared_chat_conversation_id: 0,
            prepared_chat_user_message_id: 0,
            prepared_chat_character: String::new(),
            prepared_chat_user_key: String::new(),
            prepared_chat_user_content: String::new(),
            active_chat_request_id: 0,
            active_chat_request_conversation_id: 0,
            active_chat_user_message_id: 0,
            active_chat_character: String::new(),
            active_chat_user_key: String::new(),
            active_chat_user_content: String::new(),
            completed_chat_request_id: 0,
            completed_chat_conversation_id: 0,
            completed_chat_user_message_id: 0,
            completed_chat_character: String::new(),
            completed_chat_user_key: String::new(),
            completed_chat_user_content: String::new(),
            next_chat_request_id: 1,
            active_chat_cancellation: None,
            memory_cancellations: HashMap::new(),
        }
    }
}

impl Drop for BackendRust {
    fn drop(&mut self) {
        if let Some(cancellation) = self.active_chat_cancellation.take() {
            cancellation.cancel();
        }
        for cancellation in self.memory_cancellations.drain().map(|(_, token)| token) {
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

    pub fn prepare_chat_turn(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        character: &QString,
        user_key: &QString,
        requested_conversation_id: &QString,
        content: &QString,
    ) -> bool {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A native LLM request is already running"));
            return false;
        }
        let requested_conversation_id = requested_conversation_id
            .to_string()
            .trim()
            .parse::<i64>()
            .ok();
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match database.begin_private_chat_turn(
            &character.to_string(),
            &user_key.to_string(),
            requested_conversation_id,
            &content.to_string(),
            None,
        ) {
            Ok(turn) => {
                let payload = serde_json::to_string(&turn)
                    .expect("private chat turn serialization cannot fail");
                let state = self.as_mut().rust_mut().get_mut();
                state.prepared_chat_conversation_id = turn.conversation_id;
                state.prepared_chat_user_message_id = turn.user_message_id;
                state.prepared_chat_character = character.to_string();
                state.prepared_chat_user_key = user_key.to_string();
                state.prepared_chat_user_content = content.to_string().trim().to_owned();
                state.completed_chat_request_id = 0;
                state.completed_chat_conversation_id = 0;
                state.completed_chat_user_message_id = 0;
                state.completed_chat_character.clear();
                state.completed_chat_user_key.clear();
                state.completed_chat_user_content.clear();
                self.as_mut().set_chat_active_conversation_id(QString::from(
                    &turn.conversation_id.to_string(),
                ));
                self.as_mut().set_chat_turn_json(QString::from(&payload));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                self.as_mut()
                    .set_status(QString::from("Native chat turn saved"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat turn error: {error}")));
                false
            }
        }
    }

    pub fn build_chat_request(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        config_path: &QString,
        project_root: &QString,
        character_display_name: &QString,
        current_time_instruction: &QString,
    ) -> bool {
        let (conversation_id, character, user_key) = {
            let state = self.as_ref().get_ref().rust();
            (
                state.prepared_chat_conversation_id,
                state.prepared_chat_character.clone(),
                state.prepared_chat_user_key.clone(),
            )
        };
        if conversation_id <= 0 || character.trim().is_empty() {
            self.as_mut().set_status(QString::from(
                "Prepare a native chat turn before building its request",
            ));
            self.as_mut().set_chat_request_json(QString::from("{}"));
            return false;
        }
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                return false;
            }
        };
        let config = match ConfigDocument::load(Path::new(&config_path.to_string())) {
            Ok(config) => config,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat config error: {error}")));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                return false;
            }
        };
        match build_native_chat_request(
            &database,
            &config,
            Path::new(&project_root.to_string()),
            &character,
            &character_display_name.to_string(),
            &user_key,
            conversation_id,
            &current_time_instruction.to_string(),
        ) {
            Ok(request) => {
                let payload = serde_json::to_string(&request)
                    .expect("native chat request serialization cannot fail");
                self.as_mut().set_chat_request_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native chat request ready"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat request error: {error}")));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                false
            }
        }
    }

    pub fn save_chat_assistant(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        config_path: &QString,
        character_display_name: &QString,
        request_id: i64,
        content: &QString,
        reasoning: &QString,
        outcome_json: &QString,
    ) -> bool {
        let (
            completed_request_id,
            conversation_id,
            user_message_id,
            character,
            user_key,
            user_content,
        ) = {
            let state = self.as_ref().get_ref().rust();
            (
                state.completed_chat_request_id,
                state.completed_chat_conversation_id,
                state.completed_chat_user_message_id,
                state.completed_chat_character.clone(),
                state.completed_chat_user_key.clone(),
                state.completed_chat_user_content.clone(),
            )
        };
        if request_id <= 0 || completed_request_id != request_id {
            self.as_mut().set_status(QString::from(
                "Native chat completion is stale or unavailable",
            ));
            return false;
        }
        if conversation_id <= 0 {
            self.as_mut()
                .set_status(QString::from("Native chat completion has no conversation"));
            return false;
        }
        let response = parse_chat_response(&content.to_string(), &reasoning.to_string());
        if response.content.is_empty()
            && response.reasoning.is_empty()
            && response.actions.is_empty()
        {
            self.as_mut()
                .set_status(QString::from("Native assistant response is empty"));
            return false;
        }
        let trace = assistant_tool_trace(&outcome_json.to_string());
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match database.add_message(
            conversation_id,
            "assistant",
            &response.content,
            &response.reasoning,
            None,
            trace.as_ref(),
        ) {
            Ok(message_id) => {
                let fallback = (!character.is_empty() && !user_content.is_empty())
                    .then(|| analyze_interaction(&user_content, &response.actions));
                let memory_job = fallback.as_ref().map(|fallback| {
                    prepare_memory_extraction_job(
                        &database,
                        Path::new(&config_path.to_string()),
                        &database_path.to_string(),
                        &character,
                        &character_display_name.to_string(),
                        &user_key,
                        &user_content,
                        &response.content,
                        user_message_id,
                        fallback,
                    )
                });
                let mut relationship_state = None;
                let mut relationship_error = None;
                let mut relationship_pending = false;
                match memory_job {
                    Some(Ok(Some(job))) => {
                        let cancellation = CancellationToken::new();
                        self.as_mut()
                            .rust_mut()
                            .get_mut()
                            .memory_cancellations
                            .insert(request_id, cancellation.clone());
                        let qt_thread = self.qt_thread();
                        if let Err(error) = std::thread::Builder::new()
                            .name(format!("bandori-memory-{request_id}"))
                            .spawn(move || {
                                run_memory_extraction(qt_thread, request_id, job, cancellation);
                            })
                        {
                            self.as_mut()
                                .rust_mut()
                                .get_mut()
                                .memory_cancellations
                                .remove(&request_id);
                            relationship_error =
                                Some(format!("Could not start native memory worker: {error}"));
                            match apply_interaction_analysis(
                                &database,
                                &character,
                                &user_key,
                                &user_content,
                                &response.actions,
                                "chat",
                            ) {
                                Ok(state) => relationship_state = Some(state),
                                Err(error) => relationship_error = Some(error.to_string()),
                            }
                        } else {
                            relationship_pending = true;
                        }
                    }
                    Some(Ok(None)) | None => {
                        if fallback.is_some() {
                            match apply_interaction_analysis(
                                &database,
                                &character,
                                &user_key,
                                &user_content,
                                &response.actions,
                                "chat",
                            ) {
                                Ok(state) => relationship_state = Some(state),
                                Err(error) => relationship_error = Some(error.to_string()),
                            }
                        }
                    }
                    Some(Err(error)) => {
                        relationship_error = Some(error);
                        match apply_interaction_analysis(
                            &database,
                            &character,
                            &user_key,
                            &user_content,
                            &response.actions,
                            "chat",
                        ) {
                            Ok(state) => relationship_state = Some(state),
                            Err(error) => relationship_error = Some(error.to_string()),
                        }
                    }
                }
                let relationship_updated = relationship_state.is_some();
                let payload = json!({
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "assistant_message_id": message_id,
                    "request_id": request_id,
                    "content": response.content,
                    "reasoning": response.reasoning,
                    "actions": response.actions,
                    "relationship_state": relationship_state,
                    "relationship_error": relationship_error,
                    "relationship_pending": relationship_pending,
                })
                .to_string();
                let state = self.as_mut().rust_mut().get_mut();
                state.completed_chat_request_id = 0;
                state.completed_chat_conversation_id = 0;
                state.completed_chat_user_message_id = 0;
                state.completed_chat_character.clear();
                state.completed_chat_user_key.clear();
                state.completed_chat_user_content.clear();
                self.as_mut().set_chat_turn_json(QString::from(&payload));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                self.as_mut()
                    .set_status(QString::from(if relationship_pending {
                        "Native assistant response saved; memory analysis is running"
                    } else if relationship_updated {
                        "Native assistant response and relationship state saved"
                    } else {
                        "Native assistant response saved; relationship update was unavailable"
                    }));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Assistant save error: {error}")));
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
        if self.as_ref().get_ref().rust().prepared_chat_conversation_id <= 0 {
            self.as_mut().set_status(QString::from(
                "Prepare and build a native chat turn before starting its stream",
            ));
            return 0;
        }

        let request_id;
        let request_conversation_id;
        let cancellation = CancellationToken::new();
        {
            let state = self.as_mut().rust_mut().get_mut();
            if let Some(previous) = state.active_chat_cancellation.take() {
                previous.cancel();
            }
            request_id = state.next_chat_request_id.max(1);
            state.next_chat_request_id = request_id.checked_add(1).unwrap_or(1);
            request_conversation_id = state.prepared_chat_conversation_id;
            state.prepared_chat_conversation_id = 0;
            state.active_chat_request_id = request_id;
            state.active_chat_request_conversation_id = request_conversation_id;
            state.active_chat_user_message_id = state.prepared_chat_user_message_id;
            state.prepared_chat_user_message_id = 0;
            state.active_chat_character = std::mem::take(&mut state.prepared_chat_character);
            state.active_chat_user_key = std::mem::take(&mut state.prepared_chat_user_key);
            state.active_chat_user_content = std::mem::take(&mut state.prepared_chat_user_content);
            state.completed_chat_request_id = 0;
            state.completed_chat_conversation_id = 0;
            state.completed_chat_user_message_id = 0;
            state.completed_chat_character.clear();
            state.completed_chat_user_key.clear();
            state.completed_chat_user_content.clear();
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
            state.prepared_chat_conversation_id = request_conversation_id;
            state.prepared_chat_user_message_id = state.active_chat_user_message_id;
            state.active_chat_user_message_id = 0;
            state.prepared_chat_character = std::mem::take(&mut state.active_chat_character);
            state.prepared_chat_user_key = std::mem::take(&mut state.active_chat_user_key);
            state.prepared_chat_user_content = std::mem::take(&mut state.active_chat_user_content);
            state.active_chat_request_id = 0;
            state.active_chat_request_conversation_id = 0;
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
            let finished = serde_json::from_str::<Value>(&payload)
                .ok()
                .and_then(|value| {
                    value
                        .get("state")
                        .and_then(Value::as_str)
                        .map(str::to_owned)
                })
                .is_some_and(|state| state == "finished");
            let state = self.as_mut().rust_mut().get_mut();
            if finished && state.active_chat_request_conversation_id > 0 {
                state.completed_chat_request_id = request_id;
                state.completed_chat_conversation_id = state.active_chat_request_conversation_id;
                state.completed_chat_user_message_id = state.active_chat_user_message_id;
                state.completed_chat_character = std::mem::take(&mut state.active_chat_character);
                state.completed_chat_user_key = std::mem::take(&mut state.active_chat_user_key);
                state.completed_chat_user_content =
                    std::mem::take(&mut state.active_chat_user_content);
            } else {
                state.completed_chat_request_id = 0;
                state.completed_chat_conversation_id = 0;
                state.completed_chat_user_message_id = 0;
                state.completed_chat_character.clear();
                state.completed_chat_user_key.clear();
                state.completed_chat_user_content.clear();
            }
            state.active_chat_request_id = 0;
            state.active_chat_request_conversation_id = 0;
            state.active_chat_user_message_id = 0;
            state.active_chat_character.clear();
            state.active_chat_user_key.clear();
            state.active_chat_user_content.clear();
            state.active_chat_cancellation = None;
        }
        self.as_mut()
            .chat_stream_event(&QString::from(payload.as_str()));
    }

    fn emit_chat_memory_payload(mut self: Pin<&mut Self>, request_id: i64, payload: String) {
        self.as_mut()
            .rust_mut()
            .get_mut()
            .memory_cancellations
            .remove(&request_id);
        self.as_mut()
            .chat_memory_event(&QString::from(payload.as_str()));
    }
}

#[derive(Clone)]
struct MemoryExtractionJob {
    database_path: String,
    character: String,
    user_key: String,
    source_message_id: i64,
    fallback: InteractionAnalysis,
    config: LlmTransportConfig,
    request: LlmTransportRequest,
}

#[allow(clippy::too_many_arguments)]
fn prepare_memory_extraction_job(
    database: &Database,
    config_path: &Path,
    database_path: &str,
    character: &str,
    character_display_name: &str,
    user_key: &str,
    user_text: &str,
    assistant_text: &str,
    source_message_id: i64,
    fallback: &InteractionAnalysis,
) -> Result<Option<MemoryExtractionJob>, String> {
    let Some(config) = load_memory_transport_config(config_path)? else {
        return Ok(None);
    };
    let existing = database
        .character_memories(character, user_key, 12)
        .map_err(|error| format!("Memory context error: {error}"))?;
    let global = database
        .character_memories(GLOBAL_MEMORY_CHARACTER, user_key, 12)
        .map_err(|error| format!("Global memory context error: {error}"))?;
    Ok(Some(MemoryExtractionJob {
        database_path: database_path.to_owned(),
        character: character.to_owned(),
        user_key: user_key.to_owned(),
        source_message_id,
        fallback: fallback.clone(),
        config,
        request: LlmTransportRequest {
            messages: build_memory_extraction_messages(
                user_text,
                assistant_text,
                &existing,
                &global,
                character_display_name,
            ),
            tools: Vec::new(),
            previous_response_id: String::new(),
        },
    }))
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

fn load_memory_transport_config(path: &Path) -> Result<Option<LlmTransportConfig>, String> {
    let config =
        ConfigDocument::load(path).map_err(|error| format!("Memory LLM config error: {error}"))?;
    let api_url = nonempty_config_string(&config, "llm_aux_api_url", "llm_api_url");
    let api_key = nonempty_config_string(&config, "llm_aux_api_key", "llm_api_key");
    let model = nonempty_config_string(&config, "llm_aux_model_id", "llm_model_id");
    if api_url.is_empty() || api_key.is_empty() || model.is_empty() {
        return Ok(None);
    }
    Ok(Some(LlmTransportConfig {
        api_url,
        api_key,
        model,
        mode: LlmApiMode::ChatCompletions,
        enable_thinking: None,
    }))
}

fn nonempty_config_string(config: &ConfigDocument, preferred: &str, fallback: &str) -> String {
    let value = config_string(config, preferred);
    if value.is_empty() {
        config_string(config, fallback)
    } else {
        value
    }
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

fn assistant_tool_trace(outcome_json: &str) -> Option<Value> {
    let outcome = serde_json::from_str::<Value>(outcome_json).ok()?;
    let usage = outcome.get("usage")?.as_object()?;
    Some(json!({"llm_usage": usage}))
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

fn run_memory_extraction(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    job: MemoryExtractionJob,
    cancellation: CancellationToken,
) {
    let database = match Database::open(Path::new(&job.database_path)) {
        Ok(database) => database,
        Err(error) => {
            queue_memory_payload(
                &qt_thread,
                request_id,
                json!({
                    "request_id": request_id,
                    "state": "error",
                    "message": format!("Memory database error: {error}"),
                }),
            );
            return;
        }
    };
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            finish_memory_with_fallback(
                &qt_thread,
                request_id,
                &database,
                &job,
                &cancellation,
                format!("Memory async runtime error: {error}"),
            );
            return;
        }
    };
    let transport = match LlmTransport::new(job.config.clone()) {
        Ok(transport) => transport,
        Err(error) => {
            finish_memory_with_fallback(
                &qt_thread,
                request_id,
                &database,
                &job,
                &cancellation,
                error.to_string(),
            );
            return;
        }
    };
    let mut response_text = String::new();
    let result = runtime.block_on(transport.stream(&job.request, &cancellation, |event| {
        if let LlmStreamEvent::TextDelta { text } = event {
            response_text.push_str(&text);
        }
    }));
    match result {
        Ok(outcome) => {
            if cancellation.is_cancelled() {
                queue_memory_payload(
                    &qt_thread,
                    request_id,
                    json!({"request_id": request_id, "state": "cancelled"}),
                );
                return;
            }
            let parsed = parse_memory_extraction(&response_text);
            let analysis = parsed.relationship.as_ref().unwrap_or(&job.fallback);
            let relationship_state = match apply_model_relationship_analysis(
                &database,
                &job.character,
                &job.user_key,
                analysis,
            ) {
                Ok(state) => state,
                Err(error) => {
                    queue_memory_payload(
                        &qt_thread,
                        request_id,
                        json!({
                            "request_id": request_id,
                            "state": "error",
                            "message": format!("Memory relationship update error: {error}"),
                        }),
                    );
                    return;
                }
            };
            match store_extracted_memories(
                &database,
                &job.character,
                &job.user_key,
                &parsed,
                Some(job.source_message_id),
                None,
            ) {
                Ok(stored) => queue_memory_payload(
                    &qt_thread,
                    request_id,
                    json!({
                        "request_id": request_id,
                        "state": "finished",
                        "relationship_state": relationship_state,
                        "used_model_relationship": parsed.relationship.is_some(),
                        "memories_added": stored.added,
                        "memories_removed": stored.removed,
                        "usage": outcome.usage,
                    }),
                ),
                Err(error) => queue_memory_payload(
                    &qt_thread,
                    request_id,
                    json!({
                        "request_id": request_id,
                        "state": "error",
                        "relationship_state": relationship_state,
                        "message": format!("Memory persistence error: {error}"),
                    }),
                ),
            }
        }
        Err(LlmTransportError::Cancelled) => queue_memory_payload(
            &qt_thread,
            request_id,
            json!({"request_id": request_id, "state": "cancelled"}),
        ),
        Err(error) => finish_memory_with_fallback(
            &qt_thread,
            request_id,
            &database,
            &job,
            &cancellation,
            error.to_string(),
        ),
    }
}

fn finish_memory_with_fallback(
    qt_thread: &ffi::BackendCxxQtThread,
    request_id: i64,
    database: &Database,
    job: &MemoryExtractionJob,
    cancellation: &CancellationToken,
    message: String,
) {
    if cancellation.is_cancelled() {
        queue_memory_payload(
            qt_thread,
            request_id,
            json!({"request_id": request_id, "state": "cancelled"}),
        );
        return;
    }
    let payload = match apply_relationship_analysis(
        database,
        &job.character,
        &job.user_key,
        &job.fallback,
        "chat",
    ) {
        Ok(state) => json!({
            "request_id": request_id,
            "state": "fallback",
            "relationship_state": state,
            "message": message,
        }),
        Err(error) => json!({
            "request_id": request_id,
            "state": "error",
            "message": format!("{message}; fallback relationship update failed: {error}"),
        }),
    };
    queue_memory_payload(qt_thread, request_id, payload);
}

fn queue_memory_payload(qt_thread: &ffi::BackendCxxQtThread, request_id: i64, payload: Value) {
    let payload = payload.to_string();
    qt_thread
        .queue(move |backend| {
            backend.emit_chat_memory_payload(request_id, payload);
        })
        .ok();
}

fn config_summary(loaded: bool, keys: usize, pets: usize, fps: i64) -> String {
    let source = if loaded { "config.json" } else { "defaults" };
    format!("{source} · {keys} keys · {pets} configured pets · {fps} FPS")
}
