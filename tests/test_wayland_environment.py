import unittest

from wayland.environment import (
    WaylandStartupError,
    configure_native_wayland,
    detect_compositor,
    is_wayland_session,
    verify_native_wayland_qpa,
)


class _FakeApplication:
    def __init__(self, platform_name):
        self._platform_name = platform_name

    def platformName(self):
        return self._platform_name


class WaylandEnvironmentTest(unittest.TestCase):
    def test_wayland_session_detection_is_linux_only(self):
        env = {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
        self.assertTrue(is_wayland_session(env, "linux"))
        self.assertFalse(is_wayland_session(env, "win32"))

    def test_native_wayland_is_selected_without_qpa_override(self):
        env = {"XDG_SESSION_TYPE": "wayland"}
        self.assertTrue(configure_native_wayland(env, "linux"))
        self.assertEqual("wayland", env["QT_QPA_PLATFORM"])
        self.assertEqual("PassThrough", env["QT_SCALE_FACTOR_ROUNDING_POLICY"])

    def test_xcb_is_rejected_in_wayland_session(self):
        env = {
            "XDG_SESSION_TYPE": "wayland",
            "QT_QPA_PLATFORM": "xcb",
        }
        with self.assertRaises(WaylandStartupError):
            configure_native_wayland(env, "linux")

    def test_xcb_fallback_chain_is_rejected(self):
        env = {
            "XDG_SESSION_TYPE": "wayland",
            "QT_QPA_PLATFORM": "wayland;xcb",
        }
        with self.assertRaises(WaylandStartupError):
            configure_native_wayland(env, "linux")

    def test_non_wayland_qpa_is_rejected_after_application_start(self):
        import wayland.environment as environment

        original = environment.is_wayland_session
        environment.is_wayland_session = lambda: True
        try:
            with self.assertRaises(WaylandStartupError):
                verify_native_wayland_qpa(_FakeApplication("xcb"))
            self.assertTrue(verify_native_wayland_qpa(_FakeApplication("wayland")))
        finally:
            environment.is_wayland_session = original

    def test_compositor_detection(self):
        self.assertEqual(
            "hyprland",
            detect_compositor({"HYPRLAND_INSTANCE_SIGNATURE": "abc"}),
        )
        self.assertEqual(
            "gnome",
            detect_compositor({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}),
        )
        self.assertEqual(
            "plasma",
            detect_compositor({"XDG_CURRENT_DESKTOP": "KDE"}),
        )
        self.assertEqual("generic", detect_compositor({}))


if __name__ == "__main__":
    unittest.main()
