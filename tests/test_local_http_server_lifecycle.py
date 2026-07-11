from pathlib import Path


def test_local_http_request_threads_do_not_block_server_close():
    from ai_status_server import _LocalThreadingHTTPServer as AiServer
    from chat_integration_server import _LocalThreadingHTTPServer as ChatServer

    assert AiServer.daemon_threads is True
    assert ChatServer.daemon_threads is True


def test_local_http_request_body_reads_have_a_timeout():
    for file_name in ("ai_status_server.py", "chat_integration_server.py"):
        source = Path(file_name).read_text(encoding="utf-8")
        assert "self.connection.settimeout(" in source
        assert "except TimeoutError:" in source


def test_chat_overlay_queue_acceptance_does_not_clear_persisted_unread():
    source = Path("main.py").read_text(encoding="utf-8")
    handler = source.split("    def handle_chat_integration_message", 1)[1].split(
        "    def handle_chat_integration_read", 1
    )[0]

    assert "overlay_delivered = broadcast_chat_overlay(event, stored)" in handler
    assert "mark_external_chat_read" not in handler
