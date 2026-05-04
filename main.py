import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LIVE2D_PACKAGE = os.path.join(BASE_DIR, "third_party", "live2d-py", "package")
if LIVE2D_PACKAGE not in sys.path:
    sys.path.insert(0, LIVE2D_PACKAGE)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from qfluentwidgets import setTheme, Theme

import live2d.v2 as live2d
from platform_patch import PatchedPlatformManager
from model_manager import ModelManager


def main():
    live2d.init()

    live2d.Live2DFramework.setPlatformManager(
        PatchedPlatformManager(live2d.Live2DFramework.getPlatformManager())
    )

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)

    app = QApplication(sys.argv)
    app.setApplicationName("BandoriPet")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)

    setTheme(Theme.LIGHT)

    mgr = ModelManager()
    pet_window_ref = {}

    def on_model_selected(char, costume):
        pet_window_ref["char"] = char
        pet_window_ref["costume"] = costume

    def on_settings_changed(data):
        pet_window_ref["fps"] = data.get("fps", 120)
        pet_window_ref["opacity"] = data.get("opacity", 1.0)
        pet_window_ref["dark"] = data.get("dark_theme", False)

    def launch_pet():
        from pet_window import PetWindow
        if pet_window_ref.get("dark", False):
            setTheme(Theme.DARK)
        pet = PetWindow(
            live2d,
            model_manager=mgr,
            character=pet_window_ref.get("char", ""),
            costume=pet_window_ref.get("costume", ""),
            fps=pet_window_ref.get("fps", 120),
            opacity=pet_window_ref.get("opacity", 1.0),
        )
        pet.show()
        pet_window_ref["window"] = pet

    from settings_window import SettingsWindow
    settings = SettingsWindow(mgr)
    settings.model_selected.connect(on_model_selected)
    settings.settings_changed.connect(on_settings_changed)
    settings.launch_requested.connect(launch_pet)

    screen = app.primaryScreen()
    if screen:
        geo = screen.availableGeometry()
        settings.move(
            (geo.width() - settings.width()) // 2,
            (geo.height() - settings.height()) // 2
        )

    settings.show()

    ret = app.exec()
    live2d.dispose()
    return ret


if __name__ == "__main__":
    sys.exit(main())
