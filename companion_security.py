from __future__ import annotations

import base64
import hashlib
import ipaddress
import secrets
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from process_utils import app_data_dir


PAIRING_TTL_SECONDS = 120
PAIRING_URI_SCHEME = "bandoripet://pair"


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _utc_millis() -> int:
    return int(time.time() * 1000)


def _save_config(config) -> None:
    result = config.save()
    if result is False:
        raise RuntimeError("Failed to save companion configuration")


@dataclass(frozen=True, slots=True)
class AuthenticatedDevice:
    device_id: str
    name: str
    profile_key: str


class CompanionSecurityStore:
    """Persistent identity and hashed per-device credentials.

    The short-lived bootstrap token is kept in config so the settings and chat
    processes can coordinate. Long-lived device credentials are never stored
    in plaintext on the desktop.
    """

    def __init__(self, config):
        self.config = config

    def reload(self) -> None:
        try:
            self.config.load()
        except Exception:
            pass

    def instance_id(self) -> str:
        self.reload()
        value = str(self.config.get("companion_instance_id", "") or "").strip()
        try:
            return str(uuid.UUID(value))
        except (ValueError, AttributeError):
            value = str(uuid.uuid4())
            self.config.set("companion_instance_id", value)
            _save_config(self.config)
            return value

    def identity_paths(self) -> tuple[Path, Path]:
        directory = Path(app_data_dir()) / "companion"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "identity-cert.pem", directory / "identity-key.pem"

    def ensure_tls_identity(self) -> tuple[Path, Path, str]:
        cert_path, key_path = self.identity_paths()
        if not (cert_path.is_file() and key_path.is_file()):
            instance_id = self.instance_id()
            key = ec.generate_private_key(ec.SECP256R1())
            subject = issuer = x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, f"BandoriPet-{instance_id[:8]}")
            ])
            now = datetime.now(timezone.utc)
            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(key, hashes.SHA256())
            )
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ))
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        public_key = cert.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        pin = base64.b64encode(hashlib.sha256(public_key).digest()).decode("ascii")
        return cert_path, key_path, pin

    def issue_pairing(self, *, profile_key: str, host_candidates: list[str], port: int) -> dict:
        token = secrets.token_urlsafe(32)
        expires_at = _utc_millis() + PAIRING_TTL_SECONDS * 1000
        self.config.set("companion_pairing_token_hash", _token_hash(token))
        self.config.set("companion_pairing_expires_at", expires_at)
        self.config.set("companion_pairing_profile_key", str(profile_key or "default"))
        _save_config(self.config)
        _cert, _key, pin = self.ensure_tls_identity()
        payload = {
            "v": 1,
            "instanceId": self.instance_id(),
            "name": str(self.config.get("companion_device_name", socket.gethostname()) or socket.gethostname()),
            "hosts": [str(value) for value in host_candidates if str(value).strip()],
            "port": int(port),
            "pinSha256": pin,
            "token": token,
            "expiresAt": expires_at,
        }
        encoded = base64.urlsafe_b64encode(
            __import__("json").dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        return {"payload": payload, "uri": f"{PAIRING_URI_SCHEME}?data={quote(encoded)}"}

    def pair_device(self, *, bootstrap_token: str, device_id: str, device_name: str, credential: str) -> AuthenticatedDevice:
        self.reload()
        expires_at = int(self.config.get("companion_pairing_expires_at", 0) or 0)
        expected = str(self.config.get("companion_pairing_token_hash", "") or "")
        if not expected or expires_at < _utc_millis() or not secrets.compare_digest(expected, _token_hash(bootstrap_token)):
            raise PermissionError("PAIRING_EXPIRED")
        try:
            device_id = str(uuid.UUID(str(device_id)))
        except (ValueError, AttributeError) as exc:
            raise ValueError("INVALID_DEVICE_ID") from exc
        credential = str(credential or "")
        if len(credential) < 32:
            raise ValueError("WEAK_CREDENTIAL")
        profile_key = str(self.config.get("companion_pairing_profile_key", "default") or "default")
        devices = [item for item in self.config.get("companion_paired_devices", []) if isinstance(item, dict)]
        devices = [item for item in devices if str(item.get("id", "")) != device_id]
        devices.append({
            "id": device_id,
            "name": str(device_name or "Android")[:80],
            "credential_hash": _token_hash(credential),
            "profile_key": profile_key,
            "created_at": _utc_millis(),
            "last_seen_at": _utc_millis(),
        })
        self.config.set("companion_paired_devices", devices)
        self.config.set("companion_pairing_token_hash", "")
        self.config.set("companion_pairing_expires_at", 0)
        _save_config(self.config)
        return AuthenticatedDevice(device_id, str(device_name or "Android")[:80], profile_key)

    def authenticate(self, device_id: str, credential: str) -> AuthenticatedDevice | None:
        self.reload()
        credential_hash = _token_hash(credential)
        devices = [item for item in self.config.get("companion_paired_devices", []) if isinstance(item, dict)]
        matched = None
        for item in devices:
            if str(item.get("id", "")) != str(device_id or ""):
                continue
            if secrets.compare_digest(str(item.get("credential_hash", "")), credential_hash):
                matched = item
            break
        if matched is None:
            return None
        matched["last_seen_at"] = _utc_millis()
        self.config.set("companion_paired_devices", devices)
        try:
            _save_config(self.config)
        except Exception:
            pass
        return AuthenticatedDevice(
            str(matched.get("id", "")),
            str(matched.get("name", "Android") or "Android"),
            str(matched.get("profile_key", "default") or "default"),
        )

    def revoke(self, device_id: str) -> bool:
        self.reload()
        current = [item for item in self.config.get("companion_paired_devices", []) if isinstance(item, dict)]
        remaining = [item for item in current if str(item.get("id", "")) != str(device_id or "")]
        if len(remaining) == len(current):
            return False
        self.config.set("companion_paired_devices", remaining)
        _save_config(self.config)
        return True


def local_host_candidates() -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM)
    except OSError:
        infos = []
    for info in infos:
        value = str(info[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.is_loopback or address.is_unspecified or address.is_multicast:
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
