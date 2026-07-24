import json
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import QColorDialog, QFileDialog, QInputDialog, QMessageBox

from settings_window.constants import *
from plugin_system.paths import plugin_paths


def _pretty_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


class PluginManagementPageMixin:
    """Plugin manager and renderer for versioned declarative plugin UI."""

    def _build_plugins_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("pluginsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(TitleLabel(
            _tr("SettingsWindow.plugins_title", default="插件管理"), page
        ))
        subtitle = SubtitleLabel(_tr(
            "SettingsWindow.plugins_subtitle",
            default="安装 Python/Lua 受控插件或 Python 原生插件；更新始终需要手动确认。",
        ), page)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        warning = CardWidget(page)
        warning_layout = QVBoxLayout(warning)
        warning_layout.setContentsMargins(14, 12, 14, 12)
        warning_layout.addWidget(StrongBodyLabel(
            _tr("SettingsWindow.plugins_security_title", default="安全说明"), warning
        ))
        warning_text = BodyLabel(_tr(
            "SettingsWindow.plugins_security_text",
            default=(
                "受控 Python 插件具有权限代理和独立进程，但不是恶意代码安全沙箱；"
                "原生 Python 插件拥有完整宿主权限，等同运行第三方程序。"
            ),
        ), warning)
        warning_text.setWordWrap(True)
        warning_layout.addWidget(warning_text)
        layout.addWidget(warning)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        install_file = PushButton(_tr("SettingsWindow.plugins_install_file", default="安装 .bdplugin"), page)
        install_file.clicked.connect(self._plugin_install_file)
        toolbar.addWidget(install_file)
        install_folder = PushButton(_tr("SettingsWindow.plugins_install_folder", default="安装本地目录"), page)
        install_folder.clicked.connect(self._plugin_install_folder)
        toolbar.addWidget(install_folder)
        install_url = PushButton(_tr("SettingsWindow.plugins_install_url", default="从 URL 安装"), page)
        install_url.clicked.connect(self._plugin_install_url)
        toolbar.addWidget(install_url)
        toolbar.addStretch()
        refresh = PushButton(_tr("SettingsWindow.plugins_refresh", default="刷新"), page)
        refresh.clicked.connect(self._refresh_plugins_page)
        toolbar.addWidget(refresh)
        layout.addLayout(toolbar)

        self._plugins_status = BodyLabel("", page)
        self._plugins_status.setWordWrap(True)
        layout.addWidget(self._plugins_status)

        self._plugins_list = QWidget(page)
        self._plugins_list_layout = QVBoxLayout(self._plugins_list)
        self._plugins_list_layout.setContentsMargins(0, 0, 0, 0)
        self._plugins_list_layout.setSpacing(10)
        layout.addWidget(self._plugins_list)

        self._plugin_declared_ui = QWidget(page)
        self._plugin_declared_ui_layout = QVBoxLayout(self._plugin_declared_ui)
        self._plugin_declared_ui_layout.setContentsMargins(0, 8, 0, 0)
        self._plugin_declared_ui_layout.setSpacing(10)
        layout.addWidget(self._plugin_declared_ui)
        layout.addStretch()

        QTimer.singleShot(0, self._refresh_plugins_page)
        return page

    def _plugin_bridge_or_error(self):
        bridge = getattr(self, "_plugin_bridge", None)
        if bridge is None or not bridge.connect():
            self._plugins_status.setText(_tr(
                "SettingsWindow.plugins_supervisor_unavailable",
                default="插件监督器不可用；请确认主程序正在运行。",
            ))
            return None
        return bridge

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                PluginManagementPageMixin._clear_layout(child)

    def _plugin_admin(self, method: str, params=None):
        bridge = self._plugin_bridge_or_error()
        if bridge is None:
            return None
        try:
            return bridge.plugin_admin(method, params or {}, timeout_ms=120_000)
        except Exception as exc:
            QMessageBox.critical(
                self,
                _tr("SettingsWindow.plugins_error", default="插件操作失败"),
                str(exc),
            )
            return None

    def _refresh_plugins_page(self):
        if not hasattr(self, "_plugins_list_layout"):
            return
        plugins = self._plugin_admin("list")
        if plugins is None:
            return
        self._clear_layout(self._plugins_list_layout)
        self._plugins_status.setText(_tr(
            "SettingsWindow.plugins_count", default="已安装 {count} 个插件", count=len(plugins)
        ))
        if not plugins:
            empty = BodyLabel(_tr(
                "SettingsWindow.plugins_empty", default="尚未安装插件。"
            ), self._plugins_list)
            self._plugins_list_layout.addWidget(empty)
        for item in plugins:
            self._plugins_list_layout.addWidget(self._build_plugin_card(item))
        self._refresh_plugin_declared_ui()

    def _build_plugin_card(self, item: dict):
        card = CardWidget(self._plugins_list)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(15, 13, 15, 13)
        layout.setSpacing(8)
        active = item.get("active", {}) if isinstance(item.get("active"), dict) else {}
        manifest = active.get("manifest", {}) if isinstance(active.get("manifest"), dict) else {}
        scan = active.get("scan", {}) if isinstance(active.get("scan"), dict) else {}
        plugin_id = str(item.get("id", "") or "")
        name = str(manifest.get("name", plugin_id) or plugin_id)
        version = str(item.get("active_version", "") or "")
        execution = str(item.get("execution", "managed") or "managed")
        language = str(item.get("language", "") or "")
        risk = str(scan.get("risk", "info") or "info")

        title_row = QHBoxLayout()
        title_row.addWidget(StrongBodyLabel(f"{name}  {version}", card), 1)
        state_text = _tr("SettingsWindow.plugins_enabled", default="已启用") if item.get("enabled") else _tr("SettingsWindow.plugins_disabled", default="已停用")
        title_row.addWidget(BodyLabel(state_text, card))
        layout.addLayout(title_row)
        detail = BodyLabel(
            f"{plugin_id} · {language}/{execution} · risk={risk}"
            + f" · signature={scan.get('signature', {}).get('status', 'unsigned')}"
            + (" · " + _tr("SettingsWindow.plugins_restart_required", default="需要重启") if item.get("pending_restart") else ""),
            card,
        )
        detail.setWordWrap(True)
        layout.addWidget(detail)

        buttons = QHBoxLayout()
        toggle = PushButton(
            _tr("SettingsWindow.plugins_disable", default="停用") if item.get("enabled")
            else _tr("SettingsWindow.plugins_enable", default="启用"),
            card,
        )
        toggle.clicked.connect(lambda _checked=False, pid=plugin_id, enabled=not bool(item.get("enabled")): self._plugin_set_enabled(pid, enabled))
        buttons.addWidget(toggle)
        report = PushButton(_tr("SettingsWindow.plugins_report", default="扫描报告"), card)
        report.clicked.connect(lambda _checked=False, value=scan: self._show_plugin_report(value))
        buttons.addWidget(report)
        permissions = PushButton(_tr("SettingsWindow.plugins_permissions", default="权限"), card)
        permissions.clicked.connect(lambda _checked=False, value=item: self._edit_plugin_permissions(value))
        buttons.addWidget(permissions)
        update = PushButton(_tr("SettingsWindow.plugins_check_update", default="检查更新"), card)
        update.setEnabled(bool(manifest.get("update_url")))
        update.clicked.connect(lambda _checked=False, pid=plugin_id: self._plugin_check_update(pid))
        buttons.addWidget(update)
        rollback = PushButton(_tr("SettingsWindow.plugins_rollback", default="回滚"), card)
        rollback.setEnabled(bool(item.get("previous_version")))
        rollback.clicked.connect(lambda _checked=False, pid=plugin_id: self._plugin_rollback(pid))
        buttons.addWidget(rollback)
        open_data = PushButton(_tr("SettingsWindow.plugins_open_data", default="数据目录"), card)
        open_data.clicked.connect(lambda _checked=False, pid=plugin_id: self._open_plugin_data(pid))
        buttons.addWidget(open_data)
        open_log = PushButton(_tr("SettingsWindow.plugins_open_log", default="日志"), card)
        open_log.clicked.connect(lambda _checked=False, pid=plugin_id: self._open_plugin_log(pid))
        buttons.addWidget(open_log)
        remove = PushButton(_tr("SettingsWindow.plugins_uninstall", default="卸载"), card)
        remove.clicked.connect(lambda _checked=False, pid=plugin_id: self._plugin_uninstall(pid))
        buttons.addWidget(remove)
        buttons.addStretch()
        layout.addLayout(buttons)
        return card

    def _plugin_install_file(self):
        path, _selected = QFileDialog.getOpenFileName(
            self,
            _tr("SettingsWindow.plugins_install_file", default="安装 .bdplugin"),
            "",
            "BandoriPet Plugin (*.bdplugin *.zip);;All Files (*)",
        )
        if path:
            self._stage_and_confirm("stage_local", {"path": path})

    def _plugin_install_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, _tr("SettingsWindow.plugins_install_folder", default="安装本地目录")
        )
        if path:
            self._stage_and_confirm("stage_local", {"path": path})

    def _plugin_install_url(self):
        url, ok = QInputDialog.getText(
            self,
            _tr("SettingsWindow.plugins_install_url", default="从 URL 安装"),
            _tr("SettingsWindow.plugins_url_prompt", default="公共 HTTP/HTTPS 插件地址："),
        )
        if not ok or not url.strip():
            return
        allow_http = False
        if url.strip().lower().startswith("http://"):
            answer = QMessageBox.warning(
                self,
                _tr("SettingsWindow.plugins_http_title", default="不安全传输"),
                _tr("SettingsWindow.plugins_http_text", default="HTTP 可能被篡改。仍要下载吗？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            allow_http = answer == QMessageBox.StandardButton.Yes
            if not allow_http:
                return
        self._stage_and_confirm("stage_url", {"url": url.strip(), "allow_insecure_http": allow_http})

    def _stage_and_confirm(self, method: str, params: dict):
        preview = self._plugin_admin(method, params)
        if not isinstance(preview, dict):
            return
        report = preview.get("report", {})
        manifest = preview.get("manifest", {})
        if report.get("blocked"):
            self._show_plugin_report(report)
            self._plugin_admin("cancel", {"token": preview.get("token", "")})
            return
        signature = report.get("signature", {})
        warning = []
        if signature.get("status") == "unsigned":
            warning.append(_tr("SettingsWindow.plugins_unsigned", default="此插件未签名。"))
        if manifest.get("execution") == "native":
            warning.append(_tr(
                "SettingsWindow.plugins_native_warning",
                default="原生插件拥有完整宿主权限，启停和更新需要重启目标进程。",
            ))
        text = "\n".join([
            f"{manifest.get('name', manifest.get('id', ''))} {manifest.get('version', '')}",
            f"ID: {manifest.get('id', '')}",
            f"Language/execution: {manifest.get('language', '')}/{manifest.get('execution', '')}",
            f"Risk: {report.get('risk', 'info')}",
            *warning,
            "",
            _tr("SettingsWindow.plugins_permissions", default="权限") + ":\n" + _pretty_json(manifest.get("permissions", {})),
        ])
        answer = QMessageBox.question(
            self,
            _tr("SettingsWindow.plugins_confirm", default="确认安装插件"),
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._plugin_admin("cancel", {"token": preview.get("token", "")})
            return
        trust = False
        if str(signature.get("status", "")).startswith("valid") and not signature.get("trusted"):
            trust = QMessageBox.question(
                self,
                _tr("SettingsWindow.plugins_trust_publisher", default="信任发布者"),
                f"{signature.get('publisher', '')}\n{signature.get('fingerprint', '')}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        installed = self._plugin_admin("commit", {
            "token": preview.get("token", ""),
            "enable": True,
            "trust_publisher": trust,
        })
        if installed is not None:
            self._refresh_plugins_page()

    def _plugin_set_enabled(self, plugin_id: str, enabled: bool):
        if self._plugin_admin("set_enabled", {"plugin_id": plugin_id, "enabled": enabled}) is not None:
            self._refresh_plugins_page()

    def _show_plugin_report(self, report: dict):
        findings = report.get("findings", []) if isinstance(report, dict) else []
        lines = [
            f"Scanner: {report.get('scanner_version', '')}",
            f"SHA-256: {report.get('package_sha256', '')}",
            f"Risk: {report.get('risk', 'info')}",
            f"Signature: {report.get('signature', {}).get('status', 'unsigned')}",
            "",
        ]
        for finding in findings:
            lines.append(
                f"[{finding.get('severity', 'info').upper()}] {finding.get('rule', '')} "
                f"{finding.get('path', '')}:{finding.get('line', 0)}\n"
                f"{finding.get('message', '')}\n{finding.get('evidence', '')}\n"
                f"{finding.get('recommendation', '')}"
            )
        QMessageBox.information(
            self,
            _tr("SettingsWindow.plugins_report", default="扫描报告"),
            "\n\n".join(lines) if lines else _tr("SettingsWindow.plugins_no_report", default="没有扫描报告。"),
        )

    def _edit_plugin_permissions(self, item: dict):
        plugin_id = str(item.get("id", "") or "")
        if item.get("execution") == "native":
            QMessageBox.warning(
                self,
                _tr("SettingsWindow.plugins_native_permissions", default="原生插件权限"),
                _tr("SettingsWindow.plugins_native_permissions_text", default="原生插件始终拥有完整宿主权限；清单仅说明意图。"),
            )
            return
        current = item.get("granted_permissions", {})
        text, ok = QInputDialog.getMultiLineText(
            self,
            _tr("SettingsWindow.plugins_permissions", default="权限"),
            _tr("SettingsWindow.plugins_permissions_prompt", default="编辑已授予权限（不能超过清单声明）："),
            _pretty_json(current),
        )
        if not ok:
            return
        try:
            permissions = json.loads(text)
        except json.JSONDecodeError as exc:
            QMessageBox.critical(self, _tr("SettingsWindow.plugins_error", default="插件操作失败"), str(exc))
            return
        if self._plugin_admin("set_permissions", {"plugin_id": plugin_id, "permissions": permissions}) is not None:
            self._refresh_plugins_page()

    def _plugin_check_update(self, plugin_id: str):
        update = self._plugin_admin("check_update", {"plugin_id": plugin_id})
        if not isinstance(update, dict):
            return
        if not update.get("update_available"):
            QMessageBox.information(self, _tr("SettingsWindow.plugins_check_update", default="检查更新"), _tr("SettingsWindow.plugins_up_to_date", default="当前已是最新版本。"))
            return
        answer = QMessageBox.question(
            self,
            _tr("SettingsWindow.plugins_update_available", default="发现插件更新"),
            f"{update.get('current_version', '')} → {update.get('latest_version', '')}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            package_url = str(update.get("package_url", "") or "")
            allow_http = False
            if package_url.lower().startswith("http://"):
                allow_http = QMessageBox.warning(
                    self,
                    _tr("SettingsWindow.plugins_http_title", default="不安全传输"),
                    _tr("SettingsWindow.plugins_http_text", default="HTTP 可能被篡改。仍要下载吗？"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                ) == QMessageBox.StandardButton.Yes
                if not allow_http:
                    return
            self._stage_and_confirm("stage_url", {
                "url": package_url,
                "sha256": update.get("sha256", ""),
                "allow_insecure_http": allow_http,
            })

    def _plugin_rollback(self, plugin_id: str):
        if QMessageBox.question(self, _tr("SettingsWindow.plugins_rollback", default="回滚"), plugin_id) == QMessageBox.StandardButton.Yes:
            if self._plugin_admin("rollback", {"plugin_id": plugin_id}) is not None:
                self._refresh_plugins_page()

    def _plugin_uninstall(self, plugin_id: str):
        answer = QMessageBox.question(
            self,
            _tr("SettingsWindow.plugins_uninstall", default="卸载"),
            _tr("SettingsWindow.plugins_uninstall_keep_data", default="卸载插件？默认保留插件数据。") + f"\n{plugin_id}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            delete_data = QMessageBox.question(
                self,
                _tr("SettingsWindow.plugins_delete_data", default="删除插件数据"),
                _tr("SettingsWindow.plugins_delete_data_text", default="同时永久删除此插件保存的数据吗？"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
            if self._plugin_admin("uninstall", {"plugin_id": plugin_id, "delete_data": delete_data}) is not None:
                self._refresh_plugins_page()

    def _open_plugin_data(self, plugin_id: str):
        path = plugin_paths().data / plugin_id
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_plugin_log(self, plugin_id: str):
        paths = plugin_paths()
        log_path = paths.logs / f"{plugin_id}.log"
        target = log_path if log_path.is_file() else paths.logs
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _refresh_plugin_declared_ui(self):
        if not hasattr(self, "_plugin_declared_ui_layout"):
            return
        self._clear_layout(self._plugin_declared_ui_layout)
        bridge = self._plugin_bridge_or_error()
        contributions = bridge.contributions("ui", "settings_page") if bridge is not None else []
        native_loader = getattr(self, "_native_plugin_loader", None)
        native_widgets = (
            native_loader.create_widgets("settings_page", self._plugin_declared_ui)
            if native_loader is not None else []
        )
        if not contributions and not native_widgets:
            return
        self._plugin_declared_ui_layout.addWidget(TitleLabel(
            _tr("SettingsWindow.plugins_extension_settings", default="插件提供的设置"),
            self._plugin_declared_ui,
        ))
        for contribution in contributions:
            spec = contribution.get("spec", {})
            if not isinstance(spec, dict) or int(spec.get("schema_version", 1) or 1) != 1:
                continue
            card = CardWidget(self._plugin_declared_ui)
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(8)
            layout.addWidget(StrongBodyLabel(str(spec.get("title", spec.get("label", contribution.get("id", ""))) or ""), card))
            if spec.get("description"):
                description = BodyLabel(str(spec.get("description")), card)
                description.setWordWrap(True)
                layout.addWidget(description)
            children = spec.get("children", [])
            if not isinstance(children, list):
                children = []
            for control in children:
                if isinstance(control, dict):
                    self._render_plugin_control(layout, card, contribution, control)
            self._plugin_declared_ui_layout.addWidget(card)
        for widget in native_widgets:
            self._plugin_declared_ui_layout.addWidget(widget)

    def _render_plugin_control(self, layout, parent, contribution: dict, control: dict):
        kind = str(control.get("type", "text") or "text").lower()
        control_id = str(control.get("id", "") or "")
        label = str(control.get("label", control_id) or control_id)
        row = QHBoxLayout()
        if kind == "group":
            group = CardWidget(parent)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(12, 10, 12, 10)
            group_layout.setSpacing(7)
            if label:
                group_layout.addWidget(StrongBodyLabel(label, group))
            if control.get("description"):
                description = BodyLabel(str(control.get("description")), group)
                description.setWordWrap(True)
                group_layout.addWidget(description)
            children = control.get("children", [])
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        self._render_plugin_control(
                            group_layout, group, contribution, child
                        )
            layout.addWidget(group)
            return
        if kind == "text":
            text = BodyLabel(str(control.get("text", label) or ""), parent)
            text.setWordWrap(True)
            layout.addWidget(text)
            return

        def changed(value):
            bridge = getattr(self, "_plugin_bridge", None)
            if bridge is not None:
                bridge.notify_event("ui.changed", {
                    "plugin_id": contribution.get("plugin_id", ""),
                    "component_id": contribution.get("id", ""),
                    "control_id": control_id,
                    "value": value,
                })

        if kind == "button":
            widget = PushButton(label, parent)
            widget.clicked.connect(lambda _checked=False: changed(control.get("value", True)))
            row.addWidget(widget)
            row.addStretch()
            layout.addLayout(row)
            return

        row.addWidget(BodyLabel(label, parent), 1)
        if kind == "switch":
            widget = SwitchButton(parent)
            widget.setChecked(bool(control.get("value", False)))
            widget.checkedChanged.connect(changed)
        elif kind == "number":
            widget = SpinBox(parent)
            widget.setRange(int(control.get("min", -2147483648)), int(control.get("max", 2147483647)))
            widget.setValue(int(control.get("value", 0) or 0))
            widget.valueChanged.connect(changed)
        elif kind == "select":
            widget = ComboBox(parent)
            options = control.get("options", []) if isinstance(control.get("options"), list) else []
            for option in options:
                if isinstance(option, dict):
                    widget.addItem(str(option.get("label", option.get("value", ""))), userData=option.get("value"))
                else:
                    widget.addItem(str(option), userData=option)
            current = control.get("value")
            for index in range(widget.count()):
                if widget.itemData(index) == current:
                    widget.setCurrentIndex(index)
                    break
            widget.currentIndexChanged.connect(lambda index: changed(widget.itemData(index)))
        elif kind == "file":
            widget = PushButton(_tr("SettingsWindow.plugins_choose_file", default="选择文件"), parent)

            def choose_file():
                path, _selected = QFileDialog.getOpenFileName(self, label)
                if path:
                    changed(path)

            widget.clicked.connect(choose_file)
        elif kind == "color":
            widget = PushButton(str(control.get("value", "#ffffff") or "#ffffff"), parent)

            def choose_color():
                color = QColorDialog.getColor(QColor(widget.text()), self, label)
                if color.isValid():
                    widget.setText(color.name())
                    changed(color.name())

            widget.clicked.connect(choose_color)
        else:
            widget = LineEdit(parent)
            widget.setText(str(control.get("value", "") or ""))
            widget.editingFinished.connect(lambda: changed(widget.text()))
        row.addWidget(widget)
        layout.addLayout(row)
