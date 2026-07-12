import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from live2d_lua_adapter_base import LuaLive2DRuntimeBase
from live2d_lua_adapter_moc import LuaLive2DModuleMOC
from live2d_lua_adapter_moc3 import LuaLive2DModuleMOC3
from live2d_widget import render_pipeline_for_model
from live2d_widget_base import DIRECT_RENDER_PIPELINE
from live2d_widget_moc3 import MOC3_RENDER_PIPELINE
import live2d_widget_moc3


def test_only_cubism2_runtime_installs_platform_manager_override():
    assert LuaLive2DModuleMOC._configure_runtime is not LuaLive2DRuntimeBase._configure_runtime
    assert LuaLive2DModuleMOC3._configure_runtime is LuaLive2DRuntimeBase._configure_runtime


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
