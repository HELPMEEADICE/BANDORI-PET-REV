import sys
import json
import secrets
import signal
import threading
import os
import uuid

from process_utils import (
    app_base_dir,
    clamp_int,
    cleanup_stale_runtime_locks,
    configure_debug_logging,
    ensure_windows_app_user_model_shortcut,
    ipc_server_name,
    process_program_and_args,
    set_windows_app_user_model_id,
)
from config_manager import ConfigManager, DEFAULTS
from gpu_acceleration import configure_qt_opengl_environment, is_gpu_acceleration_enabled
from startup_manager import repair_startup_command
from app_info import APP_NAME

configure_debug_logging()
BASE_DIR = str(app_base_dir())
APP_AUMID = APP_NAME
_STARTUP_CONFIG = ConfigManager()
try:
    repair_startup_command()
except OSError:
    pass
configure_qt_opengl_environment(is_gpu_acceleration_enabled(_STARTUP_CONFIG))

from PySide6.QtCore import Qt, QObject, QProcess, QTimer, Signal
from PySide6.QtNetwork import QLocalServer
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from live2d_widget import Live2DWidget
from model_manager import ModelManager
from i18n_manager import set_language, detect_system_language, tr as _tr
from app_theme import apply_app_theme
from ai_status_server import AiStatusHttpServer
from chat_integration_server import ChatIntegrationHttpServer
from napcat_adapter import NapcatClient
from onebot_message import onebot_event_mentions_self
from database_manager import DatabaseManager
from tray_utils import keep_tray_icon_visible, load_tray_icon
from alarm_manager import ReminderScheduler
from gpu_acceleration import configure_qt_gpu_acceleration
from special_event_manager import SpecialEventManager
from event_db_manager import SpecialEvent


class AiEventBridge(QObject):
    line_received = Signal(str)


def main():
    if not os.environ.get("BANDORI_PET_IPC_SERVER_NAME", "").strip():
        os.environ["BANDORI_PET_IPC_SERVER_NAME"] = (
            f"{ipc_server_name()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )

    cfg = _STARTUP_CONFIG

    lang = cfg.get("language", "")
    if not lang:
        lang = detect_system_language()
    set_language(lang)

    configure_qt_gpu_acceleration(QApplication, Qt, cfg)
    Live2DWidget.configure_default_surface_format()
    icon_path = os.path.join(BASE_DIR, "logo.ico")
    ensure_windows_app_user_model_shortcut(APP_AUMID, APP_NAME, icon_path)
    set_windows_app_user_model_id(APP_AUMID)

    app = QApplication(sys.argv)

    if sys.platform == "darwin":
        import macos_patch
        macos_patch.hide_dock_icon()
    app.setWindowIcon(load_tray_icon())
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    apply_app_theme(cfg.get("dark_theme", False))

    mgr = ModelManager()
    pet_window_ref = {"processes": [], "closing_processes": []}
    ipc_ref = {"clients": [], "buffers": {}, "lock": threading.RLock()}
    ai_status_ref = {"server": None}
    chat_integration_ref = {"server": None, "db": None, "lock": threading.RLock()}
    napcat_ref = {"client": None, "workers": [], "lock": threading.RLock()}
    reminder_ref = {"scheduler": None}
    event_manager_ref = {"manager": None}
    ai_event_bridge = AiEventBridge()

    char = cfg.get("character", "")
    costume = cfg.get("costume", "")

    from i18n_manager import current_language

    tray_icon = None
    # Qt 6 on macOS needs the tray QMenu parented to a real QWidget so the
    # NSStatusItem can anchor its popup; without it the menu silently fails to
    # appear in NSApplicationActivationPolicyAccessory apps.
    tray_anchor = QWidget()
    tray_ref = {"menu": None, "actions": [], "anchor": tray_anchor}
    quit_ref = {"running": False}

    def init_tray():
        nonlocal tray_icon
        tray_icon = QSystemTrayIcon(app)
        tray_icon.setIcon(load_tray_icon())
        tray_icon.setToolTip(_tr("MainTray.tooltip"))

        menu = QMenu(tray_anchor)
        chat_action = menu.addAction(_tr("MainTray.chat"))
        chat_action.triggered.connect(launch_chat_process)
        settings_action = menu.addAction(_tr("MainTray.settings"))
        settings_action.triggered.connect(lambda: launch_settings_process(show_launch=False))
        exit_action = menu.addAction(_tr("MainTray.exit"))
        exit_action.triggered.connect(quit_all)
        tray_icon.setContextMenu(menu)
        tray_icon.activated.connect(on_tray_activated)
        tray_ref["menu"] = menu
        tray_ref["actions"] = [chat_action, settings_action, exit_action]
        keep_tray_icon_visible(tray_icon)

    def on_tray_activated(reason: QSystemTrayIcon.ActivationReason):
        if reason != QSystemTrayIcon.ActivationReason.Trigger:
            return
        if sys.platform == "darwin":
            return
        launch_settings_process(show_launch=False)

    def quit_all():
        if quit_ref["running"]:
            return
        quit_ref["running"] = True
        if tray_icon is not None:
            tray_icon.hide()
        app.quit()

        # Safety net: if the aboutToQuit handlers block or the event loop
        # stalls, force-terminate after a short delay so the process never
        # hangs on exit.
        def _force_exit():
            import os as _os
            _os._exit(0)

        QTimer.singleShot(10_000, _force_exit)

    def init_ipc_server():
        name = ipc_server_name()
        QLocalServer.removeServer(name)
        server = QLocalServer(app)

        def accept_clients():
            while server.hasPendingConnections():
                socket = server.nextPendingConnection()
                with ipc_ref["lock"]:
                    ipc_ref["clients"].append(socket)
                    ipc_ref["buffers"][socket] = ""
                socket.readyRead.connect(lambda s=socket: read_ipc_client(s))
                socket.disconnected.connect(lambda s=socket: remove_ipc_client(s))
                socket.errorOccurred.connect(lambda _error, s=socket: remove_ipc_client(s))

        server.newConnection.connect(accept_clients)
        if server.listen(name):
            ipc_ref["server"] = server
            return
        # A stale endpoint (previous crash, leftover socket file) can keep the
        # name busy; clear it once and retry before giving up.
        QLocalServer.removeServer(name)
        if server.listen(name):
            ipc_ref["server"] = server
            return
        error = server.errorString()
        server.deleteLater()
        message = (
            f"IPC server failed to listen on '{name}': {error}. "
            "Cross-process features (chat launch, action broadcast, settings "
            "sync) will not work."
        )
        print(message)
        show_system_notification(
            APP_NAME,
            _tr("MainTray.ipc_error_title", default="进程通信启动失败"),
            _tr(
                "MainTray.ipc_error_text",
                default="桌宠各窗口间通信未能建立，聊天唤起/设置同步可能失效。请重启程序，若仍出现请重启电脑。",
            ),
        )

    def stop_ipc_server():
        with ipc_ref["lock"]:
            sockets = list(ipc_ref.get("clients", []))
            ipc_ref["clients"] = []
            ipc_ref["buffers"] = {}
            server = ipc_ref.pop("server", None)
        for socket in sockets:
            if not isValid(socket):
                continue
            try:
                socket.disconnectFromServer()
                socket.close()
            except RuntimeError:
                pass
            socket.deleteLater()
        if server is not None and isValid(server):
            try:
                server.close()
                QLocalServer.removeServer(ipc_server_name())
            except RuntimeError:
                pass
            server.deleteLater()

    def remove_ipc_client(socket):
        with ipc_ref["lock"]:
            clients = ipc_ref.get("clients", [])
            if socket in clients:
                clients.remove(socket)
            ipc_ref.get("buffers", {}).pop(socket, None)
        if isValid(socket):
            socket.deleteLater()

    def write_ipc_line(socket, line: str):
        if not isValid(socket) or not socket.isOpen():
            remove_ipc_client(socket)
            return
        try:
            socket.write((line + "\n").encode("utf-8"))
            socket.flush()
        except RuntimeError:
            remove_ipc_client(socket)

    def broadcast_ipc_line(line: str, exclude_socket=None):
        with ipc_ref["lock"]:
            sockets = list(ipc_ref.get("clients", []))
        for socket in sockets:
            if exclude_socket is not None and socket is exclude_socket:
                continue
            write_ipc_line(socket, line)

    ai_event_bridge.line_received.connect(broadcast_ipc_line)

    def broadcast_reminder_event(event: dict):
        if not isinstance(event, dict):
            return
        payload = json.dumps(event, ensure_ascii=False)
        broadcast_ipc_line(f"REMINDER_EVENT\t{payload}")

    def show_system_notification(app_title: str, title: str, text: str):
        if tray_icon is None:
            return
        icon = load_tray_icon()
        if not icon.isNull():
            app.setWindowIcon(icon)
            tray_icon.setIcon(icon)
        set_windows_app_user_model_id(APP_AUMID)
        app.setApplicationName(APP_NAME)
        app.setApplicationDisplayName(APP_NAME)
        tray_icon.showMessage(
            str(title or "提醒"),
            str(text or ""),
            QSystemTrayIcon.MessageIcon.Information,
            15_000,
        )

    def init_reminder_scheduler():
        scheduler = reminder_ref.get("scheduler")
        if scheduler is not None:
            scheduler.stop()
            scheduler.deleteLater()
        reminder_ref["scheduler"] = ReminderScheduler(
            cfg,
            mgr,
            broadcast_reminder_event,
            show_system_notification,
            app,
        )

    def stop_reminder_scheduler():
        scheduler = reminder_ref.get("scheduler")
        if scheduler is not None:
            scheduler.stop()
        reminder_ref["scheduler"] = None

    def init_special_event_manager():
        manager = event_manager_ref.get("manager")
        if manager is not None:
            manager.stop()
            manager.deleteLater()
        manager = SpecialEventManager(parent=app)

        def on_special_event(event: SpecialEvent):
            if event.event_type == "birthday":
                cfg.load()
                if not bool(cfg.get("birthday_tray_notifications_enabled", True)):
                    return
            title = event.name.get("zh", "")
            try:
                text = event.prompt_template.format(
                    name_zh=event.name.get("zh", ""),
                    month=event.month,
                    day=event.day,
                )
            except (KeyError, ValueError):
                text = event.prompt_template
            show_system_notification(APP_NAME, f"\U0001f389 {title}", text)

        manager.event_detected.connect(on_special_event)
        manager.start()
        event_manager_ref["manager"] = manager

    def stop_special_event_manager():
        manager = event_manager_ref.get("manager")
        if manager is not None:
            manager.stop()
        event_manager_ref["manager"] = None

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

    def ensure_local_port_token(token_key: str) -> str:
        # A loopback HTTP port with no token accepts unauthenticated requests
        # from any local process or web page (CORS does not block plain POSTs),
        # which could inject fake chat/AI events into the pet. When such a port
        # is enabled without a token, mint and persist one so the running server
        # is always authenticated. cfg.save() merges with disk, so this never
        # clobbers other settings.
        token = str(cfg.get(token_key, "") or "").strip()
        if token:
            return token
        token = secrets.token_urlsafe(18)
        cfg.set(token_key, token)
        try:
            cfg.save()
        except Exception as exc:
            print(f"Failed to persist generated {token_key}: {exc}")
        return token

    def close_chat_integration_db():
        db = chat_integration_ref.get("db")
        if db is not None:
            db.close()
        chat_integration_ref["db"] = None

    def init_ai_status_server():
        stop_ai_status_server()
        if not cfg.get("ai_status_port_enabled", False):
            return
        port = clamp_int(cfg.get("ai_status_port", 38472), 1024, 65535, 38472)
        token = ensure_local_port_token("ai_status_token")

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
        ai_event_bridge.line_received.emit(f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}")

    def handle_chat_integration_message(event: dict) -> dict:
        with chat_integration_ref["lock"]:
            stored = chat_integration_db().add_external_chat_message(event)
        if not stored.get("duplicate"):
            broadcast_chat_overlay(event, stored)
            # Notification model: the overlay copy already lives on the pet side
            # and self-clears after its TTL, so clear the unread backlog now to
            # stop stale messages (e.g. earlier test pushes) from re-surfacing
            # on the next event. AI context reads messages regardless of the
            # unread flag, so this does not affect what the model can see.
            with chat_integration_ref["lock"]:
                chat_integration_db().mark_external_chat_read("", "")
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
        ai_event_bridge.line_received.emit(f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}")
        return result

    def init_chat_integration_server():
        stop_chat_integration_server()
        if not cfg.get("chat_integration_enabled", False):
            return
        port = clamp_int(cfg.get("chat_integration_port", 38473), 1024, 65535, 38473)
        token = ensure_local_port_token("chat_integration_token")
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

    def stop_napcat_adapter(force=False):
        with napcat_ref["lock"]:
            client = napcat_ref.get("client")
            workers = list(napcat_ref.get("workers", []))
            napcat_ref["workers"].clear()
        if client is not None:
            client.stop()
            if isValid(client):
                client.deleteLater()
        for worker in workers:
            if isValid(worker) and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if force and not worker.wait(500):
                    worker.terminate()
                    worker.wait(500)
            if isValid(worker):
                worker.deleteLater()
        with napcat_ref["lock"]:
            napcat_ref["client"] = None

    def init_napcat_adapter():
        stop_napcat_adapter()
        if not cfg.get("napcat_enabled", False):
            return
        ws_url = str(cfg.get("napcat_ws_url", "") or "").strip()
        if not ws_url:
            return
        token = str(cfg.get("napcat_access_token", "") or "").strip()
        client = NapcatClient(ws_url, token, handle_napcat_message, parent=app)
        napcat_ref["client"] = client
        client.start()
        _napcat_apply_retention()

    def _napcat_should_reply(event: dict) -> bool:
        if not cfg.get("napcat_auto_reply_enabled", False):
            return False
        raw_event = event.get("raw_event") if isinstance(event, dict) else None
        if not isinstance(raw_event, dict):
            return False
        message_type = str(raw_event.get("message_type") or "").lower()
        if message_type == "group":
            if cfg.get("napcat_reply_group_at_only", True):
                return onebot_event_mentions_self(raw_event)
            return True
        return bool(cfg.get("napcat_reply_private", True))

    def _napcat_reply_character() -> str:
        explicit = str(cfg.get("napcat_reply_character", "") or "").strip()
        if explicit:
            return explicit
        models = cfg.get("models", [])
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and item.get("character"):
                    return str(item["character"])
        return char

    def _napcat_chat_type(event: dict) -> str:
        chat_type = str(event.get("chat_type") or "").lower() if isinstance(event, dict) else ""
        if chat_type in ("group", "private"):
            return chat_type
        raw_event = event.get("raw_event") if isinstance(event, dict) else None
        if isinstance(raw_event, dict) and str(raw_event.get("message_type") or "").lower() == "group":
            return "group"
        return "private"

    def _napcat_should_save(chat_type: str) -> bool:
        policy = str(cfg.get("napcat_save_policy", "all") or "all").lower()
        if policy == "overlay_only":
            return False
        if policy == "private_only":
            return chat_type != "group"
        return True

    def broadcast_napcat_transient_overlay(event: dict):
        # Notification-only path for messages we are NOT persisting (save policy
        # = overlay_only, or private_only applied to a group message). Shows the
        # single incoming message in the floating window without a DB write.
        content = str(event.get("text") or event.get("content") or "")
        content = content.replace("\r", " ").replace("\n", " ").strip()
        if not content:
            return
        if len(content) > 80:
            content = content[:80] + "..."
        sender = str(event.get("sender_name") or event.get("sender_id") or "").strip()
        body = f"{sender}: {content}" if sender else content
        overlay = {
            "source": str(event.get("platform") or "qq"),
            "state": "stream",
            "mode": "replace",
            "title": str(event.get("thread_name") or "").strip()
            or _tr("ChatIntegration.overlay_new_message", default="新消息"),
            "text": body,
            "action": "surprised",
            "ttl_ms": 9000,
            "anchor_to_pet": True,
        }
        broadcast_ipc_line(f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}")

    def _napcat_apply_retention():
        # Auto-delete expired records for chat types whose retention mode is "auto".
        try:
            with chat_integration_ref["lock"]:
                db = chat_integration_db()
                db.prune_external_group_chat_limit()
                if str(cfg.get("napcat_group_retention_mode", "manual") or "manual").lower() == "auto":
                    db.purge_external_chat_older_than(cfg.get("napcat_group_retention_days", 7), chat_type="group")
                if str(cfg.get("napcat_private_retention_mode", "manual") or "manual").lower() == "auto":
                    db.purge_external_chat_older_than(cfg.get("napcat_private_retention_days", 30), chat_type="private")
        except Exception as exc:
            print(f"NapCat retention cleanup failed: {exc}")

    def handle_napcat_message(event: dict):
        if _napcat_should_save(_napcat_chat_type(event)):
            try:
                handle_chat_integration_message(event)
            except Exception as exc:
                print(f"NapCat message handling failed: {exc}")
                return
            _napcat_apply_retention()
        else:
            broadcast_napcat_transient_overlay(event)
        if _napcat_should_reply(event):
            _napcat_generate_reply(event)

    def _napcat_generate_reply(event: dict):
        from llm_manager import NonStreamWorker, build_system_prompt, strip_action_tags

        api_url = str(cfg.get("llm_api_url", "") or "").strip()
        api_key = str(cfg.get("llm_api_key", "") or "").strip()
        model_id = str(cfg.get("llm_model_id", "") or "").strip()
        if not api_url or not api_key or not model_id:
            return
        character = _napcat_reply_character()
        system_prompt = build_system_prompt(character, cfg)
        if not system_prompt:
            return
        sender_name = str(event.get("sender_name") or "对方")
        user_text = f"{sender_name}：{event.get('text') or ''}".strip()
        try:
            with chat_integration_ref["lock"]:
                context = chat_integration_db().external_chat_context_text()
        except Exception:
            context = ""
        if context:
            user_text += "\n\n【最近外部聊天上下文】\n" + context
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        enable_thinking = cfg.get("llm_enable_thinking", None)
        worker = NonStreamWorker(api_url, api_key, model_id, messages, enable_thinking, app)
        raw_event = event.get("raw_event") if isinstance(event, dict) else None
        character_for_event = character
        cleanup_state = {"done": False}

        # Bound to the worker's lifetime rather than fired and forgotten: a
        # reply that finishes early cancels this immediately, so high-frequency
        # group messages don't pile up timers waiting out the full timeout.
        timeout_timer = QTimer(app)
        timeout_timer.setSingleShot(True)
        timeout_timer.setInterval(130_000)

        def _stop_timeout_timer():
            if isValid(timeout_timer):
                timeout_timer.stop()
                timeout_timer.deleteLater()

        def _cleanup(delete_later=True):
            _stop_timeout_timer()
            with napcat_ref["lock"]:
                if cleanup_state["done"]:
                    return False
                cleanup_state["done"] = True
                if worker in napcat_ref["workers"]:
                    napcat_ref["workers"].remove(worker)
            if delete_later and isValid(worker):
                worker.deleteLater()
            return True

        def _on_timeout():
            if isValid(worker) and worker.isRunning():
                worker.requestInterruption()

        def _on_destroyed():
            _stop_timeout_timer()
            with napcat_ref["lock"]:
                cleanup_state["done"] = True
                if worker in napcat_ref["workers"]:
                    napcat_ref["workers"].remove(worker)

        def _on_finished(full_text, _reasoning, _actions):
            if not _cleanup(delete_later=False):
                return
            clean = strip_action_tags(full_text)
            with napcat_ref["lock"]:
                client = napcat_ref.get("client")
            if clean and client is not None and isinstance(raw_event, dict):
                client.send_reply(
                    raw_event,
                    clean,
                    mention_sender=bool(cfg.get("napcat_reply_mention_sender", True)),
                )
                overlay = {
                    "source": "napcat",
                    "state": "stream",
                    "mode": "replace",
                    "title": _tr("ChatIntegration.napcat_reply_title", default="已回复 QQ"),
                    "text": clean,
                    "action": "smile",
                    "ttl_ms": 9000,
                    "anchor_to_pet": True,
                    "character": character_for_event,
                }
                ai_event_bridge.line_received.emit(f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}")
            if isValid(worker):
                worker.deleteLater()

        def _on_error(message):
            print(f"NapCat auto-reply failed: {message}")
            _cleanup()

        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.destroyed.connect(_on_destroyed)
        timeout_timer.timeout.connect(_on_timeout)
        with napcat_ref["lock"]:
            napcat_ref["workers"].append(worker)
        worker.start()
        timeout_timer.start()

    def read_ipc_client(socket):
        if not isValid(socket):
            return
        data = bytes(socket.readAll()).decode("utf-8", errors="replace")
        with ipc_ref["lock"]:
            buffers = ipc_ref.setdefault("buffers", {})
            buffer = buffers.get(socket, "") + data
            lines = buffer.splitlines(keepends=True)
            if lines and not lines[-1].endswith(("\n", "\r")):
                buffers[socket] = lines.pop()
            else:
                buffers[socket] = ""
        for raw_line in lines:
            handle_ipc_line(raw_line.rstrip("\r\n"), source_socket=socket)

    def handle_ipc_line(line: str, source_socket=None):
        if line.startswith("ACTION\t") or line.startswith("LIP\t"):
            broadcast_ipc_line(line)
        elif line.startswith("POKE_USER\t"):
            broadcast_ipc_line(line)
        elif line.startswith("AI_EVENT\t"):
            broadcast_ipc_line(line)
        elif line.startswith("CHAT_EVENT\t"):
            broadcast_ipc_line(line)
        elif line.startswith("REMINDER_EVENT\t"):
            broadcast_ipc_line(line)
        elif line.startswith("PEER_POS\t"):
            broadcast_ipc_line(line)
        elif line.startswith("PEER_DRAG\t"):
            broadcast_ipc_line(line)
        elif line.startswith("PREVIEW_MOTION\t"):
            broadcast_ipc_line(line)
        elif line.startswith("LAYER_ORDER\t"):
            broadcast_ipc_line(line)
        elif line.startswith("RADIAL_MENU_OPEN\t"):
            broadcast_ipc_line(line)
        elif line.startswith("RADIAL_MENU_CLOSED\t"):
            broadcast_ipc_line(line)
        elif line == "FOCUS_CHAT":
            broadcast_ipc_line(line, exclude_socket=source_socket)
        elif line.startswith("OPEN_SETTINGS"):
            handle_open_settings_request(line)
        elif line.startswith("MODEL\t") or line.startswith("SETTINGS\t") or line == "LAUNCH":
            handle_settings_line(line)
            if line.startswith("SETTINGS\t"):
                broadcast_ipc_line(line, exclude_socket=source_socket)

    def notify_chat_processes_shutdown():
        with ipc_ref["lock"]:
            sockets = list(ipc_ref.get("clients", []))
        for socket in sockets:
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
                if not model_char or model_char in seen or model_char not in mgr.characters:
                    continue
                if not model_costume:
                    model_costume = mgr.get_default_costume(model_char)
                if not model_costume:
                    continue
                path = mgr.get_model_json_path(model_char, model_costume)
                if not path:
                    continue
                entry = {**item, "character": model_char, "costume": model_costume, "path": path}
                result.append(entry)
                seen.add(model_char)
        if not result and char and costume and mgr.get_model_json_path(char, costume):
            result.append({"character": char, "costume": costume, "path": mgr.get_model_json_path(char, costume)})
        return result

    def save_config():
        cfg.load()
        cfg.set("language", current_language())
        cfg.save()

    def _close_qprocess(process, force=False, wait=True):
        if not process or not isValid(process):
            return
        if wait:
            try:
                process.finished.disconnect()
            except RuntimeError:
                pass
        if process.state() != QProcess.ProcessState.NotRunning:
            if force:
                process.kill()
                if not wait:
                    try:
                        process.finished.connect(process.deleteLater)
                    except (RuntimeError, TypeError):
                        pass
                    return
                process.waitForFinished(250)
            else:
                process.terminate()
                if not wait:
                    def kill_if_still_running(p=process):
                        if isValid(p) and p.state() != QProcess.ProcessState.NotRunning:
                            p.kill()

                    QTimer.singleShot(1500, kill_if_still_running)
                    return
                if not process.waitForFinished(1000):
                    process.kill()
                    process.waitForFinished(1000)
        process.deleteLater()

    def close_pet_processes(force=False, wait=True):
        processes = [
            process
            for process in list(pet_window_ref.get("processes", []))
            if process and isValid(process)
        ]
        if force and wait:
            for process in processes:
                if process.state() != QProcess.ProcessState.NotRunning:
                    try:
                        process.finished.disconnect()
                    except RuntimeError:
                        pass
                    process.kill()
            for process in processes:
                if process.state() != QProcess.ProcessState.NotRunning:
                    process.waitForFinished(250)
                process.deleteLater()
            pet_window_ref["processes"] = []
            return
        for process in processes:
            if not wait:
                process_state = process.state()
                if process_state != QProcess.ProcessState.NotRunning:
                    closing = pet_window_ref.setdefault("closing_processes", [])
                    if process not in closing:
                        closing.append(process)
            _close_qprocess(process, force, wait=wait)
        pet_window_ref["processes"] = []

    def close_settings_process(force=False, wait=True):
        process = settings_process_ref.get("process")
        _close_qprocess(process, force, wait=wait)
        settings_process_ref.pop("process", None)
        settings_process_ref.pop("show_launch", None)

    def close_chat_process(force=False, wait=True):
        process = chat_process_ref.get("process")
        _close_qprocess(process, force, wait=wait)
        chat_process_ref.pop("process", None)

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
            ("gpu_acceleration", "gpu_acceleration", True),
            ("game_topmost", "game_topmost", False),
            ("chat_window_normal_window", "chat_window_normal_window", False),
            ("chat_attachment_auto_cleanup_enabled", "chat_attachment_auto_cleanup_enabled", False),
            ("chat_attachment_retention_days", "chat_attachment_retention_days", 30),
            ("hide_live2d_model", "hide_live2d_model", False),
            ("live2d_idle_actions_enabled", "live2d_idle_actions_enabled", True),
            ("live2d_random_actions_enabled", "live2d_random_actions_enabled", True),
            ("live2d_head_tracking_enabled", "live2d_head_tracking_enabled", True),
            ("live2d_mutual_gaze_enabled", "live2d_mutual_gaze_enabled", False),
            ("move_all_roles_together", "move_all_roles_together", False),
            ("poke_motion", "poke_motion", ""),
            ("poke_expression", "poke_expression", ""),
            ("birthday_tray_notifications_enabled", "birthday_tray_notifications_enabled", True),
            ("live2d_quality", "live2d_quality", "balanced"),
            # 0 is the canonical "auto" sentinel (clamp_live2d_scale resolves it);
            # source it from DEFAULTS so this path never drifts from config_manager.
            ("live2d_scale", "live2d_scale", DEFAULTS["live2d_scale"]),
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
            ("napcat_enabled", "napcat_enabled", False),
            ("napcat_ws_url", "napcat_ws_url", "ws://127.0.0.1:3001"),
            ("napcat_access_token", "napcat_access_token", ""),
            ("napcat_auto_reply_enabled", "napcat_auto_reply_enabled", False),
            ("napcat_reply_private", "napcat_reply_private", True),
            ("napcat_reply_group_at_only", "napcat_reply_group_at_only", True),
            ("napcat_reply_mention_sender", "napcat_reply_mention_sender", True),
            ("napcat_reply_character", "napcat_reply_character", ""),
            ("napcat_save_policy", "napcat_save_policy", "all"),
            ("napcat_group_retention_mode", "napcat_group_retention_mode", "manual"),
            ("napcat_group_retention_days", "napcat_group_retention_days", 7),
            ("napcat_private_retention_mode", "napcat_private_retention_mode", "manual"),
            ("napcat_private_retention_days", "napcat_private_retention_days", 30),
            ("screen_awareness_enabled", "screen_awareness_enabled", False),
            ("screen_awareness_interval_minutes", "screen_awareness_interval_minutes", 30),
            ("screen_awareness_character_mode", "screen_awareness_character_mode", "random_visible"),
            ("screen_awareness_character", "screen_awareness_character", ""),
            ("screen_awareness_max_screenshot_width", "screen_awareness_max_screenshot_width", 1920),
            ("screen_awareness_model_mode", "screen_awareness_model_mode", "main"),
            ("screen_awareness_display_mode", "screen_awareness_display_mode", "floating"),
            ("screen_awareness_include_process_name", "screen_awareness_include_process_name", True),
            ("screen_awareness_include_window_title", "screen_awareness_include_window_title", False),
        )
        language = data.get("language")
        if language:
            set_language(language)
            pet_window_ref["language"] = language
        for cfg_key, ref_key, default in _SETTINGS_MAP:
            value = data.get(cfg_key, pet_window_ref.get(ref_key, cfg.get(cfg_key, default)))
            if cfg_key in ("ai_status_port", "chat_integration_port"):
                value = clamp_int(value, 1024, 65535, default)
            pet_window_ref[ref_key] = value
        cfg.load()
        if language:
            cfg.set("language", language)
        for cfg_key, ref_key, _default in _SETTINGS_MAP:
            cfg.set(cfg_key, pet_window_ref[ref_key])
        for key in (
            "user_name",
            "user_avatar_color",
            "user_avatar_path",
            "user_profiles",
            "active_user_profile",
            "pov_mode",
            "pov_custom_prompt",
            "pov_custom_personas",
            "pov_role_character",
            "model_action_settings",
            "models",
            "alarms",
            "pomodoros",
            "proactive_companion",
            "proactive_care_policy",
            "reminder_display_mode",
        ):
            value = data.get(key)
            if value is not None:
                cfg.set(key, value)
        cfg.save()
        init_ai_status_server()
        init_chat_integration_server()
        init_napcat_adapter()
        apply_chat_attachment_retention()
        scheduler = reminder_ref.get("scheduler")
        if scheduler is not None:
            scheduler.reload()
            if data.get("screen_awareness_test_requested"):
                scheduler.trigger_screen_awareness_now()

    def launch_pet():
        nonlocal mgr
        cfg.load()
        mgr = ModelManager()
        _sentinel = object()
        language = pet_window_ref.get("language")
        if language:
            set_language(language)
            cfg.set("language", language)
        dark = pet_window_ref.get("dark")
        if dark is not None:
            apply_app_theme(dark)
            cfg.set("dark_theme", dark)
        _pet_window_keys = (
            "fps", "opacity", "vsync", "game_topmost", "chat_window_normal_window", "hide_live2d_model",
            "live2d_idle_actions_enabled", "live2d_random_actions_enabled", "live2d_head_tracking_enabled",
            "live2d_mutual_gaze_enabled", "move_all_roles_together",
            "birthday_tray_notifications_enabled",
            "live2d_quality", "live2d_scale",
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
            path = mgr.get_model_json_path(selected_char, selected_costume)
            if path:
                models.append({"character": selected_char, "costume": selected_costume, "path": path})
        group_characters = []
        seen_group_characters = set()
        for model in models:
            model_char = model.get("character", "")
            if model_char and model_char not in seen_group_characters:
                group_characters.append(model_char)
                seen_group_characters.add(model_char)
        group_characters_arg = json.dumps(group_characters, ensure_ascii=False)
        close_pet_processes(wait=False)
        pet_window_ref["processes"] = []
        for idx, model in enumerate(models):
            process = QProcess(app)
            program, arguments = process_program_and_args(BASE_DIR, "pet_process.py", [
                "--character", model["character"],
                "--costume", model["costume"],
                "--model-path", model["path"],
                "--index", str(idx),
                "--group-characters", group_characters_arg,
            ])
            process.setProgram(program)
            process.setArguments(arguments)
            process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
            process.readyReadStandardError.connect(lambda p=process: _read_process_error(p))
            process.finished.connect(lambda *args, p=process: clear_pet_process(p))
            pet_window_ref["processes"].append(process)
            process.setWorkingDirectory(BASE_DIR)
            process.start()

    def _read_process_error(process):
        data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            try:
                print(data)
            except UnicodeEncodeError:
                safe = data.encode("ascii", errors="replace").decode("ascii")
                print(safe)

    def clear_pet_process(process):
        if not isValid(process):
            return
        processes = pet_window_ref.get("processes", [])
        if process in processes:
            processes.remove(process)
        closing_processes = pet_window_ref.get("closing_processes", [])
        if process in closing_processes:
            closing_processes.remove(process)
        process.deleteLater()

    settings_process_ref = {}
    chat_process_ref = {}

    def clear_chat_process(process):
        if not isValid(process):
            return
        if chat_process_ref.get("process") is process:
            chat_process_ref.pop("process", None)
        process.deleteLater()

    def launch_chat_process():
        existing = chat_process_ref.get("process")
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            return

        cfg.load()
        current_char = cfg.get("character", char)
        current_costume = cfg.get("costume", costume)
        if not (current_char and current_char in mgr.characters):
            models = configured_models()
            if models:
                current_char = models[0].get("character", "")
                current_costume = models[0].get("costume", current_costume)
        if not current_char:
            launch_settings_process(show_launch=False)
            return

        with ipc_ref["lock"]:
            has_ipc_clients = bool(ipc_ref.get("clients"))
        if pet_window_ref.get("processes") and has_ipc_clients:
            broadcast_ipc_line(f"OPEN_CHAT\t{current_char}")
            return

        group_characters = []
        seen_group_characters = set()
        for model in configured_models():
            model_char = model.get("character", "")
            if model_char and model_char not in seen_group_characters:
                group_characters.append(model_char)
                seen_group_characters.add(model_char)
        if current_char not in seen_group_characters:
            group_characters.insert(0, current_char)

        screen = app.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            pet_x = available.center().x()
            pet_y = available.center().y()
        else:
            pet_x = 100
            pet_y = 100

        process = QProcess(app)
        program, arguments = process_program_and_args(BASE_DIR, "chat_process.py", [
            "--character", current_char,
            "--pet-x", str(pet_x),
            "--pet-y", str(pet_y),
            "--pet-w", "1",
            "--pet-h", "1",
            "--group-characters", json.dumps(group_characters, ensure_ascii=False),
        ])
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(lambda p=process: _read_process_error(p))
        process.finished.connect(lambda *args, p=process: clear_chat_process(p))
        process.errorOccurred.connect(lambda _error, p=process: clear_chat_process(p))
        chat_process_ref["process"] = process
        process.setWorkingDirectory(BASE_DIR)
        process.start()

    def handle_settings_line(line):
        if line.startswith("MODEL\t"):
            parts = line.split("\t")
            if len(parts) >= 3:
                character = parts[1].strip()
                costume = parts[2].strip()
                if not character or not costume:
                    return
                relaunch = (
                    parts[3] == "RELAUNCH"
                    if len(parts) >= 4
                    else not settings_process_ref.get("show_launch", True)
                )
                on_model_selected(character, costume, relaunch=relaunch)
        elif line.startswith("SETTINGS\t"):
            try:
                cfg.load()
                on_settings_changed(json.loads(line.split("\t", 1)[1]))
            except json.JSONDecodeError:
                pass
        elif line == "LAUNCH":
            settings_process_ref["launched"] = True
            launch_pet()
        elif line == "EXIT":
            quit_all()

    def clear_settings_process(process):
        if not isValid(process):
            return
        if settings_process_ref.get("process") is process:
            settings_process_ref.pop("process", None)
            settings_process_ref.pop("show_launch", None)
            settings_process_ref.pop("first_run_wizard", None)
            settings_process_ref.pop("launched", None)
        process.deleteLater()

    def on_settings_process_finished(process):
        should_quit = (
            settings_process_ref.get("process") is process
            and settings_process_ref.get("show_launch", False)
            and settings_process_ref.get("first_run_wizard", False)
            and not settings_process_ref.get("launched", False)
        )
        clear_settings_process(process)
        if should_quit:
            quit_all()

    def handle_open_settings_request(line: str):
        parts = line.split("\t")
        target = parts[1].strip() if len(parts) >= 2 else "main"
        character = parts[2].strip() if len(parts) >= 3 else ""
        launch_settings_process(
            show_launch=False,
            start_on_costumes=target == "costumes",
            costume_character=character,
        )

    def launch_settings_process(show_launch=True, start_on_costumes=False, costume_character=""):
        nonlocal mgr
        existing = settings_process_ref.get("process")
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            if start_on_costumes:
                broadcast_ipc_line(f"SHOW_COSTUMES\t{costume_character}")
            return
        cfg.load()
        mgr = ModelManager()
        current_char = costume_character if start_on_costumes and costume_character else cfg.get("character", char)
        current_costume = cfg.get("costume", costume)
        current_model_valid = bool(
            current_char and current_costume
            and current_char in mgr.characters
            and mgr.get_model_json_path(current_char, current_costume)
        )
        first_run_wizard = not (configured_models() or current_model_valid)
        process = QProcess(app)
        program, arguments = process_program_and_args(BASE_DIR, "settings_process.py", [
            "--character", current_char,
            "--costume", current_costume,
            "--fps", str(cfg.get("fps", 120)),
            "--opacity", str(cfg.get("opacity", 1.0)),
            "--vsync", "1" if cfg.get("vsync", True) else "0",
            "--show-launch", "1" if show_launch else "0",
            "--start-on-costumes", "1" if start_on_costumes else "0",
            "--first-run-wizard", "1" if first_run_wizard else "0",
        ])
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardError.connect(lambda p=process: _read_process_error(p))
        process.finished.connect(lambda *args, p=process: on_settings_process_finished(p))
        settings_process_ref["process"] = process
        settings_process_ref["show_launch"] = show_launch
        settings_process_ref["first_run_wizard"] = first_run_wizard
        settings_process_ref["launched"] = False
        process.setWorkingDirectory(BASE_DIR)
        process.start()

    model_valid = bool(
        char and costume
        and char in mgr.characters
        and mgr.get_model_json_path(char, costume)
    )
    has_configured_models = bool(configured_models())

    try:
        cleanup_stale_runtime_locks(BASE_DIR)
    except Exception as exc:
        print(f"Stale runtime lock cleanup failed: {exc}")

    init_tray()
    init_ipc_server()
    init_ai_status_server()
    init_chat_integration_server()
    init_napcat_adapter()
    init_reminder_scheduler()
    init_special_event_manager()

    def _handle_signal(_signum, _frame):
        QTimer.singleShot(0, quit_all)

    for sig_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass

    # Qt's C++ event loop doesn't yield to Python often enough for pending
    # signals to fire; a no-op timer keeps the interpreter ticking so handlers
    # actually run when SIGTERM/SIGHUP arrives.
    signal_pump_timer = QTimer(app)
    signal_pump_timer.setInterval(100)
    signal_pump_timer.timeout.connect(lambda: None)
    signal_pump_timer.start()

    def apply_chat_attachment_retention():
        cfg.load()
        if not cfg.get("chat_attachment_auto_cleanup_enabled", False):
            return
        try:
            from chat_attachment_manager import (
                clamp_attachment_retention_days,
                cleanup_chat_attachments,
            )

            cleanup_chat_attachments(clamp_attachment_retention_days(
                cfg.get("chat_attachment_retention_days", 30)
            ))
        except Exception as exc:
            print(f"Chat attachment cleanup failed: {exc}")

    attachment_cleanup_timer = QTimer(app)
    attachment_cleanup_timer.setInterval(6 * 60 * 60 * 1000)
    attachment_cleanup_timer.timeout.connect(apply_chat_attachment_retention)
    attachment_cleanup_timer.start()
    QTimer.singleShot(0, apply_chat_attachment_retention)

    # ── Usage session tracking ─────────────────────────────────────────
    usage_session_ref = {"db": None, "session_id": None}

    def usage_db():
        db = usage_session_ref.get("db")
        if db is None:
            db = DatabaseManager()
            usage_session_ref["db"] = db
        return db

    def close_usage_db():
        db = usage_session_ref.get("db")
        if db is not None:
            db.close()
        usage_session_ref["db"] = None

    def end_usage_session():
        sid = usage_session_ref.get("session_id")
        if sid is not None:
            usage_db().end_usage_session(sid)
        close_usage_db()

    usage_session_ref["session_id"] = usage_db().start_usage_session()
    usage_heartbeat = QTimer(app)
    usage_heartbeat.setInterval(300_000)
    usage_heartbeat.timeout.connect(lambda: usage_db().heartbeat_usage_session(
        usage_session_ref["session_id"]))
    usage_heartbeat.start()

    app.aboutToQuit.connect(save_config)
    app.aboutToQuit.connect(notify_chat_processes_shutdown)
    app.aboutToQuit.connect(stop_ipc_server)
    app.aboutToQuit.connect(stop_ai_status_server)
    app.aboutToQuit.connect(stop_chat_integration_server)
    app.aboutToQuit.connect(lambda: stop_napcat_adapter(force=True))
    app.aboutToQuit.connect(stop_reminder_scheduler)
    app.aboutToQuit.connect(close_chat_integration_db)
    app.aboutToQuit.connect(end_usage_session)
    app.aboutToQuit.connect(lambda: close_settings_process(force=True, wait=False))
    app.aboutToQuit.connect(lambda: close_chat_process(force=True, wait=False))
    app.aboutToQuit.connect(lambda: close_pet_processes(force=True, wait=False))

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
