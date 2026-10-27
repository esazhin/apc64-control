"""LabWindow: where the window sits on the lattice (contract d33–d40, inv11).

Each interval keeps its own step count. The window is transposed by 12·octave + 7·fifth + 4·third semitones,
and the OLED shows the current interval's count ('5th +2'). A step that would push any active pad outside
0–127 is refused as an Edge: the window stays and row 2 adds 'edge' (d29). A multi-step message is taken or
refused as a whole (a build decision: the window never lands on a position nobody asked for).
"""
from dataclasses import dataclass, field

from _apc64_host.domain.oled import OledText

from .music import Interval
from .pads import NoteSpan


def _counts(octave: int = 0, fifth: int = 0, third: int = 0) -> tuple[tuple[Interval, int], ...]:
    return ((Interval.OCTAVE, octave), (Interval.FIFTH, fifth), (Interval.THIRD, third))


@dataclass(frozen=True)
class LabWindow:
    interval: Interval = Interval.OCTAVE                      # d38: each activation starts at octave …
    counts: tuple[tuple[Interval, int], ...] = field(default_factory=_counts)   # … with every count at 0

    def count(self, interval: Interval | None = None) -> int:
        return dict(self.counts)[interval or self.interval]

    def transposition(self) -> int:
        return sum(interval.semitones * n for interval, n in self.counts)

    def label(self) -> str:
        return f"{self.interval.label} {self.count():+d}"

    def cycled(self) -> "LabWindow":
        """Tempo: the next interval; steps already counted keep their interval (d34)."""
        return LabWindow(self.interval.next(), self.counts)

    def stepped(self, steps: int) -> "LabWindow":
        """`steps` more of the current interval, unchecked."""
        counts = tuple((i, n + steps if i is self.interval else n) for i, n in self.counts)
        return LabWindow(self.interval, counts)

    def shifted(self, steps: int, span: NoteSpan | None) -> "LabWindow | Edge":
        """`steps` (±n) of the current interval, or Edge when `span` (the active notes at transposition 0)
        would leave 0–127."""
        moved = self.stepped(steps)
        if span is not None and not span.fits(moved.transposition()):
            return Edge(self, steps)
        return moved

    def oled(self, name: str, edge: bool = False) -> OledText:
        """Row 1 the layout name, row 2 interval and count (d40, d41: both cut to 14 characters)."""
        return OledText(name, self.label() + (" edge" if edge else ""))


@dataclass(frozen=True)
class Edge:
    """A refused step: the window it stays at and the steps that were asked for."""
    window: LabWindow
    steps: int

    def oled(self, name: str) -> OledText:
        return self.window.oled(name, edge=True)
