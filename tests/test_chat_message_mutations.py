import os
import tempfile
import unittest

from database_manager import DatabaseManager


class ChatMessageMutationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(os.path.join(self.temp_dir.name, "chat.db"))

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_private_edit_delete_and_rollback(self):
        conversation_id = self.db.create_conversation("character", user_key="user-a")
        first = self.db.add_message(conversation_id, "user", "first")
        second = self.db.add_message(conversation_id, "assistant", "second")
        third = self.db.add_message(conversation_id, "user", "third")

        self.assertTrue(self.db.update_message_content(conversation_id, first, "edited"))
        removed = self.db.delete_message(conversation_id, second)
        self.assertEqual([second], [item["id"] for item in removed])
        fourth = self.db.add_message(conversation_id, "assistant", "fourth")
        removed = self.db.delete_messages_from(
            conversation_id,
            third,
            include_selected=True,
        )
        self.assertEqual([third, fourth], [item["id"] for item in removed])
        self.assertEqual(
            [(first, "edited")],
            [(item["id"], item["content"]) for item in self.db.get_messages(conversation_id)],
        )

    def test_group_mutations_are_scoped_by_user_and_conversation(self):
        target = self.db.add_group_message("group", "thread", "user", "target", user_key="user-a")
        later = self.db.add_group_message("group", "thread", "assistant", "later", user_key="user-a")
        other_user = self.db.add_group_message("group", "thread", "user", "other", user_key="user-b")
        other_thread = self.db.add_group_message("group", "other-thread", "user", "other", user_key="user-a")

        self.assertTrue(
            self.db.update_group_message_content("group", "thread", target, "edited", "user-a")
        )
        removed = self.db.delete_group_messages_from(
            "group",
            "thread",
            target,
            include_selected=False,
            user_key="user-a",
        )
        self.assertEqual([later], [item["id"] for item in removed])
        self.assertEqual(
            [target],
            [item["id"] for item in self.db.get_group_messages("group", "thread", user_key="user-a")],
        )
        self.assertEqual(
            [other_user],
            [item["id"] for item in self.db.get_group_messages("group", "thread", user_key="user-b")],
        )
        self.assertEqual(
            [other_thread],
            [item["id"] for item in self.db.get_group_messages("group", "other-thread", user_key="user-a")],
        )


if __name__ == "__main__":
    unittest.main()
