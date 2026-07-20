from __future__ import annotations

import json
import struct
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalSocket


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 2 * 1024 * 1024


class ProtocolError(RuntimeError):
    pass


class RpcRemoteError(RuntimeError):
    def __init__(self, code: str, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


def encode_message(message: dict[str, Any]) -> bytes:
    payload = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Plugin RPC message exceeds 2 MiB")
    return struct.pack(">I", len(payload)) + payload


class FrameDecoder:
    def __init__(self, max_message_bytes: int = MAX_MESSAGE_BYTES):
        self.max_message_bytes = int(max_message_bytes)
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[dict[str, Any]]:
        self.buffer.extend(data)
        messages: list[dict[str, Any]] = []
        while len(self.buffer) >= 4:
            size = struct.unpack(">I", self.buffer[:4])[0]
            if size <= 0 or size > self.max_message_bytes:
                raise ProtocolError("Plugin RPC frame has an invalid size")
            if len(self.buffer) < 4 + size:
                break
            payload = bytes(self.buffer[4:4 + size])
            del self.buffer[:4 + size]
            try:
                message = json.loads(
                    payload.decode("utf-8"),
                    parse_constant=lambda value: (_ for _ in ()).throw(
                        ValueError(f"Non-standard JSON constant: {value}")
                    ),
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise ProtocolError(f"Plugin RPC frame is not valid JSON: {exc}") from exc
            if not isinstance(message, dict) or message.get("v") != PROTOCOL_VERSION:
                raise ProtocolError("Plugin RPC message has an unsupported protocol version")
            kind = message.get("kind")
            if kind not in {"request", "response", "event"}:
                raise ProtocolError("Plugin RPC message has an invalid kind")
            if kind in {"request", "response"}:
                request_id = message.get("id")
                if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                    raise ProtocolError("Plugin RPC request/response has an invalid id")
            if kind in {"request", "event"}:
                method = message.get("method")
                if not isinstance(method, str) or not method or len(method) > 256:
                    raise ProtocolError("Plugin RPC request/event has an invalid method")
            if kind == "response" and "error" in message and not isinstance(message["error"], dict):
                raise ProtocolError("Plugin RPC response has an invalid error object")
            messages.append(message)
        return messages


def request_message(method: str, params: Any = None, request_id: str | None = None) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "id": request_id or uuid.uuid4().hex,
        "kind": "request",
        "method": str(method),
        "params": {} if params is None else params,
    }


def event_message(method: str, params: Any = None) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "kind": "event",
        "method": str(method),
        "params": {} if params is None else params,
    }


def response_message(
    request_id: str,
    *,
    result: Any = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = {
        "v": PROTOCOL_VERSION,
        "id": str(request_id),
        "kind": "response",
    }
    if error is None:
        message["result"] = result
    else:
        message["error"] = error
    return message


@dataclass
class _PendingCall:
    loop: QEventLoop
    result: Any = None
    error: dict[str, Any] | None = None
    finished: bool = False


class RpcPeer(QObject):
    message_received = Signal(object)
    request_received = Signal(object)
    event_received = Signal(object)
    disconnected = Signal()
    protocol_failed = Signal(str)

    def __init__(self, socket: QLocalSocket, parent: QObject | None = None):
        super().__init__(parent)
        self.socket = socket
        self.decoder = FrameDecoder()
        self.handlers: dict[str, Callable[[Any], Any]] = {}
        self._pending: dict[str, _PendingCall] = {}
        socket.readyRead.connect(self._read_available)
        socket.disconnected.connect(self._on_disconnected)

    @property
    def connected(self) -> bool:
        return self.socket.state() == QLocalSocket.LocalSocketState.ConnectedState

    def register_handler(self, method: str, handler: Callable[[Any], Any]) -> None:
        self.handlers[str(method)] = handler

    def send(self, message: dict[str, Any]) -> None:
        if not self.connected:
            raise ProtocolError("Plugin RPC peer is disconnected")
        frame = encode_message(message)
        if self.socket.write(frame) != len(frame):
            raise ProtocolError("Plugin RPC socket could not queue the complete frame")
        self.socket.flush()

    def notify(self, method: str, params: Any = None) -> None:
        self.send(event_message(method, params))

    def call(self, method: str, params: Any = None, *, timeout_ms: int = 10_000) -> Any:
        if timeout_ms <= 0:
            raise ValueError("RPC timeout must be positive")
        message = request_message(method, params)
        request_id = message["id"]
        loop = QEventLoop()
        pending = _PendingCall(loop=loop)
        self._pending[request_id] = pending
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        try:
            self.send(message)
            timer.start(int(timeout_ms))
            if not pending.finished:
                loop.exec()
            if not pending.finished:
                raise TimeoutError(f"Plugin RPC call timed out: {method}")
            if pending.error is not None:
                raise RpcRemoteError(
                    str(pending.error.get("code", "remote_error")),
                    str(pending.error.get("message", "Plugin RPC request failed")),
                    pending.error.get("data"),
                )
            return pending.result
        finally:
            timer.stop()
            self._pending.pop(request_id, None)

    def _read_available(self) -> None:
        try:
            messages = self.decoder.feed(bytes(self.socket.readAll()))
            for message in messages:
                self.message_received.emit(message)
                kind = message.get("kind")
                if kind == "response":
                    self._handle_response(message)
                elif kind == "request":
                    self._handle_request(message)
                else:
                    self._handle_event(message)
        except Exception as exc:
            self.protocol_failed.emit(str(exc))
            self.socket.abort()

    def _handle_response(self, message: dict[str, Any]) -> None:
        pending = self._pending.get(str(message.get("id", "")))
        if pending is None:
            return
        pending.result = message.get("result")
        pending.error = message.get("error") if isinstance(message.get("error"), dict) else None
        pending.finished = True
        pending.loop.quit()

    def _handle_request(self, message: dict[str, Any]) -> None:
        self.request_received.emit(message)
        request_id = str(message.get("id", ""))
        method = str(message.get("method", ""))
        handler = self.handlers.get(method)
        if handler is None:
            self.send(response_message(request_id, error={
                "code": "method_not_found",
                "message": f"Unknown RPC method: {method}",
            }))
            return
        try:
            result = handler(message.get("params"))
            self.send(response_message(request_id, result=result))
        except RpcRemoteError as exc:
            self.send(response_message(request_id, error={
                "code": exc.code,
                "message": str(exc),
                "data": exc.data,
            }))
        except Exception as exc:
            self.send(response_message(request_id, error={
                "code": "handler_error",
                "message": str(exc),
            }))

    def _handle_event(self, message: dict[str, Any]) -> None:
        self.event_received.emit(message)
        handler = self.handlers.get(str(message.get("method", "")))
        if handler is not None:
            handler(message.get("params"))

    def _on_disconnected(self) -> None:
        for pending in self._pending.values():
            pending.error = {"code": "disconnected", "message": "Plugin RPC peer disconnected"}
            pending.finished = True
            pending.loop.quit()
        self.disconnected.emit()


def connect_local_peer(
    server_name: str,
    *,
    timeout_ms: int = 5000,
    parent: QObject | None = None,
) -> RpcPeer:
    socket = QLocalSocket(parent)
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        raise ProtocolError(f"Could not connect to plugin RPC server: {socket.errorString()}")
    return RpcPeer(socket, parent)
