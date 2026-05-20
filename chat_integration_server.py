import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class ChatIntegrationHttpServer:
    def __init__(self, port: int, token: str, on_message, on_read=None):
        self._port = int(port)
        self._token = str(token or "")
        self._on_message = on_message
        self._on_read = on_read
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
            name=f"BandoriChatIntegrationHttp:{self._port}",
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
        on_message = self._on_message
        on_read = self._on_read

        class Handler(BaseHTTPRequestHandler):
            server_version = "BandoriChatIntegration/1.0"

            def log_message(self, _format, *_args):
                return

            def do_OPTIONS(self):
                self._send_json({"ok": True}, status=204)

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path in {"/", "/health", "/chat-events", "/chat-messages"}:
                    self._send_json({
                        "ok": True,
                        "service": "BandoriPet chat integration port",
                        "endpoints": ["/chat-events", "/chat-read"],
                    })
                    return
                self._send_json({"ok": False, "error": "not found"}, status=404)

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path in {"/chat-events", "/chat-event", "/chat-messages", "/chat-message"}:
                    self._handle_chat_events(parsed)
                    return
                if parsed.path == "/chat-read":
                    self._handle_chat_read(parsed)
                    return
                self._send_json({"ok": False, "error": "not found"}, status=404)

            def _handle_chat_events(self, parsed):
                if not self._authorized(parsed):
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                data = self._read_json_body()
                if data is None:
                    return
                events = data if isinstance(data, list) else [data]
                results = []
                for event in events:
                    if not isinstance(event, dict):
                        self._send_json({"ok": False, "error": "each event must be an object"}, status=400)
                        return
                    try:
                        results.append(on_message(event) or {})
                    except Exception as exc:
                        self._send_json({"ok": False, "error": str(exc)}, status=500)
                        return
                payload = {"ok": True, "count": len(results)}
                if len(results) == 1:
                    payload["result"] = results[0]
                else:
                    payload["results"] = results
                self._send_json(payload)

            def _handle_chat_read(self, parsed):
                if not self._authorized(parsed):
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                data = self._read_json_body()
                if data is None:
                    return
                if not isinstance(data, dict):
                    self._send_json({"ok": False, "error": "json body must be an object"}, status=400)
                    return
                if on_read is None:
                    self._send_json({"ok": False, "error": "read endpoint is not available"}, status=404)
                    return
                try:
                    result = on_read(data) or {}
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=500)
                    return
                self._send_json({"ok": True, "result": result})

            def _read_json_body(self):
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    length = 0
                raw = self.rfile.read(max(0, min(length, 1024 * 1024)))
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json({"ok": False, "error": "invalid json"}, status=400)
                    return None

            def _authorized(self, parsed) -> bool:
                if not token:
                    return True
                auth = self.headers.get("Authorization", "")
                if auth == f"Bearer {token}":
                    return True
                if self.headers.get("X-Bandori-Token", "") == token:
                    return True
                query_token = parse_qs(parsed.query).get("token", [""])[0]
                return query_token == token

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
