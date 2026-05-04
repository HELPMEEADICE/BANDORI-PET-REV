from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QWidget

from qfluentwidgets import (
    Dialog, ComboBox, PushButton, PrimaryPushButton,
    StrongBodyLabel, FluentIcon,
)


class ModelSelectDialog(Dialog):
    model_changed = Signal(str, str)

    def __init__(self, model_manager, current_char="", current_costume="", parent=None):
        super().__init__("", "", parent)
        self._model_manager = model_manager
        self._char_map = {}

        self.titleLabel = StrongBodyLabel(self.tr("Select Character Model"), self)

        self.char_combo = ComboBox(self)
        self.char_combo.setPlaceholderText(self.tr("Choose character..."))
        self.costume_combo = ComboBox(self)
        self.costume_combo.setPlaceholderText(self.tr("Choose costume..."))

        self._populate_characters()

        if current_char and current_char in model_manager.characters:
            display_name = self._model_manager.get_display_name(current_char)
            idx = self.char_combo.findText(display_name)
            if idx >= 0:
                self.char_combo.setCurrentIndex(idx)
                if current_costume:
                    cname = self._model_manager.get_costume_display_name(
                        current_char, current_costume
                    )
                    cidx = self.costume_combo.findText(cname)
                    if cidx >= 0:
                        self.costume_combo.setCurrentIndex(cidx)

        self.char_combo.currentTextChanged.connect(self._on_char_changed)

        self.cancel_btn = PushButton(FluentIcon.CLOSE, self.tr("Cancel"), self)
        self.ok_btn = PrimaryPushButton(FluentIcon.ACCEPT, self.tr("Apply"), self)

        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_apply)

        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(self.tr("Character:")))
        row1.addWidget(self.char_combo, 1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(self.tr("Costume:")))
        row2.addWidget(self.costume_combo, 1)

        layout.addLayout(row1)
        layout.addLayout(row2)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.ok_btn)
        layout.addLayout(btn_layout)

        self.hBoxLayout.insertWidget(1, w)
        self.setFixedWidth(400)

    def _populate_characters(self):
        self.char_combo.blockSignals(True)
        self.char_combo.clear()
        self._char_map.clear()
        for key in self._model_manager.characters:
            display = self._model_manager.get_display_name(key)
            self._char_map[display] = key
            self.char_combo.addItem(display)
        self.char_combo.blockSignals(False)

    def _populate_costumes(self, display_name: str):
        self.costume_combo.clear()
        key = self._char_map.get(display_name, display_name.lower())
        costumes = self._model_manager.get_costumes(key)
        for costume in costumes:
            cname = self._model_manager.get_costume_display_name(key, costume["id"])
            self.costume_combo.addItem(cname, costume["id"])

    def _on_char_changed(self, name: str):
        if name:
            self._populate_costumes(name)

    def _on_apply(self):
        display = self.char_combo.currentText()
        char = self._char_map.get(display, display.lower())
        idx = self.costume_combo.currentIndex()
        if idx >= 0:
            costume = self.costume_combo.itemData(idx)
            if char and costume:
                self.model_changed.emit(char, costume)
                self.accept()
