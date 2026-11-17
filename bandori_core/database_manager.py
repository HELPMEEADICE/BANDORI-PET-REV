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
from bandori_core.process_utils import app_base_dir, app_data_dir, clamp_int as _clamp_int
from bandori_core.config_manager import DEFAULT_USER_PROFILE_KEY

BASE_DIR = app_data_dir()
LEGACY_BASE_DIR = app_base_dir()
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


def _unlink_if_possible(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _remove_database_lock_on_close() -> bool:
    # POSIX flock locks an inode. Unlinking the path while another process is
    # waiting can let a third process create and lock a different inode.
    return os.name == "nt"


def _migrate_legacy_database(db_path: str) -> None:
    target = Path(db_path)
    if target != Path(DB_PATH) or LEGACY_BASE_DIR == BASE_DIR or target.exists():
        return
    legacy = LEGACY_BASE_DIR / "data.db"
    if not legacy.is_file():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, target)
        for suffix in ("-wal", "-shm"):
            legacy_sidecar = Path(str(legacy) + suffix)
            if legacy_sidecar.is_file():
                shutil.copy2(legacy_sidecar, Path(str(target) + suffix))
    except OSError:
        pass


def _db_text(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _db_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
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
        if _remove_database_lock_on_close():
            _unlink_if_possible(self._lock_path)

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
    affection = _db_int(row[3])
    trust = _db_int(row[4])
    familiarity = _db_int(row[5])
    mood_intensity = _db_int(row[7])
    return {
        "id": _db_int(row[0]) or 0,
        "character": _db_text(row[1]),
        "user_key": _db_text(row[2]),
        "affection": 50 if affection is None else affection,
        "trust": 50 if trust is None else trust,
        "familiarity": 0 if familiarity is None else familiarity,
        "mood": _db_text(row[6], "calm") or "calm",
        "mood_intensity": 20 if mood_intensity is None else mood_intensity,
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
            fd, staged_path = tempfile.mkstemp(
                prefix=target.name + ".",
                suffix=".import",
                dir=str(target.parent),
            )
            os.close(fd)
            try:
                with closing(sqlite3.connect(source_uri, uri=True, timeout=10)) as src:
                    _validate_chat_database(src)
                    with closing(sqlite3.connect(staged_path, timeout=10)) as dst:
                        dst.execute("PRAGMA busy_timeout=10000")
                        src.backup(dst)
                        _sanitize_database_attachments(dst)
                        dst.commit()
                        _validate_chat_database(dst)
                os.replace(staged_path, target)
            except Exception:
                try:
                    os.unlink(staged_path)
                except OSError:
                    pass
                raise

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
    with _shared_database_lock(str(db_path)):
        with closing(sqlite3.connect(str(db_path), timeout=10)) as conn:
            for item in states:
                if not isinstance(item, dict):
                    continue
                character = _db_text(item.get("character")).strip()
                if not character:
                    continue
                user_key = _db_text(item.get("user_key"), DEFAULT_USER_PROFILE_KEY).strip() or DEFAULT_USER_PROFILE_KEY
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
                user_key = _db_text(item.get("user_key"), DEFAULT_USER_PROFILE_KEY).strip() or DEFAULT_USER_PROFILE_KEY
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


class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        from bandori_core.native_database import open_native, NativeConnection
        _migrate_legacy_database(db_path)
        self._native = open_native(db_path)
        self._conn = NativeConnection(self._native)
        self._lock = threading.RLock()
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
            CREATE TABLE IF NOT EXISTS group_conversation_backgrounds (
                group_key TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                user_key TEXT NOT NULL DEFAULT '',
                temporary_background TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                PRIMARY KEY (group_key, conversation_id, user_key)
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
        if "temporary_background" not in conversation_columns:
            self._conn.execute("ALTER TABLE conversations ADD COLUMN temporary_background TEXT NOT NULL DEFAULT ''")
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
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_group_backgrounds_user_key ON group_conversation_backgrounds(user_key, group_key, updated_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_character_memories_lookup ON character_memories(character, user_key, importance, updated_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_mood_events_lookup ON mood_events(character, user_key, created_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_thread ON external_chat_messages(platform, thread_id, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_unread ON external_chat_messages(unread, id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_external_id ON external_chat_messages(platform, thread_id, external_message_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_external_chat_messages_chat_type ON external_chat_messages(chat_type, created_at)")
        self._conn.commit()

    def _normalize_user_key(self, user_key: str) -> str:
        return (user_key or DEFAULT_USER_PROFILE_KEY).strip() or DEFAULT_USER_PROFILE_KEY

    def _user_filter_clause(self, user_key, where: str, params: tuple, column: str = "user_key") -> tuple[str, tuple]:
        if user_key is None:
            return where, params
        normalized = self._normalize_user_key(user_key)
        conjunction = " AND " if where else "WHERE "
        return f"{where}{conjunction}{column}=?", (*params, normalized)

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

    @staticmethod
    def _token_usage_from_rows(rows) -> dict:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated": False,
            "request_count": 0,
            "untracked_count": 0,
        }
        for row in rows:
            try:
                trace = json.loads(_db_text(row[0])) if row and row[0] else {}
            except (TypeError, ValueError):
                trace = {}
            usage = trace.get("llm_usage") if isinstance(trace, dict) else None
            if not isinstance(usage, dict):
                totals["untracked_count"] += 1
                continue
            input_tokens = max(0, _db_int(usage.get("input_tokens")) or 0)
            output_tokens = max(0, _db_int(usage.get("output_tokens")) or 0)
            total_tokens = max(
                0,
                _db_int(usage.get("total_tokens")) or (input_tokens + output_tokens),
            )
            totals["input_tokens"] += input_tokens
            totals["output_tokens"] += output_tokens
            totals["total_tokens"] += total_tokens
            totals["estimated"] = totals["estimated"] or bool(usage.get("estimated", False))
            totals["request_count"] += 1
        return totals

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
        return self._invoke("get_external_chat_unread_summary", locals())

    def external_chat_context_text(
        self, limit_threads: int = 4, limit_messages: int = 6, *,
        platform: str | None = None, thread_id: str | None = None,
        chat_type: str | None = None,
    ) -> str:
        return self._invoke("external_chat_context_text", locals())

    def mark_external_chat_read(self, platform: str = "", thread_id: str = "") -> dict:
        return self._invoke("mark_external_chat_read", locals())

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
        return self._invoke("prune_external_group_chat_limit", locals())

    def delete_external_chat(self, chat_type: str = "", platform: str = "") -> dict:
        return self._invoke("delete_external_chat", locals())

    def purge_external_chat_older_than(self, days, chat_type: str = "", platform: str = "") -> dict:
        return self._invoke("purge_external_chat_older_than", locals())

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
        total = (_db_int(row[0]) or 0) if row else 0
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
            live = (_db_int(live_row[0]) or 0) if live_row else 0
            total = total - (_db_int(cur[1]) or 0) + live
        return total

    def get_usage_week(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions "
            "WHERE start_time>=datetime('now','localtime','-6 days','start of day')"
        ).fetchone()
        total = (_db_int(row[0]) or 0) if row else 0
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
            live = (_db_int(live_row[0]) or 0) if live_row else 0
            total = total - (_db_int(cur[1]) or 0) + live
        return total

    def get_usage_all_time(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds),0) FROM usage_sessions"
        ).fetchone()
        total = (_db_int(row[0]) or 0) if row else 0
        cur = self._conn.execute(
            "SELECT id, COALESCE(duration_seconds,0) FROM usage_sessions "
            "WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cur:
            live_row = self._conn.execute(
                "SELECT CAST((julianday('now','localtime')-julianday(start_time))*86400 AS INTEGER) "
                "FROM usage_sessions WHERE id=?", (int(cur[0]),)
            ).fetchone()
            live = (_db_int(live_row[0]) or 0) if live_row else 0
            total = total - (_db_int(cur[1]) or 0) + live
        return total

    def get_usage_daily(self, days: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT date(start_time) AS day, COALESCE(SUM(duration_seconds),0) AS total "
            "FROM usage_sessions "
            "WHERE start_time>=datetime('now','localtime',?,'start of day') "
            "GROUP BY date(start_time) ORDER BY day ASC",
            (f"-{days} days",),
        ).fetchall()
        return [{"day": r[0], "seconds": _db_int(r[1]) or 0} for r in rows]

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
            )
        else:
            group_rows = self._conn.execute(
                "SELECT group_key, role, content "
                "FROM group_messages WHERE user_key=? AND group_key LIKE '__group__:%' "
                "AND created_at>=datetime('now','localtime',?)",
                (user_key, f"-{days} days"),
            )

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
            data = json.loads((LEGACY_BASE_DIR / "outfit.json").read_text(encoding="utf-8"))
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
            "SELECT role, content "
            "FROM group_messages WHERE group_key=? AND (conversation_id=? OR CAST(conversation_id AS TEXT)=?) "
            "AND user_key=? ORDER BY id DESC",
            (group_key, conversation_id, conversation_id, user_key),
        )
        preview = ""
        count = 0
        for role, content in rows:
            content = _db_text(content)
            if (
                _db_text(role, "user") == "assistant"
                and (speaker := _group_message_speaker(content))
                and speaker not in aliases
            ):
                continue
            count += 1
            if not preview:
                preview = content
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

    def _invoke(self, operation, arguments):
        args = dict(arguments)
        args.pop("self", None)
        if operation in {"add_message", "add_group_message"}:
            args["attachments_json"] = _json_text(_sanitize_attachments_payload(args.pop("attachments")))
            args["tool_trace_json"] = _json_text(args.pop("tool_trace"))
        elif operation == "add_external_chat_message":
            args["raw_json"] = _json_text(args["event"])
        result = self._native.call(operation, args)
        if operation == "change_revision":
            return tuple(result)
        if operation == "get_chat_history_filter_options":
            for key in ("characters", "user_keys"):
                result[key].sort(key=str.casefold)
        return result
