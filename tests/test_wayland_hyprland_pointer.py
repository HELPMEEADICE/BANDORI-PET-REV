import unittest
from pathlib import Path

from wayland.pointer import hyprland_socket_path


class HyprlandPointerTest(unittest.TestCase):
    def test_modern_runtime_socket_path_is_preferred(self):
        path = hyprland_socket_path(
            {
                "HYPRLAND_INSTANCE_SIGNATURE": "instance",
                "XDG_RUNTIME_DIR": "/run/user/1000",
            }
        )
        self.assertEqual(
            Path("/run/user/1000/hypr/instance/.socket.sock"),
            path,
        )

    def test_missing_signature_disables_provider(self):
        self.assertIsNone(hyprland_socket_path({"XDG_RUNTIME_DIR": "/run/user/1000"}))


if __name__ == "__main__":
    unittest.main()
