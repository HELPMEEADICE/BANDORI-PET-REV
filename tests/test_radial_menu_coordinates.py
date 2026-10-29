import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect

import radial_menu_process as radial


def screen(name, geometry):
    return Mock(name=lambda: name, geometry=lambda: QRect(*geometry))


@pytest.mark.parametrize("scale", [1.0, 1.25, 1.5, 2.0])
def test_native_click_is_converted_to_qt_screen_coordinates(monkeypatch, scale):
    monkeypatch.setattr(radial.QGuiApplication, "screens", lambda: [screen("primary", (0, 0, 1920, 1080))])
    # Menu startup may take time; do not replace the captured click with a new
    # cursor sample after the pointer has moved.
    monkeypatch.setattr(radial.QCursor, "pos", Mock(side_effect=AssertionError("resampled cursor")))
    point = radial._menu_position({
        "x": 960 * scale, "y": 600 * scale,
        "coordinate_space": "native_physical", "screen_name": "primary",
        "screen_geometry": [0, 0, int(1920 * scale), int(1080 * scale)],
    })
    assert point == QPoint(960, 600)


@pytest.mark.parametrize("origin", [(3840, 120), (-2560, -400)])
def test_mixed_dpi_secondary_screen_keeps_its_own_origin(monkeypatch, origin):
    x, y = origin
    monkeypatch.setattr(radial.QGuiApplication, "screens", lambda: [
        screen("primary", (0, 0, 1920, 1080)),
        screen("secondary", (x, y, 1280, 720)),
    ])
    point = radial._menu_position({
        "x": x + 800, "y": y + 600, "coordinate_space": "native_physical",
        "screen_name": "secondary", "screen_geometry": [x, y, 2560, 1440],
    })
    assert point == QPoint(x + 400, y + 300)


def test_xwayland_output_can_match_qt_geometry_with_a_different_name(monkeypatch):
    monkeypatch.setattr(radial.QGuiApplication, "screens", lambda: [screen("DP-1", (1920, 0, 1280, 720))])
    assert radial._menu_position({
        "x": 2720, "y": 600, "coordinate_space": "native_physical",
        "screen_name": "XWAYLAND0", "screen_geometry": [1920, 0, 2560, 1440],
    }) == QPoint(2320, 300)


def test_qt_and_appkit_logical_clicks_are_not_scaled_again(monkeypatch):
    monkeypatch.setattr(radial.QGuiApplication, "screens", Mock(side_effect=AssertionError("already logical")))
    assert radial._menu_position({"x": -420, "y": 300}) == QPoint(-420, 300)


def test_disconnected_output_falls_back_to_the_current_qt_cursor(monkeypatch):
    monkeypatch.setattr(radial.QGuiApplication, "screens", lambda: [])
    monkeypatch.setattr(radial.QCursor, "pos", lambda: QPoint(200, 300))
    assert radial._menu_position({
        "x": 2400, "y": 800, "coordinate_space": "native_physical",
        "screen_name": "removed", "screen_geometry": [1920, 0, 1920, 1080],
    }) == QPoint(200, 300)
