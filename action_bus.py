from PySide6.QtNetwork import QLocalSocket

from process_utils import ipc_server_name


def publish_action(character: str, action: str):
    if not character or not action:
        return
    try:
        socket = QLocalSocket()
        socket.connectToServer(ipc_server_name())
        if socket.waitForConnected(200):
            socket.write(f"ACTION\t{character}\t{action}\n".encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
    except Exception:
        pass


def publish_lip_sync(character: str, level: float, form: float | None = None):
    if not character:
        return
    try:
        level = max(0.0, min(float(level), 1.0))
        suffix = ""
        if form is not None:
            form = max(-1.0, min(float(form), 1.0))
            suffix = f"\t{form:.3f}"
        socket = QLocalSocket()
        socket.connectToServer(ipc_server_name())
        if socket.waitForConnected(50):
            socket.write(f"LIP\t{character}\t{level:.3f}{suffix}\n".encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(50)
        socket.disconnectFromServer()
    except Exception:
        pass
