import sys

import process_utils


def test_existing_windows_shortcut_skips_com_initialization(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    shortcut = (
        tmp_path
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "BandoriPet.lnk"
    )
    shortcut.parent.mkdir(parents=True)
    shortcut.write_bytes(b"existing shortcut")
    monkeypatch.setitem(sys.modules, "pythoncom", None)

    assert process_utils.ensure_windows_app_user_model_shortcut(
        "BandoriPet",
        "BandoriPet",
    )
