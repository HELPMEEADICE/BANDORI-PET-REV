import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from process_utils import token_matches


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class LocalJsonRequestHandler(BaseHTTPRequestHandler):
    auth_token = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5.0)

    def log_message(self, _format, *_args):
        return

    def do_OPTIONS(self):
        self._send_json({"ok": True}, status=204)

    def _authorized(self, parsed) -> bool:
        token = self.auth_token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if token_matches(f"Bearer {token}", auth):
            return True
        if token_matches(token, self.headers.get("X-Bandori-Token", "")):
            return True
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        return token_matches(token, query_token)

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


class LocalHttpServer:
    thread_name_prefix = "BandoriLocalHttp"

    def __init__(self, port: int, token: str):
        self._port = int(port)
        self._token = str(token or "")
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        return self._port

    def start(self):
        self._server = LocalThreadingHTTPServer(("127.0.0.1", self._port), self._handler_class())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"{self.thread_name_prefix}:{self._port}",
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
        raise NotImplementedError
