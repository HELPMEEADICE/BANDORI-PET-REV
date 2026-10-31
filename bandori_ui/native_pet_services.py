"""UI-side services for native pets. Lives in main.py's process, never in Rust.

Owns menus, chat windows, compact overlays, plugin services, and persistence.
The native process owns all pet pixels, animation, input and window behavior.
"""
import json
import time
import uuid

from PySide6.QtCore import QObject, QPoint, QProcess, QRect, QTimer

from bandori_core.ipc_bus import radial_command_queue_key, radial_event_queue_key
from bandori_core.process_utils import app_base_dir, process_program_and_args
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue


class NativePetServices(QObject):
    def __init__(self, app, config, manager, broadcast, open_settings):
        super().__init__(app)
        self.cfg = config
        self.manager = manager
        self.broadcast = broadcast
        self.open_settings = open_settings
        self.roles = {}
        self._menus = {}
        self._chats = {}
        self._overlays = {}
        self._plugin_bridge = None
        self._meter = None
        self._springs = {}
        self._last_music = time.monotonic()
        self._closed = False
        self._captures = {}
        self._outfit_workers = {}
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        app.aboutToQuit.connect(self.close)
        self._connect_plugins(app)

    def _connect_plugins(self, app):
        from plugin_system.bridge import PluginComponentBridge
        bridge = PluginComponentBridge("pet", app)
        self._plugin_bridge = bridge

        def target(payload):
            character = str((payload or {}).get("character", ""))
            return character or next(iter(self.roles), "")

        bridge.register_service("pet.info", lambda p: self.roles.get(target(p), {}), permission="pet.read")
        for service, command in (("pet.motion.play", "action"), ("pet.expression.set", "expression"),
                                 ("pet.position.set", "position"), ("pet.visibility.set", "visibility")):
            def control(payload, command=command):
                data = dict(payload or {})
                if command == "action":
                    self.broadcast("PREVIEW_MOTION\t{}\t{}\t{}".format(target(data), data.get("motion", ""), data.get("expression", "")))
                else:
                    self.control(target(data), command, **{k: v for k, v in data.items() if k != "character"})
                return {"ok": True}
            bridge.register_service(service, control, permission="pet.control")
        bridge.connect()

    def configure_models(self, models):
        active = {model.get("character"): model for model in models}
        for char in set(self.roles) - set(active):
            self.roles.pop(char, None)
            overlay = self._overlays.pop(char, None)
            if overlay:
                overlay.close()
            state = self._menus.get(char)
            if state:
                state["commands"].publish("QUIT")
        for char, model in active.items():
            role = self.roles.setdefault(char, {"character": char, "visible": True})
            role["costume"] = model.get("costume", "")
            role["mode"] = model.get("pet_mode", "live2d")
            role["path"] = model.get("path", "")

    def control(self, character, command, **data):
        data.update(character=character, command=command)
        self.broadcast("NATIVE_CONTROL\t" + json.dumps(data, ensure_ascii=False))

    def handle_event(self, event):
        if not isinstance(event, dict):
            return
        char = str(event.get("character", ""))
        if not char:
            return
        data = event.get("data", {})
        if not isinstance(data, dict):
            return
        role = self.roles.setdefault(char, {"character": char, "costume": event.get("costume", ""), "visible": True})
        if role.get("costume") and event.get("costume") != role["costume"]:
            return
        kind = event.get("event")
        if kind == "ready":
            if self.cfg.get("compact_ai_window_enabled", False) and not self.cfg.get("compact_ai_window_auto_hide", False):
                self._ensure_overlay(char).show()
            self._request_outfit_description(char)
        elif kind == "hover":
            self._on_pet_hover(char, bool(data.get("inside", False)))
        elif kind == "snapshot":
            self._start_outfit_description(char, data.get("path", ""))
        elif kind == "placement":
            role["placement"] = data
            self._save_placement(char, event.get("costume", ""), data)
        elif kind == "context_menu":
            self.show_menu(char, data)
        elif kind == "double_click":
            from bandori_core.action_bus import publish_user_poke
            publish_user_poke(char, source="live2d")
        elif kind == "clicked" and self._plugin_bridge:
            self._plugin_bridge.notify_event("pet.clicked", {"character": char, **data})
        elif kind == "error":
            print("Neocari: " + str(data.get("message", "unknown backend error")))

    def handle_line(self, line):
        command, _, raw = line.partition("\t")
        if command == "OPEN_CHAT":
            char = raw or next(iter(self.roles), "")
            if char:
                self.open_chat(char)
            return
        if command not in {"PEER_POS", "PEER_OFFLINE", "AI_EVENT", "CHAT_EVENT", "REMINDER_EVENT", "POKE_USER", "SETTINGS"}:
            return
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if command == "SETTINGS":
            if "compact_ai_window_enabled" in data:
                auto_hide = self.cfg.get("compact_ai_window_auto_hide", False)
                for char in self.roles:
                    if not data["compact_ai_window_enabled"]:
                        if char in self._overlays:
                            self._overlays[char].hide()
                    elif not auto_hide:
                        self._ensure_overlay(char).show()
            reset_position = bool(data.get("compact_ai_window_reset_position", False))
            for char, overlay in self._overlays.items():
                overlay.refresh_theme()
                if reset_position:
                    overlay.reset_position_offset()
                    self._position_overlay(char, overlay)
                overlay.apply_auto_hide_setting()
            return
        char = str(data.get("character") or data.get("target_character") or "")
        if command == "PEER_OFFLINE":
            self.roles.pop(char, None)
            overlay = self._overlays.pop(char, None)
            if overlay:
                overlay.close()
            return
        if command == "PEER_POS":
            role = self.roles.setdefault(char, {"character": char, "visible": True})
            role["position"] = data
            overlay = self._overlays.get(char)
            if overlay and overlay.isVisible():
                self._position_overlay(char, overlay)
            return
        if not self.cfg.get("compact_ai_window_enabled", False):
            return
        enabled_key = {"AI_EVENT": "ai_event_overlay_enabled", "CHAT_EVENT": "chat_integration_overlay_enabled"}.get(command)
        if enabled_key and not self.cfg.get(enabled_key, True):
            return
        characters = [char] if char else list(self.roles)
        for char in characters:
            if char not in self.roles:
                continue
            overlay = self._ensure_overlay(char)
            self._position_overlay(char, overlay)
            overlay.reveal()
            overlay.apply_ai_event(data)

    def _on_pet_hover(self, char, inside):
        reveal = bool(
            self.cfg.get("compact_ai_window_enabled", False)
            and self.cfg.get("compact_ai_window_auto_hide", False)
            and self.cfg.get("compact_ai_window_show_on_hover", True)
        )
        overlay = self._overlays.get(char)
        if overlay is None:
            if not (inside and reveal):
                return
            overlay = self._ensure_overlay(char)
        elif inside and not overlay.isVisible():
            self._position_overlay(char, overlay)
        overlay.set_pet_hovered(inside, reveal=reveal)

    def _ensure_overlay(self, char):
        overlay = self._overlays.get(char)
        if overlay is None:
            from bandori_chat.compact_ai_window import CompactAIWindow
            overlay = CompactAIWindow(char, self.manager, self.cfg)
            overlay.action_triggered.connect(lambda action, c=char: self.broadcast(f"ACTION\t{c}\t{action}"))
            self._overlays[char] = overlay
        self._position_overlay(char, overlay)
        return overlay

    def _position_overlay(self, char, overlay):
        pos = self.roles.get(char, {}).get("position", {})
        x, y = int(pos.get("x", 100)), int(pos.get("y", 100))
        w, h = int(pos.get("w", 400)), int(pos.get("h", 0))
        default = QPoint(x + w // 2 - overlay.width() // 2, max(0, y - overlay.height() - 8))
        overlay.place_near_pet(QRect(x, y, w, h), default)

    def _request_outfit_description(self, char):
        if not self.cfg.get("llm_live2d_outfit_recognition_enabled", False):
            return
        from bandori_models.outfit_description import model_fingerprint
        from bandori_models.outfit_description_config import outfit_description_key
        from bandori_core.process_utils import app_data_dir
        role = self.roles.get(char, {})
        if role.get("mode") == "pixel" or not role.get("path"):
            return
        costume = role.get("costume", "")
        fingerprint = model_fingerprint(role["path"])
        cached = self.cfg.get("outfit_descriptions", {}).get(outfit_description_key(char, costume), {})
        if cached.get("description") and cached.get("model_fingerprint") == fingerprint:
            return
        directory = app_data_dir() / ".cache" / "native-captures"
        directory.mkdir(parents=True, exist_ok=True)
        path = str(directory / (uuid.uuid4().hex + ".png"))
        self._captures[path] = (char, costume, fingerprint)
        self.control(char, "snapshot", path=path)

    def _start_outfit_description(self, char, path):
        import base64
        from pathlib import Path
        capture = self._captures.pop(path, None)
        if capture is None or capture[0] != char:
            return
        _, costume, fingerprint = capture
        try:
            image = "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")
        finally:
            Path(path).unlink(missing_ok=True)
        if self.roles.get(char, {}).get("costume") != costume:
            return
        from bandori_models.outfit_description import OutfitDescriptionWorker, make_outfit_description_entry
        from bandori_services.network_worker import delete_thread_when_stopped
        costume_name = self.manager.get_costume_display_name(char, costume)
        worker = OutfitDescriptionWorker(dict(getattr(self.cfg, "_data", {})), image,
            self.manager.get_display_name(char), costume, costume_name)
        key = (char, costume)
        self._outfit_workers[key] = worker

        def finished(description="", source=""):
            self._outfit_workers.pop(key, None)
            if description and not self._closed and self.roles.get(char, {}).get("costume") == costume:
                from bandori_core.ipc_bus import send_ipc_message
                entry = make_outfit_description_entry(char, costume, costume_name, description, fingerprint, source)
                send_ipc_message("OUTFIT_DESCRIPTION\t" + json.dumps(entry, ensure_ascii=False))
            delete_thread_when_stopped(worker)

        worker.finished.connect(finished)
        worker.error.connect(lambda _error: finished())
        worker.start()

    def _save_placement(self, char, costume, placement):
        self.cfg.load()
        models = list(self.cfg.get("models", []))
        for model in models:
            if model.get("character") == char and model.get("costume") == costume:
                pixel = model.get("pet_mode") == "pixel"
                model["pixel_window_placement" if pixel else "window_placement"] = placement
                for key in ("x", "y", "width", "height"):
                    prefix = "pixel_window_" if pixel else "window_"
                    model[prefix + key] = placement.get(key, model.get(prefix + key, 0))
                self.cfg.set("models", models)
                self.cfg.save()
                return

    def open_chat(self, char):
        existing = self._chats.get(char)
        if existing and existing.state() != QProcess.ProcessState.NotRunning:
            self.broadcast(f"FOCUS_CHAT\t{char}")
            return
        pos = self.roles.get(char, {}).get("position", {})
        program, args = process_program_and_args(str(app_base_dir()), "chat_process.py", [
            "--character", char, "--pet-x", str(int(pos.get("x", 100))),
            "--pet-y", str(int(pos.get("y", 100))), "--pet-w", str(int(pos.get("w", 400))),
            "--pet-h", str(int(pos.get("h", 500))), "--group-characters", json.dumps(list(self.roles)),
            "--start-private-chat",
        ])
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(args)
        process.setWorkingDirectory(str(app_base_dir()))
        process.finished.connect(lambda *_: self._chat_finished(char, process))
        process.errorOccurred.connect(lambda *_: self._chat_finished(char, process))
        self._chats[char] = process
        process.start()

    def _chat_finished(self, char, process):
        if self._chats.get(char) is process:
            self._chats.pop(char, None)
        process.deleteLater()

    def show_menu(self, char, position):
        from bandori_core.i18n_manager import tr
        state = self._menus.get(char)
        if state is None:
            name = "neocari-menu-" + uuid.uuid4().hex
            commands = SharedMemoryLineQueue.create(radial_command_queue_key(name), slot_count=8, slot_size=8192)
            events = SharedMemoryLineQueue.create(radial_event_queue_key(name), slot_count=8, slot_size=4096)
            program, args = process_program_and_args(str(app_base_dir()), "radial_menu_process.py", ["--channel-name", name])
            process = QProcess(self)
            process.setProgram(program)
            process.setArguments(args)
            process.setWorkingDirectory(str(app_base_dir()))
            state = {"commands": commands, "events": events, "process": process, "ready": False, "pending": None}
            self._menus[char] = state
            process.finished.connect(lambda *_: self._menu_finished(char, state))
            process.start()
        items = []
        for action, glyph, color in (("chat", "💬", [138,43,226]), ("costume", "👗", [220,50,120]), ("motion", "🎬", [30,144,255]), ("pixel", "2D", [124,92,210])):
            if action == "pixel" and not (app_base_dir() / "pixels" / (char + ".webp")).is_file():
                continue
            items.append({"action": action, "label": tr("PetWindow.radial_" + action), "glyph": glyph, "color": color, "enabled": True})
        # The menu process converts the captured native point with its own Qt
        # screen geometry. Keep the monitor metadata through this relay.
        payload = dict(position)
        payload.update(locked=bool(self.cfg.get("drag_locked", False)), items=items)
        state["pending"] = "SHOW\t" + json.dumps(payload, ensure_ascii=False)

    def _menu_finished(self, char, state):
        if self._menus.get(char) is state:
            self._menus.pop(char, None)
        state["commands"].close()
        state["events"].close()
        state["process"].deleteLater()

    def _poll(self):
        for char, state in list(self._menus.items()):
            for line in state["events"].read_available():
                if line == "READY":
                    state["ready"] = True
                elif line.startswith("ACT\t"):
                    action = line.split("\t", 1)[1]
                    if action == "chat": self.open_chat(char)
                    elif action == "costume": self.open_settings(f"OPEN_SETTINGS\tcostumes\t{char}")
                    elif action == "motion": self.control(char, "motion")
                    elif action == "pixel": self._toggle_pixel(char)
                elif line.startswith("LOCK\t"):
                    locked = line.endswith("1")
                    self.cfg.load()
                    self.cfg.set("drag_locked", locked)
                    self.cfg.save()
                    self.broadcast("SETTINGS\t" + json.dumps({"drag_locked": locked}))
            if state["ready"] and state["pending"] and state["commands"].publish(state["pending"]):
                state["pending"] = None
        self._music_tick()

    def _toggle_pixel(self, char):
        import copy
        self.cfg.load()
        models = copy.deepcopy(self.cfg.get("models", []))
        for model in models:
            if model.get("character") == char:
                model["pet_mode"] = "live2d" if model.get("pet_mode") == "pixel" else "pixel"
                from bandori_core.ipc_bus import send_ipc_message
                send_ipc_message("SETTINGS\t" + json.dumps({"models": models}, ensure_ascii=False))
                return

    def _music_tick(self):
        from bandori_audio.music_bounce import MusicSpring, OutputLevelMonitor, music_bounce_supported
        enabled = self.cfg.get("music_bounce_enabled", False) and music_bounce_supported()
        if enabled and self._meter is None:
            self._meter = OutputLevelMonitor()
            self._meter.start()
        if not enabled:
            if self._meter:
                self._meter.stop()
                self._meter = None
                for char in self.roles: self.control(char, "music_scale", scale=1.0)
                self._springs.clear()
            return
        now = time.monotonic()
        dt, self._last_music = min(now - self._last_music, 0.1), now
        for char in self.roles:
            spring = self._springs.setdefault(char, MusicSpring())
            displacement = spring.step(self._meter.level(), dt)
            self.control(char, "music_scale", scale=max(0.65, min(1.20, 1.0 + displacement * 0.32)))

    def close(self):
        if self._closed:
            return
        self._closed = True
        for worker in list(self._outfit_workers.values()):
            worker.cancel()
            # Cancelling closes the active HTTP response; retain the worker
            # until its QThread has actually stopped before releasing it.
            worker.wait(1500)
        from pathlib import Path
        for path in self._captures:
            Path(path).unlink(missing_ok=True)
        self._captures.clear()
        self._timer.stop()
        if self._meter:
            self._meter.stop()
        for overlay in self._overlays.values(): overlay.close()
        self._overlays.clear()
        for state in list(self._menus.values()):
            state["commands"].publish("QUIT")
            process = state["process"]
            if not process.waitForFinished(500):
                process.kill()
                process.waitForFinished(500)
        for process in list(self._chats.values()):
            process.terminate()
            if not process.waitForFinished(500): process.kill()
        if self._plugin_bridge:
            self._plugin_bridge.close()
