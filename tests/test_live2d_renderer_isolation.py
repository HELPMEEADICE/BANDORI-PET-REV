import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from live2d_lua_adapter_base import LuaLive2DRuntimeBase
from live2d_lua_adapter_moc import LuaLive2DModuleMOC
from live2d_lua_adapter_moc3 import LuaLive2DModuleMOC3
from live2d_widget import render_pipeline_for_model
from live2d_widget_base import DIRECT_RENDER_PIPELINE
from live2d_widget_moc3 import MOC3_RENDER_PIPELINE


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
