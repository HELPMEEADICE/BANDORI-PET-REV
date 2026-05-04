from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QSizePolicy, QSpacerItem, QScrollArea,
)

from qfluentwidgets import (
    CardWidget, PushButton, PrimaryPushButton, ComboBox,
    BodyLabel, StrongBodyLabel, TitleLabel, SubtitleLabel,
    FluentIcon, Slider, SwitchButton,
    setTheme, Theme, isDarkTheme,
)


class CharacterCard(CardWidget):
    char_selected = Signal(str)

    def __init__(self, char_key: str, display_name: str, costume_count: int, parent=None):
        super().__init__(parent)
        self._char_key = char_key
        self.setFixedSize(180, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        name_label = StrongBodyLabel(display_name, self)
        name_label.setWordWrap(True)
        layout.addWidget(name_label)

        count_label = BodyLabel(f"{costume_count} costumes", self)
        count_label.setStyleSheet("color: #888888;")
        layout.addWidget(count_label)

        layout.addStretch()

        self.clicked.connect(self._on_card_clicked)

    def _on_card_clicked(self):
        self.char_selected.emit(self._char_key)


class CostumeItem(QPushButton):
    def __init__(self, costume_id: str, display_name: str, parent=None):
        super().__init__(parent)
        self._costume_id = costume_id
        self.setText(display_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(40)
        self.setCheckable(True)
        self.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px 16px;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                background: #fafafa;
                font-size: 14px;
            }
            QPushButton:hover {
                background: #e8f0fe;
                border-color: #1a73e8;
            }
            QPushButton:checked {
                background: #1a73e8;
                color: white;
                border-color: #1a73e8;
            }
        """)

    @property
    def costume_id(self):
        return self._costume_id


class SettingsWindow(QWidget):
    model_selected = Signal(str, str)
    settings_changed = Signal(dict)
    launch_requested = Signal()

    def __init__(self, model_manager, current_char="", current_costume="",
                 current_fps=120, current_opacity=1.0, show_launch=True):
        super().__init__()
        self._model_manager = model_manager
        self._current_char = current_char or model_manager.characters[0]
        self._current_costume = current_costume
        self._fps = current_fps
        self._opacity = current_opacity
        self._costume_buttons: list[CostumeItem] = []
        self._selected_costume = ""
        self._show_launch = show_launch

        self.setWindowTitle("Bandori Desktop Pet - Settings")
        self.setMinimumSize(890, 560)
        self.resize(890, 600)

        self._launched = False

        self._init_ui()

        if self._current_costume:
            self._selected_costume = self._current_costume
        else:
            self._selected_costume = self._model_manager.get_default_costume(
                self._current_char
            )

    def closeEvent(self, event):
        if not self._launched:
            self._on_apply()
        super().closeEvent(event)

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(24)

        self._stack = QWidget(self)
        self._stack_layout = QVBoxLayout(self._stack)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        self._stack_layout.setSpacing(0)

        self._char_page = self._build_char_page()
        self._costume_page = self._build_costume_page()
        self._costume_page.hide()

        self._stack_layout.addWidget(self._char_page)
        self._stack_layout.addWidget(self._costume_page)

        side_panel = self._build_side_panel()

        main_layout.addWidget(self._stack, 1)
        main_layout.addWidget(side_panel, 0)

    def _build_char_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        title = TitleLabel("Select Character", page)
        layout.addWidget(title)
        subtitle = SubtitleLabel("Choose a character to configure", page)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        grid_widget = QWidget()
        self._char_grid = QGridLayout(grid_widget)
        self._char_grid.setSpacing(12)
        self._char_grid.setContentsMargins(0, 8, 0, 0)

        chars = self._model_manager.characters
        col = 0
        row = 0
        cols_per_row = 3

        for char_key in chars:
            costumes = self._model_manager.get_costumes(char_key)
            if not costumes:
                continue
            display = self._model_manager.get_display_name(char_key)
            card = CharacterCard(char_key, display, len(costumes), grid_widget)
            card.char_selected.connect(self._on_char_selected)
            self._char_grid.addWidget(card, row, col)
            col += 1
            if col >= cols_per_row:
                col = 0
                row += 1

        self._char_grid.setColumnStretch(cols_per_row - 1, 0)
        for c in range(cols_per_row):
            self._char_grid.setColumnStretch(c, 0)

        scroll.setWidget(grid_widget)
        layout.addWidget(scroll, 1)
        return page

    def _build_costume_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        back_btn = PushButton(FluentIcon.LEFT_ARROW, "Back", page)
        back_btn.clicked.connect(self._go_back_to_chars)
        top_row.addWidget(back_btn)
        top_row.addStretch()

        self._costume_title = TitleLabel("Select Costume", page)
        top_row.addWidget(self._costume_title)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._costume_subtitle = SubtitleLabel("", page)
        layout.addWidget(self._costume_subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._costume_list_widget = QWidget()
        self._costume_list = QVBoxLayout(self._costume_list_widget)
        self._costume_list.setSpacing(6)
        self._costume_list.setContentsMargins(0, 4, 0, 0)
        self._costume_list.addStretch()

        scroll.setWidget(self._costume_list_widget)
        layout.addWidget(scroll, 1)
        return page

    def _build_side_panel(self):
        panel = QWidget()
        panel.setFixedWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        settings_title = StrongBodyLabel("Settings", panel)
        layout.addWidget(settings_title)

        fps_label = BodyLabel("Refresh Rate (FPS)", panel)
        layout.addWidget(fps_label)
        self._fps_slider = Slider(Qt.Orientation.Horizontal, panel)
        self._fps_slider.setRange(30, 240)
        self._fps_slider.setValue(self._fps)
        self._fps_slider.setSingleStep(10)
        self._fps_value = BodyLabel(f"{self._fps} FPS", panel)
        self._fps_slider.valueChanged.connect(
            lambda v: self._fps_value.setText(f"{v} FPS")
        )
        layout.addWidget(self._fps_slider)
        layout.addWidget(self._fps_value)

        opacity_label = BodyLabel("Opacity", panel)
        layout.addWidget(opacity_label)
        self._opacity_slider = Slider(Qt.Orientation.Horizontal, panel)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_value = BodyLabel(f"{int(self._opacity * 100)}%", panel)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_value.setText(f"{v}%")
        )
        layout.addWidget(self._opacity_slider)
        layout.addWidget(self._opacity_value)

        layout.addSpacing(8)

        theme_label = BodyLabel("Dark Theme", panel)
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

        layout.addStretch()

        btn_text = "Apply & Launch" if self._show_launch else "Apply"
        self._apply_btn = PrimaryPushButton(FluentIcon.ACCEPT, btn_text, panel)
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        return panel

    def _on_char_selected(self, char_key: str):
        self._current_char = char_key
        self._populate_costumes(char_key)
        display = self._model_manager.get_display_name(char_key)
        self._costume_title.setText(f"Costumes - {display}")
        self._costume_subtitle.setText(
            f"Select a costume for {display}"
        )
        self._char_page.hide()
        self._costume_page.show()

    def _populate_costumes(self, char_key: str):
        for btn in self._costume_buttons:
            self._costume_list.removeWidget(btn)
            btn.deleteLater()
        self._costume_buttons.clear()

        costumes = self._model_manager.get_costumes(char_key)
        for costume in costumes:
            cid = costume["id"]
            cname = self._model_manager.get_costume_display_name(char_key, cid)
            btn = CostumeItem(cid, cname, self._costume_list_widget)
            btn.clicked.connect(lambda checked, b=btn, c=cid: self._on_costume_clicked(b, c))
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

    def _go_back_to_chars(self):
        self._costume_page.hide()
        self._char_page.show()

    def _on_apply(self):
        if self._launched:
            return
        self._launched = True
        if self._current_char and self._selected_costume:
            self.model_selected.emit(self._current_char, self._selected_costume)
        self.settings_changed.emit({
            "fps": self._fps_slider.value(),
            "opacity": self._opacity_slider.value() / 100.0,
            "dark_theme": self._theme_switch.isChecked(),
        })
        if self._show_launch:
            self.launch_requested.emit()
        self.close()

    def closeEvent(self, event):
        if not self._launched:
            self._on_apply()
            return
        super().closeEvent(event)
