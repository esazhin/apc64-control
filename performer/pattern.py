"""A performer pattern: a step matrix with one lane per string (or voice), as JSON-compatible data
(docs/performer-format.md, docs/performer.schema.json).

    name: Arpeggio 1-2-3 over a manual bass
    meter: 4/4          # beats per bar / beat unit
    step: 1/8           # 1/4, 1/8, 1/16, 1/8t, 1/16t
    length: 8           # steps, up to 32
    lanes:              # lane: one cell per step; . rest, x hit, X accent; spaces and | ignored
      1: . . . x | . . . x
      2: . x . . | . x . .
      3: . . x . | . . x .
    manual: [4, 5, 6]   # lanes played by hand, passed through as played

Lanes are numbered 1–16 (with strings addressing lane 1 is the highest string) or relative to the chord held: R
(the root string) and A (the alternate bass), see docs/performer-format.md, "Chord-aware lanes".

parse_pattern(data) takes the data (a YAML or JSON file read by the caller) and gives a Pattern, or raises
PatternError with every issue found, each naming its place in the data (`path`, e.g. ('lanes', '2')), what is wrong
and how to fix it; the caller turns the path into a file line. Warnings (a name the OLED cuts, a length that is not
a whole number of bars) are kept on the pattern. to_data(pattern) gives the canonical data back, rows written with
a space between cells and a '|' at every bar.

Standard library only: this package is shared with other projects (docs/performer-format.md).
"""
from dataclasses import dataclass, field
from difflib import get_close_matches
from fractions import Fraction

FORMAT = 1
MAX_LENGTH = 32
MAX_LANE = 16
ROOT_LANE, ALT_LANE = "R", "A"                  # the relative lanes: the chord's root string and its alternate bass
RELATIVE = (ROOT_LANE, ALT_LANE)
LANE_FIX = f"lanes are 1–{MAX_LANE} (1 is the highest string), R (the root string) or A (the alternate bass)"
NAME_SHOWN = 14                       # the unit's OLED row; a longer name is cut there (a warning)
STEPS = {"1/4": Fraction(1, 4), "1/8": Fraction(1, 8), "1/16": Fraction(1, 16),
         "1/8t": Fraction(1, 12), "1/16t": Fraction(1, 24)}       # of a whole note
BEAT_UNITS = (1, 2, 4, 8, 16)
REST, HIT, ACCENT = 0, 1, 2
CELLS = {".": REST, "x": HIT, "X": ACCENT}
CELL_TEXT = {REST: ".", HIT: "x", ACCENT: "X"}
STRUMS = {".": None, "d": "down", "u": "up"}
STRUM_TEXT = {None: ".", "down": "d", "up": "u"}
PLAY_MODES = ("all", "pressed")       # all: unpressed lanes ring open; pressed: only pressed lanes play
RING = "ring"
DEFAULTS = {"meter": "4/4", "step": "1/8", "spread": 15, "swing": 50, "play": "all", "gate": RING,
            "velocity": {"hit": 100, "accent": 127}, "humanize": {"timing": 0, "velocity": 0}}
KEYS = ("format", "name", "description", "meter", "step", "length", "lanes", "strum", "spread", "swing", "play",
        "gate", "velocity", "humanize", "manual")
CELL_FIX = "write one cell per step: . (rest), x (hit) or X (accent); spaces and | are ignored"


@dataclass(frozen=True)
class Issue:
    """One finding: where in the data (`path`), what is wrong and how to fix it; an error or a warning."""
    path: tuple[str, ...]
    problem: str
    fix: str | None = None
    severity: str = "error"

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    @property
    def field(self) -> str | None:
        """The place as a reader names it: 'lane 2', 'meter', 'humanize.timing'; None for the whole pattern."""
        if not self.path:
            return None
        if self.path[0] == "lanes" and len(self.path) > 1:
            return f"lane {self.path[1]}"
        if self.path[0] == "manual" and len(self.path) > 1:
            return "manual"
        return ".".join(self.path)

    def text(self, file: str | None = None, line: int | None = None) -> str:
        """'travis.yaml line 6, lane 2: 7 steps; length is 8: …' (the field left out when the problem names it)."""
        where = file or ""
        if line is not None:
            where = f"{where} line {line}" if where else f"line {line}"
        name = self.field
        if name and name not in self.problem:
            where = f"{where}, {name}" if where else name
        head = f"{where}: {self.problem}" if where else self.problem
        return head + (f"; {self.fix}" if self.fix else "")


class PatternError(ValueError):
    """The data is not a pattern: every issue found, errors and warnings, in data order."""

    def __init__(self, issues):
        self.issues = tuple(issues)
        errors = [i for i in self.issues if i.is_error]
        super().__init__(errors[0].text() if errors else "not a pattern")


@dataclass(frozen=True)
class Meter:
    beats: int
    unit: int

    def __str__(self) -> str:
        return f"{self.beats}/{self.unit}"

    @property
    def bar(self) -> Fraction:
        """The bar's length as a fraction of a whole note."""
        return Fraction(self.beats, self.unit)


@dataclass(frozen=True)
class Pattern:
    """A validated pattern. `lanes` holds each written lane's cells (REST, HIT, ACCENT), lowest lane first, then R
    and A (lane_order);
    `strum` is None or one of None/'down'/'up' per step; times are in milliseconds, swing in percent."""
    name: str
    meter: Meter
    step: str
    length: int
    lanes: tuple[tuple[int | str, tuple[int, ...]], ...]
    strum: tuple[str | None, ...] | None = None
    spread: float = 15
    swing: float = 50
    play: str = "all"                      # all: an unpressed lane plays its open string; pressed: it rests
    gate: float | None = None             # in steps; None rings until the lane's next hit
    hit: int = 100
    accent: int = 127
    timing: float = 0                     # humanize: ± milliseconds
    jitter: int = 0                       # humanize: ± velocity
    manual: frozenset[int] = frozenset()
    description: str | None = None
    warnings: tuple[Issue, ...] = field(default=(), compare=False)

    # --- reading ------------------------------------------------------------------------------------------
    @property
    def step_fraction(self) -> Fraction:
        """One step as a fraction of a whole note (1/8t is 1/12)."""
        return STEPS[self.step]

    @property
    def step_quarters(self) -> Fraction:
        """One step in quarter notes (the beat of a BPM and of MIDI clock): 1/8 is 1/2."""
        return self.step_fraction * 4

    @property
    def bar_steps(self) -> Fraction:
        """Steps per bar: 8 for 4/4 in 1/8, 6 for 3/4."""
        return self.meter.bar / self.step_fraction

    def cells(self, lane: int | str) -> tuple[int, ...]:
        """The lane's cells (a number, R or A), all rests for a lane the pattern does not write."""
        return dict(self.lanes).get(lane_key(lane), (REST,) * self.length)

    def hits_at(self, index: int) -> tuple[tuple[int | str, int], ...]:
        """(lane, level) of every hit at step `index` (0-based), lowest lane first, then R and A; manual lanes have
        none."""
        return tuple((lane, cells[index]) for lane, cells in self.lanes if cells[index] != REST)

    @property
    def relative(self) -> bool:
        """Whether the pattern writes R or A (lanes that follow the chord)."""
        return any(lane in RELATIVE for lane, _ in self.lanes)

    def strum_at(self, index: int) -> str | None:
        return self.strum[index] if self.strum is not None else None

    @property
    def highest_lane(self) -> int:
        return max([lane for lane, _ in self.lanes if isinstance(lane, int)] + list(self.manual), default=0)


def lane_key(value) -> int | str | None:
    """A lane as written (1, '1', 'R', 'a') → 1, 'R' or 'A'; None when it is no lane."""
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.upper() in RELATIVE:
        return text.upper()
    return _lane_number(text)


def lane_order(lane) -> tuple:
    """Numbers first (1 the highest string), then R, then A."""
    return (1, RELATIVE.index(lane)) if lane in RELATIVE else (0, int(lane))


# --- parsing -----------------------------------------------------------------------------------------------
def parse_pattern(data) -> Pattern:
    """The data as a Pattern, or PatternError with every issue (see the module text)."""
    return _Parser(data).run()


def check_pattern(data) -> tuple[Pattern | None, tuple[Issue, ...]]:
    """(the pattern or None, every issue): validation without an exception."""
    try:
        pattern = parse_pattern(data)
    except PatternError as error:
        return None, error.issues
    return pattern, pattern.warnings


def row_cells(text) -> list[str]:
    """A row's cells as written: every character but spaces and '|'."""
    return [c for c in str(text) if not c.isspace() and c != "|"]


class _Parser:
    def __init__(self, data):
        self.data = data
        self.issues: list[Issue] = []

    def error(self, path, problem, fix=None):
        self.issues.append(Issue(tuple(str(p) for p in path), problem, fix))

    def warn(self, path, problem, fix=None):
        self.issues.append(Issue(tuple(str(p) for p in path), problem, fix, "warning"))

    def run(self) -> Pattern:
        data = self.data
        if not isinstance(data, dict):
            raise PatternError([Issue((), "a pattern is a mapping", "write 'name: …', 'step: 1/8' and 'lanes:'")])
        for key in data:
            if str(key) not in KEYS:
                near = get_close_matches(str(key), KEYS, n=1)
                self.error((key,), f"unknown key '{key}'",
                           (f"did you mean {near[0]}? " if near else "") + "a pattern takes " + ", ".join(KEYS))
        self._format(data.get("format"))
        name = self._name(data.get("name"))
        description = self._description(data.get("description"))
        meter = self._meter(data.get("meter", DEFAULTS["meter"]))
        step = self._step(data.get("step", DEFAULTS["step"]))
        manual = self._manual(data.get("manual"))
        lanes = self._lanes(data.get("lanes"))
        length = self._length(data.get("length"), lanes, data.get("strum"))
        strum = self._strum(data.get("strum"), length)
        spread = self._number(data, "spread", 0, 100, "milliseconds between the strings of a strum")
        swing = self._number(data, "swing", 50, 75, "50 is straight, 66 a triplet feel, 75 the most")
        play = self._play(data.get("play", DEFAULTS["play"]))
        gate = self._gate(data.get("gate", DEFAULTS["gate"]))
        hit, accent = self._velocity(data.get("velocity"))
        timing, jitter = self._humanize(data.get("humanize"))
        if lanes is not None and length is not None:
            lanes = self._fit(lanes, length, manual)
        if "spread" in data and data.get("strum") is None:
            self.warn(("spread",), "spread is unused without a strum row", "add 'strum: d . . .' or remove spread")
        if meter is not None and step is not None and length is not None:
            bar = meter.bar / STEPS[step]
            if bar.denominator != 1 or length % bar.numerator:
                self.warn(("length",), f"{length} steps are not a whole number of {meter} bars of {step} steps"
                          f" ({_steps_text(bar)} a bar)", "the pattern loops after its length all the same")
        if any(i.is_error for i in self.issues):
            raise PatternError(self.issues)
        return Pattern(name, meter, step, length, lanes, strum, spread, swing, play, gate, hit, accent, timing,
                       jitter, manual, description, tuple(self.issues))

    # --- the keys ---------------------------------------------------------------------------------------
    def _format(self, value):
        if value is not None and (isinstance(value, bool) or value != FORMAT):
            self.error(("format",), f"format {value!r} is not known here", f"this is format {FORMAT}; write 'format: 1' or leave it out")

    def _name(self, value) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            self.error(("name",), "the pattern has no name", "add 'name: Travis pick'")
            return None
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            self.error(("name",), "the name must be text", "write e.g. 'name: Travis pick'")
            return None
        name = " ".join(str(value).split())
        if len(name) > NAME_SHOWN:
            self.warn(("name",), f"the OLED shows {NAME_SHOWN} characters of the name: '{name[:NAME_SHOWN]}'",
                      "a shorter name reads whole")
        return name

    def _description(self, value) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            self.error(("description",), "the description must be text", "write it in quotes")
            return None
        return value.strip() or None

    def _meter(self, value) -> Meter | None:
        text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
        beats, _, unit = text.partition("/")
        if not (beats.strip().isdigit() and unit.strip().isdigit()):
            self.error(("meter",), f"'{value}' is not a meter", "write beats per bar / beat unit, e.g. 4/4, 3/4 or 6/8")
            return None
        beats, unit = int(beats), int(unit)
        if not 1 <= beats <= 32 or unit not in BEAT_UNITS:
            self.error(("meter",), f"{beats}/{unit} is not a meter here",
                       "beats per bar 1–32 over a beat unit of 1, 2, 4, 8 or 16")
            return None
        return Meter(beats, unit)

    def _step(self, value) -> str | None:
        text = str(value).strip().lower() if isinstance(value, str) else str(value)
        if text not in STEPS:
            self.error(("step",), f"'{value}' is not a step", "write one of " + ", ".join(STEPS))
            return None
        return text

    def _manual(self, value) -> frozenset[int]:
        if value is None:
            return frozenset()
        items = value if isinstance(value, list) else [value]
        lanes = set()
        for item in items:
            lane = _lane_number(item)
            if lane is None:
                relative = not isinstance(item, bool) and str(item).strip().upper() in RELATIVE
                self.error(("manual",), f"'{item}' is not a lane" + (" a player holds" if relative else ""),
                           ("R and A follow the chord; " if relative else "")
                           + f"write lane numbers 1–{MAX_LANE}, e.g. [4, 5, 6]")
                continue
            lanes.add(lane)
        return frozenset(lanes)

    def _lanes(self, value) -> dict[int | str, list[int]] | None:
        if value is None:
            self.error(("lanes",), "the pattern has no lanes",
                       "add 'lanes:' with one row per lane, e.g. '  1: x . x .'")
            return None
        if not isinstance(value, dict) or not value:
            self.error(("lanes",), "lanes maps lane numbers to rows", "write 'lanes:' then '  1: x . . . x . . .'")
            return None
        lanes: dict[int | str, list[int]] = {}
        for key, row in value.items():
            lane = lane_key(key)
            if lane is None:
                self.error(("lanes", key), f"'{key}' is not a lane", LANE_FIX)
                continue
            if lane in lanes:
                self.error(("lanes", key), f"lane {lane} is written twice", "keep one row per lane")
                continue
            if not isinstance(row, str):
                self.error(("lanes", key), "a lane is a row of cells", "write e.g. '. x . x' (quote it if it starts with | or -)")
                continue
            cells = []
            for i, c in enumerate(row_cells(row)):
                if c not in CELLS:
                    self.error(("lanes", key), f"'{c}' at step {i + 1} is not a cell", CELL_FIX)
                    cells = None
                    break
                cells.append(CELLS[c])
            if cells is not None:
                lanes[lane] = cells
        return lanes

    def _length(self, value, lanes, strum) -> int | None:
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LENGTH:
                self.error(("length",), f"'{value}' is not a length", f"write the number of steps, 1–{MAX_LENGTH}")
                return None
            return value
        counts = sorted({len(cells) for cells in (lanes or {}).values()})
        if not counts:
            return None
        if len(counts) > 1:
            self.error(("lanes",), f"the lanes have {', '.join(map(str, counts))} steps",
                       "give every lane the same number of cells, or write 'length:'")
            return None
        if not 1 <= counts[0] <= MAX_LENGTH:
            self.error(("lanes",), f"{counts[0]} steps", f"a pattern has 1–{MAX_LENGTH} steps")
            return None
        return counts[0]

    def _fit(self, lanes, length, manual):
        rows = []
        for lane, cells in sorted(lanes.items(), key=lambda item: lane_order(item[0])):
            if len(cells) != length:
                self.error(("lanes", lane), f"{len(cells)} steps; length is {length}", CELL_FIX)
                continue
            if lane in manual:
                self.error(("lanes", lane), f"lane {lane} is manual and has a row",
                           f"remove its row, or take {lane} out of manual")
                continue
            rows.append((lane, tuple(cells)))
        if not any(c != REST for _, cells in rows for c in cells) and not any(i.is_error for i in self.issues):
            self.error(("lanes",), "the pattern has no hit", "put an x (or X) in a lane")
        return tuple(rows)

    def _strum(self, value, length) -> tuple | None:
        if value is None:
            return None
        if not isinstance(value, str):
            self.error(("strum",), "strum is a row of d, u and .", "write e.g. 'strum: d . d u . u d u'")
            return None
        marks = []
        for i, c in enumerate(row_cells(value)):
            if c.lower() not in STRUMS:
                self.error(("strum",), f"'{c}' at step {i + 1} is not a strum mark",
                           "write d (down: low to high strings), u (up: high to low) or . (all at once)")
                return None
            marks.append(STRUMS[c.lower()])
        if length is not None and len(marks) != length:
            self.error(("strum",), f"{len(marks)} steps; length is {length}", "write one mark per step: d, u or .")
            return None
        return tuple(marks)

    def _number(self, data, key, low, high, fix) -> float:
        value = data.get(key, DEFAULTS[key])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            self.error((key,), f"'{value}' is outside {low}–{high}", f"{key} is {low}–{high}: {fix}")
            return DEFAULTS[key]
        return value

    def _play(self, value) -> str:
        text = str(value).strip().lower()
        if text not in PLAY_MODES:
            self.error(("play",), f"'{value}' is not all or pressed",
                       "all: every lane plays at its hits, an unpressed string open; pressed: only pressed lanes play")
            return "all"
        return text

    def _gate(self, value) -> float | None:
        if isinstance(value, str) and value.strip().lower() == RING:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= MAX_LENGTH:
            self.error(("gate",), f"'{value}' is not a gate",
                       f"write ring (a note rings until its lane's next hit) or a length in steps, e.g. 0.5 (0–{MAX_LENGTH})")
            return None
        return float(value)

    def _velocity(self, value) -> tuple[int, int]:
        hit, accent = DEFAULTS["velocity"]["hit"], DEFAULTS["velocity"]["accent"]
        if value is None:
            return hit, accent
        if not isinstance(value, dict):
            self.error(("velocity",), "velocity maps hit and accent to 1–127", "write 'velocity: {hit: 100, accent: 127}'")
            return hit, accent
        found = {"hit": hit, "accent": accent}
        for key, level in value.items():
            if str(key) not in found:
                self.error(("velocity", key), f"unknown key '{key}'", "velocity takes hit and accent")
                continue
            if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= 127:
                self.error(("velocity", key), f"'{level}' is outside 1–127", f"write the {key}'s velocity at full press, 1–127")
                continue
            found[str(key)] = level
        return found["hit"], found["accent"]

    def _humanize(self, value) -> tuple[float, int]:
        if value is None:
            return 0, 0
        if not isinstance(value, dict):
            self.error(("humanize",), "humanize maps timing and velocity", "write 'humanize: {timing: 5, velocity: 8}'")
            return 0, 0
        found = {"timing": 0, "velocity": 0}
        limits = {"timing": (0, 50, "± milliseconds"), "velocity": (0, 64, "± velocity")}
        for key, amount in value.items():
            if str(key) not in limits:
                self.error(("humanize", key), f"unknown key '{key}'", "humanize takes timing and velocity")
                continue
            low, high, what = limits[str(key)]
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not low <= amount <= high:
                self.error(("humanize", key), f"'{amount}' is outside {low}–{high}", f"{key} is {what}, {low}–{high}")
                continue
            found[str(key)] = amount
        return found["timing"], int(found["velocity"])


def _lane_number(value) -> int | None:
    if isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    lane = int(text)
    return lane if 1 <= lane <= MAX_LANE else None


def _steps_text(steps: Fraction) -> str:
    return str(steps.numerator) if steps.denominator == 1 else f"{float(steps):g}"


# --- the canonical data ------------------------------------------------------------------------------------
def row_text(cells, bar: int | None = None, marks=CELL_TEXT) -> str:
    """Cells as a row, a space between cells and ' | ' at every bar ('. . . x | . . . x')."""
    parts = []
    for i, cell in enumerate(cells):
        if i and bar and i % bar == 0:
            parts.append("|")
        parts.append(marks[cell])
    return " ".join(parts)


def to_data(pattern: Pattern) -> dict:
    """The pattern as canonical JSON-compatible data (defaults written out; lane keys as strings)."""
    bar = pattern.bar_steps
    bar = int(bar) if bar.denominator == 1 and bar < pattern.length else None
    data = {"format": FORMAT, "name": pattern.name}
    if pattern.description:
        data["description"] = pattern.description
    data.update({"meter": str(pattern.meter), "step": pattern.step, "length": pattern.length,
                 "lanes": {str(lane): row_text(cells, bar) for lane, cells in pattern.lanes}})
    if pattern.strum is not None:
        data["strum"] = row_text(pattern.strum, bar, STRUM_TEXT)
        data["spread"] = pattern.spread
    data.update({"swing": pattern.swing, "play": pattern.play,
                 "gate": RING if pattern.gate is None else pattern.gate,
                 "velocity": {"hit": pattern.hit, "accent": pattern.accent},
                 "humanize": {"timing": pattern.timing, "velocity": pattern.jitter},
                 "manual": sorted(pattern.manual)})
    return data
