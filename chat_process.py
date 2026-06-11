import argparse
import json
import os
import sys

from process_utils import (
    app_base_dir,
    configure_debug_logging,
    ensure_windows_app_user_model_shortcut,
    install_parent_death_watch,
    ipc_server_name,
    set_windows_app_user_model_id,
)

configure_debug_logging()

BASE_DIR = str(app_base_dir())
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

from PySide6.QtCore import QLockFile, QRect, Qt
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QApplication

from app_theme import apply_app_theme
from app_info import APP_NAME
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


def _chat_lock_path() -> str:
    runtime_dir = os.path.join(BASE_DIR, ".runtime")
    os.makedirs(runtime_dir, exist_ok=True)
    server_name = ipc_server_name() or APP_NAME
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in server_name)
    return os.path.join(runtime_dir, f"{safe_name}-chat.lock")


def _send_ipc_line(line: str, timeout_ms: int = 300):
    socket = QLocalSocket()
    socket.connectToServer(ipc_server_name())
    if socket.state() != QLocalSocket.LocalSocketState.ConnectedState:
        socket.waitForConnected(timeout_ms)
    if socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
        socket.write((line + "\n").encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()


def _app_icon_path() -> str:
    icon_path = os.path.join(BASE_DIR, "logo.ico")
    return icon_path if os.path.exists(icon_path) else ""


def _ensure_taskbar_icon_identity(app_id: str) -> bool:
    if sys.platform != "win32":
        return True
    icon_path = _app_icon_path()
    target_path = sys.executable
    arguments = ""
    if getattr(sys, "frozen", False):
        candidate = os.path.join(BASE_DIR, "BandoriPet.exe")
        if os.path.exists(candidate):
            target_path = candidate
    else:
        arguments = f'"{os.path.join(BASE_DIR, "main.py")}"'
    return ensure_windows_app_user_model_shortcut(
        app_id,
        "BandoriPet Chat",
        icon_path,
        target_path=target_path,
        arguments=arguments,
        working_dir=BASE_DIR,
    )


def _apply_app_icon(app: QApplication) -> QIcon:
    icon_path = _app_icon_path()
    icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    return icon


def main():
    os.chdir(BASE_DIR)
    args = _parse_args()

    cfg = ConfigManager()
    lang = cfg.get("language", "") or detect_system_language()
    set_language(lang)

    app_user_model_id = f"{APP_NAME}.Chat"
    if not _ensure_taskbar_icon_identity(app_user_model_id):
        app_user_model_id = APP_NAME
    set_windows_app_user_model_id(app_user_model_id)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    install_parent_death_watch(app)

    chat_lock = QLockFile(_chat_lock_path())
    if not chat_lock.tryLock(100):
        _send_ipc_line("FOCUS_CHAT")
        return 0

    normal_window_mode = bool(cfg.get("chat_window_normal_window", False))

    if sys.platform == "darwin" and not normal_window_mode:
        import macos_patch
        macos_patch.hide_dock_icon()
    app.setApplicationName("BandoriPetChat")
    app.setApplicationDisplayName("BandoriPet Chat")
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app_icon = _apply_app_icon(app)

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
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.action_triggered.connect(window.emit_action_for_ipc)
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.closed.connect(app.quit)

    shutdown_socket = QLocalSocket(app)
    shutdown_buffer = {"text": ""}

    def focus_window():
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    def read_shutdown_messages():
        shutdown_buffer["text"] += bytes(shutdown_socket.readAll()).decode("utf-8", errors="ignore")
        lines = shutdown_buffer["text"].splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            shutdown_buffer["text"] = lines.pop()
        else:
            shutdown_buffer["text"] = ""
        for line in (item.rstrip("\r\n") for item in lines):
            if line == "SHUTDOWN":
                window.close()
                break
            if line == "FOCUS_CHAT":
                focus_window()
            if line.startswith("POKE_USER\t"):
                try:
                    window.handle_external_user_poke(json.loads(line.split("\t", 1)[1]))
                except Exception:
                    window.handle_external_user_poke({})

    def register_chat_window():
        shutdown_socket.write(f"REGISTER\tCHAT\t{args.character}\n".encode("utf-8"))
        shutdown_socket.flush()

    shutdown_socket.connected.connect(register_chat_window)
    shutdown_socket.readyRead.connect(read_shutdown_messages)
    shutdown_socket.connectToServer(ipc_server_name())

    window.show()
    saved_x = cfg.get("chat_window_x")
    saved_y = cfg.get("chat_window_y")
    saved_w = cfg.get("chat_window_width")
    saved_h = cfg.get("chat_window_height")
    if None in (saved_x, saved_y, saved_w, saved_h):
        window.position_next_to_pet(QRect(args.pet_x, args.pet_y, args.pet_w, args.pet_h))

    ret = app.exec()
    chat_lock.unlock()
    return ret


if __name__ == "__main__":
    sys.exit(main())
