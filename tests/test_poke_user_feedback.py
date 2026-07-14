from pet_window import (
    POKE_USER_BADGE_DURATION_MS,
    POKE_USER_WINDOW_SHAKE_INTENSITY,
    PetWindow,
)
from chat_window.chat_window import (
    _POKE_WINDOW_SHAKE_AMPLITUDE,
    _POKE_WINDOW_SHAKE_DURATION_MS,
    ChatWindow,
)


class _PokeHarness:
    _handle_user_poke = PetWindow._handle_user_poke

    def __init__(self):
        self._current_char = "kasumi"
        self.calls = []

    def _note_user_interaction(self):
        self.calls.append(("interaction",))

    def _show_character_poked_user_feedback(self, event):
        self.calls.append(("badge", dict(event)))

    def _play_emotion_window_feedback(self, kind, intensity):
        self.calls.append(("window", kind, intensity))

    def _trigger_user_poke_feedback(self):
        self.calls.append(("model",))


class _ChatPokeHarness:
    handle_external_user_poke = ChatWindow.handle_external_user_poke

    def __init__(self):
        self._character = "kasumi"
        self._is_group_chat = False
        self._group_characters = []
        self.calls = []

    def _play_poke_window_shake(self):
        self.calls.append(("window_shake",))

    def _send_poke_to_character(self, character):
        self.calls.append(("send", character))


def test_model_poke_shows_extended_badge_and_subtle_window_shake():
    harness = _PokeHarness()
    event = {
        "character": "kasumi",
        "message": "戳戳",
        "source": "llm_tool",
        "direction": "to_user",
    }

    harness._handle_user_poke(event)

    assert POKE_USER_BADGE_DURATION_MS == 1980
    assert harness.calls == [
        ("interaction",),
        ("badge", event),
        ("window", "shake", POKE_USER_WINDOW_SHAKE_INTENSITY),
    ]


def test_model_poke_only_affects_target_character():
    harness = _PokeHarness()

    harness._handle_user_poke({
        "character": "ran",
        "source": "llm_tool",
        "direction": "to_user",
    })

    assert harness.calls == []


def test_model_poke_shakes_matching_chat_window_without_sending_again():
    harness = _ChatPokeHarness()

    harness.handle_external_user_poke({
        "character": "kasumi",
        "source": "llm_tool",
        "direction": "to_user",
    })

    assert _POKE_WINDOW_SHAKE_DURATION_MS == 360
    assert _POKE_WINDOW_SHAKE_AMPLITUDE == 8
    assert harness.calls == [("window_shake",)]


def test_model_poke_does_not_shake_unrelated_chat_window():
    harness = _ChatPokeHarness()

    harness.handle_external_user_poke({
        "character": "ran",
        "source": "llm_tool",
        "direction": "to_user",
    })

    assert harness.calls == []
