import os
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication, QWidget

import live2d_widget_base
import live2d_widget_moc3
from live2d_widget_base import DIRECT_RENDER_PIPELINE, Live2DWidgetBase
from live2d_widget_moc3 import Live2DSSAAFramebuffer
from pixel_pet_widget import PixelPetWidget
from tests.test_live2d_draw_failure_circuit_breaker import _FakeGL, _PaintHarness


@pytest.mark.parametrize("ssaa", [1, 2])
@pytest.mark.parametrize("crop", [False, True])
def test_live2d_scales_after_rendering_in_direct_ssaa_and_crop_paths(monkeypatch, ssaa, crop):
    monkeypatch.setattr(live2d_widget_base, "gl", _FakeGL())
    harness = _PaintHarness([None])
    harness._music_vertical_scale = 0.75
    harness._render_ssaa_scale = lambda: ssaa
    harness._render_pipeline = DIRECT_RENDER_PIPELINE
    if crop:
        harness._render_pipeline = SimpleNamespace(supports_leg_crop=True)
        harness._moc3_leg_crop_enabled = True
        harness._moc3_visible_height = 500
    fbo = SimpleNamespace(bind=Mock(return_value=True), release=Mock(), blit_to_default=Mock(return_value=True))
    harness._ssaa_fbo = fbo

    Live2DWidgetBase.paintGL(harness)

    fbo.bind.assert_called_once_with(100 * ssaa, (160 if crop else 100) * ssaa)
    assert fbo.blit_to_default.call_args.args[1:3] == (100, 100)
    assert fbo.blit_to_default.call_args.kwargs["vertical_scale"] == 0.75
    assert fbo.blit_to_default.call_args.kwargs["source_crop_height"] == (100 * ssaa if crop else None)
    assert harness._music_rendered_scale == 0.75
    assert harness._model.draw_calls == 1


@pytest.mark.parametrize("scale", [0.75, 1.12])
def test_framebuffer_scales_height_only_and_keeps_bottom_fixed(monkeypatch, scale):
    fake_gl = SimpleNamespace(
        GL_READ_FRAMEBUFFER=1, GL_DRAW_FRAMEBUFFER=2, GL_FRAMEBUFFER=3,
        GL_COLOR_BUFFER_BIT=4, GL_STENCIL_BUFFER_BIT=8, GL_LINEAR=5,
        glBindFramebuffer=Mock(), glViewport=Mock(), glClearColor=Mock(),
        glClear=Mock(), glBlitFramebuffer=Mock(),
    )
    monkeypatch.setattr(live2d_widget_moc3, "gl", fake_gl)
    fbo = Live2DSSAAFramebuffer()
    fbo._fbo = SimpleNamespace(handle=lambda: 11)
    fbo._size = (800, 1600)

    assert fbo.blit_to_default(7, 400, 500, (0, 0, 0, 0), source_crop_height=1000, vertical_scale=scale)

    assert fake_gl.glBlitFramebuffer.call_args.args[:8] == (0, 600, 800, 1600, 0, 0, 400, round(500 * scale))


def test_live2d_hit_areas_follow_vertical_deformation():
    custom = SimpleNamespace(hit_test_name=Mock(return_value="head"), bounds_for=lambda _name: (20, 80, 10, 50))
    harness = SimpleNamespace(_cache_h=100, _music_rendered_scale=0.75, _custom_hit_areas=custom)
    assert Live2DWidgetBase.hit_area_bounds(harness, "head") == (20, 80, 32.5, 62.5)
    assert Live2DWidgetBase._custom_hit_area_name_at(harness, 50, 40) == "head"
    custom.hit_test_name.assert_called_once_with(50, 20)
    assert Live2DWidgetBase._music_unscale_y(harness, 100) == 100


def test_pixel_render_hit_mask_and_input_region_share_the_same_vertical_scale():
    app = QApplication.instance() or QApplication([])
    widget = PixelPetWidget()
    widget._drag_locked = True
    widget._sheet_image = QImage(20, 40, QImage.Format.Format_RGBA8888)
    widget._sheet_image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(widget._sheet_image)
    painter.fillRect(4, 4, 12, 36, QColor("red"))
    painter.end()
    widget._frames = {"idle": {"row": 0}}
    widget._frame_w, widget._frame_h = 20, 40
    widget.resize(20, 40)
    widget.show()
    app.processEvents()
    geometry = widget.geometry()

    def visible_bounds():
        image = QImage(widget.size(), QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        widget.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        pixels = [(x, y) for x in range(20) for y in range(40) if image.pixelColor(x, y).alpha() > 8]
        return min(x for x, _ in pixels), max(x for x, _ in pixels), min(y for _, y in pixels), max(y for _, y in pixels)

    original = visible_bounds()
    widget.set_music_vertical_scale(0.75)
    compressed = visible_bounds()
    assert compressed == (original[0], original[1], 13, 39)
    assert widget.is_sprite_opaque_at_local(10, 14)
    assert not widget.is_sprite_opaque_at_local(10, 8)
    region = widget.input_region()
    assert region.contains(QPoint(10, 14))
    assert not region.contains(QPoint(10, 8))
    widget.set_music_vertical_scale(1.12)
    stretched = visible_bounds()
    assert stretched[0:2] == original[0:2]
    assert stretched[2] < original[2]
    assert stretched[3] == original[3]
    widget.set_music_vertical_scale(1.0)
    assert visible_bounds() == original
    assert widget.geometry() == geometry
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
