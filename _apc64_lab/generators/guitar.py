"""'guitar': a guitar (or bass) neck. Rows are strings, columns are frets: the highest string on the top used row,
the lowest on the bottom one. 8 strings use rows 1–8, 7 strings rows 1–7, 6 or fewer start at row 2 (6 strings:
rows 2–7); the rows left over are silent (kept free for a later performer step). Column 1 is the fret the window
shows first, fret 0 (the open strings) at the start, so a pad plays its string's open note + its fret.

    tuning: e-standard     # a preset (below) or the open strings low to high: [E1, A1, D2, G2, B2, E3] or [40, 45, …]
    frets: 24              # the neck's length, 12–36
    fret_marks: on         # the inlay frets marked on the pads (default on; off: every pad in its scheme colour)

Each string sends on its own MIDI channel, string 1 (the highest) on channel 1, string 2 on channel 2 …: in Custom
view the unit sends only note and channel, so this is how the lab tells low E fret 5 from the open A. The routing
rule still sends every note to its target on the rule's channel.

The window (amendment 2026-10-27): its position t is the fret in column 1 (the pads show frets t … t+7), 0 ≤ t ≤
frets − 7. Two steps, Tempo toggling them: Fret (one semitone per detent) and Page (to the next or previous of the
page positions: the multiples of 8 below the end, then the end itself; 24 frets: 0, 8, 16, 17). The OLED's row 2
always reads the frets on the pads, 'Frets 8-15'; Tempo flashes 'Step: Page' / 'Step: Fret' and a refused step
'Neck end' for about a second (2026-10-27).

Fret marks (2026-10-27): the pad columns on the inlay frets (3, 5, 7, 9, 15, 17, 19, 21, 27, 29, 31, 33) keep the
scheme's full colour and the others are shaded moderately ('shade'), so the inlays read on the unit like dots on
a neck; 12, 24 and 36, the double inlays, are lifted toward white ('bright'). They move with the window
(window_marks), as the guitar's pads are rewritten at each step. Pressed colours are unchanged.
"""
from _apc64_lab.domain.generators import Neck, NeckString, ParamKind, ParamSpec
from _apc64_lab.domain.harmony.spelling import pc_name
from _apc64_lab.domain.window import WindowSpec, WindowStep

# open strings, low to high, as MIDI numbers (C3 = 60 in the project's names, so the guitar's low E, 40, is E1)
TUNINGS = {
    "e-standard": (40, 45, 50, 55, 59, 64),
    "drop-d": (38, 45, 50, 55, 59, 64),
    "eb-standard": (39, 44, 49, 54, 58, 63),
    "d-standard": (38, 43, 48, 53, 57, 62),
    "drop-c": (36, 43, 48, 53, 57, 62),
    "dadgad": (38, 45, 50, 55, 57, 62),
    "open-g": (38, 43, 50, 55, 59, 62),
    "open-d": (38, 45, 50, 54, 57, 62),
    "b-standard-7": (35, 40, 45, 50, 55, 59, 64),
    "drop-a-7": (33, 40, 45, 50, 55, 59, 64),
    "fs-standard-8": (30, 35, 40, 45, 50, 55, 59, 64),
    "drop-e-8": (28, 35, 40, 45, 50, 55, 59, 64),
    "bass-4": (28, 33, 38, 43),
    "bass-5": (23, 28, 33, 38, 43),
}
SHOWN = 8                                         # frets on the pads at a time: the 8 columns
INLAYS = frozenset({3, 5, 7, 9, 15, 17, 19, 21, 27, 29, 31, 33})   # a single dot, as on the page's neck
DOUBLE_INLAYS = frozenset({12, 24, 36})                            # the octaves: two dots
FRET = WindowStep("Fret", "Fr", 1)
PAGE = WindowStep("Page", "Pg", paged=True)


def _lookup(text):
    key = "-".join(str(text).strip().lower().replace("♯", "s").replace("♭", "b").replace("#", "s").split())
    return key if key in TUNINGS else None


def _on_off(text):
    word = str(text).strip().lower()
    return "on" if word in ("on", "true", "yes", "1") else "off" if word in ("off", "false", "no", "0") else None


def fret_mark(fret: int) -> str:
    """The mark of a pad on this fret: None (an inlay: the scheme's colour), 'bright' (12, 24, 36), 'shade'."""
    return "bright" if fret in DOUBLE_INLAYS else None if fret in INLAYS else "shade"


def open_strings(params) -> tuple[int, ...]:
    """The open notes, low to high, of a preset or a written list."""
    tuning = params["tuning"]
    return TUNINGS[tuning] if isinstance(tuning, str) else tuple(tuning)


def bottom_row(count: int) -> int:
    """The row (0-based) of the lowest string: row 1 for 7 and 8 strings, row 2 for 6 or fewer."""
    return 0 if count >= 7 else 1


def string_rows(params) -> dict[int, tuple[int, int]]:
    """Row (0-based) → (string number, 1 = the highest; open note) for the rows that play."""
    notes = open_strings(params)
    count, bottom = len(notes), bottom_row(len(notes))
    return {bottom + k: (count - k, note) for k, note in enumerate(notes)}


class GuitarNeck:
    name = "guitar"
    params = (ParamSpec("tuning", ParamKind.NOTE_LIST, "e-standard", 4, 8,
                        "a preset, or the open strings low to high (4–8 notes, C3 = 60: the low E is E1, 40)",
                        choices=tuple(TUNINGS), lookup=_lookup),
              ParamSpec("frets", ParamKind.INT, 24, 12, 36, "the neck's length in frets"),
              ParamSpec("fret_marks", ParamKind.CHOICE, "on", doc="the inlay frets marked on the pads (on or off)",
                        choices=("on", "off"), lookup=_on_off))

    def notes(self, params):
        rows = string_rows(params)
        return tuple(rows[r][1] + x if r in rows else None for r in range(8) for x in range(8))

    def window_marks(self, params, transposition):
        """The inlay columns at this window (column x plays fret transposition + x); all None when turned off."""
        rows = string_rows(params)
        on = params.get("fret_marks", "on") == "on"
        return tuple(fret_mark(transposition + x) if on and r in rows else None for r in range(8) for x in range(8))

    def channels(self, params):
        rows = string_rows(params)
        return tuple(rows[r][0] if r in rows else None for r in range(8) for x in range(8))

    def describe(self, param, value):
        """The comment written next to a tuning chosen on the page: its open strings, numbers and names."""
        if param != "tuning":
            return None
        preset = _lookup(value)
        if preset is None:
            return "the open strings, low to high (C3 = 60)"
        notes = TUNINGS[preset]
        names = " ".join(f"{pc_name(n % 12)}{n // 12 - 2}" for n in notes)
        return f"the open strings, low to high: {' '.join(map(str, notes))} ({names}; C3 = 60)"

    def row_labels(self, params):
        rows = string_rows(params)
        return tuple(f"{rows[r][0]} {pc_name(rows[r][1])}" if r in rows else "" for r in range(8))

    def root(self, params):
        return open_strings(params)[0] % 12

    def window(self, params):
        highest = params["frets"] - (SHOWN - 1)
        return WindowSpec((FRET, PAGE), 0, highest, pages=(*range(0, highest, SHOWN), highest), shown=SHOWN,
                          unit="Frets", end_text="Neck end")

    def neck(self, params):
        notes = open_strings(params)
        strings = tuple(NeckString(len(notes) - k, note, len(notes) - k) for k, note in enumerate(notes))
        return Neck(tuple(reversed(strings)), params["frets"], SHOWN)


GENERATOR = GuitarNeck()
