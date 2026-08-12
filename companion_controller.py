from __future__ import annotations

import json
from concurrent.futures import Future
from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal, Slot


PROTOCOL_VERSION = 1
MAX_CHAT_TEXT = 16 * 1024


class CompanionProtocolError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


def _epoch_millis(value: str) -> int:
    try:
        parsed = datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return 0


def _bounded_text(value, max_bytes: int = MAX_CHAT_TEXT) -> str:
    raw = str(value or "").encode("utf-8")
    if len(raw) <= max_bytes:
        return raw.decode("utf-8")
    return raw[:max_bytes].decode("utf-8", errors="ignore")


class CompanionController(QObject):
    """Qt-thread-only facade used by the companion network thread."""

    request_received = Signal(object, object, object)
    event_ready = Signal(str, object, object)
    audio_ready = Signal(str, object)

    def __init__(self, window, config, parent=None):
        super().__init__(parent)
        self.window = window
        self.config = config
        self.request_received.connect(self._handle_request)
        self._last_state_key = ""
        self._last_stream_text = ""
        self._last_capabilities_key = ""
        self.active_profile_key = self._active_profile_key()
        self._state_timer = QTimer(self)
        self._state_timer.setInterval(120)
        self._state_timer.timeout.connect(self._publish_changed_state)
        self._state_timer.start()

    def submit(self, client, request: dict) -> Future:
        future: Future = Future()
        self.request_received.emit(client, request, future)
        return future

    def submit_hello(self, client) -> Future:
        return self.submit(client, {"method": "__session_hello__", "params": {}})

    def _active_profile_key(self) -> str:
        return str(getattr(self.window, "_chat_user_key", "default") or "default")

    def _require_profile(self, client) -> None:
        if str(getattr(client, "profile_key", "default") or "default") != self._active_profile_key():
            raise CompanionProtocolError("PROFILE_UNAVAILABLE")

    def _capabilities(self) -> dict:
        config = self.config
        llm_ready = bool(config.get("llm_api_url", "") and config.get("llm_api_key", "") and config.get("llm_model_id", ""))
        tts_ready = bool(config.get("tts_enabled", False))
        return {
            "privateHistory": True,
            "remoteChat": llm_ready,
            "tts": tts_ready,
            "llmStatus": "recent_failure" if llm_ready and config.get("companion_llm_last_error", "") else ("configured" if llm_ready else "unconfigured"),
            "ttsStatus": "recent_failure" if tts_ready and config.get("companion_tts_last_error", "") else ("configured" if tts_ready else "unconfigured"),
            "actions": True,
            "memory": True,
            "relationship": True,
            "webSearch": bool(config.get("llm_web_search_enabled", False)),
            "attachments": False,
            "asr": False,
            "mcp": False,
            "computerUse": False,
        }

    def hello(self, client) -> dict:
        available = str(getattr(client, "profile_key", "default") or "default") == self._active_profile_key()
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "desktopInstanceId": str(self.config.get("companion_instance_id", "") or ""),
            "profileAvailable": available,
            "capabilities": self._capabilities(),
            "state": self.state_snapshot() if available else self._unavailable_state(),
        }

    @staticmethod
    def _unavailable_state() -> dict:
        return {
            "mode": "profile_unavailable",
            "characterId": None,
            "conversationId": None,
            "conversationTitle": "",
            "messages": [],
            "conversations": [],
            "streamingText": "",
            "isGenerating": False,
            "isThinking": False,
        }

    def state_snapshot(self) -> dict:
        window = self.window
        if bool(getattr(window, "_is_group_chat", False)):
            return {
                "mode": "group_unavailable",
                "characterId": None,
                "conversationId": None,
                "conversationTitle": "",
                "messages": [],
                "conversations": self._conversation_summaries(),
                "streamingText": "",
                "isGenerating": bool(window._generation_busy()),
                "isThinking": False,
            }
        conversation_id = getattr(window, "_conv_id", None)
        conversations = self._conversation_summaries()
        title = next((item["title"] for item in conversations if item["id"] == str(conversation_id)), "")
        is_generating = bool(window._generation_busy())
        return {
            "mode": "private",
            "characterId": str(getattr(window, "_character", "") or ""),
            "conversationId": str(conversation_id) if conversation_id else None,
            "conversationTitle": title,
            "messages": self._messages(conversation_id, limit=100) if conversation_id else [],
            "conversations": conversations,
            "streamingText": str(getattr(window, "_visible_stream_text", "") or "") if is_generating else "",
            "isGenerating": is_generating,
            "isThinking": bool(
                is_generating
                and getattr(window, "_reasoning_stream_text", "")
                and not getattr(window, "_visible_stream_text", "")
            ),
        }

    def _conversation_summaries(self, character: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
        rows = self.window._db.get_conversations(character, self._active_profile_key())
        offset = max(0, int(offset or 0))
        limit = max(1, min(50, int(limit)))
        result = []
        for item in rows[offset: offset + limit]:
            conversation_id = item.get("id")
            title = str(item.get("title", "") or "").strip()
            if not title and conversation_id:
                title = str(self.window._db.get_first_user_message_content(conversation_id) or "").replace("\n", " ")[:32]
            preview = str(item.get("last_message_content", "") or "").replace("\n", " ")[:96]
            result.append({
                "id": str(conversation_id),
                "characterId": str(item.get("character", "") or ""),
                "title": title,
                "preview": preview,
                "createdAt": _epoch_millis(item.get("created_at", "")),
                "updatedAt": _epoch_millis(item.get("last_message_at", item.get("created_at", ""))),
            })
        return result

    def _conversation(self, conversation_id: int) -> dict | None:
        for item in self.window._db.get_conversations(user_key=self._active_profile_key()):
            if int(item.get("id", -1)) == int(conversation_id):
                return item
        return None

    def _messages(self, conversation_id, *, limit: int = 100, before_id=None) -> list[dict]:
        if not conversation_id:
            return []
        rows = self.window._db.get_messages(int(conversation_id), limit=max(1, min(100, int(limit))), before_id=before_id)
        return [{
            "id": str(item.get("id")),
            "conversationId": str(conversation_id),
            "role": str(item.get("role", "user") or "user"),
            "content": _bounded_text(item.get("content", "")),
            "timestamp": _epoch_millis(item.get("created_at", "")),
        } for item in rows if str(item.get("role", "") or "") in {"user", "assistant"}]

    @Slot(object, object, object)
    def _handle_request(self, client, request: dict, future: Future):
        if future.cancelled():
            return
        try:
            method = str(request.get("method", "") or "")
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise CompanionProtocolError("INVALID_PARAMS")
            if method == "__session_hello__":
                result = self.hello(client)
            else:
                self._require_profile(client)
                result = self._dispatch(client, method, params)
        except CompanionProtocolError as exc:
            future.set_exception(exc)
        except Exception:
            future.set_exception(CompanionProtocolError("INTERNAL_ERROR"))
        else:
            future.set_result(result)

    def _dispatch(self, client, method: str, params: dict):
        window = self.window
        if method == "state.get":
            return self.state_snapshot()
        if method == "history.list":
            limit = max(1, min(50, int(params.get("limit", 50))))
            offset = max(0, int(params.get("offset", 0) or 0))
            items = self._conversation_summaries(str(params.get("characterId", "") or ""), limit, offset)
            return {"items": items, "nextOffset": offset + len(items) if len(items) == limit else None}
        if method == "history.messages":
            conversation_id = self._parse_conversation_id(params.get("conversationId"))
            if self._conversation(conversation_id) is None:
                raise CompanionProtocolError("NOT_FOUND")
            before = params.get("beforeMessageId")
            return {"items": self._messages(conversation_id, limit=params.get("limit", 100), before_id=int(before) if before else None)}
        if method == "chat.select":
            if window._chat_context_change_blocked():
                raise CompanionProtocolError("BUSY")
            conversation_id = self._parse_conversation_id(params.get("conversationId"))
            conversation = self._conversation(conversation_id)
            if conversation is None:
                raise CompanionProtocolError("NOT_FOUND")
            character = str(conversation.get("character", "") or "")
            window._switch_chat_members([character])
            window._switch_conversation(conversation_id)
            return self.state_snapshot()
        if method == "chat.new":
            if window._chat_context_change_blocked():
                raise CompanionProtocolError("BUSY")
            character = str(params.get("characterId", "") or "")
            if character not in window._model_manager.characters:
                raise CompanionProtocolError("INVALID_CHARACTER")
            window._switch_chat_members([character])
            window._new_conversation()
            return self.state_snapshot()
        if method == "chat.send":
            if window._generation_busy():
                raise CompanionProtocolError("BUSY")
            if bool(getattr(window, "_is_group_chat", False)):
                raise CompanionProtocolError("GROUP_UNSUPPORTED")
            if window._attachment_import_active():
                raise CompanionProtocolError("BUSY")
            text = str(params.get("text", "") or "").strip()
            if not text or len(text.encode("utf-8")) > MAX_CHAT_TEXT:
                raise CompanionProtocolError("INVALID_TEXT")
            desktop_draft = window._input.toPlainText()
            window._pending_request_origin = f"android:{client.device_id}"
            try:
                window._input.setPlainText(text)
                window._send_message()
                accepted = bool(window._generation_busy() or not window._input.toPlainText().strip())
            finally:
                window._pending_request_origin = "desktop"
                window._input.setPlainText(desktop_draft)
            return {"accepted": accepted}
        if method == "chat.stop":
            if bool(getattr(window, "_is_group_chat", False)):
                raise CompanionProtocolError("GROUP_UNSUPPORTED")
            window._interrupt_generation(clear_input=False)
            return {"stopped": True}
        if method == "chat.retry":
            if window._generation_busy():
                raise CompanionProtocolError("BUSY")
            if bool(getattr(window, "_is_group_chat", False)) or not getattr(window, "_conv_id", None):
                raise CompanionProtocolError("NOT_AVAILABLE")
            history = window._db.get_messages(window._conv_id, limit=2)
            if not history or str(history[-1].get("role", "")) != "user":
                raise CompanionProtocolError("NOT_RETRYABLE")
            window._reload_after_message_change()
            window._last_user_text = str(history[-1].get("content", "") or "")
            window._reset_tts_stream()
            window._stream_buffer = ""
            window._visible_stream_text = ""
            window._reasoning_stream_text = ""
            window._response_save_error_message = ""
            window._pending_request_origin = f"android:{client.device_id}"
            try:
                window._start_response_for_character(window._character, [])
            finally:
                window._pending_request_origin = "desktop"
            return {"accepted": bool(window._generation_busy())}
        if method == "history.delete_conversation":
            if window._generation_busy():
                raise CompanionProtocolError("BUSY")
            conversation_id = self._parse_conversation_id(params.get("conversationId"))
            if self._conversation(conversation_id) is None:
                raise CompanionProtocolError("NOT_FOUND")
            window._delete_conversation(conversation_id)
            return self.state_snapshot()
        if method == "tts.replay":
            if (
                window._generation_busy()
                or bool(getattr(window, "_tts_active_workers", {}))
                or not window._tts_player.is_idle()
            ):
                raise CompanionProtocolError("BUSY")
            if not self._capabilities().get("tts"):
                raise CompanionProtocolError("TTS_UNAVAILABLE")
            conversation_id = self._parse_conversation_id(params.get("conversationId"))
            conversation = self._conversation(conversation_id)
            if conversation is None:
                raise CompanionProtocolError("NOT_FOUND")
            message_id = str(params.get("messageId", "") or "")
            message = next((item for item in window._db.get_messages(conversation_id) if str(item.get("id")) == message_id), None)
            if message is None or str(message.get("role", "")) != "assistant":
                raise CompanionProtocolError("INVALID_MESSAGE")
            text = str(message.get("content", "") or "").strip()
            if not text:
                raise CompanionProtocolError("INVALID_MESSAGE")
            window._reset_tts_stream()
            window._tts_request_allowed = True
            sequence = window._tts_next_sequence
            window._tts_next_sequence += 1
            character = str(conversation.get("character", "") or "")
            window._tts_characters[sequence] = character
            window._tts_destinations[sequence] = f"android:{client.device_id}"
            window._tts_chunk_sequences[sequence] = 0
            window._queue_tts_request(sequence, text, character)
            window._start_next_tts_request()
            return {"accepted": True}
        raise CompanionProtocolError("METHOD_NOT_FOUND")

    @staticmethod
    def _parse_conversation_id(value) -> int:
        try:
            result = int(str(value))
        except (TypeError, ValueError, OverflowError) as exc:
            raise CompanionProtocolError("INVALID_CONVERSATION_ID") from exc
        if result <= 0:
            raise CompanionProtocolError("INVALID_CONVERSATION_ID")
        return result

    def _state_key(self, state: dict) -> str:
        stable = dict(state)
        stable.pop("streamingText", None)
        return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _publish_changed_state(self):
        profile_key = self._active_profile_key()
        if profile_key != self.active_profile_key:
            self.active_profile_key = profile_key
            self._last_state_key = ""
            self._last_stream_text = ""
            self.event_ready.emit("profile.changed", {"profileAvailable": False}, None)
        try:
            state = self.state_snapshot()
        except Exception:
            return
        capabilities = self._capabilities()
        capabilities_key = json.dumps(capabilities, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if capabilities_key != self._last_capabilities_key:
            self._last_capabilities_key = capabilities_key
            self.event_ready.emit("capabilities.changed", capabilities, None)
        key = self._state_key(state)
        if key != self._last_state_key:
            self._last_state_key = key
            self.event_ready.emit("state.changed", state, None)
        stream_text = str(state.get("streamingText", "") or "")
        if stream_text != self._last_stream_text:
            self._last_stream_text = stream_text
            self.event_ready.emit("generation.delta", {
                "conversationId": state.get("conversationId"),
                "text": stream_text,
                "isGenerating": state.get("isGenerating", False),
            }, None)

    def publish_tts_audio(self, device_id: str, payload: dict) -> None:
        self.audio_ready.emit(str(device_id or ""), payload)
