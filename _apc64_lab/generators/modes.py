"""'modes': the modes explorer. Rows 1–7, bottom to top, are the seven parallel modes of one root by brightness,
darkest first: Locrian, Phrygian, Aeolian, Dorian, Mixolydian, Ionian, Lydian. Each row plays its mode from the
root (column 1) up to the octave (column 8), so a column is one scale degree in every mode.

Each row raises exactly one note of the row below it (♭5, ♭2, ♭6, ♭3, ♭7, then 4 → ♯4). That note keeps the
scheme's full colour, the root and the octave are white (pressed red), and the other notes are the scheme's
colour, dimmed; Locrian, which has no row below, stresses its ♭5, the note Phrygian raises.

Row 8 is a chromatic reference from the root: the eight semitones root to fifth (1 ♭2 2 ♭3 3 4 ♯4 5), in the
scheme's colours, to compare a row against the notes it leaves out. Every pad lies in base … base + 12.
Each mode row is spelled in its mode (C Locrian: C D♭ E♭ F G♭ A♭ B♭), at whatever window it is played.
"""
from _apc64_lab.domain.generators import CHANNEL_PARAM, ParamKind, ParamSpec
from _apc64_lab.domain.harmony.scales import BY_KEY, MODE_NAMES, MODES_BY_BRIGHTNESS, mode_steps, spell_scale
from _apc64_lab.domain.harmony.spelling import pc_name

CHROMATIC_ROW = tuple(range(8))
ROW_LABELS = tuple(MODE_NAMES[key] for key in MODES_BY_BRIGHTNESS) + ("Chromatic",)


def _rows() -> tuple[tuple[int, ...], ...]:
    """The eight rows' semitones above the root, bottom first."""
    return tuple(BY_KEY[key].intervals + (12,) for key in MODES_BY_BRIGHTNESS) + (CHROMATIC_ROW,)


def _changed() -> tuple[int, ...]:
    """The column (0-based) each mode row stresses: the degree it raised; Locrian the one Phrygian raises."""
    steps = [changed for _, changed in mode_steps()]
    steps[0] = steps[1]
    return tuple(steps)


class ModesExplorer:
    name = "modes"
    params = (ParamSpec("base", ParamKind.NOTE, 48, 0, 115, "the root: the note on pad r1c1 and every row's first pad"),
              CHANNEL_PARAM)

    def notes(self, params):
        return tuple(params["base"] + step for row in _rows() for step in row)

    def marks(self, params):
        changed = _changed()
        marks = []
        for r in range(8):
            for x in range(8):
                if x == 0 or (r < 7 and x == 7):
                    marks.append("root")
                elif r == 7:
                    marks.append(None)
                else:
                    marks.append("accent" if x == changed[r] else "dim")
        return tuple(marks)

    def row_labels(self, params):
        return ROW_LABELS

    def pad_names(self, params, transposition=0):
        root = (params["base"] + transposition) % 12
        names = []
        for key, steps in zip((*MODES_BY_BRIGHTNESS, None), _rows()):
            spelled = spell_scale(root, BY_KEY[key]) if key else {}
            names += [spelled.get((root + step) % 12) or pc_name(root + step) for step in steps]
        return tuple(names)


GENERATOR = ModesExplorer()
