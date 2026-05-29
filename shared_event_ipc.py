import mmap
import os
import re
import struct

from process_utils import ipc_server_name


MAGIC = b"BDPETIPC"
VERSION = 1
SLOT_COUNT = 256
SLOT_SIZE = 4096
HEADER = struct.Struct("<8sI4xQII")
SLOT_HEADER = struct.Struct("<QI")
SIZE = HEADER.size + SLOT_COUNT * SLOT_SIZE


def _shared_name() -> str:
    base = ipc_server_name()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
    return f"BandoriPetSharedEvents-{safe}"


class SharedEventWriter:
    def __init__(self):
        self._mmap = _open_map()
        self._ensure_header()

    def close(self):
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None

    def write_line(self, line: str):
        if self._mmap is None:
            return
        payload = str(line or "").encode("utf-8", errors="replace")[: SLOT_SIZE - SLOT_HEADER.size]
        _magic, _version, seq, slot_count, slot_size = HEADER.unpack_from(self._mmap, 0)
        if slot_count != SLOT_COUNT or slot_size != SLOT_SIZE:
            self._ensure_header(reset=True)
            seq = 0
        next_seq = int(seq) + 1
        slot_index = next_seq % SLOT_COUNT
        offset = HEADER.size + slot_index * SLOT_SIZE
        self._mmap.seek(offset)
        self._mmap.write(SLOT_HEADER.pack(0, len(payload)))
        self._mmap.write(payload)
        if len(payload) < SLOT_SIZE - SLOT_HEADER.size:
            self._mmap.write(b"\0" * (SLOT_SIZE - SLOT_HEADER.size - len(payload)))
        SLOT_HEADER.pack_into(self._mmap, offset, next_seq, len(payload))
        HEADER.pack_into(self._mmap, 0, MAGIC, VERSION, next_seq, SLOT_COUNT, SLOT_SIZE)

    def _ensure_header(self, *, reset: bool = False):
        try:
            magic, version, _seq, slot_count, slot_size = HEADER.unpack_from(self._mmap, 0)
        except Exception:
            reset = True
            magic = b""
            version = 0
            slot_count = 0
            slot_size = 0
        if reset or magic != MAGIC or version != VERSION or slot_count != SLOT_COUNT or slot_size != SLOT_SIZE:
            self._mmap.seek(0)
            self._mmap.write(b"\0" * SIZE)
            HEADER.pack_into(self._mmap, 0, MAGIC, VERSION, 0, SLOT_COUNT, SLOT_SIZE)


class SharedEventReader:
    def __init__(self):
        self._mmap = _open_map()
        self._last_seq = 0
        self._sync_header()

    def close(self):
        if self._mmap is not None:
            self._mmap.close()
            self._mmap = None

    def poll_lines(self) -> list[str]:
        if self._mmap is None:
            return []
        try:
            magic, version, seq, slot_count, slot_size = HEADER.unpack_from(self._mmap, 0)
        except Exception:
            return []
        if magic != MAGIC or version != VERSION or slot_count != SLOT_COUNT or slot_size != SLOT_SIZE:
            self._last_seq = 0
            return []
        seq = int(seq)
        if seq <= self._last_seq:
            return []
        first = max(self._last_seq + 1, seq - SLOT_COUNT + 1)
        lines = []
        for event_seq in range(first, seq + 1):
            slot_index = event_seq % SLOT_COUNT
            offset = HEADER.size + slot_index * SLOT_SIZE
            slot_seq, length = SLOT_HEADER.unpack_from(self._mmap, offset)
            if int(slot_seq) != event_seq or length <= 0 or length > SLOT_SIZE - SLOT_HEADER.size:
                continue
            data = self._mmap[offset + SLOT_HEADER.size : offset + SLOT_HEADER.size + length]
            lines.append(bytes(data).decode("utf-8", errors="replace"))
        self._last_seq = seq
        return lines

    def _sync_header(self):
        try:
            magic, version, seq, slot_count, slot_size = HEADER.unpack_from(self._mmap, 0)
        except Exception:
            return
        if magic == MAGIC and version == VERSION and slot_count == SLOT_COUNT and slot_size == SLOT_SIZE:
            self._last_seq = int(seq)


def _open_map():
    name = _shared_name()
    if os.name == "nt":
        return mmap.mmap(-1, SIZE, tagname=name)
    return mmap.mmap(-1, SIZE)
