import argparse
import json
import os
import sys

from process_utils import (
    app_base_dir,
    app_icon_path,
    bootstrap_app,
    ensure_taskbar_icon_identity,
    install_parent_death_watch,
    set_windows_app_user_model_id,
)

BASE_DIR, _STARTUP_CONFIG = bootstrap_app()

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from i18n_manager import detect_system_language, set_language
from model_manager import ModelManager
from settings_window import SettingsWindow
from app_theme import apply_app_theme
from app_info import APP_NAME
from live2d_widget import Live2DWidget
from gpu_acceleration import configure_qt_gpu_acceleration
from ipc_bus import (
    attach_main_ipc_queues,
    start_ipc_heartbeat,
)
from shared_memory_ipc import (
    decode_ipc_envelope,
    encode_ipc_envelope,
    make_peer_id,
)


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the settings window in an isolated process.")
    parser.add_argument("--character", default="")
    parser.add_argument("--costume", default="")
    parser.add_argument("--fps", type=int, default=120)
    parser.add_argument("--opacity", type=float, default=1.0)
    parser.add_argument("--vsync", choices=("0", "1"), default="1")
    parser.add_argument("--show-launch", choices=("0", "1"), default="0")
    parser.add_argument("--start-on-costumes", choices=("0", "1"), default="0")
    parser.add_argument("--first-run-wizard", choices=("0", "1"), default="0")
    return parser.parse_args()


def _apply_app_icon(app: QApplication) -> None:
    icon_path = app_icon_path()
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


def main():
    os.chdir(BASE_DIR)
    args = _parse_args()

    cfg = _STARTUP_CONFIG
    set_language(cfg.get("language", "") or detect_system_language())

    configure_qt_gpu_acceleration(QApplication, Qt, cfg)
    Live2DWidget.configure_default_surface_format()

    app_user_model_id = f"{APP_NAME}.Settings"
    if not ensure_taskbar_icon_identity(app_user_model_id, "BandoriPet Settings", BASE_DIR):
        app_user_model_id = APP_NAME
    set_windows_app_user_model_id(app_user_model_id)

    app = QApplication(sys.argv)
    install_parent_death_watch(app)

    import macos_patch
    macos_patch.hide_dock_icon_if_needed()
    app.setApplicationName(f"{APP_NAME}Settings")
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(True)
    _apply_app_icon(app)

    apply_app_theme(cfg.get("dark_theme", False))

    ipc_peer_id = make_peer_id("settings")
    ipc = {"inbound": None, "broadcast": None}
    ipc_queue = []

    def _stdout_fallback_line(line: str):
        if line.startswith(("MODEL\t", "SETTINGS\t")) or line in {"LAUNCH", "EXIT"}:
            print(line, flush=True)

    def flush_ipc_queue() -> bool:
        if not attach_main_ipc_queues(ipc):
            return False
        while ipc_queue:
            line = ipc_queue.pop(0)
            if not ipc["inbound"].publish(encode_ipc_envelope(ipc_peer_id, line)):
                ipc_queue.insert(0, line)
                return False
        return True

    def send_ipc_line(line: str):
        if line.startswith("MODEL\t") and args.show_launch == "0":
            line += "\tRELAUNCH"
        ipc_queue.append(line)
        if not flush_ipc_queue():
            try:
                ipc_queue.remove(line)
            except ValueError:
                pass
            _stdout_fallback_line(line)

    mgr = ModelManager()
    window = SettingsWindow(
        mgr,
        current_char=args.character,
        current_costume=args.costume,
        current_fps=args.fps,
        current_opacity=args.opacity,
        show_launch=args.show_launch == "1",
        start_on_costumes=args.start_on_costumes == "1",
        first_run_wizard=args.first_run_wizard == "1",
        config_manager=cfg,
        vsync=args.vsync == "1",
        live2d_module=None,
    )
    window.connect_ipc_output(send_ipc_line)

    def poll_ipc_messages():
        if not attach_main_ipc_queues(ipc):
            return
        flush_ipc_queue()
        for raw_line in ipc["broadcast"].read_available(max_messages=200):
            envelope = decode_ipc_envelope(raw_line)
            if envelope.exclude_peer_id == ipc_peer_id:
                continue
            line = envelope.line
            if line.startswith("SETTINGS\t"):
                try:
                    payload = json.loads(line.split("\t", 1)[1])
                except Exception:
                    continue
                window.apply_remote_settings(payload)
            elif line.startswith("SHOW_COSTUMES"):
                parts = line.split("\t", 1)
                character = parts[1].strip() if len(parts) == 2 else ""
                window.show_costume_picker(character)
            elif line == "SHUTDOWN":
                QTimer.singleShot(0, window.close)

    def send_ipc_heartbeat():
        send_ipc_line("REGISTER\tSETTINGS")

    start_ipc_heartbeat(app, send_ipc_heartbeat, poll_ipc_messages)
    app.aboutToQuit.connect(lambda: [q.close() for q in ipc.values() if q is not None])
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    screen = app.primaryScreen()
    if screen:
        geo = screen.availableGeometry()
        window.move(
            geo.left() + (geo.width() - window.width()) // 2,
            geo.top() + (geo.height() - window.height()) // 2,
        )

    def bring_window_to_front():
        window.showNormal()
        window.raise_()
        window.activateWindow()
        macos_patch.activate_app_ignoring_other_apps()

    window.show()
    if sys.platform == "darwin":
        for delay in (0, 150, 500, 1200):
            QTimer.singleShot(delay, bring_window_to_front)
    else:
        bring_window_to_front()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
