import copy
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPropertyAnimation
from PySide6.QtWidgets import QApplication

import bandori_chat.compact_ai_window as compact_module
from bandori_chat.compact_ai_window import (
    EXTERNAL_TASK_STALE_SECONDS,
    CompactAIWindow,
    _auto_hide_seconds_from_config,
)
from bandori_ui.native_pet_services import NativePetServices


class Config:
    def __init__(self, data):
        self.data = data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def load(self):
        pass

    def save(self):
        pass


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(compact_module, "time", fake)
    return fake


@pytest.fixture
def window(monkeypatch, clock):
    QApplication.instance() or QApplication([])
    db = Mock()
    db.get_last_conversation.return_value = None
    monkeypatch.setattr(compact_module, "DatabaseManager", lambda: db)
    cfg = Config({
        "compact_ai_window_enabled": True,
        "compact_ai_window_auto_hide": True,
        "compact_ai_window_auto_hide_seconds": 8,
    })
    win = CompactAIWindow("kasumi", Mock(), cfg)
    # Animations need a running event loop; the logic under test does not.
    monkeypatch.setattr(win, "_fade_supported", lambda: False)
    yield win, cfg, clock
    win._auto_hide_timer.stop()
    win._hover_reveal_timer.stop()
    win.hide()
    win.deleteLater()


def _expire(win, clock, seconds=8):
    clock.now += seconds
    win._on_auto_hide_timeout()


def test_auto_hide_seconds_are_clamped():
    assert _auto_hide_seconds_from_config(0) == 1
    assert _auto_hide_seconds_from_config(10_000) == 600
    assert _auto_hide_seconds_from_config("bad") == 8
    assert _auto_hide_seconds_from_config(float("inf")) == 8


def test_idle_window_hides_after_the_delay(window):
    win, _, clock = window
    win.reveal()
    assert win.isVisible()
    assert win._auto_hide_timer.isActive()
    _expire(win, clock)
    assert not win.isVisible()
    assert win.windowOpacity() == 1.0


def test_early_timeout_waits_for_the_remaining_delay(window):
    win, _, clock = window
    win.reveal()
    clock.now += 3
    win.note_activity()
    _expire(win, clock, seconds=5)
    assert win.isVisible()
    assert win._auto_hide_timer.isActive()
    # Qt's default coarse timer can round its real deadline on each platform.
    # Check the requested delay against the fake clock instead.
    assert win._auto_hide_timer.interval() == 3000
    _expire(win, clock, seconds=2)
    assert win.isVisible()
    _expire(win, clock, seconds=1)
    assert not win.isVisible()


def test_disabled_auto_hide_never_hides(window):
    win, cfg, clock = window
    cfg.data["compact_ai_window_auto_hide"] = False
    win.reveal()
    assert not win._auto_hide_timer.isActive()
    _expire(win, clock, seconds=3600)
    assert win.isVisible()


@pytest.mark.parametrize("make_busy", [
    lambda win: win._input.setPlainText("draft"),
    lambda win: setattr(win, "_pointer_inside", True),
    lambda win: setattr(win, "_dragging", True),
    lambda win: setattr(win, "_worker", Mock()),
    lambda win: setattr(win, "_tts_worker", Mock()),
    lambda win: win.set_pet_hovered(True),
])
def test_busy_states_keep_the_window_visible(window, make_busy):
    win, _, clock = window
    win.reveal()
    make_busy(win)
    _expire(win, clock, seconds=60)
    assert win.isVisible()
    assert win._auto_hide_timer.isActive()


def test_hide_waits_a_full_delay_after_becoming_idle(window):
    win, _, clock = window
    win.reveal()
    win._worker = Mock()
    _expire(win, clock, seconds=60)
    win._worker = None
    _expire(win, clock, seconds=4)
    assert win.isVisible()
    _expire(win, clock, seconds=4)
    assert not win.isVisible()


def test_failed_tts_request_does_not_pin_the_window(window):
    win, _, clock = window
    win.reveal()
    # A TTS error leaves the playing marker behind with no request or audio.
    win._tts_playing_character = "kasumi"
    _expire(win, clock)
    assert not win.isVisible()


def test_external_task_keeps_window_until_done(window):
    win, _, clock = window
    win.reveal()
    win.apply_ai_event({"state": "thinking", "text": "working"})
    _expire(win, clock, seconds=60)
    assert win.isVisible()
    win.apply_ai_event({"state": "done", "text": "finished"})
    _expire(win, clock)
    assert not win.isVisible()


def test_stale_external_task_stops_blocking(window):
    win, _, clock = window
    win.reveal()
    win.apply_ai_event({"state": "tool", "text": "running"})
    clock.now += EXTERNAL_TASK_STALE_SECONDS
    win._on_auto_hide_timeout()
    _expire(win, clock)
    assert not win.isVisible()


def test_hover_reveals_after_a_short_dwell(window):
    win, _, _ = window
    win.set_pet_hovered(True)
    assert not win.isVisible()
    assert win._hover_reveal_timer.isActive()
    win._hover_reveal_timer.timeout.emit()
    assert win.isVisible()


def test_hover_without_reveal_only_keeps_visible(window):
    win, _, _ = window
    win.set_pet_hovered(True, reveal=False)
    assert not win._hover_reveal_timer.isActive()


def test_brief_hover_does_not_reveal(window):
    win, _, _ = window
    win.set_pet_hovered(True)
    win.set_pet_hovered(False)
    assert not win._hover_reveal_timer.isActive()
    assert not win.isVisible()


@pytest.mark.parametrize("setting", [
    "compact_ai_window_enabled",
    "compact_ai_window_auto_hide",
    "compact_ai_window_show_on_hover",
])
def test_disabling_hover_reveal_cancels_pending_dwell(window, setting):
    win, cfg, _ = window
    win.set_pet_hovered(True)
    cfg.data[setting] = False
    win.apply_auto_hide_setting()
    assert not win._hover_reveal_timer.isActive()
    win._on_hover_reveal_timeout()
    assert not win.isVisible()


def test_disabling_auto_hide_cancels_a_pending_fade_out(window, monkeypatch):
    win, cfg, clock = window
    win.reveal()
    monkeypatch.setattr(win, "_fade_supported", lambda: True)
    _expire(win, clock)
    fade = win._fade_anim
    assert fade is not None
    cfg.data["compact_ai_window_auto_hide"] = False
    win.apply_auto_hide_setting()
    # A cancelled animation must not hide the now permanently visible window.
    assert fade.state() == QPropertyAnimation.State.Stopped
    assert win.windowOpacity() == 1.0
    assert win.isVisible()


def test_repeated_fades_release_finished_and_cancelled_animations(window, monkeypatch):
    win, _, _ = window
    monkeypatch.setattr(win, "_fade_supported", lambda: True)
    win.reveal()
    win._fade_anim.setCurrentTime(win._fade_anim.duration())
    for _ in range(5):
        win.conceal()
        win._fade_anim.setCurrentTime(win._fade_anim.duration() // 2)
        win.reveal()
        win._fade_anim.setCurrentTime(win._fade_anim.duration())
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not win.findChildren(QPropertyAnimation)


def test_conceal_keeps_output_text(window):
    win, _, clock = window
    win.reveal()
    win.apply_ai_event({"state": "done", "text": "keep me", "mode": "replace_raw"})
    _expire(win, clock)
    assert not win.isVisible()
    assert win._output.toPlainText() == "keep me"


@pytest.fixture
def services(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(NativePetServices, "_connect_plugins", lambda *args: None)
    cfg = Config({
        "models": [{"character": "kasumi", "costume": "live_default", "pet_mode": "live2d"}],
        "compact_ai_window_enabled": True,
        "compact_ai_window_auto_hide": True,
    })
    service = NativePetServices(app, cfg, Mock(), Mock(), Mock())
    service.configure_models(copy.deepcopy(cfg.get("models")))
    overlay = Mock()
    overlay.isVisible.return_value = False
    overlay.width.return_value = 320
    overlay.height.return_value = 108
    monkeypatch.setattr(service, "_ensure_overlay", lambda char: overlay)
    monkeypatch.setattr(service, "_request_outfit_description", lambda char: None)
    yield service, cfg, overlay
    service.close()
    service.deleteLater()


def _native_event(kind, data=None):
    return {"character": "kasumi", "costume": "live_default", "event": kind, "data": data or {}}


def test_ready_does_not_show_an_auto_hidden_overlay(services):
    service, _, overlay = services
    service.handle_event(_native_event("ready"))
    overlay.show.assert_not_called()


def test_ready_shows_overlay_when_auto_hide_is_off(services):
    service, cfg, overlay = services
    cfg.data["compact_ai_window_auto_hide"] = False
    service.handle_event(_native_event("ready"))
    overlay.show.assert_called_once()


def test_hover_event_reaches_the_overlay(services):
    service, _, overlay = services
    service.handle_event(_native_event("hover", {"inside": True}))
    overlay.set_pet_hovered.assert_called_once_with(True, reveal=True)


def test_hover_respects_show_on_hover_setting(services):
    service, cfg, overlay = services
    cfg.data["compact_ai_window_show_on_hover"] = False
    service.handle_event(_native_event("hover", {"inside": True}))
    overlay.set_pet_hovered.assert_not_called()


def test_hover_is_ignored_without_auto_hide(services):
    service, cfg, overlay = services
    cfg.data["compact_ai_window_auto_hide"] = False
    service.handle_event(_native_event("hover", {"inside": True}))
    overlay.set_pet_hovered.assert_not_called()


def test_hover_exit_updates_existing_overlay_while_auto_hide_is_disabled(services):
    service, cfg, overlay = services
    service._overlays["kasumi"] = overlay
    cfg.data["compact_ai_window_auto_hide"] = False
    service.handle_event(_native_event("hover", {"inside": False}))
    overlay.set_pet_hovered.assert_called_once_with(False, reveal=False)


def test_ai_event_reveals_the_overlay(services):
    service, _, overlay = services
    service.handle_line('AI_EVENT\t{"state":"thinking","text":"hi"}')
    overlay.reveal.assert_called_once()
    overlay.apply_ai_event.assert_called_once()


def test_settings_keep_auto_hidden_overlay_hidden(services):
    service, _, overlay = services
    service._overlays["kasumi"] = overlay
    service.handle_line('SETTINGS\t{"compact_ai_window_enabled":true}')
    overlay.show.assert_not_called()
    overlay.apply_auto_hide_setting.assert_called_once()
