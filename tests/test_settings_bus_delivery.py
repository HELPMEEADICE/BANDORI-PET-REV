import unittest
from unittest.mock import patch

import settings_bus


class SettingsBusDeliveryTest(unittest.TestCase):
    def test_publish_settings_returns_transport_result(self):
        with patch("settings_bus.send_ipc_message", return_value=False):
            self.assertFalse(settings_bus.publish_settings({"fps": 60}))
        with patch("settings_bus.send_ipc_message", return_value=True):
            self.assertTrue(settings_bus.publish_settings({"fps": 60}))

    def test_publish_settings_rejects_non_dict(self):
        self.assertFalse(settings_bus.publish_settings([]))


if __name__ == "__main__":
    unittest.main()
