"""Read-only local MCP server for recent QQNT messages."""

from __future__ import annotations

import os

from .recent import reader_from_environment


SERVER_INSTRUCTIONS = (
    "Exclusive read-only source for the user's local QQNT history. "
    "For every request to read, inspect, summarize, search, check, or monitor QQ "
    "messages or conversations, use these tools and do not use Computer Use, screen "
    "capture, accessibility APIs, OCR, or the QQ UI. Only inspect the QQ UI when the "
    "user explicitly requests UI inspection. If a tool is unavailable or fails, report "
    "that error; never silently fall back to the UI. Never claim these tools can send, "
    "delete, recall, or modify QQ messages. Request the smallest useful time window "
    "and result limit. When the user names a group, resolve it with "
    "qq_find_conversations or the conversation_name argument; never ask them to know a "
    "group number. For summaries, follow next_cursor until has_more is false and "
    "summarize incrementally; never present the first page as the complete window."
)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _allowlist() -> set[str] | None:
    raw = os.environ.get("QQNT_ALLOW_CONVERSATIONS", "").strip()
    return {item.strip() for item in raw.split(",") if item.strip()} if raw else None


def create_server():
    try:
        from mcp.server import MCPServer
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "MCP support is missing; install with "
            "`pip install 'qqnt-export-macos[bridge]'`"
        ) from exc

    server = MCPServer(
        "qqnt-local-reader",
        instructions=SERVER_INSTRUCTIONS,
    )

    @server.tool()
    def qq_bridge_status() -> dict:
        """Check whether the private local QQNT mirror and database key work."""
        return reader_from_environment().status()

    @server.tool()
    def qq_recent_messages(
        minutes: int = 10,
        limit: int = 200,
        conversation_id: str = "",
        conversation_name: str = "",
        cursor: str = "",
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

    @server.tool()
    def qq_recent_conversations(minutes: int = 1440, limit: int = 30) -> dict:
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

    @server.tool()
    def qq_find_conversations(
        query: str = "", minutes: int = 365 * 24 * 60, limit: int = 20
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
