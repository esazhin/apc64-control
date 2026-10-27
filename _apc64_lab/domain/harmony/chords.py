"""Chord detection, as the author's MusicCat Explorer does it (findChordMatches), plus the diminished and
augmented triads (suffixes ° and +, as theory.js writes them for diatonic chords).

Every template that is a subset of the played pitch-class set matches, at every root. Matches rank by
template size (most specific first), then root position before inversions; an inversion is named as a slash
chord with the bass after the slash. Octave doublings count once (d56).

Spelling from context (2026-10-27): spell_chord writes a match letter-correctly, its tones stacked on the root's
letter as the template's degrees say (C E G B♭, B D F A♭, C E G♯ for C+), every other held note as its interval
above the root. The root keeps the key's spelling when a key is given and holds it; otherwise the spelling of the
root with the fewest accidentals over the whole chord wins, the fixed table's on a tie (G♯m rather than A♭m with
its C♭, D♭ rather than C♯ with its E♯). A rare spelling (C♭, F♭, E♯, B♯, any double ♯/♭) is then replaced by the
fixed table's name for that note alone, unless the key itself spells it so (F°'s C♭ reads B: F°/B; in G♭ major it
stays C♭). find_chord_matches and chord_label stay MusicCat's.
"""
from dataclasses import dataclass
from typing import Mapping

from .spelling import PITCH_CLASS_NAMES, accidentals, is_rare, pc_name, readable, spell_above

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
# Letter steps of each template's intervals above the root: thirds stacked (a sus2 has its 2nd, a sus4 its 4th; the
# °7's sixth semitone is a diminished seventh, B–A♭; the +'s eighth an augmented fifth, C–G♯)
CHORD_LETTERS = {
    "major": (0, 2, 4), "minor": (0, 2, 4), "sus2": (0, 1, 4), "sus4": (0, 3, 4), "dom7": (0, 2, 4, 6),
    "maj7": (0, 2, 4, 6), "min7": (0, 2, 4, 6), "dim7": (0, 2, 4, 6), "half-dim7": (0, 2, 4, 6),
    "diminished": (0, 2, 4), "augmented": (0, 2, 4),
}
_INTERVALS = {quality: intervals for quality, _, intervals in CHORD_TEMPLATES}


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


@dataclass(frozen=True)
class SpelledChord:
    symbol: str                  # 'G♯m/B', 'B♭', 'F°/C♭'
    root_name: str
    names: dict                  # pitch class → its name in this chord (its tones and every other held note)


def _tones(root_name: str, root: int, quality: str) -> dict[int, str]:
    return {(root + i) % 12: spell_above(root_name, (root + i) % 12, letters)
            for i, letters in zip(_INTERVALS[quality], CHORD_LETTERS[quality])}


def _root_names(root: int, key: Mapping[int, str] | None) -> list[str]:
    if key and root in key:
        return [key[root]]
    fixed = pc_name(root)
    return [fixed] + [n for _, n in PITCH_CLASS_NAMES[root] if n != fixed and accidentals(n) <= 1 and not is_rare(n)]


def spell_chord(match: ChordMatch, notes, key: Mapping[int, str] | None = None) -> SpelledChord:
    """A chord match spelled in its own context (the module docstring); `key` maps pitch classes to a key's names."""
    best = None
    for root_name in _root_names(match.root, key):
        tones = _tones(root_name, match.root, match.quality)
        cost = sum(accidentals(n) for n in tones.values())
        if best is None or cost < best[0]:
            best = (cost, root_name, tones)
    _, root_name, names = best
    for pc in sorted({n % 12 for n in notes} - set(names)):
        names[pc] = spell_above(root_name, pc)
    names = {pc: readable(name, pc, key) for pc, name in names.items()}
    symbol = f"{root_name}{match.suffix}" + (f"/{names.get(match.bass) or readable(spell_above(root_name, match.bass), match.bass, key)}"
                                             if match.is_inversion else "")
    return SpelledChord(symbol, root_name, names)
