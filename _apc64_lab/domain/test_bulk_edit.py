"""Bulk edits over a captured record (§2.7 q1)."""
import pytest

from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.domain.bulk_edit import BulkEdit, apply_all
from _apc64_lab.domain.memory_sysex import parse_project_dump
from _apc64_lab.domain.records import refusal_text


def factory(frame):
    return parse_project_dump(frame)[1]


def test_every_pad_of_a_slot_to_channel_3(factory_frame):   # §2.7 q1 example
    before = factory(factory_frame)
    after = BulkEdit.parse("all pads channel 3").apply(before)
    assert all(pad.channel == 3 for pad in after.pads)
    assert after.strips == before.strips
    for a, b in zip(before.pads, after.pads):
        assert a.raw[:2] == b.raw[:2] and a.raw[3:] == b.raw[3:]   # only byte 2 changed


def test_two_rows_coloured_red(factory_frame):   # §2.7 q1 example 'pads r1c1–r2c8 colour red'
    after = BulkEdit.parse("pads r1c1-r2c8 colour red").apply(factory(factory_frame))
    assert all(after.pad(PadPos.from_index(i)).rest.to_hex() == "#FF0000" for i in range(16))
    assert after.pad(PadPos(3, 1)).rest.to_hex() == "#FFFFFF"


def test_unknown_bytes_survive_every_edit(factory_frame):   # inv3
    record = factory(factory_frame)
    pad = record.pads[11]
    record = record.with_pad_records({11: pad.__class__(pad.raw[:11] + b"\x05")})
    edits = [BulkEdit.parse(t) for t in ("all pads channel 2", "all pads pressed #00FF00", "all pads aftertouch on",
                                         "all pads transpose 12", "strips 1-8 channel 4", "strip 3 bipolar on")]
    after = apply_all(record, edits)
    assert after.pads[11].unknown == 0x05 and after.pad(PadPos(1, 1)).note == 36
    assert all(s.raw[3] == r.raw[3] and s.raw[5] == r.raw[5] for s, r in zip(after.strips, record.strips))
    assert after.strip(3).bipolar and after.strip(1).channel == 4


def test_edits_are_validated_naming_the_field(factory_frame):   # inv10, d101
    for text, message in (("all pads channel 17", "channel 17: channels are 1–16"),
                          ("strip 3 aftertouch on", "strips have no field 'aftertouch'; fields are channel, bar, "
                                                    "indicator, bipolar, outputs"),
                          ("all pads transpose 70", "transpose +70 puts pad r8c8 at note 157: notes are 0–127; "
                                                    "transpose less")):
        with pytest.raises(DomainInvariantError) as error:
            BulkEdit.parse(text).apply(factory(factory_frame))
        assert refusal_text(error.value) == message
    with pytest.raises(DomainInvariantError):
        BulkEdit.parse("all pads colour [300,0,0]")
    with pytest.raises(DomainInvariantError):
        BulkEdit.parse("encoder channel 3")
