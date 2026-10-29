"""Exercise the real Rust process against Python's shared-memory queues."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

from bandori_core.native_pet import native_executable, native_program_and_args
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, decode_ipc_envelope, encode_ipc_envelope


ROOT = Path(__file__).resolve().parents[1]


def test_native_launcher_imports_no_gui_or_lua_runtime():
    output = subprocess.check_output([sys.executable, "-c", (
        "import pet_process,sys; "
        "assert not any(k.startswith(('PySide6','lupa','OpenGL','bandori_live2d.live2d_lua')) for k in sys.modules); "
        "print('native launcher')"
    )], cwd=ROOT, text=True)
    assert output.strip() == "native launcher"


def test_missing_native_binary_has_build_instructions(monkeypatch, tmp_path):
    monkeypatch.setenv("BANDORI_PET_NATIVE", str(tmp_path / "missing.exe"))
    with pytest.raises(FileNotFoundError, match="cargo build"):
        native_executable(ROOT)


def test_music_updates_cannot_fill_the_reliable_command_queue():
    from bandori_core.ipc_bus import is_reliable_ipc_line
    assert not is_reliable_ipc_line('NATIVE_CONTROL\t{"character":"kasumi","command":"music_scale","scale":1.0}')
    assert is_reliable_ipc_line('NATIVE_CONTROL\t{"character":"kasumi","command":"snapshot","path":"frame.png"}')


@pytest.fixture
def backend(tmp_path):
    try:
        binary = native_executable(ROOT)
    except FileNotFoundError:
        pytest.skip("Build native/pet_backend before running native integration tests")
    from bandori_core.mapped_memory import queue_file_path
    queues = [SharedMemoryLineQueue.create("native-test-" + uuid.uuid4().hex, slot_count=32) for _ in range(4)]
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"fps": 120, "opacity": 0.8, "models": [{"character": "愛音", "costume": "制服", "path": "missing.model3.json"}]}), encoding="utf-8")
    _, args = native_program_and_args(ROOT, "愛音", "制服", "missing.model3.json", config_path=config, data_dir=tmp_path)
    flags = ["--inbound", "--reliable-inbound", "--broadcast", "--control"]
    for flag, queue in zip(flags, queues):
        args[args.index(flag) + 1] = str(queue_file_path(queue.key))
    args.extend(["--headless", "--exit-after", "15"])
    process = subprocess.Popen([str(binary), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy())
    pending = []

    def receive(event, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for queue in queues[:2]:
                for line in queue.read_available():
                    envelope = decode_ipc_envelope(line)
                    if envelope.line.startswith("NATIVE_EVENT\t"):
                        pending.append(json.loads(envelope.line.split("\t", 1)[1]))
            for index, item in enumerate(pending):
                if item["event"] == event:
                    return pending.pop(index)["data"]
            if process.poll() is not None:
                pytest.fail("native exited: " + process.communicate(timeout=1)[1].decode(errors="replace"))
            time.sleep(0.01)
        pytest.fail(f"native event {event} timed out")

    def send(line, reliable=True):
        assert queues[3 if reliable else 2].publish(encode_ipc_envelope("test-controller", line, reliable=reliable))

    try:
        assert receive("ready")["backend"] == "neocari"
        yield process, send, receive, queues, config
    finally:
        if process.poll() is None:
            send("SHUTDOWN")
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
        for queue in queues:
            queue.close()


def test_real_rust_process_preserves_settings_unicode_and_control_lane(backend):
    process, send, receive, queues, config_path = backend
    original = config_path.read_bytes()
    # Fill the lossy channel; settings and shutdown have their own queue.
    for index in range(100):
        send('PEER_POS\t' + json.dumps({"character": "kasumi", "x": index, "y": 0}), reliable=False)
    send('SETTINGS\t' + json.dumps({"fps": 60, "opacity": 0.45, "dark_theme": True,
        "model_action_settings": {"愛音\t制服": {"default_motion": "smile01", "click_motion_actions": {"head": {"motion": "bye01", "expression": "smile"}}}}}, ensure_ascii=False))
    send('LIP\t愛音\t0.7\t-0.2')
    send('NATIVE_CONTROL\t' + json.dumps({"character": "愛音", "command": "status"}, ensure_ascii=False))
    state = receive("status")
    assert state["fps"] == 60
    assert state["opacity"] == pytest.approx(0.45)
    assert state["mouth"] == pytest.approx([0.7, -0.2])
    assert state["models"][0]["character"] == "愛音"
    assert state["models"][0]["default_motion"] == "smile01"
    assert config_path.read_bytes() == original  # Rust is never a second config writer.
    send("SHUTDOWN")
    process.communicate(timeout=5)
    assert process.returncode == 0


def test_rust_ignores_non_target_commands_and_malformed_settings(backend):
    _, send, receive, _, _ = backend
    send('SETTINGS\t[]')
    send('SETTINGS\t' + json.dumps({"fps": "bad", "opacity": 0.6, "model_action_settings": []}))
    send('LIP\tother\t1.0')
    send('NATIVE_CONTROL\t' + json.dumps({"character": "愛音", "command": "status"}, ensure_ascii=False))
    state = receive("status")
    assert state["fps"] == 120
    assert state["opacity"] == pytest.approx(0.6)
    assert state["mouth"][0] == 0.0
