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

from config_manager import ConfigManager
from i18n_manager import detect_system_language, set_language
from model_manager import ModelManager
from settings_window import SettingsWindow
from app_theme import apply_app_theme
import live2d.v2 as live2d
from platform_patch import PatchedPlatformManager


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the settings window in an isolated process.")
    parser.add_argument("--character", default="")
    parser.add_argument("--costume", default="")
    parser.add_argument("--fps", type=int, default=120)
    parser.add_argument("--opacity", type=float, default=1.0)
    parser.add_argument("--vsync", choices=("0", "1"), default="1")
    parser.add_argument("--show-launch", choices=("0", "1"), default="0")
    parser.add_argument("--start-on-costumes", choices=("0", "1"), default="0")
    return parser.parse_args()


def main():
    os.chdir(BASE_DIR)
    args = _parse_args()

    cfg = ConfigManager()
    set_language(cfg.get("language", "") or detect_system_language())

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)

    app = QApplication(sys.argv)
    app.setApplicationName("BandoriPetSettings")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(True)

    apply_app_theme(cfg.get("dark_theme", False))

    live2d.init()
    live2d.Live2DFramework.setPlatformManager(
        PatchedPlatformManager(live2d.Live2DFramework.getPlatformManager())
    )

    mgr = ModelManager()
    window = SettingsWindow(
        mgr,
        current_char=args.character,
        current_costume=args.costume,
        current_fps=args.fps,
        current_opacity=args.opacity,
        show_launch=args.show_launch == "1",
        start_on_costumes=args.start_on_costumes == "1",
        config_manager=cfg,
        vsync=args.vsync == "1",
        live2d_module=live2d,
    )
    window.connect_ipc_output()
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    screen = app.primaryScreen()
    if screen:
        geo = screen.availableGeometry()
        window.move((geo.width() - window.width()) // 2, (geo.height() - window.height()) // 2)

    window.show()
    ret = app.exec()
    live2d.dispose()
    return ret


if __name__ == "__main__":
    sys.exit(main())
