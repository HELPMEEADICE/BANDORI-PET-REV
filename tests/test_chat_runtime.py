import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QLockFile

import chat_runtime


class ChatRuntimeLockTests(unittest.TestCase):
    def test_chat_lock_path_uses_ipc_server_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("chat_runtime.app_runtime_dir", return_value=Path(temp_dir)),
                patch("chat_runtime.ipc_server_name", return_value="Bandori Pet/Test"),
            ):
                path = chat_runtime.chat_lock_path()

        self.assertEqual("Bandori_Pet_Test-chat.lock", path.name)

    def test_chat_window_is_active_when_lock_is_held(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("chat_runtime.app_runtime_dir", return_value=Path(temp_dir)),
                patch("chat_runtime.ipc_server_name", return_value="BandoriPet-test"),
            ):
                lock = QLockFile(str(chat_runtime.chat_lock_path()))
                self.assertTrue(lock.tryLock(0))
                try:
                    self.assertTrue(chat_runtime.chat_window_is_active())
                finally:
                    lock.unlock()
                self.assertFalse(chat_runtime.chat_window_is_active())


if __name__ == "__main__":
    unittest.main()
