from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class LLMPageMixin:

    def _build_llm_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(8)

        title = TitleLabel(_tr("SettingsWindow.llm_title"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr("SettingsWindow.llm_subtitle"), page))
        layout.addWidget(subtitle)
        capability_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_capability_hint",
            default="提示：图片理解、联网搜索、MCP 和 Computer Use 等能力，只有在当前模型支持多模态输入或工具调用时才会实际生效。",
        ), page))
        capability_hint.setObjectName("llmHint")
        layout.addWidget(capability_hint)

        profile_header = QHBoxLayout()
        profile_header.setContentsMargins(0, 0, 0, 0)
        profile_header.setSpacing(8)
        profile_label = BodyLabel(_tr("SettingsWindow.llm_api_profile", default="API 配置档案"), page)
        profile_header.addWidget(profile_label)
        self._llm_active_api_profile_label = BodyLabel("", page)
        self._llm_active_api_profile_label.setWordWrap(False)
        profile_header.addWidget(self._llm_active_api_profile_label)
        profile_header.addStretch()
        layout.addLayout(profile_header)
        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        self._llm_api_profile_combo = OpaqueDropDownComboBox(page)
        self._llm_api_profile_combo.setFixedHeight(36)
        self._llm_api_profile_combo.currentIndexChanged.connect(self._on_llm_api_profile_selected)
        profile_row.addWidget(self._llm_api_profile_combo, 1)

        self._llm_api_profile_name = FluentContextLineEdit(page)
        self._llm_api_profile_name.setPlaceholderText(_tr("SettingsWindow.llm_api_profile_name_placeholder", default="配置名称"))
        self._llm_api_profile_name.setFixedHeight(36)
        profile_row.addWidget(self._llm_api_profile_name, 1)

        save_profile_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_api_profile_save", default="保存配置"), page)
        save_profile_btn.setFixedHeight(36)
        save_profile_btn.clicked.connect(self._save_llm_api_profile)
        profile_row.addWidget(save_profile_btn)

        delete_profile_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.llm_api_profile_delete", default="删除"), page)
        delete_profile_btn.setFixedHeight(36)
        delete_profile_btn.clicked.connect(self._delete_llm_api_profile)
        profile_row.addWidget(delete_profile_btn)
        layout.addLayout(profile_row)

        api_url_label = BodyLabel(_tr("SettingsWindow.llm_api_url"), page)
        layout.addWidget(api_url_label)
        self._llm_api_url = FluentContextLineEdit(page)
        self._llm_api_url.setPlaceholderText(_tr("SettingsWindow.llm_api_url_placeholder"))
        self._llm_api_url.setFixedHeight(36)
        self._llm_api_url.textChanged.connect(lambda: self._on_llm_api_mode_changed(self._llm_api_mode.currentIndex()) if hasattr(self, "_llm_api_mode") else None)
        api_url_input_col = QVBoxLayout()
        api_url_input_col.setContentsMargins(0, 0, 0, 0)
        api_url_input_col.setSpacing(4)
        api_url_input_col.addWidget(self._llm_api_url)
        self._llm_api_url_hint = _wrap_label(BodyLabel(_tr("SettingsWindow.llm_api_url_hint"), page))
        self._llm_api_url_hint.setObjectName("llmHint")
        api_url_input_col.addWidget(self._llm_api_url_hint)
        layout.addLayout(api_url_input_col)

        api_key_label = BodyLabel(_tr("SettingsWindow.llm_api_key"), page)
        layout.addWidget(api_key_label)
        self._llm_api_key = FluentContextLineEdit(page)
        self._llm_api_key.setPlaceholderText(_tr("SettingsWindow.llm_api_key_placeholder"))
        self._llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key.setFixedHeight(36)
        layout.addWidget(self._llm_api_key)

        model_label = BodyLabel(_tr("SettingsWindow.llm_primary_model_id"), page)
        layout.addWidget(model_label)

        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self._llm_model_id = FluentContextLineEdit(page)
        self._llm_model_id.setPlaceholderText(_tr("SettingsWindow.llm_model_id_placeholder"))
        self._llm_model_id.setFixedHeight(36)
        model_row.addWidget(self._llm_model_id, 1)

        fetch_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.llm_fetch"), page)
        fetch_btn.setFixedHeight(36)
        fetch_btn.clicked.connect(lambda: self._fetch_models(self._llm_model_id))
        model_row.addWidget(fetch_btn)
        layout.addLayout(model_row)

        thinking_label = BodyLabel(_tr("SettingsWindow.llm_enable_thinking"), page)
        layout.addWidget(thinking_label)
        self._llm_enable_thinking = OpaqueDropDownComboBox(page)
        self._llm_enable_thinking.addItems([
            _tr("SettingsWindow.llm_enable_thinking_default"),
            _tr("SettingsWindow.llm_enable_thinking_on"),
            _tr("SettingsWindow.llm_enable_thinking_off"),
        ])
        self._llm_enable_thinking.setFixedHeight(36)
        self._llm_enable_thinking.setCurrentIndex(0)
        layout.addWidget(self._llm_enable_thinking)

        show_reasoning_row = QHBoxLayout()
        show_reasoning_row.setContentsMargins(0, 0, 0, 0)
        show_reasoning_label = BodyLabel(_tr("SettingsWindow.llm_show_reasoning"), page)
        self._llm_show_reasoning = SwitchButton(page)
        self._llm_show_reasoning.setChecked(True)
        show_reasoning_row.addWidget(show_reasoning_label)
        show_reasoning_row.addStretch()
        show_reasoning_row.addWidget(self._llm_show_reasoning)
        layout.addLayout(show_reasoning_row)

        (
            self._llm_primary_model_combo_label,
            self._llm_primary_model_scroll,
            self._llm_primary_model_list,
            self._llm_primary_model_list_layout,
        ) = self._create_llm_model_picker(page)
        layout.addWidget(self._llm_primary_model_combo_label)
        layout.addWidget(self._llm_primary_model_scroll)

        aux_api_url_label = BodyLabel(_tr("SettingsWindow.llm_aux_api_url", default="辅助模型 API 地址"), page)
        layout.addWidget(aux_api_url_label)
        self._llm_aux_api_url = FluentContextLineEdit(page)
        self._llm_aux_api_url.setPlaceholderText(_tr(
            "SettingsWindow.llm_aux_api_url_placeholder",
            default="留空则复用主模型 API 地址",
        ))
        self._llm_aux_api_url.setFixedHeight(36)
        layout.addWidget(self._llm_aux_api_url)

        aux_api_key_label = BodyLabel(_tr("SettingsWindow.llm_aux_api_key", default="辅助模型 API 密钥"), page)
        layout.addWidget(aux_api_key_label)
        self._llm_aux_api_key = FluentContextLineEdit(page)
        self._llm_aux_api_key.setPlaceholderText(_tr(
            "SettingsWindow.llm_aux_api_key_placeholder",
            default="留空则复用主模型 API 密钥",
        ))
        self._llm_aux_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_aux_api_key.setFixedHeight(36)
        layout.addWidget(self._llm_aux_api_key)

        aux_model_label = BodyLabel(_tr("SettingsWindow.llm_aux_model_id"), page)
        layout.addWidget(aux_model_label)
        self._llm_aux_model_id = FluentContextLineEdit(page)
        self._llm_aux_model_id.setPlaceholderText(_tr("SettingsWindow.llm_aux_model_id_placeholder"))
        self._llm_aux_model_id.setFixedHeight(36)
        aux_model_row = QHBoxLayout()
        aux_model_row.setSpacing(8)
        aux_model_row.addWidget(self._llm_aux_model_id, 1)
        aux_fetch_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.llm_fetch"), page)
        aux_fetch_btn.setFixedHeight(36)
        aux_fetch_btn.clicked.connect(lambda: self._fetch_models(self._llm_aux_model_id))
        aux_model_row.addWidget(aux_fetch_btn)
        layout.addLayout(aux_model_row)
        (
            self._llm_aux_model_combo_label,
            self._llm_aux_model_scroll,
            self._llm_aux_model_list,
            self._llm_aux_model_list_layout,
        ) = self._create_llm_model_picker(page)
        layout.addWidget(self._llm_aux_model_combo_label)
        layout.addWidget(self._llm_aux_model_scroll)

        aux_thinking_label = BodyLabel(_tr("SettingsWindow.llm_aux_enable_thinking"), page)
        layout.addWidget(aux_thinking_label)
        self._llm_aux_enable_thinking = OpaqueDropDownComboBox(page)
        self._llm_aux_enable_thinking.addItems([
            _tr("SettingsWindow.llm_enable_thinking_default"),
            _tr("SettingsWindow.llm_enable_thinking_on"),
            _tr("SettingsWindow.llm_enable_thinking_off"),
        ])
        self._llm_aux_enable_thinking.setFixedHeight(36)
        self._llm_aux_enable_thinking.setCurrentIndex(0)
        layout.addWidget(self._llm_aux_enable_thinking)

        aux_vision_row = QHBoxLayout()
        aux_vision_row.setContentsMargins(0, 0, 0, 0)
        aux_vision_label = BodyLabel(_tr("SettingsWindow.llm_aux_vision_fallback_enabled", default="辅助模型视觉解析"), page)
        self._llm_aux_vision_fallback_enabled = SwitchButton(page)
        aux_vision_row.addWidget(aux_vision_label)
        aux_vision_row.addStretch()
        aux_vision_row.addWidget(self._llm_aux_vision_fallback_enabled)
        layout.addLayout(aux_vision_row)

        api_mode_label = BodyLabel(_tr("SettingsWindow.llm_api_mode", default="API 模式"), page)
        layout.addWidget(api_mode_label)
        self._llm_api_mode = OpaqueDropDownComboBox(page)
        self._llm_api_mode.addItem(_tr("SettingsWindow.llm_api_mode_chat", default="兼容 Chat Completions"), userData="chat_completions")
        self._llm_api_mode.addItem(_tr("SettingsWindow.llm_api_mode_responses", default="OpenAI Responses"), userData="responses")
        self._llm_api_mode.setFixedHeight(36)
        self._llm_api_mode.currentIndexChanged.connect(self._on_llm_api_mode_changed)
        layout.addWidget(self._llm_api_mode)

        web_search_row = QHBoxLayout()
        web_search_row.setContentsMargins(0, 0, 0, 0)
        web_search_label = BodyLabel(_tr("SettingsWindow.llm_web_search_enabled", default="联网搜索"), page)
        self._llm_web_search_enabled = SwitchButton(page)
        self._llm_web_search_enabled.checkedChanged.connect(self._on_llm_web_search_enabled_changed)
        web_search_row.addWidget(web_search_label)
        web_search_row.addStretch()
        web_search_row.addWidget(self._llm_web_search_enabled)
        layout.addLayout(web_search_row)

        web_search_engine_label = BodyLabel(_tr("SettingsWindow.llm_web_search_engine", default="搜索引擎"), page)
        layout.addWidget(web_search_engine_label)
        self._llm_web_search_engine = OpaqueDropDownComboBox(page)
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_bing", default="Bing"), userData="bing")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_bing_cn", default="Bing CN"), userData="bing_cn")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_google", default="Google"), userData="google")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_duckduckgo", default="DuckDuckGo"), userData="duckduckgo")
        self._llm_web_search_engine.addItem(_tr("SettingsWindow.search_engine_baidu", default="Baidu"), userData="baidu")
        self._llm_web_search_engine.setFixedHeight(36)
        layout.addWidget(self._llm_web_search_engine)

        web_search_sources_row = QHBoxLayout()
        web_search_sources_row.setContentsMargins(0, 0, 0, 0)
        sources_label = BodyLabel(_tr("SettingsWindow.llm_web_search_show_sources", default="显示联网来源"), page)
        self._llm_web_search_show_sources = SwitchButton(page)
        web_search_sources_row.addWidget(sources_label)
        web_search_sources_row.addStretch()
        web_search_sources_row.addWidget(self._llm_web_search_show_sources)
        layout.addLayout(web_search_sources_row)

        web_fetch_row = QHBoxLayout()
        web_fetch_row.setContentsMargins(0, 0, 0, 0)
        web_fetch_label = BodyLabel(_tr("SettingsWindow.llm_web_fetch_enabled", default="WebFetch 访问链接"), page)
        self._llm_web_fetch_enabled = SwitchButton(page)
        web_fetch_row.addWidget(web_fetch_label)
        web_fetch_row.addStretch()
        web_fetch_row.addWidget(self._llm_web_fetch_enabled)
        layout.addLayout(web_fetch_row)
        web_fetch_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_web_fetch_hint",
            default="开启后，模型可以读取用户提供的网页链接；同时开启联网搜索时，也可以进一步读取搜索结果里的网页。",
        ), page))
        web_fetch_hint.setObjectName("llmHint")
        layout.addWidget(web_fetch_hint)

        auto_continue_row = QHBoxLayout()
        auto_continue_row.setContentsMargins(0, 0, 0, 0)
        auto_continue_label = BodyLabel(_tr(
            "SettingsWindow.llm_auto_continue_enabled",
            default="单人对话自动接话",
        ), page)
        self._llm_auto_continue_enabled = SwitchButton(page)
        auto_continue_row.addWidget(auto_continue_label)
        auto_continue_row.addStretch()
        auto_continue_row.addWidget(self._llm_auto_continue_enabled)
        layout.addLayout(auto_continue_row)

        auto_continue_limit_row = QHBoxLayout()
        auto_continue_limit_row.setContentsMargins(16, 0, 0, 0)
        auto_continue_limit_label = BodyLabel(_tr(
            "SettingsWindow.llm_auto_continue_max_turns",
            default="接话硬上限",
        ), page)
        self._llm_auto_continue_max_turns = SpinBox(page)
        self._llm_auto_continue_max_turns.setRange(1, 20)
        self._llm_auto_continue_max_turns.setValue(5)
        self._llm_auto_continue_max_turns.setFixedHeight(34)
        auto_continue_limit_row.addWidget(auto_continue_limit_label)
        auto_continue_limit_row.addStretch()
        auto_continue_limit_row.addWidget(self._llm_auto_continue_max_turns)
        layout.addLayout(auto_continue_limit_row)
        auto_continue_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_auto_continue_hint",
            default="开启后，单人聊天里的模型可以通过 continue_conversation 工具主动续说；达到上限后继续调用会被忽略。",
        ), page))
        auto_continue_hint.setObjectName("llmHint")
        layout.addWidget(auto_continue_hint)

        cross_chat_history_row = QHBoxLayout()
        cross_chat_history_row.setContentsMargins(0, 0, 0, 0)
        cross_chat_history_label = BodyLabel(_tr(
            "SettingsWindow.llm_cross_chat_history_enabled",
            default="注入跨聊天记录",
        ), page)
        self._llm_cross_chat_history_enabled = SwitchButton(page)
        cross_chat_history_row.addWidget(cross_chat_history_label)
        cross_chat_history_row.addStretch()
        cross_chat_history_row.addWidget(self._llm_cross_chat_history_enabled)
        layout.addLayout(cross_chat_history_row)
        cross_chat_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_cross_chat_history_enabled_hint",
            default="关闭后，模型不会额外读取其他私聊或群聊的历史摘录，只保留当前会话、长期记忆和当前时间等上下文。",
        ), page))
        cross_chat_hint.setObjectName("llmHint")
        layout.addWidget(cross_chat_hint)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.llm_chat_commands_title", default="LLM 对话命令"), page))
        command_stop_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_chat_commands_hint",
            default="@stop / @停止 / @中断：强制中断当前模型输出。好感度、记忆和关系数值命令在\u201c好感度 / 记忆\u201d页说明。",
        ), page))
        command_stop_hint.setObjectName("llmHint")
        layout.addWidget(command_stop_hint)
        command_cot_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_chat_commands_cot",
            default="@cot [开/关]：快速开启或关闭思维链显示；省略参数则切换当前状态。",
        ), page))
        command_cot_hint.setObjectName("llmHint")
        layout.addWidget(command_cot_hint)
        command_websearch_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_chat_commands_websearch",
            default="@websearch [开/关]：快速开启或关闭联网搜索；省略参数则切换当前状态。",
        ), page))
        command_websearch_hint.setObjectName("llmHint")
        layout.addWidget(command_websearch_hint)
        command_sys_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_chat_commands_sys_instruction",
            default="@sys-instruction [开/关]：开启或关闭最高优先级系统提示词预设；省略参数则切换当前状态。",
        ), page))
        command_sys_hint.setObjectName("llmHint")
        layout.addWidget(command_sys_hint)

        custom_system_row = QHBoxLayout()
        custom_system_row.setContentsMargins(0, 0, 0, 0)
        custom_system_label = BodyLabel(_tr(
            "SettingsWindow.llm_custom_system_prompt",
            default="最高优先级系统提示词",
        ), page)
        self._llm_custom_system_prompt_enabled = SwitchButton(page)
        self._llm_custom_system_prompt_enabled.checkedChanged.connect(
            self._on_llm_custom_system_prompt_enabled_changed
        )
        custom_system_row.addWidget(custom_system_label)
        custom_system_row.addStretch()
        custom_system_row.addWidget(BodyLabel(_tr(
            "SettingsWindow.llm_custom_system_prompt_enabled",
            default="启用",
        ), page))
        custom_system_row.addWidget(self._llm_custom_system_prompt_enabled)
        layout.addLayout(custom_system_row)
        self._llm_custom_system_prompt = FluentContextTextEdit(page)
        self._llm_custom_system_prompt.setPlaceholderText(_tr(
            "SettingsWindow.llm_custom_system_prompt_placeholder",
            default="关闭开关可临时禁用且保留内容。这里的内容会在每次聊天请求中置于角色设定之前。",
        ))
        _horizontal_scroll_text_edit(self._llm_custom_system_prompt)
        self._llm_custom_system_prompt.setMinimumHeight(64)
        self._llm_custom_system_prompt.setMaximumHeight(96)
        layout.addWidget(self._llm_custom_system_prompt)
        custom_system_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_custom_system_prompt_hint",
            default="这段指令优先级高于角色档案、长期记忆和会话历史；建议只写全局行为约束，避免与角色身份或动作标签规则冲突。",
        ), page))
        custom_system_hint.setObjectName("llmHint")
        layout.addWidget(custom_system_hint)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        test_btn = PushButton(FluentIcon.WIFI, _tr("SettingsWindow.llm_test"), page)
        test_btn.setFixedHeight(36)
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)

        save_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.llm_apply_current", default="应用当前配置"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_llm_config)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_llm_config()
        self._style_llm_inputs()
        self._connect_theme_changed(self._style_llm_inputs)

        return page

    def _create_llm_model_picker(self, parent: QWidget):
        label = BodyLabel(_tr("SettingsWindow.llm_available_models"), parent)
        label.hide()

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(64)
        scroll.setMaximumHeight(160)
        scroll.hide()

        list_widget = QWidget(parent)
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 2, 0, 2)
        list_layout.setSpacing(1)
        scroll.setWidget(list_widget)
        return label, scroll, list_widget, list_layout

    def _llm_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_llm_api_url",
                "_llm_api_url_hint",
                "_llm_api_key",
                "_llm_model_id",
                "_llm_aux_api_url",
                "_llm_aux_api_key",
                "_llm_aux_model_id",
                "_llm_aux_enable_thinking",
                "_llm_aux_vision_fallback_enabled",
                "_llm_api_profile_combo",
                "_llm_api_profile_name",
                "_llm_api_mode",
                "_llm_web_search_enabled",
                "_llm_web_search_engine",
                "_llm_web_search_show_sources",
                "_llm_web_fetch_enabled",
                "_llm_auto_continue_enabled",
                "_llm_auto_continue_max_turns",
                "_llm_cross_chat_history_enabled",
                "_llm_custom_system_prompt_enabled",
                "_llm_custom_system_prompt",
                "_llm_enable_thinking",
                "_llm_show_reasoning",
                "_user_profile_combo",
                "_save_user_profile_btn",
                "_delete_user_profile_btn",
                "_user_name",
                "_pov_mode",
                "_pov_custom_prompt",
                "_pov_persona_combo",
                "_pov_role_character",
                "_user_avatar_preview",
                "_user_avatar_reset_btn",
                "_avatar_color_btns",
            )
        )

    def _style_llm_inputs(self):
        if not self._llm_config_widgets_ready():
            return
        dark = isDarkTheme()
        input_bg = "#282828" if dark else "#ffffff"
        input_border = "#505050" if dark else "#d0d0d0"
        text_color = "#e8e8e8" if dark else "#000000"
        style = f"""
            QLineEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
            QTextEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 13px;
            }}
            QTextEdit:focus {{
                border-color: {BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY};
            }}
            {_fluent_scrollbar_qss(dark=dark)}
        """
        self._llm_api_url.setStyleSheet(style)
        self._llm_api_key.setStyleSheet(style)
        self._llm_model_id.setStyleSheet(style)
        self._llm_aux_api_url.setStyleSheet(style)
        self._llm_aux_api_key.setStyleSheet(style)
        self._llm_aux_model_id.setStyleSheet(style)
        self._llm_api_profile_name.setStyleSheet(style)
        self._llm_custom_system_prompt.setStyleSheet(style)
        self._user_name.setStyleSheet(style)
        self._pov_custom_prompt.setStyleSheet(style)
        hint_color = "#a7b0bf" if dark else "#687385"
        self._llm_api_url_hint.setStyleSheet(f"color: {hint_color}; font-size: 13px;")
        for hint in self._llm_api_url.window().findChildren(QLabel, "llmHint"):
            hint.setStyleSheet(f"color: {hint_color}; font-size: 12px; line-height: 16px;")
        self._llm_active_api_profile_label.setStyleSheet(f"color: {hint_color}; font-size: 13px;")
        self._style_avatar_buttons()
        self._update_user_avatar_preview()

    def _load_llm_config(self):
        if self._cfg and self._llm_config_widgets_ready():
            self._llm_api_url.setText(self._cfg.get("llm_api_url", ""))
            self._llm_api_key.setText(self._cfg.get("llm_api_key", ""))
            self._llm_model_id.setText(self._cfg.get("llm_model_id", ""))
            self._llm_aux_api_url.setText(self._cfg.get("llm_aux_api_url", ""))
            self._llm_aux_api_key.setText(self._cfg.get("llm_aux_api_key", ""))
            self._llm_aux_model_id.setText(self._cfg.get("llm_aux_model_id", ""))
            aux_thinking_val = self._cfg.get("llm_aux_enable_thinking", None)
            if aux_thinking_val is True:
                self._llm_aux_enable_thinking.setCurrentIndex(1)
            elif aux_thinking_val is False:
                self._llm_aux_enable_thinking.setCurrentIndex(2)
            else:
                self._llm_aux_enable_thinking.setCurrentIndex(0)
            self._llm_aux_vision_fallback_enabled.setChecked(bool(self._cfg.get("llm_aux_vision_fallback_enabled", False)))
            api_mode = self._cfg.get("llm_api_mode", "chat_completions")
            for i in range(self._llm_api_mode.count()):
                if self._llm_api_mode.itemData(i) == api_mode:
                    self._llm_api_mode.setCurrentIndex(i)
                    break
            self._llm_web_search_enabled.setChecked(bool(self._cfg.get("llm_web_search_enabled", False)))
            web_search_engine = self._cfg.get("llm_web_search_engine", "bing_cn")
            for i in range(self._llm_web_search_engine.count()):
                if self._llm_web_search_engine.itemData(i) == web_search_engine:
                    self._llm_web_search_engine.setCurrentIndex(i)
                    break
            self._llm_web_search_show_sources.setChecked(bool(self._cfg.get("llm_web_search_show_sources", True)))
            self._llm_web_fetch_enabled.setChecked(bool(self._cfg.get("llm_web_fetch_enabled", False)))
            self._llm_auto_continue_enabled.setChecked(bool(self._cfg.get("llm_auto_continue_enabled", False)))
            try:
                auto_continue_max = int(self._cfg.get("llm_auto_continue_max_turns", 5) or 5)
            except (TypeError, ValueError):
                auto_continue_max = 5
            self._llm_auto_continue_max_turns.setValue(max(1, min(20, auto_continue_max)))
            self._llm_cross_chat_history_enabled.setChecked(bool(self._cfg.get("llm_cross_chat_history_enabled", True)))
            self._llm_custom_system_prompt_enabled.setChecked(bool(self._cfg.get("llm_custom_system_prompt_enabled", True)))
            self._llm_custom_system_prompt.setPlainText(self._cfg.get("llm_custom_system_prompt", ""))
            self._on_llm_custom_system_prompt_enabled_changed(
                self._llm_custom_system_prompt_enabled.isChecked()
            )
            self._on_llm_web_search_enabled_changed(self._llm_web_search_enabled.isChecked())
            self._on_llm_api_mode_changed(self._llm_api_mode.currentIndex())
            profile = self._cfg.active_user_profile() if hasattr(self._cfg, "active_user_profile") else {}
            self._reload_user_profile_combo(profile.get("key", self._cfg.get("active_user_profile", "")))
            if profile:
                self._load_user_profile_fields(profile)
            else:
                self._saved_user_name = self._cfg.get("user_name", "")
                self._user_name.setText(self._saved_user_name)
                self._user_avatar_path_pending = str(self._cfg.get("user_avatar_path", "") or "").strip()
                saved_color = self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
                for btn in self._avatar_color_btns:
                    btn.setChecked(btn.property("avatar_color") == saved_color)
                self._update_user_avatar_preview()
            thinking_val = self._cfg.get("llm_enable_thinking", None)
            if thinking_val is True:
                self._llm_enable_thinking.setCurrentIndex(1)
            elif thinking_val is False:
                self._llm_enable_thinking.setCurrentIndex(2)
            else:
                self._llm_enable_thinking.setCurrentIndex(0)
            self._llm_show_reasoning.setChecked(bool(self._cfg.get("llm_show_reasoning", True)))
            mode = self._cfg.get("pov_mode", "off")
            for i in range(self._pov_mode.count()):
                if self._pov_mode.itemData(i) == mode:
                    self._pov_mode.setCurrentIndex(i)
                    break
            self._pov_custom_prompt.setPlainText(self._cfg.get("pov_custom_prompt", ""))
            self._reload_pov_persona_combo()
            saved_role = self._cfg.get("pov_role_character", "")
            for i in range(self._pov_role_character.count()):
                if self._pov_role_character.itemData(i) == saved_role:
                    self._pov_role_character.setCurrentIndex(i)
                    break
            self._on_pov_mode_changed(self._pov_mode.currentIndex())
            self._reload_llm_api_profiles(
                self._cfg.get("llm_active_api_profile", "") or self._matching_llm_api_profile_name()
            )
            self._update_current_llm_api_profile_label()

    def _normalized_llm_api_profiles(self) -> list[dict]:
        if not self._cfg:
            return []
        profiles = self._cfg.get("llm_api_profiles", [])
        if not isinstance(profiles, list):
            return []
        normalized = []
        seen = set()
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            name = str(profile.get("name", "") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            api_mode = str(profile.get("llm_api_mode", "chat_completions") or "chat_completions")
            if api_mode not in ("chat_completions", "responses"):
                api_mode = "chat_completions"
            normalized.append({
                "name": name,
                "llm_api_url": str(profile.get("llm_api_url", "") or "").strip(),
                "llm_api_key": str(profile.get("llm_api_key", "") or "").strip(),
                "llm_model_id": str(profile.get("llm_model_id", "") or "").strip(),
                "llm_aux_api_url": str(profile.get("llm_aux_api_url", "") or "").strip(),
                "llm_aux_api_key": str(profile.get("llm_aux_api_key", "") or "").strip(),
                "llm_aux_model_id": str(profile.get("llm_aux_model_id", "") or "").strip(),
                "llm_aux_enable_thinking": profile.get("llm_aux_enable_thinking", None)
                if profile.get("llm_aux_enable_thinking", None) in (True, False, None) else None,
                "llm_aux_vision_fallback_enabled": bool(profile.get("llm_aux_vision_fallback_enabled", False)),
                "llm_api_mode": api_mode,
                "llm_web_search_enabled": bool(profile.get("llm_web_search_enabled", False)),
                "llm_web_search_engine": str(profile.get("llm_web_search_engine", "bing_cn") or "bing_cn"),
                "llm_web_search_show_sources": bool(profile.get("llm_web_search_show_sources", True)),
                "llm_web_fetch_enabled": bool(profile.get("llm_web_fetch_enabled", False)),
                "llm_auto_continue_enabled": bool(profile.get("llm_auto_continue_enabled", False)),
                "llm_auto_continue_max_turns": max(1, min(20, int(profile.get("llm_auto_continue_max_turns", 5) or 5)))
                if str(profile.get("llm_auto_continue_max_turns", 5) or "").strip().lstrip("-").isdigit() else 5,
                "llm_cross_chat_history_enabled": bool(profile.get("llm_cross_chat_history_enabled", True)),
                "llm_enable_thinking": profile.get("llm_enable_thinking", None)
                if profile.get("llm_enable_thinking", None) in (True, False, None) else None,
                "llm_show_reasoning": bool(profile.get("llm_show_reasoning", True)),
            })
        return normalized

    def _current_llm_api_profile(self, name: str) -> dict:
        thinking_idx = self._llm_enable_thinking.currentIndex()
        thinking = True if thinking_idx == 1 else False if thinking_idx == 2 else None
        aux_thinking_idx = self._llm_aux_enable_thinking.currentIndex()
        aux_thinking = True if aux_thinking_idx == 1 else False if aux_thinking_idx == 2 else None
        return {
            "name": name.strip(),
            "llm_api_url": self._llm_api_url.text().strip(),
            "llm_api_key": self._llm_api_key.text().strip(),
            "llm_model_id": self._llm_model_id.text().strip(),
            "llm_aux_api_url": self._llm_aux_api_url.text().strip(),
            "llm_aux_api_key": self._llm_aux_api_key.text().strip(),
            "llm_aux_model_id": self._llm_aux_model_id.text().strip(),
            "llm_aux_enable_thinking": aux_thinking,
            "llm_aux_vision_fallback_enabled": self._llm_aux_vision_fallback_enabled.isChecked(),
            "llm_api_mode": self._llm_api_mode.itemData(self._llm_api_mode.currentIndex()) or "chat_completions",
            "llm_web_search_enabled": self._llm_web_search_enabled.isChecked(),
            "llm_web_search_engine": self._llm_web_search_engine.itemData(self._llm_web_search_engine.currentIndex()) or "bing_cn",
            "llm_web_search_show_sources": self._llm_web_search_show_sources.isChecked(),
            "llm_web_fetch_enabled": self._llm_web_fetch_enabled.isChecked(),
            "llm_auto_continue_enabled": self._llm_auto_continue_enabled.isChecked(),
            "llm_auto_continue_max_turns": self._llm_auto_continue_max_turns.value(),
            "llm_cross_chat_history_enabled": self._llm_cross_chat_history_enabled.isChecked(),
            "llm_enable_thinking": thinking,
            "llm_show_reasoning": self._llm_show_reasoning.isChecked(),
        }

    def _saved_llm_api_profile(self, name: str = "__current__") -> dict:
        if not self._cfg:
            return {"name": name}
        return {
            "name": name.strip(),
            "llm_api_url": str(self._cfg.get("llm_api_url", "") or "").strip(),
            "llm_api_key": str(self._cfg.get("llm_api_key", "") or "").strip(),
            "llm_model_id": str(self._cfg.get("llm_model_id", "") or "").strip(),
            "llm_aux_api_url": str(self._cfg.get("llm_aux_api_url", "") or "").strip(),
            "llm_aux_api_key": str(self._cfg.get("llm_aux_api_key", "") or "").strip(),
            "llm_aux_model_id": str(self._cfg.get("llm_aux_model_id", "") or "").strip(),
            "llm_aux_enable_thinking": self._cfg.get("llm_aux_enable_thinking", None)
            if self._cfg.get("llm_aux_enable_thinking", None) in (True, False, None) else None,
            "llm_aux_vision_fallback_enabled": bool(self._cfg.get("llm_aux_vision_fallback_enabled", False)),
            "llm_api_mode": self._cfg.get("llm_api_mode", "chat_completions") or "chat_completions",
            "llm_web_search_enabled": bool(self._cfg.get("llm_web_search_enabled", False)),
            "llm_web_search_engine": self._cfg.get("llm_web_search_engine", "bing_cn") or "bing_cn",
            "llm_web_search_show_sources": bool(self._cfg.get("llm_web_search_show_sources", True)),
            "llm_web_fetch_enabled": bool(self._cfg.get("llm_web_fetch_enabled", False)),
            "llm_auto_continue_enabled": bool(self._cfg.get("llm_auto_continue_enabled", False)),
            "llm_auto_continue_max_turns": max(1, min(20, int(self._cfg.get("llm_auto_continue_max_turns", 5) or 5)))
            if str(self._cfg.get("llm_auto_continue_max_turns", 5) or "").strip().lstrip("-").isdigit() else 5,
            "llm_cross_chat_history_enabled": bool(self._cfg.get("llm_cross_chat_history_enabled", True)),
            "llm_enable_thinking": self._cfg.get("llm_enable_thinking", None)
            if self._cfg.get("llm_enable_thinking", None) in (True, False, None) else None,
            "llm_show_reasoning": bool(self._cfg.get("llm_show_reasoning", True)),
        }

    def _llm_profiles_equal(self, left: dict, right: dict) -> bool:
        keys = (
            "llm_api_url",
            "llm_api_key",
            "llm_model_id",
            "llm_aux_api_url",
            "llm_aux_api_key",
            "llm_aux_model_id",
            "llm_aux_enable_thinking",
            "llm_aux_vision_fallback_enabled",
            "llm_api_mode",
            "llm_web_search_enabled",
            "llm_web_search_engine",
            "llm_web_search_show_sources",
            "llm_web_fetch_enabled",
            "llm_auto_continue_enabled",
            "llm_auto_continue_max_turns",
            "llm_cross_chat_history_enabled",
            "llm_enable_thinking",
            "llm_show_reasoning",
        )
        return all(left.get(key) == right.get(key) for key in keys)

    def _llm_profile_api_identity_equal(self, left: dict, right: dict) -> bool:
        keys = (
            "llm_api_url",
            "llm_api_key",
            "llm_model_id",
            "llm_aux_api_url",
            "llm_aux_api_key",
            "llm_aux_model_id",
            "llm_aux_enable_thinking",
            "llm_aux_vision_fallback_enabled",
            "llm_api_mode",
        )
        return all(left.get(key) == right.get(key) for key in keys)

    def _matching_llm_api_profile_name(self) -> str:
        current = self._current_llm_api_profile("__current__")
        profiles = self._normalized_llm_api_profiles()
        for profile in profiles:
            if self._llm_profiles_equal(current, profile):
                return profile["name"]

        preferred_names = []
        combo_index = self._llm_api_profile_combo.currentIndex()
        combo_name = ""
        if combo_index >= 0:
            combo_name = self._llm_api_profile_combo.itemData(combo_index) or ""
        if combo_name:
            preferred_names.append(combo_name)
        if self._cfg:
            active_name = str(self._cfg.get("llm_active_api_profile", "") or "").strip()
            if active_name and active_name not in preferred_names:
                preferred_names.append(active_name)

        for name in preferred_names:
            for profile in profiles:
                if profile["name"] == name and self._llm_profile_api_identity_equal(current, profile):
                    return profile["name"]

        for profile in profiles:
            if self._llm_profile_api_identity_equal(current, profile):
                return profile["name"]
        return ""

    def _applied_llm_api_profile_display_name(self) -> tuple[str, bool]:
        if not self._cfg:
            return "", False
        current = self._saved_llm_api_profile("__current__")
        if not (
            current.get("llm_api_url")
            or current.get("llm_api_key")
            or current.get("llm_model_id")
        ):
            return "", False
        profiles = self._normalized_llm_api_profiles()
        for profile in profiles:
            if self._llm_profiles_equal(current, profile):
                return profile["name"], False

        active_name = str(self._cfg.get("llm_active_api_profile", "") or "").strip()
        for profile in profiles:
            if profile["name"] == active_name and self._llm_profile_api_identity_equal(current, profile):
                return profile["name"], True
        for profile in profiles:
            if self._llm_profile_api_identity_equal(current, profile):
                return profile["name"], True
        return "", True

    def _update_current_llm_api_profile_label(self):
        name, modified = self._applied_llm_api_profile_display_name()
        if name:
            key = (
                "SettingsWindow.llm_api_profile_current_modified"
                if modified else
                "SettingsWindow.llm_api_profile_current"
            )
            self._llm_active_api_profile_label.setText(_tr(key, name=name))
        elif modified:
            self._llm_active_api_profile_label.setText(_tr("SettingsWindow.llm_api_profile_current_custom"))
        else:
            self._llm_active_api_profile_label.setText(_tr("SettingsWindow.llm_api_profile_current_none"))

    def _reload_llm_api_profiles(self, selected_name: str = ""):
        self._loading_llm_profile = True
        try:
            profiles = self._normalized_llm_api_profiles()
            current_name = selected_name or self._llm_api_profile_name.text().strip()
            self._llm_api_profile_combo.clear()
            self._llm_api_profile_combo.addItem(_tr("SettingsWindow.llm_api_profile_none", default="未选择"), userData="")
            selected_index = 0
            for profile in profiles:
                self._llm_api_profile_combo.addItem(profile["name"], userData=profile["name"])
                if profile["name"] == current_name:
                    selected_index = self._llm_api_profile_combo.count() - 1
            self._llm_api_profile_combo.setCurrentIndex(selected_index)
            if selected_index > 0:
                self._llm_api_profile_name.setText(current_name)
            elif not selected_name:
                self._llm_api_profile_name.clear()
        finally:
            self._loading_llm_profile = False

    def _apply_llm_api_profile(self, profile: dict):
        self._llm_api_url.setText(profile.get("llm_api_url", ""))
        self._llm_api_key.setText(profile.get("llm_api_key", ""))
        self._llm_model_id.setText(profile.get("llm_model_id", ""))
        self._llm_aux_api_url.setText(profile.get("llm_aux_api_url", ""))
        self._llm_aux_api_key.setText(profile.get("llm_aux_api_key", ""))
        self._llm_aux_model_id.setText(profile.get("llm_aux_model_id", ""))
        aux_thinking = profile.get("llm_aux_enable_thinking", None)
        self._llm_aux_enable_thinking.setCurrentIndex(1 if aux_thinking is True else 2 if aux_thinking is False else 0)
        self._llm_aux_vision_fallback_enabled.setChecked(bool(profile.get("llm_aux_vision_fallback_enabled", False)))
        api_mode = profile.get("llm_api_mode", "chat_completions")
        for i in range(self._llm_api_mode.count()):
            if self._llm_api_mode.itemData(i) == api_mode:
                self._llm_api_mode.setCurrentIndex(i)
                break
        self._llm_web_search_enabled.setChecked(bool(profile.get("llm_web_search_enabled", False)))
        web_search_engine = str(profile.get("llm_web_search_engine", "bing_cn") or "bing_cn")
        for i in range(self._llm_web_search_engine.count()):
            if self._llm_web_search_engine.itemData(i) == web_search_engine:
                self._llm_web_search_engine.setCurrentIndex(i)
                break
        self._llm_web_search_show_sources.setChecked(bool(profile.get("llm_web_search_show_sources", True)))
        self._llm_web_fetch_enabled.setChecked(bool(profile.get("llm_web_fetch_enabled", False)))
        self._llm_auto_continue_enabled.setChecked(bool(profile.get("llm_auto_continue_enabled", False)))
        try:
            auto_continue_max = int(profile.get("llm_auto_continue_max_turns", 5) or 5)
        except (TypeError, ValueError):
            auto_continue_max = 5
        self._llm_auto_continue_max_turns.setValue(max(1, min(20, auto_continue_max)))
        self._llm_cross_chat_history_enabled.setChecked(bool(profile.get("llm_cross_chat_history_enabled", True)))
        self._on_llm_web_search_enabled_changed(self._llm_web_search_enabled.isChecked())
        thinking = profile.get("llm_enable_thinking", None)
        self._llm_enable_thinking.setCurrentIndex(1 if thinking is True else 2 if thinking is False else 0)
        self._llm_show_reasoning.setChecked(bool(profile.get("llm_show_reasoning", True)))
        self._on_llm_api_mode_changed(self._llm_api_mode.currentIndex())

    def _on_llm_api_profile_selected(self, index: int):
        if self._loading_llm_profile or index < 0:
            return
        name = self._llm_api_profile_combo.itemData(index) or ""
        self._llm_api_profile_name.setText(name)
        if not name:
            return
        for profile in self._normalized_llm_api_profiles():
            if profile["name"] == name:
                self._apply_llm_api_profile(profile)
                return

    def _save_llm_api_profile(self):
        if not self._cfg or not self._llm_config_widgets_ready():
            return
        name = self._llm_api_profile_name.text().strip()
        if not name:
            current = self._llm_api_profile_combo.itemData(self._llm_api_profile_combo.currentIndex()) or ""
            name = current.strip()
        if not name:
            InfoBar.warning(
                _tr("SettingsWindow.llm_api_profile_name_required_title", default="需要名称"),
                _tr("SettingsWindow.llm_api_profile_name_required_content", default="请先填写配置名称。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        profiles = [p for p in self._normalized_llm_api_profiles() if p["name"] != name]
        profiles.append(self._current_llm_api_profile(name))
        self._cfg.set("llm_api_profiles", profiles)
        try:
            self._cfg.save()
            self._reload_llm_api_profiles(name)
            self._update_current_llm_api_profile_label()
            InfoBar.success(
                _tr("SettingsWindow.llm_api_profile_saved_title", default="档案已保存"),
                _tr("SettingsWindow.llm_api_profile_saved_content", default="当前 API 配置已保存。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception:
            pass

    def _delete_llm_api_profile(self):
        if not self._cfg or not self._llm_config_widgets_ready():
            return
        name = self._llm_api_profile_combo.itemData(self._llm_api_profile_combo.currentIndex()) or self._llm_api_profile_name.text().strip()
        if not name:
            return
        profiles = [p for p in self._normalized_llm_api_profiles() if p["name"] != name]
        self._cfg.set("llm_api_profiles", profiles)
        if self._cfg.get("llm_active_api_profile", "") == name:
            self._cfg.set("llm_active_api_profile", "")
        try:
            self._cfg.save()
            self._llm_api_profile_name.clear()
            self._reload_llm_api_profiles()
            self._update_current_llm_api_profile_label()
            InfoBar.success(
                _tr("SettingsWindow.llm_api_profile_deleted_title", default="档案已删除"),
                _tr("SettingsWindow.llm_api_profile_deleted_content", default="API 配置档案已删除。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception:
            pass

    def _on_llm_api_mode_changed(self, index: int):
        mode = self._llm_api_mode.itemData(index)
        responses = mode == "responses"
        api_url = self._llm_api_url.text().strip()
        self._llm_web_search_enabled.setEnabled(True)
        self._llm_web_search_engine.setEnabled(
            bool(self._llm_web_search_enabled.isChecked())
        )
        self._llm_web_search_show_sources.setEnabled(
            bool(self._llm_web_search_enabled.isChecked())
        )
        if responses:
            if api_url and not self._supports_openai_responses_api(api_url):
                self._llm_api_url_hint.setText(_tr(
                    "SettingsWindow.llm_api_url_hint_responses_fallback",
                    default="此服务商不支持 OpenAI Responses，运行时会自动使用 Chat Completions 兼容模式；联网、MCP 和 Computer Use 会通过 tool_calls/function calling 接入。",
                ))
            else:
                self._llm_api_url_hint.setText(_tr(
                    'SettingsWindow.llm_api_url_hint_responses',
                    default='Responses 模式可填写 https://api.openai.com/v1/responses；OpenAI 官方可用原生工具，MCP/Computer 相关选项在\u201c屏幕感知与工具控制\u201d页配置。',
                ))
        else:
            self._llm_api_url_hint.setText(_tr(
                'SettingsWindow.llm_api_url_hint_chat_tools',
                default='别忘记在 API 地址末尾写 /v1/chat/completions。Chat Completions 兼容接口也可以通过 tool_calls/function calling 使用工具；联网搜索、本地 MCP 代理和 Computer Use 的开关在\u201c屏幕感知与工具控制\u201d页。',
            ))

    def _on_llm_web_search_enabled_changed(self, enabled: bool):
        self._llm_web_search_engine.setEnabled(bool(enabled))
        self._llm_web_search_show_sources.setEnabled(bool(enabled))

    def _on_llm_custom_system_prompt_enabled_changed(self, enabled: bool):
        self._llm_custom_system_prompt.setEnabled(bool(enabled))

    def _supports_openai_responses_api(self, api_url: str) -> bool:
        from llm_api_compat import supports_openai_responses_api

        return supports_openai_responses_api(api_url)

    def _effective_llm_api_mode(self) -> str:
        mode = self._llm_api_mode.itemData(self._llm_api_mode.currentIndex())
        if mode == "responses" and self._supports_openai_responses_api(self._llm_api_url.text().strip()):
            return "responses"
        return "chat_completions"

    def _save_llm_config(self, source: str = "llm", show_info: bool = True):
        if self._cfg and self._llm_config_widgets_ready():
            self._cfg.set("llm_api_url", self._llm_api_url.text().strip())
            self._cfg.set("llm_api_key", self._llm_api_key.text().strip())
            self._cfg.set("llm_model_id", self._llm_model_id.text().strip())
            self._cfg.set("llm_aux_api_url", self._llm_aux_api_url.text().strip())
            self._cfg.set("llm_aux_api_key", self._llm_aux_api_key.text().strip())
            self._cfg.set("llm_aux_model_id", self._llm_aux_model_id.text().strip())
            aux_thinking_idx = self._llm_aux_enable_thinking.currentIndex()
            if aux_thinking_idx == 1:
                self._cfg.set("llm_aux_enable_thinking", True)
            elif aux_thinking_idx == 2:
                self._cfg.set("llm_aux_enable_thinking", False)
            else:
                self._cfg.set("llm_aux_enable_thinking", None)
            self._cfg.set("llm_aux_vision_fallback_enabled", self._llm_aux_vision_fallback_enabled.isChecked())
            self._cfg.set("llm_api_mode", self._llm_api_mode.itemData(self._llm_api_mode.currentIndex()) or "chat_completions")
            self._cfg.set("llm_web_search_enabled", self._llm_web_search_enabled.isChecked())
            self._cfg.set("llm_web_search_engine", self._llm_web_search_engine.itemData(self._llm_web_search_engine.currentIndex()) or "bing_cn")
            self._cfg.set("llm_web_search_show_sources", self._llm_web_search_show_sources.isChecked())
            self._cfg.set("llm_web_fetch_enabled", self._llm_web_fetch_enabled.isChecked())
            self._cfg.set("llm_auto_continue_enabled", self._llm_auto_continue_enabled.isChecked())
            self._cfg.set("llm_auto_continue_max_turns", self._llm_auto_continue_max_turns.value())
            self._cfg.set("llm_cross_chat_history_enabled", self._llm_cross_chat_history_enabled.isChecked())
            self._cfg.set("llm_custom_system_prompt_enabled", self._llm_custom_system_prompt_enabled.isChecked())
            self._cfg.set("llm_custom_system_prompt", self._llm_custom_system_prompt.toPlainText().strip())
            pov_mode = self._pov_mode.itemData(self._pov_mode.currentIndex()) or "off"
            avatar_color = self._selected_avatar_color()
            if pov_mode == "role":
                profile_user_name = self._saved_user_name.strip()
                user_name = self._pov_role_character.currentText().strip()
            else:
                self._saved_user_name = self._user_name.text().strip()
                profile_user_name = self._saved_user_name
                user_name = profile_user_name
            if hasattr(self._cfg, "sync_active_user_profile"):
                self._cfg.sync_active_user_profile(profile_user_name, avatar_color, self._user_avatar_path_pending)
            self._cfg.set("user_name", user_name)
            self._cfg.set("pov_mode", pov_mode)
            self._cfg.set("pov_custom_prompt", self._pov_custom_prompt.toPlainText().strip())
            self._cfg.set("pov_role_character", self._pov_role_character.itemData(self._pov_role_character.currentIndex()) or "")
            self._cfg.set("user_avatar_path", self._user_avatar_path_pending)
            self._cfg.set("user_avatar_color", avatar_color)
            thinking_idx = self._llm_enable_thinking.currentIndex()
            if thinking_idx == 1:
                self._cfg.set("llm_enable_thinking", True)
            elif thinking_idx == 2:
                self._cfg.set("llm_enable_thinking", False)
            else:
                self._cfg.set("llm_enable_thinking", None)
            self._cfg.set("llm_show_reasoning", self._llm_show_reasoning.isChecked())
            active_profile = self._matching_llm_api_profile_name()
            self._cfg.set("llm_active_api_profile", active_profile)
            try:
                self._cfg.save()
                self._reload_user_profile_combo(self._cfg.get("active_user_profile", ""))
                self._refresh_memory_page()
                self._reload_llm_api_profiles(active_profile)
                self._update_current_llm_api_profile_label()
                if show_info and hasattr(self, "_user_profile_settings_data"):
                    self.settings_changed.emit(self._user_profile_settings_data())
                if show_info:
                    title_key = "SettingsWindow.pov_saved_title" if source == "pov" else "SettingsWindow.llm_saved_title"
                    content_key = "SettingsWindow.pov_saved_content" if source == "pov" else "SettingsWindow.llm_saved_content"
                    InfoBar.success(
                        _tr(title_key),
                        _tr(content_key),
                        duration=2000,
                        position=InfoBarPosition.TOP,
                        parent=self,
                    )
            except Exception:
                pass

    def _test_connection(self):
        api_url = self._llm_api_url.text().strip()
        api_key = self._llm_api_key.text().strip()
        model_id = self._llm_model_id.text().strip()

        if not api_url or not api_key or not model_id:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_config_title"),
                _tr("SettingsWindow.llm_missing_config_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        if hasattr(self, '_test_worker') and self._test_worker is not None:
            if self._test_worker.isRunning():
                self._test_worker.quit()
                self._test_worker.wait(2000)

        api_mode = self._effective_llm_api_mode() if hasattr(self, "_llm_api_mode") else "chat_completions"
        self._test_worker = TestConnectionWorker(api_url, api_key, model_id, api_mode, parent=self)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.error.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_finished(self):
        InfoBar.success(
            _tr("SettingsWindow.llm_connected_title"),
            _tr("SettingsWindow.llm_connected_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_test_error(self, msg: str):
        InfoBar.error(
            _tr("SettingsWindow.llm_connection_failed_title"),
            msg,
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _fetch_models(self, target_input=None):
        self._llm_model_fetch_target = target_input or self._llm_model_id
        is_aux_target = target_input is self._llm_aux_model_id
        api_url = (self._llm_aux_api_url.text().strip() if is_aux_target else "") or self._llm_api_url.text().strip()
        api_key = (self._llm_aux_api_key.text().strip() if is_aux_target else "") or self._llm_api_key.text().strip()

        if not api_url or not api_key:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_api_title"),
                _tr("SettingsWindow.llm_missing_api_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        models_url = models_api_url(api_url)

        if hasattr(self, '_fetch_worker') and self._fetch_worker is not None:
            if self._fetch_worker.isRunning():
                self._fetch_worker.quit()
                self._fetch_worker.wait(2000)

        self._fetch_worker = FetchModelsWorker(models_url, api_key, parent=self)
        self._fetch_worker.finished.connect(self._on_models_fetched)
        self._fetch_worker.error.connect(self._on_test_error)
        self._fetch_worker.start()

    def _on_models_fetched(self, models: list[str]):
        target = self._llm_model_fetch_target
        if target is self._llm_aux_model_id:
            list_widget = self._llm_aux_model_list
            list_layout = self._llm_aux_model_list_layout
            label = self._llm_aux_model_combo_label
            scroll = self._llm_aux_model_scroll
        else:
            list_widget = self._llm_primary_model_list
            list_layout = self._llm_primary_model_list_layout
            label = self._llm_primary_model_combo_label
            scroll = self._llm_primary_model_scroll

        while list_layout.count():
            item = list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        dark = isDarkTheme()
        for idx, model_name in enumerate(models):
            btn = QPushButton(model_name, list_widget)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left;
                    padding: 6px 14px;
                    border: none;
                    border-radius: 6px;
                    background: transparent;
                    font-size: 13px;
                    color: {'#e8e8e8' if dark else '#333333'};
                }}
                QPushButton:hover {{
                    background: {BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER};
                }}
            """)
            btn.clicked.connect(lambda checked, mn=model_name: self._set_fetched_model_id(mn))
            list_layout.addWidget(btn)
            QTimer.singleShot(idx * 30, lambda b=btn: self._animate_button_in(b))
        list_layout.addStretch()

        label.show()
        scroll.show()

    def _set_fetched_model_id(self, model_name: str):
        target = self._llm_model_fetch_target
        target.setText(model_name)
