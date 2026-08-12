from __future__ import annotations

import io
import socket
import ssl
import base64
import hashlib
from datetime import datetime

from qfluentwidgets import TextEdit as FluentTextEdit

from companion_security import CompanionSecurityStore, local_host_candidates
from config_manager import DEFAULT_USER_PROFILE_KEY
from settings_window.constants import *
from settings_window.widgets import *


class CompanionPageMixin:
    def _build_companion_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel(_tr("SettingsWindow.companion_title", default="手机互联"), page))
        layout.addWidget(_wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.companion_subtitle",
            default="让 Android 版通过加密连接共享当前桌面单聊、历史、动作和 TTS。桌面端始终保存并处理数据。",
        ), page)))

        enabled_row = QHBoxLayout()
        enabled_row.addWidget(BodyLabel(_tr("SettingsWindow.companion_enabled", default="启用桌面互联服务"), page))
        enabled_row.addStretch()
        self._companion_enabled = SwitchButton(page)
        enabled_row.addWidget(self._companion_enabled)
        layout.addLayout(enabled_row)

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addWidget(BodyLabel(_tr("SettingsWindow.companion_name", default="桌面名称"), page), 0, 0)
        self._companion_name = LineEdit(page)
        self._companion_name.setObjectName("companionDesktopNameInput")
        self._companion_name.setCustomFocusedBorderColor("#005fb8", "#60cdff")
        self._companion_name.setPlaceholderText(socket.gethostname())
        self._companion_name.setFixedHeight(36)
        form.addWidget(self._companion_name, 0, 1)
        form.addWidget(BodyLabel(_tr("SettingsWindow.companion_port", default="监听端口"), page), 1, 0)
        self._companion_port = LineEdit(page)
        self._companion_port.setObjectName("companionPortInput")
        self._companion_port.setCustomFocusedBorderColor("#005fb8", "#60cdff")
        self._companion_port.setValidator(QIntValidator(1024, 65535, self._companion_port))
        self._companion_port.setFixedHeight(36)
        form.addWidget(self._companion_port, 1, 1)
        form.addWidget(BodyLabel(_tr("SettingsWindow.companion_tts_route", default="TTS 播放位置"), page), 2, 0)
        self._companion_tts_route = OpaqueDropDownComboBox(page)
        self._companion_tts_route.addItem(_tr("SettingsWindow.companion_tts_origin", default="跟随发起端"), userData="origin")
        self._companion_tts_route.addItem(_tr("SettingsWindow.companion_tts_both", default="桌面与手机同时播放"), userData="both")
        self._companion_tts_route.setFixedHeight(36)
        form.addWidget(self._companion_tts_route, 2, 1)
        layout.addLayout(form)

        status = _wrap_label(BodyLabel("", page))
        self._companion_capability_status = status
        layout.addWidget(status)
        self._companion_service_status = _wrap_label(BodyLabel("", page))
        layout.addWidget(self._companion_service_status)

        button_row = QHBoxLayout()
        save_button = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.companion_save", default="保存互联设置"), page)
        save_button.clicked.connect(self._save_companion_config)
        pair_button = PushButton(FluentIcon.ADD, _tr("SettingsWindow.companion_pair", default="配对新手机"), page)
        pair_button.clicked.connect(self._generate_companion_pairing)
        button_row.addWidget(save_button)
        button_row.addWidget(pair_button)
        button_row.addStretch()
        layout.addLayout(button_row)

        self._companion_pairing_box = QWidget(page)
        pairing_layout = QHBoxLayout(self._companion_pairing_box)
        pairing_layout.setContentsMargins(0, 0, 0, 0)
        pairing_layout.setSpacing(16)
        self._companion_qr = QLabel(self._companion_pairing_box)
        self._companion_qr.setFixedSize(220, 220)
        self._companion_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pairing_layout.addWidget(self._companion_qr)
        pairing_text_layout = QVBoxLayout()
        pairing_text_layout.addWidget(_wrap_label(BodyLabel(_tr(
            "SettingsWindow.companion_pair_help",
            default="在 Android 版的“桌面互联”中扫描二维码。二维码两分钟后失效，并且只能使用一次。",
        ), self._companion_pairing_box)))
        self._companion_pairing_uri = FluentTextEdit(self._companion_pairing_box)
        self._companion_pairing_uri.setObjectName("companionPairingUriInput")
        self._companion_pairing_uri.setReadOnly(True)
        self._companion_pairing_uri.setFixedHeight(108)
        pairing_text_layout.addWidget(self._companion_pairing_uri)
        copy_button = PushButton(FluentIcon.COPY, _tr("SettingsWindow.companion_copy_pairing", default="复制完整配对串"), self._companion_pairing_box)
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self._companion_pairing_uri.toPlainText()))
        pairing_text_layout.addWidget(copy_button)
        pairing_text_layout.addStretch()
        pairing_layout.addLayout(pairing_text_layout, 1)
        self._companion_pairing_box.hide()
        layout.addWidget(self._companion_pairing_box)

        layout.addWidget(SubtitleLabel(_tr("SettingsWindow.companion_devices", default="已配对设备"), page))
        self._companion_devices_widget = QWidget(page)
        self._companion_devices_layout = QVBoxLayout(self._companion_devices_widget)
        self._companion_devices_layout.setContentsMargins(0, 0, 0, 0)
        self._companion_devices_layout.setSpacing(8)
        layout.addWidget(self._companion_devices_widget)
        layout.addStretch()

        self._load_companion_config()
        self._companion_status_timer = QTimer(page)
        self._companion_status_timer.setInterval(3000)
        self._companion_status_timer.timeout.connect(self._refresh_companion_service_status)
        self._companion_status_timer.start()
        return page

    def _load_companion_config(self):
        if not self._cfg:
            return
        self._companion_enabled.setChecked(bool(self._cfg.get("companion_enabled", False)))
        self._companion_name.setText(str(self._cfg.get("companion_device_name", "") or ""))
        self._companion_port.setText(str(self._cfg.get("companion_port", 38474) or 38474))
        route = str(self._cfg.get("companion_tts_routing", "origin") or "origin")
        for index in range(self._companion_tts_route.count()):
            if self._companion_tts_route.itemData(index) == route:
                self._companion_tts_route.setCurrentIndex(index)
                break
        llm_ready = bool(self._cfg.get("llm_api_url", "") and self._cfg.get("llm_api_key", "") and self._cfg.get("llm_model_id", ""))
        tts_ready = bool(self._cfg.get("tts_enabled", False))
        llm_status = "最近调用失败" if llm_ready and self._cfg.get("companion_llm_last_error", "") else ("已配置" if llm_ready else "未配置")
        tts_status = "最近调用失败" if tts_ready and self._cfg.get("companion_tts_last_error", "") else ("已配置" if tts_ready else "未配置")
        self._companion_capability_status.setText(_tr(
            "SettingsWindow.companion_capabilities",
            default="桌面能力：LLM {llm} · TTS {tts} · 记忆/好感度 可用 · 高权限工具 已禁用",
            llm=llm_status,
            tts=tts_status,
        ))
        self._refresh_companion_devices()
        self._refresh_companion_service_status()

    def _refresh_companion_service_status(self):
        if not self._cfg or not self._cfg.get("companion_enabled", False):
            self._companion_service_status.setText("服务状态：已停止")
            return
        port = max(1024, min(65535, int(self._cfg.get("companion_port", 38474) or 38474)))
        addresses = ", ".join(f"{host}:{port}" for host in local_host_candidates()) or f"127.0.0.1:{port}"
        state = "正在启动或端口不可用"
        try:
            _cert, _key, expected_pin = CompanionSecurityStore(self._cfg).ensure_tls_identity()
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with socket.create_connection(("127.0.0.1", port), timeout=0.25) as raw:
                with context.wrap_socket(raw, server_hostname="BandoriPet") as secure:
                    from cryptography import x509
                    from cryptography.hazmat.primitives import serialization
                    cert = x509.load_der_x509_certificate(secure.getpeercert(binary_form=True))
                    spki = cert.public_key().public_bytes(
                        serialization.Encoding.DER,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                    actual_pin = base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")
                    state = "运行中" if actual_pin == expected_pin else "端口被其他程序占用"
        except Exception:
            pass
        self._companion_service_status.setText(f"服务状态：{state} · 监听地址：{addresses}")

    def _save_companion_config(self, show_info=True) -> bool:
        if not self._cfg:
            return False
        try:
            port = max(1024, min(65535, int(self._companion_port.text().strip() or "38474")))
            self._companion_port.setText(str(port))
            self._cfg.set("companion_enabled", self._companion_enabled.isChecked())
            self._cfg.set("companion_port", port)
            self._cfg.set("companion_device_name", self._companion_name.text().strip() or socket.gethostname())
            self._cfg.set("companion_tts_routing", self._companion_tts_route.itemData(self._companion_tts_route.currentIndex()) or "origin")
            _require_config_saved(self._cfg)
        except Exception as exc:
            InfoBar.error(_tr("SettingsWindow.companion_save_failed", default="互联设置保存失败"), str(exc), duration=4000, position=InfoBarPosition.TOP, parent=self)
            return False
        signal = getattr(self, "settings_changed", None)
        if signal is not None:
            signal.emit({
                "companion_enabled": bool(self._cfg.get("companion_enabled", False)),
                "companion_port": port,
                "companion_device_name": str(self._cfg.get("companion_device_name", "") or ""),
                "companion_tts_routing": str(self._cfg.get("companion_tts_routing", "origin") or "origin"),
            })
        self._refresh_companion_service_status()
        if show_info:
            InfoBar.success(_tr("SettingsWindow.companion_saved", default="互联设置已保存"), _tr("SettingsWindow.companion_apply_hint", default="服务状态已更新。"), duration=2500, position=InfoBarPosition.TOP, parent=self)
        return True

    def _generate_companion_pairing(self):
        if not self._save_companion_config(show_info=False):
            return
        if not self._companion_enabled.isChecked():
            self._companion_enabled.setChecked(True)
            if not self._save_companion_config(show_info=False):
                return
        profile = self._cfg.active_user_profile() if hasattr(self._cfg, "active_user_profile") else {}
        profile_key = str(profile.get("key", "") or DEFAULT_USER_PROFILE_KEY)
        pairing = CompanionSecurityStore(self._cfg).issue_pairing(
            profile_key=profile_key,
            host_candidates=local_host_candidates() or ["127.0.0.1"],
            port=int(self._companion_port.text()),
        )
        uri = pairing["uri"]
        self._companion_pairing_uri.setPlainText(uri)
        try:
            import qrcode
            image = qrcode.make(uri).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            pixmap = QPixmap()
            pixmap.loadFromData(buffer.getvalue(), "PNG")
            self._companion_qr.setPixmap(pixmap.scaled(
                self._companion_qr.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        except Exception as exc:
            self._companion_qr.setText(str(exc))
        self._companion_pairing_box.show()

    def _refresh_companion_devices(self):
        layout = self._companion_devices_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        devices = [item for item in self._cfg.get("companion_paired_devices", []) if isinstance(item, dict)] if self._cfg else []
        if not devices:
            layout.addWidget(BodyLabel(_tr("SettingsWindow.companion_no_devices", default="尚未配对手机。"), self._companion_devices_widget))
            return
        for device in devices:
            row = QWidget(self._companion_devices_widget)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            name = str(device.get("name", "Android") or "Android")
            device_id = str(device.get("id", "") or "")
            last_seen = int(device.get("last_seen_at", 0) or 0)
            last_seen_text = datetime.fromtimestamp(last_seen / 1000).strftime("%Y-%m-%d %H:%M") if last_seen else "从未在线"
            row_layout.addWidget(BodyLabel(f"{name}  ·  {device_id[:8]}  ·  最后在线 {last_seen_text}", row))
            row_layout.addStretch()
            revoke = PushButton(FluentIcon.DELETE, _tr("SettingsWindow.companion_revoke", default="断开并撤销"), row)
            revoke.clicked.connect(lambda _checked=False, value=device_id: self._revoke_companion_device(value))
            row_layout.addWidget(revoke)
            layout.addWidget(row)

    def _revoke_companion_device(self, device_id: str):
        if self._cfg and CompanionSecurityStore(self._cfg).revoke(device_id):
            self._refresh_companion_devices()
            signal = getattr(self, "settings_changed", None)
            if signal is not None:
                signal.emit({
                    "companion_enabled": bool(self._cfg.get("companion_enabled", False)),
                    "companion_port": int(self._cfg.get("companion_port", 38474) or 38474),
                })
