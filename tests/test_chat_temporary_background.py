import os
import sqlite3
import tempfile
import unittest

from chat_window.chat_window import ChatWindow
from database_manager import DatabaseManager


class TemporaryBackgroundTests(unittest.TestCase):
    def test_private_background_persists_and_keeps_background_only_conversation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "chat.db")
            db = DatabaseManager(path)
            conversation_id = db.create_conversation("character", user_key="user-a")
            db.set_conversation_temporary_background(conversation_id, "  scene\nrule  ")
            db.delete_empty_conversations("character", "user-a")
            db.close()

            reopened = DatabaseManager(path)
            self.assertEqual(
                "scene\nrule",
                reopened.get_conversation_temporary_background(conversation_id),
            )
            self.assertEqual(
                conversation_id,
                reopened.get_last_conversation("character", "user-a")["id"],
            )
            reopened.set_conversation_temporary_background(conversation_id, "")
            reopened.delete_empty_conversations("character", "user-a")
            self.assertIsNone(reopened.get_last_conversation("character", "user-a"))
            reopened.close()

    def test_old_database_schema_is_migrated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "old.db")
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE conversations (id INTEGER PRIMARY KEY, character TEXT NOT NULL, "
                "user_key TEXT NOT NULL DEFAULT '', title TEXT DEFAULT '', created_at TEXT NOT NULL)"
            )
            conn.commit()
            conn.close()
            db = DatabaseManager(path)
            columns = {
                row[1] for row in db._conn.execute("PRAGMA table_info(conversations)").fetchall()
            }
            self.assertIn("temporary_background", columns)
            db.close()

    def test_group_background_is_isolated_and_removed_with_conversation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = DatabaseManager(os.path.join(temp_dir, "chat.db"))
            db.set_group_conversation_temporary_background("group", "one", "scene", "user-a")
            db.set_group_conversation_temporary_background("group", "one", "other", "user-b")
            self.assertEqual(
                "scene",
                db.get_group_conversation_temporary_background("group", "one", "user-a"),
            )
            self.assertEqual(
                "other",
                db.get_group_conversation_temporary_background("group", "one", "user-b"),
            )
            db.delete_group_conversation("group", "one", "user-a")
            self.assertEqual(
                "",
                db.get_group_conversation_temporary_background("group", "one", "user-a"),
            )
            self.assertEqual(
                "other",
                db.get_group_conversation_temporary_background("group", "one", "user-b"),
            )
            db.close()

    def test_prompt_section_is_added_only_for_nonempty_background(self):
        window = ChatWindow.__new__(ChatWindow)
        window._temporary_background = "night scene\nkeep it quiet"
        self.assertEqual(
            "base\n\n【当前会话临时背景】\n"
            "以下内容是当前会话的补充背景，请在理解用户消息和组织回复时自然地参考，"
            "并尽量保持场景与设定连贯：\n"
            "night scene\nkeep it quiet",
            window._system_prompt_with_temporary_background("base"),
        )
        window._temporary_background = "  "
        self.assertEqual("base", window._system_prompt_with_temporary_background("base"))


if __name__ == "__main__":
    unittest.main()
