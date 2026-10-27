"""HarmonyState: one snapshot of everything the harmony views show, and Harmony, which folds notes into it.

Fields (GET /api/lab/harmony, §3.5): held, chord, triads, degrees, hints, neighbours, trail, circle; and
trail_triads (beyond §3.5: the trail's triads, so the panel can draw the trail on the lattice).
- one pitch class held: every pitch class is labelled with its interval from it, and the six triads that
  contain it are the hints (d52);
- a major or minor triad held: it is lit, and its P/R/L neighbours are marked (d53, d61);
- nothing held: chord '—', nothing lit (d51).
"""
from dataclasses import dataclass, field

from .chords import NO_CHORD, chord_label, find_chord_matches
from .circle import circle_order
from .held import HeldNotes
from .spelling import degree_of, note_label, pc_name
from .tonnetz import MAJOR, MINOR, Triad, complete_triads, triads_containing
from .trail import ChordTrail


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

    def to_json(self) -> dict:
        def triad(t: Triad) -> dict:
            return {"root": t.root, "quality": t.quality, "label": t.label}
        return {
            "held": [{"note": n, "name": note_label(n), "pc": n % 12} for n in self.held],
            "chord": self.chord,
            "triads": [triad(t) for t in self.triads],
            "degrees": {pc_name(pc): label for pc, label in self.degrees},
            "hints": [triad(t) for t in self.hints],
            "neighbours": [triad(t) for t in self.neighbours],
            "trail": list(self.trail),
            "circle": [pc_name(pc) for pc in self.circle],
            "trail_triads": [triad(t) for t in self.trail_triads],
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


def analyse(notes, trail: ChordTrail | None = None) -> HarmonyState:
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
    return HarmonyState(tuple(notes), chord_label(notes), lit, degrees, hints, neighbours,
                        tuple(trail.labels) if trail else (), tuple(circle_order(pcs)),
                        tuple(trail.triads) if trail else ())


@dataclass
class Harmony:
    """Held notes plus the trail; every change returns the new snapshot (fed in played order, d58)."""
    held: HeldNotes = field(default_factory=HeldNotes)
    trail: ChordTrail = field(default_factory=ChordTrail)

    def note_on(self, note: int) -> HarmonyState:
        self.held.on(note)
        primary = _primary_triad(self.held.notes, complete_triads(self.held.pitch_classes))
        if primary is not None:
            self.trail.add(primary, chord_label(self.held.notes))
        return self.state()

    def note_off(self, note: int) -> HarmonyState:
        self.held.off(note)
        return self.state()

    def end(self, notes) -> HarmonyState:
        self.held.end(notes)
        return self.state()

    def state(self) -> HarmonyState:
        return analyse(self.held.notes, self.trail)
