import argparse
import json
import os
import sys

from process_utils import app_base_dir, configure_debug_logging, install_parent_death_watch, ipc_server_name, set_windows_app_user_model_id

configure_debug_logging()

BASE_DIR = str(app_base_dir())

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from config_manager import ConfigManager
from i18n_manager import detect_system_language, set_language
from model_manager import ModelManager
from settings_window import SettingsWindow
from app_theme import apply_app_theme
from live2d_widget import Live2DWidget


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
    icon_path = os.path.join(BASE_DIR, "logo.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


def main():
    os.chdir(BASE_DIR)
    args = _parse_args()

    cfg = ConfigManager()
    set_language(cfg.get("language", "") or detect_system_language())

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if sys.platform != "darwin":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    Live2DWidget.configure_default_surface_format()

    set_windows_app_user_model_id("BandoriPet.Settings")

    app = QApplication(sys.argv)
    install_parent_death_watch(app)

    if sys.platform == "darwin":
        import macos_patch
        macos_patch.hide_dock_icon()
    app.setApplicationName("BandoriPetSettings")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(True)
    _apply_app_icon(app)

    apply_app_theme(cfg.get("dark_theme", False))

    ipc_socket = QLocalSocket(app)
    ipc_socket.connectToServer(ipc_server_name())

    def send_ipc_line(line: str):
        if line.startswith("MODEL\t") and args.show_launch == "0":
            line += "\tRELAUNCH"
        if ipc_socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            ipc_socket.connectToServer(ipc_server_name())
        if ipc_socket.state() != QLocalSocket.LocalSocketState.ConnectedState:
            ipc_socket.waitForConnected(200)
        if ipc_socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
            ipc_socket.write((line + "\n").encode("utf-8"))
            ipc_socket.flush()
            ipc_socket.waitForBytesWritten(200)

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

    ipc_inbound = {"buffer": ""}

    def on_ipc_ready():
        try:
            ipc_inbound["buffer"] += bytes(ipc_socket.readAll()).decode("utf-8", "ignore")
        except Exception:
            return
        while "\n" in ipc_inbound["buffer"]:
            line, ipc_inbound["buffer"] = ipc_inbound["buffer"].split("\n", 1)
            line = line.rstrip("\r")
            if line.startswith("SETTINGS\t"):
                try:
                    payload = json.loads(line.split("\t", 1)[1])
                except Exception:
                    continue
                window.apply_remote_settings(payload)

    ipc_socket.readyRead.connect(on_ipc_ready)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    screen = app.primaryScreen()
    if screen:
        geo = screen.availableGeometry()
        window.move((geo.width() - window.width()) // 2, (geo.height() - window.height()) // 2)

    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
