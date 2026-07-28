from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from process_utils import app_base_dir
from .environment import detect_compositor, is_wayland_session


GNOME_UUID = "bandoripet-wayland@bandoripet"
KWIN_ID = "bandoripet-wayland"


def _source_root() -> Path:
    return Path(app_base_dir()) / "installer" / "linux" / "wayland"


def companion_status(env: dict[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    compositor = detect_compositor(env)
    home = Path.home()
    gnome_path = home / ".local" / "share" / "gnome-shell" / "extensions" / GNOME_UUID
    kwin_path = home / ".local" / "share" / "kwin" / "scripts" / KWIN_ID
    bridge_files = list((Path(app_base_dir()) / "wayland" / "_native").glob("_layer_shell*.so"))
    return {
        "wayland_session": is_wayland_session(env),
        "compositor": compositor,
        "gnome_installed": (gnome_path / "extension.js").is_file(),
        "kwin_installed": (kwin_path / "contents" / "code" / "main.js").is_file(),
        "native_bridge_built": bool(bridge_files),
        "hyprland_permission": (
            "ask"
            if compositor == "hyprland"
            else "not-applicable"
        ),
    }


def _run_optional(command: list[str]) -> tuple[bool, str]:
    executable = shutil.which(command[0])
    if not executable:
        return False, f"{command[0]} was not found"
    result = subprocess.run(
        [executable, *command[1:]],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    detail = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0, detail


def install_companion(compositor: str | None = None) -> tuple[bool, str]:
    if not sys.platform.startswith("linux"):
        return False, "Wayland companions can only be installed on Linux"
    compositor = compositor or detect_compositor()
    source = _source_root()
    if compositor == "gnome":
        source_dir = source / "gnome" / GNOME_UUID
        target = Path.home() / ".local" / "share" / "gnome-shell" / "extensions" / GNOME_UUID
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, target, dirs_exist_ok=True)
        enabled, detail = _run_optional(["gnome-extensions", "enable", GNOME_UUID])
        if not enabled:
            return True, (
                f"Installed to {target}. Enable it in Extensions and restart "
                f"GNOME Shell if required. {detail}"
            )
        return True, f"Installed and enabled {GNOME_UUID}"
    if compositor == "plasma":
        source_dir = source / "kwin"
        removed, _detail = _run_optional(
            ["kpackagetool6", "--type", "KWin/Script", "--remove", KWIN_ID]
        )
        del removed
        installed, detail = _run_optional(
            ["kpackagetool6", "--type", "KWin/Script", "--install", str(source_dir)]
        )
        if not installed:
            return False, detail or "kpackagetool6 could not install the KWin script"
        _run_optional(
            [
                "kwriteconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Plugins",
                "--key",
                f"{KWIN_ID}Enabled",
                "true",
            ]
        )
        _run_optional(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])
        return True, f"Installed and enabled KWin script {KWIN_ID}"
    if compositor == "hyprland":
        return True, (
            "No companion files are required. Hyprland will ask for cursorpos "
            "permission when head tracking starts."
        )
    return False, f"No full companion is available for compositor {compositor!r}"


def remove_companion(compositor: str | None = None) -> tuple[bool, str]:
    if not sys.platform.startswith("linux"):
        return False, "Wayland companions can only be removed on Linux"
    compositor = compositor or detect_compositor()
    if compositor == "gnome":
        _run_optional(["gnome-extensions", "disable", GNOME_UUID])
        target = Path.home() / ".local" / "share" / "gnome-shell" / "extensions" / GNOME_UUID
        if target.is_dir():
            shutil.rmtree(target)
        return True, f"Removed {GNOME_UUID}"
    if compositor == "plasma":
        _run_optional(
            [
                "kwriteconfig6",
                "--file",
                "kwinrc",
                "--group",
                "Plugins",
                "--key",
                f"{KWIN_ID}Enabled",
                "false",
            ]
        )
        removed, detail = _run_optional(
            ["kpackagetool6", "--type", "KWin/Script", "--remove", KWIN_ID]
        )
        _run_optional(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"])
        return removed, detail or f"Removed KWin script {KWIN_ID}"
    if compositor == "hyprland":
        return True, "Remove any saved cursorpos permission from hyprland.conf."
    return False, f"No companion is installed for compositor {compositor!r}"
