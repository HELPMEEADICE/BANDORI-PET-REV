from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .models import (
    PluginManifest,
    ScanReport,
    SecurityFinding,
    SignatureInfo,
    highest_risk,
)


SCANNER_VERSION = "1.0.0"
BINARY_SUFFIXES = frozenset({".pyd", ".so", ".dll", ".dylib", ".exe", ".bin"})
COMPILED_SUFFIXES = frozenset({".pyc", ".pyo", ".ljbc"})
OPAQUE_PAYLOAD_SUFFIXES = frozenset({".pickle", ".pkl", ".marshal"})
SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*['\"]([^'\"]{12,})['\"]"
)
URL_RE = re.compile(r"https?://[^\s'\"<>]{4,}", re.IGNORECASE)
BASE64_BLOB_RE = re.compile(r"['\"](?:[A-Za-z0-9+/]{180,}={0,2})['\"]")


def _declared_permission_names(value, prefix: str = "") -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            if child not in (False, None, [], {}):
                result.add(name)
            result.update(_declared_permission_names(child, name))
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, str):
                result.add(f"{prefix}.{child}" if prefix else child)
    elif value is True and prefix:
        result.add(prefix)
    return result


class _PythonVisitor(ast.NodeVisitor):
    IMPORT_RULES = {
        "ctypes": ("PY_NATIVE_MEMORY", "critical", "system.native"),
        "cffi": ("PY_NATIVE_MEMORY", "critical", "system.native"),
        "subprocess": ("PY_PROCESS", "high", "system.process"),
        "multiprocessing": ("PY_PROCESS", "high", "system.process"),
        "socket": ("PY_NETWORK", "high", "network"),
        "http": ("PY_NETWORK", "high", "network"),
        "urllib": ("PY_NETWORK", "high", "network"),
        "requests": ("PY_NETWORK", "high", "network"),
        "os": ("PY_OS_ACCESS", "high", "system"),
        "pathlib": ("PY_FILESYSTEM", "high", "filesystem"),
        "shutil": ("PY_FILESYSTEM", "high", "filesystem"),
        "tempfile": ("PY_FILESYSTEM", "high", "filesystem"),
        "importlib": ("PY_DYNAMIC_IMPORT", "high", "system.dynamic_code"),
        "marshal": ("PY_OPAQUE_CODE", "critical", "system.dynamic_code"),
        "pickle": ("PY_DESERIALIZATION", "high", "filesystem.read"),
    }
    CALL_RULES = {
        "eval": ("PY_DYNAMIC_EXEC", "critical", "system.dynamic_code"),
        "exec": ("PY_DYNAMIC_EXEC", "critical", "system.dynamic_code"),
        "compile": ("PY_DYNAMIC_EXEC", "critical", "system.dynamic_code"),
        "__import__": ("PY_DYNAMIC_IMPORT", "critical", "system.dynamic_code"),
        "open": ("PY_DIRECT_FILE", "high", "filesystem"),
        "breakpoint": ("PY_DEBUGGER", "high", "system.debug"),
    }

    def __init__(self, path: str, managed: bool):
        self.path = path
        self.managed = managed
        self.findings: list[SecurityFinding] = []
        self.inferred: set[str] = set()

    def _add(self, node, rule: str, severity: str, permission: str, evidence: str):
        self.inferred.add(permission)
        self.findings.append(SecurityFinding(
            rule=rule,
            severity=severity,
            message=f"Code directly uses {permission}; use the plugin capability API instead",
            path=self.path,
            line=int(getattr(node, "lineno", 0) or 0),
            evidence=evidence[:240],
            blocking=self.managed and severity in {"high", "critical"},
            inferred_permission=permission,
        ))

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in self.IMPORT_RULES:
                rule, severity, permission = self.IMPORT_RULES[root]
                self._add(node, rule, severity, permission, f"import {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        root = str(node.module or "").split(".", 1)[0]
        if root in self.IMPORT_RULES:
            rule, severity, permission = self.IMPORT_RULES[root]
            self._add(node, rule, severity, permission, f"from {node.module} import ...")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        name = ""
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name in self.CALL_RULES:
            rule, severity, permission = self.CALL_RULES[name]
            self._add(node, rule, severity, permission, f"{name}(...)")
        elif name in {"getattr", "setattr", "delattr"}:
            attribute = node.args[1] if len(node.args) > 1 else None
            if not isinstance(attribute, ast.Constant) or not isinstance(attribute.value, str):
                self._add(
                    node,
                    "PY_DYNAMIC_REFLECTION",
                    "high",
                    "system.dynamic_code",
                    f"{name}(..., dynamic_name)",
                )
            elif attribute.value.startswith("_"):
                self._add(
                    node,
                    "PY_PRIVATE_REFLECTION",
                    "critical",
                    "system.dynamic_code",
                    f"{name}(..., {attribute.value!r})",
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("__") and node.attr.endswith("__"):
            self._add(
                node,
                "PY_DUNDER_REFLECTION",
                "high",
                "system.dynamic_code",
                node.attr,
            )
        self.generic_visit(node)


def _text_findings(path: str, text: str, managed: bool) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for match in SECRET_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        findings.append(SecurityFinding(
            rule="HARDCODED_SECRET",
            severity="high",
            message="Possible hard-coded secret found in plugin source",
            path=path,
            line=line,
            evidence=match.group(0)[:120],
            blocking=False,
            inferred_permission="secrets",
        ))
    for match in BASE64_BLOB_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        findings.append(SecurityFinding(
            rule="OPAQUE_ENCODED_BLOB",
            severity="high",
            message="Large encoded blob prevents meaningful source review",
            path=path,
            line=line,
            evidence=match.group(0)[:80] + "...",
            blocking=managed,
            inferred_permission="system.dynamic_code",
        ))
    urls = sorted(set(URL_RE.findall(text)))
    for url in urls[:20]:
        findings.append(SecurityFinding(
            rule="REMOTE_URL",
            severity="low",
            message="Plugin source contains a remote URL",
            path=path,
            evidence=url[:240],
            inferred_permission="network",
        ))
    return findings


LUA_RULES = (
    (re.compile(r"\brequire\s*\(?\s*['\"]ffi['\"]"), "LUA_FFI", "critical", "system.native"),
    (re.compile(r"\brequire\s*\(?\s*['\"](?:socket|http|ssl)['\"]"), "LUA_NETWORK", "high", "network"),
    (re.compile(r"\b(?:os|io|debug)\s*\."), "LUA_UNSAFE_LIBRARY", "high", "system"),
    (re.compile(r"\b(?:load|loadstring|loadfile|dofile)\s*\("), "LUA_DYNAMIC_CODE", "critical", "system.dynamic_code"),
    (re.compile(r"\bpackage\s*\.\s*loadlib\b"), "LUA_BINARY_MODULE", "critical", "system.native"),
    (re.compile(r"\bpython\s*\."), "LUA_PYTHON_BRIDGE", "critical", "system.dynamic_code"),
)


def _scan_lua(path: str, text: str, managed: bool) -> tuple[list[SecurityFinding], set[str]]:
    findings: list[SecurityFinding] = []
    inferred: set[str] = set()
    try:
        from lupa.luajit21 import LuaRuntime

        parser = LuaRuntime(
            register_eval=False,
            register_builtins=False,
            max_memory=8 * 1024 * 1024,
        )
        parser.compile(text)
    except ImportError:
        findings.append(SecurityFinding(
            rule="LUA_SCANNER_UNAVAILABLE",
            severity="high",
            message="Lua syntax validation is unavailable",
            path=path,
            blocking=managed,
        ))
    except Exception as exc:
        match = re.search(r":(\d+):", str(exc))
        findings.append(SecurityFinding(
            rule="LUA_SYNTAX_ERROR",
            severity="high",
            message=f"Lua source cannot be parsed: {exc}",
            path=path,
            line=int(match.group(1)) if match else 0,
            blocking=True,
        ))
    for line_number, line in enumerate(text.splitlines(), start=1):
        code = line.split("--", 1)[0]
        for pattern, rule, severity, permission in LUA_RULES:
            match = pattern.search(code)
            if not match:
                continue
            inferred.add(permission)
            findings.append(SecurityFinding(
                rule=rule,
                severity=severity,
                message=f"Lua source directly uses {permission}; use the plugin capability API instead",
                path=path,
                line=line_number,
                evidence=match.group(0)[:160],
                blocking=managed,
                inferred_permission=permission,
            ))
    findings.extend(_text_findings(path, text, managed))
    inferred.update(item.inferred_permission for item in findings if item.inferred_permission)
    return findings, inferred


def scan_plugin_directory(
    root: Path,
    manifest: PluginManifest,
    *,
    package_sha256: str,
    signature: SignatureInfo | None = None,
) -> ScanReport:
    root = Path(root).resolve()
    findings: list[SecurityFinding] = []
    inferred: set[str] = set()
    managed = manifest.execution == "managed"
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        try:
            with path.open("rb") as stream:
                magic = stream.read(16)
        except OSError:
            magic = b""
        binary_magic = (
            magic.startswith((b"MZ", b"\x7fELF", b"\x1bLua", b"\x1bLJ"))
            or magic[:4] in {
                b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",
            }
        )
        if suffix in OPAQUE_PAYLOAD_SUFFIXES or (managed and magic.startswith(b"\x80")):
            findings.append(SecurityFinding(
                rule="OPAQUE_SERIALIZED_PAYLOAD",
                severity="critical",
                message="Pickle or marshal payloads are not allowed in managed plugins",
                path=relative,
                blocking=managed,
                inferred_permission="system.dynamic_code",
            ))
            inferred.add("system.dynamic_code")
            continue
        if suffix in COMPILED_SUFFIXES:
            findings.append(SecurityFinding(
                rule="OPAQUE_COMPILED_CODE",
                severity="critical",
                message="Compiled Python/Lua code cannot be security scanned",
                path=relative,
                blocking=managed,
                inferred_permission="system.dynamic_code",
            ))
            inferred.add("system.dynamic_code")
            continue
        if suffix in BINARY_SUFFIXES:
            findings.append(SecurityFinding(
                rule="NATIVE_BINARY",
                severity="critical" if managed else "high",
                message="Plugin contains a native executable or library",
                path=relative,
                blocking=managed,
                inferred_permission="system.native",
            ))
            inferred.add("system.native")
            continue
        if binary_magic:
            findings.append(SecurityFinding(
                rule="NATIVE_BINARY_MAGIC",
                severity="critical" if managed else "high",
                message="File contents identify native or compiled executable code",
                path=relative,
                evidence=magic.hex(),
                blocking=managed,
                inferred_permission="system.native",
            ))
            inferred.add("system.native")
            continue
        if suffix not in {".py", ".lua"}:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(SecurityFinding(
                rule="UNREADABLE_SOURCE",
                severity="high",
                message=f"Source file is not readable UTF-8 text: {exc}",
                path=relative,
                blocking=managed,
            ))
            continue
        if suffix == ".py":
            try:
                tree = ast.parse(text, filename=relative)
            except SyntaxError as exc:
                findings.append(SecurityFinding(
                    rule="PY_SYNTAX_ERROR",
                    severity="high",
                    message=f"Python source cannot be parsed: {exc.msg}",
                    path=relative,
                    line=int(exc.lineno or 0),
                    blocking=True,
                ))
                continue
            visitor = _PythonVisitor(relative, managed)
            visitor.visit(tree)
            visitor.findings.extend(_text_findings(relative, text, managed))
            visitor.inferred.update(
                item.inferred_permission for item in visitor.findings if item.inferred_permission
            )
            findings.extend(visitor.findings)
            inferred.update(visitor.inferred)
        else:
            lua_findings, lua_inferred = _scan_lua(relative, text, managed)
            findings.extend(lua_findings)
            inferred.update(lua_inferred)

    for entrypoint in manifest.entrypoints.values():
        entry_path = root / entrypoint
        if not entry_path.is_file() or not entry_path.resolve().is_relative_to(root):
            findings.append(SecurityFinding(
                rule="MISSING_ENTRYPOINT",
                severity="critical",
                message=f"Declared entrypoint does not exist: {entrypoint}",
                path=entrypoint,
                blocking=True,
            ))

    if manifest.execution == "native" and not manifest.architectures and any(
        path.is_file() and path.suffix.lower() in BINARY_SUFFIXES
        for path in root.rglob("*")
    ):
        findings.append(SecurityFinding(
            rule="NATIVE_ARCHITECTURE_UNDECLARED",
            severity="high",
            message="Native binary packages should declare compatible architectures",
            blocking=False,
            inferred_permission="system.native",
        ))
    expected_suffix = ".py" if manifest.language == "python" else ".lua"
    for entrypoint in manifest.entrypoints.values():
        if Path(entrypoint).suffix.lower() != expected_suffix:
            findings.append(SecurityFinding(
                rule="ENTRYPOINT_LANGUAGE_MISMATCH",
                severity="critical",
                message=f"{manifest.language} entrypoint must end with {expected_suffix}",
                path=entrypoint,
                blocking=True,
            ))

    declared = _declared_permission_names(manifest.permissions)
    for permission in sorted(inferred):
        if any(
            permission == item
            or permission.startswith(item + ".")
            or item.startswith(permission + ".")
            for item in declared
        ):
            continue
        findings.append(SecurityFinding(
            rule="UNDECLARED_PERMISSION",
            severity="medium",
            message=f"Source appears to require undeclared permission: {permission}",
            inferred_permission=permission,
        ))

    signature = signature or SignatureInfo()
    if signature.invalid:
        findings.append(SecurityFinding(
            rule="INVALID_SIGNATURE",
            severity="critical",
            message=signature.message,
            blocking=True,
        ))
    findings = [
        item if item.recommendation else replace(
            item,
            recommendation=(
                "Remove the boundary-bypassing code or publish an explicitly native Python plugin."
                if item.blocking and manifest.execution == "managed"
                else "Review the evidence, declare the minimum required permission, and document why it is needed."
            ),
        )
        for item in findings
    ]
    return ScanReport(
        scanner_version=SCANNER_VERSION,
        package_sha256=package_sha256,
        risk=highest_risk(findings),
        findings=findings,
        inferred_permissions=sorted(inferred),
        declared_permissions=manifest.permissions,
        signature=signature,
    )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(root: Path) -> str:
    digest = hashlib.sha256()
    root = Path(root).resolve()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()
