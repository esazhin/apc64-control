"""What a generator gives each pad: a note or silence, rest and pressed colours, aftertouch and channel
(contract §7 value objects: Rgb, PadAssignment, PadGrid). Pad 1 = r1c1 = bottom-left, then reading order."""
from dataclasses import dataclass

from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import Channel

PAD_COUNT = 64


@dataclass(frozen=True)
class Rgb:
    """Raw 8-bit RGB as written to a pad or strip record (contract d19: components 0–255)."""
    r: int
    g: int
    b: int

    def __post_init__(self):
        for value in (self.r, self.g, self.b):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                raise DomainInvariantError("colour", f"{value} is outside 0–255",
                                           "write each of red, green and blue as 0–255")

    @classmethod
    def of(cls, value) -> "Rgb":
        """From an Rgb, an (r, g, b) sequence or '#RRGGBB'."""
        if isinstance(value, Rgb):
            return value
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if len(text) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in text):
                raise DomainInvariantError("colour", f"'{value}' is not a colour",
                                           "write [r, g, b] with 0–255 each, or #RRGGBB")
            return cls(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
        parts = list(value)
        if len(parts) != 3:
            raise DomainInvariantError("colour", f"{value!r} is not three components",
                                       "write [r, g, b] with 0–255 each")
        return cls(*parts)

    @property
    def bytes(self) -> bytes:
        return bytes((self.r, self.g, self.b))

    def to_hex(self) -> str:
        return f"#{self.r:02X}{self.g:02X}{self.b:02X}"


BLACK = Rgb(0, 0, 0)
WHITE = Rgb(255, 255, 255)
RED = Rgb(255, 0, 0)


@dataclass(frozen=True)
class PadAssignment:
    """One pad of a generated layout. note None = silent and unlit (contract d3)."""
    note: int | None
    rest: Rgb = BLACK
    pressed: Rgb = BLACK
    aftertouch: bool = True     # d45: every active pad has its aftertouch flag set
    channel: int = 1            # q8: channel 1 unless the generator's 'channel' parameter says otherwise

    def __post_init__(self):
        if self.note is not None:
            if isinstance(self.note, bool) or not isinstance(self.note, int) or not 0 <= self.note <= 127:
                raise DomainInvariantError("note", f"note {self.note} is outside 0–127", "notes are 0–127")
        object.__setattr__(self, "channel", Channel(self.channel))

    @property
    def silent(self) -> bool:
        return self.note is None

    @classmethod
    def silence(cls) -> "PadAssignment":
        return cls(None, BLACK, BLACK, False)


@dataclass(frozen=True)
class NoteSpan:
    lowest: int
    highest: int

    def fits(self, transposition: int) -> bool:
        return 0 <= self.lowest + transposition and self.highest + transposition <= 127


@dataclass(frozen=True)
class PadGrid:
    """Exactly 64 assignments, r1c1 first, reading order from the bottom-left."""
    pads: tuple[PadAssignment, ...]

    def __post_init__(self):
        object.__setattr__(self, "pads", tuple(self.pads))
        if len(self.pads) != PAD_COUNT or not all(isinstance(p, PadAssignment) for p in self.pads):
            raise DomainInvariantError("pads", f"a layout has {PAD_COUNT} pads, got {len(self.pads)}",
                                       "return one PadAssignment per pad, r1c1 first")

    def at(self, pad: PadPos) -> PadAssignment:
        return self.pads[pad.index]

    def note_at(self, row: int, col: int) -> int | None:
        return self.at(PadPos(row, col)).note

    @property
    def active(self) -> tuple[tuple[PadPos, PadAssignment], ...]:
        return tuple((PadPos.from_index(i), p) for i, p in enumerate(self.pads) if not p.silent)

    def span(self) -> NoteSpan | None:
        """Lowest and highest note of the active pads, or None when every pad is silent."""
        notes = [p.note for p in self.pads if not p.silent]
        return NoteSpan(min(notes), max(notes)) if notes else None

    def highest_pad(self) -> PadPos | None:
        """The pad holding the highest note (the first such pad in reading order)."""
        active = self.active
        return max(active, key=lambda item: (item[1].note, -item[0].index))[0] if active else None

    def lowest_pad(self) -> PadPos | None:
        active = self.active
        return min(active, key=lambda item: (item[1].note, item[0].index))[0] if active else None
