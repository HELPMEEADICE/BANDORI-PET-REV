import re

from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class MemoryAlbumPageMixin:
    """Mixin providing the per-character conversation memory album page."""

    def _build_memory_album_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("memoryAlbumPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = TitleLabel(_tr("SettingsWindow.memory_album_title", default="回忆相册"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(
            _tr(
                "SettingsWindow.memory_album_subtitle",
                default="按角色整理最近的重要对话、历史链条和收藏语句。",
            ),
            page,
        ))
        layout.addWidget(subtitle)

        selector_row = QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(10)
        selector_row.addWidget(BodyLabel(_tr("SettingsWindow.memory_album_character", default="选择角色"), page))
        self._memory_album_character_combo = OpaqueDropDownComboBox(page)
        self._memory_album_character_combo.setFixedHeight(36)
        selected_character = self._current_char or self._selected_list_character
        selected_index = 0
        for char_key in self._model_manager.characters:
            self._memory_album_character_combo.addItem(
                self._model_manager.get_display_name(char_key),
                userData=char_key,
            )
            if char_key == selected_character:
                selected_index = self._memory_album_character_combo.count() - 1
        self._memory_album_character_combo.setCurrentIndex(selected_index)
        self._memory_album_character_combo.currentIndexChanged.connect(lambda _i: self._refresh_memory_album_page())
        selector_row.addWidget(self._memory_album_character_combo, 1)
        self._memory_album_user_label = BodyLabel("", page)
        selector_row.addWidget(self._memory_album_user_label, 1)
        refresh_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.memory_refresh", default="刷新"), page)
        refresh_btn.setFixedHeight(36)
        refresh_btn.clicked.connect(self._refresh_memory_album_page)
        selector_row.addWidget(refresh_btn)
        layout.addLayout(selector_row)

        scroll = ScrollArea(page)
        scroll.setObjectName("memoryAlbumScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._reserve_overlay_scrollbar(scroll)

        content = QWidget(scroll)
        content.setObjectName("memoryAlbumContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 12, 0)
        content_layout.setSpacing(14)

        self._memory_album_summary_panel = self._make_album_panel(content)
        summary_layout = QVBoxLayout(self._memory_album_summary_panel)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setSpacing(8)
        summary_layout.addWidget(SubtitleLabel(_tr("SettingsWindow.memory_album_recent_title", default="最近聊过什么"), self._memory_album_summary_panel))
        self._memory_album_summary_label = BodyLabel("", self._memory_album_summary_panel)
        self._memory_album_summary_label.setObjectName("memoryAlbumText")
        self._memory_album_summary_label.setWordWrap(True)
        summary_layout.addWidget(self._memory_album_summary_label)
        content_layout.addWidget(self._memory_album_summary_panel)

        self._memory_album_favorites_panel = self._make_album_panel(content)
        favorites_layout = QVBoxLayout(self._memory_album_favorites_panel)
        favorites_layout.setContentsMargins(16, 14, 16, 14)
        favorites_layout.setSpacing(8)
        favorites_layout.addWidget(SubtitleLabel(_tr("SettingsWindow.memory_album_favorites_title", default="收藏语句"), self._memory_album_favorites_panel))
        self._memory_album_favorites_layout = QVBoxLayout()
        self._memory_album_favorites_layout.setContentsMargins(0, 0, 0, 0)
        self._memory_album_favorites_layout.setSpacing(8)
        favorites_layout.addLayout(self._memory_album_favorites_layout)
        content_layout.addWidget(self._memory_album_favorites_panel)

        self._memory_album_chain_panel = self._make_album_panel(content)
        chain_layout = QVBoxLayout(self._memory_album_chain_panel)
        chain_layout.setContentsMargins(16, 14, 16, 14)
        chain_layout.setSpacing(8)
        chain_layout.addWidget(SubtitleLabel(_tr("SettingsWindow.memory_album_chain_title", default="对话历史链条"), self._memory_album_chain_panel))
        self._memory_album_chain_layout = QVBoxLayout()
        self._memory_album_chain_layout.setContentsMargins(0, 0, 0, 0)
        self._memory_album_chain_layout.setSpacing(8)
        chain_layout.addLayout(self._memory_album_chain_layout)
        content_layout.addWidget(self._memory_album_chain_panel)

        self._memory_album_timeline_panel = self._make_album_panel(content)
        timeline_layout = QVBoxLayout(self._memory_album_timeline_panel)
        timeline_layout.setContentsMargins(16, 14, 16, 14)
        timeline_layout.setSpacing(8)
        timeline_layout.addWidget(SubtitleLabel(_tr("SettingsWindow.memory_album_timeline_title", default="日期时间线"), self._memory_album_timeline_panel))
        self._memory_album_timeline_layout = QVBoxLayout()
        self._memory_album_timeline_layout.setContentsMargins(0, 0, 0, 0)
        self._memory_album_timeline_layout.setSpacing(8)
        timeline_layout.addLayout(self._memory_album_timeline_layout)
        content_layout.addWidget(self._memory_album_timeline_panel)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self._style_memory_album_page(page)
        qconfig.themeChanged.connect(lambda: self._style_memory_album_page(page))
        self._refresh_memory_album_page()
        return page

    def _make_album_panel(self, parent: QWidget) -> QWidget:
        panel = QWidget(parent)
        panel.setObjectName("memoryAlbumPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        return panel

    def _memory_album_page_ready(self) -> bool:
        return all(
            hasattr(self, attr)
            for attr in (
                "_memory_album_character_combo",
                "_memory_album_user_label",
                "_memory_album_summary_label",
                "_memory_album_favorites_layout",
                "_memory_album_chain_layout",
                "_memory_album_timeline_layout",
            )
        )

    def _selected_memory_album_character(self) -> str:
        if not hasattr(self, "_memory_album_character_combo"):
            return self._current_char or (self._model_manager.characters[0] if self._model_manager.characters else "")
        character = self._memory_album_character_combo.itemData(self._memory_album_character_combo.currentIndex())
        return character or self._current_char or (self._model_manager.characters[0] if self._model_manager.characters else "")

    @staticmethod
    def _clear_album_layout(layout: QVBoxLayout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget:
                widget.deleteLater()
            elif child_layout:
                MemoryAlbumPageMixin._clear_album_layout(child_layout)

    @staticmethod
    def _album_clean_content(content: str) -> str:
        text = re.sub(r"\s+", " ", str(content or "")).strip()
        text = re.sub(r"^【[^】]{1,32}】\s*", "", text)
        text = re.sub(r"^收藏语句[：:]\s*", "", text)
        return text

    def _album_summary_text(self, character: str, messages: list[dict], favorites: list[dict]) -> str:
        if not messages and not favorites:
            return _tr("SettingsWindow.memory_album_no_recent", default="还没有足够的聊天记录。")
        name = self._model_manager.get_display_name(character)
        user_messages = [self._album_clean_content(m.get("content", "")) for m in messages if m.get("role") == "user"]
        assistant_messages = [self._album_clean_content(m.get("content", "")) for m in messages if m.get("role") == "assistant"]
        latest = messages[-1].get("created_at", "") if messages else ""
        topics = [text for text in user_messages[-4:] if text]
        if topics:
            topic_text = "；".join(text[:48] for text in topics)
        else:
            topic_text = _tr("SettingsWindow.memory_album_recent_no_topic", default="主要是轻量互动")
        fav_part = ""
        if favorites:
            fav_part = _tr(
                "SettingsWindow.memory_album_summary_favorites",
                default=" 已收藏 {count} 句话，可作为 {name} 的长期记忆依据。",
                count=len(favorites),
                name=name,
            )
        return _tr(
            "SettingsWindow.memory_album_summary_text",
            default="最近和 {name} 的记录里，用户发言 {user_count} 条，角色回应 {assistant_count} 条。最近话题：{topics}。最新时间：{latest}.{favorites}",
            name=name,
            user_count=len(user_messages),
            assistant_count=len(assistant_messages),
            topics=topic_text,
            latest=latest or _tr("SettingsWindow.memory_never_updated", default="暂无"),
            favorites=fav_part,
        )

    def _album_add_empty(self, layout: QVBoxLayout, text: str, parent: QWidget):
        empty = BodyLabel(text, parent)
        empty.setObjectName("memoryAlbumMuted")
        empty.setWordWrap(True)
        empty.setMinimumHeight(38)
        layout.addWidget(empty)

    def _album_add_row(self, layout: QVBoxLayout, title: str, meta: str, body: str, parent: QWidget):
        row = QWidget(parent)
        row.setObjectName("memoryAlbumRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(5)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        title_label = StrongBodyLabel(title, row)
        title_label.setObjectName("memoryAlbumRowTitle")
        meta_label = BodyLabel(meta, row)
        meta_label.setObjectName("memoryAlbumMuted")
        top.addWidget(title_label, 1)
        top.addWidget(meta_label)
        row_layout.addLayout(top)
        if body:
            body_label = BodyLabel(body, row)
            body_label.setObjectName("memoryAlbumText")
            body_label.setWordWrap(True)
            row_layout.addWidget(body_label)
        layout.addWidget(row)

    def _refresh_memory_album_page(self):
        if not self._memory_album_page_ready():
            return
        character = self._selected_memory_album_character()
        if not character:
            return
        db = self._memory_database()
        user_key = user_key_from_config(self._cfg)
        user_display = self._memory_user_display(user_key) if hasattr(self, "_memory_user_display") else display_user_name(user_key)
        self._memory_album_user_label.setText(_tr("SettingsWindow.memory_current_user", default="当前用户：{display}", display=user_display))

        messages = db.get_character_recent_messages(character, user_key, limit=28)
        favorites = db.get_character_memories_by_kind(character, user_key, "favorite", limit=80)
        chain = db.get_character_conversation_chain(character, user_key, limit=18)
        days = db.get_character_album_days(character, user_key, limit=30)

        self._memory_album_summary_label.setText(self._album_summary_text(character, messages, favorites))

        self._clear_album_layout(self._memory_album_favorites_layout)
        if not favorites:
            self._album_add_empty(
                self._memory_album_favorites_layout,
                _tr("SettingsWindow.memory_album_no_favorites", default="还没有收藏语句。聊天时说“收藏这句话”或“把刚才那句加入回忆相册”即可保存。"),
                self._memory_album_favorites_panel,
            )
        for item in favorites[:12]:
            content = self._album_clean_content(item.get("content", ""))
            meta = item.get("updated_at") or item.get("created_at") or ""
            self._album_add_row(
                self._memory_album_favorites_layout,
                _tr("SettingsWindow.memory_album_favorite_row", default="收藏"),
                meta,
                content,
                self._memory_album_favorites_panel,
            )

        self._clear_album_layout(self._memory_album_chain_layout)
        if not chain:
            self._album_add_empty(
                self._memory_album_chain_layout,
                _tr("SettingsWindow.memory_album_no_chain", default="暂无对话历史链条。"),
                self._memory_album_chain_panel,
            )
        for index, item in enumerate(chain, start=1):
            source = _tr("SettingsWindow.memory_album_group_source", default="群聊") if item.get("source") == "group" else _tr("SettingsWindow.memory_album_private_source", default="私聊")
            title = item.get("title") or _tr(
                "SettingsWindow.memory_album_chain_row",
                default="第 {index} 段对话",
                index=index,
            )
            meta = _tr(
                "SettingsWindow.memory_album_chain_meta",
                default="{source} · {count} 条 · {time}",
                source=source,
                count=int(item.get("message_count") or 0),
                time=item.get("last_message_at") or item.get("created_at") or "",
            )
            body = self._album_clean_content(item.get("first_user", ""))
            self._album_add_row(self._memory_album_chain_layout, title, meta, body[:160], self._memory_album_chain_panel)

        self._clear_album_layout(self._memory_album_timeline_layout)
        if not days:
            self._album_add_empty(
                self._memory_album_timeline_layout,
                _tr("SettingsWindow.memory_album_no_timeline", default="暂无日期时间线。"),
                self._memory_album_timeline_panel,
            )
        for item in days:
            memory_count = int(item.get("memory_count") or 0)
            favorite_count = int(item.get("favorite_count") or 0)
            meta = _tr(
                "SettingsWindow.memory_album_day_meta",
                default="{count} 条消息 · {memories} 条记忆 · {favorites} 句收藏",
                count=int(item.get("message_count") or 0),
                memories=memory_count,
                favorites=favorite_count,
            )
            snippets = [self._album_clean_content(text) for text in item.get("snippets", []) if text]
            body = "\n".join(f"- {text[:96]}" for text in snippets[:3])
            self._album_add_row(self._memory_album_timeline_layout, item.get("day", ""), meta, body, self._memory_album_timeline_panel)

    def _style_memory_album_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        panel_bg = "#252525" if dark else "#ffffff"
        panel_border = "#3b3b3b" if dark else "#e4d9df"
        row_bg = "#2f2f2f" if dark else "#fbfbfc"
        row_border = "#404040" if dark else "#ece6ea"
        muted = "#a7b0bf" if dark else "#687385"
        text = "#f3f3f6" if dark else "#202126"
        page.setStyleSheet(f"""
            QWidget#memoryAlbumPage,
            QWidget#memoryAlbumContent {{
                background: {page_bg};
            }}
            QScrollArea#memoryAlbumScroll {{
                background: transparent;
                border: none;
            }}
            QScrollArea#memoryAlbumScroll > QWidget > QWidget {{
                background: transparent;
            }}
            QWidget#memoryAlbumPanel {{
                background: {panel_bg};
                border: 1px solid {panel_border};
                border-radius: 12px;
            }}
            QWidget#memoryAlbumRow {{
                background: {row_bg};
                border: 1px solid {row_border};
                border-radius: 8px;
            }}
            StrongBodyLabel#memoryAlbumRowTitle,
            BodyLabel#memoryAlbumText {{
                color: {text};
                font-size: 13px;
            }}
            BodyLabel#memoryAlbumMuted {{
                color: {muted};
                font-size: 12px;
            }}
            {_fluent_scrollbar_qss(dark=dark)}
        """)
