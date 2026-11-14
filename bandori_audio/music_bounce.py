"""Music Bounce configuration and lifecycle of the shared native audio service.

Python never samples audio, advances physics or sends frame-level scale commands.
The unused legacy MusicSpring/OutputLevelMonitor/MusicBounceController APIs were
removed; the frozen algorithm lives only in tests/baselines for parity checks.
"""
import logging
import json
import sys
import uuid

from PySide6.QtCore import QObject, QProcess, QTimer

log = logging.getLogger(__name__)
MUSIC_BOUNCE_KEY = "music_bounce_enabled"


def music_bounce_supported() -> bool:
    return sys.platform == "win32"


class NativeMusicService(QObject):
    """One producer per main application; stdin EOF revokes its lifetime.

    source_changed receives a path only after READY. Restarts always use a new
    generation, so surviving role processes cannot mistake stale data for music.
    Timers run only during startup failure/recovery or bounded shutdown.
    """
    def __init__(self, parent, source_changed, *, diagnostics=False):
        super().__init__(parent)
        self._source_changed = source_changed
        self._wanted = False
        self._closed = False
        self._stopping = False
        self.path = None
        self._candidate = None
        self._diagnostics = diagnostics
        self.metrics = None
        self._process = QProcess(self)
        self._process.readyReadStandardOutput.connect(self._read_ready)
        self._process.readyReadStandardError.connect(self._read_error)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._process_error)
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(1000)
        self._retry.timeout.connect(self._start)
        self._stop_timeout = QTimer(self)
        self._stop_timeout.setSingleShot(True)
        self._stop_timeout.setInterval(1500)
        self._stop_timeout.timeout.connect(self._process.kill)

    def set_running(self, wanted):
        self._wanted = bool(wanted) and music_bounce_supported() and not self._closed
        if self._wanted:
            if not self._retry.isActive():
                self._start()
        else:
            self._retry.stop()
            self._publish(None)
            if self._process.state() != QProcess.ProcessState.NotRunning and not self._stopping:
                self._stopping = True
                self._process.closeWriteChannel()
                self._stop_timeout.start()

    def _publish(self, path):
        if self.path != path:
            self.path = path
            self._source_changed(path)

    def _start(self):
        if not self._wanted or self._process.state() != QProcess.ProcessState.NotRunning:
            return
        from bandori_core.mapped_memory import queue_file_path
        from bandori_core.native_pet import native_executable
        from bandori_core.process_utils import app_base_dir
        try:
            executable = native_executable(app_base_dir())
            self._candidate = str(queue_file_path("music-" + uuid.uuid4().hex))
            self._stopping = False
            self._process.setProgram(str(executable))
            arguments = ["--music-service", self._candidate]
            if self._diagnostics:
                arguments.append("--music-metrics")
            self._process.setArguments(arguments)
            self._process.start()
        except (OSError, RuntimeError):
            log.warning("Cannot start native music service; retrying", exc_info=True)
            self._retry.start()

    def _read_ready(self):
        while self._process.canReadLine():
            line = bytes(self._process.readLine()).strip()
            if line == b"READY" and self._wanted and not self._stopping:
                self._publish(self._candidate)
            elif self._diagnostics and line.startswith(b"METRICS "):
                self.metrics = json.loads(line[8:])

    def _read_error(self):
        message = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if message:
            log.warning("Native music: %s", message)

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            log.warning("Native music service failed to start: %s", self._process.errorString())
            self._finished()

    def _finished(self, *_):
        self._stop_timeout.stop()
        self._publish(None)
        if self._candidate:
            from bandori_core._pet_ipc import cleanup_music_level
            try:
                cleanup_music_level(self._candidate)
            except RuntimeError:
                log.warning("Native music mapping cleanup deferred to last reader", exc_info=True)
            self._candidate = None
        self._stopping = False
        if self._wanted:
            self._retry.start()

    def close(self):
        self._closed = True
        self.set_running(False)
        if self._process.state() != QProcess.ProcessState.NotRunning:
            if not self._process.waitForFinished(1500):
                self._process.kill()
                self._process.waitForFinished(500)
        self._stop_timeout.stop()
