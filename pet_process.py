import argparse
import json
import os
import subprocess
import sys
import threading

from process_utils import (
    bootstrap_app,
    ensure_xwayland,
    hidden_subprocess_kwargs,
    install_parent_death_watch,
    process_program_and_args,
    set_windows_app_user_model_id,
)

BASE_DIR, _STARTUP_CONFIG = bootstrap_app()

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app_theme import apply_app_theme
from app_info import APP_NAME
from i18n_manager import detect_system_language, set_language
from live2d_widget import Live2DWidget
from live2d_lua_adapter import live2d
from model_manager import ModelManager, models_dir_exists, prompt_download_model_resources
from mcp_bridge import close_mcp_clients
from pet_window import PetWindow
from gpu_acceleration import configure_qt_gpu_acceleration
from tray_utils import load_tray_icon


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one isolated Live2D pet process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--costume", required=True)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--group-characters", default="")
    return parser.parse_args()


def _parse_group_characters(value: str) -> list[str]:
    try:
        parsed = json.loads(value) if value else []
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result = []
    seen = set()
    for item in parsed:
        character = str(item or "").strip()
        if character and character not in seen:
            result.append(character)
            seen.add(character)
    return result


def _make_main_relauncher(index: int, normal_shutdown_requested: threading.Event):
    restarted = threading.Event()

    def _relaunch_main_if_abnormal_parent_exit():
        if index != 0 or normal_shutdown_requested.is_set() or restarted.is_set():
            return
        restarted.set()
        env = os.environ.copy()
        env.pop("BANDORI_PET_IPC_SERVER_NAME", None)
        env["BANDORI_PET_RESTARTED_FROM_CHILD"] = "1"
        program, arguments = process_program_and_args(BASE_DIR, "main.py", [])
        try:
            subprocess.Popen(
                [program, *arguments],
                cwd=BASE_DIR,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **hidden_subprocess_kwargs(),
            )
        except OSError as exc:
            print(f"Failed to restart main process after parent exit: {exc}", file=sys.stderr)

    return _relaunch_main_if_abnormal_parent_exit


class SingleModelManager:
    def __init__(self, character: str, costume: str, model_path: str):
        self._character = character
        self._costume = costume
        self._model_path = model_path
        self._fallback_manager = None

    @property
    def characters(self) -> list[str]:
        return [self._character] if self._character else []

    def get_default_costume(self, character: str) -> str:
        return self._costume if character == self._character else ""

    def get_model_json_path(self, character: str, costume: str) -> str:
        if character == self._character and costume == self._costume:
            return self._model_path
        if self._fallback_manager is None:
            self._fallback_manager = ModelManager()
        return self._fallback_manager.get_model_json_path(character, costume)

    def get_model_format(self, character: str, costume: str) -> str:
        path = self.get_model_json_path(character, costume)
        if not path:
            return ""
        if self._fallback_manager is None:
            self._fallback_manager = ModelManager(scan_models=False)
        return self._fallback_manager._model_format_from_path(path)

    def get_display_name(self, character: str) -> str:
        if self._fallback_manager is None:
            self._fallback_manager = ModelManager()
        return self._fallback_manager.get_display_name(character)

    def get_costume_display_name(self, character: str, costume_id: str) -> str:
        if self._fallback_manager is None:
            self._fallback_manager = ModelManager()
        return self._fallback_manager.get_costume_display_name(character, costume_id)


def main():
    ensure_xwayland()
    os.chdir(BASE_DIR)
    args = _parse_args()
    cfg = _STARTUP_CONFIG
    set_language(cfg.get("language", "") or detect_system_language())

    configure_qt_gpu_acceleration(QApplication, Qt, cfg)
    Live2DWidget.configure_default_surface_format(cfg.get("vsync", True))
    set_windows_app_user_model_id(APP_NAME)

    app = QApplication(sys.argv)
    app.setWindowIcon(load_tray_icon())
    normal_shutdown_requested = threading.Event()
    install_parent_death_watch(
        app,
        on_parent_death=_make_main_relauncher(args.index, normal_shutdown_requested),
    )

    import macos_patch
    macos_patch.hide_dock_icon_if_needed()

    app.setApplicationName(f"{APP_NAME}-{args.character}")
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    apply_app_theme(cfg.get("dark_theme", False))

    if not args.model_path and not models_dir_exists():
        prompt_download_model_resources()
        return 0

    mgr = SingleModelManager(args.character, args.costume, args.model_path) if args.model_path else ModelManager()
    group_characters = (
        _parse_group_characters(args.group_characters)
        if args.group_characters
        else None
    )
    pet = PetWindow(
        live2d,
        model_manager=mgr,
        character=args.character,
        costume=args.costume,
        fps=cfg.get("fps", 120),
        opacity=cfg.get("opacity", 1.0),
        config_manager=cfg,
        enable_tray=False,
        group_characters=group_characters,
        on_shutdown_requested=normal_shutdown_requested.set,
    )

    offset_x = args.index * (28 if pet._pixel_mode else 36)
    pet.restore_saved_position(offset_x=offset_x)

    pet.set_vsync(cfg.get("vsync", True))
    if cfg.get("drag_locked", False):
        pet._live2d_widget.set_drag_locked(True)
        pet._pixel_widget.set_drag_locked(True)

    app.aboutToQuit.connect(lambda: pet._close_radial_menu_process(force=True))
    app.aboutToQuit.connect(lambda: pet._close_chat_process())
    app.aboutToQuit.connect(lambda: pet._close_compact_ai_window())
    app.aboutToQuit.connect(close_mcp_clients)
    app.aboutToQuit.connect(lambda: pet._close_settings_process())
    app.aboutToQuit.connect(pet._send_ipc_unregistration)
    app.aboutToQuit.connect(pet._close_ipc_bus)
    app.aboutToQuit.connect(pet._save_position_config)
    app.aboutToQuit.connect(pet._flush_save)
    app.aboutToQuit.connect(live2d.dispose)

    if not cfg.get("hide_live2d_model", False):
        pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
