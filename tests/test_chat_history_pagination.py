import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from database_manager import DatabaseManager
from settings_window.pages.chat_history import ChatHistoryModel, ChatHistoryPageMixin


class ChatHistoryPaginationTest(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db = DatabaseManager(str(Path(self._temp_dir.name) / "chat.db"))

    def tearDown(self):
        self._db.close()
        self._temp_dir.cleanup()

    def test_private_messages_page_backwards_without_overlap(self):
        conversation_id = self._db.create_conversation("test")
        message_ids = [
            self._db.add_message(conversation_id, "user", f"message-{index}")
            for index in range(65)
        ]

        latest = self._db.get_messages(conversation_id, limit=31)
        visible_latest = latest[-30:]
        older = self._db.get_messages(
            conversation_id,
            limit=31,
            before_id=visible_latest[0]["id"],
        )

        self.assertEqual(
            [message["id"] for message in visible_latest],
            message_ids[-30:],
        )
        self.assertEqual(
            [message["id"] for message in older[-30:]],
            message_ids[5:35],
        )
        self.assertTrue(set(message["id"] for message in visible_latest).isdisjoint(
            message["id"] for message in older
        ))

    def test_group_messages_page_backwards_respects_user(self):
        first_user_ids = []
        for index in range(40):
            first_user_ids.append(self._db.add_group_message(
                "group",
                "conversation",
                "user",
                f"first-{index}",
                user_key="first",
            ))
            self._db.add_group_message(
                "group",
                "conversation",
                "user",
                f"second-{index}",
                user_key="second",
            )

        latest = self._db.get_group_messages(
            "group",
            "conversation",
            limit=11,
            user_key="first",
        )
        older = self._db.get_group_messages(
            "group",
            "conversation",
            limit=10,
            user_key="first",
            before_id=latest[-10:][0]["id"],
        )

        self.assertEqual(
            [message["id"] for message in latest[-10:]],
            first_user_ids[-10:],
        )
        self.assertEqual(
            [message["id"] for message in older],
            first_user_ids[-20:-10],
        )

    def test_load_more_ignores_stale_generation_results(self):
        harness = SimpleNamespace(
            _history_search_generation=2,
            _history_loading_more=True,
            _history_data_model=ChatHistoryModel(),
            _history_keyword_edit=SimpleNamespace(text=lambda: "new"),
            _history_delegate=SimpleNamespace(set_keyword=lambda _keyword: None),
            _history_qmodel=SimpleNamespace(append_items=lambda _items: (_ for _ in ()).throw(AssertionError("stale result appended"))),
            _history_list_view=SimpleNamespace(set_has_more=lambda _value: None),
            _build_chat_history_query_params=lambda offset=0, skip_count=False: {"keyword": "new"},
            _enrich_record=lambda record: record,
            _update_summary_label=lambda: None,
        )
        harness._chat_history_query_signature = ChatHistoryPageMixin._chat_history_query_signature

        ChatHistoryPageMixin._on_load_more_finished(
            harness,
            {"records": [{"id": 1}], "has_more": True},
            generation=1,
            offset=0,
            signature=("old", "", "", "", "", "", ""),
        )

        self.assertTrue(harness._history_loading_more)
        self.assertEqual([], harness._history_data_model.records)

    def test_load_more_ignores_stale_filter_signature_and_allows_retry(self):
        harness = SimpleNamespace(
            _history_search_generation=3,
            _history_loading_more=True,
            _history_data_model=ChatHistoryModel(),
            _history_keyword_edit=SimpleNamespace(text=lambda: "new"),
            _history_delegate=SimpleNamespace(set_keyword=lambda _keyword: None),
            _history_qmodel=SimpleNamespace(append_items=lambda _items: (_ for _ in ()).throw(AssertionError("stale result appended"))),
            _history_list_view=SimpleNamespace(set_has_more=lambda _value: None),
            _build_chat_history_query_params=lambda offset=0, skip_count=False: {"keyword": "new"},
            _enrich_record=lambda record: record,
            _update_summary_label=lambda: None,
        )
        harness._history_data_model.records = [{"id": 0}]
        harness._chat_history_query_signature = ChatHistoryPageMixin._chat_history_query_signature

        ChatHistoryPageMixin._on_load_more_finished(
            harness,
            {"records": [{"id": 1}], "has_more": True},
            generation=3,
            offset=1,
            signature=("old", "", "", "", "", "", ""),
        )

        self.assertFalse(harness._history_loading_more)
        self.assertEqual([{"id": 0}], harness._history_data_model.records)


if __name__ == "__main__":
    unittest.main()
