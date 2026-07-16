from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import native_launcher


def _make_launchable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"native")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_explicit_python_fallback_is_removed_before_legacy_runtime():
    argv = ["main.py", "--python-legacy", "--debug"]

    assert native_launcher.dispatch_source_entrypoint(
        argv,
        environ={},
        project_root=Path.cwd(),
    ) is None
    assert argv == ["main.py", "--debug"]


def test_environment_can_request_explicit_python_fallback():
    argv = ["main.py"]

    assert native_launcher.dispatch_source_entrypoint(
        argv,
        environ={native_launcher.PYTHON_FALLBACK_ENV: "yes"},
        project_root=Path.cwd(),
    ) is None


def test_explicit_native_path_is_launched_with_forwarded_arguments(tmp_path):
    executable = _make_launchable(tmp_path / "custom-native")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 23)

    result = native_launcher.launch_native_application(
        ["main.py", "--data-root", "portable data"],
        tmp_path,
        environ={native_launcher.NATIVE_APP_ENV: str(executable)},
        runner=runner,
    )

    assert result == 23
    assert calls == [
        (
            [str(executable.resolve()), "--data-root", "portable data"],
            {"cwd": str(tmp_path.resolve()), "check": False},
        )
    ]


def test_invalid_explicit_native_path_fails_without_silent_fallback(tmp_path, capsys):
    result = native_launcher.launch_native_application(
        ["main.py"],
        tmp_path,
        environ={native_launcher.NATIVE_APP_ENV: str(tmp_path / "missing")},
    )

    assert result == 2
    assert native_launcher.NATIVE_APP_ENV in capsys.readouterr().err


def test_standard_build_candidate_is_discovered(tmp_path, monkeypatch):
    suffix = ".exe" if os.name == "nt" else ""
    executable = _make_launchable(
        tmp_path / "build-rust" / "native" / "qt" / "Release" / f"BandoriPet{suffix}"
    )
    monkeypatch.setattr(native_launcher.sys, "platform", "win32" if os.name == "nt" else "linux")

    found, error = native_launcher.find_native_application(tmp_path, environ={})

    assert found == executable.resolve()
    assert error == ""


def test_main_dispatches_before_importing_pyside():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")

    assert source.index("dispatch_source_entrypoint()") < source.index("from PySide6")
    assert 'if __name__ == "__main__":' in source


def test_source_entry_fails_before_optional_python_dependencies(tmp_path):
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment[native_launcher.NATIVE_APP_ENV] = str(tmp_path / "missing-native")

    completed = subprocess.run(
        [sys.executable, "-S", str(root / "main.py")],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert native_launcher.NATIVE_APP_ENV in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
