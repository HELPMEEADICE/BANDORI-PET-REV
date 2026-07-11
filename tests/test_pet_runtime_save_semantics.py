import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from pet_window import PetWindow


class PetRuntimeSaveSemanticsTest(unittest.TestCase):
    def test_save_failure_keeps_session_state_and_warns_only_once(self):
        tray = Mock()
        tray.isVisible.return_value = True
        window = SimpleNamespace(
            _cfg=SimpleNamespace(save=Mock(return_value=False)),
            _runtime_save_failure_reported=False,
            _tray_icon=tray,
        )

        self.assertFalse(PetWindow._persist_runtime_config(window))
        self.assertFalse(PetWindow._persist_runtime_config(window))

        self.assertTrue(window._runtime_save_failure_reported)
        tray.showMessage.assert_called_once()

    def test_successful_save_does_not_warn(self):
        tray = Mock()
        window = SimpleNamespace(
            _cfg=SimpleNamespace(save=Mock(return_value=True)),
            _runtime_save_failure_reported=False,
            _tray_icon=tray,
        )

        self.assertTrue(PetWindow._persist_runtime_config(window))
        tray.showMessage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
