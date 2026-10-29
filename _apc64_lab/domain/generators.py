"""Layout generators and colour schemes (contract §7.1: OCP and ISP; d11–d19).

A generator turns its parameters into the 64 pad notes at transposition 0 (r1c1 first; None = silent). A
colour scheme colours a note. They are chosen separately, so any scheme works with any generator (d18), and
`generate` composes the two at a window transposition. A new generator or scheme is one file in
_apc64_lab/generators/ exposing GENERATOR or SCHEME, plus its test (d12, d99).

Optional, for the generators and schemes that need them (each is looked up with getattr, so the others are
unchanged):
- a generator's `marks(params)`: 64 of 'root' (white, pressed red), 'accent' (the scheme's colour), 'dim' (the
  scheme's colour, darker) or None (the scheme's colour), r1c1 first, so a layout can stress pads by their place;
- a generator's `row_labels(params)`: 8 names, bottom row first, which the harmony pad grid shows beside the rows;
- a generator's `pad_names(params, transposition)`: 64 spellings (None for silent pads) of the pads at that window,
  for a layout whose rows are scales (the modes explorer spells each row in its mode);
- a scheme's `params` (ParamSpecs, written in the lab section like a generator's) with `configured(values)`, the
  scheme bound to them; a configured scheme's `overlay(root)`, the ScaleOverlay the page dims the pads by.

Amendment (the guitar neck, 2026-10-27), also optional and looked up the same way:
- a generator's `channels(params)`: 64 MIDI channels (1–16, None for the layout's `channel` parameter), r1c1 first,
  so pads may send on channels of their own (the guitar: one channel per string, so equal pitches on different
  strings stay apart on the Custom port, where the unit sends only note and channel);
- a generator's `root(params)`: the layout's root pitch class when it is not its `base` note's (a scheme's root);
- a generator's `window(params)`: a WindowSpec, its own window steps and transposition range (domain/window.py);
  without it the window is Octave / Fifth / Third as before. A key window (its `key_root` set, 2026-10-29: the
  modes explorer) moves the key: the scheme colours each note as it is at the first key (note − transposition), so
  the colours follow the key and the picture is the same in every key;
- a generator's `neck(params)`: a Neck (strings, frets, channels) the page draws as a fretboard.

After the guitar live test (2026-10-27), also optional:
- a generator's `window_marks(params, transposition)`: 64 marks for the pads at that window position, r1c1 first,
  for marks that move with the window (the guitar's inlay frets); where it gives a mark it wins over `marks`. Two
  more marks serve it: 'shade' (the scheme's colour, moderately darker: SHADE; a colour already dark is kept, so
  a scheme's own dim pads never go black) and 'bright' (the scheme's colour lifted toward white: BRIGHT). The
  pressed colour is never changed by a mark but 'root'.

Interpretation (a build decision): the protocol method is `notes(params)` rather than §7's `generate(params,
transposition) → PadGrid`, so a generator never deals with colours or the window; `generate()` below is the
composed `generate(params, transposition) → PadGrid` the rest of the lab uses.
"""
import colorsys
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from _apc64_host.domain.controls import PadPos
from _apc64_host.domain.issues import DomainInvariantError
from _apc64_host.domain.midi import parse_note

from difflib import get_close_matches

from .harmony.spelling import parse_pitch_class
from .music import PitchClass
from .pads import PAD_COUNT, WHITE, RED, PadAssignment, PadGrid, Rgb
from .window import WindowSpec


class ParamKind:
    NOTE = "note"                 # a note number 0–127 or a name such as C3 (C3 = 60)
    INT = "int"
    CHANNEL = "channel"           # 1–16
    PITCH_CLASS = "pitch-class"   # a note name without octave (C, F#, B♭) → 0–11; default None = the layout's root
    CHOICE = "choice"             # one of `choices` (a name), e.g. a scale
    NOTE_LIST = "notes"           # a preset name from `choices`, or a list of `minimum`–`maximum` notes (a tuning)


@dataclass(frozen=True)
class ParamSpec:
    """One named generator or scheme parameter, with its range and default (listed by the CLI, API, panel).
    A choice's value is its name; `lookup` (optional) turns what is written into a choice ('Harmonic Minor' →
    'harmonic-minor') or None, and `aliases` are accepted too."""
    name: str
    kind: str
    default: int | str | None
    minimum: int = 0
    maximum: int = 0
    doc: str = ""
    choices: tuple[str, ...] = ()
    lookup: Any = field(default=None, compare=False, repr=False)

    def parse(self, value: Any) -> int | str:
        """The validated value, or DomainInvariantError(field=name, problem, fix)."""
        if self.kind == ParamKind.CHOICE:
            return self._choice(value)
        if self.kind == ParamKind.NOTE_LIST:
            return self._notes(value) if isinstance(value, (list, tuple)) else self._choice(value)
        if self.kind == ParamKind.PITCH_CLASS:
            pc = parse_pitch_class(value) if isinstance(value, str) else None
            if pc is None:
                raise DomainInvariantError(self.name, f"'{value}' is not a note name",
                                           "write C, C♯ (or C#), D♭ (or Db) … B, without an octave")
            return pc
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

    def _choice(self, value: Any) -> str:
        text = str(value).strip()
        found = self.lookup(text) if self.lookup is not None else (text if text in self.choices else None)
        if found in self.choices:
            return found
        close = get_close_matches(text.lower(), self.choices, n=1, cutoff=0.6)
        raise DomainInvariantError(self.name, f'no {self.name} "{text}"',
                                   (f"did you mean {close[0]}? " if close else "")
                                   + f"available: {', '.join(self.choices)}")

    def _notes(self, values) -> tuple[int, ...]:
        """A list of notes, each a number or a name (C3 = 60), and as many as the parameter takes."""
        if not self.minimum <= len(values) <= self.maximum:
            raise DomainInvariantError(self.name, f"{len(values)} notes",
                                       f"write {self.minimum} to {self.maximum} notes, low to high, or one of: "
                                       + ", ".join(self.choices))
        notes = []
        for k, value in enumerate(values, 1):
            try:
                notes.append(int(parse_note(value)))
            except DomainInvariantError as error:
                raise DomainInvariantError(self.name, f"note {k}: {error.problem}", error.fix, error.joiner) from None
        return tuple(notes)

    def describe(self) -> dict:
        found = {"name": self.name, "kind": self.kind, "default": self.default, "min": self.minimum,
                 "max": self.maximum, "doc": self.doc}
        if self.choices:
            found["choices"] = list(self.choices)
        return found


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


@dataclass(frozen=True)
class ScaleOverlay:
    """The scale a configured scheme lights (its in-scale pitch classes), for the page's pad grid."""
    key: str
    name: str
    root: int
    pitch_classes: frozenset[int]
    names: tuple[tuple[int, str], ...] = ()   # pitch class → its spelling in the scale

    def to_json(self) -> dict:
        names = dict(self.names)
        return {"key": self.key, "name": self.name, "root": self.root, "root_name": names.get(self.root),
                "pcs": sorted(self.pitch_classes), "names": {str(pc): n for pc, n in sorted(names.items())}}


def scheme_params(scheme: ColourScheme) -> tuple[ParamSpec, ...]:
    params = getattr(scheme, "params", ())
    return tuple(params) if isinstance(params, (tuple, list)) else ()


def configure(scheme: ColourScheme, values: Mapping[str, Any] | None = None) -> ColourScheme:
    """The scheme bound to its parameters (defaults for any not given); a scheme without any is itself."""
    specs = scheme_params(scheme)
    if not specs:
        return scheme
    return scheme.configured({**defaults(specs), **dict(values or {})})


def overlay_of(scheme: ColourScheme, root: int) -> ScaleOverlay | None:
    """A configured scheme's scale overlay, or None (most schemes have none)."""
    hook = getattr(scheme, "overlay", None)
    return hook(root) if callable(hook) else None


MARKS = ("root", "accent", "dim", "shade", "bright")
DIM = 0.3      # a 'dim' mark keeps the scheme's hue at this brightness
SHADE = 0.45   # a 'shade' mark: darker, the hue still plain on the unit's LEDs (which crush low levels)
SHADE_FROM = 64   # a colour whose brightest channel is below this is dark already: 'shade' keeps it
BRIGHT = 0.4   # a 'bright' mark mixes this much white into the scheme's colour


def _dimmed(colour: Rgb, factor: float = DIM) -> Rgb:
    return Rgb(round(colour.r * factor), round(colour.g * factor), round(colour.b * factor))


def _shaded(colour: Rgb) -> Rgb:
    return colour if max(colour.r, colour.g, colour.b) < SHADE_FROM else _dimmed(colour, SHADE)


def _brightened(colour: Rgb) -> Rgb:
    lift = lambda c: round(c + (255 - c) * BRIGHT)
    return Rgb(lift(colour.r), lift(colour.g), lift(colour.b))


def marks_of(generator: PadLayoutGenerator, params: Mapping[str, Any]) -> tuple[str | None, ...]:
    """The generator's 64 marks (None each without a marks hook), or GeneratorFault."""
    hook = getattr(generator, "marks", None)
    if not callable(hook):
        return (None,) * PAD_COUNT
    try:
        marks = tuple(hook(params))
    except Exception as error:   # a plugin may fail any way
        raise GeneratorFault(f"marks: {error or type(error).__name__}") from error
    if len(marks) != PAD_COUNT or any(m is not None and m not in MARKS for m in marks):
        raise GeneratorFault(f"marks must be {PAD_COUNT} of {', '.join(MARKS)} or None")
    return marks


def window_marks_of(generator: PadLayoutGenerator, params: Mapping[str, Any],
                    transposition: int) -> tuple[str | None, ...] | None:
    """The generator's 64 marks at a window position, or None without the hook; GeneratorFault as marks_of."""
    hook = getattr(generator, "window_marks", None)
    if not callable(hook):
        return None
    try:
        marks = tuple(hook(params, transposition))
    except Exception as error:   # a plugin may fail any way
        raise GeneratorFault(f"window_marks: {error or type(error).__name__}") from error
    if len(marks) != PAD_COUNT or any(m is not None and m not in MARKS for m in marks):
        raise GeneratorFault(f"window_marks must be {PAD_COUNT} of {', '.join(MARKS)} or None")
    return marks


def describe_of(generator: PadLayoutGenerator, param: str, value) -> str | None:
    """The generator's comment for a parameter's new value, written next to it when the page changes it (a
    comment that spells out the old value would go stale), or None to keep the line's comment."""
    hook = getattr(generator, "describe", None)
    if not callable(hook):
        return None
    try:
        text = hook(param, value)
    except Exception:
        return None
    return str(text) if text else None


def row_labels_of(generator: PadLayoutGenerator, params: Mapping[str, Any]) -> tuple[str, ...] | None:
    """The generator's 8 row names, bottom first, or None (also when the hook fails: labels are a nicety)."""
    hook = getattr(generator, "row_labels", None)
    if not callable(hook):
        return None
    try:
        labels = tuple(str(label) for label in hook(params))
    except Exception:
        return None
    return labels if len(labels) == 8 else None


def pad_names_of(generator: PadLayoutGenerator, params: Mapping[str, Any], transposition: int = 0) -> tuple | None:
    """The generator's 64 pad spellings at a window, or None (also when the hook fails: names are a nicety)."""
    hook = getattr(generator, "pad_names", None)
    if not callable(hook):
        return None
    try:
        names = tuple(hook(params, transposition))
    except Exception:
        return None
    return names if len(names) == PAD_COUNT else None


def channels_of(generator: PadLayoutGenerator, params: Mapping[str, Any]) -> tuple[int | None, ...] | None:
    """The generator's 64 pad channels (None each: the layout's channel), or None without the hook; GeneratorFault
    when the hook fails or answers other than 64 channels 1–16 or None."""
    hook = getattr(generator, "channels", None)
    if not callable(hook):
        return None
    try:
        channels = tuple(hook(params))
    except Exception as error:   # a plugin may fail any way
        raise GeneratorFault(f"channels: {error or type(error).__name__}") from error
    if len(channels) != PAD_COUNT or any(c is not None and (isinstance(c, bool) or not isinstance(c, int)
                                                             or not 1 <= c <= 16) for c in channels):
        raise GeneratorFault(f"channels must be {PAD_COUNT} of 1–16 or None")
    return channels


def root_of(generator: PadLayoutGenerator | None, params: Mapping[str, Any]) -> int:
    """The layout's root pitch class: the generator's `root(params)` when it has one, else its base note's (C
    without a base)."""
    hook = getattr(generator, "root", None)
    if callable(hook):
        try:
            return int(hook(params)) % 12
        except Exception:   # a nicety: fall back to the base
            pass
    base = params.get("base", 0)
    return int(PitchClass.of(base if isinstance(base, int) else 0))


def window_of(generator: PadLayoutGenerator | None, params: Mapping[str, Any]) -> WindowSpec | None:
    """The generator's own window (steps and range), or None for Octave / Fifth / Third; GeneratorFault when the
    hook fails or answers something else."""
    hook = getattr(generator, "window", None)
    if not callable(hook):
        return None
    try:
        spec = hook(params)
    except Exception as error:
        raise GeneratorFault(f"window: {error or type(error).__name__}") from error
    if spec is not None and not isinstance(spec, WindowSpec):
        raise GeneratorFault("window must return a WindowSpec or None")
    return spec


@dataclass(frozen=True)
class NeckString:
    """One string of a fretboard layout: its number (1 = the highest), open note and the channel it sends on."""
    number: int
    open: int
    channel: int

    def to_json(self) -> dict:
        from .harmony.spelling import pc_name
        return {"string": self.number, "open": self.open, "name": pc_name(self.open), "channel": self.channel}


@dataclass(frozen=True)
class Neck:
    """A fretboard the page draws (the guitar generator's `neck(params)`): the strings, highest first, and the
    number of frets; `shown` frets are on the pads at a time, from the window's position."""
    strings: tuple[NeckString, ...]
    frets: int
    shown: int = 8

    def to_json(self) -> dict:
        return {"strings": [s.to_json() for s in self.strings], "frets": self.frets, "shown": self.shown}


def neck_of(generator: PadLayoutGenerator | None, params: Mapping[str, Any]) -> Neck | None:
    """The generator's fretboard for the page, or None (also when the hook fails: the view is a nicety)."""
    hook = getattr(generator, "neck", None)
    if not callable(hook):
        return None
    try:
        neck = hook(params)
    except Exception:
        return None
    return neck if isinstance(neck, Neck) else None


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


def fifths_hue(fifths_index: int) -> Rgb:
    """Full-saturation hue 30° × the position on the circle of fifths (C red, G orange, … F rose)."""
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
        return fifths_hue(pc.fifths_index), WHITE


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
    marks = marks_of(generator, params)
    moving = window_marks_of(generator, params, transposition)
    if moving is not None:
        marks = tuple(w if w is not None else m for w, m in zip(moving, marks))
    root = root_of(generator, params)
    spec = window_of(generator, params) if transposition else None
    shift = transposition if spec is not None and spec.key_root is not None else 0   # a key window: relative colours
    channel = params.get("channel", 1)
    channels = channels_of(generator, params) or (None,) * PAD_COUNT
    pads = []
    for note, mark, own_channel in zip(notes, marks, channels):
        if note is None:
            pads.append(PadAssignment.silence())
            continue
        note += transposition
        if not 0 <= note <= 127:
            raise DomainInvariantError("note", f"note {note} is outside 0–127", "move the window back")
        try:
            rest, pressed = scheme.colour(note - shift, int(root))
        except Exception as error:
            raise GeneratorFault(f"scheme {scheme.name}: {error or type(error).__name__}") from error
        if overrides and PitchClass.of(note) in overrides:
            rest = overrides[PitchClass.of(note)]
        if mark == "root":
            rest, pressed = WHITE, RED
        elif mark == "dim":
            rest = _dimmed(Rgb.of(rest))
        elif mark == "shade":
            rest = _shaded(Rgb.of(rest))
        elif mark == "bright":
            rest = _brightened(Rgb.of(rest))
        pads.append(PadAssignment(note, Rgb.of(rest), Rgb.of(pressed), True, own_channel or channel))
    return PadGrid(tuple(pads))
