"""DeviceSession: who holds the APC64, and the only way in and out of DAW mode (contract §7.1, inv12–inv17).

The session watches presence (UnitLocator, by port name) and the DAW port's holder (HolderLookup, never a
probe-open). When the unit appears it asks — the page banner (the status) and a desktop notification —
and takes nothing until a yes from the banner, the notification, a LAN browser or an agent, or with
auto-accept configured. A yes opens the DAW subdevice exclusively; Busy, No permission or a vanished port
end the attempt with nothing sent. On the open DAW port it sends the handshake (1B, 19, identity request)
and waits up to 2 s for an identity reply; only product 0x53 continues (unknown firmware is a warning).
Then the Notes and Custom subdevices are opened read-only (a busy one only turns expressive routing off),
the holding marker is set, DAW mode is switched on and the engine takes over.

release() is the one exit, for every reason (Release, stop/SIGTERM, unplug, engine fault): the engine's
clear frames (LEDs dark, OLED blank), then DAW mode off, then the gate is detached, every subdevice is
closed and the marker cleared — each exactly once. After an unplug nothing can be sent. Replug, a freed
port or a release make the host ask again (inv16).

Contract 2 (T15): registered modules' on_release(reason) runs once per release, after the DAW-off frame and
before the gate detaches, for every reason (Release, stop and SIGTERM — both ReleaseReason.STOP through the
lifespan —, unplug, engine fault); a hook that raises is logged and the exit goes on. The session is the
modules' SysexTap: subscribe(commands, callback, ended) gets each complete reply frame of those commands from
the DAW port on the reader thread, reassembled even when channel messages arrive between its pieces; those
frames are not passed to the engine. ended(reason) follows each release. held() gives the engine's HeldUnit
(with the identity) while held. With no subscriber the DAW bytes reach the engine exactly as contract 1 built it.

Connections are wrapped in taps: the session reads the DAW connection first (the identity reply), then
hands every connection to the engine, which listens through the same UnitConnection interface. Reader
threads reach the session through `dispatch` (the composition root passes loop.call_soon_threadsafe).
"""
import asyncio
import logging
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from ..domain.layout import UnitPortRole
from ..domain.unit_status import (
    Absent, Asking, Busy, Consent, ConsentSource, Decline, Held, HolderChanged, MaybeStuck, Opened,
    OpenFailed, OpenFailure, Presence, Released, ReleaseReason, StaleMarker, UnitPresence, UnitStatus,
    transition, Holder,
)
from ..protocol import sysex
from ..domain.outbound import SysexCommand
from ..protocol.stream import MidiStreamSplitter
from .engine import HeldUnit
from .modules import ModuleHooks
from .ports import (
    Cancellable, Clock, ConsentAnswer, ConsentPrompt, HolderLookup, PortBusy, PortGone, PortNoPermission,
    StateStore, UnitConnection, UnitLocator, UnitPort,
)
from .outbound_gate import GateResult

log = logging.getLogger(__name__)
ASK_TEXT = "Take control of APC64?"
IDENTITY_TIMEOUT = 2.0
HOLDER_RECHECK = 1.0
NO_REPLY = "No APC64 identity reply"


class TakeResult(StrEnum):
    TAKEN = "taken"
    ALREADY_HELD = "already_held"
    BUSY = "busy"
    NO_PERMISSION = "no_permission"
    NOT_AN_APC64 = "not_an_apc64"
    NOT_CONNECTED = "not_connected"


@dataclass(frozen=True)
class TakeAnswer:
    result: TakeResult
    by: ConsentSource | None = None
    holder: Holder | None = None
    detail: str | None = None

    @property
    def text(self) -> str:
        return {TakeResult.TAKEN: "Held", TakeResult.ALREADY_HELD: "already held",
                TakeResult.BUSY: Busy(holder=self.holder).text, TakeResult.NO_PERMISSION: "No permission to open APC64",
                TakeResult.NOT_AN_APC64: self.detail or "not an APC64",
                TakeResult.NOT_CONNECTED: "APC64 not connected"}[self.result]


class ReleaseResult(StrEnum):
    RELEASED = "released"
    NOT_HELD = "not_held"

    @property
    def text(self) -> str:
        return "Not held" if self is ReleaseResult.RELEASED else "APC64 is not held"


def _direct(fn):
    fn()


class _SysexSubscription:
    def __init__(self, router: "_SysexRouter", commands, callback, ended):
        self.commands = frozenset(SysexCommand(c) for c in commands)
        self.callback, self.ended, self._router = callback, ended, router
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True
        self._router.remove(self)


class _SysexRouter:
    """The SysexTap's side of the DAW tap: picks the subscribed reply frames out of the byte stream."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscriptions: list[_SysexSubscription] = []
        self._splitter = MidiStreamSplitter(channel_in_sysex=True)

    @property
    def active(self) -> bool:
        return bool(self._subscriptions)

    def add(self, subscription: _SysexSubscription) -> None:
        with self._lock:
            if not self._subscriptions:
                self._splitter = MidiStreamSplitter(channel_in_sysex=True)
            self._subscriptions.append(subscription)

    def remove(self, subscription: _SysexSubscription) -> None:
        with self._lock:
            if subscription in self._subscriptions:
                self._subscriptions.remove(subscription)

    def feed(self, chunk: bytes) -> bytes:
        """Delivers subscribed frames; gives back the bytes of every other message, for the engine."""
        deliveries, passed = [], []
        with self._lock:
            subscriptions = list(self._subscriptions)
            for message in self._splitter.feed(chunk):
                wanted = [s for s in subscriptions if message[0] == 0xF0 and sysex.command_of(message) in s.commands]
                if wanted:
                    deliveries.append((message, wanted))
                else:
                    passed.append(message)
        for message, wanted in deliveries:
            for subscription in wanted:
                if subscription.cancelled:
                    continue
                try:
                    subscription.callback(message)
                except Exception:
                    log.exception("session: a SysEx tap subscriber failed")
        return b"".join(passed)

    def ended(self, reason) -> None:
        with self._lock:
            subscriptions = list(self._subscriptions)
            self._splitter = MidiStreamSplitter(channel_in_sysex=True)
        for subscription in subscriptions:
            if subscription.ended is not None and not subscription.cancelled:
                try:
                    subscription.ended(reason)
                except Exception:
                    log.exception("session: a SysEx tap subscriber's ended() failed")


class _Tap:
    """One held subdevice as the session and then the engine see it (UnitConnection without write)."""

    def __init__(self, raw: UnitConnection, role: UnitPortRole, on_gone: Callable[[UnitPortRole], None],
                 sysex_router: _SysexRouter | None = None):
        self.raw, self.role = raw, role
        self._on_gone = on_gone
        self._sysex = sysex_router
        self._lock = threading.Lock()
        self._probe: Callable[[bytes], None] | None = None
        self._sink: tuple[Callable[[bytes], None], Callable[[], None]] | None = None
        self._backlog: list[bytes] = []
        self._gone = False
        self._closed = False

    def start(self, probe: Callable[[bytes], None] | None = None) -> None:
        self._probe = probe
        self.raw.listen(self._bytes, self._lost)

    def stop_probing(self) -> None:
        with self._lock:
            self._probe = None

    # UnitConnection for the engine
    def listen(self, on_bytes: Callable[[bytes], None], on_gone: Callable[[], None]) -> None:
        with self._lock:
            self._sink = (on_bytes, on_gone)
            backlog, self._backlog = self._backlog, []
            gone = self._gone
        for chunk in backlog:
            on_bytes(chunk)
        if gone:
            on_gone()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.raw.close()
        except Exception:
            log.exception("session: closing %s failed", self.role)

    # the reader thread's side
    def _bytes(self, chunk: bytes) -> None:
        with self._lock:
            if self._closed:
                return
            probe, sink = self._probe, self._sink
            if probe is None and sink is None:
                self._backlog.append(bytes(chunk))
                return
        if probe is not None:
            probe(bytes(chunk))
            return
        chunk = bytes(chunk)
        if self._sysex is not None and self._sysex.active:
            chunk = self._sysex.feed(chunk)
            if not chunk:
                return
        if sink is not None:
            sink[0](chunk)
        else:
            with self._lock:
                self._backlog.append(chunk)

    def _lost(self) -> None:
        with self._lock:
            if self._closed or self._gone:
                return
            self._gone = True
            sink = self._sink
        if sink is not None:
            sink[1]()
        self._on_gone(self.role)


class DeviceSession:
    def __init__(self, *, locator: UnitLocator, holders: HolderLookup, port: UnitPort, prompt: ConsentPrompt,
                 store: StateStore, gate, engine, clock: Clock, auto_accept: bool = False,
                 dispatch: Callable[[Callable[[], None]], None] = _direct,
                 identity_timeout: float = IDENTITY_TIMEOUT, modules: ModuleHooks | None = None):
        self._locator, self._holders, self._port, self._prompt = locator, holders, port, prompt
        self._store, self._gate, self._engine, self._clock = store, gate, engine, clock
        self._auto_accept, self._dispatch, self._identity_timeout = auto_accept, dispatch, identity_timeout
        self._status: UnitStatus = Absent()
        self._presence: UnitPresence | None = None
        self._identity: sysex.Identity | None = None
        self._taps: dict[UnitPortRole, _Tap] = {}
        self._daw_on = False
        self._generation = 0
        self._identity_wait: asyncio.Future | None = None
        self._take_task: asyncio.Task | None = None
        self._ask_task: asyncio.Task | None = None
        self._run_task: asyncio.Task | None = None
        self._holder_timer: Cancellable | None = None
        self._releasing = False
        self._stopped = False
        self._subscribers: list[Callable[[UnitStatus], None]] = []
        self._modules = modules if modules is not None else ModuleHooks()
        self._sysex_router = _SysexRouter()
        self._held_unit: HeldUnit | None = None

    # === the modules' SysexTap (contract 2, s9) ===============================================================
    def subscribe_sysex(self, commands, callback: Callable[[bytes], None],
                        ended: Callable[[ReleaseReason], None] | None = None) -> _SysexSubscription:
        subscription = _SysexSubscription(self._sysex_router, commands, callback, ended)
        self._sysex_router.add(subscription)
        return subscription

    def held_unit(self) -> HeldUnit | None:
        return self._held_unit if self.held else None

    @property
    def sysex_tap(self) -> "SessionSysexTap":
        """The SysexTap port (subscribe / held) a module is bound to."""
        return SessionSysexTap(self)

    # === readers =========================================================================================
    def status(self) -> UnitStatus:
        return self._status

    @property
    def identity(self) -> sysex.Identity | None:
        return self._identity

    @property
    def firmware(self) -> str | None:
        return str(self._identity.firmware) if self._identity else None

    @property
    def held(self) -> bool:
        return isinstance(self._status, Held)

    def subscribe(self, callback: Callable[[UnitStatus], None]) -> None:
        self._subscribers.append(callback)

    # === start ===========================================================================================
    def start(self) -> None:
        """At service start: look once, then follow presence and holder changes. Sends nothing (d6)."""
        self._locator.subscribe(self._presence_changed)
        self._holders.subscribe(self._holder_changed)
        presence = self._locator.find()
        if presence is None:
            if self._store.marker_present():   # the unit is gone, so its DAW mode is gone too (d9)
                self._store.marker_clear()
            self._observe(Presence(False))
            return
        self._presence = presence
        self._observe(Presence(True, presence.ignored))
        if self._store.marker_present():
            self._observe(StaleMarker())
        holder = self._holders.holder_of(UnitPortRole.DAW)
        if holder is not None:
            self._observe(HolderChanged(holder))
        self._offer()

    # === consent =========================================================================================
    async def take(self, source: ConsentSource) -> TakeAnswer:
        """A yes from somewhere. The first yes takes the unit; a second one is answered 'already held' (d17)."""
        source = ConsentSource(source)
        if self._take_task is not None and not self._take_task.done():
            answer = await asyncio.shield(self._take_task)
            return TakeAnswer(TakeResult.ALREADY_HELD, self._by()) if answer.result is TakeResult.TAKEN else answer
        if self.held:
            return TakeAnswer(TakeResult.ALREADY_HELD, self._by())
        self._take_task = asyncio.ensure_future(self._take(source))
        return await asyncio.shield(self._take_task)

    def decline(self) -> str:
        self._prompt.withdraw()
        self._cancel_ask()
        self._observe(Decline())
        return "ok"

    async def _take(self, source: ConsentSource) -> TakeAnswer:
        self._observe(Consent(source))
        presence = self._presence or self._locator.find()
        if presence is None:
            self._observe(Presence(False))
            return TakeAnswer(TakeResult.NOT_CONNECTED)
        self._presence = presence
        self._prompt.withdraw()   # a yes from anywhere answers the desktop question too
        self._cancel_ask()
        try:
            raw = self._port.open(UnitPortRole.DAW, presence.daw)
        except PortBusy as busy:
            holder = busy.holder or self._holders.holder_of(UnitPortRole.DAW)
            self._observe(OpenFailed(OpenFailure.BUSY, holder))
            return TakeAnswer(TakeResult.BUSY, holder=holder)
        except PortNoPermission:
            self._observe(OpenFailed(OpenFailure.NO_PERMISSION))
            return TakeAnswer(TakeResult.NO_PERMISSION)
        except PortGone:
            self._observe(OpenFailed(OpenFailure.GONE))
            return TakeAnswer(TakeResult.NOT_CONNECTED)

        self._generation += 1
        generation = self._generation
        daw = _Tap(raw, UnitPortRole.DAW, lambda role, g=generation: self._dispatch(lambda: self._gone(role, g)),
                   self._sysex_router)
        self._taps = {UnitPortRole.DAW: daw}
        waiting = asyncio.get_running_loop().create_future()
        self._identity_wait = waiting
        daw.start(self._sniffer(generation))
        self._gate.attach(raw)
        timer = self._clock.call_later(self._identity_timeout,
                                       lambda: self._dispatch(lambda: _resolve(waiting, None)))
        try:
            self._gate.send(sysex.handshake_frames())
            identity = await waiting
        except PortGone:
            self._abandon(daw)
            self._observe(OpenFailed(OpenFailure.GONE))
            return TakeAnswer(TakeResult.NOT_CONNECTED)
        finally:
            timer.cancel()
            self._identity_wait = None
        if self._taps.get(UnitPortRole.DAW) is not daw:   # released (stop, unplug) during the handshake
            return TakeAnswer(TakeResult.NOT_CONNECTED)
        if identity is None or not identity.is_apc64:
            detail = NO_REPLY if identity is None else identity.refusal
            self._abandon(daw)
            failure = OpenFailure.NO_REPLY if identity is None else OpenFailure.NOT_AN_APC64
            self._observe(OpenFailed(failure, detail=detail))
            return TakeAnswer(TakeResult.NOT_AN_APC64, detail=detail)

        self._identity = identity
        notices = []
        notes = self._open_input(UnitPortRole.NOTES, presence.notes, generation, notices)
        custom = self._open_input(UnitPortRole.CUSTOM, presence.custom, generation, notices)
        self._store.marker_set()
        try:
            result = self._gate.send([sysex.daw_on()])
        except PortGone:
            self.release_now(ReleaseReason.UNPLUG)
            return TakeAnswer(TakeResult.NOT_CONNECTED)
        self._daw_on = result == [GateResult.SENT]
        daw.stop_probing()
        self._held_unit = HeldUnit(daw, notes, custom, identity=identity)
        self._engine.on_held(self._held_unit)
        self._observe(Opened(source, identity.firmware_warning, tuple(notices)))
        self._supervise()
        log.info("session: APC64 held (%s), firmware %s", source, identity.firmware)
        return TakeAnswer(TakeResult.TAKEN, source)

    def _sniffer(self, generation: int) -> Callable[[bytes], None]:
        splitter = MidiStreamSplitter()

        def probe(chunk: bytes) -> None:   # the DAW reader thread, until the identity reply
            for message in splitter.feed(chunk):
                identity = sysex.parse_identity(message)
                if identity is not None:
                    self._dispatch(lambda i=identity: self._identified(i, generation))
        return probe

    def _identified(self, identity: sysex.Identity, generation: int) -> None:
        if generation == self._generation and self._identity_wait is not None:
            _resolve(self._identity_wait, identity)

    def _open_input(self, role: UnitPortRole, address: str | None, generation: int, notices: list) -> _Tap | None:
        """Notes/Custom read-only; a failure only turns expressive routing for that port off (d26)."""
        word = role.value.capitalize()
        if address is None:
            notices.append(f"APC64 {word} port not found: expressive pads not routed")
            return None
        try:
            raw = self._port.open(role, address)
        except PortBusy:
            notices.append(f"APC64 {word} busy: expressive pads not routed")
            return None
        except (PortNoPermission, PortGone):
            notices.append(f"APC64 {word} could not be opened: expressive pads not routed")
            return None
        tap = _Tap(raw, role, lambda r, g=generation: self._dispatch(lambda: self._gone(r, g)))
        tap.start()
        self._taps[role] = tap
        return tap

    def _abandon(self, daw: _Tap) -> None:
        """An attempt that never reached DAW mode: nothing to switch off, just let go."""
        self._gate.detach()
        daw.close()
        if self._taps.get(UnitPortRole.DAW) is daw:
            self._taps = {}

    # === release =========================================================================================
    async def release(self, reason=ReleaseReason.RELEASE) -> ReleaseResult:
        return self.release_now(reason)

    def release_now(self, reason=ReleaseReason.RELEASE) -> ReleaseResult:
        """The single exit: clear → DAW off → detach → close → marker cleared, once (inv14, d35)."""
        reason = ReleaseReason(reason)
        if self._releasing or UnitPortRole.DAW not in self._taps:
            return ReleaseResult.NOT_HELD
        self._releasing = True
        try:
            if self._identity_wait is not None:   # a handshake in flight ends now
                _resolve(self._identity_wait, None)
            self._stop_supervising()
            taps, self._taps = self._taps, {}
            raw = taps[UnitPortRole.DAW].raw
            frames = self._engine.on_released() if self._daw_on else []
            switched_off = not self._daw_on
            if self._daw_on:   # after a lost connection only DAW off is tried: it fails at once if the unit is gone
                switched_off = self._switch_off(raw, [] if reason is ReleaseReason.UNPLUG else frames)
            if self._held_unit is not None:   # contract 2: after DAW off, before detach (s3.c1); guarded (s3.c2)
                self._modules.on_release(reason)   # held() still answers inside the hook
                self._held_unit = None
            self._gate.detach()
            for tap in taps.values():
                tap.close()
            self._sysex_router.ended(reason)
            if switched_off:   # otherwise the marker stays: the unit may still be in DAW mode (d6)
                self._store.marker_clear()
            self._daw_on = False
            self._observe(Released(reason))
            log.info("session: APC64 released (%s)", reason)
        finally:
            self._releasing = False
        return ReleaseResult.RELEASED

    def _switch_off(self, raw, frames) -> bool:
        """Clear frames, then DAW mode off; DAW off is tried even when clearing failed. True when it was sent."""
        try:
            if frames:
                self._gate.send(frames)
        except PortGone:
            log.warning("session: clearing the surface failed; still trying DAW mode off")
            self._gate.attach(raw)
        try:
            return self._gate.send([sysex.daw_off()]) == [GateResult.SENT]
        except PortGone:
            log.warning("session: DAW mode off could not be sent; the marker stays (may still be in DAW mode)")
            return False

    # --- supervision (s38) -------------------------------------------------------------------------------
    def _supervise(self) -> None:
        try:
            self._run_task = asyncio.ensure_future(self._engine.run())
        except RuntimeError:   # no running loop (a synchronous caller): nothing to supervise
            self._run_task = None
            return
        self._run_task.add_done_callback(self._engine_ended)

    def _engine_ended(self, task: asyncio.Task) -> None:
        if task.cancelled() or task is not self._run_task:
            return
        error = task.exception()
        log.error("session: the engine stopped (%r); releasing the unit", error)
        self.release_now(ReleaseReason.FAULT)

    def _stop_supervising(self) -> None:
        task, self._run_task = self._run_task, None
        if task is not None and not task.done():
            task.remove_done_callback(self._engine_ended)
            task.cancel()

    # === observations ====================================================================================
    def _gone(self, role: UnitPortRole, generation: int) -> None:
        """A held subdevice failed (unplug, suspend): the holding ends."""
        if generation != self._generation or role not in self._taps:
            return
        if role is UnitPortRole.DAW:
            self.release_now(ReleaseReason.UNPLUG)
        else:
            self._taps.pop(role).close()

    def _presence_changed(self, presence: UnitPresence | None) -> None:
        before = self._presence
        self._presence = presence
        if presence is None:
            self.release_now(ReleaseReason.UNPLUG)
            self._prompt.withdraw()
            self._cancel_ask()
            if self._store.marker_present():
                self._store.marker_clear()
            self._observe(Presence(False))
            return
        moved = before is not None and before.daw != presence.daw
        if moved:   # a replug on another card: a new appearance
            self.release_now(ReleaseReason.UNPLUG)
            self._observe(Presence(False))
        appeared = before is None or moved
        self._observe(Presence(True, presence.ignored))
        if appeared:
            holder = self._holders.holder_of(UnitPortRole.DAW)
            if holder is not None:
                self._observe(HolderChanged(holder))
            self._offer()

    def _holder_changed(self, role: UnitPortRole, holder: Holder | None) -> None:
        if UnitPortRole(role) is not UnitPortRole.DAW:
            return
        before = self._status
        self._observe(HolderChanged(holder))
        if isinstance(before, Busy) and isinstance(self._status, Asking):   # the port freed up: ask again
            self._offer()
        elif isinstance(self._status, Busy) and not isinstance(before, Busy):
            self._prompt.withdraw()
            self._cancel_ask()

    def _watch_holder(self) -> None:
        """While Busy with a named holder, re-check it every second in case a change event was missed (d27)."""
        if self._holder_timer is not None or self._stopped:
            return

        def check():
            self._holder_timer = None
            status = self._status
            if isinstance(status, Busy) and status.holder is not None:
                if self._holders.holder_of(UnitPortRole.DAW) is None:
                    self._holder_changed(UnitPortRole.DAW, None)
                else:
                    self._watch_holder()
        self._holder_timer = self._clock.call_later(HOLDER_RECHECK, lambda: self._dispatch(check))

    def _offer(self) -> None:
        """Asking (or maybe stuck): take automatically when configured, otherwise ask on the desktop too."""
        if self._auto_accept and isinstance(self._status, Asking):
            self._spawn(self.take(ConsentSource.AUTO_ACCEPT))
        elif isinstance(self._status, (Asking, MaybeStuck)):
            self._ask()

    def _ask(self) -> None:
        if self._ask_task is not None and not self._ask_task.done():
            return

        async def asking():
            answer = await self._prompt.ask(ASK_TEXT)
            if answer is ConsentAnswer.TAKE:
                await self.take(ConsentSource.NOTIFICATION)
        self._ask_task = self._spawn(asking())

    def _cancel_ask(self) -> None:
        task, self._ask_task = self._ask_task, None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    def _by(self) -> ConsentSource | None:
        return self._status.by if isinstance(self._status, Held) else None

    def _observe(self, observation) -> None:
        status = transition(self._status, observation)
        if status == self._status:
            return
        self._status = status
        if isinstance(status, Busy) and status.holder is not None:
            self._watch_holder()
        for callback in list(self._subscribers):
            callback(status)

    @staticmethod
    def _spawn(coro):
        try:
            return asyncio.ensure_future(coro)
        except RuntimeError:
            coro.close()
            log.warning("session: no event loop to run %s", getattr(coro, "__name__", coro))
            return None

    def stop(self) -> None:
        """Service stop: release (clear → DAW off → close) and stop watching."""
        self._stopped = True
        if self._holder_timer is not None:
            self._holder_timer.cancel()
            self._holder_timer = None
        self._prompt.withdraw()
        self._cancel_ask()
        self.release_now(ReleaseReason.STOP)


class SessionSysexTap:
    """SysexTap over the session (s9): subscribe(commands, callback, ended) and held()."""

    def __init__(self, session: DeviceSession):
        self._session = session

    def subscribe(self, commands, callback, ended=None):
        return self._session.subscribe_sysex(commands, callback, ended)

    def held(self):
        return self._session.held_unit()


def _resolve(future: asyncio.Future, value) -> None:
    if not future.done():
        future.set_result(value)
