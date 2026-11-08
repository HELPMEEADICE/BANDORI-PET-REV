import os
from types import MethodType, SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from bandori_models import model_manager
from bandori_models.model_manager import ModelManager
from bandori_models.zst_model_archive import load_virtual_bytes
from chat_window.avatar_utils import _rounded_avatar_pixmap
from chat_window.chat_window import ChatWindow
from chat_window.message_bubble import MessageBubble
from chat_window.widgets import GroupChatListRow
from settings_window.settings_window import SettingsWindow
from settings_window.workers import ModelDetailImageWorker
from tests.test_native_assets import write_archive


@pytest.fixture
def portrait_archive(tmp_path):
    image = QImage(48, 96, QImage.Format.Format_ARGB32)
    image.fill(0xFF5588AA)
    portrait = tmp_path / "portrait.png"
    assert image.save(str(portrait))
    archive = tmp_path / "tomorin.zst"
    write_archive(archive, {
        "character.png": portrait.read_bytes(),
        "casual/model.json": b"{}",
    })
    return archive, portrait.read_bytes()


@pytest.mark.parametrize("full_scan", [False, True])
def test_portrait_recovers_after_startup_archive_scan_fails(portrait_archive, full_scan):
    archive, expected = portrait_archive
    with patch.object(model_manager, "model_search_dirs", return_value=[archive.parent]):
        with patch.object(model_manager, "scan_model_archive", side_effect=OSError("busy")):
            manager = ModelManager(scan_models=full_scan)
        assert not manager._character_images.get("tomorin")
        assert manager.get_character_image_path("tomorin") == ""
        assert manager.get_character_image_data("tomorin") == expected


@pytest.mark.parametrize("first_result", [OSError("busy"), b""])
def test_transient_archive_read_failure_recovers_in_same_request(portrait_archive, first_result):
    archive, expected = portrait_archive
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = f"{archive}::character.png"
    with patch.object(model_manager, "load_virtual_bytes", side_effect=[first_result, expected]) as read:
        data = manager.get_character_image_data("tomorin")
    assert data == expected
    assert read.call_count == 2


def test_stale_portrait_member_is_rediscovered_after_archive_replacement(portrait_archive):
    archive, expected = portrait_archive
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = f"{archive}::old-character.png"
    with patch.object(model_manager, "model_search_dirs", return_value=[archive.parent]):
        assert manager.get_character_image_data("tomorin") == expected
    assert manager._character_images["tomorin"].endswith("::character.png")


def test_missing_local_portrait_is_rediscovered(tmp_path):
    character_dir = tmp_path / "tomorin"
    character_dir.mkdir()
    portrait = character_dir / "character.webp"
    portrait.write_bytes(b"portrait")
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = str(character_dir / "character.png")
    with patch.object(model_manager, "model_search_dirs", return_value=[tmp_path]):
        assert manager.get_character_image_path("tomorin") == str(portrait.resolve())


def test_detail_worker_and_chat_avatar_recover_from_transient_read_failure(portrait_archive):
    app = QApplication.instance() or QApplication([])
    archive, expected = portrait_archive
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = f"{archive}::character.png"
    worker = ModelDetailImageWorker(manager, "tomorin", image_size=QSize(48, 96))
    results = []
    worker.image_loaded.connect(results.append)
    with patch.object(model_manager, "load_virtual_bytes", side_effect=[OSError("busy"), expected]):
        worker.start()
        assert worker.wait(5000)
    app.processEvents()
    assert len(results) == 1
    assert not results[0]["image"].isNull()

    attempts = 0

    def fail_once(path, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("busy")
        return load_virtual_bytes(path, **kwargs)

    with patch.object(model_manager, "load_virtual_bytes", side_effect=fail_once):
        data = manager.get_character_image_data("tomorin")
        assert not _rounded_avatar_pixmap(data=data, focus="head").isNull()


def test_settings_does_not_cache_failed_decode(portrait_archive):
    app = QApplication.instance() or QApplication([])
    archive, expected = portrait_archive
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = f"{archive}::character.png"
    window = SettingsWindow.__new__(SettingsWindow)
    window._model_manager = manager
    window._detail_image_pixmap_cache = {}
    with patch.object(model_manager, "load_virtual_bytes", side_effect=[OSError("busy")] * 2 + [expected]):
        assert window._load_detail_character_pixmap("tomorin") is None
        assert "tomorin" not in window._detail_image_pixmap_cache
        assert not window._load_detail_character_pixmap("tomorin").isNull()
    app.processEvents()


def test_permanent_archive_failure_stops_after_one_retry(portrait_archive):
    archive, _ = portrait_archive
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = f"{archive}::character.png"
    with patch.object(model_manager, "load_virtual_bytes", side_effect=OSError("unavailable")) as read:
        assert manager.get_character_image_data("tomorin") == b""
    assert read.call_count == 2


def test_successful_detail_decode_is_cached_without_rereading_archive(portrait_archive):
    app = QApplication.instance() or QApplication([])
    archive, expected = portrait_archive
    manager = ModelManager(discover_models=False)
    manager._character_images["tomorin"] = f"{archive}::character.png"
    window = SettingsWindow.__new__(SettingsWindow)
    window._model_manager = manager
    window._detail_image_pixmap_cache = {}
    with patch.object(model_manager, "load_virtual_bytes", return_value=expected) as read:
        first = window._load_detail_character_pixmap("tomorin")
        assert not first.isNull()
        assert window._load_detail_character_pixmap("tomorin") is first
    read.assert_called_once()
    app.processEvents()


@pytest.mark.parametrize("view", ["sidebar", "title", "message"])
@pytest.mark.parametrize("failure", ["startup_scan", "first_read"])
def test_chat_avatar_widgets_recover_on_first_open(portrait_archive, view, failure):
    app = QApplication.instance() or QApplication([])
    archive, expected = portrait_archive
    with patch.object(model_manager, "model_search_dirs", return_value=[archive.parent]):
        with patch.object(model_manager, "scan_model_archive", side_effect=OSError("busy")):
            manager = ModelManager(scan_models=False)
        if failure == "first_read":
            manager._character_images["tomorin"] = f"{archive}::character.png"
        harness = SimpleNamespace(
            _model_manager=manager, _chat_avatar_paths={},
            _normalize_group_characters=lambda characters: characters,
            _title_avatar_character=lambda: "tomorin",
            _title_avatar=QLabel(), _display_name="Tomori",
        )
        harness._avatar_info_for_character = MethodType(ChatWindow._avatar_info_for_character, harness)
        responses = [OSError("busy"), expected] if failure == "first_read" else [expected]
        with patch.object(model_manager, "load_virtual_bytes", side_effect=responses):
            if view == "sidebar":
                pixmap = ChatWindow._chat_avatar_pixmap_for_characters(harness, ["tomorin"])
                widget = GroupChatListRow(["tomorin"], "Tomori", "hello", True, avatar_pixmap=pixmap)
                label = widget.findChild(QLabel, "GroupListAvatar")
            elif view == "title":
                ChatWindow._update_title_avatar(harness)
                widget = label = harness._title_avatar
            else:
                path, data, focus = harness._avatar_info_for_character("tomorin")
                widget = MessageBubble("hello", "assistant", author="Tomori",
                                       avatar_path=path, avatar_data=data, avatar_focus=focus)
                label = widget._avatar
        assert not label.pixmap().isNull()
        assert label.text() == ""
        widget.close()
        widget.deleteLater()
        if view != "title":
            harness._title_avatar.deleteLater()
        app.processEvents()
