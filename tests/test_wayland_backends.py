import unittest

from wayland.backends import (
    GenericWaylandBackend,
    GnomeWaylandBackend,
    LayerShellWaylandBackend,
    LegacySurfaceBackend,
    select_surface_backend,
)


class WaylandBackendTest(unittest.TestCase):
    def test_backend_selection_matrix(self):
        self.assertIsInstance(
            select_surface_backend("windows", "legacy"),
            LegacySurfaceBackend,
        )
        for compositor in ("plasma", "hyprland"):
            self.assertIsInstance(
                select_surface_backend("wayland", compositor),
                LayerShellWaylandBackend,
            )
        self.assertIsInstance(
            select_surface_backend("wayland", "gnome"),
            GnomeWaylandBackend,
        )
        self.assertIsInstance(
            select_surface_backend("wayland", "sway"),
            GenericWaylandBackend,
        )

    def test_layer_shell_capabilities_fail_closed_without_bridge(self):
        backend = LayerShellWaylandBackend()
        degraded = backend.capabilities(
            layer_shell_available=False,
            global_pointer_available=True,
        )
        complete = backend.capabilities(
            layer_shell_available=True,
            global_pointer_available=True,
        )

        self.assertTrue(degraded.input_region)
        self.assertFalse(degraded.absolute_placement)
        self.assertTrue(degraded.global_pointer)
        self.assertFalse(degraded.overlay_above_fullscreen)
        self.assertTrue(complete.absolute_placement)
        self.assertTrue(complete.overlay_above_fullscreen)
        self.assertTrue(complete.multi_output)

    def test_gnome_geometry_capabilities_follow_companion_lifetime(self):
        backend = GnomeWaylandBackend()
        disconnected = backend.capabilities(
            companion_connected=False,
            global_pointer_available=True,
        )
        connected = backend.capabilities(
            companion_connected=True,
            global_pointer_available=True,
        )

        self.assertFalse(disconnected.absolute_placement)
        self.assertFalse(disconnected.global_pointer)
        self.assertTrue(connected.absolute_placement)
        self.assertTrue(connected.global_pointer)


if __name__ == "__main__":
    unittest.main()
