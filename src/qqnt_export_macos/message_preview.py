"""Small, dependency-free QQNT protobuf preview decoder.

This deliberately extracts only human-readable summaries.  It never returns
the raw protobuf body to callers.
"""

from __future__ import annotations

from collections.abc import Iterator


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


def _element_preview(data: bytes) -> str:
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
        return "[回复]"
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


def message_preview(body: bytes | None, max_chars: int = 2000) -> str:
    """Return a bounded text preview for a QQNT ``40800`` message body."""
    if not body:
        return "[无正文]"
    try:
        elements = [
            value
            for number, wire_type, value in iter_fields(bytes(body))
            if number == 40800 and wire_type == 2 and isinstance(value, bytes)
        ]
        parts = [_element_preview(element) for element in elements]
    except (ProtobufDecodeError, TypeError, ValueError):
        return "[正文解析失败]"
    preview = "".join(part for part in parts if part).strip() or "[无正文]"
    preview = "".join(char for char in preview if char in "\n\t" or ord(char) >= 32)
    if len(preview) > max_chars:
        return preview[: max_chars - 1] + "…"
    return preview
