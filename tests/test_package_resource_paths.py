from pathlib import Path

from bandori_core.process_utils import app_base_dir
from bandori_live2d.lua_hit_area_projection import _lua_source_path
from bandori_ui.fluent_bootstrap import prefer_local_pyside6_fluent_widgets


def test_source_resources_still_resolve_from_project_root():
    root = Path(__file__).resolve().parents[1]
    assert app_base_dir() == root
    assert _lua_source_path() == root / "custom_hit_area_state.lua"
    assert _lua_source_path().is_file()


def test_local_fluent_checkout_is_discovered(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    checkout = root / "third_party" / "PyQt-Fluent-Widgets"
    if not (checkout / "qfluentwidgets" / "__init__.py").is_file():
        return

    import sys

    monkeypatch.setattr(sys, "path", list(sys.path))
    prefer_local_pyside6_fluent_widgets()
    assert sys.path[0] == str(checkout)
