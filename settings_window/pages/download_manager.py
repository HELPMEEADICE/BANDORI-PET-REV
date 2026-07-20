from pathlib import Path

from settings_window.constants import *
from settings_window.workers import ModelPackageDownloadWorker
from model_manager import BAND_JSON, OUTFIT_JSON, has_valid_model_directory, model_lookup_dirs


def discover_download_model_sources(
    search_dirs=None,
    *,
    cancelled=None,
) -> dict[str, dict[str, list[Path]]]:
    """Return direct model package entries, retaining both archive and folder sources."""
    sources: dict[str, dict[str, list[Path]]] = {}
    for root in search_dirs if search_dirs is not None else model_lookup_dirs():
        if cancelled is not None and cancelled():
            break
        try:
            entries = sorted(Path(root).iterdir())
        except OSError:
            continue
        for entry in entries:
            if cancelled is not None and cancelled():
                return sources
            if entry.name.startswith(('.', '_')):
                continue
            if entry.is_file() and entry.suffix.lower() == '.zst':
                kind = 'archives'
                character = entry.stem
            elif entry.is_dir() and _contains_model_manifest(entry, cancelled=cancelled):
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


def _contains_model_manifest(path: Path, *, cancelled=None) -> bool:
    if cancelled is not None and cancelled():
        return False
    try:
        return has_valid_model_directory(path)
    except OSError:
        return False


def _path_size(paths: list[Path], *, cancelled=None) -> int:
    total = 0
    for path in paths:
        if cancelled is not None and cancelled():
            break
        try:
            if path.is_file():
                total += path.stat().st_size
            elif path.is_dir():
                for child in path.rglob('*'):
                    if cancelled is not None and cancelled():
                        return total
                    try:
                        if child.is_file():
                            total += child.stat().st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def scan_download_model_sources(search_dirs=None, *, cancelled=None) -> dict[str, dict]:
    """Discover local model sources and calculate sizes away from the UI thread."""
    sources = discover_download_model_sources(search_dirs, cancelled=cancelled)
    for source in sources.values():
        if cancelled is not None and cancelled():
            return {}
        source['archive_size'] = _path_size(source['archives'], cancelled=cancelled)
        source['folder_size'] = _path_size(source['folders'], cancelled=cancelled)
    return sources


class DownloadManagerScanWorker(QThread):
    """Build a filesystem snapshot without blocking settings navigation."""

    def __init__(self, search_dirs=None, parent=None):
        super().__init__(parent)
        self._search_dirs = tuple(search_dirs) if search_dirs is not None else None
        self.sources = None

    def run(self):
        sources = scan_download_model_sources(
            self._search_dirs,
            cancelled=self.isInterruptionRequested,
        )
        if not self.isInterruptionRequested():
            self.sources = sources


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
            lambda _checked=False: self._refresh_download_management_page(force=True)
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

        self._download_manager_list = QWidget(page)
        self._download_manager_list_layout = QVBoxLayout(self._download_manager_list)
        self._download_manager_list_layout.setContentsMargins(0, 0, 0, 0)
        self._download_manager_list_layout.setSpacing(12)
        layout.addWidget(self._download_manager_list)
        layout.addStretch()

        self._download_manager_action_buttons = {}
        self._download_manager_rows = {}
        self._download_manager_loaded = False
        self._download_manager_render_generation = 0
        self._download_manager_render_queue = []
        self._download_manager_summary.setText(
            f"{_tr('SettingsWindow.download_management_refresh', default='刷新')}…"
        )
        self._connect_theme_changed(self._restyle_download_manager_badges)
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

    def _download_manager_entries(self, sources: dict[str, dict]) -> list[dict]:
        catalog = self._download_manager_catalog()
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
                'archive_size': int(source.get('archive_size') or 0),
                'folder_size': int(source.get('folder_size') or 0),
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

    def _refresh_download_management_page(self, force: bool = False):
        if not hasattr(self, '_download_manager_list_layout'):
            return
        if getattr(self, '_download_manager_workers', {}):
            return
        if getattr(self, '_download_manager_loaded', False) and not force:
            return
        scan_worker = getattr(self, '_download_manager_scan_worker', None)
        if scan_worker is not None:
            return

        self._download_manager_refresh_btn.setEnabled(False)
        if not getattr(self, '_download_manager_loaded', False):
            self._download_manager_summary.setText(
                f"{_tr('SettingsWindow.download_management_refresh', default='刷新')}…"
            )
        worker = DownloadManagerScanWorker(parent=self)
        self._download_manager_scan_worker = worker
        worker.finished.connect(
            lambda worker=worker: self._on_download_manager_scan_finished(worker)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_download_manager_scan_finished(self, worker):
        if worker is not getattr(self, '_download_manager_scan_worker', None):
            return
        self._download_manager_scan_worker = None
        sources = worker.sources
        if sources is None:
            if not getattr(self, '_download_manager_workers', {}):
                self._download_manager_refresh_btn.setEnabled(True)
            return
        self._download_manager_loaded = True
        self._populate_download_management_page(
            self._download_manager_entries(sources)
        )

    def _populate_download_management_page(self, entries: list[dict]):
        self._download_manager_render_generation += 1
        generation = self._download_manager_render_generation
        while self._download_manager_list_layout.count():
            item = self._download_manager_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._download_manager_action_buttons = {}
        self._download_manager_rows = {}

        downloaded = sum(bool(entry['archives'] or entry['folders']) for entry in entries)
        self._download_manager_summary.setText(_tr(
            'SettingsWindow.download_management_summary',
            default='已下载 {downloaded}/{total} 个模型记录',
            downloaded=downloaded,
            total=len(entries),
        ))
        render_queue = []
        for band_name, band_entries in self._group_download_manager_entries(entries):
            render_queue.append(('band', band_name))
            for entry in band_entries:
                render_queue.append(('entry', entry))
        self._download_manager_render_queue = render_queue
        QTimer.singleShot(
            0,
            lambda generation=generation: self._render_download_manager_batch(generation),
        )

    def _render_download_manager_batch(self, generation: int):
        if generation != getattr(self, '_download_manager_render_generation', 0):
            return
        queue = self._download_manager_render_queue
        batch = queue[:6]
        del queue[:6]
        for kind, value in batch:
            if kind == 'band':
                self._download_manager_list_layout.addWidget(
                    SubtitleLabel(value, self._download_manager_list)
                )
            else:
                self._download_manager_list_layout.addWidget(
                    self._create_download_manager_card(value)
                )
        if queue:
            QTimer.singleShot(
                0,
                lambda generation=generation: self._render_download_manager_batch(generation),
            )
            return
        if (
            getattr(self, '_download_manager_scan_worker', None) is None
            and not getattr(self, '_download_manager_workers', {})
        ):
            self._download_manager_refresh_btn.setEnabled(True)

    def _restyle_download_manager_badges(self):
        for row in getattr(self, '_download_manager_rows', {}).values():
            self._style_download_manager_badge(row['badge'], row['entry'])

    def _create_download_manager_card(self, entry: dict) -> QWidget:
        card = CardWidget(self._download_manager_list)
        card.setObjectName('downloadManagerCard')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

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
        row.addLayout(text_column, 1)

        badge = BodyLabel(self._download_manager_source_label(entry), card)
        badge.setObjectName('downloadManagerBadge')
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(26)
        badge.setMinimumWidth(72)
        self._style_download_manager_badge(badge, entry)
        row.addWidget(badge)

        action = self._download_manager_action(entry)
        button = None
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
            row.addWidget(button)
        layout.addLayout(row)

        progress = ProgressBar(card)
        progress.hide()
        layout.addWidget(progress)
        progress_label = BodyLabel('', card)
        progress_label.hide()
        layout.addWidget(progress_label)
        self._download_manager_rows[entry['character']] = {
            'entry': entry,
            'detail': detail,
            'badge': badge,
            'button': button,
            'progress': progress,
            'progress_label': progress_label,
        }
        return card

    def _download_manager_entry_detail(self, entry: dict) -> str:
        descriptions = []
        if entry['archives']:
            descriptions.append(_tr(
                'SettingsWindow.download_management_archive_detail',
                default='ZST 包 {size}',
                size=_format_file_size(entry.get('archive_size', 0)),
            ))
        if entry['folders']:
            descriptions.append(_tr(
                'SettingsWindow.download_management_folder_detail',
                default='文件夹 {size}',
                size=_format_file_size(entry.get('folder_size', 0)),
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
        workers = getattr(self, '_download_manager_workers', None)
        if workers is None:
            workers = self._download_manager_workers = {}
        if character in workers:
            return
        row = self._download_manager_rows.get(character)
        if not row:
            return
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._download_manager_refresh_btn.setEnabled(False)
        button = row.get('button')
        if button is not None:
            button.setEnabled(False)
        progress = row['progress']
        progress.setRange(0, 0)
        progress.show()
        progress_label = row['progress_label']
        progress_label.setText(_tr(
            'SettingsWindow.download_management_downloading',
            default='正在下载 {character}...',
            character=character,
        ))
        progress_label.show()

        worker = ModelPackageDownloadWorker(
            [character], MODELS_DIR, parent=self, overwrite=force,
        )
        workers[character] = worker
        worker.progress.connect(self._on_download_manager_progress)
        worker.finished.connect(self._on_download_manager_finished)
        worker.error.connect(self._on_download_manager_error)
        worker.start()

    def _download_manager_character_for_worker(self, worker) -> str:
        for character, active_worker in self._download_manager_workers.items():
            if active_worker is worker:
                return character
        return ''

    def _on_download_manager_progress(self, info: dict):
        character = self._download_manager_character_for_worker(self.sender())
        if not character:
            character = str(info.get('current') or '')
        row = self._download_manager_rows.get(character)
        if not row:
            return
        total = int(info.get('total_bytes') or 0)
        downloaded = int(info.get('downloaded_bytes') or 0)
        progress = row['progress']
        if total > 0:
            progress.setRange(0, total)
            progress.setValue(min(downloaded, total))
        else:
            progress.setRange(0, 0)
        row['progress_label'].setText(_tr(
            'SettingsWindow.download_management_progress',
            default='正在下载 {character}：{speed}',
            character=character,
            speed=self._format_download_speed(float(info.get('speed') or 0.0)),
        ))

    def _on_download_manager_finished(self, result: dict):
        character = self._download_manager_character_for_worker(self.sender())
        if not character:
            return
        failed = result.get('failed', []) or []
        self._finish_download_manager_operation(character)
        all_finished = not self._download_manager_workers
        if failed:
            self._show_download_manager_error(character, '; '.join(failed[:3]))
            if all_finished:
                self._rescan_download_manager_models()
            InfoBar.error(
                _tr('SettingsWindow.download_management_failed_title', default='模型包下载失败'),
                '; '.join(failed[:3]),
                duration=6000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._mark_download_manager_card_complete(character)
        if all_finished:
            self._rescan_download_manager_models()
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
        character = self._download_manager_character_for_worker(self.sender())
        if not character:
            return
        self._finish_download_manager_operation(character)
        self._show_download_manager_error(character, message)
        if not self._download_manager_workers:
            self._rescan_download_manager_models()
        InfoBar.error(
            _tr('SettingsWindow.download_management_failed_title', default='模型包下载失败'),
            message,
            duration=6000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _finish_download_manager_operation(self, character: str):
        worker = self._download_manager_workers.pop(character, None)
        if worker is not None:
            worker.deleteLater()
        row = self._download_manager_rows.get(character)
        if row:
            row['progress'].setRange(0, 100)
            row['progress'].hide()
            row['progress_label'].hide()
            button = row.get('button')
            if button is not None:
                button.setEnabled(True)
        if not self._download_manager_workers:
            self._download_manager_refresh_btn.setEnabled(True)

    def _show_download_manager_error(self, character: str, message: str):
        row = self._download_manager_rows.get(character)
        if not row:
            return
        row['progress_label'].setText(message)
        row['progress_label'].show()

    def _mark_download_manager_card_complete(self, character: str):
        row = self._download_manager_rows.get(character)
        if not row:
            return
        entry = row['entry']
        archive = MODELS_DIR / f'{character}.zst'
        entry['archives'] = [archive] if archive.exists() else entry['archives']
        if archive.exists():
            try:
                entry['archive_size'] = archive.stat().st_size
            except OSError:
                pass
        entry['catalogued'] = True
        row['detail'].setText(self._download_manager_entry_detail(entry))
        row['badge'].setText(self._download_manager_source_label(entry))
        self._style_download_manager_badge(row['badge'], entry)
        button = row.get('button')
        if button is not None:
            button.setText(_tr('SettingsWindow.download_management_update', default='更新'))
            button.setIcon(FluentIcon.SYNC.icon())

    def _rescan_download_manager_models(self):
        self._model_manager = ModelManager()
        self._update_wizard_model_status()
        self._update_wizard_footer()
