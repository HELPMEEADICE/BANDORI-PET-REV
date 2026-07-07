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
