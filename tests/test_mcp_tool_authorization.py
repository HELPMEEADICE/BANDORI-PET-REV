import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bandori_tools import local_tools, mcp_bridge


TOOLS = [
    {"name": "read_file", "inputSchema": {"type": "object"}},
    {"name": "write_file", "inputSchema": {"type": "object"}},
]


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setattr(mcp_bridge, "_list_http_tools", lambda *_args: copy.deepcopy(TOOLS))
    return {
        "llm_mcp_enabled": True,
        "llm_mcp_use_native": False,
        "llm_mcp_servers": [{
            "label": "files", "transport": "http", "url": "https://example.invalid/mcp",
            "enabled": True, "require_approval": "never", "allowed_tools": [],
        }],
    }


@pytest.fixture
def transport(monkeypatch):
    call = Mock(return_value="executed")
    monkeypatch.setattr(mcp_bridge, "_call_http_tool", call)
    return call


def discover(config):
    return {tool["function"]["name"] for tool in mcp_bridge.mcp_proxy_tools(config)}


@pytest.mark.parametrize("change", [
    lambda cfg: cfg.update(llm_mcp_enabled=False),
    lambda cfg: cfg.update(llm_mcp_servers=[]),
    lambda cfg: cfg["llm_mcp_servers"][0].update(enabled=False),
    lambda cfg: cfg["llm_mcp_servers"][0].update(require_approval="always"),
    lambda cfg: cfg["llm_mcp_servers"][0].update(allowed_tools=["read_file"]),
    lambda cfg: cfg["llm_mcp_servers"][0].update(url="https://changed.invalid/mcp"),
    lambda cfg: cfg["llm_mcp_servers"][0].update(env={"TOKEN": "changed"}),
])
def test_revoked_or_changed_mcp_permissions_block_cached_tool(config, transport, change):
    assert "mcp__files__write_file" in discover(config)
    change(config)

    result = local_tools.run_local_tool_call("mcp__files__write_file", {}, config)

    transport.assert_not_called()
    assert "executed" not in result["content"]


def test_disabled_discovery_discards_previous_bindings(config, transport):
    discover(config)
    config["llm_mcp_enabled"] = False
    assert discover(config) == set()
    config["llm_mcp_enabled"] = True

    local_tools.run_local_tool_call("mcp__files__write_file", {}, config)

    transport.assert_not_called()


def test_tool_omitted_by_current_allowlist_cannot_be_called(config, transport):
    discover(config)
    config["llm_mcp_servers"][0]["allowed_tools"] = ["read_file"]
    assert discover(config) == {"mcp__files__read_file"}

    local_tools.run_local_tool_call("mcp__files__write_file", {}, config)
    transport.assert_not_called()
    assert local_tools.run_local_tool_call("mcp__files__read_file", {}, config)["content"] == "executed"
    assert transport.call_args.args[1] == "read_file"


def test_requests_with_same_tool_names_keep_independent_server_bindings(config, transport):
    other = copy.deepcopy(config)
    other["llm_mcp_servers"][0]["url"] = "https://other.invalid/mcp"
    discover(config)
    discover(other)

    for current in (config, other, config):
        local_tools.run_local_tool_call("mcp__files__write_file", {}, current)

    assert [call.args[0]["url"] for call in transport.call_args_list] == [
        "https://example.invalid/mcp", "https://other.invalid/mcp", "https://example.invalid/mcp",
    ]


def test_fresh_request_cannot_borrow_another_requests_tools(config, transport):
    fresh = copy.deepcopy(config)
    discover(config)

    local_tools.run_local_tool_call("mcp__files__write_file", {}, fresh)

    transport.assert_not_called()


@pytest.mark.parametrize("approval", ["always", "", "auto", None])
def test_discovered_tools_require_explicit_execution_approval(config, transport, approval):
    config["llm_mcp_servers"][0]["require_approval"] = approval
    discover(config)

    result = local_tools.run_local_tool_call("mcp__files__write_file", {}, config)

    transport.assert_not_called()
    assert "blocked by approval" in result["content"]


def test_responses_proxy_tools_preserve_request_authorization(config, transport):
    tools = local_tools.responses_tools(False, config)
    assert any(tool.get("name") == "mcp__files__write_file" for tool in tools)

    result = local_tools.run_local_tool_call("mcp__files__write_file", {"text": "hello"}, dict(config))

    assert result["content"] == "executed"
    transport.assert_called_once_with(config["llm_mcp_servers"][0], "write_file", {"text": "hello"}, cancel_event=None)


def test_approved_stdio_tool_still_dispatches(config, monkeypatch):
    config["llm_mcp_servers"][0].update(transport="stdio", command="fake-server")
    call = Mock(return_value="stdio executed")
    monkeypatch.setattr(mcp_bridge, "_stdio_client", lambda _server: SimpleNamespace(
        list_tools=lambda _cancel: TOOLS, call_tool=call,
    ))
    local_tools.chat_completion_tools(False, config)

    result = local_tools.run_local_tool_call("mcp__files__write_file", {}, config)

    assert result["content"] == "stdio executed"
    call.assert_called_once_with("write_file", {}, cancel_event=None)


def test_native_only_tool_cannot_be_invoked_through_proxy(config, transport):
    config["llm_mcp_use_native"] = True
    tools = local_tools.responses_tools(False, config)
    assert any(tool.get("type") == "mcp" for tool in tools)

    local_tools.run_local_tool_call("mcp__files__write_file", {}, config)

    transport.assert_not_called()


def test_discovery_failure_returns_a_request_local_status_tool(config, transport, monkeypatch):
    monkeypatch.setattr(mcp_bridge, "_list_http_tools", Mock(side_effect=RuntimeError("offline")))
    assert discover(config) == {"mcp__files__status"}

    result = local_tools.run_local_tool_call("mcp__files__status", {}, config)

    assert "offline" in result["content"]
    transport.assert_not_called()


def test_cancelled_discovery_does_not_authorize_partially_discovered_tools(config, transport, monkeypatch):
    config["llm_mcp_servers"].append({**config["llm_mcp_servers"][0], "label": "second"})
    monkeypatch.setattr(mcp_bridge, "_list_http_tools", Mock(side_effect=[TOOLS, InterruptedError()]))
    assert discover(config) == set()

    local_tools.run_local_tool_call("mcp__files__write_file", {}, config)

    transport.assert_not_called()
