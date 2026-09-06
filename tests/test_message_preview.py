from qqnt_export_macos.message_preview import message_preview


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
