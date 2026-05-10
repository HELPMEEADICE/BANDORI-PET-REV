import argparse
import os
import sys

from process_utils import app_base_dir, ipc_server_name

from PySide6.QtCore import QRect, Qt
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from fluent_silencer import import_qfluentwidgets

_qfluentwidgets = import_qfluentwidgets(lambda: __import__(
    "qfluentwidgets", fromlist=["Theme", "setTheme"]
))
Theme = _qfluentwidgets.Theme
setTheme = _qfluentwidgets.setTheme

from chat_window import ChatWindow
from config_manager import ConfigManager
from i18n_manager import current_language, detect_system_language, set_language
from model_manager import ModelManager


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the LLM chat window in an isolated process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--pet-x", type=int, required=True)
    parser.add_argument("--pet-y", type=int, required=True)
    parser.add_argument("--pet-w", type=int, required=True)
    parser.add_argument("--pet-h", type=int, required=True)
    return parser.parse_args()


def main():
    os.chdir(app_base_dir())
    args = _parse_args()

    cfg = ConfigManager()
    lang = cfg.get("language", "") or detect_system_language()
    set_language(lang)

    app = QApplication(sys.argv)
    app.setApplicationName("BandoriPetChat")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(True)

    setTheme(Theme.DARK if cfg.get("dark_theme", False) else Theme.LIGHT)

    mgr = ModelManager()
    models = cfg.get("models", [])
    characters = []
    seen = set()
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict):
                character = item.get("character", "")
                if character and character not in seen and character in mgr.characters:
                    characters.append(character)
                    seen.add(character)
    if args.character and args.character not in seen and args.character in mgr.characters:
        characters.insert(0, args.character)

    window = ChatWindow(args.character, mgr, None, cfg, group_characters=characters if len(characters) > 1 else None)
    window.action_triggered.connect(window.emit_action_for_ipc)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.closed.connect(lambda: cfg.set("language", current_language()))
    window.closed.connect(app.quit)

    shutdown_socket = QLocalSocket(app)

    def read_shutdown_messages():
        for line in bytes(shutdown_socket.readAll()).decode("utf-8", errors="ignore").splitlines():
            if line == "SHUTDOWN":
                window.close()
                break

    shutdown_socket.readyRead.connect(read_shutdown_messages)
    shutdown_socket.connectToServer(ipc_server_name())

    window.show()
    window.position_next_to_pet(QRect(args.pet_x, args.pet_y, args.pet_w, args.pet_h))

    ret = app.exec()
    cfg.save()
    return ret


if __name__ == "__main__":
    sys.exit(main())
