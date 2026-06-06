import html
import re

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from settings_window.constants import *
from settings_window.widgets import *


class ChatHistoryPageMixin:
    _CHAT_HISTORY_PAGE_SIZE = 100

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

        self._history_scroll = ScrollArea(page)
        self._history_scroll.setObjectName("chatHistoryScroll")
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._reserve_overlay_scrollbar(self._history_scroll)

        self._history_content = QWidget(self._history_scroll)
        self._history_content.setObjectName("chatHistoryContent")
        self._history_content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._history_results_layout = QVBoxLayout(self._history_content)
        self._history_results_layout.setContentsMargins(0, 0, 12, 0)
        self._history_results_layout.setSpacing(9)
        self._history_results_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._history_results_layout.addStretch()
        self._history_scroll.setWidget(self._history_content)
        layout.addWidget(self._history_scroll, 1)

        self._history_db = None
        self._history_shown = 0
        self._history_total = 0
        self._history_load_more_button = None
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
        self._populate_chat_history_filters()
        self._on_history_range_changed()
        return page

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

    def _populate_chat_history_filters(self):
        options = self._get_history_db().get_chat_history_filter_options()
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

    @staticmethod
    def _clear_history_results(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

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

    @staticmethod
    def _highlight_history_keyword(content: str, keyword: str) -> str:
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

    def _add_chat_history_record(self, record: dict, keyword: str):
        card = QFrame(self._history_content)
        card.setObjectName("chatHistoryRecord")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 11, 14, 11)
        card_layout.setSpacing(7)

        source_label = _tr(
            "SettingsWindow.chat_history_group",
            default="群聊",
        ) if record.get("source") == "group" else _tr(
            "SettingsWindow.chat_history_private",
            default="私聊",
        )
        character_label = self._history_display_character(record)
        role_label = self._history_role_label(record)
        header = StrongBodyLabel(
            _tr(
                "SettingsWindow.chat_history_record_header",
                default="{speaker} · {source} · {character}",
                speaker=role_label,
                source=source_label,
                character=character_label,
            ),
            card,
        )
        header.setMinimumWidth(0)
        header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.setWordWrap(True)
        card_layout.addWidget(header)

        meta = BodyLabel(
            _tr(
                "SettingsWindow.chat_history_record_meta",
                default="{time} · 用户身份：{user}",
                time=record.get("created_at", ""),
                user=self._history_display_user(record.get("user_key", "")),
            ),
            card,
        )
        meta.setObjectName("chatHistoryMuted")
        meta.setMinimumWidth(0)
        meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        meta.setWordWrap(True)
        card_layout.addWidget(meta)

        content = QLabel(card)
        content.setObjectName("chatHistoryBody")
        content.setTextFormat(Qt.TextFormat.RichText)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setWordWrap(True)
        content.setText(self._highlight_history_keyword(record.get("content", ""), keyword))
        card_layout.addWidget(content)
        self._history_results_layout.addWidget(card)

    def _chat_history_query(self, offset: int = 0) -> dict:
        date_from, date_to = self._history_date_bounds()
        keyword = self._history_keyword_edit.text().strip()
        return self._get_history_db().search_chat_history(
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            character=self._history_character_combo.currentData() or "",
            user_key=self._history_user_combo.currentData() or "",
            role=self._history_role_combo.currentData() or "",
            source=self._history_source_combo.currentData() or "",
            limit=self._CHAT_HISTORY_PAGE_SIZE,
            offset=offset,
        )

    def _finish_chat_history_results(self):
        if self._history_shown < self._history_total:
            self._history_load_more_button = PushButton(
                _tr("SettingsWindow.chat_history_load_more", default="加载更多"),
                self._history_content,
            )
            self._history_load_more_button.setFixedHeight(36)
            self._history_load_more_button.clicked.connect(self._load_more_chat_history)
            self._history_results_layout.addWidget(
                self._history_load_more_button,
                0,
                Qt.AlignmentFlag.AlignHCenter,
            )
        else:
            self._history_load_more_button = None
        self._history_results_layout.addStretch()
        self._history_summary_label.setText(_tr(
            "SettingsWindow.chat_history_result_count",
            default="找到 {total} 条，当前显示 {shown} 条",
            total=self._history_total,
            shown=self._history_shown,
        ))

    def _refresh_chat_history(self, *_args):
        if not hasattr(self, "_history_results_layout"):
            return
        keyword = self._history_keyword_edit.text().strip()
        result = self._chat_history_query(offset=0)
        self._clear_history_results(self._history_results_layout)
        records = result["records"]
        self._history_total = result["total"]
        self._history_shown = len(records)
        if not records:
            empty = BodyLabel(
                _tr("SettingsWindow.chat_history_empty", default="没有找到符合条件的聊天记录。"),
                self._history_content,
            )
            empty.setObjectName("chatHistoryEmpty")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(120)
            self._history_results_layout.addWidget(empty)
        else:
            for record in records:
                self._add_chat_history_record(record, keyword)
        self._finish_chat_history_results()

    def _load_more_chat_history(self):
        if self._history_shown >= self._history_total:
            return
        if self._history_results_layout.count():
            self._history_results_layout.takeAt(self._history_results_layout.count() - 1)
        if self._history_load_more_button is not None:
            self._history_results_layout.removeWidget(self._history_load_more_button)
            self._history_load_more_button.deleteLater()
            self._history_load_more_button = None

        keyword = self._history_keyword_edit.text().strip()
        result = self._chat_history_query(offset=self._history_shown)
        for record in result["records"]:
            self._add_chat_history_record(record, keyword)
        self._history_total = result["total"]
        self._history_shown += len(result["records"])
        if not result["records"]:
            self._history_shown = self._history_total
        self._finish_chat_history_results()

    def _style_chat_history_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#f8fafc"
        card_bg = "#242424" if dark else "#ffffff"
        border = "#3b3b3b" if dark else "#e3e7ee"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f2f2f2" if dark else "#20242a"
        page.setStyleSheet(f"""
            QWidget#chatHistoryPage, QWidget#chatHistoryContent {{
                background: {page_bg};
            }}
            QFrame#chatHistoryFilterPanel {{
                background: {panel_bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QFrame#chatHistoryRecord {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            BodyLabel#chatHistoryMuted {{
                color: {muted};
                font-size: 12px;
            }}
            QLabel#chatHistoryBody {{
                color: {text};
                background: transparent;
                font-size: 14px;
            }}
            BodyLabel#chatHistoryEmpty {{
                color: {muted};
            }}
        """)
