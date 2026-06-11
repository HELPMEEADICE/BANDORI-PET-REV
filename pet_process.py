import argparse
import json
import os
import sys

from process_utils import app_base_dir, configure_debug_logging, ensure_xwayland, install_parent_death_watch
from config_manager import ConfigManager
from gpu_acceleration import configure_qt_opengl_environment, is_gpu_acceleration_enabled

configure_debug_logging()

BASE_DIR = str(app_base_dir())
_STARTUP_CONFIG = ConfigManager()
configure_qt_opengl_environment(is_gpu_acceleration_enabled(_STARTUP_CONFIG))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app_theme import apply_app_theme
from app_info import APP_NAME
from i18n_manager import current_language, detect_system_language, set_language
from live2d_widget import Live2DWidget
from live2d_lua_adapter import live2d
from model_manager import ModelManager, models_dir_exists, prompt_download_model_resources
from pet_window import PetWindow
from gpu_acceleration import configure_qt_gpu_acceleration


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

    def get_display_name(self, character: str) -> str:
        return character.title()

    def get_costume_display_name(self, character: str, costume_id: str) -> str:
        return costume_id


def _model_entry(cfg: ConfigManager, character: str) -> dict:
    models = cfg.get("models", [])
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and item.get("character") == character:
                return item
    return {}


def main():
    ensure_xwayland()
    os.chdir(BASE_DIR)
    args = _parse_args()
    cfg = _STARTUP_CONFIG
    set_language(cfg.get("language", "") or detect_system_language())

    configure_qt_gpu_acceleration(QApplication, Qt, cfg)
    Live2DWidget.configure_default_surface_format()

    app = QApplication(sys.argv)
    install_parent_death_watch(app)

    if sys.platform == "darwin":
        import macos_patch
        macos_patch.hide_dock_icon()

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
    )

    offset_x = args.index * (28 if pet._pixel_mode else 36)
    pet.restore_saved_position(offset_x=offset_x)

    pet._live2d_widget.set_vsync(cfg.get("vsync", True))
    if cfg.get("drag_locked", False):
        pet._live2d_widget.set_drag_locked(True)
        pet._pixel_widget.set_drag_locked(True)

    app.aboutToQuit.connect(lambda: cfg.set("language", current_language()))
    app.aboutToQuit.connect(pet._save_config)
    app.aboutToQuit.connect(live2d.dispose)

    if not cfg.get("hide_live2d_model", False):
        pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
