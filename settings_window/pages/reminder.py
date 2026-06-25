from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class ReminderPageMixin:
    def _build_reminder_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("reminderPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.reminder_title", default="闹钟 / 番茄钟"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr(
            "SettingsWindow.reminder_subtitle",
            default="配置定时提醒、番茄钟和日常主动陪伴。角色会结合当前上下文、好感度与长期记忆生成自然回应。",
        ), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(10)
        mode_row.addWidget(BodyLabel(_tr("SettingsWindow.reminder_display_mode", default="提醒展示方式"), page))
        self._reminder_display_mode = OpaqueDropDownComboBox(page)
        self._reminder_display_mode.setFixedHeight(36)
        self._reminder_display_mode.addItem(_tr("SettingsWindow.reminder_display_floating", default="悬浮窗显示"), userData=DISPLAY_MODE_FLOATING)
        self._reminder_display_mode.addItem(_tr("SettingsWindow.reminder_display_system", default="系统通知提醒"), userData=DISPLAY_MODE_SYSTEM)
        mode_row.addWidget(self._reminder_display_mode, 1)
        save_mode_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_mode_btn.setFixedHeight(36)
        save_mode_btn.clicked.connect(lambda: self._save_reminder_config(show_info=True, emit_update=True))
        mode_row.addWidget(save_mode_btn)
        layout.addLayout(mode_row)

        alarm_panel = QWidget(page)
        alarm_panel.setObjectName("reminderPanel")
        alarm_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        alarm_layout = QVBoxLayout(alarm_panel)
        alarm_layout.setContentsMargins(16, 14, 16, 14)
        alarm_layout.setSpacing(10)
        alarm_layout.addWidget(StrongBodyLabel(_tr("SettingsWindow.alarm_section_title", default="闹钟"), alarm_panel))
        alarm_command_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.alarm_command_hint",
            default="对话中输入 @clock 0730 [描述]（四位数时间，0730 表示早上 7:30）可快速添加 24 小时内的时钟，默认由当前显示的第一个 Live2D 角色生成个性化提醒。",
        ), alarm_panel))
        alarm_command_hint.setObjectName("reminderHint")
        alarm_layout.addWidget(alarm_command_hint)

        alarm_form = QGridLayout()
        alarm_form.setHorizontalSpacing(10)
        alarm_form.setVerticalSpacing(8)
        alarm_form.addWidget(BodyLabel(_tr("SettingsWindow.alarm_time", default="时间"), alarm_panel), 0, 0)
        self._alarm_time_edit = TimeEdit(alarm_panel)
        self._alarm_time_edit.setDisplayFormat("HH:mm")
        self._alarm_time_edit.setTime(QTime.currentTime().addSecs(3600))
        self._alarm_time_edit.setFixedHeight(34)
        alarm_form.addWidget(self._alarm_time_edit, 0, 1)

        alarm_form.addWidget(BodyLabel(_tr("SettingsWindow.alarm_repeat", default="日期重复"), alarm_panel), 0, 2)
        self._alarm_repeat_combo = OpaqueDropDownComboBox(alarm_panel)
        self._alarm_repeat_combo.setFixedHeight(34)
        self._alarm_repeat_combo.addItem(_tr("SettingsWindow.alarm_repeat_none", default="不重复"), userData=[])
        self._alarm_repeat_combo.addItem(_tr("SettingsWindow.alarm_repeat_daily", default="每天"), userData=list(range(7)))
        self._alarm_repeat_combo.addItem(_tr("SettingsWindow.alarm_repeat_weekdays", default="工作日"), userData=[0, 1, 2, 3, 4])
        self._alarm_repeat_combo.addItem(_tr("SettingsWindow.alarm_repeat_weekends", default="周末"), userData=[5, 6])
        self._alarm_repeat_combo.addItem(_tr("SettingsWindow.alarm_repeat_custom", default="自定义"), userData="custom")
        self._alarm_repeat_combo.currentIndexChanged.connect(self._on_alarm_repeat_changed)
        alarm_form.addWidget(self._alarm_repeat_combo, 0, 3)

        self._alarm_weekday_widget = QWidget(alarm_panel)
        weekday_row = QHBoxLayout(self._alarm_weekday_widget)
        weekday_row.setContentsMargins(0, 0, 0, 0)
        weekday_row.setSpacing(6)
        self._alarm_weekday_checks: list[QCheckBox] = []
        weekday_labels = (
            _tr("ReminderCore.weekday_mon", default="周一"),
            _tr("ReminderCore.weekday_tue", default="周二"),
            _tr("ReminderCore.weekday_wed", default="周三"),
            _tr("ReminderCore.weekday_thu", default="周四"),
            _tr("ReminderCore.weekday_fri", default="周五"),
            _tr("ReminderCore.weekday_sat", default="周六"),
            _tr("ReminderCore.weekday_sun", default="周日"),
        )
        for index, label in enumerate(weekday_labels):
            check = QCheckBox(label, self._alarm_weekday_widget)
            check.setProperty("weekday", index)
            self._alarm_weekday_checks.append(check)
            weekday_row.addWidget(check)
        weekday_row.addStretch()
        alarm_form.addWidget(self._alarm_weekday_widget, 1, 1, 1, 3)

        alarm_form.addWidget(BodyLabel(_tr("SettingsWindow.alarm_description", default="描述"), alarm_panel), 2, 0)
        self._alarm_description = LineEdit(alarm_panel)
        self._alarm_description.setFixedHeight(34)
        self._alarm_description.setPlaceholderText(_tr("SettingsWindow.alarm_description_placeholder", default="例如：起床、喝水、开会"))
        alarm_form.addWidget(self._alarm_description, 2, 1, 1, 3)

        alarm_form.addWidget(BodyLabel(_tr("SettingsWindow.reminder_character", default="提醒角色"), alarm_panel), 3, 0)
        self._alarm_character_combo = OpaqueDropDownComboBox(alarm_panel)
        self._alarm_character_combo.setFixedHeight(34)
        alarm_form.addWidget(self._alarm_character_combo, 3, 1, 1, 2)
        add_alarm_btn = PrimaryPushButton(FluentIcon.ADD, _tr("SettingsWindow.alarm_add", default="添加闹钟"), alarm_panel)
        add_alarm_btn.setFixedHeight(34)
        add_alarm_btn.clicked.connect(self._add_alarm_from_form)
        alarm_form.addWidget(add_alarm_btn, 3, 3)
        alarm_layout.addLayout(alarm_form)

        self._alarm_list_widget = QWidget(alarm_panel)
        self._alarm_list_layout = QVBoxLayout(self._alarm_list_widget)
        self._alarm_list_layout.setContentsMargins(0, 4, 0, 0)
        self._alarm_list_layout.setSpacing(8)
        alarm_layout.addWidget(self._alarm_list_widget)
        layout.addWidget(alarm_panel)

        pomodoro_panel = QWidget(page)
        pomodoro_panel.setObjectName("reminderPanel")
        pomodoro_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        pomodoro_layout = QVBoxLayout(pomodoro_panel)
        pomodoro_layout.setContentsMargins(16, 14, 16, 14)
        pomodoro_layout.setSpacing(10)
        pomodoro_layout.addWidget(StrongBodyLabel(_tr("SettingsWindow.pomodoro_section_title", default="番茄钟"), pomodoro_panel))
        pomodoro_command_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.pomodoro_command_hint",
            default="对话中输入 @pomodoro [循环次数] [描述] 可快速启动番茄钟，默认由当前显示的第一个 Live2D 角色生成个性化提醒。",
        ), pomodoro_panel))
        pomodoro_command_hint.setObjectName("reminderHint")
        pomodoro_layout.addWidget(pomodoro_command_hint)

        pomo_form = QGridLayout()
        pomo_form.setHorizontalSpacing(10)
        pomo_form.setVerticalSpacing(8)
        pomo_form.addWidget(BodyLabel(_tr("SettingsWindow.pomodoro_repeat_count", default="重复次数"), pomodoro_panel), 0, 0)
        self._pomodoro_repeat_count = SpinBox(pomodoro_panel)
        self._pomodoro_repeat_count.setRange(1, 24)
        self._pomodoro_repeat_count.setValue(1)
        self._pomodoro_repeat_count.setFixedHeight(34)
        pomo_form.addWidget(self._pomodoro_repeat_count, 0, 1)
        hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.pomodoro_repeat_hint",
            default="每次为 25 分钟专注 + 5 分钟休息；每 4 次专注后自动进入 15 分钟长休息。",
        ), pomodoro_panel))
        hint.setObjectName("reminderHint")
        pomo_form.addWidget(hint, 0, 2, 1, 2)

        pomo_form.addWidget(BodyLabel(_tr("SettingsWindow.pomodoro_description", default="番茄钟描述"), pomodoro_panel), 1, 0)
        self._pomodoro_description = LineEdit(pomodoro_panel)
        self._pomodoro_description.setFixedHeight(34)
        self._pomodoro_description.setPlaceholderText(_tr("SettingsWindow.pomodoro_description_placeholder", default="例如：写代码、复习、画画"))
        pomo_form.addWidget(self._pomodoro_description, 1, 1, 1, 3)

        pomo_form.addWidget(BodyLabel(_tr("SettingsWindow.reminder_character", default="提醒角色"), pomodoro_panel), 2, 0)
        self._pomodoro_character_combo = OpaqueDropDownComboBox(pomodoro_panel)
        self._pomodoro_character_combo.setFixedHeight(34)
        pomo_form.addWidget(self._pomodoro_character_combo, 2, 1, 1, 2)
        add_pomodoro_btn = PrimaryPushButton(FluentIcon.PLAY, _tr("SettingsWindow.pomodoro_start", default="启动番茄钟"), pomodoro_panel)
        add_pomodoro_btn.setFixedHeight(34)
        add_pomodoro_btn.clicked.connect(self._add_pomodoro_from_form)
        pomo_form.addWidget(add_pomodoro_btn, 2, 3)
        pomodoro_layout.addLayout(pomo_form)

        self._pomodoro_list_widget = QWidget(pomodoro_panel)
        self._pomodoro_list_layout = QVBoxLayout(self._pomodoro_list_widget)
        self._pomodoro_list_layout.setContentsMargins(0, 4, 0, 0)
        self._pomodoro_list_layout.setSpacing(8)
        pomodoro_layout.addWidget(self._pomodoro_list_widget)
        layout.addWidget(pomodoro_panel)

        proactive_panel = QWidget(page)
        proactive_panel.setObjectName("reminderPanel")
        proactive_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        proactive_layout = QVBoxLayout(proactive_panel)
        proactive_layout.setContentsMargins(16, 14, 16, 14)
        proactive_layout.setSpacing(10)

        proactive_header = QHBoxLayout()
        proactive_header.setContentsMargins(0, 0, 0, 0)
        proactive_header.setSpacing(10)
        proactive_title_col = QVBoxLayout()
        proactive_title_col.setContentsMargins(0, 0, 0, 0)
        proactive_title_col.setSpacing(2)
        proactive_title_col.addWidget(StrongBodyLabel(_tr("SettingsWindow.proactive_section_title", default="主动陪伴 / 生活节奏"), proactive_panel))
        proactive_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.proactive_section_hint",
            default="早安、喝水、久坐、计划复盘和睡前提醒会复用角色口吻，并结合好感度与长期记忆生成自然关心。",
        ), proactive_panel))
        proactive_hint.setObjectName("reminderHint")
        proactive_title_col.addWidget(proactive_hint)
        proactive_header.addLayout(proactive_title_col, 1)
        self._proactive_enabled_switch = SwitchButton(proactive_panel)
        proactive_header.addWidget(self._proactive_enabled_switch)
        proactive_layout.addLayout(proactive_header)

        proactive_character_row = QHBoxLayout()
        proactive_character_row.setContentsMargins(0, 0, 0, 0)
        proactive_character_row.setSpacing(10)
        proactive_character_row.addWidget(BodyLabel(_tr("SettingsWindow.reminder_character", default="提醒角色"), proactive_panel))
        self._proactive_character_combo = OpaqueDropDownComboBox(proactive_panel)
        self._proactive_character_combo.setFixedHeight(34)
        proactive_character_row.addWidget(self._proactive_character_combo, 1)
        save_proactive_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), proactive_panel)
        save_proactive_btn.setFixedHeight(34)
        save_proactive_btn.clicked.connect(lambda: self._save_reminder_config(show_info=True, emit_update=True))
        proactive_character_row.addWidget(save_proactive_btn)
        proactive_layout.addLayout(proactive_character_row)

        self._proactive_list_widget = QWidget(proactive_panel)
        self._proactive_list_layout = QVBoxLayout(self._proactive_list_widget)
        self._proactive_list_layout.setContentsMargins(0, 4, 0, 0)
        self._proactive_list_layout.setSpacing(8)
        proactive_layout.addWidget(self._proactive_list_widget)
        layout.addWidget(proactive_panel)
        self._proactive_save_timer = QTimer(page)
        self._proactive_save_timer.setSingleShot(True)
        self._proactive_save_timer.timeout.connect(self._save_proactive_controls_now)

        layout.addStretch()
        self._load_reminder_config()
        self._proactive_enabled_switch.checkedChanged.connect(self._on_proactive_global_enabled_changed)
        self._proactive_character_combo.currentIndexChanged.connect(lambda _index: self._schedule_proactive_save())
        self._style_reminder_page(page)
        self._connect_theme_changed(lambda: self._style_reminder_page(page))
        return page

    def _build_care_policy_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        panel.setObjectName("carePolicySection")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 14, 0, 0)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)
        title_col.addWidget(StrongBodyLabel(_tr("SettingsWindow.care_policy_title", default="主动关怀策略"), panel))
        hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.care_policy_hint",
            default="这里是桌宠「主动开口」的总闸门：根据你此刻在做什么（打游戏、写代码、看视频……）来决定要不要打扰你。"
                    "它与上方屏幕感知设置共同决定是否主动搭话，也统一管理「主动陪伴」的生活提醒。"
                    "判断依据是你当前在做的事，而不是固定时间表。",
        ), panel))
        hint.setObjectName("carePolicyHint")
        title_col.addWidget(hint)
        header.addLayout(title_col, 1)
        self._care_policy_enabled = SwitchButton(panel)
        self._care_policy_enabled.checkedChanged.connect(lambda _checked: self._schedule_proactive_save())
        header.addWidget(self._care_policy_enabled)
        layout.addLayout(header)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.addWidget(BodyLabel(_tr("SettingsWindow.care_policy_quiet_hours", default="勿扰时段"), panel), 0, 0)
        self._care_policy_quiet_enabled = SwitchButton(panel)
        self._care_policy_quiet_enabled.checkedChanged.connect(lambda _checked: self._schedule_proactive_save())
        form.addWidget(self._care_policy_quiet_enabled, 0, 1)
        self._care_policy_quiet_start = TimeEdit(panel)
        self._care_policy_quiet_start.setDisplayFormat("HH:mm")
        self._care_policy_quiet_start.setFixedHeight(34)
        self._care_policy_quiet_start.timeChanged.connect(lambda _value: self._schedule_proactive_save())
        form.addWidget(self._care_policy_quiet_start, 0, 2)
        self._care_policy_quiet_end = TimeEdit(panel)
        self._care_policy_quiet_end.setDisplayFormat("HH:mm")
        self._care_policy_quiet_end.setFixedHeight(34)
        self._care_policy_quiet_end.timeChanged.connect(lambda _value: self._schedule_proactive_save())
        form.addWidget(self._care_policy_quiet_end, 0, 3)
        layout.addLayout(form)

        columns_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.care_policy_columns_hint",
            default="按你当下在做的事分别设置（两个维度互相独立）：\n"
                    "· 语气模式 = 开口时的口吻（轻声=更克制不打扰、增强关怀=更主动温暖、静默=只在重要提醒时才出声）；\n"
                    "· 频率倍率 = 在上方「主动开口间隔」基础上调整疏密（倍率越大间隔越长、越少打扰，1x 即不变）；\n"
                    "· 屏幕搭话 / 生活提醒 = 两个开关，分别控制这两类主动消息在该状态下是否允许出现。",
        ), panel))
        columns_hint.setObjectName("carePolicyHint")
        layout.addWidget(columns_hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        # 让语气/倍率两列吸收多余宽度，复选框列保持内容宽度，并在最右留出固定边距，
        # 避免最外侧复选框紧贴面板右边框被裁切。
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)
        grid.setColumnMinimumWidth(5, 16)
        headers = (
            _tr("SettingsWindow.care_policy_state", default="状态"),
            _tr("SettingsWindow.care_policy_mode", default="语气模式"),
            _tr("SettingsWindow.care_policy_multiplier", default="频率倍率"),
            _tr("SettingsWindow.care_policy_allow_screen", default="屏幕搭话"),
            _tr("SettingsWindow.care_policy_allow_lifestyle", default="生活提醒"),
        )
        for column, text in enumerate(headers):
            label = BodyLabel(text, panel)
            label.setObjectName("carePolicyHint")
            grid.addWidget(label, 0, column)

        self._care_policy_rule_widgets = {}
        for row, state in enumerate(CARE_DESKTOP_STATES, start=1):
            grid.addWidget(BodyLabel(self._care_policy_state_label(state), panel), row, 0)
            mode_combo = OpaqueDropDownComboBox(panel)
            mode_combo.setFixedHeight(32)
            mode_combo.setMinimumWidth(120)
            for mode in ("normal", "quiet", "silent", "encourage"):
                mode_combo.addItem(self._care_policy_mode_label(mode), userData=mode)
            mode_combo.currentIndexChanged.connect(lambda _index: self._schedule_proactive_save())
            grid.addWidget(mode_combo, row, 1)

            multiplier_combo = OpaqueDropDownComboBox(panel)
            multiplier_combo.setFixedHeight(32)
            multiplier_combo.setMinimumWidth(96)
            for value in (0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0):
                multiplier_combo.addItem(f"{value:g}x", userData=value)
            multiplier_combo.currentIndexChanged.connect(lambda _index: self._schedule_proactive_save())
            grid.addWidget(multiplier_combo, row, 2)

            allow_screen = CheckBox("", panel)
            allow_screen.stateChanged.connect(lambda _state: self._schedule_proactive_save())
            grid.addWidget(allow_screen, row, 3, Qt.AlignmentFlag.AlignLeft)
            allow_lifestyle = CheckBox("", panel)
            allow_lifestyle.stateChanged.connect(lambda _state: self._schedule_proactive_save())
            grid.addWidget(allow_lifestyle, row, 4, Qt.AlignmentFlag.AlignLeft)
            self._care_policy_rule_widgets[state] = {
                "mode": mode_combo,
                "cooldown_multiplier": multiplier_combo,
                "allow_screen_awareness": allow_screen,
                "allow_lifestyle_reminders": allow_lifestyle,
            }
        layout.addLayout(grid)
        self._load_care_policy_controls()
        return panel

    def _care_policy_state_label(self, state: str) -> str:
        return _tr(f"SettingsWindow.care_policy_state_{state}", default={
            "gaming": "游戏",
            "media": "媒体",
            "coding": "编码",
            "writing": "写作",
            "chatting": "聊天",
            "web": "网页",
            "desktop": "桌面",
            "idle": "空闲",
            "unknown": "未知",
        }.get(state, state))

    def _care_policy_mode_label(self, mode: str) -> str:
        # 语气模式只影响开口的口吻（silent 还会拦截非重要提醒），与频率无关——
        # 频率由相邻的「频率倍率」单独控制。
        return _tr(f"SettingsWindow.care_policy_mode_{mode}", default={
            "normal": "正常",
            "quiet": "轻声",
            "silent": "静默",
            "encourage": "增强关怀",
        }.get(mode, mode))

    def _set_combo_data(self, combo: ComboBox, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def _on_alarm_repeat_changed(self):
        if not hasattr(self, "_alarm_repeat_combo"):
            return
        custom = self._alarm_repeat_combo.itemData(self._alarm_repeat_combo.currentIndex()) == "custom"
        self._alarm_weekday_widget.setVisible(custom)

    def _reminder_characters(self) -> list[str]:
        result = []
        seen = set()
        for item in self._configured_models:
            character = str(item.get("character", "") or "").strip()
            if character and character not in seen:
                result.append(character)
                seen.add(character)
        if not result and self._cfg:
            models = self._cfg.get("models", [])
            if isinstance(models, list):
                for item in models:
                    if isinstance(item, dict):
                        character = str(item.get("character", "") or "").strip()
                        if character and character not in seen:
                            result.append(character)
                            seen.add(character)
        if self._current_char and self._current_char not in seen:
            result.insert(0, self._current_char)
        return result or list(self._model_manager.characters[:12])

    def _fill_reminder_character_combo(self, combo: ComboBox, selected: str = ""):
        combo.clear()
        characters = self._reminder_characters()
        default_char = selected or (default_reminder_character(self._cfg) if self._cfg else "")
        for character in characters:
            combo.addItem(self._model_manager.get_display_name(character), userData=character)
        if combo.count() <= 0 and default_char:
            combo.addItem(default_char, userData=default_char)
        for index in range(combo.count()):
            if combo.itemData(index) == default_char:
                combo.setCurrentIndex(index)
                return

    def _selected_reminder_character(self, combo: ComboBox) -> str:
        if combo.count() <= 0:
            return default_reminder_character(self._cfg) if self._cfg else ""
        return str(combo.itemData(combo.currentIndex()) or "").strip()

    def _alarm_repeat_days_from_form(self) -> list[int]:
        value = self._alarm_repeat_combo.itemData(self._alarm_repeat_combo.currentIndex())
        if value == "custom":
            return [index for index, check in enumerate(self._alarm_weekday_checks) if check.isChecked()]
        return list(value or [])

    def _load_reminder_config(self):
        if not self._cfg:
            return
        mode = normalize_display_mode(self._cfg.get(REMINDER_DISPLAY_MODE_KEY, DISPLAY_MODE_FLOATING))
        for index in range(self._reminder_display_mode.count()):
            if self._reminder_display_mode.itemData(index) == mode:
                self._reminder_display_mode.setCurrentIndex(index)
                break
        self._fill_reminder_character_combo(self._alarm_character_combo)
        self._fill_reminder_character_combo(self._pomodoro_character_combo)
        proactive = normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {}))
        self._loading_proactive_controls = True
        self._proactive_enabled_switch.setChecked(bool(proactive.get("enabled", False)))
        self._fill_reminder_character_combo(self._proactive_character_combo, proactive.get("character", ""))
        self._loading_proactive_controls = False
        self._load_care_policy_controls()
        self._on_alarm_repeat_changed()
        self._refresh_reminder_lists()

    def _apply_reminder_remote_settings(self, data: dict):
        """Reflect reminder changes pushed from other processes (e.g. chat @clock / @pomodoro)."""
        if not isinstance(data, dict) or not self._cfg:
            return
        reminder_keys = (
            ALARM_CONFIG_KEY,
            POMODORO_CONFIG_KEY,
            PROACTIVE_COMPANION_CONFIG_KEY,
            PROACTIVE_CARE_POLICY_CONFIG_KEY,
            REMINDER_DISPLAY_MODE_KEY,
        )
        if not any(key in data for key in reminder_keys):
            return
        if ALARM_CONFIG_KEY in data:
            self._cfg.set(ALARM_CONFIG_KEY, normalize_alarms(data.get(ALARM_CONFIG_KEY, [])))
        if POMODORO_CONFIG_KEY in data:
            self._cfg.set(POMODORO_CONFIG_KEY, normalize_pomodoros(data.get(POMODORO_CONFIG_KEY, [])))
        if PROACTIVE_COMPANION_CONFIG_KEY in data:
            save_timer = getattr(self, "_proactive_save_timer", None)
            if save_timer is not None and save_timer.isActive():
                save_timer.stop()
            proactive = normalize_proactive_companion(data.get(PROACTIVE_COMPANION_CONFIG_KEY, {}))
            self._cfg.set(PROACTIVE_COMPANION_CONFIG_KEY, proactive)
            self._loading_proactive_controls = True
            try:
                if hasattr(self, "_proactive_enabled_switch"):
                    self._proactive_enabled_switch.setChecked(bool(proactive.get("enabled", False)))
                if hasattr(self, "_proactive_character_combo"):
                    self._fill_reminder_character_combo(self._proactive_character_combo, proactive.get("character", ""))
            finally:
                self._loading_proactive_controls = False
        if PROACTIVE_CARE_POLICY_CONFIG_KEY in data:
            policy = normalize_proactive_care_policy(data.get(PROACTIVE_CARE_POLICY_CONFIG_KEY, {}))
            self._cfg.set(PROACTIVE_CARE_POLICY_CONFIG_KEY, policy)
            self._load_care_policy_controls()
            if hasattr(self, "_screen_awareness_interval"):
                self._load_screen_awareness_controls()
        if REMINDER_DISPLAY_MODE_KEY in data:
            mode = normalize_display_mode(data.get(REMINDER_DISPLAY_MODE_KEY, DISPLAY_MODE_FLOATING))
            self._cfg.set(REMINDER_DISPLAY_MODE_KEY, mode)
            if hasattr(self, "_reminder_display_mode"):
                for index in range(self._reminder_display_mode.count()):
                    if self._reminder_display_mode.itemData(index) == mode:
                        self._reminder_display_mode.setCurrentIndex(index)
                        break
        if hasattr(self, "_alarm_list_layout"):
            self._refresh_reminder_lists()

    def _reminder_settings_data(self) -> dict:
        if not self._cfg:
            return {
                ALARM_CONFIG_KEY: [],
                POMODORO_CONFIG_KEY: [],
                PROACTIVE_COMPANION_CONFIG_KEY: normalize_proactive_companion({}),
                PROACTIVE_CARE_POLICY_CONFIG_KEY: normalize_proactive_care_policy({}),
                REMINDER_DISPLAY_MODE_KEY: DISPLAY_MODE_FLOATING,
            }
        return {
            ALARM_CONFIG_KEY: normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, [])),
            POMODORO_CONFIG_KEY: normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, [])),
            PROACTIVE_COMPANION_CONFIG_KEY: normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {})),
            PROACTIVE_CARE_POLICY_CONFIG_KEY: normalize_proactive_care_policy(self._cfg.get(PROACTIVE_CARE_POLICY_CONFIG_KEY, {})),
            REMINDER_DISPLAY_MODE_KEY: normalize_display_mode(self._cfg.get(REMINDER_DISPLAY_MODE_KEY, DISPLAY_MODE_FLOATING)),
        }

    def _save_reminder_config(self, show_info: bool = True, emit_update: bool = True):
        if not self._cfg or not hasattr(self, "_reminder_display_mode"):
            return
        save_timer = getattr(self, "_proactive_save_timer", None)
        if save_timer is not None and save_timer.isActive():
            save_timer.stop()
        self._sync_proactive_config_from_ui()
        self._sync_care_policy_config_from_ui()
        mode = self._reminder_display_mode.itemData(self._reminder_display_mode.currentIndex()) or DISPLAY_MODE_FLOATING
        self._cfg.set(REMINDER_DISPLAY_MODE_KEY, normalize_display_mode(mode))
        self._cfg.set(ALARM_CONFIG_KEY, normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, [])))
        self._cfg.set(POMODORO_CONFIG_KEY, normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, [])))
        self._cfg.set(PROACTIVE_COMPANION_CONFIG_KEY, normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {})))
        self._cfg.set(PROACTIVE_CARE_POLICY_CONFIG_KEY, normalize_proactive_care_policy(self._cfg.get(PROACTIVE_CARE_POLICY_CONFIG_KEY, {})))
        try:
            if not self._config_save_deferred():
                self._cfg.save()
            if emit_update:
                self.settings_changed.emit(self._reminder_settings_data())
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.reminder_saved_title", default="提醒设置已保存"),
                    _tr("SettingsWindow.reminder_saved_content", default="闹钟和番茄钟调度已更新。"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.reminder_failed_title", default="提醒设置保存失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _add_alarm_from_form(self):
        if not self._cfg:
            return
        repeat_days = self._alarm_repeat_days_from_form()
        if self._alarm_repeat_combo.itemData(self._alarm_repeat_combo.currentIndex()) == "custom" and not repeat_days:
            InfoBar.warning(
                _tr("SettingsWindow.alarm_repeat_empty_title", default="请选择重复日期"),
                _tr("SettingsWindow.alarm_repeat_empty_content", default="自定义重复至少需要选择一天。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        alarm = create_alarm(
            self._alarm_time_edit.time().toString("HH:mm"),
            repeat_days,
            self._alarm_description.text().strip(),
            self._selected_reminder_character(self._alarm_character_combo),
        )
        alarms = normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, []))
        alarms.append(alarm)
        self._cfg.set(ALARM_CONFIG_KEY, alarms)
        self._alarm_description.clear()
        self._save_reminder_config(show_info=False, emit_update=True)
        self._refresh_reminder_lists()
        InfoBar.success(
            _tr("SettingsWindow.alarm_added_title", default="闹钟已添加"),
            _tr("SettingsWindow.alarm_added_content", default="到点后会由所选角色生成提醒。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _add_pomodoro_from_form(self):
        if not self._cfg:
            return
        pomodoro = create_pomodoro(
            self._pomodoro_repeat_count.value(),
            self._pomodoro_description.text().strip(),
            self._selected_reminder_character(self._pomodoro_character_combo),
        )
        pomodoros = normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, []))
        pomodoros.append(pomodoro)
        self._cfg.set(POMODORO_CONFIG_KEY, pomodoros)
        self._pomodoro_description.clear()
        self._save_reminder_config(show_info=False, emit_update=True)
        self._refresh_reminder_lists()
        InfoBar.success(
            _tr("SettingsWindow.pomodoro_added_title", default="番茄钟已启动"),
            _tr("SettingsWindow.pomodoro_added_content", default="25 分钟专注计时已经开始。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _delete_alarm(self, alarm_id: str):
        if not self._cfg:
            return
        alarms = [alarm for alarm in normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, [])) if alarm.get("id") != alarm_id]
        self._cfg.set(ALARM_CONFIG_KEY, alarms)
        self._save_reminder_config(show_info=False, emit_update=True)
        self._refresh_reminder_lists()

    def _toggle_alarm_enabled(self, alarm_id: str, enabled: bool):
        if not self._cfg:
            return
        alarms = normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, []))
        for alarm in alarms:
            if alarm.get("id") == alarm_id:
                alarm["enabled"] = bool(enabled)
                alarm["next_at"] = ""
                break
        self._cfg.set(ALARM_CONFIG_KEY, normalize_alarms(alarms))
        self._save_reminder_config(show_info=False, emit_update=True)
        self._refresh_reminder_lists()

    def _delete_pomodoro(self, pomodoro_id: str):
        if not self._cfg:
            return
        pomodoros = [
            pomodoro for pomodoro in normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, []))
            if pomodoro.get("id") != pomodoro_id
        ]
        self._cfg.set(POMODORO_CONFIG_KEY, pomodoros)
        self._save_reminder_config(show_info=False, emit_update=True)
        self._refresh_reminder_lists()

    def _refresh_reminder_lists(self):
        if not hasattr(self, "_alarm_list_layout") or not self._cfg:
            return
        self._clear_layout(self._alarm_list_layout)
        alarms = normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, []))
        if not alarms:
            self._alarm_list_layout.addWidget(self._empty_reminder_label(
                _tr("SettingsWindow.alarm_empty", default="还没有闹钟。"),
                self._alarm_list_widget,
            ))
        else:
            for alarm in alarms:
                self._alarm_list_layout.addWidget(self._alarm_row(alarm))
        self._alarm_list_layout.addStretch()

        self._clear_layout(self._pomodoro_list_layout)
        pomodoros = normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, []))
        if not pomodoros:
            self._pomodoro_list_layout.addWidget(self._empty_reminder_label(
                _tr("SettingsWindow.pomodoro_empty", default="还没有运行中的番茄钟。"),
                self._pomodoro_list_widget,
            ))
        else:
            for pomodoro in pomodoros:
                self._pomodoro_list_layout.addWidget(self._pomodoro_row(pomodoro))
        self._pomodoro_list_layout.addStretch()

        if hasattr(self, "_proactive_list_layout"):
            self._loading_proactive_controls = True
            try:
                self._clear_layout(self._proactive_list_layout)
                proactive = normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {}))
                self._proactive_item_widgets = {}
                for item in proactive.get("items", []):
                    row = self._proactive_row(item)
                    self._proactive_list_layout.addWidget(row)
                self._proactive_list_layout.addStretch()
            finally:
                self._loading_proactive_controls = False

    def _alarm_row(self, alarm: dict) -> QWidget:
        row = QWidget(self._alarm_list_widget)
        row.setObjectName("reminderRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        desc = alarm.get("description", "") or _tr("SettingsWindow.alarm_no_description", default="无描述")
        character = alarm.get("character", "")
        display = self._model_manager.get_display_name(character) if character else _tr("SettingsWindow.reminder_default_character", default="默认角色")
        schedule_label = self._alarm_schedule_label(alarm)
        title = StrongBodyLabel(f"{alarm.get('time', '--:--')}  {repeat_days_label(alarm.get('repeat_days', []))}", row)
        subtitle = BodyLabel(f"{desc} · {display} · {schedule_label}", row)
        subtitle.setObjectName("reminderHint")
        subtitle.setWordWrap(True)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col, 1)
        enabled = SwitchButton(row)
        enabled.setChecked(bool(alarm.get("enabled", True)))
        enabled.checkedChanged.connect(lambda checked, aid=alarm.get("id", ""): self._toggle_alarm_enabled(aid, checked))
        layout.addWidget(enabled)
        delete_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.memory_delete", default="删除"), row)
        delete_btn.clicked.connect(lambda checked=False, aid=alarm.get("id", ""): self._delete_alarm(aid))
        layout.addWidget(delete_btn)
        return row

    def _alarm_schedule_label(self, alarm: dict) -> str:
        if not alarm.get("enabled", True):
            return _tr("SettingsWindow.alarm_finished", default="已提醒") if alarm.get("last_triggered_at") else _tr("SettingsWindow.alarm_disabled", default="未启用")
        next_at = self._format_reminder_time(alarm.get("next_at", ""))
        if not next_at:
            return _tr("SettingsWindow.alarm_not_scheduled", default="未安排")
        if alarm.get("repeat_days"):
            return _tr("SettingsWindow.alarm_next_at", default="下次 {time}").format(time=next_at)
        return _tr("SettingsWindow.alarm_once_at", default="提醒时间 {time}").format(time=next_at)

    def _pomodoro_row(self, pomodoro: dict) -> QWidget:
        row = QWidget(self._pomodoro_list_widget)
        row.setObjectName("reminderRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        desc = pomodoro.get("description", "") or _tr("SettingsWindow.pomodoro_no_description", default="无描述")
        character = pomodoro.get("character", "")
        display = self._model_manager.get_display_name(character) if character else _tr("SettingsWindow.reminder_default_character", default="默认角色")
        status = pomodoro_phase_label(pomodoro.get("phase", "focus"))
        next_at = self._format_reminder_time(pomodoro.get("next_at", ""))
        title = StrongBodyLabel(
            _tr(
                "SettingsWindow.pomodoro_row_title",
                default="{status} · {done}/{total}",
                status=status,
                done=pomodoro.get("completed_focus_count", 0),
                total=pomodoro.get("repeat_count", 1),
            ),
            row,
        )
        subtitle = BodyLabel(
            _tr(
                "SettingsWindow.pomodoro_row_subtitle",
                default="{desc} · {character} · 下次切换 {time}",
                desc=desc,
                character=display,
                time=next_at or _tr("SettingsWindow.pomodoro_ended", default="已结束"),
            ),
            row,
        )
        subtitle.setObjectName("reminderHint")
        subtitle.setWordWrap(True)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col, 1)
        delete_btn = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.memory_delete", default="删除"), row)
        delete_btn.clicked.connect(lambda checked=False, pid=pomodoro.get("id", ""): self._delete_pomodoro(pid))
        layout.addWidget(delete_btn)
        return row

    def _proactive_row(self, item: dict) -> QWidget:
        row = QWidget(self._proactive_list_widget)
        row.setObjectName("reminderRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        title = StrongBodyLabel(self._proactive_item_title(item), row)
        detail_text = self._proactive_schedule_label(item)
        subtitle = BodyLabel(detail_text, row)
        subtitle.setObjectName("reminderHint")
        subtitle.setWordWrap(True)
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        layout.addLayout(text_col, 1)

        enabled = SwitchButton(row)
        enabled.setChecked(bool(item.get("enabled", True)))
        enabled.checkedChanged.connect(lambda checked, iid=item.get("id", ""): self._set_proactive_item_enabled(iid, checked))
        layout.addWidget(enabled)

        if item.get("schedule_type") == "interval":
            interval = SpinBox(row)
            interval.setRange(10, 480)
            interval.setSingleStep(10)
            interval.setValue(int(item.get("interval_minutes") or 60))
            interval.setFixedWidth(92)
            interval.setSuffix(_tr("SettingsWindow.proactive_minutes_suffix", default=" 分钟"))
            interval.valueChanged.connect(lambda _value, iid=item.get("id", ""): self._on_proactive_item_control_changed(iid))
            layout.addWidget(interval)
            primary_control = interval
        else:
            time_edit = TimeEdit(row)
            time_edit.setDisplayFormat("HH:mm")
            time_edit.setTime(QTime.fromString(str(item.get("time") or "08:30"), "HH:mm"))
            time_edit.setFixedWidth(92)
            time_edit.timeChanged.connect(lambda _value, iid=item.get("id", ""): self._on_proactive_item_control_changed(iid))
            layout.addWidget(time_edit)
            primary_control = time_edit

        self._proactive_item_widgets[str(item.get("id") or "")] = {
            "enabled": enabled,
            "primary": primary_control,
            "subtitle": subtitle,
            "schedule_type": item.get("schedule_type", "daily"),
        }
        primary_control.setEnabled(bool(item.get("enabled", True)))
        return row

    def _proactive_schedule_label(self, item: dict) -> str:
        if item.get("schedule_type") == "interval":
            return _tr(
                "SettingsWindow.proactive_interval_label",
                default="每 {minutes} 分钟 · {start}-{end}",
                minutes=item.get("interval_minutes", 60),
                start=item.get("active_start", "09:00"),
                end=item.get("active_end", "22:00"),
            )
        return _tr("SettingsWindow.proactive_daily_label", default="每天 {time}", time=item.get("time", ""))

    def _proactive_item_title(self, item: dict) -> str:
        item_id = str(item.get("id") or item.get("kind") or "").strip()
        return _tr(
            f"SettingsWindow.proactive_{item_id}_title",
            default=str(item.get("title") or item_id),
        )

    def _set_proactive_item_enabled(self, item_id: str, enabled: bool):
        widgets = getattr(self, "_proactive_item_widgets", {}).get(str(item_id or ""))
        if widgets:
            widgets["primary"].setEnabled(bool(enabled))
        self._on_proactive_item_control_changed(item_id)

    def _on_proactive_global_enabled_changed(self, _checked: bool):
        if getattr(self, "_loading_proactive_controls", False):
            return
        self._schedule_proactive_save()

    def _on_proactive_item_control_changed(self, item_id: str):
        if getattr(self, "_loading_proactive_controls", False):
            return
        if not self._cfg:
            return
        self._update_proactive_row_preview(item_id)
        self._schedule_proactive_save()

    def _schedule_proactive_save(self):
        if getattr(self, "_loading_proactive_controls", False):
            return
        if not self._cfg:
            return
        timer = getattr(self, "_proactive_save_timer", None)
        if timer is None:
            self._save_proactive_controls_now()
            return
        timer.start(350)

    def _save_proactive_controls_now(self):
        if getattr(self, "_loading_proactive_controls", False):
            return
        if not self._cfg:
            return
        self._sync_proactive_config_from_ui()
        self._sync_care_policy_config_from_ui()
        self._cfg.save()
        self.settings_changed.emit(self._reminder_settings_data())

    def _update_proactive_row_preview(self, item_id: str):
        widgets = getattr(self, "_proactive_item_widgets", {}).get(str(item_id or ""))
        if not widgets:
            return
        item = {
            "schedule_type": widgets.get("schedule_type", "daily"),
        }
        primary = widgets["primary"]
        if item["schedule_type"] == "interval":
            item["interval_minutes"] = int(primary.value())
            item["active_start"] = "09:00"
            item["active_end"] = "22:00"
        else:
            item["time"] = primary.time().toString("HH:mm")
        subtitle = widgets.get("subtitle")
        if subtitle is not None:
            subtitle.setText(self._proactive_schedule_label(item))

    def _sync_proactive_config_from_ui(self):
        if not self._cfg or not hasattr(self, "_proactive_enabled_switch"):
            return
        proactive = normalize_proactive_companion(self._cfg.get(PROACTIVE_COMPANION_CONFIG_KEY, {}))
        item_by_id = {str(item.get("id") or ""): item for item in proactive.get("items", [])}
        for item_id, widgets in getattr(self, "_proactive_item_widgets", {}).items():
            item = item_by_id.get(item_id)
            if not item:
                continue
            item["enabled"] = bool(widgets["enabled"].isChecked())
            primary = widgets["primary"]
            if item.get("schedule_type") == "interval":
                item["interval_minutes"] = int(primary.value())
            else:
                item["time"] = primary.time().toString("HH:mm")
            item["next_at"] = ""
        proactive["enabled"] = bool(self._proactive_enabled_switch.isChecked())
        proactive["character"] = self._selected_reminder_character(self._proactive_character_combo)
        self._cfg.set(PROACTIVE_COMPANION_CONFIG_KEY, normalize_proactive_companion(proactive))

    def _load_care_policy_controls(self):
        if not self._cfg or not hasattr(self, "_care_policy_enabled"):
            return
        policy = normalize_proactive_care_policy(self._cfg.get(PROACTIVE_CARE_POLICY_CONFIG_KEY, {}))
        self._loading_proactive_controls = True
        try:
            self._care_policy_enabled.setChecked(bool(policy.get("enabled", True)))
            self._care_policy_quiet_enabled.setChecked(bool(policy.get("quiet_hours_enabled", False)))
            self._care_policy_quiet_start.setTime(QTime.fromString(str(policy.get("quiet_start") or "23:30"), "HH:mm"))
            self._care_policy_quiet_end.setTime(QTime.fromString(str(policy.get("quiet_end") or "08:00"), "HH:mm"))
            rules = policy.get("state_rules", {}) if isinstance(policy.get("state_rules"), dict) else {}
            for state, widgets in getattr(self, "_care_policy_rule_widgets", {}).items():
                rule = rules.get(state, {}) if isinstance(rules.get(state, {}), dict) else {}
                self._set_combo_data(widgets["mode"], rule.get("mode", "normal"))
                self._set_combo_data(widgets["cooldown_multiplier"], float(rule.get("cooldown_multiplier", 1.0) or 1.0))
                widgets["allow_screen_awareness"].setChecked(bool(rule.get("allow_screen_awareness", True)))
                widgets["allow_lifestyle_reminders"].setChecked(bool(rule.get("allow_lifestyle_reminders", True)))
        finally:
            self._loading_proactive_controls = False

    def _sync_care_policy_config_from_ui(self):
        if not self._cfg or not hasattr(self, "_care_policy_enabled"):
            return
        current = normalize_proactive_care_policy(self._cfg.get(PROACTIVE_CARE_POLICY_CONFIG_KEY, {}))
        shared_interval = (
            int(self._screen_awareness_interval.value())
            if hasattr(self, "_screen_awareness_interval")
            else int(current.get("global_cooldown_minutes", 30) or 30)
        )
        policy = {
            "enabled": bool(self._care_policy_enabled.isChecked()),
            "global_cooldown_minutes": shared_interval,
            "quiet_hours_enabled": bool(self._care_policy_quiet_enabled.isChecked()),
            "quiet_start": self._care_policy_quiet_start.time().toString("HH:mm"),
            "quiet_end": self._care_policy_quiet_end.time().toString("HH:mm"),
            "last_care_at": current.get("last_care_at", ""),
            "last_screen_awareness_at": current.get("last_screen_awareness_at", ""),
            "last_skip_reason": current.get("last_skip_reason", ""),
            "state_rules": {},
        }
        self._cfg.set("screen_awareness_interval_minutes", shared_interval)
        for state, widgets in getattr(self, "_care_policy_rule_widgets", {}).items():
            policy["state_rules"][state] = {
                "mode": widgets["mode"].itemData(widgets["mode"].currentIndex()) or "normal",
                "cooldown_multiplier": widgets["cooldown_multiplier"].itemData(widgets["cooldown_multiplier"].currentIndex()) or 1.0,
                "allow_screen_awareness": bool(widgets["allow_screen_awareness"].isChecked()),
                "allow_lifestyle_reminders": bool(widgets["allow_lifestyle_reminders"].isChecked()),
            }
        self._cfg.set(PROACTIVE_CARE_POLICY_CONFIG_KEY, normalize_proactive_care_policy(policy))

    def _save_care_policy_config(self, show_info: bool = True, emit_update: bool = True) -> bool:
        if not self._cfg or not hasattr(self, "_care_policy_enabled"):
            return False
        save_timer = getattr(self, "_proactive_save_timer", None)
        if save_timer is not None and save_timer.isActive():
            save_timer.stop()
        self._sync_care_policy_config_from_ui()
        try:
            if not self._config_save_deferred():
                self._cfg.save()
            if emit_update:
                self.settings_changed.emit({
                    PROACTIVE_CARE_POLICY_CONFIG_KEY: normalize_proactive_care_policy(
                        self._cfg.get(PROACTIVE_CARE_POLICY_CONFIG_KEY, {})
                    ),
                })
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.care_policy_saved_title", default="主动关怀策略已保存"),
                    _tr("SettingsWindow.care_policy_saved_content", default="屏幕搭话和生活提醒规则已更新。"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            return True
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.reminder_failed_title", default="提醒设置保存失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return False

    def _empty_reminder_label(self, text: str, parent: QWidget) -> QLabel:
        label = BodyLabel(text, parent)
        label.setObjectName("reminderHint")
        label.setWordWrap(True)
        return label

    def _format_reminder_time(self, value: str) -> str:
        dt = parse_iso_datetime(value)
        if not dt:
            return ""
        return dt.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                SettingsWindow._clear_layout(child_layout)

    def _style_reminder_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        row_bg = "#2d2d2d" if dark else "#fbfbfd"
        border = "#3b3b3b" if dark else "#e4d9df"
        row_border = "#444444" if dark else "#eee3e9"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f3f3f6" if dark else "#202126"
        page.setStyleSheet(f"""
            QWidget#reminderPage {{
                background: {page_bg};
            }}
            QWidget#reminderPanel {{
                background: {panel_bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QWidget#reminderRow {{
                background: {row_bg};
                border: 1px solid {row_border};
                border-radius: 8px;
            }}
            QWidget#reminderPanel BodyLabel,
            QWidget#reminderPanel StrongBodyLabel {{
                color: {text};
            }}
            BodyLabel#reminderHint {{
                color: {muted};
                font-size: 13px;
            }}
            QTimeEdit, QSpinBox, QCheckBox {{
                color: {text};
                font-size: 13px;
            }}
        """)
