"""Chord types and a chord's root (docs/performer-format.md, "Chord-aware lanes" and "Voicings").

CHORD_TYPES names the chord types a voicing is built from (build_voicing in voicing.py), each with its intervals in
semitones above the root and the suffix of its symbol ('m7': Am7); DEFAULT_TYPES are the eight a program offers
first. chord_root(notes) recognises the chord of some notes and answers its root's pitch class, or None: every
recognised type whose pitch classes are all among the notes' matches at every root, the larger types first, then a
root equal to the lowest note's (root position), then the order of RECOGNISED, then the lower root. It is the
default the engine asks for the root of what is held; a program with its own chord recognition passes that instead
(Performer(chord_root=…)).

Chords in key (2026-10-29): the types KEY ('key') and KEY_7 ('key 7') are not one chord but the key's own:
diatonic_chord(scale, root, seventh) stacks the scale's thirds from a root in it (degrees 1-3-5, with the seventh
1-3-5-7) and names the chord by its intervals (C major's B: m7b5; A harmonic minor's C: maj7#5), a type of
CHORD_TYPES where one fits, else one named by its degrees ('(2,b5)'). Strict: a root outside the scale, or a scale
that is not seven notes, has none.

Standard library only: this package is shared with other projects.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChordType:
    name: str                       # the key a program and a layout use: 'maj', 'm7'
    suffix: str                     # the symbol after the root: '' (C), 'm7' (Am7); plain ASCII for small displays
    intervals: tuple[int, ...]      # semitones above the root, the root (0) first

    def symbol(self, root_name: str) -> str:
        return f"{root_name}{self.suffix}"

    @property
    def label(self) -> str:
        """The type as a short label on its own: 'maj', 'm7'."""
        return self.name


CHORD_TYPES = {t.name: t for t in (
    ChordType("maj", "", (0, 4, 7)),
    ChordType("min", "m", (0, 3, 7)),
    ChordType("7", "7", (0, 4, 7, 10)),
    ChordType("maj7", "maj7", (0, 4, 7, 11)),
    ChordType("m7", "m7", (0, 3, 7, 10)),
    ChordType("sus2", "sus2", (0, 2, 7)),
    ChordType("sus4", "sus4", (0, 5, 7)),
    ChordType("dim", "dim", (0, 3, 6)),
    ChordType("aug", "aug", (0, 4, 8)),
    ChordType("6", "6", (0, 4, 7, 9)),
    ChordType("m6", "m6", (0, 3, 7, 9)),
    ChordType("dim7", "dim7", (0, 3, 6, 9)),
    ChordType("m7b5", "m7b5", (0, 3, 6, 10)),
    ChordType("7sus4", "7sus4", (0, 5, 7, 10)),
    ChordType("add9", "add9", (0, 4, 7, 2)),
    ChordType("5", "5", (0, 7)),
    # the qualities a seven-note scale's stacked thirds give besides the above (chords in key)
    ChordType("mM7", "mM7", (0, 3, 7, 11)),
    ChordType("maj7#5", "maj7#5", (0, 4, 8, 11)),
    ChordType("7b5", "7b5", (0, 4, 6, 10)),
    ChordType("7#5", "7#5", (0, 4, 8, 10)),
    ChordType("mM7b5", "mM7b5", (0, 3, 6, 11)),
    ChordType("b5", "(b5)", (0, 4, 6)),
)}
KEY, KEY_7 = "key", "key 7"           # the key's own chords: a triad, a seventh (diatonic_chord)
KEY_TYPES = (KEY, KEY_7)
DEGREES = {1: "b2", 2: "2", 3: "b3", 4: "3", 5: "4", 6: "b5", 7: "5", 8: "#5", 9: "6", 10: "b7", 11: "7"}
DEFAULT_TYPES = ("maj", "min", "7", "maj7", "m7", "sus2", "sus4", "dim")
ALIASES = {"major": "maj", "": "maj", "m": "min", "minor": "min", "dom7": "7", "min7": "m7", "°": "dim",
           "diminished": "dim", "+": "aug", "augmented": "aug", "ø": "m7b5", "half-dim7": "m7b5", "power": "5"}
# What chord_root recognises, in the order a tie is broken (the harmony views' templates: triads, sus, sevenths)
RECOGNISED = ("maj", "min", "sus2", "sus4", "7", "maj7", "m7", "dim7", "m7b5", "dim", "aug")


def chord_type(name) -> ChordType | None:
    """The chord type a name names ('m7', 'min7', 'Maj7'), or None."""
    text = str(name).strip()
    if text in CHORD_TYPES:
        return CHORD_TYPES[text]
    key = ALIASES.get(text.lower(), text.lower())
    return CHORD_TYPES.get(key) or next((t for n, t in CHORD_TYPES.items() if n.lower() == key), None)


def key_type(name) -> str | None:
    """KEY or KEY_7 when a name names one ('key', 'Key7', 'key-7'), else None."""
    text = "".join(str(name).lower().split()).replace("-", "")
    return KEY if text == "key" else KEY_7 if text == "key7" else None


def diatonic_chord(scale, root: int, seventh: bool = False) -> ChordType | None:
    """The chord of a seven-note scale (its pitch classes, any order) stacked in thirds from `root` (a note or a
    pitch class), as a ChordType named by its intervals (the module text); None for a root outside the scale or a
    scale of another size."""
    pcs = sorted({int(p) % 12 for p in scale})
    root = int(root) % 12
    if len(pcs) != 7 or root not in pcs:
        return None
    at = pcs.index(root)
    intervals = tuple((pcs[(at + k) % 7] - root) % 12 for k in ((0, 2, 4, 6) if seventh else (0, 2, 4)))
    named = next((t for t in CHORD_TYPES.values() if t.intervals == intervals), None)
    if named is not None:
        return named
    degrees = ",".join(DEGREES[i] for i in intervals[1:] if i not in (4, 7))
    return ChordType(f"({degrees})", f"({degrees})", intervals)


def chord_root(notes) -> int | None:
    """The root pitch class of the chord the notes make (the module text), or None when they make none."""
    notes = [int(n) for n in notes]
    if not notes:
        return None
    played = {n % 12 for n in notes}
    bass = min(notes) % 12
    best = None
    for order, name in enumerate(RECOGNISED):
        intervals = CHORD_TYPES[name].intervals
        for root in range(12):
            if {(root + i) % 12 for i in intervals} <= played:
                rank = (-len(intervals), root != bass, order, root)
                if best is None or rank < best[0]:
                    best = (rank, root)
    return best[1] if best is not None else None
