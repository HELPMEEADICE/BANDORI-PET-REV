"""System-output metering and an underdamped, audio-driven squash/stretch.

The Windows backend reads Core Audio's output peak meter. It never opens a
microphone or records audio, and COM objects stay on their owning worker thread.
"""

import ctypes
import logging
import math
import sys
import threading
import time
import uuid

from PySide6.QtCore import QEvent, QObject, Qt, QTimer


log = logging.getLogger(__name__)
MUSIC_BOUNCE_KEY = "music_bounce_enabled"


def music_bounce_supported() -> bool:
    return sys.platform == "win32"


class _GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    def __init__(self, value):
        super().__init__((ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(value).bytes_le))


def _com_method(pointer, index, result_type, *argument_types):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(table[index])


def _check_hresult(result):
    if result < 0:
        raise OSError(f"Core Audio HRESULT 0x{result & 0xFFFFFFFF:08X}")


def _release(pointer):
    if pointer:
        _com_method(pointer, 2, ctypes.c_ulong)(pointer)


class _WindowsOutputMeter:
    """A thread-local meter for the default multimedia rendering endpoint.

    https://learn.microsoft.com/windows/win32/coreaudio/peak-meters
    """

    def __init__(self):
        self._ole = ctypes.WinDLL("ole32")
        self._ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        self._ole.CoInitializeEx.restype = ctypes.c_long
        self._ole.CoUninitialize.argtypes = []
        self._ole.CoUninitialize.restype = None
        self._ole.CoCreateInstance.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_ulong,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p),
        ]
        self._ole.CoCreateInstance.restype = ctypes.c_long
        self._enumerator = ctypes.c_void_p()
        self._meter = ctypes.c_void_p()
        self._read_peak = None
        self._refresh_at = 0.0
        _check_hresult(self._ole.CoInitializeEx(None, 0))
        try:
            _check_hresult(self._ole.CoCreateInstance(
                ctypes.byref(_GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")),
                None, 1,
                ctypes.byref(_GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")),
                ctypes.byref(self._enumerator),
            ))
            self._bind_default_endpoint()
        except Exception:
            self.close()
            raise

    def _bind_default_endpoint(self):
        device = ctypes.c_void_p()
        meter = ctypes.c_void_p()
        try:
            # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eMultimedia).
            _check_hresult(_com_method(
                self._enumerator, 4, ctypes.c_long,
                ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
            )(self._enumerator, 0, 1, ctypes.byref(device)))
            # IMMDevice::Activate(IID_IAudioMeterInformation).
            _check_hresult(_com_method(
                device, 3, ctypes.c_long, ctypes.POINTER(_GUID), ctypes.c_ulong,
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            )(
                device, ctypes.byref(_GUID("C02216F6-8C67-4B5B-9D00-D008E73E0064")),
                23, None, ctypes.byref(meter),
            ))
        except Exception:
            _release(meter)
            raise
        finally:
            _release(device)
        _release(self._meter)
        self._meter = meter
        self._read_peak = _com_method(meter, 3, ctypes.c_long, ctypes.POINTER(ctypes.c_float))
        # Rebind after headphone/speaker changes, including when the old endpoint
        # still exists. Do this on the worker, never in a GUI timer callback.
        self._refresh_at = time.monotonic() + 2.0

    def read(self):
        if time.monotonic() >= self._refresh_at:
            self._bind_default_endpoint()
        peak = ctypes.c_float()
        _check_hresult(self._read_peak(self._meter, ctypes.byref(peak)))
        return float(peak.value)

    def close(self):
        _release(self._meter)
        _release(self._enumerator)
        self._meter = ctypes.c_void_p()
        self._enumerator = ctypes.c_void_p()
        self._ole.CoUninitialize()


class OutputLevelMonitor:
    """Latest-value mailbox; stopping never blocks the UI on a device call."""

    def __init__(self, meter_factory=_WindowsOutputMeter):
        self._meter_factory = meter_factory
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._peak = 0.0
        self._sample_at = 0.0
        self._thread = threading.Thread(target=self._run, name="music-output-meter", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def level(self):
        with self._lock:
            if self._stop.is_set() or time.monotonic() - self._sample_at > 0.25:
                return 0.0
            return self._peak

    def _run(self):
        reported_error = False
        while not self._stop.is_set():
            meter = None
            try:
                meter = self._meter_factory()
                while not self._stop.is_set():
                    peak = meter.read()
                    with self._lock:
                        self._peak = peak if math.isfinite(peak) else 0.0
                        self._sample_at = time.monotonic()
                    reported_error = False
                    if self._stop.wait(1.0 / 60.0):
                        break
            except Exception:
                with self._lock:
                    self._peak = 0.0
                    self._sample_at = 0.0
                if not reported_error:
                    log.warning("Music bounce output meter unavailable; retrying", exc_info=True)
                    reported_error = True
            finally:
                if meter is not None:
                    meter.close()
            if self._stop.wait(1.0):
                break


class MusicSpring:
    """Beat impulses plus a softly driven spring, with visible overshoot.

    The fast/slow envelope difference detects musical attacks. An adaptive peak
    keeps quieter tracks lively; a noise gate prevents movement during silence.
    Physics uses small time steps so motion is stable across rendering rates.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.position = 0.0
        self.velocity = 0.0
        self._fast = 0.0
        self._slow = 0.0
        self._reference = 0.08
        self._cooldown = 0.0

    def step(self, peak: float, dt: float) -> float:
        if not math.isfinite(dt) or dt <= 0:
            return self.position
        dt = min(dt, 0.1)
        peak = max(0.0, min(1.0, peak)) if math.isfinite(peak) else 0.0
        if peak < 0.003:
            peak = 0.0
        self._reference = max(0.08, peak, self._reference * math.exp(-dt / 2.0))
        level = min(1.0, peak / self._reference)
        self._fast += (level - self._fast) * (1.0 - math.exp(-dt / 0.025))
        self._slow += (level - self._slow) * (1.0 - math.exp(-dt / 0.22))
        self._cooldown = max(0.0, self._cooldown - dt)
        attack = self._fast - self._slow
        if peak and attack > 0.075 and self._cooldown <= 0.0:
            self.velocity -= 4.0 + min(1.0, attack * 3.0) * 6.0
            self._cooldown = 0.18
        target = -0.32 * self._fast
        steps = max(1, math.ceil(dt * 240))
        h = dt / steps
        for _ in range(steps):
            # omega=15 rad/s, damping ratio=0.23: a springy ~0.43 s cycle.
            self.velocity += (-225.0 * (self.position - target) - 6.9 * self.velocity) * h
            self.position += self.velocity * h
        self.position = max(-1.6, min(0.9, self.position))
        if peak == 0 and abs(self.position) < 0.001 and abs(self.velocity) < 0.01:
            self.position = self.velocity = 0.0
        return self.position


def _stop_monitors(monitors):
    while monitors:
        monitors.pop().stop()


class MusicBounceController(QObject):
    """Drive vertical model scaling without moving or resizing the window."""

    def __init__(self, window, can_animate, apply_scale, monitor_factory=OutputLevelMonitor):
        super().__init__(window)
        self._window = window
        self._can_animate = can_animate
        self._apply_scale = apply_scale
        self._monitor_factory = monitor_factory
        self._monitor = None
        self._monitor_cleanup = []
        self._enabled = False
        self._scale = 1.0
        self._spring = MusicSpring()
        self._last_tick = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        window.installEventFilter(self)
        # Capture only the worker holder: Python QObject attributes may already
        # be cleared when Qt emits destroyed during interpreter shutdown.
        window.destroyed.connect(lambda _obj=None, monitors=self._monitor_cleanup: _stop_monitors(monitors))

    def set_enabled(self, enabled):
        self._enabled = bool(enabled) and music_bounce_supported()
        if self._enabled and self._window.isVisible():
            self._last_tick = time.monotonic()
            self._timer.start()
        else:
            self.suspend()

    def _stop_monitor(self):
        _stop_monitors(self._monitor_cleanup)
        self._monitor = None

    def suspend(self):
        self._timer.stop()
        self._stop_monitor()
        self.reset()

    def _set_scale(self, scale):
        if scale != self._scale:
            self._scale = scale
            self._apply_scale(scale)

    def reset(self):
        self._spring.reset()
        self._set_scale(1.0)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.Show:
            self.set_enabled(self._enabled)
        elif kind in (QEvent.Type.Hide, QEvent.Type.Close):
            self.suspend()
        return False

    def _tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now
        if not self._enabled or not self._window.isVisible():
            self.suspend()
            return
        if not self._can_animate():
            self.reset()
            self._stop_monitor()
            self._timer.setInterval(150)
            return
        self._timer.setInterval(16)
        if self._monitor is None:
            self._monitor = self._monitor_factory()
            self._monitor_cleanup.append(self._monitor)
            self._monitor.start()
        displacement = self._spring.step(self._monitor.level(), dt)
        # Strong beats squash the model; underdamped overshoot stretches it
        # back up. Width and all window geometry remain unchanged.
        self._set_scale(max(0.65, min(1.20, 1.0 + displacement * 0.32)))
