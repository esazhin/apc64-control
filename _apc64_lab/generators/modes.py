"""'modes': the modes explorer. Rows 1–7, bottom to top, are the seven parallel modes of one root, from the major
scale up to the darkest: Ionian, Dorian, Phrygian, Lydian, Mixolydian, Aeolian, Locrian (2026-10-29: the order of
the modes of the major scale). Each row plays its mode from the root (column 1) up to the octave (column 8), so a
column is one scale degree in every mode. Row 8 is dark (silent): the chromatic notes are on every other layout.

The notes in which a mode differs from Ionian (the major scale) keep the scheme's full colour, so each row shows
what makes it that mode (Dorian: ♭3 and ♭7; Lydian: ♯4); the root and the octave are white (pressed red), and the
notes it shares with Ionian are the scheme's colour, dimmed (all of Ionian's but its root and octave).

Its own window (a key window, domain/window.py): the encoder moves the key, the root of every row, by a Semitone or,
after Tempo, by a Fifth (round the circle of fifths); the twelve keys go round, a step past B coming back to C an
octave lower. The OLED's row 2 names the key ('Key Db'). The pads, their colours and marks are the same picture in
every key (the colours follow the key: a pad is coloured as its degree is in C), and each row is spelled in its mode
of the key from the key's root as the key is named (C, D♭, D, E♭, E, F, G♭, G, A♭, A, B♭, B: the OLED's names),
each letter once, whatever accidentals that takes: E♭ Phrygian E♭ F♭ G♭ A♭ B♭ C♭ D♭, E♭ Locrian E♭ F♭ G♭ A♭ B𝄫
C♭ D♭ (every row is a mode of the same root, so every row starts on the same name). Every pad lies in base …
base + 12 at the first key.
"""
from _apc64_lab.domain.generators import CHANNEL_PARAM, ParamKind, ParamSpec
from _apc64_lab.domain.harmony.scales import BY_KEY, MODE_NAMES
from _apc64_lab.domain.harmony.spelling import PARENT_KEYS, diatonic_scale
from _apc64_lab.domain.window import WindowSpec, WindowStep

# the modes of the major scale in order, bottom row first
MODES = ("major", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian")
ROW_LABELS = tuple(MODE_NAMES[key] for key in MODES) + ("",)
SEMITONE = WindowStep("Semitone", "Semi", 1)
FIFTH = WindowStep("Fifth", "5th", 7)


def _rows() -> tuple[tuple[int, ...], ...]:
    """The seven mode rows' semitones above the root, bottom first."""
    return tuple(BY_KEY[key].intervals + (12,) for key in MODES)


class ModesExplorer:
    name = "modes"
    params = (ParamSpec("base", ParamKind.NOTE, 48, 0, 115, "the root: the note on pad r1c1 and every row's first pad"),
              CHANNEL_PARAM)

    def notes(self, params):
        return tuple(params["base"] + step for row in _rows() for step in row) + (None,) * 8

    def marks(self, params):
        ionian = _rows()[0]
        marks = []
        for row in _rows():
            for x, step in enumerate(row):
                marks.append("root" if x in (0, 7) else "accent" if step != ionian[x] else "dim")
        return tuple(marks) + (None,) * 8

    def row_labels(self, params):
        return ROW_LABELS

    def pad_names(self, params, transposition=0):
        root = (params["base"] + transposition) % 12
        names = []
        for steps in _rows():
            spelled = diatonic_scale(root, PARENT_KEYS[root], tuple(b - a for a, b in zip(steps, steps[1:-1])))
            names += [_double(name) for name in spelled] + [_double(spelled[0])]
        return tuple(names) + (None,) * 8

    def window(self, params):
        """The key: Semitone or Fifth steps, round the twelve keys from the base's (row 2 'Key Db')."""
        return WindowSpec((SEMITONE, FIFTH), 0, 11, circular=True, key_root=params["base"] % 12, end_text="Key: no room")


def _double(name: str) -> str:
    """A double accidental as its own sign: B♭♭ → B𝄫, F♯♯ → F𝄪."""
    return name.replace("♭♭", "𝄫").replace("♯♯", "𝄪")


GENERATOR = ModesExplorer()
