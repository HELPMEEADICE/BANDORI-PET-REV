from pathlib import Path

from bandori_core.process_utils import app_base_dir
from bandori_ui.fluent_bootstrap import prefer_local_pyside6_fluent_widgets




def test_local_fluent_checkout_is_discovered(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    checkout = root / "third_party" / "PyQt-Fluent-Widgets"
    if not (checkout / "qfluentwidgets" / "__init__.py").is_file():
        return

    import sys

    monkeypatch.setattr(sys, "path", list(sys.path))
    prefer_local_pyside6_fluent_widgets()
    assert sys.path[0] == str(checkout)
