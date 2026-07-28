import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget

from wayland.companion_service import WaylandCompanionService
from wayland.backends import LayerShellWaylandBackend
from wayland.controller import DesktopSurfaceController
from wayland.types import StackMode, SurfacePlacement, SurfaceRole


class WaylandControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legacy_controller_preserves_move_semantics(self):
        widget = QWidget()
        widget.resize(120, 80)
        controller = DesktopSurfaceController()
        placement = SurfacePlacement("", 25, 35, 120, 80)

        controller.register_surface(widget, SurfaceRole.PET, placement, StackMode.TOP)
        controller.move_by(widget, 10, -5)

        self.assertEqual(QPoint(35, 30), widget.pos())
        self.assertEqual((35, 30), (
            controller.placement(widget).x,
            controller.placement(widget).y,
        ))
        controller.close()
        widget.close()

    def test_companion_rejects_wrong_session_token(self):
        service = WaylandCompanionService()
        samples = []
        service.PointerReceived.connect(samples.append)

        self.assertFalse(service.PushPointer(10.0, 20.0, 0, 1, "wrong"))
        self.assertTrue(service.PushPointer(10.0, 20.0, 0, 1, service.token))
        self.assertEqual(1, len(samples))
        self.assertEqual((10.0, 20.0), (samples[0].x, samples[0].y))
        self.assertLess(
            abs(time.monotonic_ns() // 1000 - samples[0].monotonic_us),
            1_000_000,
        )
        service.close()

    def test_companion_geometry_and_disconnect_are_token_scoped(self):
        service = WaylandCompanionService()
        placements = []
        disconnected = []
        service.GeometryReceived.connect(
            lambda surface_id, placement: placements.append(
                (surface_id, placement)
            )
        )
        service.CompanionDisconnected.connect(lambda: disconnected.append(True))

        self.assertFalse(
            service.GeometryApplied("surface", "DP-1", 1, 2, 30, 40, "wrong")
        )
        self.assertTrue(
            service.GeometryApplied(
                "surface",
                "DP-1",
                1,
                2,
                30,
                40,
                service.token,
            )
        )
        self.assertFalse(service.CompanionGone("wrong"))
        self.assertTrue(service.CompanionGone(service.token))

        self.assertEqual(1, len(placements))
        self.assertEqual("DP-1", placements[0][1].output_id)
        self.assertEqual([True], disconnected)
        service.close()

    def test_surface_marker_binds_pid_token_surface_and_role(self):
        service = WaylandCompanionService()
        marker = service.marker("abc123", SurfaceRole.AI_PANEL)

        self.assertIn(f"p{os.getpid()}", marker)
        self.assertIn(service.token, marker)
        self.assertIn("abc123", marker)
        self.assertIn("ai_panel", marker)
        service.close()

    def test_stale_pointer_samples_are_not_returned(self):
        controller = DesktopSurfaceController()
        from wayland.types import PointerSample

        controller._latest_pointer = PointerSample(
            10,
            20,
            0,
            time.monotonic_ns() // 1000 - 300_000,
            "test",
        )
        self.assertIsNone(controller.latest_pointer(max_age_ms=250))
        controller.close()

    def test_cross_output_placement_rebinds_layer_surface(self):
        class FakeWindowHandle:
            def __init__(self):
                self.screen = None
                self.mask = None

            def setScreen(self, screen):
                self.screen = screen

            def setMask(self, region):
                self.mask = region

        class FakeScreen:
            def geometry(self):
                return QRect(1000, 0, 1000, 800)

        class FakeBridge:
            status = SimpleNamespace(available=True, reason="")

            def __init__(self):
                self.rebinds = 0

            def set_margins(self, *_args):
                pass

            def set_size(self, *_args):
                pass

            def rebind_output(self, _window):
                self.rebinds += 1

        widget = QWidget()
        controller = DesktopSurfaceController()
        controller.register_surface(
            widget,
            SurfaceRole.PET,
            SurfacePlacement("A", 10, 20, 120, 80),
        )
        fake_window = FakeWindowHandle()
        fake_bridge = FakeBridge()
        controller.native_wayland = True
        controller.compositor = "plasma"
        controller.backend = LayerShellWaylandBackend()
        controller._bridge = fake_bridge
        controller._qwindow = lambda *_args: fake_window

        with patch("wayland.controller._screen_for_id", return_value=FakeScreen()):
            controller.set_placement(
                widget,
                SurfacePlacement("B", 1100, 30, 120, 80),
            )

        self.assertEqual(1, fake_bridge.rebinds)
        self.assertIsNotNone(fake_window.screen)
        controller.close()
        widget.close()


if __name__ == "__main__":
    unittest.main()
