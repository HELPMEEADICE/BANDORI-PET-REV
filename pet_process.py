import argparse
import json
import os
import subprocess
import sys
import threading

from process_utils import (
    bootstrap_app,
    ensure_xwayland,
    hidden_subprocess_kwargs,
    install_parent_death_watch,
    process_program_and_args,
    set_windows_app_user_model_id,
)

BASE_DIR, _STARTUP_CONFIG = bootstrap_app()

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmapCache
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QVBoxLayout

from app_theme import apply_app_theme
from app_info import APP_NAME
from i18n_manager import detect_system_language, set_language
from live2d_widget import Live2DWidget
from live2d_lua_adapter import live2d_for_format
from model_manager import (
    MODEL_FORMAT_MOC,
    MODEL_FORMAT_MOC3,
    ModelManager,
    models_dir_exists,
    prompt_download_model_resources,
)
from pet_window import PetWindow
from gpu_acceleration import configure_qt_gpu_acceleration
from tray_utils import load_tray_icon


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one isolated Live2D pet process.")
    parser.add_argument("--character", required=True)
    parser.add_argument("--costume", required=True)
    parser.add_argument("--model-path", default="")
    parser.add_argument("--model-format", choices=(MODEL_FORMAT_MOC, MODEL_FORMAT_MOC3), default="")
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--group-characters", default="")
    return parser.parse_args()


def _parse_group_characters(value: str) -> list[str]:
    try:
        parsed = json.loads(value) if value else []
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    result = []
    seen = set()
    for item in parsed:
        character = str(item or "").strip()
        if character and character not in seen:
            result.append(character)
            seen.add(character)
    return result


def _make_main_relauncher(index: int, normal_shutdown_requested: threading.Event):
    restarted = threading.Event()

    def _relaunch_main_if_abnormal_parent_exit():
        if index != 0 or normal_shutdown_requested.is_set() or restarted.is_set():
            return
        restarted.set()
        env = os.environ.copy()
        env.pop("BANDORI_PET_IPC_SERVER_NAME", None)
        env["BANDORI_PET_RESTARTED_FROM_CHILD"] = "1"
        program, arguments = process_program_and_args(BASE_DIR, "main.py", [])
        try:
            subprocess.Popen(
                [program, *arguments],
                cwd=BASE_DIR,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **hidden_subprocess_kwargs(),
            )
        except OSError as exc:
            print(f"Failed to restart main process after parent exit: {exc}", file=sys.stderr)

    return _relaunch_main_if_abnormal_parent_exit


class SingleModelManager:
    def __init__(self, character: str, costume: str, model_path: str, model_format: str = ""):
        self._character = character
        self._costume = costume
        self._model_path = model_path
        self._model_format = model_format if model_format in {MODEL_FORMAT_MOC, MODEL_FORMAT_MOC3} else ""
        self._metadata_manager = None
        self._fallback_manager = None

    def _get_metadata_manager(self):
        if self._metadata_manager is None:
            self._metadata_manager = ModelManager(scan_models=False, discover_models=False)
        return self._metadata_manager

    @property
    def characters(self) -> list[str]:
        return [self._character] if self._character else []

    def get_default_costume(self, character: str) -> str:
        return self._costume if character == self._character else ""

    def get_model_json_path(self, character: str, costume: str) -> str:
        if character == self._character and costume == self._costume:
            return self._model_path
        if self._fallback_manager is None:
            self._fallback_manager = ModelManager()
        return self._fallback_manager.get_model_json_path(character, costume)

    def get_model_format(self, character: str, costume: str) -> str:
        path = self.get_model_json_path(character, costume)
        if not path:
            return ""
        if character == self._character and costume == self._costume and self._model_format:
            return self._model_format
        return self._get_metadata_manager()._model_format_from_path(path)

    def get_display_name(self, character: str) -> str:
        return self._get_metadata_manager().get_display_name(character)

    def get_costume_display_name(self, character: str, costume_id: str) -> str:
        return self._get_metadata_manager().get_costume_display_name(character, costume_id)


def main():
    ensure_xwayland()
    os.chdir(BASE_DIR)
    args = _parse_args()
    live2d = live2d_for_format(args.model_format)
    cfg = _STARTUP_CONFIG
    set_language(cfg.get("language", "") or detect_system_language())

    configure_qt_gpu_acceleration(QApplication, Qt, cfg)
    Live2DWidget.configure_default_surface_format(cfg.get("vsync", True))
    set_windows_app_user_model_id(APP_NAME)

    app = QApplication(sys.argv)
    # Pet processes only need a handful of tray/window icons. The Qt default
    # cache is sized for full desktop applications and is duplicated per pet.
    QPixmapCache.setCacheLimit(2048)
    app.setWindowIcon(load_tray_icon())
    normal_shutdown_requested = threading.Event()
    install_parent_death_watch(
        app,
        on_parent_death=_make_main_relauncher(args.index, normal_shutdown_requested),
    )

    import macos_patch
    macos_patch.hide_dock_icon_if_needed()

    app.setApplicationName(f"{APP_NAME}-{args.character}")
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    apply_app_theme(cfg.get("dark_theme", False), include_fluent=False)

    if not args.model_path and not models_dir_exists():
        prompt_download_model_resources()
        return 0

    mgr = (
        SingleModelManager(
            args.character,
            args.costume,
            args.model_path,
            args.model_format,
        )
        if args.model_path
        else ModelManager()
    )
    group_characters = (
        _parse_group_characters(args.group_characters)
        if args.group_characters
        else None
    )
    pet = PetWindow(
        live2d,
        model_manager=mgr,
        character=args.character,
        costume=args.costume,
        fps=cfg.get("fps", 120),
        opacity=cfg.get("opacity", 1.0),
        config_manager=cfg,
        enable_tray=False,
        group_characters=group_characters,
        on_shutdown_requested=normal_shutdown_requested.set,
    )

    from plugin_system.bridge import PluginComponentBridge
    from plugin_system.native import NativePluginLoader

    plugin_bridge = PluginComponentBridge("pet", app)
    pet._plugin_bridge = plugin_bridge
    plugin_bridge.register_service("pet.info", lambda _payload: {
        "character": pet._current_char,
        "costume": pet._current_costume,
        "mode": "pixel" if pet._pixel_mode else "live2d",
        "visible": pet.isVisible(),
        "position": {"x": pet.x(), "y": pet.y()},
    }, permission="pet.read")
    plugin_bridge.register_service("pet.motion.play", lambda payload: (
        pet._start_click_motion(
            str((payload or {}).get("motion", "") or ""),
            str((payload or {}).get("expression", "") or ""),
        ) or {"ok": True}
    ), permission="pet.control")
    plugin_bridge.register_service("pet.expression.set", lambda payload: (
        pet._apply_click_expression(str((payload or {}).get("expression", "") or ""))
        or {"ok": True}
    ), permission="pet.control")
    plugin_bridge.register_service("pet.position.set", lambda payload: (
        pet.move(int((payload or {}).get("x", pet.x())), int((payload or {}).get("y", pet.y())))
        or {"ok": True}
    ), permission="pet.control")
    plugin_bridge.register_service("pet.visibility.set", lambda payload: (
        pet.setVisible(bool((payload or {}).get("visible", True))) or {"ok": True}
    ), permission="pet.control")
    plugin_bridge.connect()

    plugin_overlay = QFrame(pet)
    plugin_overlay.setObjectName("pluginPetOverlay")
    plugin_overlay.setStyleSheet(
        "#pluginPetOverlay { background: rgba(20, 20, 28, 150); border-radius: 8px; }"
        "QLabel, QPushButton { color: white; }"
    )
    plugin_overlay_layout = QVBoxLayout(plugin_overlay)
    plugin_overlay_layout.setContentsMargins(7, 6, 7, 6)
    plugin_overlay_layout.setSpacing(4)

    def refresh_plugin_pet_overlay():
        while plugin_overlay_layout.count():
            item = plugin_overlay_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for contribution in plugin_bridge.contributions("ui", "pet_overlay"):
            spec = contribution.get("spec", {})
            if not isinstance(spec, dict):
                continue
            label = str(spec.get("label", spec.get("text", contribution.get("id", ""))) or "")
            if spec.get("interactive", False):
                widget = QPushButton(label, plugin_overlay)

                def clicked(_checked=False, item=contribution):
                    payload = {
                        "plugin_id": item.get("plugin_id", ""),
                        "component_id": item.get("id", ""),
                        "character": pet._current_char,
                    }
                    result = plugin_bridge.dispatch_event("pet.overlay.action.before", payload)
                    if not result.get("cancelled"):
                        plugin_bridge.notify_event("pet.overlay.action", result.get("payload", payload))

                widget.clicked.connect(clicked)
            else:
                widget = QLabel(label, plugin_overlay)
            plugin_overlay_layout.addWidget(widget)
        plugin_overlay.adjustSize()
        plugin_overlay.move(8, 8)
        plugin_overlay.setVisible(plugin_overlay_layout.count() > 0)

    plugin_bridge.contributions_changed.connect(refresh_plugin_pet_overlay)
    refresh_plugin_pet_overlay()

    native_plugin_loader = NativePluginLoader(
        "pet",
        transport_factory=plugin_bridge.native_transport,
        application=app,
        controller=pet,
        window=pet,
        objects={"model_manager": mgr, "config": cfg, "live2d": live2d},
    )
    native_plugin_loader.load_all()

    def close_mcp_clients_on_shutdown():
        # MCP networking is not used while constructing the pet. Import it only
        # if shutdown actually needs to dispose a client created later.
        from mcp_bridge import close_mcp_clients

        close_mcp_clients()

    offset_x = args.index * (28 if pet._pixel_mode else 36)
    pet.restore_saved_position(offset_x=offset_x)

    pet.set_vsync(cfg.get("vsync", True))
    if cfg.get("drag_locked", False):
        pet._live2d_widget.set_drag_locked(True)
        pet._pixel_widget.set_drag_locked(True)

    app.aboutToQuit.connect(lambda: pet._close_radial_menu_process(force=True))
    app.aboutToQuit.connect(lambda: pet._close_chat_process())
    app.aboutToQuit.connect(lambda: pet._close_compact_ai_window())
    app.aboutToQuit.connect(close_mcp_clients_on_shutdown)
    app.aboutToQuit.connect(lambda: pet._close_settings_process())
    app.aboutToQuit.connect(pet._send_ipc_unregistration)
    app.aboutToQuit.connect(pet._close_ipc_bus)
    app.aboutToQuit.connect(pet._save_position_config)
    app.aboutToQuit.connect(pet._flush_save)
    app.aboutToQuit.connect(live2d.dispose)
    app.aboutToQuit.connect(native_plugin_loader.close)
    app.aboutToQuit.connect(plugin_bridge.close)

    if not cfg.get("hide_live2d_model", False):
        pet.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
