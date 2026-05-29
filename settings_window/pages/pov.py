from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class POVPageMixin:

    def _build_pov_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("povPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = TitleLabel(_tr("SettingsWindow.pov_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.pov_subtitle"), page))
        layout.addWidget(subtitle)

        profile_title = SubtitleLabel(_tr("SettingsWindow.llm_profile"), page)
        layout.addWidget(profile_title)

        user_profile_label = BodyLabel(_tr("SettingsWindow.pov_user_profile", default="当前用户"), page)
        layout.addWidget(user_profile_label)
        user_profile_row = QHBoxLayout()
        user_profile_row.setSpacing(8)
        self._user_profile_combo = OpaqueDropDownComboBox(page)
        self._user_profile_combo.setFixedHeight(36)
        self._user_profile_combo.currentIndexChanged.connect(self._on_user_profile_selected)
        user_profile_row.addWidget(self._user_profile_combo, 1)
        new_user_btn = PushButton(FluentIcon.ADD, _tr("SettingsWindow.pov_user_profile_new", default="新增"), page)
        new_user_btn.setFixedHeight(36)
        new_user_btn.clicked.connect(self._create_user_profile)
        user_profile_row.addWidget(new_user_btn)
        self._save_user_profile_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.pov_user_profile_save", default="保存用户"), page)
        self._save_user_profile_btn.setFixedHeight(36)
        self._save_user_profile_btn.clicked.connect(lambda: self._save_active_user_profile(show_info=True))
        user_profile_row.addWidget(self._save_user_profile_btn)
        self._delete_user_profile_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.pov_user_profile_delete", default="删除"), page)
        self._delete_user_profile_btn.setFixedHeight(36)
        self._delete_user_profile_btn.clicked.connect(self._delete_active_user_profile)
        user_profile_row.addWidget(self._delete_user_profile_btn)
        layout.addLayout(user_profile_row)

        name_label = BodyLabel(_tr("SettingsWindow.llm_display_name"), page)
        layout.addWidget(name_label)
        self._user_name = FluentContextLineEdit(page)
        self._user_name.setPlaceholderText(_tr("SettingsWindow.llm_display_name_placeholder"))
        self._user_name.setFixedHeight(36)
        self._user_name.textChanged.connect(lambda _text: self._update_user_avatar_preview())
        layout.addWidget(self._user_name)

        image_label = BodyLabel(_tr("SettingsWindow.llm_avatar_image"), page)
        layout.addWidget(image_label)
        avatar_row = QHBoxLayout()
        avatar_row.setSpacing(10)
        self._user_avatar_preview = QLabel(page)
        self._user_avatar_preview.setFixedSize(44, 44)
        self._user_avatar_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar_row.addWidget(self._user_avatar_preview)
        choose_avatar_btn = PushButton(FluentIcon.PHOTO, _tr("SettingsWindow.llm_avatar_choose"), page)
        choose_avatar_btn.setFixedHeight(36)
        choose_avatar_btn.clicked.connect(self._choose_user_avatar)
        avatar_row.addWidget(choose_avatar_btn)
        self._user_avatar_reset_btn = PushButton(FluentIcon.RETURN, _tr("SettingsWindow.llm_avatar_reset"), page)
        self._user_avatar_reset_btn.setFixedHeight(36)
        self._user_avatar_reset_btn.clicked.connect(self._reset_user_avatar)
        avatar_row.addWidget(self._user_avatar_reset_btn)
        avatar_row.addStretch()
        layout.addLayout(avatar_row)

        avatar_label = BodyLabel(_tr("SettingsWindow.llm_avatar_color"), page)
        layout.addWidget(avatar_label)
        self._avatar_colors = [
            (BANDORI_PRIMARY, "Bandori"),
            ("#e91e63", _tr("color.pink")),
            ("#9c27b0", _tr("color.purple")),
            ("#4caf50", _tr("color.green")),
            ("#ff9800", _tr("color.orange")),
            ("#f44336", _tr("color.red")),
            ("#00bcd4", _tr("color.cyan")),
            ("#607d8b", _tr("color.grey")),
        ]
        colors_row = QHBoxLayout()
        colors_row.setSpacing(6)
        self._avatar_color_btns: list[QPushButton] = []
        for color_hex, color_name in self._avatar_colors:
            btn = QPushButton("", page)
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color_name)
            btn.setProperty("avatar_color", color_hex)
            btn.clicked.connect(lambda checked, b=btn: self._on_avatar_color_clicked(b))
            self._avatar_color_btns.append(btn)
            colors_row.addWidget(btn)
        colors_row.addStretch()
        layout.addLayout(colors_row)

        mode_label = BodyLabel(_tr("SettingsWindow.pov_mode"), page)
        layout.addWidget(mode_label)
        self._pov_mode = OpaqueDropDownComboBox(page)
        self._pov_mode.addItem(_tr("SettingsWindow.pov_mode_off"), userData="off")
        self._pov_mode.addItem(_tr("SettingsWindow.pov_mode_custom"), userData="custom")
        self._pov_mode.addItem(_tr("SettingsWindow.pov_mode_role"), userData="role")
        self._pov_mode.setFixedHeight(36)
        self._pov_mode.currentIndexChanged.connect(self._on_pov_mode_changed)
        layout.addWidget(self._pov_mode)

        prompt_label = BodyLabel(_tr("SettingsWindow.pov_custom_prompt"), page)
        layout.addWidget(prompt_label)
        self._pov_custom_prompt = FluentContextTextEdit(page)
        self._pov_custom_prompt.setPlaceholderText(_tr("SettingsWindow.pov_custom_prompt_placeholder"))
        self._pov_custom_prompt.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._pov_custom_prompt.setMinimumHeight(64)
        self._pov_custom_prompt.setMaximumHeight(96)
        layout.addWidget(self._pov_custom_prompt)

        persona_label = BodyLabel(_tr("SettingsWindow.pov_saved_personas"), page)
        layout.addWidget(persona_label)
        persona_row = QHBoxLayout()
        persona_row.setSpacing(8)
        self._pov_persona_combo = OpaqueDropDownComboBox(page)
        self._pov_persona_combo.setFixedHeight(36)
        self._pov_persona_combo.currentIndexChanged.connect(self._on_pov_persona_selected)
        persona_row.addWidget(self._pov_persona_combo, 1)
        save_persona_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.pov_save_persona"), page)
        save_persona_btn.setFixedHeight(36)
        save_persona_btn.clicked.connect(self._save_current_pov_persona)
        persona_row.addWidget(save_persona_btn)
        delete_persona_btn = PushButton(FluentIcon.CLOSE, _tr("SettingsWindow.pov_delete_persona"), page)
        delete_persona_btn.setFixedHeight(36)
        delete_persona_btn.clicked.connect(self._delete_current_pov_persona)
        persona_row.addWidget(delete_persona_btn)
        layout.addLayout(persona_row)

        role_label = BodyLabel(_tr("SettingsWindow.pov_role_character"), page)
        layout.addWidget(role_label)
        self._pov_role_character = OpaqueDropDownComboBox(page)
        self._pov_role_character.setFixedHeight(36)
        for char_key in self._model_manager.characters:
            self._pov_role_character.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
        self._pov_role_character.currentIndexChanged.connect(self._sync_role_display_name)
        layout.addWidget(self._pov_role_character)

        pov_hint_panel = QWidget(page)
        pov_hint_panel.setObjectName("povHintPanel")
        pov_hint_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pov_hint_layout = QVBoxLayout(pov_hint_panel)
        pov_hint_layout.setContentsMargins(14, 12, 14, 12)
        pov_hint_layout.setSpacing(0)
        pov_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.pov_hint"), pov_hint_panel))
        pov_hint.setObjectName("povHintText")
        pov_hint.setMinimumHeight(52)
        pov_hint_layout.addWidget(pov_hint)
        layout.addWidget(pov_hint_panel)

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(lambda: self._save_llm_config("pov"))
        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self._style_pov_page(page)
        qconfig.themeChanged.connect(lambda: self._style_pov_page(page))

        return page

    def _style_pov_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        text = "#d5dae5" if dark else "#4b5565"
        page.setStyleSheet(f"""
            QWidget#povPage {{
                background: {page_bg};
            }}
            QWidget#povHintPanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 8px;
            }}
            BodyLabel#povHintText {{
                color: {text};
                font-size: 13px;
                line-height: 1.35em;
            }}
        """)

    def _on_pov_mode_changed(self, index: int):
        mode = self._pov_mode.itemData(index) or "off"
        self._pov_custom_prompt.setEnabled(mode == "custom")
        self._pov_persona_combo.setEnabled(mode == "custom")
        self._pov_role_character.setEnabled(mode == "role")
        self._user_name.setEnabled(mode != "role")
        if mode == "role":
            if self._user_name.text().strip():
                self._saved_user_name = self._user_name.text().strip()
            self._sync_role_display_name()
        else:
            self._user_name.setText(self._saved_user_name)

    def _normalized_pov_personas(self) -> list[dict]:
        if not self._cfg:
            return []
        raw_personas = self._cfg.get("pov_custom_personas", [])
        if not isinstance(raw_personas, list):
            return []
        personas = []
        seen_prompts = set()
        for item in raw_personas:
            if not isinstance(item, dict):
                continue
            prompt = str(item.get("prompt", "") or "").strip()
            if not prompt or prompt in seen_prompts:
                continue
            title = str(item.get("title", "") or "").strip() or self._pov_persona_title(prompt)
            personas.append({"title": title, "prompt": prompt})
            seen_prompts.add(prompt)
        return personas

    def _reload_pov_persona_combo(self):
        current_prompt = self._pov_custom_prompt.toPlainText().strip()
        self._pov_persona_combo.blockSignals(True)
        self._pov_persona_combo.clear()
        self._pov_persona_combo.addItem(_tr("SettingsWindow.pov_persona_new"), userData="")
        selected_index = 0
        for persona in self._normalized_pov_personas():
            self._pov_persona_combo.addItem(persona["title"], userData=persona["prompt"])
            if persona["prompt"] == current_prompt:
                selected_index = self._pov_persona_combo.count() - 1
        self._pov_persona_combo.setCurrentIndex(selected_index)
        self._pov_persona_combo.blockSignals(False)

    def _on_pov_persona_selected(self, index: int):
        prompt = self._pov_persona_combo.itemData(index) or ""
        for i in range(self._pov_mode.count()):
            if self._pov_mode.itemData(i) == "custom":
                self._pov_mode.setCurrentIndex(i)
                break
        if not prompt:
            self._pov_custom_prompt.clear()
            return
        self._pov_custom_prompt.setPlainText(prompt)

    @staticmethod
    def _pov_persona_title(prompt: str) -> str:
        title = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
        if len(title) > 24:
            title = title[:24] + "..."
        return title or "Persona"

    def _save_current_pov_persona(self):
        if not self._cfg:
            return
        prompt = self._pov_custom_prompt.toPlainText().strip()
        if not prompt:
            InfoBar.warning(
                _tr("SettingsWindow.pov_persona_empty_title"),
                _tr("SettingsWindow.pov_persona_empty_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        personas = [p for p in self._normalized_pov_personas() if p.get("prompt") != prompt]
        personas.append({"title": self._pov_persona_title(prompt), "prompt": prompt})
        self._cfg.set("pov_custom_personas", personas)
        self._cfg.set("pov_custom_prompt", prompt)
        try:
            self._cfg.save()
        except Exception:
            return
        self._reload_pov_persona_combo()
        InfoBar.success(
            _tr("SettingsWindow.pov_persona_saved_title"),
            _tr("SettingsWindow.pov_persona_saved_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _delete_current_pov_persona(self):
        if not self._cfg:
            return
        prompt = self._pov_persona_combo.itemData(self._pov_persona_combo.currentIndex()) or ""
        if not prompt:
            return
        personas = [p for p in self._normalized_pov_personas() if p.get("prompt") != prompt]
        self._cfg.set("pov_custom_personas", personas)
        try:
            self._cfg.save()
        except Exception:
            return
        self._reload_pov_persona_combo()
        InfoBar.success(
            _tr("SettingsWindow.pov_persona_deleted_title"),
            _tr("SettingsWindow.pov_persona_deleted_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _sync_role_display_name(self):
        if self._pov_mode.itemData(self._pov_mode.currentIndex()) != "role":
            return
        self._user_name.setText(self._pov_role_character.currentText())
