import argparse
import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication

from qfluentwidgets import Theme, setTheme

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
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    args = _parse_args()

    cfg = ConfigManager()
    lang = cfg.get("language", "") or detect_system_language()
    set_language(lang)

    app = QApplication(sys.argv)
    app.setApplicationName("BandoriPetChat")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(True)

    setTheme(Theme.DARK if cfg.get("dark_theme", False) else Theme.LIGHT)

    window = ChatWindow(args.character, ModelManager(), None, cfg)
    window.action_triggered.connect(window.emit_action_for_ipc)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.closed.connect(lambda: cfg.set("language", current_language()))

    window.show()
    window.position_next_to_pet(QRect(args.pet_x, args.pet_y, args.pet_w, args.pet_h))

    ret = app.exec()
    cfg.save()
    return ret


if __name__ == "__main__":
    sys.exit(main())
