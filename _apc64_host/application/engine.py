"""HostEngine: the one ordered entry point for everything that changes the surface (contract §7.1, inv10, inv22).

Every input — unit bytes from the rawmidi reader threads, feedback MIDI, replica and API calls, timer ticks,
layout swaps, port presence — goes through one thread-safe FIFO and is handled one at a time by the pure
HostSurface / ExpressiveRouter. The effects they return are executed here:

- Send → TargetPorts; the activity entry is built from the send's result (sent, or not sent: <device>
  missing / send failed), aftertouch sends are folded into their note's entry (q7);
- Led / StripBar / Oled → encoded frames through the OutboundGate (dropped silently while not held);
  frames the gate refuses are listed as refused activity;
- Activity / Play → the activity log and the play stream, stamped with the wall-clock time;
- ScheduleAfter → a Clock timer that enqueues the Tick; RequestLayout → the library, then a swap.

Learn intercepts presses before the surface sees them (a captured touch runs no binding); calibration sees
every played note-on. The last nav and strip positions are persisted and restored when a layout is first
made live (q6). A fault while handling an input is logged and surfaces as the exception of run(), which
the DeviceSession supervises (s38.c3); the engine keeps serving the page either way.

Contract 2 (T14): registered modules (ModuleCollection) are served here. A ModuleAction binding (the base-layer
encoder or Tempo of a generated layout) calls the module's action with a ControlEvent; Shift + encoder stays the
layout browser and a Shift-layer press never reaches a module action. The single load point (_swap: page, API,
CLI, Shift + encoder browser, hot reload) calls on_layout_loaded; every pad-mode report calls on_pad_mode; each
take calls on_held; every Led effect passes led_filter. The engine is the modules' ModuleDisplay (resting OLED
text under host transients, warnings on the banner and OLED) and NoteEnder (end_notes). Calls a module makes from
inside a hook are queued behind the input being handled. Every play event is stamped with its PlaySource.

Threads: post() may be called from any thread; it enqueues and hands a drain to `dispatch` (the
composition root passes loop.call_soon_threadsafe). submit() is for callers on the loop: it enqueues and
drains at once, so API calls return the state after their input was handled (s16.c2).
"""
import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from ..domain.controls import ControlId, Encoder, EncoderPress
from ..domain.effects import (
    Activity, ActivityEntry, ActivityResult, CallModule, CatalogUpdate, EncoderTurn, FeedbackMessage, InputSource,
    LayoutSwap, Led, Oled, Origin, Play, PlayedMidi, PlayedNote, PlaySource, PlaySourceKind, Press, Redraw, Release,
    RequestLayout, ScheduleAfter, SelectBank, SelectPage, Send, SetPageShift, SetResting, ShowTransient, StripBar,
    StripMove, Tick, UnitView, ViewReport,
)
from ..domain.layout import (
    BankNo, DeviceName, Layout, LayoutId, NavState, PageLocation, PageNo, UnitPortRole,
)
from ..domain.issues import DomainInvariantError
from ..domain.leds import LedFrame
from ..domain.midi import ChannelPressure, PolyAftertouch
from ..domain.oled import OLED_WIDTH, OledText
from ..domain.outbound import HAZARD_TEXT
from ..domain.router import NOT_ROUTED, ExpressiveRouter
from ..domain.surface import HostSurface
from ..protocol import surface_map
from ..protocol.midi_codec import MidiDecoder
from ..protocol.stream import MidiStreamSplitter
from ..protocol.sysex import command_of, oled_frames
from .modules import ModuleCollection, collect
from .outbound_gate import GateResult
from .ports import (
    Cancellable, Clock, FeedbackInputs, PortCatalog, PortGone, SendResult, StateStore, TargetPorts, UnitConnection,
)

log = logging.getLogger(__name__)
POSITIONS_FLUSH = 1.0   # strip positions are written at most once a second
MODULE_WARNINGS = 5     # the newest module warnings kept for the banner
SESSION_SOURCE = PlaySource(PlaySourceKind.SESSION_BINDING)


# --- values the engine hands out ------------------------------------------------------------------------
@dataclass(frozen=True)
class HeldUnit:
    """The connections of one holding: DAW (read; written only through the gate), Notes and Custom (read)."""
    daw: UnitConnection
    notes: UnitConnection | None = None
    custom: UnitConnection | None = None
    identity: object | None = None     # protocol.sysex.Identity of this holding (contract 2: firmware for modules)


@dataclass(frozen=True)
class EngineOk:
    nav: NavState


@dataclass(frozen=True)
class UnknownLayout:
    layout: str
    allowed: tuple[str, ...]

    @property
    def problem(self) -> str:
        return f"no layout {self.layout}"


@dataclass(frozen=True)
class RoutingStatus:
    notes: str | None          # 'mpc ch 2' when the Notes port is routed
    custom: str | None
    text: str                  # NOT_ROUTED when the layout routes neither


@dataclass(frozen=True)
class EngineSnapshot:
    layout: Layout | None
    nav: NavState
    frame: LedFrame
    oled: OledText
    view: UnitView
    toggles: dict[ControlId, bool]
    missing: frozenset[DeviceName]
    routing: RoutingStatus
    played: tuple[PlayedNote, ...]
    held: bool
    positions: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()     # module warnings (contract 2 ModuleDisplay.warn), newest last


# --- queue items that are not domain inputs ---------------------------------------------------------------
@dataclass(frozen=True)
class _UnitBytes:
    generation: int
    role: UnitPortRole
    chunk: bytes


@dataclass(frozen=True)
class _Hold:
    unit: HeldUnit


@dataclass(frozen=True)
class _Presence:
    port: str
    present: bool


@dataclass(frozen=True)
class _LibraryChanged:
    pass


@dataclass(frozen=True)
class _UnitFrames:
    frames: tuple[bytes, ...]
    subject: str


@dataclass(frozen=True)
class _Warn:
    text: str | None


@dataclass(frozen=True)
class _EndNotes:
    notes: tuple[int, ...]
    role: UnitPortRole


def _direct(fn):
    fn()


class HostEngine:
    def __init__(self, *, gate, targets: TargetPorts, feedback: FeedbackInputs, activity, stream, library,
                 learn, calibration, clock: Clock, store: StateStore, catalog: PortCatalog | None = None,
                 dispatch: Callable[[Callable[[], None]], None] = _direct, wall: Callable[[], float] = time.time,
                 modules: ModuleCollection | None = None):
        self._gate, self._targets, self._feedback = gate, targets, feedback
        self._activity, self._stream, self._library = activity, stream, library
        self._learn, self._calibration = learn, calibration
        self._clock, self._store, self._catalog = clock, store, catalog
        self._dispatch, self._wall = dispatch, wall
        self._surface = HostSurface()
        self._router = ExpressiveRouter()
        self._inbox: queue.SimpleQueue = queue.SimpleQueue()
        self._lock = threading.RLock()
        self._held: HeldUnit | None = None
        self._generation = 0
        self._splitter = MidiStreamSplitter()
        self._decoders: dict[UnitPortRole, MidiDecoder] = {}
        self._captured: set[ControlId] = set()
        self._present: set[str] = {p.name for p in catalog.list()} if catalog is not None else set()
        self._missing: frozenset[DeviceName] = frozenset()
        self._listening: dict[str, Cancellable] = {}
        self._saved_nav: NavState | None = None
        self._saved_positions: dict = {}
        self._positions_timer: Cancellable | None = None
        self._restored = False
        self._started = False
        self._fault_future: asyncio.Future | None = None
        self._subscribers: list[Callable[[], None]] = []
        self._changed = False
        self._modules = modules if modules is not None else collect([])
        self._hooks = self._modules.hooks
        self._warnings: list[str] = []
        self._drain_thread: int | None = None
        targets.subscribe_presence(lambda port, present: self.post(_Presence(port, present)))
        library.subscribe(lambda: self.post(_LibraryChanged()))

    # === inputs ==========================================================================================
    def post(self, item) -> None:
        """From any thread: enqueue, and let the loop drain."""
        self._inbox.put(item)
        self._dispatch(self._drain)

    def submit(self, item) -> None:
        """On the loop: enqueue and handle now (after anything queued before it)."""
        self._inbox.put(item)
        self._drain()

    # the API's side (s16) ----------------------------------------------------------------------------
    def load(self, layout_id) -> EngineOk | UnknownLayout:
        try:
            layout = self._library.compiled(LayoutId(layout_id))
        except DomainInvariantError:
            layout = None
        if layout is None:
            return UnknownLayout(str(layout_id), tuple(self._library.catalog().ids))
        self.submit(LayoutSwap(layout))
        return EngineOk(self.nav)

    def select_page(self, page) -> EngineOk:
        self.submit(SelectPage(PageNo(page), InputSource.REPLICA))
        return EngineOk(self.nav)

    def select_bank(self, bank) -> EngineOk:
        self.submit(SelectBank(BankNo(bank), InputSource.REPLICA))
        return EngineOk(self.nav)

    def set_page_shift(self, held: bool) -> EngineOk:
        self.submit(SetPageShift(bool(held)))
        return EngineOk(self.nav)

    def replica_input(self, event) -> EngineOk:
        """A click or drag in the replica: the same path as the unit's own input (a19, d49)."""
        if not isinstance(event, (Press, Release, StripMove, EncoderTurn)):
            raise TypeError(f"not replica input: {event!r}")
        self.submit(replace(event, source=InputSource.REPLICA))
        return EngineOk(self.nav)

    def send_to_unit(self, frames, subject: str = "host") -> None:
        """Frames from any other part of the host (modules) go through the same gate and are listed."""
        self.submit(_UnitFrames(tuple(bytes(f) for f in frames), subject))

    # the modules' side (contract 2: ModuleDisplay, NoteEnder; LayoutLoader is load() above) ------------
    def set_resting_oled(self, text: OledText | None) -> None:
        """The OLED shows `text` whenever no host transient (a name, the browser) is on screen (s2.c8)."""
        if text is not None and not isinstance(text, OledText):
            raise TypeError(f"resting OLED text must be OledText, not {text!r}")
        self._module_post(SetResting(text))

    def warn(self, text: str | None) -> None:
        """A warning on the page banner and, for about 2 s, the OLED; None clears the module warnings."""
        self._module_post(_Warn(None if text is None else str(text)))

    def end_notes(self, notes, role: UnitPortRole = UnitPortRole.CUSTOM) -> None:
        """One note-off per held note at its target, a NOTE_ENDED play event each, later releases absorbed."""
        self._module_post(_EndNotes(tuple(int(n) for n in notes), UnitPortRole(role)))

    def _module_post(self, item) -> None:
        """From inside the engine's own handling (a hook or module action): queued behind the current input;
        from anywhere else: as post()."""
        if self._drain_thread == threading.get_ident():
            self._inbox.put(item)
        else:
            self.post(item)

    def start(self) -> None:
        """After the layouts were first loaded: make the remembered layout (else the first by name) live."""
        self._started = True
        self.submit(_LibraryChanged())

    # the pipeline's side (s61) -------------------------------------------------------------------------
    def swap(self, layout_id, layout: Layout) -> bool:
        """The active layout's content changed: make the new compile live (toggles kept where unchanged)."""
        current = self._surface.layout
        if current is None or current.id != LayoutId(layout_id):
            return False
        self.submit(LayoutSwap(layout))
        return True

    # the session's side (s38) --------------------------------------------------------------------------
    def on_held(self, unit: HeldUnit) -> None:
        self.submit(_Hold(unit))

    def on_released(self) -> list[bytes]:
        """Stops LED output and gives the frames that clear the surface (LEDs dark, OLED blank)."""
        with self._lock:
            self._held = None
            self._generation += 1
            self._flush_positions()
        self._mark_changed()
        self._notify()
        return surface_map.clear_frames()

    async def run(self) -> None:
        """Runs until a fault: an unhandled error while handling input is raised here (s38.c3)."""
        future = asyncio.get_running_loop().create_future()
        self._fault_future = future
        try:
            await future
        finally:
            if self._fault_future is future:
                self._fault_future = None

    # === readers =========================================================================================
    @property
    def nav(self) -> NavState:
        return self._surface.nav

    @property
    def layout(self) -> Layout | None:
        return self._surface.layout

    @property
    def held(self) -> bool:
        return self._held is not None

    def context(self) -> tuple[Layout | None, NavState]:
        return self._surface.layout, self._surface.nav

    def snapshot(self) -> EngineSnapshot:
        with self._lock:
            surface, layout, nav = self._surface, self._surface.layout, self._surface.nav
            toggles = {}
            page = layout.page(nav.page) if layout else None
            if page is not None:
                for control, binding in page.layers[nav.layer].items():
                    if binding.toggle:
                        toggles[control] = surface.toggled(PageLocation(nav.page, nav.layer, control))
            return EngineSnapshot(layout, nav, surface.frame(), surface.oled(), surface.view, toggles,
                                  self._missing, self._routing(), self._router.sounding(), self.held,
                                  surface.strip_positions(), tuple(self._warnings))

    def subscribe(self, callback: Callable[[], None]) -> None:
        """callback() after every batch of inputs that may have changed the snapshot."""
        self._subscribers.append(callback)

    def _routing(self) -> RoutingStatus:
        layout = self._surface.layout
        rules = layout.routing if layout else {}

        def text(role):
            rule = rules.get(role)
            return f"{rule.device} ch {rule.channel}" if rule else None
        notes, custom = text(UnitPortRole.NOTES), text(UnitPortRole.CUSTOM)
        return RoutingStatus(notes, custom, "" if (notes or custom) else NOT_ROUTED)

    # === the queue =======================================================================================
    def _drain(self) -> None:
        with self._lock:
            outer, self._drain_thread = self._drain_thread, threading.get_ident()
            try:
                while True:
                    try:
                        item = self._inbox.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        self._process(item)
                    except Exception as error:   # a fault: logged, surfaced to the supervisor, next input goes on
                        self._fault(error)
            finally:
                self._drain_thread = outer
            self._persist()
        self._notify()

    def _fault(self, error: Exception) -> None:
        log.exception("engine fault while handling input", exc_info=error)
        future = self._fault_future
        if future is not None and not future.done():
            future.get_loop().call_soon_threadsafe(_set_exception, future, error)

    def _notify(self) -> None:
        if not self._changed:
            return
        self._changed = False
        for callback in list(self._subscribers):
            callback()

    def _mark_changed(self) -> None:
        self._changed = True

    def _process(self, item) -> None:
        self._mark_changed()
        match item:
            case _UnitBytes():
                self._unit_bytes(item)
            case Press() | Release() | StripMove() | EncoderTurn():
                self._surface_input(item)
            case PlayedMidi():
                self._played(item)
            case LayoutSwap():
                self._swap(item)
            case _Hold(unit=unit):
                self._hold(unit)
            case _Presence(port=port, present=present):
                (self._present.add if present else self._present.discard)(port)
                self._refresh_missing()
            case _LibraryChanged():
                self._run(self._surface.handle(CatalogUpdate(self._library.catalog())))
                if self._started:
                    self._ensure_layout()
            case _UnitFrames(frames=frames, subject=subject):
                self._to_unit(list(frames), subject)
            case ViewReport():
                self._view_report(item)
            case _Warn(text=text):
                self._warn(text)
            case _EndNotes(notes=notes, role=role):
                self._run(self._router.end_notes(notes, role, self._surface.view), PlaySource.of_role(role))
            case SelectPage() | SelectBank() | SetPageShift() | FeedbackMessage() | Tick() \
                    | Redraw() | CatalogUpdate() | SetResting() | ShowTransient():
                self._run(self._surface.handle(item))
            case _:
                raise TypeError(f"the engine cannot handle {item!r}")

    # --- unit input --------------------------------------------------------------------------------------
    def _listener(self, generation: int, role: UnitPortRole):
        def on_bytes(chunk: bytes) -> None:   # a reader thread: hop onto the queue
            self.post(_UnitBytes(generation, role, bytes(chunk)))

        def on_gone() -> None:                # the session releases; nothing more comes from this role
            log.info("engine: %s connection gone", role)
        return on_bytes, on_gone

    def _unit_bytes(self, item: _UnitBytes) -> None:
        if item.generation != self._generation or self._held is None:
            return   # bytes from a holding that has ended
        if item.role is UnitPortRole.DAW:
            for message in self._splitter.feed(item.chunk):
                event = surface_map.decode(message)
                if event is None:
                    log.debug("engine: skipped DAW message %s", message.hex(" "))
                    continue
                if isinstance(event, ViewReport):
                    self._view_report(event)
                else:
                    self._surface_input(event)
        else:
            for message in self._decoders[item.role].feed(item.chunk):
                self._played(PlayedMidi(item.role, message))

    def _surface_input(self, event) -> None:
        control = _control_of(event)
        browsing = self._surface.nav.shift and isinstance(control, (Encoder, EncoderPress))
        if isinstance(event, Release):
            if control in self._captured:
                self._captured.discard(control)
                return
        elif control is not None and not browsing and self._learn.intercept(control) == "captured":
            if isinstance(event, Press):
                self._captured.add(control)
            return
        self._run(self._surface.handle(event), SESSION_SOURCE)

    def _played(self, played: PlayedMidi) -> None:
        self._calibration.observe(played, self._surface.view)
        self._run(self._router.handle(played, self._surface.view), PlaySource.of_role(played.role))

    def _view_report(self, report: ViewReport) -> None:
        self._run(self._surface.handle(report), SESSION_SOURCE)
        self._hooks.on_pad_mode(report.view)

    def _warn(self, text: str | None) -> None:
        if text is None:
            self._warnings.clear()
            return
        if text in self._warnings:
            self._warnings.remove(text)
        self._warnings.append(text)
        del self._warnings[:-MODULE_WARNINGS]
        self._run(self._surface.handle(ShowTransient(OledText(*_oled_rows(text)))))

    # --- lifecycle ---------------------------------------------------------------------------------------
    def _hold(self, unit: HeldUnit) -> None:
        self._held = unit
        self._started = True
        self._generation += 1
        self._splitter = MidiStreamSplitter()
        self._decoders = {UnitPortRole.NOTES: MidiDecoder(), UnitPortRole.CUSTOM: MidiDecoder()}
        for role, connection in ((UnitPortRole.DAW, unit.daw), (UnitPortRole.NOTES, unit.notes),
                                 (UnitPortRole.CUSTOM, unit.custom)):
            if connection is not None:
                connection.listen(*self._listener(self._generation, role))
        self._surface.view = UnitView.SESSION   # the handshake asked for Session view (19 00 01 00)
        if not self._ensure_layout():
            self._run(self._surface.handle(Redraw()))
        self._hooks.on_held(unit)

    def _ensure_layout(self) -> bool:
        """With no layout live, make the remembered one (else the first by name) live; True if it did."""
        if self._surface.layout is not None:
            return False
        catalog = self._library.catalog()
        saved = self._store.nav_get() if not self._restored else None
        if saved is not None:
            self._surface.restore_positions(saved[1])
        if not catalog.ids:
            return False
        self._restored = True
        target, page, bank = catalog.ids[0], None, None
        if saved is not None and saved[0].layout in catalog.ids:
            target, page, bank = saved[0].layout, saved[0].page, saved[0].bank
        self._swap(LayoutSwap(self._library.compiled(target), page, bank))
        return True

    def _swap(self, swap: LayoutSwap) -> None:
        """The single load point: every path that makes a layout live comes through here (s2.c6)."""
        effects = self._surface.handle(swap)
        self._router.set_layout(swap.layout)
        self._listen_feedback(swap.layout)
        self._refresh_missing()
        self._run(effects)
        self._hooks.on_layout_loaded(swap.layout)

    def _listen_feedback(self, layout: Layout | None) -> None:
        wanted = set()
        if layout is not None:
            for (device, _, _) in layout.feedback_index().entries:
                wanted.add(str(layout.devices[device].pattern))
        for pattern in [p for p in self._listening if p not in wanted]:
            self._listening.pop(pattern).cancel()
        for pattern in sorted(wanted - set(self._listening)):
            self._listening[pattern] = self._feedback.listen(
                pattern, lambda message, port=pattern: self.post(FeedbackMessage(port, message)))

    def _refresh_missing(self) -> None:
        layout = self._surface.layout
        if layout is None or self._catalog is None and not self._present:
            return
        self._missing = frozenset(name for name, device in layout.devices.items()
                                  if not any(device.pattern.matches(port) for port in self._present))

    # --- effects -----------------------------------------------------------------------------------------
    def _run(self, effects, source: PlaySource | None = None) -> None:
        frames: list[bytes] = []
        unsent: list[str] = []
        for effect in effects:
            match effect:
                case Send():
                    reason = self._send(effect)
                    if reason:
                        unsent.append(reason)
                case Led():
                    led = self._hooks.led_filter(effect) if self._hooks else effect
                    if led is not None:
                        frames.append(surface_map.encode_led(led.control, led.state))
                case CallModule():
                    self._call_module(effect)
                case StripBar(strip=strip, state=state):
                    frames += surface_map.encode_bar(strip, state)
                case Oled(text=text):
                    frames += oled_frames(text)
                case Activity(entry=entry):
                    self._activity.append(replace(entry, at=self._wall()))
                case Play(event=event):
                    if unsent and event.sent and event.reason is None:
                        event = replace(event, reason="not sent: " + ", ".join(dict.fromkeys(unsent)))
                    if event.port is None and source is not None:
                        event = replace(event, port=source)
                    self._stream.publish(replace(event, at=self._wall()))
                case ScheduleAfter(seconds=seconds, tick=tick):
                    self._clock.call_later(seconds, lambda tick=tick: self.post(tick))
                case RequestLayout(layout=layout_id):
                    layout = self._library.compiled(layout_id)
                    if layout is not None:
                        self._swap(LayoutSwap(layout))
        if frames:
            self._to_unit(frames, "surface")

    def _call_module(self, call: CallModule) -> None:
        """A ModuleAction binding fired: the module's handler gets the ControlEvent; the activity list shows it."""
        subject = str(call.control) if call.control is not None else str(call.action)
        event = call.event
        what = f"{call.action} " + ("press" if event.press else f"{event.steps:+d}")
        handler = self._modules.action(call.action)
        if handler is None:
            self._activity.append(ActivityEntry(subject, ActivityResult.NOT_SENT, what, call.action.module,
                                                "no such module action", at=self._wall()))
            return
        try:
            handler(event)
        except Exception:   # a module's bug never faults the engine (and so never releases the unit)
            log.exception("module action %s failed", call.action)
            self._activity.append(ActivityEntry(subject, ActivityResult.NOT_SENT, what, call.action.module,
                                                "module action failed", at=self._wall()))
            return
        self._activity.append(ActivityEntry(subject, ActivityResult.SENT, what, call.action.module, at=self._wall()))

    def _send(self, send: Send) -> str | None:
        """Sends to a target and lists the result; returns why it was not sent, or None."""
        result = self._targets.send(str(send.port), send.message)
        subject, origin = _subject(send.origin), send.origin
        description = send.message.describe()
        if result is SendResult.SENT:
            if send.device in self._missing:
                self._missing = self._missing - {send.device}
            entry = ActivityEntry(subject, ActivityResult.SENT, description, str(send.port), note=origin.note)
            reason = None
        elif result is SendResult.MISSING:
            self._missing = self._missing | {send.device}
            reason = f"{send.device} missing"
            entry = ActivityEntry(subject, ActivityResult.NOT_SENT, description, str(send.device), reason,
                                  note=origin.note)
        else:
            reason = f"{send.device} send failed"
            entry = ActivityEntry(subject, ActivityResult.NOT_SENT, description, str(send.port), reason,
                                  note=origin.note)
        if origin.kind == "aftertouch" and origin.note is not None:
            pressure = send.message.pressure if isinstance(send.message, (PolyAftertouch, ChannelPressure)) else 0
            self._activity.fold(origin.note, int(pressure))
        else:
            self._activity.append(replace(entry, at=self._wall()))
        return reason

    def _to_unit(self, frames: list[bytes], subject: str) -> None:
        try:
            results = self._gate.send(frames)
        except PortGone:
            log.info("engine: the unit went away while being drawn; the session releases it")
            return
        for frame, result in zip(frames, results):
            if result is GateResult.REFUSED:
                command = command_of(frame)
                self._activity.append(ActivityEntry(subject, ActivityResult.REFUSED,
                                                    HAZARD_TEXT.get(command, str(command)), "APC64",
                                                    at=self._wall()))

    # --- persistence (s53) -------------------------------------------------------------------------------
    def _persist(self) -> None:
        nav = self._surface.nav
        if nav.layout is None:
            return
        nav = replace(nav, shift=False)
        if nav != self._saved_nav:
            self._flush_positions()
        elif self._positions_timer is None and self._surface.strip_positions() != self._saved_positions:
            self._positions_timer = self._clock.call_later(POSITIONS_FLUSH, lambda: self._dispatch(self._timed_flush))

    def _timed_flush(self) -> None:
        with self._lock:
            self._positions_timer = None
            self._flush_positions()

    def _flush_positions(self) -> None:
        nav = self._surface.nav
        if nav.layout is None:
            return
        nav = replace(nav, shift=False)
        positions = self._surface.strip_positions()
        if self._positions_timer is not None:
            self._positions_timer.cancel()
            self._positions_timer = None
        if nav == self._saved_nav and positions == self._saved_positions:
            return
        self._store.nav_put(nav, positions)
        self._saved_nav, self._saved_positions = nav, positions


def _oled_rows(text: str) -> tuple[str, str]:
    """A warning on the two 14-character rows, broken at a space where it can be."""
    text = " ".join(str(text).split())
    if len(text) <= OLED_WIDTH:
        return text, ""
    cut = text.rfind(" ", 0, OLED_WIDTH + 1)
    cut = cut if cut > 0 else OLED_WIDTH
    return text[:cut], text[cut:].strip()


def _set_exception(future: asyncio.Future, error: Exception) -> None:
    if not future.done():
        future.set_exception(error)


def _control_of(event) -> ControlId | None:
    match event:
        case Press(control=control) | Release(control=control):
            return control
        case StripMove(strip=strip):
            return strip
        case EncoderTurn():
            return Encoder()
    return None


def _subject(origin: Origin) -> str:
    if origin.control is not None:
        return str(origin.control)
    if origin.note is not None:
        return f"note {origin.note}"
    return f"{origin.role} {origin.kind}" if origin.role else origin.kind
