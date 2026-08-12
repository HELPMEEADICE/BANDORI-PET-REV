import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest

import companion_security
from companion_security import CompanionSecurityStore


class FakeConfig:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        return True

    def load(self):
        return True


def _decode_pairing(uri):
    encoded = parse_qs(urlparse(uri).query)["data"][0]
    encoded += "=" * ((4 - len(encoded) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(encoded))


def test_pairing_is_one_time_hashed_and_revocable(tmp_path, monkeypatch):
    monkeypatch.setattr(companion_security, "app_data_dir", lambda: str(tmp_path))
    config = FakeConfig()
    security = CompanionSecurityStore(config)
    pairing = security.issue_pairing(profile_key="alice", host_candidates=["192.168.1.7"], port=38474)
    payload = _decode_pairing(pairing["uri"])

    assert payload["v"] == 1
    assert payload["hosts"] == ["192.168.1.7"]
    assert payload["pinSha256"] == security.ensure_tls_identity()[2]

    credential = "a" * 43
    device_id = "1efdbd91-1868-4fbd-8385-8f01cd82bceb"
    paired = security.pair_device(
        bootstrap_token=payload["token"],
        device_id=device_id,
        device_name="Pixel",
        credential=credential,
    )
    assert paired.profile_key == "alice"
    stored = config.get("companion_paired_devices")[0]
    assert stored["credential_hash"] == hashlib.sha256(credential.encode()).hexdigest()
    assert credential not in json.dumps(stored)
    assert security.authenticate(device_id, credential).name == "Pixel"

    with pytest.raises(PermissionError, match="PAIRING_EXPIRED"):
        security.pair_device(
            bootstrap_token=payload["token"],
            device_id="c18d0870-f960-4e2f-9722-02d64415e024",
            device_name="Replay",
            credential="b" * 43,
        )

    assert security.revoke(device_id)
    assert security.authenticate(device_id, credential) is None


def test_pairing_expiration_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(companion_security, "app_data_dir", lambda: str(tmp_path))
    config = FakeConfig()
    security = CompanionSecurityStore(config)
    pairing = security.issue_pairing(profile_key="default", host_candidates=["10.0.0.2"], port=38474)
    config.set("companion_pairing_expires_at", 1)

    with pytest.raises(PermissionError, match="PAIRING_EXPIRED"):
        security.pair_device(
            bootstrap_token=pairing["payload"]["token"],
            device_id="e4aeea6d-f72a-4cce-8d8c-695bd9601be3",
            device_name="Expired",
            credential="c" * 43,
        )
