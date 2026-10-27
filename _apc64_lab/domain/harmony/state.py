"""HarmonyState: one snapshot of everything the harmony views show, and Harmony, which folds notes into it.

Fields (GET /api/lab/harmony, §3.5): held, chord, triads, degrees, hints, neighbours, trail, circle; and, beyond
§3.5, trail_triads (the trail's triads, so the panel can draw the trail on the lattice) and chord_root and
chord_tones (the named chord's root and pitch classes, so the pad grid can mark them; None and () without one);
and `played` (the guitar amendment): each held voice as (source, channel, note), the channel where the source
gives a string identity (the APC64's Custom port; None elsewhere), so the neck view can place a note on its string.
The core never fills it: the tracker, which knows the sources, adds it.
- one pitch class held: every pitch class is labelled with its interval from it, and the six triads that
  contain it are the hints (d52);
- a major or minor triad held: it is lit, and its P/R/L neighbours are marked (d53, d61);
- nothing held: chord '—', nothing lit (d51).

Spelling from context (2026-10-27): `names` spells every pitch class for what is held (spell_held), and the chord,
the held notes and the trail entries use it: the named chord's own spelling when the held notes form a chord (E
major → G♯; B♭ major → B♭ D F); else the key's, when the layout gives one (a `scale` scheme), with any note outside
it spelled above the lowest held note; else each note as its interval above the lowest held note (E + a major third
→ G♯). A rare spelling (C♭, F♭, E♯, B♯, a double ♯/♭) becomes the plain name unless the key needs it.
Display and lookup are apart: `degrees` keys, `circle` and each triad's `label` keep the fixed table (the views look
places up by them); each triad also carries `display`, its root as spelled now (with E major held the neighbours
display Em, C♯m, G♯m), and `names` spells all 12 pitch classes for the lattice's nodes and the held keys.
"""
from dataclasses import dataclass, field
from typing import Mapping

from .chords import CHORD_TEMPLATES, NO_CHORD, find_chord_matches, spell_chord
from .circle import circle_order
from .held import HeldNotes
from .spelling import degree_of, note_label_spelled, pc_name, readable, spell_above
from .tonnetz import MAJOR, MINOR, Triad, complete_triads, triads_containing
from .trail import ChordTrail, TrailEntry


@dataclass(frozen=True)
class HarmonyState:
    held: tuple[int, ...] = ()
    chord: str = NO_CHORD
    triads: tuple[Triad, ...] = ()
    degrees: tuple[tuple[int, str], ...] = ()       # (pitch class, '♭3') when one pitch class is held
    hints: tuple[Triad, ...] = ()
    neighbours: tuple[Triad, ...] = ()
    trail: tuple[str, ...] = ()
    circle: tuple[int, ...] = ()
    trail_triads: tuple[Triad, ...] = ()            # the trail's triads, for drawing it on the lattice
    chord_root: int | None = None                   # the named chord's root pitch class
    chord_tones: tuple[int, ...] = ()               # its pitch classes (the template's), root first
    played: tuple[tuple[str, int | None, int], ...] = ()   # (source, channel or None, note) per held voice
    names: tuple[str, ...] = ()                     # the 12 pitch classes as spelled for what is held (C first)

    def name_of(self, pc: int) -> str:
        return self.names[pc % 12] if len(self.names) == 12 else pc_name(pc)

    def to_json(self) -> dict:
        def triad(t: Triad) -> dict:
            display = self.name_of(t.root) + ("m" if t.quality == MINOR else "")
            return {"root": t.root, "quality": t.quality, "label": t.label, "display": display}
        return {
            "held": [{"note": n, "name": note_label_spelled(n, self.name_of(n)), "pc": n % 12} for n in self.held],
            "chord": self.chord,
            "triads": [triad(t) for t in self.triads],
            "degrees": {pc_name(pc): label for pc, label in self.degrees},
            "hints": [triad(t) for t in self.hints],
            "neighbours": [triad(t) for t in self.neighbours],
            "trail": list(self.trail),
            "circle": [pc_name(pc) for pc in self.circle],
            "trail_triads": [triad(t) for t in self.trail_triads],
            "chord_root": self.chord_root,
            "chord_tones": list(self.chord_tones),
            "played": [{"source": source, "channel": channel, "note": note} for source, channel, note in self.played],
            "names": {str(pc): self.name_of(pc) for pc in range(12)},
        }


def _primary_triad(notes, lit: tuple[Triad, ...]) -> Triad | None:
    """The lit triad the chord is named after when there is one, else the first lit triad."""
    if not lit:
        return None
    for match in find_chord_matches(notes):
        if match.quality in (MAJOR, MINOR):
            named = Triad(match.root, match.quality)
            if named in lit:
                return named
    return lit[0]


@dataclass(frozen=True)
class Spelling:
    chord: str                   # the chord's symbol, or the held notes' names, or '—'
    names: tuple[str, ...]       # all 12 pitch classes, C first


def spell_held(notes, key: Mapping[int, str] | None = None) -> Spelling:
    """The held notes spelled from their context (the module docstring). `key` maps a key's pitch classes to its
    names (a scale overlay's spelling)."""
    notes = sorted(set(notes))
    if not notes:
        return Spelling(NO_CHORD, tuple((key or {}).get(pc) or pc_name(pc) for pc in range(12)))
    lowest = pc_name(notes[0])
    if key and notes[0] % 12 in key:
        lowest = key[notes[0] % 12]
    matches = find_chord_matches(notes)
    if matches:
        chord = spell_chord(matches[0], notes, key)
        names = tuple(chord.names.get(pc) or readable(spell_above(chord.root_name, pc), pc, key) for pc in range(12))
        return Spelling(chord.symbol, names)
    names = tuple((key or {}).get(pc) or readable(spell_above(lowest, pc), pc, key) for pc in range(12))
    order = sorted({n % 12 for n in notes}, key=lambda pc: (pc - notes[0]) % 12)
    return Spelling(" ".join(names[pc] for pc in order), names)


def analyse(notes, trail: ChordTrail | None = None, key: Mapping[int, str] | None = None) -> HarmonyState:
    notes = sorted(set(notes))
    pcs = {n % 12 for n in notes}
    lit = complete_triads(pcs)
    degrees, hints, neighbours = (), (), ()
    if len(pcs) == 1:
        (single,) = pcs
        degrees = tuple((pc, degree_of(pc, single)) for pc in range(12))
        hints = triads_containing(single)
    primary = _primary_triad(notes, lit)
    if primary is not None:
        neighbours = primary.neighbours()
    chord_root, chord_tones = _chord_tones(notes)
    spelled = spell_held(notes, key)
    return HarmonyState(tuple(notes), spelled.chord, lit, degrees, hints, neighbours,
                        tuple(trail.labels) if trail else (), tuple(circle_order(pcs)),
                        tuple(trail.triads) if trail else (), chord_root, chord_tones, names=spelled.names)


_INTERVALS = {quality: intervals for quality, _, intervals in CHORD_TEMPLATES}


def _chord_tones(notes) -> tuple[int | None, tuple[int, ...]]:
    """The best chord match's root and its template's pitch classes (the name's chord, not every held note)."""
    matches = find_chord_matches(notes)
    if not matches:
        return None, ()
    best = matches[0]
    return best.root, tuple((best.root + i) % 12 for i in _INTERVALS[best.quality])


@dataclass
class Harmony:
    """Held notes plus the trail; every change returns the new snapshot (fed in played order, d58).

    `key` is the spelling context a layout gives (pitch class → name; empty for none). The trail takes every named
    chord at a note-on (trail.py); `_growing` says the newest entry was made by notes still held, none released
    since, so a chord that grows replaces it."""
    held: HeldNotes = field(default_factory=HeldNotes)
    trail: ChordTrail = field(default_factory=ChordTrail)
    key: dict = field(default_factory=dict)
    _growing: bool = False

    def note_on(self, note: int) -> HarmonyState:
        self.held.on(note)
        notes = self.held.notes
        matches = find_chord_matches(notes)
        if matches:
            best = matches[0]
            primary = _primary_triad(notes, complete_triads(self.held.pitch_classes))
            label = spell_chord(best, notes, self.key).symbol
            self.trail.add(TrailEntry(best.root, best.quality, label, primary), grow=self._growing)
            self._growing = True
        return self.state()

    def note_off(self, note: int) -> HarmonyState:
        self.held.off(note)
        self._growing = False
        return self.state()

    def end(self, notes) -> HarmonyState:
        self.held.end(notes)
        self._growing = False
        return self.state()

    def clear_trail(self) -> HarmonyState:
        self.trail.clear()
        self._growing = False
        return self.state()

    def set_key(self, key: Mapping[int, str] | None) -> bool:
        """The layout's key spelling (None: no key); True when it changed."""
        key = {int(pc) % 12: str(name) for pc, name in dict(key or {}).items()}
        if key == self.key:
            return False
        self.key = key
        return True

    def state(self) -> HarmonyState:
        return analyse(self.held.notes, self.trail, self.key)
