from PySide6.QtCore import Qt, Signal, QThread, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation, QPoint, QEvent
from PySide6.QtGui import QFont, QColor, QPalette, QPixmap, QCursor, QPainter, QPainterPath, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QSizePolicy, QSpacerItem, QScrollArea,
    QLineEdit, QGraphicsOpacityEffect, QGraphicsColorizeEffect, QApplication,
)

from qfluentwidgets import (
    CardWidget, PushButton, PrimaryPushButton,
    BodyLabel, StrongBodyLabel, TitleLabel, SubtitleLabel,
    FluentIcon, Slider, SwitchButton, ScrollArea, ComboBox,
    setTheme, Theme, isDarkTheme, InfoBar, InfoBarPosition,
)
from qfluentwidgets.common.config import qconfig

from i18n_manager import tr as _tr, set_language, available_languages, current_language

import json

from live2d_widget import Live2DWidget

_BG_LIGHT = "#ffffff"
_BG_DARK = "#1e1e1e"


def _theme_color(key: str) -> QColor:
    colors = {
        "bg": QColor(_BG_DARK if isDarkTheme() else _BG_LIGHT),
        "text": QColor("#ffffff" if isDarkTheme() else "#000000"),
        "dim": QColor("#999999" if isDarkTheme() else "#888888"),
    }
    return colors.get(key, QColor(_BG_LIGHT))


class CharacterCard(CardWidget):
    char_selected = Signal(str)

    def __init__(self, char_key: str, display_name: str, costume_count: int,
                 image_path: str = "", parent=None):
        super().__init__(parent)
        self._char_key = char_key
        self.setFixedSize(220, 360)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        image = QPixmap(image_path) if image_path else QPixmap()
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
        self.char_selected.emit(self._char_key)


class BandCard(CardWidget):
    band_selected = Signal(str)

    def __init__(self, band_id: str, display_name: str, character_count: int,
                 logo_path: str = "", parent=None):
        super().__init__(parent)
        self._band_id = band_id
        self.setFixedSize(180, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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


class CostumeItem(QPushButton):
    preview_requested = Signal(object, str)
    preview_cancelled = Signal()

    def __init__(self, costume_id: str, display_name: str, parent=None):
        super().__init__(parent)
        self._costume_id = costume_id
        self.setText(display_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setCheckable(True)
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
        hover_bg = "#3a3a3a" if dark else "#e8f0fe"
        hover_border = "#60cdff" if dark else "#1a73e8"
        checked_bg = "#60cdff" if dark else "#1a73e8"
        checked_fg = "#1a1a1a" if dark else "white"
        text_color = "#e0e0e0" if dark else "#333333"
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 8px 16px;
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
        """)

    @property
    def costume_id(self):
        return self._costume_id

    def enterEvent(self, event):
        self._maybe_request_preview()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.preview_cancelled.emit()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        self._maybe_request_preview()
        super().keyPressEvent(event)

    def _maybe_request_preview(self):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.preview_requested.emit(self, self._costume_id)


class Live2DPreviewBubble(QWidget):
    def __init__(self, live2d_module, parent=None):
        super().__init__(None)
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
        self._live2d_widget.set_static_render(True)
        self._apply_live2d_background()
        layout.addWidget(self._live2d_widget)
        qconfig.themeChanged.connect(self._on_theme_changed)

    def _on_theme_changed(self):
        self._apply_live2d_background()
        self.update()

    def _apply_live2d_background(self):
        if isDarkTheme():
            self._live2d_widget.set_clear_color(32 / 255, 32 / 255, 32 / 255, 1.0)
        else:
            self._live2d_widget.set_clear_color(1.0, 1.0, 1.0, 1.0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        dark = isDarkTheme()
        bg = QColor(32, 32, 32, 255) if dark else QColor(255, 255, 255, 255)
        border = QColor(96, 205, 255, 190) if dark else QColor(26, 115, 232, 165)
        shadow = QColor(0, 0, 0, 65) if dark else QColor(0, 0, 0, 38)

        rect = self.rect().adjusted(18, 2, -2, -2)
        tail_y = max(70, min(self.height() - 70, 150))

        path = QPainterPath()
        path.addRoundedRect(rect, 18, 18)
        tail = QPainterPath()
        tail.moveTo(19, tail_y - 18)
        tail.lineTo(2, tail_y)
        tail.lineTo(19, tail_y + 18)
        tail.closeSubpath()
        path = path.united(tail)

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
        if not self.isVisible():
            self.show()
        self.raise_()


class NavButton(QPushButton):
    nav_activated = Signal(str)

    def __init__(self, nav_key: str, icon, text: str, parent=None):
        super().__init__(parent)
        self._nav_key = nav_key
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(44)
        if hasattr(icon, 'icon'):
            self.setIcon(icon.icon())
        else:
            self.setIcon(icon)
        self.setText(f"  {text}")
        self.setCheckable(True)
        self._update_stylesheet()
        qconfig.themeChanged.connect(self._update_stylesheet)
        self.clicked.connect(lambda: self.nav_activated.emit(self._nav_key))

    def enterEvent(self, event):
        if not self._checking_hover_effect():
            self._apply_hover_effect(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_hover_effect(False)
        super().leaveEvent(event)

    def _checking_hover_effect(self):
        eff = self.graphicsEffect()
        return isinstance(eff, QGraphicsColorizeEffect) and eff.strength() > 0.0

    def _apply_hover_effect(self, entering: bool):
        eff = self.graphicsEffect()
        if not isinstance(eff, QGraphicsColorizeEffect):
            eff = QGraphicsColorizeEffect(self)
            eff.setColor(QColor(96, 205, 255))
            eff.setStrength(0.0)
            self.setGraphicsEffect(eff)
        if hasattr(self, '_hover_anim'):
            self._hover_anim.stop()
        self._hover_anim = QPropertyAnimation(eff, b"strength")
        self._hover_anim.setDuration(180)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.setStartValue(eff.strength())
        self._hover_anim.setEndValue(0.35 if entering else 0.0)
        if not entering:
            self._hover_anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._hover_anim.start()

    def _update_stylesheet(self):
        dark = isDarkTheme()
        bg = "#2a2a2a" if dark else "#fafafa"
        hover_bg = "#3a3a3a" if dark else "#e0e7f0"
        checked_bg = "#3a3a5a" if dark else "#d1e4ff"
        checked_border = "#60cdff"
        text_color = "#e0e0e0" if dark else "#2a2a2a"
        checked_text = "#ffffff" if dark else "#0d5ec9"
        border = "1px solid transparent" if dark else "1px solid #e0e0e0"
        self.setStyleSheet(f"""
            QPushButton {{
                text-align: left;
                padding: 8px 14px;
                border: {border};
                border-radius: 8px;
                background: {bg};
                font-size: 14px;
                color: {text_color};
            }}
            QPushButton:hover {{
                background: {hover_bg};
            }}
            QPushButton:checked {{
                background: {checked_bg};
                color: {checked_text};
            }}
        """)


class SettingsWindow(QWidget):
    model_selected = Signal(str, str)
    settings_changed = Signal(dict)
    launch_requested = Signal()

    def __init__(self, model_manager, current_char="", current_costume="",
                 current_fps=120, current_opacity=1.0, show_launch=True,
                 start_on_costumes=False, config_manager=None, vsync=True,
                 live2d_module=None):
        super().__init__()
        self._model_manager = model_manager
        self._live2d = live2d_module
        self._current_char = current_char or model_manager.characters[0]
        self._current_costume = current_costume
        self._fps = current_fps
        self._opacity = current_opacity
        self._costume_buttons: list[CostumeItem] = []
        self._selection_cards: list[CardWidget] = []
        self._selected_costume = ""
        self._selected_band = model_manager.get_character_band(self._current_char)
        self._preview_bubble = None
        self._show_launch = show_launch
        self._start_on_costumes = start_on_costumes
        self._theme_widgets: list[QWidget] = []
        self._cfg = config_manager
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, NavButton] = {}
        self._current_page = "characters"
        self._vsync = vsync

        self.setWindowTitle(_tr("SettingsWindow.title"))
        self.setMinimumSize(1050, 650)
        self.resize(1050, 650)

        self._launched = False
        self._init_ui()
        QApplication.instance().installEventFilter(self)

        if self._current_costume:
            self._selected_costume = self._current_costume
        else:
            self._selected_costume = self._model_manager.get_default_costume(
                self._current_char
            )

        self._nav_buttons["characters"].setChecked(True)

        if self._start_on_costumes:
            self._populate_costumes(self._current_char)
            display = self._model_manager.get_display_name(self._current_char)
            self._costume_title.setText(_tr("SettingsWindow.costumes_title", display=display))
            self._costume_subtitle.setText(_tr("SettingsWindow.costume_subtitle", display=display))
            self._char_page.hide()
            self._costume_page.show()
        else:
            self._populate_bands()

    def _on_language_changed(self, index: int):
        lang = self._lang_combo.itemData(index)
        if lang and lang != current_language():
            set_language(lang)
            if self._cfg:
                self._cfg.set("language", lang)
                self._cfg.save()

    def closeEvent(self, event):
        self._hide_costume_preview()
        if not self._launched:
            self._on_apply()
        self._save_llm_config()
        self._cleanup_workers()
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyRelease and event.key() == Qt.Key.Key_Shift:
            self._hide_costume_preview()
        elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Shift:
            widget = QApplication.widgetAt(QCursor.pos())
            while widget is not None:
                if isinstance(widget, CostumeItem):
                    self._show_costume_preview(widget, widget.costume_id)
                    break
                widget = widget.parentWidget()
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, '_entrance_done'):
            self._entrance_done = True
            QTimer.singleShot(80, self._play_entrance)
            QTimer.singleShot(120, lambda: self._animate_indicator(self._current_page))

    def _play_entrance(self):
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start()

    @staticmethod
    def _animate_button_in(btn):
        effect = QGraphicsOpacityEffect(btn)
        effect.setOpacity(0.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", btn)
        anim.setDuration(200)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: btn.setGraphicsEffect(None))
        anim.start()

    def _cleanup_workers(self):
        for attr in ('_test_worker', '_fetch_worker'):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(2000)

    def _make_theme_widget(self, w: QWidget) -> QWidget:
        w.setAutoFillBackground(True)
        self._theme_widgets.append(w)
        self._apply_theme_bg(w)
        return w

    def _apply_theme_bg(self, w: QWidget):
        bg = _BG_DARK if isDarkTheme() else _BG_LIGHT
        pal = w.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(bg))
        w.setPalette(pal)

    def _update_all_theme_bgs(self):
        for w in self._theme_widgets:
            self._apply_theme_bg(w)

    def _init_ui(self):
        self._make_theme_widget(self)
        qconfig.themeChanged.connect(self._update_all_theme_bgs)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = self._build_sidebar()
        main_layout.addWidget(sidebar, 0)

        right_area = QWidget()
        right_layout = QHBoxLayout(right_area)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(16)

        self._page_stack = self._make_theme_widget(QWidget())
        self._page_stack_layout = QVBoxLayout(self._page_stack)
        self._page_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._page_stack_layout.setSpacing(0)

        self._char_page = self._build_char_page()
        self._costume_page = self._build_costume_page()
        self._llm_page = self._build_llm_page()
        self._costume_page.hide()
        self._llm_page.hide()

        self._page_stack_layout.addWidget(self._char_page)
        self._page_stack_layout.addWidget(self._costume_page)
        self._page_stack_layout.addWidget(self._llm_page)

        self._pages["characters"] = self._char_page
        self._pages["costumes"] = self._costume_page
        self._pages["llm"] = self._llm_page

        page_scroll = ScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setWidget(self._page_stack)
        page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        side_panel = self._build_side_panel()

        right_layout.addWidget(page_scroll, 1)
        right_layout.addWidget(side_panel, 0)

        main_layout.addWidget(right_area, 1)

    def _update_sidebar_style(self):
        if not hasattr(self, '_sidebar'):
            return
        dark = isDarkTheme()
        self._sidebar.setStyleSheet(f"""
            #sidebar {{
                background: {'#181818' if dark else '#f5f6f8'};
                border-right: 1px solid {'#404040' if dark else '#d5d5d5'};
            }}
        """)

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(180)
        sidebar.setObjectName("sidebar")
        self._sidebar = sidebar

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)

        title = StrongBodyLabel(_tr("SettingsWindow.nav_title"), sidebar)
        title.setContentsMargins(12, 4, 0, 8)
        layout.addWidget(title)

        btn_chars = NavButton("characters", FluentIcon.EMOJI_TAB_SYMBOLS, _tr("SettingsWindow.nav_chars"), sidebar)
        btn_chars.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["characters"] = btn_chars
        layout.addWidget(btn_chars)

        btn_llm = NavButton("llm", FluentIcon.ROBOT, _tr("SettingsWindow.nav_llm"), sidebar)
        btn_llm.nav_activated.connect(self._on_nav_selected)
        self._nav_buttons["llm"] = btn_llm
        layout.addWidget(btn_llm)

        layout.addStretch()

        self._update_sidebar_style()
        self._theme_widgets.append(sidebar)
        qconfig.themeChanged.connect(self._update_sidebar_style)

        self._nav_indicator = QWidget(sidebar)
        self._nav_indicator.setFixedSize(4, 28)
        self._nav_indicator.setStyleSheet(f"""
            background: #60cdff;
            border-radius: 2px;
        """)
        self._nav_indicator.hide()

        return sidebar

    def _on_nav_selected(self, nav_key: str):
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == nav_key)
        for key, page in self._pages.items():
            if key.endswith("costumes"):
                continue
            page.setVisible(key == nav_key)
        self._costume_page.hide()
        if nav_key == "characters":
            self._populate_bands()
        self._current_page = nav_key
        self._animate_indicator(nav_key)

    def _animate_indicator(self, nav_key: str):
        btn = self._nav_buttons.get(nav_key)
        if btn is None:
            return
        target_y = btn.mapTo(btn.parent(), btn.rect().topLeft()).y()
        target_y += (btn.height() - self._nav_indicator.height()) // 2
        target_x = 6
        target = self._nav_indicator.geometry()
        target.setRect(target_x, target_y, 4, 28)

        if not self._nav_indicator.isVisible():
            self._nav_indicator.move(target_x, target_y)
            self._nav_indicator.show()
            effect = QGraphicsOpacityEffect(self._nav_indicator)
            effect.setOpacity(0.0)
            self._nav_indicator.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", self._nav_indicator)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.finished.connect(lambda: self._nav_indicator.setGraphicsEffect(None))
            anim.start()
            return

        if hasattr(self, '_indicator_anim') and self._indicator_anim:
            self._indicator_anim.stop()
        self._indicator_anim = QPropertyAnimation(self._nav_indicator, b"geometry")
        self._indicator_anim.setDuration(300)
        self._indicator_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._indicator_anim.setStartValue(self._nav_indicator.geometry())
        self._indicator_anim.setEndValue(target)
        self._indicator_anim.start()

    def _build_char_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        self._selection_back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.band_back"), page)
        self._selection_back_btn.clicked.connect(self._go_back_to_bands)
        top_row.addWidget(self._selection_back_btn)
        top_row.addStretch()
        self._selection_title = TitleLabel(_tr("SettingsWindow.band_title"), page)
        top_row.addWidget(self._selection_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._selection_subtitle = SubtitleLabel(_tr("SettingsWindow.band_subtitle"), page)
        layout.addWidget(self._selection_subtitle)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        grid_widget = self._make_theme_widget(QWidget())
        self._char_grid = QGridLayout(grid_widget)
        self._char_grid.setSpacing(12)
        self._char_grid.setContentsMargins(0, 8, 0, 0)
        cols_per_row = 3
        for c in range(cols_per_row):
            self._char_grid.setColumnStretch(c, 0)
        self._selection_grid_widget = grid_widget
        self._selection_back_btn.hide()

        scroll.setWidget(grid_widget)
        layout.addWidget(scroll, 1)
        return page

    def _clear_selection_cards(self):
        for card in self._selection_cards:
            self._char_grid.removeWidget(card)
            card.deleteLater()
        self._selection_cards.clear()

    def _populate_bands(self):
        self._clear_selection_cards()
        self._selected_band = ""
        self._selection_back_btn.hide()
        self._selection_title.setText(_tr("SettingsWindow.band_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.band_subtitle"))

        col = 0
        row = 0
        cols_per_row = 3
        card_idx = 0
        for band in self._model_manager.bands:
            characters = band.get("characters", [])
            if not characters:
                continue
            card = BandCard(
                band.get("id", ""), band.get("display", ""),
                len(characters), band.get("logo", ""), self._selection_grid_widget
            )
            card.band_selected.connect(self._on_band_selected)
            card.animate_in(delay_ms=card_idx * 80)
            self._char_grid.addWidget(card, row, col)
            self._selection_cards.append(card)
            col += 1
            card_idx += 1
            if col >= cols_per_row:
                col = 0
                row += 1

    def _populate_characters(self, band_id: str):
        self._clear_selection_cards()
        self._selected_band = band_id
        self._selection_back_btn.show()
        band_display = self._model_manager.get_band_display_name(band_id)
        self._selection_title.setText(_tr("SettingsWindow.char_title"))
        self._selection_subtitle.setText(_tr("SettingsWindow.char_subtitle_with_band", band=band_display))

        col = 0
        row = 0
        card_idx = 0
        for char_key in self._model_manager.get_band_characters(band_id):
            costumes = self._model_manager.get_costumes(char_key)
            if not costumes:
                continue
            display = self._model_manager.get_display_name(char_key)
            image_path = self._model_manager.get_character_image_path(char_key)
            card = CharacterCard(
                char_key, display, len(costumes), image_path,
                self._selection_grid_widget
            )
            card.char_selected.connect(self._on_char_selected)
            card.animate_in(delay_ms=card_idx * 80)
            self._char_grid.addWidget(card, row, col)
            self._selection_cards.append(card)
            col += 1
            card_idx += 1

    def _build_costume_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        back_btn = PushButton(FluentIcon.LEFT_ARROW, _tr("SettingsWindow.costume_back"), page)
        back_btn.clicked.connect(self._go_back_to_chars)
        top_row.addWidget(back_btn)
        top_row.addStretch()

        self._costume_title = TitleLabel(_tr("SettingsWindow.costume_title"), page)
        top_row.addWidget(self._costume_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._costume_subtitle = SubtitleLabel("", page)
        layout.addWidget(self._costume_subtitle)

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._costume_list_widget = self._make_theme_widget(QWidget())
        self._costume_list = QVBoxLayout(self._costume_list_widget)
        self._costume_list.setSpacing(6)
        self._costume_list.setContentsMargins(0, 4, 0, 0)
        self._costume_list.addStretch()

        scroll.setWidget(self._costume_list_widget)
        layout.addWidget(scroll, 1)
        return page

    def _build_llm_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.llm_title"), page)
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr("SettingsWindow.llm_subtitle"), page)
        layout.addWidget(subtitle)

        profile_title = SubtitleLabel(_tr("SettingsWindow.llm_profile"), page)
        layout.addWidget(profile_title)

        name_label = BodyLabel(_tr("SettingsWindow.llm_display_name"), page)
        layout.addWidget(name_label)
        self._user_name = QLineEdit(page)
        self._user_name.setPlaceholderText(_tr("SettingsWindow.llm_display_name_placeholder"))
        self._user_name.setFixedHeight(36)
        layout.addWidget(self._user_name)

        avatar_label = BodyLabel(_tr("SettingsWindow.llm_avatar_color"), page)
        layout.addWidget(avatar_label)
        self._avatar_colors = [
            ("#2aabee", _tr("color.blue")),
            ("#e91e63", _tr("color.pink")),
            ("#9c27b0", _tr("color.purple")),
            ("#4caf50", _tr("color.green")),
            ("#ff9800", _tr("color.orange")),
            ("#f44336", _tr("color.red")),
            ("#00bcd4", _tr("color.cyan")),
            ("#607d8b", _tr("color.grey")),
        ]
        colors_row = QHBoxLayout()
        colors_row.setSpacing(6)
        self._avatar_color_btns: list[QPushButton] = []
        for color_hex, color_name in self._avatar_colors:
            btn = QPushButton("", page)
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(color_name)
            btn.setProperty("avatar_color", color_hex)
            btn.clicked.connect(lambda checked, b=btn: self._on_avatar_color_clicked(b))
            self._avatar_color_btns.append(btn)
            colors_row.addWidget(btn)
        colors_row.addStretch()
        layout.addLayout(colors_row)

        api_url_label = BodyLabel(_tr("SettingsWindow.llm_api_url"), page)
        layout.addWidget(api_url_label)
        self._llm_api_url = QLineEdit(page)
        self._llm_api_url.setPlaceholderText(_tr("SettingsWindow.llm_api_url_placeholder"))
        self._llm_api_url.setFixedHeight(36)
        layout.addWidget(self._llm_api_url)

        api_key_label = BodyLabel(_tr("SettingsWindow.llm_api_key"), page)
        layout.addWidget(api_key_label)
        self._llm_api_key = QLineEdit(page)
        self._llm_api_key.setPlaceholderText(_tr("SettingsWindow.llm_api_key_placeholder"))
        self._llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._llm_api_key.setFixedHeight(36)
        layout.addWidget(self._llm_api_key)

        model_label = BodyLabel(_tr("SettingsWindow.llm_model_id"), page)
        layout.addWidget(model_label)

        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        self._llm_model_id = QLineEdit(page)
        self._llm_model_id.setPlaceholderText(_tr("SettingsWindow.llm_model_id_placeholder"))
        self._llm_model_id.setFixedHeight(36)
        model_row.addWidget(self._llm_model_id)

        fetch_btn = PushButton(FluentIcon.SYNC, _tr("SettingsWindow.llm_fetch"), page)
        fetch_btn.setFixedHeight(36)
        fetch_btn.clicked.connect(self._fetch_models)
        model_row.addWidget(fetch_btn)
        layout.addLayout(model_row)

        thinking_label = BodyLabel(_tr("SettingsWindow.llm_enable_thinking"), page)
        layout.addWidget(thinking_label)
        self._llm_enable_thinking = ComboBox(page)
        self._llm_enable_thinking.addItems([
            _tr("SettingsWindow.llm_enable_thinking_default"),
            _tr("SettingsWindow.llm_enable_thinking_on"),
            _tr("SettingsWindow.llm_enable_thinking_off"),
        ])
        self._llm_enable_thinking.setFixedHeight(36)
        self._llm_enable_thinking.setCurrentIndex(0)
        layout.addWidget(self._llm_enable_thinking)

        self._llm_model_combo_label = BodyLabel(_tr("SettingsWindow.llm_available_models"), page)
        self._llm_model_combo_label.hide()
        layout.addWidget(self._llm_model_combo_label)

        self._llm_model_scroll = ScrollArea()
        self._llm_model_scroll.setWidgetResizable(True)
        self._llm_model_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._llm_model_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._llm_model_scroll.setMinimumHeight(80)
        self._llm_model_scroll.setMaximumHeight(220)
        self._llm_model_scroll.hide()

        self._llm_model_list = QWidget(page)
        self._llm_model_list_layout = QVBoxLayout(self._llm_model_list)
        self._llm_model_list_layout.setContentsMargins(0, 4, 0, 4)
        self._llm_model_list_layout.setSpacing(2)
        self._llm_model_scroll.setWidget(self._llm_model_list)
        layout.addWidget(self._llm_model_scroll)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        test_btn = PushButton(FluentIcon.WIFI, _tr("SettingsWindow.llm_test"), page)
        test_btn.setFixedHeight(36)
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)

        save_btn = PrimaryPushButton(FluentIcon.SAVE, _tr("SettingsWindow.llm_save"), page)
        save_btn.setFixedHeight(36)
        save_btn.clicked.connect(self._save_llm_config)
        btn_row.addWidget(save_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._load_llm_config()
        self._style_llm_inputs()
        qconfig.themeChanged.connect(self._style_llm_inputs)

        return page

    def _style_llm_inputs(self):
        dark = isDarkTheme()
        input_bg = "#282828" if dark else "#ffffff"
        input_border = "#505050" if dark else "#d0d0d0"
        text_color = "#e8e8e8" if dark else "#000000"
        style = f"""
            QLineEdit {{
                background: {input_bg};
                color: {text_color};
                border: 1px solid {input_border};
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: #60cdff;
            }}
        """
        self._llm_api_url.setStyleSheet(style)
        self._llm_api_key.setStyleSheet(style)
        self._llm_model_id.setStyleSheet(style)
        self._user_name.setStyleSheet(style)
        self._style_avatar_buttons()

    def _style_avatar_buttons(self):
        for btn in self._avatar_color_btns:
            color = btn.property("avatar_color")
            checked = btn.isChecked()
            btn.setText("\u2713" if checked else "")
            size = 30 if checked else 28
            btn.setFixedSize(size, size)
            border = "3px solid #ffffff" if checked else "2px solid transparent"
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {color};
                    border: {border};
                    border-radius: {size // 2}px;
                    color: #ffffff;
                    font-weight: 900;
                    font-size: 14px;
                }}
            """)

    def _on_avatar_color_clicked(self, btn: QPushButton):
        for b in self._avatar_color_btns:
            b.setChecked(False)
        btn.setChecked(True)
        self._style_avatar_buttons()
        self._pulse_button(btn)

    @staticmethod
    def _pulse_button(btn):
        effect = QGraphicsColorizeEffect(btn)
        effect.setColor(QColor(255, 255, 255))
        effect.setStrength(0.0)
        btn.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"strength", btn)
        anim.setDuration(120)
        anim.setStartValue(0.7)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: btn.setGraphicsEffect(None))
        anim.start()

    def _load_llm_config(self):
        if self._cfg:
            self._llm_api_url.setText(self._cfg.get("llm_api_url", ""))
            self._llm_api_key.setText(self._cfg.get("llm_api_key", ""))
            self._llm_model_id.setText(self._cfg.get("llm_model_id", ""))
            self._user_name.setText(self._cfg.get("user_name", ""))
            saved_color = self._cfg.get("user_avatar_color", "#2aabee")
            for btn in self._avatar_color_btns:
                btn.setChecked(btn.property("avatar_color") == saved_color)
            thinking_val = self._cfg.get("llm_enable_thinking", None)
            if thinking_val is True:
                self._llm_enable_thinking.setCurrentIndex(1)
            elif thinking_val is False:
                self._llm_enable_thinking.setCurrentIndex(2)
            else:
                self._llm_enable_thinking.setCurrentIndex(0)

    def _save_llm_config(self):
        if self._cfg:
            self._cfg.set("llm_api_url", self._llm_api_url.text().strip())
            self._cfg.set("llm_api_key", self._llm_api_key.text().strip())
            self._cfg.set("llm_model_id", self._llm_model_id.text().strip())
            self._cfg.set("user_name", self._user_name.text().strip())
            for btn in self._avatar_color_btns:
                if btn.isChecked():
                    self._cfg.set("user_avatar_color", btn.property("avatar_color"))
                    break
            thinking_idx = self._llm_enable_thinking.currentIndex()
            if thinking_idx == 1:
                self._cfg.set("llm_enable_thinking", True)
            elif thinking_idx == 2:
                self._cfg.set("llm_enable_thinking", False)
            else:
                self._cfg.set("llm_enable_thinking", None)
            try:
                self._cfg.save()
                InfoBar.success(
                    _tr("SettingsWindow.llm_saved_title"),
                    _tr("SettingsWindow.llm_saved_content"),
                    duration=2000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
            except Exception:
                pass

    def _test_connection(self):
        api_url = self._llm_api_url.text().strip()
        api_key = self._llm_api_key.text().strip()
        model_id = self._llm_model_id.text().strip()

        if not api_url or not api_key or not model_id:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_config_title"),
                _tr("SettingsWindow.llm_missing_config_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        if hasattr(self, '_test_worker') and self._test_worker is not None:
            if self._test_worker.isRunning():
                self._test_worker.quit()
                self._test_worker.wait(2000)

        self._test_worker = TestConnectionWorker(api_url, api_key, model_id, parent=self)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.error.connect(self._on_test_error)
        self._test_worker.start()

    def _on_test_finished(self):
        InfoBar.success(
            _tr("SettingsWindow.llm_connected_title"),
            _tr("SettingsWindow.llm_connected_content"),
            duration=2000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _on_test_error(self, msg: str):
        InfoBar.error(
            _tr("SettingsWindow.llm_connection_failed_title"),
            msg,
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _fetch_models(self):
        api_url = self._llm_api_url.text().strip()
        api_key = self._llm_api_key.text().strip()

        if not api_url or not api_key:
            InfoBar.warning(
                _tr("SettingsWindow.llm_missing_api_title"),
                _tr("SettingsWindow.llm_missing_api_content"),
                duration=2000,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return

        base_url = api_url.rstrip("/")
        base_url = base_url.rsplit("/chat/completions", 1)[0]
        models_url = base_url + "/models"

        if hasattr(self, '_fetch_worker') and self._fetch_worker is not None:
            if self._fetch_worker.isRunning():
                self._fetch_worker.quit()
                self._fetch_worker.wait(2000)

        self._fetch_worker = FetchModelsWorker(models_url, api_key, parent=self)
        self._fetch_worker.finished.connect(self._on_models_fetched)
        self._fetch_worker.error.connect(self._on_test_error)
        self._fetch_worker.start()

    def _on_models_fetched(self, models: list[str]):
        for i in range(self._llm_model_list_layout.count()):
            item = self._llm_model_list_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        dark = isDarkTheme()
        for idx, model_name in enumerate(models):
            btn = QPushButton(model_name, self._llm_model_list)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(f"""
                QPushButton {{
                    text-align: left;
                    padding: 6px 14px;
                    border: none;
                    border-radius: 6px;
                    background: transparent;
                    font-size: 13px;
                    color: {'#e8e8e8' if dark else '#333333'};
                }}
                QPushButton:hover {{
                    background: {'#3a3a5a' if dark else '#e8f0fe'};
                }}
            """)
            btn.clicked.connect(lambda checked, mn=model_name: self._llm_model_id.setText(mn))
            self._llm_model_list_layout.addWidget(btn)
            QTimer.singleShot(idx * 30, lambda b=btn: self._animate_button_in(b))
        self._llm_model_list_layout.addStretch()

        self._llm_model_combo_label.show()
        self._llm_model_scroll.show()

    def _build_side_panel(self):
        panel = self._make_theme_widget(QWidget())
        panel.setFixedWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        settings_title = StrongBodyLabel(_tr("SettingsWindow.side_settings"), panel)
        layout.addWidget(settings_title)

        fps_label = BodyLabel(_tr("SettingsWindow.side_fps"), panel)
        layout.addWidget(fps_label)
        self._fps_slider = Slider(Qt.Orientation.Horizontal, panel)
        self._fps_slider.setRange(30, 240)
        self._fps_slider.setValue(self._fps)
        self._fps_slider.setSingleStep(10)
        self._fps_value = BodyLabel(_tr("SettingsWindow.fps_value", v=self._fps), panel)
        self._fps_slider.valueChanged.connect(
            lambda v: self._fps_value.setText(_tr("SettingsWindow.fps_value", v=v))
        )
        layout.addWidget(self._fps_slider)
        layout.addWidget(self._fps_value)

        vsync_label = BodyLabel(_tr("SettingsWindow.side_vsync"), panel)
        self._vsync_switch = SwitchButton(panel)
        self._vsync_switch.setChecked(self._vsync)
        self._vsync_switch.checkedChanged.connect(self._on_vsync_changed)
        vsync_row = QHBoxLayout()
        vsync_row.addWidget(vsync_label)
        vsync_row.addStretch()
        vsync_row.addWidget(self._vsync_switch)
        layout.addLayout(vsync_row)

        if self._vsync:
            self._fps_slider.setEnabled(False)
            self._fps_value.setEnabled(False)

        opacity_label = BodyLabel(_tr("SettingsWindow.side_opacity"), panel)
        layout.addWidget(opacity_label)
        self._opacity_slider = Slider(Qt.Orientation.Horizontal, panel)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_value = BodyLabel(_tr("SettingsWindow.opacity_value", v=int(self._opacity * 100)), panel)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_value.setText(_tr("SettingsWindow.opacity_value", v=v))
        )
        layout.addWidget(self._opacity_slider)
        layout.addWidget(self._opacity_value)

        layout.addSpacing(8)

        theme_label = BodyLabel(_tr("SettingsWindow.side_dark_theme"), panel)
        self._theme_switch = SwitchButton(panel)
        self._theme_switch.setChecked(isDarkTheme())
        self._theme_switch.checkedChanged.connect(
            lambda v: setTheme(Theme.DARK if v else Theme.LIGHT)
        )
        theme_row = QHBoxLayout()
        theme_row.addWidget(theme_label)
        theme_row.addStretch()
        theme_row.addWidget(self._theme_switch)
        layout.addLayout(theme_row)

        lang_label = BodyLabel(_tr("SettingsWindow.language"), panel)
        self._lang_combo = ComboBox(panel)
        self._lang_combo.setMinimumWidth(120)
        langs = available_languages()
        current = current_language()
        for lang in langs:
            display = {"en_US": "English", "zh_CN": "中文"}.get(lang, lang)
            self._lang_combo.addItem(display, lang)
            if lang == current:
                self._lang_combo.setCurrentIndex(self._lang_combo.count() - 1)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        lang_row = QHBoxLayout()
        lang_row.addWidget(lang_label)
        lang_row.addStretch()
        lang_row.addWidget(self._lang_combo)
        layout.addLayout(lang_row)

        layout.addStretch()

        btn_text = _tr("SettingsWindow.apply_launch") if self._show_launch else _tr("SettingsWindow.apply")
        self._apply_btn = PrimaryPushButton(FluentIcon.ACCEPT, btn_text, panel)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        return panel

    def _on_char_selected(self, char_key: str):
        self._current_char = char_key
        self._selected_band = self._model_manager.get_character_band(char_key)
        self._populate_costumes(char_key)
        display = self._model_manager.get_display_name(char_key)
        self._costume_title.setText(_tr("SettingsWindow.costumes_title", display=display))
        self._costume_subtitle.setText(
            _tr("SettingsWindow.costume_subtitle", display=display)
        )
        self._char_page.hide()
        self._costume_page.show()
        self._current_page = "costumes"

    def _on_band_selected(self, band_id: str):
        self._populate_characters(band_id)

    def _populate_costumes(self, char_key: str):
        for btn in self._costume_buttons:
            self._costume_list.removeWidget(btn)
            btn.deleteLater()
        self._costume_buttons.clear()

        costumes = self._model_manager.get_costumes(char_key)
        for idx, costume in enumerate(costumes):
            cid = costume["id"]
            cname = self._model_manager.get_costume_display_name(char_key, cid)
            btn = CostumeItem(cid, cname, self._costume_list_widget)
            btn.clicked.connect(lambda checked, b=btn, c=cid: self._on_costume_clicked(b, c))
            btn.preview_requested.connect(self._show_costume_preview)
            btn.preview_cancelled.connect(self._hide_costume_preview)
            btn.animate_in(delay_ms=idx * 40)
            self._costume_buttons.append(btn)
            self._costume_list.insertWidget(self._costume_list.count() - 1, btn)

        if self._costume_buttons:
            default_id = self._model_manager.get_default_costume(char_key)
            for btn in self._costume_buttons:
                if btn.costume_id == default_id:
                    btn.setChecked(True)
                    self._selected_costume = default_id
                    break

    def _on_costume_clicked(self, btn: CostumeItem, costume_id: str):
        for b in self._costume_buttons:
            b.setChecked(False)
        btn.setChecked(True)
        self._selected_costume = costume_id

    def _show_costume_preview(self, anchor: QWidget, costume_id: str):
        if not self._live2d:
            return
        model_path = self._model_manager.get_model_json_path(self._current_char, costume_id)
        if not model_path:
            return
        if self._preview_bubble is None:
            self._preview_bubble = Live2DPreviewBubble(self._live2d, self)
        self._preview_bubble.show_preview(model_path, anchor)

    def _hide_costume_preview(self):
        if self._preview_bubble is not None:
            self._preview_bubble.hide()

    def _go_back_to_chars(self):
        self._costume_page.hide()
        self._char_page.show()
        self._current_page = "characters"
        band_id = self._selected_band or self._model_manager.get_character_band(self._current_char)
        if band_id:
            self._populate_characters(band_id)
        else:
            self._populate_bands()
        for key, btn in self._nav_buttons.items():
            btn.setChecked(key == "characters")
        self._animate_indicator("characters")

    def _go_back_to_bands(self):
        self._populate_bands()

    def _on_vsync_changed(self, checked: bool):
        self._vsync = checked
        self._fps_slider.setEnabled(not checked)
        self._fps_value.setEnabled(not checked)

    def _on_apply(self):
        if self._launched:
            return
        self._launched = True
        self._save_llm_config()
        if self._current_char and self._selected_costume:
            self.model_selected.emit(self._current_char, self._selected_costume)
        self.settings_changed.emit({
            "fps": self._fps_slider.value(),
            "opacity": self._opacity_slider.value() / 100.0,
            "dark_theme": self._theme_switch.isChecked(),
            "vsync": self._vsync_switch.isChecked(),
        })
        if self._show_launch:
            self.launch_requested.emit()
        self.close()

    def connect_ipc_output(self):
        self.model_selected.connect(lambda char, costume: print(f"MODEL\t{char}\t{costume}", flush=True))
        self.settings_changed.connect(lambda data: print(f"SETTINGS\t{json.dumps(data, ensure_ascii=False)}", flush=True))
        self.launch_requested.connect(lambda: print("LAUNCH", flush=True))


class TestConnectionWorker(QThread):
    finished = Signal()
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model_id: str, parent=None):
        super().__init__(parent)
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    def run(self):
        try:
            import urllib.request
            import json
            import ssl

            ctx = ssl.create_default_context()

            body = json.dumps({
                "model": self._model_id,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
            }).encode("utf-8")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._api_url, data=body, headers=headers, method="POST"
            )

            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    self.finished.emit()
                else:
                    self.error.emit("Unexpected response format")
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))


class FetchModelsWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, models_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self._models_url = models_url
        self._api_key = api_key

    def run(self):
        try:
            import urllib.request
            import json
            import ssl

            ctx = ssl.create_default_context()

            headers = {
                "Authorization": f"Bearer {self._api_key}",
            }

            req = urllib.request.Request(
                self._models_url, headers=headers, method="GET"
            )

            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("data", [])
                ids = [m.get("id", "") for m in models if m.get("id")]
                self.finished.emit(sorted(ids))
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                msg = err_body.get("error", {}).get("message", str(e))
            except Exception:
                msg = str(e)
            self.error.emit(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            self.error.emit(f"Network error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))
