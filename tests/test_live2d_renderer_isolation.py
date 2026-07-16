import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from live2d_lua_adapter_base import LuaLAppModelBase, LuaLive2DRuntimeBase
from live2d_lua_adapter_moc import LuaLive2DModuleMOC
from live2d_lua_adapter_moc3 import LuaLive2DModuleMOC3, _patch_lua_moc3_pet_embed_delta
from live2d_widget import Live2DWidget, render_pipeline_for_model
from live2d_widget_base import DIRECT_RENDER_PIPELINE
from live2d_widget_moc3 import MOC3_RENDER_PIPELINE
import live2d_widget_moc3


def test_releasing_hidden_model_disposes_renderer_and_runtime_for_reuse():
    calls = []
    harness = SimpleNamespace(
        _render_timer=SimpleNamespace(stop=lambda: calls.append("timer")),
        _initialized_gl=True,
        _safe_make_current=lambda: calls.append("context"),
        _dispose_model_renderer=lambda: calls.append("renderer"),
        _live2d=SimpleNamespace(dispose=lambda: calls.append("runtime")),
        _model_path="model.zst::live/model.json",
        _pending_model="pending",
        _custom_hit_areas=SimpleNamespace(clear=lambda: calls.append("hit-areas")),
        _reset_render_failure_state=lambda: calls.append("reset"),
    )

    Live2DWidget.release_model(harness)

    assert harness._model_path == ""
    assert harness._pending_model == ""
    assert calls == ["timer", "context", "renderer", "runtime", "hit-areas", "reset"]


def test_only_cubism2_runtime_installs_platform_manager_override():
    assert LuaLive2DModuleMOC._configure_runtime is not LuaLive2DRuntimeBase._configure_runtime
    assert LuaLive2DModuleMOC3._configure_runtime is LuaLive2DRuntimeBase._configure_runtime


def test_live2d_widget_has_no_redundant_head_tracking_timer():
    source = Path("live2d_widget_base.py").read_text(encoding="utf-8")

    assert "_head_track_timer" not in source
    assert "_poll_head_tracking" not in source
    assert "self._track_current_head_target()" in source


def test_live2d_widget_has_no_temporary_dpi_trace_hooks():
    source = Path("live2d_widget_base.py").read_text(encoding="utf-8")

    assert "_trace_dpi" not in source
    assert "dpi_trace" not in source


def test_render_pipeline_is_selected_once_at_format_boundary():
    moc_model = type("Model", (), {"renderer_format": "moc"})()
    moc3_model = type("Model", (), {"renderer_format": "moc3"})()

    assert render_pipeline_for_model(moc_model) is DIRECT_RENDER_PIPELINE
    assert render_pipeline_for_model(moc3_model) is MOC3_RENDER_PIPELINE
    assert MOC3_RENDER_PIPELINE.ssaa_scale("balanced") == 2
    assert MOC3_RENDER_PIPELINE.ssaa_scale("performance") == 1


def test_moc3_ssaa_fallback_renders_without_advancing_model(monkeypatch):
    calls = []
    fake_gl = SimpleNamespace(
        GL_FRAMEBUFFER=1,
        GL_COLOR_BUFFER_BIT=2,
        GL_STENCIL_BUFFER_BIT=4,
        glBindFramebuffer=lambda *_args: None,
        glViewport=lambda *_args: None,
        glClearColor=lambda *_args: None,
        glClear=lambda *_args: None,
    )
    monkeypatch.setattr(live2d_widget_moc3, "gl", fake_gl)

    model = SimpleNamespace(
        Render=lambda: calls.append("render"),
        Draw=lambda: calls.append("draw"),
    )
    live2d_widget_moc3.Live2DSSAAFramebuffer.draw_direct_to_default(
        model,
        default_fbo=7,
        width=320,
        height=480,
        clear_color=(0.0, 0.0, 0.0, 0.0),
    )

    assert calls == ["render"]


def test_moc3_render_target_size_changes_only_when_needed():
    calls = []
    model = SimpleNamespace(ResizeRenderer=lambda width, height: calls.append((width, height)))
    harness = SimpleNamespace(
        _model=model,
        _render_pipeline=MOC3_RENDER_PIPELINE,
        _quality_profile="balanced",
        _cache_w=300,
        _cache_h=400,
        _system_scale=1.5,
        _renderer_target_size=None,
    )
    harness._render_ssaa_scale = lambda: MOC3_RENDER_PIPELINE.ssaa_scale(harness._quality_profile)

    Live2DWidget._sync_renderer_target_size(harness)
    Live2DWidget._sync_renderer_target_size(harness)
    harness._quality_profile = "performance"
    Live2DWidget._sync_renderer_target_size(harness)

    assert calls == [(900, 1200), (450, 600)]


def test_screen_dpi_round_trip_does_not_resize_logical_model():
    logical_resizes = []
    renderer_resizes = []
    viewports = []
    ratios = iter((1.5, 1.0, 1.5, 1.0))
    model = SimpleNamespace(
        Resize=lambda width, height: logical_resizes.append((width, height)),
        ResizeRenderer=lambda width, height: renderer_resizes.append((width, height)),
    )
    harness = SimpleNamespace(
        _model=model,
        _render_pipeline=MOC3_RENDER_PIPELINE,
        _quality_profile="performance",
        _cache_w=400,
        _cache_h=500,
        _system_scale=1.0,
        _renderer_target_size=(400, 500),
        _initialized_gl=True,
    )
    harness._current_device_pixel_ratio = lambda: next(ratios)
    harness._safe_make_current = lambda: None
    harness._reset_hit_stability = lambda: None
    harness._render_ssaa_scale = lambda: 1
    harness._sync_renderer_target_size = lambda force=False: Live2DWidget._sync_renderer_target_size(
        harness,
        force=force,
    )
    harness._apply_physical_viewport = lambda width, height: viewports.append(
        (int(width * harness._system_scale), int(height * harness._system_scale))
    )
    harness.update = lambda: None

    for _ in range(4):
        Live2DWidget.refresh_screen_scale(harness)

    assert logical_resizes == []
    assert renderer_resizes == [
        (600, 750),
        (400, 500),
        (600, 750),
        (400, 500),
    ]
    assert viewports == renderer_resizes


def test_device_pixel_ratio_prefers_opengl_widget_backing_store_value():
    harness = SimpleNamespace(devicePixelRatioF=lambda: 1.25)

    assert Live2DWidget._current_device_pixel_ratio(harness) == 1.25


def test_resize_renderer_does_not_change_logical_model_size():
    calls = []
    model = object.__new__(LuaLAppModelBase)
    model._renderer = object()
    model._module = SimpleNamespace(
        _resize=lambda _renderer, width, height: calls.append(("logical", width, height)),
        _resize_renderer=lambda _renderer, width, height: calls.append(("render", width, height)),
    )
    model._width = 1
    model._height = 1
    model.matrixManager = SimpleNamespace(on_resize=lambda *_args: None)

    model.Resize(320, 480)
    model.ResizeRenderer(640, 960)

    assert calls == [("logical", 320, 480), ("render", 640, 960)]
    assert (model._width, model._height) == (320, 480)


def test_moc3_runtime_patch_separates_logical_and_render_target_sizes():
    source = (
        Path(__file__).resolve().parents[1]
        / "third_party"
        / "Live2D-v2-Lua"
        / "live2d_moc3_pet_embed.lua"
    ).read_bytes()

    patched = _patch_lua_moc3_pet_embed_delta("live2d_moc3_pet_embed", source)

    assert b"function Renderer:resize_renderer" in patched
    assert b"return self:resize_renderer(self.width, self.height)" in patched
    assert b"return self:resize_renderer(self.render_width, self.render_height)" in patched
    render_resize = patched.split(b"function Renderer:resize_renderer", 1)[1].split(
        b"function Renderer:set_offset",
        1,
    )[0]
    assert b"self.width =" not in render_resize
    assert b"/ math.max(self.width, 1)" in patched
    assert b"/ math.max(self.height, 1)" in patched
    assert _patch_lua_moc3_pet_embed_delta("live2d_moc3_pet_embed", patched) == patched
