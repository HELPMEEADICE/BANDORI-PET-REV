import os

from PySide6.QtCore import Qt, QRectF, Signal, QTimer, QSize, QEvent
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPalette, QPixmap, QKeySequence
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import (
    QApplication,
    QTextEdit,
    QFrame,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
)
from qfluentwidgets import Action, FluentIcon, RoundMenu, isDarkTheme

from app_theme import accent_color
from i18n_manager import tr as _tr
from win32_dwm import apply_windows_11_border_fix, frame_changed


AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
INTERRUPT_COMMANDS = {"@stop", "/stop", "@停止", "/停止", "@中断", "/中断", "@interrupt", "/interrupt"}


COMMAND_REGISTRY = [
    ("@auto",     "@auto 或 @自动",            "启动自动聊天（可带话题）"),
    ("@stop",     "@stop 或 @停止",            "停止自动对话 / 中断生成"),
    ("@cot",      "@cot 或 @思维链",           "切换思维链/推理显示"),
    ("@web",      "@web 或 @联网搜索",         "切换联网搜索"),
    ("@sys",      "@sys-instruction 或 @系统提示", "切换最高优先级系统提示词"),
    ("@clock",    "@clock 或 @时钟",           "添加闹钟"),
    ("@pomodoro", "@pomodoro 或 @番茄钟",      "启动番茄钟计时器"),
    ("@memory",   "@memory 或 @记忆",          "查看记忆状态"),
    ("@status",   "@status 或 @状态",          "查看关系状态"),
    ("@remember", "@remember 或 @记住",        "手动记住内容"),
    ("@forget",   "@forget 或 @忘记",          "遗忘记忆"),
    ("@affection","@affection 或 @好感度",     "设置好感度 0-100"),
    ("@trust",    "@trust 或 @信任",          "设置信任值 0-100"),
    ("@familiarity","@familiarity 或 @熟悉度", "设置熟悉度 0-100"),
    ("@setmood",  "@setmood 或 @当前心情",     "设置当前心情 0-100"),
]


def _command_match_score(prefix: str, item: tuple) -> int:
    """计算命令与前缀的匹配分数，越小越靠前。"""
    lower = prefix.lower().replace("/", "@")
    primary, display, desc = item
    primary_norm = primary.lower()
    display_norm = display.lower().replace("/", "@")
    if primary_norm == lower:
        return 0
    if primary_norm.startswith(lower):
        return 1
    if lower in display_norm:
        return 2
    if lower in desc.lower():
        return 3
    return 99


def filter_commands(text: str):
    """根据输入文本过滤匹配的命令列表。"""
    if not text:
        return list(COMMAND_REGISTRY)
    lower = text.lower()
    scored = [(_command_match_score(lower, item), item) for item in COMMAND_REGISTRY]
    scored.sort(key=lambda x: x[0])
    return [item for _, item in scored if _ <= 2] or [item for _, item in scored if _ <= 3]


class FluentContextTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj == self.viewport() and event.type() == QEvent.Type.ContextMenu:
            self._show_context_menu(event.globalPos())
            event.accept()
            return True
        return super().eventFilter(obj, event)

    def contextMenuEvent(self, event):
        self._show_context_menu(event.globalPos())
        event.accept()

    def _show_context_menu(self, pos):
        menu = RoundMenu(parent=self)
        self._style_context_menu(menu)
        cursor = self.textCursor()
        has_selection = cursor.hasSelection()
        has_text = bool(self.toPlainText())
        can_edit = not self.isReadOnly()

        undo_action = self._make_context_action(
            menu, FluentIcon.RETURN, _tr("Common.undo", default="Undo"), QKeySequence.StandardKey.Undo, self.undo
        )
        redo_action = self._make_context_action(
            menu, FluentIcon.ROTATE, _tr("Common.redo", default="Redo"), QKeySequence.StandardKey.Redo, self.redo
        )
        undo_action.setEnabled(can_edit and self.document().isUndoAvailable())
        redo_action.setEnabled(can_edit and self.document().isRedoAvailable())
        menu.addActions([undo_action, redo_action])
        menu.addSeparator()

        cut_action = self._make_context_action(
            menu, FluentIcon.CUT, _tr("Common.cut", default="Cut"), QKeySequence.StandardKey.Cut, self.cut
        )
        copy_action = self._make_context_action(
            menu, FluentIcon.COPY, _tr("Common.copy", default="Copy"), QKeySequence.StandardKey.Copy, self.copy
        )
        paste_action = self._make_context_action(
            menu, FluentIcon.PASTE, _tr("Common.paste", default="Paste"), QKeySequence.StandardKey.Paste, self.paste
        )
        delete_action = self._make_context_action(
            menu, FluentIcon.DELETE, _tr("Common.delete", default="Delete"), None, self._delete_selection
        )
        cut_action.setEnabled(can_edit and has_selection)
        copy_action.setEnabled(has_selection)
        paste_action.setEnabled(can_edit and QApplication.clipboard().mimeData().hasText())
        delete_action.setEnabled(can_edit and has_selection)
        menu.addActions([cut_action, copy_action, paste_action, delete_action])
        menu.addSeparator()

        select_all_action = self._make_context_action(
            menu,
            FluentIcon.CLEAR_SELECTION,
            _tr("Common.select_all", default="Select All"),
            QKeySequence.StandardKey.SelectAll,
            self.selectAll,
        )
        select_all_action.setEnabled(has_text)
        menu.addAction(select_all_action)
        menu.exec(pos, ani=True)

    def _make_context_action(self, menu, icon, text, shortcut, slot):
        action = Action(icon, text, menu)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(slot)
        return action

    def _style_context_menu(self, menu):
        dark = isDarkTheme()
        bg = "#1f2430" if dark else "#ffffff"
        text = "#f4f6fb" if dark else "#20242d"
        muted = "rgba(255, 255, 255, 138)" if dark else "rgba(32, 36, 45, 150)"
        border = "rgba(255, 255, 255, 24)" if dark else "rgba(32, 36, 45, 28)"
        hover = "rgba(255, 255, 255, 20)" if dark else "rgba(160, 32, 96, 18)"
        pressed = "rgba(255, 255, 255, 30)" if dark else "rgba(160, 32, 96, 30)"
        accent = accent_color(dark)

        menu.setObjectName("FluentTextEditContextMenu")
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        menu.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        menu.setAutoFillBackground(True)
        menu.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        menu.view.setViewportMargins(0, 6, 0, 6)
        menu.view.setObjectName("FluentTextEditContextMenuView")
        menu.view.setFrameShape(QFrame.Shape.NoFrame)
        menu.view.setGraphicsEffect(None)
        menu.view.setAutoFillBackground(True)
        menu.view.viewport().setAutoFillBackground(True)
        menu.view.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        palette = menu.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(bg))
        palette.setColor(QPalette.ColorRole.Base, QColor(bg))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        menu.setPalette(palette)
        menu.view.setPalette(palette)

        menu_style = f"""
            QMenu#FluentTextEditContextMenu,
            RoundMenu#FluentTextEditContextMenu {{
                background: {bg};
                border: none;
                border-radius: 12px;
            }}
            QListWidget#FluentTextEditContextMenuView,
            MenuActionListWidget#FluentTextEditContextMenuView {{
                background: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 12px;
                outline: none;
                padding: 4px;
                selection-background-color: transparent;
            }}
            QListWidget#FluentTextEditContextMenuView::item,
            MenuActionListWidget#FluentTextEditContextMenuView::item {{
                height: 32px;
                border: none;
                border-radius: 7px;
                color: {text};
                padding: 0 12px 0 10px;
                margin: 1px 4px;
            }}
            QListWidget#FluentTextEditContextMenuView::item:selected,
            QListWidget#FluentTextEditContextMenuView::item:hover,
            MenuActionListWidget#FluentTextEditContextMenuView::item:selected,
            MenuActionListWidget#FluentTextEditContextMenuView::item:hover {{
                background: {hover};
                color: {text};
            }}
            QListWidget#FluentTextEditContextMenuView::item:pressed,
            MenuActionListWidget#FluentTextEditContextMenuView::item:pressed {{
                background: {pressed};
            }}
            QListWidget#FluentTextEditContextMenuView::item:disabled,
            MenuActionListWidget#FluentTextEditContextMenuView::item:disabled {{
                color: {muted};
            }}
            QListWidget#FluentTextEditContextMenuView::separator,
            MenuActionListWidget#FluentTextEditContextMenuView::separator {{
                height: 1px;
                background: {border};
                margin: 5px 8px;
            }}
            QListWidget#FluentTextEditContextMenuView QScrollBar:vertical,
            MenuActionListWidget#FluentTextEditContextMenuView QScrollBar:vertical {{
                width: 6px;
                background: transparent;
            }}
            QListWidget#FluentTextEditContextMenuView QScrollBar::handle:vertical,
            MenuActionListWidget#FluentTextEditContextMenuView QScrollBar::handle:vertical {{
                background: {accent};
                border-radius: 3px;
            }}
        """
        menu.setStyleSheet(menu_style)
        menu.view.setStyleSheet(menu_style)
        menu.view.viewport().setStyleSheet(f"background: {bg}; border: none; color: {text};")
        menu.aboutToShow.connect(lambda: QTimer.singleShot(0, lambda: self._refresh_context_menu_window(menu)))

    def _refresh_context_menu_window(self, menu):
        width = menu.width()
        height = menu.height()
        if width > 0 and height > 0:
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, width, height), 12, 12)
            menu.setMask(QRegion(path.toFillPolygon().toPolygon()))

        hwnd = int(menu.winId())
        if hwnd:
            apply_windows_11_border_fix(hwnd)
            frame_changed(hwnd)

    def _delete_selection(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            cursor.removeSelectedText()
            self.setTextCursor(cursor)


class _CommandListItem(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(8)
        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            "color: #1f2328; font-size: 10pt; font-weight: 600; padding: 0; border: none; background: transparent;"
        )
        self._name_label.setMinimumWidth(0)
        self._desc_label = QLabel()
        self._desc_label.setStyleSheet(
            "color: #657089; font-size: 9pt; padding: 0; border: none; background: transparent;"
        )
        self._desc_label.setMinimumWidth(0)
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._name_label, 0)
        layout.addWidget(self._desc_label, 1)
        self._full_name = ""
        self._full_desc = ""

    def set_command(self, name: str, desc: str):
        self._full_name = name
        self._full_desc = desc
        self._update_elided_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self):
        width = max(0, self.width() - 28)
        desc_target_width = 128 if width >= 300 else 72
        name_width = max(96, min(max(142, width // 2), width - desc_target_width - 8))
        desc_width = max(0, width - name_width - 8)
        name_metrics = QFontMetrics(self._name_label.font())
        desc_metrics = QFontMetrics(self._desc_label.font())
        self._name_label.setFixedWidth(name_width)
        self._name_label.setText(name_metrics.elidedText(self._full_name, Qt.TextElideMode.ElideRight, name_width))
        self._desc_label.setText(desc_metrics.elidedText(self._full_desc, Qt.TextElideMode.ElideRight, desc_width))


class CommandCompleter(QWidget):
    command_selected = Signal(str)

    MAX_VISIBLE = 7
    ITEM_HEIGHT = 34
    MIN_WIDTH = 420
    MARGIN = 10

    def __init__(self, input_widget: QTextEdit):
        super().__init__(input_widget.window())
        self._input = input_widget
        self._items: list[tuple] = []
        self._shown = False
        self._follow_timer = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self.setObjectName("commandCompleterPopup")
        self.setStyleSheet("""
            #commandCompleterPopup {
                background-color: #fbfdff;
                border: 1px solid #d6deea;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background: #fbfdff;
                border: none;
                outline: none;
                color: #1f2328;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                border-radius: 5px;
                margin: 1px 2px;
                padding: 0;
            }
            QListWidget::item:selected {
                background: #edf4ff;
            }
            QListWidget::item:hover:!selected {
                background: #f3f8ff;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 4px 2px 4px 0;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: #c9d4e3;
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: #aebccc;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

    def _clear(self):
        self._list.clear()
        self._items = []

    def _build_items(self, items: list[tuple]):
        self._clear()
        self._items = list(items)
        for _primary, display, desc in items:
            row_item = QListWidgetItem()
            row_item.setSizeHint(QSize(0, self.ITEM_HEIGHT))
            self._list.addItem(row_item)

            command_widget = _CommandListItem()
            command_widget.setFixedHeight(self.ITEM_HEIGHT)
            command_widget.set_command(display, desc)
            self._list.setItemWidget(row_item, command_widget)

    def _position_popup(self):
        if not self._items:
            return
        input_top_left = self._input.mapToGlobal(self._input.rect().topLeft())
        input_bottom_left = self._input.mapToGlobal(self._input.rect().bottomLeft())
        window = self._input.window()
        screen = window.screen() if window is not None else QApplication.screenAt(input_top_left)
        primary_screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else primary_screen.availableGeometry()
        window_rect = window.frameGeometry() if window is not None else available

        horizontal_bounds = available.intersected(window_rect)
        if horizontal_bounds.isEmpty():
            horizontal_bounds = available
        max_width = max(180, horizontal_bounds.width() - self.MARGIN * 2)
        width = min(max(self._input.width(), self.MIN_WIDTH), max_width)
        x = input_top_left.x()
        if x + width > horizontal_bounds.right() - self.MARGIN:
            x = horizontal_bounds.right() - self.MARGIN - width
        x = max(horizontal_bounds.left() + self.MARGIN, x)

        top_limit = max(available.top(), window_rect.top()) + self.MARGIN
        bottom_limit = min(available.bottom(), window_rect.bottom()) - self.MARGIN
        available_above = max(0, input_top_left.y() - top_limit - 6)
        available_below = max(0, bottom_limit - input_bottom_left.y() - 6)
        row_height = self.ITEM_HEIGHT + 2
        max_rows_above = max(1, available_above // row_height)
        max_rows_below = max(1, available_below // row_height)

        if available_above >= row_height * min(len(self._items), self.MAX_VISIBLE) or available_above >= available_below:
            visible = max(1, min(len(self._items), self.MAX_VISIBLE, max_rows_above))
            height = visible * row_height + 8
            y = max(top_limit, input_top_left.y() - height - 6)
        else:
            visible = max(1, min(len(self._items), self.MAX_VISIBLE, max_rows_below))
            height = visible * row_height + 8
            y = min(bottom_limit - height, input_bottom_left.y() + 6)

        if hasattr(self, '_last_geo') and self._last_geo == (x, y, width, height):
            return
        self._last_geo = (x, y, width, height)
        self.setGeometry(x, y, width, height)

    def show_commands(self, items: list[tuple]):
        if not items:
            self.hide()
            return
        self._build_items(items)
        self._position_popup()
        if self._items:
            self._list.setCurrentRow(0)
        self._shown = True
        self.show()

    def hide(self):
        self._shown = False
        super().hide()

    def showEvent(self, event):
        super().showEvent(event)
        if self._follow_timer is None:
            self._follow_timer = QTimer(self)
            self._follow_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._follow_timer.timeout.connect(self._on_follow_timer)
        self._follow_timer.start(10)

    def hideEvent(self, event):
        if self._follow_timer is not None:
            self._follow_timer.stop()
        self._last_geo = None
        super().hideEvent(event)

    def _on_follow_timer(self):
        if self._shown:
            self._position_popup()

    def filter(self, text: str):
        items = filter_commands(text)
        if items:
            self.show_commands(items)
        else:
            self.hide()

    def move_up(self):
        if not self._shown:
            return
        row = self._list.currentRow()
        if row > 0:
            self._list.setCurrentRow(row - 1)

    def move_down(self):
        if not self._shown:
            return
        row = self._list.currentRow()
        if row < self._list.count() - 1:
            self._list.setCurrentRow(row + 1)

    def select_current(self):
        if not self._shown:
            return
        row = self._list.currentRow()
        if 0 <= row < len(self._items):
            primary = self._items[row][0]
            self.hide()
            self.command_selected.emit(primary)

    def _on_item_clicked(self, item: QListWidgetItem):
        row = self._list.row(item)
        if 0 <= row < len(self._items):
            primary = self._items[row][0]
            self.hide()
            self.command_selected.emit(primary)

    def is_shown(self) -> bool:
        return self._shown


def circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    if source.isNull():
        return QPixmap()

    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    rounded = QPixmap(size, size)
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path_shape = QPainterPath()
    path_shape.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(path_shape)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return rounded


def rounded_avatar_pixmap(path: str, size: int) -> QPixmap:
    if not path or not os.path.exists(path):
        return QPixmap()
    source = QPixmap(path)
    if source.isNull():
        return QPixmap()

    side = min(source.width(), source.height())
    crop = source.copy(
        max(0, (source.width() - side) // 2),
        max(0, (source.height() - side) // 2),
        side,
        side,
    )
    return circular_pixmap(crop, size)
