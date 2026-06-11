from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


SCREEN_AWARENESS_CONFIG_KEYS = (
    "screen_awareness_enabled",
    "screen_awareness_interval_minutes",
    "screen_awareness_character_mode",
    "screen_awareness_character",
    "screen_awareness_max_screenshot_width",
    "screen_awareness_model_mode",
    SCREEN_AWARENESS_DISPLAY_MODE_KEY,
    "screen_awareness_include_process_name",
    "screen_awareness_include_window_title",
)


class ScreenAwarenessPageMixin:
    def _build_screen_awareness_section(self, parent: QWidget) -> QWidget:
        screen_panel = QWidget(parent)
        screen_panel.setObjectName("screenAwarenessPanel")
        screen_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        screen_layout = QVBoxLayout(screen_panel)
        screen_layout.setContentsMargins(16, 14, 16, 14)
        screen_layout.setSpacing(10)

        screen_header = QHBoxLayout()
        screen_header.setContentsMargins(0, 0, 0, 0)
        screen_title_col = QVBoxLayout()
        screen_title_col.setContentsMargins(0, 0, 0, 0)
        screen_title_col.setSpacing(2)
        screen_title_col.addWidget(StrongBodyLabel(_tr("SettingsWindow.screen_awareness_title", default="屏幕感知主动搭话"), screen_panel))
        screen_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.screen_awareness_hint",
            default="主模型可以直接看屏幕，也可以先由辅助模型读取内容，再交给主模型自然搭话。",
        ), screen_panel))
        screen_hint.setObjectName("screenAwarenessHint")
        screen_title_col.addWidget(screen_hint)
        screen_header.addLayout(screen_title_col, 1)
        self._screen_awareness_enabled = SwitchButton(screen_panel)
        screen_header.addWidget(self._screen_awareness_enabled)
        screen_layout.addLayout(screen_header)

        screen_form = QGridLayout()
        screen_form.setHorizontalSpacing(10)
        screen_form.setVerticalSpacing(8)
        screen_form.addWidget(BodyLabel(_tr("SettingsWindow.screen_awareness_interval", default="触发频率"), screen_panel), 0, 0)
        self._screen_awareness_interval = SpinBox(screen_panel)
        self._screen_awareness_interval.setRange(1, 120)
        self._screen_awareness_interval.setValue(30)
        self._screen_awareness_interval.setSuffix(_tr("SettingsWindow.proactive_minutes_suffix", default=" 分钟"))
        self._screen_awareness_interval.setFixedHeight(34)
        screen_form.addWidget(self._screen_awareness_interval, 0, 1)

        screen_form.addWidget(BodyLabel(_tr("SettingsWindow.screen_awareness_speaker", default="说话角色"), screen_panel), 0, 2)
        self._screen_awareness_character = OpaqueDropDownComboBox(screen_panel)
        self._screen_awareness_character.setFixedHeight(34)
        screen_form.addWidget(self._screen_awareness_character, 0, 3)

        screen_form.addWidget(BodyLabel(_tr("SettingsWindow.screen_awareness_max_width", default="截图最长边"), screen_panel), 1, 0)
        self._screen_awareness_max_width = SpinBox(screen_panel)
        self._screen_awareness_max_width.setRange(640, 1920)
        self._screen_awareness_max_width.setSingleStep(160)
        self._screen_awareness_max_width.setValue(1920)
        self._screen_awareness_max_width.setFixedHeight(34)
        screen_form.addWidget(self._screen_awareness_max_width, 1, 1)

        screen_form.addWidget(BodyLabel(_tr("SettingsWindow.screen_awareness_model_mode", default="屏幕读取方式"), screen_panel), 1, 2)
        self._screen_awareness_model_mode = OpaqueDropDownComboBox(screen_panel)
        self._screen_awareness_model_mode.addItem(
            _tr("SettingsWindow.screen_awareness_model_mode_main", default="主模型直接识别"),
            userData="main",
        )
        self._screen_awareness_model_mode.addItem(
            _tr("SettingsWindow.screen_awareness_model_mode_aux", default="辅助模型读取后交给主模型"),
            userData="aux",
        )
        self._screen_awareness_model_mode.setFixedHeight(34)
        screen_form.addWidget(self._screen_awareness_model_mode, 1, 3)

        screen_form.addWidget(BodyLabel(_tr(
            "SettingsWindow.screen_awareness_display_mode",
            default="提醒展示方式",
        ), screen_panel), 2, 0)
        self._screen_awareness_display_mode = OpaqueDropDownComboBox(screen_panel)
        self._screen_awareness_display_mode.addItem(
            _tr("SettingsWindow.reminder_display_floating", default="悬浮窗显示"),
            userData=DISPLAY_MODE_FLOATING,
        )
        self._screen_awareness_display_mode.addItem(
            _tr("SettingsWindow.reminder_display_system", default="系统通知提醒"),
            userData=DISPLAY_MODE_SYSTEM,
        )
        self._screen_awareness_display_mode.setFixedHeight(34)
        screen_form.addWidget(self._screen_awareness_display_mode, 2, 1)

        screen_form.addWidget(BodyLabel(_tr(
            "SettingsWindow.screen_awareness_include_process_name",
            default="???????",
        ), screen_panel), 3, 0)
        self._screen_awareness_include_process_name = SwitchButton(screen_panel)
        screen_form.addWidget(self._screen_awareness_include_process_name, 3, 1)

        screen_form.addWidget(BodyLabel(_tr(
            "SettingsWindow.screen_awareness_include_window_title",
            default="??????",
        ), screen_panel), 3, 2)
        self._screen_awareness_include_window_title = SwitchButton(screen_panel)
        screen_form.addWidget(self._screen_awareness_include_window_title, 3, 3)

        test_screen_btn = PushButton(FluentIcon.PLAY, _tr("SettingsWindow.screen_awareness_test", default="立即测试"), screen_panel)
        test_screen_btn.setFixedHeight(34)
        test_screen_btn.clicked.connect(self._test_screen_awareness_now)
        save_screen_btn = PushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), screen_panel)
        save_screen_btn.setFixedHeight(34)
        save_screen_btn.clicked.connect(lambda: self._save_screen_awareness_config(show_info=True, emit_update=True))
        screen_form.addWidget(test_screen_btn, 4, 2)
        screen_form.addWidget(save_screen_btn, 4, 3)
        screen_layout.addLayout(screen_form)

        self._load_screen_awareness_controls()
        return screen_panel

    def _apply_screen_awareness_remote_settings(self, data: dict):
        if not isinstance(data, dict) or not self._cfg:
            return
        if not any(key in data for key in SCREEN_AWARENESS_CONFIG_KEYS):
            return
        for key in SCREEN_AWARENESS_CONFIG_KEYS:
            if key in data:
                self._cfg.set(key, data.get(key))
        self._load_screen_awareness_controls()

    def _fill_screen_awareness_character_combo(self, mode: str = "random_visible", selected: str = ""):
        combo = self._screen_awareness_character
        combo.clear()
        combo.addItem(_tr("SettingsWindow.screen_awareness_speaker_random", default="随机当前显示角色"), userData="__random_visible__")
        combo.addItem(_tr("SettingsWindow.screen_awareness_speaker_default", default="默认提醒角色"), userData="__default__")
        for character in self._reminder_characters():
            combo.addItem(self._model_manager.get_display_name(character), userData=character)
        target = "__random_visible__" if mode == "random_visible" else "__default__" if mode == "default" else selected
        for index in range(combo.count()):
            if combo.itemData(index) == target:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def _selected_screen_awareness_character(self) -> tuple[str, str]:
        if not hasattr(self, "_screen_awareness_character") or self._screen_awareness_character.count() <= 0:
            return "random_visible", ""
        value = str(self._screen_awareness_character.itemData(self._screen_awareness_character.currentIndex()) or "").strip()
        if value == "__random_visible__":
            return "random_visible", ""
        if value == "__default__":
            return "default", ""
        return "fixed", value

    def _selected_screen_awareness_model_mode(self) -> str:
        if not hasattr(self, "_screen_awareness_model_mode"):
            return "main"
        mode = str(self._screen_awareness_model_mode.currentData() or "main").strip()
        return "aux" if mode == "aux" else "main"

    def _set_screen_awareness_model_mode(self, mode):
        target = "aux" if str(mode or "").strip() == "aux" else "main"
        for index in range(self._screen_awareness_model_mode.count()):
            if self._screen_awareness_model_mode.itemData(index) == target:
                self._screen_awareness_model_mode.setCurrentIndex(index)
                return
        self._screen_awareness_model_mode.setCurrentIndex(0)

    def _set_screen_awareness_display_mode(self, mode):
        target = normalize_display_mode(mode)
        for index in range(self._screen_awareness_display_mode.count()):
            if self._screen_awareness_display_mode.itemData(index) == target:
                self._screen_awareness_display_mode.setCurrentIndex(index)
                return
        self._screen_awareness_display_mode.setCurrentIndex(0)

    def _load_screen_awareness_controls(self):
        if not self._cfg or not hasattr(self, "_screen_awareness_enabled"):
            return
        self._screen_awareness_enabled.setChecked(bool(self._cfg.get("screen_awareness_enabled", False)))
        self._screen_awareness_interval.setValue(max(1, min(120, int(self._cfg.get("screen_awareness_interval_minutes", 30) or 30))))
        self._fill_screen_awareness_character_combo(
            str(self._cfg.get("screen_awareness_character_mode", "random_visible") or "random_visible"),
            self._cfg.get("screen_awareness_character", ""),
        )
        self._screen_awareness_max_width.setValue(max(640, min(1920, int(self._cfg.get("screen_awareness_max_screenshot_width", 1920) or 1920))))
        self._set_screen_awareness_model_mode(self._cfg.get("screen_awareness_model_mode", "main"))
        self._set_screen_awareness_display_mode(
            self._cfg.get(SCREEN_AWARENESS_DISPLAY_MODE_KEY, DISPLAY_MODE_FLOATING)
        )
        if hasattr(self, "_screen_awareness_include_process_name"):
            self._screen_awareness_include_process_name.setChecked(
                bool(self._cfg.get("screen_awareness_include_process_name", True))
            )
        if hasattr(self, "_screen_awareness_include_window_title"):
            self._screen_awareness_include_window_title.setChecked(
                bool(self._cfg.get("screen_awareness_include_window_title", False))
            )

    def _sync_screen_awareness_config_from_ui(self):
        if not self._cfg or not hasattr(self, "_screen_awareness_enabled"):
            return
        self._cfg.set("screen_awareness_enabled", bool(self._screen_awareness_enabled.isChecked()))
        self._cfg.set("screen_awareness_interval_minutes", int(self._screen_awareness_interval.value()))
        mode, character = self._selected_screen_awareness_character()
        self._cfg.set("screen_awareness_character_mode", mode)
        self._cfg.set("screen_awareness_character", character)
        self._cfg.set("screen_awareness_max_screenshot_width", int(self._screen_awareness_max_width.value()))
        self._cfg.set("screen_awareness_model_mode", self._selected_screen_awareness_model_mode())
        display_mode = self._screen_awareness_display_mode.currentData() or DISPLAY_MODE_FLOATING
        self._cfg.set(SCREEN_AWARENESS_DISPLAY_MODE_KEY, normalize_display_mode(display_mode))
        if hasattr(self, "_screen_awareness_include_process_name"):
            self._cfg.set(
                "screen_awareness_include_process_name",
                bool(self._screen_awareness_include_process_name.isChecked()),
            )
        if hasattr(self, "_screen_awareness_include_window_title"):
            self._cfg.set(
                "screen_awareness_include_window_title",
                bool(self._screen_awareness_include_window_title.isChecked()),
            )

    def _screen_awareness_settings_data(self) -> dict:
        if self._cfg:
            return {
                "screen_awareness_enabled": bool(self._cfg.get("screen_awareness_enabled", False)),
                "screen_awareness_interval_minutes": int(self._cfg.get("screen_awareness_interval_minutes", 30) or 30),
                "screen_awareness_character_mode": str(self._cfg.get("screen_awareness_character_mode", "random_visible") or "random_visible"),
                "screen_awareness_character": str(self._cfg.get("screen_awareness_character", "") or ""),
                "screen_awareness_max_screenshot_width": int(self._cfg.get("screen_awareness_max_screenshot_width", 1920) or 1920),
                "screen_awareness_model_mode": str(self._cfg.get("screen_awareness_model_mode", "main") or "main"),
                "screen_awareness_include_process_name": bool(self._cfg.get("screen_awareness_include_process_name", True)),
                "screen_awareness_include_window_title": bool(self._cfg.get("screen_awareness_include_window_title", False)),
                SCREEN_AWARENESS_DISPLAY_MODE_KEY: normalize_display_mode(
                    self._cfg.get(SCREEN_AWARENESS_DISPLAY_MODE_KEY, DISPLAY_MODE_FLOATING)
                ),
            }
        return {
            "screen_awareness_enabled": False,
            "screen_awareness_interval_minutes": 30,
            "screen_awareness_character_mode": "random_visible",
            "screen_awareness_character": "",
            "screen_awareness_max_screenshot_width": 1920,
            "screen_awareness_model_mode": "main",
            "screen_awareness_include_process_name": True,
            "screen_awareness_include_window_title": False,
            SCREEN_AWARENESS_DISPLAY_MODE_KEY: DISPLAY_MODE_FLOATING,
        }

    def _save_screen_awareness_config(self, show_info: bool = True, emit_update: bool = True):
        if not self._cfg or not hasattr(self, "_screen_awareness_enabled"):
            return False
        self._sync_screen_awareness_config_from_ui()
        try:
            self._cfg.save()
            if emit_update:
                self.settings_changed.emit(self._screen_awareness_settings_data())
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.screen_awareness_saved_title", default="屏幕感知设置已保存"),
                    _tr("SettingsWindow.screen_awareness_saved_content", default="屏幕观察和主动搭话设置已更新。"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            return True
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.screen_awareness_failed_title", default="屏幕感知设置保存失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return False

    def _test_screen_awareness_now(self):
        if not self._cfg or not hasattr(self, "_screen_awareness_enabled"):
            return
        if not self._screen_awareness_enabled.isChecked():
            InfoBar.warning(
                _tr("SettingsWindow.screen_awareness_test_disabled_title", default="请先开启屏幕感知"),
                _tr("SettingsWindow.screen_awareness_test_disabled_content", default="开启后才能立即执行一次截图分析测试。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._sync_screen_awareness_config_from_ui()
        try:
            self._cfg.save()
            data = self._screen_awareness_settings_data()
            data["screen_awareness_test_requested"] = True
            self.settings_changed.emit(data)
            InfoBar.success(
                _tr("SettingsWindow.screen_awareness_test_sent_title", default="已发送测试请求"),
                _tr("SettingsWindow.screen_awareness_test_sent_content", default="主程序会立即截屏并按所选方式调用模型；如果主模型判断不必打扰，可能不会弹出消息。"),
                duration=3500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.screen_awareness_failed_title", default="屏幕感知设置保存失败"),
                str(exc),
                duration=4000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
