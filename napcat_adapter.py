"""NapCat (OneBot v11) forward-WebSocket client.

BandoriPet connects *out* to a NapCat WebSocket server (正向 WS), the same way
AstrBot's OneBot adapter does, instead of waiting for NapCat to push to the
local HTTP webhook. Incoming message events are normalized and handed to a
callback; replies are sent back over the same connection via OneBot actions.
"""

import json
import uuid

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest
from PySide6.QtWebSockets import QWebSocket

from onebot_message import normalize_onebot_event

RECONNECT_INTERVAL_MS = 3000


class NapcatClient(QObject):
    """Maintains a forward WebSocket connection to a NapCat OneBot server."""

    status_changed = Signal(str)  # one of: disconnected / connecting / connected / error

    def __init__(self, ws_url: str, access_token: str = "", on_message=None, parent=None):
        super().__init__(parent)
        self._ws_url = str(ws_url or "").strip()
        self._access_token = str(access_token or "").strip()
        self._on_message = on_message
        self._status = "disconnected"
        self._self_id = ""
        self._stopping = False
        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message)
        self._socket.errorOccurred.connect(self._on_error)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.setInterval(RECONNECT_INTERVAL_MS)
        self._reconnect_timer.timeout.connect(self._connect_now)

    # ── lifecycle ──────────────────────────────────────────────────────────
    @property
    def status(self) -> str:
        return self._status

    @property
    def self_id(self) -> str:
        return self._self_id

    def start(self):
        self._stopping = False
        self._connect_now()

    def stop(self):
        self._stopping = True
        self._reconnect_timer.stop()
        try:
            self._socket.close()
        except RuntimeError:
            pass
        self._set_status("disconnected")

    def _connect_now(self):
        if self._stopping or not self._ws_url:
            return
        self._set_status("connecting")
        url = QUrl(self._ws_url)
        if self._access_token:
            # OneBot v11 also accepts the token as a query param; keep it as a
            # fallback for servers that don't read the Authorization header.
            query = url.query()
            token_param = f"access_token={self._access_token}"
            url.setQuery(f"{query}&{token_param}" if query else token_param)
        request = QNetworkRequest(url)
        if self._access_token:
            request.setRawHeader(b"Authorization", f"Bearer {self._access_token}".encode("utf-8"))
        self._socket.open(request)

    def _schedule_reconnect(self):
        if self._stopping:
            return
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    # ── socket signal handlers ─────────────────────────────────────────────
    def _on_connected(self):
        self._set_status("connected")

    def _on_disconnected(self):
        if self._stopping:
            self._set_status("disconnected")
            return
        self._set_status("disconnected")
        self._schedule_reconnect()

    def _on_error(self, _error):
        if self._stopping:
            return
        self._set_status("error")
        self._schedule_reconnect()

    def _on_text_message(self, message: str):
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        # API call responses carry echo/retcode rather than post_type.
        if "post_type" not in data:
            return
        self_id = str(data.get("self_id") or "")
        if self_id:
            self._self_id = self_id
        post_type = str(data.get("post_type") or "").lower()
        if post_type == "meta_event":
            return
        if post_type != "message":
            return
        # Ignore our own outgoing messages to avoid reply loops.
        if self_id and str(data.get("user_id") or "") == self_id:
            return
        normalized = normalize_onebot_event(data)
        if normalized is None:
            return
        if self._on_message is not None:
            self._on_message(normalized)

    # ── outbound actions ───────────────────────────────────────────────────
    def call_action(self, action: str, params: dict):
        if self._status != "connected":
            return False
        payload = {
            "action": action,
            "params": params or {},
            "echo": uuid.uuid4().hex,
        }
        try:
            self._socket.sendTextMessage(json.dumps(payload, ensure_ascii=False))
            return True
        except RuntimeError:
            return False

    def send_reply(self, raw_event: dict, text: str) -> bool:
        """Send a text reply to the group/private chat the event came from."""
        text = str(text or "").strip()
        if not text or not isinstance(raw_event, dict):
            return False
        message_type = str(raw_event.get("message_type") or "").lower()
        group_id = raw_event.get("group_id")
        user_id = raw_event.get("user_id")
        if message_type == "group" and group_id:
            return self.call_action("send_group_msg", {"group_id": group_id, "message": text})
        if user_id:
            return self.call_action("send_private_msg", {"user_id": user_id, "message": text})
        return False

    # ── helpers ────────────────────────────────────────────────────────────
    def _set_status(self, status: str):
        if status == self._status:
            return
        self._status = status
        self.status_changed.emit(status)
