import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSize, QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from shiboken6 import isValid

from settings_window.images import read_scaled_image
from settings_window.pages.statistics import StatisticsPageMixin
from settings_window.settings_window import SettingsWindow
from settings_window.widgets import PageRefreshTimer
from settings_window.workers import ModelDetailImageWorker, ModelDetailMetadataWorker


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def flush_events(app):
    app.processEvents()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_page_refresh_stops_when_hidden_or_minimized_and_resumes(app):
    window = QWidget()
    page = QWidget(window)
    refresh = Mock()
    timer = PageRefreshTimer(page, 60_000, refresh)
    assert not timer.isActive()

    window.show()
    flush_events(app)
    assert timer.isActive()
    assert timer.interval() == 60_000
    assert refresh.call_count == 1

    for hide, show in (
        (page.hide, page.show),
        (window.hide, window.show),
        (window.showMinimized, window.showNormal),
    ):
        hide()
        flush_events(app)
        assert not timer.isActive()
        calls = refresh.call_count
        # A timeout already queued before Hide must not perform background work.
        timer.timeout.emit()
        assert refresh.call_count == calls

        show()
        flush_events(app)
        assert timer.isActive()
        assert refresh.call_count == calls + 1

    window.close()
    assert not timer.isActive()
    window.deleteLater()
    flush_events(app)


class _StatisticsHarness(StatisticsPageMixin, QWidget):
    def __init__(self, db):
        super().__init__()
        self._cfg = None
        self._current_char = "kasumi"
        self._model_manager = SimpleNamespace(
            characters=["kasumi"], get_display_name=lambda character: character,
        )
        self._get_stats_db = lambda: db
        self._statistics_page = self._build_statistics_page()
        QVBoxLayout(self).addWidget(self._statistics_page)

    def _make_theme_widget(self, widget):
        return widget

    def _connect_theme_changed(self, _callback):
        pass

    def charts(self):
        return [view.chart() for view in (
            self._affection_chart_view, self._char_messages_chart_view,
            self._daily_msg_chart_view, self._daily_usage_chart_view,
        )]


@pytest.mark.parametrize("with_data", [False, True])
def test_statistics_refresh_releases_old_charts_and_does_no_hidden_queries(app, with_data):
    db = Mock()
    db.get_chat_summary.return_value = {"total_messages": 2, "total_group_messages": 0}
    for name in ("get_usage_today", "get_usage_week", "get_usage_all_time"):
        getattr(db, name).return_value = 120
    db.get_hourly_heatmap.return_value = [[0] * 24 for _ in range(7)]
    db.get_mood_events_for_chart.return_value = [
        {"day": "2026-10-01", "affection": 10, "trust": 20, "familiarity": 30},
    ] if with_data else []
    db.get_messages_per_character_range.return_value = [
        {"character": "kasumi", "count": 2},
    ] if with_data else []
    db.get_daily_message_counts.return_value = [
        {"day": "2026-10-01", "count": 2},
    ] if with_data else []
    db.get_usage_daily.return_value = [
        {"day": "2026-10-01", "seconds": 120},
    ] if with_data else []
    window = _StatisticsHarness(db)
    assert not db.mock_calls

    previous = window.charts()
    window.show()
    flush_events(app)
    assert all(not isValid(chart) for chart in previous)

    for _ in range(3):
        previous = window.charts()
        window._refresh_statistics()
        flush_events(app)
        assert all(not isValid(chart) for chart in previous)
        assert all(isValid(chart) for chart in window.charts())

    window.hide()
    db.reset_mock()
    window._stats_refresh_timer.timeout.emit()
    assert not db.mock_calls
    assert not window._stats_refresh_timer.isActive()
    window.deleteLater()
    flush_events(app)


@pytest.fixture
def large_image(tmp_path):
    path = tmp_path / "large.png"
    image = QImage(2400, 3600, QImage.Format.Format_ARGB32)
    image.fill(0x80223344)
    assert image.save(str(path))
    return path


@pytest.mark.parametrize("source", ["path", "archive", "fallback"])
def test_thumbnail_decode_preserves_aspect_ratio_and_transparency(large_image, source):
    path = str(large_image) if source == "path" else "missing.png" if source == "fallback" else ""
    data = large_image.read_bytes() if source != "path" else b""
    image = read_scaled_image(path, data, QSize(400, 260))
    assert not image.isNull()
    assert image.width() <= 400
    assert image.height() == 260
    assert abs(image.width() / image.height() - 2 / 3) < 0.01
    assert image.pixelColor(0, 0).alpha() == 128


def test_detail_cache_retains_thumbnails_instead_of_source_images(app, large_image):
    window = SettingsWindow.__new__(SettingsWindow)
    window._model_manager = SimpleNamespace(
        get_character_image_path=lambda _character: str(large_image),
        get_character_image_data=lambda _character: b"",
    )
    window._detail_image_pixmap_cache = {}
    for index in range(12):
        window._load_detail_character_pixmap(str(index))
    cache = window._detail_image_pixmap_cache
    assert len(cache) == 8
    assert sum(p.width() * p.height() * p.depth() // 8 for p in cache.values()) < 2 * 1024 * 1024


def test_image_worker_decodes_thumbnail_before_delivering_to_ui(app, large_image):
    worker = ModelDetailImageWorker(SimpleNamespace(
        get_character_image_path=lambda _character: str(large_image),
        get_character_image_data=lambda _character: b"",
    ), "kasumi", image_size=QSize(800, 520))
    results, completed = [], []
    worker.image_loaded.connect(results.append)
    worker.finished.connect(lambda: completed.append(True))
    worker.start()
    assert worker.wait(5000)
    flush_events(app)
    assert completed == [True]
    assert len(results) == 1
    assert set(results[0]) == {"character", "image"}
    assert results[0]["image"].height() == 520
    assert results[0]["image"].sizeInBytes() < 1024 * 1024


@pytest.mark.parametrize("kind", ["image", "metadata"])
def test_cancelled_detail_worker_still_completes_and_is_released(app, kind):
    def interrupt(*_args):
        QThread.currentThread().requestInterruption()
        return "" if kind == "image" else []

    if kind == "image":
        worker = ModelDetailImageWorker(SimpleNamespace(
            get_character_image_path=interrupt,
            get_character_image_data=Mock(side_effect=AssertionError("cancelled")),
        ), "kasumi")
    else:
        worker = ModelDetailMetadataWorker(SimpleNamespace(
            get_motion_names=interrupt,
            get_expression_names=Mock(side_effect=AssertionError("cancelled")),
        ), {"character": "kasumi", "costume": "live_default"})
    results, completed = [], []
    result_signal = worker.image_loaded if kind == "image" else worker.metadata_loaded
    result_signal.connect(results.append)
    worker.finished.connect(lambda: completed.append(True))
    worker.start()
    assert worker.wait(5000)
    flush_events(app)
    assert not results
    assert completed == [True]

    window = SimpleNamespace(
        _model_detail_image_worker=worker, _model_detail_metadata_worker=None,
        _retired_settings_workers=[worker],
    )
    SettingsWindow._on_model_detail_worker_completed(window, worker)
    assert window._model_detail_image_worker is None
    assert window._retired_settings_workers == []
    flush_events(app)
    assert not isValid(worker)


def test_opening_settings_does_not_import_chart_runtime():
    subprocess.run([
        sys.executable, "-c",
        "import sys; import settings_window; assert 'PySide6.QtCharts' not in sys.modules",
    ], check=True, capture_output=True, timeout=30)


@pytest.mark.parametrize("explicit_threads", [None, "2"])
def test_settings_process_limits_numeric_threads_and_preserves_user_overrides(tmp_path, explicit_threads):
    env = dict(os.environ, BANDORI_PET_DATA_DIR=str(tmp_path))
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        env.pop(name, None)
        if explicit_threads is not None:
            env[name] = explicit_threads
    subprocess.run([
        sys.executable, "-c",
        "import os; import settings_process; "
        "assert all(os.environ[name] == " + repr(explicit_threads or "1") +
        " for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'))",
    ], env=env, check=True, capture_output=True, timeout=30)
