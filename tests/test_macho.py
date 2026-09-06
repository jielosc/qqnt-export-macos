import pytest

from qqnt_export_macos.macho import (
    _containing_function,
    _decode_add_immediate,
    _decode_adrp,
    _decode_function_starts,
)


def test_decode_function_starts():
    assert _decode_function_starts(bytes([0x10, 0x05, 0x00]), 0, 3, 0x1000) == [
        0x1010,
        0x1015,
    ]


def test_decode_add_immediate():
    # add x8, x8, #0x123
    instruction = 0x91000000 | (0x123 << 10) | (8 << 5) | 8
    assert _decode_add_immediate(instruction, 8) == 0x123
    assert _decode_add_immediate(instruction, 7) is None


def test_decode_adrp_zero_page_delta():
    decoded = _decode_adrp(0x90000008, 0x12345ABC)
    assert decoded == (0x12345000, 8)


def test_containing_function():
    assert _containing_function([0x1000, 0x1040, 0x1100], 0x10A0) == 0x1040
    with pytest.raises(ValueError):
        _containing_function([0x1000], 0x900)
