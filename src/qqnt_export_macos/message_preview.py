"""Small, dependency-free QQNT protobuf preview decoder.

This deliberately extracts only human-readable summaries.  It never returns
the raw protobuf body to callers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping


class ProtobufDecodeError(ValueError):
    """Raised when a message body is not a supported protobuf stream."""


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ProtobufDecodeError("truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
    raise ProtobufDecodeError("oversized varint")


def iter_fields(data: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    """Yield ``(field_number, wire_type, value)`` for ordinary protobuf fields."""
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire_type = tag >> 3, tag & 7
        if not number:
            raise ProtobufDecodeError("zero field number")
        if wire_type == 0:
            value, offset = _varint(data, offset)
        elif wire_type == 1:
            end = offset + 8
            if end > len(data):
                raise ProtobufDecodeError("truncated fixed64")
            value, offset = data[offset:end], end
        elif wire_type == 2:
            length, offset = _varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtobufDecodeError("truncated bytes field")
            value, offset = data[offset:end], end
        elif wire_type == 5:
            end = offset + 4
            if end > len(data):
                raise ProtobufDecodeError("truncated fixed32")
            value, offset = data[offset:end], end
        else:
            raise ProtobufDecodeError(f"unsupported wire type {wire_type}")
        yield number, wire_type, value


def _text(value: int | bytes) -> str:
    if not isinstance(value, bytes):
        return ""
    return value.decode("utf-8", errors="replace").strip()


def _element_preview(data: bytes, *, include_reply_marker: bool = True) -> str:
    fields: dict[int, list[int | bytes]] = {}
    for number, _wire_type, value in iter_fields(data):
        fields.setdefault(number, []).append(value)

    element_type = int(fields.get(45002, [0])[-1])
    first_text = lambda number: _text(fields.get(number, [b""])[-1])
    text = first_text(45101)
    if text:
        return text
    if element_type == 2:
        summary = first_text(45815)
        return f"[图片：{summary}]" if summary else "[图片]"
    if element_type == 3:
        name = first_text(45402)
        return f"[文件：{name}]" if name else "[文件]"
    if element_type == 4:
        transcript = first_text(45923)
        duration = fields.get(45906, [0])[-1]
        if transcript:
            return f"[语音转写：{transcript}]"
        return f"[语音 {duration} 秒]" if duration else "[语音]"
    if element_type == 5:
        return "[视频]"
    if element_type == 6:
        emoji = first_text(47602) or first_text(45004) or first_text(80900)
        return emoji or "[表情]"
    if element_type == 7:
        return "[回复]" if include_reply_marker else ""
    if element_type == 8:
        notice = first_text(47713) or first_text(48214) or first_text(48271)
        return notice or "[系统提示]"
    if element_type == 9:
        return "[红包或转账]"
    if element_type == 10:
        summary = first_text(48705) or first_text(48701)
        return summary or "[卡片消息]"
    if element_type == 21:
        summary = first_text(48157) or first_text(48153)
        return summary or "[通话]"
    if element_type == 26:
        return "[动态消息]"
    location = first_text(52152)
    if location:
        return f"[位置：{location}]"
    return f"[消息类型 {element_type}]" if element_type else "[无法预览]"


def message_preview(
    body: bytes | None,
    max_chars: int = 2000,
    *,
    include_reply_marker: bool = True,
) -> str:
    """Return a bounded text preview for a QQNT ``40800`` message body."""
    if not body:
        return "[无正文]"
    try:
        elements = [
            value
            for number, wire_type, value in iter_fields(bytes(body))
            if number == 40800 and wire_type == 2 and isinstance(value, bytes)
        ]
        parts = [
            _element_preview(element, include_reply_marker=include_reply_marker)
            for element in elements
        ]
    except (ProtobufDecodeError, TypeError, ValueError):
        return "[正文解析失败]"
    preview = "".join(part for part in parts if part).strip() or "[无正文]"
    preview = "".join(char for char in preview if char in "\n\t" or ord(char) >= 32)
    if len(preview) > max_chars:
        return preview[: max_chars - 1] + "…"
    return preview


def message_metadata(
    body: bytes | None,
    *,
    member_names: Mapping[str, str] | None = None,
) -> dict[str, list[dict]]:
    """Extract structured @ and reply metadata without exposing raw protobuf.

    QQNT represents an @ element as a type-1 element with ``45102 == 2``.
    ``45101`` contains the rendered ``@display-name`` and ``45103``/``45105``
    contain the target UIN/UID.  Keep this separate from ``message_preview``
    so existing consumers of the string ``content`` field remain compatible.
    """

    empty = {"mentions": [], "elements": []}
    if not body:
        return empty

    try:
        elements = [
            value
            for number, wire_type, value in iter_fields(bytes(body))
            if number == 40800 and wire_type == 2 and isinstance(value, bytes)
        ]
        mentions: list[dict] = []
        structured_elements: list[dict] = []
        pending_reply: dict[str, str | None] | None = None
        for element in elements:
            fields: dict[int, list[int | bytes]] = {}
            for number, _wire_type, value in iter_fields(element):
                fields.setdefault(number, []).append(value)

            element_type = fields.get(45002, [0])[-1]
            if element_type == 7:
                reply_uid = _text(fields.get(40020, [b""])[-1])
                reply_uin = fields.get(47403, [0])[-1]
                referenced_message_id_ref = fields.get(47401, [0])[-1]
                referenced_message_id = fields.get(47416, [0])[-1]
                referenced_message_seq = fields.get(47402, [0])[-1]
                quoted_timestamp = fields.get(47404, [0])[-1]
                quoted_parts = []
                for quoted_element in fields.get(47423, []):
                    if not isinstance(quoted_element, bytes):
                        continue
                    try:
                        quoted_parts.append(
                            _element_preview(
                                quoted_element,
                                include_reply_marker=False,
                            )
                        )
                    except (ProtobufDecodeError, TypeError, ValueError):
                        continue
                quoted_content = "".join(part for part in quoted_parts if part).strip()
                if not quoted_content:
                    quoted_content = _text(fields.get(47413, [b""])[-1])
                pending_reply = {
                    "uid": reply_uid or None,
                    "uin": str(reply_uin)
                    if isinstance(reply_uin, int) and reply_uin
                    else None,
                }
                identity = pending_reply["uid"] or pending_reply["uin"] or ""
                sender_name = (
                    str((member_names or {}).get(identity) or "").strip()
                    if identity
                    else ""
                )
                structured_elements.append(
                    {
                        "type": "reply",
                        "data": {
                            "referencedMessageId": str(
                                referenced_message_id_ref or referenced_message_id
                            )
                            if isinstance(
                                referenced_message_id_ref or referenced_message_id,
                                int,
                            )
                            and (referenced_message_id_ref or referenced_message_id)
                            else None,
                            "referencedMessageIdRef": str(referenced_message_id_ref)
                            if isinstance(referenced_message_id_ref, int)
                            and referenced_message_id_ref
                            else None,
                            "referencedMessageSeq": referenced_message_seq
                            if isinstance(referenced_message_seq, int)
                            and referenced_message_seq
                            else None,
                            "senderUid": pending_reply["uid"],
                            "senderUin": pending_reply["uin"],
                            "senderName": sender_name or None,
                            "timestamp": quoted_timestamp
                            if isinstance(quoted_timestamp, int) and quoted_timestamp
                            else None,
                            "content": quoted_content or None,
                        },
                    }
                )
                continue

            mention_kind = fields.get(45102, [0])[-1]
            if element_type != 1 or not isinstance(mention_kind, int):
                pending_reply = None
                continue

            rendered = _text(fields.get(45101, [b""])[-1])
            if not rendered.startswith("@") or (
                len(rendered) == 1 and mention_kind != 2 and not pending_reply
            ):
                pending_reply = None
                continue

            if mention_kind not in {0, 2}:
                pending_reply = None
                continue

            target_uin = fields.get(45103, [0])[-1]
            target_uid = _text(fields.get(45105, [b""])[-1])
            if pending_reply:
                target_uin = target_uin or pending_reply["uin"] or 0
                target_uid = target_uid or pending_reply["uid"] or ""

            name = rendered[1:].strip()
            if mention_kind == 0 and pending_reply and member_names:
                identity = target_uid or str(target_uin)
                mapped_name = str(member_names.get(identity) or "").strip()
                if mapped_name and name.startswith(mapped_name):
                    name = mapped_name

            target_uin_text = (
                str(target_uin)
                if isinstance(target_uin, int) and target_uin
                else str(pending_reply["uin"])
                if pending_reply and pending_reply["uin"]
                else None
            )
            target = {
                "uid": target_uid or None,
                "uin": target_uin_text,
                "name": name,
            }
            mentions.append(target)
            structured_elements.append({"type": "at", "data": target.copy()})
            pending_reply = None
    except (ProtobufDecodeError, TypeError, ValueError):
        return empty

    return {"mentions": mentions, "elements": structured_elements}


def chatlab_message_type(body: bytes | None) -> int:
    """Map a QQNT body to the closest ChatLab message type.

    ChatLab uses type 25 for replies, 0 for plain text, 1 for images and
    5 for mixed/face messages.  Less common element types are mapped to the
    corresponding values used by QQNT_Export where practical.
    """
    if not body:
        return 0
    try:
        element_types: list[int] = []
        for number, wire_type, value in iter_fields(bytes(body)):
            if number != 40800 or wire_type != 2 or not isinstance(value, bytes):
                continue
            fields = {
                field_number: field_value
                for field_number, _field_wire_type, field_value in iter_fields(value)
            }
            raw_type = fields.get(45002, 0)
            if isinstance(raw_type, int):
                element_types.append(raw_type)
    except (ProtobufDecodeError, TypeError, ValueError):
        return 0

    if 7 in element_types:
        return 25
    if 2 in element_types:
        return 1
    if 3 in element_types:
        return 4
    if 4 in element_types:
        return 2
    if 5 in element_types:
        return 3
    if any(element_type in {6, 11} for element_type in element_types):
        return 5
    if 9 in element_types:
        return 20
    if 10 in element_types:
        return 24
    if 8 in element_types:
        return 81
    if 21 in element_types:
        return 23
    if 26 in element_types:
        return 24
    if 16 in element_types:
        return 26
    return 0
