"""Native parity, process boundaries and service lifecycle regressions."""
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QCoreApplication, QProcess
from bandori_audio.music_bounce import NativeMusicService
from tests.baselines.music_spring import MusicSpring

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def native_binary(name, example=False):
    suffix = ".exe" if os.name == "nt" else ""
    path = ROOT / "native/pet_backend/target/debug"
    if example:
        path /= "examples"
    path /= name + suffix
    if not path.is_file():
        pytest.skip(f"Build native binary first: {path}")
    return path


def pump(app, predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_silence_and_noise_do_not_move_the_spring():
    spring = MusicSpring()
    for _ in range(120):
        assert spring.step(0.002, 1 / 60) == 0.0


def test_beat_has_lift_rebound_and_eventually_settles():
    spring = MusicSpring()
    positions = [spring.step(0.8 if frame < 5 else 0.0, 1 / 60) for frame in range(240)]

    assert min(positions) < -0.5
    assert max(positions[10:]) > 0.15
    assert positions[-1] == 0.0
    assert spring.velocity == 0.0


def test_strong_beats_move_more_than_barely_audible_audio():
    def lift(level):
        spring = MusicSpring()
        return -min(spring.step(level if frame < 5 else 0, 1 / 60) for frame in range(60))

    assert lift(0.8) > lift(0.01) * 1.4


@pytest.mark.parametrize("fps", [30, 60, 144])
def test_spring_remains_bounded_at_different_frame_rates(fps):
    spring = MusicSpring()
    positions = []
    for frame in range(fps * 12):
        # 120 BPM attacks; silence after 8 seconds.
        peak = 0.7 if frame / fps < 8 and (frame / fps) % 0.5 < 0.08 else 0.0
        positions.append(spring.step(peak, 1 / fps))

    assert all(math.isfinite(value) and -1.6 <= value <= 0.9 for value in positions)
    assert min(positions) < -0.4
    assert max(positions) > 0.15
    assert abs(positions[-1]) < 0.001


def test_invalid_samples_and_delayed_frames_cannot_poison_physics():
    spring = MusicSpring()
    for peak, dt in [(float("nan"), 1 / 60), (float("inf"), 1 / 60), (0.5, 10), (1, -1)]:
        assert math.isfinite(spring.step(peak, dt))
    previous = spring.position
    assert spring.step(1, float("nan")) == previous


@pytest.mark.parametrize("fps", [30, 60, 144])
def test_rust_trace_matches_frozen_python_for_beats_volume_changes_and_invalid_data(fps):
    binary = native_binary("music_trace", True)
    spring = MusicSpring()
    samples = []
    for frame in range(fps * 20):
        t = frame / fps
        # Continuous beats, soft music after loud music and a silent tail.
        peak = (0.8 if t < 4 else 0.012) if t < 14 and t % 0.5 < 0.08 else 0.0
        samples.append((peak, 1 / fps))
    samples += [(p, d) for p in [math.nan, math.inf, -math.inf, -1, 2, 0.002, 0.003]
                for d in [math.nan, math.inf, -1, 0, 1e-300, 0.03, 10]]
    expected = [spring.step(p, d) for p, d in samples]
    trace = "\n".join(f"{p} {d}" for p, d in samples) + "\nreset\n0.8 0.03\n"
    result = subprocess.run([str(binary)], input=trace, text=True, capture_output=True, check=True, timeout=10)
    actual = [float(v) for v in result.stdout.splitlines()]
    assert actual[:-1] == pytest.approx(expected, abs=1e-11, rel=1e-11)
    assert actual[-1] == pytest.approx(MusicSpring().step(0.8, 0.03), abs=1e-11)


def peer_command(process, line):
    process.stdin.write(line + "\n")
    process.stdin.flush()
    return process.stdout.readline().strip()


def test_multiple_process_consumers_survive_producer_crash_and_generation_restart(tmp_path):
    binary = native_binary("level_peer", True)
    path = tmp_path / "level"
    processes = []

    def start(mode, target=path):
        process = subprocess.Popen([str(binary), mode, str(target)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        processes.append(process)
        assert process.stdout.readline().strip() == "READY"
        return process

    try:
        producer = start("producer")
        readers = [start("consumer") for _ in range(4)]
        assert peer_command(producer, "0.75 1000") == "true"
        assert [float(peer_command(r, "1000")) for r in readers] == [0.75] * 4
        producer.stdin.write("abort\n")
        producer.stdin.flush()
        assert producer.wait(timeout=5) == 13
        assert [float(peer_command(r, "1251")) for r in readers] == [0.0] * 4
        # The next generation can run while old consumers are still mapped.
        new = start("producer", tmp_path / "next-level")
        assert peer_command(new, "0.25 1400") == "true"
        assert path.exists()
        for reader in readers:
            reader.stdin.close()
            assert reader.wait(timeout=5) == 0
        assert not path.exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.stdin.close()
                process.wait(timeout=5)


def test_native_service_pipe_eof_cleans_mapping_without_gui_or_python(tmp_path):
    binary = native_binary("bandori-pet-native")
    path = tmp_path / "音楽.shm"
    process = subprocess.Popen([str(binary), "--music-service", str(path)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == b"READY"
        assert path.stat().st_size == 40
        process.stdin.close()
        assert process.wait(timeout=5) == 0
        assert not path.exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_native_service_exits_after_parent_crashes(tmp_path):
    binary = native_binary("bandori-pet-native")
    path = tmp_path / "parent-crash.shm"
    parent = subprocess.run([sys.executable, "-c", (
        "import os,subprocess,sys; "
        "p=subprocess.Popen([sys.argv[1],'--music-service',sys.argv[2]],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL); "
        "assert p.stdout.readline().strip()==b'READY'; "
        "print(p.pid,flush=True); os._exit(0)"
    ), str(binary), str(path)], capture_output=True, text=True, check=True, timeout=10)
    assert int(parent.stdout.strip()) > 0
    deadline = time.monotonic() + 5
    while path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not path.exists()


def test_native_manager_restart_disable_and_no_periodic_python_work(app, monkeypatch):
    binary = native_binary("bandori-pet-native")
    monkeypatch.setenv("BANDORI_PET_NATIVE", str(binary))
    monkeypatch.setattr("bandori_audio.music_bounce.music_bounce_supported", lambda: True)
    changes = []
    manager = NativeMusicService(None, changes.append)
    try:
        manager.set_running(True)
        pump(app, lambda: manager.path is not None)
        first, pid = manager.path, manager._process.processId()
        assert not manager._retry.isActive()
        assert not manager._stop_timeout.isActive()
        manager.set_running(True)
        assert manager._process.processId() == pid
        manager._process.kill()
        pump(app, lambda: manager.path is not None and manager.path != first)
        assert None in changes
        manager.set_running(False)
        assert manager.path is None
        pump(app, lambda: manager._process.state() == QProcess.ProcessState.NotRunning)
        assert not manager._retry.isActive()
        assert not Path(first).exists()  # also reclaims producer killed before any consumer attached
    finally:
        manager.close()


def test_unsupported_platform_starts_no_service(app, monkeypatch):
    monkeypatch.setattr("bandori_audio.music_bounce.music_bounce_supported", lambda: False)
    manager = NativeMusicService(None, Mock())
    manager._start = Mock()
    manager.set_running(True)
    manager._start.assert_not_called()
    assert not manager._retry.isActive()
    manager.close()
