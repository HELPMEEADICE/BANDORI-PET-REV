from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class ASRPageMixin:

    def _build_asr_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.asr_title", default="聊天 ASR 语音输入"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.asr_subtitle",
            default="配置聊天输入框的语音识别接口、语言和识别后的输入行为。",
        ), page))
        layout.addWidget(subtitle)

        asr_enable_row = QHBoxLayout()
        asr_enable_row.setContentsMargins(0, 0, 0, 0)
        asr_enable_label = BodyLabel(_tr("SettingsWindow.asr_enabled", default="启用聊天语音输入"), page)
        self._asr_enabled = SwitchButton(page)
        asr_enable_row.addWidget(asr_enable_label)
        asr_enable_row.addStretch()
        asr_enable_row.addWidget(self._asr_enabled)
        layout.addLayout(asr_enable_row)

        asr_api_label = BodyLabel(_tr("SettingsWindow.asr_api_url", default="ASR API 地址"), page)
        layout.addWidget(asr_api_label)
        self._asr_api_url = FluentContextLineEdit(page)
        self._asr_api_url.setPlaceholderText("http://127.0.0.1:8000/v1/audio/transcriptions")
        self._asr_api_url.setFixedHeight(36)
        layout.addWidget(self._asr_api_url)

        asr_key_label = BodyLabel(_tr("SettingsWindow.asr_api_key", default="ASR API Key"), page)
        layout.addWidget(asr_key_label)
        self._asr_api_key = FluentContextLineEdit(page)
        self._asr_api_key.setPlaceholderText(_tr("SettingsWindow.asr_api_key_placeholder", default="本地服务可留空"))
        self._asr_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._asr_api_key.setFixedHeight(36)
        layout.addWidget(self._asr_api_key)

        asr_model_label = BodyLabel(_tr("SettingsWindow.asr_model_id", default="ASR 模型名"), page)
        layout.addWidget(asr_model_label)
        self._asr_model_id = FluentContextLineEdit(page)
        self._asr_model_id.setPlaceholderText("whisper-large-v3")
        self._asr_model_id.setFixedHeight(36)
        layout.addWidget(self._asr_model_id)

        asr_lang_label = BodyLabel(_tr("SettingsWindow.asr_language", default="识别语言"), page)
        layout.addWidget(asr_lang_label)
        self._asr_language = OpaqueDropDownComboBox(page)
        self._asr_language.addItem(_tr("SettingsWindow.asr_language_auto", default="自动检测"), userData="")
        self._asr_language.addItem(_tr("SettingsWindow.asr_language_chinese", default="中文"), userData="zh")
        self._asr_language.addItem(_tr("SettingsWindow.asr_language_japanese", default="日语"), userData="ja")
        self._asr_language.addItem(_tr("SettingsWindow.asr_language_english", default="英语"), userData="en")
        self._asr_language.setMaxVisibleItems(4)
        self._asr_language.setFixedHeight(36)
        layout.addWidget(self._asr_language)

        asr_insert_label = BodyLabel(_tr("SettingsWindow.asr_insert_mode", default="识别文本插入方式"), page)
        layout.addWidget(asr_insert_label)
        self._asr_insert_mode = OpaqueDropDownComboBox(page)
        self._asr_insert_mode.addItem(_tr("SettingsWindow.asr_insert_append", default="追加到输入框"), userData="append")
        self._asr_insert_mode.addItem(_tr("SettingsWindow.asr_insert_replace", default="替换输入框内容"), userData="replace")
        self._asr_insert_mode.setMaxVisibleItems(2)
        self._asr_insert_mode.setFixedHeight(36)
        layout.addWidget(self._asr_insert_mode)

        asr_auto_row = QHBoxLayout()
        asr_auto_row.setContentsMargins(0, 0, 0, 0)
        asr_auto_label = BodyLabel(_tr("SettingsWindow.asr_auto_send", default="识别完成后自动发送"), page)
        self._asr_auto_send = SwitchButton(page)
        asr_auto_row.addWidget(asr_auto_label)
        asr_auto_row.addStretch()
        asr_auto_row.addWidget(self._asr_auto_send)
        layout.addLayout(asr_auto_row)

        asr_max_label = BodyLabel(_tr("SettingsWindow.asr_max_record_seconds", default="最长录音秒数"), page)
        layout.addWidget(asr_max_label)
        self._asr_max_record_seconds = SpinBox(page)
        self._asr_max_record_seconds.setRange(3, 300)
        self._asr_max_record_seconds.setFixedHeight(36)
        layout.addWidget(self._asr_max_record_seconds)

        asr_test_label = BodyLabel(_tr("SettingsWindow.asr_test_result", default="测试识别结果"), page)
        layout.addWidget(asr_test_label)
        self._asr_test_result = FluentContextTextEdit(page)
        self._asr_test_result.setPlaceholderText(_tr("SettingsWindow.asr_test_placeholder", default="点击开始录音，再次点击停止并识别。"))
        _horizontal_scroll_text_edit(self._asr_test_result)
        self._asr_test_result.setFixedHeight(92)
        layout.addWidget(self._asr_test_result)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._asr_test_button = PushButton(FluentIcon.MICROPHONE, _tr("SettingsWindow.asr_test_button_start", default="开始录音"), page)
        self._asr_test_button.setFixedHeight(36)
        self._asr_test_button.setEnabled(_SETTINGS_ASR_AVAILABLE)
        self._asr_test_button.clicked.connect(self._toggle_asr_test)
        btn_row.addWidget(self._asr_test_button)
        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_asr_config)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_asr_config()
        self._style_asr_inputs()
        qconfig.themeChanged.connect(self._style_asr_inputs)

        return page

    def _asr_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_asr_enabled",
                "_asr_api_url",
                "_asr_api_key",
                "_asr_model_id",
                "_asr_language",
                "_asr_insert_mode",
                "_asr_auto_send",
                "_asr_max_record_seconds",
            )
        )

    def _style_asr_inputs(self):
        if not self._asr_config_widgets_ready():
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
        self._asr_api_url.setStyleSheet(style)
        self._asr_api_key.setStyleSheet(style)
        self._asr_model_id.setStyleSheet(style)
        self._asr_test_result.setStyleSheet(style)

    def _load_asr_config(self):
        if self._cfg and self._asr_config_widgets_ready():
            self._asr_enabled.setChecked(bool(self._cfg.get("asr_enabled", False)))
            self._asr_api_url.setText(self._cfg.get("asr_api_url", "http://127.0.0.1:8000/v1/audio/transcriptions"))
            self._asr_api_key.setText(self._cfg.get("asr_api_key", ""))
            self._asr_model_id.setText(self._cfg.get("asr_model_id", "whisper-large-v3"))
            saved_language = self._cfg.get("asr_language", "zh")
            for i in range(self._asr_language.count()):
                if self._asr_language.itemData(i) == saved_language:
                    self._asr_language.setCurrentIndex(i)
                    break
            saved_insert = self._cfg.get("asr_insert_mode", "append")
            for i in range(self._asr_insert_mode.count()):
                if self._asr_insert_mode.itemData(i) == saved_insert:
                    self._asr_insert_mode.setCurrentIndex(i)
                    break
            self._asr_auto_send.setChecked(bool(self._cfg.get("asr_auto_send", False)))
            self._asr_max_record_seconds.setValue(int(self._cfg.get("asr_max_record_seconds", 60) or 60))

    def _current_asr_config(self) -> dict:
        max_record_seconds = int(self._asr_max_record_seconds.value())
        return {
            "asr_enabled": self._asr_enabled.isChecked(),
            "asr_api_url": self._asr_api_url.text().strip() or "http://127.0.0.1:8000/v1/audio/transcriptions",
            "asr_api_key": self._asr_api_key.text().strip(),
            "asr_model_id": self._asr_model_id.text().strip() or "whisper-large-v3",
            "asr_language": self._asr_language.itemData(self._asr_language.currentIndex()) or "",
            "asr_auto_send": self._asr_auto_send.isChecked(),
            "asr_insert_mode": self._asr_insert_mode.itemData(self._asr_insert_mode.currentIndex()) or "append",
            "asr_sample_rate": 16000,
            "asr_max_record_seconds": max_record_seconds,
            "asr_timeout_seconds": 60,
        }

    def _save_asr_config(self, show_info: bool = True):
        if self._cfg and self._asr_config_widgets_ready():
            config = self._current_asr_config()
            for key, value in config.items():
                self._cfg.set(key, value)
            try:
                self._cfg.save()
                if show_info:
                    InfoBar.success(
                        _tr("SettingsWindow.asr_saved_title", default="ASR 配置已保存"),
                        _tr("SettingsWindow.asr_saved_content", default="聊天语音输入配置已更新。"),
                        duration=2000,
                        position=InfoBarPosition.TOP,
                        parent=self,
                    )
            except Exception:
                pass

    def _toggle_asr_test(self):
        if getattr(self, "_asr_test_recording", False):
            self._stop_asr_test_recording()
            return
        self._start_asr_test_recording()

    def _start_asr_test_recording(self):
        if not _ensure_settings_asr_available():
            InfoBar.warning(
                _tr("SettingsWindow.asr_test_unavailable_title", default="ASR 不可用"),
                _tr("SettingsWindow.asr_test_unavailable_content", default="当前环境缺少录音或识别依赖，无法进行测试。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not (self._cfg and self._asr_config_widgets_ready()):
            return
        from asr_manager import ASRRecorderWorker as recorder_class
        self._save_asr_config(show_info=False)
        self._asr_test_recording = True
        self._asr_test_result.setPlainText("")
        self._asr_test_button.setText(_tr("SettingsWindow.asr_test_button_stop", default="停止并识别"))
        self._asr_test_worker = recorder_class(self._current_asr_config(), self)
        self._asr_test_worker.audio_ready.connect(self._on_asr_test_audio_ready)
        self._asr_test_worker.error.connect(self._on_asr_test_error)
        self._asr_test_worker.finished.connect(self._on_asr_test_recording_finished)
        self._asr_test_worker.start()

    def _stop_asr_test_recording(self):
        worker = getattr(self, "_asr_test_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
        self._asr_test_button.setEnabled(False)

    def _on_asr_test_recording_finished(self):
        self._asr_test_recording = False
        if getattr(self, "_asr_test_request_worker", None) is None:
            self._asr_test_button.setEnabled(True)
            self._asr_test_button.setText(_tr("SettingsWindow.asr_test_button_start", default="开始录音"))

    def _on_asr_test_audio_ready(self, audio: bytes, media_type: str):
        from asr_manager import ASRRequestWorker as request_class
        self._asr_test_result.setPlainText(_tr("SettingsWindow.asr_test_transcribing", default="正在识别..."))
        self._asr_test_request_worker = request_class(audio, media_type, self._current_asr_config(), self)
        self._asr_test_request_worker.text_ready.connect(self._on_asr_test_text_ready)
        self._asr_test_request_worker.error.connect(self._on_asr_test_error)
        self._asr_test_request_worker.finished.connect(self._on_asr_test_request_finished)
        self._asr_test_request_worker.start()

    def _on_asr_test_text_ready(self, text: str):
        self._asr_test_result.setPlainText(text)

    def _on_asr_test_request_finished(self):
        self._asr_test_request_worker = None
        self._asr_test_button.setEnabled(True)
        self._asr_test_button.setText(_tr("SettingsWindow.asr_test_button_start", default="开始录音"))

    def _on_asr_test_error(self, msg: str):
        self._asr_test_recording = False
        self._asr_test_request_worker = None
        self._asr_test_button.setEnabled(True)
        self._asr_test_button.setText(_tr("SettingsWindow.asr_test_button_start", default="开始录音"))
        InfoBar.error(
            _tr("SettingsWindow.asr_test_failed_title", default="ASR 测试失败"),
            msg,
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
