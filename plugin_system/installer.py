from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import urllib.parse
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.version import Version

from public_network import open_public_url

from .models import InstallPreview, PluginError, PluginManifest, ScanReport, SignatureInfo
from .paths import PluginPaths, PluginStateStore, plugin_paths
from .scanner import scan_plugin_directory, sha256_directory, sha256_file
from .signing import verify_archive_signature


MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024
MAX_PACKAGE_FILES = 20_000
MAX_UPDATE_DESCRIPTOR_BYTES = 256 * 1024
WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul", "clock$",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _safe_relative_name(raw_name: str) -> str:
    name = unicodedata.normalize("NFC", str(raw_name or "").replace("\\", "/"))
    if not name or "\x00" in name or len(name) > 1024:
        raise PluginError("Plugin package contains an invalid path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PluginError(f"Unsafe path in plugin package: {raw_name!r}")
    for part in path.parts:
        if len(part) > 240 or part.endswith((" ", ".")) or ":" in part:
            raise PluginError(f"Non-portable path in plugin package: {raw_name!r}")
        stem = part.split(".", 1)[0].casefold()
        if stem in WINDOWS_RESERVED_NAMES:
            raise PluginError(f"Reserved filename in plugin package: {raw_name!r}")
    return path.as_posix()


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _permission_changes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    if old == new:
        return {}
    return {"previous": old, "requested": new}


class PluginInstaller:
    def __init__(
        self,
        paths: PluginPaths | None = None,
        state_store: PluginStateStore | None = None,
    ) -> None:
        self.paths = paths or plugin_paths()
        self.state = state_store or PluginStateStore(self.paths)
        self._previews: dict[str, InstallPreview] = {}

    def _new_stage(self) -> Path:
        self.paths.ensure()
        return Path(tempfile.mkdtemp(prefix="install-", dir=str(self.paths.staging)))

    def _validate_archive(self, archive_path: Path) -> tuple[PluginManifest, SignatureInfo]:
        if not archive_path.is_file():
            raise PluginError(f"Plugin package does not exist: {archive_path}")
        if archive_path.stat().st_size > MAX_PACKAGE_BYTES:
            raise PluginError("Plugin package exceeds the 256 MiB compressed limit")
        try:
            archive = zipfile.ZipFile(archive_path)
        except (OSError, zipfile.BadZipFile) as exc:
            raise PluginError(f"Plugin package is not a valid ZIP archive: {exc}") from exc
        with archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            if not files or len(files) > MAX_PACKAGE_FILES:
                raise PluginError("Plugin package has an invalid number of files")
            expanded = 0
            seen: set[str] = set()
            for info in files:
                safe_name = _safe_relative_name(info.filename)
                folded = safe_name.casefold()
                if folded in seen:
                    raise PluginError(f"Duplicate or case-colliding package path: {safe_name}")
                seen.add(folded)
                if _is_zip_symlink(info):
                    raise PluginError(f"Symbolic links are not allowed in plugin packages: {safe_name}")
                if info.file_size < 0 or info.file_size > MAX_SINGLE_FILE_BYTES:
                    raise PluginError(f"Plugin file exceeds the 256 MiB limit: {safe_name}")
                expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise PluginError("Plugin package exceeds the 1 GiB expanded limit")
            try:
                manifest_payload = archive.read("plugin.json")
            except KeyError as exc:
                raise PluginError("Plugin package does not contain plugin.json at its root") from exc
            manifest = PluginManifest.from_bytes(manifest_payload)
            signature = verify_archive_signature(
                archive,
                trusted_fingerprints=self.state.trusted_fingerprints(),
            )
            if signature.invalid:
                raise PluginError(signature.message)
            return manifest, signature

    def _extract_archive(self, archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        root = destination.resolve()
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                safe_name = _safe_relative_name(info.filename)
                target = (destination / Path(*PurePosixPath(safe_name).parts)).resolve()
                if not target.is_relative_to(root):
                    raise PluginError(f"Plugin path escapes staging directory: {safe_name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info, "r") as source, target.open("wb") as output:
                    while True:
                        chunk = source.read(min(1024 * 1024, MAX_SINGLE_FILE_BYTES + 1 - written))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_SINGLE_FILE_BYTES:
                            raise PluginError(f"Plugin file expanded past its limit: {safe_name}")
                        output.write(chunk)

    def _stage_archive(self, archive_path: Path, source: str) -> InstallPreview:
        manifest, signature = self._validate_archive(archive_path)
        stage = self._new_stage()
        payload = stage / "payload"
        try:
            self._extract_archive(archive_path, payload)
            package_hash = sha256_file(archive_path)
            report = scan_plugin_directory(
                payload,
                manifest,
                package_sha256=package_hash,
                signature=signature,
            )
            existing = self.state.plugin(manifest.id)
            changes = _permission_changes(
                existing.get("permissions", {}) if isinstance(existing, dict) else {},
                manifest.permissions,
            )
            token = uuid.uuid4().hex
            preview = InstallPreview(
                token=token,
                staging_path=str(stage),
                source=source,
                manifest=manifest,
                report=report,
                requires_insecure_transport_confirmation=source.lower().startswith("http://"),
                permission_changes=changes,
            )
            self._previews[token] = preview
            return preview
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def stage_local(self, source: str | Path) -> InstallPreview:
        path = Path(source).expanduser().resolve()
        if path.is_dir():
            return self._stage_directory(path)
        return self._stage_archive(path, str(path))

    def _stage_directory(self, source: Path) -> InstallPreview:
        stage = self._new_stage()
        payload = stage / "payload"
        payload.mkdir()
        total = 0
        count = 0
        seen: set[str] = set()
        try:
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise PluginError(f"Symbolic links are not allowed: {path}")
                if not path.is_file():
                    continue
                relative = _safe_relative_name(path.relative_to(source).as_posix())
                if relative.casefold() in seen:
                    raise PluginError(f"Duplicate or case-colliding path: {relative}")
                seen.add(relative.casefold())
                size = path.stat().st_size
                count += 1
                total += size
                if count > MAX_PACKAGE_FILES or size > MAX_SINGLE_FILE_BYTES or total > MAX_EXPANDED_BYTES:
                    raise PluginError("Plugin directory exceeds package safety limits")
                target = payload / Path(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
            manifest_path = payload / "plugin.json"
            if not manifest_path.is_file():
                raise PluginError("Plugin directory does not contain plugin.json")
            manifest = PluginManifest.from_bytes(manifest_path.read_bytes())
            package_hash = sha256_directory(payload)
            signature = SignatureInfo(message="Local plugin directory is unsigned")
            report = scan_plugin_directory(
                payload,
                manifest,
                package_sha256=package_hash,
                signature=signature,
            )
            existing = self.state.plugin(manifest.id)
            token = uuid.uuid4().hex
            preview = InstallPreview(
                token=token,
                staging_path=str(stage),
                source=str(source),
                manifest=manifest,
                report=report,
                permission_changes=_permission_changes(
                    existing.get("permissions", {}) if isinstance(existing, dict) else {},
                    manifest.permissions,
                ),
            )
            self._previews[token] = preview
            return preview
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise

    def stage_url(
        self,
        url: str,
        *,
        allow_insecure_http: bool = False,
        expected_sha256: str = "",
    ) -> InstallPreview:
        parsed = urllib.parse.urlsplit(str(url or "").strip())
        if parsed.scheme.lower() not in {"http", "https"}:
            raise PluginError("Remote plugin URLs must use HTTP or HTTPS")
        if parsed.scheme.lower() == "http" and not allow_insecure_http:
            raise PluginError("HTTP plugin downloads require explicit insecure transport confirmation")
        download_stage = self._new_stage()
        package_path = download_stage / "download.bdplugin"
        try:
            with open_public_url(
                url,
                timeout=20,
                max_redirects=5,
                headers={
                    "Accept": "application/zip, application/octet-stream;q=0.9",
                    "Accept-Encoding": "identity",
                },
            )[0] as response:
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_PACKAGE_BYTES:
                            raise PluginError("Remote plugin exceeds the 256 MiB download limit")
                    except ValueError:
                        pass
                written = 0
                with package_path.open("wb") as output:
                    while True:
                        chunk = response.read(min(1024 * 1024, MAX_PACKAGE_BYTES + 1 - written))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > MAX_PACKAGE_BYTES:
                            raise PluginError("Remote plugin exceeds the 256 MiB download limit")
                        output.write(chunk)
            actual_hash = sha256_file(package_path)
            if expected_sha256 and actual_hash.lower() != expected_sha256.lower().strip():
                raise PluginError("Downloaded plugin SHA-256 does not match the update descriptor")
            return self._stage_archive(package_path, str(url))
        finally:
            shutil.rmtree(download_stage, ignore_errors=True)

    def commit(
        self,
        preview_or_token: InstallPreview | str,
        *,
        enable: bool | None = None,
        trust_publisher: bool = False,
        allow_downgrade: bool = False,
    ) -> dict[str, Any]:
        token = preview_or_token.token if isinstance(preview_or_token, InstallPreview) else str(preview_or_token)
        preview = self._previews.get(token)
        if preview is None:
            raise PluginError("Install preview expired or does not belong to this installer")
        if preview.report.blocked:
            raise PluginError("Plugin cannot be installed because its security report is blocking")
        manifest = preview.manifest
        stage = Path(preview.staging_path).resolve()
        payload = stage / "payload"
        if not payload.is_dir() or not stage.is_relative_to(self.paths.staging.resolve()):
            raise PluginError("Plugin staging directory is invalid")
        current = self.state.plugin(manifest.id)
        current_version = str(current.get("active_version", "") or "")
        if current_version and Version(manifest.version) < Version(current_version) and not allow_downgrade:
            raise PluginError("Plugin downgrade requires explicit confirmation")

        target_parent = self.paths.packages / manifest.id
        target_parent.mkdir(parents=True, exist_ok=True)
        target = target_parent / manifest.version
        if target.exists():
            raise PluginError(f"Plugin version is already installed: {manifest.id} {manifest.version}")
        os.replace(payload, target)

        if trust_publisher and preview.report.signature.valid:
            self.state.trust_publisher(
                preview.report.signature.fingerprint,
                preview.report.signature.publisher,
            )
            preview.report.signature = SignatureInfo(
                **{
                    **preview.report.signature.to_dict(),
                    "status": "valid_trusted",
                    "trusted": True,
                    "message": "Signature is valid and the publisher is trusted",
                }
            )

        def update(state):
            item = state["plugins"].get(manifest.id, {})
            if not isinstance(item, dict):
                item = {}
            versions = item.get("versions", {})
            if not isinstance(versions, dict):
                versions = {}
            existing_active = str(item.get("active_version", "") or "")
            if existing_active and isinstance(versions.get(existing_active), dict):
                versions[existing_active]["granted_permissions"] = item.get(
                    "granted_permissions", {}
                )
            versions[manifest.version] = {
                "path": str(target),
                "package_sha256": preview.report.package_sha256,
                "manifest": manifest.to_dict(),
                "scan": preview.report.to_dict(),
                "source": preview.source,
                "granted_permissions": manifest.permissions,
            }
            previous_version = item.get("active_version", "")
            item.update({
                "active_version": manifest.version,
                "previous_version": previous_version if previous_version != manifest.version else item.get("previous_version", ""),
                "enabled": bool(item.get("enabled", False)) if enable is None else bool(enable),
                "permissions": manifest.permissions,
                "granted_permissions": manifest.permissions,
                "execution": manifest.execution,
                "language": manifest.language,
                "source": preview.source,
                "pending_restart": manifest.execution == "native",
                "versions": versions,
            })
            state["plugins"][manifest.id] = item
            return item

        try:
            installed = self.state.mutate(update)
        except BaseException:
            shutil.rmtree(target, ignore_errors=True)
            raise
        self._previews.pop(token, None)
        shutil.rmtree(stage, ignore_errors=True)
        return installed

    def cancel(self, preview_or_token: InstallPreview | str) -> None:
        token = preview_or_token.token if isinstance(preview_or_token, InstallPreview) else str(preview_or_token)
        preview = self._previews.pop(token, None)
        if preview is not None:
            shutil.rmtree(preview.staging_path, ignore_errors=True)

    def list_installed(self) -> list[dict[str, Any]]:
        plugins = self.state.load().get("plugins", {})
        result = []
        for plugin_id, item in sorted(plugins.items()):
            if not isinstance(item, dict):
                continue
            active = str(item.get("active_version", "") or "")
            version_info = item.get("versions", {}).get(active, {}) if active else {}
            result.append({"id": plugin_id, **item, "active": version_info})
        return result

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        result: dict[str, Any] = {}
        def update(state):
            nonlocal result
            item = state["plugins"].get(plugin_id)
            if not isinstance(item, dict):
                raise PluginError(f"Plugin is not installed: {plugin_id}")
            active = item.get("versions", {}).get(item.get("active_version", ""), {})
            report_raw = active.get("scan", {}) if isinstance(active, dict) else {}
            report = ScanReport.from_dict(report_raw) if report_raw else None
            if enabled and report is not None and report.blocked:
                raise PluginError("Plugin security report blocks enabling it")
            item["enabled"] = bool(enabled)
            item["pending_restart"] = item.get("execution") == "native"
            result = dict(item)
        self.state.mutate(update)
        return result

    def set_permissions(self, plugin_id: str, permissions: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(permissions, dict):
            raise PluginError("Granted permissions must be a JSON object")

        def is_subset(granted, declared) -> bool:
            if declared is True:
                return True
            if granted is False or granted is None or granted == {} or granted == []:
                return True
            if granted is True:
                return declared is True
            if isinstance(granted, dict) and isinstance(declared, dict):
                return all(key in declared and is_subset(value, declared[key]) for key, value in granted.items())
            if isinstance(granted, list) and isinstance(declared, list):
                return set(map(str, granted)).issubset(set(map(str, declared)))
            return granted == declared

        result: dict[str, Any] = {}

        def update(state):
            nonlocal result
            item = state["plugins"].get(plugin_id)
            if not isinstance(item, dict):
                raise PluginError(f"Plugin is not installed: {plugin_id}")
            declared = item.get("permissions", {})
            if item.get("execution") != "native" and not is_subset(permissions, declared):
                raise PluginError("Granted permissions cannot exceed the plugin manifest")
            item["granted_permissions"] = permissions
            active_version = str(item.get("active_version", "") or "")
            version_info = item.get("versions", {}).get(active_version, {})
            if isinstance(version_info, dict):
                version_info["granted_permissions"] = permissions
            result = dict(item)

        self.state.mutate(update)
        return result

    def rollback(self, plugin_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        def update(state):
            nonlocal result
            item = state["plugins"].get(plugin_id)
            if not isinstance(item, dict):
                raise PluginError(f"Plugin is not installed: {plugin_id}")
            previous = str(item.get("previous_version", "") or "")
            active = str(item.get("active_version", "") or "")
            if not previous or previous not in item.get("versions", {}):
                raise PluginError("No previous plugin version is available")
            versions = item.get("versions", {})
            active_info = versions.get(active, {})
            previous_info = versions.get(previous, {})
            if isinstance(active_info, dict):
                active_info["granted_permissions"] = item.get("granted_permissions", {})
            item["active_version"], item["previous_version"] = previous, active
            manifest = previous_info.get("manifest", {}) if isinstance(previous_info, dict) else {}
            if isinstance(manifest, dict):
                declared = manifest.get("permissions", {})
                item["permissions"] = declared if isinstance(declared, dict) else {}
                item["execution"] = str(manifest.get("execution", item.get("execution", "")))
                item["language"] = str(manifest.get("language", item.get("language", "")))
            grants = previous_info.get("granted_permissions") if isinstance(previous_info, dict) else None
            item["granted_permissions"] = (
                grants if isinstance(grants, dict) else item.get("permissions", {})
            )
            item["pending_restart"] = item.get("execution") == "native"
            result = dict(item)
        self.state.mutate(update)
        return result

    def uninstall(self, plugin_id: str, *, delete_data: bool = False) -> None:
        removed: dict[str, Any] = {}
        def update(state):
            nonlocal removed
            item = state["plugins"].pop(plugin_id, None)
            if not isinstance(item, dict):
                raise PluginError(f"Plugin is not installed: {plugin_id}")
            removed = item
        self.state.mutate(update)
        package_dir = (self.paths.packages / plugin_id).resolve()
        if package_dir.is_relative_to(self.paths.packages.resolve()):
            shutil.rmtree(package_dir, ignore_errors=True)
        if delete_data:
            data_dir = (self.paths.data / plugin_id).resolve()
            if data_dir.is_relative_to(self.paths.data.resolve()):
                shutil.rmtree(data_dir, ignore_errors=True)

    def check_update(self, plugin_id: str) -> dict[str, Any]:
        item = self.state.plugin(plugin_id)
        active_version = str(item.get("active_version", "") or "")
        active = item.get("versions", {}).get(active_version, {})
        manifest = active.get("manifest", {}) if isinstance(active, dict) else {}
        update_url = str(manifest.get("update_url", "") or "").strip()
        if not update_url:
            raise PluginError("Plugin does not declare an update URL")
        parsed = urllib.parse.urlsplit(update_url)
        if parsed.scheme.lower() != "https":
            raise PluginError("Update descriptors must use HTTPS")
        response, _final_url = open_public_url(
            update_url,
            timeout=15,
            max_redirects=5,
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        )
        with response:
            payload = response.read(MAX_UPDATE_DESCRIPTOR_BYTES + 1)
        if len(payload) > MAX_UPDATE_DESCRIPTOR_BYTES:
            raise PluginError("Plugin update descriptor exceeds 256 KiB")
        try:
            descriptor = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"Plugin update descriptor is invalid JSON: {exc}") from exc
        if not isinstance(descriptor, dict) or descriptor.get("id") != plugin_id:
            raise PluginError("Plugin update descriptor id does not match")
        latest = str(descriptor.get("version", "") or "").strip()
        package_url = str(descriptor.get("package_url", "") or "").strip()
        expected_hash = str(descriptor.get("sha256", "") or "").strip().lower()
        if not latest or not package_url or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise PluginError("Plugin update descriptor is missing version, package_url or SHA-256")
        return {
            "id": plugin_id,
            "current_version": active_version,
            "latest_version": latest,
            "update_available": Version(latest) > Version(active_version),
            "package_url": package_url,
            "sha256": expected_hash,
        }
