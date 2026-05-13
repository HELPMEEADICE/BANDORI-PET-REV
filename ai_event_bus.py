import json

from PySide6.QtNetwork import QLocalSocket

from process_utils import ipc_server_name


def publish_ai_event(data: dict):
    if not isinstance(data, dict):
        return
    try:
        socket = QLocalSocket()
        socket.connectToServer(ipc_server_name())
        if socket.waitForConnected(200):
            payload = json.dumps(data, ensure_ascii=False)
            socket.write(f"AI_EVENT\t{payload}\n".encode("utf-8"))
            socket.flush()
            socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
    except Exception:
        pass
