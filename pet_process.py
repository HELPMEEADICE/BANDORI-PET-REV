import argparse
import os
import sys

from process_utils import app_base_dir

BASE_DIR = str(app_base_dir())
LIVE2D_PACKAGE = os.path.join(BASE_DIR, "third_party", "live2d-py", "package")
if LIVE2D_PACKAGE not in sys.path:
    sys.path.insert(0, LIVE2D_PACKAGE)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import live2d.v2 as live2d
from app_theme import apply_app_theme
from config_manager import ConfigManager
from i18n_manager import current_language, detect_system_language, set_language
from live2d_widget import Live2DWidget
from model_manager import ModelManager
from pet_window import PetWindow
from platform_patch import PatchedPlatformManager


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one isolated Live2D pet process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--costume", required=True)
    parser.add_argument("--index", type=int, default=0)
    return parser.parse_args()


def _model_entry(cfg: ConfigManager, character: str) -> dict:
    models = cfg.get("models", [])
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and item.get("character") == character:
                return item
    return {}


def main():
    os.chdir(BASE_DIR)
    args = _parse_args()
    cfg = ConfigManager()
    set_language(cfg.get("language", "") or detect_system_language())

    live2d.init()
    live2d.Live2DFramework.setPlatformManager(
        PatchedPlatformManager(live2d.Live2DFramework.getPlatformManager())
    )

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    Live2DWidget.configure_default_surface_format()
    app = QApplication(sys.argv)
    app.setApplicationName(f"BandoriPet-{args.character}")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)
    apply_app_theme(cfg.get("dark_theme", False))

    mgr = ModelManager()
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
        w = entry.get("window_width", cfg.get("window_width", 400))
        h = entry.get("window_height", cfg.get("window_height", 500))
        if x >= 0 and y >= 0:
            pet.resize(w, h)
            pet.move(x + args.index * 36 if "window_x" not in entry else x, y)
            pet._show_pos_set = True

    pet._live2d_widget.set_vsync(cfg.get("vsync", True))
    if cfg.get("drag_locked", False):
        pet._live2d_widget.set_drag_locked(True)
        pet._pixel_widget.set_drag_locked(True)

    app.aboutToQuit.connect(lambda: cfg.set("language", current_language()))
    app.aboutToQuit.connect(pet._save_config)
    app.aboutToQuit.connect(live2d.dispose)

    pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
