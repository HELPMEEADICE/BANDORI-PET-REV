from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import PurePosixPath

from .models import SignatureInfo


FILES_MANIFEST_PATH = "META-INF/files.json"
PUBLIC_KEY_PATH = "META-INF/public_key.ed25519"
SIGNATURE_PATH = "META-INF/signature.ed25519"
SIGNATURE_META_PATHS = frozenset({FILES_MANIFEST_PATH, PUBLIC_KEY_PATH, SIGNATURE_PATH})


def _decode_text_or_raw(payload: bytes, expected_lengths: set[int]) -> bytes:
    stripped = payload.strip()
    if len(stripped) in expected_lengths:
        return stripped
    try:
        decoded = base64.b64decode(stripped, validate=True)
    except (ValueError, base64.binascii.Error):
        return payload
    return decoded


def _raw_public_key(payload: bytes) -> bytes:
    stripped = payload.strip()
    if stripped.startswith(b"-----BEGIN"):
        from cryptography.hazmat.primitives import serialization

        key = serialization.load_pem_public_key(stripped)
        return key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    return _decode_text_or_raw(stripped, {32})


def publisher_fingerprint(raw_public_key: bytes) -> str:
    return hashlib.sha256(raw_public_key).hexdigest()


def verify_archive_signature(
    archive: zipfile.ZipFile,
    *,
    trusted_fingerprints: set[str] | None = None,
) -> SignatureInfo:
    names = {info.filename for info in archive.infolist() if not info.is_dir()}
    present = names & SIGNATURE_META_PATHS
    if not present:
        return SignatureInfo()
    if present != SIGNATURE_META_PATHS:
        return SignatureInfo(
            status="invalid",
            message="Plugin signature metadata is incomplete",
        )

    try:
        files_payload = archive.read(FILES_MANIFEST_PATH)
        files_document = json.loads(files_payload.decode("utf-8"))
        files = files_document.get("files", {})
        publisher = str(files_document.get("publisher", "") or "").strip()
        if files_document.get("algorithm") != "sha256" or not isinstance(files, dict):
            raise ValueError("files.json must declare a sha256 file map")

        payload_names = names - SIGNATURE_META_PATHS
        listed_names = set(files)
        if payload_names != listed_names:
            missing = sorted(payload_names - listed_names)
            extra = sorted(listed_names - payload_names)
            raise ValueError(
                f"signed file list mismatch (unlisted={missing[:3]}, missing={extra[:3]})"
            )
        for name, expected in files.items():
            if not isinstance(name, str) or PurePosixPath(name).is_absolute():
                raise ValueError("signed file list contains an invalid path")
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual.lower() != str(expected or "").lower():
                raise ValueError(f"file hash does not match: {name}")

        public_key_raw = _raw_public_key(archive.read(PUBLIC_KEY_PATH))
        signature = _decode_text_or_raw(archive.read(SIGNATURE_PATH), {64})
        if len(public_key_raw) != 32 or len(signature) != 64:
            raise ValueError("Ed25519 key or signature has an invalid length")

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(signature, files_payload)
        fingerprint = publisher_fingerprint(public_key_raw)
        trusted = fingerprint in (trusted_fingerprints or set())
        return SignatureInfo(
            status="valid_trusted" if trusted else "valid_untrusted",
            fingerprint=fingerprint,
            publisher=publisher,
            message=(
                "Signature is valid and the publisher is trusted"
                if trusted
                else "Signature is valid but the publisher is not trusted yet"
            ),
            trusted=trusted,
        )
    except ImportError as exc:
        return SignatureInfo(
            status="unavailable",
            message=f"Ed25519 verification is unavailable: {exc}",
        )
    except Exception as exc:
        return SignatureInfo(
            status="invalid",
            message=f"Plugin signature verification failed: {exc}",
        )


def build_signed_files_document(
    files: dict[str, bytes],
    *,
    publisher: str = "",
) -> bytes:
    """Build the canonical bytes that publisher tooling must sign."""
    document = {
        "algorithm": "sha256",
        "files": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in sorted(files.items())
            if name not in SIGNATURE_META_PATHS
        },
        "publisher": str(publisher or "").strip(),
    }
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
