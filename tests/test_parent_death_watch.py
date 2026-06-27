from pathlib import Path


def test_parent_death_watch_uses_windows_process_handle():
    source = Path("process_utils.py").read_text(encoding="utf-8")

    assert "def _install_windows_parent_handle_watch" in source
    assert 'if os.name == "nt":' in source
    assert "on_parent_death" in source
    assert "kernel32.OpenProcess" in source
    assert "kernel32.WaitForSingleObject" in source
    assert "BandoriPetParentDeathWatch" in source


def test_pet_process_restarts_main_on_abnormal_parent_exit():
    source = Path("pet_process.py").read_text(encoding="utf-8")

    assert "install_parent_death_watch(" in source
    assert "on_parent_death=_make_main_relauncher(args.index, normal_shutdown_requested)" in source
    assert 'env.pop("BANDORI_PET_IPC_SERVER_NAME", None)' in source
    assert 'process_program_and_args(BASE_DIR, "main.py", [])' in source
    assert "if index != 0 or normal_shutdown_requested.is_set() or restarted.is_set():" in source


def test_pet_shutdown_ipc_disables_parent_restart():
    process_source = Path("pet_process.py").read_text(encoding="utf-8")
    window_source = Path("pet_window.py").read_text(encoding="utf-8")

    assert "on_shutdown_requested=normal_shutdown_requested.set" in process_source
    assert "on_shutdown_requested=None" in window_source
    assert "self._on_shutdown_requested = on_shutdown_requested" in window_source
    assert "if callable(self._on_shutdown_requested):" in window_source


def test_windows_tray_icon_gets_periodic_reshow_timer():
    source = Path("tray_utils.py").read_text(encoding="utf-8")

    assert 'sys.platform.startswith("win")' in source
    assert "_bandori_visibility_timer" in source
    assert "timer.timeout.connect(lambda: reshow(0))" in source
