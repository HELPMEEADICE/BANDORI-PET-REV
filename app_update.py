import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from app_info import APP_NAME, APP_REPOSITORY, APP_VERSION, MAIN_EXECUTABLE
from process_utils import app_base_dir, hidden_subprocess_kwargs, log_swallowed


_VERSION_RE = re.compile(r"\d+(?:\.\d+){0,3}")
_PROCESS_NAMES = (
    APP_NAME,
    "pet_process",
    "radial_menu_process",
    "settings_process",
    "chat_process",
    "bandori-ai-event",
    "bandori-codex-runner",
)
_PORTABLE_UPDATE_PROTECTED_FILES = (
    "config.json",
    "data.db",
    "data.db-shm",
    "data.db-wal",
)


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
    asset_sha256: str = ""
    commits_behind: int = 0
    commits_ahead: int = 0


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
    if sys.platform == "darwin":
        return "macos_app"
    if sys.platform == "win32":
        install_type = _detect_windows_install_type(base_dir)
        if install_type:
            return install_type
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
        archive_path = _download_asset(
            info.download_url,
            info.asset_name,
            info.asset_size,
            info.asset_sha256,
        )
        _launch_portable_zip_updater(archive_path)
        return UpdateResult(
            True,
            "The updater has started. BandoriPet will close, copy the new files, and restart.",
            requires_restart=True,
            exits_app=True,
        )
    if info.action == "install_msi":
        installer_path = _download_asset(
            info.download_url,
            info.asset_name,
            info.asset_size,
            info.asset_sha256,
        )
        _launch_msi_updater(installer_path)
        return UpdateResult(
            True,
            "The installer has started. BandoriPet will close and reopen after installation.",
            requires_restart=True,
            exits_app=True,
        )
    if info.action == "install_inno":
        installer_path = _download_asset(
            info.download_url,
            info.asset_name,
            info.asset_size,
            info.asset_sha256,
        )
        _launch_inno_updater(installer_path)
        return UpdateResult(
            True,
            "The installer has started. BandoriPet will close and reopen after installation.",
            requires_restart=True,
            exits_app=True,
        )
    if info.action == "install_macos":
        package_path = _download_asset(
            info.download_url,
            info.asset_name,
            info.asset_size,
            info.asset_sha256,
        )
        _launch_macos_updater(package_path)
        return UpdateResult(
            True,
            "The macOS updater has started. BandoriPet will close, replace the app, and restart.",
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


def _git_env() -> dict:
    env = os.environ.copy()
    # The update check runs in a hidden, console-less subprocess. Without these,
    # git can block forever waiting for credential or terminal input (for example
    # when the remote was switched to a private fork or cached credentials have
    # expired), which makes the version check hang until it times out instead of
    # failing fast with a useful message.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GCM_INTERACTIVE", "Never")
    env.setdefault("GIT_ASKPASS", "")
    env.setdefault("SSH_ASKPASS", "")
    return env


def _run_git(args: list[str], cwd: Path, timeout: int = 60) -> str:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git was not found in PATH.")
    try:
        proc = subprocess.run(
            [git, *args],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_git_env(),
            **hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"git {args[0]} timed out after {timeout}s. "
            "Check your network connection or proxy settings."
        ) from exc
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


def _ref_exists(cwd: Path, ref: str) -> bool:
    try:
        _run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd, timeout=10)
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
        # An upstream that tracks a local branch (no remote prefix) cannot tell us
        # whether the remote has new commits, so fall through to the remote refs.
        if upstream and "/" in upstream:
            return upstream
    except Exception as exc:
        log_swallowed("app_update.resolve_upstream", exc)

    branch = _run_git(["branch", "--show-current"], cwd, timeout=10)
    if branch and _ref_exists(cwd, f"origin/{branch}"):
        return f"origin/{branch}"

    try:
        head = _run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd, timeout=10)
        if head and _ref_exists(cwd, head):
            return head
    except Exception as exc:
        log_swallowed("app_update.resolve_origin_head", exc)

    raise RuntimeError(
        "No remote-tracking branch was found for this Git checkout. "
        "Set an upstream with: git branch --set-upstream-to=origin/<branch>"
    )


def _check_git_update(cwd: Path) -> UpdateInfo:
    upstream = _git_upstream(cwd)
    remote = upstream.split("/", 1)[0] if "/" in upstream else "origin"
    _run_git(["fetch", "--tags", "--prune", remote], cwd, timeout=120)

    counts = _run_git(["rev-list", "--left-right", "--count", f"HEAD...{upstream}"], cwd, timeout=30)
    parts = counts.split()
    if len(parts) != 2:
        raise RuntimeError(f"Git returned an unexpected revision count: {counts!r}")
    commits_ahead, commits_behind = (int(part) for part in parts)
    current_commit = _run_git(["rev-parse", "--short", "HEAD"], cwd, timeout=10)
    latest_commit = _run_git(["rev-parse", "--short", upstream], cwd, timeout=10)
    dirty = bool(_run_git(["status", "--porcelain", "--untracked-files=no"], cwd, timeout=10))
    update_available = commits_behind > 0

    detail = ""
    can_update = update_available and not dirty and commits_ahead == 0
    if dirty and update_available:
        detail = "Tracked files have local changes. Commit, stash, or discard them before one-click update."
    elif commits_ahead and update_available:
        detail = (
            f"This checkout and {upstream} have diverged "
            f"({commits_ahead} local, {commits_behind} remote commit(s)). "
            "Resolve the branch manually before updating."
        )
    elif update_available:
        detail = f"{commits_behind} new commit(s) are available from {upstream}."
    elif commits_ahead:
        detail = f"This checkout is {commits_ahead} commit(s) ahead of {upstream}; no remote update is available."

    return UpdateInfo(
        channel="source",
        latest_version=f"{upstream}@{latest_commit}",
        update_available=update_available,
        can_update=can_update,
        action="git_pull" if can_update else "",
        summary=f"Current commit {current_commit}; latest {latest_commit}.",
        detail=detail,
        commits_behind=commits_behind,
        commits_ahead=commits_ahead,
    )


def _apply_git_update(cwd: Path) -> UpdateResult:
    upstream = _git_upstream(cwd)
    remote = upstream.split("/", 1)[0] if "/" in upstream else "origin"
    branch = upstream.split("/", 1)[1] if "/" in upstream else upstream
    old_commit = _run_git(["rev-parse", "HEAD"], cwd, timeout=10)
    _run_git(["pull", "--ff-only", remote, branch], cwd, timeout=180)
    new_commit = _run_git(["rev-parse", "HEAD"], cwd, timeout=10)

    requirements = cwd / "requirements.txt"
    requirements_changed = bool(
        old_commit != new_commit
        and _run_git(
            ["diff", "--name-only", old_commit, new_commit, "--", "requirements.txt"],
            cwd,
            timeout=30,
        )
    )
    if requirements.exists() and requirements_changed:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements),
            ],
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=True,
            **hidden_subprocess_kwargs(),
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
            "Publish a Windows .zip/.exe/.msi or macOS .dmg/.zip asset "
            "for the current platform and architecture."
        )
        return info

    info.asset_name = str(asset.get("name") or "")
    info.asset_size = int(asset.get("size") or 0)
    info.download_url = str(asset.get("browser_download_url") or "")
    info.action = _asset_action(info.asset_name, channel)
    info.asset_sha256 = _release_asset_sha256(asset, release.get("assets", []))
    info.can_update = bool(
        info.download_url
        and info.action
        and info.asset_sha256
    )
    if info.download_url and info.action and not info.asset_sha256:
        info.detail = (
            (info.detail + "\n\n") if info.detail else ""
        ) + (
            "Automatic update is disabled because this release does not provide "
            "a SHA-256 digest or checksum file for the selected asset."
        )
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
        with _open_url(req, timeout=20, purpose="checking for updates") as resp:
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
        if not _asset_matches_current_platform(lower):
            continue
        if channel == "msi":
            if not lower.endswith(".msi"):
                continue
        elif channel == "inno":
            if not lower.endswith(".exe"):
                continue
        elif channel == "macos_app":
            if not lower.endswith((".dmg", ".zip")):
                continue
        elif channel == "portable":
            if not lower.endswith(".zip") and not lower.endswith(".msi"):
                continue
        else:
            continue
        if not _asset_matches_current_arch(lower):
            continue

        score = 0
        if "bandoripet" in lower or "bandori-pet" in lower:
            score += 8
        if _platform_token() in lower or "win" in lower:
            score += 4
        if _asset_arch(lower) == _current_arch():
            score += 3
        if lower.endswith(".zip") and channel == "portable":
            score += 6
        if lower.endswith(".msi"):
            score += 5 if channel == "msi" else 1
        if lower.endswith(".exe") and channel == "inno":
            score += 5
            if "setup" in lower or "installer" in lower:
                score += 2
        if lower.endswith(".dmg") and channel == "macos_app":
            score += 7
        if lower.endswith(".zip") and channel == "macos_app":
            score += 3
        candidates.append((score, asset))

    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def _asset_action(asset_name: str, channel: str) -> str:
    lower = asset_name.lower()
    if lower.endswith(".msi"):
        return "install_msi"
    if lower.endswith(".exe") and channel == "inno":
        return "install_inno"
    if lower.endswith(".zip") and channel == "portable":
        return "portable_zip"
    if lower.endswith((".dmg", ".zip")) and channel == "macos_app":
        return "install_macos"
    return ""


def _platform_token() -> str:
    if sys.platform == "win32":
        return "win"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform.lower()


def _current_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        return "amd64"
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    return machine


def _asset_arch(name: str) -> str:
    lower = name.lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", lower).strip("-")
    tokens = set(normalized.split("-"))
    if {"arm64", "aarch64"} & tokens:
        return "arm64"
    if (
        {"amd64", "x64", "win64", "winamd64"} & tokens
        or "x86_64" in lower
        or "x86-64" in normalized
    ):
        return "amd64"
    if {"x86", "i386", "i686", "win32"} & tokens:
        return "unsupported-x86"
    return ""


def _asset_matches_current_arch(name: str) -> bool:
    asset_arch = _asset_arch(name)
    return not asset_arch or asset_arch == _current_arch()


def _asset_platforms(name: str) -> set[str]:
    tokens = [token for token in re.split(r"[^a-z0-9]+", name.lower()) if token]
    platforms: set[str] = set()
    for token in tokens:
        if token.startswith("win") or token == "windows":
            platforms.add("win")
        if token.startswith("mac") or token in {"osx", "darwin"}:
            platforms.add("mac")
        if token.startswith("linux"):
            platforms.add("linux")
    return platforms


def _asset_matches_current_platform(name: str) -> bool:
    platforms = _asset_platforms(name)
    return not platforms or _platform_token() in platforms


def _direct_url_opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=_ssl_context()),
    ).open


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except Exception as exc:
        log_swallowed("app_update.load_certifi", exc)
    return context


def _open_url(req: urllib.request.Request, timeout: int, purpose: str):
    proxies = urllib.request.getproxies()
    proxy_url = proxies.get("https") or proxies.get("http")
    context = _ssl_context()
    attempts = [
        (
            "configured network path",
            lambda request, timeout: urllib.request.urlopen(
                request,
                timeout=timeout,
                context=context,
            ),
        )
    ]
    if proxy_url:
        attempts.append(("direct connection", _direct_url_opener()))

    failures: list[str] = []
    for label, opener in attempts:
        try:
            return opener(req, timeout=timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            failures.append(f"{label}: {exc}")

    proxy_hint = f" The configured proxy is {proxy_url}." if proxy_url else ""
    detail = "; ".join(failures)
    raise RuntimeError(
        f"Network error while {purpose}.{proxy_hint} "
        f"Check that the proxy is running or disable the stale system proxy, then retry. {detail}"
    )


def _normalize_sha256(value: str) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1].strip()
    return text if re.fullmatch(r"[0-9a-f]{64}", text) else ""


def _release_asset_sha256(asset: dict, assets: list[dict]) -> str:
    digest = _normalize_sha256(asset.get("digest", ""))
    if digest:
        return digest

    asset_name = str(asset.get("name") or "")
    checksum_asset = _select_checksum_asset(asset_name, assets)
    if checksum_asset is None:
        return ""
    url = str(checksum_asset.get("browser_download_url") or "")
    if not url:
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    try:
        with _open_url(req, timeout=20, purpose="downloading the update checksum") as resp:
            content = resp.read(1024 * 1024 + 1)
    except (RuntimeError, urllib.error.URLError, urllib.error.HTTPError, OSError):
        return ""
    if len(content) > 1024 * 1024:
        return ""
    return _parse_checksum_file(content.decode("utf-8", errors="replace"), asset_name)


def _select_checksum_asset(asset_name: str, assets: list[dict]) -> dict | None:
    exact_names = {
        f"{asset_name}.sha256".lower(),
        f"{asset_name}.sha256sum".lower(),
    }
    manifest_names = {
        "sha256sums",
        "sha256sums.txt",
        "checksums.txt",
        "checksum.txt",
    }
    fallback = None
    for candidate in assets:
        name = str(candidate.get("name") or "").strip().lower()
        if not candidate.get("browser_download_url"):
            continue
        if name in exact_names:
            return candidate
        if name in manifest_names:
            fallback = candidate
    return fallback


def _parse_checksum_file(content: str, asset_name: str) -> str:
    target_name = Path(asset_name).name
    single_digest = ""
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([0-9a-fA-F]{64})(?:\s+[*]?(.+?))?\s*$", line)
        if not match:
            continue
        digest = match.group(1).lower()
        listed_name = (match.group(2) or "").strip()
        if listed_name and Path(listed_name).name == target_name:
            return digest
        if not listed_name:
            single_digest = digest
    return single_digest


def _download_asset(
    url: str,
    asset_name: str,
    expected_size: int = 0,
    expected_sha256: str = "",
) -> Path:
    if not url:
        raise RuntimeError("Release asset URL is empty.")
    expected_digest = _normalize_sha256(expected_sha256)
    if not expected_digest:
        raise RuntimeError("Release asset SHA-256 checksum is missing or invalid.")
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", asset_name or "BandoriPet-update")
    download_dir = Path(tempfile.gettempdir()) / "BandoriPetUpdate"
    download_dir.mkdir(parents=True, exist_ok=True)
    target = download_dir / safe_name
    partial = target.with_name(f"{target.name}.part")
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    try:
        with (
            _open_url(req, timeout=30, purpose="downloading the update") as resp,
            open(partial, "wb") as f,
        ):
            digest = hashlib.sha256()
            while chunk := resp.read(1024 * 1024):
                f.write(chunk)
                digest.update(chunk)
        actual_size = partial.stat().st_size
        if expected_size > 0 and actual_size != expected_size:
            raise RuntimeError(
                f"The update download is incomplete: expected {expected_size} bytes, "
                f"received {actual_size} bytes."
            )
        actual_digest = digest.hexdigest()
        if actual_digest != expected_digest:
            raise RuntimeError(
                "The update download failed SHA-256 verification: "
                f"expected {expected_digest}, received {actual_digest}."
            )
        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
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
        **hidden_subprocess_kwargs(),
    )


def _launch_portable_zip_updater(archive_path: Path) -> None:
    target_dir = app_base_dir()
    app_exe = target_dir / MAIN_EXECUTABLE
    process_names = ", ".join(_ps_quote(name) for name in _PROCESS_NAMES)
    protected_files = ", ".join(_ps_quote(name) for name in _PORTABLE_UPDATE_PROTECTED_FILES)
    script = f"""
$ErrorActionPreference = 'Stop'
$zip = {_ps_quote(archive_path)}
$target = {_ps_quote(target_dir)}
$app = {_ps_quote(app_exe)}
$processNames = @({process_names})
$protectedFiles = @({protected_files})
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
    Where-Object {{ -not ($protectedFiles -contains $_.Name) }} |
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
    log_path = installer_path.with_suffix(".install.log")
    args = f'/i "{installer_path}" /passive /norestart /L*v "{log_path}"'
    script = f"""
$ErrorActionPreference = 'Stop'
$installer = {_ps_quote(installer_path)}
$target = {_ps_quote(target_dir)}
$app = {_ps_quote(app_exe)}
$log = {_ps_quote(log_path)}
$processNames = @({process_names})
try {{
    Start-Sleep -Seconds 1
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {{ $processNames -contains $_.ProcessName }} |
        Stop-Process -Force -ErrorAction SilentlyContinue
    $installerProcess = Start-Process -FilePath 'msiexec.exe' -ArgumentList {_ps_quote(args)} -Verb RunAs -Wait -PassThru
    if (@(0, 1641, 3010) -notcontains $installerProcess.ExitCode) {{
        throw "MSI installer exited with code $($installerProcess.ExitCode)."
    }}
    if (Test-Path -LiteralPath $app) {{
        Start-Process -FilePath $app -WorkingDirectory $target
    }}
}} catch {{
    $message = "BandoriPet update failed: $($_.Exception.Message)`nInstaller log: $log"
    $message | Out-File -LiteralPath $log -Append -Encoding utf8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($message, 'BandoriPet Update', 'OK', 'Error') | Out-Null
    if (Test-Path -LiteralPath $app) {{
        Start-Process -FilePath $app -WorkingDirectory $target
    }}
}}
"""
    _launch_powershell_script(_write_update_script("apply-msi", script))


def _launch_inno_updater(installer_path: Path) -> None:
    target_dir = app_base_dir()
    app_exe = target_dir / MAIN_EXECUTABLE
    process_names = ", ".join(_ps_quote(name) for name in _PROCESS_NAMES)
    log_path = installer_path.with_suffix(".install.log")
    args = f'/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /LOG="{log_path}"'
    script = f"""
$ErrorActionPreference = 'Stop'
$installer = {_ps_quote(installer_path)}
$target = {_ps_quote(target_dir)}
$app = {_ps_quote(app_exe)}
$log = {_ps_quote(log_path)}
$processNames = @({process_names})
try {{
    Start-Sleep -Seconds 1
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object {{ $processNames -contains $_.ProcessName }} |
        Stop-Process -Force -ErrorAction SilentlyContinue
    $startArgs = @{{
        FilePath = $installer
        ArgumentList = {_ps_quote(args)}
        Wait = $true
        PassThru = $true
    }}
    if ($target.StartsWith($env:ProgramFiles, [StringComparison]::OrdinalIgnoreCase)) {{
        $startArgs.Verb = 'RunAs'
    }}
    $installerProcess = Start-Process @startArgs
    if (@(0, 1641, 3010) -notcontains $installerProcess.ExitCode) {{
        throw "EXE installer exited with code $($installerProcess.ExitCode)."
    }}
    if (Test-Path -LiteralPath $app) {{
        Start-Process -FilePath $app -WorkingDirectory $target
    }}
}} catch {{
    $message = "BandoriPet update failed: $($_.Exception.Message)`nInstaller log: $log"
    $message | Out-File -LiteralPath $log -Append -Encoding utf8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($message, 'BandoriPet Update', 'OK', 'Error') | Out-Null
    if (Test-Path -LiteralPath $app) {{
        Start-Process -FilePath $app -WorkingDirectory $target
    }}
}}
"""
    _launch_powershell_script(_write_update_script("apply-inno", script))


def _mac_app_bundle() -> Path:
    executable = Path(sys.executable).resolve()
    for candidate in (executable, *executable.parents):
        if candidate.suffix.lower() == ".app":
            return candidate
    raise RuntimeError("BandoriPet is not running from a macOS .app bundle.")


def _launch_macos_updater(package_path: Path) -> None:
    if sys.platform != "darwin":
        raise RuntimeError("The macOS updater can only run on macOS.")

    target_app = _mac_app_bundle()
    script_dir = Path(tempfile.gettempdir()) / "BandoriPetUpdate"
    script_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    helper_path = script_dir / f"apply-macos-helper-{token}.sh"
    launcher_path = script_dir / f"apply-macos-{token}.sh"
    log_path = script_dir / f"apply-macos-{token}.log"
    process_names = " ".join(shlex.quote(name) for name in _PROCESS_NAMES)

    helper = f"""#!/bin/zsh
set -euo pipefail
package={shlex.quote(str(package_path))}
target={shlex.quote(str(target_app))}
work_dir="$(mktemp -d "${{TMPDIR:-/tmp}}/BandoriPetUpdate.XXXXXX")"
mount_dir=""
stage="${{target}}.update-stage-$$"
backup="${{target}}.update-backup-$$"
success=0

move_user_data() {{
    local source_root="$1"
    local destination_root="$2"
    local item relative destination
    setopt local_options null_glob
    local user_items=(
        "$source_root/Contents/MacOS"/config.json*
        "$source_root/Contents/MacOS"/data.db*
        "$source_root/Contents/MacOS"/models
        "$source_root/Contents/MacOS"/chat_attachments
        "$source_root/Contents/MacOS"/*.log
    )
    for item in "${{user_items[@]}}"; do
        [[ -e "$item" ]] || continue
        relative="${{item#$source_root/}}"
        destination="$destination_root/$relative"
        /bin/mkdir -p "${{destination:h}}"
        /bin/rm -rf "$destination"
        /bin/mv "$item" "$destination"
    done
}}

cleanup() {{
    if [[ -n "$mount_dir" ]]; then
        /usr/bin/hdiutil detach "$mount_dir" -quiet >/dev/null 2>&1 || true
    fi
    /bin/rm -rf "$work_dir"
    if [[ "$success" -ne 1 && -d "$backup" ]]; then
        if [[ -d "$target" ]]; then
            move_user_data "$target" "$backup" || true
        fi
        /bin/rm -rf "$target"
        /bin/mv "$backup" "$target"
    elif [[ "$success" -ne 1 ]]; then
        /bin/rm -rf "$target"
    fi
    /bin/rm -rf "$stage"
}}
trap cleanup EXIT

case "$package" in
    *.dmg)
        mount_dir="$work_dir/mount"
        /bin/mkdir -p "$mount_dir"
        /usr/bin/hdiutil attach "$package" -nobrowse -readonly -mountpoint "$mount_dir" -quiet
        source_root="$mount_dir"
        ;;
    *.zip)
        source_root="$work_dir/archive"
        /bin/mkdir -p "$source_root"
        /usr/bin/ditto -x -k "$package" "$source_root"
        ;;
    *)
        echo "Unsupported macOS update package: $package" >&2
        exit 2
        ;;
esac

source_app="$(/usr/bin/find "$source_root" -maxdepth 3 -type d -name '{APP_NAME}.app' -print -quit)"
if [[ -z "$source_app" ]]; then
    echo "{APP_NAME}.app was not found in the update package." >&2
    exit 3
fi

for process_name in {process_names}; do
    /usr/bin/pkill -x "$process_name" >/dev/null 2>&1 || true
done
/bin/sleep 2

/bin/rm -rf "$stage" "$backup"
/usr/bin/ditto "$source_app" "$stage"
if [[ -d "$target" ]]; then
    /bin/mv "$target" "$backup"
fi
/bin/mv "$stage" "$target"
if [[ -d "$backup" ]]; then
    move_user_data "$backup" "$target"
fi
/usr/bin/xattr -dr com.apple.quarantine "$target" >/dev/null 2>&1 || true
/usr/bin/codesign --force --deep --sign - "$target"
/usr/bin/codesign --verify --deep --strict "$target"
success=1
/bin/rm -rf "$backup"
"""
    launcher = f"""#!/bin/zsh
helper={shlex.quote(str(helper_path))}
target={shlex.quote(str(target_app))}
log={shlex.quote(str(log_path))}
/bin/sleep 2

if [[ -w "$target" && -w "${{target:h}}" ]]; then
    /bin/zsh "$helper" >>"$log" 2>&1
    status=$?
else
    /usr/bin/osascript - "$helper" "$log" <<'APPLESCRIPT'
on run argv
    set helperPath to item 1 of argv
    set logPath to item 2 of argv
    do shell script "/bin/zsh " & quoted form of helperPath & " >> " & quoted form of logPath & " 2>&1" with administrator privileges
end run
APPLESCRIPT
    status=$?
fi

if [[ "$status" -eq 0 ]]; then
    /usr/bin/open "$target"
else
    /usr/bin/osascript -e 'display alert "BandoriPet update failed" message "The app was restored. See the updater log for details: {str(log_path).replace(chr(34), '')}" as critical'
fi
"""
    helper_path.write_text(helper, encoding="utf-8")
    launcher_path.write_text(launcher, encoding="utf-8")
    helper_path.chmod(0o700)
    launcher_path.chmod(0o700)
    subprocess.Popen(
        ["/bin/zsh", str(launcher_path)],
        cwd=str(script_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _detect_windows_install_type(base_dir: Path) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except Exception:
        return ""

    base = str(base_dir.resolve()).lower()
    marker_type = _registry_marker_install_type(winreg, base)
    if marker_type:
        return marker_type

    uninstall_paths = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
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
                                inno_app_path = _reg_value(winreg, subkey, "Inno Setup: App Path")
                                if not (
                                    _path_matches_base(install_location, base)
                                    or _path_matches_base(display_icon, base)
                                    or _path_matches_base(inno_app_path, base)
                                ):
                                    continue
                                return _registry_entry_install_type(winreg, subkey, subkey_name)
                        except OSError:
                            continue
            except OSError:
                continue
    return ""


def _registry_marker_install_type(winreg, base: str) -> str:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"Software\{APP_NAME}") as key:
                install_dir = _reg_value(winreg, key, "InstallDir")
                if not install_dir or not _path_matches_base(install_dir, base):
                    continue
                install_type = _normalize_install_type(_reg_value(winreg, key, "InstallerType"))
                if install_type:
                    return install_type
        except OSError:
            continue
    return ""


def _registry_entry_install_type(winreg, subkey, subkey_name: str) -> str:
    install_type = _normalize_install_type(_reg_value(winreg, subkey, "InstallerType"))
    if install_type:
        return install_type

    uninstall = _reg_value(winreg, subkey, "UninstallString").lower()
    quiet_uninstall = _reg_value(winreg, subkey, "QuietUninstallString").lower()
    windows_installer = _reg_value(winreg, subkey, "WindowsInstaller")
    if windows_installer == "1" or "msiexec" in uninstall or "msiexec" in quiet_uninstall:
        return "msi"

    if _reg_value(winreg, subkey, "Inno Setup: App Path"):
        return "inno"
    if "unins" in uninstall and ".exe" in uninstall:
        return "inno"
    if re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", subkey_name):
        return "msi"
    return "inno"


def _normalize_install_type(value: str) -> str:
    lower = (value or "").strip().lower()
    if lower in {"inno", "inno_setup", "inno setup", "exe"}:
        return "inno"
    if lower == "msi":
        return "msi"
    return ""


def _reg_value(winreg, key, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
        return str(value or "")
    except OSError:
        return ""


def _path_matches_base(value: str, base: str) -> bool:
    if not value:
        return False
    match = re.search(r'"([^"]+)"', value)
    candidate = match.group(1) if match else value.split(",", 1)[0].strip()
    try:
        candidate_path = Path(candidate).resolve()
    except OSError:
        return False
    candidate_text = str(candidate_path).lower()
    return candidate_text == base or candidate_text.startswith(base + os.sep)
