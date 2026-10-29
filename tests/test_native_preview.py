import os
from pathlib import Path
import subprocess
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap
import pytest

from bandori_core.native_pet import native_executable
from settings_window.widgets import Live2DPreviewRenderWidget


def test_preview_displays_native_png_and_rescales_without_a_gl_context(tmp_path):
    app = QApplication.instance() or QApplication([])
    widget = Live2DPreviewRenderWidget()
    widget.resize(200, 240)
    image = QPixmap(50, 100)
    image.fill()
    output = str(tmp_path / "frame.png")
    assert image.save(output)
    widget._output = output
    widget._finished(0, None)
    assert not widget.pixmap().isNull()
    assert widget.pixmap().height() <= widget.height()
    widget.dispose()
    widget.deleteLater()
    app.processEvents()


def test_new_preview_request_cancels_the_old_process_before_starting(monkeypatch):
    app = QApplication.instance() or QApplication([])
    from unittest.mock import Mock
    from PySide6.QtCore import QProcess
    widget = Live2DPreviewRenderWidget()
    process = Mock()
    process.state.return_value = QProcess.ProcessState.Running
    widget._process = process
    widget.set_model_path("new.model3.json")
    process.kill.assert_called_once()
    assert widget._model_path == "new.model3.json"
    assert widget._serial != widget._active_serial
    widget.dispose()
    widget.deleteLater()
    app.processEvents()


def test_real_neocari_preview_exports_a_png(tmp_path):
    root = Path(__file__).resolve().parents[1]
    model = root / "models/.cache/kasumi/live_default/model.json"
    if not model.is_file():
        pytest.skip("local model required")
    try:
        binary = native_executable(root)
    except FileNotFoundError:
        pytest.skip("native build required")
    output = tmp_path / "preview.png"
    result = subprocess.run([str(binary), "--render-preview", str(model), "--output", str(output), "--root", str(root)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
