from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class BehaviorPageMixin:

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

    @staticmethod
    def _set_switch_state(switch, checked: bool, enabled: bool | None = None):
        if switch is None:
            return
        switch.blockSignals(True)
        switch.setChecked(bool(checked))
        if enabled is not None:
            switch.setEnabled(bool(enabled))
        switch.blockSignals(False)

    def _sync_live2d_behavior_switches(self):
        for attr in ("_live2d_idle_actions_switch", "_behavior_idle_actions_switch"):
            self._set_switch_state(getattr(self, attr, None), self._live2d_idle_actions_enabled)
        for attr in ("_live2d_head_tracking_switch", "_behavior_head_tracking_switch"):
            self._set_switch_state(
                getattr(self, attr, None),
                self._live2d_head_tracking_enabled,
                not self._live2d_mutual_gaze_enabled,
            )
        for attr in ("_live2d_mutual_gaze_switch", "_behavior_mutual_gaze_switch"):
            self._set_switch_state(getattr(self, attr, None), self._live2d_mutual_gaze_enabled)

    def _save_live2d_behavior_config(self):
        if not self._cfg:
            return
        self._cfg.set("live2d_idle_actions_enabled", self._live2d_idle_actions_enabled)
        self._cfg.set("live2d_head_tracking_enabled", self._live2d_head_tracking_enabled)
        self._cfg.set("live2d_mutual_gaze_enabled", self._live2d_mutual_gaze_enabled)
        self._cfg.save()

    def _on_live2d_idle_actions_changed(self, checked: bool):
        self._live2d_idle_actions_enabled = bool(checked)
        self._sync_live2d_behavior_switches()
        self._save_live2d_behavior_config()

    def _on_live2d_head_tracking_changed(self, checked: bool):
        checked = bool(checked) and not self._live2d_mutual_gaze_enabled
        self._live2d_head_tracking_enabled = checked
        self._sync_live2d_behavior_switches()
        self._save_live2d_behavior_config()

    def _on_live2d_mutual_gaze_changed(self, checked: bool):
        self._live2d_mutual_gaze_enabled = bool(checked)
        if self._live2d_mutual_gaze_enabled:
            self._live2d_head_tracking_enabled = False
        self._sync_live2d_behavior_switches()
        self._save_live2d_behavior_config()

    def _populate_default_motion_combo(self, item: dict):
        combo = self._default_motion_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_tr("SettingsWindow.follow_model_default"), userData="")
        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        for motion in motions:
            combo.addItem(motion, userData=motion)
        current = item.get("default_motion", "")
        if current not in motions:
            current = ""
            item["default_motion"] = ""
        for idx in range(combo.count()):
            if combo.itemData(idx) == current:
                combo.setCurrentIndex(idx)
                break
        combo.blockSignals(False)

    def _on_default_motion_changed(self, index: int):
        item = self._selected_model_item()
        if not item:
            return
        motion = self._default_motion_combo.itemData(index) or ""
        item["default_motion"] = motion
        self._save_configured_models()

    def _reset_default_motion(self):
        item = self._selected_model_item()
        if not item:
            return
        item["default_motion"] = ""
        self._populate_default_motion_combo(item)
        self._save_configured_models()

    def _populate_default_expression_combo(self, item: dict):
        combo = self._default_expression_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_tr("SettingsWindow.follow_model_default"), userData="")
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])
        for expression in expressions:
            combo.addItem(expression, userData=expression)
        current = item.get("default_expression", "")
        if current not in expressions:
            current = ""
            item["default_expression"] = ""
        for idx in range(combo.count()):
            if combo.itemData(idx) == current:
                combo.setCurrentIndex(idx)
                break
        combo.blockSignals(False)

    def _on_default_expression_changed(self, index: int):
        item = self._selected_model_item()
        if not item:
            return
        expression = self._default_expression_combo.itemData(index) or ""
        item["default_expression"] = expression
        self._save_configured_models()

    def _reset_default_expression(self):
        item = self._selected_model_item()
        if not item:
            return
        item["default_expression"] = ""
        self._populate_default_expression_combo(item)
        self._save_configured_models()

    def _populate_click_motion_combos(self, item: dict):
        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])
        actions = normalize_click_motion_actions(
            item.get("click_motion_actions", {}),
            motions,
            expressions,
        )
        item["click_motion_actions"] = actions
        for region, combo in self._click_motion_combos.items():
            expression_combo = self._click_expression_combos[region]
            current = actions.get(region, {})
            current_motion = current.get("motion", "")
            current_expression = current.get("expression", "")
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(_tr("SettingsWindow.click_motion_auto", default="智能匹配"), userData="")
            combo.addItem(_tr("SettingsWindow.click_motion_random", default="随机"), userData=CLICK_MOTION_RANDOM)
            combo.addItem(_tr("SettingsWindow.click_motion_none", default="不做反应"), userData=CLICK_MOTION_NONE)
            for motion in motions:
                combo.addItem(motion, userData=motion)
            for idx in range(combo.count()):
                if combo.itemData(idx) == current_motion:
                    combo.setCurrentIndex(idx)
                    break
            combo.blockSignals(False)

            expression_combo.blockSignals(True)
            expression_combo.clear()
            expression_combo.addItem(_tr("SettingsWindow.click_expression_default", default="默认"), userData="")
            for expression in expressions:
                expression_combo.addItem(expression, userData=expression)
            for idx in range(expression_combo.count()):
                if expression_combo.itemData(idx) == current_expression:
                    expression_combo.setCurrentIndex(idx)
                    break
            expression_combo.blockSignals(False)

    def _reload_click_motion_profiles(self, select_name: str = ""):
        from click_motion_presets import BUILTIN_CLICK_MOTION_PROFILES, BUILTIN_PROFILE_NAMES, preset_combo_label

        if not hasattr(self, "_click_motion_profile_combo"):
            return

        combo = self._click_motion_profile_combo
        current_name = select_name or combo.itemData(combo.currentIndex()) or ""

        combo.blockSignals(True)
        combo.clear()

        for preset in BUILTIN_CLICK_MOTION_PROFILES:
            label = preset_combo_label(preset, tr_func=_tr)
            combo.addItem(label, userData=preset["name"])

        custom_profiles = self._cfg.get_click_motion_profiles() if self._cfg else []
        for profile in custom_profiles:
            name = profile.get("name", "")
            if name and name not in BUILTIN_PROFILE_NAMES:
                combo.addItem(name, userData=name)

        selected_index = 0
        if current_name:
            for idx in range(combo.count()):
                if combo.itemData(idx) == current_name:
                    selected_index = idx
                    break
        combo.setCurrentIndex(selected_index)
        combo.blockSignals(False)

    def _on_click_motion_profile_selected(self, index: int):
        from click_motion_presets import BUILTIN_CLICK_MOTION_PROFILES, BUILTIN_PROFILE_NAMES, resolve_preset_to_actions

        if index < 0:
            return

        combo = self._click_motion_profile_combo
        name = combo.itemData(index) or ""

        item = self._selected_model_item()
        if not item:
            return

        if self._cfg:
            self._cfg.set_click_motion_active_profile(name)
            try:
                self._cfg.save()
            except Exception:
                pass

        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])

        if name in BUILTIN_PROFILE_NAMES:
            preset = next((p for p in BUILTIN_CLICK_MOTION_PROFILES if p["name"] == name), None)
            if preset:
                resolved = resolve_preset_to_actions(preset, motions, expressions, item["character"])
                item["click_motion_actions"] = resolved
                self._click_motion_profile_name.clear()
            else:
                self._click_motion_profile_name.clear()
                return
        elif name:
            self._click_motion_profile_name.setText(name)
            profiles = self._cfg.get_click_motion_profiles() if self._cfg else []
            profile = next((p for p in profiles if p.get("name") == name), None)
            if profile:
                actions = profile.get("click_motion_actions", {})
                item["click_motion_actions"] = normalize_click_motion_actions(actions, motions, expressions)
            else:
                return
        else:
            self._click_motion_profile_name.clear()
            return

        self._populate_click_motion_combos(item)
        if hasattr(self, "_click_motion_profile_name"):
            self._click_motion_profile_name.setText(name if name not in BUILTIN_PROFILE_NAMES else "")

    def _save_click_motion_profile(self):
        from click_motion_presets import BUILTIN_PROFILE_NAMES

        if not self._cfg:
            return

        name = self._click_motion_profile_name.text().strip()
        if not name:
            combo = self._click_motion_profile_combo
            current_data = combo.itemData(combo.currentIndex()) or ""
            if current_data and current_data not in BUILTIN_PROFILE_NAMES:
                name = current_data
        if not name:
            InfoBar.warning(
                _tr("SettingsWindow.click_motion_profile_name_required_title", default="需要名称"),
                _tr("SettingsWindow.click_motion_profile_name_required_content", default="请先填写档案名称。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if name in BUILTIN_PROFILE_NAMES:
            InfoBar.warning(
                _tr("SettingsWindow.click_motion_profile_name_reserved_title", default="名称冲突"),
                _tr("SettingsWindow.click_motion_profile_name_reserved_content", default="此名称已被内置预设使用，请换一个名称。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        item = self._selected_model_item()
        if not item:
            return

        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])
        actions = normalize_click_motion_actions(
            item.get("click_motion_actions", {}),
            motions,
            expressions,
        )

        self._cfg.save_click_motion_profile(name, actions)
        self._cfg.set_click_motion_active_profile(name)
        try:
            self._cfg.save()
            self._click_motion_profile_name.setText(name)
            self._reload_click_motion_profiles(select_name=name)
            InfoBar.success(
                _tr("SettingsWindow.click_motion_profile_saved_title", default="档案已保存"),
                _tr("SettingsWindow.click_motion_profile_saved_content", default="当前动作反馈配置已保存为档案。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception:
            pass

    def _delete_click_motion_profile(self):
        from click_motion_presets import BUILTIN_PROFILE_NAMES

        if not self._cfg:
            return

        combo = self._click_motion_profile_combo
        name = combo.itemData(combo.currentIndex()) or ""
        if not name or name in BUILTIN_PROFILE_NAMES:
            return

        self._cfg.delete_click_motion_profile(name)
        try:
            self._cfg.save()
            self._click_motion_profile_name.clear()
            self._reload_click_motion_profiles()
            InfoBar.success(
                _tr("SettingsWindow.click_motion_profile_deleted_title", default="档案已删除"),
                _tr("SettingsWindow.click_motion_profile_deleted_content", default="自定义档案已删除。"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception:
            pass

    def _apply_click_motion_profile(self):
        from click_motion_presets import BUILTIN_CLICK_MOTION_PROFILES, BUILTIN_PROFILE_NAMES, resolve_preset_to_actions

        scope = self._current_click_motion_scope()
        item = self._selected_model_item()
        if not item:
            return

        motions = self._model_manager.get_motion_names(item["character"], item["costume"])
        expressions = self._model_manager.get_expression_names(item["character"], item["costume"])
        actions = normalize_click_motion_actions(
            item.get("click_motion_actions", {}),
            motions,
            expressions,
        )

        profile_name = self._click_motion_profile_combo.itemData(
            self._click_motion_profile_combo.currentIndex()
        ) or ""

        if scope == CLICK_MOTION_SCOPE_ALL:
            for model_item in self._configured_models:
                char = model_item.get("character", "")
                cost = model_item.get("costume", "")
                if not char or not cost:
                    continue
                if profile_name in BUILTIN_PROFILE_NAMES and profile_name:
                    preset = next((p for p in BUILTIN_CLICK_MOTION_PROFILES if p["name"] == profile_name), None)
                    if preset:
                        char_motions = self._model_manager.get_motion_names(char, cost)
                        char_exprs = self._model_manager.get_expression_names(char, cost)
                        resolved = resolve_preset_to_actions(preset, char_motions, char_exprs, char)
                        model_item["click_motion_actions"] = resolved
                else:
                    model_item["click_motion_actions"] = dict(actions)
        elif scope == CLICK_MOTION_SCOPE_CHARACTER:
            for model_item in self._configured_models:
                if model_item.get("character") != item["character"]:
                    continue
                model_item["click_motion_actions"] = dict(actions)
        else:
            item["click_motion_actions"] = dict(actions)

        self._save_configured_models()
        InfoBar.success(
            _tr("SettingsWindow.click_motion_applied_title", default="已应用"),
            _tr("SettingsWindow.click_motion_applied_content", default="动作反馈配置已应用。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_default_motion_preview(self, index: int):
        motion = self._default_motion_combo.itemData(index) or ""
        if motion in CLICK_MOTION_SPECIAL_VALUES or not motion:
            return
        self._send_preview_motion(motion, "")

    def _on_default_expression_preview(self, index: int):
        expression = self._default_expression_combo.itemData(index) or ""
        if not expression:
            return
        self._send_preview_motion("", expression)

    def _on_click_combo_preview(self, region: str, combo, index: int):
        motion = combo.itemData(index) or ""
        if motion in CLICK_MOTION_SPECIAL_VALUES or not motion:
            return
        self._send_preview_motion(motion, "")

    def _on_expression_combo_preview(self, region: str, combo, index: int):
        expression = combo.itemData(index) or ""
        if not expression:
            return
        self._send_preview_motion("", expression)

    def _send_preview_motion(self, motion: str, expression: str):
        if not self._ipc_output:
            return
        character = (self._selected_model_item() or {}).get("character", "")
        if not character:
            return
        if motion and motion in CLICK_MOTION_SPECIAL_VALUES:
            motion = ""
        line = f"PREVIEW_MOTION\t{character}\t{motion}\t{expression}"
        self._ipc_output(line)

    def _on_click_motion_changed(self, region: str, index: int):
        item = self._selected_model_item()
        if not item:
            return
        combo = self._click_motion_combos.get(region)
        if combo is None:
            return
        actions = normalize_click_motion_actions(item.get("click_motion_actions", {}))
        value = combo.itemData(index) or ""
        current = dict(actions.get(region, {}))
        if value:
            current["motion"] = value
            if value == CLICK_MOTION_NONE:
                current["expression"] = ""
                expression_combo = self._click_expression_combos.get(region)
                if expression_combo is not None:
                    expression_combo.blockSignals(True)
                    expression_combo.setCurrentIndex(0)
                    expression_combo.blockSignals(False)
            actions[region] = current
        else:
            current["motion"] = ""
            if current.get("expression"):
                actions[region] = current
            else:
                actions.pop(region, None)
        item["click_motion_actions"] = actions
        self._save_configured_models()

    def _on_click_expression_changed(self, region: str, index: int):
        item = self._selected_model_item()
        if not item:
            return
        combo = self._click_expression_combos.get(region)
        if combo is None:
            return
        actions = normalize_click_motion_actions(item.get("click_motion_actions", {}))
        value = combo.itemData(index) or ""
        current = dict(actions.get(region, {}))
        if value:
            current["expression"] = value
            actions[region] = current
        else:
            current["expression"] = ""
            if current.get("motion"):
                actions[region] = current
            else:
                actions.pop(region, None)
        item["click_motion_actions"] = actions
        self._save_configured_models()

    def _reset_click_motions(self):
        item = self._selected_model_item()
        if not item:
            return
        item["click_motion_actions"] = {}
        self._populate_click_motion_combos(item)
        self._save_configured_models()

    def _current_click_motion_scope(self) -> str:
        if not hasattr(self, "_click_motion_scope_combo"):
            return CLICK_MOTION_SCOPE_COSTUME
        scope = self._click_motion_scope_combo.itemData(
            self._click_motion_scope_combo.currentIndex()
        )
        return scope if scope in CLICK_MOTION_SCOPES else CLICK_MOTION_SCOPE_COSTUME

    def _build_behavior_switch_row(
        self,
        parent: QWidget,
        title_key: str,
        hint_key: str,
        switch_attr: str,
        checked: bool,
        handler,
        enabled: bool = True,
    ):
        row_widget = QWidget(parent)
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)

        switch_row = QHBoxLayout()
        switch_row.setContentsMargins(0, 0, 0, 0)
        switch_row.setSpacing(12)
        label = StrongBodyLabel(_tr(title_key), row_widget)
        switch = SwitchButton(row_widget)
        switch.setChecked(bool(checked))
        switch.setEnabled(bool(enabled))
        switch.checkedChanged.connect(handler)
        setattr(self, switch_attr, switch)
        switch_row.addWidget(label, 1)
        switch_row.addWidget(switch, 0, Qt.AlignmentFlag.AlignRight)
        row_layout.addLayout(switch_row)

        hint = BodyLabel(_tr(hint_key), row_widget)
        hint.setWordWrap(True)
        row_layout.addWidget(hint)
        return row_widget

    def _build_behavior_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.behavior_title", default="角色行为"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr(
            "SettingsWindow.behavior_subtitle",
            default="设置角色的待机动作、视线跟随和多角色互动行为。",
        ), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        section = StrongBodyLabel(_tr("SettingsWindow.behavior_live2d_section", default="Live2D 行为"), page)
        layout.addWidget(section)

        layout.addWidget(self._build_behavior_switch_row(
            page,
            "SettingsWindow.live2d_idle_actions",
            "SettingsWindow.live2d_idle_actions_hint",
            "_behavior_idle_actions_switch",
            self._live2d_idle_actions_enabled,
            self._on_live2d_idle_actions_changed,
        ))
        layout.addWidget(self._build_behavior_switch_row(
            page,
            "SettingsWindow.live2d_head_tracking",
            "SettingsWindow.live2d_head_tracking_hint",
            "_behavior_head_tracking_switch",
            self._live2d_head_tracking_enabled,
            self._on_live2d_head_tracking_changed,
            enabled=not self._live2d_mutual_gaze_enabled,
        ))
        layout.addWidget(self._build_behavior_switch_row(
            page,
            "SettingsWindow.live2d_mutual_gaze",
            "SettingsWindow.live2d_mutual_gaze_hint",
            "_behavior_mutual_gaze_switch",
            self._live2d_mutual_gaze_enabled,
            self._on_live2d_mutual_gaze_changed,
        ))

        note = BodyLabel(_tr(
            "SettingsWindow.behavior_apply_hint",
            default="这些选项会保存为全局设置；点击右侧应用后，当前桌宠会立即刷新。",
        ), page)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        self._sync_live2d_behavior_switches()
        return page
