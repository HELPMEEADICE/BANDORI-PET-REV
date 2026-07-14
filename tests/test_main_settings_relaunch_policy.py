from pathlib import Path


def _main_source() -> str:
    return Path("main.py").read_text(encoding="utf-8")


def test_settings_relaunch_uses_runtime_model_signature():
    source = _main_source()
    settings_block = source.split("    def on_settings_changed(data):", 1)[1].split("    def launch_pet", 1)[0]

    assert "selected_model_changed" in settings_block
    assert "models_runtime_changed" in settings_block
    assert "new_models_signature != old_models_signature" in settings_block


def test_settings_relaunch_no_longer_triggers_for_any_models_payload():
    source = _main_source()
    settings_block = source.split("    def on_settings_changed(data):", 1)[1].split("    def launch_pet", 1)[0]

    assert 'or "models" in data' not in settings_block
    assert "selected_model_changed\n            or models_runtime_changed" in settings_block


def test_vsync_change_relaunches_active_pets_to_recreate_the_gl_surface():
    source = _main_source()
    settings_block = source.split("    def on_settings_changed(data):", 1)[1].split("    def launch_pet", 1)[0]

    assert 'old_vsync = bool(cfg.get("vsync", True))' in settings_block
    assert 'vsync_changed = "vsync" in data and requested_vsync != old_vsync' in settings_block
    assert "or vsync_changed" in settings_block
