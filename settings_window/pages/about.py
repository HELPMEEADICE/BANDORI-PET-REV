from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class AboutPageMixin:
    def _build_about_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("aboutPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        hero = QWidget(page)
        hero.setObjectName("aboutHero")
        hero.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(18)

        icon_path = _app_icon_path()
        if icon_path:
            icon_label = QLabel(hero)
            icon_label.setObjectName("aboutHeroIcon")
            icon_label.setFixedSize(84, 84)
            icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_label.setPixmap(QIcon(icon_path).pixmap(72, 72))
            hero_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        hero_text = QVBoxLayout()
        hero_text.setContentsMargins(0, 0, 0, 0)
        hero_text.setSpacing(8)
        title = TitleLabel(_tr("SettingsWindow.about_title"), hero)
        subtitle = SubtitleLabel(_tr("SettingsWindow.about_subtitle"), hero)
        subtitle.setWordWrap(True)
        desc = BodyLabel(_tr("SettingsWindow.about_desc"), hero)
        desc.setWordWrap(True)
        version = BodyLabel(_tr("SettingsWindow.about_version", version=APP_VERSION), hero)
        version.setObjectName("aboutVersion")
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_text.addWidget(desc)
        hero_text.addWidget(version)
        hero_layout.addLayout(hero_text, 1)
        layout.addWidget(hero)

        info_card = QWidget(page)
        info_card.setObjectName("aboutInfoCard")
        info_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.setSpacing(10)

        license_label = BodyLabel(_tr("SettingsWindow.about_license"), info_card)
        license_label.setWordWrap(True)
        info_layout.addWidget(license_label)

        disclaimer = BodyLabel(_tr("SettingsWindow.about_disclaimer"), info_card)
        disclaimer.setWordWrap(True)
        info_layout.addWidget(disclaimer)
        layout.addWidget(info_card)

        link_label = QLabel(
            _tr(
                "SettingsWindow.about_links",
                repo=PROJECT_REPO_URL,
                license=PROJECT_LICENSE_URL,
            ),
            info_card,
        )
        link_label.setWordWrap(True)
        link_label.setTextFormat(Qt.TextFormat.RichText)
        link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        link_label.setOpenExternalLinks(True)
        self._style_about_link(link_label)
        qconfig.themeChanged.connect(lambda: self._style_about_link(link_label))
        info_layout.addWidget(link_label)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 2, 0, 0)
        btn_row.setSpacing(10)
        repo_btn = TransparentPushButton(FluentIcon.GITHUB, _tr("SettingsWindow.about_open_repo"), info_card)
        repo_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_REPO_URL)))
        license_btn = TransparentPushButton(FluentIcon.HELP, _tr("SettingsWindow.about_open_license"), info_card)
        license_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_LICENSE_URL)))
        btn_row.addWidget(repo_btn)
        btn_row.addWidget(license_btn)
        btn_row.addStretch()
        info_layout.addLayout(btn_row)

        qq_group = "1046229865"
        qq_row = QHBoxLayout()
        qq_row.setContentsMargins(0, 2, 0, 0)
        qq_row.setSpacing(10)
        qq_label = BodyLabel(_tr("SettingsWindow.about_qq_group", qq_group=qq_group), info_card)
        qq_label.setWordWrap(True)
        qq_btn = TransparentPushButton(FluentIcon.PEOPLE, _tr("SettingsWindow.about_open_qq_group"), info_card)
        qq_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(PROJECT_QQ_GROUP_URL)))
        qq_row.addWidget(qq_label)
        qq_row.addWidget(qq_btn)
        qq_row.addStretch()
        info_layout.addLayout(qq_row)

        update_card = QWidget(page)
        update_card.setObjectName("aboutUpdateCard")
        update_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        update_layout = QVBoxLayout(update_card)
        update_layout.setContentsMargins(18, 16, 18, 16)
        update_layout.setSpacing(10)

        update_title = StrongBodyLabel(_tr("SettingsWindow.update_title"), update_card)
        update_layout.addWidget(update_title)

        self._update_status_label = BodyLabel(
            _tr(
                "SettingsWindow.update_idle",
                channel=self._update_channel_label(detect_update_channel()),
            ),
            update_card,
        )
        self._update_status_label.setWordWrap(True)
        update_layout.addWidget(self._update_status_label)

        self._update_detail_label = BodyLabel(_tr("SettingsWindow.update_hint"), update_card)
        self._update_detail_label.setObjectName("aboutUpdateDetail")
        self._update_detail_label.setWordWrap(True)
        update_layout.addWidget(self._update_detail_label)

        update_btn_row = QHBoxLayout()
        update_btn_row.setContentsMargins(0, 2, 0, 0)
        update_btn_row.setSpacing(10)
        self._check_update_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.update_check"), update_card)
        self._check_update_btn.clicked.connect(self._check_for_app_updates)
        self._apply_update_btn = PrimaryPushButton(FluentIcon.ACCEPT, _tr("SettingsWindow.update_apply"), update_card)
        self._apply_update_btn.setEnabled(False)
        self._apply_update_btn.clicked.connect(self._apply_pending_app_update)
        update_btn_row.addWidget(self._check_update_btn)
        update_btn_row.addWidget(self._apply_update_btn)
        update_btn_row.addStretch()
        update_layout.addLayout(update_btn_row)
        layout.addWidget(update_card)

        tech = BodyLabel(_tr("SettingsWindow.about_tech"), page)
        tech.setObjectName("aboutTech")
        tech.setWordWrap(True)
        layout.addWidget(tech)

        self._style_about_page(page)
        qconfig.themeChanged.connect(lambda: self._style_about_page(page))
        layout.addStretch()
        return page

    @staticmethod
    def _style_about_page(page: QWidget):
        dark = isDarkTheme()
        hero_bg = "#2b1730" if dark else "#fff0f6"
        hero_border = "#5f2a43" if dark else "#ffd1e2"
        card_bg = "#242424" if dark else "#ffffff"
        card_border = "#3a3a3a" if dark else "#ead8df"
        icon_bg = "#3d1d31" if dark else "#ffffff"
        page_bg = _BG_DARK if dark else _BG_LIGHT
        text = "#f8f4f7" if dark else "#231f24"
        muted = "#cbb8c4" if dark else "#6f5b68"
        page.setStyleSheet(f"""
            QWidget#aboutPage {{
                background: {page_bg};
            }}
            QWidget#aboutHero {{
                background: {hero_bg};
                border: 1px solid {hero_border};
                border-radius: 18px;
            }}
            QLabel#aboutHeroIcon {{
                background: {icon_bg};
                border: 1px solid {hero_border};
                border-radius: 20px;
            }}
            QWidget#aboutInfoCard {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 14px;
            }}
            QWidget#aboutUpdateCard {{
                background: {card_bg};
                border: 1px solid {card_border};
                border-radius: 14px;
            }}
            QWidget#aboutHero TitleLabel {{ color: {text}; }}
            QWidget#aboutHero SubtitleLabel {{ color: {text}; font-weight: 700; }}
            QWidget#aboutHero BodyLabel {{ color: {muted}; font-size: 13px; line-height: 1.5; }}
            BodyLabel#aboutVersion {{ color: {text}; font-weight: 700; }}
            QWidget#aboutInfoCard BodyLabel {{ color: {text}; font-size: 13px; }}
            QWidget#aboutUpdateCard BodyLabel {{ color: {text}; font-size: 13px; }}
            QWidget#aboutUpdateCard BodyLabel#aboutUpdateDetail {{ color: {muted}; }}
            BodyLabel#aboutTech {{ color: {muted}; font-size: 13px; padding: 2px 4px; }}
        """)

    @staticmethod
    def _style_about_link(label: QLabel):
        color = BANDORI_PRIMARY_DARK if isDarkTheme() else BANDORI_PRIMARY
        text = "#dcdcdc" if isDarkTheme() else "#303030"
        label.setStyleSheet(f"QLabel {{ color: {text}; font-size: 13px; }} QLabel a {{ color: {color}; }}")

    def _update_channel_label(self, channel: str) -> str:
        return _tr(
            f"SettingsWindow.update_channel_{channel}",
            default=_tr("SettingsWindow.update_channel_unknown"),
        )

    def _check_for_app_updates(self):
        worker = getattr(self, "_update_check_worker", None)
        if worker is not None and worker.isRunning():
            return
        self._pending_update_info = None
        self._check_update_btn.setEnabled(False)
        self._apply_update_btn.setEnabled(False)
        self._apply_update_btn.setText(_tr("SettingsWindow.update_apply"))
        self._update_status_label.setText(_tr("SettingsWindow.update_checking"))
        self._update_detail_label.setText("")

        self._update_check_worker = UpdateCheckWorker(parent=self)
        self._update_check_worker.finished.connect(self._on_app_update_checked)
        self._update_check_worker.error.connect(self._on_app_update_check_error)
        self._update_check_worker.start()

    def _on_app_update_checked(self, info):
        self._update_check_worker = None
        self._check_update_btn.setEnabled(True)
        self._pending_update_info = info if info.can_update else None

        if info.update_available:
            latest = info.latest_version or info.summary
            self._update_status_label.setText(
                _tr("SettingsWindow.update_available", version=latest)
            )
            if info.can_update:
                self._apply_update_btn.setEnabled(True)
                self._apply_update_btn.setText(
                    _tr("SettingsWindow.update_apply_version", version=latest)
                )
            else:
                self._apply_update_btn.setEnabled(False)
                self._apply_update_btn.setText(_tr("SettingsWindow.update_apply"))
        else:
            self._update_status_label.setText(_tr("SettingsWindow.update_none"))
            self._apply_update_btn.setEnabled(False)
            self._apply_update_btn.setText(_tr("SettingsWindow.update_apply"))

        self._update_detail_label.setText(self._format_update_detail(info))

    def _on_app_update_check_error(self, message: str):
        self._update_check_worker = None
        self._check_update_btn.setEnabled(True)
        self._apply_update_btn.setEnabled(False)
        self._update_status_label.setText(_tr("SettingsWindow.update_failed"))
        self._update_detail_label.setText(message)
        InfoBar.error(
            _tr("SettingsWindow.update_failed"),
            message,
            duration=5000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _format_update_detail(self, info) -> str:
        parts = []
        if info.channel:
            parts.append(
                _tr(
                    "SettingsWindow.update_channel_line",
                    channel=self._update_channel_label(info.channel),
                )
            )
        if info.asset_name:
            size = self._format_update_size(info.asset_size)
            parts.append(
                _tr(
                    "SettingsWindow.update_asset_line",
                    asset=info.asset_name,
                    size=size,
                )
            )
        detail = (info.detail or info.summary or "").strip()
        if detail:
            if len(detail) > 420:
                detail = detail[:420].rstrip() + "..."
            parts.append(detail)
        return "\n".join(parts) if parts else _tr("SettingsWindow.update_hint")

    @staticmethod
    def _format_update_size(size: int) -> str:
        if not size:
            return "-"
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"

    def _apply_pending_app_update(self):
        info = getattr(self, "_pending_update_info", None)
        if info is None or not info.can_update:
            return
        worker = getattr(self, "_update_apply_worker", None)
        if worker is not None and worker.isRunning():
            return

        reply = QMessageBox.warning(
            self,
            _tr("SettingsWindow.update_confirm_title"),
            _tr("SettingsWindow.update_confirm_content"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._check_update_btn.setEnabled(False)
        self._apply_update_btn.setEnabled(False)
        self._update_status_label.setText(_tr("SettingsWindow.update_applying"))
        self._update_detail_label.setText("")

        self._update_apply_worker = UpdateApplyWorker(info, parent=self)
        self._update_apply_worker.finished.connect(self._on_app_update_applied)
        self._update_apply_worker.error.connect(self._on_app_update_apply_error)
        self._update_apply_worker.start()

    def _on_app_update_applied(self, result):
        self._update_apply_worker = None
        self._check_update_btn.setEnabled(True)
        self._apply_update_btn.setEnabled(False)
        self._update_status_label.setText(_tr("SettingsWindow.update_apply_success"))
        self._update_detail_label.setText(result.message)
        InfoBar.success(
            _tr("SettingsWindow.update_apply_success"),
            result.message,
            duration=5000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
        if result.exits_app:
            app = QApplication.instance()
            if app is not None:
                QTimer.singleShot(800, app.quit)

    def _on_app_update_apply_error(self, message: str):
        self._update_apply_worker = None
        self._check_update_btn.setEnabled(True)
        self._apply_update_btn.setEnabled(getattr(self, "_pending_update_info", None) is not None)
        self._update_status_label.setText(_tr("SettingsWindow.update_apply_failed"))
        self._update_detail_label.setText(message)
        InfoBar.error(
            _tr("SettingsWindow.update_apply_failed"),
            message,
            duration=7000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
