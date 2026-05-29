import os
import secrets
import shutil
import urllib.error
import urllib.parse

__all__ = []  # will be populated at end of file
import urllib.request
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import fluent_bootstrap

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation, QPoint, QEvent, QUrl, QRectF, QRect, QSize, QTime
from PySide6.QtGui import QColor, QPalette, QPixmap, QIcon, QCursor, QPainter, QPainterPath, QPen, QBrush, QIntValidator, QDoubleValidator, QDesktopServices, QFont, QTextCursor, QRegion, QKeyEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QSizePolicy, QScrollArea,
    QLineEdit, QGraphicsOpacityEffect, QGraphicsColorizeEffect, QApplication,
    QTextEdit, QPlainTextEdit, QToolButton, QFileDialog, QMessageBox,
    QCheckBox,
)
from shiboken6 import isValid

from qfluentwidgets import (
    CardWidget, PushButton, PrimaryPushButton, TransparentPushButton,
    BodyLabel, StrongBodyLabel, TitleLabel, SubtitleLabel,
    FluentIcon, Slider, SwitchButton, ScrollArea, ComboBox, LineEdit,
    TimeEdit, SpinBox,
    isDarkTheme, InfoBar, InfoBarPosition, ProgressBar,
)
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from qfluentwidgets.components.widgets.menu import (
    LineEditMenu,
    MenuAnimationManager,
    MenuAnimationType,
)
from qfluentwidgets.common.config import qconfig

from i18n_manager import tr as _tr, set_language, available_languages, current_language, normalize_language
from llm_api_compat import (
    chat_completions_api_url,
    is_google_generative_language_url,
    models_api_url,
    responses_api_url,
    sanitize_chat_body_for_url,
)
from process_utils import app_base_dir
from model_manager import MODELS_DIR, ModelManager
from app_info import APP_LICENSE_URL, APP_QQ_GROUP_URL, APP_REPO_URL, APP_VERSION
from app_update import detect_update_channel
from app_theme import (
    BANDORI_PRIMARY,
    BANDORI_PRIMARY_HOVER,
    BANDORI_PRIMARY_PRESSED,
    BANDORI_PRIMARY_DARK,
    BANDORI_PRIMARY_DARK_HOVER,
    BANDORI_PRIMARY_DARK_PRESSED,
    BANDORI_PRIMARY_SOFT,
    BANDORI_PRIMARY_SOFT_HOVER,
    BANDORI_PRIMARY_SOFT_DARK,
    BANDORI_PRIMARY_SOFT_DARK_HOVER,
    _THEME_ON,
    _THEME_OFF,
    _THEME_FOLLOW_SYSTEM,
    accent_color,
    apply_app_theme,
)
from database_manager import DatabaseManager
from config_manager import BUILTIN_LLM_API_PROFILES, DEFAULT_USER_PROFILE_KEY, make_user_profile_key
from relationship_memory import (
    MEMORY_KIND_LABELS,
    affection_label,
    display_user_name,
    mood_label,
    role_character_from_user_key,
    user_key_from_config,
)
from reminder_core import (
    ALARM_CONFIG_KEY,
    DISPLAY_MODE_FLOATING,
    DISPLAY_MODE_SYSTEM,
    POMODORO_CONFIG_KEY,
    REMINDER_DISPLAY_MODE_KEY,
    create_alarm,
    create_pomodoro,
    default_reminder_character,
    normalize_alarms,
    normalize_display_mode,
    normalize_pomodoros,
    parse_iso_datetime,
    pomodoro_phase_label,
    repeat_days_label,
)
from win32_dwm import apply_windows_11_border_fix, frame_changed

TTSPlayer = None
TTSRequestWorker = None
_SETTINGS_TTS_AVAILABLE = True
_SETTINGS_TTS_CHECKED = False


def _ensure_settings_tts_available() -> bool:
    global TTSPlayer, TTSRequestWorker, _SETTINGS_TTS_AVAILABLE, _SETTINGS_TTS_CHECKED
    if _SETTINGS_TTS_CHECKED:
        return _SETTINGS_TTS_AVAILABLE
    _SETTINGS_TTS_CHECKED = True
    try:
        from tts_manager import TTSPlayer as player_class, TTSRequestWorker as worker_class
    except (ImportError, OSError):
        _SETTINGS_TTS_AVAILABLE = False
        return False
    TTSPlayer = player_class
    TTSRequestWorker = worker_class
    _SETTINGS_TTS_AVAILABLE = True
    return True

import json

from startup_manager import (
    is_startup_enabled,
    is_supported as is_startup_supported,
    set_startup_enabled,
)
from live2d_click_actions import (
    CLICK_MOTION_AUTO,
    CLICK_MOTION_NONE,
    CLICK_MOTION_RANDOM,
    CLICK_MOTION_REGIONS,
    CLICK_MOTION_SPECIAL_VALUES,
    normalize_click_motion_actions,
)
from live2d_quality import LIVE2D_SCALE_MAX, LIVE2D_SCALE_MIN, clamp_live2d_scale, normalize_live2d_quality
from ui_helpers import AVATAR_EXTENSIONS, FluentContextTextEdit, rounded_avatar_pixmap

_BG_LIGHT = "#ffffff"
_BG_DARK = "#1e1e1e"
_AVATAR_EXTENSIONS = AVATAR_EXTENSIONS
MODEL_PACKAGE_BASE_URL = "https://modelscope.cn/datasets/HELPMEEADICE/BanG-Dream-Live2D/resolve/master/models"

_ROLEPLAY_STATUS_COLORS = {
    "green": "#2ecc71",
    "yellow": "#f1c40f",
    "red": "#e74c3c",
}

_ROLEPLAY_STATUS_TIPS = {
    "green": "SettingsWindow.roleplay_status_green",
    "yellow": "SettingsWindow.roleplay_status_yellow",
    "red": "SettingsWindow.roleplay_status_red",
}

DATA_PACKAGE_FORMAT = "bandori_pet_settings_bundle"
DATA_PACKAGE_VERSION = 1

DATA_CATEGORY_ALL = "all"
DATA_CATEGORY_LIVE2D = "live2d_models"
DATA_CATEGORY_LLM = "llm"
DATA_CATEGORY_TTS = "tts"
DATA_CATEGORY_POV = "pov"
DATA_CATEGORY_RELATIONSHIP = "relationship"
DATA_CATEGORY_REMINDERS = "reminders"
DATA_CATEGORY_COMPACT = "compact_window"
DATA_CATEGORY_CHAT = "chat_integration"
DATA_CATEGORY_MCP = "mcp_computer"
DATA_CATEGORY_MISC = "misc"
DATA_CATEGORY_CLICK_PROFILES = "click_motion_profiles"

BUILTIN_LLM_API_PROFILE_NAMES = {
    str(profile.get("name", "")).strip()
    for profile in BUILTIN_LLM_API_PROFILES
}

SECRET_CONFIG_KEYS = {
    "llm_api_key",
    "llm_aux_api_key",
}

DATA_CONFIG_KEYS = {
    DATA_CATEGORY_LIVE2D: (
        "character",
        "costume",
        "models",
        "model_action_settings",
        "live2d_idle_actions_enabled",
        "live2d_head_tracking_enabled",
        "live2d_mutual_gaze_enabled",
    ),
    DATA_CATEGORY_LLM: (
        "llm_api_url",
        "llm_model_id",
        "llm_aux_api_url",
        "llm_aux_model_id",
        "llm_aux_enable_thinking",
        "llm_aux_vision_fallback_enabled",
        "llm_api_mode",
        "llm_web_search_enabled",
        "llm_web_search_engine",
        "llm_web_search_show_sources",
        "llm_custom_system_prompt_enabled",
        "llm_custom_system_prompt",
        "llm_api_profiles",
        "llm_active_api_profile",
        "user_name",
        "user_avatar_color",
        "user_avatar_path",
        "user_profiles",
        "active_user_profile",
        "chat_avatar_paths",
        "group_chat_sidebar_ratio",
        "group_chat_sidebar_collapsed",
        "chat_window_always_on_top",
        "llm_enable_thinking",
        "llm_show_reasoning",
    ),
    DATA_CATEGORY_TTS: (
        "tts_enabled",
        "tts_api_url",
        "tts_language",
        "tts_reference_character",
        "tts_streaming",
        "tts_temperature",
        "tts_translate_to_selected_language",
    ),
    DATA_CATEGORY_POV: (
        "pov_mode",
        "pov_custom_prompt",
        "pov_custom_personas",
        "pov_role_character",
        "user_profiles",
        "active_user_profile",
    ),
    DATA_CATEGORY_REMINDERS: (
        "alarms",
        "pomodoros",
        "reminder_display_mode",
    ),
    DATA_CATEGORY_COMPACT: (
        "compact_ai_window_enabled",
        "compact_ai_window_background_color",
        "compact_ai_window_text_color",
        "compact_ai_window_opacity",
        "compact_ai_window_font_size",
        "ai_event_overlay_enabled",
        "ai_status_port_enabled",
        "ai_status_port",
        "ai_status_token",
    ),
    DATA_CATEGORY_CHAT: (
        "chat_integration_enabled",
        "chat_integration_overlay_enabled",
        "chat_integration_include_context",
        "chat_integration_port",
        "chat_integration_token",
        "napcat_enabled",
        "napcat_ws_url",
        "napcat_access_token",
        "napcat_auto_reply_enabled",
        "napcat_reply_private",
        "napcat_reply_group_at_only",
        "napcat_reply_character",
    ),
    DATA_CATEGORY_MCP: (
        "llm_hide_tool_call_details",
        "llm_mcp_enabled",
        "llm_mcp_use_native",
        "llm_mcp_servers",
        "computer_use_enabled",
        "computer_use_auto_detect",
        "computer_use_send_screenshots",
        "computer_use_max_screenshot_width",
        "computer_use_allow_screenshot",
        "computer_use_allow_mouse",
        "computer_use_allow_keyboard",
        "computer_use_allow_clipboard",
        "computer_use_allow_wait",
    ),
    DATA_CATEGORY_MISC: (
        "language",
        "fps",
        "opacity",
        "dark_theme",
        "vsync",
        "game_topmost",
        "chat_window_normal_window",
        "hide_live2d_model",
        "auto_start",
        "drag_locked",
        "live2d_quality",
        "live2d_scale",
        "fluent_chat_window_enabled",
        "chat_display_names",
        "pinned_chat_keys",
        "live2d_hit_alpha_threshold",
        "live2d_lip_sync_max_open",
        "window_x",
        "window_y",
        "window_width",
        "window_height",
        "pixel_window_x",
        "pixel_window_y",
        "pet_mode",
    ),
    DATA_CATEGORY_CLICK_PROFILES: (
        "click_motion_profiles",
    ),
}

DATA_EXPORT_ORDER = (
    DATA_CATEGORY_LIVE2D,
    DATA_CATEGORY_CLICK_PROFILES,
    DATA_CATEGORY_LLM,
    DATA_CATEGORY_TTS,
    DATA_CATEGORY_POV,
    DATA_CATEGORY_RELATIONSHIP,
    DATA_CATEGORY_REMINDERS,
    DATA_CATEGORY_COMPACT,
    DATA_CATEGORY_CHAT,
    DATA_CATEGORY_MCP,
    DATA_CATEGORY_MISC,
)

PROJECT_REPO_URL = APP_REPO_URL
PROJECT_LICENSE_URL = APP_LICENSE_URL
PROJECT_QQ_GROUP_URL = APP_QQ_GROUP_URL
CLICK_MOTION_CONFIG_FORMAT = "bandori-click-motion-actions"
CLICK_MOTION_CONFIG_VERSION = 1
CLICK_MOTION_SCOPE_ALL = "all_models"
CLICK_MOTION_SCOPE_CHARACTER = "current_character"
CLICK_MOTION_SCOPE_COSTUME = "current_costume"
CLICK_MOTION_SCOPES = {
    CLICK_MOTION_SCOPE_ALL,
    CLICK_MOTION_SCOPE_CHARACTER,
    CLICK_MOTION_SCOPE_COSTUME,
}
MEMORY_KIND_ORDER = ("profile", "preference", "relationship", "manual", "note")
MODEL_PICKER_STATE_KEY = "model_picker_state"
MODEL_PICKER_RECENT_LIMIT = 8
MODEL_PICKER_FILTER_ALL = "all"
MODEL_PICKER_FILTER_RECENT = "recent"
MODEL_PICKER_FILTER_FAVORITES = "favorites"


def _app_icon_path() -> str:
    base = app_base_dir()
    for name in ("icon.ico", "logo.ico"):
        path = os.path.join(base, name)
        if os.path.exists(path):
            return path
    return ""


def _rounded_avatar_pixmap(path: str, size: int) -> QPixmap:
    return rounded_avatar_pixmap(path, size)


def _wrap_label(label: QLabel):
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return label


# Populate __all__ with all public and underscored names that should be exported
__all__ = [name for name in dir() if not name.startswith('__')]
