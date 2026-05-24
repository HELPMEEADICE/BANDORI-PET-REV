import sqlite3
import os
import shutil
import tempfile
import json
import threading
from functools import wraps
from contextlib import closing
from datetime import datetime
from pathlib import Path
from types import FunctionType
from process_utils import app_base_dir

BASE_DIR = app_base_dir()
DB_PATH = os.path.join(BASE_DIR, "data.db")

_REQUIRED_TABLES = {"conversations", "messages", "group_messages"}
_REQUIRED_COLUMNS = {
    "conversations": {"id", "character", "title", "created_at"},
    "messages": {"id", "conversation_id", "role", "content", "created_at"},
    "group_messages": {"id", "group_key", "conversation_id", "role", "content", "created_at"},
}

_VALID_MESSAGE_ROLES = {"user", "assistant", "system"}
_SAFE_CHAT_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def _db_text(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _db_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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
    return resolved.suffix.lower() in _SAFE_CHAT_ATTACHMENT_EXTENSIONS


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
        if str(item.get("type", "") or "") != "image":
            continue
        path = str(item.get("path", "") or "").strip()
        if not _is_safe_chat_attachment_path(path):
            continue
        cleaned_item = {
            "type": "image",
            "path": path,
            "name": str(item.get("name", "") or Path(path).name),
            "mime": str(item.get("mime", "") or "image/png"),
        }
        vision_summary = str(item.get("vision_summary", "") or "").strip()
        if vision_summary:
            cleaned_item["vision_summary"] = vision_summary[:6000]
        vision_error = str(item.get("vision_error", "") or "").strip()
        if vision_error:
            cleaned_item["vision_error"] = vision_error[:600]
        cleaned.append(cleaned_item)
    return cleaned


def _sanitize_database_attachments(conn: sqlite3.Connection):
    for table in ("messages", "group_messages"):
        rows = conn.execute(
            f"SELECT id, attachments_json FROM {table} WHERE attachments_json != ''"
        ).fetchall()
        for row_id, attachments_json in rows:
            cleaned = _sanitize_attachments_payload(attachments_json)
            conn.execute(
                f"UPDATE {table} SET attachments_json=? WHERE id=?",
                (_json_text(cleaned), row_id),
            )


def _message_row_dict(row, grouped: bool = False) -> dict | None:
    role = _db_text(row[3] if grouped else row[2]).strip()
    if role not in _VALID_MESSAGE_ROLES:
        return None

    if grouped:
        msg_id = _db_int(row[0])
        if msg_id is None:
            return None
        return {
            "id": msg_id,
            "group_key": _db_text(row[1]),
            "conversation_id": _db_text(row[2], "default") or "default",
            "role": role,
            "content": _db_text(row[4]),
            "reasoning_content": _db_text(row[5]),
            "attachments_json": _db_text(row[6]),
            "tool_trace_json": _db_text(row[7]),
            "created_at": _db_text(row[8]),
        }

    msg_id = _db_int(row[0])
    conversation_id = _db_int(row[1])
    if msg_id is None or conversation_id is None:
        return None
    return {
        "id": msg_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": _db_text(row[3]),
        "reasoning_content": _db_text(row[4]),
        "attachments_json": _db_text(row[5]),
        "tool_trace_json": _db_text(row[6]),
        "created_at": _db_text(row[7]),
    }


def _memory_row_dict(row) -> dict:
    return {
        "id": _db_int(row[0]) or 0,
        "character": _db_text(row[1]),
        "user_key": _db_text(row[2]),
        "kind": _db_text(row[3], "note") or "note",
        "content": _db_text(row[4]),
        "importance": _db_int(row[5]) or 0,
        "source_message_id": _db_int(row[6]),
        "source_group_message_id": _db_int(row[7]),
        "created_at": _db_text(row[8]),
        "updated_at": _db_text(row[9]),
    }


def _state_row_dict(row) -> dict:
    if not row:
        return {}
    return {
        "id": _db_int(row[0]) or 0,
        "character": _db_text(row[1]),
        "user_key": _db_text(row[2]),
        "affection": _db_int(row[3]) or 50,
        "trust": _db_int(row[4]) or 50,
        "familiarity": _db_int(row[5]) or 0,
        "mood": _db_text(row[6], "calm") or "calm",
        "mood_intensity": _db_int(row[7]) or 20,
        "summary": _db_text(row[8]),
        "updated_at": _db_text(row[9]),
    }


def _external_message_row_dict(row) -> dict:
    return {
        "id": _db_int(row[0]) or 0,
        "platform": _db_text(row[1], "external") or "external",
        "thread_id": _db_text(row[2], "default") or "default",
        "external_message_id": _db_text(row[3]),
        "sender_id": _db_text(row[4]),
        "sender_name": _db_text(row[5]),
        "direction": _db_text(row[6], "inbound") or "inbound",
        "content": _db_text(row[7]),
        "unread": bool(_db_int(row[8])),
        "raw_json": _db_text(row[9]),
        "created_at": _db_text(row[10]),
    }


def _clean_external_text(value, default: str = "") -> str:
    text = _db_text(value, default).strip()
    return text[:500]


def _clean_external_content(value) -> str:
    text = _db_text(value).strip()
    return text[:20_000]


def _clamp_int(value, low: int, high: int, default: int = 0) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _same_path(a: str | os.PathLike, b: str | os.PathLike) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def _validate_chat_database(conn: sqlite3.Connection):
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    missing_tables = _REQUIRED_TABLES - tables
    if missing_tables:
        raise ValueError(f"missing table(s): {', '.join(sorted(missing_tables))}")

    for table, required_columns in _REQUIRED_COLUMNS.items():
        columns = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns = required_columns - columns
        if missing_columns:
            raise ValueError(
                f"table {table} missing column(s): {', '.join(sorted(missing_columns))}"
            )


def _ensure_database(db_path=DB_PATH):
    manager = DatabaseManager(db_path)
    manager.close()


def chat_database_summary(db_path=DB_PATH) -> dict:
    path = Path(db_path)
    if not path.exists():
        return {"conversations": 0, "messages": 0, "group_messages": 0}
    with closing(sqlite3.connect(str(path), timeout=10)) as conn:
        _validate_chat_database(conn)
        conversations = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        group_messages = conn.execute("SELECT COUNT(*) FROM group_messages").fetchone()[0]
    return {"conversations": conversations, "messages": messages, "group_messages": group_messages}


def _read_only_database_uri(path: Path, immutable: bool = False) -> str:
    params = "mode=ro"
    if immutable:
        params += "&immutable=1"
    return path.resolve().as_uri() + "?" + params


def _database_sidecar_paths(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in ("-wal", "-shm")]


def _copy_database_for_import(source: Path, temp_dir: Path) -> Path:
    local_source = temp_dir / source.name
    shutil.copy2(source, local_source)
    for source_sidecar in _database_sidecar_paths(source):
        if source_sidecar.exists():
            local_sidecar = Path(str(local_source) + source_sidecar.name[len(source.name):])
            shutil.copy2(source_sidecar, local_sidecar)
    return local_source


def export_chat_database(destination_path: str, source_path=DB_PATH) -> dict:
    source = Path(source_path)
    destination = Path(destination_path)
    if _same_path(source, destination):
        raise ValueError("source and destination are the same file")

    _ensure_database(str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    os.close(fd)
    try:
        with closing(sqlite3.connect(str(source), timeout=10)) as src:
            _validate_chat_database(src)
            with closing(sqlite3.connect(tmp_path, timeout=10)) as dst:
                src.backup(dst)
                dst.execute("PRAGMA journal_mode=DELETE")
                dst.commit()
        os.replace(tmp_path, destination)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return chat_database_summary(str(destination))


def import_chat_database(source_path: str, target_path=DB_PATH) -> dict:
    source = Path(source_path)
    target = Path(target_path)
    if not source.exists():
        raise FileNotFoundError(str(source))
    if _same_path(source, target):
        raise ValueError("source and target are the same file")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bandori-chat-import-") as temp_dir:
        local_source = _copy_database_for_import(source, Path(temp_dir))
        source_uri = _read_only_database_uri(local_source)
        with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as src:
            _validate_chat_database(src)
            with closing(sqlite3.connect(str(target), timeout=10)) as dst:
                src.backup(dst)
                _sanitize_database_attachments(dst)
                dst.commit()

    _ensure_database(str(target))
    return chat_database_summary(str(target))


def _with_database_lock(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class _DatabaseManagerMeta(type):
    def __new__(mcls, name, bases, namespace):
        for attr_name, attr_value in list(namespace.items()):
            if attr_name == "__init__" or attr_name.startswith("__"):
                continue
            if isinstance(attr_value, FunctionType):
                namespace[attr_name] = _with_database_lock(attr_value)
        return super().__new__(mcls, name, bases, namespace)


class DatabaseManager(metaclass=_DatabaseManagerMeta):
    def __init__(self, db_path=DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                title TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                reasoning_content TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '',
                tool_trace_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS group_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_key TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                reasoning_content TEXT NOT NULL DEFAULT '',
                attachments_json TEXT NOT NULL DEFAULT '',
                tool_trace_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS group_chat_meta (
                group_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS relationship_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                affection INTEGER NOT NULL DEFAULT 50,
                trust INTEGER NOT NULL DEFAULT 50,
                familiarity INTEGER NOT NULL DEFAULT 0,
                mood TEXT NOT NULL DEFAULT 'calm',
                mood_intensity INTEGER NOT NULL DEFAULT 20,
                summary TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(character, user_key)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS character_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'note',
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 50,
                source_message_id INTEGER,
                source_group_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(character, user_key, content)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS mood_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'interaction',
                affection_delta INTEGER NOT NULL DEFAULT 0,
                trust_delta INTEGER NOT NULL DEFAULT 0,
                familiarity_delta INTEGER NOT NULL DEFAULT 0,
                mood TEXT NOT NULL DEFAULT '',
                mood_intensity INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS external_chat_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                thread_name TEXT NOT NULL DEFAULT '',
                unread_count INTEGER NOT NULL DEFAULT 0,
                last_message_id INTEGER,
                last_message_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(platform, thread_id)
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS external_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                external_message_id TEXT NOT NULL DEFAULT '',
                sender_id TEXT NOT NULL DEFAULT '',
                sender_name TEXT NOT NULL DEFAULT '',
                direction TEXT NOT NULL DEFAULT 'inbound' CHECK(direction IN ('inbound', 'outbound', 'draft')),
                content TEXT NOT NULL,
                unread INTEGER NOT NULL DEFAULT 1,
                raw_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_group_messages_key_conv_id ON group_messages(group_key, conversation_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_character_memories_lookup ON character_memories(character, user_key, importance, updated_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_events_lookup ON mood_events(character, user_key, created_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_thread ON external_chat_messages(platform, thread_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_unread ON external_chat_messages(unread, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_external_id ON external_chat_messages(platform, thread_id, external_message_id)")
        columns = [r[1] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "reasoning_content" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''")
        if "attachments_json" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''")
        if "tool_trace_json" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''")
        group_columns = [r[1] for r in self._conn.execute("PRAGMA table_info(group_messages)").fetchall()]
        if "conversation_id" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")
        if "reasoning_content" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''")
        if "attachments_json" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''")
        if "tool_trace_json" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''")
        self._conn.commit()

    def _normalize_user_key(self, user_key: str) -> str:
        return (user_key or "__default__").strip() or "__default__"

    def get_relationship_state(self, character: str, user_key: str = "") -> dict:
        user_key = self._normalize_user_key(user_key)
        row = self._conn.execute(
            "SELECT id, character, user_key, affection, trust, familiarity, mood, mood_intensity, summary, updated_at "
            "FROM relationship_states WHERE character=? AND user_key=?",
            (character, user_key),
        ).fetchone()
        if row:
            return _state_row_dict(row)
        return {
            "id": 0,
            "character": character,
            "user_key": user_key,
            "affection": 50,
            "trust": 50,
            "familiarity": 0,
            "mood": "calm",
            "mood_intensity": 20,
            "summary": "",
            "updated_at": "",
        }

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
        user_key = self._normalize_user_key(user_key)
        current = self.get_relationship_state(character, user_key)
        next_state = {
            "affection": _clamp_int(current["affection"] if affection is None else affection, 0, 100, 50),
            "trust": _clamp_int(current["trust"] if trust is None else trust, 0, 100, 50),
            "familiarity": _clamp_int(current["familiarity"] if familiarity is None else familiarity, 0, 100, 0),
            "mood": (mood if mood is not None else current["mood"]) or "calm",
            "mood_intensity": _clamp_int(
                current["mood_intensity"] if mood_intensity is None else mood_intensity,
                0,
                100,
                20,
            ),
            "summary": current["summary"] if summary is None else str(summary or ""),
        }
        now = _now_text()
        self._conn.execute(
            "INSERT INTO relationship_states "
            "(character, user_key, affection, trust, familiarity, mood, mood_intensity, summary, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(character, user_key) DO UPDATE SET "
            "affection=excluded.affection, trust=excluded.trust, familiarity=excluded.familiarity, "
            "mood=excluded.mood, mood_intensity=excluded.mood_intensity, summary=excluded.summary, "
            "updated_at=excluded.updated_at",
            (
                character,
                user_key,
                next_state["affection"],
                next_state["trust"],
                next_state["familiarity"],
                next_state["mood"],
                next_state["mood_intensity"],
                next_state["summary"],
                now,
            ),
        )
        self._conn.commit()
        return self.get_relationship_state(character, user_key)

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
        user_key = self._normalize_user_key(user_key)
        current = self.get_relationship_state(character, user_key)
        if mood_intensity is None:
            if mood:
                mood_intensity = max(25, min(85, current["mood_intensity"] + 8))
            else:
                mood_intensity = max(10, current["mood_intensity"] - 3)
        next_state = self.upsert_relationship_state(
            character,
            user_key,
            affection=current["affection"] + affection_delta,
            trust=current["trust"] + trust_delta,
            familiarity=current["familiarity"] + familiarity_delta,
            mood=mood or current["mood"],
            mood_intensity=mood_intensity,
        )
        self.add_mood_event(
            character,
            user_key,
            event_type=event_type,
            affection_delta=affection_delta,
            trust_delta=trust_delta,
            familiarity_delta=familiarity_delta,
            mood=mood,
            mood_intensity=mood_intensity,
            reason=reason,
        )
        return next_state

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
        user_key = self._normalize_user_key(user_key)
        content = str(content or "").strip()
        if not content:
            return 0
        kind = (kind or "note").strip() or "note"
        importance = _clamp_int(importance, 1, 100, 50)
        now = _now_text()
        cur = self._conn.execute(
            "INSERT INTO character_memories "
            "(character, user_key, kind, content, importance, source_message_id, source_group_message_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(character, user_key, content) DO UPDATE SET "
            "kind=excluded.kind, importance=max(character_memories.importance, excluded.importance), "
            "source_message_id=coalesce(excluded.source_message_id, character_memories.source_message_id), "
            "source_group_message_id=coalesce(excluded.source_group_message_id, character_memories.source_group_message_id), "
            "updated_at=excluded.updated_at",
            (
                character,
                user_key,
                kind,
                content,
                importance,
                source_message_id,
                source_group_message_id,
                now,
                now,
            ),
        )
        self._conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        row = self._conn.execute(
            "SELECT id FROM character_memories WHERE character=? AND user_key=? AND content=?",
            (character, user_key, content),
        ).fetchone()
        return _db_int(row[0]) if row else 0

    def get_character_memories(self, character: str, user_key: str = "", limit: int = 8) -> list[dict]:
        user_key = self._normalize_user_key(user_key)
        limit = _clamp_int(limit, 1, 100, 8)
        rows = self._conn.execute(
            "SELECT id, character, user_key, kind, content, importance, source_message_id, "
            "source_group_message_id, created_at, updated_at "
            "FROM character_memories WHERE character=? AND user_key=? "
            "ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?",
            (character, user_key, limit),
        ).fetchall()
        return [_memory_row_dict(row) for row in rows]

    def update_character_memory(
        self,
        memory_id: int,
        character: str,
        user_key: str,
        kind: str,
        content: str,
        importance: int = 50,
    ) -> bool:
        user_key = self._normalize_user_key(user_key)
        content = str(content or "").strip()
        if not memory_id or not content:
            return False
        kind = (kind or "note").strip() or "note"
        importance = _clamp_int(importance, 1, 100, 50)
        cur = self._conn.execute(
            "UPDATE character_memories "
            "SET kind=?, content=?, importance=?, updated_at=? "
            "WHERE id=? AND character=? AND user_key=?",
            (kind, content, importance, _now_text(), memory_id, character, user_key),
        )
        self._conn.commit()
        return bool(cur.rowcount)

    def delete_character_memory(self, memory_id: int, character: str = "", user_key: str = "") -> bool:
        if not memory_id:
            return False
        character_filter = str(character or "")
        user_key_filter = self._normalize_user_key(user_key) if user_key else ""
        cur = self._conn.execute(
            "DELETE FROM character_memories "
            "WHERE id=? AND (?='' OR character=?) AND (?='' OR user_key=?)",
            (memory_id, character_filter, character_filter, user_key_filter, user_key_filter),
        )
        self._conn.commit()
        return bool(cur.rowcount)

    def delete_character_memories_like(self, character: str, user_key: str, query: str) -> int:
        user_key = self._normalize_user_key(user_key)
        query = str(query or "").strip()
        if not query:
            return 0
        cur = self._conn.execute(
            "DELETE FROM character_memories WHERE character=? AND user_key=? AND content LIKE ?",
            (character, user_key, f"%{query}%"),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def add_mood_event(
        self,
        character: str,
        user_key: str,
        *,
        event_type: str = "interaction",
        affection_delta: int = 0,
        trust_delta: int = 0,
        familiarity_delta: int = 0,
        mood: str = "",
        mood_intensity: int = 0,
        reason: str = "",
    ) -> int:
        user_key = self._normalize_user_key(user_key)
        cur = self._conn.execute(
            "INSERT INTO mood_events "
            "(character, user_key, event_type, affection_delta, trust_delta, familiarity_delta, mood, mood_intensity, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                character,
                user_key,
                event_type or "interaction",
                _clamp_int(affection_delta, -100, 100, 0),
                _clamp_int(trust_delta, -100, 100, 0),
                _clamp_int(familiarity_delta, -100, 100, 0),
                mood or "",
                _clamp_int(mood_intensity, 0, 100, 0),
                reason or "",
                _now_text(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def create_conversation(self, character: str, title: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self._conn.execute(
            "INSERT INTO conversations (character, title, created_at) VALUES (?, ?, ?)",
            (character, title, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_conversations(self, character: str = "") -> list[dict]:
        if character:
            rows = self._conn.execute(
                "SELECT conversations.id, conversations.character, conversations.title, conversations.created_at, "
                "MAX(messages.created_at) AS last_message_at, MAX(messages.id) AS last_message_id "
                "FROM conversations JOIN messages ON messages.conversation_id=conversations.id "
                "WHERE conversations.character=? "
                "GROUP BY conversations.id, conversations.character, conversations.title, conversations.created_at "
                "ORDER BY last_message_id DESC",
                (character,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT conversations.id, conversations.character, conversations.title, conversations.created_at, "
                "MAX(messages.created_at) AS last_message_at, MAX(messages.id) AS last_message_id "
                "FROM conversations JOIN messages ON messages.conversation_id=conversations.id "
                "GROUP BY conversations.id, conversations.character, conversations.title, conversations.created_at "
                "ORDER BY last_message_id DESC"
            ).fetchall()
        result = []
        for r in rows:
            conv_id = _db_int(r[0])
            if conv_id is None:
                continue
            result.append({
                "id": conv_id,
                "character": _db_text(r[1]),
                "title": _db_text(r[2]),
                "created_at": _db_text(r[3]),
                "last_message_at": _db_text(r[4]) if len(r) > 4 else _db_text(r[3]),
            })
        return result

    def get_last_conversation(self, character: str) -> dict | None:
        row = self._conn.execute(
            "SELECT conversations.id, conversations.character, conversations.title, conversations.created_at, "
            "MAX(messages.created_at) AS last_message_at, MAX(messages.id) AS last_message_id "
            "FROM conversations JOIN messages ON messages.conversation_id=conversations.id "
            "WHERE conversations.character=? "
            "GROUP BY conversations.id, conversations.character, conversations.title, conversations.created_at "
            "ORDER BY last_message_id DESC LIMIT 1",
            (character,)
        ).fetchone()
        if row:
            conv_id = _db_int(row[0])
            if conv_id is None:
                return None
            return {
                "id": conv_id,
                "character": _db_text(row[1]),
                "title": _db_text(row[2]),
                "created_at": _db_text(row[3]),
                "last_message_at": _db_text(row[4]) if len(row) > 4 else _db_text(row[3]),
            }
        return None

    def update_conversation_title(self, conv_id: int, title: str):
        self._conn.execute(
            "UPDATE conversations SET title=? WHERE id=?",
            (title, conv_id)
        )
        self._conn.commit()

    def add_message(self, conversation_id: int, role: str, content: str, reasoning_content: str = "", attachments=None, tool_trace=None) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        attachments_json = _json_text(_sanitize_attachments_payload(attachments))
        tool_trace_json = _json_text(tool_trace)
        cur = self._conn.execute(
            "INSERT INTO messages (conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_messages(self, conversation_id: int, limit: int | None = None) -> list[dict]:
        params: tuple = (conversation_id,)
        order = "ASC"
        limit_sql = ""
        if limit is not None:
            limit = _clamp_int(limit, 1, 1000, 1000)
            params = (conversation_id, limit)
            order = "DESC"
            limit_sql = " LIMIT ?"
        rows = self._conn.execute(
            "SELECT id, conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at FROM messages "
            f"WHERE conversation_id=? ORDER BY id {order}{limit_sql}",
            params,
        ).fetchall()
        if limit is not None:
            rows.reverse()
        result = []
        for r in rows:
            message = _message_row_dict(r)
            if message is not None:
                result.append(message)
        return result

    def get_first_user_message_content(self, conversation_id: int) -> str:
        row = self._conn.execute(
            "SELECT content FROM messages WHERE conversation_id=? AND role='user' AND content != '' "
            "ORDER BY id ASC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        return _db_text(row[0]).strip() if row else ""

    def add_group_message(self, group_key: str, conversation_id: str, role: str, content: str, reasoning_content: str = "", attachments=None, tool_trace=None) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        attachments_json = _json_text(_sanitize_attachments_payload(attachments))
        tool_trace_json = _json_text(tool_trace)
        cur = self._conn.execute(
            "INSERT INTO group_messages (group_key, conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (group_key, conversation_id or "default", role, content, reasoning_content, attachments_json, tool_trace_json, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_group_messages(self, group_key: str, conversation_id: str, limit: int | None = None) -> list[dict]:
        conversation_id = conversation_id or "default"
        params: tuple = (group_key, conversation_id, conversation_id)
        order = "ASC"
        limit_sql = ""
        if limit is not None:
            limit = _clamp_int(limit, 1, 1000, 1000)
            params = (group_key, conversation_id, conversation_id, limit)
            order = "DESC"
            limit_sql = " LIMIT ?"
        rows = self._conn.execute(
            "SELECT id, group_key, conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at FROM group_messages "
            f"WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) ORDER BY id {order}{limit_sql}",
            params,
        ).fetchall()
        if limit is not None:
            rows.reverse()
        result = []
        for r in rows:
            message = _message_row_dict(r, grouped=True)
            if message is not None:
                result.append(message)
        return result

    def delete_group_conversation(self, group_key: str, conversation_id: str):
        conversation_id = conversation_id or "default"
        self._conn.execute(
            "DELETE FROM group_messages WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)",
            (group_key, conversation_id, conversation_id),
        )
        self._conn.commit()

    def get_group_conversations(self, group_key: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT conversation_id, id, role, content, created_at FROM group_messages "
            "WHERE group_key=? ORDER BY id DESC",
            (group_key,)
        ).fetchall()
        result = []
        seen = set()
        for conversation_id, msg_id, role, content, created_at in rows:
            conversation_id = _db_text(conversation_id, "default") or "default"
            if _db_text(role).strip() not in _VALID_MESSAGE_ROLES:
                continue
            msg_id = _db_int(msg_id)
            if msg_id is None:
                continue
            if conversation_id in seen:
                continue
            seen.add(conversation_id)
            result.append({
                "group_key": group_key,
                "conversation_id": conversation_id,
                "message_id": msg_id,
                "role": _db_text(role).strip(),
                "content": _db_text(content),
                "created_at": _db_text(created_at),
            })
        return result

    def get_group_chats(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT group_key, conversation_id, id, role, content, created_at FROM group_messages "
            "ORDER BY id DESC"
        ).fetchall()
        result = []
        seen = set()
        for group_key, conversation_id, msg_id, role, content, created_at in rows:
            group_key = _db_text(group_key)
            conversation_id = _db_text(conversation_id, "default") or "default"
            if _db_text(role).strip() not in _VALID_MESSAGE_ROLES:
                continue
            msg_id = _db_int(msg_id)
            if msg_id is None:
                continue
            if group_key in seen:
                continue
            seen.add(group_key)
            result.append({
                "group_key": group_key,
                "conversation_id": conversation_id,
                "message_id": msg_id,
                "role": _db_text(role).strip(),
                "content": _db_text(content),
                "created_at": _db_text(created_at),
            })
        return result

    def get_group_display_name(self, group_key: str) -> str:
        row = self._conn.execute(
            "SELECT display_name FROM group_chat_meta WHERE group_key=?",
            (group_key,)
        ).fetchone()
        return _db_text(row[0]) if row else ""

    def set_group_display_name(self, group_key: str, display_name: str):
        name = display_name.strip()
        if not name:
            self._conn.execute("DELETE FROM group_chat_meta WHERE group_key=?", (group_key,))
            self._conn.commit()
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._conn.execute(
            "INSERT INTO group_chat_meta (group_key, display_name, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(group_key) DO UPDATE SET display_name=excluded.display_name, updated_at=excluded.updated_at",
            (group_key, name, now)
        )
        self._conn.commit()

    def delete_conversation(self, conv_id: int):
        self._conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        self._conn.commit()

    def delete_empty_conversations(self, character: str = ""):
        if character:
            self._conn.execute(
                "DELETE FROM conversations WHERE character=? AND NOT EXISTS ("
                "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                ")",
                (character,),
            )
        else:
            self._conn.execute(
                "DELETE FROM conversations WHERE NOT EXISTS ("
                "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                ")"
            )
        self._conn.commit()

    def add_external_chat_message(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("chat event must be an object")
        platform = _clean_external_text(event.get("platform") or event.get("source") or "external", "external") or "external"
        thread_id = _clean_external_text(
            event.get("thread_id")
            or event.get("conversation_id")
            or event.get("chat_id")
            or event.get("room_id")
            or "default",
            "default",
        ) or "default"
        thread_name = _clean_external_text(
            event.get("thread_name")
            or event.get("conversation_name")
            or event.get("chat_name")
            or event.get("room_name")
            or thread_id
        )
        external_message_id = _clean_external_text(
            event.get("message_id")
            or event.get("external_message_id")
            or event.get("id")
            or ""
        )
        sender_id = _clean_external_text(event.get("sender_id") or event.get("author_id") or "")
        sender_name = _clean_external_text(
            event.get("sender_name")
            or event.get("author_name")
            or event.get("sender")
            or event.get("from")
            or sender_id
            or "unknown"
        )
        content = _clean_external_content(
            event.get("text")
            or event.get("content")
            or event.get("message")
            or event.get("body")
            or ""
        )
        if not content:
            raise ValueError("chat event text/content is required")

        direction = _clean_external_text(event.get("direction") or "inbound", "inbound").lower()
        if direction not in {"inbound", "outbound", "draft"}:
            direction = "inbound"
        unread = 1 if bool(event.get("unread", direction == "inbound")) and direction == "inbound" else 0
        created_at = _clean_external_text(event.get("timestamp") or event.get("created_at") or _now_text(), _now_text())

        if external_message_id:
            duplicate = self._conn.execute(
                "SELECT id FROM external_chat_messages "
                "WHERE platform=? AND thread_id=? AND external_message_id=? LIMIT 1",
                (platform, thread_id, external_message_id),
            ).fetchone()
            if duplicate:
                return {
                    "duplicate": True,
                    "message_id": _db_int(duplicate[0]) or 0,
                    "thread": self._external_thread_summary(platform, thread_id),
                    "unread": self.get_external_chat_unread_summary(),
                }

        cur = self._conn.execute(
            "INSERT INTO external_chat_messages "
            "(platform, thread_id, external_message_id, sender_id, sender_name, direction, content, unread, raw_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                platform,
                thread_id,
                external_message_id,
                sender_id,
                sender_name,
                direction,
                content,
                unread,
                _json_text(event),
                created_at,
            ),
        )
        message_id = int(cur.lastrowid or 0)
        now = _now_text()
        self._conn.execute(
            "INSERT INTO external_chat_threads "
            "(platform, thread_id, thread_name, unread_count, last_message_id, last_message_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(platform, thread_id) DO UPDATE SET "
            "thread_name=CASE WHEN excluded.thread_name != '' THEN excluded.thread_name ELSE external_chat_threads.thread_name END, "
            "unread_count=external_chat_threads.unread_count + ?, "
            "last_message_id=excluded.last_message_id, "
            "last_message_at=excluded.last_message_at, "
            "updated_at=excluded.updated_at",
            (
                platform,
                thread_id,
                thread_name,
                unread,
                message_id,
                created_at,
                now,
                unread,
            ),
        )
        self._conn.commit()
        return {
            "duplicate": False,
            "message_id": message_id,
            "thread": self._external_thread_summary(platform, thread_id),
            "unread": self.get_external_chat_unread_summary(),
        }

    def _external_thread_summary(self, platform: str, thread_id: str) -> dict:
        row = self._conn.execute(
            "SELECT platform, thread_id, thread_name, unread_count, last_message_at "
            "FROM external_chat_threads WHERE platform=? AND thread_id=?",
            (platform, thread_id),
        ).fetchone()
        if not row:
            return {
                "platform": platform,
                "thread_id": thread_id,
                "thread_name": thread_id,
                "unread_count": 0,
                "last_message_at": "",
            }
        return {
            "platform": _db_text(row[0], "external") or "external",
            "thread_id": _db_text(row[1], "default") or "default",
            "thread_name": _db_text(row[2]) or _db_text(row[1], "default"),
            "unread_count": _db_int(row[3]) or 0,
            "last_message_at": _db_text(row[4]),
        }

    def get_external_chat_unread_summary(self, limit_threads: int = 5, limit_messages: int = 3) -> dict:
        limit_threads = _clamp_int(limit_threads, 1, 20, 5)
        limit_messages = _clamp_int(limit_messages, 1, 10, 3)
        total_row = self._conn.execute(
            "SELECT COALESCE(SUM(unread_count), 0) FROM external_chat_threads"
        ).fetchone()
        total_unread = _db_int(total_row[0] if total_row else 0) or 0
        rows = self._conn.execute(
            "SELECT platform, thread_id, thread_name, unread_count, last_message_at "
            "FROM external_chat_threads WHERE unread_count > 0 "
            "ORDER BY last_message_at DESC, updated_at DESC LIMIT ?",
            (limit_threads,),
        ).fetchall()
        threads = []
        for row in rows:
            platform = _db_text(row[0], "external") or "external"
            thread_id = _db_text(row[1], "default") or "default"
            msg_rows = self._conn.execute(
                "SELECT id, platform, thread_id, external_message_id, sender_id, sender_name, direction, content, unread, raw_json, created_at "
                "FROM external_chat_messages WHERE platform=? AND thread_id=? AND unread=1 "
                "ORDER BY id DESC LIMIT ?",
                (platform, thread_id, limit_messages),
            ).fetchall()
            messages = [_external_message_row_dict(item) for item in reversed(msg_rows)]
            threads.append({
                "platform": platform,
                "thread_id": thread_id,
                "thread_name": _db_text(row[2]) or thread_id,
                "unread_count": _db_int(row[3]) or 0,
                "last_message_at": _db_text(row[4]),
                "messages": messages,
            })
        return {"total_unread": total_unread, "threads": threads}

    def external_chat_context_text(self, limit_threads: int = 4, limit_messages: int = 6) -> str:
        limit_threads = _clamp_int(limit_threads, 1, 12, 4)
        limit_messages = _clamp_int(limit_messages, 1, 20, 6)
        rows = self._conn.execute(
            "SELECT platform, thread_id, thread_name, unread_count, last_message_at "
            "FROM external_chat_threads ORDER BY last_message_at DESC, updated_at DESC LIMIT ?",
            (limit_threads,),
        ).fetchall()
        if not rows:
            return ""
        lines = [
            "【外部聊天软件上下文】",
            "以下是 BandoriPet 最近从外部聊天软件收到的消息。可以用于理解用户当前可能在处理的对话；除非用户要求代写或总结，不要主动暴露隐私细节。",
        ]
        for row in rows:
            platform = _db_text(row[0], "external") or "external"
            thread_id = _db_text(row[1], "default") or "default"
            thread_name = _db_text(row[2]) or thread_id
            unread_count = _db_int(row[3]) or 0
            lines.append(f"[{platform} / {thread_name} / 未读 {unread_count}]")
            msg_rows = self._conn.execute(
                "SELECT id, platform, thread_id, external_message_id, sender_id, sender_name, direction, content, unread, raw_json, created_at "
                "FROM external_chat_messages WHERE platform=? AND thread_id=? "
                "ORDER BY id DESC LIMIT ?",
                (platform, thread_id, limit_messages),
            ).fetchall()
            for message in [_external_message_row_dict(item) for item in reversed(msg_rows)]:
                sender = message["sender_name"] or message["sender_id"] or "unknown"
                content = message["content"].replace("\r", " ").replace("\n", " ").strip()
                if len(content) > 500:
                    content = content[:500] + "..."
                marker = "未读" if message["unread"] else "已读"
                lines.append(f"- {message['created_at']} {sender}（{marker}）：{content}")
        return "\n".join(lines)

    def mark_external_chat_read(self, platform: str = "", thread_id: str = "") -> dict:
        platform = _clean_external_text(platform)
        thread_id = _clean_external_text(thread_id)
        cur = self._conn.execute(
            "UPDATE external_chat_messages SET unread=0 "
            "WHERE unread=1 AND (?='' OR platform=?) AND (?='' OR thread_id=?)",
            (platform, platform, thread_id, thread_id),
        )
        if platform and thread_id:
            self._conn.execute(
                "UPDATE external_chat_threads SET unread_count=0, updated_at=? WHERE platform=? AND thread_id=?",
                (_now_text(), platform, thread_id),
            )
        elif platform:
            self._conn.execute(
                "UPDATE external_chat_threads SET unread_count=0, updated_at=? WHERE platform=?",
                (_now_text(), platform),
            )
        elif thread_id:
            self._conn.execute(
                "UPDATE external_chat_threads SET unread_count=0, updated_at=? WHERE thread_id=?",
                (_now_text(), thread_id),
            )
        else:
            self._conn.execute(
                "UPDATE external_chat_threads SET unread_count=0, updated_at=?",
                (_now_text(),),
            )
        self._conn.commit()
        return {
            "marked_read": int(cur.rowcount or 0),
            "unread": self.get_external_chat_unread_summary(),
        }

    def close(self):
        self._conn.close()
