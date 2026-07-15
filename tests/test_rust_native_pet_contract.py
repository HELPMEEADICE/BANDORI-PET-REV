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
    backend = source("rust/crates/bandori-qt-bridge/src/backend.rs")
    supervisor_header = source("native/qt/pet_process_supervisor.h")
    supervisor = source("native/qt/pet_process_supervisor.cpp")
    window_header = source("native/qt/native_main_window.h")
    window = source("native/qt/native_main_window.cpp")

    assert "pub fn parse_chat_response" in actions
    assert "generated_python_action_vectors_match_rust" in actions
    assert "parse_chat_response" in backend
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
