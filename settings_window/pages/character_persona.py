from pathlib import Path

from character_persona_manager import (
    CHARACTER_PERSONA_ACTIVE_KEY,
    CHARACTER_PERSONA_PRESETS_KEY,
    new_persona_id,
    normalize_character_persona_active,
    normalize_character_persona_presets,
    now_iso,
    persona_title_from_prompt,
)
from llm_manager import default_character_persona_prompt
from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class CharacterPersonaPageMixin:

    def _build_character_persona_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("characterPersonaPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title = TitleLabel(_tr("SettingsWindow.character_persona_title", default="角色人格"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.character_persona_subtitle",
            default="为每个角色管理自定义人格提示词，并可随时切换。自定义预设会替换默认预设；默认预设可在 characters 目录下查看。",
        ), page))
        layout.addWidget(subtitle)

        character_label = BodyLabel(_tr("SettingsWindow.character_persona_character", default="角色"), page)
        layout.addWidget(character_label)
        self._character_persona_character = OpaqueDropDownComboBox(page)
        self._character_persona_character.setFixedHeight(36)
        for char_key in self._model_manager.characters:
            self._character_persona_character.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
        self._character_persona_character.currentIndexChanged.connect(self._on_character_persona_character_changed)
        layout.addWidget(self._character_persona_character)

        preset_label = BodyLabel(_tr("SettingsWindow.character_persona_preset", default="当前人格预设"), page)
        layout.addWidget(preset_label)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        self._character_persona_preset = OpaqueDropDownComboBox(page)
        self._character_persona_preset.setFixedHeight(36)
        self._character_persona_preset.currentIndexChanged.connect(self._on_character_persona_preset_selected)
        preset_row.addWidget(self._character_persona_preset, 1)
        import_btn = PushButton(FluentIcon.FOLDER, _tr("SettingsWindow.character_persona_import", default="导入文档"), page)
        import_btn.setFixedHeight(36)
        import_btn.clicked.connect(self._import_character_persona_documents)
        preset_row.addWidget(import_btn)
        layout.addLayout(preset_row)

        name_label = BodyLabel(_tr("SettingsWindow.character_persona_name", default="预设名称"), page)
        layout.addWidget(name_label)
        self._character_persona_title = FluentContextLineEdit(page)
        self._character_persona_title.setObjectName("characterPersonaTitleInput")
        self._character_persona_title.setFixedHeight(36)
        self._character_persona_title.setPlaceholderText(_tr(
            "SettingsWindow.character_persona_name_placeholder",
            default="请输入预设名称",
        ))
        layout.addWidget(self._character_persona_title)

        prompt_label = BodyLabel(_tr("SettingsWindow.character_persona_prompt", default="人格提示词"), page)
        layout.addWidget(prompt_label)
        self._character_persona_prompt = FluentContextTextEdit(page)
        self._character_persona_prompt.setMinimumHeight(220)
        self._character_persona_prompt.setPlaceholderText(_tr(
            "SettingsWindow.character_persona_prompt_placeholder",
            default="在这里输入该角色的人格、经历、说话风格和行为准则。",
        ))
        layout.addWidget(self._character_persona_prompt, 1)

        self._character_persona_default_label = BodyLabel(
            _tr("SettingsWindow.character_persona_default_preview", default="默认人格预览（只读）"),
            page,
        )
        layout.addWidget(self._character_persona_default_label)
        self._character_persona_default_preview = FluentContextTextEdit(page)
        self._character_persona_default_preview.setReadOnly(True)
        self._character_persona_default_preview.setMinimumHeight(140)
        layout.addWidget(self._character_persona_default_preview)

        hint_panel = QWidget(page)
        hint_panel.setObjectName("characterPersonaHintPanel")
        hint_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hint_layout = QVBoxLayout(hint_panel)
        hint_layout.setContentsMargins(14, 12, 14, 12)
        hint_layout.setSpacing(0)
        hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.character_persona_hint",
            default="选择“使用默认人格”会恢复读取 characters 目录。删除当前启用预设时也会自动回退默认。",
        ), hint_panel))
        hint.setObjectName("characterPersonaHintText")
        hint_layout.addWidget(hint)
        layout.addWidget(hint_panel)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        save_new_btn = PushButton(FluentIcon.ADD, _tr("SettingsWindow.character_persona_save_new", default="另存为新预设"), page)
        save_new_btn.setFixedHeight(36)
        save_new_btn.clicked.connect(self._save_character_persona_as_new)
        btn_row.addWidget(save_new_btn)
        update_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.character_persona_update", default="保存并启用"), page)
        update_btn.setFixedHeight(36)
        update_btn.clicked.connect(self._save_character_persona_current)
        btn_row.addWidget(update_btn)
        delete_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.character_persona_delete", default="删除预设"), page)
        delete_btn.setFixedHeight(36)
        delete_btn.clicked.connect(self._delete_character_persona_current)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._style_character_persona_page(page)
        self._connect_theme_changed(lambda: self._style_character_persona_page(page))
        self._reload_character_persona_page()
        return page

    def _style_character_persona_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        text = "#d5dae5" if dark else "#4b5565"
        page.setStyleSheet(f"""
            QWidget#characterPersonaPage {{
                background: {page_bg};
            }}
            QWidget#characterPersonaHintPanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 8px;
            }}
            BodyLabel#characterPersonaHintText {{
                color: {text};
                font-size: 13px;
            }}
            QTextEdit {{
                border: 1px solid {panel_border};
                border-radius: 8px;
                padding: 8px;
                background: {panel_bg};
                color: {text};
            }}
            QLineEdit#characterPersonaTitleInput {{
                border: 1px solid {panel_border};
                border-radius: 8px;
                padding: 0 10px;
                background: {panel_bg};
                color: {text};
            }}
            QLineEdit#characterPersonaTitleInput:focus {{
                border: 1px solid {BANDORI_PRIMARY};
            }}
            {_fluent_scrollbar_qss(dark=dark)}
        """)

    def _character_persona_character_key(self) -> str:
        if not hasattr(self, "_character_persona_character"):
            return ""
        return self._character_persona_character.itemData(self._character_persona_character.currentIndex()) or ""

    def _character_persona_preset_id(self) -> str:
        if not hasattr(self, "_character_persona_preset"):
            return ""
        return self._character_persona_preset.itemData(self._character_persona_preset.currentIndex()) or ""

    def _character_persona_presets(self) -> dict[str, list[dict]]:
        return normalize_character_persona_presets(
            self._cfg.get(CHARACTER_PERSONA_PRESETS_KEY, {}) if self._cfg else {}
        )

    def _character_persona_active(self) -> dict[str, str]:
        return normalize_character_persona_active(
            self._cfg.get(CHARACTER_PERSONA_ACTIVE_KEY, {}) if self._cfg else {}
        )

    def _save_character_persona_data(self, presets: dict[str, list[dict]], active: dict[str, str]):
        if not self._cfg:
            return False
        self._cfg.set(CHARACTER_PERSONA_PRESETS_KEY, presets)
        self._cfg.set(CHARACTER_PERSONA_ACTIVE_KEY, active)
        try:
            _require_config_saved(self._cfg)
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.character_persona_failed_title", default="保存失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return False
        return True

    def _reload_character_persona_page(self):
        if not hasattr(self, "_character_persona_character"):
            return
        current = (self._current_char or self._cfg.get("character", "")) if self._cfg else self._current_char
        if current:
            for i in range(self._character_persona_character.count()):
                if self._character_persona_character.itemData(i) == current:
                    self._character_persona_character.setCurrentIndex(i)
                    break
        self._reload_character_persona_for_current_character()

    def _reload_character_persona_for_current_character(self):
        character = self._character_persona_character_key()
        presets = self._character_persona_presets().get(character, [])
        active_id = self._character_persona_active().get(character, "")

        self._character_persona_preset.blockSignals(True)
        self._character_persona_preset.clear()
        self._character_persona_preset.addItem(
            _tr("SettingsWindow.character_persona_use_default", default="使用默认人格"),
            userData="",
        )
        selected_index = 0
        for preset in presets:
            self._character_persona_preset.addItem(preset["title"], userData=preset["id"])
            if preset["id"] == active_id:
                selected_index = self._character_persona_preset.count() - 1
        self._character_persona_preset.setCurrentIndex(selected_index)
        self._character_persona_preset.blockSignals(False)

        self._character_persona_default_preview.setPlainText(
            default_character_persona_prompt(character, self._cfg)
        )
        selected_preset_id = active_id if selected_index > 0 else ""
        self._set_character_persona_default_preview_visible(not selected_preset_id)
        self._load_character_persona_editor(character, selected_preset_id)

    def _load_character_persona_editor(self, character: str, preset_id: str):
        self._character_persona_title.clear()
        self._character_persona_prompt.clear()
        if not preset_id:
            return
        for preset in self._character_persona_presets().get(character, []):
            if preset["id"] == preset_id:
                self._character_persona_title.setText(preset["title"])
                self._character_persona_prompt.setPlainText(preset["prompt"])
                return

    def _on_character_persona_character_changed(self, _index: int):
        self._reload_character_persona_for_current_character()

    def _on_character_persona_preset_selected(self, _index: int):
        character = self._character_persona_character_key()
        preset_id = self._character_persona_preset_id()
        active = self._character_persona_active()
        if preset_id:
            active[character] = preset_id
        else:
            active.pop(character, None)
        if not self._save_character_persona_data(self._character_persona_presets(), active):
            return
        self._set_character_persona_default_preview_visible(not preset_id)
        self._load_character_persona_editor(character, preset_id)

    def _set_character_persona_default_preview_visible(self, visible: bool):
        if hasattr(self, "_character_persona_default_label"):
            self._character_persona_default_label.setVisible(visible)
        if hasattr(self, "_character_persona_default_preview"):
            self._character_persona_default_preview.setVisible(visible)

    def _current_character_persona_payload(self) -> tuple[str, str, str]:
        character = self._character_persona_character_key()
        prompt = self._character_persona_prompt.toPlainText().strip()
        title = self._character_persona_title.text().strip() or persona_title_from_prompt(prompt)
        return character, title, prompt

    def _warn_empty_character_persona(self):
        InfoBar.warning(
            _tr("SettingsWindow.character_persona_empty_title", default="无法保存"),
            _tr("SettingsWindow.character_persona_empty_content", default="请先填写人格提示词。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _save_character_persona_as_new(self):
        character, title, prompt = self._current_character_persona_payload()
        if not character or not prompt:
            self._warn_empty_character_persona()
            return
        presets = self._character_persona_presets()
        active = self._character_persona_active()
        ts = now_iso()
        preset = {
            "id": new_persona_id(),
            "title": title,
            "prompt": prompt,
            "created_at": ts,
            "updated_at": ts,
        }
        presets.setdefault(character, []).append(preset)
        active[character] = preset["id"]
        if not self._save_character_persona_data(presets, active):
            return
        self._reload_character_persona_for_current_character()
        self._show_character_persona_saved()

    def _save_character_persona_current(self):
        character, title, prompt = self._current_character_persona_payload()
        if not character or not prompt:
            self._warn_empty_character_persona()
            return
        preset_id = self._character_persona_preset_id()
        if not preset_id:
            self._save_character_persona_as_new()
            return
        presets = self._character_persona_presets()
        active = self._character_persona_active()
        updated = False
        for preset in presets.get(character, []):
            if preset["id"] == preset_id:
                preset["title"] = title
                preset["prompt"] = prompt
                preset["updated_at"] = now_iso()
                updated = True
                break
        if not updated:
            self._save_character_persona_as_new()
            return
        active[character] = preset_id
        if not self._save_character_persona_data(presets, active):
            return
        self._reload_character_persona_for_current_character()
        self._show_character_persona_saved()

    def _delete_character_persona_current(self):
        character = self._character_persona_character_key()
        preset_id = self._character_persona_preset_id()
        if not character or not preset_id:
            return
        presets = self._character_persona_presets()
        active = self._character_persona_active()
        presets[character] = [preset for preset in presets.get(character, []) if preset["id"] != preset_id]
        if not presets[character]:
            presets.pop(character, None)
        if active.get(character) == preset_id:
            active.pop(character, None)
        if not self._save_character_persona_data(presets, active):
            return
        self._reload_character_persona_for_current_character()
        InfoBar.success(
            _tr("SettingsWindow.character_persona_deleted_title", default="已删除"),
            _tr("SettingsWindow.character_persona_deleted_content", default="已删除所选人格预设，并回退默认人格。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _import_character_persona_documents(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            _tr("SettingsWindow.character_persona_import_title", default="导入人格提示词"),
            "",
            _tr("SettingsWindow.character_persona_import_filter", default="Text files (*.md *.txt)"),
        )
        if not paths:
            return
        texts = []
        failed = []
        for path in sorted(paths):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    texts.append((path, content))
            except Exception:
                failed.append(path)
        if not texts:
            InfoBar.warning(
                _tr("SettingsWindow.character_persona_import_empty_title", default="导入失败"),
                _tr("SettingsWindow.character_persona_import_empty_content", default="没有读取到可用的文本内容。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        merged = "\n\n".join(f"# {Path(path).name}\n\n{content}" for path, content in texts)
        default_title = Path(texts[0][0]).stem if len(texts) == 1 else Path(texts[0][0]).stem + " 等"
        self._character_persona_title.setText(default_title)
        self._character_persona_prompt.setPlainText(merged)
        if failed:
            InfoBar.warning(
                _tr("SettingsWindow.character_persona_import_partial_title", default="部分导入"),
                _tr("SettingsWindow.character_persona_import_partial_content", default="部分文件读取失败，已导入可读取的文本。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _show_character_persona_saved(self):
        InfoBar.success(
            _tr("SettingsWindow.character_persona_saved_title", default="已保存"),
            _tr("SettingsWindow.character_persona_saved_content", default="角色人格预设已保存并启用。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
