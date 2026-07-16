import sys
import json
import signal
import threading
import os
import time
import uuid

from process_utils import (
    bootstrap_app,
    clamp_int,
    cleanup_stale_runtime_locks,
    ensure_windows_app_user_model_shortcut,
    ipc_server_name,
    process_program_and_args,
    set_windows_app_user_model_id,
)
from startup_manager import repair_startup_command
from app_info import APP_NAME
from local_port_security import ensure_local_port_token

BASE_DIR, _STARTUP_CONFIG = bootstrap_app()
from config_manager import DEFAULTS
APP_AUMID = APP_NAME
try:
    repair_startup_command()
except OSError:
    pass

from PySide6.QtCore import Qt, QObject, QProcess, QTimer, Signal
from shiboken6 import isValid
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

from live2d_widget import Live2DWidget
from model_manager import ModelManager
from outfit_description import (
    OUTFIT_DESCRIPTIONS_KEY,
    normalize_outfit_descriptions,
    outfit_description_key,
)
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
from ipc_bus import (
    ipc_broadcast_queue_key,
    ipc_control_queue_key,
    ipc_inbound_queue_key,
    ipc_reliable_inbound_queue_key,
    is_control_ipc_line,
    is_reliable_ipc_line,
    pet_characters_without_active_peers,
)
from shared_memory_ipc import (
    SharedMemoryLineQueue,
    coalesce_latest_peer_positions,
    decode_ipc_envelope,
    encode_ipc_envelope,
    make_peer_id,
)


class AiEventBridge(QObject):
    line_received = Signal(str)
    delivery_requested = Signal(str, object)


def main():
    os.environ["BANDORI_PET_MAIN_PID"] = str(os.getpid())

    def refresh_ipc_session_name():
        os.environ.pop("BANDORI_PET_IPC_SERVER_NAME", None)
        os.environ["BANDORI_PET_IPC_SERVER_NAME"] = (
            f"{ipc_server_name()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )

    if not os.environ.get("BANDORI_PET_IPC_SERVER_NAME", "").strip():
        refresh_ipc_session_name()

    cfg = _STARTUP_CONFIG

    lang = cfg.get("language", "")
    if not lang:
        lang = detect_system_language()
    set_language(lang)

    configure_qt_gpu_acceleration(QApplication, Qt, cfg)
    Live2DWidget.configure_default_surface_format(cfg.get("vsync", True))
    icon_path = os.path.join(BASE_DIR, "logo.ico")
    ensure_windows_app_user_model_shortcut(APP_AUMID, APP_NAME, icon_path)
    set_windows_app_user_model_id(APP_AUMID)

    app = QApplication(sys.argv)

    import macos_patch
    macos_patch.hide_dock_icon_if_needed()
    app.setWindowIcon(load_tray_icon())
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    apply_app_theme(cfg.get("dark_theme", False))

    mgr = ModelManager()
    pet_window_ref = {"processes": [], "closing_processes": []}
    ipc_ref = {"lock": threading.RLock(), "peers": {}, "latest_settings_line": ""}
    main_peer_id = make_peer_id("main")
    ai_status_ref = {"server": None}
    chat_integration_ref = {"server": None, "db": None, "lock": threading.RLock()}
    napcat_ref = {"client": None, "workers": [], "lock": threading.RLock()}
    reminder_ref = {"scheduler": None, "restart_generation": 0}
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
        if sys.platform == "darwin":
            try:
                from macos_status_item import MacOSStatusItem, available as native_status_item_available

                if native_status_item_available():
                    tray_icon = MacOSStatusItem(
                        _tr("MainTray.tooltip"),
                        [
                            {
                                "title": _tr("MainTray.chat"),
                                "callback": lambda: QTimer.singleShot(0, launch_chat_process),
                            },
                            {
                                "title": _tr("MainTray.settings"),
                                "callback": lambda: QTimer.singleShot(
                                    0,
                                    lambda: launch_settings_process(show_launch=False),
                                ),
                            },
                            {
                                "title": _tr("MainTray.exit"),
                                "callback": lambda: QTimer.singleShot(0, quit_all),
                            },
                        ],
                    )
                    return
            except Exception as exc:
                print(f"Native macOS status item failed: {exc}", file=sys.stderr)

        tray_icon = QSystemTrayIcon(app)
        tray_icon.setIcon(load_tray_icon())
        tray_icon.setToolTip(_tr("MainTray.tooltip"))

        menu = QMenu(tray_anchor)
        chat_action = menu.addAction(_tr("MainTray.chat"))
        chat_action.triggered.connect(launch_chat_process)
        settings_action = menu.addAction(_tr("MainTray.settings"))
        settings_action.triggered.connect(lambda: launch_settings_process(show_launch=False))
        exit_action = menu.addAction(_tr("MainTray.exit"))
        exit_action.triggered.connect(lambda: QTimer.singleShot(0, quit_all))
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

        notify_child_processes_shutdown()
        close_settings_process(force=False, wait=False)
        close_chat_process(force=False, wait=False)
        close_pet_processes(force=False, wait=False)

        # Safety net: if the aboutToQuit handlers block or the event loop
        # stalls, force-terminate after a short delay so the process never
        # hangs on exit.
        def _force_exit():
            os._exit(0)

        force_exit_timer = threading.Timer(1.5, _force_exit)
        force_exit_timer.daemon = True
        force_exit_timer.start()

        scheduler = reminder_ref.get("scheduler")
        if scheduler is not None:
            scheduler.stop()

        def _quit_when_reminders_stop():
            if scheduler is not None and scheduler.has_running_workers():
                QTimer.singleShot(50, _quit_when_reminders_stop)
                return
            app.quit()

        QTimer.singleShot(50, _quit_when_reminders_stop)

    def init_ipc_server():
        def create_ipc_queues():
            inbound = SharedMemoryLineQueue.create(ipc_inbound_queue_key())
            reliable_inbound = SharedMemoryLineQueue.create(
                ipc_reliable_inbound_queue_key(), slot_count=32, slot_size=65536
            )
            try:
                outbound = SharedMemoryLineQueue.create(ipc_broadcast_queue_key())
                control = SharedMemoryLineQueue.create(
                    ipc_control_queue_key(), slot_count=16, slot_size=65536
                )
            except RuntimeError:
                inbound.close()
                reliable_inbound.close()
                if "outbound" in locals():
                    outbound.close()
                raise
            return inbound, reliable_inbound, outbound, control

        def start_ipc_polling(inbound, reliable_inbound, outbound, control):
            with ipc_ref["lock"]:
                ipc_ref["inbound"] = inbound
                ipc_ref["reliable_inbound"] = reliable_inbound
                ipc_ref["outbound"] = outbound
                ipc_ref["control"] = control
            poll_timer = QTimer(app)
            poll_timer.setInterval(15)
            poll_timer.timeout.connect(read_ipc_messages)
            poll_timer.start()
            cleanup_timer = QTimer(app)
            cleanup_timer.setInterval(3000)
            cleanup_timer.timeout.connect(prune_ipc_peers)
            cleanup_timer.start()
            ipc_ref["poll_timer"] = poll_timer
            ipc_ref["cleanup_timer"] = cleanup_timer

        try:
            inbound, reliable_inbound, outbound, control = create_ipc_queues()
        except RuntimeError as exc:
            first_error = str(exc)
            refresh_ipc_session_name()
            try:
                inbound, reliable_inbound, outbound, control = create_ipc_queues()
            except RuntimeError as retry_exc:
                exc = retry_exc
            else:
                print(f"Shared-memory IPC recovered with a fresh session name after: {first_error}")
                start_ipc_polling(inbound, reliable_inbound, outbound, control)
                return
            error = str(exc)
            message = (
                f"Shared-memory IPC failed to initialize: {error}. "
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
            return
        start_ipc_polling(inbound, reliable_inbound, outbound, control)

    def stop_ipc_server():
        with ipc_ref["lock"]:
            queues = [
                ipc_ref.pop("inbound", None),
                ipc_ref.pop("reliable_inbound", None),
                ipc_ref.pop("outbound", None),
                ipc_ref.pop("control", None),
            ]
            timers = [ipc_ref.pop("poll_timer", None), ipc_ref.pop("cleanup_timer", None)]
            ipc_ref["peers"] = {}
        for timer in timers:
            if timer is not None and isValid(timer):
                timer.stop()
                timer.deleteLater()
        for queue in queues:
            if queue is not None:
                queue.close()

    def broadcast_ipc_line(line: str, exclude_peer_id: str = ""):
        reliable = is_reliable_ipc_line(line)
        with ipc_ref["lock"]:
            queue = ipc_ref.get("control") if reliable else ipc_ref.get("outbound")
        if queue is None:
            return False
        return queue.publish(
            encode_ipc_envelope(
                main_peer_id,
                line,
                exclude_peer_id=exclude_peer_id,
                reliable=reliable,
            )
        )

    ai_event_bridge.line_received.connect(broadcast_ipc_line)

    def deliver_ipc_line(line: str, timeout: float = 1.0) -> bool:
        if threading.current_thread() is threading.main_thread():
            return broadcast_ipc_line(line)
        completion = {"event": threading.Event(), "delivered": False}
        ai_event_bridge.delivery_requested.emit(line, completion)
        if not completion["event"].wait(max(0.0, float(timeout))):
            return False
        return bool(completion["delivered"])

    def _complete_ipc_delivery(line: str, completion: dict):
        try:
            completion["delivered"] = broadcast_ipc_line(line)
        finally:
            completion["event"].set()

    ai_event_bridge.delivery_requested.connect(_complete_ipc_delivery)

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

    def init_reminder_scheduler(generation=None):
        if generation is None:
            reminder_ref["restart_generation"] += 1
            generation = reminder_ref["restart_generation"]
        elif generation != reminder_ref["restart_generation"]:
            return
        scheduler = reminder_ref.get("scheduler")
        if scheduler is not None:
            scheduler.stop()
            if scheduler.has_running_workers():
                QTimer.singleShot(50, lambda current=generation: init_reminder_scheduler(current))
                return
            scheduler.deleteLater()
        reminder_ref["scheduler"] = ReminderScheduler(
            cfg,
            mgr,
            broadcast_reminder_event,
            show_system_notification,
            app,
        )

    def stop_reminder_scheduler():
        reminder_ref["restart_generation"] += 1
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
        token = ensure_local_port_token(cfg, "ai_status_token")

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
            return False
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
        line = f"CHAT_EVENT\t{json.dumps(overlay, ensure_ascii=False)}"
        return deliver_ipc_line(line)

    def handle_chat_integration_message(event: dict) -> dict:
        with chat_integration_ref["lock"]:
            stored = chat_integration_db().add_external_chat_message(event)
        if not stored.get("duplicate"):
            overlay_delivered = broadcast_chat_overlay(event, stored)
            # Queue acceptance is not a read acknowledgement: a later burst can
            # still replace an overlay before a pet consumes it. Only the
            # explicit /chat-read endpoint clears persisted unread messages.
            stored["overlay_delivered"] = overlay_delivered
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
        token = ensure_local_port_token(cfg, "chat_integration_token")
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

        def delete_worker_when_stopped(worker):
            if not isValid(worker):
                return
            if worker.isRunning():
                QTimer.singleShot(50, lambda w=worker: delete_worker_when_stopped(w))
                return
            worker.deleteLater()

        for worker in workers:
            if isValid(worker) and worker.isRunning():
                cancel = getattr(worker, "cancel", None)
                if callable(cancel):
                    cancel()
                else:
                    worker.requestInterruption()
                if force:
                    worker.wait(500)
            if isValid(worker) and worker.isRunning():
                delete_worker_when_stopped(worker)
                continue
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
        duplicate = False
        if _napcat_should_save(_napcat_chat_type(event)):
            try:
                stored = handle_chat_integration_message(event)
                duplicate = bool(stored.get("duplicate"))
            except Exception as exc:
                print(f"NapCat message handling failed: {exc}")
                return
            _napcat_apply_retention()
        else:
            broadcast_napcat_transient_overlay(event)
        if not duplicate and _napcat_should_reply(event):
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
        cleanup_state = {"done": False, "timed_out": False}

        # Bound to the worker's lifetime rather than fired and forgotten: a
        # reply that finishes early cancels this immediately, so high-frequency
        # group messages don't pile up timers waiting out the full timeout.
        timeout_timer = QTimer(app)
        timeout_timer.setSingleShot(True)
        timeout_timer.setInterval(130_000)
        force_cleanup_timer = QTimer(app)
        force_cleanup_timer.setSingleShot(True)
        force_cleanup_timer.setInterval(5_000)

        def _stop_timeout_timer():
            if isValid(timeout_timer):
                timeout_timer.stop()
                timeout_timer.deleteLater()
            if isValid(force_cleanup_timer):
                force_cleanup_timer.stop()
                force_cleanup_timer.deleteLater()

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
            cleanup_state["timed_out"] = True
            if isValid(worker) and worker.isRunning():
                worker.cancel()
                force_cleanup_timer.start()
            else:
                _cleanup()

        def _force_timeout_cleanup():
            if not isValid(worker):
                _cleanup(delete_later=False)
                return
            if worker.isRunning():
                force_cleanup_timer.start()
                return
            _cleanup()

        def _on_destroyed():
            _stop_timeout_timer()
            with napcat_ref["lock"]:
                cleanup_state["done"] = True
                if worker in napcat_ref["workers"]:
                    napcat_ref["workers"].remove(worker)

        def _on_finished(full_text, _reasoning, _actions):
            if not _cleanup(delete_later=False):
                return
            if cleanup_state["timed_out"]:
                if isValid(worker):
                    worker.deleteLater()
                return
            clean = strip_action_tags(full_text)
            with napcat_ref["lock"]:
                client = napcat_ref.get("client")
            if clean and client is not None and isinstance(raw_event, dict):
                reply_sent = client.send_reply(
                    raw_event,
                    clean,
                    mention_sender=bool(cfg.get("napcat_reply_mention_sender", True)),
                )
                if reply_sent:
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
                else:
                    print("NapCat auto-reply could not be queued: connection is unavailable")
            if isValid(worker):
                worker.deleteLater()

        def _on_error(message):
            print(f"NapCat auto-reply failed: {message}")
            _cleanup()

        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.destroyed.connect(_on_destroyed)
        timeout_timer.timeout.connect(_on_timeout)
        force_cleanup_timer.timeout.connect(_force_timeout_cleanup)
        with napcat_ref["lock"]:
            napcat_ref["workers"].append(worker)
        worker.start()
        timeout_timer.start()

    def read_ipc_messages():
        with ipc_ref["lock"]:
            reliable_queue = ipc_ref.get("reliable_inbound")
            queue = ipc_ref.get("inbound")
        if reliable_queue is None or queue is None:
            return
        raw_lines = reliable_queue.read_available(max_messages=200)
        raw_lines += coalesce_latest_peer_positions(
            queue.read_available(max_messages=200)
        )
        for raw_line in raw_lines:
            envelope = decode_ipc_envelope(raw_line)
            if not envelope.line:
                continue
            if envelope.line.startswith(("REGISTER\t", "UNREGISTER\t")):
                handle_ipc_line(envelope.line, source_peer_id=envelope.sender_id)
                continue
            touch_ipc_peer(envelope.sender_id)
            handle_ipc_line(envelope.line, source_peer_id=envelope.sender_id)
    def touch_ipc_peer(peer_id: str):
        if not peer_id:
            return
        with ipc_ref["lock"]:
            peer = ipc_ref.setdefault("peers", {}).get(peer_id)
            if peer is not None:
                peer["last_seen"] = time.monotonic()

    def register_ipc_peer(line: str, peer_id: str):
        if not peer_id:
            return False
        parts = line.split("\t")
        kind = parts[1].strip().upper() if len(parts) >= 2 else "UNKNOWN"
        character = parts[2].strip() if len(parts) >= 3 else ""
        with ipc_ref["lock"]:
            is_new_peer = peer_id not in ipc_ref.setdefault("peers", {})
            ipc_ref.setdefault("peers", {})[peer_id] = {
                "kind": kind,
                "character": character,
                "last_seen": time.monotonic(),
            }
            latest_settings_line = ipc_ref.get("latest_settings_line", "")
        if is_new_peer and latest_settings_line:
            broadcast_ipc_line(latest_settings_line)
        return is_new_peer

    def remove_ipc_peers(peer_ids) -> list[str]:
        peer_ids = {str(peer_id or "") for peer_id in peer_ids if peer_id}
        if not peer_ids:
            return []
        with ipc_ref["lock"]:
            peers = ipc_ref.setdefault("peers", {})
            removed = [
                peers.pop(peer_id)
                for peer_id in peer_ids
                if peer_id in peers
            ]
            offline_characters = pet_characters_without_active_peers(
                removed,
                peers.values(),
            )
        return offline_characters

    def broadcast_offline_pet_characters(characters) -> None:
        for character in characters:
            payload = json.dumps({"character": character}, ensure_ascii=False)
            broadcast_ipc_line(f"PEER_OFFLINE\t{payload}")

    def unregister_ipc_peer(peer_id: str) -> bool:
        offline_characters = remove_ipc_peers([peer_id])
        broadcast_offline_pet_characters(offline_characters)
        return bool(offline_characters)

    def prune_ipc_peers(max_age_seconds: float = 8.0):
        now = time.monotonic()
        with ipc_ref["lock"]:
            peers = ipc_ref.setdefault("peers", {})
            stale = [
                peer_id
                for peer_id, peer in peers.items()
                if now - float(peer.get("last_seen", 0.0)) > max_age_seconds
            ]
        broadcast_offline_pet_characters(remove_ipc_peers(stale))

    def clear_ipc_peers(kind: str = ""):
        normalized = str(kind or "").upper()
        with ipc_ref["lock"]:
            peers = ipc_ref.setdefault("peers", {})
            if not normalized:
                peers.clear()
                return
            stale = [
                peer_id
                for peer_id, peer in peers.items()
                if str(peer.get("kind", "") or "").upper() == normalized
            ]
            for peer_id in stale:
                peers.pop(peer_id, None)

    def has_registered_pet_clients() -> bool:
        prune_ipc_peers()
        with ipc_ref["lock"]:
            return any(
                peer.get("kind") == "PET"
                for peer in ipc_ref.get("peers", {}).values()
            )

    def is_registered_pet_peer(peer_id: str) -> bool:
        if not peer_id:
            return False
        with ipc_ref["lock"]:
            peer = ipc_ref.setdefault("peers", {}).get(peer_id)
            return bool(peer and str(peer.get("kind", "") or "").upper() == "PET")

    def handle_ipc_line(line: str, source_peer_id: str = ""):
        if line.startswith("REGISTER\t"):
            register_ipc_peer(line, source_peer_id)
            return
        if line.startswith("UNREGISTER\t"):
            unregister_ipc_peer(source_peer_id)
            return
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
            if is_registered_pet_peer(source_peer_id):
                broadcast_ipc_line(line)
        elif line.startswith("PEER_DRAG\t"):
            if is_registered_pet_peer(source_peer_id):
                broadcast_ipc_line(line)
        elif line.startswith("PEER_DRAG_END\t"):
            if is_registered_pet_peer(source_peer_id):
                broadcast_ipc_line(line)
        elif line.startswith("PREVIEW_MOTION\t"):
            broadcast_ipc_line(line)
        elif line.startswith("LAYER_ORDER\t"):
            if is_registered_pet_peer(source_peer_id):
                broadcast_ipc_line(line)
        elif line.startswith("RADIAL_MENU_OPEN\t"):
            if is_registered_pet_peer(source_peer_id):
                broadcast_ipc_line(line)
        elif line.startswith("RADIAL_MENU_CLOSED\t"):
            if is_registered_pet_peer(source_peer_id):
                broadcast_ipc_line(line)
        elif line.startswith("OUTFIT_DESCRIPTION\t"):
            try:
                entry = json.loads(line.split("\t", 1)[1])
            except (json.JSONDecodeError, IndexError):
                return
            if not isinstance(entry, dict):
                return
            character = str(entry.get("character", "") or "").strip()
            costume = str(entry.get("costume", "") or "").strip()
            normalized = normalize_outfit_descriptions({
                outfit_description_key(character, costume): entry,
            })
            if not normalized:
                return
            cfg.load()
            descriptions = normalize_outfit_descriptions(
                cfg.get(OUTFIT_DESCRIPTIONS_KEY, {})
            )
            descriptions.update(normalized)
            cfg.set(OUTFIT_DESCRIPTIONS_KEY, descriptions)
            cfg.save()
        elif line == "FOCUS_CHAT":
            broadcast_ipc_line(line, exclude_peer_id=source_peer_id)
        elif line == "FOCUS_SETTINGS":
            broadcast_ipc_line(line, exclude_peer_id=source_peer_id)
        elif line.startswith("OPEN_SETTINGS"):
            handle_open_settings_request(line)
        elif line.startswith("MODEL\t") or line.startswith("SETTINGS\t") or line == "LAUNCH":
            handle_settings_line(line, source_peer_id=source_peer_id)

    def notify_child_processes_shutdown():
        broadcast_ipc_line("SHUTDOWN")

    def configured_models():
        from config_manager import load_configured_models

        result = load_configured_models(cfg, mgr)
        if not result and char and costume and mgr.get_model_json_path(char, costume):
            result.append({"character": char, "costume": costume, "path": mgr.get_model_json_path(char, costume)})
        return result

    def save_config():
        cfg.load()
        cfg.set("language", current_language())
        cfg.save()
        cfg.flush_save()

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

                    QTimer.singleShot(800, kill_if_still_running)
                    return
                if not process.waitForFinished(1000):
                    process.kill()
                    process.waitForFinished(1000)
        process.deleteLater()

    def close_pet_processes(force=False, wait=True):
        clear_ipc_peers("PET")
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

    def has_active_pet_processes() -> bool:
        return any(
            process
            and isValid(process)
            and process.state() != QProcess.ProcessState.NotRunning
            for process in pet_window_ref.get("processes", [])
        )

    def on_model_selected(selected_char, selected_costume, relaunch=False):
        nonlocal char, costume
        model_changed = (
            selected_char != pet_window_ref.get("char", char)
            or selected_costume != pet_window_ref.get("costume", costume)
        )
        char = selected_char
        costume = selected_costume
        pet_window_ref["char"] = selected_char
        pet_window_ref["costume"] = selected_costume
        if relaunch or (model_changed and has_active_pet_processes()):
            launch_pet()

    def _models_runtime_signature(models) -> tuple:
        if not isinstance(models, list):
            return ()
        signature = []
        for item in models:
            if not isinstance(item, dict):
                continue
            signature.append((
                str(item.get("character", "") or "").strip(),
                str(item.get("costume", "") or "").strip(),
                str(item.get("path", "") or "").strip(),
                str(item.get("pet_mode", "live2d") or "live2d").strip(),
            ))
        return tuple(signature)

    def on_settings_changed(data):
        nonlocal char, costume
        _SETTINGS_MAP = (
            ("fps", "fps", 120),
            ("opacity", "opacity", 1.0),
            ("dark_theme", "dark", False),
            ("vsync", "vsync", True),
            ("gpu_acceleration", "gpu_acceleration", True),
            ("game_topmost", "game_topmost", False),
            ("obs_window_capture_compatible", "obs_window_capture_compatible", False),
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
        selected_char = str(data.get("character", "") or "").strip()
        selected_costume = str(data.get("costume", "") or "").strip()
        selected_model_changed = bool(selected_char and selected_costume) and (
            selected_char != pet_window_ref.get("char", char)
            or selected_costume != pet_window_ref.get("costume", costume)
        )
        old_models_signature = _models_runtime_signature(cfg.get("models", []))
        new_models_signature = (
            _models_runtime_signature(data.get("models", []))
            if "models" in data
            else old_models_signature
        )
        models_runtime_changed = "models" in data and new_models_signature != old_models_signature
        old_vsync = bool(cfg.get("vsync", True))
        requested_vsync = bool(data.get("vsync", old_vsync))
        vsync_changed = "vsync" in data and requested_vsync != old_vsync
        pet_relaunch_requested = has_active_pet_processes() and (
            selected_model_changed
            or models_runtime_changed
            or vsync_changed
        )
        if selected_char and selected_costume:
            char = selected_char
            costume = selected_costume
            pet_window_ref["char"] = selected_char
            pet_window_ref["costume"] = selected_costume
        ai_status_keys = ("ai_status_port_enabled", "ai_status_port", "ai_status_token")
        chat_integration_keys = (
            "chat_integration_enabled", "chat_integration_port", "chat_integration_token"
        )
        napcat_keys = (
            "napcat_enabled", "napcat_ws_url", "napcat_access_token",
            "napcat_auto_reply_enabled", "napcat_reply_private", "napcat_reply_group_at_only",
            "napcat_reply_mention_sender", "napcat_reply_character", "napcat_save_policy",
            "napcat_group_retention_mode", "napcat_group_retention_days",
            "napcat_private_retention_mode", "napcat_private_retention_days",
        )
        attachment_retention_keys = (
            "chat_attachment_auto_cleanup_enabled", "chat_attachment_retention_days"
        )
        reminder_keys = (
            "alarms", "pomodoros", "proactive_companion", "proactive_care_policy",
            "reminder_display_mode", "screen_awareness_enabled",
            "screen_awareness_interval_minutes", "screen_awareness_character_mode",
            "screen_awareness_character", "screen_awareness_max_screenshot_width",
            "screen_awareness_model_mode", "screen_awareness_display_mode",
            "screen_awareness_include_process_name", "screen_awareness_include_window_title",
        )
        old_ai_status = tuple(cfg.get(key) for key in ai_status_keys)
        old_chat_integration = tuple(cfg.get(key) for key in chat_integration_keys)
        old_napcat = tuple(cfg.get(key) for key in napcat_keys)
        old_attachment_retention = tuple(cfg.get(key) for key in attachment_retention_keys)
        old_reminder = tuple(cfg.get(key) for key in reminder_keys)
        for cfg_key, ref_key, default in _SETTINGS_MAP:
            value = data.get(cfg_key, pet_window_ref.get(ref_key, cfg.get(cfg_key, default)))
            if cfg_key in ("ai_status_port", "chat_integration_port"):
                value = clamp_int(value, 1024, 65535, default)
            pet_window_ref[ref_key] = value
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
            "character_persona_presets",
            "character_persona_active",
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
        if selected_char and selected_costume:
            cfg.set("character", selected_char)
            cfg.set("costume", selected_costume)
        cfg.save()
        if pet_relaunch_requested:
            pet_window_ref["suppress_next_model_relaunch"] = (selected_char, selected_costume)
            launch_pet(persist_config=False)
        new_ai_status = tuple(cfg.get(key) for key in ai_status_keys)
        new_chat_integration = tuple(cfg.get(key) for key in chat_integration_keys)
        new_napcat = tuple(cfg.get(key) for key in napcat_keys)
        new_attachment_retention = tuple(cfg.get(key) for key in attachment_retention_keys)
        new_reminder = tuple(cfg.get(key) for key in reminder_keys)
        if old_ai_status != new_ai_status or (cfg.get("ai_status_port_enabled", False) and ai_status_ref.get("server") is None):
            init_ai_status_server()
        if old_chat_integration != new_chat_integration or (cfg.get("chat_integration_enabled", False) and chat_integration_ref.get("server") is None):
            init_chat_integration_server()
        if old_napcat != new_napcat or (cfg.get("napcat_enabled", False) and napcat_ref.get("client") is None):
            init_napcat_adapter()
        if old_attachment_retention != new_attachment_retention:
            apply_chat_attachment_retention()
        scheduler = reminder_ref.get("scheduler")
        if scheduler is not None:
            if old_reminder != new_reminder:
                scheduler.reload()
            if data.get("screen_awareness_test_requested"):
                scheduler.trigger_screen_awareness_now()

    def launch_pet(persist_config=True):
        nonlocal mgr
        if persist_config:
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
            "fps", "opacity", "vsync", "game_topmost", "obs_window_capture_compatible",
            "chat_window_normal_window", "hide_live2d_model",
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
        if persist_config:
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
        old_processes = [
            process
            for process in list(pet_window_ref.get("processes", []))
            if process and isValid(process)
        ]
        clear_ipc_peers("PET")
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
        for process in old_processes:
            if process.state() != QProcess.ProcessState.NotRunning:
                closing = pet_window_ref.setdefault("closing_processes", [])
                if process not in closing:
                    closing.append(process)
            _close_qprocess(process, force=False, wait=False)

    def _read_process_error(process):
        if not isValid(process):
            return
        data = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if data:
            try:
                print(data)
            except UnicodeEncodeError:
                safe = data.encode("ascii", errors="replace").decode("ascii")
                print(safe)

    def _read_settings_process_output(process):
        if not isValid(process):
            return
        data = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not data:
            return
        buffer = settings_process_ref.get("stdout_buffer", "") + data
        lines = buffer.split("\n")
        settings_process_ref["stdout_buffer"] = lines.pop() if lines else ""
        for line in lines:
            line = line.rstrip("\r")
            if line:
                handle_settings_line(line)

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
            broadcast_ipc_line("FOCUS_CHAT")
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

        if pet_window_ref.get("processes") and has_registered_pet_clients():
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

    def handle_settings_line(line, source_peer_id=""):
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
                suppressed = pet_window_ref.pop("suppress_next_model_relaunch", None)
                if suppressed == (character, costume):
                    relaunch = False
                on_model_selected(character, costume, relaunch=relaunch)
        elif line.startswith("SETTINGS\t"):
            try:
                payload = json.loads(line.split("\t", 1)[1])
            except json.JSONDecodeError:
                return
            with ipc_ref["lock"]:
                ipc_ref["latest_settings_line"] = line
            on_settings_changed(payload)
            broadcast_ipc_line(line, exclude_peer_id=source_peer_id)
        elif line == "LAUNCH":
            settings_process_ref["launched"] = True
            launch_pet(persist_config=False)
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
            settings_process_ref.pop("stdout_buffer", None)
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
        existing = settings_process_ref.get("process")
        if existing is not None and existing.state() != QProcess.ProcessState.NotRunning:
            if start_on_costumes:
                broadcast_ipc_line(f"SHOW_COSTUMES\t{costume_character}")
            else:
                broadcast_ipc_line("FOCUS_SETTINGS")
            return
        cfg.load()
        current_char = costume_character if start_on_costumes and costume_character else cfg.get("character", char)
        current_costume = cfg.get("costume", costume)
        # ``show_launch`` is used only by the startup no-model path. Avoid a
        # second synchronous model scan here; the settings process performs its
        # own authoritative scan before constructing the model UI.
        first_run_wizard = bool(show_launch)
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
        process.readyReadStandardOutput.connect(lambda p=process: _read_settings_process_output(p))
        process.readyReadStandardError.connect(lambda p=process: _read_process_error(p))
        process.finished.connect(lambda *args, p=process: on_settings_process_finished(p))
        settings_process_ref["process"] = process
        settings_process_ref["show_launch"] = show_launch
        settings_process_ref["first_run_wizard"] = first_run_wizard
        settings_process_ref["launched"] = False
        settings_process_ref["stdout_buffer"] = ""
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
    app.aboutToQuit.connect(notify_child_processes_shutdown)
    app.aboutToQuit.connect(stop_ai_status_server)
    app.aboutToQuit.connect(stop_chat_integration_server)
    app.aboutToQuit.connect(lambda: stop_napcat_adapter(force=True))
    app.aboutToQuit.connect(stop_reminder_scheduler)
    app.aboutToQuit.connect(close_chat_integration_db)
    app.aboutToQuit.connect(end_usage_session)
    app.aboutToQuit.connect(lambda: close_settings_process(force=False, wait=False))
    app.aboutToQuit.connect(lambda: close_chat_process(force=False, wait=False))
    app.aboutToQuit.connect(lambda: close_pet_processes(force=False, wait=False))
    app.aboutToQuit.connect(stop_ipc_server)

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
