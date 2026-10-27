"""Layout generators and colour schemes (contract §7.1: OCP and ISP; d11–d19).

A generator turns its parameters into the 64 pad notes at transposition 0 (r1c1 first; None = silent). A
colour scheme colours a note. They are chosen separately, so any scheme works with any generator (d18), and
`generate` composes the two at a window transposition. A new generator or scheme is one file in
_apc64_lab/generators/ exposing GENERATOR or SCHEME, plus its test (d12, d99).

Interpretation (a build decision): the protocol method is `notes(params)` rather than §7's `generate(params,
transposition) → PadGrid`, so a generator never deals with colours or the window; `generate()` below is the
composed `generate(params, transposition) → PadGrid` the rest of the lab uses.
"""
import colorsys
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import parse_note

from .music import PitchClass
from .pads import PAD_COUNT, WHITE, RED, PadAssignment, PadGrid, Rgb


class ParamKind:
    NOTE = "note"         # a note number 0–127 or a name such as C3 (C3 = 60)
    INT = "int"
    CHANNEL = "channel"   # 1–16


@dataclass(frozen=True)
class ParamSpec:
    """One named generator or scheme parameter, with its range and default (listed by the CLI, API, panel)."""
    name: str
    kind: str
    default: int
    minimum: int
    maximum: int
    doc: str = ""

    def parse(self, value: Any) -> int:
        """The validated value, or DomainInvariantError(field=name, problem, fix)."""
        if self.kind == ParamKind.NOTE:
            try:
                number = int(parse_note(value))
            except DomainInvariantError as error:
                raise DomainInvariantError(self.name, error.problem, error.fix, error.joiner) from None
        else:
            if isinstance(value, bool) or not (isinstance(value, int) or str(value).lstrip("+-").isdigit()):
                raise DomainInvariantError(self.name, f"'{value}' is not a whole number",
                                           f"write a number from {self.minimum} to {self.maximum}")
            number = int(value)
        if not self.minimum <= number <= self.maximum:
            what = "channels are" if self.kind == ParamKind.CHANNEL else f"{self.name} is"
            raise DomainInvariantError(self.name, f"{number} is outside {self.minimum}–{self.maximum}",
                                       f"{what} {self.minimum}–{self.maximum}")
        return number

    def describe(self) -> dict:
        return {"name": self.name, "kind": self.kind, "default": self.default, "min": self.minimum,
                "max": self.maximum, "doc": self.doc}


CHANNEL_PARAM = ParamSpec("channel", ParamKind.CHANNEL, 1, 1, 16, "MIDI channel the unit sends the pads on (q8)")


@runtime_checkable
class PadLayoutGenerator(Protocol):
    name: str
    params: tuple[ParamSpec, ...]

    def notes(self, params: Mapping[str, int]) -> Sequence[int | None]:
        """64 notes at transposition 0, r1c1 first (None = silent). Notes may fall outside 0–127; the
        caller refuses them, naming the pad."""
        ...


@runtime_checkable
class ColourScheme(Protocol):
    name: str

    def colour(self, note: int, root: int) -> tuple[Rgb, Rgb]:
        """(rest, pressed) for a note; `root` is the layout's root pitch class (its base note's)."""
        ...


def defaults(spec: Sequence[ParamSpec]) -> dict[str, int]:
    return {p.name: p.default for p in spec}


def parse_params(spec: Sequence[ParamSpec], given: Mapping[str, Any]) -> dict[str, int]:
    """Defaults overlaid with the given values, each validated; unknown names are refused."""
    known = {p.name: p for p in spec}
    values = defaults(spec)
    for name, value in given.items():
        if name not in known:
            raise DomainInvariantError(name, f"unknown parameter '{name}'",
                                       "parameters are " + (", ".join(known) or "none"))
        values[name] = known[name].parse(value)
    return values


# --- built-ins (d11, d17) --------------------------------------------------------------------------------
class TonnetzCheckerboard:
    """Staggered checkerboard (d1): pad (x, r) from 0 at the bottom-left is active when x + r is even and holds
    base + 7·(x − r)/2 + 4·r, so two pads right is a fifth, up-right a major third, up-left a minor third
    down. Pads with odd x + r are silent and unlit (d3)."""
    name = "tonnetz"
    params = (ParamSpec("base", ParamKind.NOTE, 48, 0, 127, "note on pad r1c1 (C3 = 60)"), CHANNEL_PARAM)

    def notes(self, params):
        base = params["base"]
        return tuple(None if (x + r) % 2 else base + 7 * (x - r) // 2 + 4 * r
                     for r in range(8) for x in range(8))


class Isomorphic:
    """Every pad active (d2): bottom-left note, a semitone step per column and one per row."""
    name = "isomorphic"
    params = (ParamSpec("base", ParamKind.NOTE, 36, 0, 127, "note on pad r1c1 (C3 = 60)"),
              ParamSpec("column", ParamKind.INT, 1, -12, 12, "semitones per column to the right"),
              ParamSpec("row", ParamKind.INT, 5, -12, 12, "semitones per row upwards"),
              CHANNEL_PARAM)

    def notes(self, params):
        return tuple(params["base"] + params["column"] * x + params["row"] * r for r in range(8) for x in range(8))


def _hue(fifths_index: int) -> Rgb:
    r, g, b = colorsys.hsv_to_rgb(fifths_index / 12, 1.0, 1.0)
    return Rgb(round(r * 255), round(g * 255), round(b * 255))


class FifthsHue:
    """Default scheme (d17): hue = 30° × position on the circle of fifths and C white; pressed is white, and
    red for C (the prototype's colours)."""
    name = "fifths"

    def colour(self, note, root):
        pc = PitchClass.of(note)
        if pc == 0:
            return WHITE, RED
        return _hue(pc.fifths_index), WHITE


BUILTIN_GENERATORS: tuple[PadLayoutGenerator, ...] = (TonnetzCheckerboard(), Isomorphic())
BUILTIN_SCHEMES: tuple[ColourScheme, ...] = (FifthsHue(),)
DEFAULT_SCHEME = "fifths"


# --- composition -----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class OutOfRange:
    """A generated pad outside 0–127 (d4): which pad, its note, and the base that would fit (if linear)."""
    pad: PadPos
    note: int
    limit_base: int | None   # the highest (note > 127) or lowest (note < 0) base that fits, when 'base' exists
    high: bool

    def problem(self, base: int | None) -> str:
        """'110 puts pad r8c8 at note 138' (A10), or 'pad r8c8 gets note 138' for a generator without base."""
        return f"{base} puts {self.pad} at note {self.note}" if base is not None else f"{self.pad} gets note {self.note}"

    def fix(self) -> str:
        if self.limit_base is None:
            return "notes are 0–127; change the parameters"
        return f"the {'highest' if self.high else 'lowest'} base is {self.limit_base}"


class GeneratorFault(Exception):
    """A generator that raised, returned other than 64 pads, or returned a non-note (d13)."""


def raw_notes(generator: PadLayoutGenerator, params: Mapping[str, int]) -> tuple[int | None, ...]:
    """The generator's 64 notes at transposition 0, or GeneratorFault naming what went wrong."""
    try:
        notes = tuple(generator.notes(params))
    except Exception as error:   # a plugin may fail any way; it is listed as broken, never written
        raise GeneratorFault(str(error) or type(error).__name__) from error
    if len(notes) != PAD_COUNT:
        raise GeneratorFault(f"returned {len(notes)} pads, expected {PAD_COUNT}")
    for note in notes:
        if note is not None and (isinstance(note, bool) or not isinstance(note, int)):
            raise GeneratorFault(f"returned {note!r}, not a note number")
    return notes


def out_of_range(notes: Sequence[int | None], params: Mapping[str, int]) -> OutOfRange | None:
    """The worst pad outside 0–127, preferring the highest overshoot, or None when all fit."""
    active = [(PadPos.from_index(i), n) for i, n in enumerate(notes) if n is not None]
    high = max(active, key=lambda item: (item[1], -item[0].index), default=None)
    low = min(active, key=lambda item: (item[1], item[0].index), default=None)
    base = params.get("base")
    if high is not None and high[1] > 127:
        return OutOfRange(high[0], high[1], None if base is None else base - (high[1] - 127), True)
    if low is not None and low[1] < 0:
        return OutOfRange(low[0], low[1], None if base is None else base - low[1], False)
    return None


def generate(generator: PadLayoutGenerator, params: Mapping[str, int], scheme: ColourScheme,
             transposition: int = 0, overrides: Mapping[int, Rgb] | None = None) -> PadGrid:
    """The 64 pads at a window transposition, coloured by the scheme (rest colours per pitch class may be
    overridden). Raises GeneratorFault for a broken generator and DomainInvariantError for a note outside
    0–127 (callers check out_of_range first to name the pad)."""
    notes = raw_notes(generator, params)
    root = PitchClass.of(params.get("base", 0))
    channel = params.get("channel", 1)
    pads = []
    for note in notes:
        if note is None:
            pads.append(PadAssignment.silence())
            continue
        note += transposition
        if not 0 <= note <= 127:
            raise DomainInvariantError("note", f"note {note} is outside 0–127", "move the window back")
        try:
            rest, pressed = scheme.colour(note, int(root))
        except Exception as error:
            raise GeneratorFault(f"scheme {scheme.name}: {error or type(error).__name__}") from error
        if overrides and PitchClass.of(note) in overrides:
            rest = overrides[PitchClass.of(note)]
        pads.append(PadAssignment(note, Rgb.of(rest), Rgb.of(pressed), True, channel))
    return PadGrid(tuple(pads))
