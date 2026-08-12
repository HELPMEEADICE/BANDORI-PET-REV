from __future__ import annotations

import asyncio
import io
import json
import ssl
import socket
import struct
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from companion_controller import CompanionProtocolError, PROTOCOL_VERSION
from companion_security import AuthenticatedDevice, CompanionSecurityStore


@dataclass(frozen=True, slots=True)
class CompanionClient:
    device_id: str
    name: str
    profile_key: str


class CompanionServer:
    def __init__(self, controller, config):
        self.controller = controller
        self.config = config
        self.security = CompanionSecurityStore(config)
        self._thread = None
        self._loop = None
        self._runner = None
        self._clients: dict[str, object] = {}
        self._client_contexts: dict[str, CompanionClient] = {}
        self._pairing_attempts = defaultdict(deque)
        self._sequence = 0
        self._status = "stopped"
        self._error = ""
        self._zeroconf = None
        self._service_info = None
        controller.event_ready.connect(self.publish_event)
        controller.audio_ready.connect(self.publish_audio)

    @property
    def status(self) -> dict:
        return {"state": self._status, "error": self._error, "clients": len(self._clients)}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._thread_main, name="BandoriCompanionWSS", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            try:
                future.result(timeout=3)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._thread = None
        self._status = "stopped"

    def revalidate_clients(self) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._revalidate_clients(), loop)

    async def _revalidate_clients(self) -> None:
        try:
            self.security.reload()
            authorized = {
                str(item.get("id", ""))
                for item in self.config.get("companion_paired_devices", [])
                if isinstance(item, dict)
            }
        except Exception:
            return
        for device_id, ws in list(self._clients.items()):
            if device_id in authorized:
                continue
            self._clients.pop(device_id, None)
            self._client_contexts.pop(device_id, None)
            try:
                await ws.close(code=4003, message=b"authorization revoked")
            except Exception:
                pass

    def _thread_main(self):
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async())
            loop.run_forever()
        except Exception as exc:
            self._status = "error"
            self._error = str(exc)
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            except Exception:
                pass
            loop.close()
            self._loop = None

    async def _start_async(self):
        try:
            from aiohttp import web
        except ImportError as exc:
            raise RuntimeError("aiohttp is required for desktop companion mode") from exc
        cert_path, key_path, _pin = self.security.ensure_tls_identity()
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.load_cert_chain(str(cert_path), str(key_path))
        application = web.Application(client_max_size=64 * 1024)
        application.router.add_get("/v1/ws", self._websocket)
        self._runner = web.AppRunner(application, access_log=None)
        await self._runner.setup()
        port = max(1024, min(65535, int(self.config.get("companion_port", 38474) or 38474)))
        site = web.TCPSite(self._runner, "0.0.0.0", port, ssl_context=ssl_context)
        await site.start()
        self._start_mdns(port)
        self._status = "running"
        self._error = ""

    async def _shutdown(self):
        self._stop_mdns()
        for ws in list(self._clients.values()):
            try:
                await ws.close(code=1001, message=b"server shutdown")
            except Exception:
                pass
        self._clients.clear()
        self._client_contexts.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        if self._status != "error":
            self._status = "stopped"

    def _start_mdns(self, port: int) -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf
            from companion_security import local_host_candidates

            addresses = []
            for host in local_host_candidates():
                try:
                    family = socket.AF_INET6 if ":" in host else socket.AF_INET
                    addresses.append(socket.inet_pton(family, host))
                except OSError:
                    continue
            if not addresses:
                return
            instance_id = self.security.instance_id()
            device_name = str(self.config.get("companion_device_name", "") or socket.gethostname() or "BandoriPet")
            safe_name = device_name.replace(".", "-")[:48]
            service_type = "_bandoripet._tcp.local."
            info = ServiceInfo(
                service_type,
                f"{safe_name}-{instance_id[:8]}.{service_type}",
                addresses=addresses,
                port=int(port),
                properties={
                    b"instance": instance_id.encode("utf-8"),
                    b"name": device_name.encode("utf-8"),
                    b"v": str(PROTOCOL_VERSION).encode("ascii"),
                },
                server=f"bandoripet-{instance_id[:8]}.local.",
            )
            zeroconf = Zeroconf()
            zeroconf.register_service(info)
            self._zeroconf = zeroconf
            self._service_info = info
        except Exception:
            self._zeroconf = None
            self._service_info = None

    def _stop_mdns(self) -> None:
        zeroconf = self._zeroconf
        info = self._service_info
        self._zeroconf = None
        self._service_info = None
        if zeroconf is None:
            return
        try:
            if info is not None:
                zeroconf.unregister_service(info)
        except Exception:
            pass
        try:
            zeroconf.close()
        except Exception:
            pass

    async def _websocket(self, request):
        from aiohttp import WSMsgType, web
        if request.headers.get("Origin"):
            raise web.HTTPForbidden(text="Browser origins are not accepted")
        ws = web.WebSocketResponse(heartbeat=20, receive_timeout=65, max_msg_size=64 * 1024)
        await ws.prepare(request)
        device = self._authenticate_headers(request.headers)
        auth_attempted = bool(request.headers.get("X-Bandori-Device") or request.headers.get("Authorization"))
        if auth_attempted and device is None:
            await ws.close(code=4003, message=b"authentication failed")
            return ws
        client = CompanionClient(device.device_id, device.name, device.profile_key) if device else None
        if client is not None:
            old = self._clients.get(client.device_id)
            self._clients[client.device_id] = ws
            self._client_contexts[client.device_id] = client
            if old is not None and old is not ws:
                await old.close(code=4001, message=b"replaced")
            hello = await asyncio.wrap_future(self.controller.submit_hello(client))
            await self._send_event(ws, "session.hello", hello)
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    if message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
                    continue
                try:
                    payload = json.loads(message.data)
                except (TypeError, json.JSONDecodeError):
                    await self._send_error(ws, None, "INVALID_JSON")
                    continue
                if client is None:
                    paired = await self._handle_pairing(ws, payload, request.remote)
                    if paired:
                        await ws.close(code=1000, message=b"reconnect authenticated")
                        break
                    continue
                await self._handle_request(ws, client, payload)
        finally:
            if client is not None and self._clients.get(client.device_id) is ws:
                self._clients.pop(client.device_id, None)
                self._client_contexts.pop(client.device_id, None)
        return ws

    def _authenticate_headers(self, headers) -> AuthenticatedDevice | None:
        device_id = str(headers.get("X-Bandori-Device", "") or "")
        authorization = str(headers.get("Authorization", "") or "")
        credential = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not device_id or not credential:
            return None
        return self.security.authenticate(device_id, credential)

    async def _handle_pairing(self, ws, payload: dict, remote_address: str | None = None) -> bool:
        request_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("v") != PROTOCOL_VERSION or payload.get("method") != "pair.request":
            await self._send_error(ws, request_id, "AUTH_REQUIRED")
            return False
        params = payload.get("params", {})
        peer = str(remote_address or "unknown")
        attempts = self._pairing_attempts[peer]
        now = time.monotonic()
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        if len(attempts) >= 5:
            await self._send_error(ws, request_id, "RATE_LIMITED")
            return False
        attempts.append(now)
        try:
            device = self.security.pair_device(
                bootstrap_token=str(params.get("token", "") or ""),
                device_id=str(params.get("deviceId", "") or ""),
                device_name=str(params.get("deviceName", "Android") or "Android"),
                credential=str(params.get("credential", "") or ""),
            )
        except (PermissionError, ValueError) as exc:
            await self._send_error(ws, request_id, str(exc))
            return False
        await self._send_response(ws, request_id, {
            "deviceId": device.device_id,
            "profileKey": device.profile_key,
            "reconnect": True,
        })
        return True

    async def _handle_request(self, ws, client: CompanionClient, payload: dict):
        request_id = payload.get("id") if isinstance(payload, dict) else None
        method = payload.get("method") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("v") != PROTOCOL_VERSION
            or not isinstance(request_id, str)
            or not request_id
            or len(request_id) > 128
            or not isinstance(method, str)
            or not method
            or len(method) > 80
        ):
            await self._send_error(ws, request_id, "INVALID_REQUEST")
            return
        future = self.controller.submit(client, payload)
        try:
            result = await asyncio.wrap_future(future)
        except CompanionProtocolError as exc:
            await self._send_error(ws, request_id, exc.code, str(exc))
        except Exception:
            await self._send_error(ws, request_id, "INTERNAL_ERROR")
        else:
            await self._send_response(ws, request_id, result)

    async def _send_response(self, ws, request_id, result):
        await ws.send_json({"v": PROTOCOL_VERSION, "id": request_id, "ok": True, "result": result})

    async def _send_error(self, ws, request_id, code: str, message: str = ""):
        await ws.send_json({
            "v": PROTOCOL_VERSION,
            "id": request_id,
            "ok": False,
            "error": {"code": str(code or "ERROR"), "message": str(message or code or "ERROR")[:500]},
        })

    async def _send_event(self, ws, event: str, data):
        self._sequence += 1
        await ws.send_json({"v": PROTOCOL_VERSION, "seq": self._sequence, "event": event, "data": data})

    def publish_event(self, event: str, data, target_device) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._publish_event(event, data, target_device), loop)

    async def _publish_event(self, event: str, data, target_device):
        targets = [(target_device, self._clients.get(str(target_device)))] if target_device else list(self._clients.items())
        active_profile = str(getattr(self.controller, "active_profile_key", "default") or "default")
        for device_id, ws in targets:
            if ws is None or ws.closed:
                continue
            try:
                client = self._client_contexts.get(str(device_id))
                profile_available = client is not None and client.profile_key == active_profile
                if event == "profile.changed":
                    if profile_available:
                        hello = await asyncio.wrap_future(self.controller.submit_hello(client))
                        await self._send_event(ws, "session.hello", hello)
                    else:
                        await self._send_event(ws, "profile.changed", {"profileAvailable": False})
                elif profile_available:
                    await self._send_event(ws, event, data)
            except Exception:
                pass

    def publish_audio(self, device_id: str, payload: dict) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self._publish_audio(device_id, payload), loop)

    async def _publish_audio(self, device_id: str, payload: dict):
        if not str(device_id or ""):
            for target in list(self._clients):
                await self._publish_audio(target, payload)
            return
        ws = self._clients.get(str(device_id or ""))
        if ws is None or ws.closed:
            return
        client = self._client_contexts.get(str(device_id or ""))
        active_profile = str(getattr(self.controller, "active_profile_key", "default") or "default")
        if client is None or client.profile_key != active_profile:
            return
        raw = payload.get("audio", b"")
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            return
        try:
            pcm, sample_rate, channels = await asyncio.to_thread(self._decode_pcm16, bytes(raw))
        except Exception as exc:
            await self._send_event(ws, "tts.error", {"message": str(exc)[:240]})
            return
        stream_id = bytes.fromhex(str(payload.get("streamId", "")).replace("-", ""))[:16]
        if len(stream_id) != 16:
            return
        chunk_sequence = int(payload.get("chunkSequence", 0) or 0)
        if chunk_sequence == 0:
            await self._send_event(ws, "tts.started", {
                "streamId": str(payload.get("streamId")),
                "sampleRate": sample_rate,
                "channels": channels,
                "encoding": "pcm_s16le",
                "characterId": payload.get("characterId", ""),
                "text": payload.get("text", ""),
            })
        for frame_index, offset in enumerate(range(0, len(pcm), 32 * 1024)):
            sequence = chunk_sequence * 100_000 + frame_index
            frame = (
                b"BPAT"
                + bytes((1, 1))
                + stream_id
                + struct.pack(">I", sequence)
                + pcm[offset: offset + 32 * 1024]
            )
            await ws.send_bytes(frame)

    @staticmethod
    def _decode_pcm16(audio: bytes) -> tuple[bytes, int, int]:
        import numpy as np
        import soundfile as sf
        data, sample_rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
        data = np.clip(data, -1.0, 1.0)
        pcm = (data * 32767.0).astype("<i2", copy=False).tobytes()
        return pcm, int(sample_rate), int(data.shape[1])
