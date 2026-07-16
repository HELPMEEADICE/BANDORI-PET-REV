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
    assert 'position_x_key = "pixel_window_x" if pet_mode == "pixel" else "window_x"' in main
    assert 'position_y_key = "pixel_window_y" if pet_mode == "pixel" else "window_y"' in main


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
    assert "pub gpu_acceleration: bool" in dashboard
    assert "pub live2d_quality: String" in dashboard
    assert "pub live2d_scale: i64" in dashboard
    assert "pub default_motion: String" in dashboard
    assert "pub default_expression: String" in dashboard
    assert "pub idle_actions_enabled: bool" in dashboard
    assert "pub random_actions_enabled: bool" in dashboard
    assert "bool vsync = true" in supervisor_header
    assert "bool gpuAcceleration = true" in supervisor_header
    assert 'QString live2dQuality = QStringLiteral("balanced")' in supervisor_header
    assert 'QStringLiteral("--vsync")' in supervisor
    assert 'QStringLiteral("--gpu-acceleration")' in supervisor
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
    assert "widget.setLive2dWindowSize(scaledLive2dSize(modelFormat, currentScale))" in pet
    assert pet.index("configureDefaultSurfaceFormat(initialVsync)") < pet.index("QApplication app")
    assert "&bandori::Live2dGlWidget::runtimeReady" in pet
    assert "apply_default_state" in live2d_ffi
    assert "MotionPriority::Force, true" in runtime
    assert 'call_method::<bool>("isFinished", ())' in runtime
    assert "select_default_motion" in runtime
    assert "select_default_expression" in runtime
    assert "rendererRestartRequired" in window
    assert 'QStringLiteral("gpu_acceleration")' in window
    assert "AA_UseSoftwareOpenGL" in pet
    assert "AA_UseDesktopOpenGL" in pet
    assert 'qEnvironmentVariable("BANDORI_GPU_ACCELERATION")' in pet
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


def test_native_pixel_pet_uses_qt_sprite_animation_and_rust_mode_specific_persistence():
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    config = source("rust/crates/bandori-core/src/config.rs")
    widget_header = source("native/qt/live2d_gl_widget.h")
    widget = source("native/qt/live2d_gl_widget.cpp")
    pet = source("native/qt/pet_main.cpp")
    radial_menu = source("native/qt/native_radial_menu.cpp")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    window = source("native/qt/native_main_window.cpp")
    main = source("main.py")

    assert "pub pixel_window_x: i64" in dashboard
    assert "pub pixel_window_y: i64" in dashboard
    assert "pub pet_mode: String" in config
    assert "pixel_pet_state_preserves_live2d_geometry_and_uses_pixel_position" in config
    assert 'entry.insert("pixel_window_x".into()' in config
    assert "enum class RenderMode" in widget_header
    assert "bool loadPixelSprite" in widget_header
    assert "bool setPixelMode(bool enabled)" in widget_header
    assert "void Live2dGlWidget::advancePixelFrame()" in widget
    assert "void Live2dGlWidget::stepPixelWander()" in widget
    assert "int Live2dGlWidget::pixelAlphaAt" in widget
    assert 'QStringLiteral("pet-mode")' in pet
    assert 'QStringLiteral("frames.json")' in pet
    assert 'action == QStringLiteral("pixel")' in pet
    assert "radialMenu.setPixelActive(widget.pixelMode())" in pet
    assert "void NativeRadialMenu::setPixelActive" in radial_menu
    assert 'QString petMode = QStringLiteral("live2d")' in supervisor_header
    assert 'QStringLiteral("--pet-mode")' in supervisor
    assert "spec.petMode" in window
    assert '"--pet-mode", pet_mode' in main


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


def test_native_control_center_restores_and_debounces_legacy_chat_geometry():
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    for key in (
        "chat_window_x",
        "chat_window_y",
        "chat_window_width",
        "chat_window_height",
    ):
        assert key in dashboard
        assert f'QStringLiteral("{key}")' in window
    assert "restoreNativeWindowGeometry" in window
    assert "QGuiApplication::screens()" in window
    assert "availableGeometry().intersects(saved)" in window
    assert "persistNativeWindowGeometry" in window
    assert "nativeWindowGeometryTimer_.setInterval(350)" in window
    assert "void moveEvent(QMoveEvent* event) override" in window_header
    assert "void resizeEvent(QResizeEvent* event) override" in window_header


def test_native_click_motion_profiles_are_rust_owned_editable_and_hot_applied():
    profiles = source("rust/crates/bandori-core/src/click_motion_profiles.rs")
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    pet = source("native/qt/pet_main.cpp")

    assert "pub fn mutate_click_motion_profiles" in profiles
    assert "pub fn click_motion_profile_summaries" in profiles
    assert "builtins_and_custom_crud_persist_model_actions_and_active_profile" in profiles
    assert '"click_motion_active_profile"' in profiles
    assert '"model_action_settings"' in profiles
    assert "click_motion_active_profile" in dashboard
    assert "click_motion_profile_name" in dashboard
    assert "mutateClickMotionProfile" in backend
    assert "mutateClickMotionProfile" in generation
    assert "qfw::ComboBox* clickMotionProfileComboBox_" in window_header
    assert "saveCurrentClickMotionProfile" in window
    assert "deleteSelectedClickMotionProfile" in window
    assert "broadcastClickMotionSettings" in window
    assert "supervisor_.broadcastSettings" in window
    assert 'QStringLiteral("click_motion_actions")' in pet


def test_native_pet_window_compatibility_and_compact_style_apply_live():
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    integrations = source("rust/crates/bandori-core/src/local_integration.rs")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    window = source("native/qt/native_main_window.cpp")
    pet = source("native/qt/pet_main.cpp")

    for key in (
        "game_topmost",
        "obs_window_capture_compatible",
        "hide_live2d_model",
        "compact_ai_window_opacity",
        "compact_ai_window_font_size",
        "compact_ai_window_background_color",
        "compact_ai_window_text_color",
    ):
        assert key in dashboard
        assert f'QStringLiteral("{key}")' in window
        assert f'QStringLiteral("{key}")' in pet
    assert "normalized_overlay_color" in integrations
    assert "bool gameTopmost = false" in supervisor_header
    assert "bool obsWindowCaptureCompatible = false" in supervisor_header
    assert "bool hideLive2dModel = false" in supervisor_header
    assert 'QStringLiteral("--game-topmost")' in supervisor
    assert 'QStringLiteral("--obs-window-capture-compatible")' in supervisor
    assert 'QStringLiteral("--hide-live2d-model")' in supervisor
    assert "applyObsWindowCaptureStyle" in pet
    assert "enforceGameTopmost" in pet
    assert "compactOverlayStyle" in pet
    assert "if (!modelHidden)" in pet


def test_native_chat_presentation_state_is_rust_owned_and_qt_applied():
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    for key in (
        "chat_avatar_paths",
        "chat_display_names",
        "chat_window_always_on_top",
        "chat_window_normal_window",
        "fluent_chat_window_enabled",
        "group_chat_sidebar_collapsed",
        "group_chat_sidebar_ratio",
        "pinned_chat_keys",
    ):
        assert f'"{key}"' in dashboard
    assert "normalized_chat_string_map" in dashboard
    assert "normalized_pinned_chat_keys" in dashboard
    assert "QSplitter* chatGroupSplitter_" in window_header
    assert "saveChatPresentationSettings" in window
    assert "toggleCurrentChatPin" in window
    assert "renameCurrentPrivateChat" in window
    assert "chooseCurrentChatAvatar" in window
    assert "toggleGroupChatSidebar" in window
    assert "applyChatWindowPolicy" in window
    assert 'QStringLiteral("chat_window_always_on_top")' in window


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


def test_native_emotion_behavior_matches_python_rules_and_reaches_qt_pet_and_tts():
    emotion = source("rust/crates/bandori-core/src/emotion_behavior.rs")
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    live2d_ffi = source("rust/crates/bandori-live2d/src/ffi.rs")
    live2d_runtime = source("rust/crates/bandori-live2d/src/runtime.rs")
    widget = source("native/qt/live2d_gl_widget.cpp")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    pet = source("native/qt/pet_main.cpp")

    assert "pub struct EmotionBehavior" in emotion
    assert "pub fn infer_emotion_behavior" in emotion
    assert "latest_action_wins_like_the_python_action_scan" in emotion
    assert "emotion_behavior_enabled" in dashboard
    assert "getEmotionBehaviorJson" in backend
    assert "infer_emotion_behavior" in backend
    assert "getEmotionBehaviorJson" in generation
    assert "bool emotionBehaviorEnabled = true" in supervisor_header
    assert 'QStringLiteral("--emotion-behavior-enabled")' in supervisor
    assert "bandori_live2d_trigger_expression_tag" in live2d_ffi
    assert "bandori_live2d_trigger_motion_tag" in live2d_ffi
    assert "pub fn trigger_expression_tag" in live2d_runtime
    assert "pub fn trigger_motion_tag" in live2d_runtime
    assert "Live2dGlWidget::triggerExpressionTag" in widget
    assert "Live2dGlWidget::triggerMotionTag" in widget
    assert "qfw::SwitchButton* emotionBehaviorSwitch_" in window_header
    assert "dispatchNativeEmotionBehavior" in window
    assert "backend_.getEmotionBehaviorJson" in window
    assert 'QStringLiteral("EMOTION\\t") + compactJson(behavior)' in window
    assert "enqueueNativeTts(chatStreamText_, character, false, ttsRate)" in window
    assert 'QStringLiteral("EMOTION\\t")' in pet
    assert "playEmotionWindowFeedback" in pet
    assert 'QStringLiteral("expression_tags")' in pet
    assert 'QStringLiteral("motion_tags")' in pet
    assert 'QStringLiteral("emotion_behavior_enabled")' in pet


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


def test_native_web_tools_are_configured_bounded_and_executed_in_rust():
    core = source("rust/crates/bandori-core/src/lib.rs")
    web = source("rust/crates/bandori-core/src/web_tools.rs")
    tools = source("rust/crates/bandori-core/src/chat_tools.rs")
    context = source("rust/crates/bandori-core/src/chat_context.rs")
    group = source("rust/crates/bandori-core/src/group_chat.rs")
    settings = source("rust/crates/bandori-core/src/llm_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod web_tools;" in core
    assert "pub struct NativeWebToolSettings" in web
    assert "async fn request_public_text_with_final_url" in web
    assert "resolve_public_addresses" in web
    assert ".resolve_to_addrs(host, addresses)" in web
    assert "Policy::none()" in web
    assert ".no_proxy()" in web
    assert "MAX_REDIRECTS" in web
    assert "MAX_FETCH_BODY_BYTES" in web
    assert "pub fn native_chat_tools_for_config" in tools
    assert "pub async fn execute_native_tool_call_with_context_async" in tools
    assert "with_native_tool_system_hint_for_config" in context
    assert "with_native_tool_system_hint_for_config" in group
    assert "web_search_enabled: bool" in settings
    assert "web_fetch_enabled: bool" in settings
    assert "execute_native_tool_call_with_context_async" in backend
    assert "qfw::SwitchButton* llmWebSearchSwitch_" in header
    assert "qfw::SwitchButton* llmWebFetchSwitch_" in header
    assert 'QStringLiteral("web_search_enabled")' in window
    assert 'QStringLiteral("web_fetch_enabled")' in window


def test_native_mcp_supports_http_stdio_responses_and_local_proxy_tools():
    workspace = source("Cargo.toml")
    core = source("rust/crates/bandori-core/src/lib.rs")
    mcp = source("rust/crates/bandori-core/src/mcp_tools.rs")
    tools = source("rust/crates/bandori-core/src/chat_tools.rs")
    settings = source("rust/crates/bandori-core/src/llm_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert '"io-util"' in workspace
    assert '"process"' in workspace
    assert "pub mod mcp_tools;" in core
    assert "pub struct NativeMcpRuntime" in mcp
    assert "struct HttpMcpClient" in mcp
    assert "struct StdioMcpClient" in mcp
    assert 'const MCP_PROTOCOL_VERSION: &str = "2025-06-18"' in mcp
    assert "notifications/initialized" in mcp
    assert '"tools/list"' in mcp
    assert '"tools/call"' in mcp
    assert "extract_stdio_message" in mcp
    assert "MAX_MCP_MESSAGE_BYTES" in mcp
    assert "MCP tool blocked by approval setting" in mcp
    assert "fn native_tool_definition" in mcp
    assert "【MCP 工具边界】" in tools
    assert "mcp_enabled: bool" in settings
    assert "mcp_servers: Vec<Value>" in settings
    assert "NativeMcpRuntime::prepare_from_path" in backend
    assert "execute_mcp_tool_call" in backend
    assert "qfw::SwitchButton* llmMcpEnabledSwitch_" in header
    assert "qfw::PlainTextEdit* llmMcpServersEdit_" in header
    assert 'QStringLiteral("mcp_servers")' in window


def test_native_computer_use_is_permissioned_cancellable_and_qt_brokered():
    core = source("rust/crates/bandori-core/src/lib.rs")
    computer = source("rust/crates/bandori-core/src/computer_tools.rs")
    tools = source("rust/crates/bandori-core/src/chat_tools.rs")
    settings = source("rust/crates/bandori-core/src/llm_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod computer_tools;" in core
    assert "pub struct NativeComputerSettings" in computer
    assert "pub fn computer_tool_definitions" in computer
    assert "pub fn allows(&self, tool_name: &str)" in computer
    assert '"computer_screenshot"' in computer
    assert '"computer_click"' in computer
    assert '"computer_type"' in computer
    assert '"computer_set_clipboard"' in computer
    assert '"computer_wait"' in computer
    assert "【Computer Use 边界】" in tools
    assert "pub extra_messages: Vec<Value>" in tools
    assert "messages.extend(result.extra_messages.iter().cloned())" in tools
    assert "computer_use_allow_mouse: bool" in settings
    assert "computer_use_allow_keyboard: bool" in settings
    assert "struct NativeComputerBroker" in backend
    assert "CancellationToken" in backend
    assert "tokio::time::timeout(Duration::from_secs(30)" in backend
    assert "fn execute_computer_tool_call(" in backend
    assert "fn valid_computer_extra_message(" in backend
    assert 'url.starts_with("data:image/png;base64,")' in backend
    assert '"completeComputerTool"' in bridge_test
    assert '"computerToolRequest"' in bridge_test
    assert '"computerToolCancel"' in bridge_test
    assert "void handleNativeComputerTool(" in header
    assert "QJsonObject computerScreenshotMetrics_" in header
    assert "&Backend::computerToolRequest" in window
    assert "backend_.completeComputerTool" in window
    assert "QTimer::singleShot" in window
    assert "pendingComputerWaitRequests_.remove(requestId)" in window
    assert "SendInput(" in window
    assert 'QStringLiteral("data:image/png;base64,")' in window
    assert "QPoint NativeMainWindow::mapNativeComputerPoint" in window


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


def test_native_tts_is_rust_owned_streamed_and_played_through_qt_multimedia():
    workspace = source("Cargo.toml")
    transport = source("rust/crates/bandori-tts/src/lib.rs")
    settings = source("rust/crates/bandori-core/src/tts_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    cmake = source("CMakeLists.txt") + source("native/qt/CMakeLists.txt")

    assert '"rust/crates/bandori-tts"' in workspace
    assert "pub struct TtsTransport" in transport
    assert "pub async fn synthesize" in transport
    assert "pub fn prepare_tts_request" in transport
    assert "struct FramedAudioDecoder" in transport
    assert "MAX_AUDIO_BYTES" in transport
    assert "pub fn clean_tts_text" in transport
    assert "pub struct NativeTtsSettings" in settings
    assert "load_native_tts_settings" in settings
    assert "save_native_tts_settings" in settings
    assert "deny_unknown_fields" in settings
    assert "tts_settings_json" in backend
    assert "startTtsSynthesis" in backend
    assert "cancelTtsSynthesis" in backend
    assert "ttsAudioEvent" in backend
    assert "QByteArray" in backend
    assert "run_tts_synthesis" in backend
    assert "startTtsSynthesis" in generation
    assert "ttsAudioEvent" in generation
    assert "QMediaPlayer* ttsMediaPlayer_" in window_header
    assert "QQueue<QTemporaryFile*> ttsAudioQueue_" in window_header
    assert "QWidget* NativeMainWindow::createTtsSettingsPage()" in window
    assert "backend_.loadTtsSettings" in window
    assert "backend_.saveTtsSettings" in window
    assert "backend_.startTtsSynthesis" in window
    assert "backend_.cancelTtsSynthesis" in window
    assert "enqueueNativeTts(chatStreamText_, character, false, ttsRate)" in window
    assert "enqueueNativeTts(text, ttsCharacter)" in window
    assert 'QStringLiteral("LIP\\t%1\\t%2\\t%3")' in window
    assert "Qt6::Multimedia" in cmake


def test_native_asr_records_with_qt_and_transcribes_through_rust():
    workspace = source("Cargo.toml")
    transport = source("rust/crates/bandori-asr/src/lib.rs")
    settings = source("rust/crates/bandori-core/src/asr_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert '"rust/crates/bandori-asr"' in workspace
    assert "pub struct AsrTransport" in transport
    assert "pub async fn transcribe" in transport
    assert "pub fn prepare_asr_request" in transport
    assert "multipart/form-data; boundary=" in transport
    assert "MAX_AUDIO_BYTES" in transport
    assert "transcript_from_payload" in transport
    assert "transport_posts_authorized_multipart_and_parses_segments" in transport
    assert "pub struct NativeAsrSettings" in settings
    assert "has_api_key" in settings
    assert "deny_unknown_fields" in settings
    assert "blank_key_preserves_secret_and_explicit_clear_removes_it" in settings
    assert "asr_settings_json" in backend
    assert "startAsrTranscription" in backend
    assert "cancelAsrTranscription" in backend
    assert "asrTranscriptionEvent" in backend
    assert "run_asr_transcription" in backend
    assert "getAsrSettingsJson" in generation
    assert "startAsrTranscription" in generation
    assert "asrTranscriptionEvent" in generation
    assert "QAudioSource* asrAudioSource_" in window_header
    assert "qfw::PushButton* chatAsrButton_" in window_header
    assert "QWidget* NativeMainWindow::createAsrSettingsPage()" in window
    assert "QMediaDevices::defaultAudioInput" in window
    assert "encodeWaveAudio" in window
    assert "backend_.loadAsrSettings" in window
    assert "backend_.saveAsrSettings" in window
    assert "backend_.startAsrTranscription" in window
    assert "backend_.cancelAsrTranscription" in window
    assert 'QStringLiteral("insert_mode")' in window
    assert 'QStringLiteral("auto_send")' in window


def test_native_screen_awareness_captures_with_qt_and_analyzes_through_rust():
    core = source("rust/crates/bandori-core/src/lib.rs")
    settings = source("rust/crates/bandori-core/src/screen_awareness_settings.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod screen_awareness_settings;" in core
    assert "pub struct NativeScreenAwarenessSettings" in settings
    assert "load_native_screen_awareness_settings" in settings
    assert "save_native_screen_awareness_settings" in settings
    assert "deny_unknown_fields" in settings
    assert "global_cooldown_minutes" in settings
    assert "screen_awareness_settings_json" in backend
    assert "startScreenAwareness" in backend
    assert "cancelScreenAwareness" in backend
    assert "screenAwarenessEvent" in backend
    assert "MAX_SCREENSHOT_BYTES" in backend
    assert "run_screen_awareness" in backend
    assert "collect_screen_awareness_text" in backend
    assert "getScreenAwarenessSettingsJson" in generation
    assert "startScreenAwareness" in generation
    assert "screenAwarenessEvent" in generation
    assert "QTimer screenAwarenessTimer_" in window_header
    assert "QWidget* NativeMainWindow::createScreenAwarenessPage()" in window
    assert "QGuiApplication::screens()" in window
    assert "screen->grabWindow(0)" in window
    assert "nativeForegroundDesktopState" in window
    assert "backend_.loadScreenAwarenessSettings" in window
    assert "backend_.saveScreenAwarenessSettings" in window
    assert "backend_.startScreenAwareness" in window
    assert "backend_.cancelScreenAwareness" in window
    assert 'QStringLiteral("NO_SPEAK")' not in window
    assert 'QStringLiteral("REMINDER_EVENT\\t")' in window
    assert "enqueueNativeTts(text, character, false, ttsRate)" in window


def test_native_special_events_drive_context_and_tray_notifications_without_python():
    core = source("rust/crates/bandori-core/src/lib.rs")
    events = source("rust/crates/bandori-core/src/special_events.rs")
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    chat = source("rust/crates/bandori-core/src/chat_context.rs")
    group_chat = source("rust/crates/bandori-core/src/group_chat.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    generation = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub mod special_events;" in core
    assert "pub struct SpecialEvent" in events
    assert "pub fn load_today_special_events" in events
    assert "pub fn build_special_event_context" in events
    assert "MAX_EVENT_DATABASE_BYTES" in events
    assert "leap_day_events_are_valid_and_inactive_in_non_leap_years" in events
    assert "birthday_tray_notifications_enabled" in dashboard
    assert "【今日特殊事件】" in chat
    assert "【今日特殊事件】" in group_chat
    assert "special_events_json" in backend
    assert "fn load_special_events(" in backend
    assert "native_special_event_context" in backend
    assert "getSpecialEventsJson" in generation
    assert "loadSpecialEvents" in generation
    assert "QTimer specialEventTimer_" in window_header
    assert "qfw::SwitchButton* birthdayNotificationsSwitch_" in window_header
    assert "backend_.loadSpecialEvents" in window
    assert "void NativeMainWindow::pollNativeSpecialEvents()" in window
    assert "scheduleNativeSpecialEventPoll" in window
    assert "currentLocalDateTime()" in window


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


def test_native_packaging_separates_read_only_resources_from_writable_user_data():
    submodules = source(".gitmodules")
    cmake = source("CMakeLists.txt")
    native_cmake = source("native/qt/CMakeLists.txt")
    main = source("native/qt/main.cpp")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    desktop = source("packaging/linux/bandoripet.desktop")

    assert "third_party/Qt-Fluent-Widgets" in submodules
    assert "third_party/Live2D-v2-Lua" in submodules
    assert "APP_VERSION" in cmake
    assert "BANDORI_PET_RESOURCE_DESTINATION" in cmake
    assert "BANDORI_PET_PACKAGE_BUNDLED_MODELS" in cmake
    assert "third_party/Live2D-v2-Lua/live2d" in cmake
    assert 'set(CPACK_GENERATOR "ZIP;NSIS")' in cmake
    assert 'set(CPACK_GENERATOR "DragNDrop")' in cmake
    assert 'set(CPACK_GENERATOR "TGZ;DEB")' in cmake
    assert "qt_generate_deploy_app_script" in native_cmake
    assert "MACOSX_BUNDLE_GUI_IDENTIFIER" in native_cmake
    assert "INSTALL_RPATH" in native_cmake
    assert "discoverBandoriResourceRoot" in main
    assert 'QStringLiteral("data-root")' in main
    assert 'QStringLiteral("config")' in main
    assert "QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)" in main
    assert 'QStringLiteral(".bandoripet-native-package")' in main
    assert "QString dataRoot" in header
    assert "QString dataRoot_" in header
    assert "QString NativeMainWindow::nativeDatabasePath() const" in window
    assert 'QDir(projectRoot_).filePath(QStringLiteral("data.db"))' not in window
    assert "QString configPath" in supervisor_header
    assert "QString configPath_" in supervisor_header
    assert "const QByteArray configPath = configPath_.toUtf8()" in supervisor
    assert "Exec=BandoriPet" in desktop


def test_native_auto_start_is_cross_platform_and_transactional_with_config():
    dashboard = source("rust/crates/bandori-core/src/dashboard.rs")
    auto_start_header = source("native/qt/native_autostart.h")
    auto_start = source("native/qt/native_autostart.cpp")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    native_cmake = source("native/qt/CMakeLists.txt")

    assert "pub auto_start: bool" in dashboard
    assert "pub auto_start: Option<bool>" in dashboard
    assert 'config.set("auto_start", Value::Bool(enabled))' in dashboard
    assert "nativeAutoStartArguments" in auto_start_header
    assert "Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Run" in auto_start
    assert "RegSetValueExW" in auto_start
    assert "Library/LaunchAgents/io.github.helpeadice.bandoripet.plist" in auto_start
    assert "QStandardPaths::ConfigLocation" in auto_start
    assert "X-GNOME-Autostart-enabled=true" in auto_start
    assert "QSaveFile" in auto_start
    assert "autoStartSwitch_" in window_header
    assert 'QStringLiteral("auto_start"), desiredAutoStart' in window
    assert "applyNativeAutoStart(previousAutoStart" in window
    assert "reconcileNativeAutoStart();" in window
    assert "native_autostart.cpp" in native_cmake
    assert "advapi32" in native_cmake


def test_native_startup_migrates_legacy_mutable_data_before_opening_rust_state():
    core = source("rust/crates/bandori-core/src/lib.rs")
    migration = source("rust/crates/bandori-core/src/legacy_migration.rs")
    ffi = source("rust/crates/bandori-core/src/config_ffi.rs")
    ffi_header = source("native/qt/bandori_config_ffi.h")
    main = source("native/qt/main.cpp")

    assert "pub mod legacy_migration;" in core
    assert "pub fn migrate_legacy_data(" in migration
    assert "MAX_CONFIG_BYTES" in migration
    assert "atomic_write" in migration
    assert "atomic_copy" in migration
    assert "wal_checkpoint(TRUNCATE)" in migration
    assert "rebase_database_attachments" in migration
    assert 'PathBuf::from("chat_attachments")' in migration
    assert 'PathBuf::from("models")' in migration
    assert 'Path::new(".runtime").join("chat_avatars")' in migration
    assert "SymbolicLink" in migration
    assert "MIGRATION_MARKER" in migration
    assert "migration_copies_mutable_data_rebases_paths_and_is_idempotent" in migration
    assert "bandori_config_migrate_legacy_data" in ffi
    assert "bandori_config_migrate_legacy_data" in ffi_header
    assert 'QStringLiteral("legacy-data-root")' in main
    assert "discoverLegacyDataRoot" in main
    assert "defaultPackagedDataRoot" in main
    assert "bandori_config_migrate_legacy_data" in main
    assert "return 3;" in main


def test_native_loopback_integrations_are_bounded_redacted_and_pet_visible():
    core = source("rust/crates/bandori-core/src/lib.rs")
    integration = source("rust/crates/bandori-core/src/local_integration.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")
    pet_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    pet = source("native/qt/pet_main.cpp")

    assert "pub mod local_integration;" in core
    assert "Ipv4Addr::LOCALHOST" in integration
    assert "MAX_BODY_BYTES: usize = 1024 * 1024" in integration
    assert "WORKERS_PER_SERVICE: usize = 4" in integration
    assert "PENDING_CONNECTIONS: usize = 32" in integration
    assert "constant_time_eq" in integration
    assert "normalize_onebot_event" in integration
    assert "add_external_chat_message" in integration
    assert "mark_external_chat_read" in integration
    assert "loopback_server_authenticates_stores_deduplicates_and_marks_read" in integration
    assert "ai_status_token_configured" in integration
    assert "chat_token_configured" in integration
    assert "integration_settings_json" in backend
    assert "integration_status_json" in backend
    assert "NativeIntegrationServer" in backend
    assert "fn start_integration_services(" in backend
    assert "fn stop_integration_services(" in backend
    assert "integration_event" in backend
    assert '"getIntegrationSettingsJson"' in bridge_test
    assert '"startIntegrationServices"' in bridge_test
    assert '"integrationEvent"' in bridge_test
    assert "QWidget* createIntegrationPage()" in header
    assert "backend_.startIntegrationServices" in window
    assert 'QStringLiteral("CHAT_EVENT\\t")' in window
    assert 'QStringLiteral("AI_EVENT\\t")' in window
    assert "compactAiWindowEnabled" in pet_header
    assert 'QStringLiteral("--compact-ai-window-enabled")' in supervisor
    assert 'QStringLiteral("CHAT_EVENT\\t")' in pet
    assert 'QStringLiteral("AI_EVENT\\t")' in pet
    assert 'state == QStringLiteral("clear")' in pet


def test_native_napcat_uses_qt_websocket_and_rust_policy_reply_pipeline():
    cmake = source("CMakeLists.txt")
    native_cmake = source("native/qt/CMakeLists.txt")
    core = source("rust/crates/bandori-core/src/lib.rs")
    napcat = source("rust/crates/bandori-core/src/napcat.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    bridge_test = source("rust/crates/bandori-core/tests/qt_bridge_generation.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "WebSockets" in cmake
    assert "Qt6::WebSockets" in native_cmake
    assert "pub mod napcat;" in core
    assert "pub fn ingest_native_napcat_event" in napcat
    assert "pub fn prepare_native_napcat_reply" in napcat
    assert "group_at_policy_stores_once_and_requests_reply" in napcat
    assert "overlay_only_does_not_persist" in napcat
    assert "access_token_configured" in napcat
    assert "napcat_reply_cancellations" in backend
    assert "run_napcat_reply" in backend
    assert '"napcatReplyEvent"' in bridge_test
    assert "QWebSocket* napcatSocket_" in header
    assert "void NativeMainWindow::startNativeNapcat()" in window
    assert "setMaxAllowedIncomingMessageSize(1024 * 1024)" in window
    assert 'QByteArrayLiteral("Authorization")' in window
    assert 'QStringLiteral("access_token")' in window
    assert "backend_.ingestNapcatEvent" in window
    assert "backend_.deleteNapcatRecords" in window
    assert "backend_.startNapcatReply" in window
    assert "kMaximumConcurrentNapcatReplies = 4" in window
    assert 'QStringLiteral("send_group_msg")' in window
    assert 'QStringLiteral("send_private_msg")' in window


def test_native_proactive_companion_is_managed_scheduled_and_policy_aware():
    core = source("rust/crates/bandori-core/src/reminder.rs")
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub struct ProactiveCompanion" in core
    assert "pub fn normalize_proactive_companion" in core
    assert "pub fn compute_next_proactive_at" in core
    assert "tick_config_reminders_with_desktop_state" in core
    assert "evaluate_proactive_care" in core
    assert 'config.get("proactive_companion")' in core
    assert 'config.set("proactive_care_policy"' in core
    assert '"update_proactive_item"' in core
    assert "desktop_state_json: &QString" in backend
    assert "defer_overdue_proactive: bool" in backend
    assert "qfw::SwitchButton* proactiveEnabledSwitch_" in header
    assert "bool deferOverdueProactiveReminders_ = true" in header
    assert "void NativeMainWindow::saveSelectedNativeProactiveItem()" in window
    assert "compactJson(nativeForegroundDesktopState())" in window
    assert "codingProcesses" in window
    assert "gameProcesses" in window
    assert 'QStringLiteral("idle")' in window
    assert 'QStringLiteral("proactive_companion")' in window
    assert 'QStringLiteral("proactive_kind")' in window
