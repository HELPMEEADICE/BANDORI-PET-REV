from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QCoreApplication

from companion_controller import CompanionController


class FakeConfig:
    values = {
        "llm_api_url": "https://example.invalid/v1",
        "llm_api_key": "secret",
        "llm_model_id": "model",
        "tts_enabled": True,
        "llm_web_search_enabled": True,
        "companion_instance_id": "15fc3780-6d27-46bd-84d4-550c1af70df6",
    }

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeDatabase:
    def get_conversations(self, character="", user_key="default"):
        rows = [
            {"id": 7, "character": "kasumi", "title": "Private", "created_at": "2026-08-12 10:00:00"},
            {"id": 8, "character": "ran", "title": "Other", "created_at": "2026-08-12 11:00:00"},
        ]
        return [item for item in rows if not character or item["character"] == character]

    def get_messages(self, conversation_id, limit=None, before_id=None):
        return [{"id": 1, "role": "user", "content": "hello", "created_at": "2026-08-12 10:01:00"}]

    def get_first_user_message_content(self, conversation_id):
        return "hello"


class FakeWindow:
    def __init__(self):
        self._chat_user_key = "alice"
        self._is_group_chat = False
        self._conv_id = 7
        self._character = "kasumi"
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._db = FakeDatabase()

    def _generation_busy(self):
        return False


def test_state_contains_all_private_conversations_and_no_secrets():
    app = QCoreApplication.instance() or QCoreApplication([])
    controller = CompanionController(FakeWindow(), FakeConfig())
    client = SimpleNamespace(profile_key="alice")

    hello = controller.hello(client)
    assert hello["desktopInstanceId"] == "15fc3780-6d27-46bd-84d4-550c1af70df6"
    assert [item["id"] for item in hello["state"]["conversations"]] == ["7", "8"]
    assert hello["capabilities"]["mcp"] is False
    assert hello["capabilities"]["computerUse"] is False
    assert "api_key" not in str(hello).lower()
    controller._state_timer.stop()


def test_completed_reply_is_not_duplicated_as_streaming_text():
    app = QCoreApplication.instance() or QCoreApplication([])
    window = FakeWindow()
    window._visible_stream_text = "saved assistant reply"
    controller = CompanionController(window, FakeConfig())

    state = controller.state_snapshot()

    assert state["isGenerating"] is False
    assert state["streamingText"] == ""
    controller._state_timer.stop()


def test_group_state_never_exposes_group_metadata_or_messages():
    app = QCoreApplication.instance() or QCoreApplication([])
    window = FakeWindow()
    window._is_group_chat = True
    controller = CompanionController(window, FakeConfig())

    state = controller.state_snapshot()
    assert state["mode"] == "group_unavailable"
    assert state["messages"] == []
    assert "group" not in state
    controller._state_timer.stop()


def test_state_polling_runs_only_while_a_client_is_connected():
    app = QCoreApplication.instance() or QCoreApplication([])
    controller = CompanionController(FakeWindow(), FakeConfig())

    assert not controller._state_timer.isActive()
    controller.window._chat_user_key = "new-profile"
    controller.client_count_changed.emit(1)
    assert controller.active_profile_key == "new-profile"
    assert controller._state_timer.isActive()
    controller._publish_changed_state()
    assert len(controller._last_state_key) == 16

    controller.client_count_changed.emit(0)
    assert not controller._state_timer.isActive()
    assert controller._last_state_key == b""
    assert controller._last_state_stamp is None


def test_unchanged_database_revision_skips_full_snapshot():
    app = QCoreApplication.instance() or QCoreApplication([])
    window = FakeWindow()
    revision = [0]
    window._db.change_revision = lambda: (revision[0], 1)
    controller = CompanionController(window, FakeConfig())
    controller.state_snapshot = Mock(wraps=controller.state_snapshot)

    controller._publish_changed_state()
    controller._publish_changed_state()
    assert controller.state_snapshot.call_count == 1

    revision[0] += 1
    controller._publish_changed_state()
    assert controller.state_snapshot.call_count == 2

    window._visible_stream_text = "new stream text"
    controller._publish_changed_state()
    assert controller.state_snapshot.call_count == 3
    controller._state_timer.stop()
