import base64
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import public_network
from chat_window.chat_window import AttachmentImportWorker


_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _BytesResponse:
    def __init__(self, payload: bytes, content_type: str = "image/png"):
        self._payload = payload
        self._position = 0
        self.closed = False
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(payload)),
        }

    def read(self, amount: int | None = None) -> bytes:
        if amount is None:
            amount = len(self._payload) - self._position
        start = self._position
        self._position = min(len(self._payload), self._position + amount)
        return self._payload[start:self._position]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class _TestImageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.paths.append(self.path)
        self.server.host_headers.append(self.headers.get("Host"))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{self.server.server_port}/secret.png",
            )
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(_PNG_BYTES)))
        self.end_headers()
        self.wfile.write(_PNG_BYTES)

    def log_message(self, _format, *_args):
        pass


class PublicNetworkSecurityTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _TestImageHandler)
        self.server.paths = []
        self.server.host_headers = []
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def _local_endpoint(self):
        return public_network._ResolvedEndpoint(
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            ("127.0.0.1", self.server.server_port),
        )

    def test_rejects_a_host_if_any_dns_answer_is_not_public(self):
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 80)),
        ]
        with patch("public_network.socket.getaddrinfo", return_value=records):
            with self.assertRaises(PermissionError):
                public_network._resolve_public_endpoints("images.example", 80)

    def test_rejects_multicast_even_when_ipaddress_marks_it_global(self):
        records = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("224.0.0.1", 80)),
        ]
        with patch("public_network.socket.getaddrinfo", return_value=records):
            with self.assertRaises(PermissionError):
                public_network._resolve_public_endpoints("images.example", 80)

    def test_rejects_an_invalid_zero_port(self):
        with self.assertRaisesRegex(ValueError, "invalid port"):
            public_network.open_public_url("http://images.example:0/image.png")

    def test_connects_to_the_exact_validated_endpoint(self):
        endpoint = self._local_endpoint()
        url = f"http://images.example:{self.server.server_port}/image.png"
        with patch("public_network._resolve_public_endpoints", return_value=(endpoint,)):
            response, final_url = public_network.open_public_url(url)
            with response:
                payload = response.read()

        self.assertEqual(payload, _PNG_BYTES)
        self.assertEqual(final_url, url)
        self.assertEqual(self.server.paths, ["/image.png"])
        self.assertEqual(
            self.server.host_headers,
            [f"images.example:{self.server.server_port}"],
        )

    def test_revalidates_and_blocks_a_private_redirect(self):
        endpoint = self._local_endpoint()
        original_resolver = public_network._resolve_public_endpoints

        def resolve(host, port):
            if host == "images.example":
                return (endpoint,)
            return original_resolver(host, port)

        url = f"http://images.example:{self.server.server_port}/redirect"
        with patch("public_network._resolve_public_endpoints", side_effect=resolve):
            with self.assertRaises(PermissionError):
                public_network.open_public_url(url)

        self.assertEqual(self.server.paths, ["/redirect"])


class RemoteImageImportSecurityTests(unittest.TestCase):
    def test_rejects_loopback_image_url_before_connecting(self):
        with TemporaryDirectory() as target_dir:
            worker = AttachmentImportWorker([], Path(target_dir))
            with self.assertRaises(PermissionError):
                worker._import_remote(
                    {"url": "http://127.0.0.1:65535/private.png"},
                    0,
                    1,
                )
            self.assertEqual(list(Path(target_dir).iterdir()), [])

    def test_rejects_and_removes_content_that_is_not_an_image(self):
        response = _BytesResponse(b"internal service secret", "image/png")
        url = "https://images.example/not-really.png"
        with TemporaryDirectory() as target_dir:
            worker = AttachmentImportWorker([], Path(target_dir))
            with patch(
                "chat_window.chat_window.open_public_url",
                return_value=(response, url),
            ):
                with self.assertRaisesRegex(OSError, "readable image"):
                    worker._import_remote({"url": url}, 0, 1)

            self.assertTrue(response.closed)
            self.assertEqual(list(Path(target_dir).iterdir()), [])

    def test_imports_a_decodable_supported_image(self):
        response = _BytesResponse(_PNG_BYTES)
        url = "https://images.example/pixel.png"
        with TemporaryDirectory() as target_dir:
            worker = AttachmentImportWorker([], Path(target_dir))
            with patch(
                "chat_window.chat_window.open_public_url",
                return_value=(response, url),
            ):
                result = worker._import_remote({"url": url}, 0, 1)

            self.assertEqual(result["mime"], "image/png")
            self.assertEqual(result["name"], "pixel.png")
            self.assertEqual(Path(result["path"]).read_bytes(), _PNG_BYTES)


if __name__ == "__main__":
    unittest.main()
