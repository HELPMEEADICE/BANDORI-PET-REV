import copy
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

import bandori_chat.compact_ai_window as compact_module
from bandori_chat.compact_ai_window import CompactAIWindow
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


@pytest.fixture
def window(monkeypatch):
    QApplication.instance() or QApplication([])
    db = Mock()
    db.get_last_conversation.return_value = None
    monkeypatch.setattr(compact_module, "DatabaseManager", lambda: db)
    win = CompactAIWindow("kasumi", Mock(), Config({}))
    yield win
    win.deleteLater()


def _drag(win, start: QPoint, end: QPoint):
    win._begin_drag(start)
    win._update_drag(end)
    win._end_drag()


def test_default_position_is_used_until_the_user_drags(window):
    window.place_near_pet(QRect(400, 500, 300, 400), QPoint(420, 380))
    assert window.pos() == QPoint(420, 380)
    window.place_near_pet(QRect(450, 520, 300, 400), QPoint(470, 400))
    assert window.pos() == QPoint(470, 400)


def test_dragged_offset_follows_the_pet(window):
    window.place_near_pet(QRect(400, 500, 300, 400), QPoint(420, 380))
    _drag(window, QPoint(0, 0), QPoint(-150, 40))
    assert window.pos() == QPoint(270, 420)

    # The pet moves; the window keeps its dragged offset instead of snapping back.
    window.place_near_pet(QRect(500, 450, 300, 400), QPoint(520, 330))
    assert window.pos() == QPoint(370, 370)


def test_position_updates_do_not_fight_an_active_drag(window):
    window.place_near_pet(QRect(400, 500, 300, 400), QPoint(420, 380))
    window._begin_drag(QPoint(0, 0))
    window._update_drag(QPoint(-100, 0))
    window.place_near_pet(QRect(400, 500, 300, 400), QPoint(420, 380))
    assert window.pos() == QPoint(320, 380)
    window._end_drag()


def test_reset_returns_to_the_default_position(window):
    window.place_near_pet(QRect(400, 500, 300, 400), QPoint(420, 380))
    _drag(window, QPoint(0, 0), QPoint(-150, 40))
    window.reset_position_offset()
    window.place_near_pet(QRect(400, 500, 300, 400), QPoint(420, 380))
    assert window.pos() == QPoint(420, 380)


@pytest.fixture
def services(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(NativePetServices, "_connect_plugins", lambda *args: None)
    cfg = Config({
        "models": [{"character": "kasumi", "costume": "live_default", "pet_mode": "live2d"}],
        "compact_ai_window_enabled": True,
    })
    service = NativePetServices(app, cfg, Mock(), Mock(), Mock())
    service.configure_models(copy.deepcopy(cfg.get("models")))
    yield service
    service.close()
    service.deleteLater()


def test_pet_moves_reposition_through_the_dragged_offset(services):
    overlay = Mock()
    overlay.width.return_value = 320
    overlay.height.return_value = 108
    overlay.isVisible.return_value = True
    services._overlays["kasumi"] = overlay
    services.handle_line('PEER_POS\t{"character":"kasumi","x":400,"y":500,"w":300,"h":400}')
    pet_geo, default = overlay.place_near_pet.call_args.args
    assert pet_geo == QRect(400, 500, 300, 400)
    assert default == QPoint(400 + 150 - 160, 500 - 108 - 8)
    overlay.move.assert_not_called()


def test_reset_setting_clears_the_dragged_offset(services):
    overlay = Mock()
    overlay.width.return_value = 320
    overlay.height.return_value = 108
    services._overlays["kasumi"] = overlay
    services.handle_line('SETTINGS\t{"compact_ai_window_reset_position":true}')
    overlay.reset_position_offset.assert_called_once()
    overlay.place_near_pet.assert_called_once()
