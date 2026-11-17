"""Storage contract: isolated files only; legacy is a test oracle, never a fallback."""
import sqlite3

import pytest

from bandori_core.database_manager import DatabaseManager
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
