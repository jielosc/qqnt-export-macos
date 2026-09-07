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
        "qq_find_conversations",
        "qq_recent_conversations",
        "qq_recent_messages",
    }


def test_server_instructions_are_self_contained_in_first_512_characters():
    first_512 = mcp_server.SERVER_INSTRUCTIONS[:512]
    assert "查看、读取、搜索、总结、回顾或监控" in first_512
    assert "qq_recent_messages" in first_512
    assert "qq_find_conversations" in first_512
    assert "qq_recent_conversations" in first_512
    assert "qq_bridge_status" in first_512
    assert "next_cursor" in first_512
    assert "has_more=false" in first_512
    assert "do not use Computer Use" in first_512


def test_mcp_publishes_intent_descriptions_schemas_and_read_only_hints():
    mcp = pytest.importorskip("mcp")

    async def inspect_tools():
        async with mcp.Client(mcp_server.create_server()) as client:
            result = await client.list_tools()
            return {tool.name: tool for tool in result.tools}

    tools = asyncio.run(inspect_tools())
    messages = tools["qq_recent_messages"]
    assert "ALWAYS CALL" in messages.description
    assert "conversation_name" in messages.description
    assert "next_cursor" in messages.description
    assert "has_more is false" in messages.description
    assert messages.annotations.read_only_hint is True
    assert messages.annotations.destructive_hint is False
    assert messages.annotations.idempotent_hint is True
    assert messages.annotations.open_world_hint is False

    properties = messages.input_schema["properties"]
    for name in ("minutes", "limit", "conversation_id", "conversation_name", "cursor"):
        assert properties[name]["description"]
    assert "not a total-result cap" in properties["limit"]["description"]
    assert "human-readable QQ group name" in properties["conversation_name"]["description"]

    assert "Diagnostic only" in tools["qq_bridge_status"].description
    assert "Do not call" in tools["qq_bridge_status"].description
    assert "which QQ chats or groups were recently active" in tools[
        "qq_recent_conversations"
    ].description
    assert "ambiguous" in tools["qq_find_conversations"].description


def test_mcp_refuses_content_without_explicit_switch(monkeypatch):
    mcp = pytest.importorskip("mcp")
    monkeypatch.delenv("QQNT_ALLOW_CONTENT", raising=False)

    async def call_recent():
        async with mcp.Client(mcp_server.create_server()) as client:
            return await client.call_tool("qq_recent_messages", {})

    assert asyncio.run(call_recent()).is_error
