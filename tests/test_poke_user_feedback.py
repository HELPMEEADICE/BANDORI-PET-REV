from unittest.mock import patch

from PySide6.QtCore import QPoint

from chat_window.chat_window import (
    _POKE_WINDOW_SHAKE_AMPLITUDE,
    _POKE_WINDOW_SHAKE_DURATION_MS,
    ChatWindow,
)




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


class _SignalHarness:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _AnimationHarness:
    def __init__(self, parent):
        self.parent = parent
        self.valueChanged = _SignalHarness()
        self.finished = _SignalHarness()
        self.key_values = []
        self.started = False

    def setDuration(self, duration):
        self.duration = duration

    def setEasingCurve(self, curve):
        self.curve = curve

    def setKeyValueAt(self, step, value):
        self.key_values.append((step, value))

    def start(self):
        self.started = True


class _ShakeHarness:
    _play_poke_window_shake = ChatWindow._play_poke_window_shake

    def __init__(self):
        self._closing = False
        self._close_animating = False
        self._poke_window_anim = None
        self._poke_window_anim_origin = None
        self.moves = []

    def isVisible(self):
        return True

    def isMinimized(self):
        return False

    def pos(self):
        return QPoint(120, 80)

    def move(self, point):
        self.moves.append(QPoint(point))






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


def test_chat_poke_shake_builds_and_starts_position_animation():
    harness = _ShakeHarness()

    with patch("chat_window.chat_window.QVariantAnimation", _AnimationHarness):
        harness._play_poke_window_shake()

    animation = harness._poke_window_anim
    assert animation.started is True
    assert animation.duration == _POKE_WINDOW_SHAKE_DURATION_MS
    assert animation.key_values[0] == (0.0, QPoint(120, 80))
    assert animation.key_values[-1] == (1.0, QPoint(120, 80))
    assert harness._poke_window_anim_origin == QPoint(120, 80)


def test_model_poke_does_not_shake_unrelated_chat_window():
    harness = _ChatPokeHarness()

    harness.handle_external_user_poke({
        "character": "ran",
        "source": "llm_tool",
        "direction": "to_user",
    })

    assert harness.calls == []
