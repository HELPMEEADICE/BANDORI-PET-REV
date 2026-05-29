from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class TTSPageMixin:

    def _build_tts_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.tts_title", "聊天与提醒 TTS"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.tts_subtitle",
            "配置聊天回复和提醒播报的语音合成、参考音频和非中文 TTS 翻译。",
        ), page))
        layout.addWidget(subtitle)

        tts_enable_row = QHBoxLayout()
        tts_enable_row.setContentsMargins(0, 0, 0, 0)
        tts_enable_label = BodyLabel(_tr("SettingsWindow.tts_enabled", "启用聊天与提醒语音合成"), page)
        self._tts_enabled = SwitchButton(page)
        tts_enable_row.addWidget(tts_enable_label)
        tts_enable_row.addStretch()
        tts_enable_row.addWidget(self._tts_enabled)
        layout.addLayout(tts_enable_row)

        tts_api_label = BodyLabel(_tr("SettingsWindow.tts_api_url", "TTS API 地址"), page)
        layout.addWidget(tts_api_label)
        self._tts_api_url = FluentContextLineEdit(page)
        self._tts_api_url.setPlaceholderText("http://127.0.0.1:9880/")
        self._tts_api_url.setFixedHeight(36)
        layout.addWidget(self._tts_api_url)

        tts_lang_label = BodyLabel(_tr("SettingsWindow.tts_language", "TTS 文本语言"), page)
        layout.addWidget(tts_lang_label)
        self._tts_language = OpaqueDropDownComboBox(page)
        self._tts_language.addItem(_tr("SettingsWindow.tts_language_chinese", "中文"), userData="Chinese")
        self._tts_language.addItem(_tr("SettingsWindow.tts_language_japanese", "日语"), userData="Japanese")
        self._tts_language.addItem(_tr("SettingsWindow.tts_language_english", "英语"), userData="English")
        self._tts_language.setFixedHeight(36)
        layout.addWidget(self._tts_language)

        tts_ref_label = BodyLabel(_tr("SettingsWindow.tts_reference", "参考音频角色"), page)
        layout.addWidget(tts_ref_label)
        self._tts_reference_character = OpaqueDropDownComboBox(page)
        self._tts_reference_character.addItem(_tr("SettingsWindow.tts_reference_auto", "跟随当前角色"), userData="")
        ref_dir = app_base_dir() / "audio_reference"
        ref_paths = []
        if ref_dir.exists():
            for suffix in ("*.mp3", "*.wav", "*.flac", "*.ogg", "*.m4a"):
                ref_paths.extend(ref_dir.glob(suffix))
        seen_refs = set()
        for audio_path in sorted(ref_paths, key=lambda path: path.stem):
            key = audio_path.stem
            if key in seen_refs:
                continue
            seen_refs.add(key)
            display = self._model_manager.get_display_name(key) if key in self._model_manager.characters else key
            self._tts_reference_character.addItem(display, userData=key)
        self._tts_reference_character.setFixedHeight(36)
        layout.addWidget(self._tts_reference_character)

        tts_temperature_label = BodyLabel(_tr("SettingsWindow.tts_temperature", "TTS 温度参数"), page)
        layout.addWidget(tts_temperature_label)
        self._tts_temperature = FluentContextLineEdit(page)
        self._tts_temperature.setPlaceholderText("0.9")
        self._tts_temperature.setFixedHeight(36)
        temp_validator = QDoubleValidator(0.01, 2.0, 2, self._tts_temperature)
        temp_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self._tts_temperature.setValidator(temp_validator)
        layout.addWidget(self._tts_temperature)

        tts_stream_row = QHBoxLayout()
        tts_stream_row.setContentsMargins(0, 0, 0, 0)
        tts_stream_label = BodyLabel(_tr("SettingsWindow.tts_streaming", "启用 TTS 流式请求"), page)
        self._tts_streaming = SwitchButton(page)
        self._tts_streaming.setChecked(True)
        tts_stream_row.addWidget(tts_stream_label)
        tts_stream_row.addStretch()
        tts_stream_row.addWidget(self._tts_streaming)
        layout.addLayout(tts_stream_row)

        tts_translate_row = QHBoxLayout()
        tts_translate_row.setContentsMargins(0, 0, 0, 0)
        tts_translate_label = BodyLabel(_tr("SettingsWindow.tts_translate_to_selected_language", "非中文 TTS 时用快速模型逐段翻译到所选语言"), page)
        self._tts_translate_to_selected_language = SwitchButton(page)
        self._tts_translate_to_selected_language.setChecked(True)
        tts_translate_row.addWidget(tts_translate_label)
        tts_translate_row.addStretch()
        tts_translate_row.addWidget(self._tts_translate_to_selected_language)
        layout.addLayout(tts_translate_row)

        tts_test_label = BodyLabel(_tr("SettingsWindow.tts_test_text", default="测试文本"), page)
        layout.addWidget(tts_test_label)
        self._tts_test_text = FluentContextTextEdit(page)
        self._tts_test_text.setPlaceholderText(_tr(
            "SettingsWindow.tts_test_text_placeholder",
            default="留空则使用默认测试文案。",
        ))
        self._tts_test_text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._tts_test_text.setFixedHeight(92)
        layout.addWidget(self._tts_test_text)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._tts_test_button = PushButton(FluentIcon.PLAY, _tr("SettingsWindow.tts_test_button", default="测试播放"), page)
        self._tts_test_button.setFixedHeight(36)
        self._tts_test_button.setEnabled(_SETTINGS_TTS_AVAILABLE)
        self._tts_test_button.clicked.connect(self._test_tts)
        btn_row.addWidget(self._tts_test_button)
        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_tts_config)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_tts_config()
        self._style_tts_inputs()
        qconfig.themeChanged.connect(self._style_tts_inputs)

        return page

    def _tts_config_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_tts_enabled",
                "_tts_api_url",
                "_tts_language",
                "_tts_reference_character",
                "_tts_temperature",
                "_tts_streaming",
                "_tts_translate_to_selected_language",
            )
        )

    def _style_tts_inputs(self):
        if not self._tts_config_widgets_ready():
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
        """
        self._tts_api_url.setStyleSheet(style)
        self._tts_temperature.setStyleSheet(style)
        self._tts_test_text.setStyleSheet(style)

    def _load_tts_config(self):
        if self._cfg and self._tts_config_widgets_ready():
            self._tts_enabled.setChecked(bool(self._cfg.get("tts_enabled", False)))
            self._tts_api_url.setText(self._cfg.get("tts_api_url", "http://127.0.0.1:9880/"))
            saved_tts_language = self._cfg.get("tts_language", "Chinese")
            for i in range(self._tts_language.count()):
                if self._tts_language.itemData(i) == saved_tts_language:
                    self._tts_language.setCurrentIndex(i)
                    break
            saved_ref = self._cfg.get("tts_reference_character", "")
            for i in range(self._tts_reference_character.count()):
                if self._tts_reference_character.itemData(i) == saved_ref:
                    self._tts_reference_character.setCurrentIndex(i)
                    break
            self._tts_temperature.setText(str(self._cfg.get("tts_temperature", 0.9)))
            self._tts_streaming.setChecked(bool(self._cfg.get("tts_streaming", True)))
            self._tts_translate_to_selected_language.setChecked(bool(self._cfg.get("tts_translate_to_selected_language", True)))

    def _current_tts_config(self, include_llm: bool = False) -> dict:
        try:
            temperature = max(0.01, min(2.0, float(self._tts_temperature.text().strip() or "0.9")))
        except ValueError:
            temperature = 0.9
        self._tts_temperature.setText(str(temperature))
        config = {
            "tts_enabled": self._tts_enabled.isChecked(),
            "tts_api_url": self._tts_api_url.text().strip() or "http://127.0.0.1:9880/",
            "tts_language": self._tts_language.itemData(self._tts_language.currentIndex()) or "Chinese",
            "tts_reference_character": self._tts_reference_character.itemData(self._tts_reference_character.currentIndex()) or "",
            "tts_temperature": temperature,
            "tts_streaming": self._tts_streaming.isChecked(),
            "tts_translate_to_selected_language": self._tts_translate_to_selected_language.isChecked(),
        }
        if include_llm and self._cfg:
            for key in (
                "llm_api_url",
                "llm_api_key",
                "llm_model_id",
                "llm_aux_api_url",
                "llm_aux_api_key",
                "llm_aux_model_id",
                "llm_aux_enable_thinking",
            ):
                config[key] = self._cfg.get(key, None)
        return config

    def _save_tts_config(self, show_info: bool = True):
        if self._cfg and self._tts_config_widgets_ready():
            config = self._current_tts_config()
            for key, value in config.items():
                self._cfg.set(key, value)
            try:
                self._cfg.save()
                if show_info:
                    InfoBar.success(
                        _tr("SettingsWindow.tts_saved_title"),
                        _tr("SettingsWindow.tts_saved_content"),
                        duration=2000,
                        position=InfoBarPosition.TOP,
                        parent=self,
                    )
            except Exception:
                pass

    def _test_tts(self):
        if getattr(self, "_tts_test_running", False):
            return
        if not _ensure_settings_tts_available():
            self._set_tts_test_running(False)
            InfoBar.warning(
                _tr("SettingsWindow.tts_test_unavailable_title", default="TTS 不可用"),
                _tr("SettingsWindow.tts_test_unavailable_content", default="当前环境缺少 TTS 播放依赖，无法进行测试播放。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not (self._cfg and self._tts_config_widgets_ready()):
            return

        config = self._current_tts_config(include_llm=True)
        test_text = self._tts_test_text.toPlainText().strip()
        if not test_text:
            test_text = _tr("SettingsWindow.tts_test_default_text", default="你好，这是一段 TTS 测试语音。")

        test_character = str(config.get("tts_reference_character", "") or "").strip() or self._current_char
        if not test_character:
            for index in range(self._tts_reference_character.count()):
                candidate = str(self._tts_reference_character.itemData(index) or "").strip()
                if candidate:
                    test_character = candidate
                    break
        if not test_character:
            InfoBar.warning(
                _tr("SettingsWindow.tts_test_missing_reference_title", default="缺少参考音频"),
                _tr("SettingsWindow.tts_test_missing_reference_content", default="请先选择参考音频角色，或确保当前模型角色有对应参考音频。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        self._save_tts_config(show_info=False)
        self._stop_tts_test_playback()
        self._set_tts_test_running(True)
        self._tts_test_failed = False
        self._tts_test_received_audio = False
        if getattr(self, "_tts_test_player", None) is None:
            self._tts_test_player = TTSPlayer(self)
            self._tts_test_player.error.connect(self._on_tts_test_error)
            self._tts_test_player.playback_finished.connect(self._on_tts_test_playback_finished)
        self._tts_test_worker = TTSRequestWorker(0, 0, test_text, test_character, config, self)
        self._tts_test_worker.audio_ready.connect(self._on_tts_test_audio_ready)
        self._tts_test_worker.error.connect(self._on_tts_test_error)
        self._tts_test_worker.finished.connect(self._on_tts_test_finished)
        self._tts_test_worker.start()

    def _set_tts_test_running(self, running: bool):
        self._tts_test_running = running
        button = getattr(self, "_tts_test_button", None)
        if button is not None:
            button.setEnabled(_SETTINGS_TTS_AVAILABLE and not running)

    def _stop_tts_test_playback(self):
        worker = getattr(self, "_tts_test_worker", None)
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.wait(2000)
        player = getattr(self, "_tts_test_player", None)
        if player is not None:
            player.stop()

    def _on_tts_test_audio_ready(self, _sequence: int, _generation: int, audio: bytes, media_type: str):
        if not audio or getattr(self, "_tts_test_player", None) is None:
            return
        self._tts_test_received_audio = True
        self._tts_test_player.enqueue(audio, media_type)

    def _on_tts_test_finished(self):
        if getattr(self, "_tts_test_failed", False):
            self._set_tts_test_running(False)
            return
        if not getattr(self, "_tts_test_received_audio", False):
            self._set_tts_test_running(False)
            InfoBar.warning(
                _tr("SettingsWindow.tts_test_empty_title", default="测试未返回音频"),
                _tr("SettingsWindow.tts_test_empty_content", default="TTS 请求已完成，但没有收到可播放的音频数据。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        InfoBar.success(
            _tr("SettingsWindow.tts_test_success_title", default="正在播放测试语音"),
            _tr("SettingsWindow.tts_test_success_content", default="已收到 TTS 音频并开始播放。"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_tts_test_playback_finished(self):
        self._set_tts_test_running(False)

    def _on_tts_test_error(self, msg: str):
        self._tts_test_failed = True
        self._set_tts_test_running(False)
        player = getattr(self, "_tts_test_player", None)
        if player is not None:
            player.stop()
        InfoBar.error(
            _tr("SettingsWindow.tts_test_failed_title", default="TTS 测试失败"),
            msg,
            duration=4000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
