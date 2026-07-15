from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_qt_shared_memory_delegates_wire_layout_to_rust():
    queue = source("native/qt/shared_memory_line_queue.cpp")

    assert "bandori_ipc_initialize_queue" in queue
    assert "bandori_ipc_publish" in queue
    assert "bandori_ipc_read_next" in queue
    assert "QSharedMemory" in queue


def test_native_alpha_hit_reads_one_physical_pixel_and_keeps_hit_grace():
    widget = source("native/qt/live2d_gl_widget.cpp")

    assert "glReadPixels(\n        sampleX, sampleY, 1, 1" in widget
    assert "kAlphaHitIntervalMsec = 16" in widget
    assert "kAlphaHitGraceMsec = 80" in widget
    assert "kAlphaHitGraceDistance = 12" in widget
    assert "WS_EX_TRANSPARENT" in widget
    assert "Qt::WindowTransparentForInput" in widget


def test_native_drag_ipc_uses_cumulative_updates_and_reliable_final_state():
    pet = source("native/qt/pet_main.cpp")

    assert 'QStringLiteral("PEER_DRAG\\t")' in pet
    assert 'QStringLiteral("PEER_DRAG_END\\t")' in pet
    assert 'QStringLiteral("total_dx")' in pet
    assert 'QStringLiteral("total_dy")' in pet
    assert "completedPeerDragIds.contains(dragId)" in pet
    assert "true);" in pet


def test_native_mutual_gaze_broadcasts_positions_and_clamps_global_target():
    pet = source("native/qt/pet_main.cpp")
    widget = source("native/qt/live2d_gl_widget.cpp")

    assert 'QStringLiteral("PEER_POS\\t")' in pet
    assert "peerPositionTimer.setInterval(200)" in pet
    assert "nearestDistance" in pet
    assert "distance > 600.0" in widget
    assert "bandori_live2d_drag(host_, local.x(), local.y())" in widget


def test_native_pet_restores_visible_position_and_accepts_motion_preview():
    pet = source("native/qt/pet_main.cpp")
    main = source("main.py")

    assert 'QStringLiteral("PREVIEW_MOTION\\t")' in pet
    assert "availableGeometry().intersects(requestedGeometry)" in pet
    assert "QGuiApplication::primaryScreen()" in pet
    assert '"--x", str(model.get("window_x"' in main
    assert '"--y", str(model.get("window_y"' in main


def test_native_pet_state_is_persisted_through_rust_config_boundary():
    pet = source("native/qt/pet_main.cpp")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    config_ffi = source("rust/crates/bandori-core/src/config_ffi.rs")

    assert 'QStringLiteral("PET_STATE\\t")' in pet
    assert "bandori_config_save_pet_state" in supervisor
    assert "ConfigDocument::load" in config_ffi
    assert "apply_pet_window_state" in config_ffi
    assert "config.save(path)" in config_ffi
    assert 'QStringLiteral("drag_locked"), widget.dragLocked()' in pet
    assert "pub drag_locked: Option<bool>" in source(
        "rust/crates/bandori-core/src/config.rs"
    )


def test_native_pet_click_double_click_and_poke_feedback_cross_rust_boundary():
    widget_header = source("native/qt/live2d_gl_widget.h")
    widget = source("native/qt/live2d_gl_widget.cpp")
    pet = source("native/qt/pet_main.cpp")
    live2d_ffi = source("rust/crates/bandori-live2d/src/ffi.rs")
    runtime = source("rust/crates/bandori-live2d/src/runtime.rs")
    main = source("main.py")

    assert "void clicked(double x, double y)" in widget_header
    assert "void doubleClicked(double x, double y)" in widget_header
    assert "void rightClicked(int globalX, int globalY)" in widget_header
    assert "pressedOnModel_ = isOpaqueAtGlobal(globalPosition)" in widget
    assert "if (dragLocked_)" in widget
    assert "emit clicked(position.x(), position.y())" in widget
    assert "emit doubleClicked(position.x(), position.y())" in widget
    assert "bandori_live2d_trigger_interaction" in widget
    assert "trigger_interaction_feedback" in live2d_ffi
    assert "select_interaction_motion" in runtime
    assert 'QStringLiteral("POKE_USER\\t")' in pet
    assert "shakeWindow(widget, 72)" in pet
    assert '"--click-motion-actions", json.dumps(' in main
    assert '"--poke-expression", str(cfg.get("poke_expression"' in main


def test_native_renderer_honors_surface_quality_and_configured_default_state():
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    widget_header = source("native/qt/live2d_gl_widget.h")
    widget = source("native/qt/live2d_gl_widget.cpp")
    pet = source("native/qt/pet_main.cpp")
    live2d_ffi = source("rust/crates/bandori-live2d/src/ffi.rs")
    runtime = source("rust/crates/bandori-live2d/src/runtime.rs")
    window = source("native/qt/native_main_window.cpp")
    main = source("main.py")

    assert "pub vsync: bool" in dashboard
    assert "pub live2d_quality: String" in dashboard
    assert "pub live2d_scale: i64" in dashboard
    assert "pub default_motion: String" in dashboard
    assert "pub default_expression: String" in dashboard
    assert "pub idle_actions_enabled: bool" in dashboard
    assert "pub random_actions_enabled: bool" in dashboard
    assert "bool vsync = true" in supervisor_header
    assert 'QString live2dQuality = QStringLiteral("balanced")' in supervisor_header
    assert 'QStringLiteral("--vsync")' in supervisor
    assert 'QStringLiteral("--quality")' in supervisor
    assert 'QStringLiteral("--scale")' in supervisor
    assert 'QStringLiteral("--default-motion")' in supervisor
    assert 'QStringLiteral("--default-expression")' in supervisor
    assert 'QStringLiteral("--idle-actions-enabled")' in supervisor
    assert 'QStringLiteral("--random-actions-enabled")' in supervisor
    assert "void runtimeReady()" in widget_header
    assert "void setRenderQuality(const QString& quality)" in widget_header
    assert "textureQuality_" in widget
    assert "ssaaScale_" in widget
    assert "bandori_live2d_apply_default_state" in widget
    assert "bandori_live2d_is_motion_finished" in widget
    assert "defaultStateTimer_.setInterval(500)" in widget
    assert "earlyBooleanOption" in pet
    assert "scaledLive2dSize" in pet
    assert "widget.setFixedSize(scaledLive2dSize(modelFormat, currentScale))" in pet
    assert pet.index("configureDefaultSurfaceFormat(initialVsync)") < pet.index("QApplication app")
    assert "&bandori::Live2dGlWidget::runtimeReady" in pet
    assert "apply_default_state" in live2d_ffi
    assert "MotionPriority::Force, true" in runtime
    assert 'call_method::<bool>("isFinished", ())' in runtime
    assert "select_default_motion" in runtime
    assert "select_default_expression" in runtime
    assert "rendererRestartRequired" in window
    assert "supervisor_.startAll(activeSpecs_)" in window
    assert '"--vsync", str(bool(cfg.get("vsync"' in main
    assert '"--quality", str(cfg.get("live2d_quality"' in main
    assert '"--scale", str(cfg.get("live2d_scale"' in main
    assert '"--default-motion", str(model.get("default_motion"' in main
    assert '"--idle-actions-enabled", str(bool(cfg.get("live2d_idle_actions_enabled"' in main


def test_native_radial_menu_routes_actions_and_uses_shaped_popup():
    menu_header = source("native/qt/native_radial_menu.h")
    menu = source("native/qt/native_radial_menu.cpp")
    pet = source("native/qt/pet_main.cpp")
    main = source("main.py")

    assert "class NativeRadialMenu final" in menu_header
    assert "Qt::Popup | Qt::FramelessWindowHint" in menu
    assert "setMask(region)" in menu
    assert "QVariantAnimation" in menu
    assert "ignoreReleaseUntilButtonsUp_" in menu
    assert "void NativeRadialMenu::setLanguage" in menu
    assert "&bandori::Live2dGlWidget::rightClicked" in pet
    assert 'QStringLiteral("RADIAL_MENU_OPEN\\t")' in pet
    assert 'QStringLiteral("OPEN_CHAT_NATIVE\\t")' in pet
    assert 'QStringLiteral("OPEN_SETTINGS\\tcostumes\\t")' in pet
    assert 'QStringLiteral("__random__")' in pet
    assert 'line.startswith("OPEN_CHAT_NATIVE\\t")' in main
    assert "launch_chat_process(native_request=request)" in main


def test_python_supervisor_keeps_native_renderer_opt_in_and_full_fallback():
    main = source("main.py")

    assert 'BANDORI_PET_NATIVE_RENDERER", ""' in main
    assert 'BANDORI_PET_NATIVE_RENDERER_PATH", ""' in main
    assert '"--hit-alpha-threshold"' in main
    assert '"--move-all-roles-together"' in main
    assert "using Python renderer" in main


def test_native_main_window_consumes_safe_rust_dashboard_state():
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    window = source("native/qt/native_main_window.cpp")

    assert "DashboardSnapshot::load" in backend
    assert "NativeRuntimeSnapshot" in backend
    assert "persist_native_settings" in backend
    assert "llm_api_key" not in dashboard.split("#[cfg(test)]", 1)[0]
    assert "backend_.reloadState" in window
    assert "backend_.getModelCatalogJson" in window
    assert "backend_.getRuntimeConfigJson" in window
    assert "qfw::SettingCardGroup" in window
    assert "qfw::GroupHeaderCardWidget" in window
    assert "backend_.saveNativeSettings" in window
    assert "supervisor_.broadcastSettings(settingsJson)" in window
    assert "startConfiguredPet" in window
    assert "supervisor_.startAll(activeSpecs_)" in window


def test_native_chat_history_reads_existing_database_through_rust():
    core = source("rust/crates/bandori-core/src/chat_dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    window = source("native/qt/native_main_window.cpp")

    assert "load_native_chat_snapshot" in core
    assert "Database::open" in core
    assert "get_conversations" in core
    assert "MAX_NATIVE_CHAT_MESSAGE_LIMIT" in core
    assert "has_older_messages" in core
    assert "loadChatState" in backend
    assert "chat_conversations_json" in backend
    assert "chat_messages_json" in backend
    assert "QWidget* NativeMainWindow::createChatPage()" in window
    assert "backend_.loadChatState" in window
    assert "backend_.getChatConversationsJson" in window
    assert "backend_.getChatMessagesJson" in window
    assert "backend_.getChatHasOlderMessages" in window
    assert "chatLoadOlderButton_" in window
    assert "attachmentSummaries" in window
    assert "void NativeMainWindow::openNativeChat" in window
    assert 'line.startsWith(QStringLiteral("OPEN_CHAT_NATIVE\\t"))' in window
    assert "Native chat UI is not ported yet" not in window


def test_native_chat_composer_streams_persists_and_dispatches_actions_through_rust():
    actions = source("rust/crates/bandori-core/src/chat_actions.rs")
    relationship = source("rust/crates/bandori-core/src/relationship_analysis.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub fn parse_chat_response" in actions
    assert "generated_python_action_vectors_match_rust" in actions
    assert "generated_python_interaction_vectors_match_rust" in relationship
    assert "pub fn apply_interaction_analysis" in relationship
    assert "parse_chat_response" in backend
    assert "completed_chat_user_content" in backend
    assert "apply_interaction_analysis" in backend
    assert '"actions": response.actions' in backend
    assert "qfw::PlainTextEdit* chatInput_" in window_header
    assert "void NativeMainWindow::sendNativeChat()" in window
    assert "backend_.prepareChatTurn" in window
    assert "backend_.buildChatRequest" in window
    assert "backend_.startChatStream" in window
    assert "backend_.cancelChatStream" in window
    assert "backend_.saveChatAssistant" in window
    assert "&Backend::chatStreamEvent" in window
    assert 'QStringLiteral("ACTION\\t%1\\t%2")' in window
    assert "bool broadcastControlLine" in supervisor_header
    assert "PetProcessSupervisor::broadcastControlLine" in supervisor
    assert 'QStringLiteral("__default__")' in window


def test_native_chat_memory_extraction_uses_model_or_single_fallback_update():
    memory = source("rust/crates/bandori-core/src/memory_extraction.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    window = source("native/qt/native_main_window.cpp")

    assert "generated_python_memory_contract_matches_rust" in memory
    assert "pub fn build_memory_extraction_messages" in memory
    assert "pub fn parse_memory_extraction" in memory
    assert "pub fn store_extracted_memories" in memory
    assert "load_memory_transport_config" in backend
    assert "run_memory_extraction" in backend
    assert "finish_memory_with_fallback" in backend
    assert 'analysis, "chat_model")' in memory
    assert "memory_cancellations" in backend
    assert "chatMemoryEvent" in backend
    assert "&Backend::chatMemoryEvent" in window


def test_native_chat_attachments_are_copied_sanitized_and_inlined_by_rust():
    attachments = source("rust/crates/bandori-core/src/chat_attachments.rs")
    context = source("rust/crates/bandori-core/src/chat_context.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "MAX_CHAT_ATTACHMENT_BYTES" in attachments
    assert "create_new(true)" in attachments
    assert "discard_imported_chat_attachments" in attachments
    assert "resolve_chat_attachment" in attachments
    assert '"type": "image_url"' in attachments
    assert "FILE_INLINE_BYTES" in attachments
    assert "chat_message_content" in context
    assert "latest_user_message_id" in context
    assert "importChatAttachments" in backend
    assert "discardChatAttachments" in backend
    assert "attachments_json: &QString" in backend
    assert "QJsonArray pendingChatAttachments_" in window_header
    assert "QFileDialog::getOpenFileNames" in window
    assert "backend_.getChatImportedAttachmentsJson" in window
    assert "backend_.prepareChatTurn" in window


def test_native_chat_attachment_retention_is_scoped_configurable_and_qt_managed():
    attachments = source("rust/crates/bandori-core/src/chat_attachments.rs")
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub struct ChatAttachmentStats" in attachments
    assert "pub struct ChatAttachmentCleanupResult" in attachments
    assert "pub fn chat_attachment_stats" in attachments
    assert "pub fn cleanup_chat_attachments" in attachments
    assert "attachment_stats_and_cleanup_are_scoped_to_the_database_directory" in attachments
    assert "chat_attachment_auto_cleanup_enabled" in dashboard
    assert "chat_attachment_retention_days" in dashboard
    assert "attachment_management_json" in backend
    assert "loadAttachmentStats" in backend
    assert "cleanupChatAttachments" in backend
    assert "getAttachmentManagementJson" in generation
    assert "loadAttachmentStats" in generation
    assert "cleanupChatAttachments" in generation
    assert "attachmentAutoCleanupSwitch_" in window_header
    assert "attachmentRetentionDaysSpinBox_" in window_header
    assert "refreshNativeAttachmentStats" in window
    assert "saveNativeAttachmentSettings" in window
    assert "cleanupNativeChatAttachments" in window
    assert "backend_.cleanupChatAttachments" in window


def test_native_cross_chat_context_is_filtered_and_python_contract_backed():
    history = source("rust/crates/bandori-core/src/cross_chat_history.rs")
    context = source("rust/crates/bandori-core/src/chat_context.rs")
    exporter = source("tools/export_rust_contracts.py")

    assert "pub fn build_cross_chat_history" in history
    assert "generated_python_cross_chat_history_matches_rust" in history
    assert ".get_conversations(Some(member), Some(user_key))" in history
    assert ".group_chats(Some(user_key))" in history
    assert "characters_for_group_key" in history
    assert "compact_history_text" in history
    assert "build_cross_chat_history" in context
    assert '"llm_cross_chat_history_enabled"' in context
    assert "_cross_chat_history_contract" in exporter


def test_native_private_conversation_management_validates_ownership_and_cleans_files():
    management = source("rust/crates/bandori-core/src/chat_management.rs")
    attachments = source("rust/crates/bandori-core/src/chat_attachments.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub fn delete_owned_private_conversation" in management
    assert ".get_conversations(Some(character), Some(user_key))" in management
    assert "delete_message_attachment_copies" in management
    assert "pub fn delete_message_attachment_copies" in attachments
    assert "deleteChatConversation" in backend
    assert "bool draftingNewConversation_" in window_header
    assert "void NativeMainWindow::startNewChatConversation()" in window
    assert "void NativeMainWindow::deleteSelectedChatConversation()" in window
    assert "QMessageBox::question" in window


def test_native_group_chat_core_is_python_contract_backed_and_user_partitioned():
    group = source("rust/crates/bandori-core/src/group_chat.rs")
    database = source("rust/crates/bandori-core/src/database.rs")
    management = source("rust/crates/bandori-core/src/chat_management.rs")
    exporter = source("tools/export_rust_contracts.py")

    assert "pub fn conversation_key_for" in group
    assert "pub fn build_group_planner_request" in group
    assert "pub fn parse_group_plan" in group
    assert "pub fn build_native_group_chat_request" in group
    assert "pub fn sanitize_group_assistant_reply" in group
    assert "generated_python_group_chat_contract_matches_rust" in group
    assert "Some(user_key)" in group
    assert "pub fn begin_group_chat_turn" in database
    assert "pub fn delete_owned_group_conversation" in management
    assert '"group_chat": _group_chat_contract()' in exporter


def test_native_group_chat_bridge_sequences_planner_speakers_and_group_memory_sources():
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")

    assert "enum ActiveChatKind" in backend
    assert "GroupPlan" in backend
    assert "GroupSpeaker" in backend
    assert "struct GroupTurnContext" in backend
    assert "pub fn prepare_group_chat_turn" in backend
    assert "pub fn build_group_plan_request" in backend
    assert "pub fn resolve_group_plan" in backend
    assert "pub fn build_group_chat_request" in backend
    assert "pub fn start_group_plan_stream" in backend
    assert "pub fn start_group_chat_stream" in backend
    assert "pub fn save_group_chat_assistant" in backend
    assert "Some(context.user_message_id)" in backend
    assert "source_group_message_id" in backend
    assert "group_assistant_content" in backend
    for method in (
        "prepareGroupChatTurn",
        "buildGroupPlanRequest",
        "resolveGroupPlan",
        "buildGroupChatRequest",
        "startGroupPlanStream",
        "startGroupChatStream",
        "saveGroupChatAssistant",
    ):
        assert method in generation


def test_native_qt_chat_page_exposes_group_selection_and_sequential_speaker_streams():
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "qfw::ComboBox* chatModeComboBox_" in header
    assert "qfw::ComboBox* chatGroupComboBox_" in header
    assert "qfw::ListWidget* chatGroupMembersList_" in header
    assert "QAbstractItemView::MultiSelection" in window
    assert "QString NativeMainWindow::selectedGroupKey() const" in window
    assert 'QStringLiteral("__group__:")' in window
    assert "backend_.loadGroupChatState" in window
    assert "backend_.prepareGroupChatTurn" in window
    assert "backend_.startGroupPlanStream" in window
    assert "backend_.resolveGroupPlan" in window
    assert "void NativeMainWindow::startNextGroupResponse()" in window
    assert "backend_.startGroupChatStream" in window
    assert "backend_.saveGroupChatAssistant" in window
    assert "groupSpokenNames_.append(characterDisplay)" in window
    assert 'QStringLiteral("group_plan")' in window
    assert 'QStringLiteral("group_speaker")' in window
    assert "backend_.finishGroupChatTurn()" in window


def test_native_chat_tools_are_bounded_looped_and_dispatched_through_existing_ipc():
    tools = source("rust/crates/bandori-core/src/chat_tools.rs")
    protocol = source("rust/crates/bandori-llm-protocol/src/lib.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    exporter = source("tools/export_rust_contracts.py")

    assert "CHAT_COMPLETIONS_POKE_USER_TOOL" in exporter
    assert "CHAT_COMPLETIONS_REMINDER_TOOLS" in exporter
    assert '"chat_tools"' in exporter
    assert "pub struct NativeToolCallAccumulator" in tools
    assert "replace_arguments" in tools
    assert "MAX_TOOL_ARGUMENT_BYTES" in tools
    assert "pub fn execute_native_tool_call" in tools
    assert "pub fn execute_native_tool_call_with_context" in tools
    assert "pub struct NativeToolExecutionContext" in tools
    assert "Unsupported native tool" in tools
    assert "responses_tool_definition" in protocol
    assert "const MAX_NATIVE_TOOL_ROUNDS: usize = 3" in backend
    assert "async fn stream_with_native_tools" in backend
    assert "chat_tool_followup_messages" in backend
    assert "request.previous_response_id = outcome.response_id" in backend
    assert "NativeToolRuntimeContext" in backend
    assert "execute_native_tool_call_with_context" in backend
    assert "native_tool_trace(&outcome)" in backend
    assert 'trace.insert("tool_calls"' in tools
    assert "int dispatchChatToolEffects" in header
    assert "int NativeMainWindow::dispatchChatToolEffects" in window
    assert 'QStringLiteral("poke_user")' in window
    assert 'QStringLiteral("POKE_USER\\t")' in window
    assert 'QStringLiteral("llm_tool")' in window
    assert 'QStringLiteral("to_user")' in window


def test_native_reminder_core_is_python_contract_backed_and_qt_independent():
    reminder = source("rust/crates/bandori-core/src/reminder.rs")
    core = source("rust/crates/bandori-core/src/lib.rs")
    exporter = source("tools/export_rust_contracts.py")

    assert "pub mod reminder;" in core
    assert "pub struct LocalDateTime" in reminder
    assert "pub fn normalize_time" in reminder
    assert "pub fn normalize_repeat_days" in reminder
    assert "pub fn compute_next_alarm_at" in reminder
    assert "pub fn create_alarm" in reminder
    assert "pub fn create_pomodoro" in reminder
    assert "pub fn tick_reminders" in reminder
    assert "generated_python_reminder_vectors_match_rust" in reminder
    assert "_reminder_contract(" in exporter
    assert 'OUTPUT_DIR / "reminder_vectors.json"' in exporter


def test_native_reminder_service_persists_and_delivers_system_or_pet_notifications():
    reminder = source("rust/crates/bandori-core/src/reminder.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    pet = source("native/qt/pet_main.cpp")

    assert "pub fn tick_config_reminders" in reminder
    assert "config.save(config_path)?" in reminder
    assert "default_character" in reminder
    assert "fn tick_reminders(" in backend
    assert "tick_config_reminders" in backend
    assert "reminder_events_json" in backend
    assert "QTimer reminderTimer_" in header
    assert "void NativeMainWindow::pollNativeReminders()" in window
    assert "backend_.tickReminders" in window
    assert "trayIcon_->showMessage" in window
    assert 'QStringLiteral("REMINDER_EVENT\\t")' in window
    assert "QLabel reminderBubble" in pet
    assert 'line.startsWith(QStringLiteral("REMINDER_EVENT\\t"))' in pet
    assert "reminderBubbleGeneration" in pet


def test_native_qt_reminder_management_uses_whitelisted_rust_mutations():
    reminder = source("rust/crates/bandori-core/src/reminder.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub struct NativeReminderState" in reminder
    assert "enum NativeReminderMutation" in reminder
    assert '#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]' in reminder
    assert "pub fn load_native_reminder_state" in reminder
    assert "pub fn mutate_native_reminders" in reminder
    assert "at most 256 alarms can be saved" in reminder
    assert "config.save(config_path)?" in reminder
    assert "native_management_commands_are_whitelisted_owned_and_atomic" in reminder
    assert "reminder_state_json" in backend
    assert "fn load_reminder_state(" in backend
    assert "fn mutate_reminder(" in backend
    assert "MAX_REMINDER_COMMAND_BYTES" in backend
    assert '"getReminderStateJson"' in bridge_test
    assert '"loadReminderState"' in bridge_test
    assert '"mutateReminder"' in bridge_test
    assert "QJsonObject reminderState_" in header
    assert "qfw::TimePicker* alarmTimePicker_" in header
    assert "qfw::ListWidget* reminderList_" in header
    assert "void NativeMainWindow::populateReminderCharacters()" in window
    assert "backend_.loadReminderState" in window
    assert "backend_.mutateReminder" in window
    assert 'QStringLiteral("set_display_mode")' in window
    assert 'QStringLiteral("add_alarm")' in window
    assert 'QStringLiteral("toggle_alarm")' in window
    assert 'QStringLiteral("delete_alarm")' in window
    assert 'QStringLiteral("add_pomodoro")' in window
    assert 'QStringLiteral("delete_pomodoro")' in window
    assert "alarmWeekdayCheckBoxes_" in window
    assert "loadNativeReminderState();" in window


def test_native_llm_settings_are_redacted_whitelisted_and_qt_editable():
    core = source("rust/crates/bandori-core/src/lib.rs")
    settings = source("rust/crates/bandori-core/src/llm_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod llm_settings;" in core
    assert "pub struct NativeLlmSettingsState" in settings
    assert "api_key_configured: bool" in settings
    assert "aux_api_key_configured: bool" in settings
    assert "pub struct NativeLlmSettingsUpdate" in settings
    assert '#[serde(deny_unknown_fields)]' in settings
    assert "pub fn load_native_llm_settings" in settings
    assert "pub fn save_native_llm_settings" in settings
    assert "pub struct NativeLlmProfileSummary" in settings
    assert "enum NativeLlmProfileMutation" in settings
    assert "pub fn mutate_native_llm_profiles" in settings
    assert "blank_secret_input_preserves_existing_keys" in settings
    assert "explicit_secret_clear_and_replacement_are_distinct_and_bounded" in settings
    assert "profile_mutations_apply_secrets_without_exposing_them" in settings
    assert 'config.set("llm_active_api_profile", Value::String(String::new()))' in settings
    assert "llm_settings_json" in backend
    assert "MAX_LLM_SETTINGS_BYTES" in backend
    assert "fn load_llm_settings(" in backend
    assert "fn save_llm_settings(" in backend
    assert "fn mutate_llm_profile(" in backend
    assert '"getLlmSettingsJson"' in bridge_test
    assert '"loadLlmSettings"' in bridge_test
    assert '"saveLlmSettings"' in bridge_test
    assert '"mutateLlmProfile"' in bridge_test
    assert "QWidget* createLlmSettingsPage()" in header
    assert "qfw::LineEdit* llmApiKeyEdit_" in header
    assert "qfw::ComboBox* llmProfileComboBox_" in header
    assert "QLineEdit::Password" in window
    assert "Leave blank to keep the saved key" in window
    assert "backend_.loadLlmSettings" in window
    assert "backend_.saveLlmSettings" in window
    assert "backend_.mutateLlmProfile" in window
    assert 'settings.insert(QStringLiteral("api_key"), primaryKey)' in window
    assert 'settings.insert(QStringLiteral("aux_api_key"), auxiliaryKey)' in window
    assert "loadNativeLlmSettings();" in window
    assert 'QStringLiteral("apply_profile")' in window
    assert 'QStringLiteral("save_current_profile")' in window
    assert 'QStringLiteral("delete_profile")' in window


def test_native_provider_discovery_and_connection_tests_are_bounded_and_async():
    transport = source("rust/crates/bandori-llm/src/lib.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub async fn fetch_models" in transport
    assert "pub async fn test_connection" in transport
    assert "PROVIDER_OPERATION_TIMEOUT" in transport
    assert "MAX_JSON_BODY_BYTES" in transport
    assert "MAX_PROVIDER_MODELS" in transport
    assert "models_api_url" in transport
    assert "provider_model_discovery_is_authenticated_sorted_and_deduplicated" in transport
    assert "provider_connection_test_falls_back_from_responses_to_chat_completions" in transport
    assert "fn start_provider_operation(" in backend
    assert "fn cancel_provider_operation(" in backend
    assert "run_provider_operation" in backend
    assert "provider_error_message" in backend
    assert "provider_operation_event" in backend
    assert '"startProviderOperation"' in bridge_test
    assert '"cancelProviderOperation"' in bridge_test
    assert '"providerOperationEvent"' in bridge_test
    assert "qfw::ComboBox* llmPrimaryDiscoveredModelsComboBox_" in header
    assert "qfw::ComboBox* llmAuxDiscoveredModelsComboBox_" in header
    assert "backend_.startProviderOperation" in window
    assert "handleNativeProviderOperation" in window
    assert "kMaximumVisibleProviderModels" in window
    assert "&Backend::providerOperationEvent" in window


def test_native_memory_dashboard_is_owned_transactional_and_qt_editable():
    core = source("rust/crates/bandori-core/src/lib.rs")
    memory = source("rust/crates/bandori-core/src/memory_dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod memory_dashboard;" in core
    assert "pub struct NativeMemorySnapshot" in memory
    assert "enum NativeMemoryMutation" in memory
    assert '#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]' in memory
    assert "pub fn load_native_memory_snapshot" in memory
    assert "pub fn mutate_native_memories" in memory
    assert "GLOBAL_MEMORY_CHARACTER" in memory
    assert "requested.is_subset(&owned)" in memory
    assert "memory_dashboard_is_partitioned_whitelisted_and_supports_global_memories" in memory
    assert "memory_snapshot_json" in backend
    assert "MAX_MEMORY_COMMAND_BYTES" in backend
    assert "fn load_memory_state(" in backend
    assert "fn mutate_memory(" in backend
    assert '"getMemorySnapshotJson"' in bridge_test
    assert '"loadMemoryState"' in bridge_test
    assert '"mutateMemory"' in bridge_test
    assert "QWidget* createMemoryPage()" in header
    assert "qfw::ListWidget* memoryList_" in header
    assert "backend_.loadMemoryState" in window
    assert "backend_.mutateMemory" in window
    assert 'QStringLiteral("__global__")' in window
    assert 'QStringLiteral("save_memory")' in window
    assert 'QStringLiteral("delete_memories")' in window
    assert "QAbstractItemView::ExtendedSelection" in window


def test_native_user_profiles_normalize_sync_runtime_and_refresh_owned_views():
    core = source("rust/crates/bandori-core/src/lib.rs")
    profiles = source("rust/crates/bandori-core/src/user_profiles.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod user_profiles;" in core
    assert "pub struct NativeUserProfile" in profiles
    assert "pub struct NativeUserProfilesState" in profiles
    assert "enum NativeUserProfileMutation" in profiles
    assert "pub fn load_native_user_profiles" in profiles
    assert "pub fn mutate_native_user_profiles" in profiles
    assert "DEFAULT_USER_PROFILE_KEY" in profiles
    assert "make_profile_key" in profiles
    assert "persist_state" in profiles
    assert "recover_after_last_delete" in profiles
    assert "user_profiles_json" in backend
    assert "MAX_USER_PROFILE_COMMAND_BYTES" in backend
    assert "fn load_user_profiles(" in backend
    assert "fn mutate_user_profile(" in backend
    assert "set_runtime_config_json" in backend
    assert '"getUserProfilesJson"' in bridge_test
    assert '"loadUserProfiles"' in bridge_test
    assert '"mutateUserProfile"' in bridge_test
    assert "QWidget* createUserProfilesPage()" in header
    assert "qfw::ComboBox* userProfileComboBox_" in header
    assert "backend_.loadUserProfiles" in window
    assert "backend_.mutateUserProfile" in window
    assert 'QStringLiteral("create_profile")' in window
    assert 'QStringLiteral("update_profile")' in window
    assert 'QStringLiteral("activate_profile")' in window
    assert 'QStringLiteral("delete_profile")' in window
    assert "refreshNativeMemoryState();" in window
    assert "refreshChatState({}, true);" in window


def test_native_persona_settings_are_rust_owned_and_qt_fluent_managed():
    core = source("rust/crates/bandori-core/src/lib.rs")
    personas = source("rust/crates/bandori-core/src/persona_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod persona_settings;" in core
    assert "pub struct NativePersonaSettingsState" in personas
    assert "pub struct NativeCharacterPersonaCollection" in personas
    assert "enum NativePersonaMutation" in personas
    assert '#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]' in personas
    assert "pub fn load_native_persona_settings" in personas
    assert "pub fn mutate_native_persona_settings" in personas
    assert "normalized_pov_personas" in personas
    assert "normalized_character_presets" in personas
    assert "persist_state" in personas
    assert "character_persona_crud_activates_and_falls_back_to_default" in personas
    assert 'format!("__role__:{role_character}")' in source(
        "rust/crates/bandori-core/src/dashboard.rs"
    )
    assert "persona_settings_json" in backend
    assert "MAX_PERSONA_COMMAND_BYTES" in backend
    assert "fn load_persona_settings(" in backend
    assert "fn mutate_persona_settings(" in backend
    assert '"getPersonaSettingsJson"' in bridge_test
    assert '"loadPersonaSettings"' in bridge_test
    assert '"mutatePersonaSettings"' in bridge_test
    assert "QWidget* createPersonaPage()" in header
    assert "qfw::ComboBox* povModeComboBox_" in header
    assert "qfw::ComboBox* characterPersonaPresetComboBox_" in header
    assert "backend_.loadPersonaSettings" in window
    assert "backend_.mutatePersonaSettings" in window
    assert 'QStringLiteral("save_pov")' in window
    assert 'QStringLiteral("save_pov_persona")' in window
    assert 'QStringLiteral("activate_character_persona")' in window
    assert 'QStringLiteral("save_character_persona")' in window
    assert 'QStringLiteral("delete_character_persona")' in window
    assert "importNativeCharacterPersonaDocuments" in window
    assert "refreshNativeMemoryState();" in window
    assert "refreshChatState({}, true);" in window
    assert "qfw::GroupHeaderCardWidget" in window


def test_native_history_search_is_bounded_unified_and_paginated():
    core = source("rust/crates/bandori-core/src/lib.rs")
    history = source("rust/crates/bandori-core/src/history_dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod history_dashboard;" in core
    assert "pub struct NativeHistoryQuery" in history
    assert '#[serde(default, deny_unknown_fields)]' in history
    assert "pub fn load_native_history_filters" in history
    assert "pub fn search_native_history" in history
    assert "MAX_HISTORY_PAGE_SIZE" in history
    assert "checked_date" in history
    assert "history_dashboard_searches_private_and_group_records_with_literal_filters" in history
    assert "history_filters_json" in backend
    assert "history_result_json" in backend
    assert "MAX_HISTORY_QUERY_BYTES" in backend
    assert "fn load_history_filters(" in backend
    assert "fn search_history(" in backend
    assert '"getHistoryFiltersJson"' in bridge_test
    assert '"getHistoryResultJson"' in bridge_test
    assert '"loadHistoryFilters"' in bridge_test
    assert '"searchHistory"' in bridge_test
    assert "QWidget* createHistorySearchPage()" in header
    assert "qfw::LineEdit* historyKeywordEdit_" in header
    assert "qfw::ListWidget* historyList_" in header
    assert "backend_.loadHistoryFilters" in window
    assert "backend_.searchHistory" in window
    assert 'QStringLiteral("skip_count")' in window
    assert "historyHasMore_" in window
    assert "loadNativeHistoryFilters();" in window


def test_native_statistics_are_user_scoped_and_do_not_require_qt_charts():
    core = source("rust/crates/bandori-core/src/lib.rs")
    statistics = source("rust/crates/bandori-core/src/statistics_dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    cmake = source("CMakeLists.txt")

    assert "pub mod statistics_dashboard;" in core
    assert "pub struct NativeStatisticsQuery" in statistics
    assert "pub struct NativeStatisticsSnapshot" in statistics
    assert '#[serde(default, deny_unknown_fields)]' in statistics
    assert "pub fn load_native_statistics" in statistics
    assert "messages_per_character_range" in statistics
    assert "hourly_heatmap" in statistics
    assert "statistics_snapshot_is_user_scoped_and_attributes_group_speakers" in statistics
    assert "statistics_snapshot_json" in backend
    assert "MAX_STATISTICS_QUERY_BYTES" in backend
    assert "fn load_statistics(" in backend
    assert '"getStatisticsSnapshotJson"' in bridge_test
    assert '"loadStatistics"' in bridge_test
    assert "QWidget* createStatisticsPage()" in header
    assert "qfw::TableWidget* statisticsRelationshipTable_" in header
    assert "qfw::TableWidget* statisticsHeatmapTable_" in header
    assert "backend_.loadStatistics" in window
    assert 'QStringLiteral("display_aliases")' in window
    assert "durationLabel" in window
    assert "QChart" not in window
    assert "Charts" not in cmake


def test_native_data_management_preserves_secrets_and_confirms_database_restore():
    core = source("rust/crates/bandori-core/src/lib.rs")
    data = source("rust/crates/bandori-core/src/data_management.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod data_management;" in core
    assert "pub const DATA_PACKAGE_FORMAT" in data
    assert "const SECRET_CONFIG_KEYS" in data
    assert "sanitize_llm_profiles" in data
    assert "prepare_llm_import" in data
    assert "validate_relationship_data" in data
    assert "write_json_atomically" in data
    assert "pub fn export_settings_package" in data
    assert "pub fn import_settings_package" in data
    assert "pub fn export_chat_database" in data
    assert "pub fn import_chat_database" in data
    assert "settings_package_round_trip_preserves_secrets_and_rejects_unknown_keys" in data
    assert "data_operation_json" in backend
    assert "MAX_SETTINGS_PACKAGE_BYTES" in backend
    assert '"getDataOperationJson"' in bridge_test
    assert '"exportSettingsPackage"' in bridge_test
    assert '"importSettingsPackage"' in bridge_test
    assert '"exportChatDatabase"' in bridge_test
    assert '"importChatDatabase"' in bridge_test
    assert "QWidget* createDataManagementPage()" in header
    assert "backend_.exportSettingsPackage" in window
    assert "backend_.importSettingsPackage" in window
    assert "backend_.exportChatDatabase" in window
    assert "backend_.importChatDatabase" in window
    assert 'tr("Replace current chat database?")' in window
    assert "activeChatRequestId_ != 0 || groupSequenceActive_" in window


def test_native_supervisor_runs_all_pets_on_one_shared_ipc_session():
    header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    window = source("native/qt/native_main_window.cpp")

    assert "void startAll(QList<PetLaunchSpec> specs)" in header
    assert "std::vector<std::unique_ptr<ChildState>> children_" in header
    assert "initializeIpcSession()" in supervisor
    assert "for (const auto& child : children_)" in supervisor
    assert 'environment.insert(QStringLiteral("BANDORI_PET_IPC_SERVER_NAME"), ipcSessionName_)' in supervisor
    assert 'QStringLiteral("SHUTDOWN")' in supervisor
    assert "for (const QString& raw : inboundQueue_->readAvailable())" in supervisor
    assert "broadcastQueue_->publish(raw)" in supervisor
    assert "controlQueue_->publish(raw)" in supervisor
    assert 'QStringLiteral("PEER_OFFLINE\\t")' in supervisor
    assert "supervisor_.startAll(activeSpecs_)" in window
    assert "bool NativeMainWindow::startConfiguredPets()" in window


def test_native_control_center_owns_cross_platform_tray_lifecycle():
    main = source("native/qt/main.cpp")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "QApplication::setQuitOnLastWindowClosed(false)" in main
    assert "void closeEvent(QCloseEvent* event) override" in window_header
    assert "QSystemTrayIcon::isSystemTrayAvailable()" in window
    assert "trayIcon_->setContextMenu(menu)" in window
    assert "startConfiguredPets()" in window
    assert "&PetProcessSupervisor::stop" in window
    assert "event->ignore()" in window
    assert "QCoreApplication::quit()" in window
