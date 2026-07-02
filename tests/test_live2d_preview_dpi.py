import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import settings_window.widgets as widgets
from settings_window.widgets import Live2DPreviewRenderWidget


class _ScaledPreviewWidget(Live2DPreviewRenderWidget):
    def devicePixelRatioF(self):
        return 1.5


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
    def __init__(self, fake_gl=None):
        self._gl = fake_gl
        self.resizes = []

    def Resize(self, width, height):
        self.resizes.append((width, height))
        if self._gl is not None:
            self._gl.glViewport(0, 0, width, height)


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


if __name__ == "__main__":
    unittest.main()
