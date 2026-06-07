import unittest
from unittest.mock import patch

import asr_manager


class ASRPythonDetectionTest(unittest.TestCase):
    def test_windows_store_alias_is_rejected(self):
        alias = r"C:\Users\demo\AppData\Local\Microsoft\WindowsApps\python.exe"
        with (
            patch.object(asr_manager.sys, "platform", "win32"),
            patch.dict(
                asr_manager.os.environ,
                {"LOCALAPPDATA": r"C:\Users\demo\AppData\Local"},
                clear=False,
            ),
        ):
            self.assertTrue(asr_manager._is_windows_store_python_alias(alias))

    def test_venv_command_skips_broken_python_candidate(self):
        candidates = [
            [r"C:\broken\python.exe"],
            [r"C:\Python311\python.exe"],
        ]
        with (
            patch.object(asr_manager, "_venv_python_candidates", return_value=candidates),
            patch.object(
                asr_manager,
                "_python_can_create_venv",
                side_effect=[False, True],
            ),
            patch.object(
                asr_manager,
                "ASR_LOCAL_SERVER_DIR",
                asr_manager.Path(r"C:\BandoriPet\.runtime\asr-server"),
            ),
        ):
            command = asr_manager._venv_create_command()

        self.assertEqual(command[:4], [r"C:\Python311\python.exe", "-m", "venv", r"C:\BandoriPet\.runtime\asr-server\.venv"])

    def test_venv_command_reports_missing_real_python(self):
        with (
            patch.object(asr_manager, "_venv_python_candidates", return_value=[]),
            self.assertRaisesRegex(RuntimeError, "WindowsApps"),
        ):
            asr_manager._venv_create_command()


if __name__ == "__main__":
    unittest.main()
