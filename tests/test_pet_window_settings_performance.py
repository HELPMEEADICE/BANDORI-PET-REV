from pathlib import Path


SOURCE = Path("pet_window.py").read_text(encoding="utf-8")


def _apply_settings_block() -> str:
    return SOURCE.split("    def _apply_settings(self, data: dict):", 1)[1].split("    def _live2d_size", 1)[0]


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
