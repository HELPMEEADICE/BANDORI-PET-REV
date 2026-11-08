"""VRM discovery/import, metadata and native MToon regressions."""
import json
import os
import struct
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bandori_models import custom_model_import as importer
from bandori_models import model_manager
from bandori_models.vrm_manifest import read_vrm_manifest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native/pet_backend/crates/pet-vrm/tests/fixtures"


@pytest.mark.parametrize("version", [0, 1])
def test_import_vrm_scan_format_motions_and_expressions(tmp_path, version):
    models = tmp_path / "models"
    source = tmp_path / "Avatar.vrm"
    source.write_bytes((FIXTURES / f"minimal-vrm{version}.vrm").read_bytes())
    (tmp_path / "wave.vrma").write_bytes(b"external motion")
    source.with_suffix(".pet.json").write_text(json.dumps({"motions": {"Wave": "wave.vrma"}}))
    with patch.object(importer, "MODELS_DIR", models):
        assert importer.import_from_vrm(str(source), "测试VRM") == ("测试VRM", ["default"])
    assert (models / "测试VRM/default/wave.vrma").read_bytes() == b"external motion"
    with patch.object(model_manager, "MODELS_DIR", models), patch.object(model_manager, "BUNDLED_MODELS_DIR", models):
        manager = model_manager.ModelManager()
        assert manager.get_model_format("测试VRM", "default") == "vrm"
        assert set(manager.get_motion_names("测试VRM", "default")) == {"Idle", "Wave", "LookAround", "Thinking", "Relax", "Blush"}
        assert manager.get_expression_names("测试VRM", "default") == ["joy" if version == 0 else "happy"]
        assert model_manager.models_dir_exists()


def test_vrm_import_rejects_truncated_container_and_escaping_motion(tmp_path):
    source = tmp_path / "broken.vrm"
    source.write_bytes(b"glTF")
    with pytest.raises(importer.CustomModelImportError, match="bad_model_json"):
        importer.import_from_vrm(str(source), "Broken")
    source.write_bytes((FIXTURES / "minimal-vrm0.vrm").read_bytes())
    source.with_suffix(".pet.json").write_text('{"motions":{"Escape":"../secret.vrma"}}')
    with pytest.raises(importer.CustomModelImportError, match="unsafe_resource_path"):
        importer.import_from_vrm(str(source), "Unsafe")
    source.write_bytes(source.read_bytes()[:-4])
    with pytest.raises(ValueError, match="header"):
        read_vrm_manifest(source)


def test_vrm_file_picker_and_format_badge():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    from settings_window.widgets import CostumeItem, CustomModelImportDialog
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    dialog = CustomModelImportDialog(parent)
    dialog._set_source("C:/avatars/POPY.vrm", "vrm")
    assert dialog.source_kind == "vrm" and dialog.display_name == "POPY"
    item = CostumeItem("default", "POPY", model_format="vrm")
    item.resize(300, 40)
    assert item._format_badge.text() == "VRM"
    assert not item._format_badge.isHidden()
    assert item._has_format_badge
    item.deleteLater()
    dialog.deleteLater()
    parent.deleteLater()
    app.processEvents()


def _rewrite_glb(source, path, change):
    data = source.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    manifest = json.loads(data[20:20 + length])
    change(manifest)
    encoded = json.dumps(manifest).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary = data[20 + length:]
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(encoded) + len(binary))
                     + struct.pack("<I4s", len(encoded), b"JSON") + encoded + binary)


def test_native_mtoon_emission_changes_rendered_pixels(tmp_path):
    from bandori_core.native_pet import native_executable
    from PIL import Image, ImageStat
    try:
        binary = native_executable(ROOT)
    except FileNotFoundError:
        pytest.skip("native build required")
    colors = []
    for emissive in (False, True):
        model = tmp_path / f"emission-{emissive}.vrm"
        def change(data):
            material = data["extensions"]["VRM"]["materialProperties"][0]
            material["vectorProperties"]["_EmissionColor"] = [0, 0, int(emissive), 1]
        _rewrite_glb(FIXTURES / "minimal-vrm0.vrm", model, change)
        output = model.with_suffix(".png")
        run = subprocess.run([str(binary), "--render-preview", str(model), "--output", str(output)],
                             capture_output=True, timeout=30)
        assert run.returncode == 0, run.stderr.decode(errors="replace")
        with Image.open(output) as image:
            assert image.getchannel("A").getextrema() == (0, 255)
            colors.append(ImageStat.Stat(image.convert("RGB"), mask=image.getchannel("A")).mean)
    assert colors[1][2] > colors[0][2] + 100
