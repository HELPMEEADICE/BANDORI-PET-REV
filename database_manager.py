import sqlite3
import os
import shutil
import tempfile
import json
import re
import threading
import time
from functools import wraps, lru_cache
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from types import FunctionType
from process_utils import app_base_dir, clamp_int as _clamp_int

BASE_DIR = app_base_dir()
DB_PATH = os.path.join(BASE_DIR, "data.db")
_DB_LOCKS: dict[str, "_DatabaseFileLock"] = {}
_DB_LOCKS_GUARD = threading.Lock()

_REQUIRED_TABLES = {"conversations", "messages", "group_messages"}
_REQUIRED_COLUMNS = {
    "conversations": {"id", "character", "title", "created_at"},
    "messages": {"id", "conversation_id", "role", "content", "created_at"},
    "group_messages": {"id", "group_key", "conversation_id", "role", "content", "created_at"},
}

_VALID_MESSAGE_ROLES = {"user", "assistant", "system"}
_EXTERNAL_GROUP_CHAT_MESSAGE_LIMIT = 50


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


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class _DatabaseFileLock:
    _LOCK_TIMEOUT_SECONDS = 10.0

    def __init__(self, db_path: str):
        self._thread_lock = threading.RLock()
        self._local = threading.local()
        lock_path = Path(db_path).resolve().with_suffix(Path(db_path).suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = lock_path
        self._file = None

    def __enter__(self):
        self._thread_lock.acquire()
        try:
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                try:
                    self._lock_file()
                except Exception:
                    self.close()
                    raise
            self._local.depth = depth + 1
            return self
        except Exception:
            self._thread_lock.release()
            raise

    def __exit__(self, exc_type, exc, tb):
        depth = getattr(self._local, "depth", 0) - 1
        try:
            if depth <= 0:
                self._local.depth = 0
                self._unlock_file()
            else:
                self._local.depth = depth
        finally:
            self._thread_lock.release()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def close(self):
        file = getattr(self, "_file", None)
        if file is not None and not file.closed:
            file.close()

    def _lock_file(self):
        if self._file is None or self._file.closed:
            self._file = open(self._lock_path, "a+b")
        self._file.seek(0)
        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + self._LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
                    return
                except OSError as exc:
                    if getattr(exc, "errno", None) not in {13, 36}:
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for database lock: {self._file.name}") from exc
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)

    def _unlock_file(self):
        if self._file is None or self._file.closed:
            return
        self._file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self.close()

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


def _sanitize_database_attachments(conn: sqlite3.Connection):
    removed = 0
    for table in ("messages", "group_messages"):
        rows = conn.execute(
            f"SELECT id, attachments_json FROM {table} WHERE attachments_json != ''"
        ).fetchall()
        for row_id, attachments_json in rows:
            cleaned = _sanitize_attachments_payload(attachments_json)
            try:
                original = json.loads(attachments_json)
            except (TypeError, ValueError):
                original = []
            if isinstance(original, list):
                removed += max(0, len(original) - len(cleaned))
            conn.execute(
                f"UPDATE {table} SET attachments_json=? WHERE id=?",
                (_json_text(cleaned), row_id),
            )
    return removed


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


def _album_message_row_dict(row, grouped: bool = False) -> dict | None:
    message = _message_row_dict(row, grouped=grouped)
    if message is None:
        return None
    message["source"] = "group" if grouped else "private"
    if grouped and message.get("role") == "assistant":
        message["speaker"] = _group_message_speaker(message.get("content", ""))
    return message


def _group_message_speaker(content: str) -> str:
    first_line = str(content or "").splitlines()[0].strip() if content else ""
    if first_line.startswith("【") and "】" in first_line:
        return first_line[1:first_line.index("】")].strip()
    return ""


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


def sanitize_chat_attachment_references(db_path=DB_PATH) -> int:
    _ensure_database(db_path)
    with _shared_database_lock(str(db_path)):
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            removed = _sanitize_database_attachments(conn)
            conn.commit()
            return removed


def _read_only_database_uri(path: Path, immutable: bool = False) -> str:
    params = "mode=ro"
    if immutable:
        params += "&immutable=1"
    return path.resolve().as_uri() + "?" + params


def _database_sidecar_paths(path: Path) -> list[Path]:
    return [Path(str(path) + suffix) for suffix in ("-wal", "-shm")]


def _checkpoint_database(path: Path, mode: str = "TRUNCATE"):
    if not path.exists():
        return
    with closing(sqlite3.connect(str(path), timeout=10)) as conn:
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchall()


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
    _checkpoint_database(source, "PASSIVE")
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

    with _shared_database_lock(str(target)):
        target.parent.mkdir(parents=True, exist_ok=True)
        _ensure_database(str(target))
        _checkpoint_database(target)
        with tempfile.TemporaryDirectory(prefix="bandori-chat-import-") as temp_dir:
            local_source = _copy_database_for_import(source, Path(temp_dir))
            source_uri = _read_only_database_uri(local_source)
            with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as src:
                _validate_chat_database(src)
                with closing(sqlite3.connect(str(target), timeout=10)) as dst:
                    dst.execute("PRAGMA busy_timeout=10000")
                    src.backup(dst)
                    _sanitize_database_attachments(dst)
                    dst.commit()
                    _validate_chat_database(dst)

        _checkpoint_database(target)
        return chat_database_summary(str(target))


def export_relationship_data(db_path=DB_PATH) -> dict:
    _ensure_database(db_path)
    path = Path(db_path)
    if not path.exists():
        return {"relationship_states": [], "character_memories": []}
    with closing(sqlite3.connect(str(path), timeout=10)) as conn:
        states = [
            _state_row_dict(row)
            for row in conn.execute(
                "SELECT id, character, user_key, affection, trust, familiarity, mood, "
                "mood_intensity, summary, updated_at "
                "FROM relationship_states ORDER BY character, user_key"
            ).fetchall()
        ]
        memories = [
            _memory_row_dict(row)
            for row in conn.execute(
                "SELECT id, character, user_key, kind, content, importance, "
                "source_message_id, source_group_message_id, created_at, updated_at "
                "FROM character_memories ORDER BY character, user_key, importance DESC, updated_at DESC, id DESC"
            ).fetchall()
        ]
    return {
        "relationship_states": states,
        "character_memories": memories,
    }


def import_relationship_data(data, db_path=DB_PATH) -> dict:
    if not isinstance(data, dict):
        raise ValueError("relationship data must be a JSON object")

    _ensure_database(db_path)
    states = data.get("relationship_states", [])
    memories = data.get("character_memories", [])
    if not isinstance(states, list):
        states = []
    if not isinstance(memories, list):
        memories = []

    state_count = 0
    memory_count = 0
    with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
        for item in states:
            if not isinstance(item, dict):
                continue
            character = _db_text(item.get("character")).strip()
            if not character:
                continue
            user_key = _db_text(item.get("user_key"), "__default__").strip() or "__default__"
            updated_at = _db_text(item.get("updated_at")) or _now_text()
            conn.execute(
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
                    _clamp_int(item.get("affection"), 0, 100, 50),
                    _clamp_int(item.get("trust"), 0, 100, 50),
                    _clamp_int(item.get("familiarity"), 0, 100, 0),
                    _db_text(item.get("mood"), "calm").strip() or "calm",
                    _clamp_int(item.get("mood_intensity"), 0, 100, 20),
                    _db_text(item.get("summary")),
                    updated_at,
                ),
            )
            state_count += 1

        for item in memories:
            if not isinstance(item, dict):
                continue
            character = _db_text(item.get("character")).strip()
            content = _db_text(item.get("content")).strip()
            if not character or not content:
                continue
            user_key = _db_text(item.get("user_key"), "__default__").strip() or "__default__"
            created_at = _db_text(item.get("created_at")) or _now_text()
            updated_at = _db_text(item.get("updated_at")) or created_at
            conn.execute(
                "INSERT INTO character_memories "
                "(character, user_key, kind, content, importance, source_message_id, "
                "source_group_message_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(character, user_key, content) DO UPDATE SET "
                "kind=excluded.kind, importance=excluded.importance, "
                "source_message_id=coalesce(excluded.source_message_id, character_memories.source_message_id), "
                "source_group_message_id=coalesce(excluded.source_group_message_id, character_memories.source_group_message_id), "
                "updated_at=excluded.updated_at",
                (
                    character,
                    user_key,
                    _db_text(item.get("kind"), "note").strip() or "note",
                    content,
                    _clamp_int(item.get("importance"), 1, 100, 50),
                    _db_int(item.get("source_message_id")),
                    _db_int(item.get("source_group_message_id")),
                    created_at,
                    updated_at,
                ),
            )
            memory_count += 1
        conn.commit()
    return {
        "relationship_states": state_count,
        "character_memories": memory_count,
    }


def _with_database_lock(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            try:
                return method(self, *args, **kwargs)
            except Exception:
                _rollback_quietly(getattr(self, "_conn", None))
                raise
    return wrapper


def _database_is_locked_error(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc).lower()


def _try_database_operation(operation):
    try:
        return True, operation()
    except sqlite3.OperationalError as exc:
        return False, exc


def _rollback_quietly(conn):
    if conn is None:
        return
    try:
        conn.rollback()
    except sqlite3.Error:
        pass


def _shared_database_lock(db_path: str) -> _DatabaseFileLock:
    key = str(Path(db_path).resolve())
    with _DB_LOCKS_GUARD:
        lock = _DB_LOCKS.get(key)
        if lock is None:
            lock = _DatabaseFileLock(db_path)
            _DB_LOCKS[key] = lock
        return lock


def _sleep_outside_rlock(lock, seconds: float):
    release_save = getattr(lock, "_release_save", None)
    acquire_restore = getattr(lock, "_acquire_restore", None)
    if release_save is None or acquire_restore is None:
        time.sleep(seconds)
        return
    state = release_save()
    try:
        time.sleep(seconds)
    finally:
        acquire_restore(state)


def _run_with_locked_retry(conn, operation, attempts: int = 5, delay: float = 0.25, lock=None):
    for attempt in range(max(1, attempts)):
        ok, result = _try_database_operation(operation)
        if ok:
            return result
        exc = result
        if not _database_is_locked_error(exc) or attempt >= attempts - 1:
            raise exc
        _rollback_quietly(conn)
        seconds = delay * (attempt + 1)
        if lock is not None:
            _sleep_outside_rlock(lock, seconds)
        else:
            time.sleep(seconds)


class _DatabaseManagerMeta(type):
    def __new__(mcls, name, bases, namespace):
        for attr_name, attr_value in list(namespace.items()):
            if attr_name in {"__init__", "close"} or attr_name.startswith("__"):
                continue
            if isinstance(attr_value, FunctionType):
                namespace[attr_name] = _with_database_lock(attr_value)
        return super().__new__(mcls, name, bases, namespace)


class DatabaseManager(metaclass=_DatabaseManagerMeta):
    def __init__(self, db_path=DB_PATH):
        self._lock = _shared_database_lock(db_path)
        with self._lock:
            self._conn = sqlite3.connect(db_path, timeout=2, check_same_thread=False)
            self._conn.execute("PRAGMA busy_timeout=2000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_tables()
            self._closed = False

    def __del__(self):
        try:
            if not getattr(self, "_closed", True):
                self.close()
        except Exception:
            pass

    def _create_tables(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                character TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
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
                user_key TEXT NOT NULL DEFAULT '',
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
                affection INTEGER,
                trust INTEGER,
                familiarity INTEGER,
                mood TEXT NOT NULL DEFAULT '',
                mood_intensity INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                end_time TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS external_chat_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                thread_name TEXT NOT NULL DEFAULT '',
                chat_type TEXT NOT NULL DEFAULT '',
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
                chat_type TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        columns = [r[1] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "reasoning_content" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''")
        if "attachments_json" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''")
        if "tool_trace_json" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''")
        conversation_columns = [r[1] for r in self._conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "user_key" not in conversation_columns:
            self._conn.execute("ALTER TABLE conversations ADD COLUMN user_key TEXT NOT NULL DEFAULT ''")
        group_columns = [r[1] for r in self._conn.execute("PRAGMA table_info(group_messages)").fetchall()]
        if "conversation_id" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")
        if "user_key" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN user_key TEXT NOT NULL DEFAULT ''")
        if "reasoning_content" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''")
        if "attachments_json" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN attachments_json TEXT NOT NULL DEFAULT ''")
        if "tool_trace_json" not in group_columns:
            self._conn.execute("ALTER TABLE group_messages ADD COLUMN tool_trace_json TEXT NOT NULL DEFAULT ''")
        external_msg_columns = [r[1] for r in self._conn.execute("PRAGMA table_info(external_chat_messages)").fetchall()]
        if "chat_type" not in external_msg_columns:
            self._conn.execute("ALTER TABLE external_chat_messages ADD COLUMN chat_type TEXT NOT NULL DEFAULT ''")
        external_thread_columns = [r[1] for r in self._conn.execute("PRAGMA table_info(external_chat_threads)").fetchall()]
        if "chat_type" not in external_thread_columns:
            self._conn.execute("ALTER TABLE external_chat_threads ADD COLUMN chat_type TEXT NOT NULL DEFAULT ''")
        mood_event_columns = [r[1] for r in self._conn.execute("PRAGMA table_info(mood_events)").fetchall()]
        if "affection" not in mood_event_columns:
            self._conn.execute("ALTER TABLE mood_events ADD COLUMN affection INTEGER")
        if "trust" not in mood_event_columns:
            self._conn.execute("ALTER TABLE mood_events ADD COLUMN trust INTEGER")
        if "familiarity" not in mood_event_columns:
            self._conn.execute("ALTER TABLE mood_events ADD COLUMN familiarity INTEGER")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_id ON messages(conversation_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv_role_id ON messages(conversation_id, role, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_character_user ON conversations(character, user_key, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_group_messages_key_user_conv_id ON group_messages(group_key, user_key, conversation_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_character_memories_lookup ON character_memories(character, user_key, importance, updated_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_events_lookup ON mood_events(character, user_key, created_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_thread ON external_chat_messages(platform, thread_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_unread ON external_chat_messages(unread, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_external_id ON external_chat_messages(platform, thread_id, external_message_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_chat_type ON external_chat_messages(chat_type, created_at)")
        self._conn.commit()

    def _normalize_user_key(self, user_key: str) -> str:
        return (user_key or "__default__").strip() or "__default__"

    def assign_legacy_chat_history_user(self, user_key: str) -> int:
        user_key = self._normalize_user_key(user_key)
        def operation():
            conv_cur = self._conn.execute(
                "UPDATE conversations SET user_key=? WHERE user_key='' OR user_key IS NULL",
                (user_key,),
            )
            group_cur = self._conn.execute(
                "UPDATE group_messages SET user_key=? WHERE user_key='' OR user_key IS NULL",
                (user_key,),
            )
            self._conn.commit()
            return int(conv_cur.rowcount or 0) + int(group_cur.rowcount or 0)

        return _run_with_locked_retry(self._conn, operation, lock=self._lock)

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
        numeric_changed = (
            (affection is not None and next_state["affection"] != current["affection"])
            or (trust is not None and next_state["trust"] != current["trust"])
            or (familiarity is not None and next_state["familiarity"] != current["familiarity"])
        )
        mood_changed = (
            (mood is not None and next_state["mood"] != current["mood"])
            or (mood_intensity is not None and next_state["mood_intensity"] != current["mood_intensity"])
        )
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
        if numeric_changed or mood_changed:
            self._conn.execute(
                "INSERT INTO mood_events "
                "(character, user_key, event_type, affection_delta, trust_delta, familiarity_delta, "
                "affection, trust, familiarity, mood, mood_intensity, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    character,
                    user_key,
                    "manual_set",
                    next_state["affection"] - current["affection"],
                    next_state["trust"] - current["trust"],
                    next_state["familiarity"] - current["familiarity"],
                    next_state["affection"],
                    next_state["trust"],
                    next_state["familiarity"],
                    next_state["mood"] if mood_changed else "",
                    next_state["mood_intensity"] if mood_changed else 0,
                    "manual relationship state update",
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

        now = _now_text()
        next_values = {
            "affection": _clamp_int(current["affection"] + affection_delta, 0, 100, 50),
            "trust": _clamp_int(current["trust"] + trust_delta, 0, 100, 50),
            "familiarity": _clamp_int(current["familiarity"] + familiarity_delta, 0, 100, 0),
            "mood": mood or current["mood"] or "calm",
            "mood_intensity": _clamp_int(mood_intensity, 0, 100, 20),
            "summary": current["summary"],
        }
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
                next_values["affection"],
                next_values["trust"],
                next_values["familiarity"],
                next_values["mood"],
                next_values["mood_intensity"],
                next_values["summary"],
                now,
            ),
        )
        self._conn.execute(
            "INSERT INTO mood_events "
            "(character, user_key, event_type, affection_delta, trust_delta, familiarity_delta, "
            "affection, trust, familiarity, mood, mood_intensity, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                character,
                user_key,
                event_type or "interaction",
                _clamp_int(affection_delta, -100, 100, 0),
                _clamp_int(trust_delta, -100, 100, 0),
                _clamp_int(familiarity_delta, -100, 100, 0),
                next_values["affection"],
                next_values["trust"],
                next_values["familiarity"],
                mood or "",
                _clamp_int(mood_intensity, 0, 100, 0),
                str(reason or "")[:500],
                now,
            ),
        )
        next_state = self.get_relationship_state(character, user_key)
        self._conn.commit()
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

    def get_character_memories_by_kind(
        self,
        character: str,
        user_key: str = "",
        kind: str = "",
        limit: int = 50,
    ) -> list[dict]:
        user_key = self._normalize_user_key(user_key)
        kind = str(kind or "").strip()
        limit = _clamp_int(limit, 1, 200, 50)
        if not kind:
            return self.get_character_memories(character, user_key, limit)
        rows = self._conn.execute(
            "SELECT id, character, user_key, kind, content, importance, source_message_id, "
            "source_group_message_id, created_at, updated_at "
            "FROM character_memories WHERE character=? AND user_key=? AND kind=? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (character, user_key, kind, limit),
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

    def delete_character_memories(self, memory_ids, character: str = "", user_key: str = "") -> int:
        ids = set()
        for memory_id in memory_ids:
            try:
                normalized_id = int(memory_id or 0)
            except (TypeError, ValueError):
                continue
            if normalized_id > 0:
                ids.add(normalized_id)
        ids = sorted(ids)
        if not ids:
            return 0
        character_filter = str(character or "")
        user_key_filter = self._normalize_user_key(user_key) if user_key else ""
        placeholders = ",".join("?" for _ in ids)
        cur = self._conn.execute(
            "DELETE FROM character_memories "
            f"WHERE id IN ({placeholders}) AND (?='' OR character=?) AND (?='' OR user_key=?)",
            (*ids, character_filter, character_filter, user_key_filter, user_key_filter),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def delete_character_memories_like(self, character: str, user_key: str, query: str) -> int:
        user_key = self._normalize_user_key(user_key)
        query = str(query or "").strip()
        if not query:
            return 0
        cur = self._conn.execute(
            "DELETE FROM character_memories WHERE character=? AND user_key=? AND content LIKE ? ESCAPE '\\'",
            (character, user_key, f"%{_escape_like(query)}%"),
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

    def create_conversation(self, character: str, title: str = "", user_key: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_key = self._normalize_user_key(user_key)
        cur = self._conn.execute(
            "INSERT INTO conversations (character, user_key, title, created_at) VALUES (?, ?, ?, ?)",
            (character, user_key, title, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_conversations(self, character: str = "", user_key: str | None = None) -> list[dict]:
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None
        if character:
            where = "WHERE c.character=?"
            params: tuple = (character,)
            if user_filter is not None:
                where += " AND c.user_key=?"
                params = (character, user_filter)
            rows = self._conn.execute(
                "SELECT c.id, c.character, c.user_key, c.title, c.created_at, "
                "latest.created_at AS last_message_at, latest.id AS last_message_id, latest.content AS last_message_content "
                "FROM conversations c "
                "JOIN messages latest ON latest.id=("
                "SELECT MAX(m.id) FROM messages m WHERE m.conversation_id=c.id"
                ") "
                f"{where} "
                "ORDER BY latest.id DESC",
                params,
            ).fetchall()
        else:
            where = ""
            params = ()
            if user_filter is not None:
                where = "WHERE c.user_key=?"
                params = (user_filter,)
            rows = self._conn.execute(
                "SELECT c.id, c.character, c.user_key, c.title, c.created_at, "
                "latest.created_at AS last_message_at, latest.id AS last_message_id, latest.content AS last_message_content "
                "FROM conversations c "
                "JOIN messages latest ON latest.id=("
                "SELECT MAX(m.id) FROM messages m WHERE m.conversation_id=c.id"
                ") "
                f"{where} "
                "ORDER BY latest.id DESC",
                params,
            ).fetchall()
        result = []
        for r in rows:
            conv_id = _db_int(r[0])
            if conv_id is None:
                continue
            result.append({
                "id": conv_id,
                "character": _db_text(r[1]),
                "user_key": _db_text(r[2]),
                "title": _db_text(r[3]),
                "created_at": _db_text(r[4]),
                "last_message_at": _db_text(r[5]) if len(r) > 5 else _db_text(r[4]),
                "last_message_content": _db_text(r[7]) if len(r) > 7 else "",
            })
        return result

    def get_last_conversation(self, character: str, user_key: str | None = None) -> dict | None:
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None
        where = "WHERE c.character=?"
        params: tuple = (character,)
        if user_filter is not None:
            where += " AND c.user_key=?"
            params = (character, user_filter)
        row = self._conn.execute(
            "SELECT c.id, c.character, c.user_key, c.title, c.created_at, "
            "latest.created_at AS last_message_at, latest.id AS last_message_id, latest.content AS last_message_content "
            "FROM conversations c "
            "JOIN messages latest ON latest.id=("
            "SELECT MAX(m.id) FROM messages m WHERE m.conversation_id=c.id"
            ") "
            f"{where} "
            "ORDER BY latest.id DESC LIMIT 1",
            params,
        ).fetchone()
        if row:
            conv_id = _db_int(row[0])
            if conv_id is None:
                return None
            return {
                "id": conv_id,
                "character": _db_text(row[1]),
                "user_key": _db_text(row[2]),
                "title": _db_text(row[3]),
                "created_at": _db_text(row[4]),
                "last_message_at": _db_text(row[5]) if len(row) > 5 else _db_text(row[4]),
                "last_message_content": _db_text(row[7]) if len(row) > 7 else "",
            }
        return None

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

    def add_group_message(self, group_key: str, conversation_id: str, role: str, content: str, reasoning_content: str = "", attachments=None, tool_trace=None, user_key: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_key = self._normalize_user_key(user_key)
        attachments_json = _json_text(_sanitize_attachments_payload(attachments))
        tool_trace_json = _json_text(tool_trace)
        cur = self._conn.execute(
            "INSERT INTO group_messages (group_key, conversation_id, user_key, role, content, reasoning_content, attachments_json, tool_trace_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (group_key, conversation_id or "default", user_key, role, content, reasoning_content, attachments_json, tool_trace_json, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_group_messages(self, group_key: str, conversation_id: str, limit: int | None = None, user_key: str | None = None) -> list[dict]:
        conversation_id = conversation_id or "default"
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None
        where = "WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)"
        params: tuple = (group_key, conversation_id, conversation_id)
        if user_filter is not None:
            where += " AND user_key=?"
            params = (group_key, conversation_id, conversation_id, user_filter)
        order = "ASC"
        limit_sql = ""
        if limit is not None:
            limit = _clamp_int(limit, 1, 1000, 1000)
            params = (*params, limit)
            order = "DESC"
            limit_sql = " LIMIT ?"
        rows = self._conn.execute(
            "SELECT id, group_key, conversation_id, role, content, reasoning_content, attachments_json, tool_trace_json, created_at FROM group_messages "
            f"{where} ORDER BY id {order}{limit_sql}",
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

    def delete_group_conversation(self, group_key: str, conversation_id: str, user_key: str | None = None):
        conversation_id = conversation_id or "default"
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None

        def operation():
            if user_filter is None:
                self._conn.execute(
                    "DELETE FROM group_messages WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?)",
                    (group_key, conversation_id, conversation_id),
                )
            else:
                self._conn.execute(
                    "DELETE FROM group_messages WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) AND user_key=?",
                    (group_key, conversation_id, conversation_id, user_filter),
                )
            self._conn.commit()

        _run_with_locked_retry(self._conn, operation, lock=self._lock)

    def get_group_conversations(self, group_key: str, user_key: str | None = None) -> list[dict]:
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None
        where = "WHERE group_key=?"
        params: tuple = (group_key,)
        if user_filter is not None:
            where += " AND user_key=?"
            params = (group_key, user_filter)
        rows = self._conn.execute(
            "SELECT g.conversation_id, g.user_key, g.id, g.role, g.content, g.created_at "
            "FROM group_messages g "
            "JOIN ("
            "SELECT conversation_id, MAX(id) AS latest_id FROM group_messages "
            f"{where} AND role IN ('user', 'assistant', 'system') "
            "GROUP BY conversation_id"
            ") latest ON g.id=latest.latest_id "
            "ORDER BY latest.latest_id DESC",
            params,
        ).fetchall()
        result = []
        for conversation_id, row_user_key, msg_id, role, content, created_at in rows:
            conversation_id = _db_text(conversation_id, "default") or "default"
            if _db_text(role).strip() not in _VALID_MESSAGE_ROLES:
                continue
            msg_id = _db_int(msg_id)
            if msg_id is None:
                continue
            result.append({
                "group_key": group_key,
                "conversation_id": conversation_id,
                "user_key": _db_text(row_user_key),
                "message_id": msg_id,
                "role": _db_text(role).strip(),
                "content": _db_text(content),
                "created_at": _db_text(created_at),
            })
        return result

    def get_group_chats(self, user_key: str | None = None) -> list[dict]:
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None
        where = ""
        params: tuple = ()
        if user_filter is not None:
            where = "WHERE user_key=?"
            params = (user_filter,)
        rows = self._conn.execute(
            "SELECT g.group_key, g.conversation_id, g.user_key, g.id, g.role, g.content, g.created_at "
            "FROM group_messages g "
            "JOIN ("
            "SELECT group_key, MAX(id) AS latest_id FROM group_messages "
            f"{where} "
            f"{'AND' if where else 'WHERE'} role IN ('user', 'assistant', 'system') "
            "GROUP BY group_key"
            ") latest ON g.id=latest.latest_id "
            "ORDER BY latest.latest_id DESC",
            params,
        ).fetchall()
        result = []
        for group_key, conversation_id, row_user_key, msg_id, role, content, created_at in rows:
            group_key = _db_text(group_key)
            conversation_id = _db_text(conversation_id, "default") or "default"
            if _db_text(role).strip() not in _VALID_MESSAGE_ROLES:
                continue
            msg_id = _db_int(msg_id)
            if msg_id is None:
                continue
            result.append({
                "group_key": group_key,
                "conversation_id": conversation_id,
                "user_key": _db_text(row_user_key),
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
        def operation():
            self._conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
            self._conn.commit()

        _run_with_locked_retry(self._conn, operation, lock=self._lock)

    def delete_empty_conversations(self, character: str = "", user_key: str | None = None):
        user_filter = self._normalize_user_key(user_key) if user_key is not None else None
        def operation():
            if character:
                where = "character=?"
                params: tuple = (character,)
                if user_filter is not None:
                    where += " AND user_key=?"
                    params = (character, user_filter)
                self._conn.execute(
                    f"DELETE FROM conversations WHERE {where} AND NOT EXISTS ("
                    "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                    ")",
                    params,
                )
            else:
                self._conn.execute(
                    "DELETE FROM conversations WHERE NOT EXISTS ("
                    "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                    ")"
                )
            self._conn.commit()

        _run_with_locked_retry(self._conn, operation, lock=self._lock)

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
        chat_type = _clean_external_text(event.get("chat_type") or "").lower()
        if chat_type not in {"group", "private"}:
            chat_type = ""
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
            "(platform, thread_id, external_message_id, sender_id, sender_name, direction, content, unread, chat_type, raw_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                platform,
                thread_id,
                external_message_id,
                sender_id,
                sender_name,
                direction,
                content,
                unread,
                chat_type,
                _json_text(event),
                created_at,
            ),
        )
        message_id = int(cur.lastrowid or 0)
        now = _now_text()
        self._conn.execute(
            "INSERT INTO external_chat_threads "
            "(platform, thread_id, thread_name, chat_type, unread_count, last_message_id, last_message_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(platform, thread_id) DO UPDATE SET "
            "thread_name=CASE WHEN excluded.thread_name != '' THEN excluded.thread_name ELSE external_chat_threads.thread_name END, "
            "chat_type=CASE WHEN excluded.chat_type != '' THEN excluded.chat_type ELSE external_chat_threads.chat_type END, "
            "unread_count=external_chat_threads.unread_count + ?, "
            "last_message_id=excluded.last_message_id, "
            "last_message_at=excluded.last_message_at, "
            "updated_at=excluded.updated_at",
            (
                platform,
                thread_id,
                thread_name,
                chat_type,
                unread,
                message_id,
                created_at,
                now,
                unread,
            ),
        )
        pruned_messages = 0
        if chat_type == "group":
            pruned_messages = self._prune_external_group_thread_messages(platform, thread_id)
        self._conn.commit()
        return {
            "duplicate": False,
            "message_id": message_id,
            "pruned_messages": pruned_messages,
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

    def _resync_external_chat_threads(self):
        """Drop empty threads and recompute unread/last-message after a deletion."""
        self._conn.execute(
            "DELETE FROM external_chat_threads WHERE NOT EXISTS ("
            "SELECT 1 FROM external_chat_messages m "
            "WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id)"
        )
        self._conn.execute(
            "UPDATE external_chat_threads SET "
            "unread_count=(SELECT COUNT(*) FROM external_chat_messages m "
            "WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id AND m.unread=1), "
            "last_message_id=(SELECT MAX(m.id) FROM external_chat_messages m "
            "WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id), "
            "last_message_at=(SELECT m.created_at FROM external_chat_messages m "
            "WHERE m.platform=external_chat_threads.platform AND m.thread_id=external_chat_threads.thread_id "
            "ORDER BY m.id DESC LIMIT 1), "
            "updated_at=?",
            (_now_text(),)
        )

    def _prune_external_group_thread_messages(self, platform: str, thread_id: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM external_chat_messages "
            "WHERE platform=? AND thread_id=? AND chat_type='group' AND id NOT IN ("
            "SELECT id FROM external_chat_messages "
            "WHERE platform=? AND thread_id=? AND chat_type='group' "
            "ORDER BY id DESC LIMIT ?"
            ")",
            (
                platform,
                thread_id,
                platform,
                thread_id,
                _EXTERNAL_GROUP_CHAT_MESSAGE_LIMIT,
            ),
        )
        deleted_messages = int(cur.rowcount or 0)
        if deleted_messages:
            self._resync_external_chat_threads()
        return deleted_messages

    def prune_external_group_chat_limit(self) -> dict:
        """Keep only the newest stored messages for each external group chat."""
        def operation():
            rows = self._conn.execute(
                "SELECT platform, thread_id FROM external_chat_threads WHERE chat_type='group' "
                "UNION "
                "SELECT platform, thread_id FROM external_chat_messages WHERE chat_type='group'"
            ).fetchall()
            deleted_messages = 0
            for row in rows:
                platform = _db_text(row[0], "external") or "external"
                thread_id = _db_text(row[1], "default") or "default"
                deleted_messages += self._prune_external_group_thread_messages(platform, thread_id)
            self._conn.commit()
            return {"deleted_messages": deleted_messages}

        return _run_with_locked_retry(self._conn, operation)

    def delete_external_chat(self, chat_type: str = "", platform: str = "") -> dict:
        """Delete all external chat records, optionally scoped by chat_type/platform.

        ``chat_type`` is "group" / "private" (empty = any). Used by the manual
        "delete records" buttons in the NapCat settings.
        """
        chat_type = _clean_external_text(chat_type)
        platform = _clean_external_text(platform)

        def operation():
            cur = self._conn.execute(
                "DELETE FROM external_chat_messages "
                "WHERE (?='' OR chat_type=?) AND (?='' OR platform=?)",
                (chat_type, chat_type, platform, platform),
            )
            deleted_messages = int(cur.rowcount or 0)
            tcur = self._conn.execute(
                "DELETE FROM external_chat_threads "
                "WHERE (?='' OR chat_type=?) AND (?='' OR platform=?)",
                (chat_type, chat_type, platform, platform),
            )
            deleted_threads = int(tcur.rowcount or 0)
            if deleted_messages:
                self._resync_external_chat_threads()
            self._conn.commit()
            return {
                "deleted_messages": deleted_messages,
                "deleted_threads": deleted_threads,
                "unread": self.get_external_chat_unread_summary(),
            }

        return _run_with_locked_retry(self._conn, operation)

    def purge_external_chat_older_than(self, days, chat_type: str = "", platform: str = "") -> dict:
        """Delete external chat records older than ``days`` (retention auto-clean).

        Records created strictly before ``now - days`` are removed; threads left
        empty are dropped and the rest have their unread/last-message recomputed.
        """
        days = _clamp_int(days, 1, 3650, 7)
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        chat_type = _clean_external_text(chat_type)
        platform = _clean_external_text(platform)

        def operation():
            cur = self._conn.execute(
                "DELETE FROM external_chat_messages "
                "WHERE created_at < ? AND (?='' OR chat_type=?) AND (?='' OR platform=?)",
                (cutoff, chat_type, chat_type, platform, platform),
            )
            deleted_messages = int(cur.rowcount or 0)
            if deleted_messages:
                self._resync_external_chat_threads()
            self._conn.commit()
            return {"deleted_messages": deleted_messages}

        return _run_with_locked_retry(self._conn, operation)

    # ── Usage session tracking ──────────────────────────────────────────

    def start_usage_session(self) -> int:
        cur = self._conn.execute(
            "INSERT INTO usage_sessions (start_time) VALUES (datetime('now','localtime'))"
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def end_usage_session(self, session_id: int):
        self._conn.execute(
            "UPDATE usage_sessions SET end_time=datetime('now', 'localtime'),"
            "duration_seconds=CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) "
            "WHERE id=? AND end_time IS NULL",
            (session_id,),
        )
        self._conn.commit()

    def heartbeat_usage_session(self, session_id: int):
        self._conn.execute(
            "UPDATE usage_sessions SET duration_seconds=CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) "
            "WHERE id=? AND end_time IS NULL",
            (session_id,),
        )
        self._conn.commit()

    def get_usage_today(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions "
            "WHERE date(start_time)=date('now','localtime')"
        ).fetchone()
        total = int(row[0]) if row else 0
        cur = self._conn.execute(
            "SELECT id, COALESCE(duration_seconds,0) FROM usage_sessions "
            "WHERE end_time IS NULL AND date(start_time)=date('now','localtime') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cur:
            live_row = self._conn.execute(
                "SELECT CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) "
                "FROM usage_sessions WHERE id=?", (int(cur[0]),)
            ).fetchone()
            live = int(live_row[0]) if live_row and live_row[0] is not None else 0
            total = total - int(cur[1]) + live
        return total

    def get_usage_week(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions "
            "WHERE start_time>=datetime('now','localtime','-6 days','start of day')"
        ).fetchone()
        total = int(row[0]) if row else 0
        cur = self._conn.execute(
            "SELECT id, COALESCE(duration_seconds,0) FROM usage_sessions "
            "WHERE end_time IS NULL AND start_time>=datetime('now','localtime','-6 days','start of day') "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cur:
            live_row = self._conn.execute(
                "SELECT CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) "
                "FROM usage_sessions WHERE id=?", (int(cur[0]),)
            ).fetchone()
            live = int(live_row[0]) if live_row and live_row[0] is not None else 0
            total = total - int(cur[1]) + live
        return total

    def get_usage_all_time(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions"
        ).fetchone()
        total = int(row[0]) if row else 0
        cur = self._conn.execute(
            "SELECT id, COALESCE(duration_seconds,0) FROM usage_sessions "
            "WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cur:
            live_row = self._conn.execute(
                "SELECT CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) "
                "FROM usage_sessions WHERE id=?", (int(cur[0]),)
            ).fetchone()
            live = int(live_row[0]) if live_row and live_row[0] is not None else 0
            total = total - int(cur[1]) + live
        return total

    def get_usage_daily(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT date(start_time) AS day, COALESCE(SUM(duration_seconds),0) AS total "
            "FROM usage_sessions "
            "WHERE start_time>=datetime('now','localtime',?,'start of day') "
            "GROUP BY date(start_time) ORDER BY day ASC",
            (f"-{days} days",),
        ).fetchall()
        return [{"day": r[0], "seconds": int(r[1])} for r in rows]

    # ── Statistics queries ──────────────────────────────────────────────

    def get_mood_events_for_chart(self, character: str, days: int = 30,
                                  user_key: str = "") -> list[dict]:
        user_key = self._normalize_user_key(user_key)
        if days <= 0:
            rows = self._conn.execute(
                "SELECT created_at, affection_delta, trust_delta, familiarity_delta, affection, trust, familiarity "
                "FROM mood_events WHERE character=? AND user_key=? "
                "ORDER BY created_at ASC, id ASC",
                (character, user_key),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT created_at, affection_delta, trust_delta, familiarity_delta, affection, trust, familiarity "
                "FROM mood_events WHERE character=? AND user_key=? "
                "AND created_at>=datetime('now','localtime',?) "
                "ORDER BY created_at ASC, id ASC",
                (character, user_key, f"-{days} days"),
            ).fetchall()
        state = self.get_relationship_state(character, user_key)
        if not rows:
            today = datetime.now().strftime("%Y-%m-%d")
            return [{
                "day": today,
                "affection": state["affection"],
                "trust": state["trust"],
                "familiarity": state["familiarity"],
            }]

        first_snapshot_index = -1
        for i, r in enumerate(rows):
            if _db_int(r[4]) is not None and _db_int(r[5]) is not None and _db_int(r[6]) is not None:
                first_snapshot_index = i
                break

        if first_snapshot_index < 0:
            day = _db_text(state.get("updated_at")) or datetime.now().strftime("%Y-%m-%d")
            return [{
                "day": day,
                "affection": state["affection"],
                "trust": state["trust"],
                "familiarity": state["familiarity"],
            }]

        result: list[dict] = []
        affection = trust = familiarity = 0
        for r in rows[first_snapshot_index:]:
            snapshot_affection = _db_int(r[4])
            snapshot_trust = _db_int(r[5])
            snapshot_familiarity = _db_int(r[6])
            if snapshot_affection is None or snapshot_trust is None or snapshot_familiarity is None:
                affection = max(0, min(100, affection + int(r[1] or 0)))
                trust = max(0, min(100, trust + int(r[2] or 0)))
                familiarity = max(0, min(100, familiarity + int(r[3] or 0)))
            else:
                affection = max(0, min(100, snapshot_affection))
                trust = max(0, min(100, snapshot_trust))
                familiarity = max(0, min(100, snapshot_familiarity))
            result.append({
                "day": r[0],
                "affection": affection,
                "trust": trust,
                "familiarity": familiarity,
            })

        updated_at = _db_text(state.get("updated_at"))
        if updated_at and result and updated_at >= _db_text(result[-1].get("day")):
            if (
                updated_at != _db_text(result[-1].get("day"))
                or int(result[-1]["affection"]) != int(state["affection"])
                or int(result[-1]["trust"]) != int(state["trust"])
                or int(result[-1]["familiarity"]) != int(state["familiarity"])
            ):
                result.append({
                    "day": updated_at,
                    "affection": state["affection"],
                    "trust": state["trust"],
                    "familiarity": state["familiarity"],
                })
        return result

    def get_chat_summary(self) -> dict:
        conv_row = self._conn.execute("SELECT COUNT(*) FROM conversations").fetchone()
        msg_row = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        gmsg_row = self._conn.execute("SELECT COUNT(*) FROM group_messages").fetchone()
        return {
            "total_conversations": int(conv_row[0]) if conv_row else 0,
            "total_messages": int(msg_row[0]) if msg_row else 0,
            "total_group_messages": int(gmsg_row[0]) if gmsg_row else 0,
        }

    def get_daily_message_counts(self, days: int = 30, user_key: str | None = None) -> list[dict]:
        params: list = [f"-{days} days"]
        private_user_filter = ""
        group_user_filter = ""
        if user_key is not None:
            normalized_user = self._normalize_user_key(user_key)
            private_user_filter = "AND c.user_key=? "
            group_user_filter = "AND user_key=? "
            params.append(normalized_user)

        private_rows = self._conn.execute(
            "SELECT date(m.created_at) AS day, COUNT(*) AS cnt "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.created_at>=datetime('now','localtime',?) "
            f"{private_user_filter}"
            "GROUP BY date(m.created_at)",
            tuple(params),
        ).fetchall()

        group_params: list = [f"-{days} days"]
        if user_key is not None:
            group_params.append(self._normalize_user_key(user_key))
        group_rows = self._conn.execute(
            "SELECT date(created_at) AS day, COUNT(*) AS cnt "
            "FROM group_messages "
            "WHERE created_at>=datetime('now','localtime',?) "
            f"{group_user_filter}"
            "GROUP BY date(created_at)",
            tuple(group_params),
        ).fetchall()

        counts: dict[str, int] = {}
        for day, count in list(private_rows) + list(group_rows):
            day_text = _db_text(day)
            if not day_text:
                continue
            counts[day_text] = counts.get(day_text, 0) + int(count or 0)
        return [{"day": day, "count": counts[day]} for day in sorted(counts)]

    def get_messages_per_character_range(self, days: int = 0, user_key: str = "") -> list[dict]:
        user_key = self._normalize_user_key(user_key)
        if days <= 0:
            rows = self._conn.execute(
                "SELECT c.character, COUNT(m.id) AS msg_count "
                "FROM conversations c JOIN messages m ON m.conversation_id=c.id "
                "WHERE c.user_key=? AND c.character!='' AND c.character!='__group__' "
                "GROUP BY c.character ORDER BY msg_count DESC",
                (user_key,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT c.character, COUNT(m.id) AS msg_count "
                "FROM conversations c JOIN messages m ON m.conversation_id=c.id "
                "WHERE c.user_key=? AND c.character!='' AND c.character!='__group__' "
                "AND m.created_at>=datetime('now','localtime',?) "
                "GROUP BY c.character ORDER BY msg_count DESC",
                (user_key, f"-{days} days"),
            ).fetchall()
        counts = {_db_text(r[0]): int(r[1]) for r in rows if _db_text(r[0])}

        if days <= 0:
            group_rows = self._conn.execute(
                "SELECT group_key, role, content "
                "FROM group_messages WHERE user_key=? AND group_key LIKE '__group__:%'",
                (user_key,),
            ).fetchall()
        else:
            group_rows = self._conn.execute(
                "SELECT group_key, role, content "
                "FROM group_messages WHERE user_key=? AND group_key LIKE '__group__:%' "
                "AND created_at>=datetime('now','localtime',?)",
                (user_key, f"-{days} days"),
            ).fetchall()

        for row in group_rows:
            for character in self._group_message_count_characters(row):
                counts[character] = counts.get(character, 0) + 1

        return [
            {"character": character, "count": count}
            for character, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        ]

    def get_hourly_heatmap(self, days: int = 7, user_key: str | None = None) -> list[list[int]]:
        grid = [[0] * 24 for _ in range(7)]
        params: list = [f"-{days} days"]
        private_user_filter = ""
        if user_key is not None:
            private_user_filter = "AND c.user_key=? "
            params.append(self._normalize_user_key(user_key))
        rows = self._conn.execute(
            "SELECT CAST(strftime('%w', m.created_at) AS INTEGER) AS wday, "
            "CAST(strftime('%H', m.created_at) AS INTEGER) AS hour, COUNT(*) AS cnt "
            "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE m.created_at>=datetime('now','localtime',?) "
            f"{private_user_filter}"
            "GROUP BY wday, hour",
            tuple(params),
        ).fetchall()
        group_params: list = [f"-{days} days"]
        group_user_filter = ""
        if user_key is not None:
            group_user_filter = "AND user_key=? "
            group_params.append(self._normalize_user_key(user_key))
        group_rows = self._conn.execute(
            "SELECT CAST(strftime('%w', created_at) AS INTEGER) AS wday, "
            "CAST(strftime('%H', created_at) AS INTEGER) AS hour, COUNT(*) AS cnt "
            "FROM group_messages "
            "WHERE created_at>=datetime('now','localtime',?) "
            f"{group_user_filter}"
            "GROUP BY wday, hour",
            tuple(group_params),
        ).fetchall()
        for r in list(rows) + list(group_rows):
            wday = int(r[0])
            hour = int(r[1])
            count = int(r[2])
            iso_day = (wday - 1) % 7
            if 0 <= iso_day < 7 and 0 <= hour < 24:
                grid[iso_day][hour] += count
        return grid

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
            data = json.loads((BASE_DIR / "outfit.json").read_text(encoding="utf-8"))
            info = data.get("characters", {}).get(character, {})
            display = str(info.get("display", "") or "").strip()
            if display:
                aliases.add(display)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
        aliases.discard("")
        return aliases

    def _group_message_count_characters(self, row) -> list[str]:
        group_key = _db_text(row[0])
        role = _db_text(row[1], "user")
        content = _db_text(row[2])
        members = self._group_key_characters(group_key)
        if not members:
            return []
        if role != "assistant":
            return members
        speaker = _group_message_speaker(content)
        if not speaker:
            return members
        matched = [
            character
            for character in members
            if speaker in self._character_display_aliases(character)
        ]
        return matched or members

    @staticmethod
    def _group_key_contains_character(group_key: str, character: str) -> bool:
        prefix = "__group__:"
        if not group_key.startswith(prefix) or not character:
            return False
        members = [part for part in group_key[len(prefix):].split("|") if part]
        return character in members

    @staticmethod
    def _character_aliases(character: str, aliases: list[str] | tuple[str, ...] | set[str] | None = None) -> set[str]:
        result = {str(character or "").strip()}
        for alias in aliases or []:
            text = str(alias or "").strip()
            if text:
                result.add(text)
        result.discard("")
        return result

    @staticmethod
    def _group_message_matches_character(row, character: str, aliases: set[str]) -> bool:
        role = _db_text(row[3], "user")
        if role != "assistant":
            return True
        speaker = _group_message_speaker(_db_text(row[4]))
        return not speaker or speaker in aliases

    def _group_conversation_album_preview(
        self,
        group_key: str,
        conversation_id: str,
        user_key: str,
        aliases: set[str],
    ) -> tuple[str, int]:
        rows = self._conn.execute(
            "SELECT id, group_key, conversation_id, role, content, reasoning_content, "
            "attachments_json, tool_trace_json, created_at "
            "FROM group_messages WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) "
            "AND user_key=? ORDER BY id DESC",
            (group_key, conversation_id, conversation_id, user_key),
        ).fetchall()
        preview = ""
        count = 0
        for row in rows:
            if not self._group_message_matches_character(row, "", aliases):
                continue
            count += 1
            if not preview:
                preview = _db_text(row[4])
        return preview, count

    def get_character_recent_messages(
        self,
        character: str,
        user_key: str = "",
        limit: int = 24,
        character_aliases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        user_key = self._normalize_user_key(user_key)
        limit = _clamp_int(limit, 1, 200, 24)
        aliases = self._character_aliases(character, character_aliases)
        private_rows = self._conn.execute(
            "SELECT m.id, m.conversation_id, m.role, m.content, m.reasoning_content, "
            "m.attachments_json, m.tool_trace_json, m.created_at "
            "FROM conversations c JOIN messages m ON m.conversation_id=c.id "
            "WHERE c.character=? AND c.user_key=? "
            "ORDER BY m.id DESC LIMIT ?",
            (character, user_key, limit),
        ).fetchall()
        messages = []
        for row in private_rows:
            message = _album_message_row_dict(row)
            if message is not None:
                messages.append(message)

        group_rows = self._conn.execute(
            "SELECT id, group_key, conversation_id, role, content, reasoning_content, "
            "attachments_json, tool_trace_json, created_at "
            "FROM group_messages WHERE user_key=? AND group_key LIKE '__group__:%' "
            "ORDER BY id DESC LIMIT ?",
            (user_key, min(1000, max(limit * 8, 120))),
        ).fetchall()
        for row in group_rows:
            group_key = _db_text(row[1])
            if not self._group_key_contains_character(group_key, character):
                continue
            if not self._group_message_matches_character(row, character, aliases):
                continue
            message = _album_message_row_dict(row, grouped=True)
            if message is not None:
                messages.append(message)

        messages.sort(key=lambda item: (item.get("created_at", ""), int(item.get("id") or 0)), reverse=True)
        result = messages[:limit]
        result.reverse()
        return result

    def get_character_conversation_chain(
        self,
        character: str,
        user_key: str = "",
        limit: int = 20,
        character_aliases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        user_key = self._normalize_user_key(user_key)
        limit = _clamp_int(limit, 1, 100, 20)
        aliases = self._character_aliases(character, character_aliases)
        rows = self._conn.execute(
            "SELECT c.id, c.character, c.user_key, c.title, c.created_at, "
            "MIN(m.created_at) AS first_message_at, MAX(m.created_at) AS last_message_at, "
            "COUNT(m.id) AS message_count, "
            "(SELECT content FROM messages WHERE conversation_id=c.id AND role='user' AND content!='' ORDER BY id ASC LIMIT 1) AS first_user, "
            "(SELECT content FROM messages WHERE conversation_id=c.id AND content!='' ORDER BY id DESC LIMIT 1) AS preview "
            "FROM conversations c JOIN messages m ON m.conversation_id=c.id "
            "WHERE c.character=? AND c.user_key=? "
            "GROUP BY c.id, c.character, c.user_key, c.title, c.created_at "
            "ORDER BY MAX(m.id) DESC LIMIT ?",
            (character, user_key, limit),
        ).fetchall()
        result = []
        for row in rows:
            result.append({
                "source": "private",
                "conversation_id": _db_int(row[0]) or 0,
                "group_key": "",
                "user_key": _db_text(row[2]),
                "title": _db_text(row[3]),
                "created_at": _db_text(row[4]),
                "first_message_at": _db_text(row[5]),
                "last_message_at": _db_text(row[6]),
                "message_count": int(row[7] or 0),
                "first_user": _db_text(row[8]),
                "preview": _db_text(row[9]),
            })

        group_rows = self._conn.execute(
            "SELECT group_key, conversation_id, MIN(created_at), MAX(created_at), COUNT(id), "
            "(SELECT content FROM group_messages gm2 "
            " WHERE gm2.group_key=gm.group_key AND gm2.conversation_id=gm.conversation_id "
            " AND gm2.user_key=gm.user_key AND gm2.role='user' AND gm2.content!='' ORDER BY gm2.id ASC LIMIT 1) AS first_user, "
            "(SELECT content FROM group_messages gm2 "
            " WHERE gm2.group_key=gm.group_key AND gm2.conversation_id=gm.conversation_id "
            " AND gm2.user_key=gm.user_key AND gm2.content!='' ORDER BY gm2.id DESC LIMIT 1) AS preview "
            "FROM group_messages gm WHERE gm.user_key=? AND gm.group_key LIKE '__group__:%' "
            "GROUP BY group_key, conversation_id, user_key "
            "ORDER BY MAX(id) DESC LIMIT ?",
            (user_key, min(300, max(limit * 6, 60))),
        ).fetchall()
        for row in group_rows:
            group_key = _db_text(row[0])
            if not self._group_key_contains_character(group_key, character):
                continue
            conversation_id = _db_text(row[1], "default") or "default"
            preview, message_count = self._group_conversation_album_preview(group_key, conversation_id, user_key, aliases)
            result.append({
                "source": "group",
                "conversation_id": conversation_id,
                "group_key": group_key,
                "user_key": user_key,
                "title": "",
                "created_at": _db_text(row[2]),
                "first_message_at": _db_text(row[2]),
                "last_message_at": _db_text(row[3]),
                "message_count": message_count or int(row[4] or 0),
                "first_user": _db_text(row[5]),
                "preview": preview or _db_text(row[6]),
            })

        result.sort(key=lambda item: item.get("last_message_at", ""), reverse=True)
        return result[:limit]

    def get_character_album_days(
        self,
        character: str,
        user_key: str = "",
        limit: int = 30,
        character_aliases: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> list[dict]:
        limit = _clamp_int(limit, 1, 120, 30)
        messages = self.get_character_recent_messages(character, user_key, limit=600, character_aliases=character_aliases)
        by_day: dict[str, dict] = {}
        for message in messages:
            created_at = str(message.get("created_at") or "")
            day = created_at[:10] if len(created_at) >= 10 else ""
            if not day:
                continue
            entry = by_day.setdefault(day, {
                "day": day,
                "message_count": 0,
                "user_count": 0,
                "assistant_count": 0,
                "first_at": created_at,
                "last_at": created_at,
                "snippets": [],
                "snippet_items": [],
            })
            entry["message_count"] += 1
            if message.get("role") == "user":
                entry["user_count"] += 1
            elif message.get("role") == "assistant":
                entry["assistant_count"] += 1
            entry["first_at"] = min(entry["first_at"], created_at)
            entry["last_at"] = max(entry["last_at"], created_at)
            content = re.sub(r"\s+", " ", _db_text(message.get("content"))).strip()
            if content and len(entry["snippets"]) < 3:
                entry["snippets"].append(content[:120])
            if content and len(entry["snippet_items"]) < 3:
                entry["snippet_items"].append({
                    "role": message.get("role", ""),
                    "content": content[:160],
                    "source": message.get("source", ""),
                    "speaker": message.get("speaker", ""),
                })

        memories = self.get_character_memories(character, user_key, limit=100)
        for memory in memories:
            created_at = str(memory.get("created_at") or memory.get("updated_at") or "")
            day = created_at[:10] if len(created_at) >= 10 else ""
            if not day:
                continue
            entry = by_day.setdefault(day, {
                "day": day,
                "message_count": 0,
                "user_count": 0,
                "assistant_count": 0,
                "first_at": created_at,
                "last_at": created_at,
                "snippets": [],
                "snippet_items": [],
            })
            entry["memory_count"] = int(entry.get("memory_count") or 0) + 1
            if memory.get("kind") == "favorite":
                entry["favorite_count"] = int(entry.get("favorite_count") or 0) + 1

        days = sorted(by_day.values(), key=lambda item: item.get("day", ""), reverse=True)
        return days[:limit]

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._conn.close()
