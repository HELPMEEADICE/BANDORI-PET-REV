from PySide6.QtGui import QSurfaceFormat

import live2d_widget_base
from live2d_widget_base import Live2DWidgetBase


class _VSyncHarness:
    def __init__(self, *, initialized: bool):
        self._initialized_gl = initialized
        self._vsync = True
        self._static_render = False
        self.make_current_calls = 0
        self.timer_update_calls = 0
        self.repaint_calls = 0

    def _safe_make_current(self):
        self.make_current_calls += 1

    def _update_render_timer(self):
        self.timer_update_calls += 1

    def update(self):
        self.repaint_calls += 1


def test_default_surface_format_uses_configured_vsync():
    original = QSurfaceFormat(QSurfaceFormat.defaultFormat())
    try:
        Live2DWidgetBase.configure_default_surface_format(False)
        assert QSurfaceFormat.defaultFormat().swapInterval() == 0

        Live2DWidgetBase.configure_default_surface_format(True)
        assert QSurfaceFormat.defaultFormat().swapInterval() == 1
    finally:
        QSurfaceFormat.setDefaultFormat(original)


def test_unspecified_vsync_preserves_existing_surface_setting():
    original = QSurfaceFormat(QSurfaceFormat.defaultFormat())
    try:
        Live2DWidgetBase.configure_default_surface_format(False)
        Live2DWidgetBase.configure_default_surface_format()
        assert QSurfaceFormat.defaultFormat().swapInterval() == 0
    finally:
        QSurfaceFormat.setDefaultFormat(original)


def test_vsync_selected_before_gl_initialization_is_retained(monkeypatch):
    harness = _VSyncHarness(initialized=False)
    apply_calls = []
    monkeypatch.setattr(
        live2d_widget_base,
        "_apply_windows_swap_interval",
        lambda enabled: apply_calls.append(enabled),
    )

    Live2DWidgetBase.set_vsync(harness, False)

    assert harness._vsync is False
    assert apply_calls == []
    assert harness.make_current_calls == 0


def test_windows_runtime_vsync_switch_uses_current_context(monkeypatch):
    harness = _VSyncHarness(initialized=True)
    apply_calls = []
    monkeypatch.setattr(live2d_widget_base.os, "name", "nt")
    monkeypatch.setattr(
        live2d_widget_base,
        "_apply_windows_swap_interval",
        lambda enabled: apply_calls.append(enabled) or True,
    )

    Live2DWidgetBase.set_vsync(harness, False)

    assert harness._vsync is False
    assert harness.make_current_calls == 1
    assert apply_calls == [False]
    assert harness.timer_update_calls == 1
    assert harness.repaint_calls == 1
