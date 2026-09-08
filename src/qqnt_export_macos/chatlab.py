"""Export a bounded live QQNT message range as a ChatLab JSON document."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .message_preview import chatlab_message_type, message_metadata, message_preview
from .recent import QQRecentReader, query_message_range


CHATLAB_VERSION = "0.0.2"


def _sender_identity(row: dict[str, Any]) -> str:
    for field in ("sender_uid", "sender_number"):
        value = str(row.get(field) or "").strip()
        if value and value != "0":
            return value
    return "unknown"


def build_chatlab_payload(
    rows: list[dict[str, Any]],
    *,
    conversation_id: str,
    conversation_name: str | None,
    range_start: datetime,
    range_end: datetime,
    exported_at: int | None = None,
) -> dict[str, Any]:
    """Convert normalized QQNT rows into a ChatLab-compatible payload."""
    kind, conversation_key = conversation_id.split(":", 1)
    members_by_id: dict[str, dict[str, str]] = {}
    messages: list[dict[str, Any]] = []
    message_ids = {str(row["message_id"]) for row in rows}
    ids_by_sequence: dict[int, list[str]] = {}
    member_names: dict[str, str] = {}
    for row in rows:
        sequence = int(row.get("sequence") or 0)
        if sequence:
            ids_by_sequence.setdefault(sequence, []).append(str(row["message_id"]))
        display_name = str(row.get("card") or row.get("nickname") or "").strip()
        if display_name:
            for identity_field in ("sender_uid", "sender_number"):
                identity = str(row.get(identity_field) or "").strip()
                if identity and identity != "0":
                    member_names.setdefault(identity, display_name)

    for row in rows:
        sender_id = _sender_identity(row)
        account_name = str(row.get("nickname") or "").strip()
        group_nickname = str(row.get("card") or "").strip()
        display_name = group_nickname or account_name or sender_id
        member = members_by_id.setdefault(
            sender_id,
            {
                "platformId": sender_id,
                "accountName": account_name or display_name,
            },
        )
        if not member["accountName"] and account_name:
            member["accountName"] = account_name
        if group_nickname and not member.get("groupNickname"):
            member["groupNickname"] = group_nickname

        body = row.get("body")
        metadata = message_metadata(body, member_names=member_names)
        reply_data = next(
            (
                element.get("data", {})
                for element in metadata["elements"]
                if element.get("type") == "reply"
            ),
            {},
        )
        direct_reply_id = str(reply_data.get("referencedMessageId") or "").strip()
        reply_sequence = int(reply_data.get("referencedMessageSeq") or 0)
        sequence_matches = ids_by_sequence.get(reply_sequence, [])
        reply_id = (
            direct_reply_id
            if direct_reply_id in message_ids
            else sequence_matches[0]
            if len(sequence_matches) == 1
            else direct_reply_id
        )
        message: dict[str, Any] = {
            "platformMessageId": str(row["message_id"]),
            "sender": sender_id,
            "accountName": account_name or display_name,
            "timestamp": int(row.get("sent_at") or 0),
            "type": chatlab_message_type(body),
            "content": message_preview(body, include_reply_marker=False),
        }
        if kind == "group":
            message["groupNickname"] = group_nickname or display_name
        if reply_id:
            message["replyToMessageId"] = reply_id
        reply_content = str(reply_data.get("content") or "").strip()
        if reply_content:
            message["replyContext"] = {
                "sender": reply_data.get("senderUid") or reply_data.get("senderUin"),
                "accountName": reply_data.get("senderName"),
                "timestamp": reply_data.get("timestamp"),
                "content": reply_content,
            }
        if metadata["mentions"] or metadata["elements"]:
            message["contentMetadata"] = metadata
        messages.append(message)

    meta = {
        "name": conversation_name or conversation_id,
        "platform": "qq",
        "type": "group" if kind == "group" else "private",
    }
    if kind == "group":
        meta["groupId"] = conversation_key

    return {
        "chatlab": {
            "version": CHATLAB_VERSION,
            "exportedAt": int(exported_at or datetime.now().timestamp()),
            "generator": "qqnt-export-macos",
        },
        "meta": meta,
        "members": list(members_by_id.values()),
        "messages": messages,
        "statistics": {
            "messageCount": len(messages),
            "timeRange": {
                "start": range_start.isoformat(),
                "end": range_end.isoformat(),
            },
        },
    }


def export_chatlab_range(
    reader: QQRecentReader,
    *,
    range_start: datetime,
    range_end: datetime,
    conversation_id: str | None = None,
    conversation_name: str | None = None,
) -> dict[str, Any]:
    """Read one exact half-open time range and return a ChatLab payload."""
    if range_start.tzinfo is None or range_end.tzinfo is None:
        raise ValueError("ChatLab export range must include timezone information")
    if range_start >= range_end:
        raise ValueError("ChatLab export start must be before end")
    if bool(conversation_id) == bool(conversation_name):
        raise ValueError("use exactly one of conversation_id or conversation_name")

    resolved_name = None
    if conversation_name:
        conversation_id, resolved_name = reader.resolve_group_name(conversation_name)
    assert conversation_id is not None

    connection = reader._connection()
    try:
        rows = query_message_range(
            connection,
            start_timestamp=int(range_start.timestamp()),
            end_timestamp=int(range_end.timestamp()),
            conversation_id=conversation_id,
        )
    finally:
        connection.close()

    if resolved_name is None and conversation_id.startswith("group:"):
        resolved_name = reader.group_names().get(conversation_id.split(":", 1)[1])
    return build_chatlab_payload(
        rows,
        conversation_id=conversation_id,
        conversation_name=resolved_name,
        range_start=range_start,
        range_end=range_end,
    )


def write_chatlab_payload(
    destination: Path,
    payload: dict[str, Any],
    *,
    overwrite: bool = False,
) -> Path:
    """Atomically write a private ChatLab JSON file."""
    destination = destination.expanduser().resolve()
    if destination.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {destination}")
    parent_existed = destination.parent.exists()
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent_existed:
        os.chmod(destination.parent, 0o700)

    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, destination)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return destination
