from pathlib import Path


def test_tray_exit_defers_quit_until_context_menu_unwinds():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "exit_action.triggered.connect(lambda: QTimer.singleShot(0, quit_all))" in source


def test_main_shutdown_uses_cooperative_nonblocking_process_close():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "notify_child_processes_shutdown()" in source
    assert "QTimer.singleShot(50, _quit_when_reminders_stop)" in source
    assert "app.aboutToQuit.connect(notify_child_processes_shutdown)" in source
    assert "app.aboutToQuit.connect(lambda: close_settings_process(force=False, wait=False))" in source
    assert "app.aboutToQuit.connect(lambda: close_pet_processes(force=False, wait=False))" in source


def test_main_force_exit_watchdog_does_not_depend_on_qt_event_loop():
    source = Path("main.py").read_text(encoding="utf-8")
    quit_source = source.split("    def quit_all():", 1)[1].split("    def init_ipc_server", 1)[0]
    assert "threading.Timer" in quit_source
    assert "QTimer.singleShot(1500, _force_exit)" not in quit_source
    assert "scheduler.has_running_workers()" in quit_source


def test_napcat_reply_overlay_requires_successful_send():
    source = Path("main.py").read_text(encoding="utf-8")
    finished = source.split("        def _on_finished(full_text", 1)[1].split("        def _on_error", 1)[0]
    assert "reply_sent = client.send_reply(" in finished
    assert "if reply_sent:" in finished


def test_napcat_timeout_suppresses_late_reply_and_has_cleanup_fallback():
    source = Path("main.py").read_text(encoding="utf-8")
    reply_flow = source.split("    def _napcat_generate_reply", 1)[1].split("    def read_ipc_messages", 1)[0]
    assert 'cleanup_state["timed_out"] = True' in reply_flow
    assert 'if cleanup_state["timed_out"]:' in reply_flow
    assert "force_cleanup_timer.timeout.connect(_force_timeout_cleanup)" in reply_flow
    assert "worker.terminate()" in reply_flow


def test_settings_process_handles_shutdown_ipc():
    source = Path("settings_process.py").read_text(encoding="utf-8")
    assert 'elif line == "SHUTDOWN":' in source
    assert "QTimer.singleShot(0, window.close)" in source


def test_chat_process_uses_immediate_shutdown_path():
    process_source = Path("chat_process.py").read_text(encoding="utf-8")
    window_source = Path("chat_window/chat_window.py").read_text(encoding="utf-8")
    assert "window.request_immediate_shutdown()" in process_source
    assert "def request_immediate_shutdown(self):" in window_source
    assert "if self._immediate_shutdown:" in window_source


def test_settings_apply_does_not_block_on_flush_before_close():
    settings_source = Path("settings_window/settings_window.py").read_text(encoding="utf-8")
    apply_source = settings_source.split("    def _on_apply(self):", 1)[1].split("    def connect_ipc_output", 1)[0]
    main_source = Path("main.py").read_text(encoding="utf-8")

    assert "flush_save()" not in apply_source
    assert "cfg.save()" in main_source.split("    def on_settings_changed(data):", 1)[1].split("    def launch_pet", 1)[0]
    assert "launch_pet(persist_config=False)" in main_source.split('        elif line == "LAUNCH":', 1)[1].split('        elif line == "EXIT":', 1)[0]
