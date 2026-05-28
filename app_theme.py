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


def _default_ui_font_family() -> str:
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform.startswith("linux"):
        return "Noto Sans CJK SC"
    return "Microsoft YaHei UI"


BANDORI_UI_FONT_FAMILY = _default_ui_font_family()


def accent_color(dark: bool = False) -> str:
    return BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY


def apply_app_theme(dark: bool):
    qfluent = import_qfluentwidgets(lambda: __import__(
        "qfluentwidgets", fromlist=["Theme", "setTheme", "setThemeColor"]
    ))
    assert_pyside6_fluent_widgets()
    qfluent.setTheme(qfluent.Theme.DARK if dark else qfluent.Theme.LIGHT)
    qfluent.setThemeColor(accent_color(dark))
