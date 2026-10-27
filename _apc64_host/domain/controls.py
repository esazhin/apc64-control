"""Every physical control of the APC64: the ControlId sum type, the SURFACE catalog and control names.

Names (contract a25): 'pad r1c1'..'pad r8c8' with row 1 at the bottom, 'track 1'..'track 8',
'trackctl 1'..'trackctl 8', 'scene 1'..'scene 8', 'stripmode 1'..'stripmode 6', 'strip 1'..'strip 8',
named buttons ('play', 'rec', 'stop', 'up', 'tempo', 'recarm', …), 'shift', 'encoder' and 'encoder press'.
Range forms run in reading order from the bottom-left: 'pads r1c1-r2c8' is 16 pads, 'tracks 1-8' is 8.
"""
import re
from dataclasses import dataclass
from enum import StrEnum

from .issues import DomainInvariantError


def _check(value: int, low: int, high: int, what: str, fix: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DomainInvariantError("control", f"no such {what}", fix, joiner=", ")
    return value


@dataclass(frozen=True, order=True)
class PadPos:
    """A grid pad; row 1 is the bottom row and col 1 the left column."""
    row: int
    col: int

    def __post_init__(self):
        for value in (self.row, self.col):
            _check(value, 1, 8, "pad", "pads are r1c1–r8c8")

    @property
    def index(self) -> int:
        """0–63 in reading order from the bottom-left (the DAW-mode pad number, contract d47)."""
        return (self.row - 1) * 8 + self.col - 1

    @classmethod
    def from_index(cls, index: int) -> "PadPos":
        return cls(index // 8 + 1, index % 8 + 1)

    def __str__(self) -> str:
        return f"pad r{self.row}c{self.col}"


@dataclass(frozen=True, order=True)
class _Numbered:
    n: int
    WORD = ""
    COUNT = 8

    def __post_init__(self):
        _check(self.n, 1, self.COUNT, self.WORD, f"{self.WORD}s are 1–{self.COUNT}")

    def __str__(self) -> str:
        return f"{self.WORD} {self.n}"


@dataclass(frozen=True, order=True)
class TrackButton(_Numbered):
    WORD = "track"


@dataclass(frozen=True, order=True)
class TrackControl(_Numbered):
    WORD = "trackctl"


@dataclass(frozen=True, order=True)
class SceneButton(_Numbered):
    WORD = "scene"


@dataclass(frozen=True, order=True)
class StripModeButton(_Numbered):
    WORD = "stripmode"
    COUNT = 6


@dataclass(frozen=True, order=True)
class Strip(_Numbered):
    WORD = "strip"


@dataclass(frozen=True, order=True)
class StripTouch(_Numbered):
    """The touch of a strip; bound through its strip's 'touch' action."""
    WORD = "strip"

    def __str__(self) -> str:
        return f"strip {self.n} touch"


class FunctionName(StrEnum):
    TEMPO = "tempo"
    CLEAR = "clear"
    DUPLICATE = "duplicate"
    QUANTIZE = "quantize"
    FIXED = "fixed"
    UNDO = "undo"


class TransportName(StrEnum):
    PLAY = "play"
    REC = "rec"
    STOP = "stop"


class NavName(StrEnum):
    DOWN = "down"
    UP = "up"
    LEFT = "left"
    RIGHT = "right"


class ModeName(StrEnum):
    RECARM = "recarm"
    MUTE = "mute"
    SOLO = "solo"
    CLIPSTOP = "clipstop"   # the track-mode Stop button, named apart from transport 'stop'


class ViewName(StrEnum):
    SESSION = "session"
    NOTE = "note"
    CHORD = "chord"
    STEP = "step"
    PROJECT = "project"
    CUSTOM = "custom"


@dataclass(frozen=True, order=True)
class _Named:
    kind: StrEnum

    def __str__(self) -> str:
        return str(self.kind)


@dataclass(frozen=True, order=True)
class FunctionButton(_Named):
    kind: FunctionName


@dataclass(frozen=True, order=True)
class Transport(_Named):
    kind: TransportName


@dataclass(frozen=True, order=True)
class Nav(_Named):
    kind: NavName


@dataclass(frozen=True, order=True)
class ModeButton(_Named):
    kind: ModeName


@dataclass(frozen=True, order=True)
class DeviceLocal(_Named):
    """A pad-mode (view) button: the unit's own, never reaching the host (PROTOCOL-SPEC §5)."""
    kind: ViewName

    def __str__(self) -> str:
        return f"view {self.kind}"


@dataclass(frozen=True, order=True)
class Encoder:
    def __str__(self) -> str:
        return "encoder"


@dataclass(frozen=True, order=True)
class EncoderPress:
    def __str__(self) -> str:
        return "encoder press"


@dataclass(frozen=True, order=True)
class Shift:
    def __str__(self) -> str:
        return "shift"


ControlId = (PadPos | TrackButton | TrackControl | SceneButton | StripModeButton | Strip | StripTouch
             | FunctionButton | Transport | Nav | ModeButton | DeviceLocal | Encoder | EncoderPress | Shift)


class ControlRole(StrEnum):
    BINDABLE = "bindable"
    NAVIGATION = "navigation"
    MODIFIER = "modifier"
    DEVICE_LOCAL = "device_local"


class LedKind(StrEnum):
    RGB = "rgb"          # pads, track buttons, track-control row: note-on, ch = behaviour, velocity = colour
    SINGLE = "single"    # one-colour LED: note-on, ch = state - 1
    BAR = "bar"          # strip LED bar: colour CC, mode CC and pitch-bend position
    NONE = "none"


class Reachability(StrEnum):
    """Whether the control's Shift layer is known to reach the host (contract d45)."""
    VERIFIED = "verified"
    UNVERIFIED = "unverified: live check pending"
    NOT_REACHABLE = "not reachable on this unit"


@dataclass(frozen=True)
class Geometry:
    """Schematic panel position in pad-sized units (x to the right, y downwards); not to scale."""
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0


@dataclass(frozen=True)
class SurfaceEntry:
    id: ControlId
    role: ControlRole
    display: str
    geometry: Geometry
    led: LedKind
    shift_reach: Reachability = Reachability.VERIFIED

    @property
    def name(self) -> str:
        return str(self.id)

    @property
    def bindable(self) -> bool:
        return self.role is ControlRole.BINDABLE


# Strip-mode button names as PROTOCOL-SPEC §5 gives them (notes 121–126 in panel order). An earlier note said
# Device, Volume, Pan, Send A, Send B, Channel Strip; contract d44 settles the labels by a live look.
STRIP_MODE_NAMES = ("Device", "Volume", "Pan", "Sends", "Channel", "Off")

_GRID_X = 9.5


def _build_surface() -> tuple[SurfaceEntry, ...]:
    B, NAV, MOD, LOCAL = (ControlRole.BINDABLE, ControlRole.NAVIGATION, ControlRole.MODIFIER,
                          ControlRole.DEVICE_LOCAL)
    unverified = Reachability.UNVERIFIED
    entries = []
    for row in range(1, 9):
        for col in range(1, 9):
            pad = PadPos(row, col)
            entries.append(SurfaceEntry(pad, B, f"Pad r{row}c{col}", Geometry(_GRID_X + col - 1, 9 - row),
                                        LedKind.RGB, unverified))
    for n in range(1, 9):
        entries.append(SurfaceEntry(SceneButton(n), NAV, f"Scene {n}", Geometry(_GRID_X + 8.25, n),
                                    LedKind.SINGLE, Reachability.VERIFIED if n <= 4 else unverified))
        entries.append(SurfaceEntry(TrackButton(n), B, f"Track {n}", Geometry(_GRID_X + n - 1, 9.25),
                                    LedKind.RGB, unverified))
        entries.append(SurfaceEntry(TrackControl(n), B, f"Track control {n}",
                                    Geometry(_GRID_X + n - 1, 10.25), LedKind.RGB, unverified))
        entries.append(SurfaceEntry(Strip(n), B, f"Strip {n}", Geometry(n - 1, 1, 0.8, 4.5), LedKind.BAR))
        entries.append(SurfaceEntry(StripTouch(n), B, f"Strip {n} touch", Geometry(n - 1, 1, 0.8, 4.5),
                                    LedKind.NONE))
    for n, label in enumerate(STRIP_MODE_NAMES, start=1):
        entries.append(SurfaceEntry(StripModeButton(n), NAV, label, Geometry(n - 1, 6), LedKind.SINGLE))
    for i, name in enumerate(FunctionName):
        entries.append(SurfaceEntry(FunctionButton(name), B, name.value.capitalize(), Geometry(i, 7),
                                    LedKind.SINGLE))
    for i, name in enumerate(TransportName):
        entries.append(SurfaceEntry(Transport(name), B, name.value.capitalize(), Geometry(i, 9.25),
                                    LedKind.SINGLE))
    for i, name in enumerate(NavName):
        entries.append(SurfaceEntry(Nav(name), B, name.value.capitalize(), Geometry(4 + i, 9.25),
                                    LedKind.SINGLE))
    for i, (name, label) in enumerate(zip(ModeName, ("Rec Arm", "Mute", "Solo", "Stop"))):
        entries.append(SurfaceEntry(ModeButton(name), B, label, Geometry(i, 10.25), LedKind.SINGLE))
    entries.append(SurfaceEntry(Shift(), MOD, "Shift", Geometry(7, 10.25), LedKind.SINGLE))
    entries.append(SurfaceEntry(Encoder(), B, "Encoder", Geometry(7, 0), LedKind.NONE))
    entries.append(SurfaceEntry(EncoderPress(), B, "Encoder press", Geometry(7, 0), LedKind.SINGLE))
    for i, name in enumerate(ViewName):
        entries.append(SurfaceEntry(DeviceLocal(name), LOCAL, name.value.capitalize(),
                                    Geometry(_GRID_X + 8.25, 9.25 + i * 0.5, 1, 0.5), LedKind.NONE))
    return tuple(entries)


SURFACE: tuple[SurfaceEntry, ...] = _build_surface()
_BY_ID = {entry.id: entry for entry in SURFACE}
_BY_NAME = {entry.name: entry.id for entry in SURFACE}


def entry(control: ControlId) -> SurfaceEntry:
    return _BY_ID[control]


def role_of(control: ControlId) -> ControlRole:
    return _BY_ID[control].role


PADS = tuple(PadPos(r, c) for r in range(1, 9) for c in range(1, 9))
STRIPS = tuple(Strip(n) for n in range(1, 9))

# Words of the numbered families, singular and plural, mapped to their constructor
_NUMBERED = {
    "track": TrackButton, "tracks": TrackButton,
    "trackctl": TrackControl, "trackctls": TrackControl,
    "scene": SceneButton, "scenes": SceneButton,
    "stripmode": StripModeButton, "stripmodes": StripModeButton,
    "strip": Strip, "strips": Strip,
}
_PAD_WORDS = ("pad", "pads")
_PAD = re.compile(r"^r(\d+)c(\d+)$")
_NUMBER = re.compile(r"^\d+$")


def _normalise(text: str) -> str:
    return " ".join(str(text).lower().replace("–", "-").split())


def control_names() -> list[str]:
    """Every single-control name the layout format accepts, in SURFACE order."""
    return [entry.name for entry in SURFACE]


def _pad(token: str) -> PadPos:
    match = _PAD.match(token)
    if not match:
        raise DomainInvariantError("control", "no such pad", "pads are r1c1–r8c8", joiner=", ")
    return PadPos(int(match[1]), int(match[2]))


def _number(token: str, word: str) -> int:
    if not _NUMBER.match(token):
        raise DomainInvariantError("control", f"'{token}' is not a {word} number",
                                   f"write {word} 1, {word} 2, …", joiner="; ")
    return int(token)


def parse_controls(text: str) -> tuple[ControlId, ...]:
    """A single control name or a range form, expanded in reading order ('pads r1c1-r2c8' → 16 pads)."""
    name = _normalise(text)
    if name in _BY_NAME:
        return (_BY_NAME[name],)
    words = name.split(" ")
    head, rest = words[0], " ".join(words[1:]).replace(" ", "")
    if head in _PAD_WORDS and rest:
        first, _, last = rest.partition("-")
        start = _pad(first)
        end = _pad(last) if last else start
        if end.index < start.index:
            raise DomainInvariantError(
                "control", f"the range {name} runs backwards",
                f"write pads r{end.row}c{end.col}-r{start.row}c{start.col}", joiner="; ")
        return tuple(PadPos.from_index(i) for i in range(start.index, end.index + 1))
    if head in _NUMBERED and rest:
        kind = _NUMBERED[head]
        first, _, last = rest.partition("-")
        low = _number(first, kind.WORD)
        high = _number(last, kind.WORD) if last else low
        if high < low:
            raise DomainInvariantError("control", f"the range {name} runs backwards",
                                       f"write {kind.WORD}s {high}-{low}", joiner="; ")
        return tuple(kind(n) for n in range(low, high + 1))
    raise DomainInvariantError(
        "control", f"unknown control '{text}'",
        "use pad r1c1–r8c8, track 1–8, trackctl 1–8, strip 1–8, encoder, encoder press, "
        + ", ".join(e.name for e in SURFACE if isinstance(e.id, (FunctionButton, Transport, Nav, ModeButton))),
        joiner="; ")


def parse_control(text: str) -> ControlId:
    """Exactly one control; a range is refused."""
    controls = parse_controls(text)
    if len(controls) != 1:
        raise DomainInvariantError("control", f"'{text}' names {len(controls)} controls",
                                   "name a single control here", joiner="; ")
    return controls[0]


def format_controls(controls) -> str:
    """The shortest name for a run of controls: 'pad r1c3', 'pads r1c5–r1c8', 'tracks 1–8'.

    A run that is not contiguous in reading order is written as comma-separated runs.
    """
    controls = sorted(controls, key=_order_key)
    if not controls:
        return ""
    runs, run = [], [controls[0]]
    for control in controls[1:]:
        prev = run[-1]
        if type(control) is type(prev) and _order_key(control)[1] == _order_key(prev)[1] + 1:
            run.append(control)
        else:
            runs.append(run)
            run = [control]
    runs.append(run)
    return ", ".join(_format_run(r) for r in runs)


def _order_key(control):
    if isinstance(control, PadPos):
        return ("pad", control.index)
    if isinstance(control, _Numbered):
        return (type(control).__name__, control.n)
    return (type(control).__name__, 0)


def _format_run(run) -> str:
    first, last = run[0], run[-1]
    if len(run) == 1:
        return str(first)
    if isinstance(first, PadPos):
        return f"pads r{first.row}c{first.col}–r{last.row}c{last.col}"
    return f"{first.WORD}s {first.n}–{last.n}"
