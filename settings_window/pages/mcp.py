from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class MCPPageMixin:

    def _build_mcp_computer_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("mcpComputerPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.mcp_computer_title", default="智能工具与电脑控制"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.mcp_computer_subtitle",
            default="支持服务商原生 MCP，也支持 Chat Completions 的 tool_calls/function calling，把 MCP 和 Computer Use 转成兼容工具。",
        ), page))
        layout.addWidget(subtitle)
        capability_hint = _wrap_label(BodyLabel(_tr(
            "SettingsWindow.mcp_capability_hint",
            default="提示：启用 MCP 或 Computer Use 只是把工具提供给模型；必须使用支持 tool_calls/function calling 的模型才会调用工具，截图理解还需要模型支持多模态输入。",
        ), page))
        layout.addWidget(capability_hint)

        risk_panel = QWidget(page)
        risk_panel.setObjectName("mcpRiskPanel")
        risk_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        risk_layout = QVBoxLayout(risk_panel)
        risk_layout.setContentsMargins(12, 10, 12, 10)
        risk_layout.setSpacing(4)
        risk_layout.addWidget(StrongBodyLabel(_tr("SettingsWindow.computer_use_risk_title", default="风险提示"), risk_panel))
        risk_layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.computer_use_risk_text",
            default=(
                "Computer Use 会把屏幕截图发送给模型，并可按你的授权移动鼠标、点击、输入文本或按快捷键。"
                "只在可信任务中开启；不要让模型接触密码、支付、删除、购买、发帖等不可逆操作。"
            ),
        ), risk_panel)))
        layout.addWidget(risk_panel)

        self._llm_hide_tool_call_details = SwitchButton(page)
        self._add_switch_row(
            layout,
            page,
            _tr("SettingsWindow.llm_hide_tool_call_details", default="沉浸模式隐藏工具细节"),
            self._llm_hide_tool_call_details,
        )
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_hide_tool_call_details_hint",
            default="开启后会提示模型不要在角色回复里说出 MCP、工具调用、function calling、Computer Use 等实现细节。",
        ), page)))

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.mcp_title", default="MCP 接口"), page))
        self._llm_mcp_enabled = SwitchButton(page)
        self._llm_mcp_use_native = SwitchButton(page)
        self._add_switch_row(layout, page, _tr("SettingsWindow.llm_mcp_enabled", default="启用 MCP 工具"), self._llm_mcp_enabled)
        self._add_switch_row(layout, page, _tr("SettingsWindow.llm_mcp_use_native", default="OpenAI Responses 优先使用原生 MCP"), self._llm_mcp_use_native)
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_mcp_use_native_hint",
            default="原生 MCP 只对支持该工具的服务商生效；DeepSeek、OpenRouter 等兼容接口会走本地 MCP 代理工具。",
        ), page)))

        layout.addWidget(BodyLabel(_tr("SettingsWindow.llm_mcp_servers", default="MCP 服务器 JSON（纯文本）"), page))
        self._llm_mcp_servers_text = JsonCodeEdit(page)
        self._llm_mcp_servers_text.setPlaceholderText(self._default_mcp_servers_json())
        self._llm_mcp_servers_text.setFixedHeight(260)
        layout.addWidget(self._llm_mcp_servers_text)
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.llm_mcp_servers_hint",
            default="这里是纯文本 JSON，只读取字符内容；支持 stdio、本地/远程 HTTP 代理，以及 OpenAI Responses 原生 native/server_url 配置。",
        ), page)))

        mcp_btn_row = QHBoxLayout()
        guide_btn = PushButton(FluentIcon.INFO, _tr("SettingsWindow.mcp_open_guide", default="打开教程"), page)
        guide_btn.clicked.connect(self._open_mcp_guide)
        format_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.mcp_format_json", default="格式化 JSON"), page)
        format_btn.clicked.connect(self._format_mcp_servers_json)
        copy_btn = PushButton(FluentIcon.COPY, _tr("SettingsWindow.mcp_copy_json", default="复制 JSON"), page)
        copy_btn.clicked.connect(self._copy_mcp_servers_json)
        test_mcp_btn = PushButton(FluentIcon.WIFI, _tr("SettingsWindow.mcp_test_connection", default="测试 MCP 连接"), page)
        test_mcp_btn.clicked.connect(self._test_mcp_connection)
        mcp_btn_row.addWidget(guide_btn)
        mcp_btn_row.addWidget(format_btn)
        mcp_btn_row.addWidget(copy_btn)
        mcp_btn_row.addWidget(test_mcp_btn)
        mcp_btn_row.addStretch()
        layout.addLayout(mcp_btn_row)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.computer_use_title", default="Computer Use 权限"), page))
        self._computer_use_enabled = SwitchButton(page)
        self._computer_use_auto_detect = SwitchButton(page)
        self._computer_use_send_screenshots = SwitchButton(page)
        self._computer_use_allow_screenshot = SwitchButton(page)
        self._computer_use_allow_mouse = SwitchButton(page)
        self._computer_use_allow_keyboard = SwitchButton(page)
        self._computer_use_allow_clipboard = SwitchButton(page)
        self._computer_use_allow_wait = SwitchButton(page)
        for label, widget in (
            (_tr("SettingsWindow.computer_use_enabled", default="启用 Computer Use"), self._computer_use_enabled),
            (_tr("SettingsWindow.computer_use_auto_detect", default="让模型按自然语义自行判断是否使用"), self._computer_use_auto_detect),
            (_tr("SettingsWindow.computer_use_send_screenshots", default="向模型发送操作后的截图"), self._computer_use_send_screenshots),
            (_tr("SettingsWindow.computer_use_allow_screenshot", default="允许截屏"), self._computer_use_allow_screenshot),
            (_tr("SettingsWindow.computer_use_allow_mouse", default="允许鼠标移动、点击、滚动"), self._computer_use_allow_mouse),
            (_tr("SettingsWindow.computer_use_allow_keyboard", default="允许键盘输入和快捷键"), self._computer_use_allow_keyboard),
            (_tr("SettingsWindow.computer_use_allow_clipboard", default="允许剪贴板写入"), self._computer_use_allow_clipboard),
            (_tr("SettingsWindow.computer_use_allow_wait", default="允许等待/暂停"), self._computer_use_allow_wait),
        ):
            self._add_switch_row(layout, page, label, widget)

        screenshot_row = QHBoxLayout()
        screenshot_row.setSpacing(8)
        screenshot_row.addWidget(BodyLabel(_tr("SettingsWindow.computer_use_max_screenshot_width", default="截图最长边像素"), page))
        self._computer_use_max_screenshot_width = FluentContextLineEdit(page)
        self._computer_use_max_screenshot_width.setValidator(QIntValidator(640, 1920, self._computer_use_max_screenshot_width))
        self._computer_use_max_screenshot_width.setFixedHeight(34)
        self._computer_use_max_screenshot_width.setMaximumWidth(120)
        screenshot_row.addWidget(self._computer_use_max_screenshot_width)
        screenshot_row.addStretch()
        layout.addLayout(screenshot_row)
        layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.computer_use_hint",
            default="DeepSeek/OpenRouter 等兼容接口会通过 tool_calls/function calling 使用这些能力。模型需要支持图片输入，才能稳定理解屏幕截图；鼠标工具会把截图坐标映射到真实桌面坐标。",
        ), page)))

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.clicked.connect(self._save_mcp_computer_config)
        layout.addWidget(save_btn, 0, Qt.AlignmentFlag.AlignRight)
        layout.addStretch()

        self._load_mcp_computer_config()
        self._style_mcp_computer_page(page)
        qconfig.themeChanged.connect(lambda: self._style_mcp_computer_page(page))
        return page

    def _add_switch_row(self, layout: QVBoxLayout, page: QWidget, label: str, switch: SwitchButton):
        row = QHBoxLayout()
        row.addWidget(BodyLabel(label, page))
        row.addStretch()
        row.addWidget(switch)
        layout.addLayout(row)

    def _style_mcp_computer_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        risk_bg = "#2a2022" if dark else "#fff4e5"
        risk_border = "#8a5b20" if dark else "#ffd599"
        text_border = "#4a4a4a" if dark else "#d8d8d8"
        input_bg = "#2b2b2b" if dark else "#ffffff"
        text = "#f7f7fb" if dark else "#1f2328"
        page.setStyleSheet(f"""
            QWidget#mcpComputerPage {{
                background: {page_bg};
            }}
            #mcpRiskPanel {{
                background: {risk_bg};
                border: 1px solid {risk_border};
                border-radius: 8px;
            }}
            #mcpRiskPanel QLabel {{
                background: transparent;
            }}
            QTextEdit, QPlainTextEdit, QLineEdit {{
                color: {text};
                background: {input_bg};
                border: 1px solid {text_border};
                border-radius: 6px;
                padding: 6px;
            }}
            QPlainTextEdit#JsonCodeEdit {{
                padding-left: 0px;
                selection-background-color: {BANDORI_PRIMARY};
            }}
        """)
        self._refresh_theme_widget_styles(page)
        self._refresh_json_code_edit_theme(getattr(self, "_llm_mcp_servers_text", None))

    def _mcp_computer_widgets_ready(self) -> bool:
        return all(
            hasattr(self, name)
            for name in (
                "_llm_hide_tool_call_details",
                "_llm_mcp_enabled",
                "_llm_mcp_use_native",
                "_llm_mcp_servers_text",
                "_computer_use_enabled",
                "_computer_use_auto_detect",
                "_computer_use_send_screenshots",
                "_computer_use_allow_screenshot",
                "_computer_use_allow_mouse",
                "_computer_use_allow_keyboard",
                "_computer_use_allow_clipboard",
                "_computer_use_allow_wait",
                "_computer_use_max_screenshot_width",
            )
        )

    def _default_mcp_servers_json(self) -> str:
        project_dir = str(app_base_dir()).replace("\\", "/")
        sample = [
            {
                "enabled": True,
                "label": "filesystem",
                "transport": "stdio",
                "command": "python",
                "args": ["filesystem_mcp_server.py", "~/Documents"],
                "cwd": project_dir,
                "allowed_tools": [],
                "require_approval": "always",
            },
            {
                "enabled": True,
                "label": "remote_docs",
                "transport": "native",
                "url": "https://example.com/mcp",
                "allowed_tools": [],
                "require_approval": "never",
            },
        ]
        return json.dumps(sample, ensure_ascii=False, indent=2)

    def _load_mcp_computer_config(self):
        if not self._cfg or not self._mcp_computer_widgets_ready():
            return
        self._llm_hide_tool_call_details.setChecked(bool(self._cfg.get("llm_hide_tool_call_details", True)))
        self._llm_mcp_enabled.setChecked(bool(self._cfg.get("llm_mcp_enabled", False)))
        self._llm_mcp_use_native.setChecked(bool(self._cfg.get("llm_mcp_use_native", True)))
        servers = self._cfg.get("llm_mcp_servers", [])
        self._llm_mcp_servers_text.setPlainText(json.dumps(servers if isinstance(servers, list) else [], ensure_ascii=False, indent=2))
        self._computer_use_enabled.setChecked(bool(self._cfg.get("computer_use_enabled", False)))
        self._computer_use_auto_detect.setChecked(bool(self._cfg.get("computer_use_auto_detect", True)))
        self._computer_use_send_screenshots.setChecked(bool(self._cfg.get("computer_use_send_screenshots", True)))
        self._computer_use_allow_screenshot.setChecked(bool(self._cfg.get("computer_use_allow_screenshot", True)))
        self._computer_use_allow_mouse.setChecked(bool(self._cfg.get("computer_use_allow_mouse", False)))
        self._computer_use_allow_keyboard.setChecked(bool(self._cfg.get("computer_use_allow_keyboard", False)))
        self._computer_use_allow_clipboard.setChecked(bool(self._cfg.get("computer_use_allow_clipboard", False)))
        self._computer_use_allow_wait.setChecked(bool(self._cfg.get("computer_use_allow_wait", True)))
        self._computer_use_max_screenshot_width.setText(str(self._cfg.get("computer_use_max_screenshot_width", 1280)))

    def _parse_mcp_servers_text(self) -> list[dict] | None:
        text = self._llm_mcp_servers_text.toPlainText().strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            InfoBar.error(
                _tr("SettingsWindow.mcp_json_invalid_title", default="MCP JSON 有误"),
                _tr("SettingsWindow.mcp_json_invalid_content", default="请检查 JSON 格式：{error}", error=str(exc)),
                duration=3500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        if not isinstance(data, list):
            InfoBar.error(
                _tr("SettingsWindow.mcp_json_invalid_title", default="MCP JSON 有误"),
                _tr("SettingsWindow.mcp_json_must_be_list", default="MCP 服务器配置必须是数组。"),
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return None
        return data

    def _format_mcp_servers_json(self):
        if not self._mcp_computer_widgets_ready():
            return
        data = self._parse_mcp_servers_text()
        if data is None:
            return
        self._llm_mcp_servers_text.setPlainText(json.dumps(data, ensure_ascii=False, indent=2))

    def _copy_mcp_servers_json(self):
        if not self._mcp_computer_widgets_ready():
            return
        QApplication.clipboard().setText(self._llm_mcp_servers_text.toPlainText())
        InfoBar.success(
            _tr("SettingsWindow.mcp_json_copied_title", default="已复制"),
            _tr("SettingsWindow.mcp_json_copied_content", default="MCP JSON 已复制为纯文本。"),
            duration=1600,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _test_mcp_connection(self):
        if not self._mcp_computer_widgets_ready():
            return
        servers = self._parse_mcp_servers_text()
        if servers is None:
            return
        if not self._llm_mcp_enabled.isChecked():
            InfoBar.warning(
                _tr("SettingsWindow.mcp_test_disabled_title", default="MCP 未启用"),
                _tr("SettingsWindow.mcp_test_disabled_content", default="请先打开\u201c启用 MCP 工具\u201d，再测试连接。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if not any(isinstance(server, dict) and server.get("enabled", True) for server in servers):
            InfoBar.warning(
                _tr("SettingsWindow.mcp_test_empty_title", default="没有可测试的 MCP"),
                _tr("SettingsWindow.mcp_test_empty_content", default="MCP 服务器 JSON 里没有启用的服务器。"),
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        if hasattr(self, "_mcp_test_worker") and self._mcp_test_worker is not None and self._mcp_test_worker.isRunning():
            self._mcp_test_worker.quit()
            self._mcp_test_worker.wait(2000)
        config = {
            "llm_mcp_enabled": True,
            "llm_mcp_use_native": self._llm_mcp_use_native.isChecked(),
            "llm_mcp_servers": servers,
        }
        self._mcp_test_worker = McpConnectionTestWorker(config, parent=self)
        self._mcp_test_worker.finished.connect(self._on_mcp_test_finished)
        self._mcp_test_worker.error.connect(self._on_mcp_test_error)
        self._mcp_test_worker.start()

    def _on_mcp_test_finished(self, details: str):
        InfoBar.success(
            _tr("SettingsWindow.mcp_test_success_title", default="MCP 连接成功"),
            details,
            duration=6000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_mcp_test_error(self, details: str):
        InfoBar.error(
            _tr("SettingsWindow.mcp_test_failed_title", default="MCP 连接失败"),
            details,
            duration=8000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _open_mcp_guide(self):
        path = os.path.join(app_base_dir(), "MCP_COMPUTER_USE_GUIDE.md")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _save_mcp_computer_config(self, show_info: bool = True):
        if not self._cfg or not self._mcp_computer_widgets_ready():
            return
        servers = self._parse_mcp_servers_text()
        if servers is None:
            return
        try:
            max_width = int(self._computer_use_max_screenshot_width.text().strip() or "1280")
        except ValueError:
            max_width = 1280
        max_width = max(640, min(1920, max_width))
        self._cfg.set("llm_hide_tool_call_details", self._llm_hide_tool_call_details.isChecked())
        self._cfg.set("llm_mcp_enabled", self._llm_mcp_enabled.isChecked())
        self._cfg.set("llm_mcp_use_native", self._llm_mcp_use_native.isChecked())
        self._cfg.set("llm_mcp_servers", servers)
        self._cfg.set("computer_use_enabled", self._computer_use_enabled.isChecked())
        self._cfg.set("computer_use_auto_detect", self._computer_use_auto_detect.isChecked())
        self._cfg.set("computer_use_send_screenshots", self._computer_use_send_screenshots.isChecked())
        self._cfg.set("computer_use_max_screenshot_width", max_width)
        self._cfg.set("computer_use_allow_screenshot", self._computer_use_allow_screenshot.isChecked())
        self._cfg.set("computer_use_allow_mouse", self._computer_use_allow_mouse.isChecked())
        self._cfg.set("computer_use_allow_keyboard", self._computer_use_allow_keyboard.isChecked())
        self._cfg.set("computer_use_allow_clipboard", self._computer_use_allow_clipboard.isChecked())
        self._cfg.set("computer_use_allow_wait", self._computer_use_allow_wait.isChecked())
        self._cfg.save()
        if show_info:
            InfoBar.success(
                _tr("SettingsWindow.mcp_saved_title", default="智能工具与电脑控制已保存"),
                _tr("SettingsWindow.mcp_saved_content", default="新的工具配置会在下一次聊天请求时生效。"),
                duration=2200,
                position=InfoBarPosition.TOP,
                parent=self,
            )
