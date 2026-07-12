import uuid


def _unique_key(prefix: str) -> str:
    return f"test-{prefix}-{uuid.uuid4().hex}"


def test_shared_memory_queue_delivers_lines_in_order():
    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("order")
    writer = SharedMemoryLineQueue.create(key, slot_count=4, slot_size=256)
    reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    try:
        assert writer.publish("ACTION\tkasumi\twave\n")
        assert writer.publish("SETTINGS\t{}")

        assert reader.read_available() == ["ACTION\tkasumi\twave", "SETTINGS\t{}"]
        assert reader.read_available() == []
    finally:
        reader.close()
        writer.close()


def test_shared_memory_queue_readers_have_independent_cursors():
    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("cursors")
    writer = SharedMemoryLineQueue.create(key, slot_count=4, slot_size=256)
    first_reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    second_reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    try:
        writer.publish("PEER_POS\t{\"x\":1}")

        assert first_reader.read_available() == ["PEER_POS\t{\"x\":1}"]
        assert second_reader.read_available() == ["PEER_POS\t{\"x\":1}"]
    finally:
        second_reader.close()
        first_reader.close()
        writer.close()


def test_shared_memory_queue_overflow_returns_recent_complete_messages():
    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("overflow")
    writer = SharedMemoryLineQueue.create(key, slot_count=2, slot_size=256)
    reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    try:
        writer.publish("one")
        writer.publish("two")
        writer.publish("three")

        assert reader.read_available() == ["two", "three"]
    finally:
        reader.close()
        writer.close()


def test_default_shared_memory_queue_accepts_large_settings_payloads():
    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("large")
    writer = SharedMemoryLineQueue.create(key)
    reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    large_line = "SETTINGS\t" + ("x" * 32768)
    try:
        assert writer.publish(large_line)
        assert reader.read_available() == [large_line]
    finally:
        reader.close()
        writer.close()


def test_closed_shared_memory_queue_read_write_are_noops():
    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("closed")
    queue = SharedMemoryLineQueue.create(key, slot_count=1, slot_size=128)
    queue.close()

    assert not queue.publish("ACTION\tkasumi\twave")
    assert queue.read_available() == []


def test_default_shared_memory_queue_stays_below_macos_shared_memory_budget():
    from shared_memory_ipc import (
        _DEFAULT_SLOT_COUNT,
        _DEFAULT_SLOT_SIZE,
        _queue_memory_size,
    )

    assert _queue_memory_size(_DEFAULT_SLOT_COUNT, _DEFAULT_SLOT_SIZE) < 4 * 1024 * 1024
    assert _DEFAULT_SLOT_SIZE >= 32768


def test_main_and_radial_ipc_fit_macos_shared_memory_budget():
    from shared_memory_ipc import (
        _DEFAULT_SLOT_COUNT,
        _DEFAULT_SLOT_SIZE,
        _queue_memory_size,
    )

    main_ipc_bytes = 3 * _queue_memory_size(_DEFAULT_SLOT_COUNT, _DEFAULT_SLOT_SIZE)
    radial_ipc_bytes = _queue_memory_size(8, 8192) + _queue_memory_size(8, 4096)

    assert main_ipc_bytes + radial_ipc_bytes < 4 * 1024 * 1024


def test_main_uses_a_separate_control_queue_for_reliable_commands():
    from pathlib import Path

    bus_source = Path("ipc_bus.py").read_text(encoding="utf-8")
    main_source = Path("main.py").read_text(encoding="utf-8")
    pet_source = Path("pet_window.py").read_text(encoding="utf-8")

    assert "def ipc_control_queue_key()" in bus_source
    assert 'ipc_ref.get("control")' in main_source
    assert '"_ipc_control_queue"' in pet_source


def test_main_resends_latest_settings_to_new_ipc_peers():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")

    assert 'ipc_ref["latest_settings_line"] = line' in source
    assert 'latest_settings_line = ipc_ref.get("latest_settings_line", "")' in source
    assert "if is_new_peer and latest_settings_line:" in source


def test_main_registers_new_ipc_peer_before_touching_heartbeat():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")
    read_flow = source.split("    def read_ipc_messages", 1)[1].split(
        "    def touch_ipc_peer", 1
    )[0]

    register_check = 'if envelope.line.startswith("REGISTER\\t"):'
    assert register_check in read_flow
    assert 'handle_ipc_line(envelope.line, source_peer_id=envelope.sender_id)' in read_flow
    assert read_flow.index(register_check) < read_flow.index(
        "touch_ipc_peer(envelope.sender_id)"
    )


def test_ipc_envelope_round_trips_sender_and_exclusion():
    from shared_memory_ipc import decode_ipc_envelope, encode_ipc_envelope

    encoded = encode_ipc_envelope(
        "peer-1",
        "SETTINGS\t{\"dark_theme\":true}\n",
        exclude_peer_id="peer-2",
    )

    decoded = decode_ipc_envelope(encoded)

    assert decoded.sender_id == "peer-1"
    assert decoded.exclude_peer_id == "peer-2"
    assert decoded.line == 'SETTINGS\t{"dark_theme":true}'


def test_internal_process_ipc_no_longer_uses_qt_local_sockets():
    from pathlib import Path

    internal_ipc_files = [
        "ipc_bus.py",
        "main.py",
        "settings_process.py",
        "chat_process.py",
        "pet_window.py",
        "radial_menu_process.py",
    ]

    for file_name in internal_ipc_files:
        source = Path(file_name).read_text(encoding="utf-8")
        assert "QLocalSocket" not in source
        assert "QLocalServer" not in source


def test_main_clears_stale_pet_peers_when_pet_processes_close():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")

    assert 'clear_ipc_peers("PET")' in source


def test_main_retries_ipc_with_fresh_session_name_on_create_failure():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")

    assert "refresh_ipc_session_name()" in source


def test_settings_process_falls_back_to_stdout_for_launch_messages():
    from pathlib import Path

    source = Path("settings_process.py").read_text(encoding="utf-8")

    assert "def _stdout_fallback_line" in source
    assert 'line.startswith(("MODEL\\t", "SETTINGS\\t")) or line in {"LAUNCH", "EXIT"}' in source
    assert "print(line, flush=True)" in source


def test_main_reads_settings_process_stdout_fallback():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")

    assert "def _read_settings_process_output(process)" in source
    assert "process.readyReadStandardOutput.connect" in source
    assert "handle_settings_line(line)" in source


def test_main_relaunches_active_pet_when_model_message_changes_selection():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")

    assert "def has_active_pet_processes()" in source
    assert "model_changed and has_active_pet_processes()" in source
