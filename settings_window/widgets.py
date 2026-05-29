from settings_window.constants import *


class FluentContextLineEdit(QLineEdit):
    def contextMenuEvent(self, event):
        menu = LineEditMenu(self)
        menu.exec(event.globalPos(), ani=True)


class FluentPlainTextEdit(QPlainTextEdit):
    def insertFromMimeData(self, source):
        self.insertPlainText(source.text())


class CodeLineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint_event(event)


class JsonCodeEdit(FluentPlainTextEdit):
    INDENT = "  "

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("JsonCodeEdit")
        self._line_number_area = CodeLineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._update_editor_caret)
        self.update_line_number_area_width(0)
        font = QFont("Cascadia Mono")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        font.setPointSize(10)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * len(self.INDENT))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setAcceptDrops(True)

    def line_number_area_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_editor_caret(self):
        self.viewport().update()
        self._line_number_area.update()

    def update_line_number_area_width(self, _block_count):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))

    def line_number_area_paint_event(self, event):
        painter = QPainter(self._line_number_area)
        dark = isDarkTheme()
        painter.fillRect(event.rect(), QColor("#252525" if dark else "#f4f4f4"))
        painter.setPen(QColor("#8f8f8f" if dark else "#737373"))

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        current_block = self.textCursor().blockNumber()
        width = self._line_number_area.width() - 5

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if block_number == current_block:
                    painter.setPen(QColor(BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY))
                else:
                    painter.setPen(QColor("#8f8f8f" if dark else "#737373"))
                painter.drawText(0, top, width, self.fontMetrics().height(), Qt.AlignmentFlag.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            if block.isValid():
                bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key.Key_Tab and not (
            modifiers
            & (
                Qt.KeyboardModifier.ControlModifier
                | Qt.KeyboardModifier.AltModifier
                | Qt.KeyboardModifier.ShiftModifier
            )
        ):
            self._indent_selection()
            return
        if key == Qt.Key.Key_Backtab or (
            key == Qt.Key.Key_Tab and modifiers & Qt.KeyboardModifier.ShiftModifier
        ):
            self._unindent_selection()
            return
        super().keyPressEvent(event)

    def _selected_blocks(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        if end > start:
            end -= 1
        block = self.document().findBlock(start)
        last = self.document().findBlock(end)
        blocks = []
        while block.isValid():
            blocks.append(block)
            if block == last:
                break
            block = block.next()
        return blocks

    def _indent_selection(self):
        cursor = self.textCursor()
        if not cursor.hasSelection():
            cursor.insertText(self.INDENT)
            return
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        blocks = self._selected_blocks()
        cursor.beginEditBlock()
        for block in blocks:
            line_cursor = QTextCursor(block)
            line_cursor.insertText(self.INDENT)
        cursor.endEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end + len(self.INDENT) * len(blocks), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)

    def _unindent_selection(self):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        blocks = self._selected_blocks()
        removed_before_start = 0
        removed_total = 0
        cursor.beginEditBlock()
        for block in blocks:
            text = block.text()
            count = 0
            if text.startswith("\t"):
                count = 1
            else:
                count = min(len(text) - len(text.lstrip(" ")), len(self.INDENT))
            if count <= 0:
                continue
            if block.position() < start:
                removed_before_start += count
            removed_total += count
            line_cursor = QTextCursor(block)
            line_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, count)
            line_cursor.removeSelectedText()
        cursor.endEditBlock()
        if cursor.hasSelection():
            new_start = max(0, start - removed_before_start)
            new_end = max(new_start, end - removed_total)
            cursor.setPosition(new_start)
            cursor.setPosition(new_end, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)


class OpaqueDropDownComboBox(ComboBox):
    def _createComboMenu(self):
        return OpaqueDropDownComboBoxMenu(self)


class OpaqueDropDownComboBoxMenu(ComboBoxMenu):
    def __init__(self, parent=None):
        super().__init__(parent)
        dark = isDarkTheme()
        bg = "#2b2b2b" if dark else "#ffffff"
        border = "#4a4a4a" if dark else "#d8d8d8"
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.setPalette(palette)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.view.setGraphicsEffect(None)
        self.view.setStyleSheet(
            self.view.styleSheet()
            + f"""
            QListWidget#comboListWidget {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            """
        )

    def exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        self.view.adjustSize(pos, aniType)
        self.adjustSize()
        if not ani:
            aniType = MenuAnimationType.NONE
        self.aniManager = MenuAnimationManager.make(self, aniType)
        self.aniManager.exec(pos)
        self.show()
        if getattr(self, "isSubMenu", False) and getattr(self, "menuItem", None):
            self.menuItem.setSelected(True)


class ModelListItem(QWidget):
    selected = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, character: str, title: str, subtitle: str, current: bool, parent=None):
        super().__init__(parent)
        self._character = character
        self._current = current
        self._selection_anim = None
        self._animated_bg = None
        self.setObjectName("ModelListItem")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 6, 6)
        layout.setSpacing(6)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._title = BodyLabel(title, self)
        self._subtitle = QLabel(subtitle, self)
        for label in (self._title, self._subtitle):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setToolTip(label.text())
        text_col.addWidget(self._title)
        text_col.addWidget(self._subtitle)
        layout.addLayout(text_col, 1)

        self._remove_btn = QToolButton(self)
        self._remove_btn.setText("x")
        self._remove_btn.setFixedSize(22, 22)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.clicked.connect(lambda: self.remove_requested.emit(self._character))
        layout.addWidget(self._remove_btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setFixedHeight(50)
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)
        if self._current:
            QTimer.singleShot(0, self._play_selected_animation)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._character)
        super().mousePressEvent(event)

    def _apply_theme(self):
        dark = isDarkTheme()
        selected_bg = QColor(BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT)
        bg = self._qss_color(self._animated_bg) if self._animated_bg else self._qss_color(selected_bg) if self._current else "transparent"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER
        text = "#f7f7fb" if dark else "#1f2328"
        muted = "#9aa5bd" if dark else "#657089"
        danger = "#ff6b6b" if dark else "#c42b1c"
        self.setStyleSheet(f"""
            #ModelListItem {{
                background: {bg};
                border-radius: 8px;
            }}
            #ModelListItem:hover {{ background: {hover}; }}
            QLabel {{ color: {muted}; font-size: 11px; }}
            BodyLabel {{ color: {text}; font-size: 13px; }}
            QToolButton {{
                color: {danger};
                background: transparent;
                border: none;
                border-radius: 11px;
                font-weight: 700;
            }}
            QToolButton:hover {{ background: {'#4a2730' if dark else '#fde7e9'}; }}
        """)

    @staticmethod
    def _qss_color(color: QColor) -> str:
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

    def _play_selected_animation(self):
        dark = isDarkTheme()
        start = QColor(BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT)
        start.setAlpha(0)
        end = QColor(BANDORI_PRIMARY_SOFT_DARK if dark else BANDORI_PRIMARY_SOFT)

        anim = QVariantAnimation(self)
        anim.setDuration(220)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_selected_anim_value)
        anim.finished.connect(self._on_selected_anim_finished)
        self._selection_anim = anim
        anim.start()

    def _on_selected_anim_value(self, value):
        self._animated_bg = value
        self._apply_theme()

    def _on_selected_anim_finished(self):
        self._animated_bg = None
        self._apply_theme()


class AddModelListItem(QPushButton):
    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(_tr("SettingsWindow.model_list_add"), parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.clicked.connect(self.add_requested.emit)
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def _apply_theme(self):
        dark = isDarkTheme()
        border = accent_color(dark)
        bg = "#242226" if dark else BANDORI_PRIMARY_SOFT
        hover = "#30262b" if dark else BANDORI_PRIMARY_SOFT_HOVER
        text = BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY
        self.setStyleSheet(f"""
            QPushButton {{
                color: {text};
                background: {bg};
                border: 1px dashed {border};
                border-radius: 10px;
                font-weight: 600;
                text-align: center;
            }}
            QPushButton:hover {{ background: {hover}; }}
        """)


class RoleplayStatusDot(QWidget):
    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self._status = status if status in _ROLEPLAY_STATUS_COLORS else "red"
        self.setFixedSize(14, 14)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setToolTip(_tr(_ROLEPLAY_STATUS_TIPS.get(self._status, "")))

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 210), 2))
        painter.setBrush(QBrush(QColor(_ROLEPLAY_STATUS_COLORS[self._status])))
        painter.drawEllipse(1, 1, self.width() - 2, self.height() - 2)


class FullHitToolButton(QToolButton):
    def hitButton(self, pos):
        return self.rect().contains(pos)


class CharacterCard(CardWidget):
    char_selected = Signal(str)
    favorite_toggled = Signal(str, bool)

    def __init__(self, char_key: str, display_name: str, costume_count: int,
                 image_path: str = "", roleplay_status: str = "red", parent=None,
                 image_data: bytes = b"", favorite: bool = False):
        super().__init__(parent)
        self._char_key = char_key
        self._favorite = bool(favorite)
        self._disabled_for_existing = False
        self.setFixedSize(220, 360)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._status_dot = RoleplayStatusDot(roleplay_status, self)
        self._favorite_btn = FullHitToolButton(self)
        self._favorite_btn.setCheckable(True)
        self._favorite_btn.setChecked(self._favorite)
        self._favorite_btn.setFixedSize(28, 28)
        self._favorite_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._favorite_btn.setToolTip(_tr("SettingsWindow.favorite_character_tooltip"))
        self._favorite_btn.clicked.connect(self._on_favorite_clicked)
        self._favorite_btn.raise_()
        self._position_status_dot()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        image = QPixmap(image_path) if image_path else QPixmap()
        if image.isNull() and image_data:
            image.loadFromData(image_data)
        if not image.isNull():
            image_label = QLabel(self)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            image_label.setPixmap(
                image.scaled(
                    188, 260,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(image_label, 1)

        name_label = StrongBodyLabel(display_name, self)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        self._count_label = BodyLabel(_tr("costume_count", count=costume_count), self)
        self._count_label.setStyleSheet(self._count_label_style())
        layout.addWidget(self._count_label)

        layout.addStretch()
        self.clicked.connect(self._on_card_clicked)
        qconfig.themeChanged.connect(self._update_count_label_style)
        qconfig.themeChanged.connect(self._update_favorite_style)
        self._update_favorite_style()

    def animate_in(self, delay_ms: int = 0):
        if self._disabled_for_existing:
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, anim.start)
        else:
            anim.start()

    @staticmethod
    def _count_label_style():
        return f"color: {'#999999' if isDarkTheme() else '#888888'};"

    def _update_count_label_style(self):
        self._count_label.setStyleSheet(self._count_label_style())

    def _on_card_clicked(self):
        if self._disabled_for_existing:
            return
        self.char_selected.emit(self._char_key)

    def _on_favorite_clicked(self, checked: bool):
        self._favorite = bool(checked)
        self._update_favorite_style()
        self.favorite_toggled.emit(self._char_key, self._favorite)

    def set_favorite(self, favorite: bool):
        self._favorite = bool(favorite)
        self._favorite_btn.setChecked(self._favorite)
        self._update_favorite_style()

    def _update_favorite_style(self):
        dark = isDarkTheme()
        icon_color = accent_color(dark) if self._favorite else ("#9aa5bd" if dark else "#7b8494")
        bg = BANDORI_PRIMARY_SOFT_DARK if self._favorite and dark else BANDORI_PRIMARY_SOFT if self._favorite else "#2b2b2b" if dark else "#ffffff"
        hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER
        border = accent_color(dark) if self._favorite else "#4a4a4a" if dark else "#d9dde7"
        self._favorite_btn.setIcon(FluentIcon.HEART.icon(color=QColor(icon_color)))
        self._favorite_btn.setStyleSheet(f"""
            QToolButton {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 14px;
            }}
            QToolButton:hover {{
                background: {hover};
                border-color: {accent_color(dark)};
            }}
        """)

    def set_disabled_for_existing(self, disabled: bool):
        self._disabled_for_existing = disabled
        self.setCursor(Qt.CursorShape.ForbiddenCursor if disabled else Qt.CursorShape.PointingHandCursor)
        self._favorite_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setGraphicsEffect(None)
        if disabled:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.38)
            self.setGraphicsEffect(effect)
            self._favorite_btn.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_status_dot()

    def _position_status_dot(self):
        self._status_dot.move(self.width() - self._status_dot.width() - 12, 12)
        self._favorite_btn.move(self.width() - self._favorite_btn.width() - 8, 34)
        self._favorite_btn.raise_()


class BandCard(CardWidget):
    band_selected = Signal(str)

    def __init__(self, band_id: str, display_name: str, character_count: int,
                 logo_path: str = "", roleplay_status: str = "red", parent=None):
        super().__init__(parent)
        self._band_id = band_id
        self.setFixedSize(180, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._status_dot = RoleplayStatusDot(roleplay_status, self)
        self._position_status_dot()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        name_label = StrongBodyLabel(display_name, self)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        self._count_label = BodyLabel(_tr("character_count", count=character_count), self)
        self._count_label.setStyleSheet(self._count_label_style())
        layout.addWidget(self._count_label)

        logo = QPixmap(logo_path) if logo_path else QPixmap()
        if not logo.isNull():
            logo_label = QLabel(self)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo_label.setPixmap(
                logo.scaled(
                    142, 36,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            layout.addWidget(logo_label)

        layout.addStretch()
        self.clicked.connect(self._on_card_clicked)
        qconfig.themeChanged.connect(self._update_count_label_style)

    def animate_in(self, delay_ms: int = 0):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, anim.start)
        else:
            anim.start()

    @staticmethod
    def _count_label_style():
        return f"color: {'#999999' if isDarkTheme() else '#888888'};"

    def _update_count_label_style(self):
        self._count_label.setStyleSheet(self._count_label_style())

    def _on_card_clicked(self):
        self.band_selected.emit(self._band_id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_status_dot()

    def _position_status_dot(self):
        self._status_dot.move(self.width() - self._status_dot.width() - 12, 12)


class CostumeItem(QPushButton):
    preview_requested = Signal(object, str)
    preview_toggled = Signal(object, str)
    preview_cancelled = Signal(str)
    favorite_toggled = Signal(str, bool)

    def __init__(self, costume_id: str, display_name: str, parent=None, favorite: bool = False):
        super().__init__(parent)
        self._costume_id = costume_id
        self._display_name = display_name
        self._favorite = bool(favorite)
        self.setText(display_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setCheckable(True)
        self._preview_btn = FullHitToolButton(self)
        self._preview_btn.setIcon(FluentIcon.VIEW.icon())
        self._preview_btn.setToolTip(_tr("SettingsWindow.preview_costume_tooltip"))
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setFixedSize(28, 28)
        self._preview_btn.clicked.connect(lambda checked=False: self.preview_toggled.emit(self, self._costume_id))
        self._favorite_btn = FullHitToolButton(self)
        self._favorite_btn.setCheckable(True)
        self._favorite_btn.setChecked(self._favorite)
        self._favorite_btn.setToolTip(_tr("SettingsWindow.favorite_costume_tooltip"))
        self._favorite_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._favorite_btn.setFixedSize(28, 28)
        self._favorite_btn.clicked.connect(self._on_favorite_clicked)
        self._preview_btn.raise_()
        self._favorite_btn.raise_()
        self._update_stylesheet()
        qconfig.themeChanged.connect(self._update_stylesheet)

    def animate_in(self, delay_ms: int = 0):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        if delay_ms > 0:
            QTimer.singleShot(delay_ms, anim.start)
        else:
            anim.start()

    def _update_stylesheet(self):
        dark = isDarkTheme()
        bg = "#2d2d2d" if dark else "#fafafa"
        border = "#555555" if dark else "#e0e0e0"
        hover_bg = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER
        hover_border = accent_color(dark)
        checked_bg = accent_color(dark)
        checked_fg = "#1a1a1a" if dark else "white"
        text_color = "#e0e0e0" if dark else "#333333"
        tool_bg = "#262626" if dark else "#ffffff"
        tool_border = "#4a4a4a" if dark else "#d9dde7"
        tool_hover = BANDORI_PRIMARY_SOFT_DARK_HOVER if dark else BANDORI_PRIMARY_SOFT_HOVER
        favorite_icon = accent_color(dark) if self._favorite else ("#9aa5bd" if dark else "#7b8494")
        self._preview_btn.setIcon(FluentIcon.VIEW.icon(color=QColor(text_color)))
        self._favorite_btn.setIcon(FluentIcon.HEART.icon(color=QColor(favorite_icon)))
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 8px 84px 8px 16px;
                border: 1px solid {border};
                border-radius: 6px;
                background: {bg};
                font-size: 14px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border-color: {hover_border};
            }}
            QPushButton:checked {{
                background: {checked_bg};
                color: {checked_fg};
                border-color: {hover_border};
            }}
            QToolButton {{
                background: {tool_bg};
                border: 1px solid {tool_border};
                border-radius: 14px;
            }}
            QToolButton:hover {{
                background: {tool_hover};
                border-color: {hover_border};
            }}
        """)

    @property
    def costume_id(self):
        return self._costume_id

    @property
    def display_name(self):
        return self._display_name

    def _on_favorite_clicked(self, checked: bool):
        self._favorite = bool(checked)
        self._update_stylesheet()
        self.favorite_toggled.emit(self._costume_id, self._favorite)

    def enterEvent(self, event):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.preview_requested.emit(self, self._costume_id)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.preview_cancelled.emit(self._costume_id)
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Shift:
            self.preview_requested.emit(self, self._costume_id)
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        y = (self.height() - self._preview_btn.height()) // 2
        self._favorite_btn.move(self.width() - self._favorite_btn.width() - 10, y)
        self._preview_btn.move(self._favorite_btn.x() - self._preview_btn.width() - 8, y)
        self._preview_btn.raise_()
        self._favorite_btn.raise_()


class Live2DPreviewBubble(QWidget):
    def __init__(self, live2d_module, quality_profile="balanced", parent=None):
        super().__init__(None)
        from live2d_widget import Live2DWidget

        self._current_model_path = ""
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.resize(300, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 10, 10, 10)
        self._live2d_widget = Live2DWidget(self)
        self._live2d_widget.set_live2d_module(live2d_module)
        self._live2d_widget.set_render_quality(quality_profile)
        self._live2d_widget.set_static_render(True)
        self._apply_live2d_background()
        layout.addWidget(self._live2d_widget)
        qconfig.themeChanged.connect(self._on_theme_changed)

    def _apply_windows_frame_fix(self):
        if os.name != "nt":
            return
        hwnd = int(self.winId())
        if not hwnd:
            return
        apply_windows_11_border_fix(hwnd)
        frame_changed(hwnd)

    def _on_theme_changed(self):
        self._apply_live2d_background()
        self.update()

    def _apply_live2d_background(self):
        if isDarkTheme():
            self._live2d_widget.set_clear_color(32 / 255, 32 / 255, 32 / 255, 1.0)
        else:
            self._live2d_widget.set_clear_color(1.0, 1.0, 1.0, 1.0)

    def set_render_quality(self, profile: str):
        self._live2d_widget.set_render_quality(profile)

    def _bubble_path(self) -> QPainterPath:
        rect = self.rect().adjusted(18, 2, -2, -2)
        tail_y = max(70, min(self.height() - 70, 150))

        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        tail = QPainterPath()
        tail.moveTo(19, tail_y - 18)
        tail.lineTo(2, tail_y)
        tail.lineTo(19, tail_y + 18)
        tail.closeSubpath()
        return path.united(tail)

    def _update_window_mask(self):
        self.setMask(QRegion(self._bubble_path().toFillPolygon().toPolygon()))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dark = isDarkTheme()
        bg = QColor(32, 32, 32, 255) if dark else QColor(255, 255, 255, 255)
        border = QColor(BANDORI_PRIMARY_DARK if dark else BANDORI_PRIMARY)
        border.setAlpha(190 if dark else 165)
        shadow = QColor(0, 0, 0, 65) if dark else QColor(0, 0, 0, 38)

        path = self._bubble_path()

        shadow_path = QPainterPath(path)
        shadow_path.translate(0, 3)
        painter.fillPath(shadow_path, QBrush(shadow))
        painter.fillPath(path, QBrush(bg))
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)

    def show_preview(self, model_path: str, anchor: QWidget):
        if not model_path:
            self.hide()
            return
        if model_path != self._current_model_path:
            self._current_model_path = model_path
            self._live2d_widget.set_model_path(model_path)

        top_right = anchor.mapToGlobal(anchor.rect().topRight())
        pos = top_right + QPoint(14, -120)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = min(max(pos.x(), geo.left()), geo.right() - self.width())
            y = min(max(pos.y(), geo.top()), geo.bottom() - self.height())
            pos = QPoint(x, y)
        self.move(pos)
        self._update_window_mask()
        self._apply_windows_frame_fix()
        if not self.isVisible():
            self.show()
            self._apply_windows_frame_fix()
        self.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_window_mask()

    def is_showing(self, model_path: str) -> bool:
        return self.isVisible() and model_path == self._current_model_path


class NavButton(QPushButton):
    nav_activated = Signal(str)

    def __init__(self, nav_key: str, icon, text: str, parent=None, accent: str = BANDORI_PRIMARY):
        super().__init__(parent)
        self._nav_key = nav_key
        self._custom_icon = icon if isinstance(icon, str) else ""
        self._fluent_icon = icon if hasattr(icon, "icon") else None
        self._fallback_icon = icon if isinstance(icon, QIcon) else QIcon()
        self._accent = QColor(accent if QColor(accent).isValid() else BANDORI_PRIMARY)
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self.setText(text)
        self.setCheckable(True)
        self.setIconSize(QSize(18, 18))
        self._update_stylesheet()
        qconfig.themeChanged.connect(self._update_stylesheet)
        self.clicked.connect(lambda: self.nav_activated.emit(self._nav_key))

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def _update_stylesheet(self):
        self.setStyleSheet("QPushButton { border: none; background: transparent; }")
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dark = isDarkTheme()
        checked = self.isChecked()
        accent = QColor(self._accent)
        if dark:
            accent = accent.lighter(118)

        if dark:
            bg = QColor("#242226")
            hover_bg = QColor("#2f2930")
            checked_bg = self._mix_color(QColor("#242226"), accent, 0.24)
            border = QColor("#413841")
            checked_border = self._mix_color(QColor("#413841"), accent, 0.55)
            text = QColor("#f1edf2")
            checked_text = QColor("#ffffff")
            muted_text = QColor("#cfc6d0")
        else:
            bg = QColor("#ffffff")
            hover_bg = QColor("#fff6f9")
            checked_bg = QColor(accent)
            checked_bg.setAlpha(28)
            border = QColor("#ece5ea")
            checked_border = QColor(accent)
            checked_border.setAlpha(170)
            text = QColor("#242832")
            checked_text = QColor(accent)
            muted_text = QColor("#4f5968")

        rect = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        painter.setPen(QPen(checked_border if checked else border, 1))
        painter.setBrush(QBrush(checked_bg if checked else hover_bg if self._hovered else bg))
        painter.drawRoundedRect(rect, 9, 9)

        plate_rect = QRectF(12, (self.height() - 28) / 2, 28, 28)
        plate = QColor(accent)
        plate.setAlpha(236 if checked else 38 if not dark else 52)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(plate))
        painter.drawRoundedRect(plate_rect, 8, 8)

        icon_color = QColor("#ffffff") if checked else QColor(accent)
        icon_rect = QRect(
            int(plate_rect.x() + 5),
            int(plate_rect.y() + 5),
            18,
            18,
        )
        if self._custom_icon == "avatar":
            self._paint_avatar_icon(painter, QRectF(icon_rect), icon_color)
        elif self._fluent_icon is not None:
            self._fluent_icon.icon(color=icon_color).paint(painter, icon_rect)
        else:
            self._fallback_icon.paint(painter, icon_rect)

        font = QFont(self.font())
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(checked_text if checked else muted_text if self._hovered else text)
        text_rect = QRect(50, 0, max(1, self.width() - 58), self.height())
        label = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

    @staticmethod
    def _mix_color(base: QColor, overlay: QColor, amount: float) -> QColor:
        amount = max(0.0, min(1.0, amount))
        inv = 1.0 - amount
        return QColor(
            int(base.red() * inv + overlay.red() * amount),
            int(base.green() * inv + overlay.green() * amount),
            int(base.blue() * inv + overlay.blue() * amount),
        )

    @staticmethod
    def _paint_avatar_icon(painter: QPainter, rect: QRectF, color: QColor):
        painter.save()
        pen = QPen(color, max(2, int(round(rect.width() * 0.12))))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        head_size = rect.width() * 0.38
        head = QRectF(
            rect.center().x() - head_size / 2,
            rect.top() + rect.height() * 0.13,
            head_size,
            head_size,
        )
        painter.drawEllipse(head)

        shoulders = QPainterPath()
        shoulders.moveTo(rect.left() + rect.width() * 0.18, rect.bottom() - rect.height() * 0.12)
        shoulders.cubicTo(
            rect.left() + rect.width() * 0.26,
            rect.top() + rect.height() * 0.62,
            rect.left() + rect.width() * 0.38,
            rect.top() + rect.height() * 0.57,
            rect.center().x(),
            rect.top() + rect.height() * 0.57,
        )
        shoulders.cubicTo(
            rect.left() + rect.width() * 0.62,
            rect.top() + rect.height() * 0.57,
            rect.left() + rect.width() * 0.74,
            rect.top() + rect.height() * 0.62,
            rect.right() - rect.width() * 0.18,
            rect.bottom() - rect.height() * 0.12,
        )
        painter.drawPath(shoulders)
        painter.restore()
