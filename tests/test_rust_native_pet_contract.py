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


def test_python_supervisor_keeps_native_renderer_opt_in_and_full_fallback():
    main = source("main.py")

    assert 'BANDORI_PET_NATIVE_RENDERER", ""' in main
    assert 'BANDORI_PET_NATIVE_RENDERER_PATH", ""' in main
    assert '"--hit-alpha-threshold"' in main
    assert '"--move-all-roles-together"' in main
    assert "using Python renderer" in main
