import argparse
import json
import os
import select
import sys

from bandori_core.process_utils import (
    app_base_dir,
    configure_debug_logging,
    configure_frozen_runtime_paths,
    install_parent_death_watch,
    interaction_trace,
    set_windows_app_user_model_id,
)
from wayland.environment import configure_native_wayland

configure_debug_logging()
configure_frozen_runtime_paths()
configure_native_wayland()

BASE_DIR = str(app_base_dir())

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication

from bandori_core.app_info import APP_NAME
from bandori_core.ipc_bus import AdaptivePollInterval, radial_command_queue_key, radial_event_queue_key
from bandori_ui.radial_menu import RadialMenu
from bandori_core.shared_memory_ipc import SharedMemoryLineQueue


_EVENT_QUEUE = None
_STDIO_MODE = False


def _parse_args():
    parser = argparse.ArgumentParser(description="Show radial menu in a separate process.")
    parser.add_argument("--channel-name", default="")
    parser.add_argument("--stdio", action="store_true")
    return parser.parse_args()


def _emit(line: str):
    if _STDIO_MODE:
        print(line, flush=True)
        return
    if _EVENT_QUEUE is not None:
        _EVENT_QUEUE.publish(line)


def _payload_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    return items if isinstance(items, list) else []


def _item_color(item: dict) -> QColor | None:
    color_values = item.get("color") or [80, 80, 80]
    if len(color_values) != 3:
        return None
    return QColor(int(color_values[0]), int(color_values[1]), int(color_values[2]))


def _menu_position(payload: dict) -> QPoint:
    x, y = float(payload.get("x", 0)), float(payload.get("y", 0))
    if payload.get("coordinate_space") != "native_physical":
        # Legacy Qt callers and AppKit already supply desktop logical points.
        return QPoint(round(x), round(y))
    native = payload.get("screen_geometry")
    if not isinstance(native, list) or len(native) != 4 or native[2] <= 0 or native[3] <= 0:
        return QCursor.pos()
    screens = QGuiApplication.screens()
    name = str(payload.get("screen_name", "")).casefold()
    screen = next((s for s in screens if name and s.name().casefold() == name), None)
    if screen is None:
        # XWayland and native Qt may give the same output different names.
        candidates = [s for s in screens if (s.geometry().x(), s.geometry().y()) == tuple(native[:2])]
        if len(candidates) == 1:
            screen = candidates[0]
        elif len(screens) == 1:
            screen = screens[0]
    if screen is None:
        # An output may have been disconnected while the menu was starting.
        return QCursor.pos()
    geometry = screen.geometry()
    # Transform offsets within the clicked output, preserving its Qt origin.
    # Dividing the whole desktop point by DPR moves mixed-DPI secondary screens.
    return QPoint(
        geometry.x() + round((x - native[0]) * geometry.width() / native[2]),
        geometry.y() + round((y - native[1]) * geometry.height() / native[3]),
    )


def _build_menu(payload: dict, actions: list[str], emit_action=_emit) -> RadialMenu:
    menu = RadialMenu()
    actions.clear()
    for item in _payload_items(payload):
        action = str(item.get("action", "") or "").strip()
        label = str(item.get("label", "") or "")
        glyph = str(item.get("glyph", "") or "")
        color = _item_color(item)
        enabled = bool(item.get("enabled", True))
        if not action or color is None:
            continue
        actions.append(action)
        index = len(actions) - 1
        menu.add_item(
            "",
            label,
            color,
            on_click=lambda idx=index: emit_action(actions[idx]),
            glyph=glyph,
            enabled=enabled,
        )
    menu.set_locked(bool(payload.get("locked", False)))
    menu.prepare_for_show()
    return menu


def _update_menu(menu: RadialMenu, payload: dict, actions: list[str]) -> bool:
    items = _payload_items(payload)
    if len(items) != len(actions):
        return False

    next_actions: list[str] = []
    for index, item in enumerate(items):
        action = str(item.get("action", "") or "").strip()
        color = _item_color(item)
        if not action or color is None:
            return False
        next_actions.append(action)
        menu.update_item(
            index,
            label=str(item.get("label", "") or ""),
            glyph=str(item.get("glyph", "") or ""),
            enabled=bool(item.get("enabled", True)),
            color=color,
        )

    actions[:] = next_actions
    menu.set_locked(bool(payload.get("locked", False)))
    menu.prepare_for_show()
    return True


def main():
    global _EVENT_QUEUE
    global _STDIO_MODE
    os.chdir(BASE_DIR)
    args = _parse_args()
    _STDIO_MODE = bool(args.stdio)

    channel_name = str(args.channel_name or "").strip()
    if not channel_name and not _STDIO_MODE:
        return 2

    set_windows_app_user_model_id(f"{APP_NAME}.RadialMenu")
    app = QApplication(sys.argv)
    from wayland.environment import verify_native_wayland_qpa

    verify_native_wayland_qpa(app)
    install_parent_death_watch(app)
    app.setApplicationName(f"{APP_NAME}-RadialMenu")
    app.setOrganizationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    import bandori_platform.macos_patch as macos_patch
    macos_patch.hide_dock_icon_if_needed()

    command_queue = None
    if not _STDIO_MODE:
        try:
            command_queue = SharedMemoryLineQueue.attach(
                radial_command_queue_key(channel_name),
                start_at_tail=False,
            )
            _EVENT_QUEUE = SharedMemoryLineQueue.attach(radial_event_queue_key(channel_name))
        except RuntimeError as exc:
            print(f"Radial menu shared-memory IPC attach failed: {exc}", file=sys.stderr)
            return 3

    menu = None
    menu_actions: list[str] = []

    from plugin_system.bridge import PluginComponentBridge
    from plugin_system.native import NativePluginLoader

    plugin_bridge = PluginComponentBridge("radial", app)
    plugin_bridge.connect()

    def dispatch_action(action: str):
        result = plugin_bridge.dispatch_event("radial.action.before", {"action": action})
        if result.get("cancelled"):
            return
        action = str(result.get("payload", {}).get("action", action) or action)
        if action.startswith("plugin:"):
            plugin_bridge.notify_event("radial.action", {"action": action})
        else:
            _emit(f"ACT\t{action}")

    def with_plugin_items(payload: dict) -> dict:
        result = dict(payload)
        items = list(_payload_items(payload))
        for contribution in plugin_bridge.contributions("ui", "radial_menu"):
            spec = contribution.get("spec", {})
            if not isinstance(spec, dict):
                continue
            color = spec.get("color", [91, 91, 116])
            items.append({
                "action": f"plugin:{contribution.get('plugin_id', '')}:{contribution.get('id', '')}",
                "label": str(spec.get("label", contribution.get("id", "")) or ""),
                "glyph": str(spec.get("glyph", "") or ""),
                "color": color if isinstance(color, list) else [91, 91, 116],
                "enabled": bool(spec.get("enabled", True)),
            })
        result["items"] = items
        return result

    def on_menu_closed():
        interaction_trace("radial_process", "menu_closed")
        _emit("STATE\tCLOSED")

    def on_lock_toggled(locked: bool):
        _emit(f"LOCK\t{1 if locked else 0}")

    def attach_menu(new_menu: RadialMenu):
        nonlocal menu
        if menu is not None:
            try:
                menu.closed.disconnect(on_menu_closed)
            except Exception:
                pass
            try:
                menu.lock_toggled.disconnect(on_lock_toggled)
            except Exception:
                pass
            menu.deleteLater()
        menu = new_menu
        menu.closed.connect(on_menu_closed)
        menu.lock_toggled.connect(on_lock_toggled)

    def show_payload(payload: dict):
        payload = with_plugin_items(payload)
        interaction_trace(
            "radial_process",
            "show_payload",
            x=payload.get("x"),
            y=payload.get("y"),
            existing=menu is not None,
        )
        if menu is None:
            attach_menu(_build_menu(payload, menu_actions, dispatch_action))
        elif not _update_menu(menu, payload, menu_actions):
            attach_menu(_build_menu(payload, menu_actions, dispatch_action))
        if menu is None:
            return
        if menu._is_showing:
            menu.dismiss()
        menu.show_at(_menu_position(payload))
        _emit("STATE\tOPEN")

    def close_menu():
        if menu is not None:
            menu.dismiss()

    def handle_line(line: str):
        interaction_trace(
            "radial_process",
            "command",
            command=line.split("\t", 1)[0],
        )
        if line.startswith("SHOW\t"):
            try:
                payload = json.loads(line.split("\t", 1)[1])
            except json.JSONDecodeError:
                return
            if isinstance(payload, dict):
                show_payload(payload)
        elif line == "CLOSE":
            close_menu()
        elif line == "EXIT":
            close_menu()
            app.quit()

    def read_commands():
        if command_queue is None:
            return False
        lines = command_queue.read_available(max_messages=100)
        for line in lines:
            handle_line(line)
        return bool(lines)

    def read_stdio_commands():
        had_activity = False
        while True:
            ready, _write, _error = select.select([sys.stdin], [], [], 0)
            if not ready:
                return had_activity
            line = sys.stdin.readline()
            if line == "":
                app.quit()
                return had_activity
            had_activity = True
            handle_line(line.rstrip("\r\n"))

    command_timer = QTimer(app)
    command_poll_state = AdaptivePollInterval(
        active_interval_ms=15,
        idle_interval_ms=75,
        empty_polls_before_idle=40,
    )
    command_reader = read_stdio_commands if _STDIO_MODE else read_commands

    def poll_commands():
        interval = command_poll_state.observe(command_reader())
        if command_timer.interval() != interval:
            command_timer.setInterval(interval)

    command_timer.setInterval(command_poll_state.active_interval_ms)
    command_timer.timeout.connect(poll_commands)
    command_timer.start()

    native_plugin_loader = NativePluginLoader(
        "radial",
        transport_factory=plugin_bridge.native_transport,
        application=app,
        controller=show_payload,
        objects={"show_payload": show_payload, "close_menu": close_menu, "attach_menu": attach_menu},
    )
    native_plugin_loader.load_all()
    if command_queue is not None:
        app.aboutToQuit.connect(command_queue.close)
    app.aboutToQuit.connect(lambda: _EVENT_QUEUE.close() if _EVENT_QUEUE is not None else None)
    app.aboutToQuit.connect(native_plugin_loader.close)
    app.aboutToQuit.connect(plugin_bridge.close)
    _emit("READY")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
