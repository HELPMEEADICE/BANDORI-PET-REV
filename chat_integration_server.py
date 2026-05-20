import json
import threading
from datetime import datetime
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
                if parsed.path in {"/chat-events", "/chat-event", "/chat-messages", "/chat-message"}:
                    data = self._query_payload(parsed)
                    if self._looks_like_chat_event(data):
                        self._handle_chat_events(parsed, data)
                        return
                    self._send_service_info()
                    return
                if parsed.path == "/chat-read":
                    self._handle_chat_read(parsed, self._query_payload(parsed))
                    return
                if parsed.path in {"/", "/health"}:
                    self._send_service_info()
                    return
                self._send_json({"ok": False, "error": "not found"}, status=404)

            def _send_service_info(self):
                self._send_json({
                    "ok": True,
                    "service": "BandoriPet chat integration port",
                    "endpoints": ["/chat-events", "/chat-read"],
                    "formats": ["application/json", "application/x-www-form-urlencoded", "text/plain", "query"],
                })

            def do_POST(self):
                parsed = urlparse(self.path)
                if parsed.path in {"/chat-events", "/chat-event", "/chat-messages", "/chat-message"}:
                    self._handle_chat_events(parsed)
                    return
                if parsed.path == "/chat-read":
                    self._handle_chat_read(parsed)
                    return
                self._send_json({"ok": False, "error": "not found"}, status=404)

            def _handle_chat_events(self, parsed, data=None):
                if not self._authorized(parsed):
                    self._send_json({
                        "ok": False,
                        "error": "unauthorized",
                    }, status=401)
                    return
                if data is None:
                    data = self._read_request_body()
                if data is None:
                    return
                events = data if isinstance(data, list) else [data]
                results = []
                for event in events:
                    if not isinstance(event, dict):
                        self._send_json({"ok": False, "error": "each event must be an object"}, status=400)
                        return
                    event = self._normalize_event(event)
                    if event is None:
                        results.append({"ignored": True})
                        continue
                    try:
                        results.append(on_message(event) or {})
                    except ValueError as exc:
                        self._send_json({"ok": False, "error": str(exc)}, status=400)
                        return
                    except Exception as exc:
                        self._send_json({"ok": False, "error": str(exc)}, status=500)
                        return
                payload = {"ok": True, "count": len(results)}
                if len(results) == 1:
                    payload["result"] = results[0]
                else:
                    payload["results"] = results
                self._send_json(payload)

            def _handle_chat_read(self, parsed, data=None):
                if not self._authorized(parsed):
                    self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                    return
                if data is None:
                    data = self._read_request_body()
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
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=500)
                    return
                self._send_json({"ok": True, "result": result})

            def _read_request_body(self):
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    length = 0
                raw = self.rfile.read(max(0, min(length, 1024 * 1024)))
                if not raw:
                    return {}
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type == "application/x-www-form-urlencoded":
                    try:
                        return self._flatten_params(parse_qs(raw.decode("utf-8"), keep_blank_values=True))
                    except UnicodeDecodeError:
                        self._send_json({"ok": False, "error": "invalid form data"}, status=400)
                        return None
                if content_type == "text/plain":
                    try:
                        return {"text": raw.decode("utf-8")}
                    except UnicodeDecodeError:
                        self._send_json({"ok": False, "error": "invalid text data"}, status=400)
                        return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json({"ok": False, "error": "invalid json"}, status=400)
                    return None

            def _query_payload(self, parsed) -> dict:
                data = self._flatten_params(parse_qs(parsed.query, keep_blank_values=True))
                data.pop("token", None)
                return data

            def _flatten_params(self, params: dict) -> dict:
                flattened = {}
                for key, values in params.items():
                    if not key:
                        continue
                    if isinstance(values, list):
                        flattened[key] = values[-1] if values else ""
                    else:
                        flattened[key] = values
                return flattened

            def _looks_like_chat_event(self, data: dict) -> bool:
                if not isinstance(data, dict):
                    return False
                return any(key in data for key in ("text", "content", "message", "body"))

            def _normalize_event(self, event: dict) -> dict | None:
                post_type = str(event.get("post_type") or "").lower()
                if not post_type:
                    return event
                if post_type != "message":
                    return None
                text = self._onebot_message_text(event)
                if not text:
                    return None
                message_type = str(event.get("message_type") or "").lower()
                sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
                sender_id = str(event.get("user_id") or sender.get("user_id") or "")
                sender_name = (
                    str(sender.get("card") or "").strip()
                    or str(sender.get("nickname") or "").strip()
                    or sender_id
                    or "unknown"
                )
                group_id = str(event.get("group_id") or "")
                if message_type == "group" and group_id:
                    thread_id = group_id
                    thread_name = str(event.get("group_name") or event.get("group_id") or "QQ 群聊")
                else:
                    thread_id = sender_id or str(event.get("target_id") or "private")
                    thread_name = sender_name or "QQ 私聊"
                normalized = {
                    "platform": "qq",
                    "thread_id": thread_id or "default",
                    "thread_name": thread_name,
                    "sender_id": sender_id,
                    "sender_name": sender_name,
                    "text": text,
                    "message_id": str(event.get("message_id") or event.get("message_seq") or ""),
                    "raw_event": event,
                }
                if event.get("time"):
                    try:
                        normalized["timestamp"] = datetime.fromtimestamp(int(event["time"])).strftime("%Y-%m-%d %H:%M:%S")
                    except (OSError, TypeError, ValueError, OverflowError):
                        pass
                return normalized

            def _onebot_message_text(self, event: dict) -> str:
                raw_message = event.get("raw_message")
                if raw_message:
                    return str(raw_message).strip()
                message = event.get("message")
                if isinstance(message, str):
                    return message.strip()
                if isinstance(message, list):
                    parts = [self._onebot_segment_text(item) for item in message]
                    return "".join(part for part in parts if part).strip()
                return str(event.get("content") or event.get("text") or "").strip()

            def _onebot_segment_text(self, segment) -> str:
                if isinstance(segment, str):
                    return segment
                if not isinstance(segment, dict):
                    return ""
                seg_type = str(segment.get("type") or "").lower()
                data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
                if seg_type == "text":
                    return str(data.get("text") or "")
                if seg_type == "at":
                    qq = str(data.get("qq") or "").strip()
                    return f"@{qq} " if qq else "@ "
                if seg_type in {"face", "emoji"}:
                    return f"[{seg_type}:{data.get('id') or ''}]"
                if seg_type in {"image", "record", "video", "file"}:
                    return f"[{seg_type}]"
                return f"[{seg_type}]" if seg_type else ""

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
