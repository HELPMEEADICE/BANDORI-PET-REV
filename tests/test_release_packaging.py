import hashlib
import struct
import zipfile

import pytest

from installer import package_release as release


def frozen_windows_tree(tmp_path, machine=0x8664, arch="AMD64"):
    build = tmp_path / "BUILD" / f"BANDORI-PET-REV-RELEASE-WIN-{arch}"
    build.mkdir(parents=True)
    for name in release.RESOURCES:
        (build / name).write_text("resource", encoding="utf-8")
    (build / "models").mkdir()
    (build / "lib").mkdir()
    (build / "lib" / "library.zip").write_bytes(b"frozen python")
    (build / "pet_assets.dll").write_bytes(b"archive library")
    header = bytearray(70)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 60, 64)
    struct.pack_into("<4sH", header, 64, b"PE\0\0", machine)
    for name in release.EXECUTABLES:
        (build / f"{name}.exe").write_bytes(header)
    return build


@pytest.mark.parametrize("tag", ["3.2.1", "v3.2.1"])
def test_release_version_accepts_existing_tag_convention(tag):
    assert release.validate_version("3.2.1", tag) == "3.2.1"


@pytest.mark.parametrize("version,tag", [
    ("3.2.1", "v3.2.0"), ("3.2.1\nextra", None),
    ("256.0.0", None), ("3.256.0", None), ("3.2.65536", None),
])
def test_invalid_version_or_mismatched_release_fails(version, tag):
    with pytest.raises(ValueError):
        release.validate_version(version, tag)


@pytest.mark.parametrize("arch,machine,pe_machine,msi_arch,inno_arch,suffix", [
    ("x86_64", "AMD64", 0x8664, "win64", "winamd64", "win-x86_64"),
    ("aarch64", "ARM64", 0xAA64, "win-arm64", "winarm64", "win-arm64"),
])
def test_windows_zip_unpacks_at_executable_root_and_preserves_resources(
    tmp_path, monkeypatch, arch, machine, pe_machine, msi_arch, inno_arch, suffix,
):
    build = frozen_windows_tree(tmp_path, machine=pe_machine, arch=machine)
    monkeypatch.setattr(release, "ROOT", tmp_path)
    monkeypatch.setattr(release.platform, "machine", lambda: machine)
    version = release.APP_VERSION
    (tmp_path / "BUILD" / f"BandoriPet-{version}-{msi_arch}.msi").write_bytes(b"msi")
    (tmp_path / "BUILD" / f"BandoriPet-{version}-{inno_arch}-setup.exe").write_bytes(b"inno")
    output = tmp_path / "installers"
    release.package_windows(arch, output)
    assert (output / f"BandoriPet-{version}-{suffix}.msi").read_bytes() == b"msi"
    assert (output / f"BandoriPet-{version}-{suffix}-setup.exe").read_bytes() == b"inno"
    with zipfile.ZipFile(output / f"BandoriPet-{version}-{suffix}.zip") as archive:
        assert archive.read("BandoriPet.exe") == (build / "BandoriPet.exe").read_bytes()
        assert archive.read("lib/library.zip") == b"frozen python"
        assert "models/" in archive.namelist()
        assert ".bandoripet-managed-files" in archive.namelist()
        assert all(name not in archive.namelist() for name in release.USER_DATA)


@pytest.mark.parametrize("name", release.USER_DATA)
def test_packaging_rejects_private_user_data(tmp_path, name):
    build = frozen_windows_tree(tmp_path)
    (build / name).touch()
    with pytest.raises(ValueError, match="User data"):
        release.validate_build(build, "windows", "x86_64")


def test_packaging_rejects_wrong_architecture_and_bundled_models(tmp_path):
    build = frozen_windows_tree(tmp_path, machine=0xAA64)
    with pytest.raises(ValueError, match="architecture"):
        release.validate_build(build, "windows", "x86_64")
    release.validate_build(build, "windows", "aarch64")
    (build / "models" / "private.model").write_bytes(b"model")
    with pytest.raises(ValueError, match="models directory must be empty"):
        release.validate_build(build, "windows", "aarch64")


def test_packaging_rejects_retired_renderer_but_keeps_plugin_runtime(tmp_path):
    build = frozen_windows_tree(tmp_path)
    (build / "lib" / "lupa").mkdir()
    (build / "lib" / "lupa" / "luajit21.pyd").write_bytes(b"plugin runtime")
    release.validate_build(build, "windows", "x86_64")
    (build / "custom_hit_area_state.ljbc").write_bytes(b"obsolete renderer")
    with pytest.raises(ValueError, match="Retired renderer"):
        release.validate_build(build, "windows", "x86_64")


def test_packaging_requires_native_archive_library(tmp_path):
    build = frozen_windows_tree(tmp_path)
    (build / "pet_assets.dll").unlink()
    with pytest.raises(ValueError, match="pet-assets library"):
        release.validate_build(build, "windows", "x86_64")


def test_checksums_cover_installer_bytes_and_require_every_format(tmp_path):
    names = ["application.zip", "application.msi", "application-setup.exe"]
    for name in names:
        (tmp_path / name).write_bytes(name.encode("ascii"))
    release.write_checksums(tmp_path, names, "SHA256SUMS.txt")
    for line in (tmp_path / "SHA256SUMS.txt").read_text().splitlines():
        digest, name = line.split("  ")
        assert digest == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
    (tmp_path / names[-1]).unlink()
    with pytest.raises(ValueError, match="Missing or empty installer"):
        release.write_checksums(tmp_path, names, "SHA256SUMS.txt")
    (tmp_path / names[-1]).touch()
    with pytest.raises(ValueError, match="Missing or empty installer"):
        release.write_checksums(tmp_path, names, "SHA256SUMS.txt")
