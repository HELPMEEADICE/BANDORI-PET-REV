import sys
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LIVE2D_PACKAGE = os.path.join(BASE_DIR, "third_party", "live2d-py", "package")
if LIVE2D_PACKAGE not in sys.path:
    sys.path.insert(0, LIVE2D_PACKAGE)

from PySide6.QtCore import Qt, QProcess
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
        pet_window_ref["vsync"] = data.get("vsync", True)

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
        pet._live2d_widget.set_vsync(pet_window_ref.get("vsync", cfg.get("vsync", True)))
        if cfg.get("drag_locked", False):
            pet._live2d_widget.set_drag_locked(True)
        pet_window_ref["window"] = pet

    settings_process_ref = {}

    def read_settings_output(process):
        data = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            if line.startswith("MODEL\t"):
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    on_model_selected(parts[1], parts[2])
            elif line.startswith("SETTINGS\t"):
                try:
                    on_settings_changed(json.loads(line.split("\t", 1)[1]))
                except json.JSONDecodeError:
                    pass
            elif line == "LAUNCH":
                launch_pet()

    def read_settings_error(process):
        data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            print(data)

    def clear_settings_process(process):
        if settings_process_ref.get("process") is process:
            settings_process_ref.pop("process", None)
        process.deleteLater()

    def launch_settings_process(show_launch=True):
        script = os.path.join(BASE_DIR, "settings_process.py")
        process = QProcess(app)
        process.setProgram(sys.executable)
        process.setArguments([
            script,
            "--character", char,
            "--costume", costume,
            "--fps", str(cfg.get("fps", 120)),
            "--opacity", str(cfg.get("opacity", 1.0)),
            "--vsync", "1" if cfg.get("vsync", True) else "0",
            "--show-launch", "1" if show_launch else "0",
            "--start-on-costumes", "0",
        ])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(lambda p=process: read_settings_output(p))
        process.readyReadStandardError.connect(lambda p=process: read_settings_error(p))
        process.finished.connect(lambda *args, p=process: clear_settings_process(p))
        settings_process_ref["process"] = process
        process.start()

    model_valid = bool(
        char and costume
        and char in mgr.characters
        and ModelManager.get_model_json_path(char, costume)
    )

    if not model_valid:
        if mgr.characters:
            char = mgr.characters[0]
            costume = mgr.get_default_costume(char)

    app.aboutToQuit.connect(save_config)

    if model_valid:
        pet_window_ref["char"] = char
        pet_window_ref["costume"] = costume
        pet_window_ref["vsync"] = cfg.get("vsync", True)
        launch_pet()
    else:
        launch_settings_process(show_launch=True)

    ret = app.exec()
    live2d.dispose()
    return ret


def isDarkTheme():
    from qfluentwidgets import isDarkTheme as _is_dark
    return _is_dark()


if __name__ == "__main__":
    sys.exit(main())
