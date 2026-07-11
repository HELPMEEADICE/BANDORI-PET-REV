import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from chat_window.chat_window import ChatWindow


class _ConfigStub:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        return False


class _AvatarHarness(QWidget):
    _set_character_avatar = ChatWindow._set_character_avatar
    _reset_character_avatar = ChatWindow._reset_character_avatar

    def __init__(self, storage_dir):
        super().__init__()
        self._cfg = _ConfigStub()
        self._chat_avatar_paths = {"kasumi": "old.png"}
        self._storage_dir = Path(storage_dir)
        self.refresh_count = 0

    def _avatar_storage_dir(self):
        return self._storage_dir

    @staticmethod
    def _safe_avatar_name(character, ext):
        return f"{character}{ext}"

    def _refresh_avatar_views(self):
        self.refresh_count += 1


class ChatAvatarSaveSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_new_avatar_remains_active_for_session_when_config_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(b"avatar")
            harness = _AvatarHarness(Path(tmp) / "avatars")

            with (
                patch("chat_window.chat_window.QFileDialog.getOpenFileName", return_value=(str(source), "")),
                patch("chat_window.chat_window.QMessageBox.warning") as warning,
            ):
                result = harness._set_character_avatar("kasumi")

            self.assertIs(result, False)
            self.assertTrue(harness._chat_avatar_paths["kasumi"].endswith("kasumi.png"))
            self.assertEqual(1, harness.refresh_count)
            self.assertTrue(warning.called)

    def test_reset_avatar_remains_active_for_session_when_config_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness = _AvatarHarness(tmp)

            with patch("chat_window.chat_window.QMessageBox.warning") as warning:
                result = harness._reset_character_avatar("kasumi")

            self.assertIs(result, False)
            self.assertNotIn("kasumi", harness._chat_avatar_paths)
            self.assertEqual(1, harness.refresh_count)
            self.assertTrue(warning.called)


if __name__ == "__main__":
    unittest.main()
