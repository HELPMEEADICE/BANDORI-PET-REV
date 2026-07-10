import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess, QRect

from chat_process import focus_chat_window
from chat_window.chat_window import ChatWindow
from pet_window import PetWindow


class _RunningProcess:
    def state(self):
        return QProcess.ProcessState.Running


class _PetChatHarness:
    _open_chat = PetWindow._open_chat

    def __init__(self):
        self._chat_process = _RunningProcess()
        self.ipc_lines = []

    def _send_ipc(self, line: str) -> bool:
        self.ipc_lines.append(line)
        return True


class _WindowAnim:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class _ChatWindowHarness:
    prepare_for_reopen = ChatWindow.prepare_for_reopen

    def __init__(self):
        self._closing = True
        self._close_animating = True
        self._close_waiting_for_workers = True
        self._window_anim = _WindowAnim()
        self._pre_close_geometry = QRect(20, 30, 640, 480)
        self.restored_geometry = None
        self.enabled = False
        self.opacity = 0.0

    def setEnabled(self, enabled: bool):
        self.enabled = enabled

    def setWindowOpacity(self, opacity: float):
        self.opacity = opacity

    def setGeometry(self, geometry: QRect):
        self.restored_geometry = QRect(geometry)


class _FocusWindow:
    def __init__(self):
        self.events = []

    def prepare_for_reopen(self):
        self.events.append("prepare")

    def isMinimized(self):
        self.events.append("isMinimized")
        return False

    def show(self):
        self.events.append("show")

    def showNormal(self):
        self.events.append("showNormal")

    def raise_(self):
        self.events.append("raise")

    def activateWindow(self):
        self.events.append("activate")


class ChatReopenTest(unittest.TestCase):
    def test_pet_reopening_running_chat_sends_focus_request(self):
        harness = _PetChatHarness()

        harness._open_chat()

        self.assertEqual(["FOCUS_CHAT"], harness.ipc_lines)

    def test_focus_restores_chat_window_deferred_close_state(self):
        harness = _ChatWindowHarness()

        harness.prepare_for_reopen()
        self.assertFalse(harness._closing)
        self.assertFalse(harness._close_animating)
        self.assertFalse(harness._close_waiting_for_workers)
        self.assertTrue(harness.enabled)
        self.assertEqual(1.0, harness.opacity)
        self.assertTrue(harness._window_anim.stopped)
        self.assertEqual(QRect(20, 30, 640, 480), harness.restored_geometry)
        self.assertFalse(hasattr(harness, "_pre_close_geometry"))

    def test_ipc_focus_prepares_window_before_showing(self):
        window = _FocusWindow()

        focus_chat_window(window)
        self.assertEqual(["prepare", "isMinimized", "show", "raise", "activate"], window.events)

    def test_main_reopening_running_direct_chat_broadcasts_focus(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('broadcast_ipc_line("FOCUS_CHAT")', source)

    def test_main_reopening_running_settings_broadcasts_focus(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('broadcast_ipc_line("FOCUS_SETTINGS")', source)
        self.assertIn('broadcast_ipc_line(f"SHOW_COSTUMES\\t{costume_character}")', source)

    def test_settings_process_focuses_existing_window_requests(self):
        source = Path("settings_process.py").read_text(encoding="utf-8")
        self.assertIn('elif line == "FOCUS_SETTINGS":', source)
        self.assertIn('window.show_costume_picker(character)\n                bring_window_to_front()', source)


if __name__ == "__main__":
    unittest.main()
