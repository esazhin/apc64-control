"""What the application needs from the unit, MIDI ports, files, the desktop and the clock, as structural Protocols.

Infrastructure adapters (and the simulated APC64) implement these; application services take them in their
constructors and never import an adapter (contract §7 dependency direction).
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from ..domain.layout import ContentHash, LayoutId, NavState, UnitPortRole, VersionId
from ..domain.calibration import Calibration
from ..domain.midi import MidiMessage, Value14
from ..domain.outbound import SysexCommand
from ..domain.unit_status import Holder, UnitPresence


# --- errors ---------------------------------------------------------------------------------------------
class PortBusy(Exception):
    """The subdevice is held by another program (EBUSY); never fought for (contract inv13)."""

    def __init__(self, holder: Holder | None = None):
        self.holder = holder
        super().__init__(f"busy: held by {holder.name}" if holder else "busy")


class PortNoPermission(Exception):
    """The subdevice cannot be opened by this user right now (EACCES, no seat), not Busy (d25)."""


class PortGone(Exception):
    """The subdevice vanished (unplugged, ENODEV/EIO) or was closed underneath us."""


# --- values ---------------------------------------------------------------------------------------------
class SendResult(StrEnum):
    SENT = "sent"
    MISSING = "missing"
    FAILED = "failed"


class PortDirection(StrEnum):
    OUTPUT = "output"     # we can send to it (a target)
    INPUT = "input"       # we can listen to it (feedback)
    BOTH = "both"


@dataclass(frozen=True)
class PortInfo:
    name: str
    direction: PortDirection
    present: bool = True


class ChangeKind(StrEnum):
    CHANGED = "changed"
    DELETED = "deleted"


class ConsentAnswer(StrEnum):
    TAKE = "take"
    DISMISSED = "dismissed"


MISSING = None   # LayoutSource.read of a file that is not there


@runtime_checkable
class Cancellable(Protocol):
    def cancel(self) -> None: ...


# --- the unit -------------------------------------------------------------------------------------------
@runtime_checkable
class UnitLocator(Protocol):
    def find(self) -> UnitPresence | None: ...
    def subscribe(self, callback: Callable[[UnitPresence | None], None]) -> None: ...


@runtime_checkable
class HolderLookup(Protocol):
    def holder_of(self, role: UnitPortRole) -> Holder | None: ...
    def subscribe(self, callback: Callable[[UnitPortRole, Holder | None], None]) -> None: ...


@runtime_checkable
class UnitConnection(Protocol):
    """One exclusively held subdevice. Only the DAW connection is written, and only by the OutboundGate."""

    def listen(self, on_bytes: Callable[[bytes], None], on_gone: Callable[[], None]) -> None: ...
    def write(self, data: bytes) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class UnitPort(Protocol):
    def open(self, role: UnitPortRole, address: str) -> UnitConnection:
        """Exclusive open; Notes and Custom are input-only. Raises PortBusy, PortNoPermission or PortGone."""
        ...


# --- other MIDI ports (ALSA sequencer) ------------------------------------------------------------------
@runtime_checkable
class TargetPorts(Protocol):
    def send(self, port: str, message: MidiMessage) -> SendResult: ...
    def subscribe_presence(self, callback: Callable[[str, bool], None]) -> None: ...


@runtime_checkable
class FeedbackInputs(Protocol):
    def listen(self, port: str, callback: Callable[[MidiMessage], None]) -> Cancellable: ...


@runtime_checkable
class PortCatalog(Protocol):
    def list(self) -> list[PortInfo]:
        """Every MIDI port by name, never including the APC64's own (contract a14)."""
        ...


# --- files and state ------------------------------------------------------------------------------------
@runtime_checkable
class LayoutSource(Protocol):
    def list(self) -> list[LayoutId]: ...
    def read(self, layout: LayoutId) -> tuple[str, ContentHash] | None: ...
    def write(self, layout: LayoutId, text: str) -> None: ...
    def changes(self, callback: Callable[[LayoutId, ChangeKind], None]) -> None: ...


@runtime_checkable
class VersionStore(Protocol):
    def save(self, layout: LayoutId, text: str, content_hash: ContentHash) -> VersionId: ...
    def list(self, layout: LayoutId) -> list[VersionId]: ...
    def read(self, layout: LayoutId, version: VersionId) -> str | None: ...


@runtime_checkable
class StateStore(Protocol):
    def marker_set(self) -> None: ...
    def marker_clear(self) -> None: ...
    def marker_present(self) -> bool: ...
    def calibration_get(self) -> Calibration | None: ...
    def calibration_put(self, calibration: Calibration | None) -> None: ...
    def nav_get(self) -> tuple[NavState, dict[tuple, Value14]] | None: ...
    def nav_put(self, nav: NavState, positions: dict[tuple, Value14]) -> None: ...


# --- the desktop and time -------------------------------------------------------------------------------
@runtime_checkable
class ConsentPrompt(Protocol):
    def ask(self, text: str) -> Awaitable[ConsentAnswer]: ...
    def withdraw(self) -> None: ...


@runtime_checkable
class Clock(Protocol):
    def monotonic(self) -> float: ...
    def call_later(self, seconds: float, callback: Callable[[], None]) -> Cancellable: ...


# --- extension (contract 2) -----------------------------------------------------------------------------
@runtime_checkable
class HostModule(Protocol):
    """A feature added without editing the core: commands it may send, API routes and a page panel.

    These three are all a module must have. The hooks below (HostModuleBase) are optional: collect() gives a
    module that lacks one the no-op default, so a contract 1-style module still registers (contract 2, T9)."""
    name: str

    def outbound_additions(self) -> frozenset[SysexCommand]: ...
    def router(self) -> Any | None: ...
    def panel(self) -> str | None: ...


class HostModuleBase:
    """Every HostModule hook with its default (contract 2 §7 ports, s2/s3). Subclass it and override what the
    module needs; a module may also implement the hooks without inheriting.

    Threading: every hook runs on the host's event loop. on_held, on_layout_loaded, on_pad_mode, led_filter and
    module actions run inside the engine's handling of an input, so they must not block; they may call the
    engine's ModuleDisplay/NoteEnder/LayoutLoader, whose effects are queued after the current input.
    on_release runs inside the session's release (after DAW off, before the connection detaches) and may block
    briefly: SysexTap callbacks arrive on the reader thread, so it can wait for a reply with a timeout."""
    name = "module"

    # what the module adds to the core
    def outbound_additions(self) -> frozenset[SysexCommand]:
        """Commands every caller may send once this module is registered (reads)."""
        return frozenset()

    def outbound_scoped(self) -> dict:
        """{SysexCommand: WriteCapability}: commands that pass the gate only with that token (writes, inv2)."""
        return {}

    def router(self) -> Any | None:
        return None

    def panel(self) -> str | None:
        """The module's static directory, served at /modules/<name>/; the page loads <name>.js from it."""
        return None

    def actions(self) -> dict:
        """{action name: handler(ControlEvent)} for ModuleAction(<name>, action) bindings (s2.c7)."""
        return {}

    def layout_sections(self) -> dict:
        """{top-level key: SectionCompiler}: layout sections this module compiles (s4)."""
        return {}

    def cli_commands(self) -> tuple:
        """The module's `apc64 <name> …` subcommands (mounted by the host CLI)."""
        return ()

    # the host's events
    def bind(self, host: "HostPorts") -> None:
        """Once, after the engine and session exist: the host ports the module may call."""

    def on_held(self, unit) -> None:
        """Once per take, with the engine's HeldUnit (its identity carries the firmware)."""

    def on_layout_loaded(self, layout, section) -> None:
        """From the engine's single load point, for every load path and hot reload; section is this module's
        compiled layout section, or None."""

    def on_pad_mode(self, view) -> None:
        """On every pad-mode report from the unit (UnitView)."""

    def on_release(self, reason) -> None:
        """Once per release (ReleaseReason), after DAW off and before the connection detaches (s3.c1)."""

    def led_filter(self, led):
        """A Led effect about to be drawn: return it (maybe changed) or None to suppress it (s2.c8)."""
        return led


@runtime_checkable
class ModuleDisplay(Protocol):
    """The OLED and banner a module may use (s2.c3, s2.c8)."""

    def set_resting_oled(self, text) -> None:
        """OledText shown whenever no host transient is on screen; None gives the host's idle text back."""
        ...

    def warn(self, text: str | None) -> None:
        """A warning on the page banner and (as a transient) the OLED; None clears the module's warnings."""
        ...


@runtime_checkable
class NoteEnder(Protocol):
    def end_notes(self, notes, role: UnitPortRole = UnitPortRole.CUSTOM) -> None:
        """A note-off per held note at its routing target, an 'ended by window shift' play event each, and the
        unit's next release of each note absorbed (s2.c9)."""
        ...


@runtime_checkable
class LayoutLoader(Protocol):
    def load(self, layout_id) -> Any:
        """EngineOk, or UnknownLayout(name, allowed) (s2.c5)."""
        ...


@runtime_checkable
class ViewRequester(Protocol):
    def request_view(self, view) -> bool:
        """Asks the unit for a pad mode (19 00 01 <m>); True when it was sent while held. The unit obeys and does
        not report it, so the host takes the view as reported at once (on_pad_mode follows); 2026-10-27."""
        ...


@runtime_checkable
class SectionTweaks(Protocol):
    def save_section_field(self, layout_id, path: str, value, base_hash=None, comment: str | None = None) -> Any:
        """Saved, or the issues that refused it (s38); `comment` replaces the line's comment when given."""
        ...


@runtime_checkable
class SysexTap(Protocol):
    """Complete SysEx replies from the held DAW port (s9)."""

    def subscribe(self, commands, callback: Callable[[bytes], None],
                  ended: Callable[[Any], None] | None = None) -> Cancellable:
        """callback(frame) for each complete frame of those commands, in arrival order, on the reader thread;
        ended(reason) when a holding ends (after on_release). Lasts until cancelled."""
        ...

    def held(self) -> Any:
        """The HeldUnit (with identity) while held, else None."""
        ...


@runtime_checkable
class TopicPublisher(Protocol):
    def publish(self, topic: str, payload: Any) -> None:
        """Send payload on the page socket's topic; the latest per topic and kind greets new connections."""
        ...


@dataclass(frozen=True)
class HostPorts:
    """What bind() hands a module: the host's ports, by role (each may be None in a test composition)."""
    display: ModuleDisplay | None = None
    notes: NoteEnder | None = None
    loader: LayoutLoader | None = None
    tweaks: SectionTweaks | None = None
    sysex: SysexTap | None = None
    gate: Any = None                  # OutboundGate.send(frames, issuer=None)
    stream: Any = None                # PlayStream (subscribe / publish)
    topics: TopicPublisher | None = None
    clock: Clock | None = None
    dispatch: Callable | None = None
    inputs: Any = None                # FeedbackInputs: any other MIDI input (§2.7 q7)
    views: ViewRequester | None = None   # the pad-mode request with the view assumed (2026-10-27)
