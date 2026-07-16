from pathlib import Path

from lupa import LuaRuntime


LUA_ROOT = (Path(__file__).resolve().parents[1] / "third_party" / "Live2D-v2-Lua").as_posix()


def _lua_runtime() -> LuaRuntime:
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(
        "local root = ...; package.path = package.path .. ';' .. root .. '/?.lua;' .. root .. '/?/init.lua'",
        LUA_ROOT,
    )
    return lua


def test_moc3_motion_and_expression_caches_are_lru_bounded():
    lua = _lua_runtime()
    result = lua.execute(
        """
        package.loaded['live2d.cubism3.moc3'] = {}
        package.loaded['live2d.cubism3.json.model3'] = {}
        package.loaded['live2d.cubism3.json.motion3'] = {
            parse = function(data) return { payload = data } end
        }
        package.loaded['live2d.cubism3.json.expression3'] = {
            parse = function(data) return { payload = data } end
        }
        package.loaded['live2d.cubism3.json.pose3'] = {}
        package.loaded['live2d.cubism3.json.physics3'] = {}
        package.loaded['live2d.cubism3.runtime'] = {}
        package.loaded['live2d.cubism3.motion'] = {}
        package.loaded['live2d.cubism3.expression'] = {
            ExpressionManager = { new = function() return {} end }
        }
        package.loaded['live2d.cubism3.physics'] = {}

        local moc3 = require('live2d_moc3_embed')
        local renderer = moc3.new({
            resource_streams = { __loader = function(path) return path end }
        })
        renderer.base_path = ''
        renderer.motion_cache_limit = 2
        renderer.expression_cache_limit = 2
        renderer.model_data = { file_references = {
            motions = { a = {{ File = 'a' }}, b = {{ File = 'b' }}, c = {{ File = 'c' }} },
            expressions = {
                { Name = 'a', File = 'ea' },
                { Name = 'b', File = 'eb' },
                { Name = 'c', File = 'ec' },
            },
        } }

        renderer:load_motion('a', 0)
        renderer:load_motion('b', 0)
        renderer:load_motion('a', 0)
        renderer:load_motion('c', 0)
        renderer:load_expression('a')
        renderer:load_expression('b')
        renderer:load_expression('a')
        renderer:load_expression('c')

        local motion_count, expression_count = 0, 0
        for _ in pairs(renderer.motion_cache) do motion_count = motion_count + 1 end
        for _ in pairs(renderer.expression_cache) do expression_count = expression_count + 1 end
        return {
            motion_count,
            renderer.motion_cache['a'] ~= nil,
            renderer.motion_cache['b'] == nil,
            expression_count,
            renderer.expression_cache['ea'] ~= nil,
            renderer.expression_cache['eb'] == nil,
        }
        """
    )

    assert [result[i] for i in range(1, 7)] == [2, True, True, 2, True, True]


def test_moc_motion_cache_is_lru_bounded():
    lua = _lua_runtime()
    result = lua.execute(
        """
        package.loaded['live2d.core.motion.live2d_motion'] = {
            loadMotion = function(data) return { payload = data } end
        }
        package.loaded['live2d.framework.Live2DFramework'] = {
            getPlatformManager = function()
                return { loadBytes = function(_, path) return path end }
            end
        }
        package.loaded['live2d.framework.matrix.l2d_model_matrix'] = {}
        package.loaded['live2d.framework.motion.l2d_expression_motion'] = {
            loadJson = function(data) return { payload = data } end
        }
        package.loaded['live2d.framework.motion.l2d_motion_manager'] = {
            new = function() return {} end
        }
        package.loaded['live2d.framework.physics.l2d_physics'] = {}
        package.loaded['live2d.framework.pose.l2d_pose'] = {}

        local BaseModel = require('live2d.framework.model.l2d_base_model')
        local model = BaseModel.new()
        model.motionCacheLimit = 2
        model:loadMotion('a', 'a')
        model:loadMotion('b', 'b')
        model:touchMotion('a')
        model:loadMotion('c', 'c')

        local count = 0
        for _ in pairs(model.motions) do count = count + 1 end
        return { count, model.motions.a ~= nil, model.motions.b == nil, model.motions.c ~= nil }
        """
    )

    assert [result[i] for i in range(1, 5)] == [2, True, True, True]
