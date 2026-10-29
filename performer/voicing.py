"""A chord voiced on the strings: a root note on its string and a chord type → one note per string, or muted
(docs/performer-format.md, "Voicings").

    build_voicing({6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}, root=48, string=5, chord="maj")
    → Voicing x32010: string 5 C, 4 E, 3 G (open), 2 C, 1 E (open); string 6 muted

The rules:
- The root is the bass: it stays on its string at its fret (root − the open note; below the open note there is no
  voicing), every lower string is muted, and no note of the voicing is below it.
- Every higher string takes a chord tone or is muted. The fretted notes lie within a span of 4 frets; an open string
  is used where it is a chord tone and the shape is in the open position (no fretted note above fret 3).
- The shape must be playable by one hand: at its lowest fret one barre across the strings between (a barre cannot
  pass over an open string), or, with the root open, one finger on each string there (A7 x02020); every higher fret
  one finger per run of neighbouring strings (a partial barre); four fingers at most.
- Of the playable shapes the best is, in this order: the most of the chord without its fifth (the root, each
  third, sus note, seventh, sixth or ♭5), the fewest muted strings between sounding ones, the most sounding strings,
  the most open strings, the fifth, the CAGED shape of the root's string (root on string 6 the E shape R 5 R 3 5 R,
  on 5 the A shape R 5 R 3 5, on 4 the D shape R 5 R 3, a seventh in place of the octave; strings counted from the
  root's up, in a standard tuning's intervals), the fewest fretted notes below the root's fret (the shape grows up
  the neck from the root), the fewest fingers, the lowest frets. With the root open (fret 0) the CAGED shape comes
  before the open strings, so the open E, A and D shapes are kept (Esus4 022200, not 002200).

Standard library only; deterministic. Strings are numbered as the pattern format numbers lanes: 1 the highest.
"""
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from typing import Mapping

from .chords import ChordType, chord_type

SPAN = 4                     # frets a hand covers
OPEN_POSITION = 3            # open strings join a shape whose fretted notes are all at or below this fret
# CAGED: the role of each string above the root's in the shape at the nut, by the root's string (E, A and D shapes):
# R the root, O the octave (or the seventh in a seventh chord), 3 the third (a sus chord's 2nd or 4th), 5 the fifth
SHAPES = {6: "R5O35R", 5: "R5O35", 4: "R5O3"}
FINGERS = 4
MAX_FRET = 36


@dataclass(frozen=True)
class Voicing:
    """One note per string (None: muted), highest string first; the root note and its string; the chord type."""
    root: int
    root_string: int
    chord: str
    notes: tuple[tuple[int, int | None], ...]
    frets: tuple[tuple[int, int | None], ...]

    def note(self, string: int) -> int | None:
        return dict(self.notes).get(int(string))

    @property
    def sounding(self) -> dict[int, int]:
        """{string: note} of the strings that play."""
        return {s: n for s, n in self.notes if n is not None}

    @property
    def muted(self) -> frozenset[int]:
        return frozenset(s for s, n in self.notes if n is None)

    def shape(self) -> str:
        """The frets from the lowest string to the highest, x for muted: 'x32010' (two digits for frets above 9 are
        written in parentheses: 'x(10)(12)…')."""
        def one(fret):
            return "x" if fret is None else str(fret) if fret < 10 else f"({fret})"
        return "".join(one(f) for _, f in sorted(self.frets, reverse=True))


class VoicingError(ValueError):
    """The root cannot be played on that string (below its open note, past the neck, or no such string)."""


def build_voicing(opens: Mapping[int, int], root: int, string: int, chord, frets: int = 24) -> Voicing:
    """The voicing of `chord` (a ChordType or its name) with `root` on `string`, for strings tuned to `opens`
    ({string: open note}, 1 the highest); `frets`: the neck's length. Raises VoicingError or ValueError."""
    kind = chord if isinstance(chord, ChordType) else chord_type(chord)
    if kind is None:
        raise ValueError(f"no chord type {chord!r}")
    tuning = tuple(sorted((int(s), int(n)) for s, n in opens.items()))
    return _build(tuning, int(root), int(string), kind, int(frets))


@lru_cache(maxsize=4096)
def _build(tuning: tuple, root: int, string: int, kind: ChordType, neck: int) -> Voicing:
    opens = dict(tuning)
    if string not in opens:
        raise VoicingError(f"there is no string {string}")
    fret = root - opens[string]
    if fret < 0 or fret > min(neck, MAX_FRET):
        raise VoicingError(f"{root} is not on string {string} (open {opens[string]}, {neck} frets)")
    weights = {(root + i) % 12: (16 if i == 0 else 0 if i % 12 == 7 else 4) for i in kind.intervals}
    roles = _roles(root, kind)
    upper = [s for s in sorted(opens) if s < string]                    # the higher strings, string 1 first
    best = None
    for low in (range(1, 2) if fret == 0 else range(max(1, fret - SPAN + 1), fret + 1)):
        window = range(low, min(low + SPAN - 1, neck) + 1)
        choices = [_candidates(opens[s], root, window, weights) for s in upper]
        for picked in product(*choices):
            shape = dict(zip(upper, picked))
            shape[string] = fret
            score = _score(shape, opens, fret, string, weights, roles)
            if score is not None and (best is None or score > best[0]):
                best = (score, shape)
    shape = best[1] if best is not None else {string: fret}
    frets = tuple((s, shape.get(s)) for s in sorted(opens))
    notes = tuple((s, None if f is None else opens[s] + f) for s, f in frets)
    return Voicing(root, string, kind.name, notes, frets)


def _candidates(open_note: int, root: int, window, weights) -> list:
    """A string's choices: muted, open (a chord tone), or a chord tone fretted within the window; never below the
    root."""
    found: list = [None]
    if open_note % 12 in weights and open_note >= root:
        found.append(0)
    found += [f for f in window if (open_note + f) % 12 in weights and open_note + f >= root]
    return found


def _roles(root: int, kind: ChordType) -> dict[str, frozenset[int]]:
    """The pitch classes each CAGED role takes in this chord type."""
    intervals = kind.intervals
    third = next((i for i in intervals if i in (3, 4)), next((i for i in intervals if i in (2, 5)), None))
    fifth = next((i for i in intervals if i in (6, 7, 8)), None)
    sevenths = {i for i in intervals if i in (9, 10, 11)}
    pcs = lambda found: frozenset((root + i) % 12 for i in found)
    return {"R": pcs({0}), "O": pcs({0} | sevenths), "3": pcs({third} - {None}), "5": pcs({fifth} - {None})}


def _caged(shape: dict, opens: dict, string: int, roles: dict) -> int:
    """How many strings above the root's take their role in the CAGED shape of the root's string."""
    template = SHAPES.get(string)
    if template is None:
        return 0
    found = 0
    for offset, role in enumerate(template[1:], 1):
        fret = shape.get(string - offset)
        if fret is not None and (opens[string - offset] + fret) % 12 in roles[role]:
            found += 1
    return found


def _score(shape: dict, opens: dict, fret: int, string: int, weights: dict, roles: dict):
    """The shape's rank (higher is better), or None when it cannot be played (the module text)."""
    fretted = [f for f in shape.values() if f]
    if fretted and max(fretted) - min(fretted) > SPAN - 1:
        return None
    upper = {s: f for s, f in shape.items() if s != string}
    open_strings = sum(1 for f in upper.values() if f == 0)
    if open_strings and fretted and max(fretted) > OPEN_POSITION:
        return None
    fingers = _fingers(shape, fret)
    if fingers is None:
        return None
    sounding = [s for s, f in shape.items() if f is not None]
    covered = {(opens[s] + shape[s]) % 12 for s in sounding}
    top = min(sounding)
    inner = sum(1 for s, f in upper.items() if f is None and s > top)
    below = sum(1 for f in upper.values() if f and fret and f < fret)
    fifth = int(any(weights[pc] == 0 for pc in covered))
    caged = _caged(shape, opens, string, roles)
    shaped = (caged, open_strings, fifth) if fret == 0 else (open_strings, fifth, caged)
    return (sum(weights[pc] for pc in covered), -inner, len(sounding), *shaped, -below, -fingers, -sum(fretted))


def _fingers(shape: dict, root_fret: int = 0) -> int | None:
    """Fingers the shape needs (the module text), or None when one hand cannot play it."""
    fretted = {s: f for s, f in shape.items() if f}
    if not fretted:
        return 0
    low = min(fretted.values())
    at_low = [s for s, f in fretted.items() if f == low]
    count = 1
    if any(shape.get(s) == 0 for s in range(min(at_low), max(at_low) + 1)):
        runs = _runs(at_low, shape)
        if any(len(run) > 1 for run in runs) or root_fret:
            return None                               # a barre cannot pass over an open string
        count = len(runs)                             # an open root: a finger on each string at the lowest fret
    for level in sorted(set(fretted.values()) - {low}):
        previous = None
        for s in sorted(s for s, f in fretted.items() if f == level):
            between = range(previous + 1, s) if previous is not None else ()
            if previous is None or any((shape.get(x) or 0) < level for x in between):
                count += 1
            previous = s
    return count if count <= FINGERS else None


def _runs(strings, shape) -> list[list[int]]:
    """Neighbouring strings (no open or muted string between) as runs."""
    runs: list[list[int]] = []
    for s in sorted(strings):
        if runs and all(shape.get(x) for x in range(runs[-1][-1] + 1, s)):
            runs[-1].append(s)
        else:
            runs.append([s])
    return runs
