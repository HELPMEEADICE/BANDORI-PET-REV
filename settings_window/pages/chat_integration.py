from process_utils import clamp_int
from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class ChatIntegrationPageMixin:

    def _build_chat_integration_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("chatIntegrationPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.setMinimumWidth(0)
        page.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = _wrap_label(TitleLabel(_tr("SettingsWindow.chat_integration_title", default="聊天接入"), page))
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.chat_integration_subtitle",
            default="接收外部聊天软件或脚本推送的消息，写入本地上下文，并在桌宠悬浮窗显示未读摘要。",
        ), page))
        layout.addWidget(subtitle)

        self._chat_integration_enabled = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.chat_integration_enabled", default="启用本地聊天接入端口"),
            self._chat_integration_enabled,
        )

        self._chat_integration_overlay_enabled = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.chat_integration_overlay_enabled", default="收到消息时显示悬浮窗摘要"),
            self._chat_integration_overlay_enabled,
        )

        self._chat_integration_include_context = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.chat_integration_include_context", default="允许模型读取最近外部聊天上下文"),
            self._chat_integration_include_context,
        )

        layout.addWidget(SubtitleLabel(_tr(
            "SettingsWindow.chat_integration_quick_setup",
            default="快速配置",
        ), page))

        endpoint_field = QWidget(page)
        endpoint_field.setMinimumWidth(0)
        endpoint_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        endpoint_layout = QVBoxLayout(endpoint_field)
        endpoint_layout.setContentsMargins(0, 0, 0, 0)
        endpoint_layout.setSpacing(5)
        endpoint_layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.chat_integration_endpoint",
            default="接收地址",
        ), endpoint_field)))
        endpoint_row = QHBoxLayout()
        endpoint_row.setContentsMargins(0, 0, 0, 0)
        endpoint_row.setSpacing(8)
        self._chat_integration_endpoint_input = FluentContextLineEdit(page)
        self._chat_integration_endpoint_input.setReadOnly(True)
        self._chat_integration_endpoint_input.setFixedHeight(36)
        self._chat_integration_endpoint_input.setMinimumWidth(0)
        self._chat_integration_endpoint_input.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            self._chat_integration_endpoint_input.sizePolicy().verticalPolicy(),
        )
        copy_endpoint_btn = PushButton(FluentIcon.COPY, _tr(
            "SettingsWindow.chat_integration_copy_endpoint",
            default="复制地址",
        ), page)
        copy_endpoint_btn.setMinimumWidth(0)
        copy_endpoint_btn.clicked.connect(self._copy_chat_integration_endpoint)
        endpoint_row.addWidget(self._chat_integration_endpoint_input, 1)
        endpoint_row.addWidget(copy_endpoint_btn)
        endpoint_layout.addLayout(endpoint_row)
        layout.addWidget(endpoint_field)

        config_grid = QGridLayout()
        config_grid.setContentsMargins(0, 0, 0, 0)
        config_grid.setHorizontalSpacing(12)
        config_grid.setVerticalSpacing(8)
        config_grid.setColumnStretch(0, 1)
        config_grid.setColumnStretch(1, 2)

        port_field = QWidget(page)
        port_field.setMinimumWidth(0)
        port_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        port_layout = QVBoxLayout(port_field)
        port_layout.setContentsMargins(0, 0, 0, 0)
        port_layout.setSpacing(5)
        port_layout.addWidget(_wrap_label(BodyLabel(
            _tr("SettingsWindow.chat_integration_port_number", default="端口"),
            port_field,
        )))
        self._chat_integration_port_input = LineEdit(page)
        self._chat_integration_port_input.setFixedHeight(36)
        self._chat_integration_port_input.setMinimumWidth(0)
        self._chat_integration_port_input.setValidator(QIntValidator(1024, 65535, self))
        self._chat_integration_port_input.setPlaceholderText("38473")
        port_layout.addWidget(self._chat_integration_port_input)

        token_field = QWidget(page)
        token_field.setMinimumWidth(0)
        token_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        token_layout = QVBoxLayout(token_field)
        token_layout.setContentsMargins(0, 0, 0, 0)
        token_layout.setSpacing(5)
        token_layout.addWidget(_wrap_label(BodyLabel(
            _tr("SettingsWindow.chat_integration_token", default="Token"),
            token_field,
        )))
        self._chat_integration_token_input = LineEdit(page)
        self._chat_integration_token_input.setFixedHeight(36)
        self._chat_integration_token_input.setMinimumWidth(0)
        self._chat_integration_token_input.setPlaceholderText(_tr(
            "SettingsWindow.chat_integration_token_placeholder",
            default="可留空；给第三方脚本使用时建议填写",
        ))
        token_layout.addWidget(self._chat_integration_token_input)
        config_grid.addWidget(port_field, 0, 0)
        config_grid.addWidget(token_field, 0, 1)
        layout.addLayout(config_grid)

        token_actions = QGridLayout()
        token_actions.setContentsMargins(0, 0, 0, 0)
        token_actions.setHorizontalSpacing(8)
        token_actions.setVerticalSpacing(8)
        token_actions.setColumnStretch(0, 1)
        token_actions.setColumnStretch(1, 1)
        generate_token_btn = PushButton(FluentIcon.SYNC, _tr(
            "SettingsWindow.chat_integration_generate_token",
            default="生成 Token",
        ), page)
        generate_token_btn.clicked.connect(self._generate_chat_integration_token)
        copy_token_btn = PushButton(FluentIcon.COPY, _tr(
            "SettingsWindow.chat_integration_copy_token",
            default="复制 Token",
        ), page)
        copy_token_btn.clicked.connect(self._copy_chat_integration_token)
        for column, button in enumerate((generate_token_btn, copy_token_btn)):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, button.sizePolicy().verticalPolicy())
            token_actions.addWidget(button, 0, column)
        layout.addLayout(token_actions)

        hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.chat_integration_hint",
            default="开启后监听 127.0.0.1，可接收 JSON、表单、纯文本或 URL 参数。外部消息会进入本地数据库；开启上下文后，下一次角色聊天会看到最近消息。",
        ), page))
        layout.addWidget(hint)

        self._chat_integration_preview = JsonCodeEdit(page)
        self._chat_integration_preview.setReadOnly(True)
        self._chat_integration_preview.setFixedHeight(170)
        self._chat_integration_preview.setMinimumWidth(0)
        self._chat_integration_preview.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            self._chat_integration_preview.sizePolicy().verticalPolicy(),
        )
        layout.addWidget(self._chat_integration_preview)

        btn_grid = QGridLayout()
        btn_grid.setContentsMargins(0, 0, 0, 0)
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(8)
        btn_grid.setColumnStretch(0, 1)
        btn_grid.setColumnStretch(1, 1)
        save_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.chat_integration_save", default="保存聊天接入配置"), page)
        save_btn.clicked.connect(lambda: self._save_chat_integration_config(show_info=True, emit_update=True))
        copy_setup_btn = PushButton(FluentIcon.COPY, _tr(
            "SettingsWindow.chat_integration_copy_setup",
            default="复制接入信息",
        ), page)
        copy_setup_btn.clicked.connect(self._copy_chat_integration_setup)
        test_btn = PushButton(FluentIcon.WIFI, _tr(
            "SettingsWindow.chat_integration_test",
            default="发送测试消息",
        ), page)
        test_btn.clicked.connect(self._test_chat_integration)
        guide_btn = PushButton(FluentIcon.INFO, _tr(
            "SettingsWindow.chat_integration_open_guide",
            default="打开教程",
        ), page)
        guide_btn.clicked.connect(self._open_chat_integration_guide)
        for index, button in enumerate((save_btn, copy_setup_btn, test_btn, guide_btn)):
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, button.sizePolicy().verticalPolicy())
            btn_grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(btn_grid)

        apply_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.chat_integration_apply_hint",
            default="保存后会立即通知正在运行的桌宠刷新端口；如果没有启动桌宠，请启动后再测试。",
        ), page))
        layout.addWidget(apply_hint)

        self._build_napcat_section(layout, page)
        layout.addStretch()

        self._chat_integration_port_input.textChanged.connect(self._update_chat_integration_quick_setup)
        self._chat_integration_token_input.textChanged.connect(self._update_chat_integration_quick_setup)
        self._load_chat_integration_config()
        self._style_chat_integration_page(page)
        self._connect_theme_changed(lambda: self._style_chat_integration_page(page))
        return page

    def _chat_integration_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_chat_integration_enabled",
                "_chat_integration_overlay_enabled",
                "_chat_integration_include_context",
                "_chat_integration_endpoint_input",
                "_chat_integration_port_input",
                "_chat_integration_token_input",
                "_chat_integration_preview",
            )
        )

    def _style_chat_integration_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        text_border = "#4a4a4a" if dark else "#d8d8d8"
        input_bg = "#2b2b2b" if dark else "#ffffff"
        text = "#f7f7fb" if dark else "#1f2328"
        readonly_bg = "#242424" if dark else "#f8f8f8"
        control_hover_bg = "#333333" if dark else "#f9fafb"
        control_pressed_bg = "#262626" if dark else "#f3f4f6"
        disabled_bg = "#252525" if dark else "#f5f6f8"
        disabled_text = "#b7beca" if dark else "#4b5563"
        disabled_border = "#3a3a3a" if dark else "#d9dee8"
        page.setStyleSheet(f"""
            QWidget#chatIntegrationPage {{
                background: {page_bg};
            }}
            QLineEdit {{
                color: {text};
                background: {input_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                padding: 6px;
            }}
            QLineEdit[readOnly="true"] {{
                background: {readonly_bg};
            }}
            QPlainTextEdit#JsonCodeEdit {{
                color: {text};
                background: {readonly_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                padding-left: 0px;
                selection-background-color: {BANDORI_PRIMARY};
            }}
            {_fluent_scrollbar_qss(dark=dark)}
            #NapcatRecordCombo {{
                color: {text};
                background-color: {input_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                border-bottom: 1px solid {text_border};
                padding: 5px 31px 6px 11px;
                text-align: left;
            }}
            #NapcatRecordCombo:hover {{
                background-color: {control_hover_bg};
            }}
            #NapcatRecordCombo:pressed {{
                color: {text};
                background-color: {control_pressed_bg};
                border-bottom: 1px solid {text_border};
            }}
            #NapcatRecordDaysSpin {{
                color: {text};
                background-color: {input_bg};
                border: 1px solid {text_border};
                border-bottom: 1px solid {text_border};
                border-radius: 6px;
                padding: 0px 76px 0px 12px;
                selection-background-color: {BANDORI_PRIMARY};
            }}
            #NapcatRecordDaysSpin:hover,
            #NapcatRecordDaysSpin:focus {{
                color: {text};
                background-color: {control_hover_bg};
                border: 1px solid {text_border};
                border-bottom: 1px solid {text_border};
            }}
            #NapcatRecordDaysSpin:disabled {{
                color: {disabled_text};
                background-color: {disabled_bg};
                border: 1px solid {disabled_border};
                border-bottom: 1px solid {disabled_border};
            }}
            QLineEdit#NapcatRecordDaysSpinEdit {{
                color: {text};
                background: transparent;
                border: none;
                padding: 0px;
                selection-background-color: {BANDORI_PRIMARY};
            }}
            QLineEdit#NapcatRecordDaysSpinEdit:hover,
            QLineEdit#NapcatRecordDaysSpinEdit:focus {{
                color: {text};
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QLineEdit#NapcatRecordDaysSpinEdit:disabled {{
                color: {disabled_text};
                background: transparent;
                border: none;
                padding: 0px;
            }}
        """)
        self._refresh_theme_widget_styles(page)
        self._refresh_json_code_edit_theme(getattr(self, "_chat_integration_preview", None))

    def _chat_integration_endpoint_url(self) -> str:
        if self._chat_integration_widgets_ready():
            port = clamp_int(self._chat_integration_port_input.text(), 1024, 65535, 38473)
        elif self._cfg:
            port = clamp_int(self._cfg.get("chat_integration_port", 38473), 1024, 65535, 38473)
        else:
            port = 38473
        return f"http://127.0.0.1:{port}/chat-events"

    def _chat_integration_sample_event(self) -> dict:
        return {
            "platform": "qq",
            "thread_id": "default",
            "thread_name": "接入测试",
            "sender_name": "测试用户",
            "text": "这是一条从聊天软件推送到 BandoriPet 的测试消息。",
        }

    def _chat_integration_setup_text(self) -> str:
        endpoint = self._chat_integration_endpoint_url()
        token = self._chat_integration_token_input.text().strip() if self._chat_integration_widgets_ready() else ""
        headers = "Content-Type: application/json"
        if token:
            headers += f"\nAuthorization: Bearer {token}"
        sample = json.dumps(self._chat_integration_sample_event(), ensure_ascii=False, indent=2)
        url_sample = (
            f"{endpoint}?platform=qq&thread_id=default&thread_name=接入测试"
            f"&sender_name=发送人&text=消息内容"
        )
        if token:
            url_sample += f"&token={token}"
        return "\n".join([
            "BandoriPet 聊天接入信息",
            f"接收地址: {endpoint}",
            "请求方式: POST（推荐）或 GET URL 参数；支持 JSON、表单和纯文本正文",
            headers,
            "",
            "最小 JSON:",
            sample,
            "",
            "URL 参数模式:",
            url_sample,
            "",
            "字段对应：text=消息内容，sender_name=发送人，thread_name=群聊/私聊名称。",
        ])

    def _update_chat_integration_quick_setup(self, *_args):
        if not self._chat_integration_widgets_ready():
            return
        self._chat_integration_endpoint_input.setText(self._chat_integration_endpoint_url())
        self._chat_integration_preview.setPlainText(self._chat_integration_setup_text())

    def _copy_chat_integration_endpoint(self):
        if not self._chat_integration_widgets_ready():
            return
        QApplication.clipboard().setText(self._chat_integration_endpoint_url())
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_endpoint_copied_title", default="已复制"),
            _tr("SettingsWindow.chat_integration_endpoint_copied_content", default="聊天接入地址已复制。"),
            duration=1600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _generate_chat_integration_token(self):
        if not self._chat_integration_widgets_ready():
            return
        self._chat_integration_token_input.setText(secrets.token_urlsafe(18))
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_token_generated_title", default="已生成 Token"),
            _tr("SettingsWindow.chat_integration_token_generated_content", default="请保存配置后，把 Token 一起填到聊天软件或转发插件里。"),
            duration=2200,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _copy_chat_integration_token(self):
        if not self._chat_integration_widgets_ready():
            return
        token = self._chat_integration_token_input.text().strip()
        if not token:
            InfoBar.warning(
                _tr("SettingsWindow.chat_integration_token_empty_title", default="没有 Token"),
                _tr("SettingsWindow.chat_integration_token_empty_content", default="当前 Token 为空，可以先点击\u201c生成 Token\u201d。"),
                duration=2200,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        QApplication.clipboard().setText(token)
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_token_copied_title", default="已复制"),
            _tr("SettingsWindow.chat_integration_token_copied_content", default="Token 已复制。"),
            duration=1600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _copy_chat_integration_setup(self):
        if not self._chat_integration_widgets_ready():
            return
        QApplication.clipboard().setText(self._chat_integration_setup_text())
        InfoBar.success(
            _tr("SettingsWindow.chat_integration_setup_copied_title", default="已复制"),
            _tr("SettingsWindow.chat_integration_setup_copied_content", default="接入信息已复制，可直接粘贴到聊天软件的 Webhook/HTTP 配置里。"),
            duration=2200,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _open_chat_integration_guide(self):
        path = os.path.join(app_base_dir(), "CHAT_INTEGRATION_GUIDE.md")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _test_chat_integration(self):
        if not self._chat_integration_widgets_ready():
            return
        if not self._chat_integration_enabled.isChecked():
            self._chat_integration_enabled.setChecked(True)
        self._save_chat_integration_config(show_info=False, emit_update=True)
        QTimer.singleShot(350, self._send_chat_integration_test_request)

    def _send_chat_integration_test_request(self):
        endpoint = self._chat_integration_endpoint_url()
        token = self._chat_integration_token_input.text().strip() if self._chat_integration_widgets_ready() else ""
        data = json.dumps(self._chat_integration_sample_event(), ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
            payload = json.loads(body) if body else {}
            if isinstance(payload, dict) and payload.get("ok"):
                InfoBar.success(
                    _tr("SettingsWindow.chat_integration_test_success_title", default="测试成功"),
                    _tr("SettingsWindow.chat_integration_test_success_content", default="BandoriPet 已收到测试消息，悬浮摘要和上下文接入可用。"),
                    duration=2600,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return
            raise RuntimeError(body or "empty response")
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace")
            detail = body or str(exc)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as exc:
            detail = str(exc)
        InfoBar.error(
            _tr("SettingsWindow.chat_integration_test_failed_title", default="测试失败"),
            _tr(
                "SettingsWindow.chat_integration_test_failed_content",
                default="没有连上本地接入口。请确认桌宠正在运行，并已保存/应用聊天接入配置。错误：{error}",
                error=detail,
            ),
            duration=4500,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _load_chat_integration_config(self):
        if not self._cfg or not self._chat_integration_widgets_ready():
            return
        self._chat_integration_enabled.setChecked(bool(self._cfg.get("chat_integration_enabled", False)))
        self._chat_integration_overlay_enabled.setChecked(bool(self._cfg.get("chat_integration_overlay_enabled", True)))
        self._chat_integration_include_context.setChecked(bool(self._cfg.get("chat_integration_include_context", True)))
        self._chat_integration_port_input.setText(str(clamp_int(self._cfg.get("chat_integration_port", 38473), 1024, 65535, 38473)))
        self._chat_integration_token_input.setText(str(self._cfg.get("chat_integration_token", "") or ""))
        self._load_napcat_config()
        self._update_chat_integration_quick_setup()

    def _chat_integration_settings_data(self) -> dict:
        if not self._cfg:
            return {}
        data = {
            "chat_integration_enabled": self._cfg.get("chat_integration_enabled", False),
            "chat_integration_overlay_enabled": self._cfg.get("chat_integration_overlay_enabled", True),
            "chat_integration_include_context": self._cfg.get("chat_integration_include_context", True),
            "chat_integration_port": clamp_int(self._cfg.get("chat_integration_port", 38473), 1024, 65535, 38473),
            "chat_integration_token": self._cfg.get("chat_integration_token", ""),
        }
        data.update(self._napcat_settings_data())
        return data

    def _save_chat_integration_config(self, show_info: bool = True, emit_update: bool = False):
        if not self._cfg or not self._chat_integration_widgets_ready():
            return
        enabled = self._chat_integration_enabled.isChecked()
        token = self._chat_integration_token_input.text().strip()
        if enabled and not token:
            # Never persist an enabled port without a token: an unauthenticated
            # loopback port can be driven by any local process or web page.
            token = secrets.token_urlsafe(18)
            self._chat_integration_token_input.setText(token)
        self._cfg.set("chat_integration_enabled", enabled)
        self._cfg.set("chat_integration_overlay_enabled", self._chat_integration_overlay_enabled.isChecked())
        self._cfg.set("chat_integration_include_context", self._chat_integration_include_context.isChecked())
        self._cfg.set("chat_integration_port", clamp_int(self._chat_integration_port_input.text(), 1024, 65535, 38473))
        self._cfg.set("chat_integration_token", token)
        self._save_napcat_into_cfg()
        try:
            self._cfg.save()
            if emit_update:
                self.settings_changed.emit(self._chat_integration_settings_data())
            if show_info:
                InfoBar.success(
                    _tr("SettingsWindow.chat_integration_saved_title", default="已保存"),
                    _tr("SettingsWindow.chat_integration_saved_content", default="聊天接入配置已保存。"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.chat_integration_failed_title", default="保存失败"),
                str(exc),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )

    def _build_napcat_section(self, layout, page):
        layout.addWidget(SubtitleLabel(_tr(
            "SettingsWindow.napcat_title",
            default="NapCat 适配（正向 WebSocket）",
        ), page))
        napcat_desc = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.napcat_desc",
            default="像 AstrBot 那样主动连接 NapCat。请先在 NapCat WebUI 开启 WebSocket 服务器，再在下方填写地址。",
        ), page))
        layout.addWidget(napcat_desc)

        self._napcat_enabled = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.napcat_enabled", default="启用 NapCat 连接"),
            self._napcat_enabled,
        )

        url_grid = QGridLayout()
        url_grid.setContentsMargins(0, 0, 0, 0)
        url_grid.setHorizontalSpacing(12)
        url_grid.setVerticalSpacing(8)
        url_grid.setColumnStretch(0, 1)
        url_grid.setColumnStretch(1, 1)
        self._napcat_ws_url_input = LineEdit(page)
        self._napcat_ws_url_input.setFixedHeight(36)
        self._napcat_ws_url_input.setMinimumWidth(0)
        self._napcat_ws_url_input.setPlaceholderText("ws://127.0.0.1:3001")
        self._napcat_token_input = LineEdit(page)
        self._napcat_token_input.setFixedHeight(36)
        self._napcat_token_input.setMinimumWidth(0)
        self._napcat_token_input.setPlaceholderText(_tr(
            "SettingsWindow.napcat_token_placeholder",
            default="Access Token，可留空",
        ))
        for column, (label, control) in enumerate((
            (_tr("SettingsWindow.napcat_ws_url", default="WS 地址"), self._napcat_ws_url_input),
            (_tr("SettingsWindow.napcat_token", default="Token"), self._napcat_token_input),
        )):
            field = QWidget(page)
            field.setMinimumWidth(0)
            field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            field_layout = QVBoxLayout(field)
            field_layout.setContentsMargins(0, 0, 0, 0)
            field_layout.setSpacing(5)
            field_layout.addWidget(_wrap_label(BodyLabel(label, field)))
            field_layout.addWidget(control)
            url_grid.addWidget(field, 0, column)
        layout.addLayout(url_grid)

        self._napcat_auto_reply_enabled = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.napcat_auto_reply_enabled", default="启用自动回复（AI 生成并发回 QQ）"),
            self._napcat_auto_reply_enabled,
        )
        self._napcat_reply_private = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.napcat_reply_private", default="私聊自动回复"),
            self._napcat_reply_private,
        )
        self._napcat_reply_group_at_only = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.napcat_reply_group_at_only", default="群聊仅在 @机器人 时回复"),
            self._napcat_reply_group_at_only,
        )
        self._napcat_reply_mention_sender = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.napcat_reply_mention_sender", default="回复开头 @ 发消息的人"),
            self._napcat_reply_mention_sender,
        )

        layout.addWidget(SubtitleLabel(_tr(
            "SettingsWindow.napcat_record_title",
            default="聊天记录管理",
        ), page))

        policy_field = QWidget(page)
        policy_field.setMinimumWidth(0)
        policy_field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy_layout = QVBoxLayout(policy_field)
        policy_layout.setContentsMargins(0, 0, 0, 0)
        policy_layout.setSpacing(5)
        policy_layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.napcat_save_policy",
            default="聊天记录保存策略",
        ), policy_field)))
        self._napcat_save_policy_combo = OpaqueDropDownComboBox(page)
        self._napcat_save_policy_combo.setObjectName("NapcatRecordCombo")
        self._napcat_save_policy_combo.addItem(_tr(
            "SettingsWindow.napcat_save_policy_all", default="全部保存（群聊和私聊）",
        ), userData="all")
        self._napcat_save_policy_combo.addItem(_tr(
            "SettingsWindow.napcat_save_policy_private", default="只保存私聊",
        ), userData="private_only")
        self._napcat_save_policy_combo.addItem(_tr(
            "SettingsWindow.napcat_save_policy_overlay", default="仅悬浮窗提示，不保存",
        ), userData="overlay_only")
        self._napcat_save_policy_combo.setMinimumWidth(0)
        self._napcat_save_policy_combo.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            self._napcat_save_policy_combo.sizePolicy().verticalPolicy(),
        )
        policy_layout.addWidget(self._napcat_save_policy_combo)
        layout.addWidget(policy_field)

        (
            self._napcat_group_retention_mode_combo,
            self._napcat_group_retention_days_spin,
        ) = self._build_napcat_retention_row(
            layout,
            page,
            label=_tr("SettingsWindow.napcat_group_retention", default="群聊记录保留"),
            delete_label=_tr("SettingsWindow.napcat_delete_group", default="删除群聊记录"),
            on_delete=self._napcat_delete_group_records,
        )
        (
            self._napcat_private_retention_mode_combo,
            self._napcat_private_retention_days_spin,
        ) = self._build_napcat_retention_row(
            layout,
            page,
            label=_tr("SettingsWindow.napcat_private_retention", default="私聊记录保留"),
            delete_label=_tr("SettingsWindow.napcat_delete_private", default="删除私聊记录"),
            on_delete=self._napcat_delete_private_records,
        )

        napcat_btn_row = QHBoxLayout()
        napcat_btn_row.setContentsMargins(0, 0, 0, 0)
        test_conn_btn = PushButton(FluentIcon.WIFI, _tr(
            "SettingsWindow.napcat_test", default="测试连接",
        ), page)
        test_conn_btn.clicked.connect(self._test_napcat_connection)
        self._napcat_status_label = BodyLabel("", page)
        self._napcat_status_label.setWordWrap(True)
        self._napcat_status_label.setMinimumWidth(0)
        self._napcat_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        test_conn_btn.setMinimumWidth(0)
        napcat_btn_row.addWidget(test_conn_btn)
        napcat_btn_row.addWidget(self._napcat_status_label, 1)
        layout.addLayout(napcat_btn_row)

    def _build_napcat_retention_row(self, layout, page, *, label, delete_label, on_delete):
        field = QWidget(page)
        field.setMinimumWidth(0)
        field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row = QGridLayout(field)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(5)
        row.setColumnStretch(0, 1)
        row.setColumnStretch(1, 1)
        row.setColumnStretch(2, 1)
        row.addWidget(_wrap_label(BodyLabel(label, field)), 0, 0, 1, 3)
        mode_combo = OpaqueDropDownComboBox(page)
        mode_combo.setObjectName("NapcatRecordCombo")
        mode_combo.addItem(_tr("SettingsWindow.napcat_retention_auto", default="自动删除"), userData="auto")
        mode_combo.addItem(_tr("SettingsWindow.napcat_retention_manual", default="手动删除"), userData="manual")
        mode_combo.setMinimumWidth(0)
        mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, mode_combo.sizePolicy().verticalPolicy())
        row.addWidget(mode_combo, 1, 0)
        days_field = QWidget(field)
        days_field.setMinimumWidth(0)
        days_layout = QHBoxLayout(days_field)
        days_layout.setContentsMargins(0, 0, 0, 0)
        days_layout.setSpacing(6)
        days_spin = SpinBox(page)
        days_spin.setObjectName("NapcatRecordDaysSpin")
        days_spin.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        days_spin.lineEdit().setObjectName("NapcatRecordDaysSpinEdit")
        days_spin.lineEdit().setFrame(False)
        days_spin.setRange(1, 3650)
        days_spin.setMinimumWidth(0)
        days_spin.setSizePolicy(QSizePolicy.Policy.Expanding, days_spin.sizePolicy().verticalPolicy())
        days_layout.addWidget(days_spin, 1)
        days_layout.addWidget(BodyLabel(_tr("SettingsWindow.napcat_retention_days_unit", default="天"), days_field))
        row.addWidget(days_field, 1, 1)
        delete_btn = PushButton(FluentIcon.DELETE, delete_label, page)
        delete_btn.setMinimumWidth(0)
        delete_btn.setSizePolicy(QSizePolicy.Policy.Expanding, delete_btn.sizePolicy().verticalPolicy())
        delete_btn.clicked.connect(on_delete)
        row.addWidget(delete_btn, 1, 2)
        layout.addWidget(field)
        mode_combo.currentIndexChanged.connect(
            lambda _i, c=mode_combo, s=days_spin: s.setEnabled((c.itemData(c.currentIndex()) or "") == "auto")
        )
        return mode_combo, days_spin

    def _set_combo_by_data(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _napcat_delete_group_records(self):
        self._napcat_delete_records(
            "group",
            _tr("SettingsWindow.napcat_delete_group_confirm_title", default="删除群聊记录"),
            _tr(
                "SettingsWindow.napcat_delete_group_confirm_content",
                default="确定要删除全部已保存的 QQ 群聊记录吗？此操作不可撤销。",
            ),
        )

    def _napcat_delete_private_records(self):
        self._napcat_delete_records(
            "private",
            _tr("SettingsWindow.napcat_delete_private_confirm_title", default="删除私聊记录"),
            _tr(
                "SettingsWindow.napcat_delete_private_confirm_content",
                default="确定要删除全部已保存的 QQ 私聊记录吗？此操作不可撤销。",
            ),
        )

    def _napcat_delete_records(self, chat_type: str, title: str, content: str):
        reply = QMessageBox.warning(
            self,
            title,
            content,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            db = DatabaseManager()
            try:
                result = db.delete_external_chat(chat_type=chat_type)
            finally:
                db.close()
        except Exception as exc:
            InfoBar.error(
                _tr("SettingsWindow.napcat_delete_failed_title", default="删除失败"),
                str(exc),
                duration=3500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        InfoBar.success(
            _tr("SettingsWindow.napcat_delete_done_title", default="已删除"),
            _tr(
                "SettingsWindow.napcat_delete_done_content",
                default="已删除 {count} 条记录。",
                count=int(result.get("deleted_messages", 0) if isinstance(result, dict) else 0),
            ),
            duration=2600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _napcat_widgets_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_napcat_enabled",
                "_napcat_ws_url_input",
                "_napcat_token_input",
                "_napcat_auto_reply_enabled",
                "_napcat_reply_private",
                "_napcat_reply_group_at_only",
                "_napcat_reply_mention_sender",
                "_napcat_save_policy_combo",
                "_napcat_group_retention_mode_combo",
                "_napcat_group_retention_days_spin",
                "_napcat_private_retention_mode_combo",
                "_napcat_private_retention_days_spin",
            )
        )

    def _load_napcat_config(self):
        if not self._cfg or not self._napcat_widgets_ready():
            return
        self._napcat_enabled.setChecked(bool(self._cfg.get("napcat_enabled", False)))
        self._napcat_ws_url_input.setText(str(self._cfg.get("napcat_ws_url", "ws://127.0.0.1:3001") or ""))
        self._napcat_token_input.setText(str(self._cfg.get("napcat_access_token", "") or ""))
        self._napcat_auto_reply_enabled.setChecked(bool(self._cfg.get("napcat_auto_reply_enabled", False)))
        self._napcat_reply_private.setChecked(bool(self._cfg.get("napcat_reply_private", True)))
        self._napcat_reply_group_at_only.setChecked(bool(self._cfg.get("napcat_reply_group_at_only", True)))
        self._napcat_reply_mention_sender.setChecked(bool(self._cfg.get("napcat_reply_mention_sender", True)))
        self._set_combo_by_data(self._napcat_save_policy_combo, str(self._cfg.get("napcat_save_policy", "all") or "all"))
        self._set_combo_by_data(self._napcat_group_retention_mode_combo, str(self._cfg.get("napcat_group_retention_mode", "manual") or "manual"))
        self._napcat_group_retention_days_spin.setValue(clamp_int(self._cfg.get("napcat_group_retention_days", 7), 1, 3650, 7))
        self._set_combo_by_data(self._napcat_private_retention_mode_combo, str(self._cfg.get("napcat_private_retention_mode", "manual") or "manual"))
        self._napcat_private_retention_days_spin.setValue(clamp_int(self._cfg.get("napcat_private_retention_days", 30), 1, 3650, 7))
        self._napcat_group_retention_days_spin.setEnabled(
            (self._napcat_group_retention_mode_combo.itemData(self._napcat_group_retention_mode_combo.currentIndex()) or "") == "auto"
        )
        self._napcat_private_retention_days_spin.setEnabled(
            (self._napcat_private_retention_mode_combo.itemData(self._napcat_private_retention_mode_combo.currentIndex()) or "") == "auto"
        )

    def _napcat_settings_data(self) -> dict:
        if not self._cfg:
            return {}
        return {
            "napcat_enabled": self._cfg.get("napcat_enabled", False),
            "napcat_ws_url": self._cfg.get("napcat_ws_url", "ws://127.0.0.1:3001"),
            "napcat_access_token": self._cfg.get("napcat_access_token", ""),
            "napcat_auto_reply_enabled": self._cfg.get("napcat_auto_reply_enabled", False),
            "napcat_reply_private": self._cfg.get("napcat_reply_private", True),
            "napcat_reply_group_at_only": self._cfg.get("napcat_reply_group_at_only", True),
            "napcat_reply_mention_sender": self._cfg.get("napcat_reply_mention_sender", True),
            "napcat_reply_character": self._cfg.get("napcat_reply_character", ""),
            "napcat_save_policy": self._cfg.get("napcat_save_policy", "all"),
            "napcat_group_retention_mode": self._cfg.get("napcat_group_retention_mode", "manual"),
            "napcat_group_retention_days": self._cfg.get("napcat_group_retention_days", 7),
            "napcat_private_retention_mode": self._cfg.get("napcat_private_retention_mode", "manual"),
            "napcat_private_retention_days": self._cfg.get("napcat_private_retention_days", 30),
        }

    def _save_napcat_into_cfg(self):
        if not self._cfg or not self._napcat_widgets_ready():
            return
        self._cfg.set("napcat_enabled", self._napcat_enabled.isChecked())
        self._cfg.set("napcat_ws_url", self._napcat_ws_url_input.text().strip())
        self._cfg.set("napcat_access_token", self._napcat_token_input.text().strip())
        self._cfg.set("napcat_auto_reply_enabled", self._napcat_auto_reply_enabled.isChecked())
        self._cfg.set("napcat_reply_private", self._napcat_reply_private.isChecked())
        self._cfg.set("napcat_reply_group_at_only", self._napcat_reply_group_at_only.isChecked())
        self._cfg.set("napcat_reply_mention_sender", self._napcat_reply_mention_sender.isChecked())
        self._cfg.set("napcat_save_policy", self._napcat_save_policy_combo.itemData(self._napcat_save_policy_combo.currentIndex()) or "all")
        self._cfg.set("napcat_group_retention_mode", self._napcat_group_retention_mode_combo.itemData(self._napcat_group_retention_mode_combo.currentIndex()) or "manual")
        self._cfg.set("napcat_group_retention_days", clamp_int(self._napcat_group_retention_days_spin.value(), 1, 3650, 7))
        self._cfg.set("napcat_private_retention_mode", self._napcat_private_retention_mode_combo.itemData(self._napcat_private_retention_mode_combo.currentIndex()) or "manual")
        self._cfg.set("napcat_private_retention_days", clamp_int(self._napcat_private_retention_days_spin.value(), 1, 3650, 7))

    def _test_napcat_connection(self):
        if not self._napcat_widgets_ready():
            return
        from PySide6.QtNetwork import QNetworkRequest
        from PySide6.QtWebSockets import QWebSocket

        ws_url = self._napcat_ws_url_input.text().strip()
        if not ws_url:
            InfoBar.warning(
                _tr("SettingsWindow.napcat_test_empty_title", default="缺少地址"),
                _tr("SettingsWindow.napcat_test_empty_content", default="请先填写 NapCat WebSocket 地址。"),
                duration=2200,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        token = self._napcat_token_input.text().strip()
        self._napcat_status_label.setText(_tr("SettingsWindow.napcat_status_connecting", default="连接中…"))

        socket = QWebSocket()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(4000)
        state = {"done": False}

        def finish(ok: bool, detail: str = ""):
            if state["done"]:
                return
            state["done"] = True
            timer.stop()
            try:
                socket.close()
            except RuntimeError:
                pass
            socket.deleteLater()
            if ok:
                self._napcat_status_label.setText(_tr("SettingsWindow.napcat_status_connected", default="已连接 ✓"))
                InfoBar.success(
                    _tr("SettingsWindow.napcat_test_success_title", default="连接成功"),
                    _tr("SettingsWindow.napcat_test_success_content", default="已成功连接到 NapCat WebSocket 服务器。"),
                    duration=2600,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            else:
                self._napcat_status_label.setText(_tr("SettingsWindow.napcat_status_failed", default="连接失败 ✗"))
                InfoBar.error(
                    _tr("SettingsWindow.napcat_test_failed_title", default="连接失败"),
                    _tr(
                        "SettingsWindow.napcat_test_failed_content",
                        default="无法连接到 NapCat。请确认已在 NapCat 开启 WebSocket 服务器、地址和 Token 正确。{error}",
                        error=detail,
                    ),
                    duration=4500,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )

        url = QUrl(ws_url)
        if token:
            query = url.query()
            token_param = f"access_token={token}"
            url.setQuery(f"{query}&{token_param}" if query else token_param)
        request = QNetworkRequest(url)
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode("utf-8"))
        socket.connected.connect(lambda: finish(True))
        socket.errorOccurred.connect(lambda _err: finish(False, socket.errorString()))
        timer.timeout.connect(lambda: finish(False, _tr("SettingsWindow.napcat_status_timeout", default="超时")))
        timer.start()
        socket.open(request)
