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


def test_python_supervisor_keeps_native_renderer_opt_in_and_full_fallback():
    main = source("main.py")

    assert 'BANDORI_PET_NATIVE_RENDERER", ""' in main
    assert 'BANDORI_PET_NATIVE_RENDERER_PATH", ""' in main
    assert '"--hit-alpha-threshold"' in main
    assert '"--move-all-roles-together"' in main
    assert "using Python renderer" in main
