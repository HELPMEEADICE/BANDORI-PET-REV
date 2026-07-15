from pathlib import Path

import pytest
from lupa.luajit21 import LuaRuntime

from live2d_lua_adapter_moc3 import _patch_lua_moc3_module


def _physics_zero_delta_probe():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute("jit.off()")
    root = (Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua").as_posix()
    physics_path = Path(root) / "live2d" / "cubism3" / "physics.lua"
    physics_source = _patch_lua_moc3_module(
        "live2d.cubism3.physics", physics_path.read_bytes()
    )
    lua.globals()["__bandori_test_physics_source"] = physics_source
    lua.execute(
        "package.preload['live2d.cubism3.physics'] = function() "
        "local fn = assert(load(__bandori_test_physics_source, '@physics.lua')); "
        "return fn() end"
    )
    lua.execute(
        "package.path = package.path .. ';' .. ... .. '/?.lua;' .. ... .. '/?/init.lua'",
        root,
        root,
    )
    return lua.execute(
        r'''
local Physics = require("live2d.cubism3.physics")

local data = {
    fps = 60,
    settings = {{
        inputs = {{
            source_id = "ParamAngleY", weight = 100,
            type = "Angle", reflect = false,
        }},
        outputs = {{
            destination_id = "ParamBodyAngleY", vertex_index = 1,
            scale = 44.558, weight = 100,
            type = "Angle", reflect = false,
        }},
        vertices = {
            { mobility = 0.8, delay = 0.2, acceleration = 1.0, radius = 10.0 },
            { mobility = 0.8, delay = 0.2, acceleration = 1.0, radius = 10.0 },
        },
        normalization_position = { minimum = -10, maximum = 10, default = 0 },
        normalization_angle = { minimum = -30, maximum = 30, default = 0 },
    }},
}

local runtime = { parameter_values = { 30.0, 0.0 } }
function runtime:parameter_index_of(id)
    if id == "ParamAngleY" then return 0 end
    if id == "ParamBodyAngleY" then return 1 end
    return nil
end
function runtime:parameter_value_by_index(index) return self.parameter_values[index + 1] end
function runtime:parameter_minimum_by_index(index) return index == 0 and -30.0 or -10.0 end
function runtime:parameter_maximum_by_index(index) return index == 0 and 30.0 or 10.0 end
function runtime:set_parameter_by_index(index, value) self.parameter_values[index + 1] = value end

local physics = assert(Physics.new(data))
for _ = 1, 120 do physics:evaluate(runtime, 1.0 / 60.0) end
local before = runtime.parameter_values[2]

-- The outer frame pipeline restores the motion/base value before physics.
runtime.parameter_values[2] = 0.0
physics:evaluate(runtime, 0.0)
return before, runtime.parameter_values[2], physics.last_substep_count
'''
    )


def test_zero_delta_reapplies_physics_pose_without_advancing():
    before, duplicate_render, substeps = _physics_zero_delta_probe()

    assert abs(before) > 0.1
    assert duplicate_render == pytest.approx(before, abs=1e-9)
    assert substeps == 0
