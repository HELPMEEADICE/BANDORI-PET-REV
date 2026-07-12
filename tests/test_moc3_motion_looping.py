import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from lupa import LuaRuntime

from live2d_lua_adapter import (
    MODEL_FORMAT_MOC,
    MODEL_FORMAT_MOC3,
    LuaLive2DModule,
    _patch_lua_moc3_pet_embed_delta,
)
from pet_window import PetWindow


class Moc3MotionLoopingTest(unittest.TestCase):
    def test_cubism2_renderer_does_not_require_moc3_bridge(self):
        moc_model = _FakeAdapterModel(MODEL_FORMAT_MOC)
        moc_runtime = _FakeAdapterRuntime(moc_model)
        moc3_runtime = _FailingAdapterRuntime()
        module = LuaLive2DModule(moc_runtime, moc3_runtime)
        module.glInit()

        self.assertEqual(0, moc_runtime.model_requests)
        self.assertEqual(0, moc3_runtime.model_requests)

        with patch("live2d_lua_adapter._model_manifest_format", return_value=MODEL_FORMAT_MOC):
            model = module.LAppModel()
            model.Resize(12, 34)
            model.LoadModelJson("test.model.json")

        self.assertEqual(MODEL_FORMAT_MOC, model.renderer_format)
        self.assertEqual((12, 34), moc_model.size)
        self.assertEqual(["test.model.json"], moc_model.loaded_paths)
        self.assertEqual(0, moc3_runtime.model_requests)

    def test_moc3_model_uses_its_own_runtime(self):
        moc_runtime = _FailingAdapterRuntime()
        moc3_model = _FakeAdapterModel(MODEL_FORMAT_MOC3)
        moc3_runtime = _FakeAdapterRuntime(moc3_model)
        module = LuaLive2DModule(moc_runtime, moc3_runtime)

        with patch("live2d_lua_adapter._model_manifest_format", return_value=MODEL_FORMAT_MOC3):
            model = module.LAppModel()
            model.LoadModelJson("test.model3.json")

        self.assertEqual(MODEL_FORMAT_MOC3, model.renderer_format)
        self.assertEqual(0, moc_runtime.model_requests)
        self.assertEqual(1, moc3_runtime.model_requests)

    def test_looping_motion_can_be_played_once(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        root = (Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua").as_posix()
        lua.execute(
            "local root = ...; "
            "package.path = package.path .. ';' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
            root,
        )

        finished = lua.execute(
            "local MotionPlayer = require('live2d.cubism3.motion'); "
            "local motion = { meta = { Duration = 1.0, Loop = true }, curves = {} }; "
            "local player = MotionPlayer.new(motion, false); "
            "player:tick(1.1); "
            "return player:is_finished()"
        )

        self.assertTrue(finished)

    def test_motion_level_fade_in_blends_inherited_curves(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        root = (Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua").as_posix()
        lua.execute(
            "local root = ...; "
            "package.path = package.path .. ';' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
            root,
        )

        value = lua.execute(
            "local MotionPlayer = require('live2d.cubism3.motion'); "
            "local runtime = { value = 30.0 }; "
            "function runtime:parameter_index_of(id) return id == 'ParamAngleX' and 0 or nil end; "
            "function runtime:parameter_value_by_index(_index) return self.value end; "
            "function runtime:set_parameter_by_index(_index, value) self.value = value end; "
            "local curve = { "
            "target = 'Parameter', id = 'ParamAngleX', "
            "fade_in_time = -1.0, fade_out_time = -1.0, "
            "sample = function(_self, _time) return 0.0 end "
            "}; "
            "local motion = { "
            "meta = { Duration = 1.0, FadeInTime = 1.0, FadeOutTime = 1.0 }, "
            "curves = { curve } "
            "}; "
            "local player = MotionPlayer.new(motion, false); "
            "player:tick(0.25); "
            "player:apply(runtime); "
            "return runtime.value"
        )

        self.assertGreater(value, 0.0)
        self.assertLess(value, 30.0)

    def test_click_motion_requests_one_shot_playback(self):
        model = _FakeModel(["mtn_smile01_C"])
        harness = _MotionHarness(model)

        with patch("pet_window.QTimer.singleShot"):
            PetWindow._start_click_motion(harness, "mtn_smile01_C")

        self.assertEqual(False, model.random_motion_calls[0]["kwargs"].get("loop"))

    def test_idle_motion_requests_looping_playback(self):
        model = _FakeModel(["mtn_idle01_C"])
        harness = _MotionHarness(model)
        harness.default_motion = "mtn_idle01_C"

        PetWindow._start_idle_motion(harness, smooth=True)

        self.assertEqual(True, model.random_motion_calls[0]["kwargs"].get("loop"))

    def test_moc3_idle_motion_name_is_used_as_default(self):
        model = _FakeModel(["mtn_idle01_C"])
        harness = _MotionHarness(model)

        PetWindow._start_idle_motion(harness, smooth=True)

        self.assertEqual("mtn_idle01_C", model.random_motion_calls[0]["name"])

    def test_moc3_pet_embed_delta_uses_elapsed_time_not_frame_count(self):
        source = b"""
local M = {}
local GL_COLOR_BUFFER_BIT = 0x00004000
function M.draw(self, opts)
    local time_msec = tonumber(opts.time_msec) or 0
    local delta = 1 / 60
    if self.last_time_msec ~= nil and time_msec > self.last_time_msec then
        delta = math.min((time_msec - self.last_time_msec) / 1000.0, 0.1)
    end
    self.last_time_msec = time_msec
    return delta
end
"""
        patched = _patch_lua_moc3_pet_embed_delta(
            "live2d_moc3_pet_embed",
            source,
        )
        lua = LuaRuntime(unpack_returned_tuples=True)
        compute_delta = lua.execute(patched.decode("utf-8") + "\nreturn compute_delta_seconds")

        state = lua.table()
        first = compute_delta(state, 1000.0)
        same = compute_delta(state, 1000.0)
        high_fps = compute_delta(state, 1004.0)
        capped = compute_delta(state, 2000.0)

        self.assertEqual(0, first)
        self.assertEqual(0, same)
        self.assertAlmostEqual(0.004, high_fps)
        self.assertAlmostEqual(0.1, capped)

    def test_bundled_moc3_pet_embed_delta_uses_elapsed_time(self):
        source = Path("third_party/Live2D-v2-Lua/live2d_moc3_pet_embed.lua").read_bytes()
        patched = _patch_lua_moc3_pet_embed_delta("live2d_moc3_pet_embed", source)
        helper = re.search(
            rb"local function compute_delta_seconds\(state, time_msec(?:, explicit_delta)?\).*?\r?\nend\r?\n",
            patched,
            re.DOTALL,
        ).group(0)
        lua = LuaRuntime(unpack_returned_tuples=True)
        compute_delta = lua.execute(helper.decode("utf-8") + "\nreturn compute_delta_seconds")

        state = lua.table()
        first = compute_delta(state, 1000.0)
        refresh_144hz = compute_delta(state, 1006.944444)
        refresh_75hz = compute_delta(state, 1020.277777)

        self.assertEqual(0, first)
        self.assertAlmostEqual(1 / 144, refresh_144hz, places=5)
        self.assertAlmostEqual(1 / 75, refresh_75hz, places=5)

    def test_moc3_resource_loader_receives_virtual_paths(self):
        from lupa.luajit21 import LuaRuntime as LuaJITRuntime

        lua = LuaJITRuntime(unpack_returned_tuples=True)
        root = (Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua").as_posix()
        lua.execute(
            "local root = ...; "
            "package.path = package.path .. ';' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
            root,
        )

        data = lua.execute(
            "local moc3 = require('live2d_moc3_embed'); "
            "local target = 'X:/models/anon.zst::live/test.moc3'; "
            "local renderer = moc3.new({ resource_streams = { "
            "__loader = function(path) if path == target then return 'moc-bytes' end end "
            "} }); "
            "return renderer:read_resource(target)"
        )

        self.assertEqual("moc-bytes", data)

    def test_moc3_texture_loader_accepts_python_callbacks(self):
        from lupa.luajit21 import LuaRuntime as LuaJITRuntime

        lua = LuaJITRuntime(unpack_returned_tuples=True)
        root = (Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua").as_posix()
        lua.execute(
            "local root = ...; "
            "package.path = package.path .. ';' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
            root,
        )
        calls = []

        def loader(texture_index, path):
            calls.append((texture_index, path))
            return "texture-bytes"

        data = lua.execute(
            "local OpenGLRenderer = require('live2d.cubism3.opengl_renderer'); "
            "local renderer = { texture_streams = { __loader = ... } }; "
            "setmetatable(renderer, { __index = OpenGLRenderer }); "
            "return renderer:resolve_texture_stream('X:/models/anon.zst::live/texture.png', 0)",
            loader,
        )

        self.assertEqual("texture-bytes", data)
        self.assertEqual([(0, "X:/models/anon.zst::live/texture.png")], calls)


class _MotionHarness:
    _safe_start_motion = PetWindow._safe_start_motion
    _is_idle_motion_name = staticmethod(PetWindow._is_idle_motion_name)

    def __init__(self, model):
        self._live2d_widget = _FakeLive2DWidget(model)
        self._live2d = _FakeLive2D()
        self._motion_guard_token = 0
        self._expression_guard_token = 0
        self._live2d_prewarmed_motions = set()
        self._live2d_prewarmed_expressions = set()
        self._live2d_idle_actions_enabled = True
        self._live2d_random_actions_enabled = True
        self.default_motion = ""

    def _current_motion_names(self):
        return list(self._live2d_widget.model.motion_names)

    def _current_model_entry(self):
        return {"default_motion": self.default_motion}

    def _apply_default_expression(self, _model):
        pass


class _FakeAdapterModel:
    def __init__(self, renderer_format):
        self.renderer_format = renderer_format
        self.size = (1, 1)
        self.loaded_paths = []

    def Resize(self, width, height):
        self.size = (width, height)

    def LoadModelJson(self, path):
        self.loaded_paths.append(path)

    def _dispose_renderer(self):
        pass


class _FakeAdapterRuntime:
    def __init__(self, model):
        self.model = model
        self.model_requests = 0

    def LAppModel(self):
        self.model_requests += 1
        return self.model

    def dispose(self):
        pass


class _FailingAdapterRuntime:
    def __init__(self):
        self.model_requests = 0

    def LAppModel(self):
        self.model_requests += 1
        raise AssertionError("wrong renderer runtime initialized")

    def dispose(self):
        pass


class _FakeLive2DWidget:
    def __init__(self, model):
        self.model = model


class _FakeLive2D:
    MotionPriority = type("MotionPriority", (), {"FORCE": 3})


class _FakeModelSetting:
    def __init__(self, motion_names):
        self._motion_names = list(motion_names)

    def getMotionNum(self, motion_name):
        return 1 if motion_name in self._motion_names else 0

    def resolveMotion(self, motion_name, no):
        if motion_name in self._motion_names:
            return motion_name, no
        return None


class _FakeModel:
    def __init__(self, motion_names):
        self.motion_names = list(motion_names)
        self.modelSetting = _FakeModelSetting(motion_names)
        self.random_motion_calls = []
        self.motion_calls = []

    def StartRandomMotion(self, name=None, priority=None, **kwargs):
        self.random_motion_calls.append({"name": name, "priority": priority, "kwargs": kwargs})

    def StartMotion(self, name, no=0, priority=None, **kwargs):
        self.motion_calls.append({"name": name, "no": no, "priority": priority, "kwargs": kwargs})


if __name__ == "__main__":
    unittest.main()
