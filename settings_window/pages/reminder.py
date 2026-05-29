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
            default="设置由角色提醒的闹钟和 25+5 番茄钟。提醒文本会结合角色好感度、长期记忆和描述生成。",
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
            default="对话中输入 @clock 0730 [描述]（四位数时间，0730 表示早上 7:30）可快速添加 24 小时内的时钟，默认由当前 Live2D 展示位的第一个角色生成个性化提醒。",
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
            default="对话中输入 @pomodoro [循环次数] [描述] 可快速启动番茄钟，默认由当前 Live2D 展示位的第一个角色生成个性化提醒。",
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

        layout.addStretch()
        self._load_reminder_config()
        self._style_reminder_page(page)
        qconfig.themeChanged.connect(lambda: self._style_reminder_page(page))
        return page

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
        self._on_alarm_repeat_changed()
        self._refresh_reminder_lists()

    def apply_remote_settings(self, data: dict):
        """Reflect reminder changes pushed from other processes (e.g. chat @clock / @pomodoro)."""
        if not isinstance(data, dict) or not self._cfg:
            return
        reminder_keys = (ALARM_CONFIG_KEY, POMODORO_CONFIG_KEY, REMINDER_DISPLAY_MODE_KEY)
        if not any(key in data for key in reminder_keys):
            return
        if ALARM_CONFIG_KEY in data:
            self._cfg.set(ALARM_CONFIG_KEY, normalize_alarms(data.get(ALARM_CONFIG_KEY, [])))
        if POMODORO_CONFIG_KEY in data:
            self._cfg.set(POMODORO_CONFIG_KEY, normalize_pomodoros(data.get(POMODORO_CONFIG_KEY, [])))
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
                REMINDER_DISPLAY_MODE_KEY: DISPLAY_MODE_FLOATING,
            }
        return {
            ALARM_CONFIG_KEY: normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, [])),
            POMODORO_CONFIG_KEY: normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, [])),
            REMINDER_DISPLAY_MODE_KEY: normalize_display_mode(self._cfg.get(REMINDER_DISPLAY_MODE_KEY, DISPLAY_MODE_FLOATING)),
        }

    def _save_reminder_config(self, show_info: bool = True, emit_update: bool = True):
        if not self._cfg or not hasattr(self, "_reminder_display_mode"):
            return
        mode = self._reminder_display_mode.itemData(self._reminder_display_mode.currentIndex()) or DISPLAY_MODE_FLOATING
        self._cfg.set(REMINDER_DISPLAY_MODE_KEY, normalize_display_mode(mode))
        self._cfg.set(ALARM_CONFIG_KEY, normalize_alarms(self._cfg.get(ALARM_CONFIG_KEY, [])))
        self._cfg.set(POMODORO_CONFIG_KEY, normalize_pomodoros(self._cfg.get(POMODORO_CONFIG_KEY, [])))
        try:
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
                time=next_at if next_at else _tr("SettingsWindow.pomodoro_ended", default="已结束"),
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
