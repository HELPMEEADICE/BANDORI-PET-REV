"""Legacy storage facade and stable queue naming. All mapping/locking is Rust.

MappedMemory.data() exposes a transaction snapshot: refresh on lock, commit on
unlock. As before, callers must lock around shared reads/writes. Application
queues use NativeQueue directly and never copy the entire mapping across FFI.
"""
from enum import IntEnum
import hashlib
import os
from pathlib import Path
import tempfile
import threading


def queue_file_path(key: str) -> Path:
    user = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    directory = Path(tempfile.gettempdir()) / ("bandori-ipc-" + hashlib.sha256(user.encode()).hexdigest()[:16])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".shm")


class MappedMemory:
    """Compatibility lock/data/unlock API backed by pet-ipc storage."""

    class SharedMemoryError(IntEnum):
        UnknownError = 0
        AlreadyExists = 4

    def __init__(self, key):
        self.path = queue_file_path(key)
        self._native = None
        self._mapping = None
        self._error = self.SharedMemoryError.UnknownError
        self._message = ""
        self._thread_lock = threading.RLock()
        self._depth = 0

    def _open(self, size=None):
        from bandori_core._pet_ipc import NativeMemory
        with self._thread_lock:
            if self._native is not None:
                self._message = "memory is already attached"
                return False
            try:
                self._native = (NativeMemory.attach(self.path) if size is None
                                else NativeMemory.create(self.path, int(size)))
                self._mapping = bytearray(self._native.snapshot())
                return True
            except (RuntimeError, OverflowError) as exc:
                self._message = str(exc)
                if "live owner" in self._message:
                    self._error = self.SharedMemoryError.AlreadyExists
                self.detach()
                return False

    def create(self, size):
        return self._open(size)

    def attach(self):
        return self._open()

    def detach(self):
        with self._thread_lock:
            if self._native is not None:
                self._native.close()
                self._native = None
            self._mapping = None

    def isAttached(self):
        return self._native is not None

    def lock(self):
        self._thread_lock.acquire()
        try:
            if self._native is None:
                self._message = "queue is detached"
                self._thread_lock.release()
                return False
            if self._depth == 0:
                self._mapping[:] = self._native.lock()
            self._depth += 1
            return True
        except RuntimeError as exc:
            self._message = str(exc)
            self._thread_lock.release()
            return False

    def unlock(self):
        try:
            if self._depth == 1 and self._native is not None:
                self._native.unlock(self._mapping)
        finally:
            self._depth = max(0, self._depth - 1)
            self._thread_lock.release()

    def data(self):
        return self._mapping

    def error(self):
        return self._error

    def errorString(self):
        return self._message
