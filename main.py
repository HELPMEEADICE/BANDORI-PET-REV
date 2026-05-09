import sys
import os
import json

from process_utils import app_base_dir, process_program_and_args

BASE_DIR = str(app_base_dir())

LIVE2D_PACKAGE = os.path.join(BASE_DIR, "third_party", "live2d-py", "package")
if LIVE2D_PACKAGE not in sys.path:
    sys.path.insert(0, LIVE2D_PACKAGE)

from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from qfluentwidgets import setTheme, Theme

import live2d.v2 as live2d
from platform_patch import PatchedPlatformManager
from live2d_widget import Live2DWidget
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
    Live2DWidget.configure_default_surface_format()

    app = QApplication(sys.argv)
    app.setApplicationName("BandoriPet")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)

    theme = Theme.DARK if cfg.get("dark_theme", False) else Theme.LIGHT
    setTheme(theme)

    mgr = ModelManager()
    pet_window_ref = {"processes": []}

    char = cfg.get("character", "")
    costume = cfg.get("costume", "")

    from i18n_manager import current_language

    tray_icon = None

    def init_tray():
        nonlocal tray_icon
        tray_icon = QSystemTrayIcon(app)
        icon_path = os.path.join(BASE_DIR, "logo.ico")
        tray_icon.setIcon(QIcon(icon_path) if os.path.exists(icon_path) else QIcon())
        tray_icon.setToolTip("BandoriPet")

        menu = QMenu()
        settings_action = menu.addAction("设置")
        settings_action.triggered.connect(lambda: launch_settings_process(show_launch=False))
        exit_action = menu.addAction("退出")
        exit_action.triggered.connect(quit_all)
        tray_icon.setContextMenu(menu)
        tray_icon.activated.connect(lambda reason: launch_settings_process(show_launch=False) if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray_icon.show()

    def quit_all():
        close_pet_processes()
        if tray_icon is not None:
            tray_icon.hide()
        app.quit()

    def configured_models():
        models = cfg.get("models", [])
        result = []
        seen = set()
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_char = item.get("character", "")
                model_costume = item.get("costume", "")
                if model_char in seen or model_char not in mgr.characters:
                    continue
                if not model_costume:
                    model_costume = mgr.get_default_costume(model_char)
                path = ModelManager.get_model_json_path(model_char, model_costume)
                if not path:
                    continue
                entry = dict(item)
                entry.update({"character": model_char, "costume": model_costume, "path": path})
                result.append(entry)
                seen.add(model_char)
        if not result and char and costume and ModelManager.get_model_json_path(char, costume):
            result.append({"character": char, "costume": costume, "path": ModelManager.get_model_json_path(char, costume)})
        return result

    def save_config():
        cfg.set("language", current_language())
        cfg.save()

    def close_pet_processes():
        for process in list(pet_window_ref.get("processes", [])):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.terminate()
                if not process.waitForFinished(1500):
                    process.kill()
        pet_window_ref["processes"] = []

    def on_model_selected(char, costume):
        pet_window_ref["char"] = char
        pet_window_ref["costume"] = costume

    def on_settings_changed(data):
        pet_window_ref["fps"] = data.get("fps", 120)
        pet_window_ref["opacity"] = data.get("opacity", 1.0)
        pet_window_ref["dark"] = data.get("dark_theme", False)
        pet_window_ref["vsync"] = data.get("vsync", True)

    def launch_pet():
        if pet_window_ref.get("dark", False):
            setTheme(Theme.DARK)
            cfg.set("dark_theme", True)
        if "fps" in pet_window_ref:
            cfg.set("fps", pet_window_ref["fps"])
        if "opacity" in pet_window_ref:
            cfg.set("opacity", pet_window_ref["opacity"])
        if "vsync" in pet_window_ref:
            cfg.set("vsync", pet_window_ref["vsync"])
        cfg.save()
        models = configured_models()
        selected_char = pet_window_ref.get("char")
        selected_costume = pet_window_ref.get("costume")
        if selected_char and selected_costume and selected_char not in {m["character"] for m in models}:
            path = ModelManager.get_model_json_path(selected_char, selected_costume)
            if path:
                models.append({"character": selected_char, "costume": selected_costume, "path": path})
        pet_window_ref["processes"] = []
        for idx, model in enumerate(models):
            process = QProcess(app)
            program, arguments = process_program_and_args(BASE_DIR, "pet_process.py", [
                "--character", model["character"],
                "--costume", model["costume"],
                "--index", str(idx),
            ])
            process.setProgram(program)
            process.setArguments(arguments)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardError.connect(lambda p=process: read_pet_error(p))
            process.finished.connect(lambda *args, p=process: clear_pet_process(p))
            pet_window_ref["processes"].append(process)
            process.start()

    def read_pet_error(process):
        data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            print(data)

    def clear_pet_process(process):
        processes = pet_window_ref.get("processes", [])
        if process in processes:
            processes.remove(process)
        process.deleteLater()

    settings_process_ref = {}

    def read_settings_output(process):
        data = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        buffer = settings_process_ref.get("stdout_buffer", "") + data
        lines = buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            settings_process_ref["stdout_buffer"] = lines.pop()
        else:
            settings_process_ref["stdout_buffer"] = ""
        for raw_line in lines:
            line = raw_line.rstrip("\r\n")
            if line.startswith("MODEL\t"):
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    on_model_selected(parts[1], parts[2])
            elif line.startswith("SETTINGS\t"):
                try:
                    cfg.load()
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
            buffered = settings_process_ref.get("stdout_buffer", "")
            if buffered:
                for line in buffered.splitlines():
                    if line.startswith("MODEL\t"):
                        parts = line.split("\t", 2)
                        if len(parts) == 3:
                            on_model_selected(parts[1], parts[2])
                    elif line.startswith("SETTINGS\t"):
                        try:
                            cfg.load()
                            on_settings_changed(json.loads(line.split("\t", 1)[1]))
                        except json.JSONDecodeError:
                            pass
                    elif line == "LAUNCH":
                        launch_pet()
            settings_process_ref.pop("process", None)
            settings_process_ref.pop("stdout_buffer", None)
        process.deleteLater()

    def launch_settings_process(show_launch=True):
        existing = settings_process_ref.get("process")
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            return
        process = QProcess(app)
        program, arguments = process_program_and_args(BASE_DIR, "settings_process.py", [
            "--character", char,
            "--costume", costume,
            "--fps", str(cfg.get("fps", 120)),
            "--opacity", str(cfg.get("opacity", 1.0)),
            "--vsync", "1" if cfg.get("vsync", True) else "0",
            "--show-launch", "1" if show_launch else "0",
            "--start-on-costumes", "0",
        ])
        process.setProgram(program)
        process.setArguments(arguments)
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

    init_tray()

    app.aboutToQuit.connect(save_config)
    app.aboutToQuit.connect(close_pet_processes)

    if configured_models() or model_valid:
        pet_window_ref["char"] = char
        pet_window_ref["costume"] = costume
        pet_window_ref["vsync"] = cfg.get("vsync", True)
        launch_pet()
    else:
        launch_settings_process(show_launch=True)

    ret = app.exec()
    return ret


def isDarkTheme():
    from qfluentwidgets import isDarkTheme as _is_dark
    return _is_dark()


if __name__ == "__main__":
    sys.exit(main())
