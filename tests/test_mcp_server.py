import asyncio

import pytest

from qqnt_export_macos import mcp_server


def test_content_gate_and_allowlist(monkeypatch):
    monkeypatch.delenv("QQNT_ALLOW_CONTENT", raising=False)
    monkeypatch.delenv("QQNT_ALLOW_CONVERSATIONS", raising=False)
    assert not mcp_server._enabled("QQNT_ALLOW_CONTENT")
    assert mcp_server._allowlist() is None

    monkeypatch.setenv("QQNT_ALLOW_CONTENT", "true")
    monkeypatch.setenv("QQNT_ALLOW_CONVERSATIONS", "c2c:1, group:2")
    assert mcp_server._enabled("QQNT_ALLOW_CONTENT")
    assert mcp_server._allowlist() == {"c2c:1", "group:2"}


def test_mcp_exposes_only_read_tools():
    mcp = pytest.importorskip("mcp")

    async def inspect_tools():
        async with mcp.Client(mcp_server.create_server()) as client:
            result = await client.list_tools()
            return {tool.name for tool in result.tools}

    assert asyncio.run(inspect_tools()) == {
        "qq_bridge_status",
        "qq_recent_conversations",
        "qq_recent_messages",
    }


def test_server_instructions_forbid_silent_ui_fallback():
    first_512 = mcp_server.SERVER_INSTRUCTIONS[:512]
    assert "do not use Computer Use" in first_512
    assert "never silently fall back to the UI" in first_512


def test_mcp_refuses_content_without_explicit_switch(monkeypatch):
    mcp = pytest.importorskip("mcp")
    monkeypatch.delenv("QQNT_ALLOW_CONTENT", raising=False)

    async def call_recent():
        async with mcp.Client(mcp_server.create_server()) as client:
            return await client.call_tool("qq_recent_messages", {})

    assert asyncio.run(call_recent()).is_error
