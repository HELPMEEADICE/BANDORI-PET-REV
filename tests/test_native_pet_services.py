import copy
import json
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QCoreApplication

from bandori_ui.native_pet_services import NativePetServices


class Config:
    def __init__(self, data):
        self.data = data
        self.saved = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def load(self):
        pass

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saved += 1


@pytest.fixture
def services(monkeypatch):
    app = QCoreApplication.instance() or QCoreApplication([])
    monkeypatch.setattr(NativePetServices, "_connect_plugins", lambda *args: None)
    cfg = Config({"models": [{"character": "kasumi", "costume": "live_default", "default_motion": "idle", "pet_mode": "live2d"}], "secret_key": "preserve"})
    broadcast = Mock()
    service = NativePetServices(app, cfg, Mock(), broadcast, Mock())
    service.configure_models(copy.deepcopy(cfg.get("models")))
    yield service, cfg, broadcast
    service.close()
    service.deleteLater()


def test_native_placement_updates_only_the_target_models_geometry(services):
    service, cfg, _ = services
    service.handle_event({"character": "kasumi", "costume": "live_default", "event": "placement", "data": {"x": -120, "y": 90, "width": 400, "height": 650}})
    assert cfg.data["models"][0]["window_x"] == -120
    assert cfg.data["models"][0]["default_motion"] == "idle"
    assert cfg.data["secret_key"] == "preserve"
    assert cfg.saved == 1


def test_unknown_or_stale_costume_cannot_overwrite_saved_geometry(services):
    service, cfg, _ = services
    original = copy.deepcopy(cfg.data)
    service.handle_event({"character": "kasumi", "costume": "old", "event": "placement", "data": {"x": 200}})
    assert cfg.data == original
    assert cfg.saved == 0


def test_pixel_position_uses_its_own_saved_coordinates(services):
    service, cfg, _ = services
    cfg.data["models"][0].update(pet_mode="pixel", window_x=800)
    service.handle_event({"character": "kasumi", "costume": "live_default", "event": "placement", "data": {"x": 100, "y": 200}})
    assert cfg.data["models"][0]["pixel_window_x"] == 100
    assert cfg.data["models"][0]["window_x"] == 800


def test_pixel_switch_sends_patch_without_mutating_controller_snapshot(services, monkeypatch):
    service, cfg, _ = services
    send = Mock()
    monkeypatch.setattr("bandori_core.ipc_bus.send_ipc_message", send)
    original = copy.deepcopy(cfg.data)
    service._toggle_pixel("kasumi")
    patch = json.loads(send.call_args.args[0].split("\t", 1)[1])
    assert patch["models"][0]["pet_mode"] == "pixel"
    assert cfg.data == original


def test_native_overlay_can_be_enabled_without_an_external_chat_event(services, monkeypatch):
    service, _, _ = services
    overlay = Mock()
    monkeypatch.setattr(service, "_ensure_overlay", lambda char: overlay)
    service.handle_line('SETTINGS\t{"compact_ai_window_enabled":true}')
    overlay.show.assert_called_once()


def test_music_settings_only_manage_service_and_never_send_scales(services, monkeypatch):
    service, cfg, broadcast = services
    cfg.data["music_bounce_enabled"] = True
    running = Mock()
    monkeypatch.setattr(service._music, "set_running", running)
    service.handle_line('SETTINGS\t{"music_bounce_enabled":true}')
    running.assert_called_with(True)
    broadcast.reset_mock()
    for _ in range(100):
        service._poll()
    broadcast.assert_not_called()
    assert not service._timer.isActive()
    service.handle_line('SETTINGS\t{"music_bounce_enabled":false}')
    running.assert_called_with(False)


def test_all_paused_roles_stop_shared_service_and_one_resuming_restarts_it(services, monkeypatch):
    service, cfg, _ = services
    cfg.data["music_bounce_enabled"] = True
    running = Mock()
    monkeypatch.setattr(service._music, "set_running", running)
    service.roles["other"] = {"character": "other", "music_active": True}
    def activity(char, active):
        service.handle_event({"character": char, "costume": "live_default", "event": "music_active", "data": {"active": active}})
    activity("kasumi", False)
    running.assert_called_with(True)
    activity("other", False)
    running.assert_called_with(False)
    activity("kasumi", True)
    running.assert_called_with(True)


def test_music_source_changes_use_reliable_control_lane(services):
    from bandori_core.ipc_bus import is_control_ipc_line, is_reliable_ipc_line
    service, _, broadcast = services
    service._music_source_changed("session-level.shm")
    line = broadcast.call_args.args[0]
    assert is_control_ipc_line(line) and is_reliable_ipc_line(line)
    assert json.loads(line.split("\t", 1)[1]) == {"path": "session-level.shm"}


def test_menu_relay_preserves_the_native_click_monitor(services):
    service, _, _ = services
    state = {"pending": None, "commands": Mock(), "process": Mock()}
    service._menus["kasumi"] = state
    position = {"x": 2720, "y": 600, "coordinate_space": "native_physical",
                "screen_name": "secondary", "screen_geometry": [1920, 0, 2560, 1440]}
    service.show_menu("kasumi", position)
    payload = json.loads(state["pending"].split("\t", 1)[1])
    assert {key: payload[key] for key in position} == position
