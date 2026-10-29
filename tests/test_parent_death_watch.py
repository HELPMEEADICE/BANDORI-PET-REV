from pathlib import Path


def test_parent_death_watch_uses_windows_process_handle():
    source = Path("bandori_core/process_utils.py").read_text(encoding="utf-8")

    assert "def _install_windows_parent_handle_watch" in source
    assert 'if os.name == "nt":' in source
    assert "on_parent_death" in source
    assert "kernel32.OpenProcess" in source
    assert "kernel32.WaitForSingleObject" in source
    assert "BandoriPetParentDeathWatch" in source


def test_native_pet_watches_parent_and_restarts_main_only_for_primary_role():
    source = Path("native/pet_backend/src/main.rs").read_text(encoding="utf-8")
    assert "!parent_alive(self.args.parent)" in source
    assert "self.args.index == 0" in source
    assert 'env_remove("BANDORI_PET_IPC_SERVER_NAME")' in source
    assert "GetExitCodeProcess" in source


def test_native_shutdown_runs_before_parent_death_relaunch():
    source = Path("native/pet_backend/src/main.rs").read_text(encoding="utf-8")
    shutdown = source.index("if self.shutdown")
    parent = source.index("!parent_alive(self.args.parent)")
    assert shutdown < parent
    assert '"SHUTDOWN" => self.shutdown = true' in source


def test_windows_tray_icon_gets_periodic_reshow_timer():
    source = Path("bandori_ui/tray_utils.py").read_text(encoding="utf-8")

    assert 'sys.platform.startswith("win")' in source
    assert "_bandori_visibility_timer" in source
    assert "timer.timeout.connect(lambda: reshow(0))" in source
