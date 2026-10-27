"""The .APC64 preset codec (T5): the real editor file in fixtures/ (a18) plus synthetic files in its layout —
header (2, 0, 0), then items (u32 size, u32 0, u32 index) + a value node (u32 size, u32 1, u32 kind, payload)."""
import struct
from pathlib import Path

import pytest

from _apc64_host.domain.controls import PadPos
from _apc64_lab.domain.apc64_preset import (
    ITEM_COUNT, PAD_FIELDS, STRIP_FIELDS, PresetError, field_of, parse_preset, preset_name, summary,
)
from _apc64_lab.domain.memory_sysex import parse_project_dump
from _apc64_lab.domain.records import PAD_SIZE, STRIP_SIZE


def items_of(record_raw: bytes):
    """The 592 (kind, index, value) items of a record, in index order (a test-only builder: no export, §2.5)."""
    out = []
    for index in range(ITEM_COUNT):
        ref = field_of(index)
        size = 3 if ref.kind == 0x10 else 1
        out.append((ref.kind, index, record_raw[ref.offset:ref.offset + size]))
    return out


REAL_FILE = Path(__file__).resolve().parents[2] / "fixtures" / "Boss RC-600.APC64"


def node_of(kind: int, value: bytes) -> bytes:
    if kind == 0x10:
        body = b"".join(node_of(3, value[i:i + 1]) for i in range(3))
    else:
        body = bytes(value)
    return struct.pack("<III", 12 + len(body), 1, kind) + body


def item_of(kind: int, index: int, value: bytes) -> bytes:
    node = node_of(kind, value)
    return struct.pack("<III", 12 + len(node), 0, index) + node


def file_of(items) -> bytes:
    return struct.pack("<III", 2, 0, 0) + b"".join(item_of(*item) for item in items)


@pytest.fixture
def boss_rc600(factory_frame):
    """A stand-in for 'Boss RC-600.APC64': the factory project with distinct values in every field."""
    record = parse_project_dump(factory_frame)[1]
    raw = bytearray(record.to_raw())
    for i in range(64):
        raw[i * PAD_SIZE + 2] = 1 + i % 16                   # channels
        raw[i * PAD_SIZE + 11] = i % 3                       # unknown bytes
    for s in range(8):
        raw[768 + s * STRIP_SIZE + 3] = s                    # strip unknown byte 3
    return bytes(raw), file_of(items_of(bytes(raw)))


def test_a_592_item_preset_gives_64_pads_and_8_strips(boss_rc600):   # A55, d84
    raw, data = boss_rc600
    record = parse_preset(data)
    assert record.to_raw() == raw
    assert summary(record) == {"pads": 64, "strips": 8}
    assert record.pad(PadPos(1, 1)).note == 24 and record.pads[5].channel == 6 and record.strip(4).unknown3 == 3
    assert preset_name("/home/user/Boss RC-600.APC64") == "Boss RC-600"


def test_the_real_editor_file_parses_and_round_trips_through_the_builder():   # a18, A55
    data = REAL_FILE.read_bytes()
    record = parse_preset(data)
    pad, strip = record.pad(PadPos(1, 1)), record.strip(1)
    assert (pad.note, pad.aftertouch, pad.channel, pad.outputs) == (36, True, 10, 7)
    assert (pad.rest.to_hex(), pad.pressed.to_hex()) == ("#C0C0BF", "#00FF00")
    assert (strip.resolution, strip.cc, strip.channel, strip.bar.to_hex()) == (1, 20, 7, "#0000FF")
    assert [s.cc for s in record.strips] == [20, 21, 22, 23, 24, 25, 8, 9]
    assert file_of(items_of(record.to_raw())) == data          # the synthetic builder writes the same bytes


def test_a_wrong_file_header_is_refused(boss_rc600):
    _, data = boss_rc600
    with pytest.raises(PresetError) as error:
        parse_preset(struct.pack("<III", 1, 0, 0) + data[12:])
    assert error.value.message == "the file starts with (1, 0, 0), expected (2, 0, 0) at byte 0"
    with pytest.raises(PresetError) as error:
        parse_preset(b"\x02\x00")
    assert error.value.message == "the file starts with 2 bytes, expected (2, 0, 0) at byte 0"


def test_items_may_come_in_any_order(boss_rc600):
    raw, _ = boss_rc600
    assert parse_preset(file_of(list(reversed(items_of(raw))))).to_raw() == raw


def test_580_items_is_refused(boss_rc600):   # A56, d85
    raw, _ = boss_rc600
    with pytest.raises(PresetError) as error:
        parse_preset(file_of(items_of(raw)[:580]))
    assert error.value.message == "580 items, expected 592"


def test_an_item_running_past_the_end_names_its_number_and_byte(boss_rc600):   # A57, d86
    raw, _ = boss_rc600
    items = items_of(raw)
    head = file_of(items[:341])
    data = head + item_of(*items[341])[:-2]             # item 341 cut short
    with pytest.raises(PresetError) as error:
        parse_preset(data)
    end = len(head) + (63 if items[341][0] == 0x10 else 25)
    assert error.value.message == f"item 341 ends past the end of the file at byte {end}"
    assert (error.value.item, error.value.offset) == (341, len(head))


def test_unknown_kind_wrong_kind_bad_index_repeat_and_range(boss_rc600):   # d86, d87
    raw, _ = boss_rc600
    items = items_of(raw)
    cases = [
        (lambda it: [(5, it[0][1], it[0][2])] + it[1:], "item 0 has kind 0x5 at byte 32; kinds are 0x3 (byte) and "
                                                        "0x10 (RGB)"),
        (lambda it: [(0x10, 0, b"\x00\x00\x00")] + it[1:], "item 0 (pad r1c1 note) has kind 0x10, expected 0x3 at "
                                                           "byte 32"),
        (lambda it: [(3, 900, b"\x00")] + it[1:], "item 0 has index 900 at byte 20; indices are 0–591"),
        (lambda it: [it[0], it[0]] + it[2:], "item 1 repeats index 0 of item 0 at byte 45"),
        (lambda it: [it[0], it[1], (3, 2, b"\x11")] + it[3:], "item 2 (pad r1c1 channel) is 17, outside 1–16 at "
                                                              "byte 86"),
    ]
    rgb = item_of(*items[4])
    bad_inner = rgb[:24 + 8] + struct.pack("<I", 0x10) + rgb[24 + 12:]   # an RGB part that is not a byte node
    long_byte = item_of(*items[0])[:12] + struct.pack("<III", 14, 1, 3) + b"\x00\x00"
    raw_cases = [
        (file_of(items[:4]) + bad_inner + file_of(items[5:])[12:], "item 4 has kind 0x10 at byte 144; kinds are "
                                                                   "0x3 (byte)"),
        (struct.pack("<III", 2, 0, 0) + struct.pack("<III", 26, 0, 0) + long_byte[12:] + file_of(items[1:])[12:],
         "item 0 has a 14-byte kind 0x3 value at byte 24, which must be 13 bytes and end the item at byte 38"),
    ]
    for data, message in raw_cases:
        with pytest.raises(PresetError) as error:
            parse_preset(data)
        assert error.value.message == message
    for edit, message in cases:
        with pytest.raises(PresetError) as error:
            parse_preset(file_of(edit(list(items))))
        assert error.value.message == message


def test_a_note_above_127_is_refused(boss_rc600):
    raw, _ = boss_rc600
    items = items_of(raw)
    items[3] = (3, 3, b"\x0a")   # pad r1c1 octave 10, note-in-octave 0 → 120: fine
    items[0] = (3, 0, b"\x0b")   # … note-in-octave 11 → 131
    with pytest.raises(PresetError) as error:
        parse_preset(file_of(items))
    assert error.value.message == "pad r1c1 is note 131, outside 0–127"


def test_the_field_tables_match_the_record_layout():   # F10a, F10b
    assert len(PAD_FIELDS) == 8 and len(STRIP_FIELDS) == 10
    assert field_of(511).name == "pad r8c8 unknown" and field_of(512).name == "strip 1 resolution"
    assert field_of(591).offset == 879 and field_of(592) is None
