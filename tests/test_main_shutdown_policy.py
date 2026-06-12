from pathlib import Path


def test_main_shutdown_does_not_wait_for_pet_processes():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "app.aboutToQuit.connect(lambda: close_pet_processes(force=False, wait=False))" in source


def test_main_shutdown_does_not_wait_for_settings_process():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "app.aboutToQuit.connect(lambda: close_settings_process(force=False, wait=False))" in source
