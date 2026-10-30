"""Find the Rust archive library when only the native renderer was built."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bandori_models import native_assets


@pytest.fixture
def loader(tmp_path, monkeypatch):
    monkeypatch.delenv("BANDORI_PET_ASSETS", raising=False)
    monkeypatch.delenv("CARGO_TARGET_DIR", raising=False)
    monkeypatch.setattr(native_assets, "_library", None)
    monkeypatch.setattr(native_assets, "__file__", str(tmp_path / "bandori_models/native_assets.py"))
    monkeypatch.setattr(native_assets, "sys", SimpleNamespace(
        platform=native_assets.sys.platform,
        executable=str(tmp_path / "python/python.exe"),
    ))
    library = SimpleNamespace(
        pet_assets_abi_version=Mock(return_value=1),
        pet_assets_request=Mock(),
        pet_assets_free=Mock(),
    )
    load = Mock(return_value=library)
    monkeypatch.setattr(native_assets.ctypes, "CDLL", load)
    name = {"win32": "pet_assets.dll", "darwin": "libpet_assets.dylib"}.get(
        native_assets.sys.platform, "libpet_assets.so",
    )
    return tmp_path, name, library, load


def make_library(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path.resolve()


@pytest.mark.parametrize("profile", ["release", "debug"])
@pytest.mark.parametrize("custom_target", [False, True])
def test_loads_library_built_as_renderer_dependency(loader, monkeypatch, profile, custom_target):
    root, name, library, load = loader
    target = root / "native/pet_backend/target"
    if custom_target:
        target = root / "custom-target"
        monkeypatch.setenv("CARGO_TARGET_DIR", str(target))
    artifact = make_library(target / profile / "deps" / name)

    assert native_assets._load_library() is library
    load.assert_called_once_with(str(artifact))
    # Reopening settings reuses the loaded Rust library.
    assert native_assets._load_library() is library
    assert load.call_count == 1


def test_packaged_library_takes_precedence_over_cargo_dependency(loader):
    root, name, library, load = loader
    make_library(root / "native/pet_backend/target/release/deps" / name)
    packaged = make_library(root / name)

    assert native_assets._load_library() is library
    load.assert_called_once_with(str(packaged))


def test_explicit_missing_library_does_not_load_another_build(loader, monkeypatch):
    root, name, _library, load = loader
    make_library(root / "native/pet_backend/target/release/deps" / name)
    monkeypatch.setenv("BANDORI_PET_ASSETS", str(root / "missing" / name))

    with pytest.raises(RuntimeError, match="pet-assets native library is missing"):
        native_assets._load_library()
    load.assert_not_called()
