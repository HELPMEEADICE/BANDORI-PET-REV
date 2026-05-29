import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _token_matches(expected: str, candidate: str) -> bool:
    """Constant-time token comparison to avoid leaking the token via timing."""
    return hmac.compare_digest(str(expected or ""), str(candidate or ""))


class AiStatusHttpServer:
    def __init__(self, port: int, token: str, on_event):
        self._port = int(port)
        self._token = str(token or "")
        self._on_event = on_event
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        return self._port

    def start(self):
        handler = self._handler_class()
        self._server = ThreadingHTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"BandoriAiStatusHttp:{self._port}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._server = None
        self._thread = None

    def _handler_class(self):
        token = self._token
        on_event = self._on_event

        class Handler(BaseHTTPRequestHandler):
            server_version = "BandoriAiStatus/1.0"

            def log_message(self, _format, *_args):
                return

            def do_OPTIONS(self):
                self._send_json({"ok": True}, status=204)

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
                raw = self.rfile.read(max(0, min(length, 1024 * 1024)))
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

            def _authorized(self, parsed) -> bool:
                if not token:
                    return True
                auth = self.headers.get("Authorization", "")
                if _token_matches(f"Bearer {token}", auth):
                    return True
                if _token_matches(token, self.headers.get("X-Bandori-Token", "")):
                    return True
                query_token = parse_qs(parsed.query).get("token", [""])[0]
                return _token_matches(token, query_token)

            def _send_json(self, data: dict, status: int = 200):
                payload = b"" if status == 204 else json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Bandori-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload:
                    self.wfile.write(payload)

        return Handler
