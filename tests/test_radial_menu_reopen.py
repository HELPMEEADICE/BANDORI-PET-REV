import os
import unittest
from unittest.mock import Mock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

import radial_menu as radial_menu_module
from pet_window import PetWindow
from radial_menu import RadialMenu


class _FakeProcess:
    def __init__(self):
        self.deleted = False

    def deleteLater(self):
        self.deleted = True


class _FakeSocket:
    def state(self):
        return QLocalSocket.LocalSocketState.UnconnectedState

    def abort(self):
        raise AssertionError("unconnected socket should not be aborted")


class _RecoveryHarness:
    _on_radial_menu_process_finished = PetWindow._on_radial_menu_process_finished

    def __init__(self, process):
        self._radial_menu_process = process
        self._radial_menu_buffer = "partial"
        self._radial_menu_server_name = "old-server"
        self._radial_menu_command_queue = ["SHOW\t{}"]
        self._radial_menu_process_ready = True
        self._radial_menu_shutting_down = False
        self._radial_menu_opening = True
        self._radial_menu_visible = True
        self._radial_menu_socket = _FakeSocket()
        self.restart_count = 0
        self.broadcasts = []

    def _broadcast_radial_menu_state(self, *, open):
        self.broadcasts.append(open)

    def _ensure_radial_menu_process(self):
        self.restart_count += 1


class RadialMenuReopenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_menu_can_show_again_after_close_animation(self):
        menu = RadialMenu()
        menu.add_item("", "Chat", QColor(80, 80, 80), lambda: None)
        item = menu._items[0].widget

        with (
            patch.object(menu, "show"),
            patch.object(menu, "hide"),
            patch.object(menu, "setFocus"),
            patch.object(menu, "_play_show_animation"),
            patch.object(menu._outside_click_timer, "start"),
            patch.object(menu._outside_click_timer, "stop"),
            patch.object(item, "show"),
        ):
            menu.show_at(QPoint(200, 200))
            self.assertTrue(menu._is_showing)
            menu._on_hide_finished()
            self.assertFalse(menu._is_showing)

            menu.show_at(QPoint(220, 220))
            self.assertTrue(menu._is_showing)

    def test_macos_global_mouse_state_detects_clicks_outside_menu_process(self):
        native_button_state = Mock(
            side_effect=lambda _source, button: button == 1
        )

        with (
            patch.object(radial_menu_module, "_get_async_key_state", None),
            patch.object(
                radial_menu_module,
                "_get_macos_button_state",
                native_button_state,
            ),
        ):
            self.assertTrue(RadialMenu._mouse_buttons_pressed())

        self.assertEqual(
            [call(0, 0), call(0, 1)],
            native_button_state.call_args_list,
        )

    def test_pending_show_survives_child_process_exit(self):
        process = _FakeProcess()
        harness = _RecoveryHarness(process)

        with patch("pet_window.QTimer.singleShot", side_effect=lambda _delay, callback: callback()):
            harness._on_radial_menu_process_finished(process)

        self.assertEqual(["SHOW\t{}"], harness._radial_menu_command_queue)
        self.assertEqual(1, harness.restart_count)
        self.assertEqual([False], harness.broadcasts)
        self.assertTrue(process.deleted)


if __name__ == "__main__":
    unittest.main()
