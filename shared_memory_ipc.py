from __future__ import annotations

import hashlib
import json
import os
import struct
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QSharedMemory


_MAGIC = b"BDIPC01!"
_VERSION = 1
_HEADER = struct.Struct("<8sIIIQ")
_SLOT_HEADER = struct.Struct("<QI")
# Keep the default queues small enough for macOS's conservative System V shared
# memory budget while still allowing large SETTINGS payloads in a single slot.
_DEFAULT_SLOT_COUNT = 16
_DEFAULT_SLOT_SIZE = 65536
_DEFAULT_FALLBACK_SLOT_COUNTS = (16, 12, 8, 4)


def _queue_memory_size(slot_count: int, slot_size: int) -> int:
    return _HEADER.size + int(slot_count) * (_SLOT_HEADER.size + int(slot_size))


@dataclass(frozen=True)
class IpcEnvelope:
    sender_id: str
    line: str
    exclude_peer_id: str = ""


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


def encode_ipc_envelope(sender_id: str, line: str, exclude_peer_id: str = "") -> str:
    return json.dumps(
        {
            "sender": str(sender_id or ""),
            "exclude": str(exclude_peer_id or ""),
            "line": normalize_ipc_line(line),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_ipc_envelope(value: str) -> IpcEnvelope:
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return IpcEnvelope("", normalize_ipc_line(value), "")
    if not isinstance(data, dict):
        return IpcEnvelope("", normalize_ipc_line(value), "")
    return IpcEnvelope(
        str(data.get("sender", "") or ""),
        normalize_ipc_line(str(data.get("line", "") or "")),
        str(data.get("exclude", "") or ""),
    )


class SharedMemoryLineQueue:
    def __init__(
        self,
        key: str,
        memory: QSharedMemory,
        *,
        slot_count: int,
        slot_size: int,
        cursor: int,
        owner: bool,
    ):
        self.key = key
        self.slot_count = int(slot_count)
        self.slot_size = int(slot_size)
        self._memory = memory
        self._cursor = int(cursor)
        self._owner = bool(owner)

    @classmethod
    def create(
        cls,
        key: str,
        *,
        slot_count: int | None = None,
        slot_size: int | None = None,
    ) -> "SharedMemoryLineQueue":
        using_default_slot_count = slot_count is None
        slot_count = _DEFAULT_SLOT_COUNT if slot_count is None else slot_count
        slot_size = _DEFAULT_SLOT_SIZE if slot_size is None else slot_size
        slot_count = max(1, int(slot_count))
        slot_size = max(64, int(slot_size))
        candidates = [slot_count]
        if using_default_slot_count:
            candidates = [count for count in _DEFAULT_FALLBACK_SLOT_COUNTS if count <= slot_count]
            if slot_count not in candidates:
                candidates.insert(0, slot_count)

        errors = []
        for candidate_count in candidates:
            memory = QSharedMemory(key)
            size = _queue_memory_size(candidate_count, slot_size)
            if memory.create(size):
                queue = cls(
                    key,
                    memory,
                    slot_count=candidate_count,
                    slot_size=slot_size,
                    cursor=0,
                    owner=True,
                )
                queue._initialize()
                return queue
            errors.append(f"{size} bytes: {memory.errorString()}")
        detail = "; ".join(errors) if errors else "no attempts made"
        raise RuntimeError(f"Failed to create shared memory '{key}': {detail}")

    @classmethod
    def attach(
        cls,
        key: str,
        *,
        start_at_tail: bool = True,
    ) -> "SharedMemoryLineQueue":
        memory = QSharedMemory(key)
        if not memory.attach():
            raise RuntimeError(f"Failed to attach shared memory '{key}': {memory.errorString()}")
        queue = cls(key, memory, slot_count=1, slot_size=64, cursor=0, owner=False)
        magic, _version, slot_count, slot_size, next_seq = queue._read_header_locked()
        if magic != _MAGIC:
            memory.detach()
            raise RuntimeError(f"Shared memory '{key}' is not a Bandori IPC queue")
        queue.slot_count = slot_count
        queue.slot_size = slot_size
        queue._cursor = next_seq if start_at_tail else max(0, next_seq - slot_count)
        return queue

    def close(self) -> None:
        if self._memory is not None and self._memory.isAttached():
            self._memory.detach()

    def is_attached(self) -> bool:
        return self._memory is not None and self._memory.isAttached()

    def publish(self, line: str) -> bool:
        payload = normalize_ipc_line(line).encode("utf-8")
        if not payload or len(payload) > self.slot_size:
            return False
        if not self._memory.lock():
            return False
        try:
            view = memoryview(self._memory.data())
            magic, version, slot_count, slot_size, next_seq = self._read_header(view)
            if magic != _MAGIC or version != _VERSION:
                return False
            slot_index = next_seq % slot_count
            offset = _HEADER.size + slot_index * (_SLOT_HEADER.size + slot_size)
            _SLOT_HEADER.pack_into(view, offset, next_seq, len(payload))
            payload_start = offset + _SLOT_HEADER.size
            view[payload_start:payload_start + len(payload)] = payload
            self._write_header(view, slot_count, slot_size, next_seq + 1)
            return True
        finally:
            self._memory.unlock()

    def read_available(self, max_messages: int | None = None) -> list[str]:
        if max_messages is not None:
            max_messages = max(0, int(max_messages))
            if max_messages == 0:
                return []
        if not self._memory.lock():
            return []
        try:
            view = memoryview(self._memory.data())
            magic, version, slot_count, slot_size, next_seq = self._read_header(view)
            if magic != _MAGIC or version != _VERSION:
                return []
            first_available = max(0, next_seq - slot_count)
            if self._cursor < first_available:
                self._cursor = first_available
            messages = []
            seq = self._cursor
            while seq < next_seq and (max_messages is None or len(messages) < max_messages):
                slot_index = seq % slot_count
                offset = _HEADER.size + slot_index * (_SLOT_HEADER.size + slot_size)
                slot_seq, length = _SLOT_HEADER.unpack_from(view, offset)
                if slot_seq != seq or length <= 0 or length > slot_size:
                    seq += 1
                    continue
                payload_start = offset + _SLOT_HEADER.size
                raw = bytes(view[payload_start:payload_start + length])
                messages.append(raw.decode("utf-8", errors="replace"))
                seq += 1
            self._cursor = seq
            return messages
        finally:
            self._memory.unlock()

    def _initialize(self) -> None:
        if not self._memory.lock():
            raise RuntimeError(f"Failed to lock shared memory '{self.key}'")
        try:
            view = memoryview(self._memory.data())
            self._write_header(view, self.slot_count, self.slot_size, 0)
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
