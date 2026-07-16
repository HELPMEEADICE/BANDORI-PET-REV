from pathlib import Path
from types import SimpleNamespace

from pet_window import PetWindow


SOURCE = Path("pet_window.py").read_text(encoding="utf-8")


def _apply_settings_block() -> str:
    return SOURCE.split("    def _apply_settings(", 1)[1].split("    def _live2d_size", 1)[0]


def test_action_only_settings_do_not_restart_full_live2d_prewarm():
    block = _apply_settings_block()

    assert "models_runtime_changed" in block
    assert "if models_runtime_changed:" in block
    assert "self._restart_live2d_action_prewarm()" in block
    assert "elif \"models\" in data or \"model_action_settings\" in data:" in block


def test_action_only_settings_still_force_restores_default_motion():
    block = _apply_settings_block()

    assert "elif \"models\" in data or \"model_action_settings\" in data:" in block
    assert "force_clear=True" in block


def test_settings_apply_does_not_reload_or_rewrite_persisted_config():
    block = _apply_settings_block()

    assert "self._cfg.load()" not in block
    assert "self._persist_runtime_config()" not in block
    assert "self._save_config()" not in block


def test_settings_ipc_loads_valid_payload_once_after_parsing():
    class Config:
        def __init__(self):
            self.loads = 0

        def get(self, key, default=None):
            if key == "models":
                return [{"character": "old", "costume": "default"}]
            return default

        def load(self):
            self.loads += 1

    received = []
    config = Config()
    harness = SimpleNamespace(
        _cfg=config,
        _models_runtime_signature=lambda models: tuple(
            (item.get("character"), item.get("costume")) for item in models
        ),
        _apply_settings=lambda data, signature: received.append((data, signature)),
    )

    PetWindow._handle_ipc_line(
        harness,
        'SETTINGS\t{"models":[{"character":"new","costume":"default"}]}',
    )

    assert config.loads == 1
    assert received == [(
        {"models": [{"character": "new", "costume": "default"}]},
        (("old", "default"),),
    )]


def test_invalid_settings_ipc_does_not_touch_config():
    config = SimpleNamespace(load=lambda: (_ for _ in ()).throw(AssertionError("unexpected load")))
    harness = SimpleNamespace(_cfg=config)

    PetWindow._handle_ipc_line(harness, "SETTINGS\t{broken")
    PetWindow._handle_ipc_line(harness, "SETTINGS\t[]")


def test_reset_positions_persists_position_once():
    calls = []
    timer = SimpleNamespace(stop=lambda: calls.append("stop"))
    harness = SimpleNamespace(
        _cfg=None,
        _sync_compact_ai_window=lambda **_kwargs: None,
        reset_position=lambda: calls.append("reset"),
        _position_save_timer=timer,
        _save_position_config=lambda: calls.append("save"),
    )

    PetWindow._apply_settings(harness, {"reset_pet_positions": True})

    assert calls == ["reset", "stop", "save"]


def test_action_prewarm_keeps_only_default_and_one_idle_motion():
    harness = SimpleNamespace(
        _live2d_widget=SimpleNamespace(model=object()),
        _current_motion_names=lambda: ["smile01", "idle01", "idle02", "wave01"],
        _current_model_entry=lambda: {"default_motion": "smile01"},
        _is_idle_motion_name=PetWindow._is_idle_motion_name,
    )

    assert PetWindow._build_live2d_prewarm_motion_queue(harness) == ["smile01", "idle01"]


def test_pixel_startup_does_not_load_live2d_model_first():
    calls = []
    harness = SimpleNamespace(
        _current_char="anon",
        _current_costume="live_01",
        _pixel_mode=True,
        _hide_live2d_model=False,
        _user_hidden_live2d_model=False,
        _model_manager=SimpleNamespace(
            get_model_json_path=lambda *_args: "anon.zst::live_01/model3.json",
            get_model_format=lambda *_args: "moc3",
        ),
        _set_live2d_model_format=lambda value: calls.append(("format", value)),
        _enable_pixel_mode=lambda save=False: calls.append(("pixel", save)) or True,
        _live2d_widget=SimpleNamespace(
            set_model_path=lambda path: calls.append(("live2d", path)),
        ),
        _update_tooltip=lambda: calls.append(("tooltip",)),
    )

    PetWindow._load_initial_model(harness)

    assert ("live2d", "anon.zst::live_01/model3.json") not in calls
    assert ("pixel", False) in calls
