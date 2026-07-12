import json
from urllib.parse import parse_qs, urlparse

from local_http_server import LocalHttpServer, LocalJsonRequestHandler
from onebot_message import normalize_onebot_event


def _prepare_chat_event_batch(events, normalize_event) -> list[dict | None]:
    events = events if isinstance(events, list) else [events]
    invalid_index = next(
        (index for index, event in enumerate(events) if not isinstance(event, dict)),
        None,
    )
    if invalid_index is not None:
        raise ValueError(f"event at index {invalid_index} must be an object")
    return [normalize_event(event) for event in events]


class ChatIntegrationHttpServer(LocalHttpServer):
    thread_name_prefix = "BandoriChatIntegrationHttp"

    def __init__(self, port: int, token: str, on_message, on_read=None):
        super().__init__(port, token)
        self._on_message = on_message
        self._on_read = on_read

    def _handler_class(self):
        handler_token = self._token
        on_message = self._on_message
        on_read = self._on_read

        class Handler(LocalJsonRequestHandler):
            server_version = "BandoriChatIntegration/1.0"
            auth_token = handler_token

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
                try:
                    events = _prepare_chat_event_batch(data, self._normalize_event)
                except ValueError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                results = []
                for index, event in enumerate(events):
                    if event is None:
                        results.append({"ignored": True})
                        continue
                    try:
                        results.append(on_message(event) or {})
                    except ValueError as exc:
                        self._send_json({
                            "ok": False,
                            "error": str(exc),
                            "failed_index": index,
                            "processed_count": len(results),
                        }, status=400)
                        return
                    except Exception as exc:
                        self._send_json({
                            "ok": False,
                            "error": str(exc),
                            "failed_index": index,
                            "processed_count": len(results),
                        }, status=500)
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
                try:
                    raw = self.rfile.read(max(0, min(length, 1024 * 1024)))
                except TimeoutError:
                    try:
                        self._send_json({"ok": False, "error": "request body timeout"}, status=408)
                    except OSError:
                        pass
                    return None
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
                return normalize_onebot_event(event)

        return Handler
