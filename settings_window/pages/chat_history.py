import html
import re

from PySide6.QtCore import QDate, QModelIndex, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ListView, ProgressRing

from settings_window.constants import *
from settings_window.widgets import *


class _ChatHistoryWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, db_factory, query_params: dict, parent=None):
        super().__init__(parent)
        self._db_factory = db_factory
        self._query_params = query_params

    def run(self):
        try:
            db = self._db_factory()
            params = self._query_params
            action = params.pop("action", "search")
            if action == "filters":
                result = db.get_chat_history_filter_options()
            else:
                result = db.search_chat_history(**params)
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class ChatHistoryModel:
    """聊天记录数据模型，管理记录列表和分页状态"""

    def __init__(self):
        self.records: list[dict] = []
        self.total: int = 0
        self.has_more: bool = False
        self.keyword: str = ""

    def clear(self):
        self.records.clear()
        self.total = 0
        self.has_more = False

    def append_records(self, records: list[dict]):
        self.records.extend(records)

    def set_result(self, result: dict):
        self.total = result.get("total", -1)
        self.has_more = result.get("has_more", False)

    @property
    def shown_count(self) -> int:
        return len(self.records)


class ChatHistoryDelegate(QStyledItemDelegate):
    """聊天记录渲染代理，使用 QPainter 绘制卡片"""

    _CARD_RADIUS = 10
    _CARD_PADDING_H = 14
    _CARD_PADDING_V = 11
    _CARD_SPACING = 7
    _CARD_MARGIN_BOTTOM = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keyword = ""
        self._colors = {
            "card_bg": "#ffffff",
            "border": "#e3e7ee",
            "muted": "#687385",
            "text": "#20242a",
            "highlight_bg": "#facc15",
            "highlight_fg": "#111827",
        }

    def set_keyword(self, keyword: str):
        self._keyword = keyword

    def update_theme(self, dark: bool):
        if dark:
            self._colors = {
                "card_bg": "#242424",
                "border": "#3b3b3b",
                "muted": "#a7b0bf",
                "text": "#f2f2f2",
                "highlight_bg": "#facc15",
                "highlight_fg": "#111827",
            }
        else:
            self._colors = {
                "card_bg": "#ffffff",
                "border": "#e3e7ee",
                "muted": "#687385",
                "text": "#20242a",
                "highlight_bg": "#facc15",
                "highlight_fg": "#111827",
            }

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        record = index.data(Qt.ItemDataRole.UserRole)
        if not record:
            painter.restore()
            return

        rect = option.rect.adjusted(
            0, 0, 0, -self._CARD_MARGIN_BOTTOM
        )

        # 绘制卡片背景
        card_bg = QColor(self._colors["card_bg"])
        border_color = QColor(self._colors["border"])
        painter.setPen(border_color)
        painter.setBrush(card_bg)
        painter.drawRoundedRect(rect, self._CARD_RADIUS, self._CARD_RADIUS)

        # 计算内容区域
        content_rect = rect.adjusted(
            self._CARD_PADDING_H, self._CARD_PADDING_V,
            -self._CARD_PADDING_H, -self._CARD_PADDING_V
        )

        y_offset = content_rect.top()
        available_width = content_rect.width()

        # 绘制 header
        header_text = self._build_header_text(record)
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(10)
        header_rect = QRect(content_rect.left(), int(y_offset), available_width, 1000)
        header_height = self._draw_text(
            painter, header_rect, header_text, header_font,
            QColor(self._colors["text"]), Qt.TextFlag.TextWordWrap
        )
        y_offset += header_height + self._CARD_SPACING

        # 绘制 meta
        meta_text = self._build_meta_text(record)
        meta_font = QFont()
        meta_font.setPointSize(9)
        meta_rect = QRect(content_rect.left(), int(y_offset), available_width, 1000)
        meta_height = self._draw_text(
            painter, meta_rect, meta_text, meta_font,
            QColor(self._colors["muted"]), Qt.TextFlag.TextWordWrap
        )
        y_offset += meta_height + self._CARD_SPACING

        # 绘制 content（带关键词高亮）
        content_text = str(record.get("content") or "")
        content_font = QFont()
        content_font.setPointSize(10)
        content_rect_y = QRect(content_rect.left(), int(y_offset), available_width, 1000)
        self._draw_content_with_highlight(
            painter, content_rect_y, content_text, content_font,
            QColor(self._colors["text"])
        )

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        record = index.data(Qt.ItemDataRole.UserRole)
        if not record:
            return QSize(0, 0)

        available_width = option.rect.width() - 2 * self._CARD_PADDING_H

        # 计算 header 高度
        header_text = self._build_header_text(record)
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(10)
        header_height = self._calculate_text_height(header_text, header_font, available_width)

        # 计算 meta 高度
        meta_text = self._build_meta_text(record)
        meta_font = QFont()
        meta_font.setPointSize(9)
        meta_height = self._calculate_text_height(meta_text, meta_font, available_width)

        # 计算 content 高度
        content_text = str(record.get("content") or "")
        content_font = QFont()
        content_font.setPointSize(10)
        content_height = self._calculate_text_height(content_text, content_font, available_width)

        total_height = (
            self._CARD_PADDING_V
            + header_height
            + self._CARD_SPACING
            + meta_height
            + self._CARD_SPACING
            + content_height
            + self._CARD_PADDING_V
            + self._CARD_MARGIN_BOTTOM
        )

        return QSize(option.rect.width(), max(80, total_height))

    def _build_header_text(self, record: dict) -> str:
        source = _tr(
            "SettingsWindow.chat_history_group", default="群聊"
        ) if record.get("source") == "group" else _tr(
            "SettingsWindow.chat_history_private", default="私聊"
        )
        character = record.get("_display_character", "")
        speaker = record.get("_display_speaker", "")
        return _tr(
            "SettingsWindow.chat_history_record_header",
            default="{speaker} · {source} · {character}",
            speaker=speaker, source=source, character=character,
        )

    def _build_meta_text(self, record: dict) -> str:
        user = record.get("_display_user", "")
        time = record.get("created_at", "")
        return _tr(
            "SettingsWindow.chat_history_record_meta",
            default="{time} · 用户身份：{user}",
            time=time, user=user,
        )

    def _draw_text(self, painter: QPainter, rect: QRect, text: str,
                   font: QFont, color: QColor, flags: Qt.TextFlag = 0) -> int:
        painter.setFont(font)
        painter.setPen(color)
        text_rect = painter.boundingRect(
            rect, flags | Qt.TextFlag.TextWordWrap, text
        )
        painter.drawText(rect, flags | Qt.TextFlag.TextWordWrap, text)
        return text_rect.height()

    def _calculate_text_height(self, text: str, font: QFont, width: int) -> int:
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setTextWidth(width)
        doc.setPlainText(text)
        return int(doc.size().height())

    def _draw_content_with_highlight(self, painter: QPainter, rect: QRect,
                                     content: str, font: QFont, color: QColor):
        if not self._keyword:
            self._draw_text(painter, rect, content, font, color)
            return

        keyword = self._keyword.strip()
        if not keyword:
            self._draw_text(painter, rect, content, font, color)
            return

        painter.setFont(font)
        painter.setPen(color)

        # 使用 QTextDocument 来渲染带高亮的文本
        doc = QTextDocument()
        doc.setDefaultFont(font)
        doc.setTextWidth(rect.width())

        # 构建带高亮的 HTML
        highlighted = self._highlight_keyword(content, keyword)
        doc.setHtml(highlighted)

        painter.save()
        painter.translate(rect.topLeft())
        doc.drawContents(painter)
        painter.restore()

    @staticmethod
    def _highlight_keyword(content: str, keyword: str) -> str:
        content = str(content or "")
        keyword = str(keyword or "").strip()
        if not keyword:
            return html.escape(content).replace("\n", "<br>")
        parts = []
        cursor = 0
        for match in re.finditer(re.escape(keyword), content, flags=re.IGNORECASE):
            parts.append(html.escape(content[cursor:match.start()]))
            parts.append(
                '<span style="background-color:#facc15;color:#111827;">'
                + html.escape(match.group(0))
                + "</span>"
            )
            cursor = match.end()
        parts.append(html.escape(content[cursor:]))
        return "".join(parts).replace("\n", "<br>")


class ChatHistoryListView(ListView):
    """继承 qfluentwidgets.ListView，使用 Fluent 风格滚动条"""

    load_more_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_more_widget: QPushButton | None = None
        self._has_more = False

        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QListView.SelectionMode.NoSelection)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # 连接滚动信号
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)

    def set_has_more(self, has_more: bool):
        self._has_more = has_more
        self._update_load_more_visibility()

    def _on_scroll_changed(self, value: int):
        if not self._has_more:
            return
        scrollbar = self.verticalScrollBar()
        if scrollbar.maximum() - value < 100:
            self.load_more_requested.emit()

    def _update_load_more_visibility(self):
        # 在 QListView 中，加载更多通过滚动触发
        pass


class ChatHistoryPageMixin:
    _CHAT_HISTORY_PAGE_SIZE = 50

    def _build_chat_history_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("chatHistoryPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        layout.addWidget(TitleLabel(
            _tr("SettingsWindow.chat_history_title", default="聊天记录"),
            page,
        ))
        layout.addWidget(_wrap_label(SubtitleLabel(
            _tr(
                "SettingsWindow.chat_history_subtitle",
                default="按日期、角色、用户身份和发言方筛选聊天，也可以搜索消息关键词。",
            ),
            page,
        )))

        filter_panel = QFrame(page)
        filter_panel.setObjectName("chatHistoryFilterPanel")
        filter_panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        filters = QGridLayout(filter_panel)
        filters.setContentsMargins(14, 14, 14, 14)
        filters.setHorizontalSpacing(10)
        filters.setVerticalSpacing(10)

        self._history_keyword_edit = LineEdit(filter_panel)
        self._history_keyword_edit.setClearButtonEnabled(True)
        self._history_keyword_edit.setPlaceholderText(_tr(
            "SettingsWindow.chat_history_keyword_placeholder",
            default="搜索聊天内容中的关键词",
        ))
        self._history_keyword_edit.setFixedHeight(36)
        self._history_keyword_edit.setMinimumWidth(0)
        filters.addWidget(self._history_keyword_edit, 0, 0, 1, 3)

        self._history_search_button = PrimaryPushButton(
            FluentIcon.SEARCH,
            _tr("SettingsWindow.chat_history_search", default="搜索"),
            filter_panel,
        )
        self._history_search_button.setFixedHeight(36)
        self._history_search_button.clicked.connect(self._refresh_chat_history)
        filters.addWidget(self._history_search_button, 0, 3)

        self._history_reset_button = PushButton(
            _tr("SettingsWindow.chat_history_reset", default="重置"),
            filter_panel,
        )
        self._history_reset_button.setFixedHeight(36)
        self._history_reset_button.clicked.connect(self._reset_chat_history_filters)
        filters.addWidget(self._history_reset_button, 0, 4)

        filters.addWidget(BodyLabel(
            _tr("SettingsWindow.chat_history_date_range", default="日期"),
            filter_panel,
        ), 1, 0)
        self._history_range_combo = OpaqueDropDownComboBox(filter_panel)
        self._history_range_combo.setFixedHeight(36)
        self._history_range_combo.addItem(
            _tr("SettingsWindow.chat_history_date_all", default="全部日期"),
            userData="all",
        )
        self._history_range_combo.addItem(
            _tr("SettingsWindow.chat_history_date_today", default="今天"),
            userData="today",
        )
        self._history_range_combo.addItem(
            _tr("SettingsWindow.chat_history_date_7d", default="近 7 天"),
            userData="7d",
        )
        self._history_range_combo.addItem(
            _tr("SettingsWindow.chat_history_date_30d", default="近 30 天"),
            userData="30d",
        )
        self._history_range_combo.addItem(
            _tr("SettingsWindow.chat_history_date_custom", default="自定义"),
            userData="custom",
        )
        filters.addWidget(self._history_range_combo, 1, 1)

        self._history_start_date = self._make_history_date_edit(filter_panel)
        self._history_end_date = self._make_history_date_edit(filter_panel)
        filters.addWidget(self._history_start_date, 1, 2)
        filters.addWidget(self._history_end_date, 1, 3)

        filters.addWidget(BodyLabel(
            _tr("SettingsWindow.chat_history_character", default="角色"),
            filter_panel,
        ), 2, 0)
        self._history_character_combo = self._make_history_combo(
            filter_panel,
            _tr("SettingsWindow.chat_history_all_characters", default="全部角色"),
        )
        filters.addWidget(self._history_character_combo, 2, 1)

        filters.addWidget(BodyLabel(
            _tr("SettingsWindow.chat_history_user_identity", default="用户身份"),
            filter_panel,
        ), 2, 2)
        self._history_user_combo = self._make_history_combo(
            filter_panel,
            _tr("SettingsWindow.chat_history_all_users", default="全部用户身份"),
        )
        filters.addWidget(self._history_user_combo, 2, 3, 1, 2)

        filters.addWidget(BodyLabel(
            _tr("SettingsWindow.chat_history_more_filters", default="更多筛选"),
            filter_panel,
        ), 3, 0)
        self._history_role_combo = self._make_history_combo(
            filter_panel,
            _tr("SettingsWindow.chat_history_all_roles", default="全部发言方"),
        )
        self._history_role_combo.addItem(
            _tr("SettingsWindow.chat_history_role_user", default="用户"),
            userData="user",
        )
        self._history_role_combo.addItem(
            _tr("SettingsWindow.chat_history_role_assistant", default="角色"),
            userData="assistant",
        )
        self._history_role_combo.addItem(
            _tr("SettingsWindow.chat_history_role_system", default="系统"),
            userData="system",
        )
        filters.addWidget(self._history_role_combo, 3, 1)

        filters.addWidget(BodyLabel(
            _tr("SettingsWindow.chat_history_chat_type", default="聊天类型"),
            filter_panel,
        ), 3, 2)
        self._history_source_combo = self._make_history_combo(
            filter_panel,
            _tr("SettingsWindow.chat_history_all_sources", default="全部聊天类型"),
        )
        self._history_source_combo.addItem(
            _tr("SettingsWindow.chat_history_private", default="私聊"),
            userData="private",
        )
        self._history_source_combo.addItem(
            _tr("SettingsWindow.chat_history_group", default="群聊"),
            userData="group",
        )
        filters.addWidget(self._history_source_combo, 3, 3, 1, 2)
        filters.setColumnStretch(1, 1)
        filters.setColumnStretch(3, 1)
        filters.setColumnStretch(4, 1)
        layout.addWidget(filter_panel)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(2, 0, 2, 0)
        self._history_summary_label = StrongBodyLabel("", page)
        summary_row.addWidget(self._history_summary_label)
        summary_row.addStretch()
        self._history_refresh_button = PushButton(
            FluentIcon.SYNC,
            _tr("SettingsWindow.memory_refresh", default="刷新"),
            page,
        )
        self._history_refresh_button.clicked.connect(self._refresh_chat_history)
        summary_row.addWidget(self._history_refresh_button)
        layout.addLayout(summary_row)

        # 创建 QListView 替代 QScrollArea
        self._history_list_view = ChatHistoryListView(page)
        self._history_list_view.setObjectName("chatHistoryList")

        # 创建数据模型和代理
        self._history_data_model = ChatHistoryModel()
        self._history_delegate = ChatHistoryDelegate(self._history_list_view)
        self._history_list_view.setItemDelegate(self._history_delegate)

        # 创建 Qt 模型
        from PySide6.QtCore import QAbstractListModel

        class ListModel(QAbstractListModel):
            def __init__(self, parent=None):
                super().__init__(parent)
                self._items: list[dict] = []

            def rowCount(self, parent=QModelIndex()):
                return len(self._items)

            def data(self, index, role=Qt.ItemDataRole.DisplayRole):
                if not index.isValid() or index.row() >= len(self._items):
                    return None
                if role == Qt.ItemDataRole.UserRole:
                    return self._items[index.row()]
                return None

            def set_items(self, items: list[dict]):
                self.beginResetModel()
                self._items = items
                self.endResetModel()

            def append_items(self, items: list[dict]):
                if not items:
                    return
                begin = len(self._items)
                self.beginInsertRows(QModelIndex(), begin, begin + len(items) - 1)
                self._items.extend(items)
                self.endInsertRows()

            def clear(self):
                self.beginResetModel()
                self._items.clear()
                self.endResetModel()

        self._history_qmodel = ListModel()
        self._history_list_view.setModel(self._history_qmodel)

        # 连接加载更多信号
        self._history_list_view.load_more_requested.connect(self._load_more_chat_history)

        layout.addWidget(self._history_list_view, 1)

        self._history_db = None
        self._history_worker = None
        self._history_filter_cache = None
        self._history_loading_widget = None
        self._history_search_generation = 0
        self._history_search_timer = QTimer(page)
        self._history_search_timer.setSingleShot(True)
        self._history_search_timer.setInterval(350)
        self._history_search_timer.timeout.connect(self._refresh_chat_history)
        self._history_keyword_edit.textChanged.connect(
            lambda _text: self._history_search_timer.start()
        )
        self._history_keyword_edit.returnPressed.connect(self._refresh_chat_history)
        self._history_range_combo.currentIndexChanged.connect(self._on_history_range_changed)
        self._history_start_date.dateChanged.connect(self._on_history_custom_date_changed)
        self._history_end_date.dateChanged.connect(self._on_history_custom_date_changed)
        for combo in (
            self._history_character_combo,
            self._history_user_combo,
            self._history_role_combo,
            self._history_source_combo,
        ):
            combo.currentIndexChanged.connect(self._refresh_chat_history)

        self._style_chat_history_page(page)
        self._connect_theme_changed(lambda: self._style_chat_history_page(page))
        return page

    def _activate_chat_history_page(self):
        self._populate_chat_history_filters(force=False)
        self._refresh_chat_history()

    @staticmethod
    def _make_history_combo(parent, all_text: str):
        combo = OpaqueDropDownComboBox(parent)
        combo.setFixedHeight(36)
        combo.setMinimumWidth(110)
        combo.addItem(all_text, userData="")
        return combo

    @staticmethod
    def _make_history_date_edit(parent):
        edit = QDateEdit(parent)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("yyyy-MM-dd")
        edit.setFixedHeight(36)
        edit.setMinimumWidth(110)
        edit.setDate(QDate.currentDate())
        return edit

    def _get_history_db(self):
        if self._history_db is None:
            self._history_db = DatabaseManager()
        return self._history_db

    def _history_user_labels(self) -> dict:
        labels = {}
        profiles = self._cfg.get_user_profiles() if self._cfg and hasattr(self._cfg, "get_user_profiles") else []
        for profile in profiles:
            key = str(profile.get("key", "") or "").strip()
            if not key:
                continue
            labels[key] = str(profile.get("name", "") or "").strip() or display_user_name(key) or key
        return labels

    def _populate_chat_history_filters(self, *, force: bool = False):
        if not force and self._history_filter_cache is not None:
            self._apply_filter_options(self._history_filter_cache)
            return
        self._start_history_worker(
            {"action": "filters"},
            on_result=self._on_filter_options_loaded,
        )

    def _on_filter_options_loaded(self, options):
        self._history_filter_cache = options
        self._apply_filter_options(options)

    def _apply_filter_options(self, options):
        selected_character = self._history_character_combo.currentData()
        selected_user = self._history_user_combo.currentData()

        self._history_character_combo.blockSignals(True)
        self._history_character_combo.clear()
        self._history_character_combo.addItem(
            _tr("SettingsWindow.chat_history_all_characters", default="全部角色"),
            userData="",
        )
        known = set()
        for character in list(self._model_manager.characters) + options["characters"]:
            if not character or character in known:
                continue
            known.add(character)
            display = self._model_manager.get_display_name(character) or character
            self._history_character_combo.addItem(display, userData=character)
        index = self._history_character_combo.findData(selected_character)
        self._history_character_combo.setCurrentIndex(max(0, index))
        self._history_character_combo.blockSignals(False)

        user_labels = self._history_user_labels()
        self._history_user_combo.blockSignals(True)
        self._history_user_combo.clear()
        self._history_user_combo.addItem(
            _tr("SettingsWindow.chat_history_all_users", default="全部用户身份"),
            userData="",
        )
        for user_key in options["user_keys"]:
            self._history_user_combo.addItem(
                user_labels.get(user_key) or display_user_name(user_key) or user_key,
                userData=user_key,
            )
        index = self._history_user_combo.findData(selected_user)
        self._history_user_combo.setCurrentIndex(max(0, index))
        self._history_user_combo.blockSignals(False)

    def _on_history_range_changed(self, *_args):
        mode = self._history_range_combo.currentData() or "all"
        custom = mode == "custom"
        self._history_start_date.setEnabled(custom)
        self._history_end_date.setEnabled(custom)
        if mode != "all":
            today = QDate.currentDate()
            if mode == "today":
                start = today
            elif mode == "7d":
                start = today.addDays(-6)
            elif mode == "30d":
                start = today.addDays(-29)
            else:
                start = self._history_start_date.date()
            self._history_start_date.blockSignals(True)
            self._history_end_date.blockSignals(True)
            self._history_start_date.setDate(start)
            self._history_end_date.setDate(today)
            self._history_start_date.blockSignals(False)
            self._history_end_date.blockSignals(False)
        self._refresh_chat_history()

    def _on_history_custom_date_changed(self, *_args):
        if self._history_range_combo.currentData() == "custom":
            self._history_search_timer.start()

    def _history_date_bounds(self) -> tuple[str, str]:
        mode = self._history_range_combo.currentData() or "all"
        if mode == "all":
            return "", ""
        start = self._history_start_date.date()
        end = self._history_end_date.date()
        if start > end:
            start, end = end, start
        return start.toString("yyyy-MM-dd"), end.toString("yyyy-MM-dd")

    def _reset_chat_history_filters(self):
        self._history_keyword_edit.blockSignals(True)
        self._history_keyword_edit.clear()
        self._history_keyword_edit.blockSignals(False)
        for combo in (
            self._history_range_combo,
            self._history_character_combo,
            self._history_user_combo,
            self._history_role_combo,
            self._history_source_combo,
        ):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._on_history_range_changed()

    def _history_display_character(self, record: dict) -> str:
        character = str(record.get("character") or "")
        if character:
            return self._model_manager.get_display_name(character) or character
        group_key = str(record.get("group_key") or "")
        members = DatabaseManager._group_key_characters(group_key)
        names = [self._model_manager.get_display_name(member) or member for member in members]
        return "、".join(names) or group_key

    def _history_display_user(self, user_key: str) -> str:
        labels = self._history_user_labels()
        return labels.get(user_key) or display_user_name(user_key) or _tr(
            "SettingsWindow.chat_history_unknown_user",
            default="默认用户",
        )

    def _history_role_label(self, record: dict) -> str:
        role = record.get("role")
        if role == "user":
            return self._history_display_user(record.get("user_key", ""))
        if role == "system":
            return _tr("SettingsWindow.chat_history_role_system", default="系统")
        if record.get("source") == "group":
            speaker = re.match(r"^\s*【([^】]+)】", str(record.get("content") or ""))
            if speaker:
                return speaker.group(1).strip()
        return self._history_display_character(record)

    def _enrich_record(self, record: dict) -> dict:
        """为记录添加显示字段"""
        record["_display_character"] = self._history_display_character(record)
        record["_display_speaker"] = self._history_role_label(record)
        record["_display_user"] = self._history_display_user(record.get("user_key", ""))
        return record

    def _build_chat_history_query_params(self, offset: int = 0, skip_count: bool = False) -> dict:
        date_from, date_to = self._history_date_bounds()
        keyword = self._history_keyword_edit.text().strip()
        return {
            "action": "search",
            "keyword": keyword,
            "date_from": date_from,
            "date_to": date_to,
            "character": self._history_character_combo.currentData() or "",
            "user_key": self._history_user_combo.currentData() or "",
            "role": self._history_role_combo.currentData() or "",
            "source": self._history_source_combo.currentData() or "",
            "limit": self._CHAT_HISTORY_PAGE_SIZE,
            "offset": offset,
            "skip_count": skip_count,
        }

    def _start_history_worker(self, params: dict, *, on_result, on_error=None):
        if self._history_worker is not None and self._history_worker.isRunning():
            self._history_worker.finished.disconnect()
            self._history_worker.error.disconnect()
            self._history_worker.wait(200)
        worker = _ChatHistoryWorker(
            db_factory=lambda: DatabaseManager(),
            query_params=params,
            parent=self._history_list_view,
        )
        worker.finished.connect(on_result)
        worker.error.connect(on_error or self._on_history_query_error)
        self._history_worker = worker
        worker.start()

    def _on_history_query_error(self, msg: str):
        self._hide_history_loading()
        self._history_summary_label.setText(
            _tr("SettingsWindow.chat_history_error", default="查询出错：{error}", error=msg)
        )

    def _show_history_loading(self):
        self._hide_history_loading()
        ring = ProgressRing(self._history_list_view)
        ring.setFixedSize(36, 36)
        ring.setStrokeWidth(4)
        ring.setAlignment(Qt.AlignmentFlag.AlignCenter)
        container = QWidget(self._history_list_view)
        container.setObjectName("chatHistoryLoadingContainer")
        cl = QHBoxLayout(container)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.setContentsMargins(0, 24, 0, 24)
        cl.addWidget(ring)
        container.setFixedSize(self._history_list_view.viewport().size())
        container.show()
        self._history_loading_widget = container

    def _hide_history_loading(self):
        if self._history_loading_widget is not None:
            self._history_loading_widget.setParent(None)
            self._history_loading_widget.deleteLater()
            self._history_loading_widget = None

    def _update_summary_label(self):
        if self._history_data_model.total >= 0:
            self._history_summary_label.setText(_tr(
                "SettingsWindow.chat_history_result_count",
                default="找到 {total} 条，当前显示 {shown} 条",
                total=self._history_data_model.total,
                shown=self._history_data_model.shown_count,
            ))
        else:
            self._history_summary_label.setText(_tr(
                "SettingsWindow.chat_history_result_count_approx",
                default="当前显示 {shown} 条",
                shown=self._history_data_model.shown_count,
            ))

    def _refresh_chat_history(self, *_args):
        if not hasattr(self, "_history_list_view"):
            return
        self._history_search_generation += 1
        gen = self._history_search_generation
        params = self._build_chat_history_query_params(offset=0, skip_count=True)
        self._history_data_model.clear()
        self._history_qmodel.clear()
        self._show_history_loading()
        self._start_history_worker(
            params,
            on_result=lambda result, _gen=gen: self._on_refresh_finished(result, _gen),
        )

    def _on_refresh_finished(self, result, generation):
        if generation != self._history_search_generation:
            return
        self._hide_history_loading()
        keyword = self._history_keyword_edit.text().strip()
        records = result["records"]

        self._history_data_model.keyword = keyword
        self._history_data_model.set_result(result)
        self._history_delegate.set_keyword(keyword)

        if not records:
            self._history_summary_label.setText(
                _tr("SettingsWindow.chat_history_empty", default="没有找到符合条件的聊天记录。")
            )
        else:
            # 为每条记录添加显示字段
            enriched_records = [self._enrich_record(r) for r in records]
            self._history_data_model.append_records(enriched_records)
            self._history_qmodel.set_items(self._history_data_model.records)
            self._history_list_view.set_has_more(self._history_data_model.has_more)
            self._update_summary_label()

    def _load_more_chat_history(self):
        if not self._history_data_model.has_more:
            return
        if self._history_data_model.total >= 0 and self._history_data_model.shown_count >= self._history_data_model.total:
            return

        params = self._build_chat_history_query_params(
            offset=self._history_data_model.shown_count, skip_count=True,
        )
        self._start_history_worker(
            params,
            on_result=self._on_load_more_finished,
        )

    def _on_load_more_finished(self, result):
        keyword = self._history_keyword_edit.text().strip()
        records = result["records"]
        self._history_data_model.total = result.get("total", self._history_data_model.total)
        self._history_data_model.has_more = result.get("has_more", False)
        self._history_delegate.set_keyword(keyword)

        if records:
            enriched_records = [self._enrich_record(r) for r in records]
            self._history_data_model.append_records(enriched_records)
            self._history_qmodel.append_items(enriched_records)
        else:
            self._history_data_model.has_more = False

        self._history_list_view.set_has_more(self._history_data_model.has_more)
        self._update_summary_label()

    def _style_chat_history_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#f8fafc"
        list_bg = page_bg

        # 更新代理主题
        self._history_delegate.update_theme(dark)

        page.setStyleSheet(f"""
            QWidget#chatHistoryPage {{
                background: {page_bg};
            }}
            QFrame#chatHistoryFilterPanel {{
                background: {panel_bg};
                border: 1px solid {self._history_delegate._colors['border']};
                border-radius: 10px;
            }}
            QListView#chatHistoryList {{
                background: {list_bg};
                border: none;
                outline: none;
            }}
            QListView#chatHistoryList::item {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QWidget#chatHistoryLoadingContainer {{
                background: transparent;
            }}
        """)
