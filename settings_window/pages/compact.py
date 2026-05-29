from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class CompactPageMixin:

    def _build_compact_window_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.compact_window_title"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr("SettingsWindow.compact_window_subtitle"), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        enabled_row = QHBoxLayout()
        enabled_row.setContentsMargins(0, 0, 0, 0)
        enabled_label = BodyLabel(_tr("SettingsWindow.compact_ai_window"), page)
        self._compact_ai_window_enabled = SwitchButton(page)
        enabled_row.addWidget(enabled_label)
        enabled_row.addStretch()
        enabled_row.addWidget(self._compact_ai_window_enabled)
        layout.addLayout(enabled_row)

        ai_event_row = QHBoxLayout()
        ai_event_row.setContentsMargins(0, 0, 0, 0)
        ai_event_label = BodyLabel(_tr("SettingsWindow.ai_event_overlay"), page)
        self._ai_event_overlay_enabled = SwitchButton(page)
        ai_event_row.addWidget(ai_event_label)
        ai_event_row.addStretch()
        ai_event_row.addWidget(self._ai_event_overlay_enabled)
        layout.addLayout(ai_event_row)

        self._compact_hint_labels = []

        ai_event_hint = BodyLabel(_tr("SettingsWindow.ai_event_overlay_hint"), page)
        ai_event_hint.setWordWrap(True)
        self._compact_hint_labels.append(ai_event_hint)
        layout.addWidget(ai_event_hint)

        port_row = QHBoxLayout()
        port_row.setContentsMargins(0, 0, 0, 0)
        self._ai_status_port_enabled = SwitchButton(page)
        port_label = BodyLabel(_tr("SettingsWindow.ai_status_port"), page)
        port_row.addWidget(port_label)
        port_row.addStretch()
        port_row.addWidget(self._ai_status_port_enabled)
        layout.addLayout(port_row)

        port_input_row = QHBoxLayout()
        port_input_row.setContentsMargins(0, 0, 0, 0)
        port_input_row.setSpacing(8)
        self._ai_status_port_input = LineEdit(page)
        self._ai_status_port_input.setFixedWidth(120)
        self._ai_status_port_input.setFixedHeight(36)
        self._ai_status_port_input.setValidator(QIntValidator(1024, 65535, self))
        self._ai_status_port_input.setPlaceholderText("38472")
        token_label = BodyLabel(_tr("SettingsWindow.ai_status_token"), page)
        self._ai_status_token_input = LineEdit(page)
        self._ai_status_token_input.setFixedHeight(36)
        self._ai_status_token_input.setPlaceholderText(_tr("SettingsWindow.ai_status_token_placeholder"))
        port_input_row.addWidget(BodyLabel(_tr("SettingsWindow.ai_status_port_number"), page))
        port_input_row.addWidget(self._ai_status_port_input)
        port_input_row.addSpacing(12)
        port_input_row.addWidget(token_label)
        port_input_row.addWidget(self._ai_status_token_input, 1)
        layout.addLayout(port_input_row)

        port_hint = BodyLabel(_tr("SettingsWindow.ai_status_port_hint"), page)
        port_hint.setWordWrap(True)
        self._compact_hint_labels.append(port_hint)
        layout.addWidget(port_hint)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.compact_commands_title", default="悬浮窗 @ 命令"), page))
        compact_commands = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.compact_commands_hint",
            default="@clear：清空悬浮窗输出；@stop / @停止 / @中断：中断当前悬浮窗回复。",
        ), page))
        self._compact_hint_labels.append(compact_commands)
        layout.addWidget(compact_commands)

        opacity_label = BodyLabel(_tr("SettingsWindow.compact_window_opacity"), page)
        layout.addWidget(opacity_label)
        self._compact_window_opacity_slider = Slider(Qt.Orientation.Horizontal, page)
        self._compact_window_opacity_slider.setRange(15, 100)
        self._compact_window_opacity_slider.setSingleStep(5)
        self._compact_window_opacity_value = BodyLabel("", page)
        self._compact_window_opacity_slider.valueChanged.connect(
            lambda v: self._compact_window_opacity_value.setText(_tr("SettingsWindow.opacity_value", v=v))
        )
        layout.addWidget(self._compact_window_opacity_slider)
        layout.addWidget(self._compact_window_opacity_value)

        font_label = BodyLabel(_tr("SettingsWindow.compact_window_font_size"), page)
        layout.addWidget(font_label)
        self._compact_window_font_size_slider = Slider(Qt.Orientation.Horizontal, page)
        self._compact_window_font_size_slider.setRange(9, 22)
        self._compact_window_font_size_slider.setSingleStep(1)
        self._compact_window_font_size_value = BodyLabel("", page)
        self._compact_window_font_size_slider.valueChanged.connect(
            lambda v: self._compact_window_font_size_value.setText(f"{v}px")
        )
        font_hint = BodyLabel(_tr("SettingsWindow.compact_window_font_hint"), page)
        font_hint.setWordWrap(True)
        self._compact_hint_labels.append(font_hint)
        layout.addWidget(self._compact_window_font_size_slider)
        layout.addWidget(self._compact_window_font_size_value)
        layout.addWidget(font_hint)

        bg_label = BodyLabel(_tr("SettingsWindow.compact_window_bg_color"), page)
        layout.addWidget(bg_label)
        self._compact_bg_color_btns = self._build_compact_color_row(
            page,
            [
                (BANDORI_PRIMARY, "Bandori"),
                ("#e91e63", _tr("color.pink")),
                ("#9c27b0", _tr("color.purple")),
                ("#4caf50", _tr("color.green")),
                ("#ff9800", _tr("color.orange")),
                ("#f44336", _tr("color.red")),
                ("#00bcd4", _tr("color.cyan")),
                ("#607d8b", _tr("color.grey")),
                ("#ffffff", "White"),
            ],
            "compact_color",
        )
        layout.addLayout(self._compact_bg_color_row)

        text_label = BodyLabel(_tr("SettingsWindow.compact_window_text_color"), page)
        layout.addWidget(text_label)
        self._compact_text_color_btns = self._build_compact_color_row(
            page,
            [
                ("#24242a", "Ink"),
                ("#ffffff", "White"),
                ("#000000", "Black"),
                ("#5b3150", "Berry"),
                ("#254a6a", "Blue"),
                ("#315c3b", "Green"),
                ("#704b12", "Gold"),
            ],
            "compact_color",
        )
        layout.addLayout(self._compact_text_color_row)

        layout.addStretch()

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_compact_window_config)
        reset_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.compact_window_reset"), page)
        reset_btn.setFixedHeight(36)
        reset_btn.clicked.connect(self._reset_compact_window_config)
        hint = BodyLabel(_tr("SettingsWindow.compact_window_apply_hint"), page)
        hint.setWordWrap(True)
        self._compact_hint_labels.append(hint)
        btn_row = QHBoxLayout()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addWidget(hint, 1)
        layout.addLayout(btn_row)

        self._load_compact_window_config()
        self._style_compact_controls()
        qconfig.themeChanged.connect(self._style_compact_controls)
        return page

    def _build_compact_color_row(self, page: QWidget, colors: list[tuple[str, str]], prop_name: str) -> list[QPushButton]:
        row = QHBoxLayout()
        row.setSpacing(6)
        btns: list[QPushButton] = []
        for color_hex, color_name in colors:
            btn = PushButton("", page)
            btn.setFixedSize(32, 32)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color_name)
            btn.setProperty(prop_name, color_hex)
            btn.clicked.connect(lambda checked, buttons=btns, b=btn: self._on_compact_color_clicked(buttons, b))
            btns.append(btn)
            row.addWidget(btn)
        row.addStretch()
        if not hasattr(self, "_compact_bg_color_row"):
            self._compact_bg_color_row = row
        else:
            self._compact_text_color_row = row
        return btns

    def _on_compact_color_clicked(self, buttons: list[QPushButton], btn: QPushButton):
        for b in buttons:
            b.setChecked(False)
        btn.setChecked(True)
        self._style_compact_color_buttons(buttons)
        self._pulse_button(btn)

    def _style_compact_color_buttons(self, buttons: list[QPushButton]):
        dark = isDarkTheme()
        checked_border = accent_color(dark)
        idle_border = "#4a4a4a" if dark else "#d7d7d7"
        hover_border = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        for btn in buttons:
            color = btn.property("compact_color")
            checked = btn.isChecked()
            btn.setText("\u2713" if checked else "")
            btn.setFixedSize(32, 32)
            border = f"2px solid {checked_border}" if checked else f"1px solid {idle_border}"
            text_color = "#111111" if QColor(color).lightness() > 170 else "#ffffff"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: {border};
                    border-radius: 6px;
                    color: {text_color};
                    font-weight: 900;
                    font-size: 14px;
                    padding: 0px;
                }}
                QPushButton:hover {{
                    border: 2px solid {hover_border};
                }}
            """)

    def _style_compact_controls(self):
        if not self._compact_config_widgets_ready():
            return
        muted = "#a0a7b7" if isDarkTheme() else "#6b7280"
        for label in getattr(self, "_compact_hint_labels", []):
            label.setStyleSheet(f"color: {muted}; font-size: 13px;")
        self._style_compact_color_buttons(self._compact_bg_color_btns)
        self._style_compact_color_buttons(self._compact_text_color_btns)

    def _compact_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_compact_ai_window_enabled",
                "_ai_event_overlay_enabled",
                "_ai_status_port_enabled",
                "_ai_status_port_input",
                "_ai_status_token_input",
                "_compact_window_opacity_slider",
                "_compact_window_opacity_value",
                "_compact_window_font_size_slider",
                "_compact_window_font_size_value",
                "_compact_bg_color_btns",
                "_compact_text_color_btns",
            )
        )

    @staticmethod
    def _selected_compact_color(buttons: list[QPushButton], fallback: str) -> str:
        for btn in buttons:
            if btn.isChecked():
                return btn.property("compact_color")
        return fallback

    @staticmethod
    def _set_compact_color_selection(buttons: list[QPushButton], color: str):
        normalized = QColor(color).name().lower() if QColor(color).isValid() else ""
        selected = False
        for btn in buttons:
            btn_color = QColor(btn.property("compact_color")).name().lower()
            checked = bool(normalized and btn_color == normalized)
            btn.setChecked(checked)
            selected = selected or checked
        if not selected and buttons:
            buttons[0].setChecked(True)

    def _load_compact_window_config(self):
        if not self._cfg or not self._compact_config_widgets_ready():
            return
        self._compact_ai_window_enabled.setChecked(bool(self._cfg.get("compact_ai_window_enabled", False)))
        self._ai_event_overlay_enabled.setChecked(bool(self._cfg.get("ai_event_overlay_enabled", False)))
        self._ai_status_port_enabled.setChecked(bool(self._cfg.get("ai_status_port_enabled", False)))
        self._ai_status_port_input.setText(str(self._clamp_ai_status_port(self._cfg.get("ai_status_port", 38472))))
        self._ai_status_token_input.setText(str(self._cfg.get("ai_status_token", "") or ""))
        opacity = self._cfg.get("compact_ai_window_opacity", 44)
        try:
            opacity = int(opacity)
        except (TypeError, ValueError):
            opacity = 44
        opacity = max(15, min(100, opacity))
        self._compact_window_opacity_slider.setValue(opacity)
        self._compact_window_opacity_value.setText(_tr("SettingsWindow.opacity_value", v=opacity))
        font_size = self._cfg.get("compact_ai_window_font_size", 12)
        try:
            font_size = int(font_size)
        except (TypeError, ValueError):
            font_size = 12
        font_size = max(9, min(22, font_size))
        self._compact_window_font_size_slider.setValue(font_size)
        self._compact_window_font_size_value.setText(f"{font_size}px")
        bg_color = self._cfg.get("compact_ai_window_background_color", "") or self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
        text_color = self._cfg.get("compact_ai_window_text_color", "#24242a")
        self._set_compact_color_selection(self._compact_bg_color_btns, bg_color)
        self._set_compact_color_selection(self._compact_text_color_btns, text_color)
        self._style_compact_color_buttons(self._compact_bg_color_btns)
        self._style_compact_color_buttons(self._compact_text_color_btns)

    def _compact_window_settings_data(self) -> dict:
        if not self._cfg:
            return {}
        data = {
            "compact_ai_window_enabled": self._cfg.get("compact_ai_window_enabled", False),
            "compact_ai_window_opacity": self._cfg.get("compact_ai_window_opacity", 44),
            "compact_ai_window_font_size": self._cfg.get("compact_ai_window_font_size", 12),
            "compact_ai_window_background_color": self._cfg.get("compact_ai_window_background_color", ""),
            "compact_ai_window_text_color": self._cfg.get("compact_ai_window_text_color", "#24242a"),
            "ai_event_overlay_enabled": self._cfg.get("ai_event_overlay_enabled", False),
            "ai_status_port_enabled": self._cfg.get("ai_status_port_enabled", False),
            "ai_status_port": self._clamp_ai_status_port(self._cfg.get("ai_status_port", 38472)),
            "ai_status_token": self._cfg.get("ai_status_token", ""),
        }
        if self._compact_window_reset_position_pending:
            data["compact_ai_window_reset_position"] = True
        return data

    def _save_compact_window_config(self, show_info: bool = True, emit_update: bool = False):
        if not self._cfg or not self._compact_config_widgets_ready():
            return
        self._cfg.set("compact_ai_window_enabled", self._compact_ai_window_enabled.isChecked())
        self._cfg.set("compact_ai_window_opacity", self._compact_window_opacity_slider.value())
        self._cfg.set("compact_ai_window_font_size", self._compact_window_font_size_slider.value())
        self._cfg.set("compact_ai_window_background_color", self._selected_compact_color(self._compact_bg_color_btns, BANDORI_PRIMARY))
        self._cfg.set("compact_ai_window_text_color", self._selected_compact_color(self._compact_text_color_btns, "#24242a"))
        self._cfg.set("ai_event_overlay_enabled", self._ai_event_overlay_enabled.isChecked())
        self._cfg.set("ai_status_port_enabled", self._ai_status_port_enabled.isChecked())
        self._cfg.set("ai_status_port", self._clamp_ai_status_port(self._ai_status_port_input.text()))
        self._cfg.set("ai_status_token", self._ai_status_token_input.text().strip())
        try:
            self._cfg.save()
            if emit_update:
                self.settings_changed.emit(self._compact_window_settings_data())
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.compact_window_saved_title"),
                    _tr("SettingsWindow.compact_window_saved_content"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
        except Exception:
            pass

    def _reset_compact_window_config(self):
        if not self._cfg or not self._compact_config_widgets_ready():
            return
        avatar_color = self._cfg.get("user_avatar_color", BANDORI_PRIMARY)
        self._compact_window_opacity_slider.setValue(44)
        self._compact_window_opacity_value.setText(_tr("SettingsWindow.opacity_value", v=44))
        self._set_compact_color_selection(self._compact_bg_color_btns, avatar_color)
        self._set_compact_color_selection(self._compact_text_color_btns, "#24242a")
        self._style_compact_color_buttons(self._compact_bg_color_btns)
        self._style_compact_color_buttons(self._compact_text_color_btns)
        self._compact_window_reset_position_pending = True
