from types import SimpleNamespace

import live2d_widget_base
from live2d_widget_base import Live2DWidgetBase


class _FakeGL:
    GL_FRAMEBUFFER = 1
    GL_BLEND = 2
    GL_FUNC_ADD = 3
    GL_COLOR_BUFFER_BIT = 4
    GL_STENCIL_BUFFER_BIT = 8
    GL_DEPTH_TEST = 16

    def __getattr__(self, name):
        if name.startswith("gl"):
            return lambda *_args, **_kwargs: None
        raise AttributeError(name)


class _FakeTimer:
    def __init__(self):
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1


class _DrawSequenceModel:
    def __init__(self, outcomes):
        self._outcomes = iter(outcomes)
        self.draw_calls = 0

    def Draw(self):
        self.draw_calls += 1
        outcome = next(self._outcomes)
        if isinstance(outcome, Exception):
            raise outcome


class _PaintHarness:
    def __init__(self, outcomes):
        self._render_failure_suspended = False
        self._consecutive_draw_failures = 0
        self._last_draw_failure_log_at = 0.0
        self._static_render = False
        self._static_render_done = False
        self._live2d = object()
        self._model = _DrawSequenceModel(outcomes)
        self._cache_w = 100
        self._cache_h = 100
        self._system_scale = 1.0
        self._clear_color = (0.0, 0.0, 0.0, 0.0)
        self._ssaa_fbo = None
        self._render_timer = _FakeTimer()
        self._perf_probe = SimpleNamespace(enabled=False, now=lambda: 0.0)

    def _track_current_head_target(self):
        pass

    def defaultFramebufferObject(self):
        return 0

    def _render_ssaa_scale(self):
        return 1

    def _apply_lip_sync(self):
        pass


def _paint(harness):
    Live2DWidgetBase.paintGL(harness)


def test_three_consecutive_draw_failures_suspend_rendering(monkeypatch, capsys):
    monkeypatch.setattr(live2d_widget_base, "gl", _FakeGL())
    monkeypatch.setattr(live2d_widget_base.time, "monotonic", lambda: 10.0)
    harness = _PaintHarness([RuntimeError("broken renderer")] * 3)

    _paint(harness)
    _paint(harness)
    _paint(harness)
    _paint(harness)

    assert harness._render_failure_suspended is True
    assert harness._consecutive_draw_failures == 3
    assert harness._render_timer.stop_calls == 1
    assert harness._model.draw_calls == 3
    stderr = capsys.readouterr().err
    assert stderr.count("Live2D draw failed: broken renderer") == 1
    assert stderr.count("Live2D rendering suspended after 3 consecutive draw failures") == 1


def test_successful_draw_resets_failure_count_and_failure_logs_are_throttled(monkeypatch, capsys):
    monkeypatch.setattr(live2d_widget_base, "gl", _FakeGL())
    monkeypatch.setattr(live2d_widget_base.time, "monotonic", lambda: 10.0)
    harness = _PaintHarness([
        RuntimeError("intermittent renderer"),
        None,
        RuntimeError("intermittent renderer"),
        None,
        RuntimeError("intermittent renderer"),
        None,
    ])

    for _ in range(6):
        _paint(harness)

    assert harness._render_failure_suspended is False
    assert harness._consecutive_draw_failures == 0
    assert harness._render_timer.stop_calls == 0
    assert capsys.readouterr().err.count("Live2D draw failed: intermittent renderer") == 1


def test_render_failure_state_can_be_reset_after_suspension():
    harness = _PaintHarness([])
    harness._render_failure_suspended = True
    harness._consecutive_draw_failures = 3

    Live2DWidgetBase._reset_render_failure_state(harness)

    assert harness._render_failure_suspended is False
    assert harness._consecutive_draw_failures == 0
