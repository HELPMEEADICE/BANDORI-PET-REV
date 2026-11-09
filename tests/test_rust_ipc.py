"""Real Rust/Python IPC tests; no fallback, sockets or GUI dependencies."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue as thread_queue
import struct
import subprocess
import sys
import threading
import uuid

import pytest

from bandori_core import _pet_ipc
from bandori_core.mapped_memory import MappedMemory, queue_file_path
from bandori_core.shared_memory_ipc import (
    SharedMemoryLineQueue as Queue, decode_ipc_envelope, encode_ipc_envelope,
)
from tools.benchmarks.legacy_ipc import SharedMemoryLineQueue as LegacyQueue
from tools.benchmarks.legacy_ipc import _lock, _unlock

ROOT = Path(__file__).resolve().parents[1]


def key():
    return "rust-ipc-test-" + uuid.uuid4().hex


def patch(path, offset, data):
    with path.open("r+b") as file:
        _lock(file)
        try:
            file.seek(offset)
            file.write(data)
            file.flush()
        finally:
            _unlock(file)


class Peer:
    """Bounded pipe reads so a deadlocked regression cannot hang pytest."""
    def __init__(self, args):
        self.process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, encoding="utf-8")
        self.output = thread_queue.Queue()
        def read_output():
            for line in self.process.stdout:
                self.output.put(line)
            self.output.put("")
        self.reader = threading.Thread(target=read_output, daemon=True)
        self.reader.start()

    def receive(self):
        line = self.output.get(timeout=15)
        assert line, "peer exited before replying"
        return json.loads(line)

    def request(self, **request):
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=5)
        self.process.stdout.close()
        self.process.stderr.close()


@pytest.fixture(scope="session")
def rust_binary():
    binary = Path(os.environ.get("BANDORI_IPC_PEER", ROOT / "native/pet_backend/target/debug/examples" /
                                  ("ipc_peer.exe" if os.name == "nt" else "ipc_peer")))
    assert binary.is_file(), "Run cargo build --manifest-path native/pet_backend/Cargo.toml -p pet-ipc --example ipc_peer --locked"
    return str(binary)


def test_python_really_uses_native_extension():
    assert _pet_ipc.BACKEND == "rust-pet-ipc"
    assert _pet_ipc.PROTOCOL_VERSION == 1
    q = Queue.create(key(), slot_count=2, slot_size=128)
    try:
        assert type(q._queue).__module__ == "bandori_core._pet_ipc"
        assert isinstance(q._queue, _pet_ipc.NativeQueue)
    finally:
        q.close()


def test_missing_extension_fails_without_fallback_or_compilation():
    script = """
import sys
class Block:
    def find_spec(self, fullname, *args):
        if fullname == 'bandori_core._pet_ipc':
            raise ImportError('blocked for test')
sys.meta_path.insert(0, Block())
import bandori_core.shared_memory_ipc
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert "Rust IPC extension is required" in result.stderr


def test_python_creates_rust_attaches(rust_binary):
    q = Queue.create(key(), slot_count=8, slot_size=256)
    peer = Peer([rust_binary, "attach", str(queue_file_path(q.key))])
    try:
        assert peer.receive() == {"ready": True}
        raw = encode_ipc_envelope("python", "ACTION\t愛音\twave", reliable=True, message_id="one")
        assert q.publish(raw)
        assert peer.request(op="read")["lines"] == [raw]
        assert peer.request(op="publish", line="Rust→Python 中文🐈") == {"ok": True}
        assert q.read_available() == [raw, "Rust→Python 中文🐈"]
    finally:
        peer.close()
        q.close()


def test_rust_creates_python_attaches(rust_binary):
    name = key()
    peer = Peer([rust_binary, "create", str(queue_file_path(name)), "8", "256"])
    q = None
    try:
        assert peer.receive() == {"ready": True}
        q = Queue.attach(name, start_at_tail=False)
        assert peer.request(op="publish", line="LIP\t愛音\t0.5")["ok"]
        assert q.read_available() == ["LIP\t愛音\t0.5"]
        assert q.publish("EMOTION\t愛音\tsmile")
        assert peer.request(op="read")["lines"] == ["LIP\t愛音\t0.5", "EMOTION\t愛音\tsmile"]
    finally:
        if q is not None:
            q.close()
        peer.close()
    assert not queue_file_path(name).exists()


@pytest.mark.parametrize("creator,attacher", [(Queue, LegacyQueue), (LegacyQueue, Queue)])
def test_frozen_v1_binary_compatibility(creator, attacher):
    q = creator.create(key(), slot_count=4, slot_size=128)
    reader = attacher.attach(q.key, start_at_tail=False)
    try:
        assert q.publish("中文 / 日本語 / 🐈\r\n")
        assert reader.read_available() == ["中文 / 日本語 / 🐈"]
        assert reader.publish("reply")
        assert q.read_available() == ["中文 / 日本語 / 🐈", "reply"]
        raw = queue_file_path(q.key).read_bytes()
        assert struct.unpack_from("<8sIIIQ", raw) == (b"BDIPC01!", 1, 4, 128, 2)
        assert struct.unpack_from("<QI", raw, 28) == (0, len("中文 / 日本語 / 🐈".encode()))
    finally:
        reader.close()
        q.close()


def test_threads_publish_same_and_separate_handles():
    q = Queue.create(key(), slot_count=1600, slot_size=128)
    readers = [Queue.attach(q.key, start_at_tail=False) for _ in range(2)]
    barrier = threading.Barrier(8)
    def publish(index):
        own = Queue.attach(q.key) if index % 2 else None
        try:
            barrier.wait(timeout=10)
            for n in range(200):
                assert (own or q).publish(f"{index}:{n}:愛音")
        finally:
            if own:
                own.close()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(publish, range(8)))
        first = readers[0].read_available()
        assert len(first) == len(set(first)) == 1600
        assert readers[1].read_available() == first
        assert readers[0].dropped_messages == 0
    finally:
        for reader in readers:
            reader.close()
        q.close()


def test_multiprocess_concurrent_publish_stress():
    q = Queue.create(key(), slot_count=4000, slot_size=256)
    script = """
import sys, json
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue
q = SharedMemoryLineQueue.attach(sys.argv[1])
print(json.dumps({'ready': True}), flush=True)
sys.stdin.readline()
for n in range(1000):
    assert q.publish(sys.argv[2] + ':' + str(n) + ':中文🐈')
q.close()
"""
    peers = [Peer([sys.executable, "-c", script, q.key, str(i)]) for i in range(4)]
    try:
        for peer in peers:
            assert peer.receive()["ready"]
        for peer in peers:
            peer.process.stdin.write("go\n")
            peer.process.stdin.flush()
        for peer in peers:
            assert peer.process.wait(timeout=30) == 0
        lines = q.read_available()
        assert len(lines) == len(set(lines)) == 4000
        assert q.dropped_messages == 0
    finally:
        for peer in peers:
            peer.close()
        q.close()


def test_killed_owner_survivors_and_recreation():
    name = key()
    script = """
import sys, json
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue
q = SharedMemoryLineQueue.create(sys.argv[1], slot_count=4, slot_size=128)
q.publish('before crash')
print(json.dumps({'ready': True}), flush=True)
sys.stdin.readline()
"""
    owner = Peer([sys.executable, "-c", script, name])
    reader = None
    try:
        assert owner.receive()["ready"]
        reader = Queue.attach(name, start_at_tail=False)
        owner.process.kill()
        owner.process.wait(timeout=5)
        with pytest.raises(RuntimeError, match="attached participants"):
            Queue.create(name, slot_count=2, slot_size=256)
        extra = Queue.attach(name, start_at_tail=False)
        try:
            assert extra.read_available() == ["before crash"]
            assert extra.publish("after crash")
        finally:
            extra.close()
        assert reader.read_available() == ["before crash", "after crash"]
    finally:
        if reader:
            reader.close()
        owner.close()
    assert not queue_file_path(name).exists()
    recovered = Queue.create(name, slot_count=2, slot_size=256)
    recovered.close()


def test_killed_creator_without_survivors_is_reclaimed():
    name = key()
    script = "from bandori_core.shared_memory_ipc import SharedMemoryLineQueue; import os,sys; q=SharedMemoryLineQueue.create(sys.argv[1]); os._exit(0)"
    subprocess.run([sys.executable, "-c", script, name], cwd=ROOT, check=True, timeout=15)
    assert queue_file_path(name).exists()
    q = Queue.create(name, slot_count=2, slot_size=64)
    try:
        assert q.publish("reclaimed")
        assert q.read_available() == ["reclaimed"]
    finally:
        q.close()


def test_concurrent_creators_have_exactly_one_winner():
    name = key()
    barrier = threading.Barrier(8)
    def create(_):
        barrier.wait(timeout=10)
        try:
            return Queue.create(name, slot_count=2, slot_size=64)
        except RuntimeError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = [q for q in pool.map(create, range(8)) if q]
    try:
        assert len(winners) == 1
    finally:
        for q in winners:
            q.close()


@pytest.mark.parametrize("offset,data", [
    (0, b"NOTIPC!!"), (8, struct.pack("<I", 2)),
    (12, struct.pack("<I", 0)), (12, struct.pack("<I", 0xFFFFFFFF)),
    (16, struct.pack("<I", 63)), (16, struct.pack("<I", 0xFFFFFFFF)),
])
def test_corrupt_headers_are_recoverable(offset, data):
    q = Queue.create(key(), slot_count=2, slot_size=128)
    try:
        patch(queue_file_path(q.key), offset, data)
        assert not q.publish("bad")
        assert q.last_publish_error
        assert q.read_available() == []
        assert q.last_read_error
        with pytest.raises(RuntimeError):
            Queue.attach(q.key)
    finally:
        q.close()


def test_corrupt_slots_and_loss_are_observable(caplog):
    q = Queue.create(key(), slot_count=2, slot_size=64)
    try:
        for n in range(3):
            assert q.publish(str(n))
        patch(queue_file_path(q.key), 28 + 8, struct.pack("<I", 65))
        assert q.read_available() == ["1"]
        assert q.dropped_messages == 2
        assert "lost 2 messages" in caplog.text
    finally:
        q.close()


def test_unicode_boundaries_utf8_replacement_and_sequence_exhaustion():
    q = Queue.create(key(), slot_count=2, slot_size=64)
    try:
        assert q.publish("🐈" * 16)
        assert not q.publish("🐈" * 16 + "x")
        assert q.last_publish_error == "payload exceeds 64 bytes"
        assert not q.publish("\r\n")
        assert q.last_publish_error == "empty payload"
        assert q.read_available(-1) == []
        assert q.read_available(1) == ["🐈" * 16]
        assert q.publish("a")
        patch(queue_file_path(q.key), 28 + 76 + 12, b"\xff")
        assert q.read_available() == ["�"]
        patch(queue_file_path(q.key), 20, struct.pack("<Q", 2**64 - 1))
        assert not q.publish("overflow")
        assert "exhausted" in q.last_publish_error
    finally:
        q.close()
    q.close()
    assert not q.is_attached()
    assert q.read_available() == []
    assert not q.publish("closed")
    assert q.last_publish_error == "queue is detached"
    assert not q.publish("")
    assert q.last_publish_error == "empty payload"
    assert not q.publish("x" * 65)
    assert q.last_publish_error == "payload exceeds 64 bytes"


def test_oversize_extent_fails_before_mapping():
    with pytest.raises(RuntimeError):
        Queue.create(key(), slot_count=2**32, slot_size=64)
    with pytest.raises(RuntimeError):
        Queue.create(key(), slot_count=2**24, slot_size=65536)


def test_legacy_mapped_memory_facade_uses_rust_transactions():
    name = key()
    owner, reader = MappedMemory(name), MappedMemory(name)
    try:
        assert owner.create(128)
        assert reader.attach()
        assert owner.lock()
        owner.data()[:5] = b"hello"
        owner.unlock()
        assert reader.lock()
        assert bytes(reader.data()[:5]) == b"hello"
        reader.unlock()
        assert type(owner._native).__module__ == "bandori_core._pet_ipc"
    finally:
        reader.detach()
        owner.detach()
    assert not owner.lock()


def test_killed_process_releases_transaction_lock():
    q = Queue.create(key(), slot_count=2, slot_size=128)
    script = """
import sys, json
from bandori_core.mapped_memory import MappedMemory
memory = MappedMemory(sys.argv[1])
assert memory.attach() and memory.lock()
print(json.dumps({'locked': True}), flush=True)
sys.stdin.readline()
"""
    peer = Peer([sys.executable, "-c", script, q.key])
    try:
        assert peer.receive()["locked"]
        peer.process.kill()
        peer.process.wait(timeout=5)
        assert q.publish("OS released the lock")
        assert q.read_available() == ["OS released the lock"]
    finally:
        peer.close()
        q.close()


def test_close_concurrent_with_publishing_has_no_borrow_errors():
    q = Queue.create(key(), slot_count=512, slot_size=64)
    barrier = threading.Barrier(5)
    def publish(_):
        barrier.wait(timeout=5)
        for _ in range(100):
            # A close racing this call is a recoverable False, never a PyO3
            # "already borrowed" exception or a use of an unmapped pointer.
            assert isinstance(q.publish("thread"), bool)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(publish, i) for i in range(4)]
        barrier.wait(timeout=5)
        q.close()
        for future in futures:
            future.result(timeout=5)
    assert q.read_available() == []


def test_repeated_attach_close_does_not_leak_os_handles():
    import psutil
    process = psutil.Process()
    counter = process.num_handles if os.name == "nt" else process.num_fds
    q = Queue.create(key(), slot_count=2, slot_size=64)
    try:
        before = counter()
        for _ in range(200):
            reader = Queue.attach(q.key)
            reader.close()
            reader.close()
        assert counter() <= before + 2
    finally:
        q.close()


def test_all_reliable_commands_preserve_envelope_and_failed_publish_semantics(monkeypatch):
    from bandori_core import ipc_bus
    commands = ["SHUTDOWN", "SETTINGS\t{}", "FOCUS_CHAT", "FOCUS_SETTINGS", "OPEN_CHAT",
                "SHOW_COSTUMES", "REGISTER\tPET\t愛音", "UNREGISTER\tPET\t愛音",
                "PEER_OFFLINE\t{}", "PEER_DRAG_END\t{}", "RADIAL_MENU_OPEN\t{}",
                "RADIAL_MENU_CLOSED\t{}", "MODEL\t愛音", "LAUNCH", "EXIT", "OPEN_SETTINGS",
                "POKE_USER\t愛音", "CHAT_EVENT\t{}", "REMINDER_EVENT\t{}", "NATIVE_EVENT\t{}",
                "NATIVE_CONTROL\t{\"command\":\"snapshot\"}", "OUTFIT_DESCRIPTION\t{}"]
    reliable = Queue.create(key(), slot_count=len(commands), slot_size=256)
    lossy = Queue.create(key(), slot_count=2, slot_size=256)
    monkeypatch.setattr(ipc_bus, "_ipc_reliable_inbound_queue", reliable)
    monkeypatch.setattr(ipc_bus, "_ipc_inbound_queue", lossy)
    try:
        for line in commands:
            assert ipc_bus.is_reliable_ipc_line(line)
            assert ipc_bus.send_ipc_message(line)
        for n in range(1000):
            assert ipc_bus.send_ipc_message(f"PEER_POS\t{n}")
        envelopes = [decode_ipc_envelope(raw) for raw in reliable.read_available()]
        assert [e.line for e in envelopes] == commands
        assert all(e.reliable for e in envelopes)
        assert reliable.dropped_messages == 0
        assert not ipc_bus.send_ipc_message("SETTINGS\t" + "x" * 300)
    finally:
        reliable.close()
        lossy.close()
