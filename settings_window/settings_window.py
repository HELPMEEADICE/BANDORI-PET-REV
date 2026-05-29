from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *
from settings_window.pages.llm import LLMPageMixin
from settings_window.pages.tts import TTSPageMixin
from settings_window.pages.pov import POVPageMixin
from settings_window.pages.memory import MemoryPageMixin
from settings_window.pages.reminder import ReminderPageMixin
from settings_window.pages.compact import CompactPageMixin
from settings_window.pages.chat_integration import ChatIntegrationPageMixin
from settings_window.pages.mcp import MCPPageMixin
from settings_window.pages.data import DataManagementPageMixin
from settings_window.pages.quality import QualityPageMixin
from settings_window.pages.about import AboutPageMixin
from settings_window.pages.behavior import BehaviorPageMixin


class SettingsWindow(
    LLMPageMixin,
    TTSPageMixin,
    POVPageMixin,
    MemoryPageMixin,
    ReminderPageMixin,
    CompactPageMixin,
    ChatIntegrationPageMixin,
    MCPPageMixin,
    DataManagementPageMixin,
    QualityPageMixin,
    AboutPageMixin,
    BehaviorPageMixin,
    QWidget,
):

    model_selected = Signal(str, str)
    settings_changed = Signal(dict)
    launch_requested = Signal()
    exit_requested = Signal()

    def __init__(self, model_manager, current_char="", current_costume="",
                 current_fps=120, current_opacity=1.0, show_launch=True,
                 start_on_costumes=False, first_run_wizard=False,
                 config_manager=None, vsync=True, live2d_module=None):
        super().__init__()
        self._model_manager = model_manager
        self._live2d = live2d_module
        characters = model_manager.characters
        self._current_char = current_char or (characters[0] if start_on_costumes and characters else "")
        self._current_costume = current_costume
        self._fps = current_fps
        self._opacity = current_opacity
        self._cfg = config_manager
        self._costume_buttons: list[CostumeItem] = []
        self._selection_cards: list[QWidget] = []
        self._selected_costume = ""
        self._configured_models = self._load_configured_models()
        self._picker_state = self._load_model_picker_state()
        self._character_search_text = ""
        self._character_filter = MODEL_PICKER_FILTER_ALL
        self._costume_search_text = ""
        self._costume_filter = MODEL_PICKER_FILTER_ALL
        self._costume_empty_label = None
        self._selected_list_character = ""
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = False
        if self._current_char:
            self._selected_list_character = self._current_char
        elif self._configured_models:
            self._selected_list_character = self._configured_models[0]["character"]
            self._current_char = self._selected_list_character
            self._current_costume = self._configured_models[0]["costume"]
        self._selected_band = model_manager.get_character_band(self._current_char)
        self._preview_bubble = None
        self._preview_pinned_key = ""
        self._preview_pinned_anchor = None
        self._preview_hover_key = ""
        self._owns_live2d = False
        self._live2d_error_shown = False
        self._show_launch = show_launch
        self._start_on_costumes = start_on_costumes
        self._first_run_wizard = bool(first_run_wizard)
        self._wizard_step = 0
        self._wizard_step_labels: list[BodyLabel] = []
        self._model_download_worker = None
        self._model_download_running = False
        self._wizard_pages: dict[str, QWidget] = {}
        self._theme_widgets: list[QWidget] = []
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, NavButton] = {}
        self._char_page = None
        self._costume_page = None
        self._llm_page = None
        self._tts_page = None
        self._pov_page = None
        self._memory_page = None
        self._relationship_guide_page = None
        self._reminder_page = None
        self._memory_db = None
        self._memory_items: list[dict] = []
        self._selected_memory_id = 0
        self._behavior_page = None
        self._compact_window_page = None
        self._chat_integration_page = None
        self._mcp_computer_page = None
        self._data_management_page = None
        self._quality_page = None
        self._about_page = None
        self._current_page = "characters"
        self._selecting_model = False
        self._vsync = vsync
        self._game_topmost = bool(self._cfg.get("game_topmost", False)) if self._cfg else False
        self._chat_window_normal_window = (
            bool(self._cfg.get("chat_window_normal_window", False)) if self._cfg else False
        )
        self._hide_live2d_model = (
            bool(self._cfg.get("hide_live2d_model", False)) if self._cfg else False
        )
        self._live2d_idle_actions_enabled = (
            bool(self._cfg.get("live2d_idle_actions_enabled", True)) if self._cfg else True
        )
        self._live2d_head_tracking_enabled = (
            bool(self._cfg.get("live2d_head_tracking_enabled", True)) if self._cfg else True
        )
        self._live2d_mutual_gaze_enabled = (
            bool(self._cfg.get("live2d_mutual_gaze_enabled", False)) if self._cfg else False
        )
        self._auto_start_supported = is_startup_supported()
        self._auto_start_enabled = False
        if self._auto_start_supported:
            self._auto_start_enabled = is_startup_enabled()
        self._live2d_quality = normalize_live2d_quality(
            self._cfg.get("live2d_quality", "balanced") if self._cfg else "balanced"
        )
        self._live2d_scale = clamp_live2d_scale(
            self._cfg.get("live2d_scale", 0) if self._cfg else 0,
            use_device_pixel_ratio_default=True,
        )
        self._saved_user_name = ""
        self._user_avatar_path_pending = ""
        self._loading_user_profile = False
        self._loading_llm_profile = False
        self._compact_window_reset_position_pending = False

        icon_path = _app_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowTitle(_tr("SettingsWindow.title"))
        self.setMinimumSize(1180, 680)
        self.resize(1180, 680)

        self._launched = False
        self._init_ui()
        QApplication.instance().installEventFilter(self)

        if self._current_costume:
            self._selected_costume = self._current_costume
        else:
            self._selected_costume = self._model_manager.get_default_costume(
                self._current_char
            )

        if self._first_run_wizard:
            self._setup_first_run_wizard()
        elif self._start_on_costumes:
            self._nav_buttons["characters"].setChecked(True)
            self._selecting_model = True
            self._populate_costumes(self._current_char)
            display = self._model_manager.get_display_name(self._current_char)
            self._costume_title.setText(_tr("SettingsWindow.costumes_title", display=display))
            self._costume_subtitle.setText(_tr("SettingsWindow.costume_subtitle", display=display))
            self._char_page.hide()
            self._costume_page.show()
        else:
            self._nav_buttons["characters"].setChecked(True)
            if self._selected_list_character:
                self._show_model_detail()
            else:
                self._enter_model_selection()
        self._refresh_model_list()

    def _load_configured_models(self) -> list[dict]:
        models = self._cfg.get("models", []) if self._cfg else []
        result = []
        seen = set()
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict):
                    continue
                character = item.get("character", "")
                costume = item.get("costume", "")
                if character in seen or character not in self._model_manager.characters:
                    continue
                if not costume:
                    costume = self._model_manager.get_default_costume(character)
                path = self._model_manager.get_model_json_path(character, costume)
                if not path:
                    continue
                entry = dict(item)
                entry.update({"character": character, "costume": costume, "path": path})
                self._restore_model_action_profile(entry, prefer_existing=True)
                entry["click_motion_actions"] = normalize_click_motion_actions(
                    entry.get("click_motion_actions", {})
                )
                if entry.get("pet_mode") not in {"live2d", "pixel"}:
                    entry["pet_mode"] = "live2d"
                result.append(entry)
                seen.add(character)
        if self._current_char and self._current_char not in seen:
            costume = self._current_costume or self._model_manager.get_default_costume(self._current_char)
            path = self._model_manager.get_model_json_path(self._current_char, costume)
            if path:
                pet_mode = self._cfg.get("pet_mode", "live2d") if self._cfg else "live2d"
                if pet_mode not in {"live2d", "pixel"}:
                    pet_mode = "live2d"
                result.insert(0, {
                    "character": self._current_char,
                    "costume": costume,
                    "path": path,
                    "window_x": self._cfg.get("window_x", -1) if self._cfg else -1,
                    "window_y": self._cfg.get("window_y", -1) if self._cfg else -1,
                    "window_width": self._cfg.get("window_width", 400) if self._cfg else 400,
                    "window_height": self._cfg.get("window_height", 500) if self._cfg else 500,
                    "pixel_window_x": self._cfg.get("pixel_window_x", -1) if self._cfg else -1,
                    "pixel_window_y": self._cfg.get("pixel_window_y", -1) if self._cfg else -1,
                    "pet_mode": pet_mode,
                    "click_motion_actions": {},
                })
        return result

    def _load_model_picker_state(self) -> dict:
        raw = self._cfg.get(MODEL_PICKER_STATE_KEY, {}) if self._cfg else {}
        if not isinstance(raw, dict):
            raw = {}
        valid_chars = set(self._model_manager.characters)
        state = {
            "recent_characters": self._clean_character_list(raw.get("recent_characters", []), valid_chars),
            "favorite_characters": self._clean_character_list(raw.get("favorite_characters", []), valid_chars),
            "recent_costumes": self._clean_costume_key_list(raw.get("recent_costumes", [])),
            "favorite_costumes": self._clean_costume_key_list(raw.get("favorite_costumes", [])),
        }
        state["recent_characters"] = state["recent_characters"][:MODEL_PICKER_RECENT_LIMIT]
        state["recent_costumes"] = state["recent_costumes"][:MODEL_PICKER_RECENT_LIMIT]
        return state

    @staticmethod
    def _clean_character_list(value, valid_chars: set[str]) -> list[str]:
        result = []
        seen = set()
        if not isinstance(value, list):
            return result
        for item in value:
            key = str(item or "").strip()
            if key and key in valid_chars and key not in seen:
                result.append(key)
                seen.add(key)
        return result

    def _clean_costume_key_list(self, value) -> list[str]:
        result = []
        seen = set()
        if not isinstance(value, list):
            return result
        for item in value:
            key = str(item or "").strip()
            if key and key not in seen and self._costume_key_exists(key):
                result.append(key)
                seen.add(key)
        return result

    def _costume_key_exists(self, key: str) -> bool:
        character, costume = self._split_costume_key(key)
        return bool(character and costume and self._model_manager.get_model_json_path(character, costume))

    @staticmethod
    def _costume_key(character: str, costume: str) -> str:
        return f"{character}:{costume}"

    @staticmethod
    def _split_costume_key(key: str) -> tuple[str, str]:
        if ":" not in key:
            return "", ""
        character, costume = key.split(":", 1)
        return character, costume

    def _save_model_picker_state(self):
        if not self._cfg:
            return
        self._cfg.set(MODEL_PICKER_STATE_KEY, {
            "recent_characters": list(self._picker_state.get("recent_characters", [])),
            "favorite_characters": list(self._picker_state.get("favorite_characters", [])),
            "recent_costumes": list(self._picker_state.get("recent_costumes", [])),
            "favorite_costumes": list(self._picker_state.get("favorite_costumes", [])),
        })
        self._cfg.save()

    def _remember_character(self, character: str):
        if not character:
            return
        recent = [item for item in self._picker_state.get("recent_characters", []) if item != character]
        recent.insert(0, character)
        self._picker_state["recent_characters"] = recent[:MODEL_PICKER_RECENT_LIMIT]
        self._save_model_picker_state()

    def _remember_costume(self, character: str, costume: str):
        if not character or not costume:
            return
        key = self._costume_key(character, costume)
        recent = [item for item in self._picker_state.get("recent_costumes", []) if item != key]
        recent.insert(0, key)
        self._picker_state["recent_costumes"] = recent[:MODEL_PICKER_RECENT_LIMIT]
        self._save_model_picker_state()

    def _is_favorite_character(self, character: str) -> bool:
        return character in self._picker_state.get("favorite_characters", [])

    def _is_favorite_costume(self, character: str, costume: str) -> bool:
        return self._costume_key(character, costume) in self._picker_state.get("favorite_costumes", [])

    def _set_character_favorite(self, character: str, favorite: bool):
        favorites = [item for item in self._picker_state.get("favorite_characters", []) if item != character]
        if favorite and character:
            favorites.insert(0, character)
        self._picker_state["favorite_characters"] = favorites
        self._save_model_picker_state()
        self._refresh_visible_character_favorites(character, favorite)

    def _set_costume_favorite(self, costume: str, favorite: bool):
        if not self._current_char or not costume:
            return
        key = self._costume_key(self._current_char, costume)
        favorites = [item for item in self._picker_state.get("favorite_costumes", []) if item != key]
        if favorite:
            favorites.insert(0, key)
        self._picker_state["favorite_costumes"] = favorites
        self._save_model_picker_state()
        if self._costume_filter == MODEL_PICKER_FILTER_FAVORITES:
            self._populate_costumes(self._current_char)

    def _refresh_visible_character_favorites(self, character: str, favorite: bool):
        for card in self._selection_cards:
            if isinstance(card, CharacterCard) and getattr(card, "_char_key", "") == character:
                card.set_favorite(favorite)
        if self._character_filter == MODEL_PICKER_FILTER_FAVORITES:
            self._refresh_character_selection_view()

    def _restore_model_action_profile(self, entry: dict, prefer_existing: bool = False):
        if not self._cfg or not hasattr(self._cfg, "get_model_action_profile"):
            return
        profile = self._cfg.get_model_action_profile(
            entry.get("character", ""),
            entry.get("costume", ""),
        )
        if not profile:
            return
        for key in ("default_motion", "default_expression", "click_motion_actions"):
            if prefer_existing and entry.get(key):
                continue
            if profile.get(key):
                entry[key] = profile[key]

    def _archive_model_action_profile(self, entry: dict):
        if not self._cfg or not hasattr(self._cfg, "set_model_action_profile"):
            return
        self._cfg.set_model_action_profile(
            entry.get("character", ""),
            entry.get("costume", ""),
            entry,
        )

    def _on_language_changed(self, index: int):
        lang = normalize_language(self._lang_combo.itemData(index))
        if lang and lang != current_language():
            set_language(lang)
            if self._cfg:
                self._cfg.set("language", lang)
                self._cfg.save()

    def closeEvent(self, event):
        should_exit_app = self._first_run_wizard and self._show_launch and not self._launched
        if should_exit_app:
            self.exit_requested.emit()
        self._dispose_live2d_preview()
        self._cleanup_workers()
        if self._memory_db is not None:
            try:
                self._memory_db.close()
            except Exception:
                pass
            self._memory_db = None
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def _ensure_live2d_preview_module(self):
        if self._live2d:
            return self._live2d
        try:
            from live2d_lua_adapter import live2d

            self._live2d = live2d
            self._owns_live2d = True
            return self._live2d
        except Exception as exc:
            if not self._live2d_error_shown:
                self._live2d_error_shown = True
                InfoBar.error(
                    _tr("SettingsWindow.preview_failed_title"),
                    _tr("SettingsWindow.preview_failed_content", error=str(exc)),
                    duration=4000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            return None

    def _dispose_live2d_preview(self):
        self._hide_costume_preview()
        if self._preview_bubble is not None:
            self._preview_bubble.close()
            self._preview_bubble.deleteLater()
            self._preview_bubble = None
        if self._owns_live2d and self._live2d is not None:
            try:
                self._live2d.dispose()
            except Exception:
                pass
            self._live2d = None
            self._owns_live2d = False

    def eventFilter(self, watched, event):
        if not isinstance(event, QKeyEvent):
            return super().eventFilter(watched, event)

        event_type = event.type()
        if event_type == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Shift:
            self._hide_hover_costume_preview()
        elif event_type == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Shift:
            widget = QApplication.widgetAt(QCursor.pos())
            while widget is not None:
                if isinstance(widget, CostumeItem):
                    self._show_costume_preview(widget, widget.costume_id)
                    break
                widget = widget.parentWidget()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(80, self._play_entrance)
            QTimer.singleShot(120, lambda: self._animate_indicator(self._current_page))

    def _play_entrance(self):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start()

    @staticmethod
    def _animate_button_in(btn):
        if btn is None or not isValid(btn):
            return
        effect = QGraphicsOpacityEffect(btn)
        effect.setOpacity(0.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", btn)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: btn.setGraphicsEffect(None) if isValid(btn) else None)
        anim.start()

    def _cleanup_workers(self):
        for attr in ('_test_worker', '_fetch_worker', '_mcp_test_worker', '_update_check_worker', '_update_apply_worker', '_tts_test_worker', '_model_download_worker'):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                if not worker.wait(2000):
                    worker.terminate()
                    worker.wait(1000)
        player = getattr(self, '_tts_test_player', None)
        if player is not None:
            player.stop()

    def _make_theme_widget(self, w: QWidget) -> QWidget:
        w.setAutoFillBackground(True)
        self._theme_widgets.append(w)
        self._apply_theme_bg(w)
        return w

    def _apply_theme_bg(self, w: QWidget):
        bg = _BG_DARK if isDarkTheme() else _BG_LIGHT
        pal = w.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        w.setPalette(pal)
        w.update()

    def _update_all_theme_bgs(self):
        for w in self._theme_widgets:
            self._apply_theme_bg(w)

    @staticmethod
    def _refresh_theme_widget_styles(widget: QWidget | None):
        if widget is None:
            return
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()

    def _refresh_json_code_edit_theme(self, edit: JsonCodeEdit | None):
        if edit is None:
            return
        self._refresh_theme_widget_styles(edit)
        self._refresh_theme_widget_styles(edit.viewport())
        self._refresh_theme_widget_styles(edit._line_number_area)

    def _init_ui(self):
        if self._first_run_wizard:
            self._init_first_run_wizard_ui()
            return

        self._make_theme_widget(self)
        qconfig.themeChanged.connect(self._update_all_theme_bgs)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        main_layout.addWidget(sidebar, 0)

        right_area = QWidget()
        right_layout = QHBoxLayout(right_area)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(16)

        self._page_stack = self._make_theme_widget(QWidget())
        self._page_stack_layout = QVBoxLayout(self._page_stack)
        self._page_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._page_stack_layout.setSpacing(0)

        self._char_page = self._build_char_page()
        self._costume_page = self._build_costume_page()
        self._costume_page.hide()

        self._page_stack_layout.addWidget(self._char_page)
        self._page_stack_layout.addWidget(self._costume_page)

        self._pages["characters"] = self._char_page
        self._pages["costumes"] = self._costume_page

        page_scroll = ScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setWidget(self._page_stack)
        page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._reserve_overlay_scrollbar(page_scroll)

        side_panel = self._build_side_panel()

        self._ensure_page("quality")

        right_layout.addWidget(page_scroll, 1)
        right_layout.addWidget(side_panel, 0)

        main_layout.addWidget(right_area, 1)

    def _init_first_run_wizard_ui(self):
        self._make_theme_widget(self)
        qconfig.themeChanged.connect(self._update_all_theme_bgs)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 18, 20, 18)
        main_layout.setSpacing(14)

        header = self._make_theme_widget(QWidget(self))
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        title = TitleLabel(_tr("SettingsWindow.wizard_title", default="首次启动向导"), header)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.wizard_subtitle",
            default="按顺序完成模型包、角色服装和可选 AI/TTS 配置，之后就可以启动桌宠。",
        ), header))
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)

        step_row = QHBoxLayout()
        step_row.setContentsMargins(0, 4, 0, 0)
        step_row.setSpacing(8)
        self._wizard_step_labels = []
        for text in (
            _tr("SettingsWindow.wizard_step_models", default="1 模型包"),
            _tr("SettingsWindow.wizard_step_character", default="2 角色/服装"),
            _tr("SettingsWindow.wizard_step_ai", default="3 AI/TTS"),
        ):
            label = BodyLabel(text, header)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFixedHeight(30)
            label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            self._wizard_step_labels.append(label)
            step_row.addWidget(label)
        header_layout.addLayout(step_row)
        main_layout.addWidget(header)

        self._wizard_stack = self._make_theme_widget(QWidget(self))
        self._wizard_stack_layout = QVBoxLayout(self._wizard_stack)
        self._wizard_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._wizard_stack_layout.setSpacing(0)

        self._wizard_model_page = self._build_wizard_model_page()
        self._char_page = self._build_char_page()
        self._costume_page = self._build_costume_page()
        self._costume_page.hide()

        self._pov_page = self._build_pov_page()
        self._pov_page.hide()
        self._llm_page = self._build_llm_page()
        self._tts_page = self._build_tts_page()
        self._wizard_ai_page = self._build_wizard_ai_page()

        for page in (self._wizard_model_page, self._char_page, self._costume_page, self._wizard_ai_page):
            self._wizard_stack_layout.addWidget(page)
            page.hide()

        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._reserve_overlay_scrollbar(scroll)
        scroll.setWidget(self._wizard_stack)
        main_layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self._wizard_back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.wizard_back", default="上一步"), self)
        self._wizard_back_btn.setFixedHeight(36)
        self._wizard_back_btn.clicked.connect(self._wizard_previous_step)
        footer.addWidget(self._wizard_back_btn)
        footer.addStretch()
        self._wizard_skip_ai_btn = PushButton(_tr("SettingsWindow.wizard_skip_ai", default="跳过 AI/TTS，启动"), self)
        self._wizard_skip_ai_btn.setFixedHeight(36)
        self._wizard_skip_ai_btn.clicked.connect(self._on_apply)
        footer.addWidget(self._wizard_skip_ai_btn)
        self._wizard_next_btn = PrimaryPushButton(
            FluentIcon.ACCEPT,
            _tr("SettingsWindow.wizard_next", default="下一步"),
            self,
        )
        self._wizard_next_btn.setFixedHeight(36)
        self._wizard_next_btn.clicked.connect(self._wizard_next_step)
        footer.addWidget(self._wizard_next_btn)
        main_layout.addLayout(footer)

        self._wizard_hidden_side_panel = self._build_side_panel()
        self._wizard_hidden_side_panel.hide()
        self._pages["characters"] = self._char_page
        self._pages["costumes"] = self._costume_page
        self._pages["llm"] = self._llm_page
        self._pages["tts"] = self._tts_page
        self._pages["pov"] = self._pov_page

        self._update_wizard_style()
        qconfig.themeChanged.connect(self._update_wizard_style)

    def _build_wizard_model_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = TitleLabel(_tr("SettingsWindow.wizard_models_title", default="检测模型包"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.wizard_models_subtitle",
            default="自动检测 models 文件夹中的角色包，缺失时可一键下载全部模型包。",
        ), page))
        layout.addWidget(subtitle)

        guide = CardWidget(page)
        guide_layout = QVBoxLayout(guide)
        guide_layout.setContentsMargins(16, 14, 16, 14)
        guide_layout.setSpacing(10)
        guide_layout.addWidget(StrongBodyLabel(_tr("SettingsWindow.wizard_models_place_title", default="正确放置方式"), guide))
        guide_text = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.wizard_models_place_content",
            default="下载模型包后请先解压，然后把解压出的角色 .zst 压缩包或角色文件夹直接放进项目目录的 models 文件夹，或使用下方的自动下载功能。",
        ), guide))
        guide_layout.addWidget(guide_text)
        self._wizard_model_detect_label = _wrap_label(BodyLabel("", guide))
        self._wizard_model_missing_label = _wrap_label(BodyLabel("", guide))
        guide_layout.addWidget(self._wizard_model_detect_label)
        guide_layout.addWidget(self._wizard_model_missing_label)
        layout.addWidget(guide)

        self._wizard_model_status_card = CardWidget(page)
        status_layout = QVBoxLayout(self._wizard_model_status_card)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setSpacing(8)
        self._wizard_model_status_title = StrongBodyLabel("", self._wizard_model_status_card)
        self._wizard_model_status_label = _wrap_label(BodyLabel("", self._wizard_model_status_card))
        self._wizard_model_nested_label = _wrap_label(BodyLabel("", self._wizard_model_status_card))
        status_layout.addWidget(self._wizard_model_status_title)
        status_layout.addWidget(self._wizard_model_status_label)
        status_layout.addWidget(self._wizard_model_nested_label)
        self._wizard_model_progress = ProgressBar(self._wizard_model_status_card)
        self._wizard_model_progress.setRange(0, 100)
        self._wizard_model_progress.setValue(0)
        self._wizard_model_progress.hide()
        self._wizard_model_download_label = _wrap_label(BodyLabel("", self._wizard_model_status_card))
        self._wizard_model_download_label.hide()
        status_layout.addWidget(self._wizard_model_progress)
        status_layout.addWidget(self._wizard_model_download_label)
        layout.addWidget(self._wizard_model_status_card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._wizard_download_missing_btn = PrimaryPushButton(
            FluentIcon.DOWNLOAD,
            _tr("SettingsWindow.wizard_models_download", default="一键下载"),
            page,
        )
        self._wizard_download_missing_btn.setFixedHeight(36)
        self._wizard_download_missing_btn.clicked.connect(self._start_download_model_packages)
        btn_row.addWidget(self._wizard_download_missing_btn)
        open_models_btn = PushButton(_tr("SettingsWindow.wizard_models_open_folder", default="打开 models 文件夹"), page)
        open_models_btn.setFixedHeight(36)
        open_models_btn.clicked.connect(self._open_models_dir)
        btn_row.addWidget(open_models_btn)
        self._wizard_open_nested_btn = PushButton(_tr("SettingsWindow.wizard_models_open_nested", default="打开错误嵌套目录"), page)
        self._wizard_open_nested_btn.setFixedHeight(36)
        self._wizard_open_nested_btn.clicked.connect(self._open_nested_models_dir)
        btn_row.addWidget(self._wizard_open_nested_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        fix_row = QHBoxLayout()
        fix_row.setSpacing(8)
        self._wizard_fix_nested_btn = PrimaryPushButton(
            FluentIcon.ACCEPT,
            _tr("SettingsWindow.wizard_models_fix_nested", default="一键整理到正确位置"),
            page,
        )
        self._wizard_fix_nested_btn.setFixedHeight(36)
        self._wizard_fix_nested_btn.clicked.connect(self._fix_nested_models_dir)
        fix_row.addWidget(self._wizard_fix_nested_btn)
        recheck_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.wizard_models_recheck", default="重新检测"), page)
        recheck_btn.setFixedHeight(36)
        recheck_btn.clicked.connect(self._recheck_model_resources)
        fix_row.addWidget(recheck_btn)
        fix_row.addStretch()
        layout.addLayout(fix_row)
        layout.addStretch()
        return page

    def _build_wizard_ai_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        title = TitleLabel(_tr("SettingsWindow.wizard_ai_title", default="可选配置 AI / TTS"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.wizard_ai_subtitle",
            default="这些配置可以先跳过，以后也能在设置页里继续调整。",
        ), page))
        layout.addWidget(subtitle)
        layout.addWidget(self._llm_page)
        layout.addWidget(self._tts_page)
        layout.addStretch()
        return page

    def _setup_first_run_wizard(self):
        self._recheck_model_resources(show_message=False)
        if self._has_available_model_resources():
            if self._selected_list_character:
                self._show_model_detail()
            else:
                self._enter_model_selection()
            self._wizard_go_to_step(1)
        else:
            self._wizard_go_to_step(0)

    def _wizard_go_to_step(self, step: int):
        self._wizard_step = max(0, min(2, int(step)))
        for page in (self._wizard_model_page, self._char_page, self._costume_page, self._wizard_ai_page):
            page.hide()
        if self._wizard_step == 0:
            self._wizard_model_page.show()
        elif self._wizard_step == 1:
            if self._current_page == "costumes":
                self._costume_page.show()
            else:
                self._char_page.show()
        else:
            self._wizard_ai_page.show()
        self._update_wizard_footer()
        self._update_wizard_style()

    def _wizard_next_step(self):
        if self._wizard_step == 0:
            self._recheck_model_resources(show_message=False)
            if not self._has_available_model_resources():
                InfoBar.warning(
                    _tr("SettingsWindow.wizard_models_missing_title", default="还没有检测到模型"),
                    _tr("SettingsWindow.wizard_models_missing_content", default="请先点击一键下载模型包，或把角色 .zst 文件放入 models 文件夹。"),
                    duration=3500,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            self._enter_model_selection()
            self._wizard_go_to_step(1)
            return
        if self._wizard_step == 1:
            selected = self._selected_model_item()
            if not selected:
                InfoBar.warning(
                    _tr("SettingsWindow.launch_missing_model_title"),
                    _tr("SettingsWindow.launch_missing_model_content"),
                    duration=2500,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            self._current_char = selected["character"]
            self._selected_costume = selected["costume"]
            self._wizard_go_to_step(2)
            return
        self._on_apply()

    def _wizard_previous_step(self):
        if self._wizard_step <= 0:
            return
        self._wizard_go_to_step(self._wizard_step - 1)

    def _update_wizard_footer(self):
        self._wizard_back_btn.setEnabled(self._wizard_step > 0)
        self._wizard_skip_ai_btn.setVisible(self._wizard_step == 2)
        self._wizard_next_btn.setEnabled(not self._model_download_running)
        if self._wizard_step == 2:
            self._wizard_next_btn.setText(_tr("SettingsWindow.wizard_save_launch", default="保存并启动"))
        else:
            self._wizard_next_btn.setText(_tr("SettingsWindow.wizard_next", default="下一步"))

    def _update_wizard_style(self):
        dark = isDarkTheme()
        active_bg = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        inactive_bg = "#2a2a2a" if dark else "#eef0f4"
        active_text = "#ffffff"
        inactive_text = "#d9dce4" if dark else "#4f5968"
        for idx, label in enumerate(self._wizard_step_labels):
            active = idx == self._wizard_step
            label.setStyleSheet(f"""
                BodyLabel {{
                    background: {active_bg if active else inactive_bg};
                    color: {active_text if active else inactive_text};
                    border-radius: 8px;
                    font-weight: 700;
                }}
            """)

    def _available_model_count(self) -> int:
        count = 0
        for character in self._model_manager.characters:
            for costume in self._model_manager.get_costumes(character):
                costume_id = costume.get("id", "")
                if costume_id and self._model_manager.get_model_json_path(character, costume_id):
                    count += 1
        return count

    def _has_available_model_resources(self) -> bool:
        return self._available_model_count() > 0

    def _nested_models_dir(self):
        return MODELS_DIR / "models"

    def _nested_models_entries(self) -> list:
        nested = self._nested_models_dir()
        if not nested.is_dir():
            return []
        return [entry for entry in nested.iterdir() if not entry.name.startswith(".")]

    def _expected_model_package_keys(self) -> list[str]:
        outfit_path = app_base_dir() / "outfit.json"
        try:
            data = json.loads(outfit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        characters = data.get("characters", {})
        if not isinstance(characters, dict):
            return []
        return sorted(str(key) for key in characters if str(key).strip())

    def _installed_model_package_keys(self) -> set[str]:
        return {
            character
            for character in self._model_manager.characters
            if self._model_manager.get_costumes(character)
        }

    def _missing_model_package_keys(self) -> list[str]:
        installed = self._installed_model_package_keys()
        return [key for key in self._expected_model_package_keys() if key not in installed]

    def _open_models_dir(self):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(MODELS_DIR.resolve())))

    def _open_nested_models_dir(self):
        nested = self._nested_models_dir()
        if nested.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(nested.resolve())))

    def _recheck_model_resources(self, show_message: bool = True):
        self._model_manager = ModelManager()
        self._configured_models = self._load_configured_models()
        if self._current_char not in self._model_manager.characters:
            self._current_char = ""
            self._current_costume = ""
            self._selected_costume = ""
            self._selected_list_character = ""
        self._selected_band = self._model_manager.get_character_band(self._current_char)
        self._refresh_model_list()
        if self._has_available_model_resources():
            if not self._current_char and self._model_manager.characters:
                self._enter_model_selection()
        self._update_wizard_model_status()
        if show_message:
            title = (
                _tr("SettingsWindow.wizard_models_ready_title", default="已检测到模型")
                if self._has_available_model_resources()
                else _tr("SettingsWindow.wizard_models_missing_title", default="还没有检测到模型")
            )
            content = (
                _tr("SettingsWindow.wizard_models_ready_content", default="可以继续选择角色和服装。")
                if self._has_available_model_resources()
                else _tr("SettingsWindow.wizard_models_missing_content", default="请先点击一键下载模型包，或把角色 .zst 文件放入 models 文件夹。")
            )
            bar = InfoBar.success if self._has_available_model_resources() else InfoBar.warning
            bar(title, content, duration=3000, position=InfoBarPosition.TOP, parent=self)
        self._update_wizard_footer()

    def _update_wizard_model_status(self):
        if not hasattr(self, "_wizard_model_status_label"):
            return
        count = self._available_model_count()
        nested_entries = self._nested_models_entries()
        expected_keys = self._expected_model_package_keys()
        installed_keys = self._installed_model_package_keys()
        missing_keys = [key for key in expected_keys if key not in installed_keys]
        if hasattr(self, "_wizard_model_detect_label"):
            self._wizard_model_detect_label.setText(_tr(
                "SettingsWindow.wizard_models_detect_detail",
                default="已检测到 {installed}/{total} 个角色模型包。",
                installed=len(installed_keys),
                total=len(expected_keys),
            ))
        if hasattr(self, "_wizard_model_missing_label"):
            if missing_keys:
                self._wizard_model_missing_label.setText(_tr(
                    "SettingsWindow.wizard_models_missing_packages",
                    default="缺失 {count} 个：{items}{more}",
                    count=len(missing_keys),
                    items=", ".join(missing_keys[:10]),
                    more=" ..." if len(missing_keys) > 10 else "",
                ))
            else:
                self._wizard_model_missing_label.setText(_tr(
                    "SettingsWindow.wizard_models_all_packages_ready",
                    default="全部角色模型包已就绪。",
                ))
        if count:
            self._wizard_model_status_title.setText(_tr("SettingsWindow.wizard_models_ready_title", default="已检测到模型"))
            self._wizard_model_status_label.setText(_tr(
                "SettingsWindow.wizard_models_ready_detail",
                default="当前检测到 {count} 个可用角色/服装模型，可以进入下一步。",
                count=count,
            ))
        else:
            self._wizard_model_status_title.setText(_tr("SettingsWindow.wizard_models_missing_title", default="还没有检测到模型"))
            self._wizard_model_status_label.setText(_tr(
                "SettingsWindow.wizard_models_missing_detail",
                default="请把解压后的角色 .zst 压缩包或角色文件夹放到：{path}",
                path=str(MODELS_DIR.resolve()),
            ))
        if nested_entries:
            self._wizard_model_nested_label.setText(_tr(
                "SettingsWindow.wizard_models_nested_detected",
                default="检测到 {count} 个文件/文件夹位于 models/models，可能是多套了一层 models 文件夹。",
                count=len(nested_entries),
            ))
        else:
            self._wizard_model_nested_label.setText(_tr(
                "SettingsWindow.wizard_models_nested_clear",
                default="没有检测到 models/models 嵌套目录。",
            ))
        self._wizard_open_nested_btn.setVisible(bool(nested_entries))
        self._wizard_fix_nested_btn.setVisible(bool(nested_entries))
        if hasattr(self, "_wizard_download_missing_btn"):
            self._wizard_download_missing_btn.setEnabled(bool(missing_keys) and not self._model_download_running)
            self._wizard_download_missing_btn.setText(
                _tr("SettingsWindow.wizard_models_downloading", default="正在下载...")
                if self._model_download_running
                else _tr("SettingsWindow.wizard_models_download", default="一键下载")
            )

    def _start_download_model_packages(self):
        if self._model_download_running:
            return
        missing_keys = self._missing_model_package_keys()
        if not missing_keys:
            InfoBar.success(
                _tr("SettingsWindow.wizard_models_ready_title", default="已检测到模型"),
                _tr("SettingsWindow.wizard_models_all_packages_ready", default="全部角色模型包已就绪。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._model_download_running = True
        self._wizard_model_progress.setRange(0, 0)
        self._wizard_model_progress.setValue(0)
        self._wizard_model_progress.show()
        self._wizard_model_download_label.setText(_tr(
            "SettingsWindow.wizard_models_download_start",
            default="准备下载 {count} 个模型包...",
            count=len(missing_keys),
        ))
        self._wizard_model_download_label.show()
        self._update_wizard_model_status()
        self._update_wizard_footer()

        worker = ModelPackageDownloadWorker(missing_keys, MODELS_DIR, parent=self)
        self._model_download_worker = worker
        worker.progress.connect(self._on_model_download_progress)
        worker.finished.connect(self._on_model_download_finished)
        worker.error.connect(self._on_model_download_error)
        worker.start()

    def _on_model_download_progress(self, info: dict):
        total_bytes = int(info.get("total_bytes") or 0)
        downloaded_bytes = int(info.get("downloaded_bytes") or 0)
        known_count = int(info.get("known_count") or 0)
        total_count = int(info.get("total") or 0)
        if total_bytes > 0 and known_count > 0 and total_count > 0:
            estimated_total = max(total_bytes / known_count * total_count, total_bytes)
            self._wizard_model_progress.setRange(0, 100)
            self._wizard_model_progress.setValue(min(99, int(downloaded_bytes * 100 / estimated_total)))
        else:
            self._wizard_model_progress.setRange(0, 0)
        speed = self._format_download_speed(float(info.get("speed") or 0.0))
        self._wizard_model_download_label.setText(_tr(
            "SettingsWindow.wizard_models_download_progress",
            default="已完成 {done}/{total} 个，下载速度 {speed}，正在处理：{current}",
            done=int(info.get("done") or 0),
            total=int(info.get("total") or 0),
            speed=speed,
            current=str(info.get("current") or "-"),
        ))

    def _on_model_download_finished(self, result: dict):
        self._model_download_running = False
        self._model_download_worker = None
        self._wizard_model_progress.setRange(0, 100)
        self._wizard_model_progress.setValue(100)
        failed = result.get("failed", []) or []
        downloaded = int(result.get("downloaded") or 0)
        self._recheck_model_resources(show_message=False)
        self._wizard_model_download_label.setText(_tr(
            "SettingsWindow.wizard_models_download_done_detail",
            default="下载完成：成功 {downloaded} 个，失败 {failed} 个。",
            downloaded=downloaded,
            failed=len(failed),
        ))
        if failed:
            InfoBar.warning(
                _tr("SettingsWindow.wizard_models_download_partial", default="部分模型下载失败"),
                "; ".join(failed[:3]),
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        else:
            InfoBar.success(
                _tr("SettingsWindow.wizard_models_download_done", default="模型包下载完成"),
                _tr("SettingsWindow.wizard_models_ready_content", default="可以继续选择角色和服装。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        self._update_wizard_footer()

    def _on_model_download_error(self, message: str):
        self._model_download_running = False
        self._model_download_worker = None
        self._wizard_model_progress.setRange(0, 100)
        self._wizard_model_progress.setValue(0)
        self._wizard_model_download_label.setText(message)
        self._update_wizard_model_status()
        self._update_wizard_footer()
        InfoBar.error(
            _tr("SettingsWindow.wizard_models_download_failed", default="模型包下载失败"),
            message,
            duration=6000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    @staticmethod
    def _format_download_speed(bytes_per_second: float) -> str:
        if bytes_per_second >= 1024 * 1024:
            return f"{bytes_per_second / 1024 / 1024:.1f} MB/s"
        if bytes_per_second >= 1024:
            return f"{bytes_per_second / 1024:.1f} KB/s"
        return f"{bytes_per_second:.0f} B/s"

    def _fix_nested_models_dir(self):
        nested = self._nested_models_dir()
        entries = self._nested_models_entries()
        if not entries:
            self._update_wizard_model_status()
            return
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        moved = 0
        skipped = []
        failed = []
        for entry in entries:
            target = MODELS_DIR / entry.name
            if target.exists():
                skipped.append(entry.name)
                continue
            try:
                shutil.move(str(entry), str(target))
                moved += 1
            except OSError as exc:
                failed.append(f"{entry.name}: {exc}")
        try:
            if nested.exists() and not any(nested.iterdir()):
                nested.rmdir()
        except OSError:
            pass
        self._recheck_model_resources(show_message=False)
        detail_parts = [_tr("SettingsWindow.wizard_models_fix_moved", default="已移动 {count} 个项目。", count=moved)]
        if skipped:
            detail_parts.append(_tr(
                "SettingsWindow.wizard_models_fix_skipped",
                default="同名冲突已跳过：{items}",
                items=", ".join(skipped[:6]),
            ))
        if failed:
            detail_parts.append(_tr(
                "SettingsWindow.wizard_models_fix_failed",
                default="部分项目移动失败：{items}",
                items="; ".join(failed[:3]),
            ))
        InfoBar.success(
            _tr("SettingsWindow.wizard_models_fix_done", default="整理完成"),
            "\n".join(detail_parts),
            duration=5000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _add_lazy_page(self, key: str, page: QWidget):
        page.hide()
        self._page_stack_layout.addWidget(page)
        self._pages[key] = page
        return page

    def _ensure_page(self, key: str) -> QWidget | None:
        if key in self._pages:
            return self._pages[key]
        if key in {"llm", "pov"}:
            self._ensure_llm_and_pov_pages()
            return self._pages.get(key)
        if key == "tts":
            self._tts_page = self._add_lazy_page("tts", self._build_tts_page())
            return self._tts_page
        if key == "memory":
            self._memory_page = self._add_lazy_page("memory", self._build_memory_page())
            return self._memory_page
        if key == "relationship_guide":
            self._relationship_guide_page = self._add_lazy_page(
                "relationship_guide",
                self._build_relationship_guide_page(),
            )
            return self._relationship_guide_page
        if key == "reminders":
            self._reminder_page = self._add_lazy_page("reminders", self._build_reminder_page())
            return self._reminder_page
        if key == "behavior":
            self._behavior_page = self._add_lazy_page("behavior", self._build_behavior_page())
            return self._behavior_page
        if key == "compact_window":
            self._compact_window_page = self._add_lazy_page("compact_window", self._build_compact_window_page())
            return self._compact_window_page
        if key == "chat_integration":
            self._chat_integration_page = self._add_lazy_page("chat_integration", self._build_chat_integration_page())
            return self._chat_integration_page
        if key == "mcp_computer":
            self._mcp_computer_page = self._add_lazy_page("mcp_computer", self._build_mcp_computer_page())
            return self._mcp_computer_page
        if key == "data_management":
            self._data_management_page = self._add_lazy_page("data_management", self._build_data_management_page())
            return self._data_management_page
        if key == "quality":
            self._quality_page = self._add_lazy_page("quality", self._build_quality_page())
            return self._quality_page
        if key == "about":
            self._about_page = self._add_lazy_page("about", self._build_about_page())
            return self._about_page
        return None

    def _ensure_llm_and_pov_pages(self):
        if self._pov_page is None:
            self._pov_page = self._add_lazy_page("pov", self._build_pov_page())
        if self._llm_page is None:
            self._llm_page = self._add_lazy_page("llm", self._build_llm_page())

    def _update_sidebar_style(self):
        dark = isDarkTheme()
        sidebar_bg = "#181818" if dark else "#f5f6f8"
        sidebar_border = "#404040" if dark else "#d5d5d5"
        self._sidebar.setStyleSheet(f"""
            #sidebar {{
                background: {sidebar_bg};
                border-right: 1px solid {sidebar_border};
            }}
            QWidget#sidebarNavContent {{
                background: {sidebar_bg};
            }}
        """)
        nav_scroll = getattr(self, "_sidebar_nav_scroll", None)
        if nav_scroll is not None:
            nav_scroll.setStyleSheet(f"""
                QScrollArea {{
                    background: {sidebar_bg};
                    border: none;
                }}
                QScrollArea > QWidget > QWidget {{
                    background: {sidebar_bg};
                }}
            """)
            pal = nav_scroll.viewport().palette()
            pal.setColor(QPalette.ColorRole.Window, QColor(sidebar_bg))
            nav_scroll.viewport().setPalette(pal)
            nav_scroll.viewport().setAutoFillBackground(True)
        nav_content = getattr(self, "_sidebar_nav_content", None)
        if nav_content is not None:
            pal = nav_content.palette()
            pal.setColor(QPalette.ColorRole.Window, QColor(sidebar_bg))
            nav_content.setPalette(pal)
            nav_content.setAutoFillBackground(True)

    @staticmethod
    def _reserve_overlay_scrollbar(scroll):
        """Reserve space on the right for qfluentwidgets' overlay scrollbar.

        ``ScrollArea`` forces the native scrollbar off and floats a 12px-wide
        fluent scrollbar at ``width - 13`` over the viewport, which otherwise
        overlaps the rightmost text/UI. Insetting the viewport keeps the
        floating bar in its own gutter instead of on top of the content.
        """
        scroll.setViewportMargins(0, 0, 14, 0)

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(210)
        sidebar.setObjectName("sidebar")
        self._sidebar = sidebar

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(10, 4, 4, 10)
        brand_row.setSpacing(8)
        icon_path = _app_icon_path()
        if icon_path:
            icon_label = QLabel(sidebar)
            icon_label.setFixedSize(24, 24)
            icon_label.setPixmap(QIcon(icon_path).pixmap(24, 24))
            brand_row.addWidget(icon_label)
        title = StrongBodyLabel(_tr("SettingsWindow.nav_title"), sidebar)
        title.setMinimumWidth(0)
        brand_row.addWidget(title, 1)
        layout.addLayout(brand_row)

        nav_scroll = ScrollArea(sidebar)
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._reserve_overlay_scrollbar(nav_scroll)
        nav_content = QWidget(nav_scroll)
        nav_content.setObjectName("sidebarNavContent")
        nav_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        nav_layout = QVBoxLayout(nav_content)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)

        btn_chars = NavButton("characters", FluentIcon.PEOPLE, _tr("SettingsWindow.nav_chars"), nav_content, "#e4004f")
        btn_chars.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["characters"] = btn_chars
        nav_layout.addWidget(btn_chars)

        btn_behavior = NavButton(
            "behavior",
            FluentIcon.GAME,
            _tr("SettingsWindow.nav_behavior", default="角色行为"),
            nav_content,
            "#f97316",
        )
        btn_behavior.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["behavior"] = btn_behavior
        nav_layout.addWidget(btn_behavior)

        btn_llm = NavButton("llm", FluentIcon.ROBOT, _tr("SettingsWindow.nav_llm"), nav_content, "#8b5cf6")
        btn_llm.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["llm"] = btn_llm
        nav_layout.addWidget(btn_llm)

        btn_tts = NavButton("tts", FluentIcon.MICROPHONE, _tr("SettingsWindow.nav_tts", "TTS 配置"), nav_content, "#f59e0b")
        btn_tts.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["tts"] = btn_tts
        nav_layout.addWidget(btn_tts)

        btn_pov = NavButton("pov", "avatar", _tr("SettingsWindow.nav_pov"), nav_content, "#ec4899")
        btn_pov.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["pov"] = btn_pov
        nav_layout.addWidget(btn_pov)

        btn_memory = NavButton("memory", FluentIcon.LIBRARY, _tr("SettingsWindow.nav_memory"), nav_content, "#10b981")
        btn_memory.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["memory"] = btn_memory
        nav_layout.addWidget(btn_memory)

        btn_relationship_guide = NavButton(
            "relationship_guide",
            FluentIcon.QUICK_NOTE,
            _tr("SettingsWindow.nav_relationship_guide"),
            nav_content,
            "#06b6d4",
        )
        btn_relationship_guide.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["relationship_guide"] = btn_relationship_guide
        nav_layout.addWidget(btn_relationship_guide)

        btn_reminders = NavButton(
            "reminders",
            FluentIcon.DATE_TIME,
            _tr("SettingsWindow.nav_reminders", default="闹钟番茄钟"),
            nav_content,
            "#ef4444",
        )
        btn_reminders.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["reminders"] = btn_reminders
        nav_layout.addWidget(btn_reminders)

        btn_compact = NavButton("compact_window", FluentIcon.CHAT, _tr("SettingsWindow.nav_compact_window"), nav_content, "#3b82f6")
        btn_compact.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["compact_window"] = btn_compact
        nav_layout.addWidget(btn_compact)

        btn_chat_integration = NavButton(
            "chat_integration",
            FluentIcon.MESSAGE,
            _tr("SettingsWindow.nav_chat_integration", default="聊天接入"),
            nav_content,
            "#14b8a6",
        )
        btn_chat_integration.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["chat_integration"] = btn_chat_integration
        nav_layout.addWidget(btn_chat_integration)

        btn_mcp_computer = NavButton(
            "mcp_computer",
            FluentIcon.DEVELOPER_TOOLS,
            _tr("SettingsWindow.nav_mcp_computer", default="工具与电脑控制"),
            nav_content,
            "#64748b",
        )
        btn_mcp_computer.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["mcp_computer"] = btn_mcp_computer
        nav_layout.addWidget(btn_mcp_computer)

        btn_data_management = NavButton(
            "data_management",
            FluentIcon.SAVE,
            _tr("SettingsWindow.nav_data_management", default="数据管理"),
            nav_content,
            "#0ea5e9",
        )
        btn_data_management.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["data_management"] = btn_data_management
        nav_layout.addWidget(btn_data_management)

        btn_quality = NavButton("quality", FluentIcon.PALETTE, _tr("SettingsWindow.nav_display"), nav_content, "#22c55e")
        btn_quality.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["quality"] = btn_quality
        nav_layout.addWidget(btn_quality)

        nav_layout.addStretch()
        nav_scroll.setWidget(nav_content)
        nav_scroll.verticalScrollBar().valueChanged.connect(
            lambda _value: self._position_nav_indicator(self._current_page)
        )
        self._sidebar_nav_scroll = nav_scroll
        self._sidebar_nav_content = nav_content
        layout.addWidget(nav_scroll, 1)

        btn_about = NavButton("about", FluentIcon.INFO, _tr("SettingsWindow.nav_about"), sidebar, "#94a3b8")
        btn_about.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["about"] = btn_about
        # The nav buttons above live inside nav_scroll, whose viewport reserves
        # 14px on the right for the overlay scrollbar. Inset the about button by
        # the same amount so it stays the same width and stays aligned.
        about_row = QHBoxLayout()
        about_row.setContentsMargins(0, 0, 14, 0)
        about_row.setSpacing(0)
        about_row.addWidget(btn_about)
        layout.addLayout(about_row)

        self._update_sidebar_style()
        self._theme_widgets.append(sidebar)
        qconfig.themeChanged.connect(self._update_sidebar_style)

        self._nav_indicator = QWidget(sidebar)
        self._nav_indicator.setFixedSize(4, 28)
        self._nav_indicator.setStyleSheet(f"""
            background: {BANDORI_PRIMARY};
            border-radius: 2px;
        """)
        self._nav_indicator.hide()

        return sidebar

    def _on_nav_selected(self, nav_key: str):
        page = self._ensure_page(nav_key)
        if page is None:
            return
        self._hide_costume_preview()

        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == nav_key)
        for stacked_page in self._pages.values():
            stacked_page.hide()

        if nav_key == "characters":
            self._selecting_model = False
            self._char_page.show()
            self._costume_page.hide()
            if self._selected_list_character:
                self._show_model_detail()
            else:
                self._enter_model_selection()
        else:
            self._costume_page.hide()
            page.show()
            if nav_key == "memory":
                self._refresh_memory_page()
        self._current_page = nav_key
        self._animate_indicator(nav_key)

    def _activate_char_page_for_model_list(self):
        page = self._ensure_page("characters")
        if page is None:
            return
        self._hide_costume_preview()
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        for stacked_page in self._pages.values():
            stacked_page.hide()
        self._costume_page.hide()
        self._char_page.show()
        self._current_page = "characters"
        self._animate_indicator("characters")

    def _animate_indicator(self, nav_key: str):
        btn = self._nav_buttons.get(nav_key)
        if btn is None:
            return
        self._ensure_nav_button_visible(nav_key)
        target = self._nav_indicator_geometry(nav_key)
        if target is None:
            return
        target_x = target.x()
        target_y = target.y()

        if not self._nav_indicator.isVisible():
            self._nav_indicator.move(target_x, target_y)
            self._nav_indicator.show()
            effect = QGraphicsOpacityEffect(self._nav_indicator)
            effect.setOpacity(0.0)
            self._nav_indicator.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self._nav_indicator)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self._nav_indicator.setGraphicsEffect(None))
            anim.start()
            return

        if hasattr(self, '_indicator_anim') and self._indicator_anim:
            self._indicator_anim.stop()
        self._indicator_anim = QPropertyAnimation(self._nav_indicator, b"geometry")
        self._indicator_anim.setDuration(300)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._indicator_anim.setStartValue(self._nav_indicator.geometry())
        self._indicator_anim.setEndValue(target)
        self._indicator_anim.start()

    def _nav_indicator_geometry(self, nav_key: str) -> QRect | None:
        btn = self._nav_buttons.get(nav_key)
        if btn is None or not hasattr(self, "_nav_indicator"):
            return None
        nav_scroll = getattr(self, "_sidebar_nav_scroll", None)
        if nav_scroll is not None and nav_key != "about":
            viewport_y = btn.mapTo(nav_scroll.viewport(), btn.rect().topLeft()).y()
            if viewport_y + btn.height() < 0 or viewport_y > nav_scroll.viewport().height():
                return None
        target_y = btn.mapTo(self._sidebar, btn.rect().topLeft()).y()
        target_y += (btn.height() - self._nav_indicator.height()) // 2
        return QRect(6, target_y, 4, 28)

    def _position_nav_indicator(self, nav_key: str):
        if not hasattr(self, "_nav_indicator"):
            return
        target = self._nav_indicator_geometry(nav_key)
        if target is None:
            self._nav_indicator.hide()
            return
        self._nav_indicator.setGeometry(target)
        self._nav_indicator.show()

    def _ensure_nav_button_visible(self, nav_key: str):
        if nav_key == "about":
            return
        btn = self._nav_buttons.get(nav_key)
        nav_scroll = getattr(self, "_sidebar_nav_scroll", None)
        if btn is not None and nav_scroll is not None:
            nav_scroll.ensureWidgetVisible(btn, 0, 8)

    def _build_char_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        self._selection_back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.band_back"), page)
        self._selection_back_btn.clicked.connect(self._go_back_to_bands)
        top_row.addWidget(self._selection_back_btn)
        top_row.addStretch()
        self._selection_title = TitleLabel(_tr("SettingsWindow.band_title"), page)
        self._selection_title.setMinimumWidth(0)
        top_row.addWidget(self._selection_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._selection_subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.band_subtitle"), page))
        self._selection_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._selection_subtitle)

        self._character_tools_widget = QWidget(page)
        character_tools = QHBoxLayout(self._character_tools_widget)
        character_tools.setContentsMargins(0, 0, 0, 0)
        character_tools.setSpacing(8)
        self._character_search = LineEdit(self._character_tools_widget)
        self._character_search.setClearButtonEnabled(True)
        self._character_search.setPlaceholderText(_tr("SettingsWindow.character_search_placeholder"))
        self._character_search.setFixedHeight(36)
        self._character_search.textChanged.connect(self._on_character_search_changed)
        character_tools.addWidget(self._character_search, 1)
        self._character_filter_combo = OpaqueDropDownComboBox(self._character_tools_widget)
        self._character_filter_combo.setFixedHeight(36)
        self._character_filter_combo.setMinimumWidth(140)
        self._character_filter_combo.addItem(_tr("SettingsWindow.filter_all"), userData=MODEL_PICKER_FILTER_ALL)
        self._character_filter_combo.addItem(_tr("SettingsWindow.filter_recent"), userData=MODEL_PICKER_FILTER_RECENT)
        self._character_filter_combo.addItem(_tr("SettingsWindow.filter_favorites"), userData=MODEL_PICKER_FILTER_FAVORITES)
        self._character_filter_combo.currentIndexChanged.connect(self._on_character_filter_changed)
        character_tools.addWidget(self._character_filter_combo)
        layout.addWidget(self._character_tools_widget)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        grid_widget = self._make_theme_widget(QWidget())
        self._char_grid = QGridLayout(grid_widget)
        self._char_grid.setSpacing(12)
        self._char_grid.setContentsMargins(0, 8, 0, 0)
        cols_per_row = 3
        for c in range(cols_per_row):
            self._char_grid.setColumnStretch(c, 0)
        self._selection_grid_widget = grid_widget
        self._selection_back_btn.hide()

        scroll.setWidget(grid_widget)
        self._selection_scroll = scroll
        layout.addWidget(scroll, 1)

        self._model_detail_widget = self._make_theme_widget(QWidget(page))
        detail_shell = QVBoxLayout(self._model_detail_widget)
        detail_shell.setContentsMargins(0, 0, 0, 0)
        detail_shell.setSpacing(0)

        detail_center = QHBoxLayout()
        detail_center.setContentsMargins(0, 0, 0, 0)
        detail_center.setSpacing(12)
        detail_center.addStretch(1)

        self._detail_card = CardWidget(self._model_detail_widget)
        self._detail_card.setFixedSize(280, 420)
        card_layout = QVBoxLayout(self._detail_card)
        card_h_margin = 26
        card_layout.setContentsMargins(card_h_margin, 22, card_h_margin, 22)
        card_layout.setSpacing(12)

        self._detail_image = QLabel(self._detail_card)
        self._detail_image.setFixedSize(self._detail_card.width() - card_h_margin * 2, 260)
        self._detail_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._detail_image, 0, Qt.AlignmentFlag.AlignHCenter)

        self._detail_name = TitleLabel("", self._detail_card)
        self._detail_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_costume = SubtitleLabel("", self._detail_card)
        self._detail_costume.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_band = BodyLabel("", self._detail_card)
        self._detail_band.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._detail_name)
        card_layout.addWidget(self._detail_costume)
        card_layout.addWidget(self._detail_band)

        action_scroll = ScrollArea(self._model_detail_widget)
        action_scroll.setObjectName("modelDetailActionScroll")
        action_scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        action_scroll.setWidgetResizable(True)
        action_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        action_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        action_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        action_scroll.setFixedWidth(320)
        action_scroll.setFixedHeight(self._detail_card.height())
        action_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        action_scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        action_scroll.viewport().setAutoFillBackground(False)
        action_container = self._make_theme_widget(QWidget(action_scroll))
        action_container.setObjectName("modelDetailActionContainer")
        action_container.setFixedWidth(292)
        action_col = QVBoxLayout(action_container)
        action_col.setContentsMargins(10, 0, 10, 0)
        action_col.setSpacing(10)
        self._switch_model_btn = QPushButton(_tr("SettingsWindow.model_switch"), action_container)
        self._switch_model_btn.setFixedSize(132, 132)
        self._switch_model_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._switch_model_btn.clicked.connect(self._edit_selected_model)
        action_col.addWidget(self._switch_model_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = _wrap_label(BodyLabel(_tr("SettingsWindow.model_detail_hint"), action_container))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(hint)

        motion_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.default_motion"), action_container))
        motion_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(motion_label)
        motion_row = QHBoxLayout()
        motion_row.setSpacing(8)
        self._default_motion_combo = OpaqueDropDownComboBox(action_container)
        self._default_motion_combo.setMinimumWidth(190)
        self._default_motion_combo.currentIndexChanged.connect(self._on_default_motion_changed)
        self._default_motion_combo.activated.connect(self._on_default_motion_preview)
        motion_row.addWidget(self._default_motion_combo, 1)
        self._default_motion_btn = PushButton(_tr("SettingsWindow.model_default"), action_container)
        self._default_motion_btn.clicked.connect(self._reset_default_motion)
        motion_row.addWidget(self._default_motion_btn)
        action_col.addLayout(motion_row)

        expression_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.default_expression"), action_container))
        expression_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(expression_label)
        expression_row = QHBoxLayout()
        expression_row.setSpacing(8)
        self._default_expression_combo = OpaqueDropDownComboBox(action_container)
        self._default_expression_combo.setMinimumWidth(190)
        self._default_expression_combo.currentIndexChanged.connect(self._on_default_expression_changed)
        self._default_expression_combo.activated.connect(self._on_default_expression_preview)
        expression_row.addWidget(self._default_expression_combo, 1)
        self._default_expression_btn = PushButton(_tr("SettingsWindow.model_default"), action_container)
        self._default_expression_btn.clicked.connect(self._reset_default_expression)
        expression_row.addWidget(self._default_expression_btn)
        action_col.addLayout(expression_row)

        click_label = _wrap_label(StrongBodyLabel(_tr("SettingsWindow.click_motion_title"), action_container))
        click_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(click_label)
        click_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.click_motion_hint"), action_container))
        click_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(click_hint)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        self._click_motion_profile_combo = OpaqueDropDownComboBox(action_container)
        self._click_motion_profile_combo.setFixedHeight(36)
        self._click_motion_profile_combo.currentIndexChanged.connect(self._on_click_motion_profile_selected)
        profile_row.addWidget(self._click_motion_profile_combo, 1)

        delete_profile_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.click_motion_profile_delete", default="删除"), action_container)
        delete_profile_btn.setFixedHeight(36)
        delete_profile_btn.clicked.connect(self._delete_click_motion_profile)
        profile_row.addWidget(delete_profile_btn)
        action_col.addLayout(profile_row)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        self._click_motion_profile_name = LineEdit(action_container)
        self._click_motion_profile_name.setPlaceholderText(_tr("SettingsWindow.click_motion_profile_name_placeholder", default="自定义档案名称"))
        self._click_motion_profile_name.setFixedHeight(36)
        name_row.addWidget(self._click_motion_profile_name, 1)

        save_profile_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.click_motion_profile_save", default="保存"), action_container)
        save_profile_btn.setFixedHeight(36)
        save_profile_btn.clicked.connect(self._save_click_motion_profile)
        name_row.addWidget(save_profile_btn)
        action_col.addLayout(name_row)

        apply_row = QHBoxLayout()
        apply_row.setSpacing(8)
        self._click_motion_apply_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.click_motion_apply", default="应用当前动作反馈"), action_container)
        self._click_motion_apply_btn.setFixedHeight(36)
        self._click_motion_apply_btn.clicked.connect(self._apply_click_motion_profile)
        apply_row.addWidget(self._click_motion_apply_btn, 1)

        self._click_motion_reset_btn = PushButton(_tr("SettingsWindow.click_motion_reset", default="恢复默认"), action_container)
        self._click_motion_reset_btn.clicked.connect(self._reset_click_motions)
        apply_row.addWidget(self._click_motion_reset_btn)
        action_col.addLayout(apply_row)

        click_grid_widget = QWidget(action_container)
        click_grid = QGridLayout(click_grid_widget)
        click_grid.setContentsMargins(0, 0, 0, 0)
        click_grid.setHorizontalSpacing(8)
        click_grid.setVerticalSpacing(6)
        self._click_motion_combos = {}
        self._click_expression_combos = {}
        click_grid.addWidget(BodyLabel(_tr("SettingsWindow.click_motion_column_motion"), click_grid_widget), 0, 0)
        click_grid.addWidget(BodyLabel(_tr("SettingsWindow.click_motion_column_expression"), click_grid_widget), 0, 1)
        for index, region in enumerate(CLICK_MOTION_REGIONS):
            row = index * 2 + 1
            label = BodyLabel(_tr(f"SettingsWindow.click_motion_region_{region}"), click_grid_widget)
            label.setWordWrap(True)
            combo = OpaqueDropDownComboBox(click_grid_widget)
            combo.setMinimumWidth(135)
            combo.setMaximumWidth(140)
            combo.currentIndexChanged.connect(
                lambda index, r=region: self._on_click_motion_changed(r, index)
            )
            combo.activated.connect(
                lambda idx, r=region, cb=combo: self._on_click_combo_preview(r, cb, idx)
            )
            expression_combo = OpaqueDropDownComboBox(click_grid_widget)
            expression_combo.setMinimumWidth(135)
            expression_combo.setMaximumWidth(140)
            expression_combo.currentIndexChanged.connect(
                lambda index, r=region: self._on_click_expression_changed(r, index)
            )
            expression_combo.activated.connect(
                lambda idx, r=region, cb=expression_combo: self._on_expression_combo_preview(r, cb, idx)
            )
            self._click_motion_combos[region] = combo
            self._click_expression_combos[region] = expression_combo
            click_grid.addWidget(label, row, 0, 1, 2)
            click_grid.addWidget(combo, row + 1, 0)
            click_grid.addWidget(expression_combo, row + 1, 1)
        click_grid.setColumnStretch(0, 1)
        click_grid.setColumnStretch(1, 1)
        action_col.addWidget(click_grid_widget)

        click_scope_label = _wrap_label(BodyLabel(_tr("SettingsWindow.click_motion_scope_label"), action_container))
        click_scope_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_col.addWidget(click_scope_label)
        self._click_motion_scope_combo = OpaqueDropDownComboBox(action_container)
        self._click_motion_scope_combo.setMinimumWidth(260)
        self._click_motion_scope_combo.addItem(
            _tr("SettingsWindow.click_motion_scope_all"),
            userData=CLICK_MOTION_SCOPE_ALL,
        )
        self._click_motion_scope_combo.addItem(
            _tr("SettingsWindow.click_motion_scope_character"),
            userData=CLICK_MOTION_SCOPE_CHARACTER,
        )
        self._click_motion_scope_combo.addItem(
            _tr("SettingsWindow.click_motion_scope_costume"),
            userData=CLICK_MOTION_SCOPE_COSTUME,
        )
        self._click_motion_scope_combo.setCurrentIndex(2)
        action_col.addWidget(self._click_motion_scope_combo, 0, Qt.AlignmentFlag.AlignHCenter)


        action_scroll.setWidget(action_container)

        detail_center.addWidget(self._detail_card, 0, Qt.AlignmentFlag.AlignTop)
        detail_center.addWidget(action_scroll, 0, Qt.AlignmentFlag.AlignTop)
        detail_center.addStretch(1)
        detail_shell.addLayout(detail_center, 1)

        self._detail_action_hint = hint
        self._detail_motion_label = motion_label
        self._detail_expression_label = expression_label
        self._detail_click_motion_label = click_label
        self._detail_click_motion_hint = click_hint
        self._detail_click_motion_scope_label = click_scope_label
        self._detail_action_scroll = action_scroll
        self._update_switch_button_style()
        qconfig.themeChanged.connect(self._update_switch_button_style)

        layout.addWidget(self._model_detail_widget, 1)
        self._model_detail_widget.hide()
        return page

    def _update_switch_button_style(self):
        dark = isDarkTheme()
        card_bg = "#252525" if dark else "#ffffff"
        card_border = "#3a3a3a" if dark else "#e5e7eb"
        hint_color = "#a7b0bf" if dark else "#687385"
        self._detail_card.setStyleSheet(f"""
            CardWidget {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 18px;
            }}
        """)
        self._detail_action_hint.setStyleSheet(f"color: {hint_color};")
        self._detail_motion_label.setStyleSheet(f"color: {hint_color};")
        self._detail_expression_label.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_label.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_hint.setStyleSheet(f"color: {hint_color};")
        self._detail_click_motion_scope_label.setStyleSheet(f"color: {hint_color};")
        self._switch_model_btn.setStyleSheet(f"""
            QPushButton {{
                color: #ffffff;
                background: {BANDORI_PRIMARY if not dark else BANDORI_PRIMARY_DARK};
                border: 1px solid {accent_color(dark)};
                border-radius: 66px;
                font-size: 18px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: {BANDORI_PRIMARY_HOVER if not dark else BANDORI_PRIMARY_DARK_HOVER}; }}
            QPushButton:pressed {{ background: {BANDORI_PRIMARY_PRESSED if not dark else BANDORI_PRIMARY_DARK_PRESSED}; }}
        """)
        self._detail_action_scroll.setStyleSheet(f"""
            #modelDetailActionScroll {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 18px;
            }}
            #modelDetailActionScroll QWidget#qt_scrollarea_viewport {{
                background: transparent;
                border: none;
            }}
            QWidget#modelDetailActionContainer {{
                background: transparent;
                border: none;
            }}
        """)

    def _show_model_detail(self):
        item = self._selected_model_item()
        if not item:
            self._enter_model_selection()
            return
        self._selecting_model = False
        self._set_character_tools_visible(False)
        self._clear_selection_cards()
        self._selection_scroll.hide()
        self._selection_grid_widget.hide()
        self._selection_back_btn.hide()
        self._selection_title.setText(_tr("SettingsWindow.model_detail_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.model_detail_subtitle"))
        self._model_detail_widget.show()

        character = item["character"]
        costume = item["costume"]
        self._current_char = character
        self._current_costume = costume
        self._selected_costume = costume
        self._selected_band = self._model_manager.get_character_band(character)

        display = self._model_manager.get_display_name(character)
        costume_name = self._model_manager.get_costume_display_name(character, costume)
        band_name = self._model_manager.get_band_display_name(self._selected_band) if self._selected_band else ""
        self._detail_name.setText(display)
        self._detail_costume.setText(_tr("SettingsWindow.detail_costume", costume=costume_name))
        self._detail_band.setText(_tr("SettingsWindow.detail_band", band=band_name) if band_name else "")
        self._populate_default_motion_combo(item)
        self._populate_default_expression_combo(item)
        self._populate_click_motion_combos(item)
        self._reload_click_motion_profiles(
            select_name=self._cfg.get_click_motion_active_profile() if self._cfg else ""
        )

        pixmap = QPixmap(self._model_manager.get_character_image_path(character))
        image_data = self._model_manager.get_character_image_data(character)
        if pixmap.isNull() and image_data:
            pixmap.loadFromData(image_data)
        if not pixmap.isNull():
            self._detail_image.setPixmap(pixmap.scaled(
                self._detail_image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._detail_image.setText(display)

    def _selected_model_item(self):
        for item in self._configured_models:
            if item["character"] == self._selected_list_character:
                return item
        return None

    def _enter_model_selection(self):
        self._selecting_model = True
        self._set_character_tools_visible(True)
        self._model_detail_widget.hide()
        self._selection_scroll.show()
        self._selection_grid_widget.show()
        self._populate_bands()
        self._char_page.show()
        self._costume_page.hide()
        self._current_page = "characters"
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        self._animate_indicator("characters")

    def _edit_selected_model(self):
        self._editing_list_character = self._selected_list_character
        self._editing_model_index = next(
            (
                idx for idx, item in enumerate(self._configured_models)
                if item["character"] == self._selected_list_character
            ),
            None,
        )
        self._adding_model = False
        self._enter_model_selection()

    def _clear_selection_cards(self):
        for card in self._selection_cards:
            self._char_grid.removeWidget(card)
            card.deleteLater()
        self._selection_cards.clear()

    def _set_character_tools_visible(self, visible: bool):
        widget = getattr(self, "_character_tools_widget", None)
        if widget is not None:
            widget.setVisible(visible)

    def _on_character_search_changed(self, text: str):
        self._character_search_text = str(text or "").strip().lower()
        self._refresh_character_selection_view()

    def _on_character_filter_changed(self, index: int):
        self._character_filter = self._character_filter_combo.itemData(index) or MODEL_PICKER_FILTER_ALL
        self._refresh_character_selection_view()

    def _refresh_character_selection_view(self):
        if not self._selecting_model or self._current_page != "characters":
            return
        if self._selected_band:
            self._populate_characters(self._selected_band)
        else:
            self._populate_bands()

    def _character_search_active(self) -> bool:
        return bool(self._character_search_text or self._character_filter != MODEL_PICKER_FILTER_ALL)

    def _character_matches_filter(self, character: str) -> bool:
        if self._character_filter == MODEL_PICKER_FILTER_RECENT:
            return character in self._picker_state.get("recent_characters", [])
        if self._character_filter == MODEL_PICKER_FILTER_FAVORITES:
            return self._is_favorite_character(character)
        return True

    def _character_matches_search(self, character: str) -> bool:
        text = self._character_search_text
        if not text:
            return True
        display = self._model_manager.get_display_name(character)
        band_id = self._model_manager.get_character_band(character)
        band = self._model_manager.get_band_display_name(band_id) if band_id else ""
        haystack = " ".join([character, display, band]).lower()
        return text in haystack

    def _filtered_characters(self, characters: list[str]) -> list[str]:
        result = [
            character for character in characters
            if self._character_matches_filter(character) and self._character_matches_search(character)
        ]
        if self._character_filter == MODEL_PICKER_FILTER_RECENT:
            order = {character: idx for idx, character in enumerate(self._picker_state.get("recent_characters", []))}
            result.sort(key=lambda character: order.get(character, 9999))
        elif self._character_filter == MODEL_PICKER_FILTER_FAVORITES:
            order = {character: idx for idx, character in enumerate(self._picker_state.get("favorite_characters", []))}
            result.sort(key=lambda character: order.get(character, 9999))
        return result

    def _add_empty_selection_message(self, text: str):
        label = _wrap_label(BodyLabel(text, self._selection_grid_widget))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(f"color: {'#a7b0bf' if isDarkTheme() else '#687385'};")
        self._char_grid.addWidget(label, 0, 0, 1, 3)
        self._selection_cards.append(label)

    def _add_character_cards(self, characters: list[str]):
        configured_characters = {
            item["character"] for item in self._configured_models
            if item.get("character") != self._selected_list_character
        }

        col = 0
        row = 0
        cols_per_row = 3
        card_idx = 0
        for char_key in characters:
            costumes = self._model_manager.get_costumes(char_key)
            if not costumes:
                continue
            display = self._model_manager.get_display_name(char_key)
            image_path = self._model_manager.get_character_image_path(char_key)
            image_data = self._model_manager.get_character_image_data(char_key)
            card = CharacterCard(
                char_key, display, len(costumes), image_path,
                "green" if self._model_manager.has_advanced_roleplay(char_key) else "red",
                self._selection_grid_widget,
                image_data=image_data,
                favorite=self._is_favorite_character(char_key),
            )
            card.set_disabled_for_existing(char_key in configured_characters)
            card.char_selected.connect(self._on_char_selected)
            card.favorite_toggled.connect(self._set_character_favorite)
            card.animate_in(delay_ms=card_idx * 50)
            self._char_grid.addWidget(card, row, col)
            self._selection_cards.append(card)
            col += 1
            card_idx += 1
            if col >= cols_per_row:
                col = 0
                row += 1

    def _populate_character_results(self, band_id: str = ""):
        self._set_character_tools_visible(True)
        self._clear_selection_cards()
        self._model_detail_widget.hide()
        self._selection_grid_widget.show()
        self._selection_scroll.show()
        self._selected_band = band_id
        self._selection_back_btn.setVisible(bool(band_id))
        source_characters = (
            self._model_manager.get_band_characters(band_id)
            if band_id else list(self._model_manager.characters)
        )
        characters = self._filtered_characters(source_characters)
        self._selection_title.setText(_tr("SettingsWindow.char_title"))
        if band_id:
            band_display = self._model_manager.get_band_display_name(band_id)
            self._selection_subtitle.setText(_tr("SettingsWindow.char_subtitle_with_band", band=band_display))
        else:
            self._selection_subtitle.setText(_tr(
                "SettingsWindow.character_search_subtitle",
                count=len(characters),
                total=len(source_characters),
            ))
        if characters:
            self._add_character_cards(characters)
        else:
            self._add_empty_selection_message(_tr("SettingsWindow.no_character_results"))

    def _populate_bands(self):
        if self._character_search_active():
            self._populate_character_results("")
            return
        self._set_character_tools_visible(True)
        self._clear_selection_cards()
        self._model_detail_widget.hide()
        self._selection_grid_widget.show()
        self._selection_scroll.show()
        self._selected_band = ""
        self._selection_back_btn.hide()
        self._selection_title.setText(_tr("SettingsWindow.band_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.band_subtitle"))

        col = 0
        row = 0
        cols_per_row = 3
        card_idx = 0
        for band in self._model_manager.bands:
            characters = band.get("characters", [])
            if not characters:
                continue
            card = BandCard(
                band.get("id", ""), band.get("display", ""),
                len(characters), band.get("logo", ""),
                self._model_manager.get_band_advanced_roleplay_status(band.get("id", "")),
                self._selection_grid_widget
            )
            card.band_selected.connect(self._on_band_selected)
            card.animate_in(delay_ms=card_idx * 80)
            self._char_grid.addWidget(card, row, col)
            self._selection_cards.append(card)
            col += 1
            card_idx += 1
            if col >= cols_per_row:
                col = 0
                row += 1

    def _populate_characters(self, band_id: str):
        self._populate_character_results(band_id)

    def _build_costume_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.costume_back"), page)
        back_btn.clicked.connect(self._go_back_to_chars)
        top_row.addWidget(back_btn)
        top_row.addStretch()

        self._costume_title = TitleLabel(_tr("SettingsWindow.costume_title"), page)
        top_row.addWidget(self._costume_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._costume_subtitle = SubtitleLabel("", page)
        layout.addWidget(self._costume_subtitle)
        self._costume_preview_hint = BodyLabel(_tr("SettingsWindow.costume_preview_hint"), page)
        self._costume_preview_hint.setWordWrap(True)
        layout.addWidget(self._costume_preview_hint)

        costume_tools = QHBoxLayout()
        costume_tools.setContentsMargins(0, 0, 0, 0)
        costume_tools.setSpacing(8)
        self._costume_search = LineEdit(page)
        self._costume_search.setClearButtonEnabled(True)
        self._costume_search.setPlaceholderText(_tr("SettingsWindow.costume_search_placeholder"))
        self._costume_search.setFixedHeight(36)
        self._costume_search.textChanged.connect(self._on_costume_search_changed)
        costume_tools.addWidget(self._costume_search, 1)
        self._costume_filter_combo = OpaqueDropDownComboBox(page)
        self._costume_filter_combo.setFixedHeight(36)
        self._costume_filter_combo.setMinimumWidth(140)
        self._costume_filter_combo.addItem(_tr("SettingsWindow.filter_all"), userData=MODEL_PICKER_FILTER_ALL)
        self._costume_filter_combo.addItem(_tr("SettingsWindow.filter_recent"), userData=MODEL_PICKER_FILTER_RECENT)
        self._costume_filter_combo.addItem(_tr("SettingsWindow.filter_favorites"), userData=MODEL_PICKER_FILTER_FAVORITES)
        self._costume_filter_combo.currentIndexChanged.connect(self._on_costume_filter_changed)
        costume_tools.addWidget(self._costume_filter_combo)
        layout.addLayout(costume_tools)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._costume_list_widget = self._make_theme_widget(QWidget())
        self._costume_list = QVBoxLayout(self._costume_list_widget)
        self._costume_list.setSpacing(6)
        self._costume_list.setContentsMargins(0, 4, 0, 0)
        self._costume_list.addStretch()

        scroll.setWidget(self._costume_list_widget)
        layout.addWidget(scroll, 1)
        return page

    def _on_char_selected(self, char_key: str):
        self._selecting_model = True
        self._current_char = char_key
        self._remember_character(char_key)
        self._selected_band = self._model_manager.get_character_band(char_key)
        self._populate_costumes(char_key)
        display = self._model_manager.get_display_name(char_key)
        self._costume_title.setText(_tr("SettingsWindow.costumes_title", display=display))
        self._costume_subtitle.setText(
            _tr("SettingsWindow.costume_subtitle", display=display)
        )
        self._char_page.hide()
        self._costume_page.show()
        self._current_page = "costumes"

    def _on_band_selected(self, band_id: str):
        self._populate_characters(band_id)

    def _on_costume_search_changed(self, text: str):
        self._costume_search_text = str(text or "").strip().lower()
        if self._current_char:
            self._populate_costumes(self._current_char)

    def _on_costume_filter_changed(self, index: int):
        self._costume_filter = self._costume_filter_combo.itemData(index) or MODEL_PICKER_FILTER_ALL
        if self._current_char:
            self._populate_costumes(self._current_char)

    def _costume_matches_filter(self, char_key: str, costume_id: str) -> bool:
        key = self._costume_key(char_key, costume_id)
        if self._costume_filter == MODEL_PICKER_FILTER_RECENT:
            return key in self._picker_state.get("recent_costumes", [])
        if self._costume_filter == MODEL_PICKER_FILTER_FAVORITES:
            return key in self._picker_state.get("favorite_costumes", [])
        return True

    def _costume_matches_search(self, char_key: str, costume_id: str, display_name: str) -> bool:
        text = self._costume_search_text
        if not text:
            return True
        return text in " ".join([costume_id, display_name]).lower()

    def _filtered_costumes(self, char_key: str, costumes: list[dict]) -> list[dict]:
        result = []
        for costume in costumes:
            cid = costume.get("id", "")
            cname = self._model_manager.get_costume_display_name(char_key, cid)
            if self._costume_matches_filter(char_key, cid) and self._costume_matches_search(char_key, cid, cname):
                item = dict(costume)
                item["_display_name"] = cname
                result.append(item)
        if self._costume_filter == MODEL_PICKER_FILTER_RECENT:
            order = {key: idx for idx, key in enumerate(self._picker_state.get("recent_costumes", []))}
            result.sort(key=lambda item: order.get(self._costume_key(char_key, item.get("id", "")), 9999))
        elif self._costume_filter == MODEL_PICKER_FILTER_FAVORITES:
            order = {key: idx for idx, key in enumerate(self._picker_state.get("favorite_costumes", []))}
            result.sort(key=lambda item: order.get(self._costume_key(char_key, item.get("id", "")), 9999))
        return result

    def _populate_costumes(self, char_key: str):
        self._hide_costume_preview()
        for btn in self._costume_buttons:
            self._costume_list.removeWidget(btn)
            btn.deleteLater()
        self._costume_buttons.clear()
        if self._costume_empty_label is not None:
            self._costume_list.removeWidget(self._costume_empty_label)
            self._costume_empty_label.deleteLater()
            self._costume_empty_label = None

        costumes = self._filtered_costumes(char_key, self._model_manager.get_costumes(char_key))
        for idx, costume in enumerate(costumes):
            cid = costume["id"]
            cname = costume.get("_display_name") or self._model_manager.get_costume_display_name(char_key, cid)
            btn = CostumeItem(
                cid,
                cname,
                self._costume_list_widget,
                favorite=self._is_favorite_costume(char_key, cid),
            )
            btn.clicked.connect(lambda checked, b=btn, c=cid: self._on_costume_clicked(b, c))
            btn.preview_requested.connect(self._show_costume_preview)
            btn.preview_toggled.connect(self._toggle_costume_preview)
            btn.preview_cancelled.connect(self._hide_hover_costume_preview)
            btn.favorite_toggled.connect(self._set_costume_favorite)
            btn.animate_in(delay_ms=idx * 40)
            self._costume_buttons.append(btn)
            self._costume_list.insertWidget(self._costume_list.count() - 1, btn)

        if not self._costume_buttons:
            self._costume_empty_label = _wrap_label(BodyLabel(_tr("SettingsWindow.no_costume_results"), self._costume_list_widget))
            self._costume_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._costume_empty_label.setStyleSheet(f"color: {'#a7b0bf' if isDarkTheme() else '#687385'};")
            self._costume_list.insertWidget(self._costume_list.count() - 1, self._costume_empty_label)
            return

        if self._costume_buttons:
            default_id = next(
                (item["costume"] for item in self._configured_models if item["character"] == char_key),
                self._model_manager.get_default_costume(char_key),
            )
            for btn in self._costume_buttons:
                if btn.costume_id == default_id:
                    btn.setChecked(True)
                    self._selected_costume = default_id
                    break

    def _on_costume_clicked(self, btn: CostumeItem, costume_id: str):
        for b in self._costume_buttons:
            b.setChecked(False)
        btn.setChecked(True)
        self._selected_costume = costume_id
        self._current_costume = costume_id
        self._remember_costume(self._current_char, costume_id)
        self._upsert_configured_model(self._current_char, costume_id)
        self._selecting_model = False
        self._hide_costume_preview()
        self._costume_page.hide()
        self._char_page.show()
        self._show_model_detail()
        if self._first_run_wizard:
            self._wizard_go_to_step(1)

    def _costume_preview_key(self, costume_id: str) -> str:
        return self._costume_key(self._current_char, costume_id)

    def _show_costume_preview(self, anchor: QWidget, costume_id: str, pinned: bool = False):
        live2d_module = self._ensure_live2d_preview_module()
        if not live2d_module:
            return
        model_path = self._model_manager.get_model_json_path(self._current_char, costume_id)
        if not model_path:
            return
        key = self._costume_preview_key(costume_id)
        if pinned:
            self._preview_pinned_key = key
            self._preview_pinned_anchor = anchor
        else:
            self._preview_hover_key = key
        if self._preview_bubble is None:
            self._preview_bubble = Live2DPreviewBubble(live2d_module, self._live2d_quality, self)
        self._preview_bubble.set_render_quality(self._live2d_quality)
        self._preview_bubble.show_preview(model_path, anchor)

    def _toggle_costume_preview(self, anchor: QWidget, costume_id: str):
        model_path = self._model_manager.get_model_json_path(self._current_char, costume_id)
        key = self._costume_preview_key(costume_id)
        if (
            self._preview_bubble is not None
            and self._preview_bubble.is_showing(model_path)
            and self._preview_pinned_key == key
        ):
            self._hide_costume_preview()
            return
        self._show_costume_preview(anchor, costume_id, pinned=True)

    def _hide_hover_costume_preview(self, costume_id: str = ""):
        key = self._costume_preview_key(costume_id) if costume_id else self._preview_hover_key
        if key and self._preview_hover_key and key != self._preview_hover_key:
            return
        self._preview_hover_key = ""
        if self._preview_pinned_key and self._preview_pinned_anchor is not None:
            _, pinned_costume = self._split_costume_key(self._preview_pinned_key)
            if pinned_costume:
                self._show_costume_preview(self._preview_pinned_anchor, pinned_costume, pinned=True)
            return
        self._hide_costume_preview()

    def _hide_costume_preview(self):
        self._preview_pinned_key = ""
        self._preview_pinned_anchor = None
        self._preview_hover_key = ""
        if self._preview_bubble is not None:
            self._preview_bubble.hide()

    def _go_back_to_chars(self):
        self._hide_costume_preview()
        self._costume_page.hide()
        self._char_page.show()
        self._current_page = "characters"
        self._selecting_model = True
        band_id = self._selected_band or self._model_manager.get_character_band(self._current_char)
        if band_id:
            self._populate_characters(band_id)
        else:
            self._populate_bands()
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        self._animate_indicator("characters")

    def _go_back_to_bands(self):
        self._hide_costume_preview()
        self._selecting_model = True
        self._populate_bands()

    def _on_fps_changed(self, value: int):
        self._fps = int(value)
        if hasattr(self, "_fps_value"):
            self._fps_value.setText(_tr("SettingsWindow.fps_value", v=value))

    def _on_vsync_changed(self, checked: bool):
        self._vsync = checked
        if hasattr(self, "_fps_slider"):
            self._fps_slider.setEnabled(not checked)
        if hasattr(self, "_fps_value"):
            self._fps_value.setEnabled(not checked)

    def _apply_auto_start_setting(self) -> bool:
        enabled = bool(self._auto_start_switch.isChecked())
        if not self._auto_start_supported:
            if self._cfg:
                self._cfg.set("auto_start", False)
            return True
        try:
            set_startup_enabled(enabled)
            self._auto_start_enabled = enabled
            if self._cfg:
                self._cfg.set("auto_start", enabled)
            return True
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.auto_start_failed_title"),
                _tr("SettingsWindow.auto_start_failed_content", error=str(exc)),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return False

    def _current_fps_setting(self) -> int:
        if hasattr(self, "_fps_slider"):
            return int(self._fps_slider.value())
        return int(self._fps)

    def _current_vsync_setting(self) -> bool:
        if hasattr(self, "_vsync_switch"):
            return bool(self._vsync_switch.isChecked())
        return bool(self._vsync)

    def _on_apply(self):
        if self._launched:
            return
        self._launched = True
        selected = self._selected_model_item()
        if selected:
            self._current_char = selected["character"]
            self._selected_costume = selected["costume"]
        if self._show_launch and not (self._current_char and self._selected_costume):
            self._launched = False
            InfoBar.warning(
                _tr("SettingsWindow.launch_missing_model_title"),
                _tr("SettingsWindow.launch_missing_model_content"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not self._apply_auto_start_setting():
            self._launched = False
            return
        self._save_llm_config(show_info=False)
        self._save_tts_config(show_info=False)
        self._save_compact_window_config(show_info=False, emit_update=False)
        self._save_chat_integration_config(show_info=False, emit_update=False)
        self._save_mcp_computer_config(show_info=False)
        self._save_reminder_config(show_info=False, emit_update=False)
        self._save_configured_models()
        settings = {
            "language": current_language(),
            "fps": self._current_fps_setting(),
            "opacity": self._opacity_slider.value() / 100.0,
            "dark_theme": self._theme_combo.currentData(),
            "vsync": self._current_vsync_setting(),
            "game_topmost": self._game_topmost_switch.isChecked(),
            "chat_window_normal_window": self._chat_window_normal_window_switch.isChecked(),
            "hide_live2d_model": self._hide_live2d_model_switch.isChecked(),
            "live2d_idle_actions_enabled": self._live2d_idle_actions_enabled,
            "live2d_head_tracking_enabled": self._live2d_head_tracking_enabled,
            "live2d_mutual_gaze_enabled": self._live2d_mutual_gaze_enabled,
            "auto_start": self._auto_start_supported and self._auto_start_switch.isChecked(),
            "live2d_quality": self._live2d_quality,
            "live2d_scale": self._live2d_scale,
            "compact_ai_window_enabled": self._cfg.get("compact_ai_window_enabled", False) if self._cfg else False,
            "compact_ai_window_opacity": self._cfg.get("compact_ai_window_opacity", 44) if self._cfg else 44,
            "compact_ai_window_font_size": self._cfg.get("compact_ai_window_font_size", 12) if self._cfg else 12,
            "compact_ai_window_background_color": self._cfg.get("compact_ai_window_background_color", "") if self._cfg else "",
            "compact_ai_window_text_color": self._cfg.get("compact_ai_window_text_color", "#24242a") if self._cfg else "#24242a",
            "ai_event_overlay_enabled": self._cfg.get("ai_event_overlay_enabled", False) if self._cfg else False,
            "ai_status_port_enabled": self._cfg.get("ai_status_port_enabled", False) if self._cfg else False,
            "ai_status_port": self._clamp_ai_status_port(self._cfg.get("ai_status_port", 38472)) if self._cfg else 38472,
            "ai_status_token": self._cfg.get("ai_status_token", "") if self._cfg else "",
            "chat_integration_enabled": self._cfg.get("chat_integration_enabled", False) if self._cfg else False,
            "chat_integration_overlay_enabled": self._cfg.get("chat_integration_overlay_enabled", True) if self._cfg else True,
            "chat_integration_include_context": self._cfg.get("chat_integration_include_context", True) if self._cfg else True,
            "chat_integration_port": self._clamp_chat_integration_port(self._cfg.get("chat_integration_port", 38473)) if self._cfg else 38473,
            "chat_integration_token": self._cfg.get("chat_integration_token", "") if self._cfg else "",
            "napcat_enabled": self._cfg.get("napcat_enabled", False) if self._cfg else False,
            "napcat_ws_url": self._cfg.get("napcat_ws_url", "ws://127.0.0.1:3001") if self._cfg else "ws://127.0.0.1:3001",
            "napcat_access_token": self._cfg.get("napcat_access_token", "") if self._cfg else "",
            "napcat_auto_reply_enabled": self._cfg.get("napcat_auto_reply_enabled", False) if self._cfg else False,
            "napcat_reply_private": self._cfg.get("napcat_reply_private", True) if self._cfg else True,
            "napcat_reply_group_at_only": self._cfg.get("napcat_reply_group_at_only", True) if self._cfg else True,
            "napcat_reply_character": self._cfg.get("napcat_reply_character", "") if self._cfg else "",
            "alarms": normalize_alarms(self._cfg.get("alarms", [])) if self._cfg else [],
            "pomodoros": normalize_pomodoros(self._cfg.get("pomodoros", [])) if self._cfg else [],
            "reminder_display_mode": normalize_display_mode(self._cfg.get("reminder_display_mode", DISPLAY_MODE_FLOATING)) if self._cfg else DISPLAY_MODE_FLOATING,
            "user_avatar_color": self._cfg.get("user_avatar_color", BANDORI_PRIMARY) if self._cfg else BANDORI_PRIMARY,
            "user_avatar_path": self._cfg.get("user_avatar_path", "") if self._cfg else "",
            "user_profiles": self._cfg.get("user_profiles", []) if self._cfg else [],
            "active_user_profile": self._cfg.get("active_user_profile", "") if self._cfg else "",
            "models": [dict(item) for item in self._configured_models],
            "model_action_settings": self._cfg.get("model_action_settings", {}) if self._cfg else {},
        }
        if self._compact_window_reset_position_pending:
            settings["compact_ai_window_reset_position"] = True
        if self._cfg:
            self._cfg.set("language", settings["language"])
            self._cfg.set("fps", settings["fps"])
            self._cfg.set("opacity", settings["opacity"])
            self._cfg.set("dark_theme", settings["dark_theme"])
            self._cfg.set("vsync", settings["vsync"])
            self._cfg.set("game_topmost", settings["game_topmost"])
            self._cfg.set("chat_window_normal_window", settings["chat_window_normal_window"])
            self._cfg.set("hide_live2d_model", settings["hide_live2d_model"])
            self._cfg.set("live2d_idle_actions_enabled", settings["live2d_idle_actions_enabled"])
            self._cfg.set("live2d_head_tracking_enabled", settings["live2d_head_tracking_enabled"])
            self._cfg.set("live2d_mutual_gaze_enabled", settings["live2d_mutual_gaze_enabled"])
            self._cfg.set("auto_start", settings["auto_start"])
            self._cfg.set("live2d_quality", settings["live2d_quality"])
            self._cfg.set("live2d_scale", settings["live2d_scale"])
            self._cfg.save()
        if self._current_char and self._selected_costume:
            self.model_selected.emit(self._current_char, self._selected_costume)
        self.settings_changed.emit(settings)
        if self._show_launch:
            self.launch_requested.emit()
        self.close()

    def connect_ipc_output(self, send_line):
        self._ipc_output = send_line
        self.model_selected.connect(lambda char, costume: send_line(f"MODEL\t{char}\t{costume}"))
        self.settings_changed.connect(lambda data: send_line(f"SETTINGS\t{json.dumps(data, ensure_ascii=False)}"))
        self.launch_requested.connect(lambda: send_line("LAUNCH"))
        self.exit_requested.connect(lambda: send_line("EXIT"))

    def _build_side_panel(self):
        panel = self._make_theme_widget(QWidget())
        panel.setObjectName("settingsSidePanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(260)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        settings_title = StrongBodyLabel(_tr("SettingsWindow.side_settings"), panel)
        layout.addWidget(settings_title)

        game_topmost_label = BodyLabel(_tr("SettingsWindow.side_game_topmost"), panel)
        self._game_topmost_switch = SwitchButton(panel)
        self._game_topmost_switch.setChecked(self._game_topmost)
        game_topmost_row = QHBoxLayout()
        game_topmost_row.setContentsMargins(0, 0, 0, 0)
        game_topmost_row.setSpacing(8)
        game_topmost_row.addWidget(game_topmost_label)
        game_topmost_row.addStretch()
        game_topmost_row.addWidget(self._game_topmost_switch)
        layout.addLayout(game_topmost_row)

        chat_window_label = BodyLabel(_tr("SettingsWindow.side_chat_window_normal"), panel)
        chat_window_hint = _tr("SettingsWindow.side_chat_window_normal_tip")
        chat_window_label.setToolTip(chat_window_hint)
        self._chat_window_normal_window_switch = SwitchButton(panel)
        self._chat_window_normal_window_switch.setChecked(self._chat_window_normal_window)
        self._chat_window_normal_window_switch.setToolTip(chat_window_hint)
        chat_window_row = QHBoxLayout()
        chat_window_row.setContentsMargins(0, 0, 0, 0)
        chat_window_row.setSpacing(8)
        chat_window_row.addWidget(chat_window_label)
        chat_window_row.addStretch()
        chat_window_row.addWidget(self._chat_window_normal_window_switch)
        layout.addLayout(chat_window_row)

        hide_live2d_label = BodyLabel(_tr("SettingsWindow.side_hide_live2d_model"), panel)
        self._hide_live2d_model_switch = SwitchButton(panel)
        self._hide_live2d_model_switch.setChecked(self._hide_live2d_model)
        hide_live2d_row = QHBoxLayout()
        hide_live2d_row.setContentsMargins(0, 0, 0, 0)
        hide_live2d_row.setSpacing(8)
        hide_live2d_row.addWidget(hide_live2d_label)
        hide_live2d_row.addStretch()
        hide_live2d_row.addWidget(self._hide_live2d_model_switch)
        layout.addLayout(hide_live2d_row)

        auto_start_label = BodyLabel(_tr("SettingsWindow.side_auto_start"), panel)
        self._auto_start_switch = SwitchButton(panel)
        self._auto_start_switch.setChecked(self._auto_start_enabled)
        self._auto_start_switch.setEnabled(self._auto_start_supported)
        if not self._auto_start_supported:
            self._auto_start_switch.setToolTip(_tr("SettingsWindow.auto_start_unsupported"))
            auto_start_label.setToolTip(_tr("SettingsWindow.auto_start_unsupported"))
        auto_start_row = QHBoxLayout()
        auto_start_row.setContentsMargins(0, 0, 0, 0)
        auto_start_row.setSpacing(8)
        auto_start_row.addWidget(auto_start_label)
        auto_start_row.addStretch()
        auto_start_row.addWidget(self._auto_start_switch)
        layout.addLayout(auto_start_row)

        lang_label = BodyLabel(_tr("SettingsWindow.language"), panel)
        self._lang_combo = OpaqueDropDownComboBox(panel)
        self._lang_combo.setMinimumWidth(120)
        langs = available_languages()
        current = current_language()
        for lang in langs:
            display = _tr(f"Language.{lang}", default=lang)
            self._lang_combo.addItem(display, userData=lang)
            if lang == current:
                self._lang_combo.setCurrentIndex(self._lang_combo.count() - 1)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row = QHBoxLayout()
        lang_row.setContentsMargins(0, 0, 0, 0)
        lang_row.setSpacing(8)
        lang_row.addWidget(lang_label)
        lang_row.addStretch()
        lang_row.addWidget(self._lang_combo)
        layout.addLayout(lang_row)

        btn_text = _tr("SettingsWindow.apply_launch") if self._show_launch else _tr("SettingsWindow.apply")
        self._apply_btn = PrimaryPushButton(FluentIcon.ACCEPT, btn_text, panel)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addSpacing(2)
        layout.addWidget(self._apply_btn)

        list_title = StrongBodyLabel(_tr("SettingsWindow.model_list_title"), panel)
        layout.addSpacing(4)
        layout.addWidget(list_title)

        self._model_list_scroll = ScrollArea(panel)
        self._model_list_scroll.setWidgetResizable(True)
        self._model_list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._model_list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._model_list_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._model_list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._model_list_widget = QWidget(panel)
        self._model_list_widget.setObjectName("modelListWidget")
        self._model_list_layout = QVBoxLayout(self._model_list_widget)
        self._model_list_layout.setContentsMargins(0, 0, 0, 0)
        self._model_list_layout.setSpacing(8)
        self._model_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._model_list_scroll.setWidget(self._model_list_widget)
        self._model_list_scroll.setMinimumHeight(140)
        layout.addWidget(self._model_list_scroll, 1)
        self._update_model_list_style()
        qconfig.themeChanged.connect(self._update_model_list_style)
        self._update_side_panel_style()
        qconfig.themeChanged.connect(self._update_side_panel_style)

        return panel

    def _update_side_panel_style(self):
        dark = isDarkTheme()
        bg = "#232125" if dark else "#fff8fb"
        border = "#3b343a" if dark else "#f1d7e1"
        title = "#fff6fb" if dark else "#2b2228"
        muted = "#d4c3cc" if dark else "#6a5b63"
        self._model_list_scroll.parentWidget().setStyleSheet(f"""
            QWidget#settingsSidePanel {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 16px;
            }}
            QWidget#settingsSidePanel StrongBodyLabel {{ color: {title}; font-size: 14px; font-weight: 700; }}
            QWidget#settingsSidePanel BodyLabel {{ color: {muted}; font-size: 13px; }}
        """)

    def _update_model_list_style(self):
        self._model_list_widget.setStyleSheet("""
            #modelListWidget {
                background: transparent;
                border: none;
            }
        """)

    def _save_configured_models(self):
        if not self._cfg:
            return
        for item in self._configured_models:
            self._archive_model_action_profile(item)
        selected = self._selected_model_item()
        if selected:
            self._cfg.set("character", selected["character"])
            self._cfg.set("costume", selected["costume"])
        elif self._configured_models:
            self._cfg.set("character", self._configured_models[0]["character"])
            self._cfg.set("costume", self._configured_models[0]["costume"])
        else:
            self._cfg.set("character", "")
            self._cfg.set("costume", "")
        self._cfg.set("models", [dict(item) for item in self._configured_models])
        self._cfg.save()

    def _refresh_model_list(self):
        while self._model_list_layout.count():
            item = self._model_list_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
            if item:
                del item
        for item in self._configured_models:
            character = item["character"]
            costume = item["costume"]
            title = self._model_manager.get_display_name(character)
            subtitle = self._model_manager.get_costume_display_name(character, costume)
            row = ModelListItem(character, title, subtitle, character == self._selected_list_character, self._model_list_widget)
            row.selected.connect(self._select_model_list_item)
            row.remove_requested.connect(self._remove_model_list_item)
            self._model_list_layout.addWidget(row)
        add_row = AddModelListItem(self._model_list_widget)
        add_row.add_requested.connect(self._add_model_from_list)
        self._model_list_layout.addWidget(add_row)

    def _select_model_list_item(self, character: str):
        for item in self._configured_models:
            if item["character"] == character:
                self._activate_char_page_for_model_list()
                self._selected_list_character = character
                self._editing_list_character = ""
                self._editing_model_index = None
                self._adding_model = False
                self._current_char = character
                self._current_costume = item["costume"]
                self._selected_costume = item["costume"]
                self._selected_band = self._model_manager.get_character_band(character)
                self._remember_character(character)
                self._remember_costume(character, item["costume"])
                self._refresh_model_list()
                self._show_model_detail()
                return

    def _add_model_from_list(self):
        self._activate_char_page_for_model_list()
        self._selected_list_character = ""
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = True
        self._refresh_model_list()
        self._enter_model_selection()

    def _remove_model_list_item(self, character: str):
        self._activate_char_page_for_model_list()
        if len(self._configured_models) <= 1:
            InfoBar.warning(
                _tr("SettingsWindow.model_list_keep_one_title"),
                _tr("SettingsWindow.model_list_keep_one_content"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._configured_models = [item for item in self._configured_models if item["character"] != character]
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = False
        if self._selected_list_character == character:
            if self._configured_models:
                self._select_model_list_item(self._configured_models[0]["character"])
            else:
                self._selected_list_character = ""
        self._refresh_model_list()
        if self._selected_list_character:
            self._show_model_detail()
        else:
            self._enter_model_selection()

    def _upsert_configured_model(self, character: str, costume: str):
        path = self._model_manager.get_model_json_path(character, costume)
        if not path:
            return
        window_width = 400
        window_height = 500
        window_x = -1
        window_y = -1
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            window_x = geo.left() + (geo.width() - window_width) // 2
            window_y = geo.top() + (geo.height() - window_height) // 2
        entry = {
            "character": character,
            "costume": costume,
            "path": path,
            "window_x": window_x,
            "window_y": window_y,
            "window_width": window_width,
            "window_height": window_height,
            "pixel_window_x": -1,
            "pixel_window_y": -1,
            "pet_mode": "live2d",
            "default_motion": "",
            "default_expression": "",
            "click_motion_actions": {},
        }
        self._restore_model_action_profile(entry)
        replace_index = self._editing_model_index
        if replace_index is None and not self._adding_model:
            replace_character = self._editing_list_character or self._selected_list_character
            for idx, item in enumerate(self._configured_models):
                if item["character"] == replace_character:
                    replace_index = idx
                    break
        if replace_index is not None and 0 <= replace_index < len(self._configured_models):
            previous = self._configured_models[replace_index]
            self._archive_model_action_profile(previous)
            preserved = dict(self._configured_models[replace_index])
            preserved.update(entry)
            preserve_keys = (
                "window_x",
                "window_y",
                "window_width",
                "window_height",
                "pixel_window_x",
                "pixel_window_y",
                "pet_mode",
            )
            if previous.get("character") == character and previous.get("costume") == costume:
                preserve_keys += (
                    "default_motion",
                    "default_expression",
                    "click_motion_actions",
                )
            for key in preserve_keys:
                if key in self._configured_models[replace_index]:
                    preserved[key] = self._configured_models[replace_index][key]
            entry = preserved
            self._configured_models[replace_index] = entry
        else:
            for idx, item in enumerate(self._configured_models):
                if item["character"] == character:
                    self._archive_model_action_profile(item)
                    preserved = dict(item)
                    preserved.update(entry)
                    preserve_keys = (
                        "window_x",
                        "window_y",
                        "window_width",
                        "window_height",
                        "pixel_window_x",
                        "pixel_window_y",
                        "pet_mode",
                    )
                    if item.get("costume") == costume:
                        preserve_keys += (
                            "default_motion",
                            "default_expression",
                            "click_motion_actions",
                        )
                    for key in preserve_keys:
                        if key in item:
                            preserved[key] = item[key]
                    entry = preserved
                    self._configured_models[idx] = entry
                    break
            else:
                self._configured_models.append(entry)
        self._selected_list_character = character
        self._editing_list_character = ""
        self._editing_model_index = None
        self._adding_model = False
        self._refresh_model_list()
        if not self._selecting_model:
            self._show_model_detail()

    def _user_profile_label(self, profile: dict) -> str:
        key = str(profile.get("key", "") or "").strip()
        name = str(profile.get("name", "") or "").strip()
        label = name or _tr("SettingsWindow.memory_default_user", default="当前用户")
        if key and key != DEFAULT_USER_PROFILE_KEY and key != name:
            label = f"{label} - {key}"
        return label

    def _normalized_user_profiles(self) -> list[dict]:
        if not self._cfg:
            return [{
                "key": DEFAULT_USER_PROFILE_KEY,
                "name": "",
                "avatar_color": BANDORI_PRIMARY,
                "avatar_path": "",
            }]
        if hasattr(self._cfg, "get_user_profiles"):
            return self._cfg.get_user_profiles()
        profiles = self._cfg.get("user_profiles", [])
        return profiles if isinstance(profiles, list) else []

    def _current_profile_key(self) -> str:
        if hasattr(self, "_user_profile_combo"):
            key = self._user_profile_combo.itemData(self._user_profile_combo.currentIndex())
            if key:
                return str(key)
        if self._cfg:
            return str(self._cfg.get("active_user_profile", "") or "")
        return ""

    def _reload_user_profile_combo(self, selected_key: str = ""):
        if not hasattr(self, "_user_profile_combo"):
            return
        profiles = self._normalized_user_profiles()
        active_key = selected_key or (self._cfg.get("active_user_profile", "") if self._cfg else "")
        self._loading_user_profile = True
        self._user_profile_combo.blockSignals(True)
        self._user_profile_combo.clear()
        selected_index = 0
        for profile in profiles:
            self._user_profile_combo.addItem(self._user_profile_label(profile), userData=profile.get("key", ""))
            if profile.get("key") == active_key:
                selected_index = self._user_profile_combo.count() - 1
        self._user_profile_combo.setCurrentIndex(selected_index)
        self._user_profile_combo.blockSignals(False)
        self._loading_user_profile = False
        self._delete_user_profile_btn.setEnabled(len(profiles) > 1)

    def _active_profile_form_name(self) -> str:
        mode = self._pov_mode.itemData(self._pov_mode.currentIndex()) if hasattr(self, "_pov_mode") else "off"
        if mode == "role":
            return self._saved_user_name.strip()
        return self._user_name.text().strip()

    def _profile_avatar_file_key(self) -> str:
        key = self._current_profile_key() or DEFAULT_USER_PROFILE_KEY
        safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in key)
        return safe[:48] or "default"

    def _load_user_profile_fields(self, profile: dict):
        self._saved_user_name = str(profile.get("name", "") or "").strip()
        self._user_avatar_path_pending = str(profile.get("avatar_path", "") or "").strip()
        saved_color = profile.get("avatar_color", BANDORI_PRIMARY)
        matched = False
        for btn in self._avatar_color_btns:
            checked = btn.property("avatar_color") == saved_color
            btn.setChecked(checked)
            matched = matched or checked
        if not matched and self._avatar_color_btns:
            self._avatar_color_btns[0].setChecked(True)
        mode = self._pov_mode.itemData(self._pov_mode.currentIndex()) if hasattr(self, "_pov_mode") else "off"
        if mode == "role":
            self._sync_role_display_name()
        else:
            self._user_name.setText(self._saved_user_name)
        self._style_avatar_buttons()
        self._update_user_avatar_preview()

    def _save_active_user_profile(self, show_info: bool = False, persist: bool = True):
        if not self._cfg:
            return
        name = self._active_profile_form_name()
        self._saved_user_name = name
        self._cfg.sync_active_user_profile(
            name,
            self._selected_avatar_color(),
            self._user_avatar_path_pending,
        )
        self._reload_user_profile_combo(self._cfg.get("active_user_profile", ""))
        if persist:
            try:
                self._cfg.save()
            except Exception:
                return
        self._refresh_memory_page()
        if show_info:
            InfoBar.success(
                _tr("SettingsWindow.pov_user_profile_saved_title", default="已保存"),
                _tr("SettingsWindow.pov_user_profile_saved_content", default="当前用户档案已保存。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _on_user_profile_selected(self, index: int):
        if self._loading_user_profile or not self._cfg:
            return
        selected_key = self._user_profile_combo.itemData(index) or ""
        current_key = self._cfg.get("active_user_profile", "")
        if selected_key == current_key:
            return
        self._save_active_user_profile(persist=False)
        self._cfg.set_active_user_profile(selected_key)
        profile = self._cfg.active_user_profile()
        if profile:
            self._load_user_profile_fields(profile)
        try:
            self._cfg.save()
        except Exception:
            pass
        self._reload_user_profile_combo(self._cfg.get("active_user_profile", ""))
        self._refresh_memory_page()

    def _create_user_profile(self):
        if not self._cfg:
            return
        self._save_active_user_profile(persist=False)
        existing = {profile.get("key", "") for profile in self._normalized_user_profiles()}
        name = _tr("SettingsWindow.pov_user_profile_new_name", default="新用户")
        key = make_user_profile_key(name, existing)
        profile = {
            "key": key,
            "name": name,
            "avatar_color": BANDORI_PRIMARY,
            "avatar_path": "",
        }
        self._cfg.upsert_user_profile(profile, make_active=True)
        self._load_user_profile_fields(profile)
        self._reload_user_profile_combo(key)
        try:
            self._cfg.save()
        except Exception:
            pass
        self._user_name.setFocus()
        self._user_name.selectAll()

    def _delete_active_user_profile(self):
        if not self._cfg:
            return
        key = self._current_profile_key()
        if not key:
            return
        self._cfg.delete_user_profile(key)
        profile = self._cfg.active_user_profile()
        if profile:
            self._load_user_profile_fields(profile)
        self._reload_user_profile_combo(self._cfg.get("active_user_profile", ""))
        try:
            self._cfg.save()
        except Exception:
            pass
        self._refresh_memory_page()

    def _style_avatar_buttons(self):
        for btn in self._avatar_color_btns:
            color = btn.property("avatar_color")
            checked = btn.isChecked()
            btn.setText("\u2713" if checked else "")
            size = 30 if checked else 28
            btn.setFixedSize(size, size)
            border = "3px solid #ffffff" if checked else "2px solid transparent"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: {border};
                    border-radius: {size // 2}px;
                    color: #ffffff;
                    font-weight: 900;
                    font-size: 14px;
                }}
            """)

    def _selected_avatar_color(self) -> str:
        for btn in self._avatar_color_btns:
            if btn.isChecked():
                return btn.property("avatar_color")
        return BANDORI_PRIMARY

    def _avatar_storage_dir(self):
        return app_base_dir() / ".runtime" / "chat_avatars"

    def _choose_user_avatar(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.llm_avatar_choose_title"),
            "",
            _tr("SettingsWindow.llm_avatar_image_filter"),
        )
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in _AVATAR_EXTENSIONS:
            return
        try:
            target_dir = self._avatar_storage_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"user_avatar_{self._profile_avatar_file_key()}{ext}"
            if os.path.abspath(path) != os.path.abspath(str(target)):
                shutil.copyfile(path, target)
            self._user_avatar_path_pending = str(target)
            self._update_user_avatar_preview()
        except OSError as exc:
            QMessageBox.critical(
                self,
                _tr("SettingsWindow.llm_avatar_save_failed_title"),
                _tr("SettingsWindow.llm_avatar_save_failed_content", error=str(exc)),
            )

    def _reset_user_avatar(self):
        self._user_avatar_path_pending = ""
        self._update_user_avatar_preview()

    def _update_user_avatar_preview(self):
        color = self._selected_avatar_color()
        dark = isDarkTheme()
        border = "#4a4a4a" if dark else "#d8d8d8"
        pixmap = _rounded_avatar_pixmap(self._user_avatar_path_pending, 44)
        if pixmap.isNull():
            name = self._user_name.text().strip()
            self._user_avatar_preview.setPixmap(QPixmap())
            fallback_name = name or _tr("ChatWindow.you")
            self._user_avatar_preview.setText(fallback_name[:1].upper() if fallback_name else "U")
            self._user_avatar_preview.setStyleSheet(f"""
                QLabel {{
                    background: {color};
                    color: #ffffff;
                    border: 1px solid {border};
                    border-radius: 22px;
                    font-size: 17px;
                    font-weight: 800;
                }}
            """)
        else:
            self._user_avatar_preview.setText("")
            self._user_avatar_preview.setPixmap(pixmap)
            self._user_avatar_preview.setStyleSheet(f"""
                QLabel {{
                    background: transparent;
                    border: 1px solid {border};
                    border-radius: 22px;
                }}
            """)
        self._user_avatar_reset_btn.setEnabled(bool(self._user_avatar_path_pending))

    def _on_avatar_color_clicked(self, btn: QPushButton):
        for b in self._avatar_color_btns:
            b.setChecked(False)
        btn.setChecked(True)
        self._style_avatar_buttons()
        self._update_user_avatar_preview()
        self._pulse_button(btn)

    @staticmethod
    def _pulse_button(btn):
        effect = QGraphicsColorizeEffect(btn)
        effect.setColor(QColor(255, 255, 255))
        effect.setStrength(0.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"strength", btn)
        anim.setDuration(120)
        anim.setStartValue(0.7)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: btn.setGraphicsEffect(None))
        anim.start()
