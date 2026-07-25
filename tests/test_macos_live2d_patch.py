from pathlib import Path

import pytest

from installer.macos.patch_live2d_image_loader import (
    FUNCTION_MARKER,
    LOAD_IMAGE_BLOCK,
    patch_image_loader,
)


def test_live2d_image_loader_patch_is_idempotent(tmp_path: Path):
    image_loader = tmp_path / "image_loader.lua"
    image_loader.write_text(
        "-- fixture prefix\n" + LOAD_IMAGE_BLOCK,
        encoding="utf-8",
    )

    assert patch_image_loader(image_loader)
    first_result = image_loader.read_text(encoding="utf-8")
    assert first_result.count(FUNCTION_MARKER) == 1
    assert "pcall(decodePNG, bytes, label)" in first_result

    assert not patch_image_loader(image_loader)
    assert image_loader.read_text(encoding="utf-8") == first_result


def test_live2d_image_loader_patch_rejects_unknown_layout(tmp_path: Path):
    image_loader = tmp_path / "image_loader.lua"
    image_loader.write_text("return {}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unexpected layout"):
        patch_image_loader(image_loader)


def test_macos_source_and_dmg_installers_use_the_same_live2d_patch():
    source_installer = Path(
        "installer/macos/install_source_dependencies.sh"
    ).read_text(encoding="utf-8")
    dmg_builder = Path("installer/macos/build_dmg.sh").read_text(encoding="utf-8")
    command = "installer/macos/patch_live2d_image_loader.py"

    assert command in source_installer
    assert command in dmg_builder
