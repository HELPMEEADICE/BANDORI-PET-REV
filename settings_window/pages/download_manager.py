from pathlib import Path

from settings_window.constants import *
from settings_window.workers import ModelPackageDownloadWorker
from model_manager import BAND_JSON, OUTFIT_JSON, model_lookup_dirs


def discover_download_model_sources(search_dirs=None) -> dict[str, dict[str, list[Path]]]:
    """Return direct model package entries, retaining both archive and folder sources."""
    sources: dict[str, dict[str, list[Path]]] = {}
    for root in search_dirs if search_dirs is not None else model_lookup_dirs():
        try:
            entries = sorted(Path(root).iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(('.', '_')):
                continue
            if entry.is_file() and entry.suffix.lower() == '.zst':
                kind = 'archives'
                character = entry.stem
            elif entry.is_dir() and _contains_model_manifest(entry):
                kind = 'folders'
                character = entry.name
            else:
                continue
            if not character:
                continue
            source = sources.setdefault(character, {'archives': [], 'folders': []})
            resolved = entry.resolve()
            if resolved not in source[kind]:
                source[kind].append(resolved)
    return sources


def _contains_model_manifest(path: Path) -> bool:
    try:
        return any(path.rglob('model.json')) or any(path.rglob('*.model3.json'))
    except OSError:
        return False


def _path_size(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            if path.is_file():
                total += path.stat().st_size
            elif path.is_dir():
                total += sum(
                    child.stat().st_size
                    for child in path.rglob('*')
                    if child.is_file()
                )
        except OSError:
            continue
    return total


def _format_file_size(size: int) -> str:
    amount = float(max(0, int(size)))
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if amount < 1024 or unit == 'TB':
            return f'{int(amount)} {unit}' if unit == 'B' else f'{amount:.1f} {unit}'
        amount /= 1024
    return f'{int(size)} B'


class DownloadManagementPageMixin:

    def _build_download_management_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName('downloadManagementPage')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        layout.addWidget(TitleLabel(
            _tr('SettingsWindow.download_management_title', default='下载管理'),
            page,
        ))
        layout.addWidget(_wrap_label(SubtitleLabel(
            _tr(
                'SettingsWindow.download_management_subtitle',
                default='按乐队查看本地模型和可下载的模型记录。ZST 模型包可在此重新下载更新。',
            ),
            page,
        )))

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self._download_manager_summary = BodyLabel('', page)
        self._download_manager_summary.setWordWrap(True)
        toolbar.addWidget(self._download_manager_summary, 1)
        self._download_manager_refresh_btn = PushButton(
            FluentIcon.SYNC,
            _tr('SettingsWindow.download_management_refresh', default='刷新'),
            page,
        )
        self._download_manager_refresh_btn.setFixedHeight(36)
        self._download_manager_refresh_btn.clicked.connect(
            self._refresh_download_management_page
        )
        toolbar.addWidget(self._download_manager_refresh_btn)
        open_folder_btn = PushButton(
            FluentIcon.FOLDER,
            _tr('SettingsWindow.download_management_open_folder', default='打开 models 文件夹'),
            page,
        )
        open_folder_btn.setFixedHeight(36)
        open_folder_btn.clicked.connect(self._open_models_dir)
        toolbar.addWidget(open_folder_btn)
        layout.addLayout(toolbar)

        self._download_manager_progress = ProgressBar(page)
        self._download_manager_progress.hide()
        layout.addWidget(self._download_manager_progress)
        self._download_manager_progress_label = BodyLabel('', page)
        self._download_manager_progress_label.hide()
        layout.addWidget(self._download_manager_progress_label)

        self._download_manager_list = QWidget(page)
        self._download_manager_list_layout = QVBoxLayout(self._download_manager_list)
        self._download_manager_list_layout.setContentsMargins(0, 0, 0, 0)
        self._download_manager_list_layout.setSpacing(12)
        layout.addWidget(self._download_manager_list)
        layout.addStretch()

        self._download_manager_action_buttons = {}
        self._refresh_download_management_page()
        self._connect_theme_changed(self._refresh_download_management_page)
        return page

    def _download_manager_catalog(self) -> dict[str, dict]:
        catalog = {}
        try:
            data = json.loads(OUTFIT_JSON.read_text(encoding='utf-8'))
            characters = data.get('characters', {})
        except (OSError, json.JSONDecodeError, ValueError):
            characters = {}
        if isinstance(characters, dict):
            for character, info in characters.items():
                key = str(character or '').strip()
                if not key:
                    continue
                details = info if isinstance(info, dict) else {}
                catalog[key] = {
                    'character': key,
                    'display': str(details.get('display') or key),
                    'catalogued': True,
                }
        for model in self._configured_models:
            character = str(model.get('character') or '').strip()
            if character:
                catalog.setdefault(character, {
                    'character': character,
                    'display': self._model_manager.get_display_name(character),
                    'catalogued': True,
                })
        return catalog

    @staticmethod
    def _download_manager_band_data() -> list[dict]:
        try:
            data = json.loads(BAND_JSON.read_text(encoding='utf-8'))
            bands = data.get('bands', [])
        except (OSError, json.JSONDecodeError, ValueError):
            bands = []
        return [band for band in bands if isinstance(band, dict)]

    def _download_manager_entries(self) -> list[dict]:
        catalog = self._download_manager_catalog()
        sources = discover_download_model_sources()
        for character in sources:
            catalog.setdefault(character, {
                'character': character,
                'display': self._model_manager.get_display_name(character),
                'catalogued': False,
            })
        entries = []
        for character, metadata in catalog.items():
            source = sources.get(character, {'archives': [], 'folders': []})
            entries.append({
                **metadata,
                'archives': source['archives'],
                'folders': source['folders'],
            })
        return entries

    def _group_download_manager_entries(self, entries: list[dict]) -> list[tuple[str, list[dict]]]:
        by_character = {entry['character']: entry for entry in entries}
        grouped = []
        assigned = set()
        for band in self._download_manager_band_data():
            characters = [
                by_character[character]
                for character in band.get('characters', [])
                if character in by_character
            ]
            if characters:
                grouped.append((str(band.get('display') or band.get('id') or ''), characters))
                assigned.update(entry['character'] for entry in characters)
        remaining = sorted(
            (entry for entry in entries if entry['character'] not in assigned),
            key=lambda entry: entry['display'].casefold(),
        )
        if remaining:
            grouped.append((
                _tr('ModelManager.custom_models_band', default='自定义模型'),
                remaining,
            ))
        return grouped

    def _refresh_download_management_page(self):
        if not hasattr(self, '_download_manager_list_layout'):
            return
        if getattr(self, '_download_manager_worker', None) is not None:
            return
        while self._download_manager_list_layout.count():
            item = self._download_manager_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._download_manager_action_buttons = {}

        entries = self._download_manager_entries()
        downloaded = sum(bool(entry['archives'] or entry['folders']) for entry in entries)
        self._download_manager_summary.setText(_tr(
            'SettingsWindow.download_management_summary',
            default='已下载 {downloaded}/{total} 个模型记录',
            downloaded=downloaded,
            total=len(entries),
        ))
        for band_name, band_entries in self._group_download_manager_entries(entries):
            band_label = SubtitleLabel(band_name, self._download_manager_list)
            self._download_manager_list_layout.addWidget(band_label)
            for entry in band_entries:
                self._download_manager_list_layout.addWidget(
                    self._create_download_manager_card(entry)
                )

    def _create_download_manager_card(self, entry: dict) -> QWidget:
        card = CardWidget(self._download_manager_list)
        card.setObjectName('downloadManagerCard')
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(4)
        text_column.addWidget(StrongBodyLabel(entry['display'], card))
        detail = BodyLabel(self._download_manager_entry_detail(entry), card)
        detail.setObjectName('downloadManagerDetail')
        detail.setWordWrap(True)
        detail.setToolTip('\n'.join(
            str(path) for path in [*entry['archives'], *entry['folders']]
        ))
        text_column.addWidget(detail)
        layout.addLayout(text_column, 1)

        badge = BodyLabel(self._download_manager_source_label(entry), card)
        badge.setObjectName('downloadManagerBadge')
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(26)
        badge.setMinimumWidth(72)
        self._style_download_manager_badge(badge, entry)
        layout.addWidget(badge)

        action = self._download_manager_action(entry)
        if action:
            is_update = action == 'update'
            button_type = PushButton if is_update else PrimaryPushButton
            button = button_type(
                FluentIcon.SYNC if is_update else FluentIcon.DOWNLOAD,
                _tr(
                    'SettingsWindow.download_management_update' if is_update else 'SettingsWindow.download_management_download',
                    default='更新' if is_update else '下载',
                ),
                card,
            )
            button.setFixedHeight(34)
            button.clicked.connect(
                lambda checked=False, character=entry['character'], force=is_update:
                self._start_download_manager_package(character, force)
            )
            self._download_manager_action_buttons[entry['character']] = button
            layout.addWidget(button)
        return card

    def _download_manager_entry_detail(self, entry: dict) -> str:
        descriptions = []
        if entry['archives']:
            descriptions.append(_tr(
                'SettingsWindow.download_management_archive_detail',
                default='ZST 包 {size}',
                size=_format_file_size(_path_size(entry['archives'])),
            ))
        if entry['folders']:
            descriptions.append(_tr(
                'SettingsWindow.download_management_folder_detail',
                default='文件夹 {size}',
                size=_format_file_size(_path_size(entry['folders'])),
            ))
        if not descriptions:
            descriptions.append(_tr(
                'SettingsWindow.download_management_record_detail',
                default='尚未下载，已有模型记录',
            ))
        return f"{entry['character']} · {' · '.join(descriptions)}"

    @staticmethod
    def _download_manager_action(entry: dict) -> str:
        if entry['archives']:
            return 'update'
        if entry['catalogued'] and not entry['folders']:
            return 'download'
        return ''

    @staticmethod
    def _download_manager_source_label(entry: dict) -> str:
        if entry['archives'] and entry['folders']:
            return _tr('SettingsWindow.download_management_source_both', default='ZST + 文件夹')
        if entry['archives']:
            return _tr('SettingsWindow.download_management_source_zst', default='ZST 包')
        if entry['folders']:
            return _tr('SettingsWindow.download_management_source_folder', default='文件夹')
        return _tr('SettingsWindow.download_management_source_record', default='未下载')

    @staticmethod
    def _style_download_manager_badge(badge: QLabel, entry: dict):
        dark = isDarkTheme()
        if entry['archives']:
            background = '#3a2d41' if dark else '#f6e7ef'
            foreground = '#f59ac0' if dark else '#b42364'
        elif entry['folders']:
            background = '#243a35' if dark else '#e5f5ef'
            foreground = '#71d4b3' if dark else '#087a5b'
        else:
            background = '#333333' if dark else '#eef0f4'
            foreground = '#b7bdc8' if dark else '#667085'
        badge.setStyleSheet(f'''
            QLabel#downloadManagerBadge {{
                color: {foreground};
                background: {background};
                border-radius: 8px;
                font-weight: 700;
                padding: 0 8px;
            }}
        ''')

    def _start_download_manager_package(self, character: str, force: bool):
        if getattr(self, '_download_manager_worker', None) is not None:
            return
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._download_manager_active_character = character
        self._download_manager_refresh_btn.setEnabled(False)
        for button in self._download_manager_action_buttons.values():
            button.setEnabled(False)
        self._download_manager_progress.setRange(0, 0)
        self._download_manager_progress.show()
        self._download_manager_progress_label.setText(_tr(
            'SettingsWindow.download_management_downloading',
            default='正在下载 {character}...',
            character=character,
        ))
        self._download_manager_progress_label.show()

        worker = ModelPackageDownloadWorker(
            [character], MODELS_DIR, parent=self, overwrite=force,
        )
        self._download_manager_worker = worker
        worker.progress.connect(self._on_download_manager_progress)
        worker.finished.connect(self._on_download_manager_finished)
        worker.error.connect(self._on_download_manager_error)
        worker.start()

    def _on_download_manager_progress(self, info: dict):
        total = int(info.get('total_bytes') or 0)
        downloaded = int(info.get('downloaded_bytes') or 0)
        if total > 0:
            self._download_manager_progress.setRange(0, total)
            self._download_manager_progress.setValue(min(downloaded, total))
        else:
            self._download_manager_progress.setRange(0, 0)
        self._download_manager_progress_label.setText(_tr(
            'SettingsWindow.download_management_progress',
            default='正在下载 {character}：{speed}',
            character=self._download_manager_active_character,
            speed=self._format_download_speed(float(info.get('speed') or 0.0)),
        ))

    def _on_download_manager_finished(self, result: dict):
        failed = result.get('failed', []) or []
        character = self._download_manager_active_character
        self._finish_download_manager_operation()
        if failed:
            self._download_manager_progress_label.setText('; '.join(failed[:3]))
            InfoBar.error(
                _tr('SettingsWindow.download_management_failed_title', default='模型包下载失败'),
                '; '.join(failed[:3]),
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._recheck_model_resources(show_message=False)
        self._refresh_download_management_page()
        InfoBar.success(
            _tr('SettingsWindow.download_management_done_title', default='模型包已更新'),
            _tr(
                'SettingsWindow.download_management_done_content',
                default='{character} 已下载完成并重新扫描。',
                character=character,
            ),
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_download_manager_error(self, message: str):
        self._finish_download_manager_operation()
        self._download_manager_progress_label.setText(message)
        InfoBar.error(
            _tr('SettingsWindow.download_management_failed_title', default='模型包下载失败'),
            message,
            duration=6000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _finish_download_manager_operation(self):
        self._download_manager_worker = None
        self._download_manager_refresh_btn.setEnabled(True)
        for button in self._download_manager_action_buttons.values():
            button.setEnabled(True)
        self._download_manager_progress.setRange(0, 100)
        self._download_manager_progress.hide()
        self._download_manager_progress_label.hide()
