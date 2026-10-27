import pytest

from _apc64_host.domain.midi import (
    ChannelPressure, ControlChange, ControlChange14, NoteOff, NoteOn, PitchBend, PolyAftertouch, ProgramChange,
)
from _apc64_host.protocol.conftest import capture
from _apc64_host.protocol.midi_codec import MidiDecoder, decode, encode


def test_a_velocity_zero_note_on_decodes_as_a_note_off():   # A111, d135
    assert decode(bytes.fromhex("903500")) == NoteOff(1, 53, 0)
    assert decode(bytes.fromhex("903538")) == NoteOn(1, 53, 56)


@pytest.mark.parametrize("message", [NoteOn(10, 36, 127), NoteOff(2, 53), PolyAftertouch(2, 53, 10),
                                     ControlChange(1, 118, 127), ProgramChange(1, 5), ChannelPressure(2, 90),
                                     PitchBend(2, 8192), PitchBend(16, 16383)])
def test_messages_round_trip(message):
    assert decode(encode(message)) == message


def test_encoding_matches_the_wire():
    assert encode(NoteOn(10, 36, 127)) == bytes.fromhex("99247F")
    assert encode(PitchBend(2, 8192)) == bytes.fromhex("E10040")
    assert encode(ControlChange14(1, 20, 52, 8193)) == bytes.fromhex("B01440B03401")


def test_the_notes_port_capture_decodes_with_running_status_and_chunking():
    raw = b"".join(data for port, data in capture("daw-mode-views-velocity-aftertouch-2026-10-23.log")
                   if port == "Notes")
    decoder = MidiDecoder()
    messages = []
    for i in range(0, len(raw), 5):
        messages += decoder.feed(raw[i:i + 5])
    assert messages[:4] == [NoteOn(1, 53, 0x38), PolyAftertouch(1, 53, 10), PolyAftertouch(1, 53, 0), NoteOff(1, 53, 0)]
    assert len(messages) == len([1 for port, _ in capture("daw-mode-views-velocity-aftertouch-2026-10-23.log")
                                 if port == "Notes"])
    assert MidiDecoder().feed(bytes.fromhex("9035383600")) == [NoteOn(1, 53, 56), NoteOff(1, 54, 0)]


def test_non_channel_data_is_not_a_message():
    assert decode(bytes.fromhex("F07E7F0601F7")) is None and decode(b"\xf8") is None and decode(b"\x90\x35") is None
