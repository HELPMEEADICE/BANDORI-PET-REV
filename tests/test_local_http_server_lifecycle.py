import json
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from local_port_security import ensure_local_port_token


def test_local_http_request_threads_do_not_block_server_close():
    from local_http_server import LocalThreadingHTTPServer

    assert LocalThreadingHTTPServer.daemon_threads is True


def test_missing_local_port_token_is_generated_and_persisted():
    config = Mock()
    config.get.return_value = ""

    with patch("local_port_security.secrets.token_urlsafe", return_value="generated-token"):
        token = ensure_local_port_token(config, "chat_integration_token")

    assert token == "generated-token"
    config.set.assert_called_once_with("chat_integration_token", "generated-token")
    config.save.assert_called_once_with()


def test_existing_local_port_token_is_reused():
    config = Mock()
    config.get.return_value = " existing-token "

    token = ensure_local_port_token(config, "ai_status_token")

    assert token == "existing-token"
    config.set.assert_not_called()
    config.save.assert_not_called()


def test_local_http_request_body_reads_have_a_timeout():
    base_source = Path("local_http_server.py").read_text(encoding="utf-8")
    assert "self.connection.settimeout(" in base_source
    for file_name in ("ai_status_server.py", "chat_integration_server.py"):
        source = Path(file_name).read_text(encoding="utf-8")
        assert "except TimeoutError:" in source


def test_shared_http_base_preserves_auth_and_cors_behavior():
    from ai_status_server import AiStatusHttpServer

    events = []
    server = AiStatusHttpServer(0, "secret", events.append)
    server.start()
    port = server._server.server_address[1]
    try:
        health = urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        assert health.status == 200
        assert health.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1"

        body = json.dumps({"kind": "test"}).encode("utf-8")
        unauthorized = urllib.request.Request(
            f"http://127.0.0.1:{port}/ai-event",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(unauthorized, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("missing token must be rejected")

        authorized = urllib.request.Request(
            f"http://127.0.0.1:{port}/ai-event",
            data=body,
            headers={"Content-Type": "application/json", "X-Bandori-Token": "secret"},
            method="POST",
        )
        response = urllib.request.urlopen(authorized, timeout=2)
        assert response.status == 200
        assert events == [{"kind": "test"}]
    finally:
        server.stop()


def test_chat_overlay_queue_acceptance_does_not_clear_persisted_unread():
    source = Path("main.py").read_text(encoding="utf-8")
    handler = source.split("    def handle_chat_integration_message", 1)[1].split(
        "    def handle_chat_integration_read", 1
    )[0]

    assert "overlay_delivered = broadcast_chat_overlay(event, stored)" in handler
    assert "mark_external_chat_read" not in handler
