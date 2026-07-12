import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import settings_window.widgets as widgets
from settings_window.widgets import Live2DPreviewRenderWidget
from live2d_widget_moc3 import MOC3_RENDER_PIPELINE


class _ScaledPreviewWidget(Live2DPreviewRenderWidget):
    def devicePixelRatioF(self):
        return 1.5


class _DpiPreviewWidget(Live2DPreviewRenderWidget):
    def __init__(self, ratio):
        self._test_ratio = ratio
        super().__init__()

    def devicePixelRatioF(self):
        return self._test_ratio


class _FakeGL:
    GL_DEPTH_TEST = 0
    GL_DITHER = 0
    GL_FRAMEBUFFER = 0
    GL_BLEND = 0
    GL_FUNC_ADD = 0
    GL_COLOR_BUFFER_BIT = 0
    GL_STENCIL_BUFFER_BIT = 0

    def __init__(self):
        self.viewports = []

    def glViewport(self, x, y, width, height):
        self.viewports.append((x, y, width, height))


class _FakeModel:
    def __init__(self, fake_gl=None, renderer_format=""):
        self._gl = fake_gl
        self.renderer_format = renderer_format
        self.resizes = []
        self.renderer_resizes = []

    def Resize(self, width, height):
        self.resizes.append((width, height))
        if self._gl is not None:
            self._gl.glViewport(0, 0, width, height)

    def ResizeRenderer(self, width, height):
        self.renderer_resizes.append((width, height))


class Live2DPreviewDpiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_resize_gl_uses_physical_size_for_high_dpi_preview(self):
        widget = _ScaledPreviewWidget()
        fake_gl = _FakeGL()
        fake_model = _FakeModel(fake_gl)
        original_gl = widgets.gl
        widgets.gl = fake_gl
        widget._model = fake_model
        try:
            widget.resizeGL(300, 360)
        finally:
            widgets.gl = original_gl

        self.assertEqual((0, 0, 450, 540), fake_gl.viewports[-1])
        self.assertEqual([(450, 540)], fake_model.resizes)

    def test_moc3_preview_resizes_logical_and_ssaa_targets_only_on_size_change(self):
        for ratio, logical_size, ssaa_size in (
            (1.0, (200, 300), (400, 600)),
            (1.5, (300, 450), (600, 900)),
            (2.0, (400, 600), (800, 1200)),
        ):
            with self.subTest(ratio=ratio):
                widget = _DpiPreviewWidget(ratio)
                fake_gl = _FakeGL()
                fake_model = _FakeModel(fake_gl, renderer_format="moc3")
                original_gl = widgets.gl
                widgets.gl = fake_gl
                widget._model = fake_model
                widget._render_pipeline = MOC3_RENDER_PIPELINE
                try:
                    widget._sync_render_size(200, 300, force=True)
                    widget._sync_render_size(200, 300)
                finally:
                    widgets.gl = original_gl

                self.assertEqual([logical_size], fake_model.resizes)
                self.assertEqual([ssaa_size], fake_model.renderer_resizes)

    def test_moc3_preview_quality_change_restores_native_target_size(self):
        widget = _DpiPreviewWidget(1.5)
        fake_model = _FakeModel(renderer_format="moc3")
        widget._model = fake_model
        widget._render_pipeline = MOC3_RENDER_PIPELINE
        widget._render_w, widget._render_h = 300, 450

        widget._sync_renderer_target_size()
        widget._quality_profile = "performance"
        widget._sync_renderer_target_size()

        self.assertEqual([(600, 900), (300, 450)], fake_model.renderer_resizes)


if __name__ == "__main__":
    unittest.main()
