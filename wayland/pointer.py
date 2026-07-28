from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .types import PointerSample


def hyprland_socket_path(env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    signature = str(env.get("HYPRLAND_INSTANCE_SIGNATURE", "")).strip()
    runtime = str(env.get("XDG_RUNTIME_DIR", "")).strip()
    if not signature or not runtime:
        return None
    modern = Path(runtime) / "hypr" / signature / ".socket.sock"
    legacy = Path("/tmp/hypr") / signature / ".socket.sock"
    return modern if modern.exists() or not legacy.exists() else legacy


def query_hyprland_cursor(path: Path, timeout: float = 0.025) -> tuple[float, float]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(b"j/cursorpos")
        chunks = []
        while True:
            part = client.recv(4096)
            if not part:
                break
            chunks.append(part)
    payload = b"".join(chunks).decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(payload)
        return float(data["x"]), float(data["y"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        left, right = payload.replace(" ", "").split(",", 1)
        return float(left), float(right)


class HyprlandPointerThread(QThread):
    sample = Signal(object)
    status_changed = Signal(bool, str)

    def __init__(self, parent=None, *, hz: int = 60):
        super().__init__(parent)
        self._active = False
        self._stop_requested = False
        self._period = 1.0 / max(1, min(int(hz), 60))

    def set_active(self, active: bool):
        self._active = bool(active)

    def stop(self):
        self._stop_requested = True
        self.wait(250)

    def run(self):
        path = hyprland_socket_path()
        last_error = ""
        status_ok = False
        while not self._stop_requested:
            if not self._active:
                self.msleep(50)
                continue
            started = time.monotonic()
            try:
                if path is None:
                    raise FileNotFoundError("Hyprland command socket was not found")
                x, y = query_hyprland_cursor(path)
                if not status_ok:
                    status_ok = True
                    last_error = ""
                    self.status_changed.emit(True, "")
                self.sample.emit(
                    PointerSample(
                        x,
                        y,
                        0,
                        time.monotonic_ns() // 1000,
                        "hyprland",
                    )
                )
            except Exception as exc:
                message = str(exc)
                if status_ok or message != last_error:
                    status_ok = False
                    last_error = message
                    self.status_changed.emit(False, message)
                self.msleep(250)
                continue
            remaining = self._period - (time.monotonic() - started)
            if remaining > 0:
                self.usleep(int(remaining * 1_000_000))
