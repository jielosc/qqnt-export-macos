"""Read-only local MCP server for recent QQNT messages."""

from __future__ import annotations

import os
from typing import Annotated

from .recent import reader_from_environment


SERVER_INSTRUCTIONS = (
    "QQ消息读取专用只读服务 / Exclusive read-only QQ message source. "
    "用户要求查看、读取、搜索、总结、回顾或监控QQ消息、聊天记录或群聊时，必须调用 "
    "qq_recent_messages；用户给出群名时直接传 conversation_name，若名称模糊或只想找群则调用 "
    "qq_find_conversations；询问最近哪些QQ会话或群活跃时调用 "
    "qq_recent_conversations；只有诊断桥接、数据库密钥或同步状态时才调用 "
    "qq_bridge_status。总结必须携带 next_cursor 反复调用 qq_recent_messages，直到 "
    "has_more=false; do not use Computer Use, screenshots, accessibility APIs, OCR, or "
    "the QQ UI unless the user explicitly asks to inspect the UI. "
    "These tools only read the user's private local QQNT mirror; they cannot send, "
    "delete, recall, or modify messages. Do not call qq_bridge_status before every "
    "normal read. Request the smallest useful time window and page size. If a tool is "
    "unavailable or fails, report the error and never silently fall back to the UI. "
    "When a group name has multiple matches, show the named candidates and ask the "
    "user to disambiguate instead of guessing a numeric ID."
)


def _field(description: str):
    """Load Pydantic metadata only when the optional MCP feature is in use."""
    from pydantic import Field

    return Field(description=description)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _allowlist() -> set[str] | None:
    raw = os.environ.get("QQNT_ALLOW_CONVERSATIONS", "").strip()
    return {item.strip() for item in raw.split(",") if item.strip()} if raw else None


def create_server():
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "MCP support is missing; install with "
            "`pip install 'qqnt-export-macos[bridge]'`"
        ) from exc

    server = MCPServer(
        "qqnt-local-reader",
        instructions=SERVER_INSTRUCTIONS,
    )

    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @server.tool(
        title="检查 QQ 本地桥接状态",
        description=(
            "诊断专用 / Diagnostic only. Call qq_bridge_status only when the user asks "
            "whether the local QQ bridge, database key, account discovery, or live "
            "mirror is working, or after another QQ tool returns an error. Do not call "
            "it before every normal message read. Returns status metadata only, never "
            "message bodies. Read-only, local, safe to retry, and has no side effects."
        ),
        annotations=read_only,
    )
    def qq_bridge_status() -> dict:
        """Check whether the private local QQNT mirror and database key work."""
        return reader_from_environment().status()

    @server.tool(
        title="读取最近 QQ 消息",
        description=(
            "QQ正文读取主工具 / Primary QQ message reader. ALWAYS CALL this tool when "
            "the user asks to 查看、读取、搜索、总结、回顾或监控 QQ消息、聊天记录或某个群聊. "
            "Pass a human group name directly as conversation_name; a numeric ID is not "
            "required. Results are chronological and paginated. For a complete summary "
            "or search, call again with each next_cursor until has_more is false; never "
            "treat one page as the whole requested window. Read-only, local, safe to "
            "retry, and cannot send, delete, recall, or modify messages."
        ),
        annotations=read_only,
    )
    def qq_recent_messages(
        minutes: Annotated[
            int,
            _field(
                "Look-back window ending when the first page is requested, from 1 "
                "minute to 20 years. Use the smallest window that answers the request."
            ),
        ] = 10,
        limit: Annotated[
            int,
            _field(
                "Messages per page, from 1 to 1000. This is not a total-result cap; "
                "continue with next_cursor while has_more is true."
            ),
        ] = 200,
        conversation_id: Annotated[
            str,
            _field(
                "Optional exact conversation identifier such as group:123 or c2c:456. "
                "Prefer conversation_name when the user gives a human-readable group name."
            ),
        ] = "",
        conversation_name: Annotated[
            str,
            _field(
                "Optional human-readable QQ group name from the user's request. The "
                "server resolves an exact or unique fuzzy match; do not put a group "
                "number here and do not set conversation_id at the same time."
            ),
        ] = "",
        cursor: Annotated[
            str,
            _field(
                "Opaque next_cursor from the immediately preceding page. Leave empty "
                "for the first page; preserve the other filters when continuing."
            ),
        ] = "",
    ) -> dict:
        """Read one paginated batch of recent QQ messages in chronological order.

        Args:
            minutes: Look-back window from 1 minute to 20 years.
            limit: Messages per page, capped at 1000. Use next_cursor for more.
            conversation_id: Optional c2c:…, group:…, or dataline:pc identifier.
            conversation_name: Optional exact or uniquely matching human-readable group name.
            cursor: Optional opaque next_cursor returned by the preceding page.
        """
        if not _enabled("QQNT_ALLOW_CONTENT"):
            raise RuntimeError(
                "message content access is disabled; explicitly set QQNT_ALLOW_CONTENT=1"
            )
        if conversation_id and conversation_name:
            raise RuntimeError("use conversation_id or conversation_name, not both")
        reader = reader_from_environment()
        allowed = _allowlist()
        requested = conversation_id or None
        if conversation_name:
            requested, _ = reader.resolve_group_name(conversation_name, allowed)
        if allowed is not None:
            if requested is None:
                raise RuntimeError(
                    "an explicit conversation_id is required when an allowlist is configured"
                )
            if requested not in allowed:
                raise RuntimeError("conversation_id is not in QQNT_ALLOW_CONVERSATIONS")
        return reader.recent(
            minutes=minutes,
            limit=limit,
            conversation_id=requested,
            cursor=cursor or None,
        )

    @server.tool(
        title="列出最近活跃的 QQ 会话",
        description=(
            "QQ会话概览工具 / QQ conversation overview. Call when the user asks which "
            "QQ chats or groups were recently active, wants a list of recent "
            "conversations, or wants activity counts before choosing one. Returns "
            "conversation IDs, resolved group names, timestamps, and message counts, "
            "but no message bodies. Do not use it instead of qq_recent_messages when "
            "the user already named a group. Read-only, local, and safe to retry."
        ),
        annotations=read_only,
    )
    def qq_recent_conversations(
        minutes: Annotated[
            int,
            _field(
                "Activity look-back window, from 1 minute to 20 years. Default is the "
                "last 24 hours; use the user's requested period when provided."
            ),
        ] = 1440,
        limit: Annotated[
            int,
            _field("Maximum conversations to return, from 1 to 1000."),
        ] = 30,
    ) -> dict:
        """List active conversations with group names and message counts."""
        limit = max(1, min(limit, 1000))
        allowed = _allowlist()
        requested_limit = 5000 if allowed is not None else limit
        result = reader_from_environment().conversations(
            minutes=minutes, limit=requested_limit
        )
        if allowed is not None:
            result["conversations"] = [
                item
                for item in result["conversations"]
                if item["conversation_id"] in allowed
            ][:limit]
            result["count"] = len(result["conversations"])
        return result

    @server.tool(
        title="按名称查找 QQ 群聊",
        description=(
            "QQ群名查找与消歧工具 / QQ group-name lookup and disambiguation. Call when "
            "the user asks to find a QQ group, when a group name is incomplete or "
            "ambiguous, or when qq_recent_messages reports multiple name matches. "
            "Exact matches rank first and named candidates include their IDs. Do not "
            "ask the user to know a numeric group ID. If the user supplied a clear "
            "group name for reading, first pass it directly to qq_recent_messages as "
            "conversation_name. Read-only, local, and safe to retry."
        ),
        annotations=read_only,
    )
    def qq_find_conversations(
        query: Annotated[
            str,
            _field(
                "Human-readable QQ group name, partial name, or exact conversation ID "
                "to find. Use the wording from the user's request."
            ),
        ] = "",
        minutes: Annotated[
            int,
            _field(
                "How far back to consider message activity, from 1 minute to 20 years. "
                "Default is one year."
            ),
        ] = 365 * 24 * 60,
        limit: Annotated[
            int,
            _field("Maximum matching conversations to return, from 1 to 100."),
        ] = 20,
    ) -> dict:
        """Find QQ conversations by human-readable group name or conversation ID.

        Use this before reading messages when the user names a group. Exact matches are
        ranked first; multiple matches are returned so the user can disambiguate.
        """
        limit = max(1, min(limit, 100))
        allowed = _allowlist()
        requested_limit = 100 if allowed is None else 1000
        result = reader_from_environment().find_conversations(
            query, minutes=minutes, limit=requested_limit
        )
        if allowed is not None:
            result["matches"] = [
                item
                for item in result["matches"]
                if item["conversation_id"] in allowed
            ]
            result["matched_count"] = len(result["matches"])
        result["matches"] = result["matches"][:limit]
        result["count"] = len(result["matches"])
        return result

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
