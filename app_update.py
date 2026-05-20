from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from app_info import APP_NAME, APP_REPOSITORY, APP_VERSION, MAIN_EXECUTABLE
from process_utils import app_base_dir


_VERSION_RE = re.compile(r"\d+(?:\.\d+){0,3}")
_PROCESS_NAMES = ("BandoriPet", "pet_process", "settings_process", "chat_process")


@dataclass
class UpdateInfo:
    channel: str
    current_version: str = APP_VERSION
    latest_version: str = ""
    update_available: bool = False
    can_update: bool = False
    action: str = ""
    summary: str = ""
    detail: str = ""
    release_url: str = ""
    download_url: str = ""
    asset_name: str = ""
    asset_size: int = 0
    commits_behind: int = 0


@dataclass
class UpdateResult:
    success: bool
    message: str
    requires_restart: bool = False
    exits_app: bool = False


def detect_update_channel() -> str:
    base_dir = app_base_dir()
    if not getattr(sys, "frozen", False):
        return "source" if _is_git_repo(base_dir) else "source_unmanaged"
    if sys.platform == "win32" and _looks_like_msi_install(base_dir):
        return "msi"
    return "portable"


def check_for_updates() -> UpdateInfo:
    channel = detect_update_channel()
    if channel == "source":
        return _check_git_update(app_base_dir())
    if channel == "source_unmanaged":
        return UpdateInfo(
            channel=channel,
            summary="This source folder is not a Git repository.",
            detail="Download a fresh release package, or use git clone to enable one-click source updates.",
        )
    return _check_release_update(channel)


def apply_update(info: UpdateInfo) -> UpdateResult:
    if info.action == "git_pull":
        return _apply_git_update(app_base_dir())
    if info.action == "portable_zip":
        archive_path = _download_asset(info.download_url, info.asset_name)
        _launch_portable_zip_updater(archive_path)
        return UpdateResult(
            True,
            "The updater has started. BandoriPet will close, copy the new files, and restart.",
            requires_restart=True,
            exits_app=True,
        )
    if info.action == "install_msi":
        installer_path = _download_asset(info.download_url, info.asset_name)
        _launch_msi_updater(installer_path)
        return UpdateResult(
            True,
            "The installer has started. BandoriPet will close and reopen after installation.",
            requires_restart=True,
            exits_app=True,
        )
    raise RuntimeError("No update action is available for this release.")


def _version_tuple(value: str) -> tuple[int, ...] | None:
    match = _VERSION_RE.search(value or "")
    if not match:
        return None
    parts = tuple(int(part) for part in match.group(0).split("."))
    return parts + (0,) * (4 - len(parts))


def _is_newer_version(latest: str, current: str) -> bool:
    latest_tuple = _version_tuple(latest)
    current_tuple = _version_tuple(current)
    if latest_tuple is not None and current_tuple is not None:
        return latest_tuple > current_tuple
    return bool(latest and latest.strip().lstrip("v") != current.strip().lstrip("v"))


def _hidden_subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _run_git(args: list[str], cwd: Path, timeout: int = 60) -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git was not found in PATH.")
    proc = subprocess.run(
        [git, *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_hidden_subprocess_kwargs(),
    )
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "git command failed").strip()
        raise RuntimeError(message)
    return proc.stdout.strip()


def _is_git_repo(path: Path) -> bool:
    try:
        _run_git(["rev-parse", "--is-inside-work-tree"], path, timeout=10)
        return True
    except Exception:
        return False


def _git_upstream(cwd: Path) -> str:
    try:
        upstream = _run_git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            cwd,
            timeout=10,
        )
        if upstream:
            return upstream
    except Exception:
        pass

    branch = _run_git(["branch", "--show-current"], cwd, timeout=10)
    if branch:
        return f"origin/{branch}"

    try:
        return _run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd, timeout=10)
    except Exception as exc:
        raise RuntimeError("No upstream branch is configured for this Git checkout.") from exc


def _check_git_update(cwd: Path) -> UpdateInfo:
    upstream = _git_upstream(cwd)
    remote = upstream.split("/", 1)[0] if "/" in upstream else "origin"
    _run_git(["fetch", "--tags", "--prune", remote], cwd, timeout=120)

    behind_text = _run_git(["rev-list", "--count", f"HEAD..{upstream}"], cwd, timeout=30)
    commits_behind = int(behind_text or "0")
    current_commit = _run_git(["rev-parse", "--short", "HEAD"], cwd, timeout=10)
    latest_commit = _run_git(["rev-parse", "--short", upstream], cwd, timeout=10)
    dirty = bool(_run_git(["status", "--porcelain", "--untracked-files=no"], cwd, timeout=10))
    update_available = commits_behind > 0

    detail = ""
    can_update = update_available and not dirty
    if dirty and update_available:
        detail = "Tracked files have local changes. Commit, stash, or discard them before one-click update."
    elif update_available:
        detail = f"{commits_behind} new commit(s) are available from {upstream}."

    return UpdateInfo(
        channel="source",
        latest_version=f"{upstream}@{latest_commit}",
        update_available=update_available,
        can_update=can_update,
        action="git_pull" if can_update else "",
        summary=f"Current commit {current_commit}; latest {latest_commit}.",
        detail=detail,
        commits_behind=commits_behind,
    )


def _apply_git_update(cwd: Path) -> UpdateResult:
    upstream = _git_upstream(cwd)
    remote = upstream.split("/", 1)[0] if "/" in upstream else "origin"
    branch = upstream.split("/", 1)[1] if "/" in upstream else upstream
    _run_git(["pull", "--ff-only", remote, branch], cwd, timeout=180)

    requirements = cwd / "requirements.txt"
    if requirements.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=True,
            **_hidden_subprocess_kwargs(),
        )

    return UpdateResult(
        True,
        "Source checkout updated. Restart BandoriPet to run the new version.",
        requires_restart=True,
    )


def _check_release_update(channel: str) -> UpdateInfo:
    release = _fetch_latest_release()
    latest_version = str(release.get("tag_name") or release.get("name") or "").strip()
    release_url = str(release.get("html_url") or "")
    update_available = _is_newer_version(latest_version, APP_VERSION)

    info = UpdateInfo(
        channel=channel,
        latest_version=latest_version,
        update_available=update_available,
        release_url=release_url,
        summary=str(release.get("name") or latest_version or "Latest release"),
        detail=str(release.get("body") or "").strip(),
    )
    if not update_available:
        return info

    asset = _select_release_asset(release.get("assets", []), channel)
    if asset is None:
        info.detail = (
            "A newer release exists, but no matching installer asset was found. "
            "Publish a .zip portable package or .msi installer in the latest GitHub Release."
        )
        return info

    info.asset_name = str(asset.get("name") or "")
    info.asset_size = int(asset.get("size") or 0)
    info.download_url = str(asset.get("browser_download_url") or "")
    info.action = _asset_action(info.asset_name, channel)
    info.can_update = bool(info.download_url and info.action)
    return info


def _fetch_latest_release() -> dict:
    url = f"https://api.github.com/repos/{APP_REPOSITORY}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(f"No GitHub Release was found for {APP_REPOSITORY}.") from exc
        raise


def _select_release_asset(assets: list[dict], channel: str) -> dict | None:
    candidates: list[tuple[int, dict]] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        lower = name.lower()
        if not str(asset.get("browser_download_url") or ""):
            continue
        if channel == "msi":
            if not lower.endswith(".msi"):
                continue
        elif channel == "portable":
            if not lower.endswith(".zip") and not lower.endswith(".msi"):
                continue
        else:
            continue

        score = 0
        if "bandoripet" in lower or "bandori-pet" in lower:
            score += 8
        if _platform_token() in lower or "win" in lower:
            score += 4
        if _arch_token() in lower:
            score += 3
        if lower.endswith(".zip") and channel == "portable":
            score += 6
        if lower.endswith(".msi"):
            score += 5 if channel == "msi" else 1
        candidates.append((score, asset))

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def _asset_action(asset_name: str, channel: str) -> str:
    lower = asset_name.lower()
    if lower.endswith(".msi"):
        return "install_msi"
    if lower.endswith(".zip") and channel == "portable":
        return "portable_zip"
    return ""


def _platform_token() -> str:
    if sys.platform == "win32":
        return "win"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform.lower()


def _arch_token() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86", "i386", "i686"}:
        return "x86"
    return machine


def _download_asset(url: str, asset_name: str) -> Path:
    if not url:
        raise RuntimeError("Release asset URL is empty.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", asset_name or "BandoriPet-update")
    download_dir = Path(tempfile.gettempdir()) / "BandoriPetUpdate"
    download_dir.mkdir(parents=True, exist_ok=True)
    target = download_dir / safe_name
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(target, "wb") as f:
        shutil.copyfileobj(resp, f)
    return target


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _write_update_script(name: str, body: str) -> Path:
    script_dir = Path(tempfile.gettempdir()) / "BandoriPetUpdate"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / f"{name}-{uuid.uuid4().hex}.ps1"
    script_path.write_text(body, encoding="utf-8")
    return script_path


def _launch_powershell_script(script_path: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Automatic packaged updates are currently supported on Windows only.")
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        cwd=str(app_base_dir()),
        **_hidden_subprocess_kwargs(),
    )


def _launch_portable_zip_updater(archive_path: Path) -> None:
    target_dir = app_base_dir()
    app_exe = target_dir / MAIN_EXECUTABLE
    process_names = ", ".join(_ps_quote(name) for name in _PROCESS_NAMES)
    script = f"""
$ErrorActionPreference = 'Stop'
$zip = {_ps_quote(archive_path)}
$target = {_ps_quote(target_dir)}
$app = {_ps_quote(app_exe)}
$processNames = @({process_names})
$stage = Join-Path ([IO.Path]::GetTempPath()) ('BandoriPetUpdate-' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $stage -Force
$source = $stage
$children = @(Get-ChildItem -LiteralPath $stage -Force)
if ($children.Count -eq 1 -and $children[0].PSIsContainer) {{
    $source = $children[0].FullName
}}
Start-Sleep -Seconds 1
Get-Process -ErrorAction SilentlyContinue |
    Where-Object {{ $processNames -contains $_.ProcessName }} |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Get-ChildItem -LiteralPath $source -Force |
    Copy-Item -Destination $target -Recurse -Force
Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $app) {{
    Start-Process -FilePath $app -WorkingDirectory $target
}}
"""
    _launch_powershell_script(_write_update_script("apply-portable", script))


def _launch_msi_updater(installer_path: Path) -> None:
    target_dir = app_base_dir()
    app_exe = target_dir / MAIN_EXECUTABLE
    process_names = ", ".join(_ps_quote(name) for name in _PROCESS_NAMES)
    args = f'/i "{installer_path}" /passive /norestart'
    script = f"""
$ErrorActionPreference = 'Stop'
$installer = {_ps_quote(installer_path)}
$target = {_ps_quote(target_dir)}
$app = {_ps_quote(app_exe)}
$processNames = @({process_names})
Start-Sleep -Seconds 1
Get-Process -ErrorAction SilentlyContinue |
    Where-Object {{ $processNames -contains $_.ProcessName }} |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Process -FilePath 'msiexec.exe' -ArgumentList {_ps_quote(args)} -Wait
if (Test-Path -LiteralPath $app) {{
    Start-Process -FilePath $app -WorkingDirectory $target
}}
"""
    _launch_powershell_script(_write_update_script("apply-msi", script))


def _looks_like_msi_install(base_dir: Path) -> bool:
    if _registry_points_to_install(base_dir):
        return True
    base = str(base_dir.resolve()).lower()
    installer_roots = [
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs") if os.environ.get("LOCALAPPDATA") else "",
    ]
    return any(root and base.startswith(str(Path(root).resolve()).lower()) for root in installer_roots)


def _registry_points_to_install(base_dir: Path) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except Exception:
        return False

    uninstall_paths = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    base = str(base_dir.resolve()).lower()
    for hive in hives:
        for root_path in uninstall_paths:
            try:
                with winreg.OpenKey(hive, root_path) as root:
                    subkey_count = winreg.QueryInfoKey(root)[0]
                    for index in range(subkey_count):
                        try:
                            subkey_name = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, subkey_name) as subkey:
                                display_name = _reg_value(winreg, subkey, "DisplayName")
                                if display_name and APP_NAME.lower() not in display_name.lower():
                                    continue
                                install_location = _reg_value(winreg, subkey, "InstallLocation")
                                display_icon = _reg_value(winreg, subkey, "DisplayIcon")
                                if _path_matches_base(install_location, base) or _path_matches_base(display_icon, base):
                                    return True
                        except OSError:
                            continue
            except OSError:
                continue
    return False


def _reg_value(winreg, key, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
        return str(value or "")
    except OSError:
        return ""


def _path_matches_base(value: str, base: str) -> bool:
    if not value:
        return False
    candidate = value.strip('"').split(",", 1)[0]
    try:
        candidate_path = Path(candidate).resolve()
    except OSError:
        return False
    candidate_text = str(candidate_path).lower()
    return candidate_text == base or candidate_text.startswith(base + os.sep)
