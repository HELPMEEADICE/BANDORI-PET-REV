#[cxx_qt::bridge]
pub mod ffi {
    unsafe extern "C++" {
        include!("cxx-qt-lib/qbytearray.h");
        include!("cxx-qt-lib/qstring.h");
        type QByteArray = cxx_qt_lib::QByteArray;
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
        #[qproperty(QString, chat_imported_attachments_json)]
        #[qproperty(QString, reminder_events_json)]
        #[qproperty(QString, reminder_state_json)]
        #[qproperty(QString, llm_settings_json)]
        #[qproperty(QString, tts_settings_json)]
        #[qproperty(QString, asr_settings_json)]
        #[qproperty(QString, memory_snapshot_json)]
        #[qproperty(QString, user_profiles_json)]
        #[qproperty(QString, persona_settings_json)]
        #[qproperty(QString, history_filters_json)]
        #[qproperty(QString, history_result_json)]
        #[qproperty(QString, statistics_snapshot_json)]
        #[qproperty(QString, data_operation_json)]
        #[qproperty(QString, attachment_management_json)]
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
        #[cxx_name = "tickReminders"]
        fn tick_reminders(
            self: Pin<&mut Self>,
            config_path: &QString,
            local_datetime: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadReminderState"]
        fn load_reminder_state(
            self: Pin<&mut Self>,
            config_path: &QString,
            local_datetime: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "mutateReminder"]
        fn mutate_reminder(
            self: Pin<&mut Self>,
            config_path: &QString,
            local_datetime: &QString,
            command_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadLlmSettings"]
        fn load_llm_settings(self: Pin<&mut Self>, config_path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "saveLlmSettings"]
        fn save_llm_settings(
            self: Pin<&mut Self>,
            config_path: &QString,
            settings_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "mutateLlmProfile"]
        fn mutate_llm_profile(
            self: Pin<&mut Self>,
            config_path: &QString,
            command_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "startProviderOperation"]
        fn start_provider_operation(
            self: Pin<&mut Self>,
            config_path: &QString,
            target: &QString,
            operation: &QString,
            api_url: &QString,
            api_key: &QString,
            model: &QString,
            api_mode: &QString,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "cancelProviderOperation"]
        fn cancel_provider_operation(self: Pin<&mut Self>, request_id: i64) -> bool;

        #[qinvokable]
        #[cxx_name = "loadTtsSettings"]
        fn load_tts_settings(self: Pin<&mut Self>, config_path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "saveTtsSettings"]
        fn save_tts_settings(
            self: Pin<&mut Self>,
            config_path: &QString,
            settings_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "startTtsSynthesis"]
        fn start_tts_synthesis(
            self: Pin<&mut Self>,
            config_path: &QString,
            project_root: &QString,
            text: &QString,
            character: &QString,
            speed_factor: f64,
            force: bool,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "cancelTtsSynthesis"]
        fn cancel_tts_synthesis(self: Pin<&mut Self>, request_id: i64) -> bool;

        #[qinvokable]
        #[cxx_name = "loadAsrSettings"]
        fn load_asr_settings(self: Pin<&mut Self>, config_path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "saveAsrSettings"]
        fn save_asr_settings(
            self: Pin<&mut Self>,
            config_path: &QString,
            settings_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "startAsrTranscription"]
        fn start_asr_transcription(
            self: Pin<&mut Self>,
            config_path: &QString,
            audio: &QByteArray,
            force: bool,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "cancelAsrTranscription"]
        fn cancel_asr_transcription(self: Pin<&mut Self>, request_id: i64) -> bool;

        #[qinvokable]
        #[cxx_name = "loadMemoryState"]
        fn load_memory_state(
            self: Pin<&mut Self>,
            database_path: &QString,
            character: &QString,
            user_key: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "mutateMemory"]
        fn mutate_memory(
            self: Pin<&mut Self>,
            database_path: &QString,
            character: &QString,
            user_key: &QString,
            command_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadUserProfiles"]
        fn load_user_profiles(self: Pin<&mut Self>, config_path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "mutateUserProfile"]
        fn mutate_user_profile(
            self: Pin<&mut Self>,
            config_path: &QString,
            command_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadPersonaSettings"]
        fn load_persona_settings(
            self: Pin<&mut Self>,
            config_path: &QString,
            project_root: &QString,
            characters_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "mutatePersonaSettings"]
        fn mutate_persona_settings(
            self: Pin<&mut Self>,
            config_path: &QString,
            project_root: &QString,
            characters_json: &QString,
            command_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadHistoryFilters"]
        fn load_history_filters(self: Pin<&mut Self>, database_path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "searchHistory"]
        fn search_history(
            self: Pin<&mut Self>,
            database_path: &QString,
            query_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadStatistics"]
        fn load_statistics(
            self: Pin<&mut Self>,
            database_path: &QString,
            query_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "exportSettingsPackage"]
        fn export_settings_package(
            self: Pin<&mut Self>,
            config_path: &QString,
            database_path: &QString,
            category: &QString,
            destination_path: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "importSettingsPackage"]
        fn import_settings_package(
            self: Pin<&mut Self>,
            config_path: &QString,
            database_path: &QString,
            category: &QString,
            source_path: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "exportChatDatabase"]
        fn export_chat_database(
            self: Pin<&mut Self>,
            database_path: &QString,
            destination_path: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "importChatDatabase"]
        fn import_chat_database(
            self: Pin<&mut Self>,
            database_path: &QString,
            source_path: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "loadAttachmentStats"]
        fn load_attachment_stats(self: Pin<&mut Self>, database_path: &QString) -> bool;

        #[qinvokable]
        #[cxx_name = "cleanupChatAttachments"]
        fn cleanup_chat_attachments(
            self: Pin<&mut Self>,
            database_path: &QString,
            older_than_days: i32,
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
        #[cxx_name = "loadGroupChatState"]
        fn load_group_chat_state(
            self: Pin<&mut Self>,
            database_path: &QString,
            group_key: &QString,
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
            attachments_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "prepareGroupChatTurn"]
        fn prepare_group_chat_turn(
            self: Pin<&mut Self>,
            database_path: &QString,
            group_key: &QString,
            user_key: &QString,
            requested_conversation_id: &QString,
            new_conversation_id: &QString,
            content: &QString,
            attachments_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "importChatAttachments"]
        fn import_chat_attachments(
            self: Pin<&mut Self>,
            database_path: &QString,
            source_paths_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "discardChatAttachments"]
        fn discard_chat_attachments(
            self: Pin<&mut Self>,
            database_path: &QString,
            attachments_json: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "deleteChatConversation"]
        fn delete_chat_conversation(
            self: Pin<&mut Self>,
            database_path: &QString,
            character: &QString,
            user_key: &QString,
            conversation_id: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "deleteGroupChatConversation"]
        fn delete_group_chat_conversation(
            self: Pin<&mut Self>,
            database_path: &QString,
            group_key: &QString,
            user_key: &QString,
            conversation_id: &QString,
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
        #[cxx_name = "buildGroupPlanRequest"]
        fn build_group_plan_request(
            self: Pin<&mut Self>,
            database_path: &QString,
            members_json: &QString,
            priority_speaker: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "resolveGroupPlan"]
        fn resolve_group_plan(
            self: Pin<&mut Self>,
            members_json: &QString,
            priority_speaker: &QString,
            response: &QString,
        ) -> bool;

        #[qinvokable]
        #[cxx_name = "buildGroupChatRequest"]
        fn build_group_chat_request(
            self: Pin<&mut Self>,
            database_path: &QString,
            config_path: &QString,
            project_root: &QString,
            character: &QString,
            character_display_name: &QString,
            members_json: &QString,
            spoken_names_json: &QString,
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
        #[cxx_name = "saveGroupChatAssistant"]
        fn save_group_chat_assistant(
            self: Pin<&mut Self>,
            database_path: &QString,
            config_path: &QString,
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
            local_datetime: &QString,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "startGroupPlanStream"]
        fn start_group_plan_stream(
            self: Pin<&mut Self>,
            config_path: &QString,
            request_json: &QString,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "startGroupChatStream"]
        fn start_group_chat_stream(
            self: Pin<&mut Self>,
            config_path: &QString,
            request_json: &QString,
            local_datetime: &QString,
        ) -> i64;

        #[qinvokable]
        #[cxx_name = "finishGroupChatTurn"]
        fn finish_group_chat_turn(self: Pin<&mut Self>);

        #[qinvokable]
        #[cxx_name = "cancelChatStream"]
        fn cancel_chat_stream(self: Pin<&mut Self>, request_id: i64) -> bool;

        #[qsignal]
        #[cxx_name = "chatStreamEvent"]
        fn chat_stream_event(self: Pin<&mut Self>, payload_json: &QString);

        #[qsignal]
        #[cxx_name = "chatMemoryEvent"]
        fn chat_memory_event(self: Pin<&mut Self>, payload_json: &QString);

        #[qsignal]
        #[cxx_name = "providerOperationEvent"]
        fn provider_operation_event(self: Pin<&mut Self>, payload_json: &QString);

        #[qsignal]
        #[cxx_name = "ttsAudioEvent"]
        fn tts_audio_event(self: Pin<&mut Self>, payload_json: &QString, audio: &QByteArray);

        #[qsignal]
        #[cxx_name = "asrTranscriptionEvent"]
        fn asr_transcription_event(self: Pin<&mut Self>, payload_json: &QString);
    }

    impl cxx_qt::Threading for Backend {}
}

use bandori_asr::{AsrConfig, AsrTransport};
use bandori_core::asr_settings::{load_native_asr_settings, save_native_asr_settings};
use bandori_core::chat_actions::parse_chat_response;
use bandori_core::chat_attachments::{
    chat_attachment_stats, cleanup_chat_attachments as cleanup_native_chat_attachments,
    discard_imported_chat_attachments, import_chat_attachments as import_attachment_files,
};
use bandori_core::chat_context::build_native_chat_request;
use bandori_core::chat_dashboard::load_native_chat_snapshot;
use bandori_core::chat_management::{
    delete_owned_group_conversation, delete_owned_private_conversation,
};
use bandori_core::chat_tools::{
    NativeToolCallAccumulator, NativeToolExecutionContext, NativeToolResult,
    chat_tool_followup_messages, execute_native_tool_call_with_context, native_tool_trace,
};
use bandori_core::config::ConfigDocument;
use bandori_core::dashboard::{
    DashboardSnapshot, NativeRuntimeSnapshot, save_native_settings as persist_native_settings,
};
use bandori_core::data_management::{
    export_chat_database as export_native_chat_database,
    export_settings_package as export_native_settings_package,
    import_chat_database as import_native_chat_database,
    import_settings_package as import_native_settings_package,
};
use bandori_core::database::Database;
use bandori_core::group_chat::{
    GroupMember, apply_group_plan_priority, build_group_planner_request_from_database,
    build_native_group_chat_request, conversation_key_for, fallback_group_plan,
    group_assistant_content, load_native_group_chat_snapshot, parse_group_plan,
};
use bandori_core::history_dashboard::{load_native_history_filters, search_native_history};
use bandori_core::llm_settings::{
    load_native_llm_settings, mutate_native_llm_profiles, save_native_llm_settings,
};
use bandori_core::memory_dashboard::{load_native_memory_snapshot, mutate_native_memories};
use bandori_core::memory_extraction::{
    GLOBAL_MEMORY_CHARACTER, apply_model_relationship_analysis, apply_relationship_analysis,
    build_memory_extraction_messages, parse_memory_extraction, store_extracted_memories,
};
use bandori_core::persona_settings::{
    load_native_persona_settings, mutate_native_persona_settings,
};
use bandori_core::relationship_analysis::{
    InteractionAnalysis, analyze_interaction, apply_interaction_analysis,
};
use bandori_core::reminder::{
    LocalDateTime, load_native_reminder_state, mutate_native_reminders, tick_config_reminders,
};
use bandori_core::statistics_dashboard::load_native_statistics;
use bandori_core::tts_settings::{load_native_tts_settings, save_native_tts_settings};
use bandori_core::user_profiles::{load_native_user_profiles, mutate_native_user_profiles};
use bandori_llm::{
    LlmApiMode, LlmStreamEvent, LlmTransport, LlmTransportConfig, LlmTransportError,
    LlmTransportRequest, TokenUsage,
};
use bandori_tts::{TtsAudioChunk, TtsConfig, TtsRequest, TtsTransport, clean_tts_text};
use core::pin::Pin;
use cxx_qt::{CxxQtType, Threading};
use cxx_qt_lib::{QByteArray, QString};
use serde_json::{Value, json};
use std::collections::{HashMap, HashSet};
use std::path::Path;
use tokio_util::sync::CancellationToken;

const MAX_CHAT_REQUEST_BYTES: usize = 40 * 1024 * 1024;
const MAX_ATTACHMENT_JSON_BYTES: usize = 256 * 1024;
const MAX_GROUP_MEMBERS_JSON_BYTES: usize = 64 * 1024;
const MAX_REMINDER_COMMAND_BYTES: usize = 64 * 1024;
const MAX_LLM_SETTINGS_BYTES: usize = 256 * 1024;
const MAX_MEMORY_COMMAND_BYTES: usize = 128 * 1024;
const MAX_USER_PROFILE_COMMAND_BYTES: usize = 64 * 1024;
const MAX_PERSONA_COMMAND_BYTES: usize = 1024 * 1024;
const MAX_HISTORY_QUERY_BYTES: usize = 64 * 1024;
const MAX_STATISTICS_QUERY_BYTES: usize = 64 * 1024;
const MAX_SETTINGS_PACKAGE_BYTES: u64 = 64 * 1024 * 1024;
const MAX_NATIVE_TOOL_ROUNDS: usize = 3;

#[derive(Debug)]
struct NativeToolLoopOutcome {
    mode: LlmApiMode,
    response_id: String,
    usage: Option<TokenUsage>,
    tool_calls: Vec<NativeToolResult>,
}

#[derive(Debug)]
struct NativeToolLoopFailure {
    error: LlmTransportError,
    usage: Option<TokenUsage>,
    tool_calls: Vec<NativeToolResult>,
}

#[derive(Clone, Debug)]
struct NativeToolRuntimeContext {
    config_path: String,
    now: LocalDateTime,
    active_character: String,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
enum ActiveChatKind {
    #[default]
    None,
    Private,
    GroupPlan,
    GroupSpeaker,
}

#[derive(Clone, Debug, Default)]
struct GroupTurnContext {
    group_key: String,
    conversation_id: String,
    user_message_id: i64,
    user_key: String,
    user_content: String,
    members: Vec<GroupMember>,
    character: String,
    character_display_name: String,
}

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
    chat_imported_attachments_json: QString,
    reminder_events_json: QString,
    reminder_state_json: QString,
    llm_settings_json: QString,
    tts_settings_json: QString,
    asr_settings_json: QString,
    memory_snapshot_json: QString,
    user_profiles_json: QString,
    persona_settings_json: QString,
    history_filters_json: QString,
    history_result_json: QString,
    statistics_snapshot_json: QString,
    data_operation_json: QString,
    attachment_management_json: QString,
    chat_has_older_messages: bool,
    prepared_chat_conversation_id: i64,
    prepared_chat_user_message_id: i64,
    prepared_chat_character: String,
    prepared_chat_user_key: String,
    prepared_chat_user_content: String,
    active_chat_request_id: i64,
    active_chat_kind: ActiveChatKind,
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
    prepared_group_turn: Option<GroupTurnContext>,
    active_group_reply: Option<GroupTurnContext>,
    completed_group_reply: Option<(i64, GroupTurnContext)>,
    next_chat_request_id: i64,
    active_chat_cancellation: Option<CancellationToken>,
    next_provider_request_id: i64,
    active_provider_request_id: i64,
    provider_cancellation: Option<CancellationToken>,
    next_tts_request_id: i64,
    active_tts_request_id: i64,
    tts_cancellation: Option<CancellationToken>,
    next_asr_request_id: i64,
    active_asr_request_id: i64,
    asr_cancellation: Option<CancellationToken>,
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
            chat_imported_attachments_json: QString::from("{\"attachments\":[],\"errors\":[]}"),
            reminder_events_json: QString::from("[]"),
            reminder_state_json: QString::from(
                "{\"display_mode\":\"floating\",\"alarms\":[],\"pomodoros\":[]}",
            ),
            llm_settings_json: QString::from("{}"),
            tts_settings_json: QString::from("{}"),
            asr_settings_json: QString::from("{}"),
            memory_snapshot_json: QString::from("{}"),
            user_profiles_json: QString::from("{}"),
            persona_settings_json: QString::from("{}"),
            history_filters_json: QString::from("{}"),
            history_result_json: QString::from("{}"),
            statistics_snapshot_json: QString::from("{}"),
            data_operation_json: QString::from("{}"),
            attachment_management_json: QString::from("{}"),
            chat_has_older_messages: false,
            prepared_chat_conversation_id: 0,
            prepared_chat_user_message_id: 0,
            prepared_chat_character: String::new(),
            prepared_chat_user_key: String::new(),
            prepared_chat_user_content: String::new(),
            active_chat_request_id: 0,
            active_chat_kind: ActiveChatKind::None,
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
            prepared_group_turn: None,
            active_group_reply: None,
            completed_group_reply: None,
            next_chat_request_id: 1,
            active_chat_cancellation: None,
            next_provider_request_id: 1,
            active_provider_request_id: 0,
            provider_cancellation: None,
            next_tts_request_id: 1,
            active_tts_request_id: 0,
            tts_cancellation: None,
            next_asr_request_id: 1,
            active_asr_request_id: 0,
            asr_cancellation: None,
            memory_cancellations: HashMap::new(),
        }
    }
}

impl Drop for BackendRust {
    fn drop(&mut self) {
        if let Some(cancellation) = self.active_chat_cancellation.take() {
            cancellation.cancel();
        }
        if let Some(cancellation) = self.provider_cancellation.take() {
            cancellation.cancel();
        }
        if let Some(cancellation) = self.tts_cancellation.take() {
            cancellation.cancel();
        }
        if let Some(cancellation) = self.asr_cancellation.take() {
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

    pub fn tick_reminders(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        local_datetime: &QString,
    ) -> bool {
        let Some(now) = LocalDateTime::parse(&local_datetime.to_string()) else {
            self.as_mut()
                .set_status(QString::from("Reminder tick needs a valid local datetime"));
            self.as_mut().set_reminder_events_json(QString::from("[]"));
            return false;
        };
        match tick_config_reminders(Path::new(&config_path.to_string()), now) {
            Ok(events) => {
                let payload = serde_json::to_string(&events)
                    .expect("native reminder event serialization cannot fail");
                self.as_mut()
                    .set_reminder_events_json(QString::from(&payload));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Reminder tick error: {error}")));
                self.as_mut().set_reminder_events_json(QString::from("[]"));
                false
            }
        }
    }

    pub fn load_reminder_state(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        local_datetime: &QString,
    ) -> bool {
        let Some(now) = LocalDateTime::parse(&local_datetime.to_string()) else {
            self.as_mut().set_status(QString::from(
                "Loading reminders needs a valid local datetime",
            ));
            return false;
        };
        match load_native_reminder_state(Path::new(&config_path.to_string()), now) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native reminder state serialization cannot fail");
                self.as_mut()
                    .set_reminder_state_json(QString::from(&payload));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Reminder load error: {error}")));
                false
            }
        }
    }

    pub fn mutate_reminder(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        local_datetime: &QString,
        command_json: &QString,
    ) -> bool {
        let Some(now) = LocalDateTime::parse(&local_datetime.to_string()) else {
            self.as_mut().set_status(QString::from(
                "Changing reminders needs a valid local datetime",
            ));
            return false;
        };
        match mutate_native_reminders(
            Path::new(&config_path.to_string()),
            now,
            &command_json.to_string(),
            MAX_REMINDER_COMMAND_BYTES,
        ) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native reminder state serialization cannot fail");
                self.as_mut()
                    .set_reminder_state_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native reminders saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Reminder change error: {error}")));
                false
            }
        }
    }

    pub fn load_llm_settings(mut self: Pin<&mut Self>, config_path: &QString) -> bool {
        match load_native_llm_settings(Path::new(&config_path.to_string())) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native LLM settings serialization cannot fail");
                self.as_mut().set_llm_settings_json(QString::from(&payload));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("LLM settings load error: {error}")));
                false
            }
        }
    }

    pub fn save_llm_settings(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        settings_json: &QString,
    ) -> bool {
        match save_native_llm_settings(
            Path::new(&config_path.to_string()),
            &settings_json.to_string(),
            MAX_LLM_SETTINGS_BYTES,
        ) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native LLM settings serialization cannot fail");
                self.as_mut().set_llm_settings_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native LLM settings saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("LLM settings save error: {error}")));
                false
            }
        }
    }

    pub fn mutate_llm_profile(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        command_json: &QString,
    ) -> bool {
        match mutate_native_llm_profiles(
            Path::new(&config_path.to_string()),
            &command_json.to_string(),
            MAX_LLM_SETTINGS_BYTES,
        ) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native LLM profile state serialization cannot fail");
                self.as_mut().set_llm_settings_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native LLM profiles saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("LLM profile change error: {error}")));
                false
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn start_provider_operation(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        target: &QString,
        operation: &QString,
        api_url: &QString,
        api_key: &QString,
        model: &QString,
        api_mode: &QString,
    ) -> i64 {
        if self.as_ref().get_ref().rust().active_provider_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A provider operation is already running"));
            return 0;
        }
        let job = match prepare_provider_operation(
            Path::new(&config_path.to_string()),
            &target.to_string(),
            &operation.to_string(),
            &api_url.to_string(),
            &api_key.to_string(),
            &model.to_string(),
            &api_mode.to_string(),
        ) {
            Ok(job) => job,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let cancellation = CancellationToken::new();
        let request_id = {
            let state = self.as_mut().rust_mut().get_mut();
            let request_id = state.next_provider_request_id.max(1);
            state.next_provider_request_id = request_id.checked_add(1).unwrap_or(1);
            state.active_provider_request_id = request_id;
            state.provider_cancellation = Some(cancellation.clone());
            request_id
        };
        self.as_mut()
            .set_status(QString::from(match job.operation.as_str() {
                "fetch_models" => "Provider model discovery started",
                _ => "Provider connection test started",
            }));
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-provider-{request_id}"))
            .spawn(move || run_provider_operation(qt_thread, request_id, job, cancellation))
        {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_provider_request_id = 0;
            state.provider_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start provider operation: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn cancel_provider_operation(mut self: Pin<&mut Self>, request_id: i64) -> bool {
        let state = self.as_mut().rust_mut().get_mut();
        if state.active_provider_request_id == 0
            || (request_id > 0 && request_id != state.active_provider_request_id)
        {
            return false;
        }
        let Some(cancellation) = state.provider_cancellation.as_ref() else {
            return false;
        };
        cancellation.cancel();
        self.as_mut()
            .set_status(QString::from("Provider operation cancellation requested"));
        true
    }

    pub fn load_tts_settings(mut self: Pin<&mut Self>, config_path: &QString) -> bool {
        match load_native_tts_settings(Path::new(&config_path.to_string())) {
            Ok(settings) => {
                let payload = serde_json::to_string(&settings)
                    .expect("native TTS settings serialization cannot fail");
                self.as_mut().set_tts_settings_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native TTS settings loaded"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("TTS settings error: {error}")));
                false
            }
        }
    }

    pub fn save_tts_settings(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        settings_json: &QString,
    ) -> bool {
        match save_native_tts_settings(
            Path::new(&config_path.to_string()),
            &settings_json.to_string(),
        ) {
            Ok(settings) => {
                let payload = serde_json::to_string(&settings)
                    .expect("native TTS settings serialization cannot fail");
                self.as_mut().set_tts_settings_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native TTS settings saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("TTS settings save error: {error}")));
                false
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub fn start_tts_synthesis(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        project_root: &QString,
        text: &QString,
        character: &QString,
        speed_factor: f64,
        force: bool,
    ) -> i64 {
        if self.as_ref().get_ref().rust().active_tts_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A native TTS request is already running"));
            return 0;
        }
        let job = match prepare_tts_synthesis_job(
            Path::new(&config_path.to_string()),
            Path::new(&project_root.to_string()),
            &text.to_string(),
            &character.to_string(),
            speed_factor,
            force,
        ) {
            Ok(Some(job)) => job,
            Ok(None) => {
                self.as_mut()
                    .set_status(QString::from("Native TTS is disabled"));
                return 0;
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let cancellation = CancellationToken::new();
        let request_id = {
            let state = self.as_mut().rust_mut().get_mut();
            let request_id = state.next_tts_request_id.max(1);
            state.next_tts_request_id = request_id.saturating_add(1);
            state.active_tts_request_id = request_id;
            state.tts_cancellation = Some(cancellation.clone());
            request_id
        };
        self.as_mut()
            .set_status(QString::from("Native TTS synthesis started"));
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-tts-{request_id}"))
            .spawn(move || run_tts_synthesis(qt_thread, request_id, job, cancellation))
        {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_tts_request_id = 0;
            state.tts_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start native TTS synthesis: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn cancel_tts_synthesis(mut self: Pin<&mut Self>, request_id: i64) -> bool {
        let state = self.as_mut().rust_mut().get_mut();
        if state.active_tts_request_id == 0
            || (request_id > 0 && request_id != state.active_tts_request_id)
        {
            return false;
        }
        let Some(cancellation) = state.tts_cancellation.as_ref() else {
            return false;
        };
        cancellation.cancel();
        self.as_mut()
            .set_status(QString::from("Native TTS cancellation requested"));
        true
    }

    pub fn load_asr_settings(mut self: Pin<&mut Self>, config_path: &QString) -> bool {
        match load_native_asr_settings(Path::new(&config_path.to_string())) {
            Ok(settings) => {
                let payload = serde_json::to_string(&settings)
                    .expect("native ASR settings serialization cannot fail");
                self.as_mut().set_asr_settings_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native ASR settings loaded"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("ASR settings error: {error}")));
                false
            }
        }
    }

    pub fn save_asr_settings(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        settings_json: &QString,
    ) -> bool {
        match save_native_asr_settings(
            Path::new(&config_path.to_string()),
            &settings_json.to_string(),
        ) {
            Ok(settings) => {
                let payload = serde_json::to_string(&settings)
                    .expect("native ASR settings serialization cannot fail");
                self.as_mut().set_asr_settings_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native ASR settings saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("ASR settings save error: {error}")));
                false
            }
        }
    }

    pub fn start_asr_transcription(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        audio: &QByteArray,
        force: bool,
    ) -> i64 {
        if self.as_ref().get_ref().rust().active_asr_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A native ASR request is already running"));
            return 0;
        }
        let audio = Vec::<u8>::from(audio);
        let job = match prepare_asr_transcription_job(
            Path::new(&config_path.to_string()),
            audio,
            force,
        ) {
            Ok(Some(job)) => job,
            Ok(None) => {
                self.as_mut()
                    .set_status(QString::from("Native ASR is disabled"));
                return 0;
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let cancellation = CancellationToken::new();
        let request_id = {
            let state = self.as_mut().rust_mut().get_mut();
            let request_id = state.next_asr_request_id.max(1);
            state.next_asr_request_id = request_id.saturating_add(1);
            state.active_asr_request_id = request_id;
            state.asr_cancellation = Some(cancellation.clone());
            request_id
        };
        self.as_mut()
            .set_status(QString::from("Native ASR transcription started"));
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-asr-{request_id}"))
            .spawn(move || run_asr_transcription(qt_thread, request_id, job, cancellation))
        {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_asr_request_id = 0;
            state.asr_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start native ASR transcription: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn cancel_asr_transcription(mut self: Pin<&mut Self>, request_id: i64) -> bool {
        let state = self.as_mut().rust_mut().get_mut();
        if state.active_asr_request_id == 0
            || (request_id > 0 && request_id != state.active_asr_request_id)
        {
            return false;
        }
        let Some(cancellation) = state.asr_cancellation.as_ref() else {
            return false;
        };
        cancellation.cancel();
        self.as_mut()
            .set_status(QString::from("Native ASR cancellation requested"));
        true
    }

    pub fn load_memory_state(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        character: &QString,
        user_key: &QString,
    ) -> bool {
        match load_native_memory_snapshot(
            Path::new(&database_path.to_string()),
            &character.to_string(),
            &user_key.to_string(),
            100,
        ) {
            Ok(snapshot) => {
                let payload = serde_json::to_string(&snapshot)
                    .expect("native memory snapshot serialization cannot fail");
                self.as_mut()
                    .set_memory_snapshot_json(QString::from(&payload));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Memory load error: {error}")));
                false
            }
        }
    }

    pub fn mutate_memory(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        character: &QString,
        user_key: &QString,
        command_json: &QString,
    ) -> bool {
        match mutate_native_memories(
            Path::new(&database_path.to_string()),
            &character.to_string(),
            &user_key.to_string(),
            &command_json.to_string(),
            MAX_MEMORY_COMMAND_BYTES,
        ) {
            Ok(snapshot) => {
                let payload = serde_json::to_string(&snapshot)
                    .expect("native memory snapshot serialization cannot fail");
                self.as_mut()
                    .set_memory_snapshot_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native memory state saved"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Memory change error: {error}")));
                false
            }
        }
    }

    pub fn load_user_profiles(mut self: Pin<&mut Self>, config_path: &QString) -> bool {
        match load_native_user_profiles(Path::new(&config_path.to_string())) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native user profile serialization cannot fail");
                self.as_mut()
                    .set_user_profiles_json(QString::from(&payload));
                if let Ok(mut config) = ConfigDocument::load(Path::new(&config_path.to_string())) {
                    config.set("active_user_profile", json!(state.active_key));
                    let runtime = NativeRuntimeSnapshot::from_config(&config);
                    let runtime_json = serde_json::to_string(&runtime)
                        .expect("native runtime snapshot serialization cannot fail");
                    self.as_mut()
                        .set_runtime_config_json(QString::from(&runtime_json));
                }
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("User profile load error: {error}")));
                false
            }
        }
    }

    pub fn mutate_user_profile(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        command_json: &QString,
    ) -> bool {
        let config_path = config_path.to_string();
        match mutate_native_user_profiles(
            Path::new(&config_path),
            &command_json.to_string(),
            MAX_USER_PROFILE_COMMAND_BYTES,
        ) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native user profile serialization cannot fail");
                self.as_mut()
                    .set_user_profiles_json(QString::from(&payload));
                match ConfigDocument::load(Path::new(&config_path)) {
                    Ok(config) => {
                        let runtime = NativeRuntimeSnapshot::from_config(&config);
                        let runtime_json = serde_json::to_string(&runtime)
                            .expect("native runtime snapshot serialization cannot fail");
                        self.as_mut()
                            .set_runtime_config_json(QString::from(&runtime_json));
                    }
                    Err(error) => {
                        self.as_mut().set_status(QString::from(&format!(
                            "User profile saved but runtime reload failed: {error}"
                        )));
                        return false;
                    }
                }
                self.as_mut()
                    .set_status(QString::from("Native user profile saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "User profile change error: {error}"
                )));
                false
            }
        }
    }

    pub fn load_persona_settings(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        project_root: &QString,
        characters_json: &QString,
    ) -> bool {
        let characters = match serde_json::from_str::<Vec<String>>(&characters_json.to_string()) {
            Ok(characters) => characters,
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Persona character list error: {error}"
                )));
                return false;
            }
        };
        match load_native_persona_settings(
            Path::new(&config_path.to_string()),
            Path::new(&project_root.to_string()),
            &characters,
        ) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native persona settings serialization cannot fail");
                self.as_mut()
                    .set_persona_settings_json(QString::from(&payload));
                if let Ok(config) = ConfigDocument::load(Path::new(&config_path.to_string())) {
                    let runtime = NativeRuntimeSnapshot::from_config(&config);
                    let runtime_json = serde_json::to_string(&runtime)
                        .expect("native runtime snapshot serialization cannot fail");
                    self.as_mut()
                        .set_runtime_config_json(QString::from(&runtime_json));
                }
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Persona settings load error: {error}"
                )));
                false
            }
        }
    }

    pub fn mutate_persona_settings(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        project_root: &QString,
        characters_json: &QString,
        command_json: &QString,
    ) -> bool {
        let characters = match serde_json::from_str::<Vec<String>>(&characters_json.to_string()) {
            Ok(characters) => characters,
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Persona character list error: {error}"
                )));
                return false;
            }
        };
        match mutate_native_persona_settings(
            Path::new(&config_path.to_string()),
            Path::new(&project_root.to_string()),
            &characters,
            &command_json.to_string(),
            MAX_PERSONA_COMMAND_BYTES,
        ) {
            Ok(state) => {
                let payload = serde_json::to_string(&state)
                    .expect("native persona settings serialization cannot fail");
                self.as_mut()
                    .set_persona_settings_json(QString::from(&payload));
                match ConfigDocument::load(Path::new(&config_path.to_string())) {
                    Ok(config) => {
                        let runtime = NativeRuntimeSnapshot::from_config(&config);
                        let runtime_json = serde_json::to_string(&runtime)
                            .expect("native runtime snapshot serialization cannot fail");
                        self.as_mut()
                            .set_runtime_config_json(QString::from(&runtime_json));
                    }
                    Err(error) => {
                        self.as_mut().set_status(QString::from(&format!(
                            "Persona settings saved but runtime reload failed: {error}"
                        )));
                        return false;
                    }
                }
                self.as_mut()
                    .set_status(QString::from("Native persona settings saved atomically"));
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Persona settings change error: {error}"
                )));
                false
            }
        }
    }

    pub fn load_history_filters(mut self: Pin<&mut Self>, database_path: &QString) -> bool {
        match load_native_history_filters(Path::new(&database_path.to_string())) {
            Ok(filters) => {
                let payload = serde_json::to_string(&filters)
                    .expect("native history filters serialization cannot fail");
                self.as_mut()
                    .set_history_filters_json(QString::from(&payload));
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "History filters load error: {error}"
                )));
                false
            }
        }
    }

    pub fn search_history(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        query_json: &QString,
    ) -> bool {
        match search_native_history(
            Path::new(&database_path.to_string()),
            &query_json.to_string(),
            MAX_HISTORY_QUERY_BYTES,
        ) {
            Ok(result) => {
                let payload = serde_json::to_string(&result)
                    .expect("native history result serialization cannot fail");
                self.as_mut()
                    .set_history_result_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native history query completed"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("History query error: {error}")));
                false
            }
        }
    }

    pub fn load_statistics(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        query_json: &QString,
    ) -> bool {
        match load_native_statistics(
            Path::new(&database_path.to_string()),
            &query_json.to_string(),
            MAX_STATISTICS_QUERY_BYTES,
        ) {
            Ok(snapshot) => {
                let payload = serde_json::to_string(&snapshot)
                    .expect("native statistics snapshot serialization cannot fail");
                self.as_mut()
                    .set_statistics_snapshot_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native statistics refreshed"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Statistics load error: {error}")));
                false
            }
        }
    }

    pub fn export_settings_package(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        database_path: &QString,
        category: &QString,
        destination_path: &QString,
    ) -> bool {
        match export_native_settings_package(
            Path::new(&config_path.to_string()),
            Path::new(&database_path.to_string()),
            &category.to_string(),
            Path::new(&destination_path.to_string()),
        ) {
            Ok(summary) => {
                let payload = serde_json::to_string(&summary)
                    .expect("native data export summary serialization cannot fail");
                self.as_mut()
                    .set_data_operation_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native settings package exported"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Settings export error: {error}")));
                false
            }
        }
    }

    pub fn import_settings_package(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        database_path: &QString,
        category: &QString,
        source_path: &QString,
    ) -> bool {
        match import_native_settings_package(
            Path::new(&config_path.to_string()),
            Path::new(&database_path.to_string()),
            &category.to_string(),
            Path::new(&source_path.to_string()),
            MAX_SETTINGS_PACKAGE_BYTES,
        ) {
            Ok(summary) => {
                let payload = serde_json::to_string(&summary)
                    .expect("native data import summary serialization cannot fail");
                self.as_mut()
                    .set_data_operation_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native settings package imported"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Settings import error: {error}")));
                false
            }
        }
    }

    pub fn export_chat_database(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        destination_path: &QString,
    ) -> bool {
        match export_native_chat_database(
            Path::new(&database_path.to_string()),
            Path::new(&destination_path.to_string()),
        ) {
            Ok(summary) => {
                let payload = serde_json::to_string(&summary)
                    .expect("native database export summary serialization cannot fail");
                self.as_mut()
                    .set_data_operation_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native chat database backup exported"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Database export error: {error}")));
                false
            }
        }
    }

    pub fn import_chat_database(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        source_path: &QString,
    ) -> bool {
        match import_native_chat_database(
            Path::new(&database_path.to_string()),
            Path::new(&source_path.to_string()),
        ) {
            Ok(summary) => {
                let payload = serde_json::to_string(&summary)
                    .expect("native database import summary serialization cannot fail");
                self.as_mut()
                    .set_data_operation_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native chat database restored"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Database restore error: {error}")));
                false
            }
        }
    }

    pub fn load_attachment_stats(mut self: Pin<&mut Self>, database_path: &QString) -> bool {
        let stats = chat_attachment_stats(Path::new(&database_path.to_string()));
        let payload = serde_json::to_string(&stats)
            .expect("native attachment statistics serialization cannot fail");
        self.as_mut()
            .set_attachment_management_json(QString::from(&payload));
        true
    }

    pub fn cleanup_chat_attachments(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        older_than_days: i32,
    ) -> bool {
        let retention = (older_than_days > 0).then_some(i64::from(older_than_days));
        match cleanup_native_chat_attachments(Path::new(&database_path.to_string()), retention) {
            Ok(result) => {
                let payload = serde_json::to_string(&result)
                    .expect("native attachment cleanup serialization cannot fail");
                self.as_mut()
                    .set_attachment_management_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native chat attachment cleanup completed"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Attachment cleanup error: {error}")));
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

    pub fn load_group_chat_state(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        group_key: &QString,
        user_key: &QString,
        requested_conversation_id: &QString,
        message_limit: i32,
    ) -> bool {
        match load_native_group_chat_snapshot(
            Path::new(&database_path.to_string()),
            &group_key.to_string(),
            &user_key.to_string(),
            Some(&requested_conversation_id.to_string()),
            i64::from(message_limit),
        ) {
            Ok(snapshot) => {
                let conversations_json = serde_json::to_string(&snapshot.conversations)
                    .expect("group conversation serialization cannot fail");
                let messages_json = serde_json::to_string(&snapshot.messages)
                    .expect("group message serialization cannot fail");
                let snapshot_json = serde_json::to_string(&snapshot)
                    .expect("group chat snapshot serialization cannot fail");
                self.as_mut()
                    .set_chat_conversations_json(QString::from(&conversations_json));
                self.as_mut()
                    .set_chat_messages_json(QString::from(&messages_json));
                self.as_mut().set_chat_active_conversation_id(QString::from(
                    &snapshot.active_conversation_id,
                ));
                self.as_mut()
                    .set_chat_has_older_messages(snapshot.has_older_messages);
                self.as_mut()
                    .set_chat_turn_json(QString::from(&snapshot_json));
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Group chat database error: {error}"
                )));
                self.as_mut()
                    .set_chat_conversations_json(QString::from("[]"));
                self.as_mut().set_chat_messages_json(QString::from("[]"));
                self.as_mut()
                    .set_chat_active_conversation_id(QString::default());
                self.as_mut().set_chat_has_older_messages(false);
                self.as_mut().set_chat_turn_json(QString::from("{}"));
                false
            }
        }
    }

    pub fn import_chat_attachments(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        source_paths_json: &QString,
    ) -> bool {
        let source = source_paths_json.to_string();
        if source.len() > MAX_ATTACHMENT_JSON_BYTES {
            self.as_mut()
                .set_status(QString::from("Attachment selection is too large"));
            return false;
        }
        let paths = match serde_json::from_str::<Vec<String>>(&source) {
            Ok(paths) => paths,
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Attachment selection error: {error}"
                )));
                return false;
            }
        };
        match import_attachment_files(Path::new(&database_path.to_string()), &paths) {
            Ok(result) => {
                let success = !result.attachments.is_empty();
                let count = result.attachments.len();
                let errors = result.errors.len();
                let payload = serde_json::to_string(&result)
                    .expect("attachment import result serialization cannot fail");
                self.as_mut()
                    .set_chat_imported_attachments_json(QString::from(&payload));
                self.as_mut().set_status(QString::from(&format!(
                    "Imported {count} attachment(s); {errors} rejected"
                )));
                success
            }
            Err(error) => {
                self.as_mut()
                    .set_chat_imported_attachments_json(QString::from(
                        "{\"attachments\":[],\"errors\":[]}",
                    ));
                self.as_mut()
                    .set_status(QString::from(&format!("Attachment import error: {error}")));
                false
            }
        }
    }

    pub fn discard_chat_attachments(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        attachments_json: &QString,
    ) -> bool {
        let source = attachments_json.to_string();
        if source.len() > MAX_ATTACHMENT_JSON_BYTES {
            self.as_mut()
                .set_status(QString::from("Attachment list is too large"));
            return false;
        }
        let attachments = match serde_json::from_str::<Value>(&source) {
            Ok(attachments) => attachments,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Attachment list error: {error}")));
                return false;
            }
        };
        match discard_imported_chat_attachments(Path::new(&database_path.to_string()), &attachments)
        {
            Ok(removed) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Discarded {removed} pending attachment(s)"
                )));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Attachment cleanup error: {error}")));
                false
            }
        }
    }

    pub fn delete_chat_conversation(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        character: &QString,
        user_key: &QString,
        conversation_id: &QString,
    ) -> bool {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut().set_status(QString::from(
                "Cannot delete a conversation while chat is active",
            ));
            return false;
        }
        let conversation_id = match conversation_id.to_string().trim().parse::<i64>() {
            Ok(value) if value > 0 => value,
            _ => {
                self.as_mut()
                    .set_status(QString::from("No saved conversation is selected"));
                return false;
            }
        };
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match delete_owned_private_conversation(
            &database,
            &character.to_string(),
            &user_key.to_string(),
            conversation_id,
        ) {
            Ok(result) if result.deleted => {
                let payload = serde_json::to_string(&result)
                    .expect("conversation delete result serialization cannot fail");
                self.as_mut().set_chat_turn_json(QString::from(&payload));
                self.as_mut().set_status(QString::from(&format!(
                    "Conversation deleted; {} attachment copy/copies removed",
                    result.attachments_removed
                )));
                true
            }
            Ok(_) => {
                self.as_mut()
                    .set_status(QString::from("Conversation was already unavailable"));
                false
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Conversation delete error: {error}"
                )));
                false
            }
        }
    }

    pub fn delete_group_chat_conversation(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        group_key: &QString,
        user_key: &QString,
        conversation_id: &QString,
    ) -> bool {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut().set_status(QString::from(
                "Cannot delete a conversation while chat is active",
            ));
            return false;
        }
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match delete_owned_group_conversation(
            &database,
            &group_key.to_string(),
            &user_key.to_string(),
            &conversation_id.to_string(),
        ) {
            Ok(result) if result.deleted => {
                let payload = serde_json::to_string(&result)
                    .expect("group conversation delete serialization cannot fail");
                self.as_mut().set_chat_turn_json(QString::from(&payload));
                self.as_mut().set_status(QString::from(&format!(
                    "Group conversation deleted; {} attachment copy/copies removed",
                    result.attachments_removed
                )));
                true
            }
            Ok(_) => {
                self.as_mut()
                    .set_status(QString::from("Group conversation was already unavailable"));
                false
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Group conversation delete error: {error}"
                )));
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
        attachments_json: &QString,
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
        let attachments_source = attachments_json.to_string();
        if attachments_source.len() > MAX_ATTACHMENT_JSON_BYTES {
            self.as_mut()
                .set_status(QString::from("Chat attachment list is too large"));
            return false;
        }
        let attachments = match serde_json::from_str::<Value>(&attachments_source) {
            Ok(Value::Array(items)) => Value::Array(items),
            Ok(_) => {
                self.as_mut()
                    .set_status(QString::from("Chat attachments must be a JSON array"));
                return false;
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat attachment error: {error}")));
                return false;
            }
        };
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
            Some(&attachments),
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
                state.prepared_group_turn = None;
                state.active_group_reply = None;
                state.completed_group_reply = None;
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

    pub fn prepare_group_chat_turn(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        group_key: &QString,
        user_key: &QString,
        requested_conversation_id: &QString,
        new_conversation_id: &QString,
        content: &QString,
        attachments_json: &QString,
    ) -> bool {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A native LLM request is already running"));
            return false;
        }
        let attachments = match parse_attachments_json(&attachments_json.to_string()) {
            Ok(attachments) => attachments,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return false;
            }
        };
        let requested = requested_conversation_id.to_string();
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match database.begin_group_chat_turn(
            &group_key.to_string(),
            &user_key.to_string(),
            Some(&requested),
            &new_conversation_id.to_string(),
            &content.to_string(),
            Some(&attachments),
        ) {
            Ok(turn) => {
                let payload = serde_json::to_string(&turn)
                    .expect("group chat turn serialization cannot fail");
                let state = self.as_mut().rust_mut().get_mut();
                state.prepared_chat_conversation_id = 0;
                state.prepared_chat_user_message_id = 0;
                state.prepared_chat_character.clear();
                state.prepared_chat_user_key.clear();
                state.prepared_chat_user_content.clear();
                state.completed_chat_request_id = 0;
                state.completed_chat_conversation_id = 0;
                state.completed_chat_user_message_id = 0;
                state.completed_chat_character.clear();
                state.completed_chat_user_key.clear();
                state.completed_chat_user_content.clear();
                state.prepared_group_turn = Some(GroupTurnContext {
                    group_key: turn.group_key.clone(),
                    conversation_id: turn.conversation_id.clone(),
                    user_message_id: turn.user_message_id,
                    user_key: user_key.to_string(),
                    user_content: content.to_string().trim().to_owned(),
                    ..GroupTurnContext::default()
                });
                state.active_group_reply = None;
                state.completed_group_reply = None;
                self.as_mut()
                    .set_chat_active_conversation_id(QString::from(&turn.conversation_id));
                self.as_mut().set_chat_turn_json(QString::from(&payload));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                self.as_mut()
                    .set_status(QString::from("Native group chat turn saved"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Group chat turn error: {error}")));
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

    pub fn build_group_plan_request(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        members_json: &QString,
        priority_speaker: &QString,
    ) -> bool {
        let context = match self.as_ref().get_ref().rust().prepared_group_turn.clone() {
            Some(context) => context,
            None => {
                self.as_mut().set_status(QString::from(
                    "Prepare a native group turn before planning speakers",
                ));
                return false;
            }
        };
        let members = match parse_group_members(&members_json.to_string()) {
            Ok(members) if group_members_match_key(&members, &context.group_key) => members,
            Ok(_) => {
                self.as_mut()
                    .set_status(QString::from("Group members do not match the active group"));
                return false;
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return false;
            }
        };
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match build_group_planner_request_from_database(
            &database,
            &context.group_key,
            &context.conversation_id,
            &context.user_key,
            &members,
            &context.user_content,
            &priority_speaker.to_string(),
        ) {
            Ok(request) => {
                let payload = serde_json::to_string(&request)
                    .expect("group planner request serialization cannot fail");
                if let Some(prepared) = self
                    .as_mut()
                    .rust_mut()
                    .get_mut()
                    .prepared_group_turn
                    .as_mut()
                {
                    prepared.members = members;
                }
                self.as_mut().set_chat_request_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native group speaker plan ready"));
                true
            }
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Group speaker plan error: {error}")));
                false
            }
        }
    }

    pub fn resolve_group_plan(
        mut self: Pin<&mut Self>,
        members_json: &QString,
        priority_speaker: &QString,
        response: &QString,
    ) -> bool {
        let members = match parse_group_members(&members_json.to_string()) {
            Ok(members) => members,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return false;
            }
        };
        let priority = priority_speaker.to_string();
        let parsed = parse_group_plan(&response.to_string(), &members);
        let used_fallback = parsed.is_empty();
        let speakers = if used_fallback {
            fallback_group_plan(&members, &priority)
        } else {
            apply_group_plan_priority(&parsed, &priority, &members)
        };
        let payload = json!({
            "speakers": speakers,
            "used_fallback": used_fallback,
        })
        .to_string();
        self.as_mut().set_chat_turn_json(QString::from(&payload));
        self.as_mut().set_status(QString::from(if used_fallback {
            "Native group speaker fallback plan ready"
        } else {
            "Native group speaker plan accepted"
        }));
        true
    }

    #[allow(clippy::too_many_arguments)]
    pub fn build_group_chat_request(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        config_path: &QString,
        project_root: &QString,
        character: &QString,
        character_display_name: &QString,
        members_json: &QString,
        spoken_names_json: &QString,
        current_time_instruction: &QString,
    ) -> bool {
        let mut context = match self.as_ref().get_ref().rust().prepared_group_turn.clone() {
            Some(context) => context,
            None => {
                self.as_mut().set_status(QString::from(
                    "Prepare a native group turn before building a reply",
                ));
                return false;
            }
        };
        let members = match parse_group_members(&members_json.to_string()) {
            Ok(members) if group_members_match_key(&members, &context.group_key) => members,
            Ok(_) => {
                self.as_mut()
                    .set_status(QString::from("Group members do not match the active group"));
                return false;
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return false;
            }
        };
        let character = character.to_string();
        let character_display_name = character_display_name.to_string();
        if !members
            .iter()
            .any(|member| member.key == character && member.name == character_display_name)
        {
            self.as_mut().set_status(QString::from(
                "Group reply character does not match the selected members",
            ));
            return false;
        }
        let spoken_names = match parse_string_array(
            &spoken_names_json.to_string(),
            MAX_GROUP_MEMBERS_JSON_BYTES,
            "Group spoken-name list",
        ) {
            Ok(values) => values,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return false;
            }
        };
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        let config = match ConfigDocument::load(Path::new(&config_path.to_string())) {
            Ok(config) => config,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat config error: {error}")));
                return false;
            }
        };
        match build_native_group_chat_request(
            &database,
            &config,
            Path::new(&project_root.to_string()),
            &character,
            &character_display_name,
            &context.user_key,
            &context.group_key,
            &context.conversation_id,
            &members,
            &spoken_names,
            &current_time_instruction.to_string(),
        ) {
            Ok(request) => {
                let payload = serde_json::to_string(&request)
                    .expect("native group chat request serialization cannot fail");
                context.members = members;
                context.character = character;
                context.character_display_name = character_display_name;
                self.as_mut().rust_mut().get_mut().prepared_group_turn = Some(context);
                self.as_mut().set_chat_request_json(QString::from(&payload));
                self.as_mut()
                    .set_status(QString::from("Native group reply request ready"));
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Group reply request error: {error}"
                )));
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
                        Some(user_message_id),
                        None,
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

    pub fn save_group_chat_assistant(
        mut self: Pin<&mut Self>,
        database_path: &QString,
        config_path: &QString,
        request_id: i64,
        content: &QString,
        reasoning: &QString,
        outcome_json: &QString,
    ) -> bool {
        let context = match self
            .as_ref()
            .get_ref()
            .rust()
            .completed_group_reply
            .as_ref()
        {
            Some((completed_request_id, context))
                if request_id > 0 && *completed_request_id == request_id =>
            {
                context.clone()
            }
            _ => {
                self.as_mut().set_status(QString::from(
                    "Native group completion is stale or unavailable",
                ));
                return false;
            }
        };
        let response = parse_chat_response(&content.to_string(), &reasoning.to_string());
        if response.content.is_empty()
            && response.reasoning.is_empty()
            && response.actions.is_empty()
        {
            self.as_mut()
                .set_status(QString::from("Native group assistant response is empty"));
            return false;
        }
        let stored_content = match group_assistant_content(
            &context.character,
            &context.members,
            &response.content,
        ) {
            Ok(content) => content,
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Group assistant response error: {error}"
                )));
                return false;
            }
        };
        let trace = assistant_tool_trace(&outcome_json.to_string());
        let database = match Database::open(Path::new(&database_path.to_string())) {
            Ok(database) => database,
            Err(error) => {
                self.as_mut()
                    .set_status(QString::from(&format!("Chat database error: {error}")));
                return false;
            }
        };
        match database.add_group_message(
            &context.group_key,
            &context.conversation_id,
            "assistant",
            &stored_content,
            &response.reasoning,
            None,
            trace.as_ref(),
            &context.user_key,
        ) {
            Ok(message_id) => {
                let fallback = (!context.character.is_empty() && !context.user_content.is_empty())
                    .then(|| analyze_interaction(&context.user_content, &response.actions));
                let memory_job = fallback.as_ref().map(|fallback| {
                    prepare_memory_extraction_job(
                        &database,
                        Path::new(&config_path.to_string()),
                        &database_path.to_string(),
                        &context.character,
                        &context.character_display_name,
                        &context.user_key,
                        &context.user_content,
                        &response.content,
                        None,
                        Some(context.user_message_id),
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
                            .name(format!("bandori-group-memory-{request_id}"))
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
                                &context.character,
                                &context.user_key,
                                &context.user_content,
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
                                &context.character,
                                &context.user_key,
                                &context.user_content,
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
                            &context.character,
                            &context.user_key,
                            &context.user_content,
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
                    "group_key": context.group_key,
                    "conversation_id": context.conversation_id,
                    "user_message_id": context.user_message_id,
                    "assistant_message_id": message_id,
                    "request_id": request_id,
                    "character": context.character,
                    "character_display_name": context.character_display_name,
                    "content": response.content,
                    "stored_content": stored_content,
                    "reasoning": response.reasoning,
                    "actions": response.actions,
                    "relationship_state": relationship_state,
                    "relationship_error": relationship_error,
                    "relationship_pending": relationship_pending,
                })
                .to_string();
                self.as_mut().rust_mut().get_mut().completed_group_reply = None;
                self.as_mut().set_chat_turn_json(QString::from(&payload));
                self.as_mut().set_chat_request_json(QString::from("{}"));
                self.as_mut()
                    .set_status(QString::from(if relationship_pending {
                        "Native group response saved; memory analysis is running"
                    } else if relationship_updated {
                        "Native group response and relationship state saved"
                    } else {
                        "Native group response saved; relationship update was unavailable"
                    }));
                true
            }
            Err(error) => {
                self.as_mut().set_status(QString::from(&format!(
                    "Group assistant save error: {error}"
                )));
                false
            }
        }
    }

    pub fn start_chat_stream(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        request_json: &QString,
        local_datetime: &QString,
    ) -> i64 {
        let config_path = config_path.to_string();
        let config = match load_llm_transport_config(Path::new(&config_path)) {
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
        let Some(tool_now) = LocalDateTime::parse(&local_datetime.to_string()) else {
            self.as_mut()
                .set_status(QString::from("Native chat needs a valid local datetime"));
            return 0;
        };

        let request_id;
        let request_conversation_id;
        let active_character;
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
            state.active_chat_kind = ActiveChatKind::Private;
            state.active_chat_request_conversation_id = request_conversation_id;
            state.active_chat_user_message_id = state.prepared_chat_user_message_id;
            state.prepared_chat_user_message_id = 0;
            state.active_chat_character = std::mem::take(&mut state.prepared_chat_character);
            active_character = state.active_chat_character.clone();
            state.active_chat_user_key = std::mem::take(&mut state.prepared_chat_user_key);
            state.active_chat_user_content = std::mem::take(&mut state.prepared_chat_user_content);
            state.completed_chat_request_id = 0;
            state.completed_chat_conversation_id = 0;
            state.completed_chat_user_message_id = 0;
            state.completed_chat_character.clear();
            state.completed_chat_user_key.clear();
            state.completed_chat_user_content.clear();
            state.completed_group_reply = None;
            state.active_chat_cancellation = Some(cancellation.clone());
        }
        self.as_mut()
            .set_status(QString::from("Native LLM request started"));
        let tool_context = NativeToolRuntimeContext {
            config_path,
            now: tool_now,
            active_character,
        };
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-llm-{request_id}"))
            .spawn(move || {
                run_llm_stream(
                    qt_thread,
                    request_id,
                    config,
                    request,
                    cancellation,
                    Some(tool_context),
                );
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
            state.active_chat_kind = ActiveChatKind::None;
            state.active_chat_request_conversation_id = 0;
            state.active_chat_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start native LLM worker: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn start_group_plan_stream(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        request_json: &QString,
    ) -> i64 {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A native LLM request is already running"));
            return 0;
        }
        let has_prepared_group = self
            .as_ref()
            .get_ref()
            .rust()
            .prepared_group_turn
            .as_ref()
            .is_some_and(|context| context.members.len() >= 2);
        if !has_prepared_group {
            self.as_mut().set_status(QString::from(
                "Prepare and build a native group plan before starting its stream",
            ));
            return 0;
        }
        let config = match load_group_planner_transport_config(Path::new(&config_path.to_string()))
        {
            Ok(config) => config,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let request = match parse_llm_request(&request_json.to_string()) {
            Ok(request) => request,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let cancellation = CancellationToken::new();
        let request_id = {
            let state = self.as_mut().rust_mut().get_mut();
            let request_id = state.next_chat_request_id.max(1);
            state.next_chat_request_id = request_id.checked_add(1).unwrap_or(1);
            state.active_chat_request_id = request_id;
            state.active_chat_kind = ActiveChatKind::GroupPlan;
            state.active_group_reply = None;
            state.completed_group_reply = None;
            state.active_chat_cancellation = Some(cancellation.clone());
            request_id
        };
        self.as_mut()
            .set_status(QString::from("Native group planner request started"));
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-group-plan-{request_id}"))
            .spawn(move || {
                run_llm_stream(qt_thread, request_id, config, request, cancellation, None);
            })
        {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_chat_request_id = 0;
            state.active_chat_kind = ActiveChatKind::None;
            state.active_chat_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start native group planner: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn start_group_chat_stream(
        mut self: Pin<&mut Self>,
        config_path: &QString,
        request_json: &QString,
        local_datetime: &QString,
    ) -> i64 {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut()
                .set_status(QString::from("A native LLM request is already running"));
            return 0;
        }
        let context = match self.as_ref().get_ref().rust().prepared_group_turn.clone() {
            Some(context)
                if !context.character.is_empty()
                    && context
                        .members
                        .iter()
                        .any(|member| member.key == context.character) =>
            {
                context
            }
            _ => {
                self.as_mut().set_status(QString::from(
                    "Build a native group reply before starting its stream",
                ));
                return 0;
            }
        };
        let config_path = config_path.to_string();
        let config = match load_llm_transport_config(Path::new(&config_path)) {
            Ok(config) => config,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let request = match parse_llm_request(&request_json.to_string()) {
            Ok(request) => request,
            Err(error) => {
                self.as_mut().set_status(QString::from(&error));
                return 0;
            }
        };
        let Some(tool_now) = LocalDateTime::parse(&local_datetime.to_string()) else {
            self.as_mut().set_status(QString::from(
                "Native group chat needs a valid local datetime",
            ));
            return 0;
        };
        let tool_context = NativeToolRuntimeContext {
            config_path,
            now: tool_now,
            active_character: context.character.clone(),
        };
        let cancellation = CancellationToken::new();
        let request_id = {
            let state = self.as_mut().rust_mut().get_mut();
            let request_id = state.next_chat_request_id.max(1);
            state.next_chat_request_id = request_id.checked_add(1).unwrap_or(1);
            state.active_chat_request_id = request_id;
            state.active_chat_kind = ActiveChatKind::GroupSpeaker;
            state.active_group_reply = Some(context);
            state.completed_group_reply = None;
            state.active_chat_cancellation = Some(cancellation.clone());
            request_id
        };
        self.as_mut()
            .set_status(QString::from("Native group reply request started"));
        let qt_thread = self.qt_thread();
        if let Err(error) = std::thread::Builder::new()
            .name(format!("bandori-group-reply-{request_id}"))
            .spawn(move || {
                run_llm_stream(
                    qt_thread,
                    request_id,
                    config,
                    request,
                    cancellation,
                    Some(tool_context),
                );
            })
        {
            let state = self.as_mut().rust_mut().get_mut();
            state.active_chat_request_id = 0;
            state.active_chat_kind = ActiveChatKind::None;
            state.active_group_reply = None;
            state.active_chat_cancellation = None;
            self.as_mut().set_status(QString::from(&format!(
                "Could not start native group reply: {error}"
            )));
            return 0;
        }
        request_id
    }

    pub fn finish_group_chat_turn(mut self: Pin<&mut Self>) {
        if self.as_ref().get_ref().rust().active_chat_request_id != 0 {
            self.as_mut().set_status(QString::from(
                "Cannot finish a group turn while a request is active",
            ));
            return;
        }
        let state = self.as_mut().rust_mut().get_mut();
        state.prepared_group_turn = None;
        state.active_group_reply = None;
        state.completed_group_reply = None;
        self.as_mut()
            .set_status(QString::from("Native group chat turn finished"));
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
            match state.active_chat_kind {
                ActiveChatKind::Private
                    if finished && state.active_chat_request_conversation_id > 0 =>
                {
                    state.completed_chat_request_id = request_id;
                    state.completed_chat_conversation_id =
                        state.active_chat_request_conversation_id;
                    state.completed_chat_user_message_id = state.active_chat_user_message_id;
                    state.completed_chat_character =
                        std::mem::take(&mut state.active_chat_character);
                    state.completed_chat_user_key = std::mem::take(&mut state.active_chat_user_key);
                    state.completed_chat_user_content =
                        std::mem::take(&mut state.active_chat_user_content);
                }
                ActiveChatKind::GroupSpeaker if finished => {
                    state.completed_group_reply = state
                        .active_group_reply
                        .take()
                        .map(|context| (request_id, context));
                }
                _ => {
                    state.completed_chat_request_id = 0;
                    state.completed_chat_conversation_id = 0;
                    state.completed_chat_user_message_id = 0;
                    state.completed_chat_character.clear();
                    state.completed_chat_user_key.clear();
                    state.completed_chat_user_content.clear();
                    state.completed_group_reply = None;
                }
            }
            state.active_chat_request_id = 0;
            state.active_chat_kind = ActiveChatKind::None;
            state.active_chat_request_conversation_id = 0;
            state.active_chat_user_message_id = 0;
            state.active_chat_character.clear();
            state.active_chat_user_key.clear();
            state.active_chat_user_content.clear();
            state.active_group_reply = None;
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

    fn emit_provider_operation_payload(mut self: Pin<&mut Self>, request_id: i64, payload: String) {
        if self.as_ref().get_ref().rust().active_provider_request_id != request_id {
            return;
        }
        let state = self.as_mut().rust_mut().get_mut();
        state.active_provider_request_id = 0;
        state.provider_cancellation = None;
        let status = serde_json::from_str::<Value>(&payload)
            .ok()
            .and_then(|value| {
                let state = value.get("state").and_then(Value::as_str)?;
                Some(if state == "finished" {
                    "Provider operation completed".to_owned()
                } else {
                    value
                        .get("message")
                        .and_then(Value::as_str)
                        .unwrap_or("Provider operation failed")
                        .to_owned()
                })
            })
            .unwrap_or_else(|| "Provider operation failed".to_owned());
        self.as_mut().set_status(QString::from(&status));
        self.as_mut()
            .provider_operation_event(&QString::from(payload.as_str()));
    }

    fn emit_tts_audio_payload(
        mut self: Pin<&mut Self>,
        request_id: i64,
        payload: String,
        audio: Vec<u8>,
        terminal: bool,
    ) {
        if self.as_ref().get_ref().rust().active_tts_request_id != request_id {
            return;
        }
        if terminal {
            let status = serde_json::from_str::<Value>(&payload)
                .ok()
                .and_then(|value| {
                    value
                        .get("state")
                        .and_then(Value::as_str)
                        .map(str::to_owned)
                })
                .map(|state| match state.as_str() {
                    "finished" => "Native TTS synthesis completed".to_owned(),
                    "cancelled" => "Native TTS synthesis cancelled".to_owned(),
                    _ => "Native TTS synthesis failed".to_owned(),
                })
                .unwrap_or_else(|| "Native TTS synthesis ended".to_owned());
            let state = self.as_mut().rust_mut().get_mut();
            state.active_tts_request_id = 0;
            state.tts_cancellation = None;
            self.as_mut().set_status(QString::from(&status));
        }
        let payload = QString::from(payload.as_str());
        let audio = QByteArray::from(audio.as_slice());
        self.as_mut().tts_audio_event(&payload, &audio);
    }

    fn emit_asr_payload(mut self: Pin<&mut Self>, request_id: i64, payload: String) {
        if self.as_ref().get_ref().rust().active_asr_request_id != request_id {
            return;
        }
        let status = serde_json::from_str::<Value>(&payload)
            .ok()
            .and_then(|value| {
                value
                    .get("state")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            })
            .map(|state| match state.as_str() {
                "finished" => "Native ASR transcription completed".to_owned(),
                "cancelled" => "Native ASR transcription cancelled".to_owned(),
                _ => "Native ASR transcription failed".to_owned(),
            })
            .unwrap_or_else(|| "Native ASR transcription ended".to_owned());
        let state = self.as_mut().rust_mut().get_mut();
        state.active_asr_request_id = 0;
        state.asr_cancellation = None;
        self.as_mut().set_status(QString::from(&status));
        self.as_mut()
            .asr_transcription_event(&QString::from(payload.as_str()));
    }
}

#[derive(Clone)]
struct ProviderOperationJob {
    target: String,
    operation: String,
    config: LlmTransportConfig,
}

#[derive(Clone)]
struct TtsSynthesisJob {
    config: TtsConfig,
    request: TtsRequest,
    character: String,
    translation: Option<LlmTransportConfig>,
}

#[derive(Clone)]
struct AsrTranscriptionJob {
    config: AsrConfig,
    audio: Vec<u8>,
}

#[derive(Clone)]
struct MemoryExtractionJob {
    database_path: String,
    character: String,
    user_key: String,
    source_message_id: Option<i64>,
    source_group_message_id: Option<i64>,
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
    source_message_id: Option<i64>,
    source_group_message_id: Option<i64>,
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
        source_group_message_id,
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

fn prepare_tts_synthesis_job(
    config_path: &Path,
    project_root: &Path,
    text: &str,
    character: &str,
    speed_factor: f64,
    force: bool,
) -> Result<Option<TtsSynthesisJob>, String> {
    let settings = load_native_tts_settings(config_path)
        .map_err(|error| format!("TTS settings error: {error}"))?;
    if !settings.enabled && !force {
        return Ok(None);
    }
    let translation = if settings.translate_to_selected_language && settings.language != "Chinese" {
        load_memory_transport_config(config_path)?
    } else {
        None
    };
    Ok(Some(TtsSynthesisJob {
        config: TtsConfig {
            api_url: settings.api_url,
            language: settings.language,
            reference_character: settings.reference_character,
            streaming: settings.streaming,
            temperature: settings.temperature,
            project_root: project_root.to_owned(),
        },
        request: TtsRequest {
            text: text.to_owned(),
            character: character.trim().to_owned(),
            speed_factor,
        },
        character: character.trim().to_owned(),
        translation,
    }))
}

fn prepare_asr_transcription_job(
    config_path: &Path,
    audio: Vec<u8>,
    force: bool,
) -> Result<Option<AsrTranscriptionJob>, String> {
    let settings = load_native_asr_settings(config_path)
        .map_err(|error| format!("ASR settings error: {error}"))?;
    if !settings.enabled && !force {
        return Ok(None);
    }
    let config =
        ConfigDocument::load(config_path).map_err(|error| format!("ASR config error: {error}"))?;
    Ok(Some(AsrTranscriptionJob {
        config: AsrConfig {
            api_url: settings.api_url,
            api_key: config_string(&config, "asr_api_key"),
            model_id: settings.model_id,
            language: settings.language,
            timeout_seconds: u64::from(settings.timeout_seconds),
        },
        audio,
    }))
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

fn load_group_planner_transport_config(path: &Path) -> Result<LlmTransportConfig, String> {
    let config =
        ConfigDocument::load(path).map_err(|error| format!("Planner LLM config error: {error}"))?;
    let api_url = nonempty_config_string(&config, "llm_aux_api_url", "llm_api_url");
    let api_key = nonempty_config_string(&config, "llm_aux_api_key", "llm_api_key");
    let model = nonempty_config_string(&config, "llm_aux_model_id", "llm_model_id");
    if api_url.is_empty() {
        return Err("Planner LLM API URL is not configured".to_owned());
    }
    if model.is_empty() {
        return Err("Planner LLM model is not configured".to_owned());
    }
    Ok(LlmTransportConfig {
        api_url,
        api_key,
        model,
        mode: LlmApiMode::ChatCompletions,
        enable_thinking: config
            .get("llm_aux_enable_thinking")
            .and_then(Value::as_bool),
    })
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

fn parse_attachments_json(source: &str) -> Result<Value, String> {
    if source.len() > MAX_ATTACHMENT_JSON_BYTES {
        return Err("Chat attachment list is too large".to_owned());
    }
    match serde_json::from_str::<Value>(source) {
        Ok(Value::Array(items)) => Ok(Value::Array(items)),
        Ok(_) => Err("Chat attachments must be a JSON array".to_owned()),
        Err(error) => Err(format!("Chat attachment error: {error}")),
    }
}

fn parse_string_array(source: &str, max_bytes: usize, label: &str) -> Result<Vec<String>, String> {
    if source.len() > max_bytes {
        return Err(format!("{label} is too large"));
    }
    serde_json::from_str::<Vec<String>>(source).map_err(|error| format!("{label} error: {error}"))
}

fn parse_group_members(source: &str) -> Result<Vec<GroupMember>, String> {
    if source.len() > MAX_GROUP_MEMBERS_JSON_BYTES {
        return Err("Group member list is too large".to_owned());
    }
    let members = serde_json::from_str::<Vec<GroupMember>>(source)
        .map_err(|error| format!("Group member list error: {error}"))?;
    let unique_keys = members
        .iter()
        .filter(|member| !member.key.is_empty() && !member.name.is_empty())
        .map(|member| member.key.as_str())
        .collect::<HashSet<_>>();
    if members.len() < 2 || unique_keys.len() != members.len() {
        return Err("Group chat needs at least two distinct named members".to_owned());
    }
    Ok(members)
}

fn group_members_match_key(members: &[GroupMember], group_key: &str) -> bool {
    let keys = members
        .iter()
        .map(|member| member.key.clone())
        .collect::<Vec<_>>();
    conversation_key_for(&keys, "") == group_key
}

fn parse_llm_request(source: &str) -> Result<LlmTransportRequest, String> {
    LlmTransportRequest::from_json(source, MAX_CHAT_REQUEST_BYTES)
        .map_err(|error| format!("Invalid native LLM request: {error}"))
}

#[allow(clippy::too_many_arguments)]
fn prepare_provider_operation(
    config_path: &Path,
    target: &str,
    operation: &str,
    api_url_override: &str,
    api_key_override: &str,
    model_override: &str,
    api_mode_override: &str,
) -> Result<ProviderOperationJob, String> {
    let target = target.trim();
    if !matches!(target, "primary" | "auxiliary") {
        return Err("Provider target must be primary or auxiliary".into());
    }
    let operation = operation.trim();
    if !matches!(operation, "fetch_models" | "test_connection") {
        return Err("Unknown provider operation".into());
    }
    let config =
        ConfigDocument::load(config_path).map_err(|error| format!("LLM config error: {error}"))?;
    let primary_url = config_string(&config, "llm_api_url");
    let primary_key = config_string(&config, "llm_api_key");
    let primary_model = config_string(&config, "llm_model_id");
    let api_url = checked_provider_value(
        if api_url_override.trim().is_empty() {
            if target == "auxiliary" {
                nonempty_config_string(&config, "llm_aux_api_url", "llm_api_url")
            } else {
                primary_url
            }
        } else {
            api_url_override.trim().to_owned()
        },
        4 * 1024,
        "API URL",
    )?;
    if !(api_url.starts_with("https://") || api_url.starts_with("http://")) {
        return Err("Provider API URL must use HTTP or HTTPS".into());
    }
    let api_key = checked_provider_value(
        if api_key_override.trim().is_empty() {
            if target == "auxiliary" {
                nonempty_config_string(&config, "llm_aux_api_key", "llm_api_key")
            } else {
                primary_key
            }
        } else {
            api_key_override.trim().to_owned()
        },
        16 * 1024,
        "API key",
    )?;
    if api_key.is_empty() {
        return Err("Provider API key is not configured".into());
    }
    let model = checked_provider_value(
        if model_override.trim().is_empty() {
            if target == "auxiliary" {
                nonempty_config_string(&config, "llm_aux_model_id", "llm_model_id")
            } else {
                primary_model
            }
        } else {
            model_override.trim().to_owned()
        },
        512,
        "model ID",
    )?;
    if operation == "test_connection" && model.is_empty() {
        return Err("Provider model ID is not configured".into());
    }
    let api_mode = if api_mode_override.trim().is_empty() {
        config_string(&config, "llm_api_mode")
    } else {
        api_mode_override.trim().to_owned()
    };
    Ok(ProviderOperationJob {
        target: target.to_owned(),
        operation: operation.to_owned(),
        config: LlmTransportConfig {
            api_url,
            api_key,
            model,
            mode: LlmApiMode::from_config(&api_mode),
            enable_thinking: None,
        },
    })
}

fn checked_provider_value(value: String, max_bytes: usize, label: &str) -> Result<String, String> {
    if value.len() > max_bytes || value.chars().any(char::is_control) {
        Err(format!(
            "Provider {label} is too long or contains control characters"
        ))
    } else {
        Ok(value)
    }
}

fn run_tts_synthesis(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    job: TtsSynthesisJob,
    cancellation: CancellationToken,
) {
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            queue_tts_payload(
                &qt_thread,
                request_id,
                json!({
                    "request_id":request_id,
                    "state":"error",
                    "message":format!("TTS async runtime error: {error}")
                }),
                Vec::new(),
                true,
            );
            return;
        }
    };
    runtime.block_on(execute_tts_synthesis(
        qt_thread,
        request_id,
        job,
        cancellation,
    ));
}

async fn execute_tts_synthesis(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    mut job: TtsSynthesisJob,
    cancellation: CancellationToken,
) {
    let mut translation_warning = String::new();
    if let Some(config) = job.translation.take() {
        match LlmTransport::new(config) {
            Ok(transport) => {
                let target = match job.config.language.as_str() {
                    "Japanese" => "自然日语",
                    "English" => "自然英语",
                    _ => "所选语言",
                };
                let request = LlmTransportRequest {
                    messages: vec![
                        json!({
                            "role":"system",
                            "content":format!("把用户给出的中文聊天台词翻译成{target}，只输出译文，不要解释。保留语气，不要输出动作标签。")
                        }),
                        json!({"role":"user","content":job.request.text.clone()}),
                    ],
                    ..Default::default()
                };
                let mut translated = String::new();
                let result = transport
                    .stream(&request, &cancellation, |event| {
                        if let LlmStreamEvent::TextDelta { text } = event
                            && translated.len().saturating_add(text.len()) <= 64 * 1024
                        {
                            translated.push_str(&text);
                        }
                    })
                    .await;
                match result {
                    Ok(_) if !translated.trim().is_empty() => {
                        job.request.text = translated.trim().to_owned();
                    }
                    Ok(_) => translation_warning = "translation returned no text".into(),
                    Err(LlmTransportError::Cancelled) => {
                        queue_tts_payload(
                            &qt_thread,
                            request_id,
                            json!({"request_id":request_id,"state":"cancelled"}),
                            Vec::new(),
                            true,
                        );
                        return;
                    }
                    Err(error) => translation_warning = error.to_string(),
                }
            }
            Err(error) => translation_warning = error.to_string(),
        }
    }
    if cancellation.is_cancelled() {
        queue_tts_payload(
            &qt_thread,
            request_id,
            json!({"request_id":request_id,"state":"cancelled"}),
            Vec::new(),
            true,
        );
        return;
    }
    let transport = match TtsTransport::new(job.config.clone()) {
        Ok(transport) => transport,
        Err(error) => {
            queue_tts_payload(
                &qt_thread,
                request_id,
                json!({"request_id":request_id,"state":"error","message":error.to_string()}),
                Vec::new(),
                true,
            );
            return;
        }
    };
    let audio_thread = qt_thread.clone();
    let character = job.character.clone();
    let prepared_text = clean_tts_text(&job.request.text);
    let language = job.config.language.clone();
    let outcome = transport
        .synthesize(&job.request, &cancellation, move |chunk: TtsAudioChunk| {
            queue_tts_payload(
                &audio_thread,
                request_id,
                json!({
                    "request_id":request_id,
                    "state":"audio",
                    "media_type":chunk.media_type,
                    "character":character.clone(),
                    "prepared_text":prepared_text.clone(),
                    "language":language.clone()
                }),
                chunk.bytes,
                false,
            );
        })
        .await;
    let payload = match outcome {
        Ok(outcome) => json!({
            "request_id":request_id,
            "state":"finished",
            "chunk_count":outcome.chunk_count,
            "total_bytes":outcome.total_bytes,
            "used_streaming":outcome.used_streaming,
            "translation_warning":translation_warning
        }),
        Err(bandori_tts::TtsError::Cancelled) => {
            json!({"request_id":request_id,"state":"cancelled"})
        }
        Err(error) => {
            json!({"request_id":request_id,"state":"error","message":error.to_string(),"translation_warning":translation_warning})
        }
    };
    queue_tts_payload(&qt_thread, request_id, payload, Vec::new(), true);
}

fn queue_tts_payload(
    qt_thread: &ffi::BackendCxxQtThread,
    request_id: i64,
    payload: Value,
    audio: Vec<u8>,
    terminal: bool,
) {
    let payload = payload.to_string();
    qt_thread
        .queue(move |backend| {
            backend.emit_tts_audio_payload(request_id, payload, audio, terminal);
        })
        .ok();
}

fn run_asr_transcription(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    job: AsrTranscriptionJob,
    cancellation: CancellationToken,
) {
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            queue_asr_payload(
                &qt_thread,
                request_id,
                json!({
                    "request_id":request_id,
                    "state":"error",
                    "message":format!("ASR async runtime error: {error}")
                }),
            );
            return;
        }
    };
    runtime.block_on(execute_asr_transcription(
        qt_thread,
        request_id,
        job,
        cancellation,
    ));
}

async fn execute_asr_transcription(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    job: AsrTranscriptionJob,
    cancellation: CancellationToken,
) {
    let payload = match AsrTransport::new(job.config) {
        Ok(transport) => match transport
            .transcribe(&job.audio, "audio/wav", &cancellation)
            .await
        {
            Ok(outcome) => json!({
                "request_id":request_id,
                "state":"finished",
                "text":outcome.text
            }),
            Err(bandori_asr::AsrError::Cancelled) => {
                json!({"request_id":request_id,"state":"cancelled"})
            }
            Err(error) => json!({
                "request_id":request_id,
                "state":"error",
                "message":error.to_string()
            }),
        },
        Err(error) => json!({
            "request_id":request_id,
            "state":"error",
            "message":error.to_string()
        }),
    };
    queue_asr_payload(&qt_thread, request_id, payload);
}

fn queue_asr_payload(qt_thread: &ffi::BackendCxxQtThread, request_id: i64, payload: Value) {
    let payload = payload.to_string();
    qt_thread
        .queue(move |backend| {
            backend.emit_asr_payload(request_id, payload);
        })
        .ok();
}

fn run_provider_operation(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    job: ProviderOperationJob,
    cancellation: CancellationToken,
) {
    let ProviderOperationJob {
        target,
        operation,
        config,
    } = job;
    let provider_secret = config.api_key.clone();
    let runtime = match tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
    {
        Ok(runtime) => runtime,
        Err(error) => {
            queue_provider_payload(
                &qt_thread,
                request_id,
                json!({
                    "request_id":request_id,
                    "target":target,
                    "operation":operation,
                    "state":"error",
                    "message":format!("Provider async runtime error: {error}")
                }),
            );
            return;
        }
    };
    let transport = match LlmTransport::new(config) {
        Ok(transport) => transport,
        Err(error) => {
            queue_provider_payload(
                &qt_thread,
                request_id,
                json!({
                    "request_id":request_id,
                    "target":target,
                    "operation":operation,
                    "state":"error",
                    "message":provider_error_message(&error, &provider_secret)
                }),
            );
            return;
        }
    };
    let payload = if operation == "fetch_models" {
        match runtime.block_on(transport.fetch_models(&cancellation)) {
            Ok(models) => json!({
                "request_id":request_id,
                "target":target,
                "operation":operation,
                "state":"finished",
                "models":models
            }),
            Err(LlmTransportError::Cancelled) => json!({
                "request_id":request_id,"target":target,"operation":operation,
                "state":"cancelled","message":"Provider operation cancelled"
            }),
            Err(error) => json!({
                "request_id":request_id,"target":target,"operation":operation,
                "state":"error","message":provider_error_message(&error, &provider_secret)
            }),
        }
    } else {
        match runtime.block_on(transport.test_connection(&cancellation)) {
            Ok(mode) => json!({
                "request_id":request_id,
                "target":target,
                "operation":operation,
                "state":"finished",
                "mode":mode
            }),
            Err(LlmTransportError::Cancelled) => json!({
                "request_id":request_id,"target":target,"operation":operation,
                "state":"cancelled","message":"Provider operation cancelled"
            }),
            Err(error) => json!({
                "request_id":request_id,"target":target,"operation":operation,
                "state":"error","message":provider_error_message(&error, &provider_secret)
            }),
        }
    };
    queue_provider_payload(&qt_thread, request_id, payload);
}

fn provider_error_message(error: &LlmTransportError, secret: &str) -> String {
    let message = error.to_string();
    if secret.is_empty() {
        message
    } else {
        message.replace(secret, "<redacted>")
    }
}

fn queue_provider_payload(qt_thread: &ffi::BackendCxxQtThread, request_id: i64, payload: Value) {
    let payload = payload.to_string();
    qt_thread
        .queue(move |backend| {
            backend.emit_provider_operation_payload(request_id, payload);
        })
        .ok();
}

fn assistant_tool_trace(outcome_json: &str) -> Option<Value> {
    let outcome = serde_json::from_str::<Value>(outcome_json).ok()?;
    native_tool_trace(&outcome)
}

fn run_llm_stream(
    qt_thread: ffi::BackendCxxQtThread,
    request_id: i64,
    config: LlmTransportConfig,
    request: LlmTransportRequest,
    cancellation: CancellationToken,
    tool_context: Option<NativeToolRuntimeContext>,
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
    let result = runtime.block_on(stream_with_native_tools(
        &transport,
        request,
        &cancellation,
        tool_context.as_ref(),
        move |event| {
            queue_stream_event(&event_thread, request_id, event);
        },
    ));
    let payload = match result {
        Ok(outcome) => json!({
            "request_id": request_id,
            "state": "finished",
            "mode": outcome.mode,
            "response_id": outcome.response_id,
            "usage": outcome.usage,
            "tool_calls": outcome.tool_calls,
        }),
        Err(failure) if matches!(&failure.error, LlmTransportError::Cancelled) => {
            json!({
                "request_id": request_id,
                "state": "cancelled",
                "usage": failure.usage,
                "tool_calls": failure.tool_calls,
            })
        }
        Err(failure) => {
            json!({
                "request_id": request_id,
                "state": "error",
                "message": failure.error.to_string(),
                "usage": failure.usage,
                "tool_calls": failure.tool_calls,
            })
        }
    };
    queue_terminal_payload(&qt_thread, request_id, payload);
}

async fn stream_with_native_tools<F>(
    transport: &LlmTransport,
    mut request: LlmTransportRequest,
    cancellation: &CancellationToken,
    tool_context: Option<&NativeToolRuntimeContext>,
    mut on_event: F,
) -> Result<NativeToolLoopOutcome, NativeToolLoopFailure>
where
    F: FnMut(LlmStreamEvent),
{
    let mut usage = None;
    let mut tool_results = Vec::new();
    for round in 0..MAX_NATIVE_TOOL_ROUNDS {
        let mut tool_calls = NativeToolCallAccumulator::default();
        let mut assistant_content = String::new();
        let outcome = match transport
            .stream(&request, cancellation, |event| {
                tool_calls.absorb(&event);
                if let LlmStreamEvent::TextDelta { text } = &event {
                    assistant_content.push_str(text);
                }
                on_event(event);
            })
            .await
        {
            Ok(outcome) => outcome,
            Err(error) => {
                return Err(NativeToolLoopFailure {
                    error,
                    usage,
                    tool_calls: tool_results,
                });
            }
        };
        merge_token_usage(&mut usage, outcome.usage);
        let calls = tool_calls.finish();
        if calls.is_empty() {
            return Ok(NativeToolLoopOutcome {
                mode: outcome.mode,
                response_id: outcome.response_id,
                usage,
                tool_calls: tool_results,
            });
        }
        let execution_context = tool_context.map(|context| NativeToolExecutionContext {
            config_path: Path::new(&context.config_path),
            now: context.now,
            active_character: &context.active_character,
        });
        let round_results = calls
            .iter()
            .map(|call| execute_native_tool_call_with_context(call, execution_context.as_ref()))
            .collect::<Vec<_>>();
        tool_results.extend(round_results.iter().cloned());
        if round + 1 >= MAX_NATIVE_TOOL_ROUNDS {
            return Err(NativeToolLoopFailure {
                error: LlmTransportError::ToolLoop(
                    "the model exceeded the native tool-call round limit",
                ),
                usage,
                tool_calls: tool_results,
            });
        }
        let followup = chat_tool_followup_messages(&calls, &round_results, &assistant_content);
        match outcome.mode {
            LlmApiMode::ChatCompletions => request.messages.extend(followup),
            LlmApiMode::Responses => {
                if outcome.response_id.trim().is_empty() {
                    return Err(NativeToolLoopFailure {
                        error: LlmTransportError::ToolLoop(
                            "a Responses API tool call did not include a response id",
                        ),
                        usage,
                        tool_calls: tool_results,
                    });
                }
                request.messages = followup.into_iter().skip(1).collect();
                request.previous_response_id = outcome.response_id;
            }
        }
    }
    unreachable!("the bounded native tool loop always returns")
}

fn merge_token_usage(total: &mut Option<TokenUsage>, update: Option<TokenUsage>) {
    let Some(update) = update else {
        return;
    };
    let total = total.get_or_insert_with(TokenUsage::default);
    total.input_tokens = total.input_tokens.saturating_add(update.input_tokens);
    total.output_tokens = total.output_tokens.saturating_add(update.output_tokens);
    total.total_tokens = total.total_tokens.saturating_add(update.total_tokens);
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
                job.source_message_id,
                job.source_group_message_id,
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
