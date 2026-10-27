import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from lupa.luajit21 import LuaRuntime

from live2d_lua_adapter_base import _install_lazy_lua_module_loader
from live2d_lua_adapter_moc import LuaLAppModelMOC, LuaLive2DModuleMOC
from live2d_lua_adapter_moc3 import LuaLAppModelMOC3, LuaLive2DModuleMOC3
from live2d_lua_moc3_source_patch import patch_live2d_lua_moc3_module
from live2d_widget_base import Live2DWidgetBase


LUA_ROOT = Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua"


def lip_sync_state(model):
    clock = SimpleNamespace(now=100)
    return SimpleNamespace(
        _hit_clock=SimpleNamespace(isValid=lambda: True, elapsed=lambda: clock.now),
        _lip_sync_target=0.0,
        _lip_sync_form_target=0.0,
        _lip_sync_last_ms=-1000,
        _lip_sync_level=0.0,
        _lip_sync_form=0.0,
        _model=model,
    ), clock


def dump_lua(source):
    lua = LuaRuntime(encoding=None)
    return lua.eval(b"function(source) return string.dump(assert(load(source)), true) end")(source)


@pytest.fixture(params=["source", "release-bytecode"])
def moc3_model(request, tmp_path):
    source = (LUA_ROOT / "live2d_moc3_pet_embed.lua").read_bytes()
    if request.param == "release-bytecode":
        # The release compiler patches source before emitting LuaJIT bytecode.
        source = dump_lua(patch_live2d_lua_moc3_module("live2d_moc3_pet_embed", source))
        suffix = ".ljbc"
    else:
        suffix = ".lua"
    (tmp_path / ("live2d_moc3_pet_embed" + suffix)).write_bytes(source)
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    lua.execute(b"jit.off()")
    lua.execute(
        b"package.path = package.path .. ';' .. ... .. '/?.lua;' .. ... .. '/?/init.lua'",
        LUA_ROOT.as_posix().encode("utf-8"),
        LUA_ROOT.as_posix().encode("utf-8"),
    )
    # Exercise the real parameter override storage without a GPU or model assets.
    runtime = lua.execute(b"""
        local Runtime = require('live2d.cubism3.runtime')
        local runtime = setmetatable({
            canvas = {width = 400, height = 800, pixels_per_unit = 100},
            parameter_index = {ParamMouthOpenY = 0, ParamMouthForm = 1,
                ParamAngleX = 2, ParamAngleY = 3, ParamEyeBallX = 4,
                ParamEyeBallY = 5, ParamBodyAngleX = 6},
            parameter_values = {0, 0, 0, 0, 0, 0, 0},
            parameter_overrides = {}, parameter_override_sources = {},
            bindings = {parameter_min_values = {0, -1, -30, -30, -1, -1, -30},
                parameter_max_values = {1, 1, 30, 30, 1, 1, 30}},
        }, Runtime)
        local inner = {}
        function inner:get_runtime() return runtime end
        function inner:set_parameter_override(id, value, source)
            return runtime:set_parameter_override(id, value, source)
        end
        function inner:clear_parameter_override(id)
            return runtime:clear_parameter_override(id)
        end
        function inner:update(delta)
            -- A singing motion supplies these mouth curves on every frame.
            runtime.parameter_values[1] = 0.7
            runtime.parameter_values[2] = -0.3
            runtime:apply_parameter_overrides()
            runtime.last_delta = delta
        end
        function inner:render() end
        package.loaded['live2d.gl_loader'] = {
            ensureExtensions = function() end, glViewport = function() end,
        }
        package.loaded['live2d_moc3_embed'] = {new = function() return inner end}
        return runtime
    """)
    _install_lazy_lua_module_loader(lua, tmp_path, extra_module_patch=patch_live2d_lua_moc3_module)
    embed = lua.execute(b"return require('live2d_moc3_pet_embed')")
    module = LuaLive2DModuleMOC3()
    module._lua = lua
    module._load_lua_runtime_functions(lua)
    model = LuaLAppModelMOC3(module)
    model._renderer = embed[b"new"](400, 800)
    model.Resize(400, 800)
    return model, runtime


def test_idle_lip_sync_preserves_motion_mouth_curves(moc3_model):
    model, runtime = moc3_model
    state, _clock = lip_sync_state(model)

    Live2DWidgetBase._apply_lip_sync(state)
    model.Draw()

    assert not model._pending_parameters
    assert runtime[b"parameter_values"][1] == pytest.approx(0.7)
    assert runtime[b"parameter_values"][2] == pytest.approx(-0.3)


def test_tts_releases_mouth_overrides_and_preserves_tracking(moc3_model):
    model, runtime = moc3_model
    state, clock = lip_sync_state(model)
    model.ResizeRenderer(1600, 3200)
    model.Drag(400, 0)
    model.SetParameterValue("PARAM_BODY_ANGLE_X", 7.0)
    state._lip_sync_target = 0.8
    state._lip_sync_form_target = 0.25
    state._lip_sync_last_ms = clock.now

    Live2DWidgetBase._apply_lip_sync(state)
    model.Draw()
    values = runtime[b"parameter_values"]
    assert values[1] == pytest.approx(0.44)
    assert values[2] == pytest.approx(0.1125)
    assert [values[i] for i in range(3, 8)] == [30, 30, 1, 1, 7]

    clock.now += 181
    Live2DWidgetBase._apply_lip_sync(state)
    model.Draw()
    assert 0 < values[1] < 0.44  # Preserve the existing TTS fade-out.
    for _ in range(20):
        Live2DWidgetBase._apply_lip_sync(state)
        model.Draw()

    assert state._lip_sync_level == state._lip_sync_form == 0.0
    assert values[1] == pytest.approx(0.7)
    assert values[2] == pytest.approx(-0.3)
    assert runtime[b"parameter_overrides"][1] is None
    assert runtime[b"parameter_overrides"][2] is None
    assert [values[i] for i in range(3, 8)] == [30, 30, 1, 1, 7]
    assert set(model._pending_parameters) == {"PARAM_BODY_ANGLE_X"}

    # Silent TTS samples still close the mouth while speech is active.
    state._lip_sync_last_ms = clock.now
    state._lip_sync_target = state._lip_sync_form_target = 0.0
    Live2DWidgetBase._apply_lip_sync(state)
    model.Draw()
    assert values[1] == values[2] == 0.0


def test_cubism2_releases_only_the_requested_host_parameter():
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    module = LuaLive2DModuleMOC()
    module._lua = lua
    module._load_lua_runtime_functions(lua)
    model = LuaLAppModelMOC(module)
    model._renderer = lua.execute(b"""
        local renderer = {}
        function renderer:draw(opts)
            self.mouth = 0.7
            for _, entry in ipairs(opts.parameters or {}) do
                if entry.id == 'PARAM_MOUTH_OPEN_Y' then self.mouth = entry.value end
            end
        end
        return renderer
    """)
    model.SetParameterValue("PARAM_MOUTH_OPEN_Y", 0.0)
    model.SetParameterValue("PARAM_ANGLE_X", 15)
    model.Draw()
    assert model._renderer[b"mouth"] == 0.0

    model.ClearParameterValue("PARAM_MOUTH_OPEN_Y")
    model.ClearParameterValue("PARAM_MOUTH_OPEN_Y")
    model.Draw()

    assert model._renderer[b"mouth"] == pytest.approx(0.7)
    assert set(model._pending_parameters) == {"PARAM_ANGLE_X"}


def test_compiled_lua_is_loaded_without_text_patches(tmp_path):
    name = "live2d_moc3_pet_embed"
    # Binary string lengths must survive even when constants contain CRLF.
    bytecode = dump_lua(b'return {value = "\\r\\n"}')
    assert b"\r\n" in bytecode
    (tmp_path / (name + ".ljbc")).write_bytes(bytecode)
    (tmp_path / (name + ".lua")).write_bytes(b"error('bytecode must take precedence')")
    lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)

    def reject_bytecode_patch(*_args):
        pytest.fail("Source patches must not run against bytecode")

    _install_lazy_lua_module_loader(lua, tmp_path, extra_module_patch=reject_bytecode_patch)

    assert lua.execute(b"return require('live2d_moc3_pet_embed').value") == b"\r\n"
