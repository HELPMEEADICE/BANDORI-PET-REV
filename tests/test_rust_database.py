"""Storage contract: isolated files only; legacy is a test oracle, never a fallback."""
import sqlite3
import inspect
import multiprocessing
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from bandori_core.database_manager import DatabaseManager
from bandori_core import database_manager as storage
from tests.baselines.legacy_database import DatabaseManager as LegacyDatabase


@pytest.mark.parametrize("factory", [LegacyDatabase, DatabaseManager])
def test_storage_contract(factory, tmp_path):
    db = factory(str(tmp_path / "contract.db"))
    try:
        cid = db.create_conversation("灯🐈", "中文・日本語", "甲")
        mid = db.add_message(cid, "user", "100%_\\ ' 🐈\nこんにちは")
        db.add_message(cid, "assistant", "回复", tool_trace={"llm_usage": {
            "input_tokens": 3, "output_tokens": 4, "total_tokens": 7}})
        assert db.get_messages(cid, limit=1)[0]["role"] == "assistant"
        assert db.get_messages(cid, before_id=mid + 1)[0]["content"].startswith("100%_")
        assert db.search_chat_history(keyword="%_\\", user_key="甲")["total"] == 1
        assert db.search_chat_history(user_key="乙")["total"] == 0
        assert db.get_conversation_token_usage(cid)["total_tokens"] == 7
        with pytest.raises(sqlite3.IntegrityError):
            db.add_message(cid, "invalid", "must roll back")
        assert len(db.get_messages(cid)) == 2
        first = db.add_character_memory("灯🐈", "甲", "note", "记忆🌟")
        assert db.add_character_memory("灯🐈", "甲", "profile", "记忆🌟", 90) == first
        assert db.get_character_memories("灯🐈", "乙") == []
        assert db.get_character_memories("灯🐈", "甲")[0]["importance"] == 90
        state = db.upsert_relationship_state("灯🐈", "甲", affection=0, trust=0)
        assert state["affection"] == state["trust"] == 0
        assert db.apply_relationship_delta("灯🐈", "甲", affection_delta=3)["affection"] == 3
        event = {"platform": "qq", "thread_id": "群", "message_id": "1", "text": "你好"}
        assert db.add_external_chat_message(event)["duplicate"] is False
        assert db.add_external_chat_message(event)["duplicate"] is True
        assert db.get_external_chat_unread_summary()["total_unread"] == 1
        assert db.mark_external_chat_read()["marked_read"] == 1
        db.delete_conversation(cid)
        assert db.get_messages(cid) == []
    finally:
        db.close()


def test_public_signatures_are_compatible():
    for name, member in inspect.getmembers(LegacyDatabase, inspect.isfunction):
        if not name.startswith("_"):
            assert inspect.signature(getattr(DatabaseManager, name)) == inspect.signature(member), name


@pytest.mark.parametrize("method,args", [
    ("update_message_content", (1, "bad-id", "x")),
    ("delete_messages_from", (1, "bad-id")),
    ("delete_message", ("bad-id", 1)),
    ("update_group_message_content", ("group", "thread", "bad-id", "x")),
    ("delete_group_messages_from", ("group", "thread", "bad-id")),
    ("delete_group_message", ("group", "thread", "bad-id")),
    ("get_conversation_token_usage", ("bad-id",)),
    ("set_conversation_temporary_background", ("bad-id", "x")),
])
def test_argument_errors_preserve_class_and_rollback(tmp_path, method, args):
    for i, factory in enumerate((LegacyDatabase, DatabaseManager)):
        with closing(factory(str(tmp_path / f"{i}.db"))) as db:
            db._conn.execute("INSERT INTO conversations(character) VALUES ('uncommitted')")
            with pytest.raises(ValueError):
                getattr(db, method)(*args)
            assert not db._conn.in_transaction
            assert db._conn.execute("SELECT COUNT(*) FROM conversations").fetchone() == (0,)


def test_legacy_falsy_and_numeric_id_coercions(tmp_path):
    outputs = []
    for i, factory in enumerate((LegacyDatabase, DatabaseManager)):
        with closing(factory(str(tmp_path / f"{i}.db"))) as db:
            cid = db.create_conversation("灯", user_key=False)
            db.set_conversation_temporary_background(cid, "background")
            db.add_group_message("group", 0, "user", "default conversation")
            outputs.append((db.get_conversation_temporary_background(float(cid)+0.8),
                            db.get_group_messages("group", "default")[0]["content"],
                            db.add_character_memory("灯", "甲", "note", False),
                            db.get_conversations(user_key="__default__")[0]["user_key"]))
    assert outputs[0] == outputs[1]


def test_native_binding_and_clear_missing_extension(monkeypatch, tmp_path):
    import sys
    from bandori_core import _pet_db
    from bandori_core.native_database import open_native
    assert _pet_db.BACKEND == "rust-pet-db"
    with closing(DatabaseManager(str(tmp_path / "binding.db"))) as db:
        assert type(db._native).__module__ == "bandori_core._pet_db"
        with pytest.raises(sqlite3.IntegrityError) as error:
            db.add_message(999, "user", "foreign key")
        assert error.value.sqlite_errorname == "SQLITE_CONSTRAINT_FOREIGNKEY"
        # SQLite's extended result code is 19 | (3 << 8); Python 3.10 does
        # not expose SQLITE_CONSTRAINT_FOREIGNKEY in the sqlite3 module.
        assert error.value.sqlite_errorcode == 787
        with pytest.raises(sqlite3.ProgrammingError):
            db._conn.execute("SELECT ?", ())
    monkeypatch.setitem(sys.modules, "bandori_core._pet_db", None)
    with pytest.raises(RuntimeError, match="python tools/build_db.py"):
        open_native(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


@pytest.mark.parametrize("value", [0, 2.5, 3.5, "67.8", "bad", float("inf")])
def test_numeric_state_compatibility(tmp_path, value):
    results = []
    for i, factory in enumerate((LegacyDatabase, DatabaseManager)):
        with closing(factory(str(tmp_path / f"{i}.db"))) as db:
            db.upsert_relationship_state("灯", "甲", affection=13)
            results.append(db.upsert_relationship_state("灯", "甲", affection=value)["affection"])
    assert results[0] == results[1]


def test_upgrade_old_schema_preserves_rows_and_unknown_columns(tmp_path):
    path = tmp_path / "old-schema.db"
    with closing(sqlite3.connect(path)) as c:
        c.executescript("""
            CREATE TABLE conversations(id INTEGER PRIMARY KEY AUTOINCREMENT,character TEXT NOT NULL,title TEXT DEFAULT '',created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),custom TEXT);
            CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id INTEGER NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
            CREATE TABLE group_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,group_key TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
            INSERT INTO conversations(character,title,custom) VALUES('灯','旧标题','插件数据');
            INSERT INTO messages(conversation_id,role,content) VALUES(1,'user','旧消息🐈');
            INSERT INTO group_messages(group_key,role,content) VALUES('group','user','旧群聊');
        """)
    with closing(DatabaseManager(str(path))) as db:
        assert db.get_messages(1)[0]["content"] == "旧消息🐈"
        assert db.get_group_messages("group", "default")[0]["content"] == "旧群聊"
        assert db._conn.execute("SELECT custom FROM conversations").fetchone() == ("插件数据",)
        assert db.assign_legacy_chat_history_user("甲") == 2
    with closing(LegacyDatabase(str(path))) as db:
        assert db.get_messages(1)[0]["content"] == "旧消息🐈"


def _seed(path):
    with closing(LegacyDatabase(str(path))) as db:
        for user in ("甲", "乙", "__default__"):
            cid = db.create_conversation("灯", "标题", user)
            for role, content in (("user", "100%_\\ 中文"), ("assistant", "回复🐈"), ("system", "背景")):
                db.add_message(cid, role, content)
                db.add_group_message("__group__:灯|爱音", "会话", role, content, user_key=user)
            db.add_group_message("__group__:灯|爱音", "会话", "assistant", "【灯】\n独白", user_key=user)
            db.set_group_conversation_temporary_background("__group__:灯|爱音", "仅背景", "风景", user)
            db.set_conversation_temporary_background(cid, "背景")
            db.add_character_memory("灯", user, "favorite", "收藏语句：记得🌟", 99)
            db.add_character_memory("灯", user, "profile", "日本語", 50)
            db.upsert_relationship_state("灯", user, affection=65, mood="happy")
            db.apply_relationship_delta("灯", user, affection_delta=-2, trust_delta=2)
        db.set_group_display_name("__group__:灯|爱音", "群聊")
        for i in range(55):
            db.add_external_chat_message({"platform": "qq", "thread_id": "群", "chat_type": "group",
                                          "message_id": str(i), "text": "你好", "timestamp": "2026-01-01 00:00:00"})
        sid = db.start_usage_session()
        db.end_usage_session(sid)
        for table in ("messages", "group_messages", "character_memories", "mood_events", "conversations"):
            db._conn.execute(f"UPDATE {table} SET created_at='2026-01-01 12:00:00'")
        db._conn.execute("UPDATE relationship_states SET updated_at='2026-01-01 12:00:00'")
        db._conn.commit()


@pytest.fixture
def pair(tmp_path):
    seed = tmp_path / "seed.db"
    _seed(seed)
    paths = [tmp_path / "old.db", tmp_path / "rust.db"]
    for path in paths:
        shutil.copy2(seed, path)
    with closing(LegacyDatabase(str(paths[0]))) as old, closing(DatabaseManager(str(paths[1]))) as new:
        yield old, new


@pytest.mark.parametrize("method,args,kwargs", [
    ("get_conversations", (), {}), ("get_last_conversation", ("灯", "甲"), {}),
    ("get_messages", (1,), {}), ("get_messages", (1,), {"limit": 2, "before_id": 3}),
    ("get_conversation_attachment_payloads", (1,), {}),
    ("get_conversation_token_usage", (1,), {}), ("get_conversation_token_usage", (None,), {}),
    ("get_chat_history_filter_options", (), {}),
    ("search_chat_history", (), {"keyword": "%_\\", "source": "group", "user_key": "甲", "skip_count": True, "limit": 1}),
    ("search_chat_history", (), {"character": "灯", "date_from": "2026-01-01", "date_to": "2026-01-02", "offset": 1}),
    ("get_group_messages", ("__group__:灯|爱音", "会话"), {"user_key": "甲"}),
    ("get_group_conversations", ("__group__:灯|爱音", "甲"), {}),
    ("get_group_chats", (), {}), ("get_group_display_name", ("__group__:灯|爱音",), {}),
    ("get_group_conversation_token_usage", ("__group__:灯|爱音", "会话", "甲"), {}),
    ("get_group_conversation_attachment_payloads", ("__group__:灯|爱音", "会话", "甲"), {}),
    ("get_group_conversation_temporary_background", ("__group__:灯|爱音", "仅背景", "甲"), {}),
    ("get_relationship_state", ("灯", "甲"), {}),
    ("get_character_memories", ("灯", "甲"), {}),
    ("get_character_memories_by_kind", ("灯", "甲", "profile"), {}),
    ("get_external_chat_unread_summary", (), {}),
    ("external_chat_context_text", (), {"platform": "qq", "thread_id": "群", "chat_type": "group"}),
    ("get_chat_summary", (), {}), ("get_usage_today", (), {}), ("get_usage_week", (), {}),
    ("get_usage_all_time", (), {}), ("get_usage_daily", (), {}),
    ("get_mood_events_for_chart", ("灯", 0, "甲"), {}),
    ("get_daily_message_counts", (3650, "甲"), {}),
    ("get_messages_per_character_range", (0, "甲"), {}),
    ("get_hourly_heatmap", (3650, "甲"), {}),
    ("get_character_recent_messages", ("灯", "甲"), {"character_aliases": {"灯"}}),
    ("get_character_conversation_chain", ("灯", "甲"), {}),
    ("get_character_album_days", ("灯", "甲"), {}),
])
def test_read_parity(pair, method, args, kwargs):
    old, new = pair
    assert getattr(new, method)(*args, **kwargs) == getattr(old, method)(*args, **kwargs)


@pytest.mark.parametrize("method,args,kwargs", [
    ("update_message_content", (1, 1, "改🐈"), {}),
    ("delete_messages_from", (1, 2), {"include_selected": False}),
    ("delete_message", (1, 2), {}), ("delete_conversation", (1,), {}),
    ("delete_empty_conversations", (), {}),
    ("delete_group_message", ("__group__:灯|爱音", "会话", 1, "甲"), {}),
    ("delete_group_messages_from", ("__group__:灯|爱音", "会话", 2), {"user_key": "甲"}),
    ("delete_group_conversation", ("__group__:灯|爱音", "会话", "甲"), {}),
    ("delete_character_memory", (1, "灯", "甲"), {}),
    ("delete_character_memories", ([1, "2", -1, "bad"], "灯", "甲"), {}),
    ("delete_character_memories_like", ("灯", "甲", "日本"), {}),
    ("mark_external_chat_read", ("qq", "群"), {}),
    ("delete_external_chat", ("group", "qq"), {}),
    ("prune_external_group_chat_limit", (), {}),
    ("purge_external_chat_older_than", (1, "group", "qq"), {}),
])
def test_mutation_parity(pair, method, args, kwargs):
    old, new = pair
    assert getattr(new, method)(*args, **kwargs) == getattr(old, method)(*args, **kwargs)
    for table in ("conversations", "messages", "group_messages", "character_memories", "external_chat_messages"):
        assert new._conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() == old._conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()


def _write_process(path, cid, count):
    with closing(DatabaseManager(path)) as db:
        for i in range(count):
            db.add_message(cid, "user", f"{os.getpid()}:{i}🐈")
            if i < 10:
                db.apply_relationship_delta("灯", "甲", affection_delta=1)


@pytest.mark.parametrize("shared", [False, True])
def test_multithread_writers_and_atomic_state(tmp_path, shared):
    path = str(tmp_path / "threads.db")
    with closing(DatabaseManager(path)) as db:
        cid = db.create_conversation("灯")
        def write(_):
            connection = db if shared else DatabaseManager(path)
            try:
                for i in range(10):
                    connection.add_message(cid, "user", str(i))
                    connection.apply_relationship_delta("灯", "甲", affection_delta=1)
            finally:
                if not shared:
                    connection.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(write, range(4)))
        assert len(db.get_messages(cid)) == 40
        assert db.get_relationship_state("灯", "甲")["affection"] == 90
        assert db.integrity_check() == "ok"


def test_multiprocess_writers(tmp_path):
    path = str(tmp_path / "process.db")
    with closing(DatabaseManager(path)) as db:
        cid = db.create_conversation("灯")
        ctx = multiprocessing.get_context("spawn")
        workers = [ctx.Process(target=_write_process, args=(path, cid, 30)) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(30)
            assert worker.exitcode == 0
        assert len(db.get_messages(cid)) == 120
        assert db.get_relationship_state("灯", "甲")["affection"] == 90


def _crash_process(path, cid, commit):
    db = DatabaseManager(path)
    db._conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES (?,'user','crash🐈')", (cid,))
    if commit:
        db._conn.commit()
    os._exit(29)


@pytest.mark.parametrize("commit", [False, True])
def test_abrupt_exit_and_wal_recovery(tmp_path, commit):
    path = str(tmp_path / "crash.db")
    with closing(DatabaseManager(path)) as db:
        cid = db.create_conversation("灯")
    worker = multiprocessing.get_context("spawn").Process(target=_crash_process, args=(path, cid, commit))
    worker.start()
    worker.join(20)
    assert worker.exitcode == 29
    with closing(DatabaseManager(path)) as reopened:
        assert len(reopened.get_messages(cid)) == int(commit)
        assert reopened.integrity_check() == "ok"


def test_lock_wait_releases_gil_and_timeout_preserves_data(tmp_path):
    path = str(tmp_path / "busy.db")
    with closing(DatabaseManager(path)) as a, closing(DatabaseManager(path)) as b:
        a._conn.execute("BEGIN IMMEDIATE")
        b._conn.execute("PRAGMA busy_timeout=100")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            b.create_conversation("failed")
        b._conn.execute("PRAGMA busy_timeout=2000")
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(b.create_conversation, "success")
            time.sleep(0.05)  # Main thread must regain the GIL to release the writer.
            assert not future.done()
            a._conn.rollback()
            assert future.result(timeout=3) == 1
        assert b._conn.execute("SELECT character FROM conversations").fetchall() == [("success",)]


def test_batch_failure_and_large_history(tmp_path):
    with closing(DatabaseManager(str(tmp_path / "large.db"))) as db:
        cid = db.create_conversation("灯")
        with pytest.raises(sqlite3.IntegrityError):
            db.add_messages(cid, [{"role": "user", "content": "a"}, {"role": "bad", "content": "b"}])
        assert db.get_messages(cid) == []
        ids = db.add_messages(cid, [{"role": "user", "content": f"{i} 中文・日本語🐈"} for i in range(20000)])
        assert db.get_messages(cid, limit=30)[0]["id"] == ids[-30]
        assert db.search_chat_history(keyword="19999 中文")["total"] == 1
        assert len(db.get_messages(cid, limit=1000, before_id=ids[-30])) == 1000


def test_live_import_export_and_relationship_roundtrip(tmp_path):
    source, target, backup = (tmp_path / name for name in ("source.db", "target.db", "backup.db"))
    with closing(DatabaseManager(str(source))) as source_db, closing(DatabaseManager(str(target))) as live:
        cid = source_db.create_conversation("新数据🐈")
        source_db.add_message(cid, "user", "WAL 中的数据")
        source_db.add_character_memory("灯", "甲", "profile", "日本語")
        source_db.upsert_relationship_state("灯", "甲", affection=23)
        live.create_conversation("旧数据")
        assert storage.export_chat_database(str(backup), str(source))["messages"] == 1
        revision = live.change_revision()
        storage.import_chat_database(str(backup), str(target))
        assert live.change_revision()[1] > revision[1]
        assert live.get_messages(cid)[0]["content"] == "WAL 中的数据"
        data = storage.export_relationship_data(str(source))
        assert storage.import_relationship_data(data, str(target)) == {"relationship_states": 1, "character_memories": 1}
        assert live.get_relationship_state("灯", "甲")["affection"] == 23
        # Original Python code can read native output without any format conversion.
        with closing(LegacyDatabase(str(backup))) as old:
            assert old.get_messages(cid) == source_db.get_messages(cid)


def test_corrupt_import_and_attachment_cleanup_are_non_destructive(tmp_path):
    target, corrupt = tmp_path / "target.db", tmp_path / "bad.db"
    corrupt.write_bytes(b"not a sqlite database\x00" * 20)
    with closing(DatabaseManager(str(target))) as db:
        cid = db.create_conversation("保留")
        mid = db.add_message(cid, "user", "保留消息")
        with pytest.raises(sqlite3.DatabaseError):
            storage.import_chat_database(str(corrupt), str(target))
        db._conn.execute("UPDATE messages SET attachments_json=? WHERE id=?", ("{corrupt", mid))
        db._conn.commit()
        with pytest.raises(ValueError, match="corrupt attachments_json"):
            storage.sanitize_chat_attachment_references(str(target))
        assert db._conn.execute("SELECT attachments_json FROM messages").fetchone() == ("{corrupt",)
        assert db.get_messages(cid)[0]["content"] == "保留消息"
    assert corrupt.read_bytes().startswith(b"not a sqlite")


def test_corruption_recovery_uses_verified_backup_without_erasing_evidence(tmp_path):
    source, backup, damaged, recovered = (tmp_path / name for name in
                                          ("source.db", "backup.db", "damaged.db", "recovered.db"))
    with closing(DatabaseManager(str(source))) as db:
        cid = db.create_conversation("灯")
        db.add_message(cid, "user", "备份必须保留🐈")
        db.add_character_memory("灯", "甲", "note", "记忆")
        db.upsert_relationship_state("灯", "甲", affection=42)
    storage.export_chat_database(str(backup), str(source))
    damaged.write_bytes(b"damaged SQLite header" * 256)
    evidence = damaged.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        DatabaseManager(str(damaged))
    storage.import_chat_database(str(backup), str(recovered))
    with closing(DatabaseManager(str(recovered))) as db:
        assert db.get_messages(cid)[0]["content"] == "备份必须保留🐈"
        assert db.get_character_memories("灯", "甲")[0]["content"] == "记忆"
        assert db.get_relationship_state("灯", "甲")["affection"] == 42
        assert db.integrity_check() == "ok"
    assert damaged.read_bytes() == evidence


def test_interrupt_does_not_wait_for_connection_mutex(tmp_path):
    with closing(DatabaseManager(str(tmp_path / "interrupt.db"))) as db:
        started = threading.Event()
        def expensive():
            started.set()
            return db._conn.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<1000000000) SELECT sum(x) FROM n").fetchone()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(expensive)
            started.wait(2)
            time.sleep(0.03)
            db._conn.interrupt()
            with pytest.raises(sqlite3.OperationalError, match="interrupt"):
                future.result(timeout=3)
        assert db.integrity_check() == "ok"
