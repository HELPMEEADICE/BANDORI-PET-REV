from __future__ import annotations

import json
import re
import sys
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from app_info import APP_VERSION


PLUGIN_SCHEMA_VERSION = 1
PLUGIN_API_VERSION = "1.0"
PLUGIN_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,126}[a-z0-9])?$")
PROCESS_TARGETS = frozenset({"main", "pet", "chat", "settings", "radial"})
SUPPORTED_LANGUAGES = frozenset({"python", "lua"})
SUPPORTED_EXECUTIONS = frozenset({"managed", "native"})
PLATFORM_NAMES = {
    "win32": "windows",
    "darwin": "macos",
}
RISK_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class PluginError(RuntimeError):
    """A user-facing plugin package or runtime error."""


def current_platform_name() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    return PLATFORM_NAMES.get(sys.platform, sys.platform)


def _normalized_architecture(value: str) -> str:
    aliases = {
        "amd64": "x86_64", "x64": "x86_64", "x86-64": "x86_64",
        "aarch64": "arm64", "arm64e": "arm64",
        "i386": "x86", "i686": "x86", "win32": "x86",
    }
    text = str(value or "").strip().lower()
    return aliases.get(text, text)


def _version_matches(specifier: str, version: str, label: str) -> None:
    try:
        accepted = SpecifierSet(specifier)
        candidate = Version(version)
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise PluginError(f"Invalid {label} version constraint: {specifier!r}") from exc
    if candidate not in accepted:
        raise PluginError(
            f"Plugin requires {label} {specifier}, but {version} is running"
        )


def _normalized_string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PluginError(f"{label} must be an array")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


@dataclass(frozen=True)
class PluginManifest:
    schema_version: int
    id: str
    name: str
    version: str
    api: str
    app: str
    language: str
    execution: str
    entrypoints: dict[str, str]
    permissions: dict[str, Any] = field(default_factory=dict)
    platforms: tuple[str, ...] = ()
    architectures: tuple[str, ...] = ()
    update_url: str = ""
    description: str = ""
    author: str = ""
    homepage: str = ""

    @classmethod
    def from_dict(
        cls,
        raw: dict[str, Any],
        *,
        check_compatibility: bool = True,
    ) -> "PluginManifest":
        if not isinstance(raw, dict):
            raise PluginError("plugin.json must contain a JSON object")
        try:
            schema_version = int(raw.get("schema_version", 0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise PluginError("schema_version must be an integer") from exc
        if schema_version != PLUGIN_SCHEMA_VERSION:
            raise PluginError(
                f"Unsupported plugin schema {schema_version}; expected {PLUGIN_SCHEMA_VERSION}"
            )

        plugin_id = str(raw.get("id", "") or "").strip().lower()
        if not PLUGIN_ID_RE.fullmatch(plugin_id):
            raise PluginError(
                "Plugin id must be 3-128 lowercase ASCII letters, digits, dots, dashes or underscores"
            )
        name = str(raw.get("name", "") or "").strip()
        if not name or len(name) > 120:
            raise PluginError("Plugin name is required and must be at most 120 characters")
        version = str(raw.get("version", "") or "").strip()
        try:
            Version(version)
        except InvalidVersion as exc:
            raise PluginError(f"Invalid plugin version: {version!r}") from exc

        api = str(raw.get("api", "") or "").strip()
        app = str(raw.get("app", "") or "").strip()
        if not api or not app:
            raise PluginError("Both api and app compatibility constraints are required")
        if check_compatibility:
            _version_matches(api, PLUGIN_API_VERSION, "plugin API")
            _version_matches(app, APP_VERSION, "BandoriPet")

        language = str(raw.get("language", "") or "").strip().lower()
        execution = str(raw.get("execution", "managed") or "managed").strip().lower()
        if language not in SUPPORTED_LANGUAGES:
            raise PluginError(f"Unsupported plugin language: {language!r}")
        if execution not in SUPPORTED_EXECUTIONS:
            raise PluginError(f"Unsupported execution mode: {execution!r}")
        if execution == "native" and language != "python":
            raise PluginError("Native plugins must use Python")

        raw_entrypoints = raw.get("entrypoints", {})
        if not isinstance(raw_entrypoints, dict):
            raise PluginError("entrypoints must be an object")
        entrypoints: dict[str, str] = {}
        for target, value in raw_entrypoints.items():
            target = str(target or "").strip().lower()
            value = str(value or "").strip().replace("\\", "/")
            if not target or not value:
                continue
            if value.startswith("/") or ".." in Path(value).parts:
                raise PluginError(f"Unsafe entrypoint path: {value!r}")
            entrypoints[target] = value
        if execution == "managed":
            if set(entrypoints) != {"worker"}:
                raise PluginError("Managed plugins require exactly the 'worker' entrypoint")
        else:
            unknown_targets = set(entrypoints) - PROCESS_TARGETS
            if unknown_targets or not entrypoints:
                raise PluginError(
                    "Native entrypoints must target one or more of: "
                    + ", ".join(sorted(PROCESS_TARGETS))
                )

        permissions = raw.get("permissions", {})
        if not isinstance(permissions, dict):
            raise PluginError("permissions must be an object")
        platforms = tuple(_normalized_string_list(raw.get("platforms"), "platforms"))
        allowed_platforms = {"windows", "macos", "linux"}
        if set(platforms) - allowed_platforms:
            raise PluginError("platforms contains an unsupported platform name")
        if check_compatibility and platforms and current_platform_name() not in platforms:
            raise PluginError(
                f"Plugin does not support this platform ({current_platform_name()})"
            )
        architectures = tuple(_normalized_string_list(raw.get("architectures"), "architectures"))
        if check_compatibility and architectures:
            current_arch = _normalized_architecture(platform.machine())
            accepted_arches = {_normalized_architecture(item) for item in architectures}
            if current_arch not in accepted_arches:
                raise PluginError(
                    f"Plugin does not support this architecture ({current_arch})"
                )

        return cls(
            schema_version=schema_version,
            id=plugin_id,
            name=name,
            version=version,
            api=api,
            app=app,
            language=language,
            execution=execution,
            entrypoints=entrypoints,
            permissions=permissions,
            platforms=platforms,
            architectures=architectures,
            update_url=str(raw.get("update_url", "") or "").strip(),
            description=str(raw.get("description", "") or "").strip(),
            author=str(raw.get("author", "") or "").strip(),
            homepage=str(raw.get("homepage", "") or "").strip(),
        )

    @classmethod
    def from_bytes(
        cls,
        payload: bytes,
        *,
        check_compatibility: bool = True,
    ) -> "PluginManifest":
        try:
            raw = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"plugin.json is not valid UTF-8 JSON: {exc}") from exc
        return cls.from_dict(raw, check_compatibility=check_compatibility)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["platforms"] = list(self.platforms)
        data["architectures"] = list(self.architectures)
        return data


@dataclass(frozen=True)
class SecurityFinding:
    rule: str
    severity: str
    message: str
    path: str = ""
    line: int = 0
    evidence: str = ""
    blocking: bool = False
    inferred_permission: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SecurityFinding":
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            rule=str(raw.get("rule", "") or ""),
            severity=str(raw.get("severity", "info") or "info"),
            message=str(raw.get("message", "") or ""),
            path=str(raw.get("path", "") or ""),
            line=max(0, int(raw.get("line", 0) or 0)),
            evidence=str(raw.get("evidence", "") or ""),
            blocking=bool(raw.get("blocking", False)),
            inferred_permission=str(raw.get("inferred_permission", "") or ""),
            recommendation=str(raw.get("recommendation", "") or ""),
        )


@dataclass(frozen=True)
class SignatureInfo:
    status: str = "unsigned"
    fingerprint: str = ""
    publisher: str = ""
    message: str = "Plugin package is unsigned"
    trusted: bool = False

    @property
    def valid(self) -> bool:
        return self.status in {"valid", "valid_untrusted", "valid_trusted"}

    @property
    def invalid(self) -> bool:
        return self.status in {"invalid", "unavailable"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SignatureInfo":
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            status=str(raw.get("status", "unsigned") or "unsigned"),
            fingerprint=str(raw.get("fingerprint", "") or ""),
            publisher=str(raw.get("publisher", "") or ""),
            message=str(raw.get("message", "Plugin package is unsigned") or ""),
            trusted=bool(raw.get("trusted", False)),
        )


@dataclass
class ScanReport:
    scanner_version: str
    package_sha256: str
    risk: str
    findings: list[SecurityFinding]
    inferred_permissions: list[str]
    declared_permissions: dict[str, Any]
    signature: SignatureInfo = field(default_factory=SignatureInfo)

    @property
    def blocked(self) -> bool:
        return self.signature.invalid or any(item.blocking for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner_version": self.scanner_version,
            "package_sha256": self.package_sha256,
            "risk": self.risk,
            "blocked": self.blocked,
            "findings": [item.to_dict() for item in self.findings],
            "inferred_permissions": list(self.inferred_permissions),
            "declared_permissions": self.declared_permissions,
            "signature": self.signature.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScanReport":
        return cls(
            scanner_version=str(raw.get("scanner_version", "")),
            package_sha256=str(raw.get("package_sha256", "")),
            risk=str(raw.get("risk", "info")),
            findings=[SecurityFinding.from_dict(item) for item in raw.get("findings", []) if isinstance(item, dict)],
            inferred_permissions=[str(item) for item in raw.get("inferred_permissions", [])],
            declared_permissions=raw.get("declared_permissions", {}) if isinstance(raw.get("declared_permissions"), dict) else {},
            signature=SignatureInfo.from_dict(raw.get("signature", {})),
        )


@dataclass
class InstallPreview:
    token: str
    staging_path: str
    source: str
    manifest: PluginManifest
    report: ScanReport
    requires_insecure_transport_confirmation: bool = False
    permission_changes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_staging_path: bool = False) -> dict[str, Any]:
        result = {
            "token": self.token,
            "source": self.source,
            "manifest": self.manifest.to_dict(),
            "report": self.report.to_dict(),
            "requires_insecure_transport_confirmation": self.requires_insecure_transport_confirmation,
            "permission_changes": self.permission_changes,
        }
        if include_staging_path:
            result["staging_path"] = self.staging_path
        return result


def highest_risk(findings: list[SecurityFinding]) -> str:
    return max(
        (item.severity for item in findings),
        key=lambda value: RISK_ORDER.get(value, 0),
        default="info",
    )
