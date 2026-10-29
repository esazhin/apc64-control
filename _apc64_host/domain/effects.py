"""What enters the pure surface and router (inputs) and what comes out of them (effects).

Time never enters the domain except as a Tick the shell enqueues for a ScheduleAfter; `at` fields are
left None here and stamped by the application when it executes the effect.
"""
from dataclasses import dataclass
from enum import StrEnum

from .controls import ControlId, Strip
from .layout import BankNo, DeviceName, Layout, LayoutCatalog, LayoutId, PageNo, PortPattern, UnitPortRole
from .leds import LedState, StripBarState
from .midi import MidiMessage, Value14
from .oled import OledText


class UnitView(StrEnum):
    """The unit's pad mode, from its '19 00 01 <m>' report (PROTOCOL-SPEC §4.5)."""
    SESSION = "session"
    OVERVIEW = "overview"
    NOTE = "note"
    CHORD = "chord"
    DRUM = "drum"
    STEP = "step"
    PROJECT = "project"
    CUSTOM = "custom"

    @property
    def host_drawn(self) -> bool:
        """Only Session view's pad grid belongs to the host; the others are the unit's (PROTOCOL-SPEC §4.6)."""
        return self is UnitView.SESSION


# The view buttons the host may switch the unit with, by the pad-mode request (19 00 01 <m>; verified live
# 2026-10-27: obeyed, never echoed). Project is not among them: it ends a lab session and its browser is the unit's.
SWITCHABLE_VIEWS = {"session": UnitView.SESSION, "note": UnitView.NOTE, "chord": UnitView.CHORD,
                    "step": UnitView.STEP, "custom": UnitView.CUSTOM}
NOT_SWITCHED = {"project": "view project stays the unit's own button: the host does not switch to Project view "
                           "(it would end a lab session, and the project browser is the unit's)"}


class InputSource(StrEnum):
    UNIT = "unit"
    REPLICA = "replica"


# --- surface inputs -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Press:
    control: ControlId
    velocity: int = 127
    source: InputSource = InputSource.UNIT


@dataclass(frozen=True)
class Release:
    control: ControlId
    source: InputSource = InputSource.UNIT


@dataclass(frozen=True)
class StripMove:
    strip: Strip
    value: Value14
    source: InputSource = InputSource.UNIT

    def __post_init__(self):
        object.__setattr__(self, "value", Value14(self.value))


@dataclass(frozen=True)
class EncoderTurn:
    """Detents turned: positive clockwise, negative counter-clockwise (contract d48)."""
    steps: int
    source: InputSource = InputSource.UNIT


@dataclass(frozen=True)
class ViewReport:
    view: UnitView


SurfaceInput = Press | Release | StripMove | EncoderTurn | ViewReport


# --- navigation and lifecycle inputs (from the page, API and engine) ----------------------------------
@dataclass(frozen=True)
class SelectPage:
    page: PageNo
    source: InputSource = InputSource.REPLICA


@dataclass(frozen=True)
class SelectBank:
    bank: BankNo
    source: InputSource = InputSource.REPLICA


@dataclass(frozen=True)
class SetPageShift:
    """Shift held or released in the page; counts the same as the unit's Shift (contract d90)."""
    held: bool


@dataclass(frozen=True)
class LayoutSwap:
    """Make `layout` live. The same LayoutId is a hot reload (nav and unchanged toggles kept, d96); another
    one is a switch (page 1 / bank 1, name on the OLED, q6). page/bank restore a remembered position."""
    layout: Layout | None
    page: int | None = None
    bank: int | None = None


@dataclass(frozen=True)
class CatalogUpdate:
    catalog: LayoutCatalog


@dataclass(frozen=True)
class Redraw:
    """Emit the whole frame again (on take, and whenever the unit's LEDs are unknown)."""


@dataclass(frozen=True)
class FeedbackMessage:
    port: str
    message: MidiMessage


@dataclass(frozen=True)
class PlayedMidi:
    role: UnitPortRole
    message: MidiMessage


@dataclass(frozen=True)
class Tick:
    kind: str
    seq: int = 0


# --- effects --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Origin:
    """Why a message is sent: the control or the played note it comes from."""
    control: ControlId | None = None
    note: int | None = None
    role: UnitPortRole | None = None
    kind: str = "press"   # press, release, move, touch, turn, toggle, note, aftertouch, cc


@dataclass(frozen=True)
class Send:
    device: DeviceName
    port: PortPattern
    message: MidiMessage
    origin: Origin = Origin()


@dataclass(frozen=True)
class Led:
    control: ControlId
    state: LedState


@dataclass(frozen=True)
class StripBar:
    strip: Strip
    state: StripBarState


@dataclass(frozen=True)
class Oled:
    text: OledText


class ActivityResult(StrEnum):
    SENT = "sent"
    NOT_SENT = "not_sent"
    REFUSED = "refused"
    UNBOUND = "unbound"
    DROPPED = "dropped"


@dataclass(frozen=True)
class ActivityEntry:
    """One line of the activity list: control (or note) → message → port, and what happened (d162)."""
    subject: str
    result: ActivityResult
    message: str | None = None
    port: str | None = None
    reason: str | None = None
    note: int | None = None
    aftertouch: int | None = None
    at: float | None = None

    def text(self) -> str:
        parts = [self.subject] + [p for p in (self.message, self.port) if p]
        verdict = {ActivityResult.SENT: "sent", ActivityResult.NOT_SENT: "not sent",
                   ActivityResult.REFUSED: "refused", ActivityResult.UNBOUND: "unbound",
                   ActivityResult.DROPPED: "dropped"}[self.result]
        return " → ".join(parts) + f": {verdict}" + (f", {self.reason}" if self.reason else "")


@dataclass(frozen=True)
class Activity:
    entry: ActivityEntry


class PlaySourceKind(StrEnum):
    """Where a played event came from (contract 2 s19.c2; §2.7 q7: any MIDI input, not only the APC64)."""
    CUSTOM = "custom"                     # the APC64's Custom port (Custom-view pads, real velocity)
    NOTES = "notes"                       # the APC64's Notes port (Note, Chord, Step and Drum views)
    SESSION_BINDING = "session_binding"   # the DAW port: a Session-view pad or button binding (a trigger)
    INPUT = "input"                       # any other MIDI input, named by its port (a keyboard, the MPC)
    PERFORMER = "performer"               # notes a module played for the unit's port (the lab's performer, §2.10)


@dataclass(frozen=True)
class PlaySource:
    kind: PlaySourceKind
    port: str | None = None               # the input's port name; for the APC64's own ports, its port name

    def __post_init__(self):
        object.__setattr__(self, "kind", PlaySourceKind(self.kind))
        if self.kind is PlaySourceKind.INPUT and not self.port:
            raise ValueError("an input source names its port")
        if self.port is None:
            object.__setattr__(self, "port", _UNIT_PORT_NAMES[self.kind])

    @classmethod
    def of_role(cls, role: UnitPortRole) -> "PlaySource":
        return cls({UnitPortRole.CUSTOM: PlaySourceKind.CUSTOM, UnitPortRole.NOTES: PlaySourceKind.NOTES}.get(
            UnitPortRole(role), PlaySourceKind.SESSION_BINDING))

    @classmethod
    def input(cls, port: str) -> "PlaySource":
        return cls(PlaySourceKind.INPUT, str(port))

    @property
    def played(self) -> bool:
        """Notes from here are played notes (harmony input), not Session-view triggers (d50) nor the notes a
        performer made of them (the harmony follows what is held, contract 2 §2.10)."""
        return self.kind not in (PlaySourceKind.SESSION_BINDING, PlaySourceKind.PERFORMER)

    def __str__(self) -> str:
        return str(self.port)


_UNIT_PORT_NAMES = {PlaySourceKind.CUSTOM: "APC64 Custom", PlaySourceKind.NOTES: "APC64 Notes",
                    PlaySourceKind.SESSION_BINDING: "APC64 DAW", PlaySourceKind.PERFORMER: "performer"}
NOTE_ENDED = "note_ended"                  # a PlayEvent kind: the host ended a held note (contract 2 s2.c9)
ENDED_BY_WINDOW_SHIFT = "ended by window shift"


@dataclass(frozen=True)
class PlayEvent:
    """One event of the agents' play stream (contract d150, d153).

    Contract 2: `port` names the input the event came from (PlaySource), and the kind NOTE_ENDED with reason
    ENDED_BY_WINDOW_SHIFT is a held note the host ended at a window shift or layout switch. `channel` (the guitar
    amendment) is the channel a played note arrived on from the unit (1–16), before routing re-channels it: a
    generated layout may send each string on its own channel."""
    kind: str                      # press, release, move, turn, note_on, note_off, aftertouch, nav, shift, view, layout,
                                   # note_ended (contract 2)
    source: InputSource = InputSource.UNIT
    view: UnitView | None = None
    control: ControlId | None = None
    note: int | None = None
    value: int | None = None
    velocity: int | None = None
    aftertouch: int | None = None
    sent: tuple[str, ...] = ()
    reason: str | None = None
    at: float | None = None
    port: PlaySource | None = None
    channel: int | None = None


@dataclass(frozen=True)
class Play:
    event: PlayEvent


@dataclass(frozen=True)
class ScheduleAfter:
    seconds: float
    tick: Tick


@dataclass(frozen=True)
class RequestLayout:
    layout: LayoutId


@dataclass(frozen=True)
class CallModule:
    """A ModuleAction binding fired (contract 2 s2.c7): the engine calls the module's handler with `event`."""
    action: object                 # ModuleAction
    event: object                  # ControlEvent
    control: ControlId | None = None


Effect = Send | Led | StripBar | Oled | Activity | Play | ScheduleAfter | RequestLayout | CallModule


# --- module display inputs (contract 2 s2.c3) -------------------------------------------------------------
@dataclass(frozen=True)
class SetResting:
    """A module's resting OLED text, shown whenever no host transient is on screen; None gives idle back."""
    text: OledText | None


@dataclass(frozen=True)
class ShowTransient:
    """Show a text for about 2 s, as the host does for a name (a module warning)."""
    text: OledText


@dataclass(frozen=True)
class PlayedNote:
    """A note sounding from the unit's own views, for the replica's played-notes row."""
    role: UnitPortRole
    note: int
    velocity: int
    aftertouch: int = 0
    routed: bool = True
