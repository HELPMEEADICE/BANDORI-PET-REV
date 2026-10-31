import base64
import hashlib
import io
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plugin_system.signing import build_signed_files_document, verify_archive_signature


def _verify_package(files, document, public_key, signature, **kwargs):
    package = io.BytesIO()
    with zipfile.ZipFile(package, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        archive.writestr("META-INF/files.json", document)
        archive.writestr("META-INF/public_key.ed25519", public_key)
        archive.writestr("META-INF/signature.ed25519", signature)
    with zipfile.ZipFile(package) as archive:
        return verify_archive_signature(archive, **kwargs)


@pytest.fixture(params=[
    pytest.param(86, id="public-key-leading-space"),
    pytest.param(37, id="public-key-trailing-carriage-return"),
    pytest.param(38, id="signature-leading-carriage-return"),
    pytest.param(3, id="signature-trailing-form-feed"),
])
def signed_payload(request):
    # Fixed seeds reproduce binary whitespace at the key/signature boundaries.
    key = Ed25519PrivateKey.from_private_bytes(request.param.to_bytes(32, "big"))
    files = {"main.py": b"def activate(ctx):\n    pass\n"}
    document = build_signed_files_document(files, publisher="Example Publisher")
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return files, document, key, public, key.sign(document)


@pytest.mark.parametrize("public_format", ["raw", "base64", "pem"])
@pytest.mark.parametrize("signature_format", ["raw", "base64"])
def test_signed_archive_preserves_binary_whitespace(signed_payload, public_format, signature_format):
    files, document, key, raw_public, signature = signed_payload
    public = raw_public
    if public_format == "base64":
        public = b"\n" + base64.b64encode(public) + b"\r\n"
    elif public_format == "pem":
        public = b"\n" + key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ) + b"\r\n"
    if signature_format == "base64":
        signature = b"\n" + base64.b64encode(signature) + b"\r\n"

    result = _verify_package(files, document, public, signature)

    assert result.status == "valid_untrusted", result.message
    assert result.fingerprint == hashlib.sha256(raw_public).hexdigest()
    assert result.publisher == "Example Publisher"


@pytest.mark.parametrize("tampered", ["file", "public_key", "signature"])
def test_tampered_archive_is_rejected_even_for_trusted_publishers(signed_payload, tampered):
    files, document, _, public, signature = signed_payload
    fingerprint = hashlib.sha256(public).hexdigest()
    if tampered == "file":
        files["main.py"] += b"# changed\n"
    elif tampered == "public_key":
        public = bytes([public[0] ^ 1]) + public[1:]
    else:
        signature = bytes([signature[0] ^ 1]) + signature[1:]

    result = _verify_package(
        files, document, public, signature, trusted_fingerprints={fingerprint}
    )

    assert result.status == "invalid"
