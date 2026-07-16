import logging
import subprocess
import sys

from fluent_bootstrap import assert_pyside6_fluent_widgets
from fluent_silencer import import_qfluentwidgets


BANDORI_PRIMARY = "#e4004f"
BANDORI_PRIMARY_HOVER = "#f02466"
BANDORI_PRIMARY_PRESSED = "#b8003f"
BANDORI_PRIMARY_DARK = "#ff5f8f"
BANDORI_PRIMARY_DARK_HOVER = "#ff7aa3"
BANDORI_PRIMARY_DARK_PRESSED = "#d93c70"
BANDORI_PRIMARY_SOFT = "#fff0f5"
BANDORI_PRIMARY_SOFT_HOVER = "#ffe2ec"
BANDORI_PRIMARY_SOFT_DARK = "#3a1826"
BANDORI_PRIMARY_SOFT_DARK_HOVER = "#4a1d2f"

_THEME_FOLLOW_SYSTEM = "follow_system"
_THEME_ON = "on"
_THEME_OFF = "off"


def _detect_system_dark() -> bool:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0
        except OSError as exc:
            logging.debug("app_theme: registry read failed: %s", exc)
            return False
    elif sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.strip().lower() == "dark"
        except (subprocess.SubprocessError, OSError) as exc:
            logging.debug("app_theme: macOS detection failed: %s", exc)
            return False
    elif sys.platform.startswith("linux"):
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True, text=True, timeout=5
            )
            if "prefer-dark" in result.stdout.strip().lower():
                return True
        except (subprocess.SubprocessError, OSError) as exc:
            logging.debug("app_theme: gsettings color-scheme failed: %s", exc)
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
                capture_output=True, text=True, timeout=5
            )
            if "dark" in result.stdout.strip().lower():
                return True
        except (subprocess.SubprocessError, OSError) as exc:
            logging.debug("app_theme: gsettings gtk-theme failed: %s", exc)
        return False
    return False


def resolve_theme_dark(theme_value) -> bool:
    if isinstance(theme_value, bool):
        return theme_value
    if theme_value == _THEME_ON:
        return True
    if theme_value == _THEME_OFF:
        return False
    if theme_value == _THEME_FOLLOW_SYSTEM:
        return _detect_system_dark()
    return False


def _default_ui_font_family() -> str:
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform.startswith("linux"):
        return "Noto Sans CJK SC"
    return "Microsoft YaHei UI"


BANDORI_UI_FONT_FAMILY = _default_ui_font_family()


def platform_ui_font_families() -> list[str]:
    if sys.platform == "darwin":
        return ["PingFang SC", "Helvetica Neue", "Arial Unicode MS"]
    if sys.platform.startswith("linux"):
        return ["Noto Sans CJK SC", "Noto Sans", "DejaVu Sans"]
    return ["Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei"]


def apply_application_font(app) -> None:
    if app is None:
        return
    try:
        from PySide6.QtGui import QFont

        font = QFont()
        font.setFamilies(platform_ui_font_families())
        app.setFont(font)
    except Exception:
        pass


def accent_color(dark: bool = False) -> str:
    return BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY


def apply_app_theme(theme_value, *, include_fluent: bool = True):
    """Apply the shared Qt font and, when needed, the Fluent widget theme.

    The tray controller and Live2D pet use custom Qt widgets only. Importing
    the complete Fluent widget package in those processes keeps a sizeable UI
    module graph resident for no visual benefit, so callers can explicitly
    skip that part while still receiving the application font.
    """
    dark = resolve_theme_dark(theme_value)
    try:
        from PySide6.QtWidgets import QApplication

        apply_application_font(QApplication.instance())
    except Exception:
        pass
    if not include_fluent:
        return

    qfluent = import_qfluentwidgets(lambda: __import__(
        "qfluentwidgets", fromlist=["Theme", "setTheme", "setThemeColor"]
    ))
    assert_pyside6_fluent_widgets()
    if hasattr(qfluent, "setFontFamilies"):
        qfluent.setFontFamilies(platform_ui_font_families(), save=False)
    qfluent.setTheme(qfluent.Theme.DARK if dark else qfluent.Theme.LIGHT)
    qfluent.setThemeColor(accent_color(dark))
