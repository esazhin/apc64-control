"""The scale library: named interval sets, the parallel modes by brightness, and scale spelling.

Each scale is a set of semitones above its root (0 first). `native` marks the 16 scales the APC64's own Note view
offers (Akai's manual §5.2), so a layout can add what the unit lacks rather than repeat it. Akai names two of its
scales without giving their notes, "Hungarian" and "Flamenco": the library defines its own under unambiguous
names (`hungarian-minor` and `hungarian-major`; `flamenco`, the eight-note Phrygian with both thirds) and does
not claim either is the unit's.

Keys are lower case with "-" (`harmonic-minor`); `find_scale` also takes the display name, spaces or "_", ♭/♮
written out or as b, and the aliases (`ionian`, `minor`, `super-locrian` …).
"""
from dataclasses import dataclass
from difflib import get_close_matches

from .spelling import PARENT_KEYS, PITCH_CLASS_NAMES, diatonic_scale, pc_name


@dataclass(frozen=True)
class Scale:
    key: str                       # 'harmonic-minor': what a layout file writes
    name: str                      # 'Harmonic minor': what the page shows
    intervals: tuple[int, ...]     # semitones above the root, ascending, 0 first
    native: bool = False           # one of the APC64 Note view's own 16
    note: str = ""

    @property
    def size(self) -> int:
        return len(self.intervals)

    def pitch_classes(self, root: int) -> frozenset[int]:
        return frozenset((root + i) % 12 for i in self.intervals)


def _s(key, name, intervals, native=False, note=""):
    return Scale(key, name, tuple(intervals), native, note)


SCALES: tuple[Scale, ...] = (
    # the Note view's own (Akai's order)
    _s("chromatic", "Chromatic", range(12), True),
    _s("major", "Major (Ionian)", (0, 2, 4, 5, 7, 9, 11), True),
    _s("melodic-minor", "Melodic minor", (0, 2, 3, 5, 7, 9, 11), True, "the ascending (jazz) form"),
    _s("harmonic-minor", "Harmonic minor", (0, 2, 3, 5, 7, 8, 11), True),
    _s("major-pentatonic", "Major pentatonic", (0, 2, 4, 7, 9), True),
    _s("minor-pentatonic", "Minor pentatonic", (0, 3, 5, 7, 10), True),
    _s("dorian", "Dorian", (0, 2, 3, 5, 7, 9, 10), True),
    _s("phrygian", "Phrygian", (0, 1, 3, 5, 7, 8, 10), True),
    _s("lydian", "Lydian", (0, 2, 4, 6, 7, 9, 11), True),
    _s("mixolydian", "Mixolydian", (0, 2, 4, 5, 7, 9, 10), True),
    _s("aeolian", "Aeolian (natural minor)", (0, 2, 3, 5, 7, 8, 10), True),
    _s("locrian", "Locrian", (0, 1, 3, 5, 6, 8, 10), True),
    _s("blues", "Blues (minor, six notes)", (0, 3, 5, 6, 7, 10), True),
    _s("whole-tone", "Whole tone", (0, 2, 4, 6, 8, 10), True),
    _s("flamenco", "Flamenco (Phrygian with ♭3 and 3)", (0, 1, 3, 4, 5, 7, 8, 10), False,
       "the library's own; Akai does not give the notes of the unit's 'Flamenco'"),
    _s("hungarian-minor", "Hungarian minor", (0, 2, 3, 6, 7, 8, 11), False,
       "the library's own; Akai does not give the notes of the unit's 'Hungarian'"),
    # beyond the unit
    _s("hungarian-major", "Hungarian major", (0, 3, 4, 6, 7, 9, 10)),
    _s("harmonic-major", "Harmonic major", (0, 2, 4, 5, 7, 8, 11)),
    _s("double-harmonic", "Double harmonic major", (0, 1, 4, 5, 7, 8, 11), note="also Byzantine"),
    _s("neapolitan-major", "Neapolitan major", (0, 1, 3, 5, 7, 9, 11)),
    _s("neapolitan-minor", "Neapolitan minor", (0, 1, 3, 5, 7, 8, 11)),
    _s("dorian-b2", "Dorian ♭2", (0, 1, 3, 5, 7, 9, 10), note="melodic minor, mode 2"),
    _s("lydian-augmented", "Lydian augmented", (0, 2, 4, 6, 8, 9, 11), note="melodic minor, mode 3"),
    _s("lydian-dominant", "Lydian dominant", (0, 2, 4, 6, 7, 9, 10), note="melodic minor, mode 4"),
    _s("mixolydian-b6", "Mixolydian ♭6", (0, 2, 4, 5, 7, 8, 10), note="melodic minor, mode 5"),
    _s("locrian-natural2", "Locrian ♮2", (0, 2, 3, 5, 6, 8, 10), note="melodic minor, mode 6"),
    _s("altered", "Altered (super Locrian)", (0, 1, 3, 4, 6, 8, 10), note="melodic minor, mode 7"),
    _s("phrygian-dominant", "Phrygian dominant", (0, 1, 4, 5, 7, 8, 10), note="harmonic minor, mode 5"),
    _s("octatonic-half-whole", "Octatonic half–whole", (0, 1, 3, 4, 6, 7, 9, 10), note="diminished, from a half step"),
    _s("octatonic-whole-half", "Octatonic whole–half", (0, 2, 3, 5, 6, 8, 9, 11), note="diminished, from a whole step"),
    _s("bebop-dominant", "Bebop dominant", (0, 2, 4, 5, 7, 9, 10, 11)),
    _s("bebop-major", "Bebop major", (0, 2, 4, 5, 7, 8, 9, 11)),
    _s("hirajoshi", "Hirajoshi", (0, 2, 3, 7, 8)),
    _s("in", "In (Sakura)", (0, 1, 5, 7, 8)),
    _s("iwato", "Iwato", (0, 1, 5, 6, 10)),
    _s("prometheus", "Prometheus", (0, 2, 4, 6, 9, 10)),
    _s("enigmatic", "Enigmatic", (0, 1, 4, 6, 8, 10, 11)),
)
BY_KEY = {s.key: s for s in SCALES}
# The Note view's two scales whose notes Akai does not give; the other 14 of its 16 are the `native` ones above.
NATIVE_UNSPECIFIED = ("Flamenco", "Hungarian")
ALIASES = {"ionian": "major", "minor": "aeolian", "natural-minor": "aeolian", "super-locrian": "altered",
           "byzantine": "double-harmonic", "sakura": "in", "whole-half": "octatonic-whole-half",
           "half-whole": "octatonic-half-whole", "jazz-minor": "melodic-minor", "spanish": "phrygian-dominant"}
SCALE_KEYS = tuple(BY_KEY)

# The seven parallel modes of one root, darkest first: each raises one note of the one below it.
MODES_BY_BRIGHTNESS = ("locrian", "phrygian", "aeolian", "dorian", "mixolydian", "major", "lydian")
MODE_NAMES = {"locrian": "Locrian", "phrygian": "Phrygian", "aeolian": "Aeolian", "dorian": "Dorian",
              "mixolydian": "Mixolydian", "major": "Ionian", "lydian": "Lydian"}


def _normal(text: str) -> str:
    text = str(text).strip().lower().replace("♭", "b").replace("♮", "natural").replace("♯", "#")
    for ch in " _–—":
        text = text.replace(ch, "-")
    text = "".join(ch for ch in text if ch.isalnum() or ch in "-#")
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-")


_BY_NAME = {_normal(s.name.split(" (")[0]): s.key for s in SCALES}


def find_scale(text) -> Scale | None:
    """The scale a key, display name or alias names ('Harmonic Minor', 'dorian_b2', 'ionian'), or None."""
    wanted = _normal(text)
    key = ALIASES.get(wanted, _BY_NAME.get(wanted, wanted))
    return BY_KEY.get(key)


def closest_scale(text) -> str | None:
    """The key nearest a misspelt one ('dorain' → 'dorian'), for the error's fix."""
    found = get_close_matches(_normal(text), [*SCALE_KEYS, *ALIASES], n=1, cutoff=0.6)
    return ALIASES.get(found[0], found[0]) if found else None


def mode_steps() -> tuple[tuple[str, int | None], ...]:
    """(mode, the degree index it raises against the mode below), darkest first; Locrian has none below."""
    steps, below = [], None
    for key in MODES_BY_BRIGHTNESS:
        intervals = BY_KEY[key].intervals
        changed = None if below is None else next(i for i, (a, b) in enumerate(zip(below, intervals)) if a != b)
        steps.append((key, changed))
        below = intervals
    return tuple(steps)


def _accidentals(name: str) -> int:
    return sum(name.count(ch) for ch in "♯♭")


def spell_scale(root: int, scale: Scale) -> dict[int, str]:
    """Pitch class → name in the scale's context. A seven-note scale is spelled letter-correctly as MusicCat
    spells keys (each letter once), from whichever spelling of the root needs the fewest accidentals (C♯ Locrian,
    not D♭ Locrian with five double flats); ties keep the parent-key spelling. Other sizes use the fixed table."""
    root %= 12
    if scale.size != 7:
        return {pc: pc_name(pc) for pc in sorted(scale.pitch_classes(root))}
    steps = tuple(b - a for a, b in zip(scale.intervals, scale.intervals[1:]))
    roots = [PARENT_KEYS[root]] + [n for _, n in PITCH_CLASS_NAMES[root] if n != PARENT_KEYS[root] and _accidentals(n) <= 1]
    best = None
    for name in roots:
        notes = diatonic_scale(root, name, steps)
        if "?" in notes:
            continue
        cost = sum(_accidentals(n) for n in notes)
        if best is None or cost < best[0]:
            best = (cost, notes)
    if best is None:
        return {pc: pc_name(pc) for pc in sorted(scale.pitch_classes(root))}
    return {(root + i) % 12: n for i, n in zip(scale.intervals, best[1])}
