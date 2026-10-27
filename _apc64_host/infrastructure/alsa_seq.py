"""TargetPorts, FeedbackInputs, PortCatalog and HolderLookup over one ALSA sequencer client (alsa-midi;
contract §7, s4/s25/s33/s45/s65/s82/s89, d59, d61, a14).

- Ports are named by their ALSA port name. A pattern (a device's PortPattern) resolves to the one port whose
  name equals it (any case) or, failing that, the one port whose name contains it; none or several → MISSING.
- The APC64's own ports (client or port name containing the stem) are never listed, sent to or connected:
  the host's exclusive rawmidi open is the only way it talks to the unit (a14, §2.5).
- Sends go to the resolved port from our 'apc64-host out' port (event_output + drain). The first send to a
  port connects our out port to it: a kernel (hardware) port opens its device only while connected, and a
  direct send to an unconnected one fails with ENODEV.
- Feedback: our 'apc64-host in' port is connected from each listened port; listeners follow their port by
  name when it vanishes and reappears (d61).
- System Announce (port start/exit, subscribe/unsubscribe) refreshes the port snapshot: presence changes are
  reported per port name, and subscribers of the APC64's ports are reported as that role's holder (s4.c4),
  so the session notices a freed port without ever probe-opening it (§7.1).

Callbacks are made through `dispatch` (default: on the calling or reader thread; the composition root passes
loop.call_soon_threadsafe).
"""
import errno
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from alsa_midi import (
    SYSTEM_ANNOUNCE, Address, ALSAError, ClientExitEvent, ClientStartEvent, MidiBytesEvent, PortCaps,
    PortChangeEvent, PortExitEvent, PortStartEvent, PortSubscribedEvent, PortType, PortUnsubscribedEvent,
    SequencerClient,
)

from ..application.ports import PortDirection, PortInfo, SendResult
from ..domain.layout import PortPattern, UnitPortRole
from ..domain.midi import MidiMessage
from ..domain.unit_status import Holder
from ..protocol.midi_codec import decode, encode

CLIENT_NAME = "apc64-host"
POLL_TIMEOUT = 0.2
_MISSING_ERRNOS = {errno.ENOENT, errno.ENXIO, errno.ENODEV}
_ANNOUNCE = (PortStartEvent, PortExitEvent, PortChangeEvent, PortSubscribedEvent, PortUnsubscribedEvent,
             ClientStartEvent, ClientExitEvent)
_ROLE_WORDS = {"daw": UnitPortRole.DAW, "notes": UnitPortRole.NOTES, "custom": UnitPortRole.CUSTOM}
_ROLE_BY_CABLE = {0: UnitPortRole.DAW, 1: UnitPortRole.NOTES, 3: UnitPortRole.CUSTOM}   # PROTOCOL-SPEC §1

log = logging.getLogger(__name__)


def _direct(fn, *args):
    fn(*args)


@dataclass(frozen=True)
class _Port:
    name: str
    address: Address
    can_send: bool        # we can write to it (a target)
    can_listen: bool      # we can read from it (feedback)


@dataclass
class _Snapshot:
    ports: list[_Port] = field(default_factory=list)          # every port but the APC64's and our own
    apc64: dict[UnitPortRole, Address] = field(default_factory=dict)


class _Listener:
    def __init__(self, owner: "AlsaSequencer", pattern: str, callback: Callable[[MidiMessage], None]):
        self.owner, self.pattern, self.callback = owner, pattern, callback
        self.address: Address | None = None
        self.cancelled = False

    def cancel(self) -> None:
        self.owner._cancel(self)


class AlsaSequencer:
    def __init__(self, stem: str = "APC64", client_factory: Callable | None = None, dispatch: Callable = _direct,
                 poll_timeout: float = POLL_TIMEOUT):
        self._stem = stem.casefold()
        self._factory = client_factory or (lambda: SequencerClient(CLIENT_NAME))
        self._dispatch = dispatch
        self._poll_timeout = poll_timeout
        self._lock = threading.RLock()
        self._client = None
        self._out = self._in = None
        self._in_port = None                           # kept alive: alsa-midi deletes a port when its object goes
        self._snapshot = _Snapshot()
        self._announced: set[str] = set()              # port names as last reported to presence subscribers
        self._holders: dict[UnitPortRole, Holder | None] = {}
        self._listeners: list[_Listener] = []
        self._connected: dict[Address, int] = {}       # listened port → listener count
        self._outgoing: set[Address] = set()           # ports our out port is connected to
        self._presence_subscribers: list[Callable[[str, bool], None]] = []
        self._holder_subscribers: list[Callable[[UnitPortRole, Holder | None], None]] = []
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    # --- lifecycle ----------------------------------------------------------------------------------------
    def open(self) -> bool:
        """Opens the client (once): two ports and a connection from System Announce. False if unavailable."""
        with self._lock:
            if self._client is not None:
                return True
            try:
                client = self._factory()
                out_port = client.create_port(f"{CLIENT_NAME} out", PortCaps.READ | PortCaps.SUBS_READ,
                                              PortType.MIDI_GENERIC | PortType.APPLICATION)
                in_port = client.create_port(f"{CLIENT_NAME} in", PortCaps.WRITE | PortCaps.SUBS_WRITE,
                                             PortType.MIDI_GENERIC | PortType.APPLICATION)
                client.subscribe_port(SYSTEM_ANNOUNCE, Address(in_port.client_id, in_port.port_id))
            except Exception as error:
                log.warning("sequencer unavailable (%s): no target or feedback ports", error)
                return False
            self._client, self._out, self._in = client, out_port, Address(in_port.client_id, in_port.port_id)
            self._in_port = in_port
            self._snapshot = self._scan()
            self._announced = {p.name for p in self._snapshot.ports}
            self._holders = {role: self._holder_now(role) for role in UnitPortRole}
            return True

    def start(self) -> None:
        if not self.open() or self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(target=self._read_loop, name="apc64-sequencer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    log.exception("sequencer: close failed")
            self._client = self._out = self._in = self._in_port = None
            self._outgoing.clear()

    # --- PortCatalog -------------------------------------------------------------------------------------
    def list(self) -> list[PortInfo]:
        """Present ports by name, each name once, never the APC64's (s25.c2)."""
        if not self.open():
            return []
        with self._lock:
            self._snapshot = self._scan()
            seen, listed = set(), []
            for port in self._snapshot.ports:
                if port.name in seen or not (port.can_send or port.can_listen):
                    continue
                seen.add(port.name)
                direction = (PortDirection.BOTH if port.can_send and port.can_listen
                             else PortDirection.OUTPUT if port.can_send else PortDirection.INPUT)
                listed.append(PortInfo(port.name, direction, True))
            return listed

    # --- TargetPorts ---------------------------------------------------------------------------------------
    def send(self, port: str, message: MidiMessage) -> SendResult:
        if not self.open():
            return SendResult.FAILED
        with self._lock:
            address = self._resolve(port, sending=True)
            if address is None:
                return SendResult.MISSING
            try:
                self._connect_output(address)
                self._client.event_output(MidiBytesEvent(encode(message)), port=self._out, dest=address)
                self._client.drain_output()
                return SendResult.SENT
            except ALSAError as error:
                self._drop_output()
                self._outgoing.discard(address)   # the next send connects afresh
                if -error.errnum in _MISSING_ERRNOS:
                    return SendResult.MISSING
                log.warning("sequencer: send to %s failed (%s)", port, error)
                return SendResult.FAILED
            except Exception:
                self._drop_output()
                log.exception("sequencer: send to %s failed", port)
                return SendResult.FAILED

    def subscribe_presence(self, callback: Callable[[str, bool], None]) -> None:
        self._presence_subscribers.append(callback)

    # --- FeedbackInputs ------------------------------------------------------------------------------------
    def listen(self, port: str, callback: Callable[[MidiMessage], None]) -> _Listener:
        listener = _Listener(self, port, callback)
        if not self.open():
            return listener
        with self._lock:
            self._listeners.append(listener)
            self._attach(listener, self._resolve(port, sending=False))
        return listener

    def _cancel(self, listener: _Listener) -> None:
        with self._lock:
            if listener.cancelled:
                return
            listener.cancelled = True
            if listener in self._listeners:
                self._listeners.remove(listener)
            self._attach(listener, None)

    # --- HolderLookup ---------------------------------------------------------------------------------------
    def holder_of(self, role: UnitPortRole) -> Holder | None:
        if not self.open():
            return None
        with self._lock:
            self._snapshot = self._scan()
            return self._holder_now(UnitPortRole(role))

    def subscribe(self, callback: Callable[[UnitPortRole, Holder | None], None]) -> None:
        self._holder_subscribers.append(callback)

    # --- events -----------------------------------------------------------------------------------------------
    def process_pending(self) -> None:
        """Handles every event waiting now (the reader thread does this continuously)."""
        while self._client is not None:
            event = self._client.event_input(prefer_bytes=True, timeout=0.001)
            if event is None:
                return
            self.handle_event(event)

    def handle_event(self, event) -> None:
        if isinstance(event, MidiBytesEvent):
            self._deliver(event)
        elif isinstance(event, _ANNOUNCE):
            self._refresh()

    def _read_loop(self) -> None:
        while not self._stopped.is_set():
            client = self._client
            if client is None:
                return
            try:
                event = client.event_input(prefer_bytes=True, timeout=self._poll_timeout)
            except ALSAError as error:
                log.warning("sequencer: input failed (%s)", error)
                self._stopped.wait(self._poll_timeout)
                continue
            if event is not None:
                try:
                    self.handle_event(event)
                except Exception:
                    log.exception("sequencer: event handling failed")

    def _deliver(self, event: MidiBytesEvent) -> None:
        message = decode(bytes(event.midi_bytes))
        if message is None or event.source is None:
            return
        source = Address(event.source)
        with self._lock:
            callbacks = [l.callback for l in self._listeners if l.address == source and not l.cancelled]
        for callback in callbacks:
            self._call(callback, message)

    def _refresh(self) -> None:
        with self._lock:   # compared with what was announced, not the snapshot: list() rescans it any time
            before = self._announced
            self._snapshot = self._scan()
            after = self._announced = {p.name for p in self._snapshot.ports}
            self._outgoing &= {p.address for p in self._snapshot.ports}   # the kernel dropped the others
            for listener in self._listeners:
                self._attach(listener, self._resolve(listener.pattern, sending=False))
            changed = []
            for role in UnitPortRole:
                holder = self._holder_now(role)
                if holder != self._holders.get(role):
                    self._holders[role] = holder
                    changed.append((role, holder))
        for name in sorted(before - after):
            for callback in list(self._presence_subscribers):
                self._call(callback, name, False)
        for name in sorted(after - before):
            for callback in list(self._presence_subscribers):
                self._call(callback, name, True)
        for role, holder in changed:
            for callback in list(self._holder_subscribers):
                self._call(callback, role, holder)

    def _call(self, callback, *args) -> None:
        try:
            self._dispatch(callback, *args)
        except Exception:
            log.exception("sequencer: callback failed")

    # --- internals (under the lock) ------------------------------------------------------------------------------
    def _is_apc64(self, client_name: str, port_name: str) -> bool:
        return self._stem in (client_name or "").casefold() or self._stem in (port_name or "").casefold()

    def _scan(self) -> _Snapshot:
        snapshot = _Snapshot()
        try:
            infos = self._client.list_ports(include_system=False, only_connectable=True, sort=False)
        except Exception as error:
            log.warning("sequencer: port listing failed (%s)", error)
            return self._snapshot
        for info in infos:
            if info.client_id == self._client.client_id:
                continue
            address = Address(info.client_id, info.port_id)
            if self._is_apc64(info.client_name, info.name):
                role = self._role_of(info)
                if role is not None:
                    snapshot.apc64.setdefault(role, address)
                continue
            caps = info.capability
            snapshot.ports.append(_Port(
                info.name, address,
                can_send=bool(caps & PortCaps.WRITE and caps & PortCaps.SUBS_WRITE),
                can_listen=bool(caps & PortCaps.READ and caps & PortCaps.SUBS_READ)))
        return snapshot

    @staticmethod
    def _role_of(info) -> UnitPortRole | None:
        for word in (info.name or "").casefold().split():
            if word in _ROLE_WORDS:
                return _ROLE_WORDS[word]
        if "midi" in (info.name or "").casefold().split():
            return None
        return _ROLE_BY_CABLE.get(info.port_id)

    def _resolve(self, pattern: str, sending: bool) -> Address | None:
        try:
            wanted = PortPattern(pattern)
        except Exception:
            return None
        if wanted.names_apc64() or self._stem in wanted.casefold():
            return None
        usable = [p for p in self._snapshot.ports if (p.can_send if sending else p.can_listen)]
        exact = [p for p in usable if p.name.casefold() == wanted.casefold()]
        matches = exact or [p for p in usable if wanted.matches(p.name)]
        names = {p.name for p in matches}
        if len(names) != 1:
            return None
        return matches[0].address

    def _connect_output(self, address: Address) -> None:
        if address in self._outgoing:
            return
        try:
            self._client.subscribe_port(Address(self._out.client_id, self._out.port_id), address)
        except ALSAError as error:
            if -error.errnum != errno.EBUSY:   # EBUSY: already connected (by aconnect, say)
                raise
        self._outgoing.add(address)

    def _attach(self, listener: _Listener, address: Address | None) -> None:
        if listener.address == address:
            return
        old, listener.address = listener.address, None
        if old is not None:
            self._connected[old] -= 1
            if self._connected[old] == 0:
                del self._connected[old]
                try:
                    self._client.unsubscribe_port(old, self._in)
                except Exception:   # the port is gone, and its connection with it
                    pass
        if address is None or listener.cancelled:
            return
        if address in self._snapshot.apc64.values():   # a14: never, whatever the name resolved to
            return
        if address not in self._connected:
            try:
                self._client.subscribe_port(address, self._in)
            except Exception as error:
                log.warning("sequencer: cannot listen to %s (%s)", listener.pattern, error)
                return
            self._connected[address] = 0
        self._connected[address] += 1
        listener.address = address

    def _holder_now(self, role: UnitPortRole) -> Holder | None:
        address = self._snapshot.apc64.get(role)
        if address is None:
            return None
        try:
            subscribers = self._client.list_port_subscribers(address)
        except Exception:
            return None
        clients = sorted({s.addr.client_id for s in subscribers
                          if s.addr.client_id not in (self._client.client_id, address.client_id)})
        for client_id in clients:
            try:
                return Holder(self._client.get_client_info(client_id).name)
            except Exception:
                continue
        return None

    def _drop_output(self) -> None:
        try:
            self._client.drop_output()
        except Exception:
            pass
