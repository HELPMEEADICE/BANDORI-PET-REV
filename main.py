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
from config_manager import ConfigManager
from i18n_manager import set_language, detect_system_language


def main():
    cfg = ConfigManager()

    lang = cfg.get("language", "")
    if not lang:
        lang = detect_system_language()
    set_language(lang)

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

    theme = Theme.DARK if cfg.get("dark_theme", False) else Theme.LIGHT
    setTheme(theme)

    mgr = ModelManager()
    pet_window_ref = {}

    char = cfg.get("character", "")
    costume = cfg.get("costume", "")

    from i18n_manager import current_language

    def save_config():
        cfg.set("language", current_language())
        pw = pet_window_ref.get("window")
        if pw:
            cfg.set("character", pw._current_char)
            cfg.set("costume", pw._current_costume)
            cfg.set("fps", pw._fps)
            cfg.set("opacity", pw._opacity)
            cfg.set("dark_theme", isDarkTheme())
            cfg.set("window_x", pw.x())
            cfg.set("window_y", pw.y())
            cfg.set("window_width", pw.width())
            cfg.set("window_height", pw.height())
        cfg.save()

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
            character=pet_window_ref.get("char", char),
            costume=pet_window_ref.get("costume", costume),
            fps=pet_window_ref.get("fps", cfg.get("fps", 120)),
            opacity=pet_window_ref.get("opacity", cfg.get("opacity", 1.0)),
            config_manager=cfg,
        )
        x = cfg.get("window_x", -1)
        y = cfg.get("window_y", -1)
        w = cfg.get("window_width", 400)
        h = cfg.get("window_height", 500)
        if x >= 0 and y >= 0:
            pet.resize(w, h)
            pet.move(x, y)
            pet._show_pos_set = True
        pet.show()
        if cfg.get("drag_locked", False):
            pet._live2d_widget.set_drag_locked(True)
        pet_window_ref["window"] = pet

    model_valid = bool(
        char and costume
        and char in mgr.characters
        and ModelManager.get_model_json_path(char, costume)
    )

    if not model_valid:
        if mgr.characters:
            char = mgr.characters[0]
            costume = mgr.get_default_costume(char)
    else:
        pet_window_ref["char"] = char
        pet_window_ref["costume"] = costume

    app.aboutToQuit.connect(save_config)

    if model_valid:
        launch_pet()
    else:
        from settings_window import SettingsWindow
        settings = SettingsWindow(
            mgr,
            current_char=char,
            current_costume=costume,
            current_fps=cfg.get("fps", 120),
            current_opacity=cfg.get("opacity", 1.0),
            show_launch=True,
            config_manager=cfg,
        )
        if cfg.get("dark_theme", False):
            settings._theme_switch.setChecked(True)

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


def isDarkTheme():
    from qfluentwidgets import isDarkTheme as _is_dark
    return _is_dark()


if __name__ == "__main__":
    sys.exit(main())
