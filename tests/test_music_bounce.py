import math
import os
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QWidget

import bandori_audio.music_bounce as music_bounce
from bandori_audio.music_bounce import MusicBounceController, MusicSpring, OutputLevelMonitor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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


def test_monitor_retries_after_device_failure_and_releases_on_own_thread():
    sampled = threading.Event()
    owner_threads = []
    attempts = []

    class Meter:
        reads = 0

        def read(self):
            owner_threads.append(threading.get_ident())
            self.reads += 1
            if self.reads >= 2:
                sampled.set()
            return 0.7

        def close(self):
            owner_threads.append(threading.get_ident())

    def factory():
        attempts.append(threading.get_ident())
        if len(attempts) == 1:
            raise OSError("endpoint disconnected")
        return Meter()

    monitor = OutputLevelMonitor(factory)
    monitor.start()
    try:
        assert sampled.wait(2)
        assert monitor.level() == 0.7
    finally:
        monitor.stop()
        monitor._thread.join(1)

    assert len(attempts) == 2
    assert set(owner_threads) == {attempts[-1]}
    assert attempts[-1] != threading.get_ident()
    assert not monitor._thread.is_alive()
    assert monitor.level() == 0.0


def test_monitor_stop_is_immediate_even_when_device_is_busy():
    reading, unblock, closed = threading.Event(), threading.Event(), threading.Event()

    class Meter:
        def read(self):
            reading.set()
            unblock.wait(2)
            return 0.9

        def close(self):
            closed.set()

    monitor = OutputLevelMonitor(Meter)
    monitor.start()
    try:
        assert reading.wait(1)
        monitor.stop()
        assert monitor.level() == 0.0
    finally:
        unblock.set()
        monitor.stop()
        monitor._thread.join(1)
    assert closed.is_set()


def test_stale_samples_are_silenced(monkeypatch):
    monitor = OutputLevelMonitor()
    monitor._peak = 0.8
    monitor._sample_at = 10.0
    monkeypatch.setattr(music_bounce.time, "monotonic", lambda: 11.0)
    assert monitor.level() == 0.0


@pytest.fixture
def scaled_window(app, monkeypatch):
    monkeypatch.setattr(music_bounce, "music_bounce_supported", lambda: True)
    window = QWidget(None, Qt.WindowType.FramelessWindowHint)
    window.setGeometry(100, 100, 180, 240)
    window.show()
    app.processEvents()
    monitor = SimpleNamespace(start=Mock(), stop=Mock(), peak=0.8)
    monitor.level = lambda: monitor.peak
    allowed, scales = [True], []
    controller = MusicBounceController(window, lambda: allowed[0], scales.append, lambda: monitor)
    controller.set_enabled(True)
    controller._timer.stop()
    clock = [100.0]
    monkeypatch.setattr(music_bounce.time, "monotonic", lambda: clock[0])
    controller._last_tick = clock[0]

    def tick(count=1):
        for _ in range(count):
            clock[0] += 1 / 60
            controller._tick()

    yield window, controller, monitor, allowed, scales, tick
    controller.set_enabled(False)
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_music_squashes_then_stretches_without_moving_or_resizing_window(scaled_window):
    window, _, monitor, _, scales, tick = scaled_window
    geometry = window.geometry()
    tick(5)
    assert min(scales) < 0.85
    monitor.peak = 0.0
    tick(240)
    assert max(scales) > 1.05
    assert scales[-1] == 1.0
    assert window.geometry() == geometry
    monitor.start.assert_called_once()


def test_disable_restores_model_proportions_and_stops_audio(scaled_window):
    window, controller, monitor, _, scales, tick = scaled_window
    geometry = window.geometry()
    tick(8)
    controller.set_enabled(False)
    assert scales[-1] == 1.0
    assert window.geometry() == geometry
    monitor.stop.assert_called_once()
    assert not controller._timer.isActive()


def test_drag_pause_restores_proportions_and_external_moves_are_respected(scaled_window):
    window, controller, _, allowed, scales, tick = scaled_window
    tick(8)
    allowed[0] = False
    tick()
    assert scales[-1] == 1.0
    assert controller._monitor is None
    window.move(150, 180)
    geometry = window.geometry()
    allowed[0] = True
    tick(8)
    assert scales[-1] < 1.0
    assert window.geometry() == geometry


def test_hiding_stops_audio_and_restores_model_then_showing_resumes(scaled_window):
    window, controller, monitor, _, scales, tick = scaled_window
    tick(8)
    window.hide()
    assert scales[-1] == 1.0
    assert not controller._timer.isActive()
    monitor.stop.assert_called_once()
    window.show()
    assert controller._timer.isActive()


def test_unsupported_platform_starts_no_audio_worker(app, monkeypatch):
    monkeypatch.setattr(music_bounce, "music_bounce_supported", lambda: False)
    window = QWidget()
    factory = Mock()
    controller = MusicBounceController(window, lambda: True, Mock(), factory)
    window.show()
    controller.set_enabled(True)
    controller._tick()
    factory.assert_not_called()
    assert not controller._timer.isActive()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_destroying_window_stops_audio_worker(app, monkeypatch):
    monkeypatch.setattr(music_bounce, "music_bounce_supported", lambda: True)
    window = QWidget()
    window.show()
    monitor = SimpleNamespace(start=Mock(), stop=Mock(), level=lambda: 0.0)
    controller = MusicBounceController(window, lambda: True, Mock(), lambda: monitor)
    controller.set_enabled(True)
    controller._tick()
    monitor.start.assert_called_once()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    monitor.stop.assert_called_once()
