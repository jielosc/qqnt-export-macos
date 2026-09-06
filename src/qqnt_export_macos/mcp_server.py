"""Read-only local MCP server for recent QQNT messages."""

from __future__ import annotations

import os

from .recent import reader_from_environment


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
        instructions=(
            "Read-only access to the user's local QQNT recent-message mirror. "
            "Never claim this tool can send, delete, recall, or modify QQ messages. "
            "Request the smallest useful time window and result limit."
        ),
    )

    @server.tool()
    def qq_bridge_status() -> dict:
        """Check whether the private local QQNT mirror and database key work."""
        return reader_from_environment().status()

    @server.tool()
    def qq_recent_messages(
        minutes: int = 10,
        limit: int = 50,
        conversation_id: str = "",
    ) -> dict:
        """Read recent QQ messages in chronological order.

        Args:
            minutes: Look-back window from 1 minute to 7 days.
            limit: Maximum messages to return, capped at 200.
            conversation_id: Optional c2c:…, group:…, or dataline:pc identifier.
        """
        if not _enabled("QQNT_ALLOW_CONTENT"):
            raise RuntimeError(
                "message content access is disabled; explicitly set QQNT_ALLOW_CONTENT=1"
            )
        requested = conversation_id or None
        allowed = _allowlist()
        if allowed is not None:
            if requested is None:
                raise RuntimeError(
                    "an explicit conversation_id is required when an allowlist is configured"
                )
            if requested not in allowed:
                raise RuntimeError("conversation_id is not in QQNT_ALLOW_CONVERSATIONS")
        return reader_from_environment().recent(
            minutes=minutes, limit=limit, conversation_id=requested
        )

    @server.tool()
    def qq_recent_conversations(minutes: int = 1440, limit: int = 30) -> dict:
        """List recently active conversation identifiers without message content."""
        result = reader_from_environment().recent(
            minutes=minutes, limit=min(max(limit * 10, limit), 200)
        )
        seen: set[str] = set()
        conversations = []
        allowed = _allowlist()
        for message in reversed(result["messages"]):
            identifier = message["conversation_id"]
            if identifier in seen or (allowed is not None and identifier not in allowed):
                continue
            seen.add(identifier)
            conversations.append(
                {
                    "conversation_id": identifier,
                    "latest_time": message["time"],
                    "latest_sender": message["sender"],
                }
            )
            if len(conversations) >= max(1, min(limit, 100)):
                break
        return {
            "synced_at": result["synced_at"],
            "count": len(conversations),
            "conversations": conversations,
        }

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
