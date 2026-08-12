from types import SimpleNamespace

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
