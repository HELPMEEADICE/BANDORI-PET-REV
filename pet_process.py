import argparse
import os
import sys

from process_utils import app_base_dir, ensure_xwayland

BASE_DIR = str(app_base_dir())

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app_theme import apply_app_theme
from config_manager import ConfigManager
from i18n_manager import current_language, detect_system_language, set_language
from live2d_widget import Live2DWidget
from live2d_lua_adapter import live2d
from model_manager import ModelManager, models_dir_exists, prompt_download_model_resources
from pet_window import PetWindow


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one isolated Live2D pet process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--costume", required=True)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--index", type=int, default=0)
    return parser.parse_args()


class SingleModelManager:
    def __init__(self, character: str, costume: str, model_path: str):
        self._character = character
        self._costume = costume
        self._model_path = model_path

    @property
    def characters(self) -> list[str]:
        return [self._character] if self._character else []

    def get_default_costume(self, character: str) -> str:
        return self._costume if character == self._character else ""

    def get_model_json_path(self, character: str, costume: str) -> str:
        if character == self._character and costume == self._costume:
            return self._model_path
        return ModelManager.get_model_json_path(character, costume)

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
    cfg = ConfigManager()
    set_language(cfg.get("language", "") or detect_system_language())

    live2d.init()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if sys.platform != "darwin":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    Live2DWidget.configure_default_surface_format()

    app = QApplication(sys.argv)

    if sys.platform == "darwin":
        import macos_patch
        macos_patch.hide_dock_icon()

    app.setApplicationName(f"BandoriPet-{args.character}")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)
    apply_app_theme(cfg.get("dark_theme", False))

    if not args.model_path and not models_dir_exists():
        prompt_download_model_resources()
        return 0

    mgr = SingleModelManager(args.character, args.costume, args.model_path) if args.model_path else ModelManager()
    pet = PetWindow(
        live2d,
        model_manager=mgr,
        character=args.character,
        costume=args.costume,
        fps=cfg.get("fps", 120),
        opacity=cfg.get("opacity", 1.0),
        config_manager=cfg,
        enable_tray=False,
    )

    entry = _model_entry(cfg, args.character)
    if pet._pixel_mode:
        x = entry.get("pixel_window_x", cfg.get("pixel_window_x", -1))
        y = entry.get("pixel_window_y", cfg.get("pixel_window_y", -1))
        if x >= 0 and y >= 0:
            pet.move(x + args.index * 28 if "pixel_window_x" not in entry else x, y)
            pet._show_pos_set = True
    else:
        x = entry.get("window_x", cfg.get("window_x", -1))
        y = entry.get("window_y", cfg.get("window_y", -1))
        if x >= 0 and y >= 0:
            pet.move(x + args.index * 36 if "window_x" not in entry else x, y)
            pet._show_pos_set = True

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
