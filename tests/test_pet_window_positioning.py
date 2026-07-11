import os
import inspect
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QWidget

from model_manager import MODEL_FORMAT_MOC3
from pet_window import LIVE2D_MOC3_BASE_HEIGHT, PetWindow


class FakeScreen:
    def __init__(self, geometry: QRect):
        self._geometry = geometry

    def availableGeometry(self):
        return QRect(self._geometry)


class PositionHarness(QWidget):
    _constrain_position_to_screen = PetWindow._constrain_position_to_screen


class ScaleHarness(QWidget):
    _live2d_size = PetWindow._live2d_size
    set_live2d_scale = PetWindow.set_live2d_scale

    def __init__(self):
        super().__init__()
        self._pixel_mode = False
        self._live2d_scale = 100
        self._live2d_model_format = ""

    def _sync_compact_ai_window(self):
        pass


class FakeConfig:
    def __init__(self, data):
        self.data = dict(data)

    def load(self):
        pass

    def save(self):
        pass

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def get_model_action_profile(self, _character, _costume):
        return {}

    def set_model_action_profile(self, _character, _costume, _profile):
        pass


class FakeModelManager:
    def get_model_json_path(self, character, costume):
        return f"/models/{character}/{costume}/model.json"


class FakeLive2DWidget:
    _drag_locked = False


class SaveConfigHarness(QWidget):
    _save_config = PetWindow._save_config
    _save_position_config = PetWindow._save_position_config
    _sync_current_model_entry = PetWindow._sync_current_model_entry
    _current_model_entry = PetWindow._current_model_entry
    _configured_model_count = PetWindow._configured_model_count
    _with_saved_action_profile = PetWindow._with_saved_action_profile
    _persist_runtime_config = PetWindow._persist_runtime_config

    def __init__(self):
        super().__init__()
        self._cfg = FakeConfig({
            "models": [{
                "character": "kasumi",
                "costume": "new_costume",
                "path": "/models/kasumi/new_costume/model.json",
            }],
            "dark_theme": "system",
        })
        self._model_manager = FakeModelManager()
        self._live2d_widget = FakeLive2DWidget()
        self._current_char = "kasumi"
        self._current_costume = "old_costume"
        self._fps = 120
        self._opacity = 1.0
        self._vsync = True
        self._live2d_quality = "balanced"
        self._live2d_scale = 100
        self._live2d_hit_alpha_threshold = 8
        self._live2d_lip_sync_max_open = 1.0
        self._pixel_mode = False
        self._show_pos_set = False
        self._startup_position_restore_pending = False
        self._restoring_saved_position = False
        self._settings_models_updated = True
        self._runtime_save_failure_reported = False
        self._tray_icon = None

    def _window_placement(self):
        return {"x": self.x(), "y": self.y()}


class PetWindowPositioningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_full_constraint_recovers_window_from_right_and_bottom_edges(self):
        harness = PositionHarness()
        harness.resize(400, 500)
        screen = FakeScreen(QRect(0, 0, 1920, 1080))

        self.assertEqual(
            (1520, 580),
            harness._constrain_position_to_screen(
                1900,
                1000,
                screen,
                allow_partial=False,
            ),
        )

    def test_full_constraint_handles_window_larger_than_screen(self):
        harness = PositionHarness()
        harness.resize(2400, 3000)
        screen = FakeScreen(QRect(100, 50, 1920, 1080))

        self.assertEqual(
            (100, 50),
            harness._constrain_position_to_screen(
                -1000,
                -1000,
                screen,
                allow_partial=False,
            ),
        )

    def test_scaling_keeps_saved_window_position(self):
        harness = ScaleHarness()
        harness.resize(400, 500)
        harness.move(1700, 900)

        harness.set_live2d_scale(200)

        self.assertEqual((800, 1000), (harness.width(), harness.height()))
        self.assertEqual((1700, 900), (harness.x(), harness.y()))

    def test_moc3_size_uses_taller_window(self):
        harness = ScaleHarness()
        harness._live2d_model_format = MODEL_FORMAT_MOC3

        self.assertEqual((400, LIVE2D_MOC3_BASE_HEIGHT), harness._live2d_size())

    def test_save_config_does_not_rewrite_models_after_remote_model_update(self):
        harness = SaveConfigHarness()

        harness._save_config()

        self.assertEqual(
            [{
                "character": "kasumi",
                "costume": "new_costume",
                "path": "/models/kasumi/new_costume/model.json",
            }],
            harness._cfg.get("models"),
        )

    def test_pet_window_vsync_initializes_from_config(self):
        source = inspect.getsource(PetWindow.__init__)

        self.assertIn('config_manager.get("vsync", True)', source)
        self.assertNotIn("self._vsync = True", source)

    def test_pet_window_save_config_does_not_rewrite_display_settings(self):
        source = inspect.getsource(PetWindow._save_config)

        for key in ("fps", "opacity", "dark_theme", "vsync", "live2d_quality", "live2d_scale"):
            self.assertNotIn(f'self._cfg.set("{key}"', source)

    def test_position_save_only_updates_position_fields(self):
        harness = SaveConfigHarness()
        harness._cfg = FakeConfig({
            "models": [{
                "character": "kasumi",
                "costume": "old_costume",
                "path": "/models/kasumi/old_costume/model.json",
                "default_motion": "idle",
            }],
            "language": "zh_CN",
            "drag_locked": False,
            "live2d_hit_alpha_threshold": 3,
        })
        harness._show_pos_set = True
        harness._settings_models_updated = False
        harness._live2d_widget._drag_locked = True
        harness._live2d_hit_alpha_threshold = 8
        harness.resize(456, 567)
        harness.move(123, 234)

        harness._save_position_config()

        self.assertEqual("zh_CN", harness._cfg.get("language"))
        self.assertFalse(harness._cfg.get("drag_locked"))
        self.assertEqual(3, harness._cfg.get("live2d_hit_alpha_threshold"))
        self.assertEqual(123, harness._cfg.get("window_x"))
        self.assertEqual(234, harness._cfg.get("window_y"))
        self.assertEqual(456, harness._cfg.get("window_width"))
        self.assertEqual(567, harness._cfg.get("window_height"))
        self.assertEqual(
            {
                "character": "kasumi",
                "costume": "old_costume",
                "path": "/models/kasumi/old_costume/model.json",
                "default_motion": "idle",
                "window_x": 123,
                "window_y": 234,
                "window_width": 456,
                "window_height": 567,
                "window_placement": {"x": 123, "y": 234},
            },
            harness._cfg.get("models")[0],
        )


if __name__ == "__main__":
    unittest.main()
