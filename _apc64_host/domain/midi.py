"""MIDI value objects, the MidiMessage sum type and note names (C3 = 60, contract q1)."""
import re
from dataclasses import dataclass

from .issues import DomainInvariantError


class _Bounded(int):
    """An int within [LOW, HIGH]; anything else raises DomainInvariantError naming the field."""
    LOW, HIGH, FIELD = 0, 127, "value"

    def __new__(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or not cls.LOW <= value <= cls.HIGH:
            raise DomainInvariantError(
                cls.FIELD, f"{cls.FIELD} must be {cls.LOW}–{cls.HIGH}",
                f"write a whole number from {cls.LOW} to {cls.HIGH} (got {value!r})")
        return super().__new__(cls, value)


class Channel(_Bounded):
    """A MIDI channel as people write it, 1–16; .wire is the 0-based status nibble."""
    LOW, HIGH, FIELD = 1, 16, "channel"

    @property
    def wire(self) -> int:
        return self - 1


class Note(_Bounded):
    FIELD = "note"


class Velocity(_Bounded):
    FIELD = "velocity"


class Value7(_Bounded):
    FIELD = "value"


class Value14(_Bounded):
    HIGH, FIELD = 16383, "14-bit value"

    @property
    def msb(self) -> int:
        return self >> 7

    @property
    def lsb(self) -> int:
        return self & 0x7F

    def to7(self) -> Value7:
        """The 7-bit value of a 14-bit position: position ÷ 128 (contract d54)."""
        return Value7(self >> 7)

    @classmethod
    def from7(cls, value: int) -> "Value14":
        """A 7-bit value scaled to the full 14-bit range (127 → 16383)."""
        return cls(round(int(Value7(value)) * 16383 / 127))


class CcNumber(_Bounded):
    FIELD = "CC number"


class Program(_Bounded):
    FIELD = "program"


class Pressure(_Bounded):
    FIELD = "pressure"


def _coerce(obj, **types):
    for name, kind in types.items():
        object.__setattr__(obj, name, kind(getattr(obj, name)))


@dataclass(frozen=True)
class NoteOn:
    channel: Channel
    note: Note
    velocity: Velocity

    def __post_init__(self):
        _coerce(self, channel=Channel, note=Note, velocity=Velocity)

    def describe(self) -> str:
        return f"note {self.note} ch {self.channel}"


@dataclass(frozen=True)
class NoteOff:
    channel: Channel
    note: Note
    velocity: Velocity = 0

    def __post_init__(self):
        _coerce(self, channel=Channel, note=Note, velocity=Velocity)

    def describe(self) -> str:
        return f"note-off {self.note} ch {self.channel}"


@dataclass(frozen=True)
class ControlChange:
    channel: Channel
    control: CcNumber
    value: Value7

    def __post_init__(self):
        _coerce(self, channel=Channel, control=CcNumber, value=Value7)

    def describe(self) -> str:
        return f"CC {self.control} = {self.value} ch {self.channel}"


@dataclass(frozen=True)
class ControlChange14:
    """A 14-bit controller sent as MSB then LSB on two CC numbers."""
    channel: Channel
    msb_control: CcNumber
    lsb_control: CcNumber
    value: Value14

    def __post_init__(self):
        _coerce(self, channel=Channel, msb_control=CcNumber, lsb_control=CcNumber, value=Value14)

    def describe(self) -> str:
        return f"CC {self.msb_control}/{self.lsb_control} = {self.value} ch {self.channel}"


@dataclass(frozen=True)
class ProgramChange:
    channel: Channel
    program: Program

    def __post_init__(self):
        _coerce(self, channel=Channel, program=Program)

    def describe(self) -> str:
        return f"program {self.program} ch {self.channel}"


@dataclass(frozen=True)
class PitchBend:
    channel: Channel
    value: Value14

    def __post_init__(self):
        _coerce(self, channel=Channel, value=Value14)

    def describe(self) -> str:
        return f"pitch bend {self.value} ch {self.channel}"


@dataclass(frozen=True)
class PolyAftertouch:
    channel: Channel
    note: Note
    pressure: Pressure

    def __post_init__(self):
        _coerce(self, channel=Channel, note=Note, pressure=Pressure)

    def describe(self) -> str:
        return f"poly aftertouch {self.note} = {self.pressure} ch {self.channel}"


@dataclass(frozen=True)
class ChannelPressure:
    channel: Channel
    pressure: Pressure

    def __post_init__(self):
        _coerce(self, channel=Channel, pressure=Pressure)

    def describe(self) -> str:
        return f"channel pressure {self.pressure} ch {self.channel}"


MidiMessage = (NoteOn | NoteOff | ControlChange | ControlChange14 | ProgramChange | PitchBend
               | PolyAftertouch | ChannelPressure)

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NOTE_NAME = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
MIDDLE_C_OCTAVE = 3   # Ableton/Akai/MPC convention: C3 = 60, so C-2 = 0 and C1 = 36


def parse_note(text) -> Note:
    """A note number (0–127) or a name such as 'C1', 'F#2', 'Bb-1' with C3 = 60."""
    if isinstance(text, int) and not isinstance(text, bool):
        return Note(text)
    raw = str(text).strip()
    if raw.isdigit():
        return Note(int(raw))
    match = _NOTE_NAME.match(raw)
    if not match:
        raise DomainInvariantError(
            "note", f"'{raw}' is not a note",
            "write a number 0–127 or a name like C1 (36), F#2 or Bb3 (C3 = 60)")
    letter, accidental, octave = match.groups()
    number = (int(octave) + 5 - MIDDLE_C_OCTAVE) * 12 + _PITCH_CLASS[letter.upper()] \
        + {"#": 1, "b": -1, "": 0}[accidental]
    if not 0 <= number <= 127:
        raise DomainInvariantError("note", f"'{raw}' is outside the MIDI range",
                                   "notes run from C-2 (0) to G8 (127)")
    return Note(number)


def note_name(note: int) -> str:
    """'C1' for 36, 'F#2' for 54 (sharps, C3 = 60)."""
    note = Note(note)
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 5 + MIDDLE_C_OCTAVE}"


def note_label(note: int) -> str:
    """A note shown with its number next to its name, as every label does: 'C1 (36)'."""
    return f"{note_name(note)} ({int(note)})"
