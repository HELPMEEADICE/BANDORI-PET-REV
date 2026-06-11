import fluent_bootstrap

fluent_bootstrap.prefer_local_pyside6_fluent_widgets()

import logging
import time

from PySide6.QtCore import Qt, QObject, QThread, Signal, QTimer, QPropertyAnimation, QEasingCurve, QEvent, QRect, QSize, QVariantAnimation, QParallelAnimationGroup
from PySide6.QtGui import QFont, QColor, QPalette, QIcon, QKeyEvent, QPainter, QPainterPath, QPen, QPixmap, QImage, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QToolButton, QMenu,
    QApplication, QWidgetAction,
    QFrame, QFileDialog, QMessageBox,
)

from i18n_manager import tr as _tr
from qfluentwidgets import Action, BodyLabel, StrongBodyLabel, FluentIcon, ProgressBar, TransparentToolButton, isDarkTheme
from qfluentwidgets.common.config import qconfig
from process_utils import app_base_dir
from app_theme import (
    BANDORI_PRIMARY_SOFT,
    BANDORI_PRIMARY_SOFT_DARK_HOVER,
    accent_color,
)
from ui_helpers import AVATAR_EXTENSIONS, FluentContextTextEdit, INTERRUPT_COMMANDS, CommandCompleter
from win32_dwm import apply_windows_11_border_fix

import base64
import mimetypes
import os
import shutil
import sys
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
import json
import re
from pathlib import Path

if sys.platform == "darwin":
    import macos_patch
else:
    macos_patch = None

from llm_manager import (
    build_system_prompt, current_time_instruction, LLMStreamWorker, ResponsesStreamWorker, NonStreamWorker,
    consume_stream_action_tags, merged_action_tags, parse_action_tags, strip_action_tags, extract_inline_search_sources,
    estimate_llm_request_tokens,
)
from emotion_behavior import emotion_tts_rate, infer_emotion_behavior
from llm_api_compat import chat_completions_api_url, use_responses_api
from llm_error_hints import format_llm_error_message
from chat_config_snapshots import (
    asr_config_snapshot,
    memory_extraction_api_config,
    tool_config_snapshot,
    tts_config_snapshot,
)
from local_tools import reminder_tools_enabled
from chat_commands import handle_command as _handle_chat_command
from token_usage import estimate_messages_tokens, estimate_untracked_history_usage
from tts_common import clean_tts_payload
from tts_manager import TTSPlayer, TTSRequestWorker, TTSTranslationWorker, flush_tts_sentence, is_tts_enabled
from .chat_window_base import ChatWindowMixin
_TTS_AVAILABLE = True

try:
    from asr_manager import ASRRecorderWorker, ASRRequestWorker
    _ASR_AVAILABLE = True
except (ImportError, OSError):
    _ASR_AVAILABLE = False
    ASRRecorderWorker = None
    ASRRequestWorker = None

from relationship_memory import (
    GLOBAL_MEMORY_CHARACTER,
    analyze_interaction,
    build_memory_extraction_messages,
    build_relationship_context,
    format_character_status,
    parse_relationship_analysis_response,
    store_extracted_memories,
)
from action_bus import publish_action, publish_emotion_behavior, publish_lip_sync, publish_user_poke

from .constants import (
    _BG_LIGHT, _BG_DARK,
    _TEAMS_ACCENT, _TELEGRAM_ACCENT,
    _CHAT_IMAGE_EXTENSIONS,
    _HISTORY_ROW_WIDTH, _HISTORY_ROW_HEIGHT, _HISTORY_SCROLL_WIDTH,
    _MESSAGE_HISTORY_PAGE_SIZE,
    _GROUP_SIDEBAR_DEFAULT_RATIO, _GROUP_SIDEBAR_MIN_RATIO,
    _GROUP_SIDEBAR_MAX_RATIO, _GROUP_SIDEBAR_ANIMATION_MS,
    _prepare_rounded_menu,
)
from .avatar_utils import _rounded_avatar_pixmap
from .widgets import (
    AuxVisionFallbackWorker, GroupRenameDialog,
    RoundedPanel, IconButton, ChatSendButton,
    FluentSplitter, ChatResizeGrip,
    ConversationHistoryRow, GroupChatListRow,
    ChatCharacterPickerPanel,
    PlanDivider,
    ComposerAttachmentCard,
)
from .message_bubble import MessageBubble

_CHAT_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
_REMOTE_IMAGE_MAX_BYTES = 16 * 1024 * 1024
_FILE_ATTACHMENT_INLINE_BYTES = 256 * 1024
_FILE_ATTACHMENT_INLINE_CHARS = 120_000
_CHAT_TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".xml", ".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".java",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
    ".kt", ".kts", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".sql", ".ini",
    ".cfg", ".conf", ".toml", ".log", ".po", ".pot", ".properties",
}
_CHAT_TEXT_ATTACHMENT_MIME_PREFIXES = ("text/",)
_CHAT_TEXT_ATTACHMENT_MIME_TYPES = {
    "application/json", "application/xml", "application/yaml", "application/x-yaml",
    "application/javascript", "application/x-javascript", "application/sql",
}


class ChatComposerTextEdit(FluentContextTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._chat_mime_can_handle = None
        self._chat_mime_insert_handler = None

    def set_chat_mime_handlers(self, can_handle, insert_handler):
        self._chat_mime_can_handle = can_handle
        self._chat_mime_insert_handler = insert_handler

    def _can_handle_chat_mime(self, source) -> bool:
        return bool(callable(self._chat_mime_can_handle) and self._chat_mime_can_handle(source))

    def canInsertFromMimeData(self, source):
        if self._can_handle_chat_mime(source):
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if self._can_handle_chat_mime(source):
            if callable(self._chat_mime_insert_handler):
                self._chat_mime_insert_handler(source)
                return
        super().insertFromMimeData(source)


class AttachmentImportWorker(QThread):
    progress = Signal(int, int, int, str)
    item_ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, jobs: list[dict], target_dir: Path, parent=None):
        super().__init__(parent)
        self._jobs = [dict(job) for job in jobs]
        self._target_dir = Path(target_dir)

    def run(self):
        job_count = len(self._jobs)
        for index, job in enumerate(self._jobs):
            if self.isInterruptionRequested():
                return
            try:
                if job.get("kind") == "remote":
                    item = self._import_remote(job, index, job_count)
                else:
                    item = self._import_local(job, index, job_count)
                if item and not self.isInterruptionRequested():
                    self.item_ready.emit(item)
                    self.progress.emit(
                        int((index + 1) * 100 / max(1, job_count)),
                        int(item.get("size", 0) or 0),
                        int(item.get("size", 0) or 0),
                        str(item.get("name", "") or ""),
                    )
            except Exception as exc:
                self.failed.emit(str(exc))

    def _emit_progress(self, index: int, job_count: int, copied: int, total: int, name: str):
        if total > 0:
            item_fraction = min(1.0, copied / total)
            percent = int(((index + item_fraction) / max(1, job_count)) * 100)
        else:
            percent = -1
        self.progress.emit(percent, copied, total, name)

    def _import_local(self, job: dict, index: int, job_count: int) -> dict | None:
        source = Path(str(job.get("path", "") or ""))
        size = int(job.get("size", 0) or 0)
        suffix = source.suffix.lower()
        target = self._target_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}{suffix}"
        copied = 0
        success = False
        try:
            with source.open("rb") as src, target.open("wb") as dst:
                while True:
                    if self.isInterruptionRequested():
                        return None
                    chunk = src.read(256 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    copied += len(chunk)
                    self._emit_progress(index, job_count, copied, size, source.name)
            try:
                shutil.copystat(source, target)
            except OSError:
                pass
            success = True
        finally:
            if not success and target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
        is_image = suffix in _CHAT_IMAGE_EXTENSIONS
        mime = mimetypes.guess_type(str(target))[0] or ("image/png" if is_image else "application/octet-stream")
        return {
            "type": "image" if is_image else "file",
            "path": str(target),
            "name": source.name,
            "mime": mime,
            "size": target.stat().st_size if target.exists() else size,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _import_remote(self, job: dict, index: int, job_count: int) -> dict | None:
        url = str(job.get("url", "") or "")
        parsed = urllib.parse.urlparse(url)
        suffix = Path(urllib.parse.unquote(parsed.path)).suffix.lower()
        suffix_is_known = suffix in _CHAT_IMAGE_EXTENSIONS
        name = Path(urllib.parse.unquote(parsed.path)).name or "web-image"
        request = urllib.request.Request(url, headers={"User-Agent": "BandoriPet/1.0"})
        target = None
        copied = 0
        content_type = ""
        success = False
        try:
            with urllib.request.urlopen(request, timeout=12) as response:
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if content_type and not content_type.startswith("image/"):
                    raise OSError("URL does not point to an image")
                total = int(response.headers.get("content-length", 0) or 0)
                if total > _REMOTE_IMAGE_MAX_BYTES:
                    raise OSError(_tr("ChatWindow.attach_remote_image_too_large", default="网页图片太大"))
                if not suffix_is_known:
                    suffix = ChatWindow._suffix_for_image_content_type(content_type)
                    if Path(name).suffix.lower() not in _CHAT_IMAGE_EXTENSIONS:
                        name = f"{Path(name).stem or 'web-image'}{suffix}"
                target = self._target_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}{suffix}"
                with target.open("wb") as dst:
                    while True:
                        if self.isInterruptionRequested():
                            return None
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > _REMOTE_IMAGE_MAX_BYTES:
                            raise OSError(_tr("ChatWindow.attach_remote_image_too_large", default="网页图片太大"))
                        dst.write(chunk)
                        self._emit_progress(index, job_count, copied, total, name)
            success = True
        finally:
            if not success and target and target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
        mime = content_type if content_type.startswith("image/") else (mimetypes.guess_type(str(target))[0] or "image/png")
        return {
            "type": "image",
            "path": str(target),
            "name": name,
            "mime": mime,
            "size": target.stat().st_size if target and target.exists() else copied,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        }


class ChatWindow(ChatWindowMixin, QWidget):
    action_triggered = Signal(str, str)
    closed = Signal()

    def __init__(self, character: str, model_manager, live2d_module,
                 config_manager, parent_pet=None, group_characters=None):
        super().__init__()
        self._character = character
        self._available_group_characters = self._normalize_group_characters(group_characters or [])
        self._group_characters = list(self._available_group_characters)
        self._is_group_chat = len(self._group_characters) > 1
        self._conversation_key = self._conversation_key_for(self._group_characters if self._is_group_chat else [character])
        self._model_manager = model_manager
        self._cfg = config_manager
        display_names = self._cfg.get("chat_display_names", {}) if self._cfg else {}
        self._chat_display_names = display_names if isinstance(display_names, dict) else {}
        pinned_chat_keys = self._cfg.get("pinned_chat_keys", []) if self._cfg else []
        self._pinned_chat_keys = [
            str(key)
            for key in pinned_chat_keys
            if str(key or "").strip()
        ] if isinstance(pinned_chat_keys, list) else []
        self._conv_id: int | None = None
        self._group_conv_id = ""
        self._worker = None
        self._cancelled_workers = []
        self._close_waiting_for_workers = False
        self._current_bubble: MessageBubble | None = None
        self._pending_actions: list[str] = []
        self._pending_action_character = character
        self._seen_actions: set[str] = set()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._stream_search_sources: list[dict] = []
        self._pending_source_json = ""
        self._tts_text_buffer = ""
        self._tts_tag_buffer = ""
        self._tts_queue: list[tuple[int, str, str]] = []
        self._tts_active_workers: dict[int, TTSRequestWorker] = {}
        self._tts_translation_workers: dict[int, TTSTranslationWorker] = {}
        self._tts_audio_buffers: dict[int, list[tuple[bytes, str]]] = {}
        self._tts_bubbles: dict[int, MessageBubble] = {}
        self._tts_characters: dict[int, str] = {}
        self._tts_completed_sequences: set[int] = set()
        self._tts_generation = 0
        self._tts_request_allowed = False
        self._current_response_actions: list[str] = []
        self._action_tag_stream_buffer = ""
        self._current_tts_rate = 1.0
        self._tts_next_sequence = 0
        self._tts_next_play_sequence = 0
        self._tts_playing_sequence: int | None = None
        self._tts_player = TTSPlayer(self)
        self._tts_player.mouth_pose_changed.connect(self._on_tts_mouth_pose_changed)
        self._tts_player.playback_finished.connect(self._on_tts_playback_finished)
        self._asr_recorder_worker = None
        self._asr_request_worker = None
        self._asr_recording = False
        self._asr_transcribing = False
        self._asr_last_error = ""
        self._pending_actions.clear()
        self._seen_actions.clear()
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setInterval(28)
        self._stream_flush_timer.timeout.connect(self._flush_stream_text)
        self._composer_colors = {}
        self._group_queue: list[str] = []
        self._group_spoken: list[str] = []
        self._auto_active = False
        self._auto_topic = ""
        self._auto_round = 0
        self._auto_max_rounds = 30
        self._auto_delay_ms = 1500
        self._group_plan_worker = None
        self._group_plan_priority_character = ""
        self._vision_fallback_worker = None
        self._memory_workers: list[NonStreamWorker] = []
        self._memory_generation = 0
        self._pending_vision_send: tuple[str, list[dict]] | None = None
        self._plan_divider = None
        self._active_response_character = character
        self._last_user_text = ""
        self._pending_interaction_context = ""
        self._last_user_message_id: int | None = None
        self._last_group_user_message_id: int | None = None
        self._raw_image_inline_message_id: int | None = None
        self._raw_image_inline_group_message_id: int | None = None
        self._closing = False
        self._close_animating = False
        self._window_anim = None
        self._pending_history_menu_action = None
        self._pending_attachments: list[dict] = []
        self._attachment_cards: list[ComposerAttachmentCard] = []
        self._attachment_import_worker: AttachmentImportWorker | None = None
        self._attachment_import_queue: list[list[dict]] = []
        self._attachment_import_last_error = ""
        self._composer_drag_active = False
        self._group_splitter = None
        self._group_toggle_btn = None
        self._group_sidebar_toggle_btn = None
        self._group_list_indicator = None
        self._group_list_indicator_anim = None
        self._group_splitter_adjusting = False
        self._group_sidebar_anim = None
        self._group_sidebar_animating = False
        self._collapsed_chat_size: QSize | None = None
        self._group_sidebar_ratio = self._normalized_group_sidebar_ratio(
            self._cfg.get("group_chat_sidebar_ratio", _GROUP_SIDEBAR_DEFAULT_RATIO)
        ) if self._cfg else _GROUP_SIDEBAR_DEFAULT_RATIO
        self._group_sidebar_collapsed = bool(
            self._cfg.get("group_chat_sidebar_collapsed", False)
        ) if self._cfg else False
        self._group_sidebar_save_timer = QTimer(self)
        self._group_sidebar_save_timer.setSingleShot(True)
        self._group_sidebar_save_timer.timeout.connect(self._save_group_sidebar_settings)
        self._group_sidebar_ratio_timer = QTimer(self)
        self._group_sidebar_ratio_timer.setSingleShot(True)
        self._group_sidebar_ratio_timer.timeout.connect(self._apply_group_sidebar_ratio_to_splitter)
        self._group_relayout_timer = QTimer(self)
        self._group_relayout_timer.setSingleShot(True)
        self._group_relayout_timer.setInterval(45)
        self._group_relayout_timer.timeout.connect(self._relayout_message_bubbles)
        self._last_message_layout_width = -1
        self._last_message_layout_count = -1
        self._scroll_to_bottom_generation = 0
        self._pending_scroll_to_bottom_generation = 0
        self._follow_stream_output = True
        self._history_oldest_message_id: int | None = None
        self._history_has_more = False
        self._history_loading = False
        self._history_pagination_ready = False
        self._history_load_generation = 0
        self._history_prepend_generation = 0

        self._user_name = self._cfg.get("user_name", "").strip() if self._cfg else ""
        self._user_avatar_color = self._cfg.get("user_avatar_color", _TELEGRAM_ACCENT) if self._cfg else _TELEGRAM_ACCENT
        self._user_avatar_path = str(self._cfg.get("user_avatar_path", "") or "").strip() if self._cfg else ""
        self._chat_user_key = self._user_memory_key()
        avatar_paths = self._cfg.get("chat_avatar_paths", {}) if self._cfg else {}
        self._chat_avatar_paths = avatar_paths if isinstance(avatar_paths, dict) else {}
        self._show_reasoning = bool(self._cfg.get("llm_show_reasoning", True)) if self._cfg else True
        self._normal_window_mode = bool(self._cfg.get("chat_window_normal_window", False)) if self._cfg else False
        self._chat_window_always_on_top = bool(self._cfg.get("chat_window_always_on_top", False)) if self._cfg else False

        from database_manager import DatabaseManager
        self._db = DatabaseManager()
        self._assign_legacy_chat_history()
        if not self._is_group_chat:
            self._db.delete_empty_conversations(self._conversation_key, self._chat_user_key)
        self._display_name = self._chat_display_name()

        icon_path = os.path.join(app_base_dir(), "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        self._apply_chat_window_minimum_size()
        self._apply_default_chat_window_size()

        self._apply_window_mode_flags()
        self.setAutoFillBackground(False)

        if self._cfg:
            saved_x = self._cfg.get("chat_window_x")
            saved_y = self._cfg.get("chat_window_y")
            saved_w = self._cfg.get("chat_window_width")
            saved_h = self._cfg.get("chat_window_height")
            if None not in (saved_x, saved_y, saved_w, saved_h):
                saved_rect = QRect(saved_x, saved_y, saved_w, saved_h)
                screen_geo = self._available_geometry_for_window(saved_rect)
                if screen_geo and screen_geo.intersects(saved_rect):
                    self.setGeometry(saved_rect)

        self._init_ui()
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

        self._load_or_create_conversation()

    def _apply_window_mode_flags(self):
        if self._normal_window_mode:
            flags = (
                Qt.WindowType.Window
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowMinimizeButtonHint
                | Qt.WindowType.WindowMaximizeButtonHint
                | Qt.WindowType.WindowCloseButtonHint
            )
            fullscreen_hint = getattr(Qt.WindowType, "WindowFullscreenButtonHint", None)
            if fullscreen_hint is not None:
                flags |= fullscreen_hint
            if self._chat_window_always_on_top:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
            return
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def _normalized_group_sidebar_ratio(self, value) -> float:
        try:
            ratio = float(value)
        except (TypeError, ValueError):
            ratio = _GROUP_SIDEBAR_DEFAULT_RATIO
        return max(_GROUP_SIDEBAR_MIN_RATIO, min(_GROUP_SIDEBAR_MAX_RATIO, ratio))

    def _chat_minimum_size_for(self, sidebar_collapsed: bool | None = None) -> tuple[int, int]:
        if sidebar_collapsed is None:
            sidebar_collapsed = self._group_sidebar_collapsed
        if not sidebar_collapsed:
            return 720, 600
        return 360, 520

    def _chat_minimum_size(self) -> tuple[int, int]:
        return self._chat_minimum_size_for()

    def _apply_chat_window_minimum_size(self, ensure_visible_size: bool = False):
        min_width, min_height = self._chat_minimum_size()
        self.setMinimumSize(min_width, min_height)
        if ensure_visible_size and (self.width() < min_width or self.height() < min_height):
            self.resize(max(self.width(), min_width), max(self.height(), min_height))

    def _apply_default_chat_window_size(self):
        if not self._group_sidebar_collapsed:
            self.resize(880, 680)
        else:
            self.resize(420, 620)

    def _available_geometry_for_window(self, geometry: QRect | None = None) -> QRect | None:
        center = (geometry or self.geometry()).center()
        screen = QApplication.screenAt(center) if center is not None else None
        if screen is None:
            screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _geometry_keeping_right_edge_for_size(self, size: QSize, anchor_geometry: QRect | None = None) -> QRect | None:
        if not size.isValid() or size.isEmpty():
            return None
        anchor = QRect(anchor_geometry or self.geometry())
        width = max(self.minimumWidth(), size.width())
        height = max(self.minimumHeight(), size.height())
        x = anchor.right() - width + 1
        y = anchor.y()
        screen_geo = self._available_geometry_for_window(anchor)
        if screen_geo is not None:
            min_x = screen_geo.left()
            max_x = screen_geo.right() - width + 1
            if max_x >= min_x:
                x = max(min_x, min(x, max_x))
            else:
                x = min_x
            min_y = screen_geo.top()
            max_y = screen_geo.bottom() - height + 1
            if max_y >= min_y:
                y = max(min_y, min(y, max_y))
            else:
                y = min_y
        return QRect(x, y, width, height)

    def _set_size_keeping_right_edge(self, size: QSize, anchor_geometry: QRect | None = None):
        geometry = self._geometry_keeping_right_edge_for_size(size, anchor_geometry=anchor_geometry)
        if geometry is not None:
            self.setGeometry(geometry)

    def _valid_collapsed_chat_size(self, size: QSize | None) -> QSize | None:
        if size is None or not size.isValid() or size.isEmpty():
            return None
        min_width, min_height = self._chat_minimum_size_for(sidebar_collapsed=True)
        return QSize(max(min_width, size.width()), max(min_height, size.height()))

    def _fallback_collapsed_chat_size(self) -> QSize:
        content_width = 0
        if self._group_splitter is not None:
            sizes = self._group_splitter.sizes()
            if len(sizes) > 1:
                content_width = sizes[1]
        if content_width <= 0:
            sidebar_width = self._group_sidebar.width() if self._group_sidebar is not None else 0
            handle_width = self._group_splitter.handleWidth() if self._group_splitter is not None else 0
            content_width = self.width() - sidebar_width - handle_width
        min_width, min_height = self._chat_minimum_size_for(sidebar_collapsed=True)
        return QSize(max(min_width, content_width), max(min_height, self.height()))

    def _expanded_chat_size_for_collapsed_size(self, size: QSize) -> QSize:
        collapsed_size = self._valid_collapsed_chat_size(size) or self._fallback_collapsed_chat_size()
        min_width, min_height = self._chat_minimum_size_for(sidebar_collapsed=False)
        ratio = self._normalized_group_sidebar_ratio(self._group_sidebar_ratio)
        sidebar_min_width = self._group_sidebar.minimumWidth() if self._group_sidebar is not None else 0
        sidebar_width = int(round(collapsed_size.width() * ratio / max(0.01, 1.0 - ratio)))
        sidebar_width = max(sidebar_min_width, sidebar_width)
        return QSize(
            max(min_width, collapsed_size.width() + sidebar_width),
            max(min_height, collapsed_size.height()),
        )

    def _sidebar_width_for_total_width(self, total_width: int) -> int:
        if self._group_sidebar is None:
            return 0
        total = max(1, int(total_width))
        min_width = self._group_sidebar.minimumWidth()
        max_width = max(min_width, int(total * _GROUP_SIDEBAR_MAX_RATIO))
        sidebar_width = int(total * self._group_sidebar_ratio)
        return max(min_width, min(max_width, sidebar_width))

    def _restore_collapsed_chat_size(self, size: QSize, anchor_geometry: QRect | None = None):
        size = self._valid_collapsed_chat_size(size) or self._fallback_collapsed_chat_size()
        if self.size() == size:
            return
        self._set_size_keeping_right_edge(size, anchor_geometry=anchor_geometry)

    def _normalize_group_characters(self, characters: list[str]) -> list[str]:
        result = []
        seen = set()
        for character in characters:
            if not character or character in seen:
                continue
            result.append(character)
            seen.add(character)
        return result

    def _private_display_name(self, character: str) -> str:
        custom_name = str(self._chat_display_names.get(character, "") or "").strip()
        return custom_name or self._model_manager.get_display_name(character)

    def _save_chat_display_names(self):
        if not self._cfg:
            return
        self._cfg.set("chat_display_names", dict(self._chat_display_names))
        try:
            self._cfg.save()
        except Exception:
            pass

    def _is_chat_pinned(self, chat_key: str) -> bool:
        return chat_key in set(self._pinned_chat_keys)

    def _set_chat_pinned(self, chat_key: str, pinned: bool):
        chat_key = str(chat_key or "").strip()
        if not chat_key:
            return
        pinned_keys = [key for key in self._pinned_chat_keys if key != chat_key]
        if pinned:
            pinned_keys.insert(0, chat_key)
        self._pinned_chat_keys = pinned_keys
        if self._cfg:
            self._cfg.set("pinned_chat_keys", list(self._pinned_chat_keys))
            try:
                self._cfg.save()
            except Exception:
                pass
        self._refresh_group_list()

    def _conversation_key_for(self, characters: list[str]) -> str:
        normalized = self._normalize_group_characters(characters)
        if len(normalized) <= 1:
            return normalized[0] if normalized else self._character
        return "__group__:" + "|".join(sorted(normalized, key=str.casefold))

    def _characters_for_group_key(self, group_key: str) -> list[str]:
        if not group_key.startswith("__group__:"):
            return []
        allowed = set(self._model_manager.characters)
        return [character for character in group_key[len("__group__:"):].split("|") if character in allowed]

    def _set_available_group_characters(self, characters: list[str]):
        merged = list(self._available_group_characters)
        seen = set(merged)
        for character in characters:
            if character and character not in seen:
                merged.append(character)
                seen.add(character)
        self._available_group_characters = self._normalize_group_characters(merged)

    def _group_display_name(self, characters: list[str]) -> str:
        group_key = self._conversation_key_for(characters)
        if group_key.startswith("__group__:"):
            custom_name = self._db.get_group_display_name(group_key).strip()
            if custom_name:
                return custom_name
        return self._group_default_display_name(characters)

    def _group_default_display_name(self, characters: list[str]) -> str:
        names = [self._model_manager.get_display_name(character) for character in characters]
        members = "、".join(names)
        return _tr(
            "ChatWindow.group_default_name",
            default="{members}：{name}",
            members=members,
            name=self._auto_group_name(characters),
        )

    def _auto_group_name(self, characters: list[str]) -> str:
        normalized = self._normalize_group_characters(characters)
        bands = {
            self._model_manager.get_character_band(character)
            for character in normalized
            if self._model_manager.get_character_band(character)
        }
        if len(bands) == 1:
            band_id = next(iter(bands))
            if band_id and band_id != "others":
                return _tr(
                    "ChatWindow.group_auto_band_room",
                    default="{band}练习室",
                    band=self._model_manager.get_band_display_name(band_id),
                )
        count = len(normalized)
        if count <= 2:
            return _tr("ChatWindow.group_auto_duo", default="双人练习室")
        if count == 3:
            return _tr("ChatWindow.group_auto_trio", default="三人聊天室")
        if count == 4:
            return _tr("ChatWindow.group_auto_quartet", default="四人排练室")
        return _tr("ChatWindow.group_auto_band", default="联合乐队群")

    def _chat_display_name(self) -> str:
        if self._is_group_chat:
            members = self._group_display_name(self._group_characters)
            return _tr("ChatWindow.group_chat_named", members=members)
        return self._private_display_name(self._character)

    def _group_chats(self) -> list[dict]:
        result = []
        seen = set()
        for chat in self._db.get_group_chats(self._chat_user_key):
            characters = self._characters_for_group_key(chat.get("group_key", ""))
            if len(characters) <= 1:
                continue
            group_key = self._conversation_key_for(characters)
            if group_key in seen:
                continue
            seen.add(group_key)
            entry = dict(chat)
            entry["characters"] = characters
            entry["group_key"] = group_key
            result.append(entry)
        current_characters = self._normalize_group_characters(self._group_characters)
        current_key = self._conversation_key_for(current_characters)
        if len(current_characters) > 1 and current_key not in seen:
            result.insert(0, {
                "group_key": current_key,
                "conversation_id": "",
                "content": "",
                "created_at": "",
                "characters": current_characters,
            })
            seen.add(current_key)
        live2d_characters = self._normalize_group_characters(self._available_group_characters)
        live2d_key = self._conversation_key_for(live2d_characters)
        if len(live2d_characters) > 1 and live2d_key not in seen:
            result.insert(0, {
                "group_key": live2d_key,
                "conversation_id": "",
                "content": "",
                "created_at": "",
                "characters": live2d_characters,
            })
        return result

    def _new_group_conversation_id(self) -> str:
        return "group-" + datetime.now().strftime("%Y%m%d%H%M%S%f")

    def _ensure_group_conversation_id(self) -> str:
        if not self._group_conv_id:
            self._group_conv_id = self._new_group_conversation_id()
        return self._group_conv_id

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_windows_11_border_fix()
        if macos_patch is not None and not self._normal_window_mode:
            QTimer.singleShot(0, lambda: macos_patch.apply_floating_tool_window_polish(self))
        self._schedule_visible_message_relayout()
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(0, self._play_entrance)

    def _schedule_visible_message_relayout(self):
        QTimer.singleShot(0, self._relayout_message_bubbles)
        QTimer.singleShot(80, self._relayout_message_bubbles)

    def _apply_windows_11_border_fix(self):
        if self._normal_window_mode:
            return
        hwnd = int(self.winId())
        apply_windows_11_border_fix(hwnd)

    def _play_entrance(self):
        self.setWindowOpacity(0.0)

        opacity = QPropertyAnimation(self, b"windowOpacity")
        opacity.setDuration(180)
        opacity.setStartValue(0.0)
        opacity.setEndValue(1.0)
        opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._window_anim = opacity
        opacity.start()

    def _play_close_animation(self):
        if self._close_animating:
            return
        self._close_animating = True
        start = self.geometry()
        self._pre_close_geometry = QRect(start)
        end = self._scaled_geometry(start, 0.96)

        group = QParallelAnimationGroup(self)
        opacity = QPropertyAnimation(self, b"windowOpacity")
        opacity.setDuration(140)
        opacity.setStartValue(self.windowOpacity())
        opacity.setEndValue(0.0)
        opacity.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(opacity)

        geometry = QPropertyAnimation(self, b"geometry")
        geometry.setDuration(160)
        geometry.setStartValue(start)
        geometry.setEndValue(end)
        geometry.setEasingCurve(QEasingCurve.Type.InCubic)
        group.addAnimation(geometry)

        group.finished.connect(self._finish_animated_close)
        self._window_anim = group
        group.start()

    @staticmethod
    def _scaled_geometry(rect: QRect, scale: float) -> QRect:
        width = max(1, int(rect.width() * scale))
        height = max(1, int(rect.height() * scale))
        return QRect(
            rect.center().x() - width // 2,
            rect.center().y() - height // 2,
            width,
            height,
        )

    def _finish_animated_close(self):
        self._closing = True
        self._close_animating = False
        self.close()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._shell = RoundedPanel(self)
        self._shell.setObjectName("ChatShell")
        main_layout.addWidget(self._shell)
        self._resize_grip = None

        shell_layout = QHBoxLayout(self._shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        self._group_splitter = FluentSplitter(Qt.Orientation.Horizontal, self._shell)
        self._group_splitter.setObjectName("GroupChatSplitter")
        self._group_splitter.setChildrenCollapsible(False)
        self._group_splitter.setHandleWidth(1)
        self._group_splitter.setOpaqueResize(True)
        self._group_splitter.splitterMoved.connect(self._on_group_splitter_moved)
        shell_layout.addWidget(self._group_splitter)

        self._group_sidebar = self._build_group_sidebar()
        self._group_splitter.addWidget(self._group_sidebar)

        content = QWidget(self._shell)
        content.setObjectName("ChatContent")
        content.setMinimumWidth(360)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._group_splitter.addWidget(content)
        self._group_splitter.setStretchFactor(0, 0)
        self._group_splitter.setStretchFactor(1, 1)
        if self._group_sidebar_collapsed:
            self._group_sidebar.setVisible(False)
        QTimer.singleShot(0, self._restore_group_splitter_sizes)

        self._titlebar = self._build_titlebar()
        content_layout.addWidget(self._titlebar)

        self._msg_area = QWidget()
        self._msg_area.setObjectName("MessageArea")
        self._msg_layout = QVBoxLayout(self._msg_area)
        self._msg_layout.setContentsMargins(0, 14, 0, 14)
        self._msg_layout.setSpacing(4)
        self._msg_layout.addStretch()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(self._msg_area)
        message_scrollbar = self._scroll.verticalScrollBar()
        message_scrollbar.rangeChanged.connect(self._on_message_scroll_range_changed)
        message_scrollbar.actionTriggered.connect(self._cancel_pending_scroll_to_bottom)
        message_scrollbar.valueChanged.connect(self._on_message_scroll_value_changed)
        message_scrollbar.sliderPressed.connect(self._pause_stream_output_follow)
        self._scroll.viewport().installEventFilter(self)
        content_layout.addWidget(self._scroll, 1)

        content_layout.addWidget(self._build_input_area())

        self._resize_grip = ChatResizeGrip(self, self._shell)
        self._resize_grip.setObjectName("ChatResizeGrip")
        self._resize_grip.setVisible(not self._normal_window_mode)
        self._resize_grip.raise_()
        self._position_resize_grip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._group_sidebar_collapsed and not self._group_sidebar_animating:
            self._schedule_group_sidebar_ratio_apply()
        self._position_resize_grip()
        if not self._group_sidebar_animating:
            self._relayout_message_bubbles()

    def _position_resize_grip(self):
        if not self._resize_grip:
            return
        inset = 5
        self._resize_grip.move(
            max(0, self._shell.width() - self._resize_grip.width() - inset),
            max(0, self._shell.height() - self._resize_grip.height() - inset),
        )

    def _restore_group_splitter_sizes(self):
        if not self._group_splitter:
            return
        if self._group_sidebar_collapsed:
            self._set_group_sidebar_collapsed(True, persist=False)
            return
        self._apply_group_sidebar_ratio_to_splitter()

    def _schedule_group_sidebar_ratio_apply(self):
        if self._group_sidebar_ratio_timer.isActive():
            self._group_sidebar_ratio_timer.stop()
        self._group_sidebar_ratio_timer.start(0)

    def _schedule_group_relayout(self):
        if self._group_relayout_timer.isActive():
            self._group_relayout_timer.stop()
        self._group_relayout_timer.start()

    def _apply_group_sidebar_ratio_to_splitter(self):
        if (
            not self._group_splitter
            or not self._group_sidebar
            or self._group_sidebar_collapsed
            or self._group_sidebar_animating
            or self._group_splitter_adjusting
        ):
            return
        total = max(1, self._group_splitter.width())
        sidebar_width = self._sidebar_width_for_total_width(total)
        content_width = max(1, total - sidebar_width)
        self._group_splitter_adjusting = True
        self._group_splitter.setSizes([sidebar_width, content_width])
        self._group_splitter_adjusting = False

    def _on_group_splitter_moved(self, pos: int, index: int):
        if self._group_splitter_adjusting or not self._group_splitter or self._group_sidebar_collapsed:
            return
        sizes = self._group_splitter.sizes()
        total = sum(sizes)
        if total <= 0:
            return
        ratio = self._normalized_group_sidebar_ratio(sizes[0] / total)
        if abs(ratio - (sizes[0] / total)) > 0.001:
            self._group_sidebar_ratio = ratio
            self._apply_group_sidebar_ratio_to_splitter()
        else:
            self._group_sidebar_ratio = ratio
        self._schedule_group_sidebar_settings_save()
        self._schedule_group_relayout()

    def _stop_group_sidebar_animation(self):
        if self._group_sidebar_anim is not None:
            try:
                self._group_sidebar_anim.stop()
            except RuntimeError:
                pass
        self._group_sidebar_anim = None
        self._group_sidebar_animating = False

    def _set_group_splitter_sizes(self, sidebar_width: int, content_width: int):
        if self._group_splitter is None:
            return
        self._group_splitter_adjusting = True
        self._group_splitter.setSizes([max(0, sidebar_width), max(1, content_width)])
        self._group_splitter_adjusting = False

    def _animate_group_sidebar_transition(
        self,
        collapsed: bool,
        target_size: QSize,
        anchor_geometry: QRect,
        scroll_state: tuple[int, bool],
    ) -> bool:
        if not self.isVisible() or self._group_splitter is None or self._group_sidebar is None:
            return False
        end_geometry = self._geometry_keeping_right_edge_for_size(target_size, anchor_geometry=anchor_geometry)
        if end_geometry is None:
            return False
        start_geometry = QRect(self.geometry())
        start_sizes = self._group_splitter.sizes()
        start_sidebar_width = start_sizes[0] if start_sizes else (0 if not collapsed else self._sidebar_width_for_total_width(start_geometry.width()))
        start_content_width = start_sizes[1] if len(start_sizes) > 1 else max(1, start_geometry.width() - start_sidebar_width)
        end_sidebar_width = 0 if collapsed else self._sidebar_width_for_total_width(end_geometry.width())
        end_content_width = max(1, end_geometry.width() - end_sidebar_width)

        self._group_sidebar_ratio_timer.stop()
        self._group_sidebar.setVisible(True)
        self._group_sidebar_animating = True

        anim = QVariantAnimation(self)
        anim.setDuration(_GROUP_SIDEBAR_ANIMATION_MS)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def apply_value(value):
            progress = float(value)
            geometry = QRect(
                int(round(start_geometry.x() + (end_geometry.x() - start_geometry.x()) * progress)),
                int(round(start_geometry.y() + (end_geometry.y() - start_geometry.y()) * progress)),
                int(round(start_geometry.width() + (end_geometry.width() - start_geometry.width()) * progress)),
                int(round(start_geometry.height() + (end_geometry.height() - start_geometry.height()) * progress)),
            )
            self.setGeometry(geometry)
            sidebar_width = int(round(start_sidebar_width + (end_sidebar_width - start_sidebar_width) * progress))
            content_width = int(round(start_content_width + (end_content_width - start_content_width) * progress))
            self._set_group_splitter_sizes(sidebar_width, content_width)
            self._restore_message_scroll_state(scroll_state)

        def finish():
            self._group_sidebar_animating = False
            self._group_sidebar_anim = None
            self.setGeometry(end_geometry)
            self._group_sidebar.setVisible(not collapsed)
            if collapsed:
                self._set_group_splitter_sizes(0, max(1, self._group_splitter.width()))
            else:
                self._apply_chat_window_minimum_size()
                self._apply_group_sidebar_ratio_to_splitter()
            self._sync_layout_after_group_sidebar_toggle(scroll_state)

        anim.valueChanged.connect(apply_value)
        anim.finished.connect(finish)
        self._group_sidebar_anim = anim
        anim.start()
        return True

    def _set_group_sidebar_collapsed(self, collapsed: bool, persist: bool = True):
        if not self._group_splitter or not self._group_sidebar:
            return
        self._stop_group_sidebar_animation()
        scroll_state = self._message_scroll_state()
        anchor_geometry = QRect(self.geometry())
        was_collapsed = self._group_sidebar_collapsed
        collapsed = bool(collapsed)
        if was_collapsed == collapsed:
            self._apply_chat_window_minimum_size()
            self._group_sidebar.setVisible(not collapsed)
            if collapsed:
                self._set_group_splitter_sizes(0, max(1, self._group_splitter.width()))
            else:
                self._apply_group_sidebar_ratio_to_splitter()
            self._sync_group_sidebar_toggle_buttons()
            return
        collapsed_size = None
        expanded_size = None
        if was_collapsed and not collapsed:
            self._collapsed_chat_size = self.size()
            expanded_size = self._expanded_chat_size_for_collapsed_size(self._collapsed_chat_size)
        elif not was_collapsed and collapsed:
            collapsed_size = self._valid_collapsed_chat_size(self._collapsed_chat_size)
            if collapsed_size is None:
                collapsed_size = self._fallback_collapsed_chat_size()
        self._group_sidebar_collapsed = bool(collapsed)
        if was_collapsed and not collapsed and expanded_size is not None and self.isVisible():
            min_width, min_height = self._chat_minimum_size_for(sidebar_collapsed=True)
            self.setMinimumSize(min_width, min_height)
        else:
            self._apply_chat_window_minimum_size()
        self._sync_group_sidebar_toggle_buttons()
        self._apply_theme()
        target_size = collapsed_size if self._group_sidebar_collapsed else expanded_size
        if target_size is not None and self._animate_group_sidebar_transition(
            self._group_sidebar_collapsed,
            target_size,
            anchor_geometry,
            scroll_state,
        ):
            if persist:
                self._schedule_group_sidebar_settings_save()
            return
        self._group_sidebar.setVisible(not self._group_sidebar_collapsed)
        if self._group_sidebar_collapsed:
            self._group_splitter.setSizes([0, max(1, self._group_splitter.width())])
            if collapsed_size is not None:
                self._restore_collapsed_chat_size(collapsed_size, anchor_geometry=anchor_geometry)
        else:
            if expanded_size is not None:
                self._set_size_keeping_right_edge(expanded_size, anchor_geometry=anchor_geometry)
            self._schedule_group_sidebar_ratio_apply()
        self._sync_layout_after_group_sidebar_toggle(scroll_state)
        if persist:
            self._schedule_group_sidebar_settings_save()

    def _message_scroll_state(self) -> tuple[int, bool]:
        sb = self._scroll.verticalScrollBar()
        return sb.value(), sb.value() >= sb.maximum() - 4

    def _restore_message_scroll_state(self, state: tuple[int, bool]):
        value, was_at_bottom = state
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum() if was_at_bottom else min(value, sb.maximum()))

    def _sync_layout_after_group_sidebar_toggle(self, scroll_state: tuple[int, bool] | None = None):
        if self.layout():
            self.layout().activate()
        if getattr(self, "_shell", None) is not None and self._shell.layout():
            self._shell.layout().activate()
        if self._group_splitter is not None:
            if self._group_sidebar_collapsed:
                self._group_splitter.setSizes([0, max(1, self._group_splitter.width())])
            else:
                self._apply_group_sidebar_ratio_to_splitter()
        self._relayout_message_bubbles()
        if scroll_state is not None:
            self._restore_message_scroll_state(scroll_state)
        for delay in (0, 35, 90):
            QTimer.singleShot(delay, lambda state=scroll_state: self._finish_group_sidebar_layout_sync(state))

    def _finish_group_sidebar_layout_sync(self, scroll_state: tuple[int, bool] | None = None):
        if self._group_splitter is not None and not self._group_sidebar_collapsed:
            self._apply_group_sidebar_ratio_to_splitter()
        self._relayout_message_bubbles()
        if scroll_state is not None:
            self._restore_message_scroll_state(scroll_state)
        self._scroll.viewport().update()
        self._scroll.update()
        self._msg_area.update()
        self._shell.update()

    def _toggle_group_sidebar(self):
        self._set_group_sidebar_collapsed(not self._group_sidebar_collapsed)

    def _toggle_chat_window_topmost(self):
        self._set_chat_window_topmost(not self._chat_window_always_on_top)

    def _set_chat_window_topmost(self, enabled: bool, persist: bool = True):
        if not self._normal_window_mode:
            return
        enabled = bool(enabled)
        if self._chat_window_always_on_top == enabled:
            self._sync_chat_window_topmost_button()
            return

        geometry = self.geometry()
        window_state = self.windowState()
        was_visible = self.isVisible()
        self._chat_window_always_on_top = enabled
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.setGeometry(geometry)
        self.setWindowState(window_state)
        if was_visible:
            self.show()
            if enabled:
                self.raise_()
                self.activateWindow()

        if persist and self._cfg:
            self._cfg.set("chat_window_always_on_top", self._chat_window_always_on_top)
            try:
                self._cfg.save()
            except Exception:
                pass
        self._sync_chat_window_topmost_button()

    def _sync_chat_window_topmost_button(self):
        if getattr(self, "_topmost_btn", None) is None:
            return
        self._topmost_btn.setVisible(self._normal_window_mode)
        if self._chat_window_always_on_top:
            self._topmost_btn.setIcon(FluentIcon.UNPIN.icon())
            self._topmost_btn.setToolTip(_tr("ChatWindow.window_unpin", default="取消窗口置顶"))
        else:
            self._topmost_btn.setIcon(FluentIcon.PIN.icon())
            self._topmost_btn.setToolTip(_tr("ChatWindow.window_pin", default="窗口置顶"))

    def _sync_group_sidebar_toggle_buttons(self):
        collapse_text = _tr(
            "ChatWindow.chat_list_collapse",
            default="收起聊天列表",
        )
        expand_text = _tr(
            "ChatWindow.chat_list_expand",
            default="展开聊天列表",
        )
        if self._group_toggle_btn is not None:
            icon = FluentIcon.MENU if self._group_sidebar_collapsed else FluentIcon.CARE_LEFT_SOLID
            self._group_toggle_btn.setIcon(icon.icon())
            self._group_toggle_btn.setToolTip(expand_text if self._group_sidebar_collapsed else collapse_text)
        if self._group_sidebar_toggle_btn is not None:
            self._group_sidebar_toggle_btn.setIcon(FluentIcon.CARE_LEFT_SOLID.icon())
            self._group_sidebar_toggle_btn.setToolTip(collapse_text)

    def _schedule_group_sidebar_settings_save(self):
        if self._cfg:
            self._group_sidebar_save_timer.start(250)

    def _save_group_sidebar_settings(self):
        if not self._cfg:
            return
        self._cfg.set("group_chat_sidebar_ratio", self._group_sidebar_ratio)
        self._cfg.set("group_chat_sidebar_collapsed", self._group_sidebar_collapsed)
        try:
            self._cfg.save()
        except Exception:
            pass

    def _build_group_sidebar(self):
        sidebar = RoundedPanel(self._shell)
        sidebar.setObjectName("GroupSidebar")
        sidebar.setMinimumWidth(164)
        sidebar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 10, 12)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title = StrongBodyLabel(
            _tr("ChatWindow.chat_list", default="聊天列表"),
            sidebar,
        )
        title.setObjectName("GroupSidebarTitle")
        title.setMinimumWidth(0)
        header.addWidget(title, 1)
        collapse_btn = TransparentToolButton(FluentIcon.CARE_LEFT_SOLID, sidebar)
        collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse_btn.setFixedSize(28, 28)
        collapse_btn.clicked.connect(lambda: self._set_group_sidebar_collapsed(True))
        header.addWidget(collapse_btn)
        subtitle = BodyLabel(
            _tr(
                "ChatWindow.chat_list_hint",
                default="快速切换私聊和群聊；右键可管理名称、头像和置顶。",
            ),
            sidebar,
        )
        subtitle.setObjectName("GroupSidebarSubtitle")
        subtitle.setWordWrap(True)
        layout.addLayout(header)
        layout.addWidget(subtitle)

        scroll = QScrollArea(sidebar)
        scroll.setObjectName("GroupListScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        list_widget = QWidget(scroll)
        list_widget.setObjectName("GroupList")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 2, 2, 2)
        list_layout.setSpacing(4)
        scroll.setWidget(list_widget)
        layout.addWidget(scroll, 1)

        new_chat_btn = QToolButton(sidebar)
        new_chat_btn.setObjectName("NewChatPickerButton")
        new_chat_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        new_chat_btn.setIcon(FluentIcon.ADD.icon())
        new_chat_btn.setText(_tr("ChatWindow.new_chat_picker", default="新建聊天"))
        new_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_chat_btn.clicked.connect(self._show_new_chat_picker)
        layout.addWidget(new_chat_btn)
        self._new_chat_picker_btn = new_chat_btn

        self._group_sidebar_title = title
        self._group_sidebar_subtitle = subtitle
        self._group_sidebar_toggle_btn = collapse_btn
        self._group_list_scroll = scroll
        self._group_list_widget = list_widget
        self._group_list_layout = list_layout
        self._group_list_indicator = QFrame(list_widget)
        self._group_list_indicator.setObjectName("GroupListCurrentIndicator")
        self._group_list_indicator.setFixedWidth(3)
        self._group_list_indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._group_list_indicator.hide()
        self._apply_group_list_indicator_theme()
        self._refresh_group_list()
        return sidebar

    def _group_preview(self, chat: dict) -> str:
        preview = str(chat.get("content", "")).strip().replace("\n", " ")
        if preview.startswith("【") and "】" in preview:
            preview = preview[preview.index("】") + 1:].strip()
        if not preview:
            preview = _tr("ChatWindow.empty_conv")
        if len(preview) > 28:
            preview = preview[:28] + "..."
        created_at = str(chat.get("created_at", ""))
        time_text = created_at[5:16] if len(created_at) >= 16 else created_at
        return f"{time_text}  {preview}".strip()

    def _chat_avatar_pixmap_for_characters(self, characters: list[str], size: int = 34) -> QPixmap:
        for character in self._normalize_group_characters(characters):
            path, data, focus = self._avatar_info_for_character(character)
            pixmap = _rounded_avatar_pixmap(path, data, size, focus)
            if not pixmap.isNull():
                return pixmap
        return QPixmap()

    def _chat_picker_characters(self) -> list[str]:
        result = []
        seen = set()

        def add(character: str):
            character = str(character or "").strip()
            if character and character in self._model_manager.characters and character not in seen:
                result.append(character)
                seen.add(character)

        add(self._character)
        for character in self._available_group_characters:
            add(character)
        models = self._cfg.get("models", []) if self._cfg else []
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict):
                    add(item.get("character", ""))
        for conv in self._db.get_conversations(user_key=self._chat_user_key):
            add(conv.get("character", ""))
        for character in self._model_manager.characters:
            add(character)
        return result

    def _private_chat_characters_with_history(self) -> list[str]:
        result = []
        seen = set()
        for conv in self._db.get_conversations(user_key=self._chat_user_key):
            character = str(conv.get("character", "") or "").strip()
            if character and character in self._model_manager.characters and character not in seen:
                result.append(character)
                seen.add(character)
        return result

    def _private_chat_preview(self, character: str) -> tuple[str, str]:
        conversations = self._db.get_conversations(character, self._chat_user_key)
        if not conversations:
            return _tr("ChatWindow.private_empty_preview", default="开始私聊"), ""
        conv = conversations[0]
        preview = str(conv.get("last_message_content") or conv.get("title") or "").strip().replace("\n", " ")
        if preview.startswith("【") and "】" in preview:
            preview = preview[preview.index("】") + 1:].strip()
        if not preview:
            preview = _tr("ChatWindow.empty_conv")
        if len(preview) > 28:
            preview = preview[:28] + "..."
        created_at = str(conv.get("last_message_at") or conv.get("created_at") or "")
        time_text = created_at[5:16] if len(created_at) >= 16 else created_at
        return f"{time_text}  {preview}".strip(), created_at

    def _private_chat_entries(self) -> list[dict]:
        entries = []
        for index, character in enumerate(self._private_chat_characters_with_history()):
            preview, last_at = self._private_chat_preview(character)
            chat_key = self._conversation_key_for([character])
            entries.append({
                "characters": [character],
                "chat_key": chat_key,
                "title": self._private_display_name(character),
                "preview": preview,
                "last_at": last_at,
                "order": index,
                "pinned": self._is_chat_pinned(chat_key),
            })
        entries.sort(key=lambda item: (0 if item["pinned"] else 1, item["order"]))
        return entries

    def _group_chat_entries(self) -> list[dict]:
        entries = []
        for index, chat in enumerate(self._group_chats()):
            characters = chat["characters"]
            chat_key = self._conversation_key_for(characters)
            entries.append({
                "characters": characters,
                "chat_key": chat_key,
                "title": self._group_display_name(characters),
                "preview": self._group_preview(chat),
                "last_at": str(chat.get("created_at", "")),
                "order": index,
                "pinned": self._is_chat_pinned(chat_key),
            })
        entries.sort(key=lambda item: (0 if item["pinned"] else 1, item["order"]))
        return entries

    def _add_chat_sidebar_section(self, text: str):
        label = BodyLabel(text, self._group_list_widget)
        label.setObjectName("GroupListSection")
        self._group_list_layout.addWidget(label)

    def _refresh_modern_chat_list(self):
        current_key = self._conversation_key
        private_entries = self._private_chat_entries()
        group_entries = self._group_chat_entries()

        self._add_chat_sidebar_section(_tr("ChatWindow.private_chats", default="私聊"))
        if not private_entries:
            empty = BodyLabel(_tr("ChatWindow.no_private_chats", default="暂无私聊记录"), self._group_list_widget)
            empty.setObjectName("GroupListEmpty")
            empty.setWordWrap(True)
            self._group_list_layout.addWidget(empty)
        for entry in private_entries:
            row = GroupChatListRow(
                entry["characters"],
                entry["title"],
                entry["preview"],
                entry["chat_key"] == current_key and not self._is_group_chat,
                self._group_list_widget,
                avatar_pixmap=self._chat_avatar_pixmap_for_characters(entry["characters"]),
                kind_text=_tr("ChatWindow.private_chat_short", default="私聊"),
                pinned=entry["pinned"],
            )
            row.selected.connect(self._switch_group_chat)
            row.context_menu_requested.connect(self._show_group_chat_context_menu)
            self._group_list_layout.addWidget(row)

        self._add_chat_sidebar_section(_tr("ChatWindow.group_chats", default="群聊"))
        if not group_entries:
            empty = BodyLabel(_tr("ChatWindow.no_group_chats", default="暂无群聊"), self._group_list_widget)
            empty.setObjectName("GroupListEmpty")
            empty.setWordWrap(True)
            self._group_list_layout.addWidget(empty)
        for entry in group_entries:
            row = GroupChatListRow(
                entry["characters"],
                entry["title"],
                entry["preview"],
                entry["chat_key"] == current_key and self._is_group_chat,
                self._group_list_widget,
                avatar_pixmap=self._chat_avatar_pixmap_for_characters(entry["characters"]),
                kind_text=_tr("ChatWindow.group_chat_short", default="群聊"),
                pinned=entry["pinned"],
            )
            row.selected.connect(self._switch_group_chat)
            row.context_menu_requested.connect(self._show_group_chat_context_menu)
            self._group_list_layout.addWidget(row)
        self._group_list_layout.addStretch()

    def _apply_group_list_indicator_theme(self):
        if self._group_list_indicator is None:
            return
        self._group_list_indicator.setStyleSheet(f"""
            QFrame#GroupListCurrentIndicator {{
                background: {accent_color(isDarkTheme())};
                border-radius: 1px;
            }}
        """)

    def _current_group_list_row(self):
        if not hasattr(self, "_group_list_layout"):
            return None
        current_key = self._conversation_key
        for i in range(self._group_list_layout.count()):
            item = self._group_list_layout.itemAt(i)
            widget = item.widget() if item else None
            if not isinstance(widget, GroupChatListRow):
                continue
            if self._conversation_key_for(widget.characters()) == current_key:
                return widget
        return None

    def _group_list_indicator_rect_for_row(self, row: GroupChatListRow) -> QRect:
        return QRect(row.x() + 1, row.y() + 14, 3, max(1, row.height() - 28))

    def _move_group_list_indicator_to_current(self, animated: bool = True):
        indicator = self._group_list_indicator
        if indicator is None:
            return
        row = self._current_group_list_row()
        if row is None:
            indicator.hide()
            return
        target = self._group_list_indicator_rect_for_row(row)
        if self._group_list_indicator_anim is not None:
            self._group_list_indicator_anim.stop()
            self._group_list_indicator_anim = None
        indicator.raise_()
        if not animated or not indicator.isVisible():
            indicator.setGeometry(target)
            indicator.show()
            return
        anim = QPropertyAnimation(indicator, b"geometry", self)
        anim.setDuration(180)
        anim.setStartValue(indicator.geometry())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: setattr(self, "_group_list_indicator_anim", None))
        self._group_list_indicator_anim = anim
        anim.start()

    def _refresh_group_list(self):
        if not hasattr(self, "_group_list_layout"):
            return
        if self._group_list_indicator_anim is not None:
            self._group_list_indicator_anim.stop()
            self._group_list_indicator_anim = None
        while self._group_list_layout.count():
            item = self._group_list_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()

        self._refresh_modern_chat_list()
        QTimer.singleShot(0, lambda: self._move_group_list_indicator_to_current(animated=False))

    def _sync_group_list_current_state(self) -> bool:
        if not hasattr(self, "_group_list_layout"):
            return False
        found_current = False
        current_key = self._conversation_key
        for i in range(self._group_list_layout.count()):
            item = self._group_list_layout.itemAt(i)
            widget = item.widget() if item else None
            if not isinstance(widget, GroupChatListRow):
                continue
            row_key = self._conversation_key_for(widget.characters())
            is_current = row_key == current_key
            widget.set_current(is_current)
            found_current = found_current or is_current
        if found_current:
            QTimer.singleShot(0, self._move_group_list_indicator_to_current)
        return found_current

    def _show_new_chat_picker(self):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        characters = self._chat_picker_characters()
        if not characters:
            return
        menu = QMenu(self)
        _prepare_rounded_menu(menu, 10)
        menu.setObjectName("NewChatPickerMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        border = "#303849" if dark else "#d8deea"
        menu.setStyleSheet(f"""
            QMenu#NewChatPickerMenu {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 10px;
                padding: 0px;
            }}
        """)
        current_selection = self._group_characters if self._is_group_chat else [self._character]
        panel = ChatCharacterPickerPanel(
            characters,
            lambda character: self._model_manager.get_display_name(character),
            selected=current_selection,
            bands=self._model_manager.bands,
            parent=menu,
        )
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)

        def open_chat(selected_characters):
            menu.close()
            self._switch_group_chat(list(selected_characters))

        panel.open_requested.connect(open_chat)
        button = getattr(self, "_new_chat_picker_btn", None)
        if button is not None:
            pos = button.mapToGlobal(button.rect().topLeft())
            menu.exec(pos)
        else:
            menu.exec(self.mapToGlobal(self.rect().center()))

    def _build_titlebar(self):
        bar = RoundedPanel()
        bar.setObjectName("Titlebar")
        bar.setFixedHeight(58)
        bar.setCursor(Qt.CursorShape.ArrowCursor)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(10)

        avatar = QLabel(self._display_name[:1].upper(), bar)
        avatar.setObjectName("TitleAvatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setCursor(Qt.CursorShape.PointingHandCursor)
        avatar.setToolTip(_tr("ChatWindow.avatar_tooltip"))
        avatar.mouseReleaseEvent = self._on_title_avatar_released
        avatar.mouseDoubleClickEvent = self._on_title_avatar_double_clicked
        layout.addWidget(avatar)
        self._title_avatar_click_timer = QTimer(self)
        self._title_avatar_click_timer.setSingleShot(True)
        self._title_avatar_click_timer.timeout.connect(self._show_conversation_history)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(0)
        title = StrongBodyLabel(self._display_name, bar)
        title.setObjectName("ChatTitle")
        subtitle = BodyLabel(_tr("ChatWindow.subtitle"), bar)
        subtitle.setObjectName("ChatSubtitle")
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        layout.addLayout(title_stack)
        layout.addStretch()

        topmost_btn = IconButton(FluentIcon.PIN, bar)
        topmost_btn.setFixedSize(32, 32)
        topmost_btn.clicked.connect(self._toggle_chat_window_topmost)
        topmost_btn.setVisible(self._normal_window_mode)
        layout.addWidget(topmost_btn)
        self._topmost_btn = topmost_btn

        group_toggle_btn = IconButton(FluentIcon.CARE_LEFT_SOLID, bar)
        group_toggle_btn.setFixedSize(32, 32)
        group_toggle_btn.clicked.connect(self._toggle_group_sidebar)
        layout.addWidget(group_toggle_btn)
        self._group_toggle_btn = group_toggle_btn

        new_btn = IconButton(FluentIcon.ADD, bar)
        new_btn.setFixedSize(32, 32)
        new_btn.setToolTip(_tr("ChatWindow.new_chat"))
        new_btn.clicked.connect(self._new_conversation)
        layout.addWidget(new_btn)

        close_btn = IconButton(FluentIcon.CLOSE, bar)
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.close)
        close_btn.setVisible(not self._normal_window_mode)
        layout.addWidget(close_btn)

        self._new_btn = new_btn
        self._close_btn = close_btn
        self._title_avatar = avatar
        self._title_label = title
        self._update_title_avatar()
        self._sync_chat_window_topmost_button()
        self._sync_group_sidebar_toggle_buttons()

        self._drag_start = None

        def mouse_press(event):
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_start = event.globalPosition().toPoint()

        def mouse_move(event):
            if self._drag_start is not None:
                delta = event.globalPosition().toPoint() - self._drag_start
                self.move(self.x() + delta.x(), self.y() + delta.y())
                self._drag_start = event.globalPosition().toPoint()

        def mouse_release(event):
            self._drag_start = None

        bar.mousePressEvent = mouse_press
        bar.mouseMoveEvent = mouse_move
        bar.mouseReleaseEvent = mouse_release

        return bar

    def _title_avatar_character(self) -> str:
        if self._is_group_chat:
            return self._group_characters[0] if self._group_characters else ""
        return self._character

    def _avatar_info_for_character(self, character: str) -> tuple[str, bytes, str]:
        if not character:
            return "", b"", "center"
        custom_path = str(self._chat_avatar_paths.get(character, "")).strip()
        if custom_path and os.path.exists(custom_path):
            return custom_path, b"", "center"
        path = self._model_manager.get_character_image_path(character)
        if path:
            return path, b"", "head"
        data = self._model_manager.get_character_image_data(character)
        return "", data, "head" if data else "center"

    def _update_title_avatar(self):
        character = self._title_avatar_character()
        path, data, focus = self._avatar_info_for_character(character)
        pixmap = _rounded_avatar_pixmap(path, data, 34, focus)
        if pixmap.isNull():
            self._title_avatar.setPixmap(QPixmap())
            self._title_avatar.setText(self._display_name[:1].upper())
        else:
            self._title_avatar.setText("")
            self._title_avatar.setPixmap(pixmap)

    def _message_character(self, content: str, role: str) -> str:
        if role != "assistant":
            return ""
        if not self._is_group_chat:
            return self._character
        first_line = content.splitlines()[0].strip() if content else ""
        if first_line.startswith("【") and "】" in first_line:
            name = first_line[1:first_line.index("】")]
            for character in self._group_characters:
                if name == self._model_manager.get_display_name(character):
                    return character
        for character in self._group_characters:
            display = self._model_manager.get_display_name(character)
            if content.startswith(f"【{display}】"):
                return character
        return ""

    def _avatar_storage_dir(self) -> Path:
        return Path(app_base_dir()) / ".runtime" / "chat_avatars"

    def _safe_avatar_name(self, character: str, ext: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", character).strip("._")
        return f"{safe or 'avatar'}{ext}"

    def _set_character_avatar(self, character: str):
        if not character:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            _tr("ChatWindow.avatar_choose_title"),
            "",
            _tr("ChatWindow.avatar_image_filter"),
        )
        if not file_path:
            return
        source = Path(file_path)
        ext = source.suffix.lower()
        if ext not in AVATAR_EXTENSIONS:
            ext = ".png"
        try:
            target_dir = self._avatar_storage_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / self._safe_avatar_name(character, ext)
            shutil.copyfile(source, target)
            self._chat_avatar_paths[character] = str(target)
            if self._cfg:
                self._cfg.set("chat_avatar_paths", dict(self._chat_avatar_paths))
                self._cfg.save()
            self._refresh_avatar_views()
        except Exception as exc:
            QMessageBox.warning(
                self,
                _tr("ChatWindow.avatar_save_failed_title"),
                _tr("ChatWindow.avatar_save_failed_content", error=str(exc)),
            )

    def _reset_character_avatar(self, character: str):
        if not character:
            return
        if character in self._chat_avatar_paths:
            self._chat_avatar_paths.pop(character, None)
            if self._cfg:
                self._cfg.set("chat_avatar_paths", dict(self._chat_avatar_paths))
                self._cfg.save()
            self._refresh_avatar_views()

    def _refresh_avatar_views(self):
        self._update_title_avatar()
        self._refresh_group_list()
        if self._is_group_chat or self._conv_id is not None:
            self._clear_message_widgets()
            self._load_messages()

    @staticmethod
    def _paperclip_icon(color: str) -> QIcon:
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color), 3.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        path = QPainterPath()
        path.moveTo(29, 15)
        path.lineTo(29, 31)
        path.cubicTo(29, 37, 25, 41, 19, 41)
        path.cubicTo(13, 41, 9, 37, 9, 31)
        path.lineTo(9, 18)
        path.cubicTo(9, 10, 15, 5, 22, 5)
        path.cubicTo(30, 5, 35, 11, 35, 18)
        path.lineTo(35, 31)
        path.cubicTo(35, 41, 28, 46, 19, 46)
        path.cubicTo(10, 46, 3, 40, 3, 31)
        path.lineTo(3, 19)
        painter.drawPath(path)
        painter.end()
        return QIcon(pixmap)

    def _refresh_attach_button_icon(self):
        attach_btn = getattr(self, "_attach_btn", None)
        if attach_btn is None:
            return
        color = "#eef2ff" if isDarkTheme() else "#34405a"
        attach_btn.setIcon(self._paperclip_icon(color))

    def _build_input_area(self):
        area = RoundedPanel()
        area.setObjectName("InputArea")
        area.setFixedHeight(110)
        outer = QVBoxLayout(area)
        outer.setContentsMargins(20, 8, 20, 14)
        outer.setSpacing(8)

        hint_row = QHBoxLayout()
        hint_row.setContentsMargins(6, 0, 6, 0)
        hint_row.setSpacing(6)
        self._status_dot = QLabel("", area)
        self._status_dot.setFixedSize(7, 7)
        self._composer_hint = QLabel(self._idle_status_text(), area)
        hint_font = QFont()
        hint_font.setPointSize(8)
        self._composer_hint.setFont(hint_font)
        hint_row.addWidget(self._status_dot)
        hint_row.addWidget(self._composer_hint)
        hint_row.addStretch()
        self._attachment_progress = ProgressBar(area)
        self._attachment_progress.setRange(0, 100)
        self._attachment_progress.setValue(0)
        self._attachment_progress.setFixedWidth(128)
        self._attachment_progress.hide()
        hint_row.addWidget(self._attachment_progress)
        self._attachment_progress_label = QLabel("", area)
        self._attachment_progress_label.setFont(hint_font)
        self._attachment_progress_label.setMinimumWidth(34)
        self._attachment_progress_label.hide()
        hint_row.addWidget(self._attachment_progress_label)
        outer.addLayout(hint_row)

        self._composer = RoundedPanel(area)
        self._composer.setObjectName("Composer")
        self._composer.setFixedHeight(66)
        self._composer.setAcceptDrops(True)
        self._composer.installEventFilter(self)
        composer_layout = QVBoxLayout(self._composer)
        composer_layout.setContentsMargins(12, 8, 12, 8)
        composer_layout.setSpacing(6)

        self._attachment_scroll = QScrollArea(self._composer)
        self._attachment_scroll.setObjectName("ComposerAttachmentScroll")
        self._attachment_scroll.setWidgetResizable(True)
        self._attachment_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._attachment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._attachment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._attachment_scroll.setFixedHeight(64)
        self._attachment_scroll.setVisible(False)
        self._attachment_scroll.setAcceptDrops(True)
        self._attachment_scroll.installEventFilter(self)

        self._attachment_strip = QWidget(self._attachment_scroll)
        self._attachment_strip.setObjectName("ComposerAttachmentStrip")
        self._attachment_strip.setAcceptDrops(True)
        self._attachment_strip.installEventFilter(self)
        self._attachment_strip_layout = QHBoxLayout(self._attachment_strip)
        self._attachment_strip_layout.setContentsMargins(0, 0, 0, 0)
        self._attachment_strip_layout.setSpacing(6)
        self._attachment_strip_layout.addStretch()
        self._attachment_scroll.setWidget(self._attachment_strip)
        composer_layout.addWidget(self._attachment_scroll)

        self._composer_controls = QWidget(self._composer)
        self._composer_controls.setObjectName("ComposerControls")
        self._composer_controls.setAcceptDrops(True)
        self._composer_controls.installEventFilter(self)
        layout = QHBoxLayout(self._composer_controls)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(10)

        self._attach_btn = IconButton(self._paperclip_icon("#34405a"), self._composer_controls)
        self._attach_btn.setFixedSize(46, 46)
        self._attach_btn.setIconSize(QSize(22, 22))
        self._attach_btn.setToolTip(_tr("ChatWindow.attach_file_tooltip", default="添加附件"))
        self._attach_btn.clicked.connect(self._choose_chat_attachments)
        self._attach_btn.setAcceptDrops(True)
        self._attach_btn.installEventFilter(self)
        layout.addWidget(self._attach_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._asr_btn = IconButton(FluentIcon.MICROPHONE, self._composer_controls)
        self._asr_btn.setFixedSize(46, 46)
        self._asr_btn.setIconSize(QSize(22, 22))
        self._asr_btn.setToolTip(_tr("ChatWindow.asr_start_tooltip", default="开始语音输入"))
        self._asr_btn.clicked.connect(self._toggle_asr_recording)
        self._asr_btn.setEnabled(self._asr_enabled())
        layout.addWidget(self._asr_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._input = ChatComposerTextEdit()
        self._input.set_chat_mime_handlers(self._mime_has_chat_attachments, self._add_chat_attachments_from_mime)
        self._input.setPlaceholderText(_tr("ChatWindow.input_placeholder"))
        self._input.setAcceptRichText(False)
        self._input.setFixedHeight(46)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font = QFont()
        font.setPointSize(10)
        self._input.setFont(font)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setAcceptDrops(True)
        self._input.installEventFilter(self)
        self._input.viewport().setAcceptDrops(True)
        self._input.viewport().installEventFilter(self)
        self._input.textChanged.connect(self._sync_input_height)
        self._input.textChanged.connect(self._on_composer_text_changed)
        self._command_completer = CommandCompleter(self._input)
        self._command_completer.command_selected.connect(self._on_command_selected)
        self._completer_suppress = False
        layout.addWidget(self._input)

        self._send_btn = ChatSendButton(self._composer_controls)
        self._send_btn.setFixedSize(46, 46)
        self._send_btn.setIconSize(QSize(22, 22))
        self._send_btn.setToolTip(_tr("ChatWindow.send_tooltip"))
        self._send_btn.clicked.connect(self._on_send_button_clicked)
        self._send_btn.setAcceptDrops(True)
        self._send_btn.installEventFilter(self)
        layout.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        composer_layout.addWidget(self._composer_controls)

        outer.addWidget(self._composer)

        self._input_area = area
        self._input_area.setAcceptDrops(True)
        self._input_area.installEventFilter(self)
        return area

    def eventFilter(self, obj, event):
        message_viewport = getattr(getattr(self, "_scroll", None), "viewport", lambda: None)()
        if obj == message_viewport and event.type() == QEvent.Type.Wheel:
            scrollbar = self._scroll.verticalScrollBar()
            vertical_delta = event.angleDelta().y() or event.pixelDelta().y()
            if vertical_delta > 0:
                self._pause_stream_output_follow()
            if vertical_delta > 0 and scrollbar.value() <= scrollbar.minimum():
                if self._load_older_messages():
                    event.accept()
                    return True
        input_widget = getattr(self, "_input", None)
        input_viewport = input_widget.viewport() if input_widget is not None else None
        drag_targets = {
            widget
            for widget in (
                input_widget,
                input_viewport,
                getattr(self, "_composer", None),
                getattr(self, "_attachment_scroll", None),
                getattr(self, "_attachment_strip", None),
                getattr(self, "_composer_controls", None),
                getattr(self, "_input_area", None),
                getattr(self, "_attach_btn", None),
                getattr(self, "_asr_btn", None),
                getattr(self, "_send_btn", None),
            )
            if widget is not None
        }
        if obj in drag_targets:
            if event.type() in (
                QEvent.Type.DragEnter,
                QEvent.Type.DragMove,
                QEvent.Type.DragLeave,
                QEvent.Type.Drop,
            ):
                return self._handle_composer_drag_event(event)
        attachment_scroll = getattr(self, "_attachment_scroll", None)
        if obj == attachment_scroll and event.type() == QEvent.Type.Wheel:
            bar = attachment_scroll.horizontalScrollBar()
            if bar.maximum() > bar.minimum():
                delta = event.angleDelta().y() or event.angleDelta().x()
                bar.setValue(bar.value() - delta)
                event.accept()
                return True
        if input_widget is not None and obj == input_widget and event.type() == QKeyEvent.Type.KeyPress:
            comp = getattr(self, "_command_completer", None)
            if comp is not None and comp.is_shown():
                if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    if event.key() == Qt.Key.Key_Up:
                        comp.move_up()
                    else:
                        comp.move_down()
                    return True
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Tab):
                    comp.select_current()
                    return True
                if event.key() == Qt.Key.Key_Escape:
                    comp.hide()
                    return True
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._send_message()
                return True
            if event.key() == Qt.Key.Key_Return and not event.modifiers():
                self._send_message()
                return True
            if event.key() == Qt.Key.Key_Return and event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                return False
        if input_widget is not None and obj == input_widget and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            QTimer.singleShot(0, self._update_composer_focus_style)
            if event.type() == QEvent.Type.FocusOut:
                comp = getattr(self, "_command_completer", None)
                if comp is not None:
                    QTimer.singleShot(100, comp.hide)
        return super().eventFilter(obj, event)

    def _apply_theme(self):
        dark = isDarkTheme()
        bg = _BG_DARK if dark else _BG_LIGHT
        border = "#242a37" if dark else "#d8deea"
        input_bg = "#181c25" if dark else "#ffffff"
        input_border = "#303849" if dark else "#cfd8ec"
        text_color = "#f8f8fb" if dark else "#1f2328"
        muted = "#a9b0c3" if dark else "#657089"
        title_bg = "#151923" if dark else "#ffffff"
        title_border = "#242a37" if dark else "#e0e6f2"
        composer_bg = "#131720" if dark else "#eef3fb"
        scroll_bg = "#0f1117" if dark else "#f5f7fb"
        self._composer_colors = {
            "bg": input_bg,
            "border": input_border,
            "focus_border": accent_color(dark),
        }

        window_bg = bg if self._normal_window_mode else "transparent"
        self.setStyleSheet(f"""
            ChatWindow {{
                background: {window_bg};
            }}
        """)

        shell_radius = 0 if self._normal_window_mode else 14
        self._shell.set_panel_style(bg, border, shell_radius, 1)
        group_sidebar_visible = (
            self._group_sidebar is not None
            and not self._group_sidebar_collapsed
        )
        outer_radius = 0 if self._normal_window_mode else 14
        title_radius = (0, outer_radius, 0, 0) if group_sidebar_visible else (outer_radius, outer_radius, 0, 0)
        input_radius = (0, 0, outer_radius, 0) if group_sidebar_visible else (0, 0, outer_radius, outer_radius)
        self._titlebar.set_panel_style(title_bg, title_border, title_radius, 0)
        self._titlebar.setStyleSheet(f"""
            QLabel#TitleAvatar {{
                background: {_TEAMS_ACCENT};
                color: #ffffff;
                border-radius: 17px;
                font-weight: 700;
            }}
            QLabel#ChatSubtitle {{
                color: {muted};
                font-size: 11px;
            }}
        """)

        if self._group_splitter is not None:
            self._group_splitter.setStyleSheet(f"""
                QSplitter#GroupChatSplitter {{
                    background: transparent;
                    border: none;
                }}
            """)

        if self._group_sidebar is not None:
            sidebar_bg = "#151923" if dark else "#f8fafd"
            sidebar_border = "#242a37" if dark else "#e6ebf3"
            self._group_sidebar.set_panel_style(sidebar_bg, "transparent", (outer_radius, 0, 0, outer_radius), 0)
            self._group_sidebar.setStyleSheet(f"""
                QLabel#GroupSidebarTitle {{
                    color: {text_color};
                    background: transparent;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QLabel#GroupSidebarSubtitle {{
                    color: {muted};
                    background: transparent;
                    font-size: 11px;
                }}
                QLabel#GroupListEmpty {{
                    color: {muted};
                    background: transparent;
                    padding: 10px;
                }}
                QLabel#GroupListSection {{
                    color: {muted};
                    background: transparent;
                    font-size: 11px;
                    font-weight: 700;
                    padding: 8px 8px 3px 8px;
                }}
                QToolButton#NewChatPickerButton {{
                    background: {'#252c3a' if dark else '#ffffff'};
                    color: {text_color};
                    border: 1px solid {sidebar_border};
                    border-radius: 8px;
                    padding: 8px 12px;
                    font-weight: 700;
                    text-align: left;
                }}
                QToolButton#NewChatPickerButton:hover {{
                    background: {'#2a3244' if dark else '#f3f7ff'};
                }}
                QToolButton#NewChatPickerButton:pressed {{
                    background: {'#202838' if dark else '#e7eefb'};
                }}
                QFrame#GroupListSeparator {{
                    background: {sidebar_border};
                    border: none;
                    margin-left: 46px;
                    margin-right: 8px;
                }}
            """)
            self._group_list_scroll.setStyleSheet(f"""
                QScrollArea#GroupListScroll {{
                    background: {sidebar_bg};
                    border: none;
                }}
                QWidget#GroupList {{
                    background: {sidebar_bg};
                }}
                QScrollBar:vertical {{
                    background: {sidebar_bg};
                    width: 6px;
                }}
                QScrollBar::handle:vertical {{
                    background: {'#4c5569' if dark else '#c7d0e3'};
                    border-radius: 3px;
                    min-height: 30px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                }}
            """)
            for i in range(self._group_list_layout.count()):
                item = self._group_list_layout.itemAt(i)
                widget = item.widget() if item else None
                if isinstance(widget, GroupChatListRow):
                    widget.apply_theme()
            self._apply_group_list_indicator_theme()

        self._input.setStyleSheet(f"""
            QTextEdit {{
                background: transparent;
                color: {text_color};
                border: none;
                padding: 9px 4px 5px 4px;
                font-size: 13px;
                selection-background-color: {_TEAMS_ACCENT};
            }}
            QTextEdit:disabled {{
                color: {muted};
            }}
        """)
        self._attachment_scroll.setStyleSheet("""
            QScrollArea#ComposerAttachmentScroll,
            QWidget#ComposerAttachmentStrip {
                background: transparent;
                border: none;
            }
        """)

        self._input_area.set_panel_style(composer_bg, title_border, input_radius, 0)
        self._update_composer_focus_style()

        self._composer_hint.setStyleSheet(f"color: {muted}; background: transparent;")
        self._status_dot.setStyleSheet(f"background: {_TELEGRAM_ACCENT}; border-radius: 3px;")
        self._new_btn.apply_theme()
        self._close_btn.apply_theme()
        if self._topmost_btn is not None:
            self._topmost_btn.apply_theme()
            self._sync_chat_window_topmost_button()
        if self._group_toggle_btn is not None:
            self._group_toggle_btn.apply_theme()
        if self._group_sidebar_toggle_btn is not None:
            if hasattr(self._group_sidebar_toggle_btn, "apply_theme"):
                self._group_sidebar_toggle_btn.apply_theme()
        self._sync_group_sidebar_toggle_buttons()
        self._send_btn.apply_theme()
        self._attach_btn.apply_theme()
        self._refresh_attach_button_icon()
        self._asr_btn.apply_theme()
        for card in self._attachment_cards:
            card.apply_theme()
        self._update_asr_button_state()
        if self._resize_grip:
            self._resize_grip.update()
        self._update_title_avatar()

        self._scroll.setStyleSheet(f"""
            QScrollArea {{
                background: {scroll_bg};
                border: none;
            }}
            QWidget#MessageArea {{
                background: {scroll_bg};
            }}
            QScrollBar:vertical {{
                background: {scroll_bg};
                width: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: {'#4c5569' if dark else '#c7d0e3'};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)
        self._scroll.viewport().setStyleSheet(f"background: {scroll_bg};")

        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        self.setPalette(pal)

        for bubble in self._message_bubbles():
            bubble.apply_theme()

    def _message_bubbles(self):
        bubbles = []
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            widget = item.widget() if item else None
            if isinstance(widget, MessageBubble):
                bubbles.append(widget)
        return bubbles

    def _relayout_message_bubbles(self, force: bool = False):
        if self._group_sidebar_animating and not force:
            return
        viewport_width = self._scroll.viewport().width()
        bubbles = self._message_bubbles()
        if (
            not force
            and viewport_width == self._last_message_layout_width
            and len(bubbles) == self._last_message_layout_count
        ):
            return
        self._last_message_layout_width = viewport_width
        self._last_message_layout_count = len(bubbles)
        for bubble in bubbles:
            bubble.update_bubble_width(viewport_width)

    def _clear_message_widgets(self):
        self._reset_tts_stream()
        self._cancel_pending_scroll_to_bottom()
        self._history_load_generation += 1
        self._history_prepend_generation += 1
        self._history_oldest_message_id = None
        self._history_has_more = False
        self._history_loading = False
        self._history_pagination_ready = False
        self._last_message_layout_width = -1
        self._last_message_layout_count = -1
        if self._msg_layout.count() > 0:
            self._msg_layout.takeAt(self._msg_layout.count() - 1)
        for i in range(self._msg_layout.count() - 1, -1, -1):
            item = self._msg_layout.takeAt(i)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
        self._msg_layout.addStretch()

    def _history_scroll_style(self, bg: str, dark: bool) -> str:
        handle = "#566074" if dark else "#c4cfe3"
        handle_hover = "#69758d" if dark else "#aebbd4"
        return f"""
            QScrollArea#ConversationHistoryScroll {{
                background: {bg};
                border: none;
            }}
            QScrollArea#ConversationHistoryScroll > QWidget > QWidget {{
                background: {bg};
            }}
            QWidget#ConversationHistoryList {{
                background: {bg};
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar:vertical {{
                background: {bg};
                width: 8px;
                margin: 4px 0px 4px 0px;
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::handle:vertical {{
                background: {handle};
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::add-line:vertical,
            QScrollArea#ConversationHistoryScroll QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollArea#ConversationHistoryScroll QScrollBar::add-page:vertical,
            QScrollArea#ConversationHistoryScroll QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """

    def _fit_history_menu_widgets(self, menu: QMenu, rows: list[ConversationHistoryRow], scrolls: list[QScrollArea]):
        if not rows and not scrolls:
            return
        menu.adjustSize()
        content_width = max(_HISTORY_ROW_WIDTH, menu.sizeHint().width() - 40)
        for row in rows:
            row.set_row_width(content_width)
        for scroll in scrolls:
            scroll.setFixedWidth(content_width + 20)
        menu.adjustSize()

    def _conversation_title(self, conv: dict) -> str:
        preview = self._db.get_first_user_message_content(conv["id"]).replace("\n", " ")
        if not preview:
            preview = conv.get("title") or _tr("ChatWindow.empty_conv")
        if len(preview) > 28:
            preview = preview[:28] + "..."
        created_at = conv.get("last_message_at") or conv.get("created_at", "")
        time_text = created_at[5:16] if len(created_at) >= 16 else created_at
        return f"{time_text}  {preview}".strip()

    def _on_title_avatar_released(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        event.accept()
        if getattr(self, "_suppress_next_title_avatar_release", False):
            self._suppress_next_title_avatar_release = False
            return
        self._title_avatar_click_timer.start(220)

    def _on_title_avatar_double_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        event.accept()
        if hasattr(self, "_title_avatar_click_timer"):
            self._title_avatar_click_timer.stop()
        self._suppress_next_title_avatar_release = True
        QTimer.singleShot(350, lambda: setattr(self, "_suppress_next_title_avatar_release", False))
        target = self._title_avatar_character()
        if target:
            self._send_poke_to_character(target)

    def _show_conversation_history(self):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        menu = QMenu(self)
        _prepare_rounded_menu(menu)
        menu.setObjectName("ConversationHistoryMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT
        border = "#303849" if dark else "#d8deea"
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#9aa5bd" if dark else "#657089"
        menu_style = f"""
            QMenu#ConversationHistoryMenu {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 8px;
                font-size: 13px;
            }}
            QMenu#ConversationHistoryMenu::item {{
                padding: 9px 12px 9px 12px;
                border-radius: 8px;
                min-width: {_HISTORY_ROW_WIDTH}px;
            }}
            QMenu#ConversationHistoryMenu::item:selected {{
                background: {hover};
            }}
            QMenu#ConversationHistoryMenu::separator {{
                height: 1px;
                background: {border};
                margin: 8px 4px;
            }}
            QMenu#ConversationHistoryMenu::item:disabled {{
                color: {muted};
            }}
        """
        menu.setStyleSheet(menu_style)
        history_rows: list[ConversationHistoryRow] = []
        history_scrolls: list[QScrollArea] = []

        if self._is_group_chat:
            conversations = self._db.get_group_conversations(self._conversation_key, self._chat_user_key)
            title = Action(FluentIcon.HISTORY, _tr("ChatWindow.history_title"), menu)
            menu.addAction(title)
            title.setEnabled(False)
            if conversations:
                history_parent = menu
                history_layout = None
                if len(conversations) > 8:
                    history_parent = QWidget(menu)
                    history_parent.setObjectName("ConversationHistoryList")
                    history_layout = QVBoxLayout(history_parent)
                    history_layout.setContentsMargins(4, 4, 8, 4)
                    history_layout.setSpacing(4)
                for conv in conversations:
                    row = ConversationHistoryRow(
                        conv["conversation_id"],
                        self._group_preview(conv),
                        conv["conversation_id"] == self._group_conv_id,
                        history_parent,
                    )
                    row.selected.connect(lambda conv_id: self._select_group_history_row(menu, conv_id))
                    row.delete_requested.connect(lambda conv_id: self._delete_group_history_row(menu, conv_id))
                    history_rows.append(row)
                    if history_layout is not None:
                        history_layout.addWidget(row)
                    else:
                        action = QWidgetAction(menu)
                        action.setDefaultWidget(row)
                        menu.addAction(action)
                if history_layout is not None:
                    scroll = QScrollArea(menu)
                    scroll.setObjectName("ConversationHistoryScroll")
                    scroll.setWidgetResizable(True)
                    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
                    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                    scroll.setFixedSize(_HISTORY_SCROLL_WIDTH, 8 * (_HISTORY_ROW_HEIGHT + 4) + 8)
                    scroll.setWidget(history_parent)
                    scroll.viewport().setAutoFillBackground(False)
                    scroll.setStyleSheet(self._history_scroll_style(bg, dark))
                    history_scrolls.append(scroll)
                    scroll_action = QWidgetAction(menu)
                    scroll_action.setDefaultWidget(scroll)
                    menu.addAction(scroll_action)
            else:
                empty = menu.addAction(_tr("ChatWindow.no_convs"))
                empty.setEnabled(False)
            menu.addSeparator()

            change_menu = QMenu(_tr("ChatWindow.avatar_change_menu"), menu)
            _prepare_rounded_menu(change_menu)
            change_menu.setObjectName("ConversationHistoryMenu")
            change_menu.setIcon(FluentIcon.PHOTO.icon())
            change_menu.setStyleSheet(menu_style)
            menu.addMenu(change_menu)
            reset_menu = QMenu(_tr("ChatWindow.avatar_reset_menu"), menu)
            _prepare_rounded_menu(reset_menu)
            reset_menu.setObjectName("ConversationHistoryMenu")
            reset_menu.setIcon(FluentIcon.RETURN.icon())
            reset_menu.setStyleSheet(menu_style)
            menu.addMenu(reset_menu)
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                change_action = change_menu.addAction(display)
                change_action.triggered.connect(lambda _checked=False, c=character: self._set_character_avatar(c))
                reset_action = reset_menu.addAction(display)
                reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
                reset_action.triggered.connect(lambda _checked=False, c=character: self._reset_character_avatar(c))
            pos = self._title_avatar.mapToGlobal(self._title_avatar.rect().bottomLeft())
            self._pending_history_menu_action = None
            self._fit_history_menu_widgets(menu, history_rows, history_scrolls)
            menu.exec(pos)
            self._run_pending_history_menu_action()
            return
        else:
            change_action = Action(FluentIcon.PHOTO, _tr("ChatWindow.avatar_change"), menu)
            menu.addAction(change_action)
            change_action.triggered.connect(lambda: self._set_character_avatar(self._character))
            reset_action = Action(FluentIcon.RETURN, _tr("ChatWindow.avatar_reset"), menu)
            menu.addAction(reset_action)
            reset_action.setEnabled(bool(self._chat_avatar_paths.get(self._character)))
            reset_action.triggered.connect(lambda: self._reset_character_avatar(self._character))
        menu.addSeparator()

        title = Action(FluentIcon.HISTORY, _tr("ChatWindow.history_title"), menu)
        menu.addAction(title)
        title.setEnabled(False)
        menu.addSeparator()

        conversations = self._db.get_conversations(self._conversation_key, self._chat_user_key)
        if not conversations:
            empty = menu.addAction(_tr("ChatWindow.no_convs"))
            empty.setEnabled(False)
        elif len(conversations) > 10:
            container = QWidget(menu)
            container.setObjectName("ConversationHistoryList")
            layout = QVBoxLayout(container)
            layout.setContentsMargins(4, 4, 8, 4)
            layout.setSpacing(4)
            for conv in conversations:
                row = ConversationHistoryRow(
                    conv["id"],
                    self._conversation_title(conv),
                    conv["id"] == self._conv_id,
                    container,
                )
                row.selected.connect(lambda conv_id: self._select_history_row(menu, conv_id))
                row.delete_requested.connect(lambda conv_id: self._delete_history_row(menu, conv_id))
                history_rows.append(row)
                layout.addWidget(row)

            scroll = QScrollArea(menu)
            scroll.setObjectName("ConversationHistoryScroll")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFixedSize(_HISTORY_SCROLL_WIDTH, 8 * (_HISTORY_ROW_HEIGHT + 4) + 8)
            scroll.setWidget(container)
            scroll.viewport().setAutoFillBackground(False)
            scroll.setStyleSheet(self._history_scroll_style(bg, dark))
            history_scrolls.append(scroll)
            scroll_action = QWidgetAction(menu)
            scroll_action.setDefaultWidget(scroll)
            menu.addAction(scroll_action)
        else:
            for conv in conversations:
                row = ConversationHistoryRow(
                    conv["id"],
                    self._conversation_title(conv),
                    conv["id"] == self._conv_id,
                    menu,
                )
                row.selected.connect(lambda conv_id: self._select_history_row(menu, conv_id))
                row.delete_requested.connect(lambda conv_id: self._delete_history_row(menu, conv_id))
                history_rows.append(row)
                action = QWidgetAction(menu)
                action.setDefaultWidget(row)
                menu.addAction(action)

        menu.addSeparator()
        new_action = Action(FluentIcon.ADD, _tr("ChatWindow.new_conversation"), menu)
        menu.addAction(new_action)
        new_action.triggered.connect(self._new_conversation)

        pos = self._title_avatar.mapToGlobal(self._title_avatar.rect().bottomLeft())
        self._pending_history_menu_action = None
        self._fit_history_menu_widgets(menu, history_rows, history_scrolls)
        menu.exec(pos)
        self._run_pending_history_menu_action()

    def _select_history_row(self, menu: QMenu, conv_id: int):
        self._pending_history_menu_action = ("switch", conv_id)
        QTimer.singleShot(0, menu.close)

    def _select_group_history_row(self, menu: QMenu, conversation_id: str):
        self._pending_history_menu_action = ("switch_group", conversation_id)
        QTimer.singleShot(0, menu.close)

    def _delete_group_history_row(self, menu: QMenu, conversation_id: str):
        self._pending_history_menu_action = ("delete_group", conversation_id)
        QTimer.singleShot(0, menu.close)

    def _delete_history_row(self, menu: QMenu, conv_id: int):
        self._pending_history_menu_action = ("delete", conv_id)
        QTimer.singleShot(0, menu.close)

    def _run_pending_history_menu_action(self):
        action = self._pending_history_menu_action
        self._pending_history_menu_action = None
        if not action:
            return
        name, value = action
        if name == "switch":
            QTimer.singleShot(0, lambda value=value: self._switch_conversation(value))
        elif name == "delete":
            QTimer.singleShot(0, lambda value=value: self._delete_conversation(value))
        elif name == "switch_group":
            QTimer.singleShot(0, lambda value=value: self._switch_group_conversation(value))
        elif name == "delete_group":
            QTimer.singleShot(0, lambda value=value: self._delete_group_conversation(value))

    def _switch_group_chat(self, characters: list[str]):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        normalized = self._normalize_group_characters(characters)
        if not normalized:
            return
        self._switch_chat_members(normalized)

    def _reset_chat_switch_state(self):
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._auto_active = False
        self._auto_round = 0
        self._last_user_message_id = None
        self._last_group_user_message_id = None

    def _sync_chat_mode_chrome(self):
        self._apply_chat_window_minimum_size(ensure_visible_size=True)
        if self._group_toggle_btn is not None:
            self._group_toggle_btn.setVisible(True)
        if self._group_sidebar is not None:
            self._group_sidebar.setVisible(not self._group_sidebar_collapsed)
        if self._group_splitter is not None:
            self._schedule_group_sidebar_ratio_apply()
        self._sync_group_sidebar_toggle_buttons()
        self._apply_theme()

    def _switch_chat_members(self, characters: list[str]):
        normalized = self._normalize_group_characters(characters)
        if not normalized:
            return
        next_is_group = len(normalized) > 1
        next_key = self._conversation_key_for(normalized)
        if next_key == self._conversation_key and next_is_group == self._is_group_chat:
            return

        self._memory_generation += 1
        self._reset_chat_switch_state()
        self._set_available_group_characters(normalized)
        self._is_group_chat = next_is_group
        if next_is_group:
            self._group_characters = normalized
            if self._character not in normalized:
                self._character = normalized[0]
        else:
            self._character = normalized[0]
            self._group_characters = []
        self._active_response_character = self._character
        self._pending_action_character = self._character
        self._conversation_key = next_key
        self._display_name = self._chat_display_name()
        self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
        self._title_label.setText(self._display_name)
        self._update_title_avatar()
        self._sync_chat_mode_chrome()
        self._clear_message_widgets()
        self._conv_id = None
        self._group_conv_id = ""
        self._load_or_create_conversation()
        if not self._sync_group_list_current_state():
            self._refresh_group_list()
        self._input.setFocus()

    def _switch_group_conversation(self, conversation_id: str):
        if conversation_id == self._group_conv_id:
            return
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._auto_active = False
        self._auto_round = 0
        self._group_conv_id = conversation_id
        self._clear_message_widgets()
        self._load_messages()
        self._input.setFocus()

    def _show_group_chat_context_menu(self, characters: list[str], global_pos):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        characters = self._normalize_group_characters(characters)
        if not characters:
            return
        group_key = self._conversation_key_for(characters)
        menu = QMenu(self)
        _prepare_rounded_menu(menu, 8)
        menu.setObjectName("GroupChatContextMenu")
        dark = isDarkTheme()
        bg = "#1b1f29" if dark else "#ffffff"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT
        border = "#303849" if dark else "#d8deea"
        text = "#f7f7fb" if dark else "#1f2328"
        menu.setStyleSheet(f"""
            QMenu#GroupChatContextMenu {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu#GroupChatContextMenu::item {{
                padding: 9px 28px 9px 12px;
                border-radius: 6px;
                min-width: 168px;
            }}
            QMenu#GroupChatContextMenu::item:selected {{
                background: {hover};
            }}
        """)
        if len(characters) == 1:
            character = characters[0]
            rename_action = Action(
                FluentIcon.EDIT,
                _tr("ChatWindow.rename_private", default="修改聊天名称"),
                menu,
            )
            rename_action.triggered.connect(lambda: self._rename_private_chat(character))
            menu.addAction(rename_action)

            change_action = Action(FluentIcon.PHOTO, _tr("ChatWindow.avatar_change"), menu)
            change_action.triggered.connect(lambda: self._set_character_avatar(character))
            menu.addAction(change_action)

            reset_action = Action(FluentIcon.RETURN, _tr("ChatWindow.avatar_reset"), menu)
            reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
            reset_action.triggered.connect(lambda: self._reset_character_avatar(character))
            menu.addAction(reset_action)
        else:
            rename_action = Action(FluentIcon.EDIT, _tr("ChatWindow.rename_group"), menu)
            rename_action.triggered.connect(lambda: self._rename_group_chat(characters))
            menu.addAction(rename_action)

            change_menu = QMenu(_tr("ChatWindow.avatar_change_menu"), menu)
            change_menu.setIcon(FluentIcon.PHOTO.icon())
            reset_menu = QMenu(_tr("ChatWindow.avatar_reset_menu"), menu)
            reset_menu.setIcon(FluentIcon.RETURN.icon())
            for character in characters:
                display = self._model_manager.get_display_name(character)
                change_action = change_menu.addAction(display)
                change_action.triggered.connect(lambda checked=False, c=character: self._set_character_avatar(c))
                reset_action = reset_menu.addAction(display)
                reset_action.setEnabled(bool(self._chat_avatar_paths.get(character)))
                reset_action.triggered.connect(lambda checked=False, c=character: self._reset_character_avatar(c))
            menu.addMenu(change_menu)
            menu.addMenu(reset_menu)

        pinned = self._is_chat_pinned(group_key)
        pin_action = menu.addAction(
            _tr("ChatWindow.unpin_chat", default="取消置顶")
            if pinned
            else _tr("ChatWindow.pin_chat", default="置顶聊天")
        )
        pin_action.triggered.connect(lambda: self._set_chat_pinned(group_key, not pinned))
        delete_action = Action(FluentIcon.DELETE, _tr("ChatWindow.delete_chat", default="删除聊天"), menu)
        delete_action.triggered.connect(lambda: self._delete_chat_entry(characters))
        menu.addSeparator()
        menu.addAction(delete_action)
        menu.exec(global_pos)

    def _rename_private_chat(self, character: str):
        default_name = self._model_manager.get_display_name(character)
        current_name = str(self._chat_display_names.get(character, "") or "").strip() or default_name
        dialog = GroupRenameDialog(
            current_name,
            self,
            title=_tr("ChatWindow.rename_private_title", default="修改聊天名称"),
            label=_tr("ChatWindow.rename_private_label", default="输入新的聊天显示名称，留空恢复角色默认名称："),
        )
        if not dialog.exec():
            return
        new_name = dialog.group_name()
        if new_name and new_name != default_name:
            self._chat_display_names[character] = new_name
        else:
            self._chat_display_names.pop(character, None)
        self._save_chat_display_names()
        if not self._is_group_chat and character == self._character:
            self._display_name = self._chat_display_name()
            self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
            self._title_label.setText(self._display_name)
            self._update_title_avatar()
        self._refresh_group_list()

    def _rename_group_chat(self, characters: list[str]):
        group_key = self._conversation_key_for(characters)
        default_name = self._group_default_display_name(characters)
        current_name = self._db.get_group_display_name(group_key).strip() or default_name
        dialog = GroupRenameDialog(current_name, self)
        if not dialog.exec():
            return
        new_name = dialog.group_name()
        self._db.set_group_display_name(group_key, new_name if new_name != default_name else "")
        if group_key == self._conversation_key:
            self._display_name = self._chat_display_name()
            self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
            self._title_label.setText(self._display_name)
            self._update_title_avatar()
        self._refresh_group_list()

    def _delete_chat_entry(self, characters: list[str]):
        characters = self._normalize_group_characters(characters)
        if not characters:
            return
        chat_key = self._conversation_key_for(characters)
        if len(characters) <= 1:
            character = characters[0]
            was_current = not self._is_group_chat and character == self._character
            for conv in self._db.get_conversations(character, self._chat_user_key):
                self._db.delete_conversation(conv["id"])
            self._chat_display_names.pop(character, None)
            self._save_chat_display_names()
            if was_current:
                self._stream_flush_timer.stop()
                self._stream_buffer = ""
                self._visible_stream_text = ""
                self._reasoning_stream_text = ""
                self._current_bubble = None
                self._clear_message_widgets()
                self._conv_id = None
                self._display_name = self._chat_display_name()
                self.setWindowTitle(_tr("ChatWindow.title", name=self._display_name))
                self._title_label.setText(self._display_name)
        else:
            was_current = self._is_group_chat and chat_key == self._conversation_key
            for conv in self._db.get_group_conversations(chat_key, self._chat_user_key):
                self._db.delete_group_conversation(chat_key, conv["conversation_id"], self._chat_user_key)
            self._db.set_group_display_name(chat_key, "")
            if was_current:
                self._stream_flush_timer.stop()
                self._stream_buffer = ""
                self._visible_stream_text = ""
                self._reasoning_stream_text = ""
                self._current_bubble = None
                self._group_queue = []
                self._group_spoken = []
                self._auto_active = False
                self._auto_round = 0
                self._clear_message_widgets()
                self._group_conv_id = ""

        self._set_chat_pinned(chat_key, False)
        self._refresh_avatar_views()
        self._input.setFocus()

    def _switch_conversation(self, conv_id: int):
        if conv_id == self._conv_id:
            return
        if self._worker and self._worker.isRunning():
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._conv_id = conv_id
        self._clear_message_widgets()
        self._load_messages()
        self._input.setFocus()

    def _delete_conversation(self, conv_id: int):
        if self._worker and self._worker.isRunning():
            return
        was_current = conv_id == self._conv_id
        self._db.delete_conversation(conv_id)
        self._refresh_group_list()

        if not was_current:
            return

        conversations = self._db.get_conversations(self._conversation_key, self._chat_user_key)
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._clear_message_widgets()
        if conversations:
            self._conv_id = conversations[0]["id"]
            self._load_messages()
        else:
            self._conv_id = None
        self._input.setFocus()

    def _delete_group_conversation(self, conversation_id: str):
        if (self._worker and self._worker.isRunning()) or (self._group_plan_worker and self._group_plan_worker.isRunning()):
            return
        was_current = conversation_id == self._group_conv_id
        self._db.delete_group_conversation(self._conversation_key, conversation_id, self._chat_user_key)
        self._refresh_group_list()

        if not was_current:
            return

        conversations = self._db.get_group_conversations(self._conversation_key, self._chat_user_key)
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._group_queue = []
        self._group_spoken = []
        self._auto_active = False
        self._auto_round = 0
        self._clear_message_widgets()
        self._group_conv_id = conversations[0]["conversation_id"] if conversations else ""
        if self._group_conv_id:
            self._load_messages()
        self._input.setFocus()

    def _has_llm_config(self) -> bool:
        return bool(
            self._cfg
            and self._cfg.get("llm_api_url", "").strip()
            and self._cfg.get("llm_api_key", "").strip()
            and self._cfg.get("llm_model_id", "").strip()
        )

    def _idle_status_text(self) -> str:
        return _tr("ChatWindow.ready") if self._has_llm_config() else _tr("ChatWindow.not_configured")

    def _set_busy(self, busy: bool, planning: bool = False):
        self._input.setEnabled(True)
        self._send_btn.setEnabled(not self._attachment_import_active())
        if hasattr(self._send_btn, "set_busy"):
            self._send_btn.set_busy(busy)
        self._update_asr_button_state()
        self._new_btn.setEnabled(not busy)
        if planning:
            status = _tr("ChatWindow.planning_group_response")
        elif busy:
            status = _tr("ChatWindow.streaming_response_with_stop", default="正在回复，输入 @stop 或 @停止 可中断")
        else:
            status = self._idle_status_text()
        self._composer_hint.setText(status)
        dot = _TEAMS_ACCENT if busy else _TELEGRAM_ACCENT
        self._status_dot.setStyleSheet(f"background: {dot}; border-radius: 3px;")

    def _asr_enabled(self) -> bool:
        return bool(_ASR_AVAILABLE and self._cfg and self._cfg.get("asr_enabled", False))

    def _update_asr_button_state(self):
        button = getattr(self, "_asr_btn", None)
        if button is None:
            return
        enabled = self._asr_enabled()
        button.setEnabled(enabled and not self._asr_transcribing)
        if not _ASR_AVAILABLE:
            button.setToolTip(_tr("ChatWindow.asr_unavailable_tooltip", default="当前环境缺少语音输入依赖"))
        elif not enabled:
            button.setToolTip(_tr("ChatWindow.asr_disabled_tooltip", default="请先在设置中启用 ASR 语音输入"))
        elif self._asr_recording:
            button.setToolTip(_tr("ChatWindow.asr_stop_tooltip", default="停止录音并识别"))
        elif self._asr_transcribing:
            button.setToolTip(_tr("ChatWindow.asr_transcribing_tooltip", default="正在识别语音"))
        else:
            button.setToolTip(_tr("ChatWindow.asr_start_tooltip", default="开始语音输入"))

    def _toggle_asr_recording(self):
        if self._asr_recording:
            self._stop_asr_recording()
            return
        self._start_asr_recording()

    def _start_asr_recording(self):
        if not self._asr_enabled() or ASRRecorderWorker is None:
            self._composer_hint.setText(_tr("ChatWindow.asr_not_enabled", default="请先在设置中启用 ASR 语音输入。"))
            self._update_asr_button_state()
            return
        if self._asr_transcribing:
            return
        self._reload_runtime_config()
        self._asr_last_error = ""
        self._asr_recording = True
        self._composer_hint.setText(_tr("ChatWindow.asr_recording", default="正在录音，再次点击麦克风结束识别。"))
        self._status_dot.setStyleSheet("background: #ef4444; border-radius: 3px;")
        if self._asr_btn is not None:
            self._asr_btn.setStyleSheet("""
                QToolButton {
                    background: #ef4444;
                    color: #ffffff;
                    border: none;
                    border-radius: 23px;
                    padding: 0px;
                }
                QToolButton:hover { background: #dc2626; }
                QToolButton:pressed { background: #b91c1c; }
            """)
        self._asr_recorder_worker = ASRRecorderWorker(asr_config_snapshot(self._cfg), self)
        self._asr_recorder_worker.audio_ready.connect(self._on_asr_audio_ready)
        self._asr_recorder_worker.error.connect(self._on_asr_error)
        self._asr_recorder_worker.finished.connect(self._on_asr_recording_finished)
        self._asr_recorder_worker.start()
        self._update_asr_button_state()

    def _stop_asr_recording(self):
        worker = self._asr_recorder_worker
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        self._composer_hint.setText(_tr("ChatWindow.asr_stopping", default="正在整理录音..."))
        self._update_asr_button_state()

    def _on_asr_recording_finished(self):
        self._asr_recording = False
        self._asr_recorder_worker = None
        if not self._asr_transcribing and not self._asr_last_error:
            self._composer_hint.setText(self._idle_status_text())
            self._status_dot.setStyleSheet(f"background: {_TELEGRAM_ACCENT}; border-radius: 3px;")
        if self._asr_btn is not None:
            self._asr_btn.apply_theme()
        self._update_asr_button_state()

    def _on_asr_audio_ready(self, audio: bytes, media_type: str):
        if not self._asr_enabled() or ASRRequestWorker is None:
            return
        self._asr_transcribing = True
        self._composer_hint.setText(_tr("ChatWindow.asr_transcribing", default="正在识别语音..."))
        self._asr_request_worker = ASRRequestWorker(audio, media_type, asr_config_snapshot(self._cfg), self)
        self._asr_request_worker.text_ready.connect(self._on_asr_text_ready)
        self._asr_request_worker.error.connect(self._on_asr_error)
        self._asr_request_worker.finished.connect(self._on_asr_request_finished)
        self._asr_request_worker.start()
        self._update_asr_button_state()

    def _on_asr_text_ready(self, text: str):
        text = str(text or "").strip()
        if not text:
            return
        mode = str(self._cfg.get("asr_insert_mode", "append") if self._cfg else "append")
        if mode == "replace":
            self._input.setPlainText(text)
        else:
            current = self._input.toPlainText().strip()
            self._input.setPlainText(f"{current}\n{text}" if current else text)
        cursor = self._input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._input.setTextCursor(cursor)
        self._input.setFocus()
        self._sync_input_height()
        self._composer_hint.setText(_tr("ChatWindow.asr_inserted", default="已填入语音识别文本。"))
        if self._cfg and bool(self._cfg.get("asr_auto_send", False)):
            QTimer.singleShot(0, self._send_message)

    def _on_asr_request_finished(self):
        self._asr_transcribing = False
        self._asr_request_worker = None
        had_error = bool(self._asr_last_error)
        if not had_error and not self._generation_busy():
            self._composer_hint.setText(self._idle_status_text())
        if had_error:
            self._asr_last_error = ""
        self._update_asr_button_state()

    def _on_asr_error(self, msg: str):
        self._asr_recording = False
        self._asr_transcribing = False
        self._asr_last_error = msg or _tr("ChatWindow.asr_failed", default="语音识别失败。")
        if self._asr_btn is not None:
            self._asr_btn.apply_theme()
        self._composer_hint.setText(self._asr_last_error)
        self._status_dot.setStyleSheet(f"background: {_TELEGRAM_ACCENT}; border-radius: 3px;")
        self._update_asr_button_state()

    def _update_composer_focus_style(self):
        if not self._composer_colors:
            return
        focused = self._input.hasFocus()
        dragging = self._composer_drag_active
        active = focused or dragging
        border = self._composer_colors["focus_border"] if active else self._composer_colors["border"]
        target_width = 3.0 if dragging else 2.0 if focused else 1.0
        current_width = getattr(self, '_composer_border_width', 1.0)
        if abs(current_width - target_width) < 0.01:
            self._composer_border_width = target_width
            self._composer.set_panel_style(self._composer_colors["bg"], border, 22, int(target_width))
            return
        self._composer_border_width = target_width
        if hasattr(self, '_composer_focus_anim'):
            self._composer_focus_anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.setStartValue(float(current_width))
        anim.setEndValue(float(target_width))
        anim.valueChanged.connect(lambda v: self._composer.set_panel_style(
            self._composer_colors["bg"],
            self._composer_colors["focus_border"] if active else self._composer_colors["border"],
            22,
            int(round(v))
        ))
        self._composer_focus_anim = anim
        anim.start()

    def _on_composer_text_changed(self):
        if self._completer_suppress:
            return
        text = self._input.toPlainText()
        cursor = self._input.textCursor()
        pos = cursor.position()

        prefix = self._extract_command_prefix(text, pos)
        if prefix is not None:
            self._command_completer.filter(prefix)
        else:
            self._command_completer.hide()

    @staticmethod
    def _extract_command_prefix(text: str, pos: int):
        before = text[:pos]
        last_space = before.rfind(" ")
        last_newline = before.rfind("\n")
        start = max(last_space, last_newline) + 1
        word = before[start:pos]
        if word.startswith("@") or word.startswith("/"):
            return word
        return None

    def _on_command_selected(self, command: str):
        text = self._input.toPlainText()
        cursor = self._input.textCursor()
        pos = cursor.position()

        prefix = self._extract_command_prefix(text, pos)
        if prefix is None:
            return

        self._completer_suppress = True
        try:
            start_idx = pos - len(prefix)
            cursor.setPosition(start_idx, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(command + " ")
            self._input.setTextCursor(cursor)
        finally:
            self._completer_suppress = False

    def _sync_input_height(self):
        doc_height = int(self._input.document().size().height()) + 10
        input_height = max(42, min(86, doc_height))
        attachment_height = 70 if self._pending_attachments else 0
        composer_height = max(66, input_height + 20 + attachment_height)
        area_height = composer_height + 44
        self._input.setFixedHeight(input_height)
        self._composer.setFixedHeight(composer_height)
        self._input_area.setFixedHeight(area_height)
        scrollbar_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if doc_height > 86 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._input.setVerticalScrollBarPolicy(scrollbar_policy)

    def _load_or_create_conversation(self):
        if self._is_group_chat:
            conversations = self._db.get_group_conversations(self._conversation_key, self._chat_user_key)
            self._group_conv_id = conversations[0]["conversation_id"] if conversations else ""
            self._load_messages()
            return
        last = self._db.get_last_conversation(self._conversation_key, self._chat_user_key)
        if last:
            self._conv_id = last["id"]
        self._load_messages()

    def _new_conversation(self):
        if self._worker and self._worker.isRunning():
            return
        if self._is_group_chat:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = ""
            self._reasoning_stream_text = ""
            self._current_bubble = None
            self._clear_message_widgets()
            self._group_conv_id = self._new_group_conversation_id()
            self._refresh_group_list()
            self._input.setFocus()
            return
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_bubble = None
        self._clear_message_widgets()
        self._conv_id = None

    def _load_messages(self):
        self._history_load_generation += 1
        load_generation = self._history_load_generation
        self._history_loading = True
        self._history_pagination_ready = False
        page_limit = _MESSAGE_HISTORY_PAGE_SIZE + 1
        if self._is_group_chat:
            if not self._group_conv_id:
                self._history_loading = False
                return
            messages = self._db.get_group_messages(
                self._conversation_key,
                self._group_conv_id,
                limit=page_limit,
                user_key=self._chat_user_key,
            )
        elif self._conv_id is None:
            self._history_loading = False
            return
        else:
            messages = self._db.get_messages(self._conv_id, limit=page_limit)
        self._history_has_more = len(messages) > _MESSAGE_HISTORY_PAGE_SIZE
        if self._history_has_more:
            messages = messages[-_MESSAGE_HISTORY_PAGE_SIZE:]
        self._history_oldest_message_id = int(messages[0]["id"]) if messages else None
        self._msg_layout.takeAt(self._msg_layout.count() - 1)
        for m in messages:
            self._msg_layout.addWidget(self._message_bubble_from_record(m))
        self._msg_layout.addStretch()
        self._history_loading = False
        self._relayout_message_bubbles()
        self._schedule_visible_message_relayout()
        self._schedule_scroll_to_bottom_after_load()
        QTimer.singleShot(
            250,
            lambda generation=load_generation: self._enable_history_pagination(generation),
        )

    def _message_bubble_from_record(self, message: dict) -> MessageBubble:
        role = message["role"]
        author = (
            self._user_name
            if role == "user" and self._user_name
            else _tr("ChatWindow.you")
            if role == "user"
            else self._message_author(message["content"])
        )
        avatar = self._user_avatar_color if role == "user" else ""
        avatar_path = self._user_avatar_path if role == "user" else ""
        avatar_data = b""
        avatar_focus = "center"
        message_character = self._message_character(message["content"], role)
        if role == "assistant":
            avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(message_character)
        bubble = MessageBubble(
            self._message_content(message["content"], role),
            role,
            author,
            message.get("created_at", ""),
            avatar_color=avatar,
            avatar_path=avatar_path,
            avatar_data=avatar_data,
            avatar_focus=avatar_focus,
            reasoning=message.get("reasoning_content", ""),
            show_reasoning=self._show_reasoning,
            search_sources=self._message_search_sources(message.get("tool_trace_json")),
            attachments=self._normalize_attachments(message.get("attachments_json")) if role == "user" else None,
            avatar_character=message_character,
        )
        self._connect_message_bubble(bubble)
        return bubble

    def _enable_history_pagination(self, generation: int):
        if generation != self._history_load_generation:
            return
        self._history_pagination_ready = True

    def _load_older_messages(self) -> bool:
        if (
            not self._history_pagination_ready
            or self._history_loading
            or not self._history_has_more
            or self._history_oldest_message_id is None
        ):
            return False

        self._cancel_pending_scroll_to_bottom()
        self._history_loading = True
        before_id = self._history_oldest_message_id
        page_limit = _MESSAGE_HISTORY_PAGE_SIZE + 1
        if self._is_group_chat:
            messages = self._db.get_group_messages(
                self._conversation_key,
                self._group_conv_id,
                limit=page_limit,
                user_key=self._chat_user_key,
                before_id=before_id,
            )
        else:
            messages = self._db.get_messages(
                self._conv_id,
                limit=page_limit,
                before_id=before_id,
            )

        self._history_has_more = len(messages) > _MESSAGE_HISTORY_PAGE_SIZE
        if self._history_has_more:
            messages = messages[-_MESSAGE_HISTORY_PAGE_SIZE:]
        if not messages:
            self._history_loading = False
            return False

        scrollbar = self._scroll.verticalScrollBar()
        old_value = scrollbar.value()
        old_maximum = scrollbar.maximum()
        for index, message in enumerate(messages):
            self._msg_layout.insertWidget(index, self._message_bubble_from_record(message))
        self._history_oldest_message_id = int(messages[0]["id"])
        self._last_message_layout_width = -1
        self._last_message_layout_count = -1
        self._history_prepend_generation += 1
        generation = self._history_prepend_generation
        for delay in (0, 30, 80, 160, 300, 500):
            QTimer.singleShot(
                delay,
                lambda generation=generation, value=old_value, maximum=old_maximum:
                    self._restore_scroll_after_history_prepend(generation, value, maximum),
            )
        QTimer.singleShot(
            700,
            lambda generation=generation, value=old_value, maximum=old_maximum:
                self._finish_history_prepend(generation, value, maximum),
        )
        return True

    def _restore_scroll_after_history_prepend(
        self,
        generation: int,
        old_value: int,
        old_maximum: int,
    ):
        if generation != self._history_prepend_generation:
            return
        if self._msg_area.layout():
            self._msg_area.layout().activate()
        self._relayout_message_bubbles(force=True)
        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.setValue(old_value + max(0, scrollbar.maximum() - old_maximum))

    def _finish_history_prepend(
        self,
        generation: int,
        old_value: int,
        old_maximum: int,
    ):
        if generation != self._history_prepend_generation:
            return
        self._restore_scroll_after_history_prepend(generation, old_value, old_maximum)
        self._history_loading = False

    def _message_author(self, content: str) -> str:
        if self._is_group_chat:
            first_line = content.splitlines()[0].strip() if content else ""
            if first_line.startswith("【") and "】" in first_line:
                return first_line[1:first_line.index("】")]
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                if content.startswith(f"【{display}】"):
                    return display
        return self._display_name

    def _message_content(self, content: str, role: str) -> str:
        if role == "assistant" and self._is_group_chat:
            character = self._message_character(content, role)
            lines = content.splitlines()
            first_line = lines[0].strip() if lines else ""
            if first_line.startswith("【") and "】" in first_line:
                return self._sanitize_group_assistant_reply(character, "\n".join(lines[1:]).lstrip())
            for character in self._group_characters:
                display = self._model_manager.get_display_name(character)
                prefix = f"【{display}】"
                if content.startswith(prefix):
                    return self._sanitize_group_assistant_reply(character, content[len(prefix):].lstrip())
        return content

    def _sanitize_group_assistant_reply(self, character: str, text: str) -> str:
        if not self._is_group_chat or not text:
            return text
        names = {
            self._model_manager.get_display_name(item): item
            for item in self._group_characters
        }
        if not names:
            return text.strip()
        name_pattern = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        label_re = re.compile(
            rf"(?m)^[ \t]*(?:【(?P<fw>{name_pattern})】|\[(?P<sq>{name_pattern})\]|(?P<plain>{name_pattern})\s*[：:])\s*"
        )
        matches = list(label_re.finditer(text))
        if not matches:
            return text.strip()

        active_name = self._model_manager.get_display_name(character)
        active_segments = []
        for index, match in enumerate(matches):
            speaker = match.group("fw") or match.group("sq") or match.group("plain") or ""
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            segment = text[start:end].strip()
            if speaker == active_name and segment:
                active_segments.append(segment)
        if active_segments:
            return "\n\n".join(active_segments).strip()

        # If the model ignored the requested speaker entirely, at least remove
        # transcript labels so the UI does not display a false nested speaker.
        return label_re.sub("", text).strip()

    def _is_poke_user_stage_direction(self, stage_text: str, character: str) -> bool:
        text = re.sub(r"\s+", "", str(stage_text or ""))
        if "戳了戳" not in text:
            return False
        user_targets = {"你", "用户", "主人", "user"}
        user_name = (self._user_name or "").strip()
        if user_name:
            user_targets.add(user_name)
        user_targets.add(_tr("ChatWindow.you"))

        target_pattern = "|".join(re.escape(item) for item in sorted(user_targets, key=len, reverse=True) if item)
        if not target_pattern:
            return False
        if re.search(rf"(?:我|咱|人家|本小姐|本大爷|本姑娘)?戳了戳(?:{target_pattern})", text, re.IGNORECASE):
            return True
        if re.search(rf"戳了戳(?:{target_pattern})", text, re.IGNORECASE):
            return True

        active_name = self._model_manager.get_display_name(character) if character else ""
        if user_name and text.startswith("你戳了戳") and user_name in text and (not active_name or active_name not in text):
            return True
        return False

    def _consume_poke_user_stage_directions(self, text: str, character: str) -> tuple[str, bool]:
        source = str(text or "")
        triggered = False

        def replace(match):
            nonlocal triggered
            inner = match.group("inner").strip()
            if not self._is_poke_user_stage_direction(inner, character):
                return match.group(0)
            triggered = True
            return ""

        cleaned = re.sub(
            r"(?P<open>[（(【\[])(?P<inner>[^（）()\[\]【】]{0,64}戳了戳[^（）()\[\]【】]{0,64})(?P<close>[）)】\]])",
            replace,
            source,
        )
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned, triggered

    def _assistant_content(self, character: str, text: str) -> str:
        if not self._is_group_chat:
            return text
        text = self._sanitize_group_assistant_reply(character, text)
        return f"【{self._model_manager.get_display_name(character)}】\n{text}"

    def _memory_target_characters(self) -> list[str]:
        return list(self._group_characters) if self._is_group_chat else [self._character]

    def _show_local_assistant_message(self, text: str):
        avatar_character = self._character
        avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(avatar_character)
        bubble = MessageBubble(
            text,
            "assistant",
            self._display_name,
            avatar_path=avatar_path,
            avatar_data=avatar_data,
            avatar_focus=avatar_focus,
            show_reasoning=self._show_reasoning,
            avatar_character=avatar_character,
        )
        self._connect_message_bubble(bubble)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom()

    def _connect_message_bubble(self, bubble: MessageBubble):
        bubble.avatar_double_clicked.connect(self._on_message_avatar_double_clicked)

    def _on_message_avatar_double_clicked(self, character: str):
        target = str(character or "").strip() or self._character
        if self._is_group_chat and target not in self._group_characters:
            return
        self._send_poke_to_character(target)

    def _send_poke_to_character(self, character: str):
        if self._generation_busy():
            self._composer_hint.setText(_tr("ChatWindow.poke_busy_hint", default="当前回复还在进行中，等她说完再戳一下吧。"))
            return
        self._reload_runtime_config()
        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        model_id = self._cfg.get("llm_model_id", "")
        if not api_url or not api_key or not model_id:
            self._composer_hint.setText(_tr("ChatWindow.not_configured"))
            return

        display = self._model_manager.get_display_name(character)
        text = _tr("ChatWindow.poke_message", default="（你戳了戳 {name}）", name=display)
        self._pending_interaction_context = _tr(
            "ChatWindow.poke_context",
            default=(
                "用户刚刚双击聊天头像戳了戳 {name}。请 {name} 以角色口吻做出短而自然的反应，"
                "可以惊讶、害羞、吐槽或回戳，不要复读系统事件。"
            ),
            name=display,
        )
        self._set_busy(True, planning=False)
        self._follow_stream_output = True
        self._reset_tts_stream()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        try:
            publish_user_poke(character, source="chat")
        except Exception:
            pass

        user_bubble = MessageBubble(
            text,
            "user",
            self._user_name or _tr("ChatWindow.you"),
            avatar_color=self._user_avatar_color,
            avatar_path=self._user_avatar_path,
            show_reasoning=self._show_reasoning,
        )
        self._connect_message_bubble(user_bubble)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, user_bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom_for_stream()

        if self._is_group_chat:
            self._last_group_user_message_id = self._db.add_group_message(
                self._conversation_key,
                self._ensure_group_conversation_id(),
                "user",
                text,
                user_key=self._chat_user_key,
            )
            self._last_user_message_id = None
            self._last_user_text = text
            self._refresh_group_list()
            self._group_spoken = []
            self._start_group_plan(text, priority_character=character)
            return

        if self._conv_id is None:
            self._conv_id = self._db.create_conversation(self._conversation_key, user_key=self._chat_user_key)
        self._last_user_message_id = self._db.add_message(self._conv_id, "user", text)
        self._last_group_user_message_id = None
        self._last_user_text = text
        self._refresh_group_list()
        self._start_response_for_character(character, [])

    @staticmethod
    def _is_interrupt_command(text: str) -> bool:
        return text.strip().lower() in INTERRUPT_COMMANDS

    def _generation_busy(self) -> bool:
        return bool(
            (self._worker is not None and self._worker.isRunning())
            or (self._group_plan_worker is not None and self._group_plan_worker.isRunning())
            or (self._vision_fallback_worker is not None and self._vision_fallback_worker.isRunning())
            or self._group_queue
        )

    def _interrupt_generation(self, clear_input: bool = True):
        interrupted = False
        worker = self._worker
        if worker is not None:
            try:
                worker.cancel()
            except Exception:
                worker.requestInterruption()
            self._park_cancelled_worker(worker)
            interrupted = True
        self._worker = None

        planner = self._group_plan_worker
        if planner is not None:
            planner.requestInterruption()
            planner.quit()
            self._park_cancelled_worker(planner)
            interrupted = True
        self._group_plan_worker = None
        self._group_queue = []
        self._auto_active = False
        self._auto_round = 0

        vision_worker = self._vision_fallback_worker
        if vision_worker is not None:
            vision_worker.requestInterruption()
            vision_worker.quit()
            self._park_cancelled_worker(vision_worker)
            interrupted = True
        self._vision_fallback_worker = None
        self._pending_vision_send = None
        self._hide_plan_divider()
        self._clear_raw_image_inline_state()

        self._stream_flush_timer.stop()
        current_text = (self._visible_stream_text + self._stream_buffer).strip()
        self._stream_buffer = ""
        self._visible_stream_text = current_text
        self._current_response_actions = []
        self._action_tag_stream_buffer = ""
        if self._current_bubble:
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(current_text or _tr("ChatWindow.response_interrupted", default="已中断当前回复。"))
        elif interrupted:
            self._composer_hint.setText(_tr("ChatWindow.response_interrupted", default="已中断当前回复。"))
        self._current_bubble = None
        self._reset_tts_stream()
        self._set_busy(False)
        if clear_input:
            self._input.clear()
        self._input.setFocus()

    def _relationship_status_text(self, sections: tuple[str, ...] | None = None) -> str:
        user_key = self._user_memory_key()
        parts = [
            format_character_status(
                self._db,
                character,
                user_key,
                self._model_manager.get_display_name(character),
                sections=sections,
            )
            for character in self._memory_target_characters()
        ]
        return "\n\n".join(parts)

    def _remember_manual_text(self, text: str):
        content = text.strip()
        if not content:
            self._show_local_assistant_message(_tr("ChatWindow.memory_remember_hint", "要记住什么？可以输入 @记住 你的内容。"))
            return
        user_key = self._user_memory_key()
        for character in self._memory_target_characters():
            self._db.add_character_memory(
                character,
                user_key,
                "manual",
                "用户希望我记住：" + content,
                95,
            )
            self._db.apply_relationship_delta(
                character,
                user_key,
                trust_delta=1,
                familiarity_delta=1,
                mood="soft",
                mood_intensity=42,
                event_type="manual_memory",
                reason="用户手动添加长期记忆",
            )
        self._show_local_assistant_message(_tr("ChatWindow.memory_remembered", "已记住：{content}", content=content))

    @staticmethod
    def _looks_like_favorite_request(text: str) -> bool:
        stripped = str(text or "").strip()
        if not stripped:
            return False
        return bool(
            re.search(
                r"(加入回忆相册|放进回忆相册|存到回忆相册|"
                r"(收藏|保存|记下).*(这句|这句话|这条|这段话|这段|刚才|上一句|上一条|回忆相册)|"
                r"收藏\s*[：:、“\"『「])",
                stripped,
            )
        )

    @staticmethod
    def _quoted_favorite_phrase(text: str) -> str:
        candidates = []
        for pattern in (r"[“\"『「](.+?)[”\"』」]", r"['‘](.+?)['’]"):
            candidates.extend(match.strip() for match in re.findall(pattern, text, flags=re.DOTALL))
        candidates = [item for item in candidates if item]
        if candidates:
            return max(candidates, key=len)[:500].strip()
        match = re.search(r"(?:收藏|加入回忆相册|放进回忆相册|存到回忆相册|保存)[^：:，,。.!！?？]{0,12}[：:]\s*(.+)$", text, re.DOTALL)
        if match:
            phrase = match.group(1).strip()
            if phrase and not re.search(r"^(这句|这句话|刚才|上一句|这段话)\b", phrase):
                return phrase[:500].strip()
        return ""

    def _last_assistant_message_for_favorite(self) -> dict | None:
        if self._is_group_chat:
            if not self._group_conv_id:
                return None
            messages = self._db.get_group_messages(
                self._conversation_key,
                self._group_conv_id,
                limit=16,
                user_key=self._chat_user_key,
            )
        elif self._conv_id:
            messages = self._db.get_messages(self._conv_id, limit=16)
        else:
            return None
        for message in reversed(messages):
            if message.get("role") == "assistant" and str(message.get("content", "") or "").strip():
                return message
        return None

    def _favorite_request_target(self, text: str) -> tuple[str, dict | None, str]:
        if not self._looks_like_favorite_request(text):
            return "", None, ""
        explicit = self._quoted_favorite_phrase(text)
        if explicit:
            return explicit, None, ""
        source_message = self._last_assistant_message_for_favorite()
        if not source_message:
            return "", None, ""
        phrase = self._message_content(source_message.get("content", ""), "assistant").strip()
        phrase = re.sub(r"\s+", " ", strip_action_tags(phrase)).strip()
        if len(phrase) > 500:
            phrase = phrase[:500].rstrip() + "..."
        source_character = ""
        if self._is_group_chat:
            source_character = self._message_character(source_message.get("content", ""), "assistant")
        return phrase, source_message, source_character

    def _store_requested_favorite(
        self,
        phrase: str,
        source_message: dict | None,
        source_character: str,
        user_message_id: int | None,
        group_user_message_id: int | None,
    ):
        phrase = str(phrase or "").strip()
        if not phrase:
            return
        user_key = self._user_memory_key()
        if self._is_group_chat and source_character:
            targets = [source_character]
        else:
            targets = self._memory_target_characters()
        source_message_id = None
        source_group_message_id = None
        if source_message:
            if source_message.get("source") == "group" or "group_key" in source_message:
                source_group_message_id = source_message.get("id")
            else:
                source_message_id = source_message.get("id")
        elif self._is_group_chat:
            source_group_message_id = group_user_message_id
        else:
            source_message_id = user_message_id

        saved = 0
        for character in targets:
            if not character:
                continue
            if self._db.add_character_memory(
                character,
                user_key,
                "favorite",
                "收藏语句：" + phrase,
                98,
                source_message_id=source_message_id,
                source_group_message_id=source_group_message_id,
            ):
                saved += 1
            self._db.apply_relationship_delta(
                character,
                user_key,
                trust_delta=1,
                familiarity_delta=1,
                mood="soft",
                mood_intensity=45,
                event_type="favorite_quote",
                reason="用户收藏了一句话作为回忆相册依据",
            )
        if saved:
            self._composer_hint.setText(_tr("ChatWindow.favorite_saved_hint", default="已收藏到回忆相册。"))

    def _forget_memory_text(self, text: str):
        query = text.strip()
        if not query:
            self._show_local_assistant_message(_tr("ChatWindow.memory_forget_hint", "要忘记哪条记忆？可以输入 @忘记 关键词。"))
            return
        user_key = self._user_memory_key()
        total = 0
        for character in self._memory_target_characters():
            total += self._db.delete_character_memories_like(character, user_key, query)
        self._show_local_assistant_message(_tr("ChatWindow.memory_forget_result", "已删除 {count} 条包含\u201c{query}\u201d的长期记忆。", count=total, query=query))

    def _set_relationship_value_text(self, field: str, text: str):
        text = text.strip()
        if not text:
            self._show_local_assistant_message(_tr("ChatWindow.set_value_hint", "请输入数值。例如：@好感度 80"))
            return
        user_key = self._user_memory_key()
        if field == "mood":
            try:
                value = int(text)
            except ValueError:
                self._show_local_assistant_message(_tr("ChatWindow.set_mood_hint", "请输入 0-100 的心情数值。例如：@当前心情 75（数值越高心情越好）"))
                return
            value = max(0, min(100, value))
            from relationship_memory import mood_from_intensity, MOOD_LABELS
            mood_key = mood_from_intensity(value)
            label = MOOD_LABELS[mood_key]
            for character in self._memory_target_characters():
                self._db.upsert_relationship_state(character, user_key, mood=mood_key, mood_intensity=value)
            self._show_local_assistant_message(
                _tr("ChatWindow.mood_set", "已设置当前心情为：{mood}（{label}，数值 {value}/100）",
                    mood=mood_key, label=label, value=value))
            return
        try:
            value = int(text)
        except ValueError:
            self._show_local_assistant_message(_tr("ChatWindow.set_value_not_number", "请输入 0-100 的数字。"))
            return
        value = max(0, min(100, value))
        field_cn = {"affection": "好感度", "trust": "信任", "familiarity": "熟悉度"}[field]
        for character in self._memory_target_characters():
            self._db.upsert_relationship_state(character, user_key, **{field: value})
        self._show_local_assistant_message(
            _tr("ChatWindow.relationship_set", "{field} 已设置为：{value}/100", field=field_cn, value=value))

    def _current_chat_members(self) -> list[str]:
        return list(self._group_characters) if self._is_group_chat else [self._character]

    def _handle_local_memory_command(self, text: str) -> bool:
        stripped = text.strip()
        lowered = stripped.lower()
        command_result = _handle_chat_command(
            self._cfg,
            stripped,
            name_resolver=self._model_manager.get_display_name,
            token_usage_resolver=self._current_token_usage_stats,
        ) if self._cfg else None
        if command_result is not None:
            self._input.clear()
            if command_result.get("show_reasoning") is not None:
                self._show_reasoning = bool(command_result["show_reasoning"])
            self._show_local_assistant_message(command_result["message"])
            return True
        if lowered in {"@memory", "/memory", "@记忆", "/记忆"}:
            self._input.clear()
            self._show_local_assistant_message(self._relationship_status_text(("global", "memories")))
            return True
        if lowered in {"@status", "/status", "@状态", "/状态"}:
            self._input.clear()
            self._show_local_assistant_message(self._relationship_status_text(("state",)))
            return True
        for prefix in ("@remember ", "/remember ", "@记住 ", "/记住 "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._remember_manual_text(stripped[len(prefix):])
                return True
        for prefix in ("@forget ", "/forget ", "@忘记 ", "/忘记 "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._forget_memory_text(stripped[len(prefix):])
                return True
        for prefix in ("@好感度 ", "/好感度 ", "@affection ", "/affection "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("affection", stripped[len(prefix):])
                return True
        for prefix in ("@信任 ", "/信任 ", "@trust ", "/trust "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("trust", stripped[len(prefix):])
                return True
        for prefix in ("@熟悉度 ", "/熟悉度 ", "@familiarity ", "/familiarity "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("familiarity", stripped[len(prefix):])
                return True
        for prefix in ("@当前心情 ", "/当前心情 ", "@setmood ", "/setmood "):
            if stripped.startswith(prefix):
                self._input.clear()
                self._set_relationship_value_text("mood", stripped[len(prefix):])
                return True
        return False

    def _apply_relationship_update(self, character: str, user_text: str, assistant_text: str, actions: list[str]):
        if not user_text.strip() or not character:
            return
        user_key = self._user_memory_key()
        fallback_analysis = analyze_interaction(user_text, assistant_text, actions)
        if self._start_memory_extraction(
            character,
            user_key,
            user_text,
            assistant_text,
            self._last_user_message_id,
            self._last_group_user_message_id,
            fallback_analysis,
        ):
            return
        self._apply_relationship_analysis(character, user_key, fallback_analysis, "chat")

    def _apply_relationship_analysis(self, character: str, user_key: str, analysis: dict, event_type: str):
        self._db.apply_relationship_delta(
            character,
            user_key,
            affection_delta=analysis["affection_delta"],
            trust_delta=analysis["trust_delta"],
            familiarity_delta=analysis["familiarity_delta"],
            mood=analysis["mood"],
            mood_intensity=analysis["mood_intensity"],
            event_type=event_type,
            reason=analysis["reason"],
        )

    def _start_memory_extraction(
        self,
        character: str,
        user_key: str,
        user_text: str,
        assistant_text: str,
        source_message_id: int | None,
        source_group_message_id: int | None,
        fallback_analysis: dict,
    ) -> bool:
        api_url, api_key, model_id = memory_extraction_api_config(
            self._cfg,
            self._use_responses_api,
            self._chat_completions_api_url,
        )
        if not api_url or not api_key or not model_id:
            return False
        existing = self._db.get_character_memories(character, user_key, limit=12)
        global_existing = self._db.get_character_memories(GLOBAL_MEMORY_CHARACTER, user_key, limit=12)
        messages = build_memory_extraction_messages(
            user_text,
            assistant_text,
            existing,
            global_memories=global_existing,
            character_name=self._model_manager.get_display_name(character),
        )
        worker = NonStreamWorker(api_url, api_key, model_id, messages, None)
        generation = self._memory_generation
        self._memory_workers.append(worker)
        worker.finished.connect(
            lambda content, _reasoning, _actions, worker=worker, character=character, user_key=user_key,
            source_message_id=source_message_id, source_group_message_id=source_group_message_id,
            fallback_analysis=fallback_analysis, generation=generation:
                self._on_memory_extraction_finished(
                    worker,
                    character,
                    user_key,
                    content,
                    source_message_id,
                    source_group_message_id,
                    fallback_analysis,
                    generation,
                )
        )
        worker.error.connect(
            lambda _error, worker=worker, character=character, user_key=user_key, fallback_analysis=fallback_analysis,
            generation=generation:
                self._on_memory_extraction_error(worker, character, user_key, fallback_analysis, generation)
        )
        worker.start()
        return True

    def _on_memory_extraction_finished(
        self,
        worker: NonStreamWorker,
        character: str,
        user_key: str,
        content: str,
        source_message_id: int | None,
        source_group_message_id: int | None,
        fallback_analysis: dict,
        generation: int,
    ):
        self._forget_memory_worker(worker)
        if generation != self._memory_generation:
            return
        relationship_analysis = parse_relationship_analysis_response(content) or fallback_analysis
        self._apply_relationship_analysis(
            character,
            user_key,
            relationship_analysis,
            "chat_model",
        )
        store_extracted_memories(
            self._db,
            character,
            user_key,
            content,
            source_message_id=source_message_id,
            source_group_message_id=source_group_message_id,
        )

    def _forget_memory_worker(self, worker: NonStreamWorker):
        self._memory_workers = [item for item in self._memory_workers if item is not worker]

    def _on_memory_extraction_error(
        self,
        worker: NonStreamWorker,
        character: str,
        user_key: str,
        fallback_analysis: dict,
        generation: int,
    ):
        self._forget_memory_worker(worker)
        if generation != self._memory_generation:
            return
        self._apply_relationship_analysis(character, user_key, fallback_analysis, "chat")

    def _group_system_prompt(self, character: str, spoken_names: list[str]) -> str:
        prompt = build_system_prompt(character, self._cfg)
        names = [self._model_manager.get_display_name(c) for c in self._group_characters]
        prompt += "\n\n【群聊规则】\n这是一个多人群聊。当前群聊成员：" + "、".join(names) + "。"
        prompt += (
            "\n你只扮演自己，不要代替其他角色说话。"
            "\n本轮只有你一个角色发言；其他角色如果需要回应，程序会在后续轮次单独生成。"
            "\n你的输出必须是一条仅属于你自己的单人回复，不要写成多人连续对话、对手戏脚本或旁白串场。"
            "\n严禁输出其他角色的直接台词，严禁替其他角色回答，严禁在同一条回复里模拟别人接话。"
            "\n如果需要提到其他成员的反应，只能用你自己的视角转述，不能写出对方的原话。"
            "\n回复时不要添加任何角色名前缀或剧本标签，例如【角色名】、[角色名]、角色名：，程序会自动添加。"
        )
        return prompt

    def _chat_attachment_dir(self) -> Path:
        path = app_base_dir() / "chat_attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _choose_chat_attachments(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            _tr("ChatWindow.attach_file_title", default="选择附件"),
            "",
            _tr("ChatWindow.attach_file_filter", default="All files (*)"),
        )
        if not paths:
            return
        self._add_chat_files(paths)

    def _chat_file_paths_from_mime(self, mime_data) -> list[str]:
        if not mime_data or not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            path = url.toLocalFile() if url.isLocalFile() or url.scheme().lower() == "file" else ""
            if not path:
                continue
            source = Path(urllib.parse.unquote(path))
            if source.exists() and source.is_file():
                resolved = str(source)
                if resolved not in paths:
                    paths.append(resolved)
        return paths

    def _remote_image_urls_from_mime(self, mime_data) -> list[str]:
        if not mime_data:
            return []
        urls = []
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    continue
                text = url.toString().strip()
                if self._is_http_url(text):
                    urls.append(text)
        html = mime_data.html() if mime_data.hasHtml() else ""
        if html:
            for match in re.finditer(r"""<img[^>]+src=["']([^"']+)["']""", html, flags=re.IGNORECASE):
                text = match.group(1).strip()
                if self._is_http_url(text):
                    urls.append(text)
        if mime_data.hasText():
            for line in mime_data.text().splitlines():
                text = line.strip()
                if self._looks_like_remote_image_url(text):
                    urls.append(text)
        unique = []
        for url in urls:
            if url not in unique:
                unique.append(url)
        return unique

    @staticmethod
    def _is_http_url(url: str) -> bool:
        return str(url or "").strip().lower().startswith(("http://", "https://"))

    @staticmethod
    def _looks_like_remote_image_url(url: str) -> bool:
        text = str(url or "").strip()
        if not ChatWindow._is_http_url(text):
            return False
        parsed = urllib.parse.urlparse(text)
        suffix = Path(urllib.parse.unquote(parsed.path)).suffix.lower()
        return suffix in _CHAT_IMAGE_EXTENSIONS

    @staticmethod
    def _suffix_for_image_content_type(content_type: str) -> str:
        normalized = str(content_type or "").split(";", 1)[0].strip().lower()
        return {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }.get(normalized, ".png")

    def _mime_has_chat_attachments(self, mime_data) -> bool:
        if not mime_data:
            return False
        if mime_data.hasImage():
            return True
        return bool(self._chat_file_paths_from_mime(mime_data) or self._remote_image_urls_from_mime(mime_data))

    def _set_composer_drag_active(self, active: bool):
        if self._composer_drag_active == active:
            return
        self._composer_drag_active = active
        self._update_composer_focus_style()

    def _handle_composer_drag_event(self, event) -> bool:
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if self._mime_has_chat_attachments(event.mimeData()):
                self._set_composer_drag_active(True)
                event.acceptProposedAction()
                return True
            self._set_composer_drag_active(False)
            event.ignore()
            return True
        if event_type == QEvent.Type.DragLeave:
            self._set_composer_drag_active(False)
            event.accept()
            return True
        if event_type == QEvent.Type.Drop:
            mime_data = event.mimeData()
            self._set_composer_drag_active(False)
            supported = self._mime_has_chat_attachments(mime_data)
            added = self._add_chat_attachments_from_mime(mime_data)
            if added:
                event.acceptProposedAction()
            elif not supported:
                self._composer_hint.setText(_tr("ChatWindow.attach_drop_unsupported", default="不支持拖放此类型的文件"))
                event.accept()
            else:
                event.acceptProposedAction()
            return True
        return False

    def _add_chat_attachments_from_mime(self, mime_data) -> int:
        added = 0
        paths = self._chat_file_paths_from_mime(mime_data)
        if paths:
            added += self._add_chat_files(paths)
        elif mime_data and mime_data.hasImage():
            # Explorer and Finder can expose both a file URL and decoded image data.
            # Prefer the original file so PNG metadata/name is preserved and it is not added twice.
            added += self._add_mime_image_attachment(mime_data)
        remote_urls = self._remote_image_urls_from_mime(mime_data)
        if remote_urls:
            added += self._add_remote_chat_images(remote_urls)
        return added

    def _add_mime_image_attachment(self, mime_data) -> int:
        if not mime_data or not mime_data.hasImage():
            return 0
        image = mime_data.imageData()
        if isinstance(image, QPixmap):
            image = image.toImage()
        if not isinstance(image, QImage) or image.isNull():
            return 0
        target_dir = self._chat_attachment_dir()
        target = target_dir / f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}.png"
        if not image.save(str(target), "PNG"):
            return 0
        self._pending_attachments.append({
            "type": "image",
            "path": str(target),
            "name": _tr("ChatWindow.dropped_image_name", default="拖放图片.png"),
            "mime": "image/png",
            "size": target.stat().st_size if target.exists() else 0,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        })
        self._refresh_attachment_previews()
        self._update_attachment_hint()
        self._input.setFocus()
        return 1

    def _add_remote_chat_images(self, urls: list[str]) -> int:
        jobs = [{"kind": "remote", "url": url} for url in urls if self._is_http_url(url)]
        return self._enqueue_attachment_import(jobs)

    def _add_chat_files(self, paths: list[str]) -> int:
        jobs = []
        for path in paths:
            source = Path(path)
            if not source.exists() or not source.is_file():
                continue
            try:
                size = source.stat().st_size
            except OSError:
                continue
            if size > _CHAT_ATTACHMENT_MAX_BYTES:
                self._composer_hint.setText(
                    _tr("ChatWindow.attach_too_large", default="附件过大，无法添加：{name}", name=source.name)
                )
                continue
            jobs.append({"kind": "local", "path": str(source), "size": size})
        return self._enqueue_attachment_import(jobs)

    def _attachment_import_active(self) -> bool:
        return bool(
            (self._attachment_import_worker is not None and self._attachment_import_worker.isRunning())
            or self._attachment_import_queue
        )

    def _enqueue_attachment_import(self, jobs: list[dict]) -> int:
        jobs = [dict(job) for job in jobs if isinstance(job, dict)]
        if not jobs:
            return 0
        self._attachment_import_queue.append(jobs)
        self._attachment_import_last_error = ""
        self._start_next_attachment_import()
        return len(jobs)

    def _start_next_attachment_import(self):
        if self._attachment_import_worker is not None and self._attachment_import_worker.isRunning():
            return
        if not self._attachment_import_queue:
            self._finish_attachment_import_ui()
            return
        jobs = self._attachment_import_queue.pop(0)
        worker = AttachmentImportWorker(jobs, self._chat_attachment_dir(), self)
        self._attachment_import_worker = worker
        worker.progress.connect(self._on_attachment_import_progress)
        worker.item_ready.connect(self._on_attachment_import_item_ready)
        worker.failed.connect(self._on_attachment_import_failed)
        worker.finished.connect(self._on_attachment_import_finished)
        self._attachment_progress.setRange(0, 100)
        self._attachment_progress.setValue(0)
        self._attachment_progress.show()
        self._attachment_progress_label.setText("0%")
        self._attachment_progress_label.show()
        self._send_btn.setEnabled(False)
        self._composer_hint.setText(
            _tr("ChatWindow.attachment_uploading", default="正在上传附件...")
        )
        worker.start()

    def _on_attachment_import_progress(self, percent: int, copied: int, total: int, name: str):
        if self.sender() is not self._attachment_import_worker:
            return
        if percent < 0:
            self._attachment_progress.setRange(0, 0)
            self._attachment_progress_label.setText(self._format_attachment_size(copied))
        else:
            if self._attachment_progress.maximum() == 0:
                self._attachment_progress.setRange(0, 100)
            percent = max(0, min(100, percent))
            self._attachment_progress.setValue(percent)
            self._attachment_progress_label.setText(f"{percent}%")
        self._composer_hint.setText(
            _tr(
                "ChatWindow.attachment_uploading_named",
                default="正在上传：{name}",
                name=name or _tr("ChatWindow.attach_file_tooltip", default="附件"),
            )
        )

    def _on_attachment_import_item_ready(self, item: dict):
        if self.sender() is not self._attachment_import_worker:
            return
        self._pending_attachments.append(dict(item))
        self._refresh_attachment_previews()

    def _on_attachment_import_failed(self, error: str):
        if self.sender() is not self._attachment_import_worker:
            return
        self._attachment_import_last_error = str(error or "")

    def _on_attachment_import_finished(self):
        worker = self.sender()
        if worker is not self._attachment_import_worker:
            return
        worker.deleteLater()
        self._attachment_import_worker = None
        if self._attachment_import_queue:
            self._start_next_attachment_import()
            return
        self._finish_attachment_import_ui()

    def _finish_attachment_import_ui(self):
        self._attachment_progress.setRange(0, 100)
        self._attachment_progress.setValue(100)
        self._attachment_progress_label.setText("100%")
        self._send_btn.setEnabled(True)
        if self._attachment_import_last_error:
            self._composer_hint.setText(
                _tr(
                    "ChatWindow.attach_failed_content",
                    default="无法添加附件：{error}",
                    error=self._attachment_import_last_error,
                )
            )
        else:
            self._update_attachment_hint()
            self._input.setFocus()
        QTimer.singleShot(500, self._hide_attachment_progress)

    def _hide_attachment_progress(self):
        if self._attachment_import_active():
            return
        self._attachment_progress.hide()
        self._attachment_progress_label.hide()

    def _update_attachment_hint(self):
        if self._attachment_import_active():
            return
        if self._pending_attachments:
            count = len(self._pending_attachments)
            self._composer_hint.setText(_tr("ChatWindow.attach_pending", default="已添加 {count} 个附件，发送时会一起交给模型。", count=count))
        else:
            self._composer_hint.setText(self._idle_status_text())

    def _refresh_attachment_previews(self):
        layout = getattr(self, "_attachment_strip_layout", None)
        scroll = getattr(self, "_attachment_scroll", None)
        if layout is None or scroll is None:
            return

        while layout.count() > 1:
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._attachment_cards = []
        for attachment in reversed(self._pending_attachments):
            card = ComposerAttachmentCard(attachment, self._attachment_strip)
            card.remove_requested.connect(self._remove_pending_attachment)
            self._attachment_cards.append(card)
            layout.insertWidget(layout.count() - 1, card, 0, Qt.AlignmentFlag.AlignLeft)

        scroll.setVisible(bool(self._attachment_cards))
        self._sync_input_height()
        QTimer.singleShot(0, lambda: scroll.horizontalScrollBar().setValue(
            scroll.horizontalScrollBar().minimum()
        ))

    def _remove_pending_attachment(self, path: str):
        removed = None
        for index, attachment in enumerate(self._pending_attachments):
            if str(attachment.get("path", "") or "") == str(path or ""):
                removed = self._pending_attachments.pop(index)
                break
        if removed is None:
            return

        self._delete_pending_attachment_copy(removed)
        self._refresh_attachment_previews()
        self._update_attachment_hint()
        self._input.setFocus()

    def _delete_pending_attachment_copy(self, attachment: dict):
        path_text = str(attachment.get("path", "") or "").strip()
        if not path_text:
            return
        path = Path(path_text)
        try:
            resolved = path.resolve()
            attachment_root = self._chat_attachment_dir().resolve()
            if resolved.parent == attachment_root and resolved.exists() and resolved.is_file():
                resolved.unlink()
        except (OSError, RuntimeError):
            pass

    def _message_search_sources(self, tool_trace) -> list[dict]:
        if not self._show_search_sources():
            return []
        if not tool_trace:
            return []
        if isinstance(tool_trace, str):
            try:
                tool_trace = json.loads(tool_trace)
            except (TypeError, ValueError):
                return []
        if not isinstance(tool_trace, dict):
            return []
        sources = tool_trace.get("web_search_sources", [])
        return MessageBubble._normalize_search_sources(sources)

    def _show_search_sources(self) -> bool:
        return bool(self._cfg.get("llm_web_search_show_sources", True)) if self._cfg else True

    def _merge_search_sources(self, sources: list[dict]):
        current = list(self._stream_search_sources)
        for source in MessageBubble._normalize_search_sources(sources):
            if all(item["url"] != source["url"] for item in current):
                current.append(source)
        self._stream_search_sources = current[:9]
        if self._current_bubble and self._show_search_sources():
            self._current_bubble.set_search_sources(self._stream_search_sources)

    def _extract_stream_search_sources(self, text: str) -> str:
        source = self._pending_source_json + text
        self._pending_source_json = ""
        cleaned, sources = extract_inline_search_sources(source)
        if sources:
            self._merge_search_sources(sources)
            return cleaned

        markers = (
            '{"web_search_sources"', '{"search_sources"', '{"sources"',
            '{ "web_search_sources"', '{ "search_sources"', '{ "sources"',
        )
        positions = [source.find(marker) for marker in markers if source.find(marker) >= 0]
        if positions:
            start = min(positions)
            self._pending_source_json = source[start:]
            return source[:start]
        return source

    def _normalize_attachments(self, attachments) -> list[dict]:
        if not attachments:
            return []
        if isinstance(attachments, str):
            try:
                attachments = json.loads(attachments)
            except (TypeError, ValueError):
                return []
        if not isinstance(attachments, list):
            return []
        result = []
        safe_root = self._chat_attachment_dir().resolve()
        for item in attachments:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type", "") or "").strip().lower()
            if item_type not in {"image", "file"}:
                continue
            path = str(item.get("path", ""))
            if not path:
                continue
            try:
                resolved = Path(path).resolve()
                resolved.relative_to(safe_root)
            except (OSError, RuntimeError, ValueError):
                continue
            if not resolved.exists() or not resolved.is_file():
                continue
            if item_type == "image" and resolved.suffix.lower() not in _CHAT_IMAGE_EXTENSIONS:
                continue
            normalized = dict(item, type=item_type, path=str(resolved))
            if "size" not in normalized:
                try:
                    normalized["size"] = resolved.stat().st_size
                except OSError:
                    pass
            result.append(normalized)
        return result

    def _image_data_url(self, attachment: dict) -> str:
        path = str(attachment.get("path", ""))
        if not path or not os.path.exists(path):
            return ""
        mime = attachment.get("mime") or mimetypes.guess_type(path)[0] or "image/png"
        try:
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
        except OSError:
            return ""
        return f"data:{mime};base64,{encoded}"

    @staticmethod
    def _format_attachment_size(size) -> str:
        try:
            value = int(size)
        except (TypeError, ValueError):
            return ""
        if value < 1024:
            return f"{value} B"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        return f"{value / (1024 * 1024):.1f} MB"

    @staticmethod
    def _is_text_attachment(path: str, mime: str) -> bool:
        suffix = Path(path).suffix.lower()
        mime = str(mime or "").split(";")[0].strip().lower()
        return (
            suffix in _CHAT_TEXT_ATTACHMENT_EXTENSIONS
            or any(mime.startswith(prefix) for prefix in _CHAT_TEXT_ATTACHMENT_MIME_PREFIXES)
            or mime in _CHAT_TEXT_ATTACHMENT_MIME_TYPES
        )

    def _file_attachment_note(self, attachment: dict) -> str:
        path = str(attachment.get("path", "") or "")
        name = str(attachment.get("name", "") or Path(path).name or "file")
        mime = str(attachment.get("mime", "") or mimetypes.guess_type(path)[0] or "application/octet-stream")
        size = attachment.get("size", "")
        size_text = self._format_attachment_size(size)
        header = [
            "【文件附件】",
            f"文件名：{name}",
            f"MIME：{mime}",
        ]
        if size_text:
            header.append(f"大小：{size_text}")
        if not path or not os.path.exists(path):
            return "\n".join(header + ["内容：文件已不可用。"])
        if not self._is_text_attachment(path, mime):
            return "\n".join(header + ["内容：该文件不是可直接内联的文本文件，已作为附件元信息提供。"])
        try:
            with open(path, "rb") as f:
                raw = f.read(_FILE_ATTACHMENT_INLINE_BYTES + 1)
        except OSError as exc:
            return "\n".join(header + [f"内容：读取失败：{exc}"])
        truncated = len(raw) > _FILE_ATTACHMENT_INLINE_BYTES
        raw = raw[:_FILE_ATTACHMENT_INLINE_BYTES]
        text = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")
        if len(text) > _FILE_ATTACHMENT_INLINE_CHARS:
            text = text[:_FILE_ATTACHMENT_INLINE_CHARS]
            truncated = True
        suffix = Path(path).suffix.lower().lstrip(".") or "text"
        note = "\n".join(header + [f"内容：\n```{suffix}\n{text}\n```"])
        if truncated:
            note += "\n（内容已截断）"
        return note

    def _chat_message_content(self, text: str, attachments=None, include_raw_images: bool = False):
        items = self._normalize_attachments(attachments)
        if not items:
            return text
        text = text or ""
        vision_notes = []
        for item in items:
            if item.get("type") != "image":
                continue
            summary = str(item.get("vision_summary", "") or "").strip()
            if summary:
                name = item.get("name") or Path(item.get("path", "")).name or "image"
                vision_notes.append(f"{name}：{summary}")
            else:
                error_note = str(item.get("vision_error", "") or "").strip()
                if error_note:
                    name = item.get("name") or Path(item.get("path", "")).name or "image"
                    vision_notes.append(f"{name}：{error_note}")
        if vision_notes:
            text += "\n\n【快速视觉模型观察】\n" + "\n".join(vision_notes)
        file_notes = [
            self._file_attachment_note(item)
            for item in items
            if item.get("type") == "file"
        ]
        if file_notes:
            text += "\n\n" + "\n\n".join(file_notes)
        parts = [{"type": "text", "text": text}]
        for item in items:
            if item.get("type") != "image":
                continue
            if not include_raw_images:
                continue
            if str(item.get("vision_summary", "") or "").strip() or str(item.get("vision_error", "") or "").strip():
                continue
            data_url = self._image_data_url(item)
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
        return parts if len(parts) > 1 else text

    def _attachments_have_raw_images(self, attachments) -> bool:
        return any(
            item.get("type") == "image"
            and not str(item.get("vision_summary", "") or "").strip()
            and not str(item.get("vision_error", "") or "").strip()
            for item in self._normalize_attachments(attachments)
        )

    def _clear_raw_image_inline_state(self):
        self._raw_image_inline_message_id = None
        self._raw_image_inline_group_message_id = None

    def _aux_vision_fallback_enabled(self) -> bool:
        if not self._cfg or not bool(self._cfg.get("llm_aux_vision_fallback_enabled", False)):
            return False
        aux_model_id = str(self._cfg.get("llm_aux_model_id", "") or "").strip()
        return bool(aux_model_id)

    def _attachments_need_aux_vision(self, attachments) -> bool:
        if not self._aux_vision_fallback_enabled():
            return False
        items = self._normalize_attachments(attachments)
        return any(
            item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
            for item in items
        )

    def _use_responses_api(self, api_url: str = "") -> bool:
        return use_responses_api(self._cfg, api_url)

    def _chat_completions_api_url(self, api_url: str) -> str:
        return chat_completions_api_url(api_url)

    def _reload_runtime_config(self):
        if self._cfg and hasattr(self._cfg, "load"):
            previous_user_key = getattr(self, "_chat_user_key", "")
            try:
                self._cfg.load()
            except Exception:
                pass
            self._user_name = self._cfg.get("user_name", "").strip()
            self._user_avatar_color = self._cfg.get("user_avatar_color", _TELEGRAM_ACCENT)
            self._user_avatar_path = str(self._cfg.get("user_avatar_path", "") or "").strip()
            self._show_reasoning = bool(self._cfg.get("llm_show_reasoning", True))
            self._update_asr_button_state()
            next_user_key = self._user_memory_key()
            if next_user_key != previous_user_key:
                self._chat_user_key = next_user_key
                self._conv_id = None
                self._group_conv_id = ""
                self._group_queue = []
                self._group_spoken = []
                self._auto_active = False
                self._auto_round = 0
                self._current_bubble = None
                self._clear_message_widgets()
                self._load_or_create_conversation()
                self._refresh_group_list()

    def _history_user_label(self) -> str:
        return self._user_name or _tr("ChatWindow.you")

    @staticmethod
    def _compact_history_text(content: str, attachments=None) -> str:
        text = str(content or "").strip()
        if isinstance(attachments, str) and attachments:
            try:
                attachments = json.loads(attachments)
            except (TypeError, ValueError):
                attachments = []
        if isinstance(attachments, list) and attachments:
            image_count = sum(1 for item in attachments if isinstance(item, dict) and item.get("type") == "image")
            file_count = sum(1 for item in attachments if isinstance(item, dict) and item.get("type") == "file")
            labels = []
            if image_count:
                labels.append(f"图片 {image_count} 张")
            if file_count:
                labels.append(f"文件 {file_count} 个")
            if labels:
                text = (text + "\n" if text else "") + "[" + "，".join(labels) + "]"
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 420:
            text = text[:420].rstrip() + "..."
        return text

    def _split_group_history_message(self, content: str) -> tuple[str, str]:
        text = str(content or "").strip()
        first_line = text.splitlines()[0].strip() if text else ""
        if first_line.startswith("【") and "】" in first_line:
            speaker = first_line[1:first_line.index("】")].strip()
            body = "\n".join(text.splitlines()[1:]).strip()
            return speaker or _tr("ChatWindow.ai", default="AI"), body
        for character in self._model_manager.characters:
            display = self._model_manager.get_display_name(character)
            for prefix in (f"【{display}】", f"{display}：", f"{display}:"):
                if text.startswith(prefix):
                    return display, text[len(prefix):].strip()
        return _tr("ChatWindow.ai", default="AI"), text

    def _append_unified_history_item(self, items: list[dict], seen: set[tuple[str, int]], source: str, message: dict, label: str, content: str):
        msg_id = message.get("id")
        if msg_id is None:
            return
        key = (source, int(msg_id))
        if key in seen:
            return
        text = self._compact_history_text(content, message.get("attachments_json"))
        if not text:
            return
        seen.add(key)
        items.append({
            "created_at": message.get("created_at", ""),
            "id": int(msg_id),
            "label": label,
            "content": text,
        })

    @staticmethod
    def _history_time_label(created_at: str) -> str:
        text = str(created_at or "").strip()
        if not text:
            return "未知时间"
        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return text

    def _unified_history_context(self, character: str, limit: int = 18) -> str:
        related = self._current_chat_members() if self._is_group_chat else [character]
        related = self._normalize_group_characters(related)
        if character and character not in related:
            related.append(character)

        items: list[dict] = []
        seen: set[tuple[str, int]] = set()
        user_label = self._history_user_label()

        for member in related:
            display = self._model_manager.get_display_name(member)
            for conv in self._db.get_conversations(member, self._chat_user_key)[:3]:
                for message in self._db.get_messages(conv["id"], limit=6):
                    if message["role"] == "assistant":
                        label = f"{display}/私聊"
                    elif message["role"] == "user":
                        label = f"{user_label}/{display}"
                    else:
                        continue
                    self._append_unified_history_item(items, seen, "private", message, label, message["content"])

        related_set = set(related)
        for chat in self._db.get_group_chats(self._chat_user_key)[:24]:
            group_key = chat.get("group_key", "")
            group_members = self._characters_for_group_key(group_key)
            if not group_members or not (related_set & set(group_members)):
                continue
            conversation_id = chat.get("conversation_id", "")
            for message in self._db.get_group_messages(group_key, conversation_id, limit=8, user_key=self._chat_user_key):
                if message["role"] == "assistant":
                    speaker, body = self._split_group_history_message(message["content"])
                    label = f"{speaker}/群聊"
                    content = body
                elif message["role"] == "user":
                    label = f"{user_label}/群聊"
                    content = message["content"]
                else:
                    continue
                self._append_unified_history_item(items, seen, "group", message, label, content)

        items.sort(key=lambda item: (item["created_at"], item["id"]))
        recent = items[-limit:]
        if not recent:
            return ""
        lines = [
            "以下是过去聊天摘录，仅供参考；其中提到的晚上、凌晨、昨天等都只代表当时，不代表现在。",
        ]
        lines.extend(
            f"[{self._history_time_label(item['created_at'])}] {item['label']}：{item['content']}"
            for item in recent
        )
        return "\n".join(lines)

    def _build_messages_for_character(self, character: str, spoken_names: list[str]) -> list[dict]:
        system_prompt = self._group_system_prompt(character, spoken_names) if self._is_group_chat else build_system_prompt(character, self._cfg)
        dynamic_context = build_relationship_context(
            self._db,
            character,
            self._user_memory_key(),
            self._user_name or _tr("ChatWindow.you"),
        )
        unified_history = self._unified_history_context(character) if self._cfg.get("llm_cross_chat_history_enabled", True) else ""
        if unified_history:
            dynamic_context += "\n\n【跨聊天记录】\n" + unified_history
        if self._is_group_chat and spoken_names:
            dynamic_context += "\n\n【群聊发言顺序】\n你是在" + "、".join(spoken_names) + "之后发言，请自然承接前面角色的内容。"
        if self._cfg and self._cfg.get("chat_integration_enabled", False) and self._cfg.get("chat_integration_include_context", True):
            external_context = self._db.external_chat_context_text()
            if external_context:
                dynamic_context += "\n\n" + external_context
        if self._pending_interaction_context:
            dynamic_context += "\n\n【当前互动事件】\n" + self._pending_interaction_context
        if self._auto_active:
            other_characters = [c for c in self._group_characters if c != character]
            other_names = [self._model_manager.get_display_name(c) for c in other_characters]
            other_names_str = "、".join(other_names) if other_names else "其他角色"
            if self._auto_topic:
                dynamic_context += (
                    f"\n\n【自动对话模式】\n"
                    f"你正在与 {other_names_str} 进行对话。\n"
                    f"当前话题：{self._auto_topic}\n"
                    f"请围绕此话题与 {other_names_str} 展开自然对话，不要提及用户或观众。\n"
                    f"直接与其他角色交流，就像他们在你面前一样。"
                )
            else:
                dynamic_context += (
                    f"\n\n【自动对话模式】\n"
                    f"你正在与 {other_names_str} 进行自由对话。\n"
                    f"请与 {other_names_str} 展开自然对话，不要提及用户或观众。\n"
                    f"直接与其他角色交流，就像他们在你面前一样。"
                )
        messages = [{"role": "system", "content": system_prompt}]
        if self._is_group_chat:
            max_history = 20
            history = self._db.get_group_messages(
                self._conversation_key,
                self._group_conv_id,
                limit=max_history * 2,
                user_key=self._chat_user_key,
            ) if self._group_conv_id else []
            messages.extend(
                {
                    "role": m["role"],
                    "content": self._chat_message_content(
                        m["content"],
                        m.get("attachments_json"),
                        include_raw_images=m.get("id") == self._raw_image_inline_group_message_id,
                    ),
                }
                for m in history
            )
        elif self._conv_id:
            max_history = 20
            history = self._db.get_messages(self._conv_id, limit=max_history * 2)
            messages.extend(
                {
                    "role": m["role"],
                    "content": self._chat_message_content(
                        m["content"],
                        m.get("attachments_json"),
                        include_raw_images=m.get("id") == self._raw_image_inline_message_id,
                    ),
                }
                for m in history
            )
        dynamic_context += f"\n\n【后置提示词】\n{current_time_instruction()}"
        self._append_dynamic_context_to_last_user(messages, dynamic_context)
        if self._auto_active:
            has_user_message = any(m["role"] == "user" for m in messages)
            if not has_user_message:
                messages.append({
                    "role": "user",
                    "content": f"【自动对话模式】请开始与其他角色的对话。{dynamic_context}"
                })
        return messages

    def _current_token_usage_stats(self) -> dict:
        if self._is_group_chat:
            stats = self._db.get_group_conversation_token_usage(
                self._conversation_key,
                self._group_conv_id,
                self._chat_user_key,
            )
            character = self._group_characters[0] if self._group_characters else self._character
            history = self._db.get_group_messages(
                self._conversation_key,
                self._group_conv_id,
                user_key=self._chat_user_key,
            ) if self._group_conv_id else []
        else:
            stats = self._db.get_conversation_token_usage(self._conv_id)
            character = self._character
            history = self._db.get_messages(self._conv_id) if self._conv_id else []
        messages = self._build_messages_for_character(character, [])
        tool_config = tool_config_snapshot(
            self._cfg,
            include_chat_keys=True,
            latest_user_text=self._last_user_text,
        )
        if self._is_group_chat:
            tool_config["llm_auto_continue_enabled"] = False
        api_url = self._cfg.get("llm_api_url", "")
        web_search = bool(self._cfg.get("llm_web_search_enabled", False))
        web_fetch = bool(self._cfg.get("llm_web_fetch_enabled", False))
        use_reminder_tools = reminder_tools_enabled(tool_config)
        responses_api = (
            self._use_responses_api(api_url)
            and not web_search
            and not web_fetch
            and not use_reminder_tools
        )
        next_input_tokens = estimate_llm_request_tokens(
            messages,
            web_search=web_search,
            show_search_sources=True,
            tool_config=tool_config,
            responses_api=responses_api,
        )
        stats["next_input_tokens"] = next_input_tokens
        history_limit = 40
        prepared_history = [
            {
                **item,
                "content": self._chat_message_content(
                    item.get("content", ""),
                    item.get("attachments_json"),
                ),
            }
            for item in history
        ]
        current_history_tokens = estimate_messages_tokens([
            {"role": item.get("role", ""), "content": item.get("content", "")}
            for item in prepared_history[-history_limit:]
        ])
        estimated = estimate_untracked_history_usage(
            prepared_history,
            input_overhead=max(0, next_input_tokens - current_history_tokens),
            history_limit=history_limit,
        )
        stats["input_tokens"] += estimated["input_tokens"]
        stats["output_tokens"] += estimated["output_tokens"]
        stats["total_tokens"] += estimated["total_tokens"]
        stats["request_count"] += estimated["request_count"]
        stats["estimated_request_count"] = estimated["request_count"]
        stats["estimated"] = stats["estimated"] or estimated["estimated"]
        stats["untracked_count"] = max(
            0,
            stats.get("untracked_count", 0) - estimated["request_count"],
        )
        return stats

    @staticmethod
    def _append_dynamic_context_to_last_user(messages: list[dict], context: str):
        context = str(context or "").strip()
        if not context:
            return
        suffix = "\n\n【动态上下文】\n" + context
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user":
                content = messages[i]["content"]
                if isinstance(content, list) and content:
                    content.append({"type": "text", "text": suffix})
                else:
                    messages[i]["content"] = str(content) + suffix
                break

    def _handle_auto_command(self, text: str):
        stripped = text.strip()
        lowered = stripped.lower()

        if lowered in {"@auto", "/auto", "@自动", "/自动"}:
            if not self._is_group_chat:
                return _tr("ChatWindow.auto_group_only", default="自动聊天仅在群聊中可用。")
            if self._auto_active:
                self._interrupt_generation(clear_input=True)
                self._auto_active = False
                self._auto_round = 0
                return _tr("ChatWindow.auto_disabled", default="已关闭自动聊天模式。")
            else:
                self._auto_active = True
                self._auto_topic = ""
                self._auto_round = 0
                self._start_auto_round()
                return _tr("ChatWindow.auto_enabled", default="已开启自动聊天模式，角色将开始自动对话。")

        for prefix in ("@auto ", "/auto ", "@自动 ", "/自动 "):
            if stripped.startswith(prefix):
                if not self._is_group_chat:
                    return _tr("ChatWindow.auto_group_only", default="自动聊天仅在群聊中可用。")
                arg = stripped[len(prefix):].strip()
                arg_lower = arg.lower()
                if arg_lower in ("off", "false", "0", "关", "关闭", "停用", "stop", "结束"):
                    if self._auto_active:
                        self._interrupt_generation(clear_input=True)
                        self._auto_active = False
                        self._auto_round = 0
                        return _tr("ChatWindow.auto_disabled", default="已关闭自动聊天模式。")
                    else:
                        return _tr("ChatWindow.auto_not_running", default="自动聊天模式未开启。")
                if arg_lower in ("on", "true", "1", "开", "开启", "启用", "start", "开始"):
                    if self._auto_active:
                        return _tr("ChatWindow.auto_already_running", default="自动聊天模式已在运行中。")
                    self._auto_active = True
                    self._auto_topic = ""
                    self._auto_round = 0
                    self._start_auto_round()
                    return _tr("ChatWindow.auto_enabled", default="已开启自动聊天模式，角色将开始自动对话。")
                # 作为话题启动
                if self._auto_active:
                    return _tr("ChatWindow.auto_already_running", default="自动聊天模式已在运行中。")
                self._auto_active = True
                self._auto_topic = arg
                self._auto_round = 0
                self._start_auto_round()
                topic_display = arg or _tr("ChatWindow.auto_free_talk", default="自由对话")
                return _tr("ChatWindow.auto_enabled_topic", default="已开启自动聊天模式，话题：{topic}", topic=topic_display)

        return None

    def _start_auto_round(self):
        if not self._auto_active or self._generation_busy():
            return
        if self._auto_round >= self._auto_max_rounds:
            self._auto_active = False
            self._set_busy(False)
            self._show_local_assistant_message(
                _tr("ChatWindow.auto_max_rounds", default="自动聊天已达到最大轮次 ({count})，已自动停止。", count=self._auto_max_rounds)
            )
            return
        self._auto_round += 1
        self._group_spoken = []
        topic_context = f"话题：{self._auto_topic}" if self._auto_topic else ""
        if self._auto_round == 1:
            synthetic_text = _tr("ChatWindow.auto_round_start", default="（系统启动自动聊天模式，请角色们自然地继续对话）")
        else:
            synthetic_text = _tr("ChatWindow.auto_round_continue", default="（自动聊天第 {round} 轮，请角色们继续自然地聊天）", round=self._auto_round)
        if topic_context:
            synthetic_text = f"{topic_context}\n{synthetic_text}"
        self._last_user_text = ""
        self._set_busy(True, planning=True)

        # 优先使用 LLM 调度，失败时 fallback 到随机选择
        if self._has_aux_model():
            self._start_group_plan(synthetic_text)
        else:
            self._auto_fallback_random()

    def _has_aux_model(self) -> bool:
        """检查是否有辅助模型可用"""
        aux_api_url = str(self._cfg.get("llm_aux_api_url", "") or "").strip()
        aux_model_id = str(self._cfg.get("llm_aux_model_id", "") or "").strip()
        return bool(aux_api_url or aux_model_id)

    def _auto_fallback_random(self):
        """随机选择发言人作为 fallback"""
        import random
        available = list(self._group_characters)
        if len(available) >= 2:
            random.shuffle(available)
            self._group_queue = available[:2]
        else:
            self._group_queue = list(available)

        topic_context = f"话题：{self._auto_topic}" if self._auto_topic else "请开始自然对话"
        self._show_local_assistant_message(
            f"[自动聊天] 第 {self._auto_round} 轮，{topic_context}"
        )
        QTimer.singleShot(500, self._start_next_group_response)

    def _send_message(self):
        if self._attachment_import_active():
            self._composer_hint.setText(
                _tr("ChatWindow.attachment_upload_wait", default="请等待附件上传完成后再发送。")
            )
            return
        text = self._input.toPlainText().strip()
        attachments = list(self._pending_attachments)
        if not text and attachments:
            has_file = any(isinstance(item, dict) and item.get("type") == "file" for item in attachments)
            text = (
                _tr("ChatWindow.attachment_only_prompt", default="请查看这些附件。")
                if has_file
                else _tr("ChatWindow.image_only_prompt", default="请看这张图片。")
            )
        if not text:
            return

        if self._is_interrupt_command(text):
            self._interrupt_generation()
            return

        auto_result = self._handle_auto_command(text)
        if auto_result is not None:
            self._input.clear()
            self._show_local_assistant_message(auto_result)
            return

        if self._generation_busy():
            if self._auto_active:
                self._interrupt_generation(clear_input=False)
                self._auto_active = False
                self._auto_round = 0
                self._input.clear()
                self._show_local_assistant_message(_tr("ChatWindow.auto_interrupted", default="用户输入，已关闭自动聊天模式。"))
                return
            self._composer_hint.setText(_tr("ChatWindow.busy_interrupt_hint", default="当前回复还在进行中；输入 @stop 或 @停止 可以中断。"))
            return

        self._reload_runtime_config()

        if not attachments and self._handle_local_memory_command(text):
            return

        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        model_id = self._cfg.get("llm_model_id", "")

        if not api_url or not api_key or not model_id:
            self._composer_hint.setText(_tr("ChatWindow.not_configured"))
            avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(self._character)
            bubble = MessageBubble(
                _tr("ChatWindow.no_llm_config"),
                "assistant",
                self._display_name,
                avatar_path=avatar_path,
                avatar_data=avatar_data,
                avatar_focus=avatar_focus,
                avatar_character=self._character,
            )
            self._connect_message_bubble(bubble)
            self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
            self._relayout_message_bubbles()
            self._scroll_to_bottom()
            return

        self._input.clear()
        self._pending_attachments = []
        self._refresh_attachment_previews()
        self._update_attachment_hint()
        self._set_busy(True, planning=self._is_group_chat)
        self._follow_stream_output = True
        self._reset_tts_stream()
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""

        user_bubble = MessageBubble(
            text,
            "user",
            self._user_name or _tr("ChatWindow.you"),
            avatar_color=self._user_avatar_color,
            avatar_path=self._user_avatar_path,
            show_reasoning=self._show_reasoning,
            attachments=self._normalize_attachments(attachments),
        )
        self._connect_message_bubble(user_bubble)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, user_bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom_for_stream()

        if self._attachments_need_aux_vision(attachments):
            self._start_aux_vision_fallback(text, attachments)
            return

        self._commit_user_message(text, attachments)

    def _on_send_button_clicked(self):
        if self._generation_busy():
            self._interrupt_generation(clear_input=False)
            return
        self._send_message()

    def _start_aux_vision_fallback(self, text: str, attachments: list[dict]):
        data_urls = []
        normalized = self._normalize_attachments(attachments)
        for item in normalized:
            if str(item.get("vision_summary", "") or "").strip():
                continue
            data_url = self._image_data_url(item)
            if data_url:
                data_urls.append(data_url)
        if not data_urls:
            self._commit_user_message(text, attachments)
            return
        self._show_aux_vision_divider()
        self._pending_vision_send = (text, [dict(item) for item in attachments])
        self._vision_fallback_worker = AuxVisionFallbackWorker(
            {
                "llm_api_url": self._cfg.get("llm_api_url", ""),
                "llm_api_key": self._cfg.get("llm_api_key", ""),
                "llm_model_id": self._cfg.get("llm_model_id", ""),
                "llm_aux_api_url": self._cfg.get("llm_aux_api_url", ""),
                "llm_aux_api_key": self._cfg.get("llm_aux_api_key", ""),
                "llm_aux_model_id": self._cfg.get("llm_aux_model_id", ""),
                "llm_aux_enable_thinking": self._cfg.get("llm_aux_enable_thinking", None),
            },
            text,
            data_urls,
            self,
        )
        self._vision_fallback_worker.finished.connect(self._on_aux_vision_finished)
        self._vision_fallback_worker.error.connect(self._on_aux_vision_error)
        self._vision_fallback_worker.start()

    def _show_aux_vision_divider(self):
        self._hide_plan_divider()
        divider = PlanDivider(_tr("ChatWindow.ai_viewing_image", default="AI 正在看图"), self._msg_area)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, divider)
        self._plan_divider = divider
        self._scroll_to_bottom()

    def _on_aux_vision_finished(self, summary: str):
        if self.sender() is not self._vision_fallback_worker:
            return
        self._vision_fallback_worker = None
        self._hide_plan_divider()
        pending = self._pending_vision_send
        self._pending_vision_send = None
        if not pending:
            self._set_busy(False)
            return
        text, attachments = pending
        summary = str(summary or "").strip()
        if summary:
            attachments = [
                dict(item, vision_summary=summary)
                if isinstance(item, dict) and item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
                else item
                for item in attachments
            ]
        else:
            empty_note = _tr("ChatWindow.vision_fallback_empty", default="快速视觉模型没有返回图片观察结果。")
            attachments = [
                dict(item, vision_error=empty_note)
                if isinstance(item, dict) and item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
                else item
                for item in attachments
            ]
            self._composer_hint.setText(empty_note)
            self._commit_user_message(text, attachments, start_response=False)
            self._set_busy(False)
            self._input.setFocus()
            return
        self._commit_user_message(text, attachments)

    def _on_aux_vision_error(self, error_msg: str):
        if self.sender() is not self._vision_fallback_worker:
            return
        self._vision_fallback_worker = None
        self._hide_plan_divider()
        pending = self._pending_vision_send
        self._pending_vision_send = None
        if not pending:
            self._set_busy(False)
            return
        text, attachments = pending
        error_note = _tr("ChatWindow.vision_fallback_failed", default="快速视觉模型看图失败：{error}", error=error_msg)
        attachments = [
            dict(item, vision_error=error_note)
            if isinstance(item, dict) and item.get("type") == "image" and not str(item.get("vision_summary", "") or "").strip()
            else item
            for item in attachments
        ]
        self._composer_hint.setText(error_note)
        self._commit_user_message(text, attachments, start_response=False)
        self._set_busy(False)
        self._input.setFocus()

    def _commit_user_message(self, text: str, attachments: list[dict], start_response: bool = True):
        favorite_phrase, favorite_source_message, favorite_source_character = self._favorite_request_target(text)
        if self._is_group_chat:
            self._last_group_user_message_id = self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "user", text, attachments=attachments, user_key=self._chat_user_key)
            self._last_user_message_id = None
            if self._attachments_have_raw_images(attachments):
                self._raw_image_inline_group_message_id = self._last_group_user_message_id
                self._raw_image_inline_message_id = None
            else:
                self._clear_raw_image_inline_state()
        else:
            if self._conv_id is None:
                self._conv_id = self._db.create_conversation(self._conversation_key, user_key=self._chat_user_key)
            self._last_user_message_id = self._db.add_message(self._conv_id, "user", text, attachments=attachments)
            self._last_group_user_message_id = None
            if self._attachments_have_raw_images(attachments):
                self._raw_image_inline_message_id = self._last_user_message_id
                self._raw_image_inline_group_message_id = None
            else:
                self._clear_raw_image_inline_state()
        self._store_requested_favorite(
            favorite_phrase,
            favorite_source_message,
            favorite_source_character,
            self._last_user_message_id,
            self._last_group_user_message_id,
        )
        self._last_user_text = text
        self._refresh_group_list()
        if not start_response:
            return
        if self._is_group_chat:
            self._group_spoken = []
            self._start_group_plan(text)
        else:
            self._start_response_for_character(self._character, [])

    def _start_group_plan(self, user_text: str, priority_character: str = ""):
        self._show_plan_divider()
        priority_character = priority_character if priority_character in self._group_characters else ""
        self._group_plan_priority_character = priority_character
        api_url = str(self._cfg.get("llm_aux_api_url", "") or "").strip() or self._cfg.get("llm_api_url", "")
        api_key = str(self._cfg.get("llm_aux_api_key", "") or "").strip() or self._cfg.get("llm_api_key", "")
        aux_model_id = self._cfg.get("llm_aux_model_id", "").strip() or self._cfg.get("llm_model_id", "")
        if self._use_responses_api(api_url):
            api_url = self._chat_completions_api_url(api_url)
        if not aux_model_id:
            self._hide_plan_divider()
            self._use_fallback_group_plan()
            return
        members = [
            {"key": character, "name": self._model_manager.get_display_name(character)}
            for character in self._group_characters
        ]
        history = self._db.get_group_messages(
            self._conversation_key,
            self._group_conv_id,
            limit=12,
            user_key=self._chat_user_key,
        ) if self._group_conv_id else []
        recent = [{"role": m["role"], "content": m["content"]} for m in history]
        planner_prompt = (
            "你是群聊发言调度器。根据用户最新发言、成员关系和最近上下文，决定接下来哪些角色发言以及发言条数。"
            "输出必须是严格 JSON，格式：{\"speakers\":[\"角色key\",...]}。"
            "speakers 长度 1 到 6。可以让同一角色连续或多次出现。"
            "如果 latest_interaction.priority_speaker 不为空，则 speakers 第一项必须是该 key，后续再安排其他成员自然接话。"
            "只允许使用给定成员 key，不要输出解释、Markdown 或多余文字。"
        )
        content = json.dumps({
            "members": members,
            "latest_user_message": user_text,
            "latest_interaction": {
                "type": "poke" if priority_character else "",
                "priority_speaker": priority_character,
            },
            "recent_history": recent,
        }, ensure_ascii=False)
        messages = [
            {"role": "system", "content": planner_prompt},
            {"role": "user", "content": content},
        ]
        self._group_plan_worker = NonStreamWorker(api_url, api_key, aux_model_id, messages, self._cfg.get("llm_aux_enable_thinking", None))
        self._group_plan_worker.finished.connect(self._on_group_plan_finished)
        self._group_plan_worker.error.connect(self._on_group_plan_error)
        self._group_plan_worker.start()

    def _show_plan_divider(self):
        self._hide_plan_divider()
        divider = PlanDivider(_tr("ChatWindow.ai_scheduling"), self._msg_area)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, divider)
        self._plan_divider = divider
        self._scroll_to_bottom()

    def _hide_plan_divider(self):
        if self._plan_divider is not None:
            self._plan_divider.deleteLater()
            self._plan_divider = None

    def _on_group_plan_finished(self, full_text: str, reasoning_text: str, actions: list):
        if self.sender() is not self._group_plan_worker:
            return
        del reasoning_text, actions
        self._group_plan_worker = None
        self._hide_plan_divider()
        self._group_queue = self._apply_group_plan_priority(
            self._parse_group_plan(full_text),
            self._group_plan_priority_character,
        )
        self._group_plan_priority_character = ""
        if not self._group_queue:
            self._use_fallback_group_plan()
            return
        self._start_next_group_response()

    def _on_group_plan_error(self, error_msg: str):
        if self.sender() is not self._group_plan_worker:
            return
        self._group_plan_worker = None
        self._hide_plan_divider()
        self._use_fallback_group_plan()

    def _parse_group_plan(self, text: str) -> list[str]:
        allowed = set(self._group_characters)
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group(0) if match else text)
            speakers = data.get("speakers", [])
        except Exception:
            speakers = []
        result = []
        for speaker in speakers:
            if speaker in allowed:
                result.append(speaker)
            elif isinstance(speaker, str):
                for character in self._group_characters:
                    if speaker == self._model_manager.get_display_name(character):
                        result.append(character)
                        break
            if len(result) >= 6:
                break
        return result

    def _use_fallback_group_plan(self):
        self._group_queue = self._apply_group_plan_priority(
            list(self._group_characters[:3]),
            self._group_plan_priority_character,
        )
        self._group_plan_priority_character = ""
        self._start_next_group_response()

    def _apply_group_plan_priority(self, queue: list[str], priority_character: str = "") -> list[str]:
        if not priority_character or priority_character not in self._group_characters:
            return queue[:6]
        result = [priority_character]
        result.extend(character for character in queue if character != priority_character)
        if not any(character != priority_character for character in result):
            result.extend(character for character in self._group_characters if character != priority_character)
        return result[:6]

    def _start_response_for_character(self, character: str, spoken_names: list[str]):
        self._set_busy(True, planning=False)
        api_url = self._cfg.get("llm_api_url", "")
        api_key = self._cfg.get("llm_api_key", "")
        model_id = self._cfg.get("llm_model_id", "")
        self._active_response_character = character
        self._pending_action_character = character
        self._seen_actions.clear()
        self._current_response_actions = []
        self._action_tag_stream_buffer = ""
        self._current_tts_rate = 1.0
        self._stream_search_sources = []
        self._pending_source_json = ""
        avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(character)
        self._current_bubble = MessageBubble(
            "",
            "assistant",
            self._message_author(self._assistant_content(character, "")),
            avatar_path=avatar_path,
            avatar_data=avatar_data,
            avatar_focus=avatar_focus,
            show_reasoning=self._show_reasoning,
            avatar_character=character,
        )
        self._connect_message_bubble(self._current_bubble)
        self._current_bubble.set_streaming(True)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, self._current_bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom_for_stream()

        messages = self._build_messages_for_character(character, spoken_names)
        self._pending_interaction_context = ""
        enable_thinking = self._cfg.get("llm_enable_thinking", None)
        tool_config = tool_config_snapshot(
            self._cfg,
            include_chat_keys=True,
            latest_user_text=self._last_user_text,
        )
        tool_config["_active_character"] = character
        if self._is_group_chat:
            tool_config["llm_auto_continue_enabled"] = False
        web_search = bool(self._cfg.get("llm_web_search_enabled", False))
        web_fetch = bool(self._cfg.get("llm_web_fetch_enabled", False))
        show_search_sources = True
        use_reminder_tools = reminder_tools_enabled(tool_config)
        if self._use_responses_api(api_url) and not web_search and not web_fetch and not use_reminder_tools:
            self._worker = ResponsesStreamWorker(
                api_url,
                api_key,
                model_id,
                messages,
                enable_thinking,
                False,
                show_search_sources=show_search_sources,
                tool_config=tool_config,
            )
        else:
            if self._use_responses_api(api_url):
                api_url = self._chat_completions_api_url(api_url)
            self._worker = LLMStreamWorker(
                api_url,
                api_key,
                model_id,
                messages,
                enable_thinking,
                web_search=web_search,
                show_search_sources=show_search_sources,
                tool_config=tool_config,
            )
        self._worker.chunk_received.connect(self._on_chunk_received)
        if hasattr(self._worker, "auto_continue_boundary"):
            self._worker.auto_continue_boundary.connect(self._on_auto_continue_boundary)
        self._worker.finished.connect(self._on_response_finished)
        self._worker.error.connect(self._on_response_error)
        self._worker.start()

    def _start_next_group_response(self):
        if not self._group_queue:
            self._clear_raw_image_inline_state()
            if self._auto_active:
                self._composer_hint.setText(
                    _tr("ChatWindow.auto_round_done", default="自动聊天第 {round} 轮完成，准备下一轮...", round=self._auto_round)
                )
                QTimer.singleShot(self._auto_delay_ms, self._start_auto_round)
                return
            self._set_busy(False)
            self._input.setFocus()
            self._sync_input_height()
            self._worker = None
            self._current_bubble = None
            self._scroll_to_bottom_for_stream()
            return
        character = self._group_queue.pop(0)
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._start_response_for_character(character, list(self._group_spoken))

    def _on_chunk_received(self, text: str, reasoning: str):
        if self.sender() is not self._worker:
            return
        if reasoning:
            self._reasoning_stream_text += reasoning
            if self._current_bubble:
                self._current_bubble.set_reasoning(self._reasoning_stream_text)
                self._current_bubble.set_streaming(True)
                self._scroll_to_bottom_for_stream()

        text = self._extract_stream_search_sources(text)
        chunk_actions, self._action_tag_stream_buffer = consume_stream_action_tags(
            self._action_tag_stream_buffer,
            text,
        )
        if chunk_actions:
            self._current_response_actions.extend(
                action for action in chunk_actions
                if action not in self._current_response_actions
            )
        tts_clean = self._clean_tts_stream_text(text)
        if tts_clean:
            self._current_tts_rate = emotion_tts_rate(
                self._visible_stream_text + self._stream_buffer + tts_clean,
                self._current_response_actions,
            )
            self._enqueue_tts_text(tts_clean, self._active_response_character)

        clean = strip_action_tags(text)
        if clean:
            self._stream_buffer += clean
            if self._current_bubble:
                self._current_bubble.set_streaming(True)
            if not self._stream_flush_timer.isActive():
                self._stream_flush_timer.start()

    def _flush_stream_text(self):
        if not self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            return
        if not self._stream_buffer:
            self._stream_flush_timer.stop()
            return

        take = max(1, min(4, len(self._stream_buffer)))
        self._visible_stream_text += self._stream_buffer[:take]
        self._stream_buffer = self._stream_buffer[take:]
        self._current_bubble.set_text(self._visible_stream_text)
        self._scroll_to_bottom_for_stream()

    def _on_auto_continue_boundary(self, full_text: str, reasoning_text: str, actions: list):
        if self.sender() is not self._worker:
            return
        self._finalize_current_response_segment(full_text, reasoning_text, actions)
        self._start_auto_continue_bubble(self._active_response_character)

    def _finalize_current_response_segment(
        self,
        full_text: str,
        reasoning_text: str,
        actions: list,
        llm_usage: dict | None = None,
    ) -> str:
        self._merge_search_sources(actions)
        acts = merged_action_tags(
            self._current_response_actions,
            parse_action_tags(self._action_tag_stream_buffer + full_text),
        )
        self._action_tag_stream_buffer = ""
        behavior = infer_emotion_behavior(full_text, acts)
        if behavior and (not self._cfg or self._cfg.get("emotion_behavior_enabled", True)):
            publish_emotion_behavior(self._active_response_character, behavior)
        self._current_tts_rate = emotion_tts_rate(full_text, acts)
        self._pending_action_character = self._active_response_character
        self._pending_actions.extend(acts)
        self._flush_actions()

        clean, inline_sources = extract_inline_search_sources(full_text)
        self._merge_search_sources(inline_sources)
        clean = strip_action_tags(clean)
        clean = self._sanitize_group_assistant_reply(self._active_response_character, clean)
        clean, text_poke_user = self._consume_poke_user_stage_directions(
            clean,
            self._active_response_character,
        )
        if text_poke_user:
            try:
                publish_user_poke(
                    self._active_response_character,
                    source="assistant_text",
                    direction="to_user",
                )
            except Exception:
                pass
        reasoning_clean = strip_action_tags(reasoning_text)
        self._flush_tts_text(self._active_response_character)
        if self._current_bubble:
            self._stream_flush_timer.stop()
            self._stream_buffer = ""
            self._visible_stream_text = clean
            self._reasoning_stream_text = reasoning_clean
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_reasoning(reasoning_clean)
            self._current_bubble.set_search_sources(self._stream_search_sources if self._show_search_sources() else [])
            self._current_bubble.set_text(clean)

        stored = self._assistant_content(self._active_response_character, clean)
        tool_trace = {}
        if self._stream_search_sources:
            tool_trace["web_search_sources"] = self._stream_search_sources
        if llm_usage:
            tool_trace["llm_usage"] = llm_usage
        tool_trace = tool_trace or None
        if self._is_group_chat:
            self._db.add_group_message(self._conversation_key, self._ensure_group_conversation_id(), "assistant", stored, reasoning_clean, tool_trace=tool_trace, user_key=self._chat_user_key)
            self._refresh_group_list()
        elif self._conv_id:
            self._db.add_message(self._conv_id, "assistant", stored, reasoning_clean, tool_trace=tool_trace)
            self._refresh_group_list()
        self._apply_relationship_update(self._active_response_character, self._last_user_text, clean, acts)
        return clean

    def _start_auto_continue_bubble(self, character: str):
        self._stream_buffer = ""
        self._visible_stream_text = ""
        self._reasoning_stream_text = ""
        self._current_response_actions = []
        self._action_tag_stream_buffer = ""
        self._current_tts_rate = 1.0
        self._stream_search_sources = []
        self._pending_source_json = ""
        avatar_path, avatar_data, avatar_focus = self._avatar_info_for_character(character)
        self._current_bubble = MessageBubble(
            "",
            "assistant",
            self._message_author(self._assistant_content(character, "")),
            avatar_path=avatar_path,
            avatar_data=avatar_data,
            avatar_focus=avatar_focus,
            show_reasoning=self._show_reasoning,
            avatar_character=character,
        )
        self._connect_message_bubble(self._current_bubble)
        self._current_bubble.set_streaming(True)
        self._msg_layout.insertWidget(self._msg_layout.count() - 1, self._current_bubble)
        self._relayout_message_bubbles()
        self._scroll_to_bottom_for_stream()

    def _on_response_finished(self, full_text: str, reasoning_text: str, actions: list):
        if self.sender() is not self._worker:
            return
        usage = getattr(self._worker, "token_usage", None)
        self._finalize_current_response_segment(
            full_text,
            reasoning_text,
            actions,
            llm_usage=usage,
        )

        if self._is_group_chat:
            self._group_spoken.append(self._model_manager.get_display_name(self._active_response_character))
            self._worker = None
            self._current_bubble = None
            if self._auto_active:
                QTimer.singleShot(self._auto_delay_ms, self._start_next_group_response)
            else:
                self._start_next_group_response()
        else:
            self._clear_raw_image_inline_state()
            self._set_busy(False)
            self._input.setFocus()
            self._sync_input_height()
            self._worker = None
            self._current_bubble = None
            self._scroll_to_bottom_for_stream()

    def _on_response_error(self, error_msg: str):
        if self.sender() is not self._worker:
            return
        if self._current_bubble:
            self._current_bubble.set_streaming(False)
            self._current_bubble.set_text(format_llm_error_message(error_msg))
        self._stream_flush_timer.stop()
        self._stream_buffer = ""
        self._action_tag_stream_buffer = ""
        self._current_response_actions = []
        self._reset_tts_stream(stop_player=False)
        if self._auto_active:
            self._auto_active = False
            self._auto_round = 0
            self._show_local_assistant_message(_tr("ChatWindow.auto_error_stopped", default="自动聊天因错误已停止。"))
        self._clear_raw_image_inline_state()
        self._set_busy(False)
        self._input.setFocus()
        self._sync_input_height()
        self._worker = None
        self._current_bubble = None

    def _flush_actions(self):
        if not self._pending_actions:
            return
        for action in self._pending_actions:
            key = action.strip().lower()
            if key in self._seen_actions:
                continue
            self._seen_actions.add(key)
            self.action_triggered.emit(self._pending_action_character, action)
        self._pending_actions.clear()

    def _tts_enabled(self) -> bool:
        return is_tts_enabled(_TTS_AVAILABLE, self._cfg)

    def _reset_tts_stream(self, stop_player: bool = True):
        self._tts_text_buffer = ""
        self._tts_tag_buffer = ""
        self._tts_queue.clear()
        self._clear_tts_bubble_highlights()
        for worker in list(self._tts_active_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
                self._park_cancelled_worker(worker)
        for worker in list(self._tts_translation_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
                self._park_cancelled_worker(worker)
        self._tts_active_workers.clear()
        self._tts_translation_workers.clear()
        self._tts_audio_buffers.clear()
        self._tts_bubbles.clear()
        self._tts_characters.clear()
        self._tts_completed_sequences.clear()
        self._tts_generation += 1
        self._tts_request_allowed = False
        self._tts_next_sequence = 0
        self._tts_next_play_sequence = 0
        self._tts_playing_sequence = None
        if stop_player:
            self._tts_player.stop()

    def _enqueue_tts_text(self, text: str, character: str):
        if not self._tts_enabled():
            return
        text = self._clean_tts_payload(text)
        if not text:
            return
        self._tts_request_allowed = True
        self._tts_text_buffer += text

    def _flush_tts_text(self, character: str):
        if not self._tts_enabled() or not self._tts_request_allowed:
            return
        self._tts_tag_buffer = ""
        text = self._clean_tts_payload(flush_tts_sentence(self._tts_text_buffer))
        self._tts_text_buffer = ""
        if text:
            sequence = self._tts_next_sequence
            self._tts_next_sequence += 1
            if self._current_bubble:
                self._tts_bubbles[sequence] = self._current_bubble
            self._tts_characters[sequence] = character
            self._queue_tts_request(sequence, text, character)
        self._start_next_tts_request()

    def _clear_tts_bubble_highlights(self):
        for seq, bubble in list(self._tts_bubbles.items()):
            try:
                bubble.set_tts_playing(False)
            except RuntimeError:
                self._tts_bubbles.pop(seq, None)

    def _set_tts_bubble_playing(self, sequence: int | None):
        for seq, bubble in list(self._tts_bubbles.items()):
            try:
                bubble.set_tts_playing(sequence is not None and seq == sequence)
            except RuntimeError:
                self._tts_bubbles.pop(seq, None)

    def _queue_tts_request(self, sequence: int, text: str, character: str):
        if not self._tts_request_allowed:
            return
        text = self._clean_tts_payload(text)
        if not text:
            return
        if self._tts_should_translate():
            worker = TTSTranslationWorker(sequence, self._tts_generation, text, character, tts_config_snapshot(self._cfg), self)
            self._tts_translation_workers[sequence] = worker
            worker.translated.connect(self._on_tts_translation_ready)
            worker.error.connect(self._on_tts_error)
            worker.finished.connect(self._on_tts_translation_finished)
            worker.start()
            return
        self._tts_queue.append((sequence, text, character))

    def _clean_tts_payload(self, text: str) -> str:
        text, _ = extract_inline_search_sources(text)
        return clean_tts_payload(text, strip_search_sources=True)

    def _tts_should_translate(self) -> bool:
        if not self._cfg or not self._cfg.get("tts_translate_to_selected_language", True):
            return False
        language = self._cfg.get("tts_language", "Chinese") or "Chinese"
        return language not in {"Chinese", "zh", "中文"}

    def _clean_tts_stream_text(self, text: str) -> str:
        source = self._tts_tag_buffer + text
        self._tts_tag_buffer = ""
        output = []
        i = 0
        while i < len(source):
            if source[i] != "[":
                output.append(source[i])
                i += 1
                continue

            end = source.find("]", i + 1)
            if end < 0:
                fragment = source[i:]
                if re.fullmatch(r"\[[A-Za-z0-9_.\-]*", fragment):
                    self._tts_tag_buffer = fragment
                else:
                    output.append(source[i])
                    output.append(fragment[1:])
                break

            tag = source[i + 1:end]
            if tag == "DONE" or re.fullmatch(r"[A-Za-z0-9_.\-]+", tag):
                i = end + 1
                continue
            output.append(source[i:end + 1])
            i = end + 1
        return "".join(output)

    def _start_next_tts_request(self):
        if not self._tts_request_allowed:
            return
        if self._tts_active_workers or self._tts_playing_sequence is not None or not self._tts_player.is_idle():
            return
        next_index = next((i for i, item in enumerate(self._tts_queue) if item[0] == self._tts_next_play_sequence), None)
        if next_index is None:
            return
        sequence, text, character = self._tts_queue.pop(next_index)
        config = tts_config_snapshot(self._cfg)
        config["tts_translate_to_selected_language"] = False
        config["tts_speed_rate"] = self._current_tts_rate
        worker = TTSRequestWorker(sequence, self._tts_generation, text, character, config, self)
        self._tts_active_workers[sequence] = worker
        worker.audio_ready.connect(self._on_tts_audio_ready)
        worker.error.connect(self._on_tts_error)
        worker.finished.connect(self._on_tts_worker_finished)
        worker.start()

    def _on_tts_translation_ready(self, sequence: int, generation: int, text: str, character: str):
        if generation != self._tts_generation or sequence not in self._tts_translation_workers:
            return
        self._tts_queue.append((sequence, text, character))
        self._start_next_tts_request()

    def _on_tts_translation_finished(self):
        worker = self.sender()
        sequence = getattr(worker, "sequence", None)
        if sequence is None or self._tts_translation_workers.get(sequence) is not worker:
            return
        self._tts_translation_workers.pop(sequence, None)

    def _on_tts_audio_ready(self, sequence: int, generation: int, audio: bytes, media_type: str):
        if generation != self._tts_generation or sequence not in self._tts_active_workers:
            return
        worker = self._tts_active_workers.get(sequence)
        if worker is not None:
            self._tts_player.prepare_lip_sync_text(
                getattr(worker, "prepared_text", ""),
                getattr(worker, "prepared_language", ""),
            )
        if sequence < self._tts_next_play_sequence:
            return
        if sequence == self._tts_next_play_sequence:
            if self._tts_playing_sequence is None:
                self._tts_playing_sequence = sequence
                self._set_tts_bubble_playing(sequence)
            if self._tts_playing_sequence == sequence:
                self._tts_player.enqueue(audio, media_type)
                return
        self._tts_audio_buffers.setdefault(sequence, []).append((audio, media_type))

    def _on_tts_error(self, error_msg: str):
        logging.getLogger(__name__).warning("TTS error: %s", error_msg)

    def _on_tts_mouth_pose_changed(self, level: float, form: float):
        character = self._tts_characters.get(self._tts_playing_sequence)
        if character:
            publish_lip_sync(character, level, form)

    def _on_tts_playback_finished(self):
        self._release_tts_audio_in_order()
        self._start_next_tts_request()

    def _on_tts_worker_finished(self):
        worker = self.sender()
        sequence = getattr(worker, "sequence", None)
        generation = getattr(worker, "generation", None)
        if generation != self._tts_generation or sequence is None or self._tts_active_workers.get(sequence) is not worker:
            return
        self._tts_active_workers.pop(sequence, None)
        self._tts_completed_sequences.add(sequence)
        self._release_tts_audio_in_order()
        self._start_next_tts_request()

    def _release_tts_audio_in_order(self):
        if self._tts_playing_sequence is not None:
            if self._tts_playing_sequence not in self._tts_completed_sequences or not self._tts_player.is_idle():
                return
            sequence = self._tts_playing_sequence
            for audio, media_type in self._tts_audio_buffers.pop(sequence, []):
                self._tts_player.enqueue(audio, media_type)
            if not self._tts_player.is_idle():
                return
            self._tts_completed_sequences.remove(sequence)
            self._tts_next_play_sequence = sequence + 1
            self._tts_playing_sequence = None
            self._set_tts_bubble_playing(None)
            self._tts_bubbles.pop(sequence, None)
            self._tts_characters.pop(sequence, None)

        while self._tts_next_play_sequence in self._tts_completed_sequences and not self._tts_audio_buffers.get(self._tts_next_play_sequence):
            self._tts_bubbles.pop(self._tts_next_play_sequence, None)
            self._tts_characters.pop(self._tts_next_play_sequence, None)
            self._tts_completed_sequences.remove(self._tts_next_play_sequence)
            self._tts_next_play_sequence += 1

        buffers = self._tts_audio_buffers.pop(self._tts_next_play_sequence, [])
        if not buffers:
            return
        self._tts_playing_sequence = self._tts_next_play_sequence
        self._set_tts_bubble_playing(self._tts_playing_sequence)
        for audio, media_type in buffers:
            self._tts_player.enqueue(audio, media_type)

    def emit_action_for_ipc(self, character: str, action: str):
        publish_action(character, action)

    def handle_external_user_poke(self, event: dict):
        if not isinstance(event, dict):
            event = {}
        if str(event.get("direction", "") or "").strip().lower() == "to_user":
            return
        if str(event.get("source", "") or "").strip().lower() == "chat":
            return
        target = str(event.get("character", "") or "").strip() or self._character
        if self._is_group_chat:
            if target not in self._group_characters:
                return
        elif target != self._character:
            return
        self._send_poke_to_character(target)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _scroll_to_bottom_for_stream(self):
        if self._follow_stream_output:
            self._scroll_to_bottom()

    def _pause_stream_output_follow(self):
        self._follow_stream_output = False

    def _schedule_scroll_to_bottom_after_load(self):
        self._scroll_to_bottom_generation += 1
        generation = self._scroll_to_bottom_generation
        self._pending_scroll_to_bottom_generation = generation
        delays = (0, 30, 80, 160, 300, 500, 800, 1200)
        for delay in delays:
            QTimer.singleShot(
                delay,
                lambda generation=generation: self._scroll_to_bottom_for_generation(generation),
            )
        QTimer.singleShot(
            2000,
            lambda generation=generation: self._finish_scroll_to_bottom_for_generation(generation),
        )

    def _on_message_scroll_range_changed(self, _minimum: int, _maximum: int):
        generation = self._pending_scroll_to_bottom_generation
        if generation:
            QTimer.singleShot(
                0,
                lambda generation=generation: self._scroll_to_bottom_for_generation(generation),
            )
        elif self._follow_stream_output and self._current_bubble is not None:
            QTimer.singleShot(0, self._scroll_to_bottom_for_stream)

    def _on_message_scroll_value_changed(self, value: int):
        scrollbar = self._scroll.verticalScrollBar()
        self._follow_stream_output = value >= scrollbar.maximum()
        if not self._history_pagination_ready or self._history_loading:
            return
        if value <= scrollbar.minimum() + 48:
            self._load_older_messages()

    def _cancel_pending_scroll_to_bottom(self, _action: int = 0):
        self._pending_scroll_to_bottom_generation = 0

    def _scroll_to_bottom_for_generation(self, generation: int):
        if (
            generation != self._scroll_to_bottom_generation
            or generation != self._pending_scroll_to_bottom_generation
        ):
            return
        if self._scroll is None or self._msg_area is None:
            return
        if self.layout():
            self.layout().activate()
        if self._msg_area.layout():
            self._msg_area.layout().activate()
        self._relayout_message_bubbles(force=True)
        self._scroll_to_bottom()

    def _finish_scroll_to_bottom_for_generation(self, generation: int):
        if generation != self._pending_scroll_to_bottom_generation:
            return
        self._scroll_to_bottom_for_generation(generation)
        self._pending_scroll_to_bottom_generation = 0

    def position_next_to_pet(self, pet_window: QWidget):
        pet_geo = pet_window if isinstance(pet_window, QRect) else pet_window.geometry()
        screen = QApplication.screenAt(pet_geo.center()) or self.screen() or QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
        else:
            screen_geo = pet_geo

        chat_w = self.width()
        left_space = pet_geo.left() - screen_geo.left()
        right_space = screen_geo.right() - pet_geo.right()

        if left_space >= chat_w + 20:
            x = pet_geo.left() - chat_w - 16
        elif right_space >= chat_w + 20:
            x = pet_geo.right() + 16
        else:
            x = max(screen_geo.left(), pet_geo.left() - chat_w - 16)

        y = pet_geo.top() + (pet_geo.height() - self.height()) // 2
        y = max(screen_geo.top(), min(y, screen_geo.bottom() - self.height()))
        self.move(x, y)

    def closeEvent(self, event):
        if not self._closing:
            event.ignore()
            self._play_close_animation()
            return
        if self._close_waiting_for_workers:
            event.ignore()
            return
        workers_to_wait = []
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            workers_to_wait.append(self._worker)
        if self._group_plan_worker and self._group_plan_worker.isRunning():
            self._group_plan_worker.quit()
            workers_to_wait.append(self._group_plan_worker)
        if self._vision_fallback_worker and self._vision_fallback_worker.isRunning():
            self._vision_fallback_worker.requestInterruption()
            self._vision_fallback_worker.quit()
            workers_to_wait.append(self._vision_fallback_worker)
        self._attachment_import_queue.clear()
        if self._attachment_import_worker and self._attachment_import_worker.isRunning():
            self._attachment_import_worker.requestInterruption()
            workers_to_wait.append(self._attachment_import_worker)
        for worker in (self._asr_recorder_worker, self._asr_request_worker):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                workers_to_wait.append(worker)
        for worker in list(self._cancelled_workers):
            if worker is not None and worker.isRunning():
                workers_to_wait.append(worker)
        self._cancelled_workers.clear()
        for worker in list(self._tts_active_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
                workers_to_wait.append(worker)
        for worker in list(self._tts_translation_workers.values()):
            if worker.isRunning():
                worker.requestInterruption()
                workers_to_wait.append(worker)
        self._memory_generation += 1
        for worker in list(self._memory_workers):
            if worker.isRunning():
                worker.requestInterruption()
                workers_to_wait.append(worker)
        deadline = time.monotonic() + 1.5
        for worker in workers_to_wait:
            remaining_ms = int(max(0.0, deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            worker.wait(min(remaining_ms, 250))
        still_running = [worker for worker in workers_to_wait if worker is not None and worker.isRunning()]
        if still_running:
            event.ignore()
            self._close_waiting_for_workers = True
            self.setEnabled(False)
            def retry_close():
                self._close_waiting_for_workers = False
                if self._closing:
                    self.close()
            QTimer.singleShot(1000, retry_close)
            return
        self._cancelled_workers.clear()
        self._memory_workers.clear()
        self._stream_flush_timer.stop()
        self._tts_player.stop()
        self._db.close()
        if self._cfg and hasattr(self, '_pre_close_geometry'):
            geo = self._pre_close_geometry
            self._cfg.set("chat_window_x", geo.x())
            self._cfg.set("chat_window_y", geo.y())
            self._cfg.set("chat_window_width", geo.width())
            self._cfg.set("chat_window_height", geo.height())
            self._cfg.save()
        self.closed.emit()
        super().closeEvent(event)
