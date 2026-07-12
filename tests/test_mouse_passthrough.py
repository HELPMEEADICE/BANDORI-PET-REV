import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect

import live2d_widget_base
from live2d_widget import Live2DWidget
from pet_window import PetWindow


class _PerfProbe:
    @staticmethod
    def now():
        return 0.0

    @staticmethod
    def add(_name, _elapsed):
        pass


class _Clock:
    def __init__(self):
        self.now = 0

    def elapsed(self):
        return self.now


class PassthroughHarness:
    _passthrough_sample_pos = PetWindow._passthrough_sample_pos
    _should_passthrough_at = PetWindow._should_passthrough_at
    _set_mouse_passthrough = PetWindow._set_mouse_passthrough

    def __init__(self):
        self._mouse_passthrough_enabled = False
        self._mouse_passthrough_last_hit_at = 0.0
        self._mouse_passthrough_last_hit_pos = None
        self.hit = False
        self.interacting = False

    @staticmethod
    def _mouse_passthrough_supported():
        return True

    def isVisible(self):
        return True

    def geometry(self):
        return QRect(0, 0, 100, 100)

    def width(self):
        return 100

    def height(self):
        return 100

    def _mouse_interaction_in_progress(self):
        return self.interacting

    def _is_pet_opaque_at_global(self, _global_pos):
        return self.hit


class HitHarness:
    _is_model_hit_at = Live2DWidget._is_model_hit_at

    def __init__(self):
        self._model = object()
        self._perf_probe = _PerfProbe()
        self._hit_clock = _Clock()
        self._last_confirmed_hit_ms = -1000
        self._last_confirmed_hit_pos = None
        self.hit = False

    def _hit_state_at(self, _x, _y):
        return self.hit


class PixelHitHarness:
    _hit_state_at = Live2DWidget._hit_state_at

    def __init__(self, alpha):
        self._model = type("Model", (), {"HitTest": lambda *_args: "hit"})()
        self._hit_alpha_threshold = 8
        self.alpha = alpha

    def _read_alpha_at(self, _x, _y):
        return self.alpha


class AlphaReadHarness:
    _read_alpha_at = Live2DWidget._read_alpha_at

    def __init__(self):
        self._initialized_gl = True
        self._model = object()
        self._cache_w = 100
        self._cache_h = 80
        self._system_scale = 1.5
        self._perf_probe = _PerfProbe()

    @staticmethod
    def _safe_make_current():
        pass

    @staticmethod
    def defaultFramebufferObject():
        return 7


class MousePassthroughTest(unittest.TestCase):
    def test_model_hit_keeps_window_interactive(self):
        harness = PassthroughHarness()
        harness.hit = True

        with patch("pet_window.time.monotonic", return_value=10.0):
            self.assertFalse(harness._should_passthrough_at(QPoint(50, 50)))

    def test_transparent_pixel_passes_through_without_geometry_fallback(self):
        harness = PassthroughHarness()
        harness.hit = False

        with patch("pet_window.time.monotonic", return_value=10.0):
            self.assertTrue(harness._should_passthrough_at(QPoint(50, 50)))

    def test_pressed_mouse_button_keeps_window_interactive(self):
        harness = PassthroughHarness()
        harness.interacting = True

        self.assertFalse(harness._should_passthrough_at(QPoint(50, 50)))

    def test_recent_hit_survives_transient_alpha_miss(self):
        harness = PassthroughHarness()
        cursor = QPoint(50, 50)
        harness.hit = True
        with patch("pet_window.time.monotonic", return_value=10.0):
            self.assertFalse(harness._should_passthrough_at(cursor))

        harness.hit = False
        with patch("pet_window.time.monotonic", return_value=10.04):
            self.assertFalse(harness._should_passthrough_at(cursor))
        with patch("pet_window.time.monotonic", return_value=10.09):
            self.assertTrue(harness._should_passthrough_at(cursor))

    def test_moving_off_model_does_not_extend_grace(self):
        harness = PassthroughHarness()
        harness.hit = True
        with patch("pet_window.time.monotonic", return_value=10.0):
            self.assertFalse(harness._should_passthrough_at(QPoint(50, 50)))

        harness.hit = False
        with patch("pet_window.time.monotonic", return_value=10.04):
            self.assertTrue(harness._should_passthrough_at(QPoint(70, 50)))

    def test_macos_native_state_overrides_stale_python_cache(self):
        harness = PassthroughHarness()

        class MacPatch:
            native_enabled = True
            set_calls = []

            @classmethod
            def get_ignores_mouse_events(cls, _widget):
                return cls.native_enabled

            @classmethod
            def set_ignores_mouse_events(cls, _widget, enabled):
                cls.set_calls.append(enabled)
                cls.native_enabled = enabled
                return True

        with (
            patch("pet_window.sys.platform", "darwin"),
            patch("pet_window.macos_patch", MacPatch),
        ):
            harness._set_mouse_passthrough(False)

        self.assertEqual([False], MacPatch.set_calls)
        self.assertFalse(harness._mouse_passthrough_enabled)

    def test_linux_xcb_supports_mouse_passthrough(self):
        class App:
            @staticmethod
            def platformName():
                return "xcb"

        with (
            patch("pet_window.os.name", "posix"),
            patch("pet_window.sys.platform", "linux"),
            patch("pet_window.QGuiApplication", App),
            patch("pet_window._xfixes", object(), create=True),
            patch("pet_window._x11", object()),
        ):
            self.assertTrue(PetWindow._mouse_passthrough_supported())

    def test_linux_x11_passthrough_uses_input_shape(self):
        harness = PassthroughHarness()
        calls = []

        class App:
            @staticmethod
            def platformName():
                return "xcb"

        def set_shape(_window, enabled):
            calls.append(enabled)
            return True

        with (
            patch("pet_window.os.name", "posix"),
            patch("pet_window.sys.platform", "linux"),
            patch("pet_window.QGuiApplication", App),
            patch("pet_window._set_x11_input_passthrough", set_shape, create=True),
        ):
            harness._set_mouse_passthrough(True)
            harness._set_mouse_passthrough(False)

        self.assertEqual([True, False], calls)
        self.assertFalse(harness._mouse_passthrough_enabled)

    def test_live2d_hit_survives_one_transient_miss(self):
        harness = HitHarness()
        harness.hit = True
        harness._hit_clock.now = 1000
        self.assertTrue(harness._is_model_hit_at(50, 50))

        harness.hit = False
        harness._hit_clock.now = 1050
        self.assertTrue(harness._is_model_hit_at(50, 50))
        harness._hit_clock.now = 1121
        self.assertFalse(harness._is_model_hit_at(50, 50))

    def test_transparent_pixel_does_not_use_live2d_geometry_fallback(self):
        self.assertFalse(PixelHitHarness(alpha=0)._hit_state_at(50, 50))
        self.assertTrue(PixelHitHarness(alpha=9)._hit_state_at(50, 50))

    def test_alpha_hit_reads_exactly_one_physical_pixel(self):
        calls = []

        class FakeGL:
            GL_FRAMEBUFFER = 1
            GL_RGBA = 2
            GL_UNSIGNED_BYTE = 3

            @staticmethod
            def glBindFramebuffer(target, framebuffer):
                calls.append(("bind", target, framebuffer))

            @staticmethod
            def glReadPixels(x, y, width, height, format_, type_, pixel):
                calls.append(("read", x, y, width, height, format_, type_))
                pixel[3] = 9

        harness = AlphaReadHarness()
        with patch.object(live2d_widget_base, "gl", FakeGL):
            alpha = harness._read_alpha_at(10, 20)

        self.assertEqual(9, alpha)
        self.assertEqual(
            [
                ("bind", FakeGL.GL_FRAMEBUFFER, 7),
                ("read", 15, 88, 1, 1, FakeGL.GL_RGBA, FakeGL.GL_UNSIGNED_BYTE),
            ],
            calls,
        )


if __name__ == "__main__":
    unittest.main()
