import argparse
import json
import os
import sys

from process_utils import app_base_dir, configure_debug_logging, ensure_xwayland, set_windows_app_user_model_id

configure_debug_logging()

BASE_DIR = str(app_base_dir())

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QColor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from radial_menu import RadialMenu


def _parse_args():
    parser = argparse.ArgumentParser(description="Show radial menu in a separate process.")
    parser.add_argument("--server-name", required=True)
    return parser.parse_args()


def _emit(line: str):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _payload_items(payload: dict) -> list[dict]:
    items = payload.get("items")
    return items if isinstance(items, list) else []


def _item_color(item: dict) -> QColor | None:
    color_values = item.get("color") or [80, 80, 80]
    if len(color_values) != 3:
        return None
    return QColor(int(color_values[0]), int(color_values[1]), int(color_values[2]))


def _build_menu(payload: dict, actions: list[str]) -> RadialMenu:
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
            on_click=lambda idx=index: _emit(f"ACT\t{actions[idx]}"),
            glyph=glyph,
            enabled=enabled,
        )
    menu.set_animation_fps(int(payload.get("fps", 120)))
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
    menu.set_animation_fps(int(payload.get("fps", 120)))
    menu.set_locked(bool(payload.get("locked", False)))
    menu.prepare_for_show()
    return True


def main():
    ensure_xwayland()
    os.chdir(BASE_DIR)
    args = _parse_args()

    server_name = str(args.server_name or "").strip()
    if not server_name:
        return 2

    set_windows_app_user_model_id("BandoriPet.RadialMenu")
    app = QApplication(sys.argv)
    install_parent_death_watch(app)
    app.setApplicationName("BandoriPet-RadialMenu")
    app.setOrganizationName("BandoriPet")
    app.setQuitOnLastWindowClosed(False)

    if sys.platform == "darwin":
        import macos_patch

        macos_patch.hide_dock_icon()

    idle_timer = QTimer(app)
    idle_timer.setSingleShot(True)
    idle_timer.setInterval(12000)
    idle_timer.timeout.connect(app.quit)
    idle_timer.start()

    QLocalServer.removeServer(server_name)
    server = QLocalServer(app)
    if not server.listen(server_name):
        return 3

    menu = None
    menu_actions: list[str] = []
    clients: list[QLocalSocket] = []
    buffers: dict[QLocalSocket, str] = {}

    def on_menu_closed():
        _emit("STATE\tCLOSED")
        idle_timer.start()

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
        nonlocal menu
        idle_timer.stop()
        if menu is None:
            attach_menu(_build_menu(payload, menu_actions))
        elif not _update_menu(menu, payload, menu_actions):
            attach_menu(_build_menu(payload, menu_actions))
        if menu is None:
            return
        if menu._is_showing:
            menu.dismiss()
        menu.show_at(QPoint(int(payload.get("x", 0)), int(payload.get("y", 0))))
        _emit("STATE\tOPEN")

    def close_menu():
        if menu is not None:
            menu.dismiss()
        else:
            idle_timer.start()

    def handle_line(line: str):
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

    def remove_client(socket: QLocalSocket):
        if socket in clients:
            clients.remove(socket)
        buffers.pop(socket, None)
        if isValid(socket):
            socket.deleteLater()

    def read_client(socket: QLocalSocket):
        if not isValid(socket):
            return
        data = bytes(socket.readAll()).decode("utf-8", errors="replace")
        buffer = buffers.get(socket, "") + data
        lines = buffer.splitlines(keepends=True)
        if lines and not lines[-1].endswith(("\n", "\r")):
            buffers[socket] = lines.pop()
        else:
            buffers[socket] = ""
        for raw_line in lines:
            handle_line(raw_line.rstrip("\r\n"))

    def accept_clients():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            clients.append(socket)
            buffers[socket] = ""
            socket.readyRead.connect(lambda s=socket: read_client(s))
            socket.disconnected.connect(lambda s=socket: remove_client(s))

    server.newConnection.connect(accept_clients)
    _emit("READY")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
