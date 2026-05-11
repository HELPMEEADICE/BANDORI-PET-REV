import sqlite3
import os
import shutil
import tempfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from process_utils import app_base_dir

BASE_DIR = app_base_dir()
DB_PATH = os.path.join(BASE_DIR, "data.db")

_REQUIRED_TABLES = {"conversations", "messages"}
_REQUIRED_COLUMNS = {
    "conversations": {"id", "character", "title", "created_at"},
    "messages": {"id", "conversation_id", "role", "content", "created_at"},
}


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
        return {"conversations": 0, "messages": 0}
    with closing(sqlite3.connect(str(path), timeout=10)) as conn:
        _validate_chat_database(conn)
        conversations = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return {"conversations": conversations, "messages": messages}


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
                dst.commit()

    _ensure_database(str(target))
    return chat_database_summary(str(target))


class DatabaseManager:
    def __init__(self, db_path=DB_PATH):
        self._db_path = db_path
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
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        columns = [r[1] for r in self._conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "reasoning_content" not in columns:
            self._conn.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''")
        self._conn.commit()

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
                "SELECT id, character, title, created_at FROM conversations "
                "WHERE character=? AND EXISTS ("
                "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                ") ORDER BY created_at DESC",
                (character,)
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, character, title, created_at FROM conversations "
                "WHERE EXISTS ("
                "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
                ") ORDER BY created_at DESC"
            ).fetchall()
        return [
            {"id": r[0], "character": r[1], "title": r[2], "created_at": r[3]}
            for r in rows
        ]

    def get_last_conversation(self, character: str) -> dict | None:
        row = self._conn.execute(
            "SELECT id, character, title, created_at FROM conversations "
            "WHERE character=? AND EXISTS ("
            "SELECT 1 FROM messages WHERE messages.conversation_id=conversations.id"
            ") ORDER BY created_at DESC LIMIT 1",
            (character,)
        ).fetchone()
        if row:
            return {"id": row[0], "character": row[1], "title": row[2], "created_at": row[3]}
        return None

    def update_conversation_title(self, conv_id: int, title: str):
        self._conn.execute(
            "UPDATE conversations SET title=? WHERE id=?",
            (title, conv_id)
        )
        self._conn.commit()

    def add_message(self, conversation_id: int, role: str, content: str, reasoning_content: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = self._conn.execute(
            "INSERT INTO messages (conversation_id, role, content, reasoning_content, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, reasoning_content, now)
        )
        self._conn.commit()
        return cur.lastrowid

    def get_messages(self, conversation_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, conversation_id, role, content, reasoning_content, created_at FROM messages "
            "WHERE conversation_id=? ORDER BY id ASC",
            (conversation_id,)
        ).fetchall()
        return [
            {"id": r[0], "conversation_id": r[1], "role": r[2],
             "content": r[3], "reasoning_content": r[4], "created_at": r[5]}
            for r in rows
        ]

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

    def close(self):
        self._conn.close()
