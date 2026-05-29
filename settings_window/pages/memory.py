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
        selected_character = self._current_char or self._selected_list_character
        selected_index = 0
        for index, char_key in enumerate(self._model_manager.characters):
            self._memory_character_combo.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
            if char_key == selected_character:
                selected_index = index
        self._memory_character_combo.setCurrentIndex(selected_index)
        self._memory_character_combo.currentIndexChanged.connect(lambda _i: self._refresh_memory_page())
        selector_row.addWidget(self._memory_character_combo, 1)
        self._memory_user_label = BodyLabel("", page)
        self._memory_user_label.setMinimumWidth(0)
        selector_row.addWidget(self._memory_user_label, 1)
        layout.addLayout(selector_row)

        status_panel = QWidget(page)
        status_panel.setObjectName("memoryStatusPanel")
        status_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setHorizontalSpacing(18)
        status_layout.setVerticalSpacing(8)
        self._memory_affection_value = StrongBodyLabel("", status_panel)
        self._memory_trust_value = StrongBodyLabel("", status_panel)
        self._memory_familiarity_value = StrongBodyLabel("", status_panel)
        self._memory_mood_value = StrongBodyLabel("", status_panel)
        self._memory_updated_value = BodyLabel("", status_panel)
        for column, (label_key, value_label) in enumerate((
            ("SettingsWindow.memory_affection", self._memory_affection_value),
            ("SettingsWindow.memory_trust", self._memory_trust_value),
            ("SettingsWindow.memory_familiarity", self._memory_familiarity_value),
            ("SettingsWindow.memory_mood", self._memory_mood_value),
        )):
            caption = BodyLabel(_tr(label_key), status_panel)
            caption.setObjectName("memoryStatCaption")
            status_layout.addWidget(caption, 0, column)
            status_layout.addWidget(value_label, 1, column)
        self._memory_updated_value.setObjectName("memoryUpdated")
        status_layout.addWidget(self._memory_updated_value, 2, 0, 1, 4)
        layout.addWidget(status_panel)

        memory_title = SubtitleLabel(_tr("SettingsWindow.memory_editor_title"), page)
        layout.addWidget(memory_title)
        memory_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.memory_editor_hint"), page))
        memory_hint.setObjectName("memoryHint")
        layout.addWidget(memory_hint)

        self._memory_item_combo = OpaqueDropDownComboBox(page)
        self._memory_item_combo.setFixedHeight(36)
        self._memory_item_combo.currentIndexChanged.connect(self._on_memory_item_selected)
        layout.addWidget(self._memory_item_combo)

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
        self._memory_content.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
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
                "_memory_item_combo",
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

    def _refresh_memory_page(self, prefer_memory_id: int | None = None):
        if not self._memory_page_ready():
            return
        character = self._selected_memory_character()
        if not character:
            return
        db = self._memory_database()
        user_key = user_key_from_config(self._cfg)
        user_display = self._memory_user_display(user_key) or _tr("SettingsWindow.memory_default_user")
        self._memory_user_label.setText(_tr("SettingsWindow.memory_current_user", display=user_display))

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
        updated_at = state.get("updated_at") or _tr("SettingsWindow.memory_never_updated")
        self._memory_updated_value.setText(_tr("SettingsWindow.memory_updated_at", time=updated_at))

        self._memory_items = db.get_character_memories(character, user_key, limit=100)
        target_id = self._selected_memory_id if prefer_memory_id is None else int(prefer_memory_id or 0)
        selected_index = 0
        self._memory_item_combo.blockSignals(True)
        self._memory_item_combo.clear()
        self._memory_item_combo.addItem(_tr("SettingsWindow.memory_new_item"), userData=0)
        for memory in self._memory_items:
            self._memory_item_combo.addItem(self._memory_item_title(memory), userData=memory["id"])
            if memory["id"] == target_id:
                selected_index = self._memory_item_combo.count() - 1
        self._memory_item_combo.setCurrentIndex(selected_index)
        self._memory_item_combo.blockSignals(False)
        self._on_memory_item_selected(selected_index)

    def _on_memory_item_selected(self, index: int):
        if not self._memory_page_ready():
            return
        memory_id = int(self._memory_item_combo.itemData(index) or 0)
        self._selected_memory_id = memory_id
        memory = next((item for item in self._memory_items if item.get("id") == memory_id), None)
        if memory:
            self._set_memory_kind(memory.get("kind", "note"))
            self._memory_importance_slider.setValue(max(1, min(100, int(memory.get("importance") or 50))))
            self._memory_content.setPlainText(memory.get("content", "") or "")
            self._memory_delete_btn.setEnabled(True)
            return
        self._set_memory_kind("profile")
        self._memory_importance_slider.setValue(70)
        self._memory_content.clear()
        self._memory_delete_btn.setEnabled(False)

    def _start_new_memory(self):
        if not self._memory_page_ready():
            return
        self._memory_item_combo.setCurrentIndex(0)
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
        """)
