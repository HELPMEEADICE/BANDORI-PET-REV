from PySide6.QtCharts import (
    QChart, QChartView, QLineSeries, QBarSeries, QBarSet,
    QValueAxis, QBarCategoryAxis,
)
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QCursor, QFont, QBrush
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QToolTip

from settings_window.constants import *
from settings_window.widgets import *
from settings_window.workers import *


_AFFECTION_COLOR = QColor("#e4004f")
_TRUST_COLOR = QColor("#10b981")
_FAMILIARITY_COLOR = QColor("#f59e0b")
_MSG_TREND_COLOR = QColor("#3b82f6")
_USAGE_BAR_COLOR = QColor("#8b5cf6")
_CHART_COLORS = [
    "#e4004f", "#8b5cf6", "#10b981", "#f59e0b", "#3b82f6",
    "#ef4444", "#06b6d4", "#ec4899", "#22c55e", "#f97316",
]
_EMPTY_HINT_COLOR = QColor("#a7b0bf")

_HEATMAP_LIGHT = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
_HEATMAP_DARK = ["#2d2d2d", "#0d4429", "#1a7a3a", "#30a14e", "#39d353"]
_HEATMAP_CELL = 12
_HEATMAP_GAP = 2
_HEATMAP_ROWS = 7
_HEATMAP_COLS = 24
_HEATMAP_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return _tr("StatisticsPage.duration_hm", default="{h}小时{m}分钟", h=hours, m=minutes)
    return _tr("StatisticsPage.duration_m", default="{m}分钟", m=minutes)


def _truncate_name(name: str, max_len: int = 6) -> str:
    return name[:max_len] + "…" if len(name) > max_len else name


def _make_empty_chart(title: str, hint: str) -> QChart:
    chart = QChart()
    chart.setTitle(title)
    axis_x = QBarCategoryAxis()
    axis_x.append([hint])
    axis_x.setLabelsColor(_EMPTY_HINT_COLOR)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    axis_y = QValueAxis()
    axis_y.setRange(0, 10)
    axis_y.setLabelsVisible(False)
    axis_y.setGridLineColor(Qt.GlobalColor.transparent)
    axis_y.setLineVisible(False)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    chart.legend().setVisible(False)
    return chart


def _connect_line_tooltip(series: QLineSeries, labels: list[str], suffix: str = ""):
    name = series.name()
    def _on_hovered(point: QPointF, state: bool):
        if not state:
            QToolTip.hideText()
            return
        idx = int(point.x())
        if 0 <= idx < len(labels):
            label = labels[idx]
        else:
            label = ""
        val = int(point.y())
        text = f"{label}\n{name}: {val}{suffix}" if label else f"{name}: {val}{suffix}"
        QToolTip.showText(QCursor.pos(), text)
    series.hovered.connect(_on_hovered)


def _connect_bar_tooltip(bar_set: QBarSet, labels: list[str], suffix: str = ""):
    name = bar_set.label()
    def _on_hovered(state: bool, index: int):
        if not state:
            QToolTip.hideText()
            return
        if 0 <= index < len(labels):
            label = labels[index]
        else:
            label = ""
        val = int(bar_set.at(index))
        text = f"{label}\n{name}: {val}{suffix}" if label else f"{name}: {val}{suffix}"
        QToolTip.showText(QCursor.pos(), text)
    bar_set.hovered.connect(_on_hovered)


def _heatmap_level(value: int, thresholds: list[int]) -> int:
    for i, t in enumerate(thresholds):
        if value <= t:
            return i
    return len(thresholds)


class _HeatmapWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: list[list[int]] = []
        self._thresholds: list[int] = [0, 0, 0, 0]
        self._colors: list[str] = list(_HEATMAP_LIGHT)
        self._hover_row = -1
        self._hover_col = -1
        self._label_font = QFont()
        self._label_font.setPointSize(8)
        self._empty_hint = ""
        self.setMouseTracking(True)
        self._update_theme()
        qconfig.themeChanged.connect(self._update_theme)
        qconfig.themeChanged.connect(self.update)

    def set_data(self, grid: list[list[int]], empty_hint: str = ""):
        self._data = grid
        self._empty_hint = empty_hint
        all_vals = [v for row in grid for v in row if v > 0]
        if all_vals:
            all_vals.sort()
            n = len(all_vals)
            self._thresholds = [
                all_vals[n // 5],
                all_vals[n * 2 // 5],
                all_vals[n * 3 // 5],
                all_vals[n * 4 // 5],
            ]
        else:
            self._thresholds = [0, 0, 0, 0]
        self.update()

    def _update_theme(self):
        self._colors = list(_HEATMAP_DARK if isDarkTheme() else _HEATMAP_LIGHT)

    def minimumSizeHint(self):
        label_w = 36
        label_h = 16
        w = label_w + _HEATMAP_COLS * (_HEATMAP_CELL + _HEATMAP_GAP) - _HEATMAP_GAP + 8
        h = label_h + _HEATMAP_ROWS * (_HEATMAP_CELL + _HEATMAP_GAP) - _HEATMAP_GAP + 8
        from PySide6.QtCore import QSize
        return QSize(w, h)

    def sizeHint(self):
        return self.minimumSizeHint()

    def _cell_rect(self, row: int, col: int) -> QRectF:
        label_w = 36
        label_h = 16
        x = label_w + col * (_HEATMAP_CELL + _HEATMAP_GAP)
        y = label_h + row * (_HEATMAP_CELL + _HEATMAP_GAP)
        return QRectF(x, y, _HEATMAP_CELL, _HEATMAP_CELL)

    def _cell_at(self, pos) -> tuple[int, int]:
        label_w = 36
        label_h = 16
        fx = pos.x() - label_w
        fy = pos.y() - label_h
        if fx < 0 or fy < 0:
            return -1, -1
        step = _HEATMAP_CELL + _HEATMAP_GAP
        col = int(fx / step)
        row = int(fy / step)
        if col >= _HEATMAP_COLS or row >= _HEATMAP_ROWS:
            return -1, -1
        cell_x = fx - col * step
        cell_y = fy - row * step
        if cell_x > _HEATMAP_CELL or cell_y > _HEATMAP_CELL:
            return -1, -1
        return row, col

    def mouseMoveEvent(self, event):
        row, col = self._cell_at(event.position().toPoint())
        if row != self._hover_row or col != self._hover_col:
            self._hover_row = row
            self._hover_col = col
            self.update()
        if 0 <= row < _HEATMAP_ROWS and 0 <= col < _HEATMAP_COLS and self._data:
            val = self._data[row][col]
            day = _HEATMAP_DAY_LABELS[row] if row < len(_HEATMAP_DAY_LABELS) else ""
            hour_str = f"{col:02d}:00-{col:02d}:59"
            text = f"{day} {hour_str}\n{_tr('SettingsWindow.statistics_heatmap_msgs', default='消息数')}: {val}"
            QToolTip.showText(QCursor.pos(), text, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        self._hover_row = -1
        self._hover_col = -1
        self.update()
        QToolTip.hideText()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._label_font)

        dark = isDarkTheme()
        text_color = QColor("#c0c0c0" if dark else "#555555")
        painter.setPen(text_color)

        has_data = any(v > 0 for row in self._data for v in row) if self._data else False

        label_w = 36
        label_h = 16

        for r in range(_HEATMAP_ROWS):
            cell_y = label_h + r * (_HEATMAP_CELL + _HEATMAP_GAP)
            label = _HEATMAP_DAY_LABELS[r] if r < len(_HEATMAP_DAY_LABELS) else ""
            painter.drawText(QRectF(0, cell_y - 2, label_w - 4, _HEATMAP_CELL + 4),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        painter.setPen(text_color)
        for c in range(_HEATMAP_COLS):
            if c % 3 == 0:
                cell_x = label_w + c * (_HEATMAP_CELL + _HEATMAP_GAP)
                painter.drawText(QRectF(cell_x, 0, _HEATMAP_CELL * 2, label_h),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, str(c))

        if not has_data:
            grid_x = label_w
            grid_y = label_h
            grid_w = _HEATMAP_COLS * (_HEATMAP_CELL + _HEATMAP_GAP) - _HEATMAP_GAP
            grid_h = _HEATMAP_ROWS * (_HEATMAP_CELL + _HEATMAP_GAP) - _HEATMAP_GAP
            empty_color = QColor(self._colors[0])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(empty_color))
            painter.drawRoundedRect(QRectF(grid_x, grid_y, grid_w, grid_h), 3, 3)
            hint = self._empty_hint or _tr("SettingsWindow.statistics_no_heatmap", default="此时间段暂无对话数据")
            painter.setPen(QColor("#a7b0bf" if dark else "#687385"))
            painter.drawText(QRectF(grid_x, grid_y, grid_w, grid_h),
                             Qt.AlignmentFlag.AlignCenter, hint)
            painter.end()
            return

        pen = QPen()
        pen.setWidth(1)
        for r in range(_HEATMAP_ROWS):
            for c in range(_HEATMAP_COLS):
                val = self._data[r][c] if r < len(self._data) and c < len(self._data[r]) else 0
                level = _heatmap_level(val, self._thresholds)
                color = QColor(self._colors[level])
                rect = self._cell_rect(r, c)
                if r == self._hover_row and c == self._hover_col:
                    pen.setColor(QColor("#ffffff" if dark else "#333333"))
                    painter.setPen(pen)
                    painter.setBrush(QBrush(color))
                    painter.drawRoundedRect(rect, 2, 2)
                else:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(color))
                    painter.drawRoundedRect(rect, 2, 2)
        painter.end()


class _StatCard(QFrame):
    def __init__(self, title: str, value: str, color: str, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(100)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        self._value_label = StrongBodyLabel(value, self)
        self._value_label.setStyleSheet(f"color: {color}; font-size: 26px; font-weight: 800;")
        self._title_label = BodyLabel(title, self)
        self._title_label.setObjectName("statCardTitle")
        layout.addWidget(self._value_label)
        layout.addWidget(self._title_label)
        self._apply_theme()
        qconfig.themeChanged.connect(self._apply_theme)

    def set_value(self, value: str):
        self._value_label.setText(value)

    def _apply_theme(self):
        dark = isDarkTheme()
        bg = "#252525" if dark else "#ffffff"
        border = "#3b3b3b" if dark else "#e4d9df"
        muted = "#a7b0bf" if dark else "#687385"
        self.setStyleSheet(f"""
            QFrame#statCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            BodyLabel#statCardTitle {{
                color: {muted};
                font-size: 13px;
            }}
        """)


class StatisticsPageMixin:

    def _build_statistics_page(self):
        page = self._make_theme_widget(QWidget())
        page.setObjectName("statisticsPage")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        title = TitleLabel(_tr("SettingsWindow.statistics_title", default="数据统计"), page)
        layout.addWidget(title)
        subtitle = _wrap_label(SubtitleLabel(_tr(
            "SettingsWindow.statistics_subtitle",
            default="查看好感度趋势、对话统计与使用时长",
        ), page))
        layout.addWidget(subtitle)

        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setSpacing(10)
        self._stat_cards = {}
        _card_defs = [
            ("messages", _tr("SettingsWindow.statistics_total_messages", default="总消息数"), _TRUST_COLOR.name()),
            ("usage_today", _tr("SettingsWindow.statistics_usage_today", default="今日使用"), _FAMILIARITY_COLOR.name()),
            ("usage_week", _tr("SettingsWindow.statistics_usage_week", default="本周使用"), "#3b82f6"),
            ("usage_total", _tr("SettingsWindow.statistics_usage_total", default="累计使用"), "#8b5cf6"),
        ]
        for idx, (key, title_text, color) in enumerate(_card_defs):
            card = _StatCard(title_text, "--", color, page)
            cards_grid.addWidget(card, idx // 2, idx % 2)
            self._stat_cards[key] = card
        cards_grid.setColumnStretch(0, 1)
        cards_grid.setColumnStretch(1, 1)
        layout.addLayout(cards_grid)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(10)
        controls_row.addWidget(BodyLabel(_tr("SettingsWindow.statistics_select_character", default="选择角色"), page))
        self._stats_char_combo = OpaqueDropDownComboBox(page)
        self._stats_char_combo.setFixedHeight(36)
        self._stats_char_combo.setMinimumWidth(160)
        controls_row.addWidget(self._stats_char_combo)
        controls_row.addSpacing(16)
        controls_row.addWidget(BodyLabel(_tr("SettingsWindow.statistics_time_range", default="时间范围"), page))
        self._stats_range_combo = OpaqueDropDownComboBox(page)
        self._stats_range_combo.setFixedHeight(36)
        self._stats_range_combo.setMinimumWidth(120)
        self._stats_range_combo.addItem(_tr("SettingsWindow.statistics_time_range_7d", default="近 7 天"), userData=7)
        self._stats_range_combo.addItem(_tr("SettingsWindow.statistics_time_range_30d", default="近 30 天"), userData=30)
        self._stats_range_combo.addItem(_tr("SettingsWindow.statistics_time_range_all", default="全部"), userData=0)
        self._stats_range_combo.currentIndexChanged.connect(self._refresh_statistics)
        controls_row.addWidget(self._stats_range_combo)
        controls_row.addStretch()
        layout.addLayout(controls_row)

        self._affection_chart_view = QChartView(page)
        self._affection_chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._affection_chart_view.setMinimumHeight(280)
        self._affection_chart_view.setMaximumHeight(320)
        layout.addWidget(self._affection_chart_view)

        self._char_messages_chart_view = QChartView(page)
        self._char_messages_chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._char_messages_chart_view.setMinimumHeight(250)
        self._char_messages_chart_view.setMaximumHeight(300)
        layout.addWidget(self._char_messages_chart_view)

        heatmap_title = StrongBodyLabel(
            _tr("SettingsWindow.statistics_heatmap_title", default="对话热力图"), page)
        heatmap_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heatmap_title)
        heatmap_wrap = QHBoxLayout()
        heatmap_wrap.addStretch()
        self._heatmap_widget = _HeatmapWidget(page)
        self._heatmap_widget.setMinimumHeight(120)
        self._heatmap_widget.setMaximumHeight(180)
        heatmap_wrap.addWidget(self._heatmap_widget)
        heatmap_wrap.addStretch()
        layout.addLayout(heatmap_wrap)

        self._daily_msg_chart_view = QChartView(page)
        self._daily_msg_chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._daily_msg_chart_view.setMinimumHeight(220)
        self._daily_msg_chart_view.setMaximumHeight(280)
        layout.addWidget(self._daily_msg_chart_view)

        self._daily_usage_chart_view = QChartView(page)
        self._daily_usage_chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._daily_usage_chart_view.setMinimumHeight(200)
        self._daily_usage_chart_view.setMaximumHeight(260)
        layout.addWidget(self._daily_usage_chart_view)

        layout.addStretch()

        self._stats_db = None
        self._stats_refresh_timer = QTimer(page)
        self._stats_refresh_timer.setInterval(60_000)
        self._stats_refresh_timer.timeout.connect(self._refresh_statistics)
        self._stats_refresh_timer.start()

        self._style_statistics_page(page)
        self._refresh_chart_themes()
        qconfig.themeChanged.connect(lambda: self._style_statistics_page(page))
        qconfig.themeChanged.connect(self._refresh_chart_themes)

        QTimer.singleShot(0, self._populate_character_combo)
        return page

    def _style_statistics_page(self, page: QWidget):
        dark = isDarkTheme()
        page_bg = _BG_DARK if dark else _BG_LIGHT
        page.setStyleSheet(f"""
            QWidget#statisticsPage {{
                background: {page_bg};
            }}
            SubtitleLabel {{
                color: {'#a7b0bf' if dark else '#687385'};
            }}
        """)

    def _populate_character_combo(self):
        self._stats_char_combo.blockSignals(True)
        self._stats_char_combo.clear()
        chars = self._model_manager.characters if hasattr(self, "_model_manager") else []
        for char_key in chars:
            name = self._model_manager.get_display_name(char_key) if hasattr(self, "_model_manager") else char_key
            self._stats_char_combo.addItem(name, userData=char_key)
        if self._current_char and self._current_char in chars:
            idx = self._stats_char_combo.findData(self._current_char)
            if idx >= 0:
                self._stats_char_combo.setCurrentIndex(idx)
        elif self._stats_char_combo.count() > 0:
            self._stats_char_combo.setCurrentIndex(0)
        self._stats_char_combo.blockSignals(False)
        self._stats_char_combo.currentIndexChanged.connect(self._refresh_statistics)
        self._refresh_statistics()

    def _get_stats_db(self):
        if self._stats_db is None:
            from database_manager import DatabaseManager
            self._stats_db = DatabaseManager()
        return self._stats_db

    def _refresh_statistics(self, *_args):
        days = self._stats_range_combo.itemData(self._stats_range_combo.currentIndex()) or 0
        char_key = self._stats_char_combo.itemData(self._stats_char_combo.currentIndex()) or ""
        user_key = user_key_from_config(self._cfg) if hasattr(self, "_cfg") else ""
        db = self._get_stats_db()
        self._refresh_overview_cards(db)
        self._refresh_affection_chart(db, char_key, days, user_key)
        self._refresh_heatmap(db, user_key)
        self._refresh_char_messages_chart(db, days, user_key)
        self._refresh_daily_msg_chart(db, days, user_key)
        self._refresh_daily_usage_chart(db, days)

    def _refresh_overview_cards(self, db):
        summary = db.get_chat_summary()
        total_msgs = summary["total_messages"] + summary["total_group_messages"]
        self._stat_cards["messages"].set_value(str(total_msgs))
        self._stat_cards["usage_today"].set_value(_format_duration(db.get_usage_today()))
        self._stat_cards["usage_week"].set_value(_format_duration(db.get_usage_week()))
        self._stat_cards["usage_total"].set_value(_format_duration(db.get_usage_all_time()))

    def _refresh_affection_chart(self, db, character: str, days: int, user_key: str = ""):
        no_char_hint = _tr("SettingsWindow.statistics_select_char_hint", default="请在下方选择角色")
        no_data_hint = _tr("SettingsWindow.statistics_no_affection_data", default="暂无好感度变化记录")
        trend_title = _tr("SettingsWindow.statistics_affection_trend", default="好感度趋势")

        if not character:
            chart = _make_empty_chart(trend_title, no_char_hint)
            self._apply_chart_theme(chart)
            self._affection_chart_view.setChart(chart)
            return
        events = db.get_mood_events_for_chart(character, days, user_key)
        if not events:
            chart = _make_empty_chart(trend_title, no_data_hint)
            self._apply_chart_theme(chart)
            self._affection_chart_view.setChart(chart)
            return

        affection_series = QLineSeries()
        affection_series.setName(_tr("SettingsWindow.statistics_affection", default="好感度"))
        trust_series = QLineSeries()
        trust_series.setName(_tr("SettingsWindow.statistics_trust", default="信任"))
        familiarity_series = QLineSeries()
        familiarity_series.setName(_tr("SettingsWindow.statistics_familiarity", default="熟悉度"))

        min_val, max_val = 100, 0
        for i, ev in enumerate(events):
            affection_series.append(i, ev["affection"])
            trust_series.append(i, ev["trust"])
            familiarity_series.append(i, ev["familiarity"])
            min_val = min(min_val, ev["affection"], ev["trust"], ev["familiarity"])
            max_val = max(max_val, ev["affection"], ev["trust"], ev["familiarity"])

        chart = QChart()
        chart.setTitle(trend_title)
        chart.addSeries(affection_series)
        chart.addSeries(trust_series)
        chart.addSeries(familiarity_series)
        chart.setAnimationOptions(QChart.AnimationOptions.SeriesAnimations)

        axis_x = QBarCategoryAxis()
        date_labels = []
        labels = []
        visible = max(1, len(events) // 10)
        for i, ev in enumerate(events):
            day_str = ev["day"][5:] if len(ev["day"]) > 5 else ev["day"]
            date_labels.append(day_str)
            if i % visible == 0 or i == len(events) - 1:
                labels.append(day_str)
            else:
                labels.append("")
        axis_x.append(labels)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        affection_series.attachAxis(axis_x)
        trust_series.attachAxis(axis_x)
        familiarity_series.attachAxis(axis_x)

        axis_y = QValueAxis()
        lo = max(0, min_val - 5)
        hi = min(100, max_val + 5)
        if lo >= hi:
            hi = lo + 10
        axis_y.setRange(lo, hi)
        axis_y.setLabelFormat("%d")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        affection_series.attachAxis(axis_y)
        trust_series.attachAxis(axis_y)
        familiarity_series.attachAxis(axis_y)

        affection_series.setPen(QPen(_AFFECTION_COLOR, 2))
        trust_series.setPen(QPen(_TRUST_COLOR, 2))
        familiarity_series.setPen(QPen(_FAMILIARITY_COLOR, 2))

        _connect_line_tooltip(affection_series, date_labels)
        _connect_line_tooltip(trust_series, date_labels)
        _connect_line_tooltip(familiarity_series, date_labels)

        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self._apply_chart_theme(chart)
        self._affection_chart_view.setChart(chart)

    def _refresh_heatmap(self, db, user_key: str = ""):
        grid = db.get_hourly_heatmap(7, user_key)
        self._heatmap_widget.set_data(grid)

    def _refresh_char_messages_chart(self, db, days: int, user_key: str = ""):
        chart_title = _tr("SettingsWindow.statistics_chat_per_character", default="各角色对话量")
        no_data_hint = _tr("SettingsWindow.statistics_no_messages", default="暂无对话记录")

        per_char = db.get_messages_per_character_range(days, user_key)
        if not per_char:
            chart = _make_empty_chart(chart_title, no_data_hint)
            self._apply_chart_theme(chart)
            self._char_messages_chart_view.setChart(chart)
            return

        top = per_char[:10]
        names = [item["character"] for item in top]
        counts = [item["count"] for item in top]
        display_names = []
        full_names = []
        for c in names:
            if hasattr(self, "_model_manager"):
                full_name = self._model_manager.get_display_name(c) or c
            else:
                full_name = c
            full_names.append(full_name)
            display_names.append(_truncate_name(full_name))

        bar_set = QBarSet(_tr("SettingsWindow.statistics_messages", default="消息数"))
        for c in counts:
            bar_set.append(c)
        bar_set.setColor(QColor(_CHART_COLORS[0]))

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.setTitle(chart_title)
        chart.addSeries(series)
        chart.setAnimationOptions(QChart.AnimationOptions.SeriesAnimations)

        axis_x = QBarCategoryAxis()
        axis_x.append(display_names)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setLabelFormat("%d")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        _connect_bar_tooltip(bar_set, full_names)

        self._apply_chart_theme(chart)
        self._char_messages_chart_view.setChart(chart)

    def _refresh_daily_msg_chart(self, db, days: int, user_key: str = ""):
        chart_title = _tr("SettingsWindow.statistics_daily_messages", default="每日消息趋势")
        no_data_hint = _tr("SettingsWindow.statistics_no_messages", default="暂无对话记录")

        actual_days = days if days > 0 else 30
        daily = db.get_daily_message_counts(actual_days, user_key)
        if not daily:
            chart = _make_empty_chart(chart_title, no_data_hint)
            self._apply_chart_theme(chart)
            self._daily_msg_chart_view.setChart(chart)
            return

        series = QLineSeries()
        series.setName(_tr("SettingsWindow.statistics_messages", default="消息数"))
        max_val = 0
        date_labels = []
        for i, d in enumerate(daily):
            series.append(i, d["count"])
            max_val = max(max_val, d["count"])
            date_labels.append(d["day"][5:] if len(d["day"]) > 5 else d["day"])

        chart = QChart()
        chart.setTitle(chart_title)
        chart.addSeries(series)
        chart.setAnimationOptions(QChart.AnimationOptions.SeriesAnimations)

        axis_x = QBarCategoryAxis()
        axis_labels = []
        visible = max(1, len(daily) // 10)
        for i, d in enumerate(daily):
            if i % visible == 0 or i == len(daily) - 1:
                axis_labels.append(d["day"][5:] if len(d["day"]) > 5 else d["day"])
            else:
                axis_labels.append("")
        axis_x.append(axis_labels)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max(max_val + 2, 10))
        axis_y.setLabelFormat("%d")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        series.setPen(QPen(_MSG_TREND_COLOR, 2))
        _connect_line_tooltip(series, date_labels)

        chart.legend().setVisible(False)
        self._apply_chart_theme(chart)
        self._daily_msg_chart_view.setChart(chart)

    def _refresh_daily_usage_chart(self, db, days: int):
        chart_title = _tr("SettingsWindow.statistics_daily_usage", default="每日使用时长")
        no_data_hint = _tr("SettingsWindow.statistics_no_usage", default="暂无使用记录")

        actual_days = days if days > 0 else 14
        daily = db.get_usage_daily(actual_days)
        if not daily:
            chart = _make_empty_chart(chart_title, no_data_hint)
            self._apply_chart_theme(chart)
            self._daily_usage_chart_view.setChart(chart)
            return

        bar_set = QBarSet(_tr("StatisticsPage.duration_minutes", default="分钟"))
        max_val = 0
        date_labels = []
        for d in daily:
            minutes = d["seconds"] // 60
            bar_set.append(minutes)
            max_val = max(max_val, minutes)
            date_labels.append(d["day"][5:] if len(d["day"]) > 5 else d["day"])
        bar_set.setColor(_USAGE_BAR_COLOR)

        series = QBarSeries()
        series.append(bar_set)

        chart = QChart()
        chart.setTitle(chart_title)
        chart.addSeries(series)
        chart.setAnimationOptions(QChart.AnimationOptions.SeriesAnimations)

        axis_x = QBarCategoryAxis()
        axis_labels = []
        visible = max(1, len(daily) // 10)
        for i, d in enumerate(daily):
            if i % visible == 0 or i == len(daily) - 1:
                axis_labels.append(d["day"][5:] if len(d["day"]) > 5 else d["day"])
            else:
                axis_labels.append("")
        axis_x.append(axis_labels)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max(max_val + 2, 10))
        axis_y.setLabelFormat("%d")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        _connect_bar_tooltip(bar_set, date_labels, suffix=_tr("StatisticsPage.duration_minutes_short", default="分钟"))

        chart.legend().setVisible(False)
        self._apply_chart_theme(chart)
        self._daily_usage_chart_view.setChart(chart)

    def _apply_chart_theme(self, chart: QChart):
        dark = isDarkTheme()
        if dark:
            chart_bg = QColor("#1e1e1e")
            chart_border = QColor("#3a3a3a")
            chart.setBackgroundBrush(chart_bg)
            chart.setTitleBrush(QColor("#f0f0f0"))
            axis_brush = QColor("#c0c0c0")
        else:
            chart_bg = QColor("#ffffff")
            chart_border = QColor("#dcdfe6")
            chart.setBackgroundBrush(chart_bg)
            chart.setTitleBrush(QColor("#1f2328"))
            axis_brush = QColor("#555555")
        chart.setBackgroundPen(QPen(chart_border, 1))
        for axis in chart.axes():
            axis.setLabelsColor(axis_brush)
            if isinstance(axis, QValueAxis):
                axis.setLinePenColor(axis_brush)
                axis.setGridLineColor(QColor("#3a3a3a" if dark else "#e0e0e0"))

    def _apply_chart_view_theme(self, view: QChartView):
        dark = isDarkTheme()
        bg = "#1e1e1e" if dark else "#ffffff"
        border = "#3a3a3a" if dark else "#dcdfe6"
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setBackgroundBrush(QBrush(QColor(bg)))
        view.viewport().setAutoFillBackground(True)
        view.viewport().setStyleSheet(f"background: {bg};")
        view.setStyleSheet(f"QChartView {{ background: {bg}; border: 1px solid {border}; }}")

    def _refresh_chart_themes(self):
        for view in (
            self._affection_chart_view,
            self._char_messages_chart_view,
            self._daily_msg_chart_view,
            self._daily_usage_chart_view,
        ):
            self._apply_chart_view_theme(view)
            chart = view.chart()
            if chart:
                self._apply_chart_theme(chart)
