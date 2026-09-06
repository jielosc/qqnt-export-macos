"""Locate QQNT's SQLCipher key function in an arm64 Mach-O module."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from pathlib import Path
import struct


CPU_TYPE_ARM64 = 0x0100000C
FAT_MAGIC = 0xCAFEBABE
MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_FUNCTION_STARTS = 0x26


@dataclass(frozen=True)
class Location:
    function_va: int
    database_log_references: tuple[int, ...]
    missing_key_log_references: tuple[int, ...]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _arm64_slice(data: bytes) -> tuple[int, bytes]:
    if len(data) < 32:
        raise ValueError("file is too small to be a Mach-O binary")
    if _u32(data, 0) == MH_MAGIC_64:
        if _u32(data, 4) != CPU_TYPE_ARM64:
            raise ValueError("thin Mach-O is not arm64")
        return 0, data
    if struct.unpack_from(">I", data, 0)[0] != FAT_MAGIC:
        raise ValueError("file is neither a fat nor a thin arm64 Mach-O")

    architecture_count = struct.unpack_from(">I", data, 4)[0]
    for index in range(architecture_count):
        base = 8 + index * 20
        if base + 20 > len(data):
            break
        cputype, _, offset, size, _ = struct.unpack_from(">iiIII", data, base)
        if cputype == CPU_TYPE_ARM64:
            if offset + size > len(data):
                raise ValueError("arm64 slice extends beyond the file")
            return offset, data[offset : offset + size]
    raise ValueError("arm64 slice not found")


def _parse_macho(slice_data: bytes):
    if _u32(slice_data, 0) != MH_MAGIC_64:
        raise ValueError("arm64 slice is not a 64-bit little-endian Mach-O")

    segments = []
    sections = []
    function_starts = None
    cursor = 32
    for _ in range(_u32(slice_data, 16)):
        if cursor + 8 > len(slice_data):
            raise ValueError("truncated Mach-O load commands")
        command, size = struct.unpack_from("<II", slice_data, cursor)
        if size < 8 or cursor + size > len(slice_data):
            raise ValueError("invalid Mach-O load command size")
        if command == LC_SEGMENT_64:
            name = slice_data[cursor + 8 : cursor + 24].rstrip(b"\0").decode()
            vmaddr = _u64(slice_data, cursor + 24)
            vmsize = _u64(slice_data, cursor + 32)
            fileoff = _u64(slice_data, cursor + 40)
            filesize = _u64(slice_data, cursor + 48)
            segments.append((name, vmaddr, vmsize, fileoff, filesize))
            section_cursor = cursor + 72
            for _ in range(_u32(slice_data, cursor + 64)):
                section_name = slice_data[
                    section_cursor : section_cursor + 16
                ].rstrip(b"\0").decode()
                segment_name = slice_data[
                    section_cursor + 16 : section_cursor + 32
                ].rstrip(b"\0").decode()
                address = _u64(slice_data, section_cursor + 32)
                section_size = _u64(slice_data, section_cursor + 40)
                section_offset = _u32(slice_data, section_cursor + 48)
                sections.append(
                    (segment_name, section_name, address, section_size, section_offset)
                )
                section_cursor += 80
        elif command == LC_FUNCTION_STARTS:
            function_starts = (
                _u32(slice_data, cursor + 8),
                _u32(slice_data, cursor + 12),
            )
        cursor += size

    try:
        text_segment = next(item for item in segments if item[0] == "__TEXT")
        text_section = next(
            item for item in sections if item[:2] == ("__TEXT", "__text")
        )
    except StopIteration as exc:
        raise ValueError("Mach-O has no __TEXT/__text mapping") from exc
    if function_starts is None:
        raise ValueError("Mach-O has no LC_FUNCTION_STARTS command")
    return segments, text_segment, text_section, function_starts


def _file_offset_to_va(segments, file_offset: int) -> int:
    for _, vmaddr, _, segment_fileoff, file_size in segments:
        if segment_fileoff <= file_offset < segment_fileoff + file_size:
            return vmaddr + file_offset - segment_fileoff
    raise ValueError(f"file offset 0x{file_offset:x} is not mapped")


def _decode_function_starts(
    data: bytes, offset: int, size: int, base_address: int
) -> list[int]:
    starts = []
    address = base_address
    cursor = offset
    end = min(offset + size, len(data))
    while cursor < end:
        value = 0
        shift = 0
        while cursor < end:
            byte = data[cursor]
            cursor += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        if value == 0:
            break
        address += value
        starts.append(address)
    return starts


def _decode_adrp(instruction: int, program_counter: int) -> tuple[int, int] | None:
    if instruction & 0x9F000000 != 0x90000000:
        return None
    immediate = (((instruction >> 5) & 0x7FFFF) << 2) | (
        (instruction >> 29) & 0x3
    )
    if immediate & (1 << 20):
        immediate -= 1 << 21
    return (program_counter & ~0xFFF) + (immediate << 12), instruction & 0x1F


def _decode_add_immediate(instruction: int, source_register: int) -> int | None:
    if instruction & 0xFF000000 != 0x91000000:
        return None
    if (instruction >> 5) & 0x1F != source_register:
        return None
    immediate = (instruction >> 10) & 0xFFF
    if (instruction >> 22) & 1:
        immediate <<= 12
    return immediate


def _find_references(text: bytes, text_address: int, target: int) -> list[int]:
    references = []
    for offset in range(0, len(text) - 20, 4):
        decoded = _decode_adrp(_u32(text, offset), text_address + offset)
        if decoded is None:
            continue
        page, register = decoded
        for lookahead in range(1, 5):
            addition = _decode_add_immediate(
                _u32(text, offset + lookahead * 4), register
            )
            if addition is not None and page + addition == target:
                references.append(text_address + offset)
                break
    return references


def _containing_function(starts: list[int], address: int) -> int:
    index = bisect.bisect_right(starts, address) - 1
    if index < 0:
        raise ValueError(f"no function starts before reference 0x{address:x}")
    return starts[index]


def locate_key_function(path: Path) -> Location:
    """Return the module-relative virtual address of nt_sqlite3_key_v2."""
    data = path.read_bytes()
    fat_offset, slice_data = _arm64_slice(data)
    segments, text_segment, text_section, function_command = _parse_macho(
        slice_data
    )

    needles = (b"nt_sqlite3_key_v2: db=", b"nt_sqlite3_key_v2: no key")
    string_addresses = []
    for needle in needles:
        absolute = data.find(needle, fat_offset, fat_offset + len(slice_data))
        if absolute < 0:
            raise ValueError(f"diagnostic string not found: {needle!r}")
        string_addresses.append(
            _file_offset_to_va(segments, absolute - fat_offset)
        )

    _, _, text_address, text_size, text_offset = text_section
    text = slice_data[text_offset : text_offset + text_size]
    data_offset, data_size = function_command
    starts = _decode_function_starts(
        slice_data, data_offset, data_size, text_segment[1]
    )
    if not starts:
        raise ValueError("Mach-O function-start table is empty")

    references = tuple(
        tuple(_find_references(text, text_address, address))
        for address in string_addresses
    )
    functions = [
        {_containing_function(starts, reference) for reference in group}
        for group in references
    ]
    shared = sorted(functions[0] & functions[1])
    if len(shared) != 1:
        detail = ", ".join(f"0x{value:x}" for value in shared) or "none"
        raise ValueError(
            f"expected one shared referencing function; candidates: {detail}"
        )
    return Location(shared[0], references[0], references[1])
