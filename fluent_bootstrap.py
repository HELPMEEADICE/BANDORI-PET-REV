import sys
import importlib.util
from pathlib import Path


def prefer_local_pyside6_fluent_widgets() -> None:
    """Prefer the repo's PySide6 qfluentwidgets checkout during source runs."""
    root = Path(__file__).resolve().parent
    local_fluent = root / "third_party" / "PyQt-Fluent-Widgets"
    if not (local_fluent / "qfluentwidgets" / "__init__.py").exists():
        return

    local_path = str(local_fluent)
    try:
        sys.path.remove(local_path)
    except ValueError:
        pass
    sys.path.insert(0, local_path)


def assert_pyside6_fluent_widgets() -> None:
    assert_pyside6_frameless_window()
    try:
        from qfluentwidgets.common import style_sheet
    except Exception:
        return
    qcolor_module = getattr(style_sheet.QColor, "__module__", "")
    if not qcolor_module.startswith("PySide6."):
        raise RuntimeError(
            "qfluentwidgets is using PyQt5, but BandoriPet uses PySide6. "
            "Install the PySide6 Fluent Widgets branch and remove the PyQt5 package, "
            "or run: python3 -m pip uninstall PyQt-Fluent-Widgets PyQt5-Frameless-Window"
        )


def assert_pyside6_frameless_window() -> None:
    spec = importlib.util.find_spec("qframelesswindow")
    if spec is None or spec.origin is None:
        return
    try:
        header = Path(spec.origin).read_text(encoding="utf-8", errors="ignore")[:2048]
    except OSError:
        return
    if "PyQt5-Frameless-Window" in header or "from PyQt5" in header:
        raise RuntimeError(
            "qframelesswindow is using PyQt5, but BandoriPet uses PySide6. "
            "Run: python3 -m pip install --force-reinstall --no-deps "
            "PySideSix-Frameless-Window==0.8.1"
        )


prefer_local_pyside6_fluent_widgets()
assert_pyside6_frameless_window()
