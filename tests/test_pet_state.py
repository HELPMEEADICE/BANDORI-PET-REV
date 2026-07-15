import json

from ipc_bus import is_reliable_ipc_line
from pet_state import persist_pet_window_state


class ConfigHarness:
    def __init__(self, values):
        self.values = dict(values)
        self.load_count = 0
        self.save_count = 0

    def load(self):
        self.load_count += 1

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.save_count += 1


def state_line(character="ran", model_path="ran/model.json"):
    return "PET_STATE\t" + json.dumps({
        "character": character,
        "model_path": model_path,
        "x": 120,
        "y": -40,
        "width": 400,
        "height": 500,
        "drag_locked": True,
        "placement": {"screen_name": "right", "relative_x": 0.25},
    })


def test_pet_state_is_reliable_and_updates_only_matching_multi_pet_entry():
    config = ConfigHarness({
        "window_x": -1,
        "models": [
            {"character": "kasumi", "path": "kasumi/model.json"},
            {"character": "ran", "path": "ran/model.json"},
        ],
    })

    assert is_reliable_ipc_line(state_line())
    assert persist_pet_window_state(config, state_line())
    assert "window_x" not in config.values["models"][0]
    assert config.values["models"][1]["window_x"] == 120
    assert config.values["models"][1]["window_y"] == -40
    assert config.values["models"][1]["window_placement"]["screen_name"] == "right"
    assert config.values["window_x"] == -1
    assert config.values["drag_locked"] is True
    assert config.save_count == 1


def test_single_pet_state_keeps_legacy_top_level_position_compatible():
    config = ConfigHarness({
        "models": [{"character": "ran", "path": "ran/model.json"}],
    })

    assert persist_pet_window_state(config, state_line())
    assert config.values["window_x"] == 120
    assert config.values["window_height"] == 500
    assert config.save_count == 1


def test_pixel_pet_state_keeps_live2d_geometry_and_saves_pixel_position():
    config = ConfigHarness({
        "window_x": 20,
        "window_width": 400,
        "models": [{
            "character": "ran",
            "path": "ran/model.json",
            "window_x": 20,
            "window_width": 400,
        }],
    })
    state = json.loads(state_line().split("\t", 1)[1])
    state["pet_mode"] = "pixel"
    state["width"] = 128
    state["height"] = 128

    assert persist_pet_window_state(
        config, "PET_STATE\t" + json.dumps(state)
    )
    assert config.values["pet_mode"] == "pixel"
    assert config.values["pixel_window_x"] == 120
    assert config.values["window_x"] == 20
    assert config.values["models"][0]["pixel_window_y"] == -40
    assert config.values["models"][0]["window_width"] == 400


def test_unknown_multi_pet_and_malformed_states_are_not_persisted():
    config = ConfigHarness({
        "models": [
            {"character": "kasumi", "path": "kasumi/model.json"},
            {"character": "ran", "path": "ran/model.json"},
        ],
    })

    assert not persist_pet_window_state(config, state_line("aya", "aya/model.json"))
    assert not persist_pet_window_state(config, "PET_STATE\tnot-json")
    assert config.save_count == 0
