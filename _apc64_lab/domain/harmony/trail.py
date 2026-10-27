"""ChordTrail (d57, amended 2026-10-27): the chords played, newest last, the last 8 kept.

Any chord the namer recognises is an entry (find_chord_matches: three or more pitch classes forming one of its
templates; a single note, two notes and an unnamed set are not chords). The same chord again in a row adds
nothing: the same root and quality, whatever the inversion or bass. A chord that grows with no release in between
replaces its own newest entry (C E G, then + B: the entry becomes Cmaj7, not C then Cmaj7); when the grown chord
equals the entry before it, the two collapse into one. Each entry keeps its primary major or minor triad, if it has
one, so the Tonnetz and the circle draw the trail through triads; an entry without one (sus4, °, °7…) is in the
trail's text only.
"""
from dataclasses import dataclass, field

from .tonnetz import Triad

TRAIL_LENGTH = 8


@dataclass(frozen=True)
class TrailEntry:
    root: int
    quality: str                 # the chord template's quality: 'major', 'minor', 'dom7', 'sus4' …
    label: str                   # as spelled when it was played: 'G♯m', 'Cmaj7/E'
    triad: Triad | None = None   # its primary major or minor triad, for the drawings

    def same(self, other: "TrailEntry") -> bool:
        return (self.root % 12, self.quality) == (other.root % 12, other.quality)

    @classmethod
    def of_triad(cls, triad: Triad, label: str | None = None) -> "TrailEntry":
        return cls(triad.root, triad.quality, label or triad.label, triad)


@dataclass
class ChordTrail:
    entries: list = field(default_factory=list)   # [TrailEntry]
    length: int = TRAIL_LENGTH

    def add(self, chord: "TrailEntry | Triad", label: str | None = None, grow: bool = False) -> bool:
        """Adds a chord unless it is the newest entry already; `grow` (the notes that made the newest entry are
        still held, with more added) replaces the newest instead. Returns whether the trail changed."""
        entry = chord if isinstance(chord, TrailEntry) else TrailEntry.of_triad(chord, label)
        if self.entries and self.entries[-1].same(entry):
            return False
        if grow and self.entries:
            self.entries.pop()
            if self.entries and self.entries[-1].same(entry):
                return True
        self.entries.append(entry)
        del self.entries[:-self.length]
        return True

    @property
    def triads(self) -> list[Triad]:
        """The entries' triads, in order; an entry without one is skipped."""
        return [e.triad for e in self.entries if e.triad is not None]

    @property
    def labels(self) -> list[str]:
        return [e.label for e in self.entries]

    def clear(self) -> None:
        self.entries.clear()
