import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from bandori_ui.radial_menu import RadialMenu
from wayland.types import StackMode


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture(params=[3, 4, 8])
def menu(application, monkeypatch, request):
    menu = RadialMenu()
    for i in range(request.param):
        menu.add_item("", str(i), QColor(80, 80, 80), lambda: None)
    for method in ("show", "raise_", "activateWindow", "setFocus", "_play_show_animation"):
        monkeypatch.setattr(menu, method, lambda: None)
    monkeypatch.setattr(menu._outside_click_timer, "start", lambda: None)
    monkeypatch.setattr(menu, "_mouse_buttons_pressed", lambda: False)
    yield menu
    menu.close()


def expanded_bounds(menu):
    center = menu._center_point()
    bounds = QRect(center.x() - 40, center.y() - 40, 80, 80)
    for item in menu._items:
        bounds = bounds.united(item.widget.geometry().translated(item.end_offset))
    return bounds.translated(menu.pos())


@pytest.mark.parametrize("available", [QRect(0, 0, 1920, 1040), QRect(-1920, -200, 1920, 1040)])
def test_bottom_right_menu_reaches_work_area_edges(menu, monkeypatch, available):
    screen = Mock(availableGeometry=lambda: available)
    monkeypatch.setattr("bandori_ui.radial_menu.QGuiApplication.screenAt", lambda _: screen)

    menu.show_at(available.bottomRight())
    bounds = expanded_bounds(menu)

    assert available.contains(bounds)
    assert bounds.bottomRight() == available.bottomRight()


def test_top_left_menu_keeps_all_buttons_inside_work_area(menu, monkeypatch):
    available = QRect(-1280, 60, 1280, 660)
    screen = Mock(availableGeometry=lambda: available)
    monkeypatch.setattr("bandori_ui.radial_menu.QGuiApplication.screenAt", lambda _: screen)

    menu.show_at(available.topLeft())
    bounds = expanded_bounds(menu)

    assert available.contains(bounds)
    assert bounds.topLeft() == available.topLeft()


def test_menu_stays_at_click_when_buttons_fit_but_padding_does_not(menu, monkeypatch):
    available = QRect(0, 0, 1920, 1040)
    screen = Mock(availableGeometry=lambda: available)
    monkeypatch.setattr("bandori_ui.radial_menu.QGuiApplication.screenAt", lambda _: screen)
    click = QPoint(960, 875)

    menu.show_at(click)

    assert menu.pos() + menu._center_point() == click
    assert available.contains(expanded_bounds(menu))


def test_wayland_overlay_keeps_expanded_menu_inside_bottom_edge(menu, monkeypatch):
    available = QRect(-1920, -200, 1920, 1040)
    screen = Mock(availableGeometry=lambda: available, serialNumber=lambda: "output")
    monkeypatch.setattr("bandori_ui.radial_menu.QGuiApplication.screenAt", lambda _: screen)
    controller = Mock(native_wayland=True)
    menu.set_surface_controller(controller, StackMode.TOP)

    menu.show_at(available.bottomRight())
    # The compositor places the full-output surface at the requested origin.
    bounds = expanded_bounds(menu).translated(available.topLeft() - menu.pos())

    assert available.contains(bounds)
    assert bounds.bottomRight() == available.bottomRight()
    assert menu.size() == available.size()
