"""Stable Python API for the Rust SQLite persistence engine.

UI orchestration and incoming attachment policy remain Python. Schema, SQL,
transactions, locking, queries, row conversion and backup run in pet-db.
There is no Python SQLite fallback and imports never invoke Cargo.
"""
import json
import os
import tempfile
from contextlib import closing
from functools import lru_cache
from pathlib import Path

# Retained as an exception namespace and for existing diagnostic imports.
import sqlite3

from bandori_core.process_utils import app_base_dir, app_data_dir
from bandori_core.native_database import NativeConnection, native_class, open_native

BASE_DIR = app_data_dir()
LEGACY_BASE_DIR = app_base_dir()
DB_PATH = os.path.join(BASE_DIR, "data.db")


def _migrate_legacy_database(db_path):
    target = Path(db_path)
    legacy = LEGACY_BASE_DIR / "data.db"
    if target == Path(DB_PATH) and LEGACY_BASE_DIR != BASE_DIR and legacy.is_file():
        native_class().migrate_legacy(str(legacy), str(target))


def _json_text(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _chat_attachment_dir() -> Path:
    return BASE_DIR / "chat_attachments"


def _is_safe_chat_attachment_path(path: str) -> bool:
    text = str(path or "").strip()
    if not text:
        return False
    try:
        resolved = Path(text).resolve()
        resolved.relative_to(_chat_attachment_dir().resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return resolved.exists() and resolved.is_file()


def _sanitize_attachments_payload(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list):
        return []

    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "") or "").strip().lower()
        if item_type not in {"image", "file"}:
            continue
        path = str(item.get("path", "") or "").strip()
        if not _is_safe_chat_attachment_path(path):
            continue
        cleaned_item = {
            "type": item_type,
            "path": path,
            "name": str(item.get("name", "") or Path(path).name)[:240],
            "mime": str(item.get("mime", "") or ("image/png" if item_type == "image" else "application/octet-stream"))[:160],
        }
        try:
            cleaned_item["size"] = int(item.get("size", "") or Path(path).stat().st_size)
        except (OSError, TypeError, ValueError):
            pass
        uploaded_at = str(item.get("uploaded_at", "") or "").strip()
        if uploaded_at:
            cleaned_item["uploaded_at"] = uploaded_at[:40]
        vision_summary = str(item.get("vision_summary", "") or "").strip()
        if item_type == "image" and vision_summary:
            cleaned_item["vision_summary"] = vision_summary[:6000]
        vision_error = str(item.get("vision_error", "") or "").strip()
        if item_type == "image" and vision_error:
            cleaned_item["vision_error"] = vision_error[:600]
        cleaned.append(cleaned_item)
    return cleaned


def _sanitize_database_attachments(conn):
    return conn._native.call("sanitize_attachments", {"attachment_dir": str(_chat_attachment_dir())})


def _same_path(a, b):
    a, b = Path(a), Path(b)
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))


def chat_database_summary(db_path=DB_PATH) -> dict:
    if not Path(db_path).exists():
        return {"conversations": 0, "messages": 0, "group_messages": 0}
    return native_class().summary(str(db_path))


def sanitize_chat_attachment_references(db_path=DB_PATH) -> int:
    with closing(DatabaseManager(db_path)) as db:
        return _sanitize_database_attachments(db._conn)


def export_chat_database(destination_path: str, source_path=DB_PATH) -> dict:
    if _same_path(source_path, destination_path):
        raise ValueError("source and destination are the same file")
    with closing(DatabaseManager(source_path)):
        native_class().snapshot(str(source_path), str(destination_path))
    return chat_database_summary(destination_path)


def import_chat_database(source_path: str, target_path=DB_PATH) -> dict:
    if not Path(source_path).exists():
        raise FileNotFoundError(str(source_path))
    if _same_path(source_path, target_path):
        raise ValueError("source and target are the same file")
    # All preparation and attachment policy complete on a private staged snapshot.
    # The target is updated through SQLite, so other processes see the new data.
    with tempfile.TemporaryDirectory(prefix="bandori-chat-import-") as temp:
        staged = Path(temp) / "staged.db"
        native_class().snapshot(str(source_path), str(staged))
        with closing(DatabaseManager(staged)) as db:
            _sanitize_database_attachments(db._conn)
        with closing(DatabaseManager(target_path)) as db:
            db._native.restore(str(staged))
    return chat_database_summary(target_path)


def export_relationship_data(db_path=DB_PATH) -> dict:
    with closing(DatabaseManager(db_path)) as db:
        return db._native.call("export_relationship_data", {})


def import_relationship_data(data, db_path=DB_PATH) -> dict:
    if not isinstance(data, dict):
        raise ValueError("relationship data must be a JSON object")
    with closing(DatabaseManager(db_path)) as db:
        return db._native.call("import_relationship_data", {"data": data})


class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        _migrate_legacy_database(db_path)
        self._native = open_native(db_path)
        self._conn = NativeConnection(self._native)
        self._closed = False

    def __del__(self):
        try:
            if not getattr(self, "_closed", True):
                self.close()
        except Exception:
            pass

    def close(self):
        self._native.close()
        self._closed = True

    def _invoke(self, operation, args):
        args.pop("self", None)
        if operation in {"add_message", "add_group_message"}:
            args["attachments_json"] = _json_text(_sanitize_attachments_payload(args.pop("attachments")))
            args["tool_trace_json"] = _json_text(args.pop("tool_trace"))
        elif operation == "add_external_chat_message":
            args["raw_json"] = _json_text(args["event"])
        elif "character_aliases" in args:
            args["character_aliases"] = list(args["character_aliases"] or [])
        elif operation == "delete_character_memories":
            args["memory_ids"] = list(args["memory_ids"])
        elif operation == "get_messages_per_character_range":
            args["asset_dir"] = str(LEGACY_BASE_DIR)
        result = self._native.call(operation, args)
        if operation == "change_revision":
            return tuple(result)
        if operation == "get_chat_history_filter_options":
            for key in ("characters", "user_keys"):
                result[key].sort(key=str.casefold)
        return result

    def add_messages(self, conversation_id: int, messages) -> list[int]:
        """Atomically insert a batch; the single-message API remains unchanged."""
        batch = []
        for item in messages:
            batch.append({
                "role": item["role"], "content": item["content"],
                "reasoning_content": item.get("reasoning_content", ""),
                "attachments_json": _json_text(_sanitize_attachments_payload(item.get("attachments"))),
                "tool_trace_json": _json_text(item.get("tool_trace")),
            })
        return self._native.call("add_messages", {"conversation_id": conversation_id, "messages": batch})

    def integrity_check(self):
        return self._native.call("integrity_check", {})

    def assign_legacy_chat_history_user(self, user_key: str) -> int:
        return self._invoke("assign_legacy_chat_history_user", locals())

    def get_relationship_state(self, character: str, user_key: str = "") -> dict:
        return self._invoke("get_relationship_state", locals())

    def upsert_relationship_state(
        self,
        character: str,
        user_key: str = "",
        *,
        affection: int | None = None,
        trust: int | None = None,
        familiarity: int | None = None,
        mood: str | None = None,
        mood_intensity: int | None = None,
        summary: str | None = None,
    ) -> dict:
        return self._invoke("upsert_relationship_state", locals())

    def apply_relationship_delta(
        self,
        character: str,
        user_key: str = "",
        *,
        affection_delta: int = 0,
        trust_delta: int = 0,
        familiarity_delta: int = 0,
        mood: str = "",
        mood_intensity: int | None = None,
        event_type: str = "interaction",
        reason: str = "",
    ) -> dict:
        return self._invoke("apply_relationship_delta", locals())

    def add_character_memory(
        self,
        character: str,
        user_key: str,
        kind: str,
        content: str,
        importance: int = 50,
        *,
        source_message_id: int | None = None,
        source_group_message_id: int | None = None,
    ) -> int:
        return self._invoke("add_character_memory", locals())

    def get_character_memories(self, character: str, user_key: str = "", limit: int = 8) -> list[dict]:
        return self._invoke("get_character_memories", locals())

    def get_character_memories_by_kind(
        self,
        character: str,
        user_key: str = "",
        kind: str = "",
        limit: int = 50,
    ) -> list[dict]:
        return self._invoke("get_character_memories_by_kind", locals())

    def update_character_memory(
        self,
        memory_id: int,
        character: str,
        user_key: str,
        kind: str,
        content: str,
        importance: int = 50,
    ) -> bool:
        return self._invoke("update_character_memory", locals())

    def delete_character_memory(self, memory_id: int, character: str = "", user_key: str = "") -> bool:
        return self._invoke("delete_character_memory", locals())

    def delete_character_memories(self, memory_ids, character: str = "", user_key: str = "") -> int:
        return self._invoke("delete_character_memories", locals())

    def delete_character_memories_like(self, character: str, user_key: str, query: str) -> int:
        return self._invoke("delete_character_memories_like", locals())

    def create_conversation(self, character: str, title: str = "", user_key: str = "") -> int:
        return self._invoke("create_conversation", locals())

    def change_revision(self) -> tuple[int, int]:
        return self._invoke("change_revision", locals())

    def get_conversations(self, character: str = "", user_key: str | None = None) -> list[dict]:
        return self._invoke("get_conversations", locals())

    def get_last_conversation(self, character: str, user_key: str | None = None) -> dict | None:
        return self._invoke("get_last_conversation", locals())

    def get_conversation_temporary_background(self, conversation_id: int | None) -> str:
        return self._invoke("get_conversation_temporary_background", locals())

    def set_conversation_temporary_background(self, conversation_id: int, content: str) -> None:
        return self._invoke("set_conversation_temporary_background", locals())

    def add_message(self, conversation_id: int, role: str, content: str, reasoning_content: str = "", attachments=None, tool_trace=None) -> int:
        return self._invoke("add_message", locals())

    def update_message_content(self, conversation_id: int, message_id: int, content: str) -> bool:
        return self._invoke("update_message_content", locals())

    def delete_messages_from(
        self,
        conversation_id: int,
        message_id: int,
        *,
        include_selected: bool = True,
    ) -> list[dict]:
        return self._invoke("delete_messages_from", locals())

    def delete_message(self, conversation_id: int, message_id: int) -> list[dict]:
        return self._invoke("delete_message", locals())

    def get_conversation_token_usage(self, conversation_id: int | None) -> dict:
        return self._invoke("get_conversation_token_usage", locals())

    def get_group_conversation_token_usage(
        self,
        group_key: str,
        conversation_id: str,
        user_key: str | None = None,
    ) -> dict:
        return self._invoke("get_group_conversation_token_usage", locals())

    def get_messages(
        self,
        conversation_id: int,
        limit: int | None = None,
        before_id: int | None = None,
    ) -> list[dict]:
        return self._invoke("get_messages", locals())

    def get_conversation_attachment_payloads(self, conversation_id: int) -> list[str]:
        return self._invoke("get_conversation_attachment_payloads", locals())

    def get_chat_history_filter_options(self) -> dict:
        return self._invoke("get_chat_history_filter_options", locals())

    def search_chat_history(
        self,
        *,
        keyword: str = "",
        date_from: str = "",
        date_to: str = "",
        character: str = "",
        user_key: str = "",
        role: str = "",
        source: str = "",
        limit: int = 300,
        offset: int = 0,
        skip_count: bool = False,
    ) -> dict:
        return self._invoke("search_chat_history", locals())

    def get_first_user_message_content(self, conversation_id: int) -> str:
        return self._invoke("get_first_user_message_content", locals())

    def add_group_message(self, group_key: str, conversation_id: str, role: str, content: str, reasoning_content: str = "", attachments=None, tool_trace=None, user_key: str = "") -> int:
        return self._invoke("add_group_message", locals())

    def update_group_message_content(
        self,
        group_key: str,
        conversation_id: str,
        message_id: int,
        content: str,
        user_key: str | None = None,
    ) -> bool:
        return self._invoke("update_group_message_content", locals())

    def delete_group_messages_from(
        self,
        group_key: str,
        conversation_id: str,
        message_id: int,
        *,
        include_selected: bool = True,
        user_key: str | None = None,
    ) -> list[dict]:
        return self._invoke("delete_group_messages_from", locals())

    def delete_group_message(
        self,
        group_key: str,
        conversation_id: str,
        message_id: int,
        user_key: str | None = None,
    ) -> list[dict]:
        return self._invoke("delete_group_message", locals())

    def get_group_messages(
        self,
        group_key: str,
        conversation_id: str,
        limit: int | None = None,
        user_key: str | None = None,
        before_id: int | None = None,
    ) -> list[dict]:
        return self._invoke("get_group_messages", locals())

    def get_group_conversation_attachment_payloads(
        self,
        group_key: str,
        conversation_id: str,
        user_key: str | None = None,
    ) -> list[str]:
        return self._invoke("get_group_conversation_attachment_payloads", locals())

    def delete_group_conversation(self, group_key: str, conversation_id: str, user_key: str | None = None):
        return self._invoke("delete_group_conversation", locals())

    def get_group_conversations(self, group_key: str, user_key: str | None = None) -> list[dict]:
        return self._invoke("get_group_conversations", locals())

    def get_group_conversation_temporary_background(
        self,
        group_key: str,
        conversation_id: str,
        user_key: str | None = None,
    ) -> str:
        return self._invoke("get_group_conversation_temporary_background", locals())

    def set_group_conversation_temporary_background(
        self,
        group_key: str,
        conversation_id: str,
        content: str,
        user_key: str = "",
    ) -> None:
        return self._invoke("set_group_conversation_temporary_background", locals())

    def get_group_chats(self, user_key: str | None = None) -> list[dict]:
        return self._invoke("get_group_chats", locals())

    def get_group_display_name(self, group_key: str) -> str:
        return self._invoke("get_group_display_name", locals())

    def set_group_display_name(self, group_key: str, display_name: str):
        return self._invoke("set_group_display_name", locals())

    def delete_conversation(self, conv_id: int):
        return self._invoke("delete_conversation", locals())

    def delete_empty_conversations(self, character: str = "", user_key: str | None = None):
        return self._invoke("delete_empty_conversations", locals())

    def add_external_chat_message(self, event: dict) -> dict:
        return self._invoke("add_external_chat_message", locals())

    def get_external_chat_unread_summary(self, limit_threads: int = 5, limit_messages: int = 3) -> dict:
        return self._invoke("get_external_chat_unread_summary", locals())

    def external_chat_context_text(
        self, limit_threads: int = 4, limit_messages: int = 6, *,
        platform: str | None = None, thread_id: str | None = None,
        chat_type: str | None = None,
    ) -> str:
        return self._invoke("external_chat_context_text", locals())

    def mark_external_chat_read(self, platform: str = "", thread_id: str = "") -> dict:
        return self._invoke("mark_external_chat_read", locals())

    def prune_external_group_chat_limit(self) -> dict:
        return self._invoke("prune_external_group_chat_limit", locals())

    def delete_external_chat(self, chat_type: str = "", platform: str = "") -> dict:
        return self._invoke("delete_external_chat", locals())

    def purge_external_chat_older_than(self, days, chat_type: str = "", platform: str = "") -> dict:
        return self._invoke("purge_external_chat_older_than", locals())

    def start_usage_session(self) -> int:
        return self._invoke("start_usage_session", locals())

    def end_usage_session(self, session_id: int):
        return self._invoke("end_usage_session", locals())

    def heartbeat_usage_session(self, session_id: int):
        return self._invoke("heartbeat_usage_session", locals())

    def get_usage_today(self) -> int:
        return self._invoke("get_usage_today", locals())

    def get_usage_week(self) -> int:
        return self._invoke("get_usage_week", locals())

    def get_usage_all_time(self) -> int:
        return self._invoke("get_usage_all_time", locals())

    def get_usage_daily(self, days: int = 30) -> list[dict]:
        return self._invoke("get_usage_daily", locals())

    def get_mood_events_for_chart(self, character: str, days: int = 30,
                                  user_key: str = "") -> list[dict]:
        return self._invoke("get_mood_events_for_chart", locals())

    def get_chat_summary(self) -> dict:
        return self._invoke("get_chat_summary", locals())

    def get_daily_message_counts(self, days: int = 30, user_key: str | None = None) -> list[dict]:
        return self._invoke("get_daily_message_counts", locals())

    def get_messages_per_character_range(self, days: int = 0, user_key: str = "") -> list[dict]:
        return self._invoke("get_messages_per_character_range", locals())

    def get_hourly_heatmap(self, days: int = 7, user_key: str | None = None) -> list[list[int]]:
        return self._invoke("get_hourly_heatmap", locals())

    @staticmethod
    def _group_key_characters(group_key: str) -> list[str]:
        prefix = "__group__:"
        if not group_key.startswith(prefix):
            return []
        return [part for part in group_key[len(prefix):].split("|") if part]

    @staticmethod
    @lru_cache(maxsize=256)
    def _character_display_aliases(character: str) -> set[str]:
        aliases = {str(character or "").strip()}
        try:
            data = json.loads((LEGACY_BASE_DIR / "outfit.json").read_text(encoding="utf-8"))
            info = data.get("characters", {}).get(character, {})
            display = str(info.get("display", "") or "").strip()
            if display:
                aliases.add(display)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        aliases.discard("")
        return aliases

    def get_character_recent_messages(
        self,
        character: str,
        user_key: str = "",
        limit: int = 24,
        character_aliases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        return self._invoke("get_character_recent_messages", locals())

    def get_character_conversation_chain(
        self,
        character: str,
        user_key: str = "",
        limit: int = 20,
        character_aliases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        return self._invoke("get_character_conversation_chain", locals())

    def get_character_album_days(
        self,
        character: str,
        user_key: str = "",
        limit: int = 30,
        character_aliases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        return self._invoke("get_character_album_days", locals())

