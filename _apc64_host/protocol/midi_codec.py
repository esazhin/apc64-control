"""MidiMessage ↔ bytes. Encoding always writes the status byte; decoding of a stream expands running
status, and a note-on with velocity 0 decodes as a note-off (contract d135)."""
from ..domain.midi import (
    ChannelPressure, ControlChange, ControlChange14, MidiMessage, NoteOff, NoteOn, PitchBend, PolyAftertouch,
    ProgramChange, Value14,
)
from .stream import MidiStreamSplitter


def encode(message: MidiMessage) -> bytes:
    ch = message.channel.wire
    match message:
        case NoteOn():
            return bytes([0x90 | ch, message.note, message.velocity])
        case NoteOff():
            return bytes([0x80 | ch, message.note, message.velocity])
        case PolyAftertouch():
            return bytes([0xA0 | ch, message.note, message.pressure])
        case ControlChange():
            return bytes([0xB0 | ch, message.control, message.value])
        case ControlChange14():
            value = message.value
            return bytes([0xB0 | ch, message.msb_control, value.msb, 0xB0 | ch, message.lsb_control, value.lsb])
        case ProgramChange():
            return bytes([0xC0 | ch, message.program])
        case ChannelPressure():
            return bytes([0xD0 | ch, message.pressure])
        case PitchBend():
            return bytes([0xE0 | ch, message.value.lsb, message.value.msb])
    raise TypeError(f"not a MIDI message: {message!r}")


def decode(data: bytes) -> MidiMessage | None:
    """One complete channel message → MidiMessage; anything else (SysEx, realtime, short) → None."""
    if len(data) < 2 or not 0x80 <= data[0] <= 0xEF or any(b & 0x80 for b in data[1:]):
        return None
    kind, ch = data[0] & 0xF0, (data[0] & 0x0F) + 1
    if kind in (0xC0, 0xD0):
        return ProgramChange(ch, data[1]) if kind == 0xC0 else ChannelPressure(ch, data[1])
    if len(data) < 3:
        return None
    a, b = data[1], data[2]
    match kind:
        case 0x80:
            return NoteOff(ch, a, b)
        case 0x90:
            return NoteOn(ch, a, b) if b else NoteOff(ch, a, 0)
        case 0xA0:
            return PolyAftertouch(ch, a, b)
        case 0xB0:
            return ControlChange(ch, a, b)
    return PitchBend(ch, Value14(a | (b << 7)))


class MidiDecoder:
    """Chunks in, MidiMessages out (SysEx and realtime are skipped)."""

    def __init__(self):
        self._splitter = MidiStreamSplitter()

    def feed(self, chunk: bytes) -> list[MidiMessage]:
        return [m for m in (decode(raw) for raw in self._splitter.feed(chunk)) if m is not None]
