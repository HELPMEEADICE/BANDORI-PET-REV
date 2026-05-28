import argparse
import json
import os
import sys

from process_utils import app_base_dir, configure_debug_logging, ipc_server_name

configure_debug_logging()

from PySide6.QtCore import QRect, Qt
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from app_theme import apply_app_theme
from chat_window import ChatWindow
from config_manager import ConfigManager
from i18n_manager import detect_system_language, set_language
from model_manager import ModelManager, models_dir_exists, prompt_download_model_resources


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the LLM chat window in an isolated process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--pet-x", type=int, required=True)
    parser.add_argument("--pet-y", type=int, required=True)
    parser.add_argument("--pet-w", type=int, required=True)
    parser.add_argument("--pet-h", type=int, required=True)
    parser.add_argument("--group-characters", default="")
    return parser.parse_args()


def _normalize_characters(characters, valid_characters: set[str], current_character: str = "") -> list[str]:
    result = []
    seen = set()
    if not isinstance(characters, list):
        characters = []
    for item in characters:
        character = str(item or "").strip()
        if not character or character in seen or character not in valid_characters:
            continue
        result.append(character)
        seen.add(character)
    if current_character and current_character in valid_characters and current_character not in seen:
        result.insert(0, current_character)
    return result


def _parse_group_characters(value: str, valid_characters: set[str], current_character: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return _normalize_characters(parsed, valid_characters, current_character)


def main():
    os.chdir(app_base_dir())
    args = _parse_args()

    cfg = ConfigManager()
    lang = cfg.get("language", "") or detect_system_language()
    set_language(lang)

    app = QApplication(sys.argv)
    install_parent_death_watch(app)

    if sys.platform == "darwin":
        import macos_patch
        macos_patch.hide_dock_icon()
    app.setApplicationName("BandoriPetChat")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)

    apply_app_theme(cfg.get("dark_theme", False))

    if not models_dir_exists():
        prompt_download_model_resources()
        return 0

    mgr = ModelManager(scan_models=False)
    valid_characters = set(mgr.characters)
    characters = _parse_group_characters(args.group_characters, valid_characters, args.character)
    if not characters:
        models = cfg.get("models", [])
        model_characters = []
        if isinstance(models, list):
            model_characters = [
                item.get("character", "")
                for item in models
                if isinstance(item, dict)
            ]
        characters = _normalize_characters(model_characters, valid_characters, args.character)

    window = ChatWindow(args.character, mgr, None, cfg, group_characters=characters if len(characters) > 1 else None)
    window.action_triggered.connect(window.emit_action_for_ipc)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
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
    cfg.load()
    cfg.save()
    return ret


if __name__ == "__main__":
    sys.exit(main())
