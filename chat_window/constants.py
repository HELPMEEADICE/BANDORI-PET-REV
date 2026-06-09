from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import QMenu

from app_theme import BANDORI_PRIMARY, BANDORI_PRIMARY_SOFT, BANDORI_PRIMARY_SOFT_DARK
from win32_dwm import apply_windows_11_border_fix, frame_changed


_BG_LIGHT = "#f5f7fb"
_BG_DARK = "#0f1117"

_USER_BUBBLE_LIGHT = BANDORI_PRIMARY_SOFT
_USER_BUBBLE_DARK = BANDORI_PRIMARY_SOFT_DARK
_ASSIST_BUBBLE_LIGHT = "#ffffff"
_ASSIST_BUBBLE_DARK = "#1b1f29"
_TEAMS_ACCENT = "#6264a7"
_TELEGRAM_ACCENT = BANDORI_PRIMARY
_CHAT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_AVATAR_PIXMAP_CACHE = {}
_AVATAR_PIXMAP_CACHE_LIMIT = 96
_HISTORY_ROW_WIDTH = 368
_HISTORY_ROW_HEIGHT = 48
_HISTORY_SCROLL_WIDTH = _HISTORY_ROW_WIDTH + 24
_MESSAGE_HISTORY_PAGE_SIZE = 30
_GROUP_SIDEBAR_DEFAULT_RATIO = 0.28
_GROUP_SIDEBAR_MIN_RATIO = 0.18
_GROUP_SIDEBAR_MAX_RATIO = 0.46
_GROUP_SIDEBAR_ANIMATION_MS = 180


def _enable_translucent_menu(menu: QMenu):
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    menu.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    menu.setAutoFillBackground(False)
    menu.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)


def _apply_rounded_menu_mask(menu: QMenu, radius: float):
    width = menu.width()
    height = menu.height()
    if width <= 0 or height <= 0:
        return
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    menu.setMask(QRegion(path.toFillPolygon().toPolygon()))


def _apply_windows_menu_border_fix(menu: QMenu):
    hwnd = int(menu.winId())
    if not hwnd:
        return
    apply_windows_11_border_fix(hwnd)
    frame_changed(hwnd)


def _prepare_rounded_menu(menu: QMenu, radius: float = 12):
    _enable_translucent_menu(menu)
    menu.setProperty("rounded_menu_radius", float(radius))
    if menu.property("rounded_menu_prepared"):
        return
    menu.setProperty("rounded_menu_prepared", True)

    def _refresh_mask():
        _apply_rounded_menu_mask(menu, float(menu.property("rounded_menu_radius") or radius))
        _apply_windows_menu_border_fix(menu)

    menu.aboutToShow.connect(lambda: QTimer.singleShot(0, _refresh_mask))


def _prepare_fluent_round_menu(menu: QMenu, radius: float = 10):
    _prepare_rounded_menu(menu, radius)
    view = getattr(menu, "view", None)
    if view is not None:
        view.setGraphicsEffect(None)
    layout = getattr(menu, "hBoxLayout", None)
    if layout is not None:
        layout.setContentsMargins(0, 0, 0, 0)
    try:
        menu.adjustSize()
    except Exception:
        pass
    _apply_rounded_menu_mask(menu, float(menu.property("rounded_menu_radius") or radius))
    _apply_windows_menu_border_fix(menu)
