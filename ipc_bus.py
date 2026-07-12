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


def ipc_control_queue_key() -> str:
    return make_shared_memory_key(ipc_server_name(), "main-control")


def is_control_ipc_line(line: str) -> bool:
    normalized = normalize_ipc_line(line)
    return normalized == "SHUTDOWN" or normalized.startswith((
        "SETTINGS\t",
        "FOCUS_CHAT",
        "FOCUS_SETTINGS",
        "OPEN_CHAT",
        "SHOW_COSTUMES",
        "CHAT_EVENT\t",
        "REMINDER_EVENT\t",
    ))


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


def attach_main_ipc_queues(ipc: dict) -> bool:
    try:
        from shared_memory_ipc import SharedMemoryLineQueue

        if ipc.get("inbound") is None or not ipc["inbound"].is_attached():
            ipc["inbound"] = SharedMemoryLineQueue.attach(ipc_inbound_queue_key())
        if ipc.get("broadcast") is None or not ipc["broadcast"].is_attached():
            ipc["broadcast"] = SharedMemoryLineQueue.attach(ipc_broadcast_queue_key())
        if ipc.get("control") is None or not ipc["control"].is_attached():
            ipc["control"] = SharedMemoryLineQueue.attach(ipc_control_queue_key())
        return True
    except Exception:
        for key in ("inbound", "broadcast", "control"):
            queue = ipc.get(key)
            if queue is not None:
                queue.close()
            ipc[key] = None
        return False


def start_ipc_heartbeat(app, send_heartbeat_fn, poll_fn):
    from PySide6.QtCore import QTimer

    poll_timer = QTimer(app)
    poll_timer.setInterval(30)
    poll_timer.timeout.connect(poll_fn)
    poll_timer.start()
    heartbeat_timer = QTimer(app)
    heartbeat_timer.setInterval(3000)
    heartbeat_timer.timeout.connect(send_heartbeat_fn)
    heartbeat_timer.start()
    QTimer.singleShot(0, send_heartbeat_fn)
    return poll_timer, heartbeat_timer
