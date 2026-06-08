import subprocess
import unittest
from unittest.mock import patch

import startup_manager


class StartupManagerTests(unittest.TestCase):
    def test_source_startup_command_uses_pythonw_and_main_script(self):
        base_dir = r"C:\repo with spaces\BandoriPet"
        python = r"C:\Python311\python.exe"
        pythonw = r"C:\Python311\pythonw.exe"

        with (
            patch.object(startup_manager.sys, "frozen", False, create=True),
            patch.object(startup_manager.sys, "executable", python),
            patch.object(startup_manager.sys, "platform", "win32"),
            patch.object(startup_manager, "app_base_dir", return_value=base_dir),
            patch.object(startup_manager.os.path, "exists", return_value=True),
        ):
            command = startup_manager.startup_command()

        self.assertEqual(
            command,
            subprocess.list2cmdline([pythonw, base_dir + r"\main.py"]),
        )

    def test_stale_command_is_not_reported_as_enabled(self):
        with (
            patch.object(
                startup_manager,
                "current_startup_command",
                return_value=r"C:\old\BandoriPet.exe",
            ),
            patch.object(
                startup_manager,
                "startup_command",
                return_value=r"C:\repo\pythonw.exe C:\repo\main.py",
            ),
        ):
            self.assertFalse(startup_manager.is_startup_enabled())

    def test_repair_rewrites_an_existing_stale_command(self):
        with (
            patch.object(
                startup_manager,
                "current_startup_command",
                return_value=r"C:\old\BandoriPet.exe",
            ),
            patch.object(
                startup_manager,
                "startup_command",
                return_value=r"C:\repo\pythonw.exe C:\repo\main.py",
            ),
            patch.object(startup_manager, "set_startup_enabled") as set_enabled,
        ):
            repaired = startup_manager.repair_startup_command()

        self.assertTrue(repaired)
        set_enabled.assert_called_once_with(True)

    def test_repair_does_not_enable_a_missing_startup_entry(self):
        with (
            patch.object(startup_manager, "current_startup_command", return_value=""),
            patch.object(startup_manager, "set_startup_enabled") as set_enabled,
        ):
            repaired = startup_manager.repair_startup_command()

        self.assertFalse(repaired)
        set_enabled.assert_not_called()


if __name__ == "__main__":
    unittest.main()
