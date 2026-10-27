"""Pitch classes and the window intervals (contract §7 value objects: PitchClass, Interval)."""
from enum import Enum

from _apc64_host.domain.issues import DomainInvariantError

from .harmony.spelling import pc_name


class PitchClass(int):
    """0–11, C = 0."""

    def __new__(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 11:
            raise DomainInvariantError("pitch class", f"{value!r} is not a pitch class", "pitch classes are 0–11 (C = 0)")
        return super().__new__(cls, value)

    @classmethod
    def of(cls, note: int) -> "PitchClass":
        return cls(int(note) % 12)

    @property
    def name(self) -> str:
        """The fixed spelling without key context: C C♯ D E♭ E F F♯ G A♭ A B♭ B (§2.7 a25)."""
        return pc_name(self)

    @property
    def fifths_index(self) -> int:
        """Position on the circle of fifths, C = 0, G = 1, … F = 11."""
        return (int(self) * 7) % 12


class Interval(Enum):
    """One window step: octave 12, fifth 7, (major) third 4 semitones (contract d35–d37)."""
    OCTAVE = (12, "Oct")
    FIFTH = (7, "5th")
    THIRD = (4, "3rd")

    def __init__(self, semitones: int, label: str):
        self.semitones = semitones
        self.label = label

    def next(self) -> "Interval":
        """Tempo cycles octave → fifth → third → octave (contract d33)."""
        order = list(Interval)
        return order[(order.index(self) + 1) % len(order)]
