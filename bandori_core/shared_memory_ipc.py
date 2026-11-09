from __future__ import annotations

import hashlib
import json
import os
import struct
import uuid
from dataclasses import dataclass

import logging

from bandori_core.mapped_memory import queue_file_path

try:
    from bandori_core._pet_ipc import NativeQueue
except ImportError as exc:
    raise ImportError(
        "Rust IPC extension is required. Run: python tools/build_ipc.py "
        "(use the same Python interpreter as the application)."
    ) from exc

_logger = logging.getLogger(__name__)


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
    """Compatibility facade over pet-ipc; all mapped queue access runs in Rust.

    Each handle has its own cursor. The v1 ring can overwrite unread messages;
    dropped_messages counts those losses and reads report them through logging.
    There is deliberately no import-time compilation or Python fallback.
    """

    def __init__(self, key: str, queue: NativeQueue):
        self.key = key
        self.slot_count = queue.slot_count
        self.slot_size = queue.slot_size
        self._queue = queue
        self._reported_drops = 0
        self._reported_read_error = ""

    @classmethod
    def create(cls, key: str, *, slot_count: int | None = None,
               slot_size: int | None = None,
               fallback_slot_counts: tuple[int, ...] | None = None) -> "SharedMemoryLineQueue":
        using_default = slot_count is None
        count = max(1, int(_DEFAULT_SLOT_COUNT if slot_count is None else slot_count))
        size = max(64, int(_DEFAULT_SLOT_SIZE if slot_size is None else slot_size))
        errors = []
        for candidate in _queue_slot_count_candidates(
            count, using_default=using_default, fallback_slot_counts=fallback_slot_counts
        ):
            try:
                native = NativeQueue.create(queue_file_path(key), candidate, size)
                return cls(key, native)
            except (RuntimeError, OverflowError) as exc:
                errors.append(f"{_queue_memory_size(candidate, size)} bytes: {exc}")
        raise RuntimeError(f"Failed to create shared memory '{key}': {'; '.join(errors)}")

    @classmethod
    def attach(cls, key: str, *, start_at_tail: bool = True) -> "SharedMemoryLineQueue":
        try:
            return cls(key, NativeQueue.attach(queue_file_path(key), bool(start_at_tail)))
        except RuntimeError as exc:
            raise RuntimeError(f"Failed to attach shared memory '{key}': {exc}") from exc

    def close(self) -> None:
        self._queue.close()

    def is_attached(self) -> bool:
        return self._queue.is_attached()

    def publish(self, line: str) -> bool:
        published = self._queue.publish(normalize_ipc_line(line))
        if not published:
            _logger.error("IPC queue %s publish failed: %s", self.key, self.last_publish_error)
        return published

    def read_available(self, max_messages: int | None = None) -> list[str]:
        if max_messages is not None:
            # A batch cannot contain more than the ring's slot count. Clamp
            # Python's unbounded integers before converting to Rust usize.
            max_messages = min(self.slot_count, max(0, int(max_messages)))
        lines, dropped, error = self._queue.read_batch(max_messages)
        if dropped > self._reported_drops:
            _logger.error("IPC queue %s lost %d messages (ring overwrite or corrupt slot)",
                          self.key, dropped - self._reported_drops)
        self._reported_drops = dropped
        if error and error != self._reported_read_error:
            _logger.error("IPC queue %s read failed: %s", self.key, error)
        self._reported_read_error = error
        return lines

    @property
    def dropped_messages(self) -> int:
        return self._queue.dropped_messages

    @dropped_messages.setter
    def dropped_messages(self, value: int) -> None:
        self._queue.dropped_messages = value

    @property
    def last_publish_error(self) -> str:
        return self._queue.last_publish_error

    @last_publish_error.setter
    def last_publish_error(self, value: str) -> None:
        self._queue.last_publish_error = value

    @property
    def last_read_error(self) -> str:
        """Diagnostic for recoverable reads, which continue to return []."""
        return self._queue.last_read_error
