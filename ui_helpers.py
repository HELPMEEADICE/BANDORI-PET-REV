import os

from PySide6.QtCore import Qt, QRectF, QEvent, Signal, QTimer, QSize
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QFont
from PySide6.QtWidgets import (
    QTextEdit,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QHBoxLayout,
    QVBoxLayout,
    QFrame,
    QLabel,
    QSpacerItem,
    QSizePolicy,
)
from qfluentwidgets.components.widgets.menu import TextEditMenu


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
    def contextMenuEvent(self, event):
        menu = TextEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


class _CommandListItem(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(8)
        self._name_label = QLabel()
        self._name_label.setStyleSheet(
            "color: #1f2328; font-size: 10pt; font-weight: 600; padding: 0; border: none; background: transparent;"
        )
        self._desc_label = QLabel()
        self._desc_label.setStyleSheet(
            "color: #657089; font-size: 9pt; padding: 0; border: none; background: transparent;"
        )
        self._desc_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._name_label)
        layout.addWidget(self._desc_label, 1)

    def set_command(self, name: str, desc: str):
        self._name_label.setText(name)
        self._desc_label.setText(desc)


class CommandCompleter(QWidget):
    command_selected = Signal(str)

    MAX_VISIBLE = 8
    ITEM_HEIGHT = 32

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
                background-color: rgba(248, 250, 253, 204);
                border: 1px solid #d0d5dd;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                background: transparent;
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
                background: rgba(0, 0, 0, 0.06);
            }
            QListWidget::item:hover:!selected {
                background: rgba(0, 0, 0, 0.03);
            }
            QScrollBar:vertical {
                background: transparent;
                width: 6px;
                margin: 4px 2px 4px 0;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.15);
                min-height: 24px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.25);
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
        for primary, display, desc in items:
            row_item = QListWidgetItem()
            row_item.setSizeHint(QSize(0, self.ITEM_HEIGHT))
            self._list.addItem(row_item)

            command_widget = _CommandListItem()
            command_widget.set_command(display, desc)
            self._list.setItemWidget(row_item, command_widget)

    def _position_popup(self):
        if not self._items:
            return
        input_global = self._input.mapToGlobal(self._input.rect().topLeft())
        width = self._input.width()
        visible = min(len(self._items), self.MAX_VISIBLE)
        height = visible * (self.ITEM_HEIGHT + 2) + 8
        x, y = input_global.x(), input_global.y() - height
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
