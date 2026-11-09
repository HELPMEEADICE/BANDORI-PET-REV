# Frozen pre-migration implementation. Tests/benchmarks ONLY; no runtime fallback.
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



import hashlib
import json
import os
import struct
import uuid
from dataclasses import dataclass



_MAGIC = b"BDIPC01!"
_VERSION = 1
_HEADER = struct.Struct("<8sIIIQ")
_SLOT_HEADER = struct.Struct("<QI")
_DEFAULT_SLOT_COUNT = 8
_DEFAULT_SLOT_SIZE = 65536
_DEFAULT_FALLBACK_SLOT_COUNTS = (8, 4, 2)


def _queue_memory_size(slot_count: int, slot_size: int) -> int:
    return _HEADER.size + int(slot_count) * (_SLOT_HEADER.size + int(slot_size))


def _queue_slot_count_candidates(
    slot_count: int,
    *,
    using_default: bool,
    fallback_slot_counts: tuple[int, ...] | None,
) -> list[int]:
    candidates = [max(1, int(slot_count))]
    fallback_counts = (
        _DEFAULT_FALLBACK_SLOT_COUNTS
        if using_default and fallback_slot_counts is None
        else fallback_slot_counts or ()
    )
    for count in fallback_counts:
        count = max(1, int(count))
        if count < candidates[0] and count not in candidates:
            candidates.append(count)
    return candidates


@dataclass(frozen=True)
class IpcEnvelope:
    sender_id: str
    line: str
    exclude_peer_id: str = ""
    message_id: str = ""
    reliable: bool = False


def normalize_ipc_line(line: str) -> str:
    return str(line or "").rstrip("\r\n")


def make_shared_memory_key(*parts: object) -> str:
    raw = "::".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    label = "-".join(str(part or "") for part in parts[-2:]) or "ipc"
    label = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in label)[:48]
    return f"BandoriPet-{label}-{digest}"


def make_peer_id(prefix: str = "peer") -> str:
    return f"{prefix}-{os.getpid()}-{uuid.uuid4().hex[:12]}"


def encode_ipc_envelope(
    sender_id: str,
    line: str,
    exclude_peer_id: str = "",
    message_id: str = "",
    reliable: bool = False,
) -> str:
    return json.dumps(
        {
            "sender": str(sender_id or ""),
            "exclude": str(exclude_peer_id or ""),
            "line": normalize_ipc_line(line),
            "message_id": str(message_id or ""),
            "reliable": bool(reliable),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_ipc_envelope(value: str) -> IpcEnvelope:
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return IpcEnvelope("", normalize_ipc_line(value))
    if not isinstance(data, dict):
        return IpcEnvelope("", normalize_ipc_line(value))
    return IpcEnvelope(
        str(data.get("sender", "") or ""),
        normalize_ipc_line(str(data.get("line", "") or "")),
        str(data.get("exclude", "") or ""),
        str(data.get("message_id", "") or ""),
        bool(data.get("reliable", False)),
    )


def coalesce_latest_peer_positions(raw_lines: list[str]) -> list[str]:
    """Keep only the newest coalescible peer update for each state stream."""
    retained: list[str] = []
    seen_streams: set[str] = set()
    for raw_line in reversed(raw_lines):
        envelope = decode_ipc_envelope(raw_line)
        stream_key = ""
        event_name = ""
        if envelope.line.startswith("PEER_POS\t"):
            event_name = "PEER_POS"
        elif envelope.line.startswith("PEER_DRAG\t"):
            event_name = "PEER_DRAG"
        if event_name:
            try:
                payload = json.loads(envelope.line.split("\t", 1)[1])
            except (IndexError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                character = str(payload.get("character", "") or "").strip()
                if event_name == "PEER_POS" and character:
                    stream_key = f"position:{character}"
                elif event_name == "PEER_DRAG" and character:
                    drag_id = str(payload.get("drag_id", "") or "").strip()
                    if drag_id:
                        stream_key = f"drag:{character}:{drag_id}"
        if stream_key:
            if stream_key in seen_streams:
                continue
            seen_streams.add(stream_key)
        retained.append(raw_line)
    retained.reverse()
    return retained


class SharedMemoryLineQueue:
    def __init__(self, key: str, memory: MappedMemory, *, slot_count: int, slot_size: int, cursor: int):
        self.key = key
        self.slot_count = int(slot_count)
        self.slot_size = int(slot_size)
        self._memory = memory
        self._cursor = int(cursor)
        self.dropped_messages = 0
        self.last_publish_error = ""

    @classmethod
    def create(
        cls,
        key: str,
        *,
        slot_count: int | None = None,
        slot_size: int | None = None,
        fallback_slot_counts: tuple[int, ...] | None = None,
    ) -> "SharedMemoryLineQueue":
        using_default_slot_count = slot_count is None
        slot_count = _DEFAULT_SLOT_COUNT if slot_count is None else slot_count
        slot_size = _DEFAULT_SLOT_SIZE if slot_size is None else slot_size
        slot_count = max(1, int(slot_count))
        slot_size = max(64, int(slot_size))
        candidates = _queue_slot_count_candidates(
            slot_count,
            using_default=using_default_slot_count,
            fallback_slot_counts=fallback_slot_counts,
        )

        errors = []
        for candidate_count in candidates:
            memory = MappedMemory(key)
            size = _queue_memory_size(candidate_count, slot_size)
            created = memory.create(size)
            if created:
                queue = cls(key, memory, slot_count=candidate_count, slot_size=slot_size, cursor=0)
                queue._initialize()
                return queue
            errors.append(f"{size} bytes: {memory.errorString()}")
        raise RuntimeError(f"Failed to create shared memory '{key}': {'; '.join(errors) or 'no attempts made'}")

    @classmethod
    def attach(cls, key: str, *, start_at_tail: bool = True) -> "SharedMemoryLineQueue":
        memory = MappedMemory(key)
        if not memory.attach():
            raise RuntimeError(f"Failed to attach shared memory '{key}': {memory.errorString()}")
        queue = cls(key, memory, slot_count=1, slot_size=64, cursor=0)
        magic, version, slot_count, slot_size, next_seq = queue._read_header_locked()
        if (magic != _MAGIC or version != _VERSION or slot_count < 1 or slot_size < 64
                or _queue_memory_size(slot_count, slot_size) != len(memory.data())):
            memory.detach()
            raise RuntimeError(f"Shared memory '{key}' is not a Bandori IPC queue")
        queue.slot_count = slot_count
        queue.slot_size = slot_size
        queue._cursor = next_seq if start_at_tail else max(0, next_seq - slot_count)
        return queue

    def close(self) -> None:
        memory = self._memory
        self._memory = None
        if memory is not None and memory.isAttached():
            memory.detach()

    def is_attached(self) -> bool:
        return self._memory is not None and self._memory.isAttached()

    def publish(self, line: str) -> bool:
        payload = normalize_ipc_line(line).encode("utf-8")
        if not payload or len(payload) > self.slot_size:
            self.last_publish_error = "empty payload" if not payload else f"payload exceeds {self.slot_size} bytes"
            return False
        self.last_publish_error = ""
        if not self.is_attached():
            self.last_publish_error = "queue is detached"
            return False
        memory = self._memory
        if memory is None or not memory.lock():
            self.last_publish_error = "queue lock failed"
            return False
        try:
            data = memory.data()
            if data is None:
                self.last_publish_error = "queue memory is unavailable"
                return False
            view = memoryview(data)
            magic, version, slot_count, slot_size, next_seq = self._read_header(view)
            if magic != _MAGIC or version != _VERSION:
                self.last_publish_error = "queue header is invalid"
                return False
            slot_index = next_seq % slot_count
            offset = _HEADER.size + slot_index * (_SLOT_HEADER.size + slot_size)
            _SLOT_HEADER.pack_into(view, offset, next_seq, len(payload))
            payload_start = offset + _SLOT_HEADER.size
            view[payload_start:payload_start + len(payload)] = payload
            self._write_header(view, slot_count, slot_size, next_seq + 1)
            return True
        finally:
            memory.unlock()

    def read_available(self, max_messages: int | None = None) -> list[str]:
        if max_messages is not None:
            max_messages = max(0, int(max_messages))
            if max_messages == 0:
                return []
        if not self.is_attached():
            return []
        memory = self._memory
        if memory is None or not memory.lock():
            return []
        try:
            data = memory.data()
            if data is None:
                return []
            view = memoryview(data)
            magic, version, slot_count, slot_size, next_seq = self._read_header(view)
            if magic != _MAGIC or version != _VERSION:
                return []
            first_available = max(0, next_seq - slot_count)
            if self._cursor < first_available:
                self.dropped_messages += first_available - self._cursor
                self._cursor = first_available
            messages = []
            seq = self._cursor
            while seq < next_seq and (max_messages is None or len(messages) < max_messages):
                slot_index = seq % slot_count
                offset = _HEADER.size + slot_index * (_SLOT_HEADER.size + slot_size)
                slot_seq, length = _SLOT_HEADER.unpack_from(view, offset)
                if slot_seq == seq and 0 < length <= slot_size:
                    payload_start = offset + _SLOT_HEADER.size
                    messages.append(bytes(view[payload_start:payload_start + length]).decode("utf-8", errors="replace"))
                seq += 1
            self._cursor = seq
            return messages
        finally:
            memory.unlock()

    def _initialize(self) -> None:
        if not self._memory.lock():
            raise RuntimeError(f"Failed to lock shared memory '{self.key}'")
        try:
            self._write_header(memoryview(self._memory.data()), self.slot_count, self.slot_size, 0)
        finally:
            self._memory.unlock()

    def _read_header_locked(self):
        if not self._memory.lock():
            raise RuntimeError(f"Failed to lock shared memory '{self.key}'")
        try:
            return self._read_header(memoryview(self._memory.data()))
        finally:
            self._memory.unlock()

    @staticmethod
    def _read_header(view):
        return _HEADER.unpack_from(view, 0)

    @staticmethod
    def _write_header(view, slot_count: int, slot_size: int, next_seq: int) -> None:
        _HEADER.pack_into(view, 0, _MAGIC, _VERSION, int(slot_count), int(slot_size), int(next_seq))
