from qqnt_export_macos.message_preview import message_metadata, message_preview


def _varint(value: int) -> bytes:
    output = bytearray()
    while value > 0x7F:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)
    return bytes(output)


def _field(number: int, value: int | bytes) -> bytes:
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _body(element: bytes) -> bytes:
    return _field(40800, element)


def test_text_preview():
    element = _field(45002, 1) + _field(45101, "你好，Agent".encode())
    assert message_preview(_body(element)) == "你好，Agent"


def test_media_preview_and_bound():
    image = _field(45002, 2) + _field(45815, "截图".encode())
    assert message_preview(_body(image)) == "[图片：截图]"
    long_text = _field(45002, 1) + _field(45101, b"a" * 20)
    assert message_preview(_body(long_text), max_chars=10) == "a" * 9 + "…"


def test_invalid_body_is_not_exposed():
    assert message_preview(b"\x82") == "[正文解析失败]"


def test_at_metadata_preserves_target_identity():
    mention = (
        _field(45002, 1)
        + _field(45101, "@目标用户".encode())
        + _field(45102, 2)
        + _field(45103, 123456)
        + _field(45105, "u_target".encode())
    )

    assert message_metadata(_body(mention)) == {
        "mentions": [
            {"uid": "u_target", "uin": "123456", "name": "目标用户"}
        ],
        "elements": [
            {
                "type": "at",
                "data": {"uid": "u_target", "uin": "123456", "name": "目标用户"},
            }
        ],
    }


def test_non_mention_text_has_no_metadata():
    text = _field(45002, 1) + _field(45101, "普通文本".encode())
    assert message_metadata(_body(text)) == {"mentions": [], "elements": []}


def test_reply_metadata_uses_group_member_identity_for_at_text():
    reply = _field(45002, 7) + _field(40020, b"u_target") + _field(47403, 123456)
    at_text = _field(45002, 1) + _field(45101, "@目标用户后续内容".encode())

    assert message_metadata(
        _body(reply) + _body(at_text),
        member_names={"u_target": "目标用户", "123456": "目标用户"},
    ) == {
        "mentions": [
            {"uid": "u_target", "uin": "123456", "name": "目标用户"}
        ],
        "elements": [
            {
                "type": "at",
                "data": {"uid": "u_target", "uin": "123456", "name": "目标用户"},
            }
        ],
    }
