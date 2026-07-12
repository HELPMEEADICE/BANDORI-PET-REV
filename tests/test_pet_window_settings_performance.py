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
