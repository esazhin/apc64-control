"""Records keep every byte they do not interpret (inv3), on the contract §4.2 values (T4)."""
import pytest

from .conftest import fixture_bytes

from _apc64_host.domain.controls import PadPos, Strip
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_lab.domain.generators import FifthsHue, TonnetzCheckerboard, generate, parse_params
from _apc64_lab.domain.memory_sysex import parse_global_dump, parse_project_dump
from _apc64_lab.domain.pads import Rgb
from _apc64_lab.domain.records import (
    FIELDS, PAD_SIZE, Confirmation, GlobalChange, GlobalSettings, ProjectRecord, RecordLengthError,
    StripAssignment, refusal_text,
)


def tonnetz_grid():
    gen = TonnetzCheckerboard()
    return generate(gen, parse_params(gen.params, {"base": 48}), FifthsHue())


def slot7_loops(factory_frame) -> ProjectRecord:
    """'Loops' in slot 7: the factory record with pad 12's unknown byte 0x05 and strip 3's 0x02/0x03."""
    record = parse_project_dump(factory_frame)[1]
    pad12 = record.pads[11]
    pad12 = pad12.__class__(pad12.raw[:11] + b"\x05")
    strip3 = record.strip(3)
    strip3 = strip3.__class__(strip3.raw[:3] + b"\x02" + strip3.raw[4:5] + b"\x03" + strip3.raw[6:])
    return record.with_pad_records({11: pad12}).with_strip_records({3: strip3})


def test_the_factory_pads_are_note_24_plus_index_white_and_red(factory_frame):   # p8, F10a
    record = parse_project_dump(factory_frame)[1]
    pad = record.pad(PadPos(1, 1))
    assert (pad.note, pad.channel, pad.rest.to_hex(), pad.pressed.to_hex(), pad.outputs) == (24, 1, "#FFFFFF",
                                                                                         "#FF0000", 7)
    assert record.pad(PadPos(8, 8)).note == 87
    assert record.strip(1).cc == 16 and record.strip(8).lsb == 0x77


def test_with_pads_keeps_pad_byte_11_and_strip_bytes_3_and_5(factory_frame):   # A2, inv3
    loops = slot7_loops(factory_frame)
    assert loops.pads[11].unknown == 0x05 and (loops.strip(3).unknown3, loops.strip(3).unknown5) == (2, 3)
    written = loops.with_pads(tonnetz_grid())
    assert written.pads[11].unknown == 0x05
    assert (written.strip(3).unknown3, written.strip(3).unknown5) == (0x02, 0x03)
    assert written.strips == loops.strips   # without a strip section the strips are written back as read


def test_with_pads_writes_the_generated_notes_and_colours(factory_frame):   # d43, A8
    written = parse_project_dump(factory_frame)[1].with_pads(tonnetz_grid())
    r1c1, r1c2 = written.pad(PadPos(1, 1)), written.pad(PadPos(1, 2))
    assert (r1c1.note, r1c1.aftertouch, r1c1.rest.to_hex(), r1c1.pressed.to_hex(), r1c1.outputs) == (
        48, True, "#FFFFFF", "#FF0000", 7)
    assert written.pad(PadPos(1, 3)).note == 55 and written.pad(PadPos(2, 2)).note == 52
    assert (r1c2.rest.to_hex(), r1c2.pressed.to_hex(), r1c2.outputs) == ("#000000", "#000000", 0)
    assert r1c2.raw[0:4] == parse_project_dump(factory_frame)[1].pad(PadPos(1, 2)).raw[0:4]   # note bytes kept


def test_only_the_bytes_of_generated_fields_change(factory_frame):   # inv3
    base = slot7_loops(factory_frame)
    written = base.with_pads(tonnetz_grid())
    for before, after in zip(base.pads, written.pads):
        assert after.raw[11] == before.raw[11]


def test_the_strip_section_writes_strip_fields_and_keeps_bytes_3_and_5(factory_frame):   # §2.7 q6
    loops = slot7_loops(factory_frame)
    written = loops.with_strips({3: StripAssignment(cc=30, channel=2, lsb=62, bar=Rgb(0, 0, 255),
                                                    indicator=Rgb(0, 255, 0), bipolar=True)})
    strip = written.strip(3)
    assert (strip.resolution, strip.cc, strip.lsb, strip.channel, strip.bar.to_hex(), strip.indicator.to_hex(),
            strip.bipolar, strip.outputs) == (2, 30, 62, 2, "#0000FF", "#00FF00", True, 7)
    assert (strip.unknown3, strip.unknown5) == (0x02, 0x03)
    assert written.strip(1) == loops.strip(1) and written.pads == loops.pads
    seven_bit = loops.with_strips({3: StripAssignment(cc=31)}).strip(3)
    assert (seven_bit.resolution, seven_bit.cc, seven_bit.lsb) == (1, 31, loops.strip(3).lsb)
    with pytest.raises(DomainInvariantError):
        StripAssignment(cc=128)


def test_differences_name_the_pad_and_strip(factory_frame):   # inv4 warning text
    base = parse_project_dump(factory_frame)[1]
    other = base.with_pad_records({PadPos(3, 4).index: base.pad(PadPos(3, 4)).with_fields(rest=Rgb(1, 2, 3))})
    assert base.differences(other) == ["pad r3c4"]
    assert base.differences(base) == []


def test_a_record_of_the_wrong_length_is_refused():   # d66, A47
    with pytest.raises(RecordLengthError) as error:
        ProjectRecord(bytes(512))
    assert (error.value.received, error.value.expected) == (512, 880)
    assert str(error.value) == "a project record holds 512 bytes, expected 880"
    with pytest.raises(RecordLengthError):
        GlobalSettings(bytes(55))


# --- global settings -------------------------------------------------------------------------------------
def block(led=2, unknown=bytes([1] + [0] * 18 + [0x0A])) -> GlobalSettings:
    """A63's block: bytes 0–19 = 01 00 … 0A, LED level 75 % (2), CV2 channel 1."""
    raw = bytearray(56)
    raw[0:20] = unknown
    raw[31:39] = bytes([1, 1, 2, 2, 3, 3, 4, 4])
    raw[39:55] = bytes(range(36, 52))
    raw[55] = led
    return GlobalSettings(bytes(raw))


def test_the_captured_block_decodes_into_named_fields(global_frame):   # A62, d88
    settings = parse_global_dump(global_frame)
    shown = {f["field"]: f["text"] for f in settings.fields()}
    assert shown["device_mode"] == "Standalone" and shown["standalone_sync"] == "Internal"   # as captured
    backup = GlobalSettings(fixture_bytes("apc64-global-backup-before-write.bin"))
    assert backup.describe("device_mode") == "Device mode Ableton Live"
    assert shown["sync_out"] == "off" and shown["led_level"] == "100%"
    assert shown["cv1_source"] == "0 Pitch-Last [TBD]" and shown["cv2_source"] == "3 Gate-Last [TBD]"
    assert shown["cv3_channel"] == "2" and shown["drum1_note"] == "36" and shown["drum16_note"] == "51"
    assert len(settings.fields()) == 3 + 8 + 8 + 16 + 1
    assert block().describe("led_level") == "LED level 75%"


def test_led_100_changes_only_byte_55(global_frame):   # A63, inv3
    before = block()
    after = before.with_change(GlobalChange.parse({"led_level": "100%"}))
    assert [i for i in range(56) if before.raw[i] != after.raw[i]] == [55]
    assert after.raw[0:20] == bytes([1] + [0] * 18 + [0x0A]) and after.led_percent == 100


def test_several_fields_in_one_change(global_frame):   # A65 (domain half), d92
    change = GlobalChange.parse({"led_level": 100, "cv2_channel": 4})
    after = block().with_change(change)
    assert after.led_percent == 100 and after.cv_channel(2) == 4
    assert [i for i in range(56) if block().raw[i] != after.raw[i]] == [32, 55]


def test_an_unchanged_value_is_found_before_any_write():   # A67 (domain half), d94
    settings = block(led=3)
    change = GlobalChange.parse({"led_level": "100"})
    assert not settings.changed_by(change) and change.labels() == "LED level"
    assert GlobalChange.parse({"led_level": 100, "cv2_channel": 4}).labels() == "LED level and CV2 channel"


def test_cv3_channel_17_is_refused_naming_the_field():   # A66, d93
    with pytest.raises(DomainInvariantError) as error:
        GlobalChange.parse({"cv3_channel": 17})
    assert error.value.field == "cv3_channel" and refusal_text(error.value) == "CV3 channel 17: channels are 1–16"


def test_out_of_range_drum_note_led_level_and_unknown_field():   # d93
    for changes, text in (({"drum5_note": 130}, "Drum 5 note 130: notes are 0–127"),
                          ({"led_level": 60}, "LED level 60%: levels are 25, 50, 75 or 100%"),
                          ({"cv1_source": 99}, "CV1 source 99: sources are 0–15 (manual §5.6 order)")):
        with pytest.raises(DomainInvariantError) as error:
            GlobalChange.parse(changes)
        assert refusal_text(error.value) == text
    with pytest.raises(DomainInvariantError) as error:
        GlobalChange.parse({"brightness": 3})
    assert error.value.problem == "no setting 'brightness'" and "led_level" in error.value.fix


def test_device_mode_needs_confirmation():   # A64, d91, inv8
    change = GlobalChange.parse({"device_mode": "Standalone"})
    assert change.values == (("device_mode", 1),) and change.hazards() == ("device_mode",)
    with pytest.raises(DomainInvariantError) as error:
        change.check(None)
    # the contract's text, then how to go ahead
    assert refusal_text(error.value) == ("device mode change needs confirmation: it changes how the unit starts; "
                                         "repeat the command with confirm")
    change.check(Confirmation())
    assert GlobalChange.parse({"led_level": 100}).hazards() == ()


def test_sync_changes_need_confirmation_too():   # inv8 ('device-mode and sync changes')
    for field in ("standalone_sync", "sync_out"):
        change = GlobalChange.parse({field: "usb"})
        with pytest.raises(DomainInvariantError, match="needs confirmation"):
            change.check(None)
    assert set(FIELDS) >= {"device_mode", "standalone_sync", "sync_out", "led_level", "cv8_channel", "drum16_note"}
