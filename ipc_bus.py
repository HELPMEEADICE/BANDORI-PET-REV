import threading

from process_utils import ipc_server_name
from shared_memory_ipc import (
    SharedMemoryLineQueue,
    encode_ipc_envelope,
    make_peer_id,
    make_shared_memory_key,
    normalize_ipc_line,
)

_ipc_lock = threading.Lock()
_ipc_sender_id = make_peer_id("oneshot")
_ipc_inbound_queue = None


def ipc_inbound_queue_key() -> str:
    return make_shared_memory_key(ipc_server_name(), "main-in")


def ipc_broadcast_queue_key() -> str:
    return make_shared_memory_key(ipc_server_name(), "main-out")


def radial_command_queue_key(name: str) -> str:
    return make_shared_memory_key(name, "radial-cmd")


def radial_event_queue_key(name: str) -> str:
    return make_shared_memory_key(name, "radial-event")


def send_ipc_message(message: str) -> bool:
    if not message:
        return False
    with _ipc_lock:
        return _send_ipc_message_locked(message)


def _send_ipc_message_locked(message: str) -> bool:
    global _ipc_inbound_queue
    try:
        if _ipc_inbound_queue is None or not _ipc_inbound_queue.is_attached():
            _ipc_inbound_queue = SharedMemoryLineQueue.attach(ipc_inbound_queue_key())
        lines = [normalize_ipc_line(line) for line in str(message).splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            return False
        ok = True
        for line in lines:
            ok = _ipc_inbound_queue.publish(encode_ipc_envelope(_ipc_sender_id, line)) and ok
        return ok
    except Exception:
        if _ipc_inbound_queue is not None:
            _ipc_inbound_queue.close()
            _ipc_inbound_queue = None
        return False
