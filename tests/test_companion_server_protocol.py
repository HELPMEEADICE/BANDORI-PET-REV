import asyncio
import socket
import sys
import time
from concurrent.futures import Future
from types import SimpleNamespace

import aiohttp
import pytest
from PySide6.QtCore import QObject, Signal

import companion_security
from companion_server import CompanionClient, CompanionServer


class FakeConfig:
    def __init__(self, port):
        self.values = {"companion_port": port, "companion_paired_devices": []}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        return True

    def load(self):
        return True


class FakeController(QObject):
    event_ready = Signal(str, object, object)
    audio_ready = Signal(str, object)
    active_profile_key = "alice"

    def submit_hello(self, client):
        future = Future()
        future.set_result({
            "protocolVersion": 1,
            "profileAvailable": client.profile_key == "alice",
            "capabilities": {"remoteChat": True},
            "state": {"mode": "private", "messages": [], "conversations": []},
        })
        return future

    def submit(self, client, request):
        future = Future()
        future.set_result({"echo": request["method"]})
        return future


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def _wait_running(server):
    for _ in range(100):
        if server.status["state"] == "running":
            return
        if server.status["state"] == "error":
            raise AssertionError(server.status["error"])
        await asyncio.sleep(0.02)
    raise AssertionError("server did not start")


def test_wss_pair_auth_request_and_revoke(tmp_path, monkeypatch):
    monkeypatch.setattr(companion_security, "app_data_dir", lambda: str(tmp_path))
    port = _free_port()
    config = FakeConfig(port)
    controller = FakeController()
    server = CompanionServer(controller, config)
    pairing = server.security.issue_pairing(profile_key="alice", host_candidates=["127.0.0.1"], port=port)
    device_id = "88df7a5f-c27a-4cbe-bf44-586179189c0d"
    credential = "remote-credential-with-more-than-32-characters"

    async def scenario():
        await _wait_running(server)
        endpoint = f"wss://127.0.0.1:{port}/v1/ws"
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.WSServerHandshakeError) as origin_error:
                await session.ws_connect(endpoint, ssl=False, origin="https://example.invalid")
            assert origin_error.value.status == 403
            pair_socket = await session.ws_connect(endpoint, ssl=False)
            await pair_socket.send_json({
                "v": 1,
                "id": "pair",
                "method": "pair.request",
                "params": {
                    "token": pairing["payload"]["token"],
                    "deviceId": device_id,
                    "deviceName": "Pixel",
                    "credential": credential,
                },
            })
            response = await pair_socket.receive_json()
            assert response["ok"] is True
            await pair_socket.close()

            headers = {"X-Bandori-Device": device_id, "Authorization": f"Bearer {credential}"}
            socket_ = await session.ws_connect(endpoint, ssl=False, headers=headers)
            hello = await socket_.receive_json()
            assert hello["event"] == "session.hello"
            assert hello["data"]["profileAvailable"] is True
            await socket_.send_json({"v": 1, "id": "state", "method": "state.get", "params": {}})
            response = await socket_.receive_json()
            assert response == {"v": 1, "id": "state", "ok": True, "result": {"echo": "state.get"}}

            assert server.security.revoke(device_id)
            server.revalidate_clients()
            for _ in range(50):
                message = await socket_.receive(timeout=1)
                if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}:
                    break
            assert socket_.closed

    server.start()
    try:
        asyncio.run(scenario())
    finally:
        server.stop()


def test_port_conflict_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(companion_security, "app_data_dir", lambda: str(tmp_path))
    with socket.socket() as occupied:
        occupied.bind(("0.0.0.0", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        server = CompanionServer(FakeController(), FakeConfig(port))
        server.start()
        try:
            for _ in range(100):
                if server.status["state"] == "error":
                    break
                time.sleep(0.02)
            assert server.status["state"] == "error"
            assert server.status["error"]
        finally:
            server.stop()


def test_pcm_stream_starts_once_and_keeps_monotonic_frame_order(monkeypatch):
    class FakeSocket:
        closed = False

        def __init__(self):
            self.json = []
            self.binary = []

        async def send_json(self, payload):
            self.json.append(payload)

        async def send_bytes(self, payload):
            self.binary.append(payload)

    server = CompanionServer(FakeController(), FakeConfig(38474))
    socket_ = FakeSocket()
    server._clients["phone"] = socket_
    server._client_contexts["phone"] = CompanionClient("phone", "Pixel", "alice")
    monkeypatch.setattr(server, "_decode_pcm16", lambda _audio: (b"\x00\x00" * 32, 24000, 1))
    stream_id = "7fc5d0c5-9178-4419-a3da-40b067173465"

    async def scenario():
        await server._publish_audio("phone", {
            "audio": b"first",
            "streamId": stream_id,
            "chunkSequence": 0,
        })
        await server._publish_audio("phone", {
            "audio": b"second",
            "streamId": stream_id,
            "chunkSequence": 1,
        })

    asyncio.run(scenario())
    assert [item["event"] for item in socket_.json] == ["tts.started"]
    assert int.from_bytes(socket_.binary[0][22:26], "big") == 0
    assert int.from_bytes(socket_.binary[1][22:26], "big") == 100_000


def test_mdns_publishes_instance_value_without_credentials(monkeypatch):
    captured = {}

    class FakeServiceInfo:
        def __init__(self, service_type, name, **kwargs):
            captured.update(service_type=service_type, name=name, **kwargs)

    class FakeZeroconf:
        def register_service(self, info):
            captured["registered"] = info

        def unregister_service(self, info):
            pass

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "zeroconf", SimpleNamespace(ServiceInfo=FakeServiceInfo, Zeroconf=FakeZeroconf))
    monkeypatch.setattr(companion_security, "local_host_candidates", lambda: ["127.0.0.1"])
    config = FakeConfig(38474)
    server = CompanionServer(FakeController(), config)

    server._start_mdns(38474)

    properties = captured["properties"]
    assert properties[b"instance"].decode("utf-8") == server.security.instance_id()
    assert set(properties) == {b"instance", b"name", b"v"}
    server._stop_mdns()
