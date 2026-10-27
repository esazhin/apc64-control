"""Akai Project Editor presets (.APC64) → ProjectRecord (contract d84–d87, a18; PROTOCOL-SPEC §8.4).

Layout, read from a real editor file (Boss RC-600.APC64, 2026-10-26); all words little-endian u32:
    file header  2, 0, 0
    592 items    u32 size (of the whole item), u32 0, u32 index, then one value node:
    value node   u32 size (of the node), u32 1, u32 kind, payload
                 kind 3 = one byte (a 13-byte node); kind 0x10 = RGB, a list of three kind-3 nodes (51 bytes)
Indices 0–511 = 64 pads × 8 fields, 512–591 = 8 strips × 10 fields. Pad fields in order: note-in-octave,
aftertouch, channel, octave, rest RGB, pressed RGB, outputs, unknown — one-to-one with pad record bytes 0–11.
Strip fields: resolution, CC, LSB, unknown, channel, unknown, bar RGB, indicator RGB, outputs, bipolar — strip
record bytes 0–13.

The contract (p9, d84) described the items as flat (kind, 0, index) + value; the real file nests the value in its own
node, as above. Anything unexpected is refused with the item number and byte offset, so a file that differs is
never imported wrongly. The file is only parsed, never run, and every field is range-checked (d87).
"""
import struct
from dataclasses import dataclass
from pathlib import PurePath

from _apc64_host.domain.controls import PadPos

from .pads import PAD_COUNT
from .records import PAD_SIZE, PROJECT_SIZE, STRIP_SIZE, ProjectRecord

ITEM_COUNT = 592
WORDS = struct.Struct("<III")             # the file header, an item header and a value-node header alike
FILE_HEADER = (2, 0, 0)
BYTE_KIND, RGB_KIND = 0x03, 0x10
BYTE_NODE = WORDS.size + 1                # 13
NODE_SIZE = {BYTE_KIND: BYTE_NODE, RGB_KIND: WORDS.size + 3 * BYTE_NODE}   # 13, 51

# (field name, record byte offset, kind, low, high) — None bounds: any byte (unknown, kept)
PAD_FIELDS = (("note", 0, BYTE_KIND, 0, 11), ("aftertouch", 1, BYTE_KIND, 0, 1), ("channel", 2, BYTE_KIND, 1, 16),
              ("octave", 3, BYTE_KIND, 0, 10), ("rest colour", 4, RGB_KIND, None, None),
              ("pressed colour", 7, RGB_KIND, None, None), ("outputs", 10, BYTE_KIND, 0, 7),
              ("unknown", 11, BYTE_KIND, None, None))
STRIP_FIELDS = (("resolution", 0, BYTE_KIND, 1, 2), ("cc", 1, BYTE_KIND, 0, 127), ("lsb", 2, BYTE_KIND, 0, 127),
                ("unknown 3", 3, BYTE_KIND, None, None), ("channel", 4, BYTE_KIND, 1, 16),
                ("unknown 5", 5, BYTE_KIND, None, None), ("bar colour", 6, RGB_KIND, None, None),
                ("indicator colour", 9, RGB_KIND, None, None), ("outputs", 12, BYTE_KIND, 0, 7),
                ("bipolar", 13, BYTE_KIND, 0, 1))
PAD_ITEMS = PAD_COUNT * len(PAD_FIELDS)   # 512


class PresetError(ValueError):
    """A refused preset: the message names the item and byte offset where there is one (A56, A57)."""

    def __init__(self, message: str, item: int | None = None, offset: int | None = None):
        self.message, self.item, self.offset = message, item, offset
        super().__init__(message)


@dataclass(frozen=True)
class FieldRef:
    """Where item `index` lands: the record byte offset, its kind, bounds and a name ('pad r1c1 channel')."""
    offset: int
    kind: int
    low: int | None
    high: int | None
    name: str


def field_of(index: int) -> FieldRef | None:
    if 0 <= index < PAD_ITEMS:
        pad, n = divmod(index, len(PAD_FIELDS))
        name, at, kind, low, high = PAD_FIELDS[n]
        return FieldRef(pad * PAD_SIZE + at, kind, low, high, f"{PadPos.from_index(pad)} {name}")
    if PAD_ITEMS <= index < ITEM_COUNT:
        strip, n = divmod(index - PAD_ITEMS, len(STRIP_FIELDS))
        name, at, kind, low, high = STRIP_FIELDS[n]
        return FieldRef(PAD_COUNT * PAD_SIZE + strip * STRIP_SIZE + at, kind, low, high, f"strip {strip + 1} {name}")
    return None


def parse_preset(data: bytes) -> ProjectRecord:
    """The 880-byte project a preset describes, or PresetError. Nothing here touches the unit."""
    data = bytes(data)
    if len(data) < WORDS.size or WORDS.unpack_from(data) != FILE_HEADER:
        found = WORDS.unpack_from(data) if len(data) >= WORDS.size else f"{len(data)} bytes"
        raise PresetError(f"the file starts with {found}, expected {FILE_HEADER} at byte 0", None, 0)
    raw = bytearray(PROJECT_SIZE)
    seen: dict[int, int] = {}
    offset, ordinal = WORDS.size, 0
    while offset < len(data):
        if offset + WORDS.size > len(data):
            raise PresetError(f"item {ordinal} ends past the end of the file at byte {offset + WORDS.size}",
                              ordinal, offset)
        size, zero, index = WORDS.unpack_from(data, offset)
        if zero != 0:
            raise PresetError(f"item {ordinal} has {zero} where 0 belongs at byte {offset + 4}", ordinal, offset + 4)
        end = offset + size
        if end > len(data):
            raise PresetError(f"item {ordinal} ends past the end of the file at byte {end}", ordinal, offset)
        kind, value = _value_node(data, offset + WORDS.size, end, ordinal)
        target = field_of(index)
        if target is None:
            raise PresetError(f"item {ordinal} has index {index} at byte {offset + 8}; indices are 0–591",
                              ordinal, offset + 8)
        if index in seen:
            raise PresetError(f"item {ordinal} repeats index {index} of item {seen[index]} at byte {offset + 8}",
                              ordinal, offset + 8)
        if kind != target.kind:
            raise PresetError(f"item {ordinal} ({target.name}) has kind {kind:#x}, expected "
                              f"{target.kind:#x} at byte {offset + 20}", ordinal, offset + 20)
        value_at = offset + 2 * WORDS.size
        if target.low is not None and not target.low <= value[0] <= target.high:
            raise PresetError(f"item {ordinal} ({target.name}) is {value[0]}, outside {target.low}–{target.high} "
                              f"at byte {value_at}", ordinal, value_at)
        raw[target.offset:target.offset + len(value)] = value
        seen[index] = ordinal
        offset, ordinal = end, ordinal + 1
    if ordinal != ITEM_COUNT:
        raise PresetError(f"{ordinal} items, expected {ITEM_COUNT}")
    record = ProjectRecord(bytes(raw))
    for pad in record.pads:   # octave·12 + note-in-octave must be a MIDI note (d87)
        if pad.note > 127:
            index = record.pads.index(pad)
            raise PresetError(f"{PadPos.from_index(index)} is note {pad.note}, outside 0–127")
    return record


def _value_node(data: bytes, at: int, end: int, ordinal: int, inner: bool = False) -> tuple[int, bytes]:
    """The (kind, value bytes) of the node at `at`, which must fill the item exactly up to `end`."""
    if at + WORDS.size > end:
        raise PresetError(f"item {ordinal} has no room for its value at byte {at}", ordinal, at)
    size, one, kind = WORDS.unpack_from(data, at)
    if one != 1:
        raise PresetError(f"item {ordinal} has {one} where 1 belongs at byte {at + 4}", ordinal, at + 4)
    if kind not in NODE_SIZE or (inner and kind != BYTE_KIND):
        allowed = "0x3 (byte)" if inner else "0x3 (byte) and 0x10 (RGB)"
        raise PresetError(f"item {ordinal} has kind {kind:#x} at byte {at + 8}; kinds are {allowed}",
                          ordinal, at + 8)
    if size != NODE_SIZE[kind] or at + size != end:
        raise PresetError(f"item {ordinal} has a {size}-byte kind {kind:#x} value at byte {at}, which must be "
                          f"{NODE_SIZE[kind]} bytes and end the item at byte {end}", ordinal, at)
    if kind == BYTE_KIND:
        return kind, data[at + WORDS.size:end]
    parts = at + WORDS.size
    return kind, b"".join(_value_node(data, parts + i * BYTE_NODE, parts + (i + 1) * BYTE_NODE, ordinal, True)[1]
                          for i in range(3))


def preset_name(filename: str) -> str:
    """The library name of an imported preset: its file name without '.APC64' ('Boss RC-600')."""
    return PurePath(str(filename)).stem


def summary(record: ProjectRecord) -> dict:
    """What an import lists (A55): pads and strips."""
    return {"pads": len(record.pads), "strips": len(record.strips)}
