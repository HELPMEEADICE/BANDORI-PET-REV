from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class DataManagementPageMixin:

    def _data_management_categories(self) -> list[tuple[str, str, str]]:
        return [
            (
                DATA_CATEGORY_LIVE2D,
                _tr("SettingsWindow.data_category_live2d", default="Live2D 角色/服装/动作"),
                _tr("SettingsWindow.data_category_live2d_desc", default="当前台前展示的全部角色、服装和自定义动作。"),
            ),
            (
                DATA_CATEGORY_CLICK_PROFILES,
                _tr("SettingsWindow.data_category_click_profiles", default="点击动作反馈预设"),
                _tr("SettingsWindow.data_category_click_profiles_desc", default="已保存的点击动作反馈自定义预设档案，不包含系统内置原版预设。"),
            ),
            (
                DATA_CATEGORY_LLM,
                _tr("SettingsWindow.data_category_llm", default="LLM 配置"),
                _tr("SettingsWindow.data_category_llm_desc", default="自定义 LLM 内容；不包含内置预设和 API 密钥。"),
            ),
            (
                DATA_CATEGORY_TTS,
                _tr("SettingsWindow.data_category_tts", default="TTS 配置"),
                _tr("SettingsWindow.data_category_tts_desc", default="TTS 开关、接口、语言、参考音色和生成参数。"),
            ),
            (
                DATA_CATEGORY_POV,
                _tr("SettingsWindow.data_category_pov", default="POV 配置"),
                _tr("SettingsWindow.data_category_pov_desc", default="POV 模式、自定义提示词、角色扮演对象和保存的人设。"),
            ),
            (
                DATA_CATEGORY_RELATIONSHIP,
                _tr("SettingsWindow.data_category_relationship", default="好感度与记忆"),
                _tr("SettingsWindow.data_category_relationship_desc", default="角色关系状态和长期记忆。"),
            ),
            (
                DATA_CATEGORY_REMINDERS,
                _tr("SettingsWindow.data_category_reminders", default="闹钟 / 番茄钟"),
                _tr("SettingsWindow.data_category_reminders_desc", default="闹钟、番茄钟和提醒展示方式。"),
            ),
            (
                DATA_CATEGORY_COMPACT,
                _tr("SettingsWindow.data_category_compact", default="悬浮窗配置"),
                _tr("SettingsWindow.data_category_compact_desc", default="悬浮窗、状态端口、颜色、透明度和字体。"),
            ),
            (
                DATA_CATEGORY_CHAT,
                _tr("SettingsWindow.data_category_chat", default="聊天接入配置"),
                _tr("SettingsWindow.data_category_chat_desc", default="外部聊天接入端口、上下文和 Token。"),
            ),
            (
                DATA_CATEGORY_MCP,
                _tr("SettingsWindow.data_category_mcp", default="MCP / Computer Use"),
                _tr("SettingsWindow.data_category_mcp_desc", default="MCP 服务器和电脑控制权限。"),
            ),
            (
                DATA_CATEGORY_MISC,
                _tr("SettingsWindow.data_category_misc", default="画质与杂项"),
                _tr("SettingsWindow.data_category_misc_desc", default="画质、刷新率、垂直同步、置顶兼容、自启动、不透明度、主题和语言等。"),
            ),
            (
                DATA_CATEGORY_ALL,
                _tr("SettingsWindow.data_category_all", default="全部迁移配置"),
                _tr("SettingsWindow.data_category_all_desc", default="导出以上全部内容，用于迁移到另一份 BandoriPet。"),
            ),
        ]


    def _build_data_management_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("dataManagementPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.data_management_title", default="数据管理"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.data_management_subtitle",
            default="按类别导入或导出设置配置；全部迁移配置会把可迁移内容打包到一个 JSON 文件里。",
        ), page))
        layout.addWidget(subtitle)

        select_row = QHBoxLayout()
        select_row.setContentsMargins(0, 0, 0, 0)
        select_row.setSpacing(10)
        select_row.addWidget(BodyLabel(_tr("SettingsWindow.data_management_category", default="配置类别"), page))
        self._data_category_combo = OpaqueDropDownComboBox(page)
        self._data_category_combo.setFixedHeight(36)
        for key, label, _desc in self._data_management_categories():
            self._data_category_combo.addItem(label, userData=key)
        self._data_category_combo.currentIndexChanged.connect(self._update_data_management_hints)
        select_row.addWidget(self._data_category_combo, 1)
        layout.addLayout(select_row)

        self._data_category_detail = _wrap_label(BodyLabel("", page))
        layout.addWidget(self._data_category_detail)
        self._data_section_hint = _wrap_label(BodyLabel("", page))
        layout.addWidget(self._data_section_hint)
        self._data_security_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.data_note_llm_keys",
            default="LLM API 密钥不会导出，也不会被导入覆盖。",
        ), page))
        layout.addWidget(self._data_security_hint)
        self._data_merge_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.data_note_relationship",
            default="好感度与记忆会合并写入本地数据库。",
        ), page))
        layout.addWidget(self._data_merge_hint)
        self._data_hint_labels = [
            self._data_category_detail,
            self._data_section_hint,
            self._data_security_hint,
            self._data_merge_hint,
        ]

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        export_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.data_export", default="导出配置"), page)
        export_btn.setFixedHeight(36)
        export_btn.clicked.connect(self._export_data_package)
        import_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.data_import", default="导入配置"), page)
        import_btn.setFixedHeight(36)
        import_btn.clicked.connect(self._import_data_package)
        action_row.addWidget(export_btn)
        action_row.addWidget(import_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        chat_title = SubtitleLabel(_tr("SettingsWindow.chat_data_title"), page)
        layout.addWidget(chat_title)
        layout.addWidget(_wrap_label(BodyLabel(_tr("SettingsWindow.chat_data_hint"), page)))

        chat_action_row = QHBoxLayout()
        chat_action_row.setContentsMargins(0, 0, 0, 0)
        chat_action_row.setSpacing(8)
        chat_export_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.chat_data_export"), page)
        chat_export_btn.setFixedHeight(36)
        chat_export_btn.clicked.connect(self._export_chat_database)
        chat_import_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.chat_data_import"), page)
        chat_import_btn.setFixedHeight(36)
        chat_import_btn.clicked.connect(self._import_chat_database)
        chat_action_row.addWidget(chat_export_btn)
        chat_action_row.addWidget(chat_import_btn)
        chat_action_row.addStretch()
        layout.addLayout(chat_action_row)

        layout.addStretch()

        self._update_data_management_hints()
        self._style_data_management_page(page)
        qconfig.themeChanged.connect(lambda: self._style_data_management_page(page))
        return page


    def _style_data_management_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        muted = "#a0a7b7" if dark else "#6b7280"
        page.setStyleSheet(f"""
            QWidget#dataManagementPage {{
                background: {page_bg};
            }}
            BodyLabel[dataManagementHint="true"] {{
                color: {muted};
                font-size: 13px;
            }}
        """)
        for label in getattr(self, "_data_hint_labels", []):
            label.setProperty("dataManagementHint", True)
            label.style().unpolish(label)
            label.style().polish(label)
        self._refresh_theme_widget_styles(page)


    def _selected_data_category(self) -> str:
        if not hasattr(self, "_data_category_combo"):
            return DATA_CATEGORY_ALL
        return self._data_category_combo.itemData(self._data_category_combo.currentIndex()) or DATA_CATEGORY_ALL


    def _data_category_label(self, category: str) -> str:
        for key, label, _desc in self._data_management_categories():
            if key == category:
                return label
        return category


    def _update_data_management_hints(self, *_args):
        if not hasattr(self, "_data_category_detail"):
            return
        category = self._selected_data_category()
        for key, _label, desc in self._data_management_categories():
            if key == category:
                self._data_category_detail.setText(desc)
                break
        sections = self._data_sections_for_category(category)
        section_names = " / ".join(self._data_category_label(section) for section in sections)
        self._data_section_hint.setText(_tr(
            "SettingsWindow.data_sections_hint",
            default="将处理：{sections}",
            sections=section_names,
        ))


    def _data_sections_for_category(self, category: str) -> list[str]:
        if category == DATA_CATEGORY_ALL:
            return list(DATA_EXPORT_ORDER)
        return [category]


    def _default_data_package_path(self, category: str) -> str:
        safe_category = category if category != DATA_CATEGORY_ALL else "all"
        filename = f"bandori-settings-{safe_category}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        return str(app_base_dir() / filename)


    def _sync_loaded_config_pages_for_data_export(self):
        if not self._cfg:
            return
        if self._configured_models:
            self._save_configured_models()
        if self._llm_config_widgets_ready():
            self._save_llm_config(show_info=False)
        if self._tts_config_widgets_ready():
            self._save_tts_config(show_info=False)
        if self._compact_config_widgets_ready():
            self._save_compact_window_config(show_info=False, emit_update=False)
        if self._chat_integration_widgets_ready():
            self._save_chat_integration_config(show_info=False, emit_update=False)
        if self._mcp_computer_widgets_ready():
            self._save_mcp_computer_config(show_info=False)
        if hasattr(self, "_reminder_display_mode"):
            self._save_reminder_config(show_info=False, emit_update=False)
        if hasattr(self, "_opacity_slider"):
            self._cfg.set("fps", self._current_fps_setting())
            self._cfg.set("opacity", self._opacity_slider.value() / 100.0)
            self._cfg.set("dark_theme", self._theme_combo.currentData())
            self._cfg.set("vsync", self._current_vsync_setting())
            self._cfg.set("game_topmost", self._game_topmost_switch.isChecked())
            self._cfg.set("chat_window_normal_window", self._chat_window_normal_window_switch.isChecked())
            self._cfg.set("hide_live2d_model", self._hide_live2d_model_switch.isChecked())
            self._cfg.set("auto_start", self._auto_start_supported and self._auto_start_switch.isChecked())
            self._cfg.set("live2d_quality", self._live2d_quality)
            self._cfg.set("live2d_scale", self._live2d_scale)
            self._cfg.save()


    def _export_data_package(self):
        if not self._cfg:
            return
        category = self._selected_data_category()
        try:
            self._sync_loaded_config_pages_for_data_export()
            payload = self._build_data_package(category)
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.data_export_failed_title", default="导出失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _tr("SettingsWindow.data_export_dialog", default="导出设置配置"),
            self._default_data_package_path(category),
            _tr("SettingsWindow.data_package_filter", default="BandoriPet 设置配置 (*.json)"),
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.data_export_failed_title", default="导出失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        InfoBar.success(
            _tr("SettingsWindow.data_export_success_title", default="配置已导出"),
            _tr(
                "SettingsWindow.data_export_success_content",
                default="已导出 {count} 个配置分组。",
                count=len(payload.get("sections", {})),
            ),
            duration=2600,
            position=InfoBarPosition.TOP,
            parent=self,
        )


    def _import_data_package(self):
        if not self._cfg:
            return
        category = self._selected_data_category()
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.data_import_dialog", default="导入设置配置"),
            str(app_base_dir()),
            _tr("SettingsWindow.data_package_filter", default="BandoriPet 设置配置 (*.json)"),
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            sections = self._extract_data_package_sections(payload, category)
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.data_import_failed_title", default="导入失败"),
                str(exc),
                duration=4500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not sections:
            InfoBar.warning(
                _tr("SettingsWindow.data_import_empty_title", default="没有可导入内容"),
                _tr("SettingsWindow.data_import_empty_content", default="所选文件里没有当前类别的配置。"),
                duration=2800,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.data_import_confirm_title", default="确认导入配置"),
            _tr(
                "SettingsWindow.data_import_confirm_content",
                default="将导入“{category}”中的 {count} 个配置分组，并覆盖对应本地设置。是否继续？",
                category=self._data_category_label(category),
                count=len(sections),
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            summary = self._apply_data_package_sections(sections)
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.data_import_failed_title", default="导入失败"),
                str(exc),
                duration=4500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._refresh_after_data_import(sections.keys())
        InfoBar.success(
            _tr("SettingsWindow.data_import_success_title", default="配置已导入"),
            _tr(
                "SettingsWindow.data_import_success_content",
                default="已导入 {count} 个配置分组。",
                count=len(summary),
            ),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )


    def _build_data_package(self, category: str) -> dict:
        sections = {}
        for section in self._data_sections_for_category(category):
            if section == DATA_CATEGORY_RELATIONSHIP:
                from database_manager import export_relationship_data
                sections[section] = {
                    "relationship": export_relationship_data(),
                }
                continue
            keys = DATA_CONFIG_KEYS.get(section, ())
            data = self._config_values_for_data_section(section, keys)
            sections[section] = {"config": data}
        return {
            "format": DATA_PACKAGE_FORMAT,
            "version": DATA_PACKAGE_VERSION,
            "app_version": APP_VERSION,
            "category": category,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "sections": sections,
        }


    def _config_values_for_data_section(self, section: str, keys) -> dict:
        data = {}
        for key in keys:
            value = self._cfg.get(key, None)
            if key in SECRET_CONFIG_KEYS:
                continue
            if section == DATA_CATEGORY_LLM and key == "llm_api_profiles":
                data[key] = self._sanitized_llm_profiles(value)
                continue
            if section == DATA_CATEGORY_LLM and key == "llm_active_api_profile":
                active = str(value or "").strip()
                data[key] = "" if active in BUILTIN_LLM_API_PROFILE_NAMES else active
                continue
            if section == DATA_CATEGORY_CLICK_PROFILES and key == "click_motion_profiles":
                data[key] = self._sanitized_click_motion_profiles(value)
                continue
            data[key] = value
        return data


    def _sanitized_llm_profiles(self, profiles) -> list[dict]:
        if not isinstance(profiles, list):
            return []
        result = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            name = str(profile.get("name", "")).strip()
            if not name or name in BUILTIN_LLM_API_PROFILE_NAMES:
                continue
            cleaned = {
                key: value
                for key, value in profile.items()
                if key not in SECRET_CONFIG_KEYS
            }
            cleaned["name"] = name
            result.append(cleaned)
        return result


    def _sanitized_click_motion_profiles(self, profiles) -> list[dict]:
        from click_motion_presets import BUILTIN_PROFILE_NAMES

        if not isinstance(profiles, list):
            return []
        result = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            name = str(profile.get("name", "")).strip()
            if not name or name in BUILTIN_PROFILE_NAMES:
                continue
            result.append(profile)
        return result


    def _extract_data_package_sections(self, payload, selected_category: str) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("settings package must be a JSON object")
        if payload.get("format") != DATA_PACKAGE_FORMAT:
            raise ValueError("unsupported settings package format")
        sections = payload.get("sections", {})
        if not isinstance(sections, dict):
            raise ValueError("settings package sections must be a JSON object")
        if selected_category == DATA_CATEGORY_ALL:
            return {
                key: value
                for key, value in sections.items()
                if key in DATA_EXPORT_ORDER and isinstance(value, dict)
            }
        section = sections.get(selected_category)
        return {selected_category: section} if isinstance(section, dict) else {}


    def _apply_data_package_sections(self, sections: dict) -> dict:
        summary = {}
        for section, content in sections.items():
            if section == DATA_CATEGORY_RELATIONSHIP:
                relationship_data = content.get("relationship", {})
                from database_manager import import_relationship_data
                summary[section] = import_relationship_data(relationship_data)
                continue
            config_data = content.get("config", {})
            if not isinstance(config_data, dict):
                continue
            applied = self._apply_config_data_section(section, config_data)
            if applied:
                summary[section] = applied
        self._cfg.save()
        if hasattr(self._cfg, "load"):
            self._cfg.load()
        return summary


    def _apply_config_data_section(self, section: str, config_data: dict) -> int:
        allowed = set(DATA_CONFIG_KEYS.get(section, ()))
        if not allowed:
            return 0
        applied = 0
        if section == DATA_CATEGORY_LLM:
            config_data = self._prepare_llm_import_data(config_data)
        for key, value in config_data.items():
            if key not in allowed or key in SECRET_CONFIG_KEYS:
                continue
            self._cfg.set(key, value)
            applied += 1
        return applied


    def _prepare_llm_import_data(self, config_data: dict) -> dict:
        data = {
            key: value
            for key, value in config_data.items()
            if key not in SECRET_CONFIG_KEYS
        }
        imported_profiles = self._sanitized_llm_profiles(data.get("llm_api_profiles", []))
        if imported_profiles:
            existing = self._cfg.get("llm_api_profiles", [])
            if not isinstance(existing, list):
                existing = []
            imported_names = {profile["name"] for profile in imported_profiles}
            merged = []
            old_by_name = {
                str(profile.get("name", "")).strip(): profile
                for profile in existing
                if isinstance(profile, dict)
            }
            for profile in existing:
                if not isinstance(profile, dict):
                    continue
                name = str(profile.get("name", "")).strip()
                if name and name not in imported_names:
                    merged.append(profile)
            for profile in imported_profiles:
                name = profile["name"]
                previous = old_by_name.get(name, {})
                restored = dict(profile)
                for secret_key in SECRET_CONFIG_KEYS:
                    if previous.get(secret_key):
                        restored[secret_key] = previous.get(secret_key)
                merged.append(restored)
            data["llm_api_profiles"] = merged
        else:
            data.pop("llm_api_profiles", None)
        active = str(data.get("llm_active_api_profile", "") or "").strip()
        if active in BUILTIN_LLM_API_PROFILE_NAMES:
            data["llm_active_api_profile"] = ""
        return data


    def _refresh_after_data_import(self, sections):
        imported_sections = set(sections)
        self._configured_models = self._load_configured_models()
        self._current_char = self._cfg.get("character", self._current_char) if self._cfg else self._current_char
        self._current_costume = self._cfg.get("costume", self._current_costume) if self._cfg else self._current_costume
        if self._configured_models:
            self._selected_list_character = self._current_char or self._configured_models[0]["character"]
        self._live2d_quality = normalize_live2d_quality(self._cfg.get("live2d_quality", "balanced"))
        self._live2d_scale = clamp_live2d_scale(
            self._cfg.get("live2d_scale", 0),
            use_device_pixel_ratio_default=True,
        )
        self._fps = int(self._cfg.get("fps", self._fps) or self._fps)
        self._opacity = float(self._cfg.get("opacity", self._opacity) or self._opacity)
        self._vsync = bool(self._cfg.get("vsync", self._vsync))
        self._game_topmost = bool(self._cfg.get("game_topmost", self._game_topmost))
        self._chat_window_normal_window = bool(
            self._cfg.get("chat_window_normal_window", self._chat_window_normal_window)
        )
        self._hide_live2d_model = bool(self._cfg.get("hide_live2d_model", self._hide_live2d_model))
        self._live2d_idle_actions_enabled = bool(self._cfg.get("live2d_idle_actions_enabled", self._live2d_idle_actions_enabled))
        self._live2d_head_tracking_enabled = bool(self._cfg.get("live2d_head_tracking_enabled", self._live2d_head_tracking_enabled))
        self._live2d_mutual_gaze_enabled = bool(self._cfg.get("live2d_mutual_gaze_enabled", self._live2d_mutual_gaze_enabled))

        self._refresh_model_list()
        if self._selected_list_character:
            self._show_model_detail()
        if self._llm_config_widgets_ready():
            self._load_llm_config()
        if self._tts_config_widgets_ready():
            self._load_tts_config()
        if self._compact_config_widgets_ready():
            self._load_compact_window_config()
        if self._chat_integration_widgets_ready():
            self._load_chat_integration_config()
        if self._mcp_computer_widgets_ready():
            self._load_mcp_computer_config()
        if hasattr(self, "_reminder_display_mode"):
            self._load_reminder_config()
        if self._memory_page_ready() and DATA_CATEGORY_RELATIONSHIP in imported_sections:
            self._refresh_memory_page()
        self._refresh_side_and_quality_widgets()
        if DATA_CATEGORY_MISC in imported_sections and hasattr(self, "_auto_start_switch"):
            self._apply_auto_start_setting()
        self._emit_imported_settings(imported_sections)
        self._update_data_management_hints()


    def _refresh_side_and_quality_widgets(self):
        if hasattr(self, "_quality_combo"):
            for index in range(self._quality_combo.count()):
                if self._quality_combo.itemData(index) == self._live2d_quality:
                    self._quality_combo.blockSignals(True)
                    self._quality_combo.setCurrentIndex(index)
                    self._quality_combo.blockSignals(False)
                    break
            self._quality_detail.setText(self._quality_detail_text(self._live2d_quality))
        if hasattr(self, "_live2d_scale_slider"):
            self._live2d_scale_slider.blockSignals(True)
            self._live2d_scale_slider.setValue(self._live2d_scale)
            self._live2d_scale_slider.blockSignals(False)
            self._live2d_scale_input.setText(str(self._live2d_scale))
        if hasattr(self, "_fps_slider"):
            self._fps_slider.blockSignals(True)
            self._fps_slider.setValue(max(30, min(240, self._fps)))
            self._fps_slider.blockSignals(False)
            self._fps_value.setText(_tr("SettingsWindow.fps_value", v=self._fps_slider.value()))
            if hasattr(self, "_vsync_switch"):
                self._vsync_switch.blockSignals(True)
                self._vsync_switch.setChecked(self._vsync)
                self._vsync_switch.blockSignals(False)
            self._on_vsync_changed(self._vsync)
        if hasattr(self, "_opacity_slider"):
            self._opacity_slider.setValue(max(20, min(100, int(self._opacity * 100))))
            self._game_topmost_switch.setChecked(self._game_topmost)
            self._chat_window_normal_window_switch.setChecked(self._chat_window_normal_window)
            self._hide_live2d_model_switch.setChecked(self._hide_live2d_model)
            self._auto_start_switch.setChecked(bool(self._cfg.get("auto_start", False)) if self._cfg else False)
            self._sync_live2d_behavior_switches()
            self._opacity_value.setText(_tr("SettingsWindow.opacity_value", v=self._opacity_slider.value()))
        if hasattr(self, "_lang_combo"):
            language = normalize_language(
                str(self._cfg.get("language", "") or current_language())
            ) if self._cfg else current_language()
            for index in range(self._lang_combo.count()):
                if self._lang_combo.itemData(index) == language:
                    self._lang_combo.blockSignals(True)
                    self._lang_combo.setCurrentIndex(index)
                    self._lang_combo.blockSignals(False)
                    break
            if language and language != current_language():
                set_language(language)
        theme_value = self._cfg.get("dark_theme", _THEME_FOLLOW_SYSTEM) if self._cfg else _THEME_FOLLOW_SYSTEM
        apply_app_theme(theme_value)
        if hasattr(self, "_theme_combo"):
            self._theme_combo.blockSignals(True)
            if isinstance(theme_value, bool):
                theme_value = _THEME_ON if theme_value else _THEME_OFF
            idx = self._theme_combo.findData(theme_value)
            if idx >= 0:
                self._theme_combo.setCurrentIndex(idx)
            self._theme_combo.blockSignals(False)


    def _emit_imported_settings(self, imported_sections: set[str]):
        if not self._cfg:
            return
        keys = []
        for section in imported_sections:
            keys.extend(DATA_CONFIG_KEYS.get(section, ()))
        settings = {key: self._cfg.get(key) for key in keys if key not in SECRET_CONFIG_KEYS}
        settings["models"] = [dict(item) for item in self._configured_models]
        settings["model_action_settings"] = self._cfg.get("model_action_settings", {})
        self.settings_changed.emit(settings)
        if DATA_CATEGORY_LIVE2D in imported_sections and self._current_char and self._current_costume:
            self.model_selected.emit(self._current_char, self._current_costume)


    def _default_chat_backup_path(self) -> str:
        name = "bandori-chat-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".db"
        return str(app_base_dir() / name)


    def _export_chat_database(self):
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _tr("SettingsWindow.chat_data_export_dialog"),
            self._default_chat_backup_path(),
            _tr("SettingsWindow.chat_data_filter"),
        )
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".db"

        try:
            from database_manager import export_chat_database

            summary = export_chat_database(path)
            InfoBar.success(
                _tr("SettingsWindow.chat_data_export_title"),
                _tr(
                    "SettingsWindow.chat_data_export_content",
                    conversations=summary["conversations"],
                    messages=summary["messages"],
                    group_messages=summary.get("group_messages", 0),
                ),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            self._show_chat_data_error(exc)


    def _import_chat_database(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.chat_data_import_dialog"),
            str(app_base_dir()),
            _tr("SettingsWindow.chat_data_filter"),
        )
        if not path:
            return

        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.chat_data_import_confirm_title"),
            _tr("SettingsWindow.chat_data_import_confirm_content"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from database_manager import import_chat_database

            summary = import_chat_database(path)
            InfoBar.success(
                _tr("SettingsWindow.chat_data_import_title"),
                _tr(
                    "SettingsWindow.chat_data_import_content",
                    conversations=summary["conversations"],
                    messages=summary["messages"],
                    group_messages=summary.get("group_messages", 0),
                ),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            self._show_chat_data_error(exc)


    def _show_chat_data_error(self, exc: Exception):
        InfoBar.error(
            _tr("SettingsWindow.chat_data_failed_title"),
            str(exc),
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )


