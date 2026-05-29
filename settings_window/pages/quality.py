from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


class QualityPageMixin:

    def _quality_options(self) -> list[tuple[str, str]]:
        return [
            ("performance", _tr("SettingsWindow.quality_performance")),
            ("balanced", _tr("SettingsWindow.quality_balanced")),
        ]

    def _quality_detail_text(self, profile: str) -> str:
        return _tr(f"SettingsWindow.quality_detail_{normalize_live2d_quality(profile)}")

    def _build_quality_page(self):
        page = self._make_theme_widget(QWidget())
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.display_title"), page)
        title.setObjectName("DisplayPageTitle")
        layout.addWidget(title)
        subtitle = SubtitleLabel(_tr("SettingsWindow.display_subtitle"), page)
        subtitle.setObjectName("DisplayPageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        quality_label = BodyLabel(_tr("SettingsWindow.quality_profile"), page)
        layout.addWidget(quality_label)

        self._quality_combo = OpaqueDropDownComboBox(page)
        self._quality_combo.setFixedHeight(36)
        current_index = 0
        for index, (profile, label) in enumerate(self._quality_options()):
            self._quality_combo.addItem(label, userData=profile)
            if profile == self._live2d_quality:
                current_index = index
        self._quality_combo.setCurrentIndex(current_index)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        layout.addWidget(self._quality_combo)

        self._quality_detail = BodyLabel(self._quality_detail_text(self._live2d_quality), page)
        self._quality_detail.setWordWrap(True)
        layout.addWidget(self._quality_detail)

        fps_label = BodyLabel(_tr("SettingsWindow.side_fps"), page)
        layout.addWidget(fps_label)
        self._fps_slider = Slider(Qt.Orientation.Horizontal, page)
        self._fps_slider.setRange(30, 240)
        self._fps_slider.setValue(max(30, min(240, self._fps)))
        self._fps_slider.setSingleStep(10)
        self._fps_value = BodyLabel(_tr("SettingsWindow.fps_value", v=self._fps_slider.value()), page)
        self._fps_slider.valueChanged.connect(self._on_fps_changed)
        layout.addWidget(self._fps_slider)
        layout.addWidget(self._fps_value)

        vsync_label = BodyLabel(_tr("SettingsWindow.side_vsync"), page)
        self._vsync_switch = SwitchButton(page)
        self._vsync_switch.setChecked(self._vsync)
        self._vsync_switch.checkedChanged.connect(self._on_vsync_changed)
        vsync_row = QHBoxLayout()
        vsync_row.setContentsMargins(0, 0, 0, 0)
        vsync_row.setSpacing(10)
        vsync_row.addWidget(vsync_label)
        vsync_row.addStretch()
        vsync_row.addWidget(self._vsync_switch)
        layout.addLayout(vsync_row)
        self._on_vsync_changed(self._vsync)

        scale_label = BodyLabel(_tr("SettingsWindow.live2d_scale"), page)
        layout.addWidget(scale_label)

        scale_row = QHBoxLayout()
        scale_row.setContentsMargins(0, 0, 0, 0)
        scale_row.setSpacing(10)
        self._live2d_scale_slider = Slider(Qt.Orientation.Horizontal, page)
        self._live2d_scale_slider.setRange(LIVE2D_SCALE_MIN, LIVE2D_SCALE_MAX)
        self._live2d_scale_slider.setValue(self._live2d_scale)
        self._live2d_scale_slider.setSingleStep(5)
        self._live2d_scale_input = LineEdit(page)
        self._live2d_scale_input.setFixedWidth(76)
        self._live2d_scale_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._live2d_scale_input.setValidator(QIntValidator(LIVE2D_SCALE_MIN, LIVE2D_SCALE_MAX, self))
        self._live2d_scale_input.setText(str(self._live2d_scale))
        self._live2d_scale_slider.valueChanged.connect(self._on_live2d_scale_slider_changed)
        self._live2d_scale_input.editingFinished.connect(self._on_live2d_scale_input_finished)
        scale_row.addWidget(self._live2d_scale_slider, 1)
        scale_row.addWidget(self._live2d_scale_input)
        layout.addLayout(scale_row)

        opacity_label = BodyLabel(_tr("SettingsWindow.side_opacity"), page)
        layout.addWidget(opacity_label)
        self._opacity_slider = Slider(Qt.Orientation.Horizontal, page)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(int(self._opacity * 100))
        self._opacity_value = BodyLabel(_tr("SettingsWindow.opacity_value", v=int(self._opacity * 100)), page)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_value.setText(_tr("SettingsWindow.opacity_value", v=v))
        )
        layout.addWidget(self._opacity_slider)
        layout.addWidget(self._opacity_value)

        layout.addSpacing(8)

        theme_label = BodyLabel(_tr("SettingsWindow.side_dark_theme"), page)
        self._theme_combo = OpaqueDropDownComboBox(page)
        self._theme_combo.setFixedHeight(36)
        theme_options = [
            (_THEME_OFF, _tr("SettingsWindow.theme_option_off")),
            (_THEME_ON, _tr("SettingsWindow.theme_option_on")),
            (_THEME_FOLLOW_SYSTEM, _tr("SettingsWindow.theme_option_follow_system")),
        ]
        current_theme = self._cfg.get("dark_theme", _THEME_FOLLOW_SYSTEM) if self._cfg else _THEME_FOLLOW_SYSTEM
        if isinstance(current_theme, bool):
            current_theme = _THEME_ON if current_theme else _THEME_OFF
        selected_index = 0
        for index, (value, label) in enumerate(theme_options):
            self._theme_combo.addItem(label, userData=value)
            if value == current_theme:
                selected_index = index
        self._theme_combo.setCurrentIndex(selected_index)
        self._theme_combo.currentIndexChanged.connect(
            lambda _: apply_app_theme(self._theme_combo.currentData())
        )
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(0, 0, 0, 0)
        theme_row.setSpacing(10)
        theme_row.addWidget(theme_label)
        theme_row.addStretch()
        theme_row.addWidget(self._theme_combo)
        layout.addLayout(theme_row)

        layout.addStretch()
        return page

    def _on_quality_changed(self, index: int):
        profile = self._quality_combo.itemData(index)
        self._live2d_quality = normalize_live2d_quality(profile)
        self._quality_detail.setText(self._quality_detail_text(self._live2d_quality))

    def _set_live2d_scale_controls(self, value: int):
        value = clamp_live2d_scale(value, use_device_pixel_ratio_default=True)
        self._live2d_scale = value
        self._live2d_scale_input.blockSignals(True)
        self._live2d_scale_slider.setValue(value)
        self._live2d_scale_input.setText(str(value))
        self._live2d_scale_input.blockSignals(False)

    def _on_live2d_scale_slider_changed(self, value: int):
        self._set_live2d_scale_controls(value)

    def _on_live2d_scale_input_finished(self):
        self._set_live2d_scale_controls(self._live2d_scale_input.text())
