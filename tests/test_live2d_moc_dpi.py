import unittest
from types import SimpleNamespace

from lupa.luajit21 import LuaRuntime

from bandori_live2d.live2d_lua_adapter_moc import LuaLAppModelMOC, LuaLive2DModuleMOC
from bandori_live2d.live2d_widget import Live2DWidget
from bandori_live2d.live2d_widget_base import DIRECT_RENDER_PIPELINE, Live2DWidgetBase
from bandori_live2d.live2d_widget_moc3 import MOC3_RENDER_PIPELINE


class Live2DMocDpiTest(unittest.TestCase):
    def test_lip_sync_keeps_moc2_parameter_ids_for_adapter_aliasing(self):
        calls = []
        harness = SimpleNamespace(
            _hit_clock=SimpleNamespace(isValid=lambda: True, elapsed=lambda: 100),
            _lip_sync_target=0.8,
            _lip_sync_form_target=0.25,
            _lip_sync_last_ms=100,
            _lip_sync_level=0.0,
            _lip_sync_form=0.0,
            _model=SimpleNamespace(
                SetParameterValue=lambda *args: calls.append(args),
            ),
        )

        Live2DWidgetBase._apply_lip_sync(harness)

        self.assertEqual(
            ["PARAM_MOUTH_OPEN_Y", "PARAM_MOUTH_FORM"],
            [call[0] for call in calls],
        )
        self.assertAlmostEqual(0.44, calls[0][1])
        self.assertAlmostEqual(0.1125, calls[1][1])

    def test_moc_render_target_uses_physical_size_without_resizing_projection(self):
        calls = []
        harness = SimpleNamespace(
            _model=SimpleNamespace(ResizeRenderer=lambda w, h: calls.append((w, h))),
            _render_pipeline=DIRECT_RENDER_PIPELINE,
            _cache_w=500,
            _cache_h=625,
            _system_scale=1.0,
            _renderer_target_size=None,
            _render_ssaa_scale=lambda: 1,
        )
        for ratio in (1.0, 1.5, 1.5, 2.0, 1.0):
            harness._system_scale = ratio
            Live2DWidget._sync_renderer_target_size(harness)

        self.assertEqual([(500, 625), (750, 937), (1000, 1250), (500, 625)], calls)

    def test_moc_native_render_resize_preserves_logical_size_and_pointer_coordinates(self):
        lua = LuaRuntime(unpack_returned_tuples=True, encoding=None)
        module = LuaLive2DModuleMOC()
        module._lua = lua
        module._load_lua_runtime_functions(lua)
        renderer, native_model = lua.execute(b"""
            local model = { live2DModel = {} }
            function model.live2DModel:resize(w, h)
                self.width = w
                self.height = h
            end
            local renderer = {}
            function renderer:get_model() return model end
            function renderer:resize(w, h)
                self.width = w
                self.height = h
                model.live2DModel:resize(w, h)
            end
            return renderer, model
        """)
        model = LuaLAppModelMOC(module)
        model._renderer = renderer
        model.Resize(500, 625)
        scene_before = model.matrixManager.screenToScene(250, 125)

        for width, height in ((750, 937), (1000, 1250), (500, 625)):
            model.ResizeRenderer(width, height)
            self.assertEqual((width, height), (
                native_model[b"live2DModel"][b"width"],
                native_model[b"live2DModel"][b"height"],
            ))
            self.assertEqual((500, 625), (renderer[b"width"], renderer[b"height"]))
            self.assertEqual((500, 625), (model._width, model._height))
            self.assertEqual(scene_before, model.matrixManager.screenToScene(250, 125))

    def test_moc_screen_dpi_refresh_changes_only_renderer_size(self):
        calls = []
        ratios = iter((1.5, 2.0, 1.0))
        harness = SimpleNamespace(
            _model=SimpleNamespace(ResizeRenderer=lambda w, h: calls.append((w, h))),
            _render_pipeline=DIRECT_RENDER_PIPELINE,
            _cache_w=500,
            _cache_h=625,
            _system_scale=1.0,
            _renderer_target_size=(500, 625),
            _render_ssaa_scale=lambda: 1,
            _initialized_gl=True,
            _current_device_pixel_ratio=lambda: next(ratios),
            _reset_hit_stability=lambda: None,
            _safe_make_current=lambda: None,
            _apply_physical_viewport=lambda w, h: None,
            update=lambda: None,
        )
        harness._sync_renderer_target_size = lambda: Live2DWidget._sync_renderer_target_size(harness)

        for _ in range(3):
            Live2DWidget.refresh_screen_scale(harness)

        self.assertEqual([(750, 937), (1000, 1250), (500, 625)], calls)

    def test_moc3_keeps_calibrated_scale_and_ssaa_render_target(self):
        scales, targets = [], []
        model = SimpleNamespace(
            SetScale=scales.append,
            ResizeRenderer=lambda w, h: targets.append((w, h)),
        )
        MOC3_RENDER_PIPELINE.prepare_model(model)
        harness = SimpleNamespace(
            _model=model,
            _render_pipeline=MOC3_RENDER_PIPELINE,
            _cache_w=500,
            _cache_h=1000,
            _system_scale=1.5,
            _renderer_target_size=None,
            _render_ssaa_scale=lambda: MOC3_RENDER_PIPELINE.ssaa_scale("balanced"),
        )

        Live2DWidget._sync_renderer_target_size(harness)

        self.assertEqual([1.45], scales)
        self.assertEqual([(1500, 3000)], targets)

    def test_moc3_crop_keeps_full_virtual_canvas_at_high_dpi(self):
        targets = []
        harness = SimpleNamespace(
            _model=SimpleNamespace(ResizeRenderer=lambda w, h: targets.append((w, h))),
            _render_pipeline=MOC3_RENDER_PIPELINE,
            _quality_profile="balanced",
            _cache_w=400,
            _cache_h=500,
            _system_scale=1.5,
            _renderer_target_size=None,
            _moc3_leg_crop_enabled=True,
            _moc3_visible_height=500,
            _render_ssaa_scale=lambda: 2,
        )

        Live2DWidget._sync_renderer_target_size(harness)

        self.assertEqual([(1200, 2400)], targets)

    def test_moc3_crop_target_height_tracks_visible_height(self):
        harness = SimpleNamespace(
            _render_pipeline=MOC3_RENDER_PIPELINE,
            _moc3_leg_crop_enabled=True,
            _moc3_visible_height=500,
        )

        target_heights = []
        for visible_height in (500, 640, 800):
            harness._moc3_visible_height = visible_height
            target_heights.append(
                Live2DWidgetBase._moc3_render_target_height(harness, 500)
            )

        self.assertEqual([800, 625, 500], target_heights)

    def test_moc3_crop_uses_full_logical_height_for_model_pointer_mapping(self):
        logical_sizes = []
        harness = SimpleNamespace(
            _model=SimpleNamespace(Resize=lambda w, h: logical_sizes.append((w, h))),
            _render_pipeline=MOC3_RENDER_PIPELINE,
            _cache_w=400,
            _cache_h=500,
            _moc3_leg_crop_enabled=True,
            _moc3_visible_height=500,
            _model_logical_size=None,
            _update_custom_hit_area_projection=lambda: None,
        )

        Live2DWidgetBase._sync_model_logical_size(harness, force=True)

        self.assertEqual([(400, 800)], logical_sizes)

    def test_crop_settings_do_not_change_moc_renderer_target(self):
        targets = []
        harness = SimpleNamespace(
            _model=SimpleNamespace(ResizeRenderer=lambda w, h: targets.append((w, h))),
            _render_pipeline=DIRECT_RENDER_PIPELINE,
            _cache_w=400,
            _cache_h=500,
            _system_scale=1.0,
            _renderer_target_size=None,
            _moc3_leg_crop_enabled=True,
            _moc3_visible_height=500,
            _render_ssaa_scale=lambda: 1,
        )

        Live2DWidget._sync_renderer_target_size(harness)

        self.assertEqual([(400, 500)], targets)


if __name__ == "__main__":
    unittest.main()
