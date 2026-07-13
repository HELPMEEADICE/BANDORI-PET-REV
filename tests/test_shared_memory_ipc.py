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


def test_peer_position_batches_keep_only_the_latest_update_per_character():
    from shared_memory_ipc import (
        coalesce_latest_peer_positions,
        encode_ipc_envelope,
    )

    kasumi_old = encode_ipc_envelope(
        "pet-kasumi", 'PEER_POS\t{"character":"kasumi","x":1,"y":2}'
    )
    action = encode_ipc_envelope("pet-kasumi", "ACTION\tkasumi\twave")
    ran_old = encode_ipc_envelope(
        "pet-ran", 'PEER_POS\t{"character":"ran","x":3,"y":4}'
    )
    malformed = encode_ipc_envelope("pet-bad", "PEER_POS\tnot-json")
    kasumi_new = encode_ipc_envelope(
        "pet-kasumi", 'PEER_POS\t{"character":"kasumi","x":5,"y":6}'
    )
    ran_new = encode_ipc_envelope(
        "pet-ran", 'PEER_POS\t{"character":"ran","x":7,"y":8}'
    )

    assert coalesce_latest_peer_positions([
        kasumi_old,
        action,
        ran_old,
        malformed,
        kasumi_new,
        ran_new,
    ]) == [action, malformed, kasumi_new, ran_new]


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
        assert reader.dropped_messages == 1
    finally:
        reader.close()
        writer.close()


def test_reliable_and_lossy_lanes_keep_reliable_commands_during_lossy_overflow():
    from shared_memory_ipc import SharedMemoryLineQueue

    lossy_key = _unique_key("lossy-lane")
    reliable_key = _unique_key("reliable-lane")
    lossy_writer = SharedMemoryLineQueue.create(lossy_key, slot_count=2, slot_size=256)
    reliable_writer = SharedMemoryLineQueue.create(
        reliable_key, slot_count=4, slot_size=256
    )
    lossy_reader = SharedMemoryLineQueue.attach(lossy_key, start_at_tail=False)
    reliable_reader = SharedMemoryLineQueue.attach(reliable_key, start_at_tail=False)
    try:
        for number in range(10):
            assert lossy_writer.publish(f"PEER_POS\t{number}")
        assert reliable_writer.publish("SETTINGS\t{}")
        assert reliable_writer.publish("CHAT_EVENT\t{}")

        assert reliable_reader.read_available() == ["SETTINGS\t{}", "CHAT_EVENT\t{}"]
        assert lossy_reader.read_available() == ["PEER_POS\t8", "PEER_POS\t9"]
        assert lossy_reader.dropped_messages == 8
    finally:
        reliable_reader.close()
        lossy_reader.close()
        reliable_writer.close()
        lossy_writer.close()


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
    assert "def ipc_reliable_inbound_queue_key()" in bus_source
    assert "def is_reliable_ipc_line" in bus_source
    assert 'ipc_ref.get("control")' in main_source
    assert 'ipc_ref.get("reliable_inbound")' in main_source
    assert '"_ipc_control_queue"' in pet_source
    assert '"_ipc_reliable_inbound_queue"' in pet_source


def test_reliable_classifier_covers_control_and_user_visible_events():
    from ipc_bus import is_reliable_ipc_line

    for line in (
        "REGISTER\tPET\tkasumi",
        "UNREGISTER\tPET\tkasumi",
        "PEER_OFFLINE\t{}",
        "RADIAL_MENU_OPEN\t{}",
        "RADIAL_MENU_CLOSED\t{}",
        "SETTINGS\t{}",
        "MODEL\tkasumi",
        "CHAT_EVENT\t{}",
        "REMINDER_EVENT\t{}",
        "POKE_USER\tkasumi",
    ):
        assert is_reliable_ipc_line(line)

    assert not is_reliable_ipc_line("PEER_POS\t{}")


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

    register_check = 'if envelope.line.startswith(("REGISTER\\t", "UNREGISTER\\t")):'
    assert register_check in read_flow
    assert 'handle_ipc_line(envelope.line, source_peer_id=envelope.sender_id)' in read_flow
    assert read_flow.index(register_check) < read_flow.index(
        "touch_ipc_peer(envelope.sender_id)"
    )


def test_offline_character_detection_ignores_overlapping_pet_processes():
    from ipc_bus import pet_characters_without_active_peers

    removed = [
        {"kind": "PET", "character": "Kasumi"},
        {"kind": "PET", "character": "Ran"},
        {"kind": "CHAT", "character": "Aya"},
    ]
    active = [
        {"kind": "PET", "character": "Kasumi"},
        {"kind": "SETTINGS", "character": "Ran"},
    ]

    assert pet_characters_without_active_peers(removed, active) == ["Ran"]


def test_main_broadcasts_reliable_offline_events_for_unregister_and_timeout():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8")

    assert 'if line.startswith("UNREGISTER\\t"):' in source
    assert 'broadcast_ipc_line(f"PEER_OFFLINE\\t{payload}")' in source
    assert "broadcast_offline_pet_characters(remove_ipc_peers(stale))" in source
    assert "def is_registered_pet_peer(peer_id: str) -> bool:" in source
    assert "if is_registered_pet_peer(source_peer_id):" in source


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


def test_create_reclaims_stale_segment_left_by_killed_owner():
    import os
    import subprocess
    import sys

    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("stale")
    # Simulate a force-killed owner: the child creates the queue and exits via
    # os._exit, skipping detach, so the System V segment is left behind with
    # zero attaches (the kernel detaches on death but never removes).
    script = (
        "import os, sys\n"
        "from shared_memory_ipc import SharedMemoryLineQueue\n"
        f"SharedMemoryLineQueue.create({key!r}, slot_count=2, slot_size=256)\n"
        "os._exit(0)\n"
    )
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        check=True,
        timeout=30,
    )

    # Without reclamation this raises AlreadyExists; with it the stale
    # segment is destroyed and the queue is recreated with a fresh header.
    writer = SharedMemoryLineQueue.create(key, slot_count=2, slot_size=256)
    reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    try:
        assert writer.publish("RECOVERED")
        assert reader.read_available() == ["RECOVERED"]
    finally:
        reader.close()
        writer.close()


def test_create_does_not_tear_down_live_segment():
    import pytest

    from shared_memory_ipc import SharedMemoryLineQueue

    key = _unique_key("live")
    writer = SharedMemoryLineQueue.create(key, slot_count=2, slot_size=256)
    reader = SharedMemoryLineQueue.attach(key, start_at_tail=False)
    try:
        with pytest.raises(RuntimeError):
            SharedMemoryLineQueue.create(key, slot_count=2, slot_size=256)

        # The failed create must not have destroyed or reset the live queue.
        assert writer.publish("STILL\tALIVE")
        assert reader.read_available() == ["STILL\tALIVE"]
    finally:
        reader.close()
        writer.close()
