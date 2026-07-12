import json
from urllib.parse import urlparse

from local_http_server import LocalHttpServer, LocalJsonRequestHandler


class AiStatusHttpServer(LocalHttpServer):
    thread_name_prefix = "BandoriAiStatusHttp"

    def __init__(self, port: int, token: str, on_event):
        super().__init__(port, token)
        self._on_event = on_event

    def _handler_class(self):
        handler_token = self._token
        on_event = self._on_event

        class Handler(LocalJsonRequestHandler):
            server_version = "BandoriAiStatus/1.0"
            auth_token = handler_token

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in {"/", "/health", "/ai-events"}:
                    self._send_json({"ok": True, "service": "BandoriPet AI status port"})
                    return
                self._send_json({"ok": False, "error": "not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path not in {"/ai-events", "/ai-event"}:
                    self._send_json({"ok": False, "error": "not found"}, status=404)
                    return
                if not self._authorized(parsed):
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    length = 0
                try:
                    raw = self.rfile.read(max(0, min(length, 1024 * 1024)))
                except TimeoutError:
                    try:
                        self._send_json({"ok": False, "error": "request body timeout"}, status=408)
                    except OSError:
                        pass
                    return
                try:
                    event = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json({"ok": False, "error": "invalid json"}, status=400)
                    return
                if not isinstance(event, dict):
                    self._send_json({"ok": False, "error": "json body must be an object"}, status=400)
                    return
                try:
                    on_event(event)
                except Exception:
                    self._send_json({"ok": False, "error": "event dispatch failed"}, status=500)
                    return
                self._send_json({"ok": True})

        return Handler
