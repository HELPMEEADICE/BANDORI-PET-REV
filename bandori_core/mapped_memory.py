"""OS memory mappings shared by Python UI processes and the Rust pet.

The data plane is mmap (no socket or stdio transport). A byte-range lock on
Windows and flock on Unix serialize writers with Rust's fs2 locks. The owner
lock is separate so a crashed creator can be reclaimed without resetting a
live queue. Files live in a private, per-user temporary directory.
"""

from enum import IntEnum
import hashlib
import mmap
import os
from pathlib import Path
import tempfile
import threading


def queue_file_path(key: str) -> Path:
    user = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    directory = Path(tempfile.gettempdir()) / ("bandori-ipc-" + hashlib.sha256(user.encode()).hexdigest()[:16])
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / (hashlib.sha256(key.encode("utf-8")).hexdigest() + ".shm")


def _lock(file, *, blocking=True):
    if os.name == "nt":
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))


def _unlock(file):
    if os.name == "nt":
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class MappedMemory:
    """Small storage interface used by SharedMemoryLineQueue."""

    class SharedMemoryError(IntEnum):
        UnknownError = 0
        AlreadyExists = 4

    def __init__(self, key):
        self.path = queue_file_path(key)
        self._file = None
        self._owner = None
        self._mapping = None
        self._error = self.SharedMemoryError.UnknownError
        self._message = ""
        self._thread_lock = threading.RLock()

    def create(self, size):
        try:
            self._owner = open(str(self.path) + ".owner", "a+b")
            try:
                _lock(self._owner, blocking=False)
            except OSError:
                self._owner.close()
                self._owner = None
                self._error = self.SharedMemoryError.AlreadyExists
                self._message = "queue already has a live owner"
                return False
            self._file = open(self.path, "a+b")
            _lock(self._file)
            try:
                self._file.truncate(size)
                self._mapping = mmap.mmap(self._file.fileno(), size)
            finally:
                _unlock(self._file)
            return True
        except OSError as exc:
            self._message = str(exc)
            self.detach()
            return False

    def attach(self):
        try:
            self._file = open(self.path, "r+b")
            self._mapping = mmap.mmap(self._file.fileno(), 0)
            return True
        except (OSError, ValueError) as exc:
            self._message = str(exc)
            self.detach()
            return False

    def detach(self):
        if self._mapping is not None:
            self._mapping.close()
            self._mapping = None
        if self._file is not None:
            self._file.close()
            self._file = None
        owner = self._owner
        self._owner = None
        # Try after every participant detaches. On Windows the owner's unlink
        # may fail while readers still map the file; the final reader retries.
        # Keep the owner lock filename stable to avoid splitting OS locks.
        if owner is not None:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            owner.close()
        else:
            try:
                with open(str(self.path) + ".owner", "a+b") as candidate:
                    _lock(candidate, blocking=False)
                    try:
                        self.path.unlink(missing_ok=True)
                    finally:
                        _unlock(candidate)
            except OSError:
                pass

    def isAttached(self):
        return self._mapping is not None

    def lock(self):
        self._thread_lock.acquire()
        try:
            _lock(self._file)
            return True
        except OSError:
            self._thread_lock.release()
            return False

    def unlock(self):
        try:
            _unlock(self._file)
        finally:
            self._thread_lock.release()

    def data(self):
        return self._mapping

    def error(self):
        return self._error

    def errorString(self):
        return self._message
