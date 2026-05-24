import sys
import json
import threading

from process_utils import app_base_dir, ipc_server_name, process_program_and_args

BASE_DIR = str(app_base_dir())

from PySide6.QtCore import Qt, QObject, QProcess, Signal
from PySide6.QtNetwork import QLocalServer
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from live2d_widget import Live2DWidget
from model_manager import ModelManager, models_dir_exists, prompt_download_model_resources
from config_manager import ConfigManager
from i18n_manager import set_language, detect_system_language, tr as _tr
from app_theme import apply_app_theme
from ai_status_server import AiStatusHttpServer
from chat_integration_server import ChatIntegrationHttpServer
from database_manager import DatabaseManager
from tray_utils import keep_tray_icon_visible, load_tray_icon


class AiEventBridge(QObject):
    line_received = Signal(str)


def _clamp_ai_status_port(value) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        port = 38472
    return max(1024, min(65535, port))


def main():
    cfg = ConfigManager()

    lang = cfg.get("language", "")
    if not lang:
        lang = detect_system_language()
    set_language(lang)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    if sys.platform != "darwin":
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    Live2DWidget.configure_default_surface_format()

    app = QApplication(sys.argv)

    if sys.platform == "darwin":
        import macos_patch
        macos_patch.hide_dock_icon()
    app.setApplicationName("BandoriPet")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)

    apply_app_theme(cfg.get("dark_theme", False))

    if not models_dir_exists():
        prompt_download_model_resources()
        return 0

    mgr = ModelManager()
    pet_window_ref = {"processes": []}
    ipc_ref = {"clients": [], "buffers": {}}
    ai_status_ref = {"server": None}
    chat_integration_ref = {"server": None, "db": None, "lock": threading.RLock()}
    ai_event_bridge = AiEventBridge()

    char = cfg.get("character", "")
    costume = cfg.get("costume", "")

    from i18n_manager import current_language

    tray_icon = None
    tray_ref = {"menu": None, "actions": []}

    def init_tray():
        nonlocal tray_icon
        tray_icon = QSystemTrayIcon(app)
        tray_icon.setIcon(load_tray_icon())
        tray_icon.setToolTip(_tr("MainTray.tooltip"))

        menu = QMenu()
        settings_action = menu.addAction(_tr("MainTray.settings"))
        settings_action.triggered.connect(lambda: launch_settings_process(show_launch=False))
        exit_action = menu.addAction(_tr("MainTray.exit"))
        exit_action.triggered.connect(quit_all)
        tray_icon.setContextMenu(menu)
        tray_icon.activated.connect(on_tray_activated)
        tray_ref["menu"] = menu
        tray_ref["actions"] = [settings_action, exit_action]
        keep_tray_icon_visible(tray_icon)

    def on_tray_activated(reason: QSystemTrayIcon.ActivationReason):
        if sys.platform == "darwin":
            return
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            launch_settings_process(show_launch=False)

    def quit_all():
        notify_chat_processes_shutdown()
        stop_ai_status_server()
        stop_chat_integration_server()
        close_pet_processes(force=True)
        close_settings_process(force=True)
        if tray_icon is not None:
            tray_icon.hide()
        app.quit()

    def init_ipc_server():
        name = ipc_server_name()
        QLocalServer.removeServer(name)
        server = QLocalServer(app)

        def accept_clients():
            while server.hasPendingConnections():
                socket = server.nextPendingConnection()
                ipc_ref["clients"].append(socket)
                ipc_ref["buffers"][socket] = ""
                socket.readyRead.connect(lambda s=socket: read_ipc_client(s))
                socket.disconnected.connect(lambda s=socket: remove_ipc_client(s))

        server.newConnection.connect(accept_clients)
        if server.listen(name):
            ipc_ref["server"] = server

    def remove_ipc_client(socket):
        clients = ipc_ref.get("clients", [])
        if socket in clients:
            clients.remove(socket)
        ipc_ref.get("buffers", {}).pop(socket, None)
        if isValid(socket):
            socket.deleteLater()

    def write_ipc_line(socket, line: str):
        if not isValid(socket) or not socket.isOpen():
            return
        socket.write((line + "\n").encode("utf-8"))
        socket.flush()

    def broadcast_ipc_line(line: str):
        for socket in list(ipc_ref.get("clients", [])):
            write_ipc_line(socket, line)

    ai_event_bridge.line_received.connect(broadcast_ipc_line)

    def stop_ai_status_server():
        server = ai_status_ref.get("server")
        if server is not None:
            server.stop()
        ai_status_ref["server"] = None

    def stop_chat_integration_server():
        server = chat_integration_ref.get("server")
        if server is not None:
            server.stop()
        chat_integration_ref["server"] = None

    def close_chat_integration_db():
        db = chat_integration_ref.get("db")
        if db is not None:
            db.close()
        chat_integration_ref["db"] = None

    def init_ai_status_server():
        stop_ai_status_server()
        if not cfg.get("ai_status_port_enabled", False):
            return
        port = _clamp_ai_status_port(cfg.get("ai_status_port", 38472))
        token = cfg.get("ai_status_token") or ""

        def on_ai_event(event: dict):
            payload = json.dumps(event, ensure_ascii=False)
            ai_event_bridge.line_received.emit(f"AI_EVENT\t{payload}")

        try:
            server = AiStatusHttpServer(port, token, on_ai_event)
            server.start()
        except OSError as exc:
            print(f"AI status port failed to start on 127.0.0.1:{port}: {exc}")
            return
        ai_status_ref["server"] = server

    def chat_integration_db():
        db = chat_integration_ref.get("db")
        if db is None:
            db = DatabaseManager()
            chat_integration_ref["db"] = db
        return db

    def format_chat_overlay(summary: dict) -> str:
        threads = summary.get("threads", []) if isinstance(summary, dict) else []
        lines = []
        for thread in threads[:5]:
            label = thread.get("thread_name") or thread.get("thread_id") or "default"
            platform = thread.get("platform") or "chat"
            unread = int(thread.get("unread_count") or 0)
            lines.append(f"[{platform}] {label}（{unread}）")
            for message in (thread.get("messages") or [])[-3:]:
                sender = message.get("sender_name") or message.get("sender_id") or "unknown"
                content = (message.get("content") or "").replace("\r", " ").replace("\n", " ").strip()
                if len(content) > 80:
                    content = content[:80] + "..."
                lines.append(f"{sender}: {content}")
        return "\n".join(lines)

    def broadcast_chat_overlay(event: dict, stored: dict):
        summary = stored.get("unread", {}) if isinstance(stored, dict) else {}
        total = int(summary.get("total_unread") or 0)
        if total <= 0:
            return
        overlay = {
            "source": str(event.get("platform") or event.get("source") or "chat"),
            "state": "stream",
            "mode": "replace",
            "title": _tr("ChatIntegration.overlay_title", default="{count} 条未读消息", count=total),
            "text": format_chat_overlay(summary),
            "action": str(event.get("action") or "surprised"),
            "ttl_ms": int(event.get("ttl_ms") or 9000),
            "anchor_to_pet": True,
        }
        character = (event.get("character") or event.get("target_character") or "").strip()
        if character:
            overlay["character"] = character
        broadcast_ipc_line(f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}")

    def handle_chat_integration_message(event: dict) -> dict:
        with chat_integration_ref["lock"]:
            stored = chat_integration_db().add_external_chat_message(event)
        if not stored.get("duplicate"):
            broadcast_chat_overlay(event, stored)
        return stored

    def handle_chat_integration_read(data: dict) -> dict:
        with chat_integration_ref["lock"]:
            result = chat_integration_db().mark_external_chat_read(
                data.get("platform") or "",
                data.get("thread_id") or data.get("conversation_id") or "",
            )
        overlay = {
            "source": "chat",
            "state": "clear",
            "mode": "replace_raw",
            "text": "",
            "ttl_ms": 1,
        }
        broadcast_ipc_line(f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}")
        return result

    def init_chat_integration_server():
        stop_chat_integration_server()
        if not cfg.get("chat_integration_enabled", False):
            return
        port = _clamp_ai_status_port(cfg.get("chat_integration_port", 38473))
        token = cfg.get("chat_integration_token") or ""
        try:
            server = ChatIntegrationHttpServer(
                port,
                token,
                handle_chat_integration_message,
                handle_chat_integration_read,
            )
            server.start()
        except OSError as exc:
            print(f"Chat integration port failed to start on 127.0.0.1:{port}: {exc}")
            return
        chat_integration_ref["server"] = server

    def read_ipc_client(socket):
        if not isValid(socket):
            return
        data = bytes(socket.readAll()).decode("utf-8", errors="replace")
        buffers = ipc_ref.setdefault("buffers", {})
        buffer = buffers.get(socket, "") + data
        lines = buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            buffers[socket] = lines.pop()
        else:
            buffers[socket] = ""
        for raw_line in lines:
            handle_ipc_line(raw_line.rstrip("\r\n"))

    def handle_ipc_line(line: str):
        if line.startswith("ACTION\t") or line.startswith("LIP\t"):
            broadcast_ipc_line(line)
        elif line.startswith("AI_EVENT\t"):
            broadcast_ipc_line(line)
        elif line.startswith("CHAT_EVENT\t"):
            broadcast_ipc_line(line)
        elif line.startswith("MODEL\t") or line.startswith("SETTINGS\t") or line == "LAUNCH":
            handle_settings_line(line)
            if line.startswith("SETTINGS\t"):
                broadcast_ipc_line(line)

    def notify_chat_processes_shutdown():
        for socket in list(ipc_ref.get("clients", [])):
            if not isValid(socket) or not socket.isOpen():
                continue
            socket.write(b"SHUTDOWN\n")
            socket.flush()
            socket.waitForBytesWritten(100)

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
                entry = {**item, "character": model_char, "costume": model_costume, "path": path}
                result.append(entry)
                seen.add(model_char)
        if not result and char and costume and ModelManager.get_model_json_path(char, costume):
            result.append({"character": char, "costume": costume, "path": ModelManager.get_model_json_path(char, costume)})
        return result

    def save_config():
        cfg.load()
        cfg.set("language", current_language())
        cfg.save()

    def _close_qprocess(process, force=False):
        if not process or not isValid(process):
            return
        try:
            process.finished.disconnect()
        except RuntimeError:
            pass
        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
        process.deleteLater()

    def close_pet_processes(force=False):
        for process in list(pet_window_ref.get("processes", [])):
            _close_qprocess(process, force)
        pet_window_ref["processes"] = []

    def close_settings_process(force=False):
        process = settings_process_ref.get("process")
        _close_qprocess(process, force)
        settings_process_ref.pop("process", None)
        settings_process_ref.pop("show_launch", None)

    def on_model_selected(selected_char, selected_costume, relaunch=False):
        nonlocal char, costume
        char = selected_char
        costume = selected_costume
        pet_window_ref["char"] = selected_char
        pet_window_ref["costume"] = selected_costume
        if relaunch:
            launch_pet()

    def on_settings_changed(data):
        _SETTINGS_MAP = (
            ("fps", "fps", 120),
            ("opacity", "opacity", 1.0),
            ("dark_theme", "dark", False),
            ("vsync", "vsync", True),
            ("game_topmost", "game_topmost", False),
            ("hide_live2d_model", "hide_live2d_model", False),
            ("live2d_idle_actions_enabled", "live2d_idle_actions_enabled", True),
            ("live2d_quality", "live2d_quality", "balanced"),
            ("live2d_scale", "live2d_scale", 100),
            ("compact_ai_window_enabled", "compact_ai_window_enabled", False),
            ("compact_ai_window_opacity", "compact_ai_window_opacity", 44),
            ("compact_ai_window_font_size", "compact_ai_window_font_size", 12),
            ("compact_ai_window_background_color", "compact_ai_window_background_color", ""),
            ("compact_ai_window_text_color", "compact_ai_window_text_color", "#24242a"),
            ("ai_event_overlay_enabled", "ai_event_overlay_enabled", False),
            ("ai_status_port_enabled", "ai_status_port_enabled", False),
            ("ai_status_port", "ai_status_port", 38472),
            ("ai_status_token", "ai_status_token", ""),
            ("chat_integration_enabled", "chat_integration_enabled", False),
            ("chat_integration_overlay_enabled", "chat_integration_overlay_enabled", True),
            ("chat_integration_include_context", "chat_integration_include_context", True),
            ("chat_integration_port", "chat_integration_port", 38473),
            ("chat_integration_token", "chat_integration_token", ""),
        )
        language = data.get("language")
        if language:
            set_language(language)
            pet_window_ref["language"] = language
        for cfg_key, ref_key, default in _SETTINGS_MAP:
            value = data.get(cfg_key, pet_window_ref.get(ref_key, cfg.get(cfg_key, default)))
            if cfg_key in ("ai_status_port", "chat_integration_port"):
                value = _clamp_ai_status_port(value)
            pet_window_ref[ref_key] = value
        cfg.load()
        if language:
            cfg.set("language", language)
        for cfg_key, ref_key, _default in _SETTINGS_MAP:
            cfg.set(cfg_key, pet_window_ref[ref_key])
        for key in ("user_avatar_color", "user_avatar_path", "model_action_settings", "models"):
            value = data.get(key)
            if value is not None:
                cfg.set(key, value)
        cfg.save()
        init_ai_status_server()
        init_chat_integration_server()

    def launch_pet():
        cfg.load()
        _sentinel = object()
        language = pet_window_ref.get("language")
        if language:
            set_language(language)
            cfg.set("language", language)
        dark = pet_window_ref.get("dark")
        if dark:
            apply_app_theme(True)
            cfg.set("dark_theme", True)
        _pet_window_keys = (
            "fps", "opacity", "vsync", "game_topmost", "hide_live2d_model",
            "live2d_idle_actions_enabled", "live2d_quality", "live2d_scale",
            "compact_ai_window_enabled", "compact_ai_window_opacity",
            "compact_ai_window_font_size", "compact_ai_window_background_color",
            "compact_ai_window_text_color", "ai_event_overlay_enabled",
            "ai_status_port_enabled", "ai_status_port", "ai_status_token",
            "chat_integration_enabled", "chat_integration_overlay_enabled",
            "chat_integration_include_context", "chat_integration_port",
            "chat_integration_token",
        )
        for key in _pet_window_keys:
            value = pet_window_ref.get(key, _sentinel)
            if value is not _sentinel:
                cfg.set(key, value)
        cfg.save()
        models = configured_models()
        selected_char = pet_window_ref.get("char")
        selected_costume = pet_window_ref.get("costume")
        if not models and selected_char and selected_costume:
            path = ModelManager.get_model_json_path(selected_char, selected_costume)
            if path:
                models.append({"character": selected_char, "costume": selected_costume, "path": path})
        close_pet_processes()
        pet_window_ref["processes"] = []
        for idx, model in enumerate(models):
            process = QProcess(app)
            program, arguments = process_program_and_args(BASE_DIR, "pet_process.py", [
                "--character", model["character"],
                "--costume", model["costume"],
                "--model-path", model["path"],
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
        if not isValid(process):
            return
        processes = pet_window_ref.get("processes", [])
        if process in processes:
            processes.remove(process)
        process.deleteLater()

    settings_process_ref = {}

    def handle_settings_line(line):
        if line.startswith("MODEL\t"):
            parts = line.split("\t")
            if len(parts) >= 3:
                relaunch = (
                    parts[3] == "RELAUNCH"
                    if len(parts) >= 4
                    else not settings_process_ref.get("show_launch", True)
                )
                on_model_selected(
                    parts[1], parts[2],
                    relaunch=relaunch,
                )
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
        if not isValid(process):
            return
        if settings_process_ref.get("process") is process:
            settings_process_ref.pop("process", None)
            settings_process_ref.pop("show_launch", None)
        process.deleteLater()

    def launch_settings_process(show_launch=True):
        existing = settings_process_ref.get("process")
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            return
        cfg.load()
        process = QProcess(app)
        program, arguments = process_program_and_args(BASE_DIR, "settings_process.py", [
            "--character", cfg.get("character", char),
            "--costume", cfg.get("costume", costume),
            "--fps", str(cfg.get("fps", 120)),
            "--opacity", str(cfg.get("opacity", 1.0)),
            "--vsync", "1" if cfg.get("vsync", True) else "0",
            "--show-launch", "1" if show_launch else "0",
            "--start-on-costumes", "0",
        ])
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(lambda p=process: read_settings_error(p))
        process.finished.connect(lambda *args, p=process: clear_settings_process(p))
        settings_process_ref["process"] = process
        settings_process_ref["show_launch"] = show_launch
        process.start()

    model_valid = bool(
        char and costume
        and char in mgr.characters
        and ModelManager.get_model_json_path(char, costume)
    )
    has_configured_models = bool(configured_models())

    init_tray()
    init_ipc_server()
    init_ai_status_server()
    init_chat_integration_server()

    app.aboutToQuit.connect(save_config)
    app.aboutToQuit.connect(stop_ai_status_server)
    app.aboutToQuit.connect(stop_chat_integration_server)
    app.aboutToQuit.connect(close_chat_integration_db)
    app.aboutToQuit.connect(close_settings_process)
    app.aboutToQuit.connect(close_pet_processes)

    if has_configured_models or model_valid:
        pet_window_ref["char"] = char
        pet_window_ref["costume"] = costume
        pet_window_ref["vsync"] = cfg.get("vsync", True)
        launch_pet()
    else:
        launch_settings_process(show_launch=True)

    ret = app.exec()
    return ret

if __name__ == "__main__":
    sys.exit(main())
