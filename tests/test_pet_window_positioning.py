import os
import inspect
import json
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget

from model_manager import MODEL_FORMAT_MOC3
import pet_window as pet_window_module
from pet_window import LIVE2D_MOC3_BASE_HEIGHT, PetWindow


class FakeScreen:
    def __init__(self, geometry: QRect):
        self._geometry = geometry

    def availableGeometry(self):
        return QRect(self._geometry)


class PositionHarness(QWidget):
    _constrain_position_to_screen = PetWindow._constrain_position_to_screen


class PeerDragHarness(QWidget):
    _handle_peer_drag = PetWindow._handle_peer_drag
    _finish_received_peer_drag = PetWindow._finish_received_peer_drag

    def __init__(self):
        super().__init__()
        self._move_all_roles_together = True
        self._current_char = "kasumi"
        self._startup_position_restore_pending = True
        self._startup_transient_position_set = True
        self._suppress_compact_ai_sync = False
        self._peer_drag_states = {}
        self._completed_peer_drag_sessions = {}
        self.compact_moves = []

    def _move_unconstrained(self, x, y):
        self.move(x, y)

    def _move_compact_ai_with_pet(self, dx, dy):
        self.compact_moves.append((dx, dy))


class LocalDragHarness(QWidget):
    _on_drag = PetWindow._on_drag
    _on_peer_drag_started = PetWindow._on_peer_drag_started
    _on_peer_drag_finished = PetWindow._on_peer_drag_finished
    _broadcast_peer_drag = PetWindow._broadcast_peer_drag

    def __init__(self):
        super().__init__()
        self._move_all_roles_together = True
        self._current_char = "kasumi"
        self._active_peer_drag_id = ""
        self._active_peer_drag_total_x = 0
        self._active_peer_drag_total_y = 0
        self._drag_anchor_ratio = None
        self._emotion_window_anim = None
        self._emotion_window_animating = False
        self._startup_position_restore_pending = False
        self._startup_transient_position_set = False
        self._suppress_compact_ai_sync = False
        self.sent = []

    def _note_user_interaction(self):
        pass

    def _refresh_topmost_for_interaction(self):
        pass

    def _move_unconstrained(self, x, y):
        self.move(x, y)

    def _move_compact_ai_with_pet(self, _dx, _dy):
        pass

    def _send_ipc(self, line):
        self.sent.append(line)
        return True

    def _capture_native_drag_anchor(self):
        pass

    def _reanchor_window_to_drag_cursor(self):
        return False

    def _sync_drag_anchor_after_window_change(self, *, force=False):
        pass


class NativeDragAnchorHarness:
    _capture_native_drag_anchor = PetWindow._capture_native_drag_anchor
    _reanchor_window_to_drag_cursor = PetWindow._reanchor_window_to_drag_cursor

    def __init__(self):
        self._current_char = "kasumi"
        self._drag_anchor_ratio = None
        self.cursor = QPoint()

    def winId(self):
        return 123

    def width(self):
        return 300

    def height(self):
        return 375

    def _native_cursor_pos(self):
        return QPoint(self.cursor)


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

    def test_peer_drag_can_follow_across_screen_boundary(self):
        harness = PeerDragHarness()
        harness.move(1800, 400)

        harness._handle_peer_drag({"character": "ran", "dx": 300, "dy": -50})

        self.assertEqual((2100, 350), (harness.x(), harness.y()))
        self.assertEqual([(300, -50)], harness.compact_moves)
        self.assertFalse(harness._startup_position_restore_pending)
        self.assertFalse(harness._startup_transient_position_set)

    def test_peer_drag_uses_latest_cumulative_offset_after_message_loss(self):
        harness = PeerDragHarness()
        harness.move(100, 200)

        harness._handle_peer_drag({
            "character": "ran",
            "drag_id": "drag-1",
            "total_dx": 5,
            "total_dy": 10,
        })
        harness._handle_peer_drag({
            "character": "ran",
            "drag_id": "drag-1",
            "total_dx": 120,
            "total_dy": -30,
        })

        self.assertEqual((220, 170), (harness.x(), harness.y()))

        harness._handle_peer_drag({
            "character": "ran",
            "drag_id": "drag-1",
            "total_dx": 150,
            "total_dy": -40,
        }, finished=True)
        self.assertEqual((250, 160), (harness.x(), harness.y()))

        harness._handle_peer_drag({
            "character": "ran",
            "drag_id": "drag-1",
            "total_dx": 80,
            "total_dy": -20,
        })
        self.assertEqual((250, 160), (harness.x(), harness.y()))

    def test_local_drag_sends_cumulative_update_and_reliable_final_state(self):
        harness = LocalDragHarness()
        harness.move(50, 60)
        harness._on_peer_drag_started()

        harness._on_drag(30, -10)
        harness._on_drag(20, 15)
        harness._on_peer_drag_finished()

        self.assertEqual((100, 65), (harness.x(), harness.y()))
        self.assertEqual(3, len(harness.sent))
        self.assertTrue(harness.sent[0].startswith("PEER_DRAG\t"))
        self.assertTrue(harness.sent[1].startswith("PEER_DRAG\t"))
        self.assertTrue(harness.sent[2].startswith("PEER_DRAG_END\t"))
        payloads = [json.loads(line.split("\t", 1)[1]) for line in harness.sent]
        self.assertEqual((30, -10), (payloads[0]["total_dx"], payloads[0]["total_dy"]))
        self.assertEqual((50, 5), (payloads[1]["total_dx"], payloads[1]["total_dy"]))
        self.assertEqual(payloads[1], payloads[2])

    @unittest.skipUnless(os.name == "nt", "native drag anchoring is Windows-specific")
    def test_native_drag_anchor_keeps_same_relative_point_across_dpi_resize(self):
        harness = NativeDragAnchorHarness()
        harness.cursor = QPoint(250, 450)
        current_rect = [100, 200, 475, 669]
        set_window_pos_calls = []

        def get_window_rect(_hwnd, rect_pointer):
            rect = rect_pointer._obj
            rect.left, rect.top, rect.right, rect.bottom = current_rect
            return True

        def set_window_pos(hwnd, insert_after, x, y, width, height, flags):
            set_window_pos_calls.append(
                (hwnd, insert_after, x, y, width, height, flags)
            )
            return True

        with (
            patch.object(pet_window_module, "_get_window_rect", get_window_rect),
            patch.object(pet_window_module, "_set_window_pos", set_window_pos),
        ):
            harness._capture_native_drag_anchor()
            self.assertAlmostEqual(0.4, harness._drag_anchor_ratio[0])
            self.assertAlmostEqual(250 / 469, harness._drag_anchor_ratio[1])

            # The native window becomes 300x375 on the other-DPR screen. The
            # same relative point must remain under the physical cursor.
            current_rect[:] = [500, 300, 800, 675]
            harness.cursor = QPoint(900, 800)
            self.assertTrue(harness._reanchor_window_to_drag_cursor())

        self.assertEqual(1, len(set_window_pos_calls))
        _hwnd, _after, x, y, width, height, flags = set_window_pos_calls[0]
        self.assertEqual((780, 600), (x, y))
        self.assertEqual((0, 0), (width, height))
        self.assertEqual(
            pet_window_module.SWP_NOSIZE
            | pet_window_module.SWP_NOZORDER
            | pet_window_module.SWP_NOACTIVATE,
            flags,
        )

    def test_scaling_keeps_saved_window_position(self):
        harness = ScaleHarness()
        harness.resize(400, 500)
        harness.move(1700, 900)

        harness.set_live2d_scale(200)

        self.assertEqual((800, 1000), (harness.width(), harness.height()))
        self.assertEqual((800, 1000), (harness.minimumWidth(), harness.minimumHeight()))
        self.assertEqual((800, 1000), (harness.maximumWidth(), harness.maximumHeight()))
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

    def test_screen_scale_refresh_is_driven_by_screen_changed(self):
        move_source = inspect.getsource(PetWindow.moveEvent)
        show_source = inspect.getsource(PetWindow.showEvent)
        screen_source = inspect.getsource(PetWindow._on_window_screen_changed)

        self.assertNotIn("refresh_screen_scale", move_source)
        self.assertIn("_ensure_screen_scale_tracking", show_source)
        self.assertIn("_screen_scale_refresh_timer.start()", screen_source)

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
