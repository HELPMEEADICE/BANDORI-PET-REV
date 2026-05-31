from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class MemoryPageMixin:
    """Mixin providing memory editor and relationship guide pages for SettingsWindow."""

    def _build_relationship_guide_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("relationshipGuidePage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = TitleLabel(_tr("SettingsWindow.relationship_guide_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.relationship_guide_subtitle"), page))
        layout.addWidget(subtitle)

        for title_key, body_key in (
            ("SettingsWindow.relationship_guide_affection_title", "SettingsWindow.relationship_guide_affection_body"),
            ("SettingsWindow.relationship_guide_trust_title", "SettingsWindow.relationship_guide_trust_body"),
            ("SettingsWindow.relationship_guide_familiarity_title", "SettingsWindow.relationship_guide_familiarity_body"),
            ("SettingsWindow.relationship_guide_mood_title", "SettingsWindow.relationship_guide_mood_body"),
            ("SettingsWindow.relationship_guide_memory_title", "SettingsWindow.relationship_guide_memory_body"),
            ("SettingsWindow.relationship_guide_pov_title", "SettingsWindow.relationship_guide_pov_body"),
            ("SettingsWindow.relationship_guide_commands_title", "SettingsWindow.relationship_guide_commands_body"),
        ):
            panel = QWidget(page)
            panel.setObjectName("relationshipGuidePanel")
            panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(16, 14, 16, 14)
            panel_layout.setSpacing(6)
            section_title = StrongBodyLabel(_tr(title_key), panel)
            section_body = BodyLabel(_tr(body_key), panel)
            section_body.setWordWrap(True)
            section_body.setObjectName("relationshipGuideText")
            panel_layout.addWidget(section_title)
            panel_layout.addWidget(section_body)
            layout.addWidget(panel)

        layout.addStretch()
        self._style_relationship_guide_page(page)
        qconfig.themeChanged.connect(lambda: self._style_relationship_guide_page(page))
        return page

    def _style_relationship_guide_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f3f3f6" if dark else "#202126"
        page.setStyleSheet(f"""
            QWidget#relationshipGuidePage {{
                background: {page_bg};
            }}
            QWidget#relationshipGuidePanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 10px;
            }}
            BodyLabel#relationshipGuideText {{
                color: {text};
                font-size: 13px;
                line-height: 1.35em;
            }}
            SubtitleLabel {{
                color: {muted};
            }}
        """)

    def _build_memory_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("memoryPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = TitleLabel(_tr("SettingsWindow.memory_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.memory_subtitle"), page))
        layout.addWidget(subtitle)

        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(10)
        selector_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_character"), page))
        self._memory_character_combo = OpaqueDropDownComboBox(page)
        self._memory_character_combo.setFixedHeight(36)
        self._memory_character_combo.addItem(
            _tr("SettingsWindow.memory_global_profile", default="用户偏好（全局 · 对所有角色生效）"),
            userData=GLOBAL_MEMORY_CHARACTER,
        )
        selected_character = self._current_char or self._selected_list_character
        selected_index = 1 if self._model_manager.characters else 0
        for char_key in self._model_manager.characters:
            self._memory_character_combo.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
            if char_key == selected_character:
                selected_index = self._memory_character_combo.count() - 1
        self._memory_character_combo.setCurrentIndex(selected_index)
        self._memory_character_combo.currentIndexChanged.connect(lambda _i: self._refresh_memory_page())
        selector_row.addWidget(self._memory_character_combo, 1)
        self._memory_user_label = BodyLabel("", page)
        self._memory_user_label.setMinimumWidth(0)
        selector_row.addWidget(self._memory_user_label, 1)
        layout.addLayout(selector_row)

        self._memory_global_hint = _wrap_label(BodyLabel(
            _tr("SettingsWindow.memory_global_hint",
                default="全局用户偏好会整理你的长期信息（昵称、喜好、底线等），并在与任何角色开启新对话时自动提供，让 AI 更快了解你。"),
            page,
        ))
        self._memory_global_hint.setObjectName("memoryHint")
        self._memory_global_hint.setVisible(False)
        layout.addWidget(self._memory_global_hint)

        status_panel = QWidget(page)
        status_panel.setObjectName("memoryStatusPanel")
        status_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._memory_status_panel = status_panel
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(12)
        self._memory_affection_value = StrongBodyLabel("", status_panel)
        self._memory_trust_value = StrongBodyLabel("", status_panel)
        self._memory_familiarity_value = StrongBodyLabel("", status_panel)
        self._memory_mood_value = StrongBodyLabel("", status_panel)
        self._memory_affection_bar = ProgressBar(status_panel)
        self._memory_trust_bar = ProgressBar(status_panel)
        self._memory_familiarity_bar = ProgressBar(status_panel)
        self._memory_mood_bar = ProgressBar(status_panel)
        self._memory_updated_value = BodyLabel("", status_panel)
        for bar in (
            self._memory_affection_bar,
            self._memory_trust_bar,
            self._memory_familiarity_bar,
            self._memory_mood_bar,
        ):
            bar.setRange(0, 100)
            bar.setFixedHeight(8)
        for index, (label_key, value_label, bar) in enumerate((
            ("SettingsWindow.memory_affection", self._memory_affection_value, self._memory_affection_bar),
            ("SettingsWindow.memory_trust", self._memory_trust_value, self._memory_trust_bar),
            ("SettingsWindow.memory_familiarity", self._memory_familiarity_value, self._memory_familiarity_bar),
            ("SettingsWindow.memory_mood", self._memory_mood_value, self._memory_mood_bar),
        )):
            row = (index // 2) * 2
            column = (index % 2) * 2
            caption = BodyLabel(_tr(label_key), status_panel)
            caption.setObjectName("memoryStatCaption")
            status_layout.addWidget(caption, row, column)
            status_layout.addWidget(value_label, row, column + 1, alignment=Qt.AlignmentFlag.AlignRight)
            status_layout.addWidget(bar, row + 1, column, 1, 2)
            status_layout.setColumnStretch(column, 1)
            status_layout.setColumnStretch(column + 1, 1)
        self._memory_updated_value.setObjectName("memoryUpdated")
        status_layout.addWidget(self._memory_updated_value, 4, 0, 1, 4)
        layout.addWidget(status_panel)

        memory_title = SubtitleLabel(_tr("SettingsWindow.memory_editor_title"), page)
        layout.addWidget(memory_title)
        memory_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.memory_editor_hint"), page))
        memory_hint.setObjectName("memoryHint")
        layout.addWidget(memory_hint)

        list_panel = QWidget(page)
        list_panel.setObjectName("memoryListPanel")
        list_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(12, 10, 12, 12)
        list_layout.setSpacing(8)

        list_toolbar = QHBoxLayout()
        list_toolbar.setContentsMargins(0, 0, 0, 0)
        list_toolbar.setSpacing(8)
        self._memory_count_label = BodyLabel("", list_panel)
        self._memory_count_label.setObjectName("memoryListMeta")
        self._memory_select_all_check = QCheckBox(_tr("SettingsWindow.memory_select_all", default="全选"), list_panel)
        self._memory_select_all_check.setTristate(True)
        self._memory_select_all_check.stateChanged.connect(self._toggle_all_memory_selection)
        self._memory_batch_delete_btn = PushButton(
            FluentIcon.DELETE,
            _tr("SettingsWindow.memory_delete_selected", default="删除所选"),
            list_panel,
        )
        self._memory_batch_delete_btn.setFixedHeight(32)
        self._memory_batch_delete_btn.clicked.connect(self._delete_selected_memory_items)
        list_toolbar.addWidget(self._memory_count_label)
        list_toolbar.addStretch()
        list_toolbar.addWidget(self._memory_select_all_check)
        list_toolbar.addWidget(self._memory_batch_delete_btn)
        list_layout.addLayout(list_toolbar)

        self._memory_list_scroll = QScrollArea(list_panel)
        self._memory_list_scroll.setObjectName("memoryListScroll")
        self._memory_list_scroll.setWidgetResizable(True)
        self._memory_list_scroll.setMinimumHeight(150)
        self._memory_list_scroll.setMaximumHeight(230)
        self._memory_list_container = QWidget(self._memory_list_scroll)
        self._memory_list_layout = QVBoxLayout(self._memory_list_container)
        self._memory_list_layout.setContentsMargins(0, 0, 0, 0)
        self._memory_list_layout.setSpacing(6)
        self._memory_list_scroll.setWidget(self._memory_list_container)
        list_layout.addWidget(self._memory_list_scroll)
        layout.addWidget(list_panel)

        edit_row = QHBoxLayout()
        edit_row.setContentsMargins(0, 0, 0, 0)
        edit_row.setSpacing(10)
        edit_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_kind"), page))
        self._memory_kind_combo = OpaqueDropDownComboBox(page)
        self._memory_kind_combo.setFixedHeight(36)
        for kind in MEMORY_KIND_ORDER:
            self._memory_kind_combo.addItem(self._memory_kind_label(kind), userData=kind)
        edit_row.addWidget(self._memory_kind_combo, 1)
        edit_row.addSpacing(8)
        edit_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_importance"), page))
        self._memory_importance_slider = Slider(Qt.Orientation.Horizontal, page)
        self._memory_importance_slider.setRange(1, 100)
        self._memory_importance_slider.setSingleStep(1)
        self._memory_importance_slider.setValue(70)
        self._memory_importance_value = BodyLabel("70", page)
        self._memory_importance_slider.valueChanged.connect(
            lambda v: self._memory_importance_value.setText(str(v))
        )
        edit_row.addWidget(self._memory_importance_slider, 1)
        edit_row.addWidget(self._memory_importance_value)
        layout.addLayout(edit_row)

        self._memory_content = FluentContextTextEdit(page)
        self._memory_content.setPlaceholderText(_tr("SettingsWindow.memory_content_placeholder"))
        _horizontal_scroll_text_edit(self._memory_content)
        self._memory_content.setMinimumHeight(96)
        self._memory_content.setMaximumHeight(150)
        layout.addWidget(self._memory_content)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(8)
        new_btn = PushButton(FluentIcon.ADD, _tr("SettingsWindow.memory_new"), page)
        new_btn.setFixedHeight(36)
        new_btn.clicked.connect(self._start_new_memory)
        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.memory_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_memory_item)
        self._memory_delete_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.memory_delete"), page)
        self._memory_delete_btn.setFixedHeight(36)
        self._memory_delete_btn.clicked.connect(self._delete_memory_item)
        refresh_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.memory_refresh"), page)
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(lambda: self._refresh_memory_page())
        btn_row.addWidget(new_btn)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(self._memory_delete_btn)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        command_panel = QWidget(page)
        command_panel.setObjectName("memoryCommandPanel")
        command_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        command_layout = QVBoxLayout(command_panel)
        command_layout.setContentsMargins(16, 14, 16, 14)
        command_layout.setSpacing(8)
        command_layout.addWidget(SubtitleLabel(_tr("SettingsWindow.memory_commands_title"), command_panel))
        for key in (
            "SettingsWindow.memory_command_memory",
            "SettingsWindow.memory_command_status",
            "SettingsWindow.memory_command_remember",
            "SettingsWindow.memory_command_forget",
            "SettingsWindow.memory_command_affection",
            "SettingsWindow.memory_command_trust",
            "SettingsWindow.memory_command_familiarity",
            "SettingsWindow.memory_command_mood",
        ):
            line = BodyLabel(_tr(key), command_panel)
            line.setWordWrap(True)
            line.setObjectName("memoryCommandLine")
            command_layout.addWidget(line)
        layout.addWidget(command_panel)

        layout.addStretch()
        self._style_memory_page(page)
        qconfig.themeChanged.connect(lambda: self._style_memory_page(page))
        self._refresh_memory_page()
        return page

    def _memory_database(self) -> DatabaseManager:
        if self._memory_db is None:
            self._memory_db = DatabaseManager()
        return self._memory_db

    @staticmethod
    def _memory_kind_label(kind: str) -> str:
        return _tr(
            f"SettingsWindow.memory_kind_{kind}",
            default=MEMORY_KIND_LABELS.get(kind, kind or "note"),
        )

    def _selected_memory_character(self) -> str:
        if not hasattr(self, "_memory_character_combo"):
            return self._current_char or (self._model_manager.characters[0] if self._model_manager.characters else "")
        character = self._memory_character_combo.itemData(self._memory_character_combo.currentIndex())
        return character or self._current_char or (self._model_manager.characters[0] if self._model_manager.characters else "")

    def _memory_page_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_memory_character_combo",
                "_memory_user_label",
                "_memory_affection_value",
                "_memory_trust_value",
                "_memory_familiarity_value",
                "_memory_mood_value",
                "_memory_updated_value",
                "_memory_affection_bar",
                "_memory_trust_bar",
                "_memory_familiarity_bar",
                "_memory_mood_bar",
                "_memory_list_layout",
                "_memory_count_label",
                "_memory_select_all_check",
                "_memory_batch_delete_btn",
                "_memory_kind_combo",
                "_memory_importance_slider",
                "_memory_content",
                "_memory_delete_btn",
            )
        )

    def _memory_item_title(self, memory: dict) -> str:
        kind = self._memory_kind_label(memory.get("kind", "note"))
        content = str(memory.get("content", "") or "").replace("\n", " ").strip()
        if len(content) > 56:
            content = content[:56].rstrip() + "..."
        return f"{kind} - {content or _tr('SettingsWindow.memory_empty_content')}"

    def _memory_item_meta(self, memory: dict) -> str:
        importance = int(memory.get("importance") or 0)
        updated_at = memory.get("updated_at") or memory.get("created_at") or ""
        if updated_at:
            return _tr(
                "SettingsWindow.memory_item_meta",
                default="重要度 {importance} · 更新于 {time}",
                importance=importance,
                time=updated_at,
            )
        return _tr(
            "SettingsWindow.memory_item_meta_no_time",
            default="重要度 {importance}",
            importance=importance,
        )

    def _memory_user_display(self, user_key: str) -> str:
        role_character = role_character_from_user_key(user_key)
        if role_character:
            role_name = self._model_manager.get_display_name(role_character)
            return _tr("Relationship.role_user_display", role=role_name)
        if self._cfg and hasattr(self._cfg, "get_user_profiles"):
            for profile in self._cfg.get_user_profiles():
                if profile.get("key") == user_key:
                    return profile.get("name", "") or _tr("SettingsWindow.memory_default_user")
        return display_user_name(user_key)

    def _set_memory_kind(self, kind: str):
        for index in range(self._memory_kind_combo.count()):
            if self._memory_kind_combo.itemData(index) == kind:
                self._memory_kind_combo.setCurrentIndex(index)
                return
        self._memory_kind_combo.setCurrentIndex(0)

    @staticmethod
    def _memory_check_state(state) -> Qt.CheckState:
        try:
            return Qt.CheckState(state)
        except (TypeError, ValueError):
            return state

    def _clear_memory_list_layout(self):
        while self._memory_list_layout.count():
            item = self._memory_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _repolish_memory_row(self, row: QWidget):
        row.style().unpolish(row)
        row.style().polish(row)
        row.update()

    def _sync_memory_row_selection(self):
        selected_id = int(getattr(self, "_selected_memory_id", 0) or 0)
        for memory_id, (row, _check) in getattr(self, "_memory_row_widgets", {}).items():
            row.setProperty("selected", memory_id == selected_id)
            self._repolish_memory_row(row)

    def _update_memory_bulk_actions(self):
        memories = getattr(self, "_memory_items", [])
        memory_ids = {int(item.get("id") or 0) for item in memories if item.get("id")}
        selected_ids = set(getattr(self, "_selected_memory_ids", set())) & memory_ids
        self._selected_memory_ids = selected_ids

        count = len(memories)
        selected_count = len(selected_ids)
        self._memory_count_label.setText(
            _tr(
                "SettingsWindow.memory_list_count",
                default="{count} 条记忆 · 已选择 {selected} 条",
                count=count,
                selected=selected_count,
            )
        )
        self._memory_batch_delete_btn.setEnabled(selected_count > 0)
        self._memory_select_all_check.setEnabled(count > 0)

        self._memory_select_all_check.blockSignals(True)
        if not count or selected_count == 0:
            self._memory_select_all_check.setCheckState(Qt.CheckState.Unchecked)
        elif selected_count == count:
            self._memory_select_all_check.setCheckState(Qt.CheckState.Checked)
        else:
            self._memory_select_all_check.setCheckState(Qt.CheckState.PartiallyChecked)
        self._memory_select_all_check.blockSignals(False)

    def _render_memory_list(self):
        self._clear_memory_list_layout()
        self._memory_row_widgets = {}
        self._selected_memory_ids = set(getattr(self, "_selected_memory_ids", set()))
        valid_ids = {int(item.get("id") or 0) for item in self._memory_items if item.get("id")}
        self._selected_memory_ids &= valid_ids

        if not self._memory_items:
            empty = BodyLabel(_tr("SettingsWindow.memory_no_items", default="暂无长期记忆。"), self._memory_list_container)
            empty.setObjectName("memoryListEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(84)
            self._memory_list_layout.addWidget(empty)
            self._memory_list_layout.addStretch()
            self._update_memory_bulk_actions()
            return

        for memory in self._memory_items:
            memory_id = int(memory.get("id") or 0)
            row = QWidget(self._memory_list_container)
            row.setObjectName("memoryListRow")
            row.setProperty("selected", memory_id == int(getattr(self, "_selected_memory_id", 0) or 0))
            row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(str(memory.get("content", "") or ""))
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(10)

            check = QCheckBox(row)
            check.setChecked(memory_id in self._selected_memory_ids)
            check.stateChanged.connect(lambda state, mid=memory_id: self._update_memory_selection(mid, state))
            row_layout.addWidget(check, alignment=Qt.AlignmentFlag.AlignTop)

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(3)
            top_row = QHBoxLayout()
            top_row.setContentsMargins(0, 0, 0, 0)
            top_row.setSpacing(8)
            kind = StrongBodyLabel(self._memory_kind_label(memory.get("kind", "note")), row)
            kind.setObjectName("memoryRowKind")
            meta = BodyLabel(self._memory_item_meta(memory), row)
            meta.setObjectName("memoryRowMeta")
            top_row.addWidget(kind)
            top_row.addStretch()
            top_row.addWidget(meta)
            content = BodyLabel(str(memory.get("content", "") or _tr("SettingsWindow.memory_empty_content")), row)
            content.setObjectName("memoryRowContent")
            content.setWordWrap(True)
            text_col.addLayout(top_row)
            text_col.addWidget(content)
            row_layout.addLayout(text_col, 1)

            row.mousePressEvent = lambda event, mid=memory_id: self._select_memory_item_by_id(mid)
            self._memory_list_layout.addWidget(row)
            self._memory_row_widgets[memory_id] = (row, check)

        self._memory_list_layout.addStretch()
        self._update_memory_bulk_actions()
        self._sync_memory_row_selection()

    def _update_memory_selection(self, memory_id: int, state):
        selected_ids = set(getattr(self, "_selected_memory_ids", set()))
        if self._memory_check_state(state) == Qt.CheckState.Checked:
            selected_ids.add(memory_id)
        else:
            selected_ids.discard(memory_id)
        self._selected_memory_ids = selected_ids
        self._update_memory_bulk_actions()

    def _toggle_all_memory_selection(self, state):
        check_state = self._memory_check_state(state)
        if check_state == Qt.CheckState.PartiallyChecked:
            check_state = Qt.CheckState.Checked
        if check_state == Qt.CheckState.Checked:
            selected_ids = {int(item.get("id") or 0) for item in self._memory_items if item.get("id")}
        else:
            selected_ids = set()
        self._selected_memory_ids = selected_ids
        for memory_id, (_row, check) in getattr(self, "_memory_row_widgets", {}).items():
            check.blockSignals(True)
            check.setChecked(memory_id in selected_ids)
            check.blockSignals(False)
        self._update_memory_bulk_actions()

    def _load_memory_item(self, memory_id: int):
        self._selected_memory_id = int(memory_id or 0)
        memory = next((item for item in self._memory_items if item.get("id") == self._selected_memory_id), None)
        if memory:
            self._set_memory_kind(memory.get("kind", "note"))
            self._memory_importance_slider.setValue(max(1, min(100, int(memory.get("importance") or 50))))
            self._memory_content.setPlainText(memory.get("content", "") or "")
            self._memory_delete_btn.setEnabled(True)
        else:
            self._set_memory_kind("profile")
            self._memory_importance_slider.setValue(70)
            self._memory_content.clear()
            self._memory_delete_btn.setEnabled(False)
        self._sync_memory_row_selection()

    def _select_memory_item_by_id(self, memory_id: int):
        if not self._memory_page_ready():
            return
        self._load_memory_item(memory_id)

    def _refresh_memory_page(self, prefer_memory_id: int | None = None):
        if not self._memory_page_ready():
            return
        character = self._selected_memory_character()
        if not character:
            return
        db = self._memory_database()
        user_key = user_key_from_config(self._cfg)
        user_display = self._memory_user_display(user_key) or _tr("SettingsWindow.memory_default_user")
        is_global = character == GLOBAL_MEMORY_CHARACTER

        if hasattr(self, "_memory_status_panel"):
            self._memory_status_panel.setVisible(not is_global)
        if hasattr(self, "_memory_global_hint"):
            self._memory_global_hint.setVisible(is_global)

        self._memory_user_label.setText(_tr("SettingsWindow.memory_current_user", display=user_display))
        if not is_global:
            state = db.get_relationship_state(character, user_key)
            self._memory_affection_value.setText(
                _tr(
                    "SettingsWindow.memory_affection_value",
                    value=state["affection"],
                    label=affection_label(state["affection"]),
                )
            )
            self._memory_trust_value.setText(_tr("SettingsWindow.memory_score_value", value=state["trust"]))
            self._memory_familiarity_value.setText(_tr("SettingsWindow.memory_score_value", value=state["familiarity"]))
            self._memory_mood_value.setText(
                _tr(
                    "SettingsWindow.memory_mood_value",
                    mood=mood_label(state["mood"]),
                    value=state["mood_intensity"],
                )
            )
            self._memory_affection_bar.setValue(int(state["affection"]))
            self._memory_trust_bar.setValue(int(state["trust"]))
            self._memory_familiarity_bar.setValue(int(state["familiarity"]))
            self._memory_mood_bar.setValue(int(state["mood_intensity"]))
            updated_at = state.get("updated_at") or _tr("SettingsWindow.memory_never_updated")
            self._memory_updated_value.setText(_tr("SettingsWindow.memory_updated_at", time=updated_at))

        self._memory_items = db.get_character_memories(character, user_key, limit=100)
        target_id = self._selected_memory_id if prefer_memory_id is None else int(prefer_memory_id or 0)
        valid_ids = {int(item.get("id") or 0) for item in self._memory_items if item.get("id")}
        if target_id not in valid_ids:
            target_id = 0
        self._selected_memory_id = target_id
        self._render_memory_list()
        self._load_memory_item(target_id)

    def _start_new_memory(self):
        if not self._memory_page_ready():
            return
        self._load_memory_item(0)
        self._memory_content.setFocus()

    def _save_memory_item(self):
        if not self._memory_page_ready():
            return
        content = self._memory_content.toPlainText().strip()
        if not content:
            InfoBar.warning(
                _tr("SettingsWindow.memory_empty_title"),
                _tr("SettingsWindow.memory_empty_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        character = self._selected_memory_character()
        user_key = user_key_from_config(self._cfg)
        kind = self._memory_kind_combo.itemData(self._memory_kind_combo.currentIndex()) or "note"
        importance = self._memory_importance_slider.value()
        try:
            if self._selected_memory_id:
                saved = self._memory_database().update_character_memory(
                    self._selected_memory_id,
                    character,
                    user_key,
                    kind,
                    content,
                    importance,
                )
                memory_id = self._selected_memory_id if saved else 0
            else:
                memory_id = 0
            if not memory_id:
                memory_id = self._memory_database().add_character_memory(
                    character,
                    user_key,
                    kind,
                    content,
                    importance,
                )
            self._refresh_memory_page(memory_id)
            InfoBar.success(
                _tr("SettingsWindow.memory_saved_title"),
                _tr("SettingsWindow.memory_saved_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.memory_failed_title"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _delete_memory_item(self):
        if not self._memory_page_ready() or not self._selected_memory_id:
            return
        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.memory_delete_confirm_title"),
            _tr("SettingsWindow.memory_delete_confirm_content"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        character = self._selected_memory_character()
        user_key = user_key_from_config(self._cfg)
        try:
            self._memory_database().delete_character_memory(self._selected_memory_id, character, user_key)
            self._selected_memory_id = 0
            self._refresh_memory_page(0)
            InfoBar.success(
                _tr("SettingsWindow.memory_deleted_title"),
                _tr("SettingsWindow.memory_deleted_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.memory_failed_title"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _delete_selected_memory_items(self):
        if not self._memory_page_ready():
            return
        selected_ids = set(getattr(self, "_selected_memory_ids", set()))
        if not selected_ids:
            return
        count = len(selected_ids)
        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.memory_delete_selected_confirm_title", default="确认批量删除"),
            _tr(
                "SettingsWindow.memory_delete_selected_confirm_content",
                default="将删除所选 {count} 条长期记忆，删除后不会再进入聊天上下文。是否继续？",
                count=count,
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        character = self._selected_memory_character()
        user_key = user_key_from_config(self._cfg)
        try:
            deleted = self._memory_database().delete_character_memories(selected_ids, character, user_key)
            if self._selected_memory_id in selected_ids:
                self._selected_memory_id = 0
            self._selected_memory_ids = set()
            self._refresh_memory_page(self._selected_memory_id)
            InfoBar.success(
                _tr("SettingsWindow.memory_deleted_title"),
                _tr(
                    "SettingsWindow.memory_deleted_selected_content",
                    default="已删除 {count} 条长期记忆。",
                    count=deleted,
                ),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.memory_failed_title"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _style_memory_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f3f3f6" if dark else "#202126"
        input_bg = "#282828" if dark else "#ffffff"
        input_border = "#505050" if dark else "#d0d0d0"
        page.setStyleSheet(f"""
            QWidget#memoryPage {{
                background: {page_bg};
            }}
            QWidget#memoryStatusPanel,
            QWidget#memoryListPanel,
            QWidget#memoryCommandPanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 12px;
            }}
            BodyLabel#memoryStatCaption,
            BodyLabel#memoryUpdated,
            BodyLabel#memoryHint {{
                color: {muted};
                font-size: 13px;
            }}
            BodyLabel#memoryCommandLine {{
                color: {text};
                font-size: 13px;
            }}
            BodyLabel#memoryListMeta,
            BodyLabel#memoryListEmpty,
            BodyLabel#memoryRowMeta {{
                color: {muted};
                font-size: 12px;
            }}
            QScrollArea#memoryListScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#memoryListScroll > QWidget > QWidget {{
                background: transparent;
            }}
            QWidget#memoryListRow {{
                background: {"#2f2f2f" if dark else "#fbfbfc"};
                border: 1px solid {"#404040" if dark else "#ece6ea"};
                border-radius: 8px;
            }}
            QWidget#memoryListRow:hover {{
                background: {"#363636" if dark else "#fff5f8"};
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY_SOFT_HOVER};
            }}
            QWidget#memoryListRow[selected="true"] {{
                background: {"#3a2630" if dark else "#fff0f5"};
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
            BodyLabel#memoryRowContent {{
                color: {text};
                font-size: 13px;
            }}
            StrongBodyLabel#memoryRowKind {{
                color: {text};
                font-size: 13px;
            }}
            QCheckBox {{
                color: {text};
                spacing: 6px;
            }}
            QTextEdit {{
                background: {input_bg};
                color: {text};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
            {_fluent_scrollbar_qss(dark=dark)}
        """)
