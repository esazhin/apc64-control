"""Chord detection, as the author's MusicCat Explorer does it (findChordMatches), plus the diminished and
augmented triads (suffixes ° and +, as theory.js writes them for diatonic chords).

Every template that is a subset of the played pitch-class set matches, at every root. Matches rank by
template size (most specific first), then root position before inversions; an inversion is named as a slash
chord with the bass after the slash. Octave doublings count once (d56).
"""
from dataclasses import dataclass

from .spelling import pc_name

# (quality, suffix, intervals): theory.js CHORD_TEMPLATES in its order, then ° and +
CHORD_TEMPLATES = (
    ("major", "", (0, 4, 7)),
    ("minor", "m", (0, 3, 7)),
    ("sus2", "sus2", (0, 2, 7)),
    ("sus4", "sus4", (0, 5, 7)),
    ("dom7", "7", (0, 4, 7, 10)),
    ("maj7", "maj7", (0, 4, 7, 11)),
    ("min7", "m7", (0, 3, 7, 10)),
    ("dim7", "dim7", (0, 3, 6, 9)),
    ("half-dim7", "m7♭5", (0, 3, 6, 10)),
    ("diminished", "°", (0, 3, 6)),
    ("augmented", "+", (0, 4, 8)),
)
NO_CHORD = "—"


@dataclass(frozen=True)
class ChordMatch:
    symbol: str          # 'C', 'Am/C', 'Bm7♭5'
    name: str            # 'C major', 'A minor / C'
    root: int
    quality: str
    suffix: str
    bass: int
    is_inversion: bool


def find_chord_matches(notes) -> list[ChordMatch]:
    """All matching templates, best first (theory.js findChordMatches)."""
    notes = list(notes)
    if not notes:
        return []
    played = {n % 12 for n in notes}
    bass = min(notes) % 12
    candidates = []
    for quality, suffix, intervals in CHORD_TEMPLATES:
        for root in range(12):
            if not {(root + i) % 12 for i in intervals} <= played:
                continue
            inversion = bass != root
            symbol = f"{pc_name(root)}{suffix}" + (f"/{pc_name(bass)}" if inversion else "")
            name = f"{pc_name(root)} {quality}" + (f" / {pc_name(bass)}" if inversion else "")
            candidates.append((len(intervals), ChordMatch(symbol, name, root, quality, suffix, bass, inversion)))
    candidates.sort(key=lambda c: (-c[0], c[1].is_inversion))   # stable, as Array.prototype.sort
    return [match for _, match in candidates]


def chord_label(notes) -> str:
    """The best match's symbol; the pitch names when nothing matches (d55); '—' when nothing is held (d51)."""
    notes = list(notes)
    if not notes:
        return NO_CHORD
    matches = find_chord_matches(notes)
    if matches:
        return matches[0].symbol
    return " ".join(pc_name(pc) for pc in sorted({n % 12 for n in notes}, key=lambda pc: (pc - min(notes)) % 12))
