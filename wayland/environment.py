from __future__ import annotations

import os
import sys


class WaylandStartupError(RuntimeError):
    """Raised when a Wayland session would silently fall back to XWayland."""


def is_wayland_session(env: dict[str, str] | None = None, platform: str | None = None) -> bool:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if not str(platform).startswith("linux"):
        return False
    return (
        str(env.get("XDG_SESSION_TYPE", "")).strip().lower() == "wayland"
        or bool(str(env.get("WAYLAND_DISPLAY", "")).strip())
    )


def configure_native_wayland(
    env: dict[str, str] | None = None,
    platform: str | None = None,
) -> bool:
    """Select Qt's native Wayland QPA before PySide6 is imported.

    A caller-supplied ``xcb`` is treated as an error rather than overwritten.
    That makes accidental XWayland use visible and testable.
    """

    env = os.environ if env is None else env
    if not is_wayland_session(env, platform):
        return False
    requested = str(env.get("QT_QPA_PLATFORM", "")).strip().lower()
    if requested:
        platform_chain = [
            item.strip().split(":", 1)[0]
            for item in requested.split(";")
            if item.strip()
        ]
        if "xcb" in platform_chain:
            raise WaylandStartupError(
                "BandoriPet detected a Wayland session but QT_QPA_PLATFORM=xcb. "
                "Unset QT_QPA_PLATFORM to run natively; XWayland fallback is disabled."
            )
        if not platform_chain or any(
            not platform.startswith("wayland")
            for platform in platform_chain
        ):
            raise WaylandStartupError(
                "BandoriPet requires the Qt Wayland platform plugin in a Wayland "
                f"session, but QT_QPA_PLATFORM={requested!r} was requested."
            )
    else:
        env["QT_QPA_PLATFORM"] = "wayland"
    env.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    env.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    return True


def verify_native_wayland_qpa(application=None) -> bool:
    """Fail closed if Qt did not actually start on its Wayland backend."""

    if not is_wayland_session():
        return False
    if application is None:
        from PySide6.QtGui import QGuiApplication

        application = QGuiApplication.instance()
    if application is None:
        raise WaylandStartupError("QGuiApplication has not been created yet.")
    platform_name = str(application.platformName() or "").strip().lower()
    if not platform_name.startswith("wayland"):
        raise WaylandStartupError(
            "BandoriPet is running in a Wayland session but Qt selected "
            f"{platform_name or 'an unknown platform'!r}. Install Qt6 Wayland; "
            "XWayland fallback is disabled."
        )
    return True


def detect_compositor(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    if str(env.get("HYPRLAND_INSTANCE_SIGNATURE", "")).strip():
        return "hyprland"
    desktop = ":".join(
        (
            str(env.get("XDG_CURRENT_DESKTOP", "")),
            str(env.get("XDG_SESSION_DESKTOP", "")),
            str(env.get("DESKTOP_SESSION", "")),
        )
    ).lower()
    if "gnome" in desktop or str(env.get("GNOME_SHELL_SESSION_MODE", "")).strip():
        return "gnome"
    if (
        "kde" in desktop
        or "plasma" in desktop
        or str(env.get("KDE_FULL_SESSION", "")).strip().lower() == "true"
    ):
        return "plasma"
    return "generic"
