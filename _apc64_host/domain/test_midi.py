import pytest

from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import (
    Channel, ChannelPressure, ControlChange, ControlChange14, Note, NoteOff, NoteOn, PitchBend, PolyAftertouch,
    ProgramChange, Value14, Velocity, note_label, note_name, parse_note,
)


def test_channel_17_is_refused_naming_the_field_and_the_fix():
    with pytest.raises(DomainInvariantError) as raised:
        Channel(17)
    assert raised.value.field == "channel"
    assert raised.value.problem == "channel must be 1–16"
    assert "1 to 16" in raised.value.fix


def test_bounded_values_refuse_bools_floats_and_out_of_range():
    for bad in (True, 3.0, -1, 128):
        with pytest.raises(DomainInvariantError):
            Note(bad)
    with pytest.raises(DomainInvariantError):
        Value14(16384)
    assert Channel(10).wire == 9 and Velocity(0) == 0


def test_note_names_use_c3_as_middle_c():
    assert parse_note("C1") == 36
    assert parse_note("C3") == 60
    assert parse_note("C-2") == 0 and parse_note("G8") == 127
    assert parse_note("F#2") == 54 and parse_note("Bb2") == 58 and parse_note("f2") == 53
    assert parse_note(38) == 38 and parse_note("38") == 38


def test_unknown_or_out_of_range_note_names_are_refused():
    for bad in ("H2", "C", "G#8", "C-3"):
        with pytest.raises(DomainInvariantError) as raised:
            parse_note(bad)
        assert raised.value.field == "note"


def test_note_names_format_with_sharps_and_labels_carry_the_number():
    assert note_name(36) == "C1" and note_name(53) == "F2" and note_name(61) == "C#3"
    assert note_label(36) == "C1 (36)"
    for n in range(128):
        assert parse_note(note_name(n)) == n


def test_messages_coerce_their_fields_and_refuse_bad_values():
    assert NoteOn(10, 36, 127) == NoteOn(Channel(10), Note(36), Velocity(127))
    with pytest.raises(DomainInvariantError):
        ControlChange(1, 128, 0)
    with pytest.raises(DomainInvariantError):
        PitchBend(0, 8192)


def test_messages_describe_themselves_for_the_activity_list():
    assert NoteOn(10, 36, 127).describe() == "note 36 ch 10"
    assert NoteOff(10, 36).describe() == "note-off 36 ch 10"
    assert ControlChange(1, 118, 127).describe() == "CC 118 = 127 ch 1"
    assert ControlChange14(1, 20, 52, 8192).describe() == "CC 20/52 = 8192 ch 1"
    assert ProgramChange(1, 5).describe() == "program 5 ch 1"
    assert PitchBend(2, 8192).describe() == "pitch bend 8192 ch 2"
    assert PolyAftertouch(2, 53, 10).describe() == "poly aftertouch 53 = 10 ch 2"
    assert ChannelPressure(2, 90).describe() == "channel pressure 90 ch 2"


def test_fourteen_bit_values_split_and_scale():
    value = Value14(16383)
    assert (value.msb, value.lsb, value.to7()) == (127, 127, 127)
    assert Value14(8192).to7() == 64
    assert Value14.from7(127) == 16383 and Value14.from7(0) == 0
